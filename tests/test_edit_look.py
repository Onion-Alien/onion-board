"""Edit…'s Sound tab in three cards (Look, Playback, Timing): the pad's picture is set
there now (it left the right-click menu), changed only on Save, and a sound from a
web link shows where it came from."""
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel

from soundboard.ui.kit.plaintext import plain_tip
from soundboard.sounds import library, thumbs
from soundboard.ui.sounds.dialogs import EditDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)
from test_thumbs import make_image
from conftest import process_events

SRC = {"site": "youtube", "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
       "title": "Never Gonna Give You Up", "channel": "Rick Astley"}


def _dialog(w, sid="s0"):
    return EditDialog(w.meta(sid), w.hotkeys, lambda *a: None, w)


def test_the_cards_are_look_playing_trim_speed_effects_and_timing(window):  # noqa: F811
    """Simple is one page: the few things people change, the rest in Advanced."""
    d = _dialog(window)
    heads = [lab.text() for lab in d.simple.widget().findChildren(QLabel)
             if lab.objectName() == "section"]
    assert heads == ["Look", "Playback", "Trim", "Speed & loudness", "Effects", "Timing"]
    assert d.timing.isHidden()                  # behind More options
    d.more.click()
    assert not d.timing.isHidden()
    assert d.btn_source is None              # a sound from a file: no "From" line
    assert not d.btn_pic_clear.isVisibleTo(d)   # no picture: nothing to remove
    d.deleteLater()


def test_a_picture_from_a_file_goes_on_only_on_save(qapp, window, tmp_path,  # noqa: F811
                                                    monkeypatch):
    pic = make_image(tmp_path / "a.png")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(pic), ""))
    m = window.meta("s0")
    d = _dialog(window)
    d.btn_pic_file.click()
    assert process_events(qapp, lambda: d.picture is not None)
    assert isinstance(d.picture, QImage) and d.btn_pic_clear.isVisibleTo(d)
    assert not m.image                        # Cancel would leave it like this
    d.apply()
    assert m.image and thumbs.Path(m.image).parent == library.THUMBS_DIR
    first = m.image
    d.deleteLater()

    d = _dialog(window)                       # remove it: also only on Save
    d.btn_pic_clear.click()
    assert d.picture == "" and m.image == first
    d.apply()
    assert m.image == "" and not thumbs.Path(first).exists()
    d.deleteLater()


def test_an_unreadable_file_is_refused(qapp, window, tmp_path, monkeypatch):  # noqa: F811
    from soundboard.ui.kit import toast
    bad = tmp_path / "x.png"
    bad.write_bytes(b"not a picture")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    d = _dialog(window)
    d.btn_pic_file.click()
    assert process_events(qapp, lambda: toast.shown(d))
    assert any("x.png" in t.text() for t in toast.shown(d)) and d.picture is None
    d.deleteLater()


def test_save_as_new_sound_puts_the_picture_on_the_copy(qapp, window, tmp_path,  # noqa: F811
                                                        monkeypatch):
    pic = make_image(tmp_path / "a.png")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(pic), ""))
    w = window
    before = len(w.cfg.sounds)

    d = w.editctl.edit("s0")
    d.btn_pic_file.click()
    assert process_events(qapp, lambda: d.picture is not None)
    d.as_copy = True
    d.done(QDialog.Accepted)
    assert len(w.cfg.sounds) == before + 1
    copy = w.cfg.sounds[w.cfg.sounds.index(w.meta("s0")) + 1]
    assert copy.image and not w.meta("s0").image


def test_a_big_picture_is_read_off_the_ui_thread_and_small(qapp, window, tmp_path,  # noqa: F811
                                                            monkeypatch):
    """A 50-megapixel photo held the UI for half a minute on a PC short of memory: it
    was decoded whole and smooth-scaled on the UI thread. Now a worker reads it already
    scaled, the UI keeps going meanwhile (and says it's getting it if that's slow)."""
    import threading
    pic = make_image(tmp_path / "big.jpg", 8000, 6000)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(pic), ""))
    real, go, threads = thumbs.read, threading.Event(), []

    def slow_read(path):
        threads.append(threading.current_thread())
        go.wait(10)
        return real(path)
    monkeypatch.setattr(thumbs, "read", slow_read)
    d = _dialog(window)
    d.btn_pic_file.click()                     # returns while the picture is being read
    assert d.picture is None
    assert process_events(qapp, lambda: d.pic_note.text() == "Getting the picture…")
    go.set()
    assert process_events(qapp, lambda: d.picture is not None)
    assert threads and threads[0] is not threading.main_thread()
    assert (d.picture.width(), d.picture.height()) == (480, 360)   # never the 8000 x 6000
    assert d.pic_note.text() == "" and d.btn_pic_clear.isVisibleTo(d)
    d.deleteLater()


def test_reading_a_picture_never_decodes_it_whole(qapp, tmp_path):
    img = thumbs.read(make_image(tmp_path / "big.jpg", 8000, 6000))
    assert (img.width(), img.height()) == (480, 360)
    small = make_image(tmp_path / "small.png", 300, 200)
    assert (thumbs.read(small).width(), thumbs.read(small).height()) == (300, 200)
    assert thumbs.read(tmp_path / "missing.png").isNull()
    assert thumbs.shrink(QImage(4000, 1000, QImage.Format_RGB32)).size().toTuple() == (1200, 300)


def test_a_downloaded_sound_says_where_it_came_from(window, monkeypatch):  # noqa: F811
    from soundboard.ui.sounds import sourcedialog
    window.meta("s0").source = dict(SRC)
    d = _dialog(window)
    texts = {lab.text() for lab in d.findChildren(QLabel)}
    assert "From YouTube: Rick Astley" in texts
    shown = []
    monkeypatch.setattr(sourcedialog.SourceDialog, "show", lambda self: shown.append(self))
    d.btn_source.click()
    assert len(shown) == 1 and shown[0].btn_open.toolTip() == plain_tip(SRC["link"])
    d.deleteLater()


def test_delete_info_from_edit_hides_the_line_and_saves(window, monkeypatch,  # noqa: F811
                                                       modal_answers):
    from soundboard.ui.sounds import sourcedialog
    window.meta("s0").source = dict(SRC)
    d = _dialog(window)
    opened = []
    monkeypatch.setattr(sourcedialog.SourceDialog, "show", lambda self: opened.append(self))
    modal_answers.add("confirm", True)
    saved = []
    d.source_forgotten.connect(lambda: saved.append(1))
    d.show()
    d.btn_source.click()
    opened[0].btn_forget.click()
    assert window.meta("s0").source == {} and saved and not d.source_row.isVisible()
    d.close()
    d.deleteLater()


def test_renaming_to_another_sounds_name_warns(window):  # noqa: F811
    d = window.editctl._new_editor(window.meta("s0"), "sound")
    other = window.meta("s1").name
    assert not d.name_hint.isVisibleTo(d)          # its own name: no warning
    d.name.setText(f"  {other.upper()} ")          # any case, spaces round it
    assert d.name_hint.isVisibleTo(d)
    d.name.setText(other + " 2")
    assert not d.name_hint.isVisibleTo(d)
    d.name.setText(other)
    d.load(window.meta("s1"))                      # reused for that sound: its own name
    assert not d.name_hint.isVisibleTo(d)
    d.deleteLater()
