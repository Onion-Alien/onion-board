"""The Sounds tab's "Sounds folder": it opens the folder the sounds are kept in, and
sound files dragged into that folder in Explorer join the board by themselves."""
import numpy as np
import pytest
import soundfile as sf

from conftest import process_events
from soundboard import library
from soundboard.library import SR, Config, SoundMeta
from soundboard.ui import mainwindow as main
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(main, "LOOSE_WAIT_MS", 50)
    main_window._loose_timer.setInterval(50)
    return main_window


def _wav(path, ms=300):
    t = np.arange(SR * ms // 1000) / SR
    sf.write(path, np.stack([np.sin(2 * np.pi * 330 * t)] * 2, 1) * 0.3, SR)


def test_loose_sounds_are_only_files_put_there_by_hand(app_dir):
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    ours = library.SOUNDS_DIR / "0123456789_Boom.wav"     # the library's own name
    mine = library.SOUNDS_DIR / "Bruh.wav"
    other = library.SOUNDS_DIR / "notes.txt"
    used = library.SOUNDS_DIR / "Kept.mp3"
    for p in (ours, mine, other, used):
        p.write_bytes(b"x")
    cfg = Config(sounds=[SoundMeta(id="a", name="Kept", file=str(used))])
    assert library.loose_sounds(cfg) == [mine]


def test_a_sound_dragged_into_the_folder_joins_the_board(window, qapp):
    dropped = library.SOUNDS_DIR / "Vine boom.wav"
    _wav(dropped)
    window._loose_timer.start()           # what the folder watcher does on a change
    assert process_events(qapp, lambda: any(m.name == "Vine boom" for m in window.cfg.sounds))
    m = next(m for m in window.cfg.sounds if m.name == "Vine boom")
    assert m.id in window.pads and m.duration > 0
    assert library.Path(m.file).is_file() and not dropped.exists()   # kept once, as ours
    assert process_events(qapp, lambda: not window._pending_imports)
    window._take_loose()
    assert [s.name for s in window.cfg.sounds].count("Vine boom") == 1


def test_a_file_still_copying_in_waits(window, qapp):
    dropped = library.SOUNDS_DIR / "Big.wav"
    _wav(dropped)
    window._loose_timer.stop()
    window._take_loose()                  # first look: noted, not taken yet
    assert dropped in window._loose_sizes and not window._pending_imports
    _wav(dropped, 600)                    # it grew meanwhile
    window._take_loose()
    assert dropped in window._loose_sizes and not window._pending_imports
    window._take_loose()                  # the same twice: done copying
    assert process_events(qapp, lambda: any(m.name == "Big" for m in window.cfg.sounds))


def test_the_button_opens_the_sounds_folder(window, monkeypatch):
    opened = []
    monkeypatch.setattr(main.QDesktopServices, "openUrl", lambda u: opened.append(u))
    window.btn_folder.click()
    assert opened and library.Path(opened[0].toLocalFile()) == library.SOUNDS_DIR
