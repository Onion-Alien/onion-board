// Test host for obmic.dll: loads it the way the audio engine does (DllGetClassObject),
// locks it for a float32 format and runs APOProcess on fake mic blocks in real time,
// writing what comes out to a raw float32 file. Nothing on the PC's audio is touched.
// Set %ProgramData% to a test folder holding a ring.bin first.
//
//   testhost <obmic.dll> <out.f32> <rate> <channels> <seconds> [mic_level] [instances] [mic_hz]
//
// The fake mic is a constant `mic_level` (default 0 = a silent buffer), so whatever
// else is in the output came from the ring; or with `mic_hz`, a sine that loud
// (mic_hz < 0: noise, frame f = noise(f) as tests/test_directmic.py computes it).
// `instances` runs that many effects on the same mic (several apps recording it), each
// writing to out.f32, out.f32.1, out.f32.2...

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <mmreg.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <timeapi.h>
#include <math.h>

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

class MediaType : public IAudioMediaType {
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

// The audio engine aggregates every effect inside an object of its own; so does this.
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

struct Instance {
    IUnknown *inner = NULL;
    Outer outer;
    IAudioProcessingObject *apo = NULL;
    IAudioProcessingObjectRT *rt = NULL;
    IAudioProcessingObjectConfiguration *cfg = NULL;
    float *outbuf = NULL;
    FILE *file = NULL;
    int valid = 0;
};

static bool create(IClassFactory *cf, Instance &x) {
    if (FAILED(cf->CreateInstance(&x.outer, IID_IUnknown, (void **)&x.inner))) return false;
    x.outer.inner = x.inner;
    if (FAILED(x.outer.QueryInterface(IID_APO, (void **)&x.apo))) return false;
    x.apo->QueryInterface(IID_RT, (void **)&x.rt);
    x.apo->QueryInterface(IID_CFG, (void **)&x.cfg);
    return x.rt && x.cfg && SUCCEEDED(x.apo->Initialize(0, NULL));
}

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: testhost dll out rate channels seconds [mic_level] [instances]"
                        " [mic_hz]\n");
        return 2;
    }
    UINT32 rate = atoi(argv[3]), ch = atoi(argv[4]);
    double seconds = atof(argv[5]);
    float mic = argc > 6 ? (float)atof(argv[6]) : 0.0f;
    int count = argc > 7 ? atoi(argv[7]) : 1;
    double micHz = argc > 8 ? atof(argv[8]) : 0.0;
    if (count < 1 || count > 32) { fprintf(stderr, "1..32 instances\n"); return 2; }
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { fprintf(stderr, "can't load %s\n", argv[1]); return 1; }
    GetClassObjectFn get = (GetClassObjectFn)(void (*)())GetProcAddress(dll, "DllGetClassObject");
    IClassFactory *cf = NULL;
    if (!get || FAILED(get(CLSID_OnionMic, IID_IClassFactory, (void **)&cf))) { fprintf(stderr, "no factory\n"); return 1; }
    {
        IAudioProcessingObject *apo = NULL;
        Outer outer;
        if (FAILED(cf->CreateInstance(&outer, IID_APO, (void **)&apo)) == FALSE) {
            fprintf(stderr, "aggregated create must ask for IUnknown\n");
            return 1;
        }
    }
    Instance *xs = new Instance[count];
    MediaType mt(rate, ch);
    UINT32 block = rate / 100;
    float *inbuf = (float *)calloc(block * ch, sizeof(float));
    APO_CONNECTION_DESCRIPTOR din = {0, (UINT_PTR)inbuf, block, &mt, 0};
    for (int n = 0; n < count; n++) {
        if (!create(cf, xs[n])) { fprintf(stderr, "instance %d failed\n", n); return 1; }
        if (n == 0) {
            IAudioMediaType *sup = NULL;
            HRESULT hr = xs[0].apo->IsInputFormatSupported(NULL, &mt, &sup);
            printf("float format supported: 0x%08lx\n", (unsigned long)hr);
        }
        xs[n].outbuf = (float *)calloc(block * ch, sizeof(float));
        APO_CONNECTION_DESCRIPTOR dout = {0, (UINT_PTR)xs[n].outbuf, block, &mt, 0};
        APO_CONNECTION_DESCRIPTOR *pin = &din, *pout = &dout;
        if (FAILED(xs[n].cfg->LockForProcess(1, &pin, 1, &pout))) { fprintf(stderr, "lock failed\n"); return 1; }
        char name[600];
        if (n == 0) snprintf(name, sizeof name, "%s", argv[2]);
        else snprintf(name, sizeof name, "%s.%d", argv[2], n);
        xs[n].file = fopen(name, "wb");
    }
    int blocks = (int)(seconds * 100);
    LARGE_INTEGER freq, t0, t;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t0);
    timeBeginPeriod(1);
    uint64_t frame = 0;
    for (int b = 0; b < blocks; b++) {
        for (UINT32 i = 0; i < block; i++) {
            float v = mic;
            if (micHz > 0) {
                v = mic * (float)sin(2 * 3.14159265358979 * micHz * (double)(frame + i) / rate);
            } else if (micHz < 0) {   // noise: a known sequence (frame f is noise(f))
                uint32_t z = (uint32_t)(frame + i) * 2654435761u;
                z ^= z >> 15;
                z *= 2246822519u;
                z ^= z >> 13;
                v = mic * ((float)(z & 0xffff) / 32768.0f - 1.0f);
            }
            for (UINT32 c = 0; c < ch; c++) inbuf[i * ch + c] = v;
        }
        frame += block;
        // every app recording the mic gets the same block, one after another
        for (int n = 0; n < count; n++) {
            Instance &x = xs[n];
            for (UINT32 i = 0; i < block * ch; i++) x.outbuf[i] = 12345.0f;   // garbage
            APO_CONNECTION_PROPERTY in = {(UINT_PTR)inbuf, block, mic != 0.0f ? BUFFER_VALID : BUFFER_SILENT, 0};
            APO_CONNECTION_PROPERTY o = {(UINT_PTR)x.outbuf, 0, BUFFER_INVALID, 0};
            APO_CONNECTION_PROPERTY *pi = &in, *po = &o;
            x.rt->APOProcess(1, &pi, 1, &po);
            if (o.u32BufferFlags == BUFFER_SILENT) {   // the engine would read zeros
                for (UINT32 i = 0; i < block * ch; i++) x.outbuf[i] = 0.0f;
            } else {
                x.valid++;
            }
            fwrite(x.outbuf, sizeof(float), block * ch, x.file);
        }
        // real time: block b ends at (b + 1) * 10 ms
        for (;;) {
            QueryPerformanceCounter(&t);
            double el = (double)(t.QuadPart - t0.QuadPart) / freq.QuadPart;
            if (el >= (b + 1) * 0.01) break;
            Sleep(1);
        }
    }
    timeEndPeriod(1);
    for (int n = 0; n < count; n++) {
        Instance &x = xs[n];
        fclose(x.file);
        x.cfg->UnlockForProcess();
        printf("instance %d: blocks %d, with sound %d\n", n, blocks, x.valid);
        x.cfg->Release();
        x.rt->Release();
        x.apo->Release();
        x.inner->Release();   // the last reference: the effect deletes itself
    }
    printf("blocks %d, with sound %d\n", blocks, xs[0].valid);
    cf->Release();
    return 0;
}
