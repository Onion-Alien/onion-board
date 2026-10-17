"""A category hidden from All: its sounds leave the All tab (and its random sound), stay on
their own tab, and the choice follows a rename, goes with a delete and survives a restart."""
import pytest

import numpy as np
from PySide6.QtWidgets import QMenu, QMessageBox

from soundboard import library
from soundboard.i18n import _
from soundboard.library import Config, SoundMeta
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_in_view_leaves_hidden_categories_out_of_all_only():
    hidden = ["Packs"]
    assert not library.in_view(["Packs"], "", hidden=hidden)
    assert not library.in_view(["Memes", "Packs / Old"], "", hidden=hidden)
    assert library.in_view(["Memes"], "", hidden=hidden)
    assert library.in_view([], "", hidden=hidden)
    assert library.in_view(["Packs"], "Packs", hidden=hidden)   # its own tab still shows it


def test_load_keeps_only_real_categories():
    cfg = Config.from_raw({"categories": ["Packs"], "hidden_from_all": ["Packs", "Gone", 3]})
    assert cfg.hidden_from_all == ["Packs"]


def _add_pack(w):
    for i in range(2):
        m = SoundMeta(id=f"p{i}", name=f"Pack{i}", file=f"p{i}.wav", tags=["Packs"])
        w.cfg.sounds.append(m)
        w.audio[m.id] = np.zeros((480, 2), np.float32)
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    w.cfg.categories.append("Packs")
    w._rebuild_pads()
    w.catctl._fill_categories()


def _pick(w, monkeypatch, text):
    """Right-click the Packs tab and pick `text` from its Advanced menu."""
    from soundboard.ui import categorycontrol

    class Shown(QMenu):   # Qt's own exec can't be patched on the class
        def exec(self, *a):
            adv = next(a.menu() for a in self.actions()
                       if a.menu() and a.text() == _("Advanced"))
            act = next(a for a in adv.actions() if a.text() == text)
            if act.isCheckable():
                act.setChecked(not act.isChecked())
            return act
    monkeypatch.setattr(categorycontrol, "QMenu", Shown)
    tb = w.catctl.cat_tabs
    i = next(i for i in range(tb.count()) if tb.tabData(i) == "Packs")
    w.catctl._category_menu(tb.tabRect(i).center())


def test_hide_from_all_menu_hides_pads_and_random_and_undoes(window, monkeypatch):
    w = window
    _add_pack(w)
    w.catctl.set_category("")
    assert not w.pads["p0"].property("filtered")
    _pick(w, monkeypatch, _("Hide its sounds from All"))
    assert w.cfg.hidden_from_all == ["Packs"]
    assert w.pads["p0"].property("filtered") and not w.pads["s0"].property("filtered")
    assert "Packs" in w.catctl.cat_tabs.tabToolTip(0)
    played = []
    w.playctl.play = played.append
    for _i in range(8):
        w.playctl.play_random("")
    assert played and not {"p0", "p1"} & set(played)
    w.catctl.set_category("Packs")                       # its own tab still has them
    assert not w.pads["p0"].property("filtered")
    w.catctl.set_category("")
    _pick(w, monkeypatch, _("Hide its sounds from All"))   # ticked: takes it back off
    assert w.cfg.hidden_from_all == []
    assert not w.pads["p0"].property("filtered")
    assert w.catctl.cat_tabs.tabToolTip(0) == ""


def test_hidden_follows_rename_and_goes_with_delete(window, monkeypatch):
    w = window
    _add_pack(w)
    w.catctl.set_hidden_from_all("Packs", True)
    w.catctl.rename_category("Packs", "Imported")
    assert w.cfg.hidden_from_all == ["Imported"]
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    w.catctl.delete_category("Imported")
    assert w.cfg.hidden_from_all == []
    w.catctl.set_category("")
    assert not w.pads["p0"].property("filtered")          # back in All
