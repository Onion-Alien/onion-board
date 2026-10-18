"""Network activity's "Keep a history between starts" (soundboard.online.netlog.keep, config
netlog_keep, `OnionBoard.exe --keep-netlog` and the installer's box): off, nothing is
written; on, each connection is saved as it ends and the next start lists it again;
unticking deletes the file, Clear empties it. No network: entries are made by hand.
The file is read and written on netlog's file thread: netlog.wait() before looking."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from soundboard.core import app, applog
from soundboard.sounds import library
from soundboard.online import net, netlog


@pytest.fixture(autouse=True)
def fresh():
    netlog.keep(None)
    netlog.clear()
    assert netlog.wait()
    yield
    netlog.keep(None)
    netlog.clear()
    assert netlog.wait()


@pytest.fixture
def path(tmp_path) -> Path:
    return tmp_path / netlog.FILE_NAME


def done(host="example.com", feature="radio") -> netlog.Entry:
    e = netlog.begin(feature, host, 443)
    e.connected("direct")
    e.request("GET", "/x?token=abc")
    e.add_sent(10)
    e.add_received(20)
    e.closed()
    return e


def restart(path: Path) -> None:
    """What quitting and starting again does to the list."""
    netlog.flush()
    with netlog._lock:
        netlog._entries.clear()
        netlog._keep_path = None   # the new process: no list, the file still there
    netlog.keep(path)
    assert netlog.wait()


def test_off_nothing_is_written(path):
    done()
    assert not path.exists()
    assert not netlog.keeping()


def test_on_connections_are_kept_across_a_restart(path):
    netlog.keep(path)
    done("a.example.com")
    netlog.blocked("radio", "b.example.com", 443, "switched off")
    netlog.begin("radio", "c.example.com", 80).failed("refused")
    restart(path)
    items = netlog.entries()
    assert [e.host for e in items] == ["a.example.com", "b.example.com", "c.example.com"]
    assert [e.state for e in items] == [netlog.CLOSED, netlog.BLOCKED, netlog.FAILED]
    a = items[0]
    assert (a.sent, a.received, a.route) == (10, 20, "direct")
    assert a.requests == ["GET /x?token=•••"]   # saved masked, like it's shown
    assert [e.n for e in items] == [1, 2, 3]
    done("d.example.com")                        # numbering carries on
    assert netlog.entries()[-1].n == 4


def test_one_still_open_at_quit_is_saved_once(path):
    netlog.keep(path)
    e = netlog.begin("radio", "stream.example.com", 443)
    e.connected("direct")
    netlog.flush()        # quit with the stream still playing
    e.add_received(5)
    e.closed()            # ...and it closes afterwards: saved again
    restart(path)
    items = netlog.entries()
    assert len(items) == 1 and items[0].state == netlog.CLOSED
    assert items[0].received == 5


def test_open_at_quit_and_never_closed_is_listed_as_done(path):
    netlog.keep(path)
    netlog.begin("radio", "stream.example.com", 443).connected("direct")
    restart(path)
    (e,) = netlog.entries()
    assert e.state == netlog.CLOSED and e.ended and "still open" in e.reason


def test_ticking_it_mid_run_saves_what_is_listed_so_far(path):
    done("early.example.com")
    netlog.keep(path)
    assert netlog.wait()
    assert "early.example.com" in path.read_text(encoding="utf-8")


def test_unticking_deletes_the_file_but_keeps_this_runs_list(path):
    netlog.keep(path)
    done()
    assert netlog.wait()
    path.with_name(path.name + ".old").write_text("", encoding="utf-8")
    netlog.keep(None)
    assert netlog.wait()
    assert not path.exists() and not path.with_name(path.name + ".old").exists()
    assert len(netlog.entries()) == 1
    done("after.example.com")
    assert netlog.wait()
    assert not path.exists()
    netlog.keep(path)     # ticked again: saved back
    assert netlog.wait()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_clear_empties_the_kept_history(path):
    netlog.keep(path)
    done()
    netlog.clear()
    assert netlog.wait()
    assert not path.exists()
    restart(path)
    assert netlog.entries() == []


def test_a_damaged_line_is_skipped(path):
    netlog.keep(path)
    done("good.example.com")
    assert netlog.wait()
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not json\n")
        f.write(json.dumps({"n": "x", "started": "soon"}) + "\n")
        f.write(json.dumps({"n": 9, "started": 1.0, "feature": "radio", "host": "h",
                            "port": 1, "how": "app", "state": "closed",
                            "future_field": 1}) + "\n")   # a newer version's line
    restart(path)
    assert [e.host for e in netlog.entries()] == ["good.example.com", "h"]


def test_a_big_file_moves_aside_and_both_are_read(path, monkeypatch):
    netlog.keep(path)
    done("h0.example.com")
    assert netlog.wait()
    # the limit from a real line's size (it differs between machines): 3 lines a file
    monkeypatch.setattr(netlog, "MAX_FILE_BYTES", path.stat().st_size * 2 + 1)
    for i in range(1, 10):
        done(f"h{i}.example.com")
    assert netlog.wait()
    assert path.with_name(path.name + ".old").exists()
    restart(path)
    assert [e.host for e in netlog.entries()][-3:] == [
        "h7.example.com", "h8.example.com", "h9.example.com"]


def test_only_the_last_max_entries_are_listed(path, monkeypatch):
    monkeypatch.setattr(netlog, "MAX_ENTRIES", 5)
    netlog.keep(path)
    for i in range(8):
        done(f"h{i}.example.com")
    restart(path)
    assert [e.host for e in netlog.entries()] == [f"h{i}.example.com" for i in range(3, 8)]


def test_the_view_says_whether_its_kept(qapp, path):
    from soundboard.ui.settings.netactivity import NOTE, NOTE_KEPT, NetActivity, _when
    w = NetActivity()
    assert w.note.text() == NOTE
    netlog.keep(path)
    assert netlog.wait()
    w.refresh(force=True)
    assert w.note.text() == NOTE_KEPT
    assert "yet" in w.summary.text()
    assert ":" in _when(0) and len(_when(0)) > 8   # another day: the date too


# --------------------------------------------------------------------------- totals

def test_site_groups_subdomains():
    assert netlog.site("r3---sn-abc.googlevideo.com") == "googlevideo.com"
    assert netlog.site("www.bbc.co.uk") == "bbc.co.uk"
    assert netlog.site("example.com") == "example.com"
    assert netlog.site("127.0.0.1") == "127.0.0.1"
    assert netlog.site("::1") == "::1"
    assert netlog.site("localhost") == "localhost"


def test_totals_add_up_every_saved_connection_not_just_the_list(path, monkeypatch):
    monkeypatch.setattr(netlog, "MAX_ENTRIES", 3)
    netlog.keep(path)
    for i in range(5):
        done(f"h{i}.example.com")
    netlog.blocked("radio", "radio.example.org", 80, "switched off")
    restart(path)
    assert len(netlog.entries()) == 3              # the list: only the last few
    items = netlog.history()
    assert len(items) == 6                         # the totals: the whole file
    a, b = netlog.totals(items)
    assert (a.name, a.connections, a.sent, a.received) == ("example.com", 5, 50, 100)
    assert len(a.hosts) == 5 and a.first <= a.last
    assert (b.name, b.blocked, b.data) == ("example.org", 1, 0)
    per_server = netlog.totals(items, by_site=False)
    assert len(per_server) == 6
    text = netlog.totals_text([a, b], "head")
    assert text.splitlines()[0] == "head"
    assert text.splitlines()[2].split("\t")[:6] == ["example.com", "5", "0", "0", "50",
                                                    "100"]


def test_totals_without_a_history_are_this_runs_list():
    done("a.example.com")
    assert netlog.kept_file() is None
    assert [e.host for e in netlog.history()] == ["a.example.com"]


def test_the_view_has_totals_and_open_log(qapp, path):
    from soundboard.ui.settings.netactivity import NetActivity, TotalsDialog
    w = NetActivity()
    assert not w.totals.isEnabled() and not w.open_log.isEnabled()
    done("a.example.com")
    done("b.example.com")
    done("c.example.net")
    w.refresh(force=True)
    # nothing saved: Open log shows this run's list in a window, writing nothing
    assert w.totals.isEnabled() and w.open_log.isEnabled()
    assert "Keep a history" in w.open_log.toolTip()
    w._open_log()
    from soundboard.ui.settings.netactivity import LogDialog
    shown = [d for d in qapp.topLevelWidgets() if isinstance(d, LogDialog)]
    assert shown and "c.example.net" in shown[-1].text.toPlainText()
    assert netlog.kept_file() is None
    shown[-1].close()
    netlog.keep(path)
    assert netlog.wait()
    w.refresh(force=True)
    assert w.open_log.isEnabled() and netlog.kept_file() == path
    d = TotalsDialog()
    assert netlog.wait()
    qapp.processEvents()   # the totals, handed over from the file thread
    assert d.table.rowCount() == 2 and d.table.item(0, 0).text() == "example.com"
    assert "3 connections to 2 sites" in d.summary.text()
    assert d.table.item(0, 1).text() == "2"
    d.by_site.setChecked(False)
    assert d.table.rowCount() == 3
    assert d.table.horizontalHeaderItem(0).text() == "Server"
    d._copy()
    assert "c.example.net" in qapp.clipboard().text()
    d.deleteLater()
    w.deleteLater()


def _hold_the_file_thread():
    """Keeps netlog's file thread busy until the event is set (as a slow disk would)."""
    go = threading.Event()
    netlog._io(go.wait, 10)
    return go


def test_totals_read_the_file_off_the_ui_thread(qapp, path, monkeypatch):
    from soundboard.ui.settings.netactivity import TotalsDialog
    netlog.keep(path)
    done("a.example.com")
    done("b.example.net")
    restart(path)
    reads = []
    real_read = netlog._read
    monkeypatch.setattr(netlog, "_read", lambda *a, **k: (
        reads.append(threading.current_thread()), real_read(*a, **k))[1])
    go = _hold_the_file_thread()
    d = TotalsDialog()             # refresh() asks, and returns without reading
    assert reads == [] and d.table.rowCount() == 0
    assert d.summary.text() == "Loading…" and not d.copy.isEnabled()
    go.set()
    assert netlog.wait()
    qapp.processEvents()           # the totals arrive through the signal
    assert reads and threading.main_thread() not in reads
    assert d.table.rowCount() == 2 and "2 connections to 2 sites" in d.summary.text()
    reads.clear()
    d.by_site.setChecked(False)    # grouping again adds up what was read: no new read
    assert reads == [] and d.table.rowCount() == 2
    d.deleteLater()


def test_totals_arriving_after_the_window_closed_are_dropped(qapp, path):
    from shiboken6 import delete
    from soundboard.ui.settings.netactivity import TotalsDialog
    netlog.keep(path)
    done()
    go = _hold_the_file_thread()
    d = TotalsDialog()
    delete(d)                      # closed while the file was being read
    go.set()
    assert netlog.wait()
    qapp.processEvents()           # nothing to show it on: no crash, nothing raised


def test_saving_never_waits_for_the_file(path, monkeypatch):
    netlog.keep(path)
    assert netlog.wait()
    go = _hold_the_file_thread()   # mid-move to .old, say
    done("a.example.com")          # ended on the UI thread: queued, not written here
    netlog.blocked("radio", "b.example.com", 443, "switched off")
    assert not path.exists()
    go.set()
    assert netlog.wait()
    text = path.read_text(encoding="utf-8")
    assert "a.example.com" in text and "b.example.com" in text


def test_ticking_it_lists_the_saved_ones_once_read(path):
    netlog.keep(path)
    done("old.example.com")
    restart(path)
    with netlog._lock:
        netlog._entries.clear()
        netlog._keep_path = None
    go = _hold_the_file_thread()
    netlog.keep(path)              # returns at once: nothing read yet
    assert netlog.entries() == []
    go.set()
    assert netlog.wait()
    assert [e.host for e in netlog.entries()] == ["old.example.com"]


def test_unticked_before_the_file_was_read(path):
    netlog.keep(path)
    done("old.example.com")
    restart(path)
    with netlog._lock:
        netlog._entries.clear()
        netlog._keep_path = None
    go = _hold_the_file_thread()
    netlog.keep(path)
    netlog.keep(None)              # changed their mind: the late read lists nothing
    go.set()
    assert netlog.wait()
    assert netlog.entries() == [] and not path.exists()


# --------------------------------------------------------------------------- the switch

@pytest.fixture
def cli(app_dir, monkeypatch):
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: pytest.fail("went online"))
    return app_dir


def test_keep_netlog_switches_it_on_and_keeps_other_settings(cli):
    cfg = library.Config()
    cfg.sound_vol, cfg.setup_done = 0.42, True
    assert cfg.save()
    assert library.Config.load().netlog_keep is False   # off by default
    assert app.keep_netlog() == 0
    cfg = library.Config.load()
    assert cfg.netlog_keep and cfg.sound_vol == 0.42 and cfg.setup_done
    assert app.keep_netlog() == 0


def test_keep_netlog_fails_on_a_locked_or_unsaved_config(cli, monkeypatch):
    monkeypatch.setattr(library.Config, "save", lambda self: False)
    assert app.keep_netlog() == 1


def test_the_installer_wires_it_up():
    iss = Path(__file__).parent.parent / "installer" / "OnionBoard.iss"
    iss = iss.read_text(encoding="utf-8")
    assert "--keep-netlog" in iss
    assert "{param:KEEPNETLOG|0}" in iss and "Check: KeepNetlogParam" in iss
