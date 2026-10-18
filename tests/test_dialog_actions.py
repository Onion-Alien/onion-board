"""Dialog footers sit bottom-right: a stretch, then the actions with the main (filled)
one first, then the others and Cancel/Done/Close (DESIGN section 0)."""
from types import SimpleNamespace

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QPushButton

from soundboard import usage
from soundboard.sounds.library import SoundMeta
from soundboard.ui import countdialog, feedbackdialog, sourcedialog

from test_sourceinfo import SRC


def x(widget, dialog):
    return widget.mapTo(dialog, QPoint(0, 0)).x()


def assert_bottom_right(dialog, *buttons, gap=40):
    """These buttons in this order left to right, packed against the right edge, with
    empty room before the first (`gap=0` when something sits on the left)."""
    xs = [x(b, dialog) for b in buttons]
    assert xs == sorted(xs), xs
    assert xs[0] > gap, (xs, dialog.width())   # not left-aligned
    last = buttons[-1]
    assert dialog.width() - (x(last, dialog) + last.width()) < 40


def button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


def test_feedback_footers_are_bottom_right_main_first(qapp, monkeypatch):
    monkeypatch.setattr(usage, "improve", lambda *a, **k: False)
    d = feedbackdialog.FeedbackDialog(SimpleNamespace())
    d.show()
    qapp.processEvents()
    assert d.send_btn.objectName() == "primary" and d.send_btn.isDefault()
    assert_bottom_right(d, d.send_btn, button(d, "Cancel"))
    d.boxes["speed"].setChecked(True)
    d.send_btn.click()
    qapp.processEvents()
    assert d.form_btn.objectName() == "primary"
    assert_bottom_right(d, d.form_btn, button(d, "Done"))
    d.deleteLater()


def test_count_me_in_done_is_bottom_right(qapp):
    d = countdialog.CountDialog()
    d.show()
    qapp.processEvents()
    done = button(d, "Done")
    assert done.isDefault()
    assert_bottom_right(d, done)
    d.deleteLater()


def test_source_box_actions_bottom_right_bin_left_and_last_in_focus(qapp):
    d = sourcedialog.SourceDialog(SoundMeta(id="a", name="Song", file="x.mp3",
                                            source=dict(SRC)))
    d.show()
    qapp.processEvents()
    close = button(d, "Close")
    assert d.btn_open.objectName() == "primary"
    assert d.focusWidget() is d.btn_open   # Enter opens the link, never Delete info
    # its long "Open on <site>" fills most of a narrow box: flush right, bin on the left
    assert_bottom_right(d, d.btn_open, d.btn_copy, close, gap=0)
    assert x(d.btn_forget, d) + d.btn_forget.width() < x(d.btn_open, d)
    assert x(d.btn_forget, d) < d.width() / 4   # Delete info stays beside the details
    mine = (d.btn_open, d.btn_copy, close, d.btn_forget)
    chain, w = [], d.btn_open   # Tab order: Open, Copy link, Close, then the bin
    while len(chain) < 4:
        if w in mine and w not in chain:
            chain.append(w)
        w = w.nextInFocusChain()
    assert chain == list(mine)
    d.close()
