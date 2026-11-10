// Fuzz host for obdsp: drives every function with random sizes, knobs and hostile samples
// (NaN, Inf, huge, denormal), each buffer ending right at a page nobody may touch, so one
// sample past the end is a crash. With the fuzz DLL any undefined behaviour is one too.
// It also checks that bad calls are refused and that state outside the buffers is left
// alone. scripts/buildtools/fuzz_dsp.py runs it.
//
//   fuzzhost <obdsp_fuzz.dll> <seconds> <seed>         exit 0 = clean
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int64_t i64;
typedef int (*abi_t)();
typedef int (*sos_t)(const double *, int, int, const void *, void *, int, i64, i64, double *);
typedef int (*tf_t)(const double *, const double *, int, const void *, void *, int, i64, i64,
                    double *);
typedef int (*os_t)(const float *, int, int, float *, const float *, i64, float *);
typedef int (*echo_t)(float *, i64, i64 *, const float *, float *, i64, float, float,
                      const double *, int, double *);
typedef int (*comp_t)(const float *, float *, i64, double *, int, int, double, double, double,
                      double, double, float, float);
typedef int (*mono_t)(const double *, double *, double *, double, double, double, double,
                      const float *, float *, i64, double *);
typedef int (*harm_t)(const double *, i64, int, const double *, const double *, double *);
typedef int (*env_t)(const double *, const i64 *, i64, double *, int, double, double, double *);
typedef int (*flange_t)(const float *, float *, i64, i64, const double *, const float *);
typedef int (*cubic_t)(const float *, i64, int, double, double, i64, i64, float, int, float *);
typedef double (*yin_t)(const float *, i64, int, int, int, double, double *);
typedef i64 (*rbytes_t)(int);
typedef int (*rinit_t)(void *, i64, int, int, const double *);
typedef int (*rrun_t)(void *, i64, const float *, float *, i64, double, double, int, float, int,
                      int);
typedef int (*rrung_t)(void *, i64, float);
typedef int (*rclear_t)(void *, i64, int, int);
typedef int (*tlev_t)(const float *, i64, const i64 *, i64, float *);
typedef int (*tgate_t)(const float *, float *, i64, const i64 *, i64, const float *,
                       const double *, double *, i64, i64 *, double *, double, int);
typedef int (*crush_t)(const float *, float *, i64, double *, float *, double, const double *,
                       float, const float *, float, const float *);
typedef int (*chorus_t)(float *, i64, const float *, float *, i64, double *, double, double,
                        const double *, double, float);
typedef int (*wobble_t)(float *, i64, const float *, float *, i64, double *, double, double,
                        const double *, double, const double *);

static uint64_t rng_state;
static uint64_t next_u() {
    uint64_t x = rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return rng_state = x;
}
static int below(int n) { return (int)(next_u() % (uint64_t)n); }
static double unit() { return (double)(next_u() >> 11) / 9007199254740992.0; }

// `bytes` of memory whose end touches a page that faults; freed with give_back.
static void *fenced(size_t bytes) {
    const size_t page = 4096;
    const size_t body = (bytes + page - 1) / page * page;
    char *base = (char *)VirtualAlloc(nullptr, body + page, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!base) { puts("FINDING out of memory"); exit(3); }
    DWORD old;
    VirtualProtect(base + body, page, PAGE_NOACCESS, &old);
    return base + body - bytes;
}
static void give_back(void *p) {
    VirtualFree((void *)((uintptr_t)p & ~(uintptr_t)4095), 0, MEM_RELEASE);
}

static float hostile() {
    switch (below(40)) {
    case 0: return NAN;
    case 1: return INFINITY;
    case 2: return -INFINITY;
    case 3: return 1e30f;
    case 4: return 1e-40f;
    case 5: return 0.0f;
    default: return (float)(2 * unit() - 1);
    }
}

static int block_size() {
    switch (below(6)) {
    case 0: return 1 + below(8);
    case 1: return 480;
    case 2: return 64 << below(5);
    case 3: return 1 + below(5000);
    case 4: return 0;
    default: return 1 + below(600);
    }
}

#define LOAD(type, name) type name = (type)(void *)GetProcAddress(dll, #name); \
    if (!name) { puts("FINDING missing " #name); return 3; }
#define REFUSED(call) if (!((call) < 0)) { printf("FINDING not refused: %s\n", #call); return 4; }
#define OK(call) if ((call) < 0) { printf("FINDING refused: %s\n", #call); return 4; }

int main(int argc, char **argv) {
    if (argc < 4) { puts("usage: fuzzhost <dll> <seconds> <seed>"); return 2; }
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { printf("FINDING can't load %s\n", argv[1]); return 3; }
    LOAD(abi_t, ob_abi) LOAD(sos_t, ob_sos) LOAD(tf_t, ob_tf) LOAD(os_t, ob_os_up)
    LOAD(os_t, ob_os_down) LOAD(echo_t, ob_echo) LOAD(comp_t, ob_compressor)
    LOAD(mono_t, ob_smartmono) LOAD(rbytes_t, ob_reverb_bytes) LOAD(rinit_t, ob_reverb_init)
    LOAD(rrun_t, ob_reverb_run) LOAD(rrung_t, ob_reverb_rung_out) LOAD(rclear_t, ob_reverb_clear)
    LOAD(harm_t, ob_harmonics) LOAD(env_t, ob_envelope) LOAD(flange_t, ob_flanger)
    LOAD(yin_t, ob_yin) LOAD(cubic_t, ob_cubic)
    LOAD(tlev_t, ob_tidy_levels) LOAD(tgate_t, ob_tidy_gate) LOAD(crush_t, ob_bitcrush)
    LOAD(chorus_t, ob_chorus) LOAD(wobble_t, ob_wobble)
    (void)ob_abi;
    const double seconds = atof(argv[2]);
    rng_state = (uint64_t)atoll(argv[3]) * 0x9E3779B97F4A7C15ULL + 1;
    const ULONGLONG t0 = GetTickCount64();
    i64 cases = 0, blocks = 0;

    while ((double)(GetTickCount64() - t0) / 1000.0 < seconds) {
        cases++;
        const int rates[] = {2000, 8000, 22050, 44100, 48000, 96000, 192000, 768000};
        const int rate = rates[below(8)];
        const double hp[5] = {0.98, -1.96, 0.98, -1.96, 0.96};
        const i64 rb = ob_reverb_bytes(rate);
        if (rb <= 0) { puts("FINDING reverb size"); return 4; }
        double *state = (double *)fenced((size_t)(rb + 7) / 8 * 8);
        const i64 rb8 = rb;
        const int pre_max = (int)(0.1 * rate);
        REFUSED(ob_reverb_init(state, rb8 + 8, rate, 0, hp))
        REFUSED(ob_reverb_init(state, rb8, rate, pre_max + 1 + below(100000), hp))
        REFUSED(ob_reverb_init(state, rb8, 1, 0, hp))
        OK(ob_reverb_init(state, rb8, rate, below(pre_max + 1), hp))

        float line[4096] = {0};
        const i64 d = 1 + below(4096);
        i64 at = below((int)d);
        double ez[4] = {0}, cg = 1.0;
        const double one_pole[5] = {0.2, 0.2, 0.0, -0.6, 0.0};
        double bank[4 * 4 * 5];
        for (int i = 0; i < 4 * 4; i++) memcpy(bank + i * 5, hp, sizeof hp);
        double fstate[4 * 2 * 8] = {0}, bands[3 * 5];
        for (int b = 0; b < 3; b++) {
            bands[b * 5] = bands[b * 5 + 1] = bands[b * 5 + 2] = 0;
            bands[b * 5 + 3] = bands[b * 5 + 4] = 1;
        }
        const int taps = 2 + below(255), factor = 1 + below(16);
        float *h = (float *)fenced(sizeof(float) * taps);
        // Clean mic's gate: its history (cap pairs), state and knobs live across blocks
        const i64 tcap = 1 + below(300);
        double *thist = (double *)fenced(sizeof(double) * 2 * tcap);
        memset(thist, 0, sizeof(double) * 2 * tcap);
        i64 tcount = 0;
        double tst[6] = {1.0, 0.0, 0.0, -120.0, -70.0, -60.0};
        double crush_ph = 0.0, ch_ph = 0.0, wb_ph = 0.0;
        float crush_held = 0.0f;
        const int sh = 2 + below(3000);
        float *shist = (float *)fenced(sizeof(float) * sh);
        for (int i = 0; i < sh; i++) shist[i] = hostile();
        float *up = (float *)fenced(sizeof(float) * (taps - 1));
        float *down = (float *)fenced(sizeof(float) * (taps - 1));
        for (int i = 0; i < taps; i++) h[i] = (float)unit();
        memset(up, 0, sizeof(float) * (taps - 1));
        memset(down, 0, sizeof(float) * (taps - 1));

        for (int b = 0; b < 30 && (double)(GetTickCount64() - t0) / 1000.0 < seconds; b++) {
            blocks++;
            const int n = block_size();
            float *x = (float *)fenced(sizeof(float) * (n + 1) * 2);
            float *y = (float *)fenced(sizeof(float) * (n + 1) * 2);
            double *dx = (double *)fenced(sizeof(double) * (n + 1) * 2);
            double *dy = (double *)fenced(sizeof(double) * (n + 1) * 2 * 2);
            for (int i = 0; i < n * 2; i++) { x[i] = hostile(); dx[i] = (double)hostile(); }

            OK(ob_reverb_run(state, rb8, x, y, n, 0.7 + 0.28 * unit(), unit(), below(pre_max + 1),
                             (float)unit(), 1 + below(8), below(5)))
            REFUSED(ob_reverb_run(state, rb8 - 4, x, y, n, 0.8, 0.5, 0, 0.5f, 8, 4))
            REFUSED(ob_reverb_run(state, rb8, x, y, -1, 0.8, 0.5, 0, 0.5f, 8, 4))
            REFUSED(ob_reverb_run(state, rb8, x, y, n, NAN, 0.5, 0, 0.5f, 8, 4))
            REFUSED(ob_reverb_run(state, rb8, x, y, n, 0.8, 0.5, 1 << 30, 0.5f, 8, 4))
            REFUSED(ob_reverb_run(state, rb8, x, y, n, 0.8, 0.5, 0, 0.5f, 0, 4))
            OK(ob_reverb_rung_out(state, rb8, 1e-5f))
            OK(ob_reverb_clear(state, rb8, below(9), below(5)))
            REFUSED(ob_reverb_clear(state, rb8, 9, 0))

            const double c[10] = {0.2, 0.4, 0.2, -0.6, 0.1, 1, 0, 0, 0, 0};
            double s[4 * 2] = {0};
            OK(ob_sos(c, 1, 2, x, y, 4, 2, n, s))
            OK(ob_sos(c, 1, 1, dx, dy, 8, 1, n, s))
            OK(ob_sos(c, 2, 1, dx, dy, 8, 1, n, s))
            double *bs = (double *)fenced(sizeof(double) * 65 * 2);
            double *bc = (double *)fenced(sizeof(double) * 65 * 5);
            memset(bs, 0, sizeof(double) * 65 * 2);
            for (int i = 0; i < 65; i++) memcpy(bc + i * 5, c, sizeof(double) * 5);
            double *by = (double *)fenced(sizeof(double) * 65 * (n + 1));
            const int bf = 1 + below(65);
            OK(ob_sos(bc, bf, 1, dx, by, 8, 1, n, bs))
            give_back(bs);
            give_back(bc);
            give_back(by);
            REFUSED(ob_sos(c, 1, 0, x, y, 4, 1, n, s))
            REFUSED(ob_sos(c, 1, 1, x, y, 5, 1, n, s))
            REFUSED(ob_sos(c, 1, 1, x, y, 4, -1, n, s))
            REFUSED(ob_sos(c, 1, 1, x, y, 4, 1, -1, s))
            REFUSED(ob_sos(c, 1, 1, x, y, 4, (i64)1 << 39, (i64)1 << 39, s))
            const double tb[3] = {0.2, 0.3, 0.1}, ta[2] = {-0.5, 0.1};
            OK(ob_tf(tb, ta, 0, x, y, 4, 1, n, s))
            OK(ob_tf(tb, ta, 1, x, y, 4, 1, n, s))
            OK(ob_tf(tb, ta, 2, dx, dy, 8, 1, n, s))
            REFUSED(ob_tf(tb, ta, -1, x, y, 4, 1, n, s))
            REFUSED(ob_tf(tb, nullptr, 2, x, y, 4, 1, n, s))

            float *big = (float *)fenced(sizeof(float) * (n + 1) * factor);
            float *back = (float *)fenced(sizeof(float) * (n + 1));
            OK(ob_os_up(h, taps, factor, up, x, n, big))
            for (int i = 0; i < n * factor; i++) if (below(50) == 0) big[i] = hostile();
            OK(ob_os_down(h, taps, factor, down, big, n, back))
            REFUSED(ob_os_up(h, 1, factor, up, x, n, big))
            REFUSED(ob_os_up(h, 257, factor, up, x, n, big))
            REFUSED(ob_os_down(h, taps, 17, down, big, n, back))
            REFUSED(ob_os_down(h, taps, factor, down, big, -1, back))
            give_back(big);
            give_back(back);

            const i64 m = n > d ? d : n;
            OK(ob_echo(line, d, &at, x, y, m, (float)unit(), (float)unit(), one_pole, 1, ez))
            OK(ob_echo(line, d, &at, x, y, m, (float)unit(), (float)unit(), nullptr, 0, nullptr))
            if (at < 0 || at >= d) { puts("FINDING echo position"); return 4; }
            REFUSED(ob_echo(line, d, &at, x, y, d + 1, 0.5f, 0.5f, nullptr, 0, nullptr))
            i64 bad = d;
            REFUSED(ob_echo(line, d, &bad, x, y, m, 0.5f, 0.5f, nullptr, 0, nullptr))

            OK(ob_compressor(x, y, n, &cg, 1 + below(200), rate, -40 * unit(), 1 + 19 * unit(), 6.0,
                             0.0005 + 0.05 * unit(), 0.02 + unit(), (float)unit() * 16,
                             (float)unit() * 16))
            REFUSED(ob_compressor(x, y, n, &cg, 0, rate, -20, 4, 6, 0.004, 0.15, 1, 1))
            REFUSED(ob_compressor(x, y, n, &cg, 48, rate, -20, 0.5, 6, 0.004, 0.15, 1, 1))

            double *work = (double *)fenced(sizeof(double) * 10 * (n + 1));
            OK(ob_smartmono(bank, fstate, bands, unit(), -0.35, -0.1, 1.41, x, y, n, work))
            REFUSED(ob_smartmono(bank, fstate, bands, 0.5, -0.35, -0.1, 1.41, x, y, -1, work))
            give_back(work);

            const int ks = below(40);
            double *ko = (double *)fenced(sizeof(double) * (ks + 1));
            double *ka = (double *)fenced(sizeof(double) * (ks + 1));
            for (int i = 0; i < ks; i++) { ko[i] = (double)hostile(); ka[i] = (double)hostile(); }
            OK(ob_harmonics(dx, n, ks, ko, ka, dy))
            REFUSED(ob_harmonics(dx, -1, ks, ko, ka, dy))
            REFUSED(ob_harmonics(dx, n, -1, ko, ka, dy))
            give_back(ko);
            give_back(ka);

            i64 *lens = (i64 *)fenced(sizeof(i64) * (n + 1));
            for (int i = 0; i < n; i++) lens[i] = below(100);
            double g2 = 1.0;
            OK(ob_envelope(dx, lens, n, &g2, rate, 0.001 + unit(), 0.001 + unit(), dy))
            REFUSED(ob_envelope(dx, lens, -1, &g2, rate, 0.1, 0.1, dy))
            REFUSED(ob_envelope(dx, lens, n, &g2, rate, 0.0, 0.1, dy))
            give_back(lens);

            const int dec = 1 + below(8), tmx = 4 + below(400);
            const i64 ylen = (i64)(tmx * 2) * dec;
            float *yh = (float *)fenced(sizeof(float) * ylen);
            double *yw = (double *)fenced(sizeof(double) * 3 * (ylen / dec + 1));
            for (i64 i = 0; i < ylen; i++) yh[i] = hostile();
            const double f0 = ob_yin(yh, ylen, dec, 2, tmx, 12000.0, yw);
            if (f0 < 0 && f0 == f0) { puts("FINDING yin refused"); return 4; }
            for (i64 i = 0; i < ylen; i++) yh[i] = (float)(2 * unit() - 1);
            if (ob_yin(yh, ylen, dec, 2, tmx, 12000.0, yw) < 0) { puts("FINDING yin"); return 4; }
            REFUSED(ob_yin(yh, ylen - 1, dec > 1 ? dec : 2, 2, tmx, 12000.0, yw))
            REFUSED(ob_yin(yh, ylen, dec, 2, (int)(ylen / dec) + 5, 12000.0, yw))
            REFUSED(ob_yin(nullptr, ylen, dec, 2, tmx, 12000.0, yw))
            give_back(yh);
            give_back(yw);

            const int fh = 3 + below(500);
            float *fx = (float *)fenced(sizeof(float) * (fh + n + 1));
            float *fy = (float *)fenced(sizeof(float) * (fh + n + 1));
            double *fd = (double *)fenced(sizeof(double) * (n + 1));
            float *fg = (float *)fenced(sizeof(float) * (n + 1));
            for (int i = 0; i < fh + n; i++) { fx[i] = hostile(); fy[i] = hostile(); }
            for (int i = 0; i < n; i++) {
                fd[i] = 1.0 + (fh - 2.001) * unit();
                fg[i] = (float)unit();
            }
            OK(ob_flanger(fx, fy, fh, n, fd, fg))
            if (n > 0) {
                fd[below(n)] = below(2) ? NAN : (double)fh + 5;
                REFUSED(ob_flanger(fx, fy, fh, n, fd, fg))
            }
            REFUSED(ob_flanger(fx, fy, 1, n, fd, fg))

            // cubic read: a source that ends at the fence, read right up to its last frame
            {
                const int ch = 1 + below(2);
                const i64 clen = 4 + below(6000);
                float *cs = (float *)fenced(sizeof(float) * clen * ch);
                for (i64 i = 0; i < clen * ch; i++) cs[i] = hostile();
                float *cd = (float *)fenced(sizeof(float) * (n + 1) * ch);
                const double step = below(4) ? 0.25 + 2.5 * unit() : 0.0;
                const i64 off = below(3) - 1;
                const double pos0 = 1 - off + unit() * 3;
                // the most frames that stay inside: floor(pos0 + step * (k - 1)) + off + 2 < clen
                i64 k = 0;
                while (k < n && (i64)(pos0 + step * (double)k) + off + 2 < clen) k++;
                OK(ob_cubic(cs, clen, ch, pos0, step, off, k, 0.5f, below(2), cd))
                if (k < n)
                    REFUSED(ob_cubic(cs, clen, ch, pos0, step, off, k + 1, 0.5f, 0, cd))
                REFUSED(ob_cubic(cs, clen, ch, 0.5, step, 0, k ? k : 1, 1.0f, 0, cd))
                REFUSED(ob_cubic(cs, clen, ch, pos0, -1.0, off, k, 1.0f, 0, cd))
                REFUSED(ob_cubic(cs, clen, ch, NAN, step, off, k, 1.0f, 0, cd))
                REFUSED(ob_cubic(cs, clen, 0, pos0, step, off, k, 1.0f, 0, cd))
                give_back(cs);
                give_back(cd);
            }
            give_back(fx);
            give_back(fy);
            give_back(fd);
            give_back(fg);

            if (n > 0) {
                const i64 pieces = 1 + below(n < 40 ? n : 40);
                i64 *edges = (i64 *)fenced(sizeof(i64) * (pieces + 1));
                for (i64 i = 0; i <= pieces; i++) edges[i] = i * n / pieces;
                float *lv = (float *)fenced(sizeof(float) * pieces);
                double *dec = (double *)fenced(sizeof(double) * 2 * pieces);
                for (i64 i = 0; i < 2 * pieces; i++) dec[i] = below(20) ? unit() : (double)hostile();
                OK(ob_tidy_levels(x, n, edges, pieces, lv))
                for (i64 i = 0; i < pieces; i++) if (below(10) == 0) lv[i] = hostile();
                if (tcount + 1 >= tcap) tcount = below((int)tcap);   // (the caller makes room)
                const double sense = below(2) ? NAN : -100 * unit();
                OK(ob_tidy_gate(x, y, n, edges, pieces, lv, dec, thist, tcap, &tcount, tst, sense,
                                below(2)))
                if (tcount < 1 || tcount > tcap) { puts("FINDING tidy count"); return 4; }
                i64 full = tcap;
                REFUSED(ob_tidy_gate(x, y, n, edges, pieces, lv, dec, thist, tcap, &full, tst, sense, 1))
                REFUSED(ob_tidy_levels(x, n + 1, edges, pieces, lv))
                if (pieces > 1) {
                    const i64 keep = edges[1];
                    edges[1] = edges[2];
                    REFUSED(ob_tidy_levels(x, n, edges, pieces, lv))
                    edges[1] = keep;
                }
                give_back(edges);
                give_back(lv);
                give_back(dec);
            }

            double *incs = (double *)fenced(sizeof(double) * (n + 1));
            float *steps = (float *)fenced(sizeof(float) * (n + 1));
            float *mixes = (float *)fenced(sizeof(float) * (n + 1));
            for (int i = 0; i < n; i++) {
                incs[i] = round(unit() * 1048576.0) / 1048576.0;
                steps[i] = below(20) ? (float)ldexp(1.0, -below(16)) : hostile();
                mixes[i] = below(20) ? (float)unit() : hostile();
            }
            const bool glide = below(2);
            OK(ob_bitcrush(x, y, n, &crush_ph, &crush_held, unit(), glide ? incs : nullptr,
                           0.25f, glide ? steps : nullptr,
                           (float)unit(), glide ? mixes : nullptr))
            if (!(crush_ph >= 0.0 && crush_ph < 1.0)) { puts("FINDING crush phase"); return 4; }
            REFUSED(ob_bitcrush(x, y, n, &crush_ph, &crush_held, 1.5, nullptr, 0.5f, nullptr, 1.0f,
                                nullptr))
            double bad_ph = NAN;
            REFUSED(ob_bitcrush(x, y, n, &bad_ph, &crush_held, 0.5, nullptr, 0.5f, nullptr, 1.0f,
                                nullptr))
            give_back(incs);
            give_back(steps);
            give_back(mixes);

            double *depths = (double *)fenced(sizeof(double) * (n + 1));
            double *trems = (double *)fenced(sizeof(double) * (n + 1));
            const double cms = unit() * (sh - 1);
            for (int i = 0; i < n; i++) {
                depths[i] = unit() * ((sh - 1) - cms);
                trems[i] = below(20) ? unit() : (double)hostile();
            }
            const double w = 2 * 3.141592653589793 * 12 * unit() / 8000;
            OK(ob_chorus(shist, sh, x, y, n, &ch_ph, w, unit() * ((sh - 1) - cms),
                         below(2) ? depths : nullptr, cms, (float)unit()))
            OK(ob_wobble(shist, sh, x, y, n, &wb_ph, w, unit() * (sh - 1),
                         below(2) ? depths : nullptr, unit(), below(2) ? trems : nullptr))
            REFUSED(ob_chorus(shist, sh, x, y, n, &ch_ph, w, (double)sh, nullptr, 0.0, 0.5f))
            REFUSED(ob_wobble(shist, sh, x, y, n, &wb_ph, w, (double)sh, nullptr, 0.5, nullptr))
            REFUSED(ob_wobble(shist, 1, x, y, n, &wb_ph, w, 0.0, nullptr, 0.5, nullptr))
            if (n > 0) {
                depths[below(n)] = below(2) ? NAN : -1.0;
                REFUSED(ob_chorus(shist, sh, x, y, n, &ch_ph, w, 0.0, depths, cms, 0.5f))
                REFUSED(ob_wobble(shist, sh, x, y, n, &wb_ph, w, 0.0, depths, 0.5, nullptr))
            }
            give_back(depths);
            give_back(trems);

            give_back(x);
            give_back(y);
            give_back(dx);
            give_back(dy);
        }
        give_back(thist);
        give_back(shist);
        give_back(state);
        give_back(h);
        give_back(up);
        give_back(down);
    }
    printf("done: %lld cases, %lld blocks, clean\n", (long long)cases, (long long)blocks);
    return 0;
}
