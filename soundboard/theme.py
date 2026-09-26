"""Colour themes and the app logo.

A theme is a set of named colour tokens. The Qt stylesheet is built from them, and
the hand-painted widgets (pads, meters, EQ curve, logo) read the same tokens through
`T` when they paint, so switching theme recolours everything live.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)

THEMES: dict[str, dict[str, str]] = {
    "Dark": dict(
        bg="#15171f", panel="#1c1f2a", card="#232633", card_hi="#2b2f3f",
        btn="#2a2e3d", btn_hover="#333849", btn_press="#3c4257",
        border="#363b4e", border_hi="#5a6080", groove="#343849", inset="#1b1d26",
        text="#e6e8f0", text_hi="#f1f3f9", muted="#8a90a6", faint="#6b7189", section="#8f96b3",
        accent="#7c5cff", accent_hi="#8d71ff", accent2="#ff4d8d", on_accent="#ffffff",
        off="#4a5068", badge="#343849", badge_text="#d6d9e6",
        danger_bg="#3a2230", danger_border="#5a2a3e", danger_text="#ff8fa3", danger_hover="#4a2a3c",
        warn_bg="#3a2e14", warn_text="#ffb020",
    ),
    "Light": dict(
        bg="#eef0f6", panel="#ffffff", card="#ffffff", card_hi="#f4f5fa",
        btn="#e7eaf2", btn_hover="#dde1ec", btn_press="#d0d6e4",
        border="#cfd5e2", border_hi="#8f98b3", groove="#d5dae6", inset="#e3e7f0",
        text="#1d2130", text_hi="#11141f", muted="#5c637c", faint="#8a90a6", section="#6a7190",
        accent="#6a4cff", accent_hi="#7d62ff", accent2="#ff3d7f", on_accent="#ffffff",
        off="#b3b9cc", badge="#e3e7f0", badge_text="#2a2f40",
        danger_bg="#ffe8ec", danger_border="#f3b3c0", danger_text="#c4213f", danger_hover="#ffd9e0",
        warn_bg="#fff1d6", warn_text="#9a5b00",
    ),
    "Toxic": dict(   # green on near-black
        bg="#0b120e", panel="#111b15", card="#16241c", card_hi="#1c2e23",
        btn="#182a1f", btn_hover="#1f3627", btn_press="#274230",
        border="#27402f", border_hi="#3f6a50", groove="#223829", inset="#0e1711",
        text="#e0f5e8", text_hi="#f0fff5", muted="#7fa08c", faint="#5b7b67", section="#86b597",
        accent="#1ee07f", accent_hi="#45ef98", accent2="#c6ff3d", on_accent="#04140b",
        off="#3a5646", badge="#223829", badge_text="#cfeedd",
        danger_bg="#361d22", danger_border="#5a2a33", danger_text="#ff8f9e", danger_hover="#45242a",
        warn_bg="#33301a", warn_text="#ffc53d",
    ),
    "Ocean": dict(   # cyan on deep navy
        bg="#0c131d", panel="#111a27", card="#162234", card_hi="#1c2b41",
        btn="#182638", btn_hover="#1f3048", btn_press="#273b57",
        border="#263a54", border_hi="#3d5f86", groove="#22354d", inset="#0e1622",
        text="#e1ecf8", text_hi="#f2f8ff", muted="#7f96b2", faint="#5c738f", section="#87a4c6",
        accent="#1fb6ff", accent_hi="#4cc6ff", accent2="#7c5cff", on_accent="#031320",
        off="#3a4f69", badge="#22354d", badge_text="#d3e3f5",
        danger_bg="#361f2b", danger_border="#5a2a40", danger_text="#ff8fb0", danger_hover="#45243a",
        warn_bg="#33301f", warn_text="#ffb020",
    ),
}
DEFAULT = "Dark"

T: dict[str, str] = dict(THEMES[DEFAULT])   # current theme (read at paint time)
current_name = DEFAULT


def set_current(name: str) -> str:
    global current_name
    name = name if name in THEMES else DEFAULT
    T.clear()
    T.update(THEMES[name])
    current_name = name
    return name


STYLE = Template("""
QWidget { background:$bg; color:$text; font-family:'Segoe UI'; font-size:10pt; }
QDialog { background:$bg; }
QFrame#card { background:$panel; border-radius:12px; }
QFrame#card QWidget { background:transparent; }
QLabel#section { color:$section; font-size:8pt; font-weight:700; letter-spacing:1px; padding-top:8px; }
QLabel#hint, QLabel#muted { color:$muted; }
QLabel#hint { font-size:8.5pt; }
QLabel#eqlabel { color:$muted; font-size:8pt; }
QLabel#empty { color:$faint; font-size:15px; padding:60px; }
QFrame#card QLabel#stepbox { background:$bg; border-radius:8px; padding:8px; margin-top:6px; }
QFrame#card QLabel#resultbox { background:$bg; border-radius:8px; padding:8px; }
QLabel#wordmark { font-size:13pt; font-weight:800; letter-spacing:2px; color:$text_hi; background:transparent; }
QLabel#tagline { color:$muted; font-size:8.5pt; background:transparent; }
QPushButton { background:$btn; border:1px solid $border; border-radius:8px; padding:7px 12px; }
QPushButton:hover { background:$btn_hover; }
QPushButton:pressed { background:$btn_press; }
QPushButton:checked { background:$accent; border-color:$accent; color:$on_accent; }
QPushButton:disabled { color:$muted; }
QPushButton#primary { background:$accent; border:none; color:$on_accent; font-weight:600; }
QPushButton#primary:hover { background:$accent_hi; }
QPushButton#danger { background:$danger_bg; border:1px solid $danger_border; color:$danger_text; font-weight:600; }
QPushButton#danger:hover { background:$danger_hover; }
QPushButton#small { padding:2px 8px; font-size:8pt; }
QPushButton#settings { padding:6px 14px; font-weight:600; }
QFrame#transport { background:$panel; border-radius:12px; }
QFrame#card QPushButton#primary { background:$accent; color:$on_accent; border:none; padding:9px; }
QFrame#card QPushButton#primary:hover { background:$accent_hi; }
QFrame#vsep { background:$border; border:none; }
QFrame#chip { background:$panel; border:1px solid $border; border-radius:14px; }
QFrame#chip[sel="true"] { border-color:$accent; }
QFrame#chip QPushButton { background:transparent; border:none; padding:2px 6px; }
QFrame#chip QPushButton#chipname { font-weight:600; }
QFrame#chip QPushButton#chipstop { border-radius:12px; padding:0; }
QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; }
QLabel#iconlabel { background:transparent; }
QPushButton#pill { border-radius:15px; padding:5px 14px; font-weight:600; }
QPushButton#pill[state="ok"] { color:#13ce66; border:1px solid #1c6b45; }
QPushButton#onair { border-radius:15px; padding:5px 14px; font-weight:700;
    background:$danger_bg; border:1px solid $danger_border; color:$danger_text; }
QPushButton#onair:checked { background:#13a35a; border:1px solid #13ce66; color:white; }
QPushButton#onair:checked:hover { background:#16b865; }
QWidget#decktop { background:transparent; }
QLabel#decktitle { color:$section; font-size:8pt; font-weight:700; letter-spacing:1px; }
QPushButton#pill[state="warn"] { background:$warn_bg; color:$warn_text; border:1px solid $warn_text; }
QSpinBox { background:$bg; border:1px solid $border; border-radius:6px; padding:3px 4px; }
QSpinBox::up-button, QSpinBox::down-button { width:0; }
QSlider::groove:vertical { width:4px; background:$groove; border-radius:2px; }
QSlider::add-page:vertical { background:$accent; border-radius:2px; }
QSlider::handle:vertical { background:white; border:1px solid $border; width:14px; height:14px; margin:0 -5px; border-radius:7px; }
QPushButton#micbanner { background:#e53935; color:white; font-weight:700; font-size:11pt;
    border:none; border-radius:10px; padding:10px; }
QPushButton#miccheck:checked { background:#e53935; border:1px solid #ff6b6b; color:white;
    font-weight:700; }
QFrame#transport QLabel, QFrame#transport QCheckBox, QFrame#transport QSlider { background:transparent; }
QPushButton#round { padding:0; font-size:14pt; border-radius:10px; }
QSlider#seek::groove:horizontal { height:6px; border-radius:3px; }
QSlider#seek::sub-page:horizontal { border-radius:3px; }
QLineEdit, QComboBox { background:$card; border:1px solid $border; border-radius:8px; padding:6px 8px; }
QFrame#card QComboBox, QFrame#card QPushButton, QFrame#card QLineEdit { background:$card; }
QFrame#card QSpinBox { background:$bg; }
QFrame#card QPushButton:checked { background:$accent; }
QFrame#card QPushButton#miccheck:checked { background:#e53935; }
QComboBox QAbstractItemView { background:$card; selection-background-color:$accent; selection-color:$on_accent; }
QSlider::groove:horizontal { height:4px; background:$groove; border-radius:2px; }
QSlider::sub-page:horizontal { background:$accent; border-radius:2px; }
QSlider::handle:horizontal { background:white; border:1px solid $border; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QCheckBox::indicator, QRadioButton::indicator { width:16px; height:16px; border-radius:4px; border:1px solid $off; background:$card; }
QRadioButton::indicator { border-radius:8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background:$accent; border-color:$accent; }
QCheckBox::indicator:checked { image:url("$check"); }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color:$border_hi; }
QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover { background:$accent_hi; border-color:$accent_hi; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background:$inset; border-color:$border; }
QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; }
QScrollBar::handle:vertical { background:$groove; border-radius:5px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QMenu { background:$card; border:1px solid $border; padding:4px; }
QMenu::item { padding:6px 18px; border-radius:6px; }
QMenu::item:selected { background:$accent; color:$on_accent; }
QToolTip { background:$card; color:$text; border:1px solid $border; }
QTabWidget::pane { border:none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background:transparent; color:$muted; padding:8px 16px; margin-right:4px;
    border:none; border-bottom:2px solid transparent; font-weight:600; }
QTabBar::tab:selected { color:$text; border-bottom:2px solid $accent; }
QTabBar::tab:hover { color:$text; }
QPushButton#live { font-weight:700; }
QPushButton#voicetile { text-align:left; padding:9px 10px; border-radius:10px; }
QPushButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QPushButton#power { font-weight:700; }
QPushButton#power:checked, QFrame#card QPushButton#power:checked { background:#13a35a; border:1px solid #13ce66; color:white; }
QPushButton#live:checked { background:#e53935; border:1px solid #ff6b6b; color:white; }
QPushButton#rec:checked { background:#e53935; border:1px solid #ff6b6b; color:white; font-weight:700; }
QPushButton#lite:checked { background:#13a35a; border:1px solid #13ce66; color:white; font-weight:700; }
QFrame#setcard { background:$panel; border-radius:12px; }
QFrame#setcard QWidget { background:transparent; }
QPushButton#hkbtn { min-width:150px; font-weight:600; }
QPushButton#themecard { background:$panel; border:2px solid $border; border-radius:12px; padding:0; }
QPushButton#themecard:hover { border-color:$border_hi; }
QPushButton#themecard:checked { background:$panel; border:2px solid $accent; }
""")


def _check_image(colour: str, size: int) -> QImage:
    """A rounded tick, drawn in code so it follows the theme's on-accent colour."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour), size * 0.16)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(size * 0.22, size * 0.52))
    path.lineTo(QPointF(size * 0.42, size * 0.72))
    path.lineTo(QPointF(size * 0.78, size * 0.30))
    p.drawPath(path)
    p.end()
    return img


def _check_url(colour: str) -> str:
    """Stylesheets need a file for `image:`, so write the tick (plus an @2x copy Qt picks
    on high-DPI screens) to the temp folder once per colour."""
    folder = Path(tempfile.gettempdir()) / "soundboard-ui"
    base = folder / f"check-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 14), (base.with_name(base.stem + "@2x.png"), 28)):
            if not path.exists():
                _check_image(colour, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def stylesheet(name: str | None = None) -> str:
    tokens = dict(THEMES.get(name or current_name, THEMES[DEFAULT]))
    tokens["check"] = _check_url(tokens["on_accent"])
    return STYLE.substitute(tokens)


def apply(app, name: str) -> str:
    """Switch the whole app to theme `name` (live)."""
    name = set_current(name)
    app.setStyleSheet(stylesheet(name))
    for w in app.allWidgets():   # hand-painted widgets read T in paintEvent
        w.update()
    return name


# --------------------------------------------------------------------------- logo

def paint_logo(p: QPainter, rect: QRectF, c1: str, c2: str):
    """The Onion Board mark: a gradient squircle holding an onion whose layers
    are drawn as sound-wave arcs — onion + soundboard in one shape."""
    s = rect.width()
    x0, y0 = rect.left(), rect.top()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    # body
    g = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    body = QPainterPath()
    body.addRoundedRect(QRectF(x0 + s * 0.04, y0 + s * 0.04, s * 0.92, s * 0.92), s * 0.26, s * 0.26)
    p.fillPath(body, g)
    # soft top highlight
    hi = QLinearGradient(QPointF(x0, y0), QPointF(x0, y0 + s * 0.6))
    hi.setColorAt(0.0, QColor(255, 255, 255, 60))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(body, hi)
    # the onion is white, or near-black on light accents (e.g. Toxic's lime) so it stays legible
    a, b = QColor(c1), QColor(c2)
    lum = sum((0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()) / 2 for q in (a, b))
    fg = QColor("#0b1a10") if lum > 165 else QColor("white")
    cx = x0 + s * 0.5

    def pt(dx, dy):   # offsets in units of s, from the top-centre of the icon
        return QPointF(cx + dx * s, y0 + dy * s)

    def bulb(w):   # onion outline, w = half-width at the widest point
        path = QPainterPath(pt(0, 0.27))
        path.cubicTo(pt(w * 0.25, 0.36), pt(w, 0.42), pt(w, 0.59))
        path.cubicTo(pt(w, 0.74), pt(w * 0.55, 0.81), pt(0, 0.81))
        path.cubicTo(pt(-w * 0.55, 0.81), pt(-w, 0.74), pt(-w, 0.59))
        path.cubicTo(pt(-w, 0.42), pt(-w * 0.25, 0.36), pt(0, 0.27))
        return path

    # sprout: two leaves curling out of the neck
    pen = QPen(fg, max(1.2, s * 0.05))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    leaf = QPainterPath(pt(0, 0.29))
    leaf.cubicTo(pt(0, 0.20), pt(-0.04, 0.15), pt(-0.12, 0.12))
    leaf.moveTo(pt(0, 0.27))
    leaf.cubicTo(pt(0.01, 0.19), pt(0.05, 0.14), pt(0.10, 0.10))
    p.drawPath(leaf)
    # bulb
    p.setPen(Qt.NoPen)
    p.fillPath(bulb(0.29), fg)
    # layers: inner outlines in the brand gradient, reading like sound waves
    if s >= 20:
        lp = QPen(g, max(1.0, s * 0.032))
        lp.setCapStyle(Qt.RoundCap)
        p.setPen(lp)
        for w in ((0.17, 0.07) if s >= 40 else (0.13,)):
            p.drawPath(bulb(w))
    # roots
    if s >= 32:
        rp = QPen(fg, max(1.0, s * 0.03))
        rp.setCapStyle(Qt.RoundCap)
        p.setPen(rp)
        for dx in (-0.06, 0.0, 0.06):
            p.drawLine(pt(dx * 0.6, 0.81), pt(dx, 0.87))
    p.restore()


BRAND = ("#7c5cff", "#ff4d8d")   # the app icon keeps its own colours in every theme


def logo_pixmap(size: int, c1: str | None = None, c2: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size), c1 or BRAND[0], c2 or BRAND[1])
    p.end()
    return pm


def app_icon(c1: str | None = None, c2: str | None = None) -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(sz, c1, c2))
    return icon


def logo_image(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size), *BRAND)
    p.end()
    return img
