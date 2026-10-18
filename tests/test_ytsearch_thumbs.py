"""Search thumbnails: a picture that's huge or never ends is cut off, and pictures are
decoded off the UI thread."""
import http.server
import threading
import time

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QTimer
from PySide6.QtGui import QImage

from conftest import process_events
from soundboard.online import quality
from soundboard.online import ytdl
from soundboard.ui.sounds import ytsearch


def png_bytes() -> bytes:
    img = QImage(32, 18, QImage.Format_RGB32)
    img.fill(0x3366CC)
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QBuffer.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


@pytest.fixture
def server():
    """/endless sends bytes until the client goes; /pic.png is a small picture."""
    sent = {"endless": 0}
    pic = png_bytes()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            if self.path == "/pic.png":
                self.send_header("Content-Length", str(len(pic)))
                self.end_headers()
                self.wfile.write(pic)
                return
            self.end_headers()          # no length: it just keeps going
            chunk = b"\xff" * 65536
            try:
                while sent["endless"] < 200_000_000:
                    self.wfile.write(chunk)
                    sent["endless"] += len(chunk)
            except OSError:
                pass                    # the app hung up: what's wanted

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.sent = sent
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def result(url):
    return ytdl.Result(id=url, title="T", channel="c", seconds=1, source="soundcloud", art=url)


def panel_with(monkeypatch, url):
    decoded, finished = [], []
    real_from_data = QImage.fromData

    def from_data(data, *a):
        decoded.append((len(data), threading.current_thread() is threading.main_thread()))
        return real_from_data(data, *a)
    monkeypatch.setattr(ytsearch.QImage, "fromData", staticmethod(from_data))
    real_on_thumb = ytsearch.SearchResults._on_thumb
    monkeypatch.setattr(ytsearch.SearchResults, "_on_thumb", lambda panel, reply, *a: (
        finished.append((reply.error(), reply.property("too_big"))),
        real_on_thumb(panel, reply, *a)))
    assert quality.current.web_extras
    panel = ytsearch.SearchResults()
    panel._add_rows([result(url)], panel._gen)
    return panel, decoded, finished


def test_a_thumbnail_that_never_ends_is_aborted_and_never_decoded(qapp, server, monkeypatch):
    # a loaded machine: the UI thread (where the size check runs) keeps stalling while
    # Qt's network thread could read on, so only a read-buffer limit holds the size down
    lag = QTimer()
    lag.setInterval(5)
    lag.timeout.connect(lambda: time.sleep(0.2))
    port = server.server_address[1]
    panel, decoded, finished = panel_with(monkeypatch, f"http://127.0.0.1:{port}/endless")
    shown = []
    panel.thumb_ready.connect(lambda url, pm: shown.append(url))
    lag.start()
    try:
        assert process_events(qapp, lambda: finished, timeout=30), server.sent
    finally:
        lag.stop()
    assert finished[0][1] is True                       # cut off by the size cap
    assert server.sent["endless"] < 20_000_000          # 5 MB cap + socket buffers
    process_events(qapp, lambda: False, timeout=0.3)
    assert decoded == [] and shown == []


def test_a_thumbnail_is_decoded_off_the_ui_thread(qapp, server, monkeypatch):
    port = server.server_address[1]
    panel, decoded, finished = panel_with(monkeypatch, f"http://127.0.0.1:{port}/pic.png")
    shown = []
    panel.thumb_ready.connect(lambda url, pm: shown.append(pm.size().toTuple()))
    assert process_events(qapp, lambda: shown, timeout=15), (finished, decoded)
    assert shown == [(32, 18)]
    assert decoded and not decoded[0][1]                # not on the UI thread


def test_a_picture_for_a_search_thats_gone_is_dropped(qapp, server, monkeypatch):
    port = server.server_address[1]
    panel, decoded, finished = panel_with(monkeypatch, f"http://127.0.0.1:{port}/pic.png")
    shown = []
    panel.thumb_ready.connect(lambda url, pm: shown.append(url))
    panel._gen += 1                                     # a new search started meanwhile
    assert process_events(qapp, lambda: finished, timeout=15)
    process_events(qapp, lambda: False, timeout=0.3)
    assert shown == [] and decoded == []
