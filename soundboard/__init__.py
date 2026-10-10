"""Onion Board — gaming soundboard with virtual-mic output, mic passthrough and test mode."""
import os as _os

__version__ = "1.9.27"

# numpy and scipy each bring an OpenBLAS that starts one thread per CPU when it loads
# and reserves ~32 MB for each: about 1 GB and 30 threads doing nothing. Two threads
# keep the filters' matrix maths within ~20 % of all of them (one was up to 70 %
# slower). It has to be set before numpy is first imported, and every entry point
# imports this package first. A value set by the user wins; BLAS_MARK says the app set
# it, so helper processes (net.child_env) and a restarted app can tell.
BLAS_THREADS = "2"
BLAS_MARK = "ONIONBOARD_SET_BLAS"
if "OPENBLAS_NUM_THREADS" not in _os.environ or _os.environ.get(BLAS_MARK):
    _os.environ["OPENBLAS_NUM_THREADS"] = BLAS_THREADS
    _os.environ[BLAS_MARK] = "1"


def without_app_blas(env: dict[str, str]) -> dict[str, str]:
    """`env` for a child process with its own maths (an add-on's Python, pip): the
    app's own OPENBLAS_NUM_THREADS taken out again; one the user set stays."""
    if env.pop(BLAS_MARK, None):
        env.pop("OPENBLAS_NUM_THREADS", None)
    return env
