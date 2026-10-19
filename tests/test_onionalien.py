"""The Onion Alien's note (ui/onionalien.AlienNote): typed out a letter at a time each
time it's shown, a click shows it all, and its height is the whole text's from the
first letter. Offscreen, stepped by hand: no timers are waited on."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.ui.bun.onionalien import AlienNote, alien_image


def paint(w):
    img = QImage(w.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    w.render(img)
    return img


def test_alien_image_draws_him():
    img = alien_image(96)
    assert img.height() == 96
    assert img.pixelColor(img.width() // 2, 60).alpha() == 255   # his middle
    assert img.pixelColor(1, 1).alpha() == 0                     # transparent round him


def test_types_out_then_finishes(qapp):
    note = AlienNote("Hi. Have fun.\n\nOnionAlien")
    note.resize(500, note.heightForWidth(500))
    note.show()
    assert note.shown == 0 and note.typing
    for _ in range(3):
        note._tick()
    assert note.shown == 3 and note.typing
    paint(note)                       # paints halfway through a line
    note._tick()                      # "." holds a beat before the next letter
    assert note.shown == 3
    note.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5),
                                     QPointF(5, 5), Qt.MouseButton.LeftButton,
                                     Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
    assert note.shown == len(note.text) and not note.typing
    assert not note._timer.isActive()
    paint(note)
    note.hide()
    note.show()                       # shown again: types out again
    assert note.shown == 0
    note.hide()
    assert not note._timer.isActive()
    QApplication.processEvents()


def test_height_fits_whole_text_and_wraps_narrow(qapp):
    note = AlienNote("No ads, no account, no spying, free forever. Found a bug? "
                     "Tell me. Have fun.\n\nOnionAlien")
    wide, narrow = note.heightForWidth(1100), note.heightForWidth(300)
    assert wide >= note.ALIEN_H
    assert narrow > wide              # wraps onto more lines, so taller
    note.resize(300, narrow)
    paint(note)


def test_clicks_make_him_cry_then_eat_the_window(qapp):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    win = QWidget()
    win.resize(500, 400)
    note = AlienNote("Hi.")
    QVBoxLayout(win).addWidget(note)
    win.show()
    QApplication.processEvents()
    for _ in range(9):
        note.poke()
    assert note.tears() == ()
    note.poke()                                   # 10: one tear
    assert len(note.tears()) == 1
    note.set_tear_ms(900)
    paint(note)
    note.set_tear_ms(5000)                        # dried up
    assert note.tears() == () and not note._tear_timer.isActive()
    for _ in range(40):
        note.poke()                               # 50: two tears
    assert len(note.tears()) == 2
    note.set_tear_ms(99_999)
    for _ in range(49):
        note.poke()
    assert note.gulp is None
    note.poke()                                   # 100: he eats the window
    gulp = note.gulp
    assert gulp is not None and gulp.isVisible() and note.hidden_alien
    assert note.clicks == 0
    note.poke()                                   # clicks while he's out do nothing
    assert note.clicks == 0
    gulp._timer.stop()
    for t in (0, gulp.HOP_MS / 2, gulp.HOP_MS + 1000, gulp.blank_at + 10,
              gulp.spit_at + 1000, gulp.home_at + 100):
        gulp.set_t(t)
        img = QImage(gulp.size(), QImage.Format.Format_ARGB32)
        gulp.render(img)
    gulp.set_t(gulp.blank_at + 10)
    assert all(gulp._piece_at(i) is None for i in range(len(gulp.pieces)))   # all gone
    gulp.set_t(gulp.blank_at + 1000)
    QTest.keyClicks(gulp, "onion")
    assert gulp.t == gulp.blank_at + 1000         # not yet
    QTest.keyClicks(gulp, "Alien Please")         # "onionalien please": give it back
    assert gulp.t == gulp.spit_at - gulp.OPEN_MS
    gulp.set_t(gulp.end)                          # spat back, home again
    assert note.gulp is None and not note.hidden_alien and not gulp.isVisible()
    win.close()
    QApplication.processEvents()
