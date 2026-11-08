"""Fetch and build the RNNoise library Clean mic uses (build.ps1 runs this).

Clean mic takes background noise out of your mic with RNNoise (BSD-3,
licenses/RNNoise-BSD-3.txt). This builds rnnoise.dll from Xiph's source at a pinned
commit and its pinned model (the same source and model the pyrnnoise 0.4.5 wheel
ships, so it cleans the same), with the MinGW-w64 gcc the mic effect is built with.

Two things make it about a third of the wheel DLL's CPU on a slower PC:
- DISABLE_DEBUG_FLOAT: the model's 8-bit weights, not its float copy of them (what
  Xiph's own builds of this network in Opus use). The float copy is 14 MB read every
  10 ms, more than a slower PC's cache, so the float build waits on memory. Measured
  on speech with hiss, fan, keyboard, TV and a quiet voice: what it keeps of the
  voice and leaves of the noise match the float build within 0.2 dB.
- Xiph's run-time CPU choice (RNN_ENABLE_X86_RTCD): only nnet_sse4_1.c and
  nnet_avx2.c are built for SSE4.1 / AVX2, and run when the CPU has them; everything
  else is plain x86-64 (SSE2), so any 64-bit PC runs it. No fast-math.

The repo has no binaries: the source archive and the model are downloaded and refused
when their SHA-256 doesn't match (for the source, the files in it, so a re-packed
archive with the same files still passes). Downloads are kept in build/rnnoise-src,
and a DLL already built from the same inputs isn't built again (~10 s: the model's
weights are one big C file).

    python scripts/buildtools/fetch_rnnoise.py [folder]
        (default: build/rnnoise; a source run uses it too)
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "directmic"))
from build_directmic import find_gxx  # noqa: E402

COMMIT = "70f1d256acd4b34a572f999a05c87bf00b67730d"   # as in pyrnnoise 0.4.5
SRC_URL = f"https://github.com/xiph/rnnoise/archive/{COMMIT}.tar.gz"
SRC_FILES_SHA256 = "97e20bf019b8931c5ece9431b385fca2d238d6d32a59f561fd31d9df68263429"
MODEL_SHA256 = "0a8755f8e2d834eff6a54714ecc7d75f9932e845df35f8b59bc52a7cfe6e8b37"   # model_version
MODEL_URL = f"https://media.xiph.org/rnnoise/models/rnnoise_data-{MODEL_SHA256}.tar.gz"
SOURCES = ["denoise.c", "rnn.c", "pitch.c", "kiss_fft.c", "celt_lpc.c", "nnet.c",
           "nnet_default.c", "parse_lpcnet_weights.c", "rnnoise_data.c", "rnnoise_tables.c"]
FLAGS = ["-O3", "-std=gnu99", "-fvisibility=hidden", "-DRNNOISE_BUILD", "-DDLL_EXPORT", "-w",
         "-DDISABLE_DEBUG_FLOAT", "-Iinclude", "-Isrc"]
# the network's code picks SSE4.1 / AVX2 at run time (pitch.c and celt_lpc.c don't take
# these: they'd look for x86 versions of their own that this source hasn't got)
RTCD = ["-DRNN_ENABLE_X86_RTCD", "-DCPU_INFO_BY_ASM", "-DOPUS_X86_MAY_HAVE_SSE4_1",
        "-DOPUS_X86_MAY_HAVE_AVX2"]
PLAIN = ["pitch.c", "celt_lpc.c"]
ARCH = {"x86/x86_dnn_map.c": [], "x86/x86cpu.c": [], "x86/nnet_sse4_1.c": ["-msse4.1"],
        "x86/nnet_avx2.c": ["-mavx", "-mfma", "-mavx2"]}
LINK = ["-shared", "-s", "-static-libgcc", "-Wl,--no-insert-timestamp"]
NAME = "rnnoise.dll"
FRAME = 480
STAMP = "BUILT-FROM.txt"
LICENSE = ROOT / "licenses" / "RNNoise-BSD-3.txt"
TIMEOUT_S = 60
BUILD_TIMEOUT_S = 300
MAX_BYTES = 120 * 1024 * 1024   # the model is ~59 MB, the source ~0.1 MB


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_sha256(files: dict[str, bytes]) -> str:
    """One SHA-256 over every file's path and bytes, in path order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + sha256(files[name]).encode() + b"\n")
    return h.hexdigest()


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"{url}: over {MAX_BYTES // (1024 * 1024)} MB")
    return data


def tar_files(data: bytes, strip: int = 0) -> dict[str, bytes]:
    """The regular files of a .tar.gz, by path (`strip` leading folders dropped)."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")[strip:]
            if not parts or any(p in ("", ".", "..") for p in parts) or ":" in m.name:
                raise SystemExit(f"unexpected path in archive: {m.name}")
            f = tar.extractfile(m)
            if f is not None:
                out["/".join(parts)] = f.read()
    return out


def source(cache: Path) -> Path:
    """The pinned source with the pinned model in it, checked, in `cache`/<commit>."""
    tree = cache / COMMIT[:12]
    if (tree / "ok").is_file():
        return tree
    cache.mkdir(parents=True, exist_ok=True)
    model_tgz = cache / f"rnnoise_data-{MODEL_SHA256}.tar.gz"
    if not (model_tgz.is_file() and sha256(model_tgz.read_bytes()) == MODEL_SHA256):
        data = download(MODEL_URL)
        got = sha256(data)
        if got != MODEL_SHA256:
            raise SystemExit(f"{MODEL_URL}: SHA-256 {got}, expected {MODEL_SHA256}")
        model_tgz.write_bytes(data)
    src = tar_files(download(SRC_URL), strip=1)
    got = files_sha256(src)
    if got != SRC_FILES_SHA256:
        raise SystemExit(f"{SRC_URL}: files' SHA-256 {got}, expected {SRC_FILES_SHA256}")
    model = tar_files(model_tgz.read_bytes())
    if tree.exists():
        shutil.rmtree(tree)
    for name, data in {**src, **model}.items():   # (the model's files go into src/)
        p = tree / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (tree / "ok").write_text("checked\n")
    return tree


def compiler() -> str:
    gxx = find_gxx()
    gcc = Path(gxx).with_name("gcc.exe") if gxx else None
    found = str(gcc) if gcc and gcc.is_file() else shutil.which("gcc")
    if not found:
        raise SystemExit("gcc not found: install MinGW-w64 (winget install "
                         "BrechtSanders.WinLibs.POSIX.UCRT) or set MINGW_GXX")
    return found


def check(dll: Path):
    """It loads, has the calls Clean mic makes, and cleans a frame."""
    lib = ctypes.CDLL(str(dll))
    lib.rnnoise_create.restype = ctypes.c_void_p
    lib.rnnoise_create.argtypes = [ctypes.c_void_p]
    lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
    lib.rnnoise_process_frame.restype = ctypes.c_float
    lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float),
                                          ctypes.POINTER(ctypes.c_float)]
    if lib.rnnoise_get_frame_size() != FRAME:
        raise SystemExit(f"{dll}: unexpected frame size")
    st = lib.rnnoise_create(None)
    frame = (ctypes.c_float * FRAME)(*([1000.0, -1000.0] * (FRAME // 2)))
    for _ in range(10):
        lib.rnnoise_process_frame(st, frame, frame)
    lib.rnnoise_destroy(st)
    if not all(abs(v) < 1e6 for v in frame):
        raise SystemExit(f"{dll}: its output is out of range")


def fetch(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dll = folder / NAME
    gcc = compiler()
    ver = subprocess.run([gcc, "-dumpfullversion"], capture_output=True, text=True,
                         timeout=TIMEOUT_S).stdout.strip()
    jobs = {s: (FLAGS if s in PLAIN else FLAGS + RTCD) for s in SOURCES}
    jobs.update({s: FLAGS + RTCD + extra for s, extra in ARCH.items()})
    key = (f"xiph/rnnoise {COMMIT}\nmodel {MODEL_SHA256}\ngcc {ver}\n"
           + "".join(f"{s}: {' '.join(f)}\n" for s, f in jobs.items())
           + f"link {' '.join(LINK)}\n")
    stamp = folder / STAMP
    if not (dll.is_file() and stamp.is_file() and stamp.read_text() == key):
        tree = source(ROOT / "build" / "rnnoise-src")
        obj = tree / "obj"
        shutil.rmtree(obj, ignore_errors=True)
        obj.mkdir()
        objs = [obj / (s.replace("/", "_") + ".o") for s in jobs]
        procs = [subprocess.Popen([gcc, *f, "-c", f"src/{s}", "-o", str(o)], cwd=tree)
                 for (s, f), o in zip(jobs.items(), objs)]   # side by side: ~30 s, not ~45
        try:
            codes = [p.wait(timeout=BUILD_TIMEOUT_S) for p in procs]
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
        if any(codes):
            raise SystemExit(f"building {NAME} failed ({codes})")
        tmp = dll.with_suffix(".part")
        r = subprocess.run([gcc, *LINK, "-o", str(tmp), *map(str, objs)], cwd=tree,
                           timeout=BUILD_TIMEOUT_S)
        if r.returncode:
            raise SystemExit(f"linking {NAME} failed ({r.returncode})")
        check(tmp)
        os.replace(tmp, dll)
        stamp.write_text(key)
    shutil.copy2(LICENSE, folder / "LICENSE.txt")   # travels with the binary
    return dll


if __name__ == "__main__":
    out = fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "rnnoise")
    print(f"RNNoise (xiph/rnnoise {COMMIT[:12]}, built here): {out}")
