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

#define OB_ABI 2
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

// ------------------------------------------------------------------ oversampling
// The two windowed-sinc lowpasses of a waveshaper's oversampling (_Oversampled in
// voicefx/builtin/parts.py). hist: the last taps - 1 samples, oldest first.

namespace {
const int OS_MAX_TAPS = 256, OS_MAX_FACTOR = 16, OS_PART = 256;
}

// x (n samples) stuffed with factor - 1 zeros and lowpassed: y gets n * factor samples.
OB_API int ob_os_up(const float *h, int taps, int factor, float *hist, const float *x,
                    i64 n, float *y) {
    if (!h || !hist || !x || !y || taps < 2 || taps > OS_MAX_TAPS || factor < 1
        || factor > OS_MAX_FACTOR || n < 0 || n > MAX_LEN)
        return OB_BAD_ARGS;
    Denormals d;
    const int keep = taps - 1;
    float buf[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR];
    const float gain = (float)factor;
    for (i64 at = 0; at < n;) {
        const int c = n - at < OS_PART ? (int)(n - at) : OS_PART;
        const int m = c * factor;
        memcpy(buf, hist, sizeof(float) * keep);
        memset(buf + keep, 0, sizeof(float) * m);
        for (int i = 0; i < c; i++) buf[keep + i * factor] = x[at + i] * gain;
        float *out = y + at * factor;
        for (int j = 0; j < m; j++) {   // only every factor-th input isn't zero
            float s = 0;
            const float *p = buf + keep + j;
            for (int k = j % factor; k < taps; k += factor) s += h[k] * p[-k];
            out[j] = s;
        }
        memcpy(hist, buf + m, sizeof(float) * keep);
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
    const int keep = taps - 1;
    float buf[OS_MAX_TAPS + OS_PART * OS_MAX_FACTOR];
    for (i64 at = 0; at < n;) {
        const int c = n - at < OS_PART ? (int)(n - at) : OS_PART;
        const int m = c * factor;
        memcpy(buf, hist, sizeof(float) * keep);
        memcpy(buf + keep, z + at * factor, sizeof(float) * m);
        for (int i = 0; i < c; i++) {
            float s = 0;
            const float *p = buf + keep + i * factor;
#pragma omp simd reduction(+ : s)
            for (int k = 0; k < taps; k++) s += h[k] * p[-k];
            y[at + i] = s;
        }
        memcpy(hist, buf + m, sizeof(float) * keep);
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
