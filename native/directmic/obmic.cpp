// Onion Board mic.
//
// A Windows audio effect (an "APO", the same kind of effect Equalizer APO is) that
// Windows' audio engine (audiodg.exe) runs on one microphone, in front of every app
// that records it. Discord and games hear what Onion Board sends through the real mic:
// no virtual cable, nothing to pick in the voice app.
//
// Board <-> effect: a small shared file (soundboard/directmic.py has the layout).
//  - The effect publishes the clean mic (after the mic's own effect, before anything
//    of the board's) into a second ring. The board takes its mic from there, so its
//    meter, mic check and voice changer never hear its own sounds coming back, and it
//    runs on the mic's clock (each mic block in, one block of what others hear out).
//  - The board writes what others hear (48 kHz mono) into the main ring. MODE_REPLACE:
//    that is the board's whole send mix, your processed voice included (voice changer,
//    volume, gate, mute all work), and replaces the mic. MODE_ADD: only the sounds,
//    added on top of the mic. The board late with a block: the clean mic from the
//    moment that block was made from fills in (the voice goes on, no skip or repeat).
//    The board gone: the mic alone, crossfaded.
//  - Every app recording the mic runs its own instance; each has a slot in the file
//    with its own read position, so they never race.
//
// If the mic already had an effect from its driver (noise suppression, beam forming)
// in the slot this takes, the installer saves its CLSID and this effect loads it as a
// child and runs it first, so nothing the mic did before is lost.
//
// Rules for this file: it runs inside audiodg.exe, so a crash here silences every
// sound on the PC. APOProcess runs on a real-time thread: no locks, no allocation,
// no file or registry access there. Everything that touches the shared file runs
// through guarded() (a fault there, say a disk error paging the file in, puts the mic
// back as it was and rests the effect for a moment instead of taking audiodg down).
// native/directmic/fuzzhost.cpp hammers it with hostile files (scripts/fuzz_directmic.py).

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <mmreg.h>
#include <propsys.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <wchar.h>
#include <new>

// ------------------------------------------------------------------ APO definitions
// audioenginebaseapo.h isn't in MinGW's headers; these match the Windows SDK.

typedef LONGLONG HNSTIME;

typedef enum { BUFFER_INVALID = 0, BUFFER_VALID = 1, BUFFER_SILENT = 2 } APO_BUFFER_FLAGS;
typedef enum { APO_CONNECTION_BUFFER_TYPE_ALLOCATED = 0, APO_CONNECTION_BUFFER_TYPE_EXTERNAL = 1,
               APO_CONNECTION_BUFFER_TYPE_DEPENDANT = 2 } APO_CONNECTION_BUFFER_TYPE;
typedef enum { APO_FLAG_NONE = 0, APO_FLAG_INPLACE = 1, APO_FLAG_SAMPLESPERFRAME_MUST_MATCH = 2,
               APO_FLAG_FRAMESPERSECOND_MUST_MATCH = 4, APO_FLAG_BITSPERSAMPLE_MUST_MATCH = 8,
               APO_FLAG_DEFAULT = 14 } APO_FLAG;

struct UNCOMPRESSEDAUDIOFORMAT {
    GUID guidFormatType;
    UINT32 dwSamplesPerFrame;
    UINT32 dwBytesPerSampleContainer;
    UINT32 dwValidBitsPerSample;
    FLOAT fFramesPerSecond;
    UINT32 dwChannelMask;
};

struct APO_CONNECTION_PROPERTY {
    UINT_PTR pBuffer;
    UINT32 u32ValidFrameCount;
    APO_BUFFER_FLAGS u32BufferFlags;
    UINT32 u32Signature;
};

struct IAudioMediaType;

struct APO_CONNECTION_DESCRIPTOR {
    APO_CONNECTION_BUFFER_TYPE Type;
    UINT_PTR pBuffer;
    UINT32 u32MaxFrameCount;
    IAudioMediaType *pFormat;
    UINT32 u32Signature;
};

struct APO_REG_PROPERTIES {
    CLSID clsid;
    APO_FLAG Flags;
    WCHAR szFriendlyName[256];
    WCHAR szCopyrightInfo[256];
    UINT32 u32MajorVersion;
    UINT32 u32MinorVersion;
    UINT32 u32MinInputConnections;
    UINT32 u32MaxInputConnections;
    UINT32 u32MinOutputConnections;
    UINT32 u32MaxOutputConnections;
    UINT32 u32MaxInstances;
    UINT32 u32NumAPOInterfaces;
    IID iidAPOInterfaceList[1];
};

struct APOInitBaseStruct {
    UINT32 cbSize;
    CLSID clsid;
};

struct APOInitSystemEffects {
    APOInitBaseStruct APOInit;
    IPropertyStore *pAPOEndpointProperties;
    IPropertyStore *pAPOSystemEffectsProperties;
    void *pReserved;
    IUnknown *pDeviceCollection;
};

struct APOInitSystemEffects2 {
    APOInitBaseStruct APOInit;
    IPropertyStore *pAPOEndpointProperties;
    IPropertyStore *pAPOSystemEffectsProperties;
    void *pReserved;
    IUnknown *pDeviceCollection;
    UINT nSoftwareIoDeviceInCollection;
    UINT nSoftwareIoConnectorIndex;
    GUID AudioProcessingMode;
    BOOL InitializeForDiscoveryOnly;
};

struct IAudioMediaType : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE IsCompressedFormat(BOOL *pfCompressed) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsEqual(IAudioMediaType *pIAudioType, DWORD *pdwFlags) = 0;
    virtual const WAVEFORMATEX *STDMETHODCALLTYPE GetAudioFormat() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetUncompressedAudioFormat(UNCOMPRESSEDAUDIOFORMAT *p) = 0;
};

struct IAudioProcessingObjectRT : public IUnknown {
    virtual void STDMETHODCALLTYPE APOProcess(UINT32 nIn, APO_CONNECTION_PROPERTY **ppIn,
                                              UINT32 nOut, APO_CONNECTION_PROPERTY **ppOut) = 0;
    virtual UINT32 STDMETHODCALLTYPE CalcInputFrames(UINT32 u32OutputFrameCount) = 0;
    virtual UINT32 STDMETHODCALLTYPE CalcOutputFrames(UINT32 u32InputFrameCount) = 0;
};

struct IAudioProcessingObjectConfiguration : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE LockForProcess(UINT32 nIn, APO_CONNECTION_DESCRIPTOR **ppIn,
                                                     UINT32 nOut, APO_CONNECTION_DESCRIPTOR **ppOut) = 0;
    virtual HRESULT STDMETHODCALLTYPE UnlockForProcess() = 0;
};

struct IAudioProcessingObject : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE Reset() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetLatency(HNSTIME *pTime) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetRegistrationProperties(APO_REG_PROPERTIES **ppRegProps) = 0;
    virtual HRESULT STDMETHODCALLTYPE Initialize(UINT32 cbDataSize, BYTE *pbyData) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsInputFormatSupported(IAudioMediaType *pOpposite,
                                                             IAudioMediaType *pRequested,
                                                             IAudioMediaType **ppSupported) = 0;
    virtual HRESULT STDMETHODCALLTYPE IsOutputFormatSupported(IAudioMediaType *pOpposite,
                                                              IAudioMediaType *pRequested,
                                                              IAudioMediaType **ppSupported) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetInputChannelCount(UINT32 *pu32ChannelCount) = 0;
};

struct IAudioSystemEffects : public IUnknown {};

static const IID IID_IAudioMediaType_ =
    {0x4e997f73, 0xb71f, 0x4798, {0x87, 0x3b, 0xed, 0x7d, 0xfc, 0xf1, 0x5b, 0x4d}};
static const IID IID_IAudioProcessingObject_ =
    {0xfd7f2b29, 0x24d0, 0x4b5c, {0xb1, 0x77, 0x59, 0x2c, 0x39, 0xf9, 0xca, 0x10}};
static const IID IID_IAudioProcessingObjectRT_ =
    {0x9e1d6a6d, 0xddbc, 0x4e95, {0xa4, 0xc7, 0xad, 0x64, 0xba, 0x37, 0x84, 0x6c}};
static const IID IID_IAudioProcessingObjectConfiguration_ =
    {0x0e5ed805, 0xaba6, 0x49c3, {0x8f, 0x9a, 0x2b, 0x8c, 0x88, 0x9c, 0x4f, 0xa8}};
static const IID IID_IAudioSystemEffects_ =
    {0x5fa00f27, 0xadd6, 0x499a, {0x8a, 0x9d, 0x6b, 0x98, 0x52, 0x1f, 0xa7, 0x5b}};
static const GUID SUBTYPE_IEEE_FLOAT =
    {0x00000003, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};
// PKEY_AudioEndpoint_GUID: which endpoint (mic) this instance runs on
static const PROPERTYKEY PKEY_AudioEndpoint_GUID_ =
    {{0x1da5d803, 0xd492, 0x4edd, {0x8c, 0x23, 0xe0, 0xc0, 0xff, 0xee, 0x7f, 0x0e}}, 4};

#define APOERR_FORMAT_NOT_SUPPORTED ((HRESULT)0x88890003L)
#define APOERR_NOT_INITIALIZED ((HRESULT)0x88890002L)

// ------------------------------------------------------------------ this effect

// {C55E76FE-6667-4828-81FD-05B393FD649E} (soundboard/directmic.py CLSID)
static const CLSID CLSID_OnionMic =
    {0xc55e76fe, 0x6667, 0x4828, {0x81, 0xfd, 0x05, 0xb3, 0x93, 0xfd, 0x64, 0x9e}};
static const wchar_t *STATE_KEY = L"SOFTWARE\\OnionBoard\\MicPlugin\\Endpoints";
static const uint32_t EFFECT_VERSION = 4;        // directmic.EFFECT_VERSION

// The shared ring file. soundboard/directmic.py writes the same layout and documents it.
// Anyone signed in can write this file, so nothing read from it is trusted: sizes are
// taken once, when it's opened, positions are masked, samples are checked.
static const uint32_t RING_MAGIC = 0x434d424f;   // "OBMC"
static const uint32_t RING_VERSION = 2;
static const uint32_t HEADER_BYTES = 4096;
static const uint32_t SLOT_OFFSET = 256;
static const uint32_t SLOTS = 16;
static const uint64_t BOARD_STALE_MS = 200;      // board quiet this long: the mic alone
static const uint64_t SLOT_STALE_MS = 3000;      // a slot this quiet is free again
static const uint64_t PUBLISH_STALE_MS = 40;     // the mic's publisher went quiet: take over
static const double LEAD_DEFAULT_S = 0.02;       // how far behind the board to read
static const double LEAD_MAX_S = 0.12;
static const double LEAD_STEP_S = 0.005;         // added after each time the board was late
static const double FADE_S = 0.01;               // crossfade between the mic and the board
static const uint32_t SHRINK_AFTER = 200;        // blocks on time before the lead shrinks back
static const double SHRINK_MAX_S = 0.02;         // the most one quiet skip takes back
static const float QUIET = 0.004f;               // (-48 dBFS) a skip this quiet can't be heard
static const uint64_t POS_MAX = 1ull << 52;      // positions past this are junk (see process)
static const uint64_t FAULT_REST_MS = 1000;      // after a fault: the plain mic this long
// The board's 48 kHz into a mic at another rate: a windowed-sinc (Kaiser) low-pass and
// resampler, from a table made in LockForProcess. Linear interpolation folded the
// board's highs back down as noise on 44.1 / 16 kHz mics.
static const int PHASES = 128;                   // table rows (interpolated between)
static const double SINC_ATTEN_DB = 80.0;
static const double SINC_PASS = 0.9;             // of the lower Nyquist: passband edge
static const double PI_ = 3.14159265358979323846;

enum { MODE_ADD = 0, MODE_REPLACE = 1 };
enum { SLOT_REPLACING = 1, SLOT_PUBLISHING = 2 };

#pragma pack(push, 1)
struct Slot {                      // one per running instance (one per app recording the mic)
    volatile LONG owner;           // 0  0 = free
    volatile uint32_t rate;        // 4  this stream's rate
    volatile uint32_t channels;    // 8
    volatile uint32_t flags;       // 12 SLOT_*
    volatile uint64_t tick;        // 16 GetTickCount64 of its last block
    volatile uint64_t read_pos;    // 24 ring frames it has read
    volatile uint32_t lead;        // 32 ring frames it reads behind the board
    volatile uint32_t underruns;   // 36 times the board was late for it
    volatile uint64_t blocks;      // 40 blocks processed
    uint8_t pad[16];               // 48
};

struct RingHeader {                // offset
    uint32_t magic;                // 0
    uint32_t version;              // 4
    uint32_t rate;                 // 8   the board's rate (48000)
    uint32_t capacity;             // 12  frames in the ring (a power of two)
    volatile uint64_t write_pos;   // 16  frames written so far (board)
    volatile uint64_t board_tick;  // 24  GetTickCount64 of the board's last write
    volatile uint32_t enabled;     // 32  board: 1 = use the ring
    volatile uint32_t mode;        // 36  board: MODE_ADD / MODE_REPLACE
    volatile float gain;           // 40  board: gain on what the board sends
    volatile float mic_gain;       // 44  board, MODE_ADD: the mic's own level (0 = muted)
    uint32_t mic_capacity;         // 48  frames in the clean-mic ring (a power of two)
    volatile LONG publisher;       // 52  owner of the slot publishing the mic
    volatile uint64_t mic_write_pos;  // 56  clean-mic frames written (effect)
    volatile uint32_t mic_rate;    // 64  the clean mic's rate
    volatile uint32_t lead;        // 68  board: frames to read behind it (0 = default)
    volatile uint64_t mic_tick;    // 72  GetTickCount64 of the last clean-mic block
    volatile uint32_t effect_version;  // 80  EFFECT_VERSION of the running effect
    uint32_t board_pid;            // 84  the board writing (another board backs off)
    // board: ring frame sync_wp is its audio for clean-mic frame sync_mic (both 0: none).
    // sync_seq is odd while the board changes them.
    volatile uint32_t sync_seq;    // 88
    uint32_t pad1;                 // 92
    volatile uint64_t sync_wp;     // 96
    volatile uint64_t sync_mic;    // 104
};
#pragma pack(pop)

static HMODULE g_module;
static volatile LONG g_objects;
static volatile LONG g_locks;
static volatile LONG g_ids;
static wchar_t g_dataDir[MAX_PATH];

static void initDataDir() {
    if (g_dataDir[0]) return;
    wchar_t base[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"ProgramData", base, MAX_PATH);
    if (!n || n >= MAX_PATH) wcscpy(base, L"C:\\ProgramData");
    _snwprintf(g_dataDir, MAX_PATH, L"%ls\\OnionBoard\\MicPlugin", base);
    g_dataDir[MAX_PATH - 1] = 0;
}

// Windows' Application event log, source "Onion Board mic": for problems only.
static void eventLog(const char *msg, WORD type = EVENTLOG_INFORMATION_TYPE) {
    HANDLE ev = RegisterEventSourceA(NULL, "Onion Board mic");
    if (!ev) return;
    ReportEventA(ev, type, 0, 1, NULL, 1, 0, &msg, NULL);
    DeregisterEventSource(ev);
}

// Rate limit: the audio engine creates and tests effects in bursts (dozens a second
// while devices change), so at most LOG_BURST lines per LOG_WINDOW_MS get through.
static const LONG LOG_BURST = 40;
static const uint64_t LOG_WINDOW_MS = 10000;
static volatile LONG g_logCount;
static volatile LONG g_logSkipped;
static volatile uint64_t g_logWindow;

// Log to %ProgramData%\OnionBoard\MicPlugin\apo.log; problems also go to the event log.
// Never from APOProcess.
static void logv(bool problem, const char *fmt, va_list ap) {
    uint64_t now = GetTickCount64();
    if (now - g_logWindow > LOG_WINDOW_MS) {
        g_logWindow = now;
        g_logCount = 0;
    }
    LONG skipped = 0;
    if (InterlockedIncrement(&g_logCount) > LOG_BURST) {
        InterlockedIncrement(&g_logSkipped);
        if (!problem) return;
    } else {
        skipped = InterlockedExchange(&g_logSkipped, 0);
    }
    initDataDir();
    char buf[700];
    SYSTEMTIME t;
    GetSystemTime(&t);
    int k = snprintf(buf, sizeof buf, "%04d-%02d-%02d %02d:%02d:%02d pid %lu: ", t.wYear,
                     t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, GetCurrentProcessId());
    if (skipped) k += snprintf(buf + k, sizeof buf - k, "(%ld lines skipped) ", skipped);
    k += vsnprintf(buf + k, sizeof buf - k - 2, fmt, ap);
    if (k > (int)sizeof buf - 3) k = sizeof buf - 3;
    if (k < 0) k = 0;
    buf[k] = 0;
    if (problem) eventLog(buf, EVENTLOG_WARNING_TYPE);
    wchar_t path[MAX_PATH];
    _snwprintf(path, MAX_PATH, L"%ls\\apo.log", g_dataDir);
    path[MAX_PATH - 1] = 0;
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    LARGE_INTEGER size;
    if (h != INVALID_HANDLE_VALUE && GetFileSizeEx(h, &size) && size.QuadPart > (256 << 10)) {
        CloseHandle(h);   // keep it small
        h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    }
    if (h == INVALID_HANDLE_VALUE) return;
    buf[k++] = '\r';
    buf[k++] = '\n';
    DWORD w;
    WriteFile(h, buf, k, &w, NULL);
    CloseHandle(h);
}

static void logf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    logv(false, fmt, ap);
    va_end(ap);
}

static void problemf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    logv(true, fmt, ap);
    va_end(ap);
}

static bool isFloat32(const WAVEFORMATEX *f) {
    if (!f || f->wBitsPerSample != 32) return false;
    if (f->wFormatTag == WAVE_FORMAT_IEEE_FLOAT) return true;
    if (f->wFormatTag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22) {
        const WAVEFORMATEXTENSIBLE *x = (const WAVEFORMATEXTENSIBLE *)f;
        return IsEqualGUID(x->SubFormat, SUBTYPE_IEEE_FLOAT);
    }
    return false;
}

static inline float clean(float x) {   // NaN / inf / out of range from the ring: tamed
    if (!(x == x)) return 0.0f;
    return x > 1.0f ? 1.0f : x < -1.0f ? -1.0f : x;
}

// ------------------------------------------------------------------ the guard
// guarded(fn, ctx) runs fn(ctx) and returns false, instead of crashing audiodg, if it
// faults: a __try / __except, which g++ hasn't got, built the way the compiler would.
// The SEH scope table names the call's range and obmicGuardFilter as its filter; the
// system's __C_specific_handler unwinds to .l_obguard_end on a fault, right after the
// call, the same as a return from it (the guarded range holds nothing else). Only
// faults the shared file can cause are caught; anything else stays fatal, as before.

static volatile LONG g_faults;              // faults caught (all instances)
static volatile DWORD g_faultCode;          // the last one's exception code
static void *volatile g_faultAddr;          // and where

extern "C" __attribute__((used)) LONG obmicGuardFilter(EXCEPTION_POINTERS *ep, void *) {
    DWORD code = ep && ep->ExceptionRecord ? ep->ExceptionRecord->ExceptionCode : 0;
    switch (code) {
    case EXCEPTION_ACCESS_VIOLATION:
    case EXCEPTION_IN_PAGE_ERROR:           // the file couldn't be paged in (disk full...)
    case EXCEPTION_ARRAY_BOUNDS_EXCEEDED:
    case EXCEPTION_DATATYPE_MISALIGNMENT:
    case EXCEPTION_ILLEGAL_INSTRUCTION:     // (the fuzz build's sanitizer traps)
    case EXCEPTION_INT_DIVIDE_BY_ZERO:
    case EXCEPTION_INT_OVERFLOW:
    case EXCEPTION_FLT_DENORMAL_OPERAND:
    case EXCEPTION_FLT_DIVIDE_BY_ZERO:
    case EXCEPTION_FLT_INEXACT_RESULT:
    case EXCEPTION_FLT_INVALID_OPERATION:
    case EXCEPTION_FLT_OVERFLOW:
    case EXCEPTION_FLT_STACK_CHECK:
    case EXCEPTION_FLT_UNDERFLOW:
        g_faultCode = code;
        g_faultAddr = ep->ExceptionRecord->ExceptionAddress;
        InterlockedIncrement(&g_faults);
        return EXCEPTION_EXECUTE_HANDLER;
    default:
        return EXCEPTION_CONTINUE_SEARCH;
    }
}

#if defined(__x86_64__) && defined(__SEH__)
__attribute__((noinline)) static bool guarded(void (*fn)(void *), void *ctx) {
    volatile int ok = 0;
    __asm__ __volatile__(".l_obguard_start:\n"
                         "\t.seh_handler __C_specific_handler, @except\n"
                         "\t.seh_handlerdata\n"
                         "\t.long 1\n"
                         "\t.rva .l_obguard_start, .l_obguard_end, obmicGuardFilter, .l_obguard_end\n"
                         "\t.text\n" ::: "memory");
    fn(ctx);
    ok = 1;
    __asm__ __volatile__("\tnop\n.l_obguard_end:\n\tnop\n" ::: "memory");
    return ok;
}
#else
#error "obmic needs x86-64 SEH (MinGW-w64 x86_64 g++)"
#endif

#ifdef OBMIC_FUZZ
// fuzz build only (scripts/fuzz_directmic.py): how many faults the guard caught
extern "C" __declspec(dllexport) LONG ObmicFuzzFaults(DWORD *code, void **addr) {
    if (code) *code = g_faultCode;
    if (addr) *addr = g_faultAddr;
    return g_faults;
}
#endif

static double besselI0(double x) {
    double sum = 1.0, term = 1.0;
    for (int k = 1; k < 64; k++) {
        term *= (x / (2.0 * k)) * (x / (2.0 * k));
        sum += term;
        if (term < sum * 1e-12) break;
    }
    return sum;
}

class OnionMicAPO : public IAudioProcessingObject,
                    public IAudioProcessingObjectRT,
                    public IAudioProcessingObjectConfiguration,
                    public IAudioSystemEffects {
public:
    // The audio engine aggregates every effect inside an object of its own (COM
    // aggregation): the interfaces' IUnknown then forwards to that outer object, and
    // only `inner` (returned by CreateInstance) owns this one's lifetime.
    struct Inner : public IUnknown {
        OnionMicAPO *self;
        HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
            return self->innerQuery(riid, ppv);
        }
        ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&self->m_ref); }
        ULONG STDMETHODCALLTYPE Release() override {
            LONG r = InterlockedDecrement(&self->m_ref);
            if (r == 0) delete self;
            return r;
        }
    };

    explicit OnionMicAPO(IUnknown *outer) {
        InterlockedIncrement(&g_objects);
        m_inner.self = this;
        m_outer = outer ? outer : &m_inner;
        m_id = (LONG)((GetCurrentProcessId() << 12) ^ (DWORD)InterlockedIncrement(&g_ids));
        if (!m_id) m_id = 1;
    }
    IUnknown *inner() { return &m_inner; }

    HRESULT innerQuery(REFIID riid, void **ppv) {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown))
            *ppv = &m_inner;
        else if (IsEqualIID(riid, IID_IAudioProcessingObject_))
            *ppv = static_cast<IAudioProcessingObject *>(this);
        else if (IsEqualIID(riid, IID_IAudioProcessingObjectRT_))
            *ppv = static_cast<IAudioProcessingObjectRT *>(this);
        else if (IsEqualIID(riid, IID_IAudioProcessingObjectConfiguration_))
            *ppv = static_cast<IAudioProcessingObjectConfiguration *>(this);
        else if (IsEqualIID(riid, IID_IAudioSystemEffects_))
            *ppv = static_cast<IAudioSystemEffects *>(this);
        else {
            *ppv = NULL;
            return E_NOINTERFACE;
        }
        static_cast<IUnknown *>(*ppv)->AddRef();
        return S_OK;
    }

    // IUnknown of every interface: the outer object's (or `inner` when not aggregated)
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
        return m_outer->QueryInterface(riid, ppv);
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return m_outer->AddRef(); }
    ULONG STDMETHODCALLTYPE Release() override { return m_outer->Release(); }

    // IAudioProcessingObject
    HRESULT STDMETHODCALLTYPE Reset() override {
        m_synced = false;
        m_played = false;
        return m_child ? m_child->Reset() : S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetLatency(HNSTIME *pTime) override {
        if (!pTime) return E_POINTER;
        if (m_child) return m_child->GetLatency(pTime);
        *pTime = 0;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetRegistrationProperties(APO_REG_PROPERTIES **pp) override {
        if (!pp) return E_POINTER;
        APO_REG_PROPERTIES *p = (APO_REG_PROPERTIES *)CoTaskMemAlloc(sizeof(APO_REG_PROPERTIES));
        if (!p) return E_OUTOFMEMORY;
        memset(p, 0, sizeof *p);
        p->clsid = CLSID_OnionMic;
        p->Flags = APO_FLAG_DEFAULT;
        wcscpy(p->szFriendlyName, L"Onion Board mic");
        wcscpy(p->szCopyrightInfo, L"Onion Board contributors");
        p->u32MajorVersion = 1;
        p->u32MinInputConnections = p->u32MaxInputConnections = 1;
        p->u32MinOutputConnections = p->u32MaxOutputConnections = 1;
        p->u32MaxInstances = 0xffffffff;
        p->u32NumAPOInterfaces = 1;
        p->iidAPOInterfaceList[0] = IID_IAudioProcessingObject_;
        *pp = p;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE Initialize(UINT32 cb, BYTE *data) override {
        bool discovery = false;
        wchar_t endpoint[64] = L"";
        if (data && cb >= sizeof(APOInitSystemEffects)) {
            APOInitSystemEffects *init = (APOInitSystemEffects *)data;
            if (cb >= sizeof(APOInitSystemEffects2))
                discovery = ((APOInitSystemEffects2 *)data)->InitializeForDiscoveryOnly != FALSE;
            if (init->pAPOEndpointProperties) {
                PROPVARIANT v;
                PropVariantInit(&v);
                if (SUCCEEDED(init->pAPOEndpointProperties->GetValue(PKEY_AudioEndpoint_GUID_, &v))
                        && v.vt == VT_LPWSTR && v.pwszVal) {
                    wcsncpy(endpoint, v.pwszVal, 63);
                    endpoint[63] = 0;
                }
                PropVariantClear(&v);
            }
            loadChild(endpoint, cb, data);
        }
        logf("initialize: endpoint %ls, %u bytes, discovery %d, child %s", endpoint, cb,
             (int)discovery, m_child ? "yes" : "no");
        if (!discovery && !m_ring && !guarded([](void *p) { ((OnionMicAPO *)p)->openRing(); }, this)) {
            problemf("the ring file faulted while opening (0x%08lx): the mic as it is",
                     (unsigned long)g_faultCode);
            m_ring = NULL;
        }
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE IsInputFormatSupported(IAudioMediaType *opp, IAudioMediaType *req,
                                                     IAudioMediaType **out) override {
        if (m_child) return m_child->IsInputFormatSupported(opp, req, out);
        return sameFormat(opp, req, out);
    }
    HRESULT STDMETHODCALLTYPE IsOutputFormatSupported(IAudioMediaType *opp, IAudioMediaType *req,
                                                      IAudioMediaType **out) override {
        if (m_child) return m_child->IsOutputFormatSupported(opp, req, out);
        return sameFormat(opp, req, out);
    }
    HRESULT STDMETHODCALLTYPE GetInputChannelCount(UINT32 *n) override {
        if (!n) return E_POINTER;
        if (m_child) return m_child->GetInputChannelCount(n);
        *n = m_channels;
        return S_OK;
    }

    // IAudioProcessingObjectConfiguration
    HRESULT STDMETHODCALLTYPE LockForProcess(UINT32 nIn, APO_CONNECTION_DESCRIPTOR **in,
                                             UINT32 nOut, APO_CONNECTION_DESCRIPTOR **out) override {
        if (nIn < 1 || nOut < 1 || !in || !out || !in[0] || !out[0]) return E_INVALIDARG;
        if (m_childConfig) {
            HRESULT hr = m_childConfig->LockForProcess(nIn, in, nOut, out);
            if (FAILED(hr)) {
                problemf("the mic's own effect failed to lock: 0x%08lx", (unsigned long)hr);
                return hr;
            }
        }
        const WAVEFORMATEX *f = out[0]->pFormat ? out[0]->pFormat->GetAudioFormat() : NULL;
        m_float = isFloat32(f);
        m_channels = f ? f->nChannels : 0;
        m_rate = f ? f->nSamplesPerSec : 0;
        m_synced = false;
        m_played = false;
        m_locked = true;
        m_w = 0.0f;
        m_mg = 1.0f;
        m_b = 1.0f;
        m_owe = 0;
        m_okBlocks = 0;
        m_restUntil = 0;
        if (m_snap) HeapFree(GetProcessHeap(), 0, m_snap);
        m_snap = NULL;
        m_snapFrames = 0;
        if (m_ring && m_rate && m_channels && m_channels <= 64) {
            // a copy of each block as it came in, to put back if processing faults
            UINT32 maxFrames = out[0]->u32MaxFrameCount;
            m_snap = (float *)HeapAlloc(GetProcessHeap(), 0,
                                        (size_t)maxFrames * m_channels * sizeof(float));
            if (m_snap) m_snapFrames = maxFrames;
        }
        if (m_ring && m_rate) makeKernel();
        if (m_ring && m_rate) {
            double lead = LEAD_DEFAULT_S * m_boardRate;
            m_leadBase = lead;
            m_lead = lead;
            if (!guarded([](void *p) { ((OnionMicAPO *)p)->claimSlot(); }, this)) {
                problemf("the ring file faulted (0x%08lx): no slot", (unsigned long)g_faultCode);
                m_slot = NULL;
            }
        }
        if (m_faults) {
            problemf("%ld faults reading the ring file were caught (last 0x%08lx at %p)",
                     (long)m_faults, (unsigned long)g_faultCode, g_faultAddr);
            m_faults = 0;
        }
        logf("lock: %u Hz, %u ch, float %d, max %u frames, ring %s, slot %d, resampler %d taps",
             m_rate, m_channels, (int)m_float, out[0]->u32MaxFrameCount,
             m_ring ? "open" : "missing", m_slot ? (int)(m_slot - slots()) : -1, 2 * m_half);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE UnlockForProcess() override {
        m_locked = false;
        releaseSlotGuarded();
        if (m_faults)
            problemf("%ld faults reading the ring file were caught (last 0x%08lx at %p)",
                     (long)m_faults, (unsigned long)g_faultCode, g_faultAddr);
        m_faults = 0;
        logf("unlock");
        return m_childConfig ? m_childConfig->UnlockForProcess() : S_OK;
    }

    // IAudioProcessingObjectRT (real-time: no locks, allocation, files or registry)
    void STDMETHODCALLTYPE APOProcess(UINT32 nIn, APO_CONNECTION_PROPERTY **in, UINT32 nOut,
                                      APO_CONNECTION_PROPERTY **out) override {
        if (m_childRT) {
            m_childRT->APOProcess(nIn, in, nOut, out);
        } else if (nIn >= 1 && nOut >= 1) {
            APO_CONNECTION_PROPERTY *i = in[0], *o = out[0];
            if (o->pBuffer != i->pBuffer && i->u32BufferFlags == BUFFER_VALID)
                memcpy((void *)o->pBuffer, (const void *)i->pBuffer,
                       (size_t)i->u32ValidFrameCount * m_channels * sizeof(float));
            o->u32ValidFrameCount = i->u32ValidFrameCount;
            o->u32BufferFlags = i->u32BufferFlags;
        }
        if (nOut >= 1 && m_float && m_ring && m_channels && m_rate)
            processGuarded(out[0]);
    }
    UINT32 STDMETHODCALLTYPE CalcInputFrames(UINT32 n) override {
        return m_childRT ? m_childRT->CalcInputFrames(n) : n;
    }
    UINT32 STDMETHODCALLTYPE CalcOutputFrames(UINT32 n) override {
        return m_childRT ? m_childRT->CalcOutputFrames(n) : n;
    }

private:
    virtual ~OnionMicAPO() {
        releaseSlotGuarded();
        if (m_childConfig) m_childConfig->Release();
        if (m_childRT) m_childRT->Release();
        if (m_child) m_child->Release();
        if (m_kernel) HeapFree(GetProcessHeap(), 0, m_kernel);
        if (m_snap) HeapFree(GetProcessHeap(), 0, m_snap);
        if (m_view) UnmapViewOfFile(m_view);
        if (m_map) CloseHandle(m_map);
        if (m_file != INVALID_HANDLE_VALUE) CloseHandle(m_file);
        InterlockedDecrement(&g_objects);
    }

    // No child: in = out, float32 only (the audio engine runs effects in float).
    HRESULT sameFormat(IAudioMediaType *opp, IAudioMediaType *req, IAudioMediaType **out) {
        if (!req || !out) return E_POINTER;
        *out = NULL;
        const WAVEFORMATEX *rf = req->GetAudioFormat();
        logf("format asked: tag %u, %u Hz, %u ch, %u bits (other side %s)",
             rf ? rf->wFormatTag : 0, rf ? (unsigned)rf->nSamplesPerSec : 0,
             rf ? rf->nChannels : 0, rf ? rf->wBitsPerSample : 0, opp ? "set" : "none");
        if (!isFloat32(rf)) return APOERR_FORMAT_NOT_SUPPORTED;
        if (opp) {   // must match the other side: same rate and channels
            const WAVEFORMATEX *a = opp->GetAudioFormat(), *b = req->GetAudioFormat();
            if (a && (a->nSamplesPerSec != b->nSamplesPerSec || a->nChannels != b->nChannels)) {
                opp->AddRef();
                *out = opp;
                return S_FALSE;
            }
        }
        req->AddRef();
        *out = req;
        return S_OK;
    }

    // The mic's own effect, saved by the installer under STATE_KEY\<endpoint>\Original.
    void loadChild(const wchar_t *endpoint, UINT32 cb, BYTE *data) {
        if (!endpoint[0] || m_child) return;
        wchar_t key[256], value[64];
        _snwprintf(key, 256, L"%ls\\%ls", STATE_KEY, endpoint);
        key[255] = 0;
        DWORD size = sizeof value;
        if (RegGetValueW(HKEY_LOCAL_MACHINE, key, L"Original", RRF_RT_REG_SZ, NULL, value, &size)
                != ERROR_SUCCESS || !value[0])
            return;
        CLSID clsid;
        if (FAILED(CLSIDFromString(value, &clsid)) || IsEqualCLSID(clsid, CLSID_OnionMic)) return;
        IAudioProcessingObject *child = NULL;
        HRESULT hr = CoCreateInstance(clsid, NULL, CLSCTX_INPROC_SERVER, IID_IAudioProcessingObject_,
                                      (void **)&child);
        if (FAILED(hr) || !child) {
            problemf("can't load the mic's own effect %ls: 0x%08lx", value, (unsigned long)hr);
            return;
        }
        BYTE *copy = (BYTE *)CoTaskMemAlloc(cb);
        if (!copy) {
            child->Release();
            return;
        }
        memcpy(copy, data, cb);
        ((APOInitBaseStruct *)copy)->clsid = clsid;
        hr = child->Initialize(cb, copy);
        CoTaskMemFree(copy);
        if (FAILED(hr)) {
            problemf("the mic's own effect %ls failed to start: 0x%08lx", value, (unsigned long)hr);
            child->Release();
            return;
        }
        if (FAILED(child->QueryInterface(IID_IAudioProcessingObjectRT_, (void **)&m_childRT)) ||
            FAILED(child->QueryInterface(IID_IAudioProcessingObjectConfiguration_,
                                         (void **)&m_childConfig))) {
            if (m_childRT) m_childRT->Release();
            m_childRT = NULL;
            m_childConfig = NULL;
            child->Release();
            return;
        }
        m_child = child;
    }

    // The resampler's table: PHASES + 1 rows of 2 * m_half taps. Row p, tap j weighs ring
    // frame k - m_half + 1 + j for a position k + p / PHASES (then delayed by m_half).
    // Same rate: no table (whole positions read the ring as it is).
    void makeKernel() {
        if (m_kernel) HeapFree(GetProcessHeap(), 0, m_kernel);
        m_kernel = NULL;
        m_half = 0;
        if (m_rate == m_boardRate) return;
        double r = m_rate < m_boardRate ? (double)m_rate / m_boardRate : 1.0;
        double fc = 0.5 * r * (1.0 + SINC_PASS) / 2.0;      // cutoff mid-transition
        double df = 0.5 * r * (1.0 - SINC_PASS);            // transition width
        double beta = 0.1102 * (SINC_ATTEN_DB - 8.7);
        int taps = (int)ceil((SINC_ATTEN_DB - 8.0) / (2.285 * 2.0 * PI_ * df)) + 1;
        int half = (taps + 1) / 2;
        if (half < 4) half = 4;
        if (half > 512) half = 512;
        size_t n = (size_t)(PHASES + 1) * 2 * half;
        float *k = (float *)HeapAlloc(GetProcessHeap(), 0, n * sizeof(float));
        if (!k) {
            problemf("no memory for the resampler: linear instead");
            return;
        }
        double i0b = besselI0(beta);
        for (int p = 0; p <= PHASES; p++) {
            float *row = k + (size_t)p * 2 * half;
            double sum = 0.0;
            for (int j = 0; j < 2 * half; j++) {
                double t = (double)(j - half + 1) - (double)p / PHASES;
                double u = t / half;
                double w = u * u < 1.0 ? besselI0(beta * sqrt(1.0 - u * u)) / i0b : 0.0;
                double x = 2.0 * fc * t;
                double sinc = fabs(x) < 1e-9 ? 1.0 : sin(PI_ * x) / (PI_ * x);
                row[j] = (float)(2.0 * fc * sinc * w);
                sum += row[j];
            }
            for (int j = 0; j < 2 * half; j++) row[j] = (float)(row[j] / sum);   // DC: 1
        }
        m_kernel = k;
        m_half = half;
    }

    // The board's audio at ring position `pos` (in ring frames, fractional).
    inline float sample(double pos) const {
        if (m_kernel) {
            double x = pos - m_half;
            double fk = floor(x);
            uint64_t k = (uint64_t)(int64_t)fk;
            float pf = (float)(x - fk) * PHASES;
            int pi = (int)pf;
            if (pi >= PHASES) pi = PHASES - 1;
            if (pi < 0) pi = 0;
            float fr = pf - (float)pi;
            const float *a = m_kernel + (size_t)pi * 2 * m_half, *b = a + 2 * m_half;
            uint64_t first = k - (uint64_t)m_half + 1;
            float acc = 0.0f;
            for (int j = 0; j < 2 * m_half; j++)
                acc += m_data[(first + j) & m_mask] * (a[j] + (b[j] - a[j]) * fr);
            return clean(acc);
        }
        uint64_t k = (uint64_t)pos;
        float f = (float)(pos - (double)k);
        float a = clean(m_data[k & m_mask]), b = clean(m_data[(k + 1) & m_mask]);
        return a + (b - a) * f;
    }

    // Peak of the board's audio over ring frames [from, from + n).
    float peakOf(double from, uint32_t n) const {
        uint64_t k = (uint64_t)(int64_t)floor(from);
        float pk = 0.0f;
        for (uint32_t i = 0; i < n; i++) {
            float v = fabsf(clean(m_data[(k + i) & m_mask]));
            if (v > pk) pk = v;
        }
        return pk;
    }

    // The board's sync pair (RingHeader.sync_*), read only while the board isn't changing
    // it: the last good one is kept meanwhile.
    void readSync() {
        RingHeader *h = m_ring;
        uint32_t a = h->sync_seq;
        if (a & 1) return;
        MemoryBarrier();
        uint64_t wp = h->sync_wp, mic = h->sync_mic;
        MemoryBarrier();
        if (h->sync_seq != a) return;
        // (past POS_MAX it's junk: the doubles below would stop counting)
        m_syncOk = (wp != 0 || mic != 0) && wp <= POS_MAX && mic <= POS_MAX;
        m_syncWp = wp;
        m_syncMic = mic;
    }

    // The clean-mic frame (fractional) the board's audio at ring position `pos` was made
    // from (the resampler's delay included: sample(pos) plays ring frame pos - m_half).
    inline double micFrame(double pos) const {
        return (double)m_syncMic + (pos - (double)m_half - (double)m_syncWp) * m_micStep;
    }

    // The clean mic (both channels averaged, as the board's mono) at mic frame `m`.
    inline float micAt(double m) const {
        double fk = floor(m);
        uint64_t k = (uint64_t)(int64_t)fk;
        float f = (float)(m - fk);
        const float *a = m_mic + (size_t)(k & m_micMask) * 2;
        const float *b = m_mic + (size_t)((k + 1) & m_micMask) * 2;
        float x0 = 0.5f * (clean(a[0]) + clean(a[1])), x1 = 0.5f * (clean(b[0]) + clean(b[1]));
        return x0 + (x1 - x0) * f;
    }

    void openRing() {
        if (m_ring) return;
        initDataDir();
        wchar_t path[MAX_PATH];
        _snwprintf(path, MAX_PATH, L"%ls\\ring2.bin", g_dataDir);
        path[MAX_PATH - 1] = 0;
        m_file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                             OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (m_file == INVALID_HANDLE_VALUE) {
            problemf("can't open %ls: error %lu", path, GetLastError());
            return;
        }
        LARGE_INTEGER size;
        if (!GetFileSizeEx(m_file, &size) || size.QuadPart < HEADER_BYTES) {
            problemf("ring file too small");
            return;
        }
        m_map = CreateFileMappingW(m_file, NULL, PAGE_READWRITE, 0, 0, NULL);
        if (!m_map) {
            problemf("can't map the ring: error %lu", GetLastError());
            return;
        }
        RingHeader *h = (RingHeader *)MapViewOfFile(m_map, FILE_MAP_ALL_ACCESS, 0, 0, 0);
        if (!h) {
            problemf("can't view the ring: error %lu", GetLastError());
            return;
        }
        m_view = h;   // (unmapped by the destructor, also if reading it faults below)
        // How much is really mapped: the file can change size between GetFileSizeEx and
        // CreateFileMapping (anyone signed in can write it), and the view is what counts.
        MEMORY_BASIC_INFORMATION mbi;
        uint64_t mapped = 0;
        if (VirtualQuery(h, &mbi, sizeof mbi) == sizeof mbi && mbi.BaseAddress == (void *)h)
            mapped = mbi.RegionSize;
        if ((uint64_t)size.QuadPart < mapped) mapped = (uint64_t)size.QuadPart;
        if (mapped < HEADER_BYTES) {
            problemf("ring file too small once mapped");
            return;
        }
        // Sizes are read once, here (volatile: the compiler can't fetch them again after
        // the checks): what's in the file later can't move them.
        const volatile RingHeader *vh = h;
        uint32_t magic = vh->magic, version = vh->version;
        uint32_t cap = vh->capacity, mcap = vh->mic_capacity, rate = vh->rate;
        uint64_t need = HEADER_BYTES + (uint64_t)cap * sizeof(float) +
                        (uint64_t)mcap * 2 * sizeof(float);
        if (magic != RING_MAGIC || version != RING_VERSION || !cap || (cap & (cap - 1)) ||
                !mcap || (mcap & (mcap - 1)) || cap > (1u << 22) || mcap > (1u << 22) ||
                mapped < need || rate < 8000 || rate > 384000) {
            problemf("ring file has the wrong layout (version %u)", version);
            return;
        }
        m_ring = h;
        m_data = (const float *)((const BYTE *)h + HEADER_BYTES);
        m_mask = cap - 1;
        m_mic = (float *)((BYTE *)h + HEADER_BYTES + (size_t)cap * sizeof(float));
        m_micMask = mcap - 1;
        m_boardRate = rate;
        h->effect_version = EFFECT_VERSION;
    }

    Slot *slots() { return (Slot *)((BYTE *)m_ring + SLOT_OFFSET); }

    void claimSlot(bool realtime = false) {
        if (m_slot || !m_ring) return;
        uint64_t now = GetTickCount64();
        Slot *s = slots();
        for (int pass = 0; pass < 2 && !m_slot; pass++) {
            for (uint32_t i = 0; i < SLOTS; i++) {
                LONG cur = s[i].owner;
                bool free = cur == 0 || (pass == 1 && now - s[i].tick > SLOT_STALE_MS);
                if (!free) continue;
                if (InterlockedCompareExchange(&s[i].owner, m_id, cur) == cur) {
                    m_slot = &s[i];
                    break;
                }
            }
        }
        if (!m_slot) {
            if (!realtime) problemf("no free slot in the ring (%u apps already)", SLOTS);
            return;
        }
        m_slot->tick = now;
        m_slot->rate = m_rate;
        m_slot->channels = m_channels;
        m_slot->flags = 0;
        m_slot->underruns = 0;
        m_slot->blocks = 0;
        m_slot->lead = (uint32_t)m_lead;
    }

    void releaseSlot() {
        if (!m_slot) return;
        InterlockedCompareExchange(&m_ring->publisher, 0, m_id);
        m_slot->flags = 0;
        InterlockedCompareExchange(&m_slot->owner, 0, m_id);
        m_slot = NULL;
    }

    void releaseSlotGuarded() {
        if (m_slot && !guarded([](void *p) { ((OnionMicAPO *)p)->releaseSlot(); }, this))
            m_slot = NULL;
    }

    // The header still as it was opened: the board only ever replaces the file with a
    // new one (this keeps the old one mapped), so a changed layout here is junk.
    bool headerOk() const {
        const volatile RingHeader *h = m_ring;
        return h->magic == RING_MAGIC && h->version == RING_VERSION &&
               h->capacity == m_mask + 1 && h->mic_capacity == m_micMask + 1 &&
               h->rate == m_boardRate;
    }

    // Back to the plain mic with nothing half done: the next good block starts afresh.
    void standDown() {
        m_synced = false;
        m_played = false;
        m_late = false;
        m_w = 0.0f;
        m_mg = 1.0f;
        m_b = 1.0f;
        m_owe = 0;
        m_okBlocks = 0;
        m_lead = m_leadBase;
    }

    struct ProcessCall { OnionMicAPO *self; APO_CONNECTION_PROPERTY *o; };

    // process() under the guard: if it faults, the block goes back to what came in (the
    // mic as it is) and the effect rests FAULT_REST_MS before it trusts the file again.
    void processGuarded(APO_CONNECTION_PROPERTY *o) {
        uint64_t now = GetTickCount64();
        if (m_restUntil && now < m_restUntil) return;   // resting: the mic as it is
        m_restUntil = 0;
        UINT32 frames = o->u32ValidFrameCount;
        if (!m_snap || frames > m_snapFrames || !o->pBuffer) return;   // can't undo it
        APO_BUFFER_FLAGS flags = o->u32BufferFlags;
        size_t bytes = (size_t)frames * m_channels * sizeof(float);
        memcpy(m_snap, (const void *)o->pBuffer, bytes);
        ProcessCall call = {this, o};
        if (guarded([](void *p) {
                ProcessCall *c = (ProcessCall *)p;
                c->self->process(c->o);
            }, &call))
            return;
        memcpy((void *)o->pBuffer, m_snap, bytes);
        o->u32ValidFrameCount = frames;
        o->u32BufferFlags = flags;
        standDown();
        m_faults++;
        m_restUntil = now + FAULT_REST_MS;
    }

    // The clean mic (after the mic's own effect, before the board): the board takes its
    // mic from here, so it never hears its own sounds coming back. One instance at a
    // time writes it; another takes over when that one stops.
    bool publish(APO_CONNECTION_PROPERTY *o, uint64_t now) {
        RingHeader *h = m_ring;
        LONG pub = h->publisher;
        if (pub != m_id) {
            if (pub != 0 && now - h->mic_tick <= PUBLISH_STALE_MS) return false;
            if (InterlockedCompareExchange(&h->publisher, m_id, pub) != pub) return false;
        }
        UINT32 frames = o->u32ValidFrameCount, ch = m_channels;
        const float *buf = (const float *)o->pBuffer;
        bool silent = o->u32BufferFlags != BUFFER_VALID;
        uint64_t wp = h->mic_write_pos;
        for (UINT32 i = 0; i < frames; i++) {
            size_t k = (size_t)((wp + i) & m_micMask) * 2;
            float a = silent ? 0.0f : buf[(size_t)i * ch];
            m_mic[k] = a;
            m_mic[k + 1] = silent ? 0.0f : ch > 1 ? buf[(size_t)i * ch + 1] : a;
        }
        MemoryBarrier();
        h->mic_rate = m_rate;
        h->mic_write_pos = wp + frames;
        h->mic_tick = now;
        return true;
    }

    void process(APO_CONNECTION_PROPERTY *o) {
        RingHeader *h = m_ring;
        if (!headerOk()) {   // junk in the header: the mic as it is until it's right again
            standDown();
            return;
        }
#ifdef OBMIC_FUZZ
        if (*(volatile uint32_t *)&h->pad1 == 0x0BADF00Du) {   // the guard's self-test
            volatile int *volatile nowhere = NULL;
            *nowhere = 1;
        }
#endif
        uint64_t now = GetTickCount64();
        if (!m_slot && m_locked) claimSlot(true);
        bool publishing = publish(o, now);
        UINT32 frames = o->u32ValidFrameCount;
        UINT32 ch = m_channels;
        float *buf = (float *)o->pBuffer;
        bool silent = o->u32BufferFlags != BUFFER_VALID;
        uint64_t wp = h->write_pos;
        bool board = h->enabled && now - h->board_tick <= BOARD_STALE_MS;
        // positions are tracked in doubles: past 2^52 frames (thousands of years at
        // 48 kHz, so only junk) they'd stop counting. The board starts over from 0.
        if (wp > POS_MAX) board = false;
        bool replaceMode = h->mode == MODE_REPLACE;
        double step = (double)m_boardRate / (double)m_rate;   // ring frames per mic frame
        double cap = (double)(m_mask + 1);
        m_micStep = 1.0 / step;
        uint32_t want = h->lead;
        if (want >= (uint32_t)(0.002 * m_boardRate) && want <= (uint32_t)(LEAD_MAX_S * m_boardRate)
                && want != (uint32_t)m_leadBase) {
            m_leadBase = want;            // the board asked for another lead
            m_lead = want;
            m_owe = 0;
            m_synced = false;
        }
        // The board late with a block (replace mode): the gap is filled in with the clean
        // mic from the very moment the board's audio was made from, so the voice carries
        // on with no skip or repeat, and this keeps its place in the ring meanwhile. (The
        // plain mic now is a lead ahead of that: each hiccup cut a bit out of the voice,
        // and the resync after it, a lead further back, played a bit twice.) Needs the
        // board's sync pair (older boards don't write one) and the clean mic at this
        // stream's rate (another app's stream, at another rate, may be publishing it).
        readSync();
        bool canFill = replaceMode && m_syncOk && h->mic_rate == m_rate;
        // the board only just started (or came back): wait until it's a lead ahead
        if (board && !m_synced && (double)wp < m_lead + frames * step + 2.0) board = false;
        bool fresh = false;
        // Back after the board was late (or quit without a word): never step back onto
        // audio already sent. That replayed the last lead's worth over and over (a
        // stutter) until the board counted as gone. Wait instead until it has a lead of
        // new audio past where this left off; the mic carries on meanwhile.
        if (board && !m_synced && m_played && (double)wp - m_lead < m_pos
                && m_pos <= (double)wp)
            board = false;
        // (filling in, this runs ahead of the board for as long as it's late)
        bool past = m_pos > (double)wp &&
                    !(canFill && m_synced && m_pos - (double)wp < 0.25 * m_boardRate);
        if (board && (!m_synced || past ||
                      (double)wp - m_pos > m_lead + 0.1 * m_boardRate ||
                      (double)wp - m_pos > cap * 0.5)) {
            m_pos = (double)wp - m_lead;
            if (m_pos < 0) m_pos = 0;
            m_owe = 0;
            m_synced = true;
            fresh = true;
        }
        // the clean mic this block would fill in with is all still in its ring
        bool micOk = canFill && m_synced;
        if (micOk) {
            uint64_t mwp = h->mic_write_pos;
            double micWp = (double)mwp;
            double m0 = micFrame(m_pos), m1 = micFrame(m_pos + frames * step) + 2.0;
            micOk = mwp <= POS_MAX && m0 >= 0.0 && m1 < micWp &&
                    micWp - m0 < (double)m_micMask - 64.0;
        }
        bool fill = micOk && board;
        // How much of the board's audio is there ahead of this instance. A block needs
        // (frames - 1) * step + 1 (the last sample interpolates up to the next frame,
        // which only counts when the position isn't whole). The board only stays in while
        // the next block's audio is there too: when it isn't (the board is late, or quit),
        // this block still has some, so the mic fades back in over it, never through a gap.
        double avail = m_synced ? (double)wp - m_pos : -1.0;
        double need = (frames - 1) * step + 1.0;
        bool have = avail >= need && avail <= cap * 0.5;
        bool ahead = have && avail >= need + frames * step;
        bool late = board && !ahead && !fresh;
        if (late && !m_late) {   // once per hiccup
            double before = m_lead;
            m_lead += LEAD_STEP_S * m_boardRate;
            if (m_lead > LEAD_MAX_S * m_boardRate) m_lead = LEAD_MAX_S * m_boardRate;
            if (fill) m_owe += m_lead - before;   // filling in: stepped back where it's quiet
            if (m_slot) m_slot->underruns = m_slot->underruns + 1;
        }
        m_late = late;
        if (late || !board) m_okBlocks = 0;
        else if (m_okBlocks < 0x7fffffff) m_okBlocks++;
        float wTarget = board && replaceMode && (ahead || fill) ? 1.0f : 0.0f;
        float bTarget = ahead || !fill ? 1.0f : 0.0f;   // 1 = the board, 0 = the mic from then
        // The mic's level while it's heard: the board's (MODE_ADD; and in MODE_REPLACE
        // while it stands in for a late board: muted stays muted)
        float mgTarget = 1.0f;
        if (board) {
            float mg = h->mic_gain;
            mgTarget = mg >= 0.0f && mg <= 4.0f ? mg : 1.0f;
        }
        bool useMic = micOk && (fill || (m_b < 1.0f && m_w > 0.0f));
        float g = h->gain;
        if (!(g >= 0.0f && g < 16.0f)) g = 1.0f;
        float ramp = 1.0f / (float)(FADE_S * m_rate);
        float w = m_w, mg = m_mg, b = useMic ? m_b : 1.0f;
        float sLast = 1.0f;
        bool any = false;
        if (have || useMic || w > 0.0f || mg != 1.0f || mgTarget != 1.0f) {
            if (silent) {   // a silent buffer's contents are undefined: start from zero
                memset(buf, 0, (size_t)frames * ch * sizeof(float));
            }
            double pos = m_pos;
            for (UINT32 i = 0; i < frames; i++) {
                mg += mg < mgTarget ? ramp : mg > mgTarget ? -ramp : 0.0f;
                if (fabsf(mg - mgTarget) < ramp) mg = mgTarget;
                float s = have ? sample(pos) * g : 0.0f;
                sLast = s;
                if (useMic) {   // crossfade: the board's audio and the mic from then
                    b += b < bTarget ? ramp : b > bTarget ? -ramp : 0.0f;
                    if (b < 0.0f || !have) b = 0.0f;
                    if (b > 1.0f) b = 1.0f;
                    s = s * b + micAt(micFrame(pos)) * mg * (1.0f - b);
                }
                if (have || useMic) pos += step;
                w += w < wTarget ? ramp : w > wTarget ? -ramp : 0.0f;
                if (w < 0.0f) w = 0.0f;
                if (w > 1.0f) w = 1.0f;
                float keep = (1.0f - w) * mg;
                if (replaceMode) s *= w;   // crossfade: the board's voice in, the mic out
                float *p = buf + (size_t)i * ch;
                for (UINT32 c = 0; c < ch; c++) {
                    float x = p[c] * keep + s;
                    p[c] = x > 1.0f ? 1.0f : x < -1.0f ? -1.0f : x;
                }
                any = any || s != 0.0f || keep != 1.0f;
            }
            if (have || useMic) m_pos = pos;
            if (have) m_played = true;
            float quiet = QUIET / (g > 1.0f ? g : 1.0f);
            if (have && !late && b >= 1.0f && m_owe > 0.5) {
                // The lead grew after a hiccup that was filled in: step back to it where
                // the board was quiet, so the stretch heard twice is silence
                double d = m_owe;
                if (d > SHRINK_MAX_S * m_boardRate) d = SHRINK_MAX_S * m_boardRate;
                uint32_t look = (uint32_t)d + 2 * (uint32_t)m_half + 2;
                if (fabsf(sLast) < QUIET && m_pos - d - m_half - 1 > 0
                        && peakOf(m_pos - d - m_half - 1, look) < quiet) {
                    m_pos -= d;
                    m_owe -= d;
                }
            } else if (have && !late && m_owe <= 0.5 && m_okBlocks > SHRINK_AFTER
                       && m_lead > m_leadBase + 0.5) {
                // On time for a while after a hiccup: read closer to the board again (less
                // delay), skipping a stretch only where it's quiet on both sides of the jump
                double d = m_lead - m_leadBase;
                if (d > SHRINK_MAX_S * m_boardRate) d = SHRINK_MAX_S * m_boardRate;
                uint32_t look = (uint32_t)d + 2 * (uint32_t)m_half + 2;
                if (fabsf(sLast) < QUIET && peakOf(m_pos - m_half - 1, look) < quiet
                        // (enough for the next block once the board has written it,
                        // as it does right after each mic block: the normal lead)
                        && (double)wp - (m_pos + d) >= need) {
                    m_pos += d;
                    m_lead -= d;
                    m_okBlocks = SHRINK_AFTER - 10;   // the next one can follow soon
                }
            }
        }
        m_w = w;
        m_mg = mg;
        m_b = useMic ? b : 1.0f;
        bool filling = useMic && !have;
        if (!filling && (!have || (late && w <= 0.0f))) {   // (silent now: a jump is fine)
            m_synced = false;
            m_owe = 0;
        }
        if (any) o->u32BufferFlags = BUFFER_VALID;
        if (m_slot) {
            m_slot->rate = m_rate;
            m_slot->channels = ch;
            m_slot->flags = (w > 0.5f ? SLOT_REPLACING : 0) | (publishing ? SLOT_PUBLISHING : 0);
            m_slot->read_pos = (uint64_t)m_pos;
            m_slot->lead = (uint32_t)m_lead;
            m_slot->blocks = m_slot->blocks + 1;
            m_slot->tick = now;
        }
    }

    LONG m_ref = 1;
    Inner m_inner;
    IUnknown *m_outer = NULL;
    LONG m_id = 0;
    IAudioProcessingObject *m_child = NULL;
    IAudioProcessingObjectRT *m_childRT = NULL;
    IAudioProcessingObjectConfiguration *m_childConfig = NULL;
    HANDLE m_file = INVALID_HANDLE_VALUE;
    HANDLE m_map = NULL;
    void *m_view = NULL;       // the file's view (m_ring once its layout checked out)
    RingHeader *m_ring = NULL;
    Slot *m_slot = NULL;
    float *m_snap = NULL;      // the block as it came in (processGuarded)
    UINT32 m_snapFrames = 0;
    uint64_t m_restUntil = 0;  // after a fault: the plain mic until this tick
    LONG m_faults = 0;         // faults this instance caught since it last logged them
    const float *m_data = NULL;
    float *m_mic = NULL;
    uint32_t m_mask = 0;
    uint32_t m_micMask = 0;
    uint32_t m_boardRate = 48000;
    UINT32 m_channels = 0;
    UINT32 m_rate = 0;
    bool m_float = false;
    bool m_locked = false;
    bool m_synced = false;
    bool m_played = false;     // m_pos is where the board's audio was last read up to
    double m_pos = 0;
    double m_lead = 0;
    double m_leadBase = 0;
    bool m_late = false;
    uint32_t m_okBlocks = 0;   // blocks the board was on time for, in a row
    float *m_kernel = NULL;    // the resampler's table (makeKernel); NULL = same rate
    int m_half = 0;            // its half width, in ring frames
    float m_w = 0.0f;    // 0 = the mic, 1 = the board's voice (MODE_REPLACE), crossfaded
    float m_mg = 1.0f;   // the mic's level (MODE_ADD; MODE_REPLACE: while it stands in)
    float m_b = 1.0f;    // filling in: 1 = the board's audio, 0 = the mic from then
    double m_owe = 0;    // ring frames the lead grew by that still need stepping back
    double m_micStep = 1.0;   // clean-mic frames per ring frame
    bool m_syncOk = false;    // the board's sync pair (readSync)
    uint64_t m_syncWp = 0;
    uint64_t m_syncMic = 0;
};

// ------------------------------------------------------------------ COM plumbing

class Factory : public IClassFactory {
public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *ppv = static_cast<IClassFactory *>(this);
            return S_OK;
        }
        *ppv = NULL;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return 2; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown *outer, REFIID riid, void **ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = NULL;
        if (outer && !IsEqualIID(riid, IID_IUnknown)) return CLASS_E_NOAGGREGATION;
        OnionMicAPO *apo = new (std::nothrow) OnionMicAPO(outer);
        if (!apo) return E_OUTOFMEMORY;
        HRESULT hr = apo->innerQuery(riid, ppv);
        apo->inner()->Release();   // the caller's reference is the only one left
        if (FAILED(hr)) problemf("create failed: 0x%08lx", (unsigned long)hr);
        return hr;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&g_locks);
        else InterlockedDecrement(&g_locks);
        return S_OK;
    }
};

static Factory g_factory;

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllGetClassObject(REFCLSID clsid, REFIID riid,
                                                                          void **ppv) {
    if (!ppv) return E_POINTER;
    *ppv = NULL;
    if (!IsEqualCLSID(clsid, CLSID_OnionMic)) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllCanUnloadNow() {
    return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = inst;
        DisableThreadLibraryCalls(inst);   // (nothing else here: the loader lock is held)
    }
    return TRUE;
}
