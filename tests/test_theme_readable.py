"""Words and icons on a switched-on button, accent links and live text read in every
theme and with a picked highlight colour; open pop-ups follow a theme switch."""
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QLabel, QPushButton

from soundboard import theme
from soundboard.ui import icons

PICKED = ("", "#ff0000", "#808080", "#ffff00", "#00aa55", "#3355ff", "#ffffff", "#000000")


def _tokens(name: str, live: str) -> dict[str, str]:
    t = dict(theme.THEMES[name])
    if live:
        theme._add_live_tokens(t, live)
    return t


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_a_switched_on_buttons_words_read_on_every_shade_of_it(name):
    """White on Dark's lit gradient top was 3.37:1, on Mint's hover 3.31:1: the plain,
    hovered and lit-top live fills all keep on_live at 4.5:1, a picked colour too."""
    for live in PICKED:
        t = _tokens(name, live)
        for fill in ("live", "live_hover", "live_top"):
            assert theme._contrast(t["on_live"], t[fill]) >= 4.5, (live, fill)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_the_filled_accent_reads(name):
    """Dark's white on its accent was 4.35:1."""
    t = theme.tokens(name)
    assert theme._contrast(t["on_accent"], t["accent"]) >= 4.5


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_buttons_and_boxes_on_a_card_stand_out_from_it(name):
    """Light's card buttons were filled with the card's own white on a white card: the
    Setup tab's Install / check again / Game read as plain text."""
    css = theme.stylesheet(name)
    rule = next(r for r in css.splitlines()
                if r.startswith("QFrame#card QComboBox, QFrame#card QPushButton"))
    fill = rule.split("background:")[1].split(";")[0].strip()
    assert fill != theme.THEMES[name]["panel"], fill


@pytest.mark.parametrize("name", [n for n in theme.THEMES if theme.is_light(n)])
def test_a_light_themes_buttons_and_boxes_show_on_every_surface(name):
    """Light's buttons were 1.06:1 on the window (a pop-up's Done read as words) and its
    boxes white on the white panels (Radio's filters, Remote's Port)."""
    t = theme.THEMES[name]
    for surface in ("bg", "panel"):
        assert theme._contrast(t["btn"], t[surface]) >= 1.12, surface
    assert theme._contrast(t["card_ctl"], t["panel"]) >= 1.10


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_live_text_reads_on_every_surface_it_sits_on(name):
    """live_text was checked against the window only: 3.53:1 on Dark's hovered card."""
    for live in PICKED:
        t = _tokens(name, live)
        if t["live_text"] != t["text_hi"]:
            for bg in theme.TEXT_ON:
                assert theme._contrast(t["live_text"], t[bg]) >= 4.5, (live, bg)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_accent_links_and_values_read(name):
    """Flashbang's privacy links were yellow on white (1.4:1); Mint's effect values
    3.2:1. accent_link is 4.5:1 on every surface words in the accent sit on."""
    t = theme.tokens(name)
    for bg in theme.TEXT_ON + ("item_hover",):
        assert theme._contrast(t["accent_link"], t[bg]) >= 4.5, bg
    css = theme.stylesheet(name)
    for rule in ("QLabel#fxvalue { color:", "QMenu::item:checked { color:"):
        assert css.split(rule, 1)[1].startswith(t["accent_link"]), rule


def _on_colours(button) -> set[str]:
    img = button.icon().pixmap(QSize(18, 18), QIcon.Mode.Normal, QIcon.State.On).toImage()
    return {QColor.fromRgba(img.pixel(x, y)).name() for x in range(img.width())
            for y in range(img.height()) if QColor.fromRgba(img.pixel(x, y)).alpha() > 200}


def test_a_switched_on_icon_follows_the_words_and_a_picked_colour(qapp):
    """The Voice switch's mic stayed white on High Contrast's yellow (1.07:1): icons on
    a live fill are drawn in on_live, and re-drawn when the user picks a colour."""
    b = QPushButton("On")
    b.setCheckable(True)
    try:
        theme.set_current("High Contrast")
        icons.set_icon(b, "mic", checked_color="on_live")
        assert theme.T["on_live"] in _on_colours(b) and "#ffffff" not in _on_colours(b)
        theme.set_live("#ffff00")
        theme.T.clear()
        theme.T.update(theme.tokens())
        icons.retheme_live()
        assert theme.T["on_live"] in _on_colours(b)
        theme.set_live("#3355ff")
        theme.T.clear()
        theme.T.update(theme.tokens())
        icons.retheme_live()
        assert theme.T["on_live"] == "#ffffff"
        assert min(QColor(c).lightness() for c in _on_colours(b)) > 180   # white now
    finally:
        theme.set_live("")
        theme.set_current(theme.DEFAULT)


def test_send_is_on_in_the_live_colour_not_recording_red():
    """Radio's and Apps' Send used a fixed red, whatever the theme or picked colour."""
    css = theme.stylesheet("Dark")
    send = css.split("QPushButton#live:checked", 1)[1].split("}", 1)[0]
    assert "#d32f2f" not in send and "$" not in send and theme.T["live"] in send
    assert "live" in theme.LIVE_NAMES
    assert "#d32f2f" in css.split("QPushButton#rec:checked", 1)[1].split("}", 1)[0]


def test_source_details_follow_a_theme_switch_while_open(qapp):
    """Left open across Light -> Dark, the details kept Light's inner-area colour behind
    the missing picture and Light's dark icons on Open and Copy link."""
    from soundboard.library import SoundMeta
    from soundboard.ui import sourcedialog
    src = dict(link="https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Song",
               channel="Someone", channel_link="https://www.youtube.com/@someone")
    app = qapp
    try:
        theme.apply(app, "Light")
        icons.retheme()
        d = sourcedialog.SourceDialog(SoundMeta(id="a", name="Song", file="x.mp3", source=src))
        d.resize(560, 300)
        d.ensurePolished()
        theme.apply(app, "Dark")
        icons.retheme()
        pic = d.findChild(QLabel, "sourcepic")
        assert pic is not None and not pic.styleSheet()
        d.show()
        qapp.processEvents()
        x = pic.mapTo(d, pic.rect().center()).x()
        y = pic.mapTo(d, pic.rect().topLeft()).y() + 4   # above the site's icon
        assert QColor(d.grab().toImage().pixel(x, y)).name() == theme.T["inset"]
        assert theme.T["on_accent"] in _on_colours_normal(d.btn_open)
        assert theme.T["text"] in _on_colours_normal(d.btn_copy)
        assert theme.tokens("Light")["text"] not in _on_colours_normal(d.btn_copy)
        d.close()
    finally:
        theme.apply(app, theme.DEFAULT)
        icons.retheme()


def _on_colours_normal(button) -> set[str]:
    img = button.icon().pixmap(QSize(18, 18)).toImage()
    return {QColor.fromRgba(img.pixel(x, y)).name() for x in range(img.width())
            for y in range(img.height()) if QColor.fromRgba(img.pixel(x, y)).alpha() > 200}
