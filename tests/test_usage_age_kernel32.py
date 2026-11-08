"""The start-time check sets its argtypes on its own copy of kernel32, so other code
calling the same function with other pointer types keeps working."""
import ctypes
import os
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_process_age_leaves_the_shared_kernel32_alone():
    from soundboard.core import usageevents
    shared = ctypes.windll.kernel32.GetProcessTimes
    shared.argtypes = None
    usageevents._process_age()
    assert shared.argtypes is None
    from soundboard.audio import appaudio
    assert appaudio.process_started(os.getpid())
