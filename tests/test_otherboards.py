"""Import from Resanance, Soundux and EXP Soundboard (Soundpad is test_soundpad.py): reading
their saved boards, and the parts every import shares."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from soundboard import expboard, otherboards, resanance, soundux
from soundboard.library import SR

PAGE = resanance.PAGE


def _wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros((SR // 20, 2)), SR)
    return path


# ---------------------------------------------------------------- a LiteDB 5 file
def _bson(doc: dict) -> bytes:
    body = b""
    for k, v in doc.items():
        key = k.encode() + b"\0"
        if isinstance(v, bool):
            body += b"\x08" + key + bytes([v])
        elif isinstance(v, int):
            body += b"\x10" + key + struct.pack("<i", v)
        elif isinstance(v, float):
            body += b"\x01" + key + struct.pack("<d", v)
        else:
            s = str(v).encode() + b"\0"
            body += b"\x02" + key + struct.pack("<i", len(s)) + s
    return struct.pack("<i", len(body) + 5) + body + b"\0"


def _page(pid: int, ptype: int, blocks: list[bytes | None], tx: int = 0,
          confirmed: bool = False) -> bytearray:
    """A page with these blocks in its slots (None: a deleted slot)."""
    p = bytearray(PAGE)
    struct.pack_into("<IB", p, 0, pid, ptype)
    struct.pack_into("<I", p, 14, tx)
    p[18] = confirmed
    pos = 32
    for i, b in enumerate(blocks):
        if b is None:
            continue
        p[pos:pos + len(b)] = b
        struct.pack_into("<HH", p, PAGE - (i + 1) * 4, len(b), pos)
        pos += len(b)
    p[30] = len(blocks) - 1 if blocks else 255
    return p


def _block(data: bytes, extend=False, nxt=(0xFFFFFFFF, 0xFF)) -> bytes:
    return bytes([extend]) + struct.pack("<IB", *nxt) + data


def _row(_id, path, name, hot="None", mod="None", profile="Sounds", index=0) -> bytes:
    return _bson({"_id": _id, "filepath": str(path), "shortname": name, "rand": False,
                  "loop": False, "hot": hot, "mod": mod, "vol": 100.0, "index": index,
                  "profile": profile})


def _resanance_db(tmp_path) -> Path:
    s = tmp_path / "sounds"
    a, b, c = _wav(s / "airhorn.mp3"), _wav(s / "bruh.wav"), _wav(s / "oof.ogg")
    header = bytearray(PAGE)
    header[4] = 1
    header[32:32 + len(resanance.MAGIC)] = resanance.MAGIC
    long_row = _row(4, c, "oof.ogg", "NumPad3", "Ctrl, Shift", "Memes", 0)
    data = _page(1, 4, [
        _block(_bson({"_id": 1, "filepath": "Stop Playback", "shortname": "Stop Playback",
                      "hot": "Pause", "mod": "None"})),
        _block(_row(2, a, "airhorn.mp3", "D8", "Ctrl", "Sounds", 1)),
        None,   # a deleted row: its bytes would still be in the page, unlisted
        _block(_row(3, b, "Bruh", "F6", "None", "Sounds", 0)),
        _block(long_row[:20], nxt=(2, 0)),   # a row that goes on in another page
        _block(_row(5, s / "gone.mp3", "gone.mp3", "Oemplus", "Alt", "Memes", 1)),
    ])
    more = _page(2, 4, [_block(long_row[20:], extend=True)])
    db = tmp_path / "Resanance" / "data" / "Resanance.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(bytes(header + data + more))
    return db


def test_resanance_reads_live_rows_tabs_and_hotkeys(tmp_path):
    rows = resanance.read(_resanance_db(tmp_path))
    assert [e.name for e in rows] == ["Bruh", "airhorn", "oof", "gone"]   # tab, then order
    assert [e.hotkey for e in rows] == ["f6", "ctrl+8", "ctrl+shift+num 3", "alt+="]
    assert [e.tags for e in rows] == [["Sounds"], ["Sounds"], ["Memes"], ["Memes"]]
    assert [e.exists for e in rows] == [True, True, True, False]


def test_resanance_one_tab_is_no_category(tmp_path):
    db = _resanance_db(tmp_path)
    raw = bytearray(db.read_bytes())
    raw[2 * PAGE:] = bytes(PAGE)   # only the first page's rows, all in "Sounds"
    raw[PAGE:2 * PAGE] = _page(1, 4, [_block(_row(2, tmp_path / "sounds" / "bruh.wav",
                                                  "bruh.wav"))])
    db.write_bytes(bytes(raw))
    assert [(e.name, e.tags) for e in resanance.read(db)] == [("bruh", [])]


def test_resanance_log_file_changes_count_once_committed(tmp_path):
    db = _resanance_db(tmp_path)
    log = db.with_name("Resanance-log.db")
    new = _page(1, 4, [_block(_row(2, tmp_path / "sounds" / "bruh.wav", "Renamed"))],
                tx=7, confirmed=True)
    lost = _page(1, 4, [_block(_row(2, tmp_path / "sounds" / "bruh.wav", "Never"))],
                 tx=8)   # never committed: ignored
    log.write_bytes(bytes(new + lost))
    # the new page 1 has only the renamed row (oof started in the old one)
    assert [e.name for e in resanance.read(db)] == ["Renamed"]


def test_resanance_not_a_database(tmp_path):
    p = tmp_path / "Resanance.db"
    p.write_bytes(b"SQLite format 3\0" + bytes(PAGE))
    with pytest.raises(ValueError):
        resanance.read(p)


@pytest.mark.parametrize("hot,mod,want", [
    ("A", "None", "a"), ("D1", "Alt", "alt+1"), ("Space", "Shift", "shift+space"),
    ("F24", "Ctrl", "ctrl+f24"), ("None", "Ctrl", ""), ("Bogus", "None", ""),
    ("ShiftKey", "None", "")])
def test_resanance_hotkeys(hot, mod, want):
    assert resanance.hotkey(hot, mod) == want


# ---------------------------------------------------------------- EXP Soundboard
def _exp_board(tmp_path, encoding="utf-8") -> Path:
    s = tmp_path / "sfx"
    rows = [{"file": str(_wav(s / "airhorn.mp3")), "activationKeysNumbers": [17, 49]},
            {"file": str(_wav(s / "café.wav")), "activationKeysNumbers": [97]},
            {"file": str(_wav(s / "it's a trap.mp3")), "activationKeysNumbers": [16, 18, 61441]},
            {"file": str(s / "gone.mp3"), "activationKeysNumbers": []},
            {"file": str(_wav(s / "chord.wav")), "activationKeysNumbers": [65, 66]}]
    p = tmp_path / "Documents" / "my board.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"soundboardEntries": rows}, ensure_ascii=False).replace("'", "\\u0027")
    p.write_bytes(text.encode(encoding))
    return p


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"])   # older Javas: the ANSI page
def test_exp_reads_files_and_hotkeys(tmp_path, encoding):
    rows = expboard.read(_exp_board(tmp_path, encoding))
    assert [e.name for e in rows] == ["airhorn", "café", "it's a trap", "gone", "chord"]
    assert [e.hotkey for e in rows] == ["ctrl+1", "num 1", "alt+shift+f14", "", ""]
    assert [e.exists for e in rows] == [True, True, True, False, True]


def test_exp_finds_a_board_in_documents_when_the_registry_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(expboard, "_last_board", lambda: None)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert expboard.default_board() is None
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents" / "other.json").write_text('{"x": 1}', encoding="utf-8")
    assert expboard.default_board() is None
    board = _exp_board(tmp_path)
    assert expboard.default_board() == board


def test_exp_java_preferences_escaping():
    assert expboard.java_pref("/D:///Sounds///Board//my board.json") == \
        r"D:\Sounds\Board\my board.json"
    assert expboard.java_pref("/D://caf/u00e9//a\\b.json") == "D:\\café\\a/b.json"


def test_exp_not_a_board(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"sounds": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        expboard.read(p)


# ---------------------------------------------------------------- Soundux
def _soundux_config(tmp_path, tabs=2) -> Path:
    m, s = tmp_path / "Memes", tmp_path / "Songs"
    memes = {"id": 1, "name": "Memes", "path": str(m), "sortMode": 0, "sounds": [
        {"id": 1, "name": "airhorn.mp3", "path": str(_wav(m / "airhorn.mp3")),
         "hotkeys": [162, 49], "hotkeySequence": "Ctrl + 1", "isFavorite": False,
         "localVolume": None, "remoteVolume": None, "modifiedDate": 0},
        {"id": 2, "name": "bruh", "path": str(_wav(m / "bruh.wav")),
         "hotkeys": [{"key": 112, "type": 0}, {"key": 165, "type": 0}], "modifiedDate": 0},
        {"id": 3, "name": "gone", "path": str(m / "gone.mp3"), "hotkeys": [],
         "modifiedDate": 0}]}
    songs = {"id": 2, "name": "Songs", "path": str(s), "sounds": [
        {"id": 4, "name": "midi pad", "path": str(_wav(s / "song.flac")),
         "hotkeys": [{"key": 36, "type": 2}], "modifiedDate": 0},
        {"id": 5, "name": "chord", "path": str(_wav(s / "chord.ogg")),
         "hotkeys": [65, 66], "modifiedDate": 0}]}
    cfg = tmp_path / "Soundux" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"data": {"height": 600, "soundIdCounter": 6,
                                        "tabs": [memes, songs][:tabs], "width": 800},
                               "settings": {"theme": 0}}), encoding="utf-8")
    return cfg


def test_soundux_reads_tabs_names_and_hotkeys(tmp_path):
    rows = soundux.read(_soundux_config(tmp_path))
    assert [e.name for e in rows] == ["airhorn", "bruh", "gone", "midi pad", "chord"]
    # 162 = left Ctrl, 165 = right Alt; a MIDI note and a two-key chord have no hotkey
    assert [e.hotkey for e in rows] == ["ctrl+1", "alt+f1", "", "", ""]
    assert [e.tags for e in rows] == [["Memes"]] * 3 + [["Songs"]] * 2
    assert [e.exists for e in rows] == [True, True, False, True, True]


def test_soundux_one_tab_is_no_category(tmp_path):
    assert {tuple(e.tags) for e in soundux.read(_soundux_config(tmp_path, tabs=1))} == {()}


def test_soundux_finds_its_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert soundux.default_config() is None
    cfg = _soundux_config(tmp_path)
    assert soundux.default_config() == cfg


def test_soundux_not_a_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"data": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        soundux.read(p)


# ---------------------------------------------------------------- shared
def test_dropped_files_go_to_the_right_reader(tmp_path):
    board = _exp_board(tmp_path)
    other = tmp_path / "settings.json"
    other.write_text("{}", encoding="utf-8")
    assert otherboards.for_file("C:/x/list.spl").key == "soundpad"
    assert otherboards.for_file("C:/x/Resanance.db").key == "resanance"
    assert otherboards.for_file(str(board)).key == "expboard"
    assert otherboards.for_file(str(_soundux_config(tmp_path))).key == "soundux"
    assert otherboards.for_file(str(other)) is None     # a .json that isn't a board
    assert otherboards.for_file("C:/x/song.mp3") is None


def test_every_source_has_a_box_on_the_installers_import_page():
    iss = (Path(__file__).parent.parent / "installer" / "OnionBoard.iss").read_text("utf-8")
    for src in otherboards.sources():
        assert f"AddImportBox('{src.key}'" in iss
    assert "(GetArrayLength(ImportBoxes) = 0)" in iss   # skipped when none is found
    assert "ListedIn('IMPORT'" in iss                  # silent installs: only if named
    assert otherboards.QUEUED_NAME in iss
