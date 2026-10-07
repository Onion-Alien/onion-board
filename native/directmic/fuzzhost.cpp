// Fuzz host for obmic.dll: throws hostile, corrupt, truncated and half-written ring
// files at the effect and drives it the way the audio engine does, many thousands of
// blocks a second, checking that it never crashes, hangs, faults (even a fault its own
// guard catches counts as a finding here) or lets anything but the mic, or sound in
// range, out. Built with the effect by `scripts/build_directmic.py --fuzz`, which also
// builds obmic_fuzz.dll: the effect with sanitizer traps (any undefined behaviour is a
// fault) and a test switch for --selftest. scripts/fuzz_directmic.py runs it.
//
//   fuzzhost <obmic_fuzz.dll> <workdir> <seconds> <seed>      fuzz; exit 0 = clean
//   fuzzhost <obmic_fuzz.dll> <workdir> --selftest            the guard puts the mic back
//   fuzzhost <obmic_fuzz.dll> <workdir> --replay <case seed>  one case, verbose
//   fuzzhost <obmic_fuzz.dll> <workdir> --lead                the lead comes back after hiccups
//
// Nothing touches the PC's audio: the effect only ever sees the ring file
// <workdir>\OnionBoard\MicPlugin\ring2.bin and buffers this program hands it.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <mmreg.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ------------------------------------------------------------------ APO interfaces
typedef enum { BUFFER_INVALID = 0, BUFFER_VALID = 1, BUFFER_SILENT = 2 } APO_BUFFER_FLAGS;
struct APO_CONNECTION_PROPERTY { UINT_PTR pBuffer; UINT32 u32ValidFrameCount;
                                 APO_BUFFER_FLAGS u32BufferFlags; UINT32 u32Signature; };
struct IAudioMediaType;
struct APO_CONNECTION_DESCRIPTOR { int Type; UINT_PTR pBuffer; UINT32 u32MaxFrameCount;
                                   IAudioMediaType *pFormat; UINT32 u32Signature; };
struct IAudioMediaType : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE IsCompressedFormat(BOOL *) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsEqual(IAudioMediaType *, DWORD *) = 0;
    virtual const WAVEFORMATEX *STDMETHODCALLTYPE GetAudioFormat() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetUncompressedAudioFormat(void *) = 0;
};
struct IAudioProcessingObjectRT : public IUnknown {
    virtual void STDMETHODCALLTYPE APOProcess(UINT32, APO_CONNECTION_PROPERTY **, UINT32,
                                              APO_CONNECTION_PROPERTY **) = 0;
    virtual UINT32 STDMETHODCALLTYPE CalcInputFrames(UINT32) = 0;
    virtual UINT32 STDMETHODCALLTYPE CalcOutputFrames(UINT32) = 0;
};
struct IAudioProcessingObjectConfiguration : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE LockForProcess(UINT32, APO_CONNECTION_DESCRIPTOR **, UINT32,
                                                     APO_CONNECTION_DESCRIPTOR **) = 0;
    virtual HRESULT STDMETHODCALLTYPE UnlockForProcess() = 0;
};
struct IAudioProcessingObject : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE Reset() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetLatency(LONGLONG *) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetRegistrationProperties(void **) = 0;
    virtual HRESULT STDMETHODCALLTYPE Initialize(UINT32, BYTE *) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsInputFormatSupported(IAudioMediaType *, IAudioMediaType *,
                                                             IAudioMediaType **) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsOutputFormatSupported(IAudioMediaType *, IAudioMediaType *,
                                                              IAudioMediaType **) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetInputChannelCount(UINT32 *) = 0;
};

static const IID IID_APO = {0xfd7f2b29, 0x24d0, 0x4b5c, {0xb1, 0x77, 0x59, 0x2c, 0x39, 0xf9, 0xca, 0x10}};
static const IID IID_RT = {0x9e1d6a6d, 0xddbc, 0x4e95, {0xa4, 0xc7, 0xad, 0x64, 0xba, 0x37, 0x84, 0x6c}};
static const IID IID_CFG = {0x0e5ed805, 0xaba6, 0x49c3, {0x8f, 0x9a, 0x2b, 0x8c, 0x88, 0x9c, 0x4f, 0xa8}};
static const CLSID CLSID_OnionMic = {0xc55e76fe, 0x6667, 0x4828, {0x81, 0xfd, 0x05, 0xb3, 0x93, 0xfd, 0x64, 0x9e}};

class MediaType final : public IAudioMediaType {
public:
    WAVEFORMATEXTENSIBLE f;
    MediaType(UINT32 rate, UINT32 ch) {
        memset(&f, 0, sizeof f);
        f.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
        f.Format.nChannels = (WORD)ch;
        f.Format.nSamplesPerSec = rate;
        f.Format.wBitsPerSample = 32;
        f.Format.nBlockAlign = (WORD)(4 * ch);
        f.Format.nAvgBytesPerSec = rate * 4 * ch;
        f.Format.cbSize = 22;
        f.Samples.wValidBitsPerSample = 32;
        f.SubFormat = {0x00000003, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};
    }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID, void **p) override { *p = NULL; return E_NOINTERFACE; }
    ULONG STDMETHODCALLTYPE AddRef() override { return 2; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE IsCompressedFormat(BOOL *c) override { *c = FALSE; return S_OK; }
    HRESULT STDMETHODCALLTYPE IsEqual(IAudioMediaType *, DWORD *) override { return E_NOTIMPL; }
    const WAVEFORMATEX *STDMETHODCALLTYPE GetAudioFormat() override { return &f.Format; }
    HRESULT STDMETHODCALLTYPE GetUncompressedAudioFormat(void *) override { return E_NOTIMPL; }
};

class Outer : public IUnknown {
public:
    IUnknown *inner = NULL;
    LONG ref = 1;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **p) override {
        if (IsEqualIID(riid, IID_IUnknown)) { *p = this; AddRef(); return S_OK; }
        return inner->QueryInterface(riid, p);
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&ref); }
    ULONG STDMETHODCALLTYPE Release() override { return InterlockedDecrement(&ref); }
};

typedef HRESULT(STDAPICALLTYPE *GetClassObjectFn)(REFCLSID, REFIID, void **);
typedef LONG(*FaultsFn)(DWORD *, void **);

// ------------------------------------------------------------------ randomness
static uint64_t g_rng;
static uint64_t rnd() {   // splitmix64
    uint64_t z = (g_rng += 0x9e3779b97f4a7c15ull);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
    return z ^ (z >> 31);
}
static uint32_t below(uint32_t n) { return n ? (uint32_t)(rnd() % n) : 0; }
static bool chance(double p) { return (double)(rnd() >> 11) / 9007199254740992.0 < p; }
static double unit() { return (double)(rnd() >> 11) / 9007199254740992.0; }

static uint64_t interesting64() {
    static const uint64_t v[] = {0, 1, 2, 3, 0x7f, 0x80, 0xff, 0x7fff, 0x8000, 0xffff,
                                 0x7fffffff, 0x80000000ull, 0xffffffffull, 0x100000000ull,
                                 (1ull << 52) - 1, 1ull << 52, (1ull << 52) + 1, 1ull << 53,
                                 1ull << 62, 0x7fffffffffffffffull, 0x8000000000000000ull,
                                 0xfffffffffffffffeull, 0xffffffffffffffffull, 48000, 44100,
                                 16000, 480, 441, 160, 4096, 65536};
    return chance(0.7) ? v[below(sizeof v / sizeof v[0])] : rnd();
}

static float interestingFloat() {
    static const float v[] = {0.0f, -0.0f, 1.0f, -1.0f, 0.5f, 2.0f, 15.99f, 16.0f, 4.0f, 4.001f,
                              1e30f, -1e30f, 1e-40f /* denormal */, -1e-40f, 3.4e38f};
    uint32_t k = below(20);
    if (k < sizeof v / sizeof v[0]) return v[k];
    if (k == 15) return NAN;
    if (k == 16) return INFINITY;
    if (k == 17) return -INFINITY;
    uint32_t bits = (uint32_t)rnd();
    float f;
    memcpy(&f, &bits, 4);
    return f;
}

static float sampleValue() {
    if (chance(0.9)) return (float)(unit() * 1.6 - 0.8);
    return interestingFloat();
}

// ------------------------------------------------------------------ the ring layout
static const uint32_t MAGIC = 0x434d424f, VERSION = 2, HEADER = 4096, SLOT_OFFSET = 256;
// field offsets and sizes (obmic.cpp RingHeader)
struct Field { uint32_t off, size; bool isFloat; };
static const Field FIELDS[] = {
    {0, 4, false}, {4, 4, false}, {8, 4, false}, {12, 4, false}, {16, 8, false},
    {24, 8, false}, {32, 4, false}, {36, 4, false}, {40, 4, true}, {44, 4, true},
    {48, 4, false}, {52, 4, false}, {56, 8, false}, {64, 4, false}, {68, 4, false},
    {72, 8, false}, {80, 4, false}, {84, 4, false}, {88, 4, false},
    {96, 8, false}, {104, 8, false},   // (not pad1 at 92: the fuzz build's fault switch)
};
static const uint32_t NFIELDS = sizeof FIELDS / sizeof FIELDS[0];

static wchar_t g_ringPath[MAX_PATH];

struct Mapped {
    HANDLE file = INVALID_HANDLE_VALUE, map = NULL;
    uint8_t *p = NULL;
    uint64_t size = 0;
    void close() {
        if (p) UnmapViewOfFile(p);
        if (map) CloseHandle(map);
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        p = NULL; map = NULL; file = INVALID_HANDLE_VALUE; size = 0;
    }
};

template <class T> static T rd(const uint8_t *p, uint32_t off) { T v; memcpy(&v, p + off, sizeof v); return v; }
template <class T> static void wr(uint8_t *p, uint32_t off, T v) { memcpy(p + off, &v, sizeof v); }

// One ring file, sane or not. Returns false if it couldn't be written.
struct Layout { uint32_t cap, mcap, rate; bool valid; uint64_t size; };

static bool writeRing(Layout &L, Mapped &m) {
    DeleteFileW(g_ringPath);
    HANDLE f = CreateFileW(g_ringPath, GENERIC_READ | GENERIC_WRITE,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz;
    sz.QuadPart = (LONGLONG)L.size;
    if (!SetFilePointerEx(f, sz, NULL, FILE_BEGIN) || !SetEndOfFile(f)) { CloseHandle(f); return false; }
    m.file = f;
    m.size = L.size;
    if (L.size == 0) return true;
    m.map = CreateFileMappingW(f, NULL, PAGE_READWRITE, 0, 0, NULL);
    if (!m.map) return false;
    m.p = (uint8_t *)MapViewOfFile(m.map, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!m.p) return false;
    uint8_t *p = m.p;
    // the header as soundboard/directmic.py writes it
    if (L.size >= HEADER) {
        wr<uint32_t>(p, 0, MAGIC);
        wr<uint32_t>(p, 4, VERSION);
        wr<uint32_t>(p, 8, L.rate);
        wr<uint32_t>(p, 12, L.cap);
        wr<float>(p, 40, 1.0f);
        wr<float>(p, 44, 1.0f);
        wr<uint32_t>(p, 48, L.mcap);
        wr<uint32_t>(p, 36, below(2));
        if (!L.valid) {   // break it some way
            switch (below(5)) {
            case 0: wr<uint32_t>(p, 0, (uint32_t)rnd()); break;
            case 1: wr<uint32_t>(p, 4, below(2) ? 1 : 3); break;
            case 2: wr<uint32_t>(p, 12, (uint32_t)interesting64()); break;
            case 3: wr<uint32_t>(p, 48, (uint32_t)interesting64()); break;
            default: wr<uint32_t>(p, 8, (uint32_t)interesting64()); break;
            }
        }
    } else {
        for (uint64_t i = 0; i < L.size; i++) p[i] = (uint8_t)rnd();
    }
    // samples: mostly sound, some junk
    uint64_t n = L.size > HEADER ? (L.size - HEADER) / 4 : 0;
    float *s = (float *)(p + HEADER);
    for (uint64_t i = 0; i < n && i < (1u << 16); i++) s[i] = sampleValue();
    return true;
}

static Layout pickLayout() {
    Layout L;
    L.cap = 1u << (4 + below(17));
    L.mcap = 1u << (4 + below(17));
    static const uint32_t rates[] = {48000, 48000, 48000, 44100, 16000, 8000, 96000, 192000,
                                     384000, 11025, 22050, 32000, 12345};
    L.rate = rates[below(sizeof rates / sizeof rates[0])];
    L.valid = chance(0.85);
    uint64_t need = HEADER + (uint64_t)L.cap * 4 + (uint64_t)L.mcap * 8;
    L.size = need;
    if (chance(0.2)) L.size += below(9000);
    if (!L.valid && chance(0.4)) {   // too small: truncated, half-written
        static const uint64_t small[] = {0, 1, 100, 4095, 4096, 4097};
        L.size = chance(0.5) ? small[below(6)] : below((uint32_t)(need > 0xffffffffull ? 0xffffffffu : need));
    }
    return L;
}

// ------------------------------------------------------------------ the effect
struct Instance {
    IUnknown *inner = NULL;
    Outer outer;
    IAudioProcessingObject *apo = NULL;
    IAudioProcessingObjectRT *rt = NULL;
    IAudioProcessingObjectConfiguration *cfg = NULL;
    MediaType *mt = NULL;
    UINT32 rate = 0, ch = 0, maxFrames = 0;
    float *in = NULL, *out = NULL;
    bool locked = false;
};

static IClassFactory *g_cf;
static FaultsFn g_faultsFn;

// the watchdog: one call stuck this long is a hang
static volatile LONGLONG g_callStart;   // QPC of the call running now (0 = none)
static volatile uint64_t g_caseSeed;
static LARGE_INTEGER g_freq;
static const double HANG_S = 0.5;

static DWORD WINAPI watchdog(void *) {
    for (;;) {
        Sleep(50);
        LONGLONG s = g_callStart;
        if (!s) continue;
        LARGE_INTEGER t;
        QueryPerformanceCounter(&t);
        if ((double)(t.QuadPart - s) / g_freq.QuadPart > HANG_S && g_callStart == s) {
            printf("HANG: one call took over %.1f s, case seed %llu\n", HANG_S,
                   (unsigned long long)g_caseSeed);
            fflush(stdout);
            TerminateProcess(GetCurrentProcess(), 4);
        }
    }
}

static LONG WINAPI crashed(EXCEPTION_POINTERS *ep) {
    HMODULE mod = NULL;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCSTR)ep->ExceptionRecord->ExceptionAddress, &mod);
    char name[MAX_PATH] = "?";
    if (mod) GetModuleFileNameA(mod, name, MAX_PATH);
    printf("CRASH: exception 0x%08lx at %p (%s + 0x%llx), case seed %llu\n",
           (unsigned long)ep->ExceptionRecord->ExceptionCode, ep->ExceptionRecord->ExceptionAddress,
           name, (unsigned long long)((uintptr_t)ep->ExceptionRecord->ExceptionAddress - (uintptr_t)mod),
           (unsigned long long)g_caseSeed);
    fflush(stdout);
    TerminateProcess(GetCurrentProcess(), 3);
    return EXCEPTION_EXECUTE_HANDLER;
}

static double g_maxCallUs;
static uint64_t g_maxCallSeed;   // the case it was in
static uint64_t g_blocks, g_findings;

static bool create(Instance &x, UINT32 rate, UINT32 ch, UINT32 maxFrames) {
    if (FAILED(g_cf->CreateInstance(&x.outer, IID_IUnknown, (void **)&x.inner))) return false;
    x.outer.inner = x.inner;
    if (FAILED(x.outer.QueryInterface(IID_APO, (void **)&x.apo))) return false;
    x.apo->QueryInterface(IID_RT, (void **)&x.rt);
    x.apo->QueryInterface(IID_CFG, (void **)&x.cfg);
    if (!x.rt || !x.cfg || FAILED(x.apo->Initialize(0, NULL))) return false;
    x.rate = rate; x.ch = ch; x.maxFrames = maxFrames;
    x.mt = new MediaType(rate, ch);
    x.in = (float *)calloc((size_t)maxFrames * ch + 16, sizeof(float));
    x.out = (float *)calloc((size_t)maxFrames * ch + 16, sizeof(float));
    APO_CONNECTION_DESCRIPTOR din = {0, (UINT_PTR)x.in, maxFrames, x.mt, 0};
    APO_CONNECTION_DESCRIPTOR dout = {0, (UINT_PTR)x.out, maxFrames, x.mt, 0};
    APO_CONNECTION_DESCRIPTOR *pin = &din, *pout = &dout;
    if (FAILED(x.cfg->LockForProcess(1, &pin, 1, &pout))) return false;
    x.locked = true;
    return true;
}

static void destroy(Instance &x) {
    if (x.locked) x.cfg->UnlockForProcess();
    if (x.cfg) x.cfg->Release();
    if (x.rt) x.rt->Release();
    if (x.apo) x.apo->Release();
    if (x.inner) x.inner->Release();
    delete x.mt;
    free(x.in);
    free(x.out);
    x = Instance();
}

static LONG faultsNow(DWORD *code = NULL, void **addr = NULL) {
    return g_faultsFn ? g_faultsFn(code, addr) : 0;
}

// One block through one instance. Returns false on a finding.
static bool runBlock(Instance &x, bool expectPassThrough, bool verbose, bool *passedThrough = NULL) {
    UINT32 frames = chance(0.9) ? x.maxFrames : below(x.maxFrames + 1);
    bool silent = chance(0.15);
    for (UINT32 i = 0; i < frames * x.ch; i++) x.in[i] = (float)(unit() * 1.8 - 0.9);
    bool inPlace = chance(0.2);
    float *obuf = inPlace ? x.in : x.out;
    if (!inPlace) for (UINT32 i = 0; i < frames * x.ch; i++) x.out[i] = 12345.0f;
    // what the engine would hand on if the effect did nothing
    static float expect[192000 / 50 * 8 + 16];
    memcpy(expect, x.in, (size_t)frames * x.ch * sizeof(float));
    APO_CONNECTION_PROPERTY in = {(UINT_PTR)x.in, frames, silent ? BUFFER_SILENT : BUFFER_VALID, 0};
    APO_CONNECTION_PROPERTY o = {(UINT_PTR)obuf, 0, BUFFER_INVALID, 0};
    APO_CONNECTION_PROPERTY *pi = &in, *po = &o;
    LONG f0 = faultsNow();
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    g_callStart = t0.QuadPart;
    x.rt->APOProcess(1, &pi, 1, &po);
    g_callStart = 0;
    QueryPerformanceCounter(&t1);
    double us = (double)(t1.QuadPart - t0.QuadPart) * 1e6 / g_freq.QuadPart;
    if (us > g_maxCallUs) {
        g_maxCallUs = us;
        g_maxCallSeed = g_caseSeed;
    }
    g_blocks++;
    bool ok = true;
    DWORD code = 0;
    void *addr = NULL;
    LONG f1 = faultsNow(&code, &addr);
    if (f1 != f0) {
        printf("FINDING: the guard caught exception 0x%08lx at %p (case seed %llu)\n",
               (unsigned long)code, addr, (unsigned long long)g_caseSeed);
        ok = false;
    }
    if (o.u32ValidFrameCount != frames) {
        printf("FINDING: %u frames out for %u in (case seed %llu)\n", o.u32ValidFrameCount, frames,
               (unsigned long long)g_caseSeed);
        ok = false;
    }
    bool same = true;
    if (o.u32BufferFlags == BUFFER_VALID) {
        for (UINT32 i = 0; i < frames * x.ch; i++) {
            float v = obuf[i];
            if (!(v >= -1.0f && v <= 1.0f)) {
                printf("FINDING: sample %u is %g (case seed %llu)\n", i, (double)v,
                       (unsigned long long)g_caseSeed);
                ok = false;
                break;
            }
            if (v != expect[i]) same = false;
        }
        if (silent) same = false;   // (a silent block made valid: the effect added something)
    } else if (o.u32BufferFlags == BUFFER_SILENT && silent) {
        same = true;                // (left silent, as it came in)
    } else {
        printf("FINDING: buffer flags %d for a %s block (case seed %llu)\n", (int)o.u32BufferFlags,
               silent ? "silent" : "valid", (unsigned long long)g_caseSeed);
        ok = false;
    }
    if (passedThrough) *passedThrough = same;
    if (expectPassThrough && !same) {
        printf("FINDING: the mic didn't pass through untouched (case seed %llu)\n",
               (unsigned long long)g_caseSeed);
        ok = false;
    }
    if (verbose)
        printf("  block: %u frames, %s, %s, %.0f us, flags %d, same %d\n", frames,
               silent ? "silent" : "valid", inPlace ? "in place" : "copy", us, (int)o.u32BufferFlags,
               (int)same);
    if (!ok) g_findings++;
    return ok;
}

// The board, as directmic.py runs it (plus whatever the case throws at the header).
struct Board {
    uint64_t wp = 0, micWp = 0;
    uint32_t seq = 0;
};

static void boardStep(Mapped &m, const Layout &L, Board &b, UINT32 micRate, UINT32 frames) {
    uint8_t *p = m.p;
    if (!p || m.size < HEADER) return;
    uint64_t dataEnd = m.size;
    // new audio (in what's really there of the file)
    uint32_t n = L.rate && micRate ? (uint32_t)((uint64_t)frames * L.rate / micRate) + below(3) : 0;
    if (chance(0.05)) n = 0;            // late
    if (chance(0.02)) n *= 4;           // a burst after being late
    if (L.cap && (L.cap & (L.cap - 1)) == 0 && HEADER + (uint64_t)L.cap * 4 <= dataEnd) {
        float *s = (float *)(p + HEADER);
        for (uint32_t i = 0; i < n; i++) s[(b.wp + i) & (L.cap - 1)] = sampleValue();
    }
    b.wp += n;
    wr<uint64_t>(p, 16, b.wp);
    wr<uint64_t>(p, 24, GetTickCount64() - (chance(0.03) ? below(400) : 0));
    wr<uint32_t>(p, 32, chance(0.97) ? 1 : 0);
    if (chance(0.01)) wr<uint32_t>(p, 36, below(2));
    if (chance(0.05)) {   // the sync pair, under its sequence number
        b.seq |= 1;
        wr<uint32_t>(p, 88, b.seq);
        uint64_t mwp = rd<uint64_t>(p, 56);
        wr<uint64_t>(p, 96, b.wp > 2000 ? b.wp - below(2000) : b.wp);
        wr<uint64_t>(p, 104, mwp > 2000 ? mwp - below(2000) : mwp);
        b.seq++;
        wr<uint32_t>(p, 88, b.seq);
    }
}

static void hostile(Mapped &m, uint32_t hits) {
    uint8_t *p = m.p;
    if (!p || m.size < HEADER) return;
    for (uint32_t k = 0; k < hits; k++) {
        uint32_t what = below(10);
        if (what < 6) {          // one header field: an interesting value
            const Field &f = FIELDS[below(NFIELDS)];
            if (f.isFloat) wr<float>(p, f.off, interestingFloat());
            else if (f.size == 8) wr<uint64_t>(p, f.off, interesting64());
            else wr<uint32_t>(p, f.off, (uint32_t)interesting64());
        } else if (what < 8) {   // a slot: random bytes
            uint32_t off = SLOT_OFFSET + below(16 * 64);
            p[off] = (uint8_t)rnd();
        } else if (what < 9) {   // anywhere in the header page (but pad1)
            uint32_t off = below(HEADER);
            if (off < 92 || off > 95) p[off] = (uint8_t)rnd();
        } else {                 // samples: junk
            uint64_t ns = (m.size - HEADER) / 4;
            if (ns) ((float *)(p + HEADER))[rnd() % ns] = interestingFloat();
        }
    }
}

// writes random bytes into the header from another thread: torn reads
static volatile uint8_t *volatile g_hammerP;
static volatile LONG g_hammerOn, g_hammerBusy;
static DWORD WINAPI hammer(void *) {
    uint64_t s = 0x1234567;
    for (;;) {
        InterlockedIncrement(&g_hammerBusy);
        volatile uint8_t *p = g_hammerOn ? g_hammerP : NULL;
        if (p) {
            for (int k = 0; k < 64; k++) {
                s = s * 6364136223846793005ull + 1442695040888963407ull;
                uint32_t off = (uint32_t)(s >> 33) % 112;   // the fields the effect reads
                if (off < 16 && ((s >> 20) & 7)) continue;  // mostly leave the layout alone
                if (off >= 92 && off <= 95) continue;       // (the fault switch)
                p[off] = (uint8_t)(s >> 13);
            }
        }
        InterlockedDecrement(&g_hammerBusy);
        if (!p) Sleep(1);
        else SwitchToThread();
    }
}

static void hammerStop() {
    g_hammerOn = 0;
    g_hammerP = NULL;
    while (g_hammerBusy) SwitchToThread();
}

// What the effect's openRing makes of the file: false = it must leave the mic alone.
static bool layoutUsable(const Mapped &m) {
    if (!m.p || m.size < HEADER) return false;
    uint32_t cap = rd<uint32_t>(m.p, 12), mcap = rd<uint32_t>(m.p, 48), rate = rd<uint32_t>(m.p, 8);
    uint64_t need = HEADER + (uint64_t)cap * 4 + (uint64_t)mcap * 8;
    return rd<uint32_t>(m.p, 0) == MAGIC && rd<uint32_t>(m.p, 4) == VERSION && cap &&
           !(cap & (cap - 1)) && mcap && !(mcap & (mcap - 1)) && cap <= (1u << 22) &&
           mcap <= (1u << 22) && m.size >= need && rate >= 8000 && rate <= 384000;
}

static bool runCase(uint64_t seed, bool verbose) {
    g_rng = seed;
    g_caseSeed = seed;
    Layout L = pickLayout();
    Mapped m;
    if (!writeRing(L, m)) {
        printf("can't write the ring file (case seed %llu): error %lu\n", (unsigned long long)seed,
               GetLastError());
        m.close();
        return true;   // not the effect's fault
    }
    static const UINT32 rates[] = {48000, 44100, 16000, 8000, 96000, 192000, 32000, 22050, 11025, 24000};
    int count = 1 + (int)below(3);
    Instance xs[3];
    bool ok = true;
    if (verbose)
        printf("case %llu: cap %u mcap %u rate %u valid %d size %llu, %d apps\n",
               (unsigned long long)seed, L.cap, L.mcap, L.rate, (int)L.valid,
               (unsigned long long)L.size, count);
    for (int n = 0; n < count; n++) {
        UINT32 rate = rates[below(sizeof rates / sizeof rates[0])];
        UINT32 ch = 1 + below(chance(0.8) ? 2 : 8);
        UINT32 maxFrames = chance(0.8) ? rate / 100 : 1 + below(rate / 50);
        if (!create(xs[n], rate, ch, maxFrames)) {
            printf("FINDING: instance %d failed to start (case seed %llu)\n", n, (unsigned long long)seed);
            g_findings++;
            ok = false;
            count = n;
            break;
        }
    }
    // A broken layout: the effect must leave the mic exactly as it is, start to end.
    bool broken = !layoutUsable(m);
    Board b;
    uint32_t blocks = 20 + below(400);
    double hostileP = chance(0.3) ? 0.0 : chance(0.5) ? 0.05 : 0.5;
    bool useHammer = chance(0.2);
    if (useHammer && m.p && m.size >= HEADER) {
        g_hammerP = m.p;
        g_hammerOn = 1;
    }
    if (verbose) printf("  broken %d, hostile %.2f, hammer %d, %u blocks\n", (int)broken, hostileP,
                        (int)useHammer, blocks);
    for (uint32_t k = 0; k < blocks && ok; k++) {
        if (count) boardStep(m, L, b, xs[0].rate, xs[0].maxFrames);
        if (chance(hostileP)) hostile(m, 1 + below(6));
        if (chance(0.003) && m.p && m.size >= HEADER) {   // all fixed again
            wr<uint32_t>(m.p, 0, MAGIC);
            wr<float>(m.p, 40, 1.0f);
            wr<float>(m.p, 44, 1.0f);
        }
        for (int n = 0; n < count && ok; n++)
            ok = runBlock(xs[n], broken, verbose);
    }
    hammerStop();
    for (int n = 0; n < 3; n++) destroy(xs[n]);
    m.close();
    return ok;
}

// The guard: a fault in the effect (the fuzz build's switch, pad1 = 0x0BADF00D) puts the
// block back exactly as it came in, rests the effect a moment, then it's back to normal.
static int selftest() {
    g_rng = 42;
    g_caseSeed = 0;
    Layout L = {1u << 16, 1u << 16, 48000, true, 0};
    L.size = HEADER + (uint64_t)L.cap * 4 + (uint64_t)L.mcap * 8;
    Mapped m;
    if (!writeRing(L, m)) { printf("can't write the ring\n"); return 1; }
    wr<uint32_t>(m.p, 36, 1);   // MODE_REPLACE: the board's audio replaces the mic
    float *s = (float *)(m.p + HEADER);
    Instance x;
    if (!create(x, 48000, 2, 480)) { printf("can't start the effect\n"); return 1; }
    Board b;
    int replaced = 0, kept = 0, faultsSeen = 0;
    LONG f0 = faultsNow();
    auto step = [&](int blocks, bool expectSame, const char *what) -> bool {
        int notSame = 0;
        for (int k = 0; k < blocks; k++) {
            for (uint32_t i = 0; i < 480; i++) s[(b.wp + i) & (L.cap - 1)] = 0.25f;
            b.wp += 480;
            wr<uint64_t>(m.p, 16, b.wp);
            wr<uint64_t>(m.p, 24, GetTickCount64());
            wr<uint32_t>(m.p, 32, 1);
            bool same = false;
            g_rng = 1000 + k;
            // (runBlock counts guard faults as findings; here they're the point)
            FaultsFn keep = g_faultsFn;
            g_faultsFn = NULL;
            runBlock(x, false, false, &same);
            g_faultsFn = keep;
            if (expectSame && !same) { printf("selftest: %s: a block wasn't the mic as it came in\n", what); return false; }
            if (!same) notSame++;
            Sleep(1);
        }
        if (!expectSame) replaced = notSame;
        return true;
    };
    g_findings = 0;
    if (!step(60, false, "before")) return 1;
    if (!replaced) { printf("selftest: the board's audio never came through\n"); return 1; }
    wr<uint32_t>(m.p, 92, 0x0BADF00Du);   // fault on every block
    if (!step(20, true, "faulting")) return 1;
    faultsSeen = (int)(faultsNow() - f0);
    if (faultsSeen < 1) { printf("selftest: the switch didn't fault\n"); return 1; }
    wr<uint32_t>(m.p, 92, 0);
    if (!step(20, true, "resting")) return 1;   // still resting (a second)
    Sleep(1100);
    replaced = 0;
    if (!step(60, false, "after")) return 1;
    kept = replaced;
    destroy(x);
    m.close();
    printf("selftest: %d faults caught, mic restored on each; board back after the rest (%d blocks)\n",
           faultsSeen, kept);
    if (!kept) { printf("selftest: the effect never came back\n"); return 1; }
    printf("SELFTEST OK\n");
    return 0;
}

// --lead: the lead the effect reads behind the board, through a board late by a block
// once, then late every other block for a while (a busy PC), then on time. It should
// grow just enough to ride each out, really read that far behind (not just count it),
// and once the board keeps time, come back to the normal lead. Run with the board's
// sync pair (late blocks filled in with the mic from then) and without (an older
// board). Block by block, so it's the same every run.
static int leadcase(bool sync) {
    const uint32_t F = 480, BASE = 960, STEP = 240;   // 10 ms blocks; LEAD_DEFAULT_S, LEAD_STEP_S
    Layout L = {1u << 16, 1u << 16, 48000, true, 0};
    L.size = HEADER + (uint64_t)L.cap * 4 + (uint64_t)L.mcap * 8;
    Mapped m;
    if (!writeRing(L, m)) { printf("can't write the ring\n"); return 1; }
    memset(m.p + HEADER, 0, (size_t)(L.size - HEADER));
    wr<uint32_t>(m.p, 36, 1);   // MODE_REPLACE
    float *s = (float *)(m.p + HEADER);
    Instance x;
    if (!create(x, 48000, 1, F)) { printf("can't start the effect\n"); return 1; }
    uint64_t wp = 0;
    uint32_t seq = 0;
    auto write = [&](uint32_t n) {   // 100 ms of tone, 100 ms of silence
        for (uint32_t i = 0; i < n; i++) {
            uint64_t k = wp + i;
            s[k & (L.cap - 1)] = (k / 4800) % 2 ? 0.0f
                : 0.4f * (float)sin(2 * 3.141592653589793 * 440 * (double)k / 48000);
        }
        wp += n;
        wr<uint64_t>(m.p, 16, wp);
        wr<uint64_t>(m.p, 24, GetTickCount64());
        wr<uint32_t>(m.p, 32, 1);
        if (sync) {   // made from the clean mic up to now
            wr<uint32_t>(m.p, 88, ++seq);
            wr<uint64_t>(m.p, 96, wp);
            wr<uint64_t>(m.p, 104, rd<uint64_t>(m.p, 56));
            wr<uint32_t>(m.p, 88, ++seq);
        }
    };
    auto block = [&]() {
        for (uint32_t i = 0; i < F; i++) x.in[i] = 0.001f;
        APO_CONNECTION_PROPERTY in = {(UINT_PTR)x.in, F, BUFFER_VALID, 0};
        APO_CONNECTION_PROPERTY o = {(UINT_PTR)x.out, 0, BUFFER_INVALID, 0};
        APO_CONNECTION_PROPERTY *pi = &in, *po = &o;
        x.rt->APOProcess(1, &pi, 1, &po);
    };
    auto slot = [&](uint32_t off) -> uint64_t {   // this instance's slot
        for (uint32_t k = 0; SLOT_OFFSET + (k + 1) * 64 <= HEADER; k++) {
            const uint8_t *p = m.p + SLOT_OFFSET + k * 64;
            if (rd<LONG>(p, 0)) return off == 24 ? rd<uint64_t>(p, off) : rd<uint32_t>(p, off);
        }
        return 0;
    };
    write(3 * F);
    // The board writes right after each mic block. At block 100 it's a block late (then
    // writes both); from 600 to 640, late every other block.
    uint32_t owed = 0, most1 = 0, most2 = 0;
    int fails = 0;
    for (int k = 0; k < 1600; k++) {
        block();
        uint32_t n = F + owed;
        owed = 0;
        if (k == 100 || (k >= 600 && k < 640 && k % 2 == 0)) { owed = n; n = 0; }
        if (n) write(n);
        uint32_t lead = (uint32_t)slot(32);
        if (k < 600) most1 = lead > most1 ? lead : most1;
        else most2 = lead > most2 ? lead : most2;
        if (k == 590 && (lead != BASE || wp - slot(24) != BASE)) {
            printf("  after the first hiccup: lead %u, reads %llu behind\n", lead,
                   (unsigned long long)(wp - slot(24)));
            fails++;
        }
    }
    uint64_t lead = slot(32), behind = wp - slot(24);
    printf("%s: one hiccup: lead up to %u; late every other block: up to %u; at the end %llu,"
           " reads %llu behind the board, late %llu times\n", sync ? "sync pair" : "no sync pair",
           most1, most2, (unsigned long long)lead, (unsigned long long)behind,
           (unsigned long long)slot(36));
    destroy(x);
    m.close();
    // one hiccup a block long: one step. Late every other block: a block more than the
    // normal lead covers it (two steps); the same lag, counted again before the step it
    // already took was taken, piled steps on top of that.
    if (most1 != BASE + STEP) { printf("  one hiccup should take one step\n"); fails++; }
    if (most2 > BASE + 2 * STEP) { printf("  a lag of one block grew it more than it needed\n"); fails++; }
    // (the board just wrote: it reads exactly the lead behind it)
    if (lead != BASE || behind != BASE) { printf("  the lead didn't come back to %u\n", BASE); fails++; }
    return fails;
}

static int leadtest() {
    g_rng = 7;
    g_caseSeed = 0;
    int fails = leadcase(true) + leadcase(false);
    printf(fails ? "LEAD FAILED\n" : "LEAD OK\n");
    return fails ? 1 : 0;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: fuzzhost dll workdir seconds seed | --selftest | --lead | --replay seed\n");
        return 2;
    }
    setvbuf(stdout, NULL, _IONBF, 0);   // (Windows' _IOLBF is full buffering: logs stay empty)
    QueryPerformanceFrequency(&g_freq);
    wchar_t work[MAX_PATH];
    MultiByteToWideChar(CP_UTF8, 0, argv[2], -1, work, MAX_PATH);
    wchar_t dir[MAX_PATH];
    _snwprintf(dir, MAX_PATH, L"%ls\\OnionBoard", work);
    CreateDirectoryW(work, NULL);
    CreateDirectoryW(dir, NULL);
    _snwprintf(dir, MAX_PATH, L"%ls\\OnionBoard\\MicPlugin", work);
    CreateDirectoryW(dir, NULL);
    _snwprintf(g_ringPath, MAX_PATH, L"%ls\\ring2.bin", dir);
    SetEnvironmentVariableW(L"ProgramData", work);   // (before the effect first looks)
    SetUnhandledExceptionFilter(crashed);
    CreateThread(NULL, 0, watchdog, NULL, 0, NULL);
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { fprintf(stderr, "can't load %s\n", argv[1]); return 1; }
    GetClassObjectFn get = (GetClassObjectFn)(void (*)())GetProcAddress(dll, "DllGetClassObject");
    g_faultsFn = (FaultsFn)(void (*)())GetProcAddress(dll, "ObmicFuzzFaults");
    if (!get || FAILED(get(CLSID_OnionMic, IID_IClassFactory, (void **)&g_cf))) {
        fprintf(stderr, "no factory\n");
        return 1;
    }
    if (!g_faultsFn) printf("(not the fuzz build: faults the guard catches go uncounted)\n");
    if (!strcmp(argv[3], "--selftest")) return selftest();
    if (!strcmp(argv[3], "--lead")) return leadtest();
    if (!strcmp(argv[3], "--replay")) {
        uint64_t seed = argc > 4 ? strtoull(argv[4], NULL, 10) : 0;
        bool ok = runCase(seed, true);
        printf(ok ? "REPLAY OK\n" : "REPLAY FOUND SOMETHING\n");
        return ok ? 0 : 5;
    }
    double seconds = atof(argv[3]);
    uint64_t seed = argc > 4 ? strtoull(argv[4], NULL, 10) : 1;
    CreateThread(NULL, 0, hammer, NULL, 0, NULL);
    LARGE_INTEGER t0, t;
    QueryPerformanceCounter(&t0);
    double lastReport = 0;
    uint64_t cases = 0;
    uint64_t master = seed;
    for (;;) {
        QueryPerformanceCounter(&t);
        double el = (double)(t.QuadPart - t0.QuadPart) / g_freq.QuadPart;
        if (el >= seconds) break;
        if (el - lastReport >= 5.0) {
            lastReport = el;
            printf("progress: %.0f s, %llu cases, %llu blocks, %llu findings, slowest block %.0f us\n",
                   el, (unsigned long long)cases, (unsigned long long)g_blocks,
                   (unsigned long long)g_findings, g_maxCallUs);
        }
        g_rng = master;
        uint64_t caseSeed = rnd();
        master = g_rng;
        runCase(caseSeed, false);
        cases++;
        if (g_findings > 50) break;
    }
    printf("done: %llu cases, %llu blocks, %llu findings, slowest block %.0f us (case seed %llu)\n",
           (unsigned long long)cases, (unsigned long long)g_blocks, (unsigned long long)g_findings,
           g_maxCallUs, (unsigned long long)g_maxCallSeed);
    return g_findings ? 5 : 0;
}
