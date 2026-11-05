"""A toast fades out from where it is: its first frame of fading used to paint nothing at all
(a blink), with Qt's "A paint device can only be painted by one painter" in the log."""
import time

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import toast


def _run(qapp, secs: float):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.004)


def test_fading_out_paints_every_frame(qapp, monkeypatch):
    monkeypatch.setattr(toast, "animations_on", lambda: True)
    host = QWidget()
    host.resize(900, 500)
    host.show()
    said: list[str] = []
    old = qInstallMessageHandler(lambda _t, _c, msg: said.append(msg))
    try:
        toast.show(host, "A notice", ms=60000)
        _run(qapp, toast.ANIM_MS / 1000 + 0.15)   # faded in, and at rest
        shown = host.findChild(toast._Toast)
        assert shown is not None
        shown.dismiss()
        _run(qapp, toast.ANIM_MS / 1000 + 0.15)
    finally:
        qInstallMessageHandler(old)
        host.close()
        host.deleteLater()
    assert [m for m in said if "Painter" in m or "painter" in m] == []
