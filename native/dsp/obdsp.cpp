// The audio maths the app runs on every block, as plain C functions for ctypes
// (soundboard/audio/nativedsp.py). The Python versions stay: they run when this DLL
// isn't there, and the tests hold the two to the same output.
//
// Rules, because a bug here takes the whole app down and the audio thread calls it:
// - no allocation, no locks, no exceptions, no state of its own: every state lives in
//   memory the caller owns (numpy arrays), so Python's garbage collector frees it and
//   there is no handle to leak or use after it's freed;
// - every size is checked first: a bad call returns a negative number and touches nothing;
// - float32 sums happen in the same order as the numpy they replace, in plain SSE2
//   (-ffp-contract=off, no fast-math), so the output matches to rounding.
#include <math.h>
#include <stdint.h>
#include <string.h>
#if defined(__x86_64__) || defined(_M_X64)
#include <xmmintrin.h>
#endif

#ifdef _WIN32
#define OB_API extern "C" __declspec(dllexport)
#else
#define OB_API extern "C" __attribute__((visibility("default")))
#endif

#define OB_ABI 5
enum { OB_OK = 0, OB_BAD_ARGS = -1, OB_BAD_STATE = -2 };

typedef int64_t i64;
static const i64 MAX_LEN = (i64)1 << 40;   // far past any real signal; guards the products

namespace {

// Very quiet tails turn into denormal floats, which cost a hundred times as much per
// operation: flushed to zero for the length of a call, and put back after it.
struct Denormals {
#if defined(__x86_64__) || defined(_M_X64)
    unsigned old;
    Denormals() : old(_mm_getcsr()) { _mm_setcsr(old | 0x8040); }
    ~Denormals() { _mm_setcsr(old); }
#else
    Denormals() {}
#endif
};

const int CHUNK = 256;

// One biquad over a block of doubles, transposed direct form II (scipy's zi layout).
inline void biquad(const double *c, double *v, int n, double *z) {
    const double b0 = c[0], b1 = c[1], b2 = c[2], a1 = c[3], a2 = c[4];
    double z1 = z[0], z2 = z[1];
    for (int i = 0; i < n; i++) {
        const double x = v[i], y = b0 * x + z1;
        z1 = b1 * x - a1 * y + z2;
        z2 = b2 * x - a2 * y;
        v[i] = y;
    }
    z[0] = z1;
    z[1] = z2;
}

template <class T>
void sos_rows(const double *c, int sections, const T *x, T *y, i64 n, double *z) {
    double v[CHUNK];
    for (i64 i = 0; i < n;) {
        const int k = n - i < CHUNK ? (int)(n - i) : CHUNK;
        for (int j = 0; j < k; j++) v[j] = (double)x[i + j];
        for (int s = 0; s < sections; s++) biquad(c + 5 * s, v, k, z + 2 * s);
        for (int j = 0; j < k; j++) y[i + j] = (T)v[j];
        i += k;
    }
}

template <class T>
void tf_row(const double *b, const double *a, int order, const T *x, T *y, i64 n, double *z) {
    if (order == 1) {   // the usual one: a one-pole, in registers
        const double b0 = b[0], b1 = b[1], a1 = a[0];
        double z1 = z[0];
        for (i64 i = 0; i < n; i++) {
            const double in = (double)x[i], o = b0 * in + z1;
            z1 = b1 * in - a1 * o;
            y[i] = (T)o;
        }
        z[0] = z1;
        return;
    }
    for (i64 i = 0; i < n; i++) {
        const double in = (double)x[i], o = b[0] * in + (order ? z[0] : 0.0);
        for (int k = 0; k + 1 < order; k++) z[k] = b[k + 1] * in - a[k] * o + z[k + 1];
        if (order) z[order - 1] = b[order] * in - a[order - 1] * o;
        y[i] = (T)o;
    }
}

// Many cascades at once (a filter bank, or one filter over many channels): each sample
// goes through all of them side by side, in as many at a time as the CPU's vectors hold.
// The values are the same as one at a time: only the order of unrelated sums changes.
const int LANES_MAX = 64, LANE_SECTIONS_MAX = 8;

template <class T>
__attribute__((always_inline)) inline void lanes_body(const double *coef, int filters, int sections,
                                                      const T *x, T *y, i64 rows, i64 n,
                                                      double *state) {
    const int L = filters * (int)rows;
    alignas(64) double c[LANE_SECTIONS_MAX][5][LANES_MAX];
    alignas(64) double z[LANE_SECTIONS_MAX][2][LANES_MAX];
    alignas(64) double v[LANES_MAX];
    for (int f = 0; f < filters; f++)
        for (int r = 0; r < (int)rows; r++) {
            const int l = f * (int)rows + r;
            for (int s = 0; s < sections; s++) {
                for (int k = 0; k < 5; k++) c[s][k][l] = coef[(f * sections + s) * 5 + k];
                z[s][0][l] = state[(l * 2 * sections) + 2 * s];
                z[s][1][l] = state[(l * 2 * sections) + 2 * s + 1];
            }
        }
    for (i64 i = 0; i < n; i++) {
        for (int f = 0; f < filters; f++)
            for (int r = 0; r < (int)rows; r++) v[f * (int)rows + r] = (double)x[r * n + i];
        for (int s = 0; s < sections; s++) {
            const double *b0 = c[s][0], *b1 = c[s][1], *b2 = c[s][2], *a1 = c[s][3],
                         *a2 = c[s][4];
            double *z1 = z[s][0], *z2 = z[s][1];
#pragma omp simd
            for (int l = 0; l < L; l++) {
                const double in = v[l], o = b0[l] * in + z1[l];
                z1[l] = b1[l] * in - a1[l] * o + z2[l];
                z2[l] = b2[l] * in - a2[l] * o;
                v[l] = o;
            }
        }
        for (int l = 0; l < L; l++) y[l * n + i] = (T)v[l];
    }
    for (int l = 0; l < L; l++)
        for (int s = 0; s < sections; s++) {
            state[(l * 2 * sections) + 2 * s] = z[s][0][l];
            state[(l * 2 * sections) + 2 * s + 1] = z[s][1][l];
        }
}

template <class T>
void lanes_plain(const double *coef, int filters, int sections, const T *x, T *y, i64 rows, i64 n,
                 double *state) {
    lanes_body(coef, filters, sections, x, y, rows, n, state);
}

#if defined(__x86_64__)
#define OB_HAS_AVX2 1
__attribute__((target("avx2"))) void lanes_avx2_f(const double *coef, int filters, int sections,
                                                  const float *x, float *y, i64 rows, i64 n,
                                                  double *state) {
    lanes_body(coef, filters, sections, x, y, rows, n, state);
}
__attribute__((target("avx2"))) void lanes_avx2_d(const double *coef, int filters, int sections,
                                                  const double *x, double *y, i64 rows, i64 n,
                                                  double *state) {
    lanes_body(coef, filters, sections, x, y, rows, n, state);
}
inline bool has_avx2() {
    static const int yes = (__builtin_cpu_init(), __builtin_cpu_supports("avx2") ? 1 : 0);
    return yes != 0;
}
inline void lanes(const double *c, int f, int s, const float *x, float *y, i64 r, i64 n, double *z) {
    if (has_avx2()) lanes_avx2_f(c, f, s, x, y, r, n, z);
    else lanes_plain(c, f, s, x, y, r, n, z);
}
inline void lanes(const double *c, int f, int s, const double *x, double *y, i64 r, i64 n, double *z) {
    if (has_avx2()) lanes_avx2_d(c, f, s, x, y, r, n, z);
    else lanes_plain(c, f, s, x, y, r, n, z);
}
#else
template <class T>
inline void lanes(const double *c, int f, int s, const T *x, T *y, i64 r, i64 n, double *z) {
    lanes_plain(c, f, s, x, y, r, n, z);
}
#endif

// A mono or stereo cascade of up to 4 sections, all of its memory in registers and every
// section taken per sample, so the CPU overlaps one section's sample with the next's (the
// chunked loop above waits on each sample's chain, and the lanes write theirs to memory
// between samples). The same operations per sample and lane as biquad(): the same values.
const int REG_SECTIONS_MAX = 4;

template <int L, int S, class T>
void sos_reg(const double *coef, const T *x, T *y, i64 n, double *state) {
    double c[S][5], z1[S][L], z2[S][L];
    for (int s = 0; s < S; s++) {
        for (int k = 0; k < 5; k++) c[s][k] = coef[s * 5 + k];
        for (int l = 0; l < L; l++) {
            z1[s][l] = state[l * 2 * S + 2 * s];
            z2[s][l] = state[l * 2 * S + 2 * s + 1];
        }
    }
    for (i64 i = 0; i < n; i++) {
        double v[L];
        for (int l = 0; l < L; l++) v[l] = (double)x[l * n + i];
        for (int s = 0; s < S; s++)
            for (int l = 0; l < L; l++) {
                const double in = v[l], o = c[s][0] * in + z1[s][l];
                z1[s][l] = c[s][1] * in - c[s][3] * o + z2[s][l];
                z2[s][l] = c[s][2] * in - c[s][4] * o;
                v[l] = o;
            }
        for (int l = 0; l < L; l++) y[l * n + i] = (T)v[l];
    }
    for (int s = 0; s < S; s++)
        for (int l = 0; l < L; l++) {
            state[l * 2 * S + 2 * s] = z1[s][l];
            state[l * 2 * S + 2 * s + 1] = z2[s][l];
        }
}

template <class T>
bool sos_small(const double *coef, int sections, i64 rows, const T *x, T *y, i64 n,
               double *state) {
#define OB_REG(L, S) \
    if (rows == L && sections == S) { sos_reg<L, S, T>(coef, x, y, n, state); return true; }
    OB_REG(1, 1) OB_REG(1, 2) OB_REG(1, 3) OB_REG(1, 4)
    OB_REG(2, 1) OB_REG(2, 2) OB_REG(2, 3) OB_REG(2, 4)
#undef OB_REG
    return false;
}

}  // namespace

OB_API int ob_abi(void) { return OB_ABI; }

// A bank of biquad cascades over the same rows. coef: (filters, sections, 5) doubles
// (b0 b1 b2 a1 a2, already divided by a0); x: (rows, n); y: (filters, rows, n);
// state: (filters, rows, 2 * sections) doubles, updated in place. `bytes`: 4 or 8.
OB_API int ob_sos(const double *coef, int filters, int sections, const void *x, void *y,
                  int bytes, i64 rows, i64 n, double *state) {
    if (!coef || !x || !y || !state || filters < 1 || sections < 1 || sections > 4096
        || filters > 4096 || (bytes != 4 && bytes != 8) || rows < 0 || n < 0
        || rows > MAX_LEN || n > MAX_LEN || (rows && n > MAX_LEN / rows / filters))
        return OB_BAD_ARGS;
    Denormals d;
    if (filters == 1 && rows <= 2 && sections <= REG_SECTIONS_MAX
        && (bytes == 4 ? sos_small(coef, sections, rows, (const float *)x, (float *)y, n, state)
                       : sos_small(coef, sections, rows, (const double *)x, (double *)y, n,
                                   state)))
        return OB_OK;
    if (filters * rows > 1 && filters * rows <= LANES_MAX && sections <= LANE_SECTIONS_MAX) {
        if (bytes == 4) lanes(coef, filters, sections, (const float *)x, (float *)y, rows, n, state);
        else lanes(coef, filters, sections, (const double *)x, (double *)y, rows, n, state);
        return OB_OK;
    }
    for (int f = 0; f < filters; f++) {
        const double *c = coef + (i64)f * sections * 5;
        for (i64 r = 0; r < rows; r++) {
            double *z = state + ((i64)f * rows + r) * 2 * sections;
            const i64 at = ((i64)f * rows + r) * n;
            if (bytes == 4)
                sos_rows(c, sections, (const float *)x + r * n, (float *)y + at, n, z);
            else
                sos_rows(c, sections, (const double *)x + r * n, (double *)y + at, n, z);
        }
    }
    return OB_OK;
}

// One transfer function. b: order + 1 doubles; a: `order` doubles (a1.., divided by a0);
// x, y: (rows, n); state: (rows, order) doubles, updated in place.
OB_API int ob_tf(const double *b, const double *a, int order, const void *x, void *y,
                 int bytes, i64 rows, i64 n, double *state) {
    if (!b || !x || !y || order < 0 || order > 4096 || (order && (!a || !state))
        || (bytes != 4 && bytes != 8) || rows < 0 || n < 0 || rows > MAX_LEN || n > MAX_LEN
        || (rows && n > MAX_LEN / rows))
        return OB_BAD_ARGS;
    Denormals d;
    for (i64 r = 0; r < rows; r++) {
        double *z = order ? state + r * order : nullptr;
        if (bytes == 4)
            tf_row(b, a, order, (const float *)x + r * n, (float *)y + r * n, n, z);
        else
            tf_row(b, a, order, (const double *)x + r * n, (double *)y + r * n, n, z);
    }
    return OB_OK;
}

// ------------------------------------------------------------------ cubic read
// dsp.hermite read along a signal at a steady step: the sound renderer at a speed, the
// pitch shifter's resampler and the mic ring's stretch. src: (len, ch) floats. Output
// frame k is read at pos = pos0 + step * k (as numpy's pos0 + step * arange), from
// frames i - 1 .. i + 2 where i = floor(pos) + off, at fraction f = float(pos - floor(pos)).
// add: dst[k] += y * g; else dst[k] = y * g. Every frame read must lie inside src.

OB_API int ob_cubic(const float *src, i64 len, int ch, double pos0, double step, i64 off,
                    i64 n, float g, int add, float *dst) {
    if (!src || !dst || ch < 1 || ch > 8 || len < 0 || n < 0 || len > MAX_LEN || n > MAX_LEN
        || !(step >= 0.0) || !(pos0 >= 0.0) || !(pos0 + step * (double)n < (double)MAX_LEN))
        return OB_BAD_ARGS;
    if (!n)
        return OB_OK;
    const i64 first = (i64)pos0 + off - 1;
    const i64 last = (i64)(pos0 + step * (double)(n - 1)) + off + 2;
    if (first < 0 || last >= len)
        return OB_BAD_ARGS;
    Denormals d;
    for (i64 k = 0; k < n; k++) {
        const double pos = pos0 + step * (double)k;
        const i64 ip = (i64)pos;
        const float f = (float)(pos - (double)ip);
        const float hf = 0.5f * f;
        const float *p = src + (ip + off - 1) * ch;
        float *o = dst + k * ch;
        for (int c = 0; c < ch; c++) {
            // the same operations in the same order as dsp.hermite on float32 arrays
            const float p0 = p[c], p1 = p[ch + c], p2 = p[2 * ch + c], p3 = p[3 * ch + c];
            const float in = 3.0f * (p1 - p2) + p3 - p0;
            const float mid = 2.0f * p0 - 5.0f * p1 + 4.0f * p2 - p3 + f * in;
            const float y = p1 + hf * (p2 - p0 + f * mid);
            if (add) o[c] += y * g;
            else o[c] = y * g;
        }
    }
    return OB_OK;
}

// ------------------------------------------------------------------ oversampling
// The two windowed-sinc lowpasses of a waveshaper's oversampling (_Oversampled in
// voicefx/builtin/parts.py). hist: the last taps - 1 samples, oldest first.

namespace {
const int OS_MAX_TAPS = 256, OS_MAX_FACTOR = 16, OS_PART = 256;

// c (<= OS_PART) samples of x up: out gets c * factor. buf: OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR.
inline void os_up_part(const float *h, int taps, int factor, float *hist, const float *x, int c,
                       float *out, float *buf) {
    const int keep = taps - 1, m = c * factor;
    const float gain = (float)factor;
    memcpy(buf, hist, sizeof(float) * keep);
    memset(buf + keep, 0, sizeof(float) * m);
    for (int i = 0; i < c; i++) buf[keep + i * factor] = x[i] * gain;
    // Only every factor-th input isn't zero: output i * factor + ph is the sum over k' of
    // h[ph + factor k'] * u[i - k'], u the inputs that aren't, in k' order. Summed for every
    // i side by side (a chain of dependent adds, one output at a time, was most of the time).
    const int K = (taps + factor - 1) / factor;   // taps of phase 0, the longest
    float u[OS_PART + OS_MAX_TAPS], acc[OS_PART];
    for (int t = 0; t < c + K - 1; t++) u[t] = buf[keep + factor * (t - (K - 1))];
    for (int ph = 0; ph < factor; ph++) {
        for (int i = 0; i < c; i++) acc[i] = 0;
        for (int k = ph, q = 0; k < taps; k += factor, q++) {
            const float hk = h[k], *src = u + (K - 1) - q;
#pragma omp simd
            for (int i = 0; i < c; i++) acc[i] += hk * src[i];
        }
        for (int i = 0; i < c; i++) out[i * factor + ph] = acc[i];
    }
    memcpy(hist, buf + m, sizeof(float) * keep);
}

// c * factor samples of z down: y gets c.
inline void os_down_part(const float *h, int taps, int factor, float *hist, const float *z, int c,
                         float *y, float *buf) {
    const int keep = taps - 1, m = c * factor;
    memcpy(buf, hist, sizeof(float) * keep);
    memcpy(buf + keep, z, sizeof(float) * m);
    if (taps % 4 == 0) {
        // The loop below, summed in the same order (four running sums, tap k going to sum
        // k % 4, then ((s0 + s1) + s2) + s3: how SSE2 vectorizes it) for every output side
        // by side, which is several times faster. w: buf split into its factor phases, so
        // the inputs of consecutive outputs sit next to each other.
        float w[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR], acc[4][OS_PART];
        const int total = keep + m, len = (total + factor - 1) / factor;
        for (int s = 0; s < factor; s++)
            for (int t = 0; s + factor * t < total; t++) w[s * len + t] = buf[s + factor * t];
        for (int r = 0; r < 4; r++) {
            float *a = acc[r];
            for (int i = 0; i < c; i++) a[i] = 0;
            for (int k = r; k < taps; k += 4) {
                const int base = keep - k;   // input of output i: buf[base + factor * i]
                const float hk = h[k], *src = w + (base % factor) * len + base / factor;
#pragma omp simd
                for (int i = 0; i < c; i++) a[i] += hk * src[i];
            }
        }
        for (int i = 0; i < c; i++) y[i] = 0.0f + (((acc[0][i] + acc[1][i]) + acc[2][i]) + acc[3][i]);
        memcpy(hist, buf + m, sizeof(float) * keep);
        return;
    }
    for (int i = 0; i < c; i++) {
        float s = 0;
        const float *p = buf + keep + i * factor;
#pragma omp simd reduction(+ : s)
        for (int k = 0; k < taps; k++) s += h[k] * p[-k];
        y[i] = s;
    }
    memcpy(hist, buf + m, sizeof(float) * keep);
}
}  // namespace

// x (n samples) stuffed with factor - 1 zeros and lowpassed: y gets n * factor samples.
OB_API int ob_os_up(const float *h, int taps, int factor, float *hist, const float *x,
                    i64 n, float *y) {
    if (!h || !hist || !x || !y || taps < 2 || taps > OS_MAX_TAPS || factor < 1
        || factor > OS_MAX_FACTOR || n < 0 || n > MAX_LEN)
        return OB_BAD_ARGS;
    Denormals d;
    float buf[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR];
    for (i64 at = 0; at < n;) {
        const int c = n - at < OS_PART ? (int)(n - at) : OS_PART;
        os_up_part(h, taps, factor, hist, x + at, c, y + at * factor, buf);
        at += c;
    }
    return OB_OK;
}

// z (n * factor samples) lowpassed and kept every factor-th: y gets n samples.
OB_API int ob_os_down(const float *h, int taps, int factor, float *hist, const float *z,
                      i64 n, float *y) {
    if (!h || !hist || !z || !y || taps < 2 || taps > OS_MAX_TAPS || factor < 1
        || factor > OS_MAX_FACTOR || n < 0 || n > MAX_LEN)
        return OB_BAD_ARGS;
    Denormals d;
    float buf[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR];
    for (i64 at = 0; at < n;) {
        const int c = n - at < OS_PART ? (int)(n - at) : OS_PART;
        os_down_part(h, taps, factor, hist, z + at * factor, c, y + at, buf);
        at += c;
    }
    return OB_OK;
}

// ------------------------------------------------------------------ echo
// One stretch of voicefx.builtin.space.Echo, no longer than its delay and with its tone
// filter settled: the delay line is the caller's array, `at` its oldest sample.
OB_API int ob_echo(float *line, i64 d, i64 *at, const float *x, float *y, i64 n, float mix,
                   float fb, const double *sos, int sections, double *z) {
    if (!line || !at || !x || !y || d < 1 || n < 0 || n > d || *at < 0 || *at >= d
        || sections < 0 || sections > 64 || (sections && (!sos || !z)))
        return OB_BAD_ARGS;
    Denormals den;
    i64 p = *at;
    double v[CHUNK];
    for (i64 i = 0; i < n;) {
        const int c = n - i < CHUNK ? (int)(n - i) : CHUNK;
        i64 q = p;
        for (int j = 0; j < c; j++) {
            v[j] = (double)line[q];
            if (++q == d) q = 0;
        }
        for (int s = 0; s < sections; s++) biquad(sos + 5 * s, v, c, z + 2 * s);
        for (int j = 0; j < c; j++) {
            const float del = (float)v[j], in = x[i + j];
            y[i + j] = in + mix * del;
            line[p] = in + fb * del;
            if (++p == d) p = 0;
        }
        i += c;
    }
    *at = p;
    return OB_OK;
}

// ------------------------------------------------------------------ compressor
// voicefx.builtin.tone.Compressor: a gain chasing each chunk's peak, in straight lines.
// g: the gain the last block ended at, updated; boost0 -> boost1: the Boost knob over this
// block; times in seconds.
OB_API int ob_compressor(const float *x, float *y, i64 n, double *g, int chunk, int rate,
                         double threshold, double ratio, double knee, double attack,
                         double release, float boost0, float boost1) {
    if (!x || !y || !g || n < 0 || n > MAX_LEN || chunk < 1 || rate < 1 || !(ratio >= 1.0)
        || !(knee > 0.0) || !(attack > 0.0) || !(release > 0.0))
        return OB_BAD_ARGS;
    Denormals den;
    const double slope = 1.0 - 1.0 / ratio;
    const bool glide = boost0 != boost1;
    const double step = glide ? ((double)boost1 - (double)boost0) / (double)n : 0.0;
    const float w = (float)knee, thr = (float)threshold, sl = (float)slope;
    double was = *g;
    for (i64 at = 0; at < n; at += chunk) {
        const int m = n - at < chunk ? (int)(n - at) : chunk;
        float peak = 0;
        for (int i = 0; i < m; i++) {
            const float a = fabsf(x[at + i]);
            if (a > peak) peak = a;
        }
        const float level = (float)(20.0 * log10((double)(peak + 1e-9f)));
        const float over = level - thr;
        float cut = 0;
        if (over >= w / 2) cut = over * sl;
        else if (over > -w / 2) cut = sl * ((over + w / 2) * (over + w / 2)) / (2 * w);
        const double t = (double)(float)pow(10.0, (double)(-cut / 20));
        const double tau = t < was ? attack : release;
        const double now = t + (was - t) * exp(-(double)m / (rate * tau));
        const double line = (now - was) / m;
        for (int i = 0; i < m; i++) {
            float ramp = (float)(line * (i + 1) + was);
            ramp *= glide ? (float)((double)boost0 + (double)(at + i + 1) * step) : boost1;
            y[at + i] = x[at + i] * ramp;
        }
        was = now;
    }
    *g = was;
    return OB_OK;
}

// ------------------------------------------------------------------ phase-aware mono
// audio/sendfx.py SmartMono. coef: (4, 4, 5) doubles; fstate: (4, 2, 8) doubles; bands:
// (3, 5) doubles (ll rr lr sign gain); x, out: (n, 2) float32; work: 10 * n doubles.
OB_API int ob_smartmono(const double *coef, double *fstate, double *bands, double k,
                        double flip, double unflip, double max_gain, const float *x,
                        float *out, i64 n, double *work) {
    if (!coef || !fstate || !bands || !x || !out || !work || n < 0 || n > MAX_LEN)
        return OB_BAD_ARGS;
    if (n == 0) return OB_OK;
    Denormals den;
    // the four cascades of each channel; the low band is the first two added up
    double *in = work + 8 * n;
    for (i64 i = 0; i < n; i++) {
        in[i] = (double)x[i * 2];
        in[n + i] = (double)x[i * 2 + 1];
    }
    lanes(coef, 4, 4, (const double *)in, work, 2, n, fstate);
    for (i64 i = 0; i < 2 * n; i++) work[i] += work[2 * n + i];
    double *left[3] = {work, work + 4 * n, work + 6 * n};
    double *right[3] = {work + n, work + 5 * n, work + 7 * n};
    double s0[3], s1[3], g0[3], g1[3];
    bool moved = false;
    for (int b = 0; b < 3; b++) {
        double ll = 0, rr = 0, lr = 0;
        const double *l = left[b], *r = right[b];
        for (i64 i = 0; i < n; i++) {
            ll += l[i] * l[i];
            rr += r[i] * r[i];
            lr += l[i] * r[i];
        }
        double *st = bands + b * 5;
        st[0] += (ll / (double)n - st[0]) * k;
        st[1] += (rr / (double)n - st[1]) * k;
        st[2] += (lr / (double)n - st[2]) * k;
        const double tot = st[0] + st[1];
        const double corr = st[0] * st[1] > 1e-18 ? st[2] / sqrt(st[0] * st[1]) : 1.0;
        double sign = st[3];
        if (sign > 0 && corr < flip) sign = -1.0;
        else if (sign < 0 && corr > unflip) sign = 1.0;
        const double m_pow = (tot + 2 * sign * st[2]) / 4;
        double want = 1.0;
        if (m_pow > 1e-18 && tot > 1e-18) want = sqrt((tot / 2) / m_pow);
        double gain = want > 1.0 ? want : 1.0;
        if (gain > max_gain) gain = max_gain;
        s0[b] = st[3];
        s1[b] = sign - st[3];
        g0[b] = st[4];
        g1[b] = gain - st[4];
        if (s1[b] != 0.0 || g1[b] != 0.0) moved = true;
        st[3] = sign;
        st[4] = gain;
    }
    const double step = 1.0 / (double)n;
    for (i64 i = 0; i < n; i++) {
        const double ramp = moved ? (double)i * step + step : 0.0;
        double mono = 0;
        for (int b = 0; b < 3; b++) {
            const double sg = s0[b] + s1[b] * ramp, gg = g0[b] + g1[b] * ramp;
            mono += (left[b][i] + right[b][i] * sg) * (0.5 * gg);
        }
        out[i * 2] = out[i * 2 + 1] = (float)mono;
    }
    return OB_OK;
}

// ------------------------------------------------------------------ synthesis
// A buzz: harmonics 1..count of the phases `ph`, each at its amplitude gliding from old[k]
// to amps[k] over the block. sin(k ph) comes from the two before it, so there's one
// sin and one cos per sample, whatever the number of harmonics.
OB_API int ob_harmonics(const double *ph, i64 n, int count, const double *old,
                        const double *amps, double *wave) {
    if (!ph || !old || !amps || !wave || n < 0 || n > MAX_LEN || count < 0 || count > 100000)
        return OB_BAD_ARGS;
    Denormals den;
    const double step = n ? 1.0 / (double)n : 0.0;
    for (i64 i = 0; i < n; i++) {
        const double ramp = (double)i * step;
        const double s1 = sin(ph[i]), twice_c = 2.0 * cos(ph[i]);
        double prev = 0.0, now = s1, sum = 0.0;
        for (int k = 0; k < count; k++) {
            sum += now * (old[k] + (amps[k] - old[k]) * ramp);
            const double next = twice_c * now - prev;
            prev = now;
            now = next;
        }
        wave[i] = sum;
    }
    return OB_OK;
}

// A gain chasing target[k] over each chunk of lengths[k] samples, from *g.
OB_API int ob_envelope(const double *target, const i64 *lengths, i64 count, double *g, int rate,
                       double attack, double release, double *out) {
    if (!target || !lengths || !g || !out || count < 0 || count > MAX_LEN || rate < 1
        || !(attack > 0.0) || !(release > 0.0))
        return OB_BAD_ARGS;
    double was = *g;
    for (i64 k = 0; k < count; k++) {
        const double t = target[k];
        const double tau = t < was ? attack : release;
        was = t + (was - t) * exp(-(double)lengths[k] / (rate * tau));
        out[k] = was;
    }
    *g = was;
    return OB_OK;
}

// voicefx.builtin.modulation.Flanger: xf, yf: `h` samples of history, then n to do; yf gets
// them. delay: n fractional delays, all at least `least` (>= 1) and short of h - 1.
// fbs: n feedback gains.
OB_API int ob_flanger(const float *xf, float *yf, i64 h, i64 n, const double *delay,
                      const float *fbs) {
    if (!xf || !yf || !delay || !fbs || h < 2 || n < 0 || n > MAX_LEN) return OB_BAD_ARGS;
    Denormals den;
    for (i64 i = 0; i < n; i++) {
        if (!(delay[i] >= 1.0 && delay[i] < (double)(h - 1))) return OB_BAD_ARGS;
        const double pos = (double)(h + i) - delay[i];
        const i64 k = (i64)pos;
        const float f = (float)(pos - (double)k);
        const float xd = xf[k] * (1 - f) + xf[k + 1] * f;
        const float yd = yf[k] * (1 - f) + yf[k + 1] * f;
        yf[h + i] = xd + fbs[i] * yd;
    }
    return OB_OK;
}

// ------------------------------------------------------------------ pitch tracker
// parts._PitchTracker.measure (YIN): the pitch of `len` samples in Hz, 0 for none, negative
// for a bad call. work: 3 * (len / dec + 1) doubles.
OB_API double ob_yin(const float *h, i64 len, int dec, int tmin, int tmax, double sr, double *work) {
    if (!h || !work || dec < 1 || len < dec || len > (i64)1 << 24 || tmin < 1 || !(sr > 0.0))
        return OB_BAD_ARGS;
    const i64 m = len / dec;
    if (m * dec != len || tmax <= tmin + 1 || tmax >= m) return OB_BAD_ARGS;
    double *w = work, *cs = work + m, *cm = work + 2 * m + 1;
    const int size = (int)m - tmax;
    double mean = 0.0;
    for (i64 i = 0; i < m; i++) {
        float sum = 0;
        for (int k = 0; k < dec; k++) sum += h[i * dec + k];
        w[i] = (double)(sum / (float)dec);
        mean += w[i];
    }
    mean /= (double)m;
    double power = 0.0;
    cs[0] = 0.0;
    for (i64 i = 0; i < m; i++) {
        w[i] -= mean;
        power += w[i] * w[i];
        cs[i + 1] = cs[i] + w[i] * w[i];
    }
    if (!(sqrt(power / (double)m) >= 3e-4)) return 0.0;   // quiet, or not a number
    const double e0 = cs[size];
    double total = 0.0;
    cm[0] = 1.0;
    for (int t = 1; t < tmax; t++) {
        double r = 0.0;
#pragma omp simd reduction(+ : r)
        for (int i = 0; i < size; i++) r += w[i] * w[i + t];
        double d = e0 + (cs[size + t] - cs[t]) - 2.0 * r;
        if (d < 0.0) d = 0.0;
        total += d;
        cm[t] = d * (double)t / (total > 1e-12 ? total : 1e-12);
    }
    int t = -1;
    for (int i = tmin; i < tmax; i++)
        if (cm[i] < 0.2) { t = i; break; }
    if (t >= 0) {
        while (t + 1 < tmax && cm[t + 1] < cm[t]) t++;
    } else {
        t = tmin;
        for (int i = tmin; i < tmax; i++)
            if (cm[i] < cm[t]) t = i;
        if (cm[t] > 0.35) return 0.0;
    }
    double tt = (double)t;
    if (t > 0 && t < tmax - 1) {
        const double a = cm[t - 1], b = cm[t], c = cm[t + 1];
        const double den = a - 2 * b + c;
        if (fabs(den) > 1e-12) tt += 0.5 * (a - c) / den;
    }
    return sr / tt;
}

// ------------------------------------------------------------------ reverb
// voicefx.builtin.space.Reverb: pre-delay, early reflections, eight damped combs into
// four allpasses, a high-pass. Its whole state is one caller-owned block of memory, with
// offsets rather than pointers, so a copy of the block is a working copy.

namespace {

const int COMBS = 8, APS = 4, EARLY = 12;
const uint32_t MAGIC = 0x4f425256;
const int COMB_D[COMBS] = {1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617};
const int AP_D[APS] = {556, 441, 341, 225};
const double EARLY_S[EARLY] = {0.0043, 0.0215, 0.0225, 0.0268, 0.0270, 0.0298,
                               0.0458, 0.0485, 0.0572, 0.0587, 0.0595, 0.0612};
const float EARLY_G[EARLY] = {0.84f, 0.5f, -0.4f, 0.38f, -0.33f, 0.32f,
                              0.28f, -0.25f, 0.22f, -0.2f, 0.18f, 0.17f};
const double PRE_MAX_S = 0.1;
const float EARLY_LEVEL = 0.35f;

struct Reverb {
    uint32_t magic;
    int32_t rate, keep, hist_at, pre, most;
    int32_t comb_len[COMBS], comb_at[COMBS], ap_len[APS], ap_at[APS], early_d[EARLY];
    int32_t comb_off[COMBS], ap_off[APS], hist_off, total;   // in floats, from data()
    double damp[COMBS];
    double hp[5];
    float hp_z[2];
    double align_end;
    float *data() { return reinterpret_cast<float *>(this + 1); }
};

// The rate's delays, cut to whole samples as Python's int() does.
bool lengths(int rate, Reverb *r, i64 *bytes) {
    if (rate < 2000 || rate > 768000) return false;
    const double k = rate / 44100.0;
    i64 at = 0;
    for (int i = 0; i < COMBS; i++) {
        const int d = (int)(COMB_D[i] * k);
        if (r) { r->comb_len[i] = d; r->comb_off[i] = (int32_t)at; }
        at += d;
    }
    for (int i = 0; i < APS; i++) {
        const int d = (int)(AP_D[i] * k);
        if (r) { r->ap_len[i] = d; r->ap_off[i] = (int32_t)at; }
        at += 2 * d;
    }
    int most = 0;
    for (int i = 0; i < EARLY; i++) {
        const int d = (int)(EARLY_S[i] * rate);
        if (r) r->early_d[i] = d;
        if (d > most) most = d;
    }
    const int keep = (int)(PRE_MAX_S * rate) + most + 1;
    if (r) {
        r->keep = keep;
        r->most = most;
        r->hist_off = (int32_t)at;
        r->total = (int32_t)(at + keep);
    }
    at += keep;
    *bytes = (i64)sizeof(Reverb) + at * (i64)sizeof(float);
    return true;
}

Reverb *reverb_of(void *state, i64 bytes) {
    if (!state || bytes < (i64)sizeof(Reverb)) return nullptr;
    Reverb *r = static_cast<Reverb *>(state);
    if (r->magic != MAGIC || r->total <= 0
        || bytes != (i64)sizeof(Reverb) + (i64)r->total * (i64)sizeof(float))
        return nullptr;
    return r;
}

// `n` samples of the dry signal from logical place `p` of (history, then x).
inline void read_taps(const float *hist, int keep, int oldest, const float *x, int p, int n,
                      float *out) {
    while (n > 0 && p < keep) {
        int at = oldest + p;
        if (at >= keep) at -= keep;
        int c = keep - at;
        if (c > keep - p) c = keep - p;
        if (c > n) c = n;
        memcpy(out, hist + at, sizeof(float) * c);
        out += c;
        p += c;
        n -= c;
    }
    if (n > 0) memcpy(out, x + (p - keep), sizeof(float) * n);
}

inline void room(const Reverb *r, const float *hist, const float *x, int n, int d0,
                 float *dry, float *early) {
    read_taps(hist, r->keep, r->hist_at, x, r->keep - d0, n, dry);
    float t[CHUNK];
    for (int i = 0; i < n; i++) early[i] = 0;
    for (int e = 0; e < EARLY; e++) {
        read_taps(hist, r->keep, r->hist_at, x, r->keep - d0 - r->early_d[e], n, t);
        const float g = EARLY_G[e];
        for (int i = 0; i < n; i++) early[i] += g * t[i];
    }
}

}  // namespace

OB_API i64 ob_reverb_bytes(int rate) {
    i64 bytes = 0;
    if (!lengths(rate, nullptr, &bytes)) return OB_BAD_ARGS;
    return bytes;
}

// state: ob_reverb_bytes(rate) bytes, 8-byte aligned. hp: the high-pass as b0 b1 b2 a1 a2
// (divided by a0).
OB_API int ob_reverb_init(void *state, i64 bytes, int rate, int pre, const double *hp) {
    i64 need = 0;
    if (!state || !hp || !lengths(rate, nullptr, &need) || bytes != need || pre < 0
        || ((uintptr_t)state & 7))
        return OB_BAD_ARGS;
    memset(state, 0, (size_t)bytes);
    Reverb *r = static_cast<Reverb *>(state);
    lengths(rate, r, &need);
    if (pre + r->most >= r->keep) {
        memset(state, 0, (size_t)bytes);
        return OB_BAD_ARGS;
    }
    r->rate = rate;
    r->pre = pre;
    memcpy(r->hp, hp, sizeof r->hp);
    r->magic = MAGIC;
    return OB_OK;
}

// One block. g, a: the combs' feedback and damping; pre: the pre-delay in samples (a new
// one glides over this block); mix: the Mix knob; combs, aps: how many of them run.
OB_API int ob_reverb_run(void *state, i64 bytes, const float *x, float *y, i64 n, double g,
                         double a, int pre, float mix, int combs, int aps) {
    Reverb *r = reverb_of(state, bytes);
    if (!r) return OB_BAD_STATE;
    if (!x || !y || n < 0 || n > MAX_LEN || pre < 0 || combs < 1 || combs > COMBS || aps < 0
        || aps > APS || !(g >= 0.0 && g <= 1.0) || !(a >= 0.0 && a <= 1.0))
        return OB_BAD_ARGS;
    // the farthest tap has to stay inside the history
    if (pre + r->most >= r->keep || r->pre + r->most >= r->keep) return OB_BAD_ARGS;
    if (n == 0) return OB_OK;
    Denormals den;
    float *data = r->data();
    float *hist = data + r->hist_off;
    const int old = r->pre;
    const float gf = (float)g;
    const double b0 = 1.0 - a;
    const float scale = (float)(0.25 * sqrt(1 - g * g) * sqrt((double)COMBS / combs));
    const float dry_gain = 1.0f - 0.6f * mix, wet_gain = mix * 0.8f;
    const double step = 1.0 / (double)n;
    double hz[2] = {r->hp_z[0], r->hp_z[1]};

    float dry[CHUNK], early[CHUNK], wet[CHUNK], dry0[CHUNK], early0[CHUNK];
    double v[CHUNK];
    for (i64 at = 0; at < n;) {
        const int c = n - at < CHUNK ? (int)(n - at) : CHUNK;
        const float *in = x + at;
        room(r, hist, in, c, pre, dry, early);
        if (old != pre) {   // the knob moved: glide from the old taps to the new
            room(r, hist, in, c, old, dry0, early0);
            for (int i = 0; i < c; i++) {
                const float ramp = (float)((double)(at + i) * step);
                dry[i] = dry0[i] + (dry[i] - dry0[i]) * ramp;
                early[i] = early0[i] + (early[i] - early0[i]) * ramp;
            }
        }
        for (int i = 0; i < c; i++) wet[i] = 0;
        for (int k = 0; k < combs; k++) {
            float *line = data + r->comb_off[k];
            const int d = r->comb_len[k];
            int p = r->comb_at[k];
            double z = r->damp[k];
            for (int i = 0; i < c; i++) {
                const double fed = b0 * (double)line[p] + z;
                z = a * fed;
                const float o = dry[i] + gf * (float)fed;
                line[p] = o;
                if (++p == d) p = 0;
                wet[i] += o;
            }
            r->comb_at[k] = p;
            r->damp[k] = z;
        }
        for (int i = 0; i < c; i++) wet[i] *= scale;
        for (int k = 0; k < aps; k++) {
            float *xh = data + r->ap_off[k];
            const int d = r->ap_len[k];
            float *yh = xh + d;
            int p = r->ap_at[k];
            for (int i = 0; i < c; i++) {
                const float s = wet[i];
                const float o = -0.5f * s + xh[p] + 0.5f * yh[p];
                xh[p] = s;
                yh[p] = o;
                if (++p == d) p = 0;
                wet[i] = o;
            }
            r->ap_at[k] = p;
        }
        for (int i = 0; i < c; i++) v[i] = (double)(wet[i] + early[i] * EARLY_LEVEL);
        biquad(r->hp, v, c, hz);
        for (int i = 0; i < c; i++) y[at + i] = in[i] * dry_gain + (float)v[i] * wet_gain;
        // the dry signal moves into the history, oldest out
        for (int left = c, from = 0; left > 0;) {
            int k = r->keep - r->hist_at;
            if (k > left) k = left;
            memcpy(hist + r->hist_at, in + from, sizeof(float) * k);
            r->hist_at += k;
            if (r->hist_at == r->keep) r->hist_at = 0;
            from += k;
            left -= k;
        }
        at += c;
    }
    r->hp_z[0] = (float)hz[0];
    r->hp_z[1] = (float)hz[1];
    r->pre = pre;
    return OB_OK;
}

// Every sample of its memory is within +-floor: 1 yes, 0 no, negative: a bad call.
OB_API int ob_reverb_rung_out(void *state, i64 bytes, float floor) {
    Reverb *r = reverb_of(state, bytes);
    if (!r) return OB_BAD_STATE;
    const float *d = r->data();
    for (int i = 0; i < r->total; i++)
        if (!(d[i] <= floor && d[i] >= -floor)) return 0;
    for (int k = 0; k < COMBS; k++)
        if (!(r->damp[k] <= (double)floor && r->damp[k] >= -(double)floor)) return 0;
    for (int k = 0; k < 2; k++)
        if (!(r->hp_z[k] <= floor && r->hp_z[k] >= -floor)) return 0;
    return 1;
}

// The lines past the first `combs` and `aps` go silent (they sat out Use less CPU).
OB_API int ob_reverb_clear(void *state, i64 bytes, int combs, int aps) {
    Reverb *r = reverb_of(state, bytes);
    if (!r) return OB_BAD_STATE;
    if (combs < 0 || combs > COMBS || aps < 0 || aps > APS) return OB_BAD_ARGS;
    float *d = r->data();
    for (int k = combs; k < COMBS; k++) {
        memset(d + r->comb_off[k], 0, sizeof(float) * r->comb_len[k]);
        r->damp[k] = 0;
    }
    for (int k = aps; k < APS; k++)
        memset(d + r->ap_off[k], 0, sizeof(float) * 2 * r->ap_len[k]);
    return OB_OK;
}

// ------------------------------------------------------------------ Clean mic's gate
// voicefx.cleanmic.Tidy._gate in two calls, numpy's log10 between them (it isn't the same
// on every CPU, so it stays numpy's): every number below comes out as the Python one does.
namespace {

// numpy's float32 add.reduce (pairwise, 8 at a time up to 128) of the squares.
float pairwise_squares(const float *a, i64 n) {
    if (n < 8) {
        float res = 0.0f;
        for (i64 i = 0; i < n; i++) res += a[i] * a[i];
        return res;
    }
    if (n <= 128) {
        float r[8];
        for (int j = 0; j < 8; j++) r[j] = a[j] * a[j];
        i64 i = 8;
        for (; i < n - (n % 8); i += 8)
            for (int j = 0; j < 8; j++) r[j] += a[i + j] * a[i + j];
        float res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; i++) res += a[i] * a[i];
        return res;
    }
    i64 n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_squares(a, n2) + pairwise_squares(a + n2, n - n2);
}

bool good_edges(const i64 *edges, i64 pieces, i64 n) {
    if (edges[0] != 0 || edges[pieces] != n) return false;
    for (i64 i = 0; i < pieces; i++)
        if (edges[i + 1] <= edges[i]) return false;
    return true;
}

}  // namespace

// lv[i] = sqrt(mean(x[edges[i]:edges[i+1]] ** 2) + 1e-12), in float32 like numpy.
OB_API int ob_tidy_levels(const float *x, i64 n, const i64 *edges, i64 pieces, float *lv) {
    if (!x || !edges || !lv || n < 1 || n > MAX_LEN || pieces < 1 || pieces > n
        || !good_edges(edges, pieces, n))
        return OB_BAD_ARGS;
    for (i64 i = 0; i < pieces; i++) {
        const i64 len = edges[i + 1] - edges[i];
        const float mean = (float)((double)pairwise_squares(x + edges[i], len) / (double)len);
        lv[i] = sqrtf(mean + 1e-12f);
    }
    return OB_OK;
}

// The rest of Tidy._gate. db: each piece's level in dB; decay: per piece, its closing-in
// factor towards a louder target, then towards a quieter one. hist: `cap` (seconds, quietest
// dB) pairs, *count of them in use (the last 1.5 s of blocks). st: g, open, held, peak_db,
// floor_db, open_db. sense: Input sensitivity in dB, NaN for automatic.
OB_API int ob_tidy_gate(const float *x, float *y, i64 n, const i64 *edges, i64 pieces,
                        const float *db, const double *decay, double *hist, i64 cap, i64 *count,
                        double *st, double sense, int gate) {
    if (!x || !y || !edges || !db || !decay || !hist || !count || !st || n < 1 || n > MAX_LEN
        || pieces < 1 || pieces > n || cap < 1 || cap > MAX_LEN || *count < 0
        || *count >= cap || !good_edges(edges, pieces, n))
        return OB_BAD_ARGS;
    const double rate = 48000.0, hold_s = 0.2, floor_s = 1.5, closed = 0.12589254117941673;
    // max(db), min(db) as Python's max() and min() pick them
    double peak = (double)db[0], low = (double)db[0];
    for (i64 i = 1; i < pieces; i++) {
        const double d = (double)db[i];
        if (d > peak) peak = d;
        if (d < low) low = d;
    }
    i64 c = *count;
    hist[2 * c] = (double)n / rate;
    hist[2 * c + 1] = -90.0 > low ? -90.0 : low;
    c++;
    // span = sum(t): Python's sum() (Neumaier's compensated sum)
    double span = hist[0], comp = 0.0;
    for (i64 i = 1; i < c; i++) {
        const double v = hist[2 * i], t = span + v;
        if (fabs(span) >= fabs(v)) comp += (span - t) + v;
        else comp += (v - t) + span;
        span = t;
    }
    if (comp != 0.0 && isfinite(comp)) span += comp;
    i64 drop = 0;
    while (c - drop > 1 && span - hist[2 * drop] >= floor_s) {
        span -= hist[2 * drop];
        drop++;
    }
    if (drop) {
        memmove(hist, hist + 2 * drop, sizeof(double) * 2 * (size_t)(c - drop));
        c -= drop;
    }
    *count = c;
    double fl = hist[1];
    for (i64 i = 1; i < c; i++)
        if (hist[2 * i + 1] < fl) fl = hist[2 * i + 1];
    if (-38.0 < fl) fl = -38.0;
    double open_at, close_at;
    if (sense != sense) {
        open_at = fl + 9 > -60.0 ? fl + 9 : -60.0;
        close_at = fl + 5 > -64.0 ? fl + 5 : -64.0;
    } else {
        open_at = sense;
        close_at = sense - 4;
    }
    double g = st[0], held = st[2];
    bool open = st[1] != 0.0;
    for (i64 i = 0; i < pieces; i++) {
        const double d = (double)db[i];
        const double piece = (double)(edges[i + 1] - edges[i]) / rate;
        if (d > open_at) {
            open = true;
            held = 0.0;
        } else if (open && d < close_at) {
            held += piece;
            if (held > hold_s) open = false;
        }
        const double target = open || !gate ? 1.0 : closed;
        const double was = g;
        g = target + (g - target) * decay[2 * i + (target > g ? 0 : 1)];
        // np.interp between the knots edges[i] - 1 and edges[i + 1] - 1
        const double k0 = (double)(edges[i] - 1), k1 = (double)(edges[i + 1] - 1);
        const double slope = (g - was) / (k1 - k0);
        for (i64 j = edges[i] ? edges[i] - 1 : 0; j < edges[i + 1] - 1; j++) {
            const double at = (double)j;
            const double v = at == k0 ? was : slope * (at - k0) + was;
            y[j] = (float)((double)x[j] * v);
        }
    }
    y[n - 1] = (float)((double)x[n - 1] * g);
    st[0] = g;
    st[1] = open ? 1.0 : 0.0;
    st[2] = held;
    st[3] = peak;
    st[4] = fl;
    st[5] = open_at;
    return OB_OK;
}

// ------------------------------------------------------------------ Bit crusher
// voicefx.builtin.retro.BitCrush.run. inc: the hold's phase step, or incs (n of them, each
// on the 1/2^20 grid) while it glides; step or steps: the rounding step; mix or mixes.
// *phase and *held carry over from block to block.
OB_API int ob_bitcrush(const float *x, float *y, i64 n, double *phase, float *held, double inc,
                       const double *incs, float step, const float *steps, float mix,
                       const float *mixes) {
    if (!x || !y || !phase || !held || n < 0 || n > MAX_LEN || !(*phase >= 0.0)
        || !(*phase < 1e6))
        return OB_BAD_ARGS;
    if (incs) {
        for (i64 i = 0; i < n; i++)
            if (!(incs[i] >= 0.0 && incs[i] <= 1.0)) return OB_BAD_ARGS;
    } else if (!(inc >= 0.0 && inc <= 1.0)) {
        return OB_BAD_ARGS;
    }
    if (!n) return OB_OK;
    const double p0 = *phase;
    double kprev = floor(p0), sum = 0.0, ph = p0, k = kprev;
    i64 idx = -1;
    float last = *held;
    for (i64 i = 0; i < n; i++) {
        if (incs) {
            sum += incs[i];
            ph = p0 + sum;
        } else {
            ph = p0 + inc * (double)(i + 1);
        }
        k = floor(ph);
        if (k - kprev > 0) idx = i;
        kprev = k;
        last = idx >= 0 ? x[idx] : *held;
        const float q = steps ? steps[i] : step;
        const float v = rintf(last / q) * q;
        const float m = mixes ? mixes[i] : mix;
        y[i] = x[i] * (1 - m) + v * m;
    }
    *held = last;
    *phase = ph - k;
    return OB_OK;
}

// ------------------------------------------------------------------ Chorus, Wobble
// Both read the voice off a swaying delay: hist (h samples, updated in place) then x.
namespace {

inline float tap(const float *hist, i64 h, const float *x, i64 k) {
    return k < h ? hist[k] : x[k - h];
}

void keep_last(float *hist, i64 h, const float *x, i64 n) {
    if (n >= h) {
        memcpy(hist, x + (n - h), sizeof(float) * (size_t)h);
    } else {
        memmove(hist, hist + n, sizeof(float) * (size_t)(h - n));
        memcpy(hist + (h - n), x, sizeof(float) * (size_t)n);
    }
}

// every delay in 0..most, so every read stays inside hist and x
bool good_depths(double depth, const double *depths, i64 n, double most) {
    if (!depths) return depth >= 0.0 && depth <= most;
    for (i64 i = 0; i < n; i++)
        if (!(depths[i] >= 0.0 && depths[i] <= most)) return false;
    return true;
}

const double TWO_PI = 6.283185307179586, HALF_PI = 1.5707963267948966;

}  // namespace

// voicefx.builtin.modulation.Chorus.run: w = 2 pi rate / sample rate, c = 1 ms in samples,
// depth or depths (gliding), mix.
OB_API int ob_chorus(float *hist, i64 h, const float *x, float *y, i64 n, double *phase,
                     double w, double depth, const double *depths, double c, float mix) {
    if (!hist || !x || !y || !phase || h < 2 || h > MAX_LEN || n < 0 || n > MAX_LEN
        || !isfinite(*phase) || !(fabs(*phase) < 1e9) || !(fabs(w) < 1e3) || !(c >= 0.0)
        || !(c <= (double)(h - 1)) || !good_depths(depth, depths, n, (double)(h - 1) - c))
        return OB_BAD_ARGS;
    if (!n) return OB_OK;
    const double p0 = *phase;
    const float keep = 1 - mix, half = mix * 0.5f;
    for (i64 i = 0; i < n; i++) {
        const double ph = p0 + w * (double)(i + 1);
        const double d = depths ? depths[i] : depth;
        const double base = ((double)(h - 1) + (double)i) - c;
        double wet = 0.0;
        for (int v = 0; v < 2; v++) {
            const double pos = base - d * (1 + sin(v ? ph + HALF_PI : ph)) * 0.5;
            const i64 k = (i64)pos;
            const double f = pos - (double)k;
            wet += (double)tap(hist, h, x, k) * (1 - f) + (double)tap(hist, h, x, k + 1) * f;
        }
        y[i] = x[i] * keep + (float)wet * half;
    }
    *phase = fmod(p0 + w * (double)n, TWO_PI);
    keep_last(hist, h, x, n);
    return OB_OK;
}

// voicefx.builtin.modulation.Wobble.run: the same delay (depth or depths), and the volume
// swaying by trem or trems.
OB_API int ob_wobble(float *hist, i64 h, const float *x, float *y, i64 n, double *phase,
                     double w, double depth, const double *depths, double trem,
                     const double *trems) {
    if (!hist || !x || !y || !phase || h < 2 || h > MAX_LEN || n < 0 || n > MAX_LEN
        || !isfinite(*phase) || !(fabs(*phase) < 1e9) || !(fabs(w) < 1e3)
        || !good_depths(depth, depths, n, (double)(h - 1)))
        return OB_BAD_ARGS;
    if (!trems && !isfinite(trem)) return OB_BAD_ARGS;
    if (!n) return OB_OK;
    const double p0 = *phase;
    for (i64 i = 0; i < n; i++) {
        const double ph = p0 + w * (double)(i + 1);
        const double d = depths ? depths[i] : depth;
        const double pos = ((double)(h - 1) + (double)i) - d * (1 + sin(ph)) * 0.5;
        const i64 k = (i64)pos;
        const double f = pos - (double)k;
        const double v = (double)tap(hist, h, x, k) * (1 - f) + (double)tap(hist, h, x, k + 1) * f;
        const double tr = trems ? trems[i] : trem;
        y[i] = (float)(v * (1 - tr * (1 + sin(ph + HALF_PI)) * 0.5));
    }
    *phase = fmod(p0 + w * (double)n, TWO_PI);
    keep_last(hist, h, x, n);
    return OB_OK;
}

// ------------------------------------------------------------------ voice effects
// Robot (voicefx.builtin.synth), Studio polish (polish.py) and Distortion (tone.py), each
// a whole block in one call. Every float32 step rounds where the numpy it replaces stores
// a float32 array, and every sum runs in numpy's order, so the output is the same to the
// last bit, except where noted: tanh (fast_tanh) and the limiter's moving average.

namespace {

const double TAU = 6.283185307179586476925286766559;   // 2 * np.pi, the same double

// np.minimum / np.maximum: a NaN on either side wins.
inline float nmin(float a, float b) { return a != a ? a : (b != b ? b : (b < a ? b : a)); }
inline float nmax(float a, float b) { return a != a ? a : (b != b ? b : (b > a ? b : a)); }
inline double nmin(double a, double b) { return a != a ? a : (b != b ? b : (b < a ? b : a)); }
inline double nmax(double a, double b) { return a != a ? a : (b != b ? b : (b > a ? b : a)); }

// np.mod(a, 2 pi): the remainder with the divisor's sign.
inline double mod_2pi(double a) {
    double m = fmod(a, TAU);
    if (m != 0.0) {
        if (m < 0.0) m += TAU;
    } else {
        m = 0.0;
    }
    return m;
}

// numpy's float32 pairwise sum (np.add.reduce over a contiguous run).
float pairwise(const float *a, i64 n) {
    if (n < 8) {
        float r = -0.0f;
        for (i64 i = 0; i < n; i++) r += a[i];
        return r;
    }
    if (n <= 128) {
        float r[8];
        for (int j = 0; j < 8; j++) r[j] = a[j];
        i64 i = 8;
        for (; i < n - (n % 8); i += 8)
            for (int j = 0; j < 8; j++) r[j] += a[i + j];
        float res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; i++) res += a[i];
        return res;
    }
    i64 n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise(a, n2) + pairwise(a + n2, n - n2);
}

// np.add.reduceat's sum of one chunk: its first value, then the pairwise sum of the rest.
inline float chunk_sum(const float *a, i64 n) { return a[0] + pairwise(a + 1, n - 1); }

// One step of parts._envelope (ob_envelope): from `was` towards t over m samples.
inline double chase(double was, double t, i64 m, int rate, double attack, double release) {
    const double tau = t < was ? attack : release;
    return t + (was - t) * exp(-(double)m / (rate * tau));
}

// parts._spread over one chunk: sample p (1-based, s < p <= e) of the straight line from
// g0 at s to g1 at e, in np.interp's sums.
inline float spread_at(double g0, double g1, i64 s, i64 e, i64 p) {
    if (p == e) return (float)g1;
    const double slope = (g1 - g0) / (double)(e - s);
    return (float)(slope * ((double)p - (double)s) + g0);
}

// tanh for the waveshapers: a rational fit (|error| < 3.5e-7, about -129 dB, measured
// against the exact tanh over +-12) that vectorizes. numpy's float32 tanh is a SIMD
// polynomial of its own, so the Python version only matches it to rounding.
__attribute__((always_inline)) inline float fast_tanh(float x) {
    const float lim = 7.90531110763549805f;
    float v = x > lim ? lim : x;   // (a NaN goes straight through)
    v = v < -lim ? -lim : v;
    const float v2 = v * v;
    float p = -2.76076847742355e-16f;
    p = p * v2 + 2.00018790482477e-13f;
    p = p * v2 + -8.60467152213735e-11f;
    p = p * v2 + 5.12229709037114e-08f;
    p = p * v2 + 1.48572235717979e-05f;
    p = p * v2 + 6.37261928875436e-04f;
    p = p * v2 + 4.89352455891786e-03f;
    p = v * p;
    float q = 1.19825839466702e-06f;
    q = q * v2 + 1.18534705686654e-04f;
    q = q * v2 + 2.26843463243900e-03f;
    q = q * v2 + 4.89352518554385e-03f;
    const float t = p / q;   // always worked out, so the loop has no branch and vectorizes
    return fabsf(x) < 0.0004f ? x : t;
}

// parts._glide over m samples: sample j of np.linspace(old, new, m + 1, float32)[1:].
struct Glide {
    double old, now, step;
    i64 m;
    bool still;
    float v;
    Glide(double a, double b, i64 m_) : old(a), now(b), step(m_ ? (b - a) / (double)m_ : 0.0),
                                        m(m_), still(a == b), v((float)b) {}
    float at(i64 j) const {
        if (still) return v;
        return j == m - 1 ? (float)now : (float)((double)(j + 1) * step + old);
    }
};

// The bend of ob_shaper over cm upsampled samples from j0. No FP traps here (GCC's
// trapping-math keeps a loop with a compare in it from vectorizing; the values are the same).
__attribute__((optimize("no-trapping-math"))) void shape_part(float *zb, int cm, i64 j0, int kind,
                                                            const Glide &drive,
                                                            const Glide &level, float d0,
                                                            float make) {
    const float r = 0.3f;
    if (kind == 0) {
        if (drive.still && level.still) {
            const float g = drive.v, lv = level.v;
            for (int j = 0; j < cm; j++) zb[j] = fast_tanh(zb[j] * g) * lv;
        } else {
            for (int j = 0; j < cm; j++)
                zb[j] = fast_tanh(zb[j] * drive.at(j0 + j)) * level.at(j0 + j);
        }
    } else if (drive.still) {
        for (int j = 0; j < cm; j++) zb[j] = fast_tanh(zb[j] * d0) * make;
    } else {
        for (int j = 0; j < cm; j++) {
            float d = drive.at(j0 + j);
            d = d < 1e-3f ? 1e-3f : d;
            zb[j] = fast_tanh(zb[j] * d) * (r / fast_tanh(r * d));
        }
    }
}

const int VOC_MAX_BANDS = LANES_MAX / 2;

struct Voc {
    const float *x;
    float *y;
    i64 n;
    const float *table;
    i64 size;
    double *phase;
    double step, scale, nz;
    const double *noise, *bank;
    int bands, sections;
    double *bstate;
    const double *env;
    float *estate;
};

__attribute__((always_inline)) inline void vocoder_body(const Voc &a) {
    const int k = a.bands, L = 2 * k, S = a.sections;
    alignas(64) double c[LANE_SECTIONS_MAX][5][LANES_MAX];
    alignas(64) double z[LANE_SECTIONS_MAX][2][LANES_MAX];
    alignas(64) double v[LANES_MAX], e1[LANES_MAX], e2[LANES_MAX];
    alignas(64) float bo[LANES_MAX], eo[LANES_MAX];
    // the bank's lanes as its state is laid out: band f's voice at 2f, its carrier at 2f + 1
    for (int l = 0; l < L; l++)
        for (int s = 0; s < S; s++) {
            for (int q = 0; q < 5; q++) c[s][q][l] = a.bank[((l / 2) * S + s) * 5 + q];
            z[s][0][l] = a.bstate[l * 2 * S + 2 * s];
            z[s][1][l] = a.bstate[l * 2 * S + 2 * s + 1];
        }
    // the envelopes' rows: every band's voice, then every band's carrier
    for (int r = 0; r < L; r++) {
        e1[r] = (double)a.estate[2 * r];
        e2[r] = (double)a.estate[2 * r + 1];
    }
    const double eb0 = a.env[0], eb1 = a.env[1], eb2 = a.env[2], ea1 = a.env[3], ea2 = a.env[4];
    const double keep = 1.0 - a.nz, ph0 = *a.phase;
    for (i64 i = 0; i < a.n; i++) {
        // the buzz: the table read with linear interpolation, plus the breath noise
        const double pos = mod_2pi(ph0 + a.step * (double)(i + 1)) * a.scale;
        const i64 at = pos < (double)(a.size - 1) ? (i64)pos : a.size - 1;
        const float t0 = a.table[at], dt = a.table[at + 1] - t0;
        const double saw = (double)t0 + (double)dt * (pos - (double)at);
        const float car = (float)(saw * keep + a.noise[i] * a.nz);
        const double xin = (double)a.x[i], cin = (double)car;
        for (int l = 0; l < L; l += 2) {
            v[l] = xin;
            v[l + 1] = cin;
        }
        for (int s = 0; s < S; s++) {
            const double *b0 = c[s][0], *b1 = c[s][1], *b2 = c[s][2], *a1 = c[s][3],
                         *a2 = c[s][4];
            double *z1 = z[s][0], *z2 = z[s][1];
#pragma omp simd
            for (int l = 0; l < L; l++) {
                const double in = v[l], o = b0[l] * in + z1[l];
                z1[l] = b1[l] * in - a1[l] * o + z2[l];
                z2[l] = b2[l] * in - a2[l] * o;
                v[l] = o;
            }
        }
        for (int f = 0; f < k; f++) {
            bo[f] = (float)v[2 * f];
            bo[k + f] = (float)v[2 * f + 1];
        }
#pragma omp simd
        for (int l = 0; l < L; l++) {
            const double in = (double)fabsf(bo[l]), o = eb0 * in + e1[l];
            e1[l] = eb1 * in - ea1 * o + e2[l];
            e2[l] = eb2 * in - ea2 * o;
            eo[l] = (float)o;
        }
        // each band of the buzz at the voice's level in it, added up band by band (numpy's
        // sum(0) does that, except over a one-sample block: there it's its pairwise sum)
        float acc = 0;
        alignas(64) float prod[LANES_MAX];
        for (int f = 0; f < k; f++) {
            const float g = nmin(eo[f] / (eo[k + f] + 2e-3f), 20.0f), p = g * bo[k + f];
            prod[f] = p;
            acc = f ? acc + p : p;
        }
        a.y[i] = a.n == 1 ? pairwise(prod, k) : acc;
    }
    if (a.n) *a.phase = mod_2pi(ph0 + a.step * (double)a.n);
    for (int l = 0; l < L; l++)
        for (int s = 0; s < S; s++) {
            a.bstate[l * 2 * S + 2 * s] = z[s][0][l];
            a.bstate[l * 2 * S + 2 * s + 1] = z[s][1][l];
        }
    for (int r = 0; r < L; r++) {   // stored as float32, as sosfilt hands it back
        a.estate[2 * r] = (float)e1[r];
        a.estate[2 * r + 1] = (float)e2[r];
    }
}

void vocoder_plain(const Voc &a) { vocoder_body(a); }
#ifdef OB_HAS_AVX2
__attribute__((target("avx2"))) void vocoder_avx2(const Voc &a) { vocoder_body(a); }
#endif

const int DEESS_MAX_CHUNK = 4096, LIMIT_MAX_LOOK = 4096;

}  // namespace

// synth.Robot's vocoder over one block (the wet signal, before the mix). table: size + 1
// floats (one cycle of the buzz, its first sample again at the end); *phase: the buzz's
// phase, updated; step: its phase per sample; scale: table samples per radian; noise: n
// doubles of breath (already scaled), nz its share. bank: (bands, sections, 5) doubles;
// bstate: (bands, 2, 2 * sections) doubles; env: one section, 5 doubles; estate: (2 * bands,
// 2) floats. The states are updated in place.
OB_API int ob_vocoder(const float *x, float *y, i64 n, const float *table, i64 size,
                      double *phase, double step, double scale, double nz, const double *noise,
                      const double *bank, int bands, int sections, double *bstate,
                      const double *env, float *estate) {
    if (!x || !y || !table || !phase || !noise || !bank || !bstate || !env || !estate || n < 0
        || n > MAX_LEN || size < 2 || size > MAX_LEN || bands < 1 || bands > VOC_MAX_BANDS
        || sections < 1 || sections > LANE_SECTIONS_MAX || !(fabs(*phase) <= 1e9)
        || !(fabs(step) <= 1e9) || !(scale > 0.0 && scale <= 1e12))
        return OB_BAD_ARGS;
    Denormals den;
    const Voc a = {x, y, n, table, size, phase, step, scale, nz, noise, bank, bands, sections,
                   bstate, env, estate};
#ifdef OB_HAS_AVX2
    if (has_avx2()) {
        vocoder_avx2(a);
        return OB_OK;
    }
#endif
    vocoder_plain(a);
    return OB_OK;
}

// parts._Oversampled.run with a tanh bend, in one call: kind 0 is Distortion's
// tanh(z * drive) * level, kind 1 Studio polish's warmth, tanh(z d) * (0.3 / tanh(0.3 d))
// with d = max(drive, 0.001). drive glides a0 -> a1 and level b0 -> b1 over the block's
// n * factor samples, as parts._glide does. up, down: the two lowpasses' memories.
OB_API int ob_shaper(const float *h, int taps, int factor, float *up, float *down,
                     const float *x, float *y, i64 n, int kind, double a0, double a1,
                     double b0, double b1) {
    if (!h || !up || !down || !x || !y || taps < 2 || taps > OS_MAX_TAPS || factor < 1
        || factor > OS_MAX_FACTOR || n < 0 || n > MAX_LEN || kind < 0 || kind > 1)
        return OB_BAD_ARGS;
    Denormals den;
    float buf[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR];
    float zb[OS_PART * OS_MAX_FACTOR];
    const i64 m = n * factor;
    const Glide drive(a0, a1, m), level(b0, b1, m);
    const float r = 0.3f;
    const float d0 = drive.v < 1e-3f ? 1e-3f : drive.v;
    const float make = kind == 1 && drive.still ? r / fast_tanh(r * d0) : 0.0f;
    for (i64 at = 0; at < n;) {
        const int c = n - at < OS_PART ? (int)(n - at) : OS_PART, cm = c * factor;
        os_up_part(h, taps, factor, up, x + at, c, zb, buf);
        shape_part(zb, cm, at * factor, kind, drive, level, d0, make);
        os_down_part(h, taps, factor, down, zb, c, y + at, buf);
        at += c;
    }
    return OB_OK;
}

// polish.Polish._deess after its two filters: top and rest are the voice split at the
// de-esser's frequency, y gets rest + top * the de-esser's gain. *lvl (the voice's recent
// level) and *dg (the gain) carry on from block to block. allow: how loud the top may be
// against that level; floor: the most it cuts; gate: the quietest top it reads; times in
// seconds (rise / fall for the level, attack / release for the gain).
OB_API int ob_deess(const float *top, const float *rest, float *y, i64 n, int chunk, int rate,
                    double *lvl, double *dg, double allow, double floor, double gate,
                    double rise, double fall, double attack, double release) {
    if (!top || !rest || !y || !lvl || !dg || n < 0 || n > MAX_LEN || chunk < 1
        || chunk > DEESS_MAX_CHUNK || rate < 1 || !(rise > 0.0) || !(fall > 0.0)
        || !(attack > 0.0) || !(release > 0.0))
        return OB_BAD_ARGS;
    Denormals den;
    float sq[DEESS_MAX_CHUNK];
    double level = *lvl, g = *dg;
    for (i64 s = 0; s < n; s += chunk) {
        const i64 m = n - s < chunk ? n - s : chunk, e = s + m;
        for (i64 i = 0; i < m; i++) sq[i] = top[s + i] * top[s + i];
        const double hi = sqrt((double)chunk_sum(sq, m) / (double)m);
        for (i64 i = 0; i < m; i++) sq[i] = rest[s + i] * rest[s + i];
        const double lo = sqrt((double)chunk_sum(sq, m) / (double)m);
        level = chase(level, lo, m, rate, rise, fall);
        double need = nmin(1.0, allow * level / (hi + 1e-9));
        need = hi < gate ? 1.0 : nmax(need, floor);
        const double was = g;
        g = chase(g, need, m, rate, attack, release);
        for (i64 i = 0; i < m; i++) {
            const float ramp = spread_at(was, g, s, e, s + i + 1);
            y[s + i] = rest[s + i] + top[s + i] * ramp;
        }
    }
    *lvl = level;
    *dg = g;
    return OB_OK;
}

// polish.Polish._limit: the lookahead limiter over one block. look (>= 2): the lookahead in
// samples; need_hist: the last 2 look - 1 gains needed, min_hist: the last look - 1 running
// minima, held: the last `look` input samples, *lg: the slow release; all updated. work:
// work_len (at least 2 n + 5 look) floats. The moving average is summed in double, where
// numpy's convolve sums float32 in its own order: the gain matches to rounding.
OB_API int ob_limiter(const float *x, float *y, i64 n, int look, double ceiling, int rate,
                      double attack, double release, double *lg, float *need_hist,
                      float *min_hist, float *held, float *work, i64 work_len) {
    if (!x || !y || !lg || !need_hist || !min_hist || !held || !work || n < 0 || n > MAX_LEN
        || look < 2 || look > LIMIT_MAX_LOOK || rate < 1 || !(attack > 0.0)
        || !(release > 0.0) || work_len < 2 * n + 5 * (i64)look)
        return OB_BAD_ARGS;
    if (n == 0) return OB_OK;
    Denormals den;
    const i64 L = look, W = 2 * L, H = W - 1;
    const float c = (float)ceiling, kf = (float)(1.0 / (double)look);
    // the gain each sample needs, after the last block's: seq(k) for k < n + W - 1
    auto needed = [&](float v) { return nmin(1.0f, c / (fabsf(v) + 1e-9f)); };
    auto seq = [&](i64 k) { return k < H ? need_hist[k] : needed(x[k - H]); };
    float *mh = work;                 // L - 1 old minima, then this block's n
    float *mins = mh + (L - 1);
    float *gain = mins + n;
    float *suf = gain + n, *pre = suf + W;
    // the running minimum over W (van Herk / Gil-Werman, like dsp.running_min)
    for (i64 b = 0; b < n; b += W) {
        const i64 cnt = n - b < W ? n - b : W;
        float run = seq(b + W - 1);
        suf[W - 1] = run;
        for (i64 j = W - 2; j >= 0; j--) suf[j] = run = nmin(seq(b + j), run);
        mins[b] = suf[0];
        if (cnt > 1) {
            run = seq(b + W);
            pre[0] = run;
            for (i64 j = 1; j < cnt - 1; j++) pre[j] = run = nmin(run, seq(b + W + j));
            for (i64 i = 1; i < cnt; i++) mins[b + i] = nmin(suf[i], pre[i - 1]);
        }
    }
    for (i64 j = 0; j < H; j++) need_hist[j] = seq(n + j);   // reads ahead of its writes
    // the moving average over the lookahead
    for (i64 j = 0; j < L - 1; j++) mh[j] = min_hist[j];
    for (i64 i = 0; i < n; i++) {
        double s = 0;
        const float *p = mh + i;
#pragma omp simd reduction(+ : s)
        for (i64 j = 0; j < L; j++) s += (double)p[j];
        gain[i] = (float)(s * (double)kf);
    }
    for (i64 j = 0; j < L - 1; j++) min_hist[j] = mh[n + j];
    // the slow release, chunk by chunk, never above the gain
    double was = *lg;
    for (i64 s = 0; s < n; s += L) {
        const i64 m = n - s < L ? n - s : L, e = s + m;
        float low = gain[s];
        for (i64 i = 1; i < m; i++) low = nmin(low, gain[s + i]);
        const double now = chase(was, (double)low, m, rate, attack, release);
        for (i64 i = 0; i < m; i++)
            gain[s + i] = nmin(gain[s + i], spread_at(was, now, s, e, s + i + 1));
        was = now;
    }
    *lg = was;
    for (i64 i = 0; i < n; i++) {
        const float v = (i < L ? held[i] : x[i - L]) * gain[i];
        y[i] = nmin(nmax(v, -c), c);
    }
    if (n >= L) {
        memcpy(held, x + n - L, sizeof(float) * L);
    } else {
        for (i64 j = 0; j < L - n; j++) held[j] = held[j + n];
        memcpy(held + (L - n), x, sizeof(float) * n);
    }
    return OB_OK;
}

// ------------------------------------------------------------------ pitch shifter's splice
namespace {

// corr[k] = sum over channels of sum_j cand[k + j] * mid[j], each channel's sum taken in
// j order, for 4 R k's at once: R vectors of running sums in registers, enough of them
// that the adds don't wait on each other (each k's sum is still taken in the same order).
typedef double v4d __attribute__((vector_size(32)));
typedef double v4du __attribute__((vector_size(32), aligned(8)));   // any 8-byte address

template <int R>
__attribute__((always_inline)) inline void splice_block(const double *cd, const double *md,
                                                        i64 clen, int ch, int ovl, i64 k0,
                                                        double *corr) {
    v4d sum[R] = {};
    for (int c = 0; c < ch; c++) {
        const double *p = cd + c * clen + k0, *m = md + (i64)c * ovl;
        v4d acc[R];
        for (int r = 0; r < R; r++) acc[r] = (v4d){0.0, 0.0, 0.0, 0.0};
        for (int j = 0; j < ovl; j++) {
            const v4d w = (v4d){m[j], m[j], m[j], m[j]};
            for (int r = 0; r < R; r++) acc[r] += *(const v4du *)(p + j + 4 * r) * w;
        }
        for (int r = 0; r < R; r++) sum[r] = c ? sum[r] + acc[r] : acc[r];
    }
    for (int r = 0; r < R; r++) *(v4du *)(corr + 4 * r) = sum[r];
}

// one k (the last few)
__attribute__((always_inline)) inline void splice_one(const double *cd, const double *md, i64 clen,
                                                      int ch, int ovl, i64 k, double *corr) {
    double sum = 0.0;
    for (int c = 0; c < ch; c++) {
        const double *p = cd + c * clen + k, *m = md + (i64)c * ovl;
        double acc = 0.0;
        for (int j = 0; j < ovl; j++) acc += p[j] * m[j];
        sum = c ? sum + acc : acc;
    }
    *corr = sum;
}

struct Splice {
    const double *cd, *md;
    i64 clen;
    int ch, ovl, seek;
    double *corr;
};

template <int R>
__attribute__((always_inline)) inline void splice_body(const Splice &a) {
    const i64 n = (i64)a.seek + 1;
    i64 k = 0;
    for (; k + 4 * R <= n; k += 4 * R)
        splice_block<R>(a.cd, a.md, a.clen, a.ch, a.ovl, k, a.corr + k);
    for (; k + 4 <= n; k += 4) splice_block<1>(a.cd, a.md, a.clen, a.ch, a.ovl, k, a.corr + k);
    for (; k < n; k++) splice_one(a.cd, a.md, a.clen, a.ch, a.ovl, k, a.corr + k);
}

void splice_plain(const Splice &a) { splice_body<4>(a); }
#ifdef OB_HAS_AVX2
__attribute__((target("avx2"))) void splice_avx2(const Splice &a) { splice_body<8>(a); }
#endif

}  // namespace

// PitchShift._stretch's splice search: the offset k (0..seek) where the next sequence lines
// up best with the last one's tail, the same arithmetic in double as the Python version:
// corr[k] / sqrt(energy[k] + 1e-9), the first best (or the first NaN, as numpy's argmax).
// cand: (seek + ovl, ch) floats; mid: (ovl, ch) floats; work: work_len doubles, at least
// (seek + ovl + ovl) * ch + seek + 1. Returns k, or a negative error.
OB_API int ob_splice(const float *cand, int ch, const float *mid, int ovl, int seek,
                     double *work, i64 work_len) {
    if (!cand || !mid || !work || ch < 1 || ch > 8 || ovl < 1 || seek < 0 || ovl > (1 << 20)
        || seek > (1 << 20)
        || work_len < ((i64)seek + 2 * (i64)ovl) * ch + (i64)seek + 1)
        return OB_BAD_ARGS;
    Denormals den;
    const i64 clen = (i64)seek + ovl;
    double *cd = work, *md = cd + clen * ch, *corr = md + (i64)ovl * ch;
    for (i64 i = 0; i < clen; i++)
        for (int c = 0; c < ch; c++) cd[c * clen + i] = (double)cand[i * ch + c];
    for (int j = 0; j < ovl; j++)
        for (int c = 0; c < ch; c++) md[(i64)c * ovl + j] = (double)mid[(i64)j * ch + c];
    const Splice a = {cd, md, clen, ch, ovl, seek, corr};
#ifdef OB_HAS_AVX2
    if (has_avx2()) splice_avx2(a);
    else splice_plain(a);
#else
    splice_plain(a);
#endif
    // energy[k] = cs[ovl - 1 + k] - cs[k - 1] with cs the running sum of each frame's
    // channels squared (numpy: cumsum of (cand ** 2).sum(1)), as in Python
    double cs = 0.0, lo = 0.0, best = 0.0;
    int at = 0;
    i64 i = 0;
    auto frame = [&](i64 f) {
        double e = 0.0;
        for (int c = 0; c < ch; c++) {
            const double v = cd[c * clen + f];
            e = c ? e + v * v : v * v;
        }
        return e;
    };
    for (; i < ovl - 1; i++) cs += frame(i);
    for (int k = 0; k <= seek; k++, i++) {
        cs += frame(i);
        const double s = corr[k] / sqrt((cs - lo) + 1e-9);
        lo += frame(k);
        if (s != s) return k;
        if (k == 0 || s > best) {
            best = s;
            at = k;
        }
    }
    return at;
}

static const int FIR_MAX_TAPS = 1025;

// np.convolve(x[:, c], h, "same") for every channel: y[i] = sum_j x[i + taps / 2 - j] h[j]
// (zero outside x), summed in double in j order. x, y: (len, ch) floats, apart; taps odd.
// numpy sums in float32 in its own order: the same to float32 rounding.
OB_API int ob_fir(const float *x, i64 len, int ch, const float *h, int taps, float *y) {
    if (!x || !y || !h || len < 0 || len > MAX_LEN || ch < 1 || ch > 8 || taps < 1
        || taps > FIR_MAX_TAPS || !(taps & 1))
        return OB_BAD_ARGS;
    Denormals den;
    const i64 half = taps / 2, total = len * ch;
    auto edge = [&](i64 t) {     // one output with the zeros past either end
        const i64 i = t / ch;
        double s = 0.0;
        for (int j = 0; j < taps; j++) {
            const i64 f = i + half - j;
            if (f >= 0 && f < len) s += (double)x[t + (half - j) * ch] * (double)h[j];
        }
        y[t] = (float)s;
    };
    const i64 lo = half * ch < total ? half * ch : total;
    const i64 hi = len > 2 * half ? (len - half) * ch : lo;
    for (i64 t = 0; t < lo; t++) edge(t);
    double hd[FIR_MAX_TAPS];
    for (int j = 0; j < taps; j++) hd[j] = (double)h[j];
    const float *base = x + half * ch;
    i64 t = lo;
    for (; t + 8 <= hi; t += 8) {
        double a[8] = {0, 0, 0, 0, 0, 0, 0, 0};
        for (int j = 0; j < taps; j++) {
            const float *p = base + t - (i64)j * ch;
            const double w = hd[j];
            for (int q = 0; q < 8; q++) a[q] += (double)p[q] * w;
        }
        for (int q = 0; q < 8; q++) y[t + q] = (float)a[q];
    }
    for (; t < hi; t++) {
        double s = 0.0;
        const float *p = base + t;
        for (int j = 0; j < taps; j++) s += (double)p[-(i64)j * ch] * hd[j];
        y[t] = (float)s;
    }
    for (t = hi > lo ? hi : lo; t < total; t++) edge(t);
    return OB_OK;
}
