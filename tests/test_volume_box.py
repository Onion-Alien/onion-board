"""A volume box caps a number typed past either end instead of dropping the key that
took it there ("5000" set 500 %, "9999" 999 %, "-50" +50 %)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from soundboard.ui.kit.panel import VolumeControl


@pytest.mark.parametrize("typed, pct", [("9999", 1000), ("5000", 1000), ("-50", 0),
                                        ("-0", 0), ("350", 350), ("75", 75)])
def test_typed_volume_is_capped_not_cut(qapp, typed, pct):
    v = VolumeControl(1.0)
    got = []
    v.changed.connect(got.append)
    le = v.spin.lineEdit()
    le.selectAll()
    QTest.keyClicks(le, typed)
    QTest.keyClick(le, Qt.Key.Key_Return)
    assert v.spin.value() == pct
    assert v.spin.text() == f"{pct}%"
    assert v.slider.value() == min(pct, 300)
    assert got == ([] if pct == 100 else [pct / 100])


def test_letters_are_still_refused(qapp):
    v = VolumeControl(1.0)
    le = v.spin.lineEdit()
    le.selectAll()
    QTest.keyClicks(le, "abc")
    QTest.keyClick(le, Qt.Key.Key_Return)
    assert v.spin.value() == 100
