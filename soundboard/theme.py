"""Colour themes and the app logo.

A theme is a set of named colour tokens. The Qt stylesheet is built from them, and
the hand-painted widgets (pads, meters, EQ curve, logo) read the same tokens through
`T` when they paint, so switching theme recolours everything live.
"""
from __future__ import annotations

import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QTransform)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.style import hooks, palettes, textures
# the colours and textures are in the style kit, shared with Onion Watch
from soundboard.style.palettes import (DEFAULT, FONT, GROUPS, LIVE_NAMES,  # noqa: F401
                                       LIVE_STYLE, TEXT_ON,
                                       THEMES, _add_live_tokens, _contrast, _mix,
                                       font_families, is_light_colour, mix, valid_colour)
from soundboard.style.textures import (AURORA, TEXTURE_TILE, TEXTURES,  # noqa: F401
                                       texture_image)


def group_name(group: str) -> str:
    """A GROUPS key as Settings shows it, in the language picked (the keys stay
    English; a function: this module can be imported before the language is)."""
    return {"Classic": _("Classic"), "Colourful": _("Colourful"), "Wild": _("Wild"),
            "Meme": _("Meme")}.get(group, group)


T: dict[str, str] = dict(THEMES[DEFAULT])   # current theme (read at paint time)
current_name = DEFAULT
live_override = ""   # the user's own highlight colour ("" = each theme's own)
textures_on = False  # Settings > Appearance: Textured (each theme's pattern) or Plain
# what the style kit (Bun's outfit, Hoot, the textures) paints in
hooks.connect(palette=lambda: T, theme_name=lambda: current_name, tr=_)


def tokens(name: str | None = None) -> dict[str, str]:
    """Theme `name`'s colours (default: the current one), with the user's own highlight
    colour if they picked one."""
    t = dict(THEMES.get(name or current_name, THEMES[DEFAULT]))
    if live_override:
        _add_live_tokens(t, live_override)
    return t


def set_live(colour: str) -> str:
    """Use `colour` for the live highlight in every theme ("" = back to each theme's
    own). Takes effect on the next apply(). Returns what was kept."""
    global live_override
    live_override = valid_colour(colour)
    return live_override


def status(kind: str) -> str:
    """The current theme's colour for an inline "ok", "warn" or "error" message. The
    bright green / amber / red of the dark themes can't be read on the light ones."""
    return T[f"{kind}_text"]


def set_tone(label, kind: str = "") -> None:
    """Colour a label as an "ok", "warn" or "error" message ("" = normal) in a way that
    follows theme changes (the stylesheet's [tone] rules)."""
    if label.property("tone") != kind:
        label.setProperty("tone", kind)
        label.style().unpolish(label)
        label.style().polish(label)


def set_current(name: str) -> str:
    global current_name
    name = name if name in THEMES else DEFAULT
    current_name = name
    T.clear()
    T.update(tokens(name))
    return name


@contextmanager
def previewing(name: str):
    """Theme `name` in `T` for the block, then the current one back: paints something
    (Bun on the theme-change cover) in a theme before apply() has switched to it."""
    global current_name
    was, colours = current_name, dict(T)
    set_current(name)
    try:
        yield
    finally:
        current_name = was
        T.clear()
        T.update(colours)


STYLE = Template("""
QWidget { background:$bg; color:$text; font-family:'$font'; font-size:10pt; }
QDialog { background:$bg; }
QFrame#card { background:$panel; border-radius:12px; }
QFrame#card QWidget { background:transparent; }
QFrame#card[interactive="true"] { border:1px solid transparent; }
QFrame#card[interactive="true"][hovered="true"] { background:$card_hi; border-color:$border_hi; }
QFrame#card[interactive="true"]:focus { background:$card_hi; border-color:$accent; }
QFrame#card[interactive="true"][playing="true"] { background:$card_hi; border:2px solid $accent; }
QLabel#section { color:$heading; font-size:10pt; font-weight:600; padding-top:8px;
                 qproperty-indent:0; }  /* padding alone makes Qt indent the text 3 px */
QLabel#section[head="true"] { padding-top:0; }
QLabel#pagetitle { color:$text_hi; font-size:12pt; font-weight:700; qproperty-indent:0; }
QLabel#hint, QLabel#muted { color:$muted; }
/* the tab help card (dialogs.TabHelpPopup): a raised surface with an edge (it floats
   over the board), the title role (1.3x base, bold) and body text */
QFrame#helpcard { background:$panel; border:1px solid $border; border-radius:16px; }
QFrame#helpcard QLabel { background:transparent; border:none; padding:0; }
QLabel#helptitle { font-size:13pt; font-weight:700; color:$text_hi; }
QLabel#helpbody { font-size:10.5pt; color:$text; }
QLabel#hint { font-size:8.5pt; }
QLabel[tone="ok"], QLabel#hint[tone="ok"] { color:$ok_text; }
QLabel[tone="warn"], QLabel#hint[tone="warn"] { color:$warn_text; }
QLabel[tone="error"], QLabel#hint[tone="error"] { color:$error_text; }
QLabel#eqlabel { color:$muted; font-size:8pt; }
QLabel#empty { color:$muted; font-size:15px; padding:8px 40px 40px 40px; }
QFrame#card QLabel#stepbox { background:$bg; border-radius:8px; padding:8px; margin-top:6px; }
QFrame#card QFrame#micflow { background:$bg; border:1px solid $border; border-radius:10px; }
QFrame#card QFrame#micoutput { background:$panel; border:1px solid $border; border-radius:8px; }
QFrame#card QFrame#micstatus { background:$card_hi; border:none; border-radius:10px; }
QFrame#card QFrame#micstatus QLabel { background:transparent; }
QLabel#micline { font-weight:600; }
QFrame#card QLabel#micguide { padding:2px 0; }
QFrame#card QFrame#micupdatebar { background:$warn_bg; border:1px solid $warn_text; border-radius:10px; }
QFrame#card QFrame#micupdatebar QLabel { background:transparent; }
QFrame#card QLabel#resultbox { background:$bg; border-radius:8px; padding:8px; }
QFrame#card QFrame#alttile { background:$bg; border-radius:8px; }
QLabel#wordmark { font-size:13pt; font-weight:700; color:$text_hi; background:transparent; }
QLabel#tagline { color:$muted; font-size:8.5pt; background:transparent; }
QPushButton { background:$btn; border:1px solid transparent; border-radius:8px; padding:7px 12px; }
QPushButton[quiet="true"] { background:transparent; }
QPushButton[quiet="true"]:hover { background:$btn_hover; }
QPushButton[quiet="true"]:pressed { background:$btn_press; }
QPushButton:hover { background:$btn_hover; }
QPushButton:focus { border-color:$accent; }
QPushButton#iconbutton { padding:7px 10px; min-width:18px; }
QPushButton:pressed { background:$btn_press; }
QPushButton:checked { background:$accent; border-color:$accent; color:$on_accent; }
QPushButton:disabled { color:$muted; }
QPushButton[busy="true"], QPushButton#primary[busy="true"] { color:$muted; }
QPushButton#primary { background:$accent; border:none; color:$on_accent; font-weight:600; }
QPushButton[guide="true"] { font-size:11pt; padding:9px 20px; border-radius:10px; }
QPushButton#primary:hover { background:$accent_hover; }
QPushButton#primary:focus { border:1px solid $text_hi; }
QFrame#soundstoolbar { background:$panel; background-image:none; border:none;
    border-radius:12px; }
QFrame#soundstoolbar QLabel, QFrame#soundstoolbar QSlider { background:transparent; }
QFrame#soundstoolbar QPushButton { background:transparent; border:1px solid transparent;
    border-radius:9px; padding:0 10px; }
QFrame#soundstoolbar QPushButton:hover { background:$btn_hover; }
QFrame#soundstoolbar QPushButton:pressed { background:$btn_press; }
QFrame#soundstoolbar QPushButton:focus { border-color:$accent; }
QFrame#soundstoolbar QPushButton#soundadd { color:$accent_link; font-weight:600; }
QFrame#soundstoolbar QPushButton[toolbarMenu="true"] { padding-right:22px; }
QLineEdit#soundssearch { background:$field; border:1px solid $border; border-radius:10px;
    padding:0 10px 0 4px; }
QLineEdit#soundssearch:hover { border-color:$border_hi; }
QLineEdit#soundssearch:focus { border-color:$accent; }
QPushButton#danger { background:$danger_bg; border:1px solid transparent; color:$danger_text; font-weight:600; }
QPushButton#danger:hover { background:$danger_hover; }
QPushButton#danger[quiet="true"] { background:transparent; }
QPushButton#danger[quiet="true"]:hover { background:$danger_bg; }
QPushButton#danger:focus { border-color:$accent; }
QPushButton#small, QPushButton#danger[small="true"] { padding:2px 8px; font-size:8pt; }
QPushButton#backhome { background:$btn; border:1px solid $border; color:$text_hi;
    font-weight:600; font-size:10pt; padding:6px 14px 6px 10px; border-radius:8px; }
QPushButton#backhome:hover { background:$btn_hover; border-color:$border_hi; }
QPushButton#tabinfo { padding:0; border-radius:8px; background:transparent; border:1px solid transparent; }
QPushButton#tabinfo:hover { background:$btn_hover; border-color:$border_hi; }
QPushButton#tabinfo:pressed { background:$btn_press; border-color:$border_hi; }
QPushButton#tabinfo:focus { border-color:$accent; }
QPushButton#moretabs { padding:4px 10px; border-radius:8px; background:transparent; border:1px solid transparent; color:$muted; }
QPushButton#moretabs:hover { background:$btn_hover; border-color:$border_hi; color:$text_hi; }
QPushButton#moretabs:pressed { background:$btn_press; }
QPushButton#moretabs:focus { border-color:$accent; }
QPushButton#moretabs::menu-indicator { image:none; width:0; }
QFrame#sidebar { background:$rail_bg; border:none; border-right:1px solid $rail_border; }
QFrame#sidebar[rtl="true"] { border-right:none; border-left:1px solid $rail_border; }   /* mirrored */
QToolButton#railtab { background:transparent; color:$muted; border:1px solid transparent;
    border-radius:8px; padding:7px 6px; font-weight:600; text-align:left; }
QToolButton#railtab:hover { background:$btn_hover; color:$text; }
QToolButton#railtab:checked { background:transparent; color:$text_hi; }   /* + the rail's fill */
QFrame#sidebar QPushButton#moretabs, QFrame#sidebar QPushButton#tabinfo,
QFrame#sidebar QPushButton#settings, QFrame#sidebar QPushButton#modebtn,
QFrame#sidebar QPushButton#railtoggle { padding:7px 6px; text-align:left; color:$muted;
    background:transparent; border:1px solid transparent; border-radius:8px; }
QFrame#sidebar QPushButton#moretabs:hover, QFrame#sidebar QPushButton#tabinfo:hover,
QFrame#sidebar QPushButton#settings:hover, QFrame#sidebar QPushButton#modebtn:hover,
QFrame#sidebar QPushButton#railtoggle:hover { background:$btn_hover; color:$text_hi; }
QFrame#sidebar QPushButton#moretabs:focus, QFrame#sidebar QPushButton#tabinfo:focus,
QFrame#sidebar QPushButton#settings:focus, QFrame#sidebar QPushButton#modebtn:focus,
QFrame#sidebar QPushButton#railtoggle:focus { border-color:$accent; }
QFrame#sidebar QPushButton#settings:checked { background:transparent; color:$text_hi; }
QFrame#sidebar QPushButton#settings:hover, QFrame#sidebar QPushButton#settings:focus {
    background:transparent; border-color:transparent; }   /* a square, painted: sidebar.py */
QFrame#sidebar QLabel#tagline { font-size:8pt; }
QFrame#sidebar QPushButton#pill, QFrame#sidebar QPushButton#onair,
QFrame#sidebar QPushButton#danger { padding:7px 6px; border-radius:8px; text-align:left; }
QFrame#sidebar QPushButton#moretabs[railopen="false"],
QFrame#sidebar QPushButton#tabinfo[railopen="false"],
QFrame#sidebar QPushButton#settings[railopen="false"],
QFrame#sidebar QPushButton#modebtn[railopen="false"],
QFrame#sidebar QPushButton#railtoggle[railopen="false"],
QFrame#sidebar QPushButton#pill[railopen="false"],
QFrame#sidebar QPushButton#onair[railopen="false"],
QFrame#sidebar QPushButton#danger[railopen="false"] { text-align:center; }
QFrame#sidebar QLabel#wordmark { font-size:12pt; }
QFrame#sidebar[twolinebrand="true"] QLabel#wordmark { font-size:10pt; }
QFrame#sidebar QFrame#raildiv { background:$border_hi; border:none; }
QFrame#sidebar QWidget#railslot { background:transparent; }
QFrame#railoutput { background:$panel; border:none; border-radius:12px; }
QFrame#railoutput[expanded="false"] { background:transparent; }
QFrame#railoutput QLabel#railoutputtitle { font-weight:700; color:$text_hi; }
QFrame#railoutput QWidget#railpairrow { background:transparent; }
QFrame#railoutput QPushButton#railpair { background:$btn; border:1px solid transparent;
    border-radius:8px; padding:0; color:$text; }   /* checked (Live) too: no accent fill under it */
QFrame#railoutput QPushButton#railpair:hover { background:$btn_hover; }
QFrame#railoutput QPushButton#railpair[muted="true"] { background:$danger_bg; }
QFrame#railoutput QPushButton#railpair:focus { border-color:$accent; }
QFrame#railoutput QPushButton#railoutputsetup { background:transparent;
    border:1px solid transparent; border-radius:6px; padding:0; }
QFrame#railoutput QPushButton#railoutputsetup[action="true"]:hover { background:$btn_hover; }
QFrame#railoutput QPushButton#railoutputsetup:focus { border-color:$accent; }
QFrame#railoutput QFrame#railoutputstrip { background:$warn_bg; border:none;
    border-radius:8px; }
QFrame#railoutputstrip QPushButton#railoutputsetup { border-radius:8px; }
QPushButton#railupdate { background:transparent; border:none; padding:0; }   /* painted: sidebar.UpdateCard */
QPushButton#railupdatecopy { background:transparent; border:1px solid transparent;
    border-radius:6px; padding:2px 6px; color:$accent_link; font-size:8.5pt; font-weight:600; }
QPushButton#railupdatecopy:hover { background:$panel; }
QPushButton#railupdatecopy:focus { border-color:$accent; }
QFrame#sidebar[compact="true"] QToolButton#railtab,
QFrame#sidebar[compact="true"] QPushButton { padding-top:2px; padding-bottom:2px; }
QPushButton#settings { padding:6px 14px; font-weight:600; }
QFrame#transport, QFrame#deck { background:$panel; border-radius:12px; }
QDialog#transport { background:$panel; }
QDialog#settingspage { background:transparent; }
QFrame#mixer { background:transparent; }
QFrame#card QPushButton#primary { background:$accent; color:$on_accent; border:none; padding:9px; }
QFrame#card QPushButton#primary:hover { background:$accent_hover; }
QFrame#vsep { background:$border; border:none; }
QFrame#toast { background:$panel; border:1px solid $border_hi; border-radius:12px; }
QFrame#toast QLabel { background:transparent; }
QFrame#toast QPushButton#toastaction { background:transparent; border:none; color:$accent_link;
    font-weight:600; padding:2px 8px 6px; border-radius:6px; }
QFrame#toast QPushButton#toastaction:hover { background:$btn_hover; }
QFrame#toast QPushButton#toastclose { background:transparent; border:none; border-radius:12px;
    padding:0; }
QFrame#toast QPushButton#toastclose:hover { background:$btn_hover; }
QFrame#chip { background:$panel; border:1px solid transparent; border-radius:14px; }
QFrame#chip[sel="true"] { border-color:$accent; }
QFrame#chip QPushButton { background:transparent; border:none; padding:2px 6px; }
QFrame#chip QPushButton#chipname { font-weight:600; }
QFrame#chip QPushButton#chipstop { border-radius:12px; padding:0; }
QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; }
QLabel#iconlabel { background:transparent; }
QFrame#card QLabel#sourcepic { background:$inset; border-radius:8px; }   /* ui/sourcedialog.py: no thumbnail */
QPushButton#pill { border-radius:15px; padding:5px 14px; font-weight:600; }
QPushButton#pill[state="ok"] { color:$live_text; background:transparent; }
QPushButton#onair { border-radius:15px; padding:5px 14px; font-weight:700;
    background:$danger_bg; border:1px solid transparent; color:$danger_text; }
QPushButton#onair:checked { background:$live; border:1px solid transparent; color:$on_live; }
QPushButton#onair:checked:hover { background:$live_hover; }
QWidget#decktop { background:transparent; }
QLabel#decktitle { color:$text; font-size:9pt; font-weight:600; }
QPushButton#pill[state="warn"] { background:$warn_bg; color:$warn_text; }
QAbstractSpinBox { background:$field; border:1px solid transparent; border-radius:6px; padding:3px 6px; }
QAbstractSpinBox:hover { border-color:$border_hi; }
QAbstractSpinBox:focus { border-color:$border_hi; }
QSpinBox::up-button, QSpinBox::down-button { width:0; }
QSpinBox#pct, QFrame#card QSpinBox#pct { background:transparent; border-color:transparent;
    padding:3px 2px; }
QSpinBox#pct:hover, QFrame#card QSpinBox#pct:hover { background:$field; border-color:$border_hi; }
QSpinBox#pct:focus, QFrame#card QSpinBox#pct:focus { background:$field; border-color:$border_hi; }
QDoubleSpinBox, QSpinBox#stepper { padding-right:2px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox#stepper::up-button, QSpinBox#stepper::down-button {
    subcontrol-origin:border; width:18px; border:none; background:transparent; }
QDoubleSpinBox::up-button, QSpinBox#stepper::up-button {
    subcontrol-position:top right; border-top-right-radius:6px; }
QDoubleSpinBox::down-button, QSpinBox#stepper::down-button {
    subcontrol-position:bottom right; border-bottom-right-radius:6px; }
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox#stepper::up-button:hover, QSpinBox#stepper::down-button:hover { background:$btn_hover; }
QDoubleSpinBox::up-arrow, QSpinBox#stepper::up-arrow { image:url("$up_small"); width:8px; height:8px; }
QDoubleSpinBox::down-arrow, QSpinBox#stepper::down-arrow { image:url("$down_small"); width:8px; height:8px; }
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off,
QSpinBox#stepper::up-arrow:disabled, QSpinBox#stepper::up-arrow:off { image:url("$up_small_off"); }
QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off,
QSpinBox#stepper::down-arrow:disabled, QSpinBox#stepper::down-arrow:off { image:url("$down_small_off"); }
QSlider::groove:vertical { width:4px; background:$groove; border-radius:2px; }
QSlider::add-page:vertical { background:$muted; border-radius:2px; }
QSlider::handle:vertical { background:$text_hi; border:1px solid transparent; width:14px; height:14px; margin:0 -5px; border-radius:7px; }
QPushButton#micbanner { background:#d32f2f; color:white; font-weight:700; font-size:11pt;
    border:none; border-radius:10px; padding:10px; }
QFrame#urgentbar { background:$warn_bg; border:1px solid $warn_text; border-radius:10px; }
QFrame#tipbar { background:$panel; border:1px solid $border_hi; border-radius:10px; }
QFrame#tipbar QLabel { background:transparent; color:$text; }
QFrame#tipbar QPushButton#primary { padding:2px 8px; font-size:8pt; }   /* as small as Not now */
QFrame#tipbar QPushButton#urgenthide { background:transparent; color:$muted; border:none;
                                       border-radius:6px; font-weight:700; font-size:12pt; }
QFrame#tipbar QPushButton#urgenthide:hover { background:$btn_hover; }
QFrame#urgentbar QLabel { background:transparent; color:$warn_text; font-weight:600; }
QFrame#urgentbar QPushButton#urgenthide { background:transparent; color:$warn_text; border:none;
    border-radius:14px; padding:0; font-size:12pt; }
QFrame#urgentbar QPushButton#urgenthide:hover { background:$danger_bg; }
QPushButton#miccheck:checked { background:#d32f2f; border:1px solid #ff6b6b; color:white; }
QDialog#transport QLabel, QDialog#transport QCheckBox, QDialog#transport QSlider,
QFrame#transport QLabel, QFrame#transport QCheckBox, QFrame#transport QSlider,
QFrame#deck QLabel, QFrame#deck QCheckBox, QFrame#deck QSlider { background:transparent; }
QPushButton#round { padding:0; font-size:14pt; border-radius:10px; }
QPushButton#transport_play { background:$accent; border:1px solid transparent; border-radius:18px; padding:0; }
QPushButton#transport_play[mini="true"] { border-radius:14px; }
QPushButton#transport_play:hover { background:$accent_hi; }
QPushButton#transport_play:pressed { background:$accent; }
QPushButton#transport_play:disabled { background:$btn; border:1px solid $border; }
QPushButton#transport_stop { background:$btn; border:1px solid $border; border-radius:10px; padding:0; }
QPushButton#transport_stop:hover { background:$btn_hover; border-color:$danger_text; }
QPushButton#transport_stop:pressed { background:$btn_press; }
QPushButton#transport_stop:disabled { background:$btn; border:1px solid $border; }
/* no side margin on the groove: the fill starts at the widget's edge, so a margin left a
   purple stub sticking out past the handle at 0:00 (it looked a few seconds in) */
QSlider#seek::groove:horizontal { height:6px; border-radius:3px; }
QSlider#seek::sub-page:horizontal { border-radius:3px; }
QLineEdit, QComboBox { background:$card_ctl; border:1px solid transparent; border-radius:8px; padding:6px 8px; }
QLineEdit:hover, QComboBox:hover { background:$card_hi; }
QLineEdit:focus, QComboBox:focus, QComboBox:on { border-color:$border_hi; }
QLineEdit { selection-background-color:$btn_press; selection-color:$text_hi; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { placeholder-text-color:$muted; }
QComboBox { padding:6px 10px; padding-right:6px; combobox-popup:0; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right;
    width:26px; border:none; background:transparent; }
QComboBox::down-arrow { image:url("$down"); width:10px; height:10px; }
QComboBox::down-arrow:on { image:url("$up"); }
QComboBox::down-arrow:disabled { image:url("$down_off"); }
QComboBox:disabled, QLineEdit:disabled { color:$muted; background:$inset; }
QFrame#card QComboBox, QFrame#card QPushButton, QFrame#card QLineEdit { background:$card_ctl; }
QFrame#card QPushButton:hover:!checked { background:$btn_hover; }
QFrame#card QPushButton#primary:hover { background:$accent_hover; }
QFrame#card QPushButton:focus { border-color:$accent; }
QFrame#card QComboBox:disabled, QFrame#card QLineEdit:disabled { background:$inset; }
QFrame#card QAbstractSpinBox { background:$field; }
QFrame#card QPushButton:checked { background:$accent; }
QFrame#card QPushButton#miccheck:checked { background:#d32f2f; }
QComboBox QAbstractItemView { background:$card; color:$text; border:1px solid $border_hi;
    padding:4px; outline:0; selection-background-color:$btn_press; selection-color:$text_hi; }
QComboBox QAbstractItemView::item { min-height:28px; padding:0 10px; border-radius:6px; }
QComboBox QAbstractItemView::item:hover { background:$item_hover; color:$text_hi; }
QComboBox QAbstractItemView::item:selected { background:$item_hover; color:$text_hi; }
QComboBox QAbstractItemView::item:disabled { color:$faint; }
QPushButton::menu-indicator { image:url("$down"); width:9px; height:9px;
    subcontrol-origin:padding; subcontrol-position:center right; right:2px; }
QPushButton::menu-indicator:open { image:url("$up"); }
QSlider::groove:horizontal { height:4px; background:$groove; border-radius:2px; }
QSlider::sub-page:horizontal { background:$muted; border-radius:2px; }
QSlider#seek::sub-page:horizontal { background:$accent; }
QSlider#seek::sub-page:horizontal:disabled { background:$groove; }
QSlider#seek[atstart="true"]::sub-page:horizontal { background:$groove; }
QSlider#seek::handle:horizontal { background:$text_hi; border:1px solid transparent; width:14px; height:14px; margin:-4px 0; border-radius:7px; }
QSlider#seek::handle:horizontal:disabled { background:$off; }
QSlider::handle:horizontal { background:$text_hi; border:1px solid transparent; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
/* room for the whole handle: Qt sizes a slider to its groove, which cut the circle's top
   and bottom off flat */
QSlider:horizontal { min-height:20px; }
QSlider:vertical { min-width:20px; }
QSlider::handle:hover, QSlider::handle:pressed { border-color:$border_hi; }
QSlider::handle:disabled { background:$inset; }
QSlider::sub-page:horizontal:disabled, QSlider::add-page:vertical:disabled { background:$off; }
/* dim="true": a control that's live but does nothing right now (the EQ while it's off) */
QSlider[dim="true"]::sub-page:horizontal, QSlider[dim="true"]::add-page:vertical { background:$off; }
QComboBox[dim="true"] { color:$muted; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid $off; background:$card; }
QCheckBox::indicator:checked { background:$accent; border-color:$accent; image:url("$check"); }
QCheckBox::indicator:hover { border-color:$border_hi; }
QCheckBox::indicator:checked:hover { background:$accent_hover; border-color:$accent_hover; }
QCheckBox::indicator:disabled { background:$inset; border-color:$border; }
QCheckBox::indicator:checked:disabled { image:url("$check_off"); }
/* radio circles are whole pictures: a stylesheet border-radius:8px on a 16px box
   clips the ring flat on its left edge */
QRadioButton::indicator { width:16px; height:16px; border:none; background:transparent; image:url("$radio"); }
QRadioButton::indicator:hover { image:url("$radio_hover"); }
QRadioButton::indicator:checked { image:url("$radio_on"); }
QRadioButton::indicator:checked:hover { image:url("$radio_on_hover"); }
QRadioButton::indicator:disabled { image:url("$radio_off"); }
QRadioButton::indicator:checked:disabled { image:url("$radio_on_off"); }
QListWidget#settingscategories { background:transparent; border:none; outline:0; }
QListWidget#settingscategories::item { padding:4px; border-radius:8px; }
QListWidget#settingscategories::item:selected { background:$card_hi; color:$text_hi; }
QListWidget#settingscategories::item:hover:!selected { background:$inset; }
QListWidget#pointlist { background:$inset; border:1px solid $border; border-radius:12px; padding:6px; outline:0; }
QListWidget#pointlist::item { background:transparent; border:none; border-radius:8px; margin:2px 0; color:$muted; }
QListWidget#pointlist::item:selected { background:$btn_press; }
QListWidget#pointlist::item:hover:!selected { background:$btn_hover; }
QWidget#pointrow, QWidget#pointrow QLabel { background:transparent; }
QLabel#pointtitle { color:$text_hi; font-weight:600; background:transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; }
QScrollBar::handle:vertical { background:$groove; border-radius:5px; min-height:30px; }
QScrollBar::handle:vertical:hover { background:$border_hi; }
QScrollBar:horizontal { background:transparent; height:10px; }
QScrollBar::handle:horizontal { background:$groove; border-radius:5px; min-width:30px; }
QScrollBar::handle:horizontal:hover { background:$border_hi; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QAbstractScrollArea::corner { background:transparent; border:none; }
QMenu { background:$card; border:1px solid $border_hi; padding:5px; }
QMenu::item { padding:7px 22px 7px 12px; border-radius:6px; margin:1px 0; }
QMenu::item:selected { background:$item_hover; color:$text_hi; }
QMenu::item:checked { color:$accent_link; }
QMenu::item:disabled { color:$faint; }
QMenu::icon { padding-left:10px; }
QMenu::separator { height:1px; background:$border; margin:5px 8px; }
QFrame#tabcard { background:$card_hi; border:1px solid transparent; border-radius:10px; margin:3px 4px; }
QFrame#tabcard:hover { border-color:$border_hi; background:$btn_hover; }
QLabel#tabcardpic { background:$inset; border-radius:12px; }
QLabel#tabcardtitle { font-size:11pt; font-weight:700; color:$text_hi; background:transparent; }
QLabel#tabcardblurb { color:$muted; background:transparent; }
QLabel#tabcardhead { font-size:12pt; font-weight:700; color:$text_hi; background:transparent; }
QWidget#tabcardtop { background:transparent; }
QToolTip { background:$card; color:$text; border:1px solid $border_hi; border-radius:6px; padding:5px 8px; }
QTabWidget::pane { border:none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background:transparent; color:$muted; padding:8px 16px; margin-right:4px;
    border:none; border-bottom:2px solid transparent; font-weight:600; }
QTabBar::tab:selected { color:$text_hi; border-bottom:2px solid $text_hi; }
QTabBar::tab:hover { color:$text; }
QTabBar::scroller { width:48px; }
QTabBar QToolButton { background:$btn; border:none; border-radius:8px; margin:5px 0 5px 2px; }
QTabBar QToolButton:hover { background:$btn_hover; }
QTabBar QToolButton:disabled { background:$bg; }
QTabBar QToolButton::left-arrow { image:url("$left"); width:10px; height:10px; }
QTabBar QToolButton::right-arrow { image:url("$right"); width:10px; height:10px; }
QTabBar QToolButton::left-arrow:disabled { image:url("$left_off"); }
QTabBar QToolButton::right-arrow:disabled { image:url("$right_off"); }
QTabBar::tear { width:0; border:none; }
QPushButton#live { font-weight:700; }
QPushButton#voicetile { text-align:left; padding:9px 10px; border-radius:10px; }
QPushButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QPushButton#voicetile[art="true"] { padding:5px 10px 5px 6px; }
QPushButton#voicetile:hover:!checked { border-color:$border_hi; }
/* the Voice tab: its row of tabs, the voice changer's picture cards, the picked voice */
QPushButton#voicetab { border-radius:10px; padding:7px 14px; background:$btn; border:1px solid $border; font-weight:600; }
QPushButton#voicetab:hover:!checked { background:$btn_hover; border-color:$border_hi; }
QPushButton#voicetab:checked { background:$accent; color:$on_accent; border-color:$accent_hi; }
QPushButton#voicetab[live="true"]:!checked { color:$live_text; border-color:$live_border; }
QFrame#card QToolButton#voicetile { background:$card; color:$text; border:1px solid transparent; border-radius:12px; padding:8px 4px 6px 4px; font-size:8.5pt; }
QFrame#card QToolButton#voicetile:hover:!checked { background:$btn_hover; border-color:$border_hi; }
QFrame#card QToolButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QFrame#card QToolButton#voicetile:focus { border-color:$accent; }
QFrame#card QToolButton#voicetile:checked:focus { border-color:$text_hi; }
QFrame#card QFrame#picked { background:$inset; border-radius:10px; }
QFrame#card QPushButton#voicecat { border-radius:12px; padding:4px 12px; min-height:16px; font-size:8.5pt; background:$btn; border:1px solid transparent; color:$text; }
QFrame#card QPushButton#voicecat:hover:!checked { background:$btn_hover; }
QFrame#card QPushButton#voicecat:checked { background:$accent; border-color:$accent_hi; color:$on_accent; font-weight:600; }
QFrame#card QToolButton#voicestar { background:transparent; border:none; border-radius:11px; padding:0; }
QFrame#card QToolButton#voicestar:hover { background:$card; border:1px solid $border_hi; }
QFrame#card QToolButton#voicestar[picked="true"]:hover { background:$btn_hover; border:none; }
QFrame#card QFrame#voicebox { background:$inset; border:1px solid $border; border-radius:8px; }
QFrame#picked[pinned="true"] { background:$panel; border-radius:12px; }
QFrame#picked QLabel#pickedname { color:$text_hi; font-size:11pt; font-weight:700; }
/* Spacious controls only in Voice and Setup cards. */
QFrame#card[roomy="true"] QPushButton { padding:9px 14px; min-height:18px; }
/* the reset family (panel.reset_button): a slim muted link with the reset arrow, the
   same beside an effect, the live controls and a sound's effects */
QPushButton#reset, QFrame#card QPushButton#reset, QFrame#card[roomy="true"] QPushButton#reset { background:transparent; border:none; color:$muted; padding:2px 6px; min-height:0; font-size:8pt; }
QPushButton#reset:hover, QFrame#card QPushButton#reset:hover, QFrame#card[roomy="true"] QPushButton#reset:hover { color:$text; background:transparent; }
QPushButton#infobutton, QFrame#card QPushButton#infobutton, QFrame#card[roomy="true"] QPushButton#infobutton { background:transparent; padding:0; min-width:24px; max-width:24px; min-height:24px; max-height:24px; border-radius:6px; }
QPushButton#infobutton:hover, QFrame#card QPushButton#infobutton:hover, QFrame#card[roomy="true"] QPushButton#infobutton:hover { background:$btn_hover; }
/* a quiet icon button stays quiet inside a card too (the ⓘ after the sound modes) */
QFrame#card QPushButton#iconbutton[quiet="true"], QFrame#card[roomy="true"] QPushButton#iconbutton[quiet="true"] { background:transparent; padding:7px 10px; min-height:0; }
QFrame#card QPushButton#iconbutton[quiet="true"]:hover, QFrame#card[roomy="true"] QPushButton#iconbutton[quiet="true"]:hover { background:$btn_hover; }
/* sides 14: a filled button's icon lines up with the plain ones' below it (measured on Setup's
   ways: 16 put the mic 2 px further in than Step-by-step guide's check) */
QFrame#card[roomy="true"] QPushButton#primary { padding:9px 14px; }
QFrame#card[roomy="true"] QPushButton#voicetile { padding:7px 12px; text-align:left; }
QFrame#card[roomy="true"] QPushButton#fold { padding:8px 10px; text-align:left; }
QFrame#card[roomy="true"] QComboBox { padding:9px 12px; }
QSlider#hue::groove:horizontal { height:12px; border-radius:6px; border:1px solid $border;
    background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff0000, stop:0.167 #ffff00,
        stop:0.333 #00ff00, stop:0.5 #00ffff, stop:0.667 #0000ff, stop:0.833 #ff00ff,
        stop:1 #ff0000); }
QSlider#hue::sub-page:horizontal, QSlider#hue::sub-page:horizontal:disabled { background:transparent; }
QSlider#hue::handle:horizontal { width:16px; height:16px; margin:-3px 0; border-radius:8px;
    border:2px solid $text_hi; }
QPlainTextEdit#speechlog { background:$bg; border:1px solid transparent; border-radius:8px; padding:8px; }

QFrame#fxcard { background:$card; border:1px solid transparent; border-radius:12px; }
QFrame#fxcard:hover { border-color:$border_hi; }
QFrame#fxcard[on="true"] { border-color:$accent; }
QFrame#fxcard[hero="true"] { background:$card; }
QFrame#fxcard[fresh="true"] { background:$card_hi; border:2px solid $accent_hi; }
QFrame#fxcard QLabel, QFrame#fxcard QCheckBox { background:transparent; }
QLabel#fxname { font-weight:700; font-size:10pt; color:$text_hi; }
QLabel#fxdesc { color:$muted; font-size:8.5pt; }
QLabel#fxparam { color:$text; font-size:9pt; }
QLabel#fxvalue { color:$accent_link; font-size:9pt; font-weight:700; }
QLabel#fxend { color:$muted; font-size:7.5pt; }   /* faint was 2.6:1 on some */
QLabel#fxgroup { color:$text; font-size:9pt; font-weight:600; padding-top:6px; }
QFrame#voicebar { background:$panel; border-radius:12px; }
QWidget#voicebarpart, QFrame#voicebar QLabel { background:transparent; }
QLabel#voicebarlabel { color:$muted; font-size:9pt; font-weight:600; }
QFrame#voicebar QPushButton#iconbutton { padding:0; min-width:0; }
QPushButton#vchip { background:$inset; border:1px solid transparent; border-radius:13px; padding:4px 11px; color:$muted; font-size:9pt; font-weight:600; min-height:0; }
QPushButton#vchip:hover { color:$text; }
QPushButton#vchip[state="on"] { color:$live_text; border-color:$live_border; }
QPushButton#vchip[state="warn"] { color:$warn_text; border-color:$warn_text; background:$warn_bg; }
QLabel#pill { background:$inset; border:1px solid transparent; border-radius:10px; padding:3px 10px; color:$muted; font-size:8.5pt; font-weight:600; }
QLabel#pill[slow="true"] { color:$warn_text; border-color:$warn_text; }
QLabel#pill[on="true"] { color:$live_text; border-color:$live_border; }
QLabel#pill[tone="muted"] { border-color:$muted; }
QLabel#pill[tone="ok"] { color:$live_text; border-color:$live_border; }
QLabel#pill[tone="warn"] { color:$warn_text; border-color:$warn_text; }
QLabel#pill[tone="error"] { color:$error_text; border-color:$error_text; }
QPushButton#subchip { border-radius:11px; padding:2px 11px; min-height:18px; font-size:8.5pt;
    background:transparent; border:1px solid $border; color:$muted; }
QPushButton#subchip:hover { color:$text; background:$btn_hover; }
QPushButton#subchip:checked { background:$accent; border-color:$accent; color:$on_accent; }
QPushButton#fold { background:transparent; border:none; color:$muted; padding:3px 6px; font-size:8.5pt; font-weight:600; }
QPushButton#fold:hover, QPushButton#fold:checked { color:$text; background:transparent; }
QFrame#card QPushButton#fold, QFrame#card QPushButton#fold:checked { background:transparent; }
QPushButton#power { font-weight:700; }
QPushButton#power:checked, QFrame#card QPushButton#power:checked { background:$live; border:1px solid $live_hi; color:$on_live; }
QPushButton#power:checked:hover, QFrame#card QPushButton#power:checked:hover { background:$live_hover; }
QPushButton#live:checked, QFrame#card QPushButton#live:checked { background:$live; border:1px solid $live_hi; color:$on_live; }
QPushButton#live:checked:hover, QFrame#card QPushButton#live:checked:hover { background:$live_hover; }
QPushButton#rec { min-height:18px; }   /* its 14px dot: as tall as Send beside it */
QPushButton#rec:checked { background:#d32f2f; border:1px solid #ff6b6b; color:white; font-weight:700; }
QDialog#recorddialog QLabel#recordtitle { font-size:19pt; font-weight:700; color:$text_hi; }
QDialog#recorddialog QPushButton#recordmark { background:$panel; border:1px solid $border; border-radius:14px; padding:0; }
QDialog#recorddialog QRadioButton#recordsource { background:$panel; border:1px solid $border; border-radius:12px; padding:12px 14px; spacing:8px; font-weight:600; }
QDialog#recorddialog QRadioButton#recordsource:hover { background:$card_hi; border-color:$border_hi; }
QDialog#recorddialog QRadioButton#recordsource:checked { background:$card_hi; border-color:$accent; color:$text_hi; }
QDialog#recorddialog QRadioButton#recordsource:focus { border-color:$text_hi; }
QDialog#recorddialog QRadioButton#recordsource:disabled { color:$muted; }
QFrame#recordstudio, QFrame#recordreview { background:$panel; border:1px solid $border; border-radius:16px; }
QFrame#recordstudio QLabel, QFrame#recordreview QLabel { background:transparent; }
QDialog#recorddialog QLabel#recordtime { font-size:28pt; font-weight:600; color:$text_hi; }
QDialog#recorddialog QLabel#recordphase { color:$muted; font-size:9pt; }
QDialog#recorddialog QLabel#recordphase[recording="true"] { color:$danger_text; }
QDialog#recorddialog QPushButton#rec { background:$danger_bg; border:1px solid $danger_border; color:$danger_text; border-radius:14px; font-weight:700; }
QDialog#recorddialog QPushButton#rec:hover { background:$danger_hover; border-color:$danger_text; }
QDialog#recorddialog QPushButton#rec:checked { background:#d32f2f; border-color:#ff6b6b; color:white; }
QDialog#recorddialog QPushButton#rec:checked:hover { background:#b92424; }
QDialog#recorddialog QPushButton#rec:focus { border-color:$text_hi; }
QDialog#recorddialog QPushButton#rec:disabled { background:$inset; border-color:$border; color:$muted; }
QFrame#setcard { background:$panel; border-radius:12px; }
QFrame#setcard QWidget { background:transparent; }
QFrame#setcard QPushButton { background:$btn; }
QFrame#setcard QPushButton:hover { background:$btn_hover; }
QFrame#setcard QPushButton[quiet="true"] { background:transparent; }
QFrame#setcard QPushButton[quiet="true"]:hover { background:$btn_hover; }
QFrame#setcard QPushButton:checked { background:$accent; color:$on_accent; }
QFrame#setcard QPushButton#primary { background:$accent; color:$on_accent; border:none; }
QFrame#setcard QPushButton#power:checked { background:$live; border:1px solid $live_hi; color:$on_live; }
QFrame#setcard QPushButton#primary:hover { background:$accent_hover; }
QFrame#setcard QLineEdit, QFrame#setcard QComboBox { background:$field; }
/* setcard's QWidget rule made number boxes see-through: Remote's Port had no box */
QFrame#setcard QAbstractSpinBox { background:$field; }
QFrame#setcard QSpinBox#pct { background:transparent; }
QFrame#setcard QSpinBox#pct:hover, QFrame#setcard QSpinBox#pct:focus { background:$field; }
QFrame#setcard QLineEdit:hover, QFrame#setcard QComboBox:hover { background:$card; }
QTableView, QFrame#setcard QTableView { background:$card; alternate-background-color:$card_hi;
    color:$text; border:1px solid transparent; border-radius:6px;
    selection-background-color:$btn_press; selection-color:$text_hi; }
QTableView::item { padding:5px 8px; border:none; }
QTableView::item:hover { background:$btn_hover; }
QTableView::item:selected { background:$btn_press; color:$text_hi; }
QHeaderView, QFrame#setcard QHeaderView { background:$btn; color:$text; }
QHeaderView::section, QFrame#setcard QHeaderView::section { background:$btn; color:$text;
    padding:8px; border:none; border-bottom:1px solid $border; font-weight:600; }
QTableCornerButton::section { background:$btn; border:none; }
QFrame#setcard QPlainTextEdit { background:$card; color:$text;
    border:1px solid transparent; border-radius:6px; padding:8px;
    selection-background-color:$btn_press; selection-color:$text_hi; }
QProgressBar#downloadprogress, QFrame#card QProgressBar#downloadprogress, QProgressBar#updatebar {
    background:$groove; border:none; border-radius:2px; }
QProgressBar#downloadprogress::chunk, QProgressBar#updatebar::chunk { background:$accent; border-radius:2px; }
QPushButton#hkbtn { min-width:150px; font-weight:600; }
/* also inside a card: there `QFrame#setcard QPushButton:checked` (an accent fill) would
   win, and the card paints its name in $text: grey on grey in Carbon */
QPushButton#themecard, QFrame#setcard QPushButton#themecard, QFrame#card QPushButton#themecard {
    background:$tile; border:2px solid $border; border-radius:12px; padding:0; }
QPushButton#themecard:hover, QFrame#setcard QPushButton#themecard:hover,
QFrame#card QPushButton#themecard:hover { background:$tile; border-color:$border_hi; }
QPushButton#themecard:checked, QFrame#setcard QPushButton#themecard:checked,
QFrame#card QPushButton#themecard:checked { background:$tile; border:2px solid $accent; }
QFrame#card QFrame#chip { background:$btn; border:1px solid transparent; border-radius:11px; }
QFrame#card QFrame#chip:hover { background:$btn_hover; }
QFrame#card QFrame#chip[sel="true"] { border-color:$accent; }
QFrame#card QFrame#chip QPushButton { background:transparent; border:none; }
QFrame#card QFrame#chip QPushButton#chipname:hover { color:$text_hi; }
QFrame#card QFrame#chip QPushButton#chipstop { border-radius:11px; color:$muted; }
QFrame#card QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; color:$danger_text; }
/* popups (combo lists, menus) are children of the widget that opens them, so the
   "card QWidget { transparent }" rules above reach them and a see-through popup draws black.
   Last so it wins the tie with those rules. */
QFrame#card QComboBox QAbstractItemView, QFrame#setcard QComboBox QAbstractItemView,
QFrame#card QComboBoxPrivateContainer, QFrame#setcard QComboBoxPrivateContainer,
QFrame#card QMenu, QFrame#setcard QMenu { background:$card; }
/* keyboard focus shows on every control in every theme: these come last because a
   rule with more ids (QFrame#card QPushButton#primary) outranks a plain :focus one */
QFrame#card QPushButton#primary:focus, QFrame#setcard QPushButton#primary:focus,
QPushButton:checked:focus, QFrame#card QPushButton:checked:focus,
QFrame#setcard QPushButton:checked:focus { border:1px solid $text_hi; }
/* a card's fold arrow: just the arrow, centred in its square (the roomy cards' text
   padding pushed it off to one side), and a plain accent box for keyboard focus */
QPushButton#fold[icononly="true"], QFrame#card[roomy="true"] QPushButton#fold[icononly="true"] {
    padding:0; min-height:0; text-align:center; border:1px solid transparent; border-radius:6px; }
QPushButton#fold[icononly="true"]:focus, QFrame#card QPushButton#fold[icononly="true"]:focus,
QFrame#card QPushButton#fold[icononly="true"]:checked:focus { border:1px solid $accent; }
QCheckBox::indicator:focus { border-color:$accent; }
QCheckBox::indicator:checked:focus { border-color:$text_hi; }
QSlider::handle:horizontal:focus, QSlider::handle:vertical:focus { border:2px solid $accent; }
/* a busy accent button looks busy in a card too (busy.hold: "Setting up…") */
QPushButton#primary[busy="true"], QPushButton#primary[busy="true"]:hover,
QFrame#card QPushButton#primary[busy="true"], QFrame#card QPushButton#primary[busy="true"]:hover,
QFrame#setcard QPushButton#primary[busy="true"],
QFrame#setcard QPushButton#primary[busy="true"]:hover { background:$inset; color:$muted; }
""")


def live_sheet() -> str:
    """The live rules in the current colours, as a widget's own stylesheet (the style
    kit's palettes.live_sheet)."""
    return palettes.live_sheet(T)


# Flat window and cards with quiet hairline borders. Textured adds each theme's tile on
# the cards and a soft glow of its two accent colours behind them (paint_window_bg: the
# root widget and opaque widgets paint it, a style sheet can't hold two gradients).
# The colours follow each theme; High Contrast keeps its solid fills and outlines.
POLISH_STYLE = Template("""
QWidget#root { background:$bg; }
QWidget#root QTabWidget, QWidget#root QTabBar, QWidget#root QStackedWidget,
QWidget#root QStackedWidget > QWidget, QWidget#root .QWidget { background:transparent; }
QLabel { background:transparent; }   /* over the gradient: no flat box behind text */
QToolTip { background:$card; }
QFrame#card, QFrame#setcard, QFrame#fxcard {
    background:$panel; border:1px solid $surface_border; }
QFrame#card[interactive="true"] { border-left:1px solid transparent; border-right:1px solid transparent; }
QFrame#card[interactive="true"][hovered="true"] { background:$card_hi; border-color:$border_hi; }
QFrame#transport, QFrame#deck { background:$glass; border-top:1px solid $edge; }
QPushButton#primary, QFrame#card QPushButton#primary, QFrame#setcard QPushButton#primary {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top, stop:0.3 $accent,
        stop:1 $accent_end);
    border:1px solid $accent_rim_side; border-top-color:$accent_rim; }
QPushButton#primary:hover, QFrame#card QPushButton#primary:hover,
QFrame#setcard QPushButton#primary:hover {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top_hi,
        stop:0.3 $accent_hover, stop:1 $accent_end_hi); }
QPushButton#primary:pressed, QFrame#card QPushButton#primary:pressed,
QFrame#setcard QPushButton#primary:pressed {
    background:$accent_press; border-top-color:$accent_rim_side; }
QPushButton#primary:focus, QFrame#card QPushButton#primary:focus,
QFrame#setcard QPushButton#primary:focus { border:1px solid $text_hi; }
QPushButton#transport_play {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top, stop:0.3 $accent,
        stop:1 $accent_end);
    border:1px solid $accent_rim_side; border-top-color:$accent_rim; }
QPushButton#transport_play:hover:!disabled {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top_hi,
        stop:0.3 $accent_hover, stop:1 $accent_end_hi); }
QPushButton#transport_play:pressed:!disabled { background:$accent_press; }
QPushButton#onair:checked, QPushButton#power:checked, QFrame#card QPushButton#power:checked,
QFrame#setcard QPushButton#power:checked, QPushButton#live:checked,
QFrame#card QPushButton#live:checked {
    background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $live_top, stop:1 $live); }
""")


def _rgba(colour: str, alpha: float) -> str:
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})"


def polish_tokens(tk: dict[str, str], light: bool) -> dict[str, str]:
    """The extra shades POLISH_STYLE paints with, from theme tokens `tk`."""
    panel = tk["panel"]
    return dict(
        tk,
        surface_border=_mix(panel, tk["border"], 0.55),
        edge=_mix(panel, tk["border"], 0.55),
        glass=_rgba(panel, 0.86),
        **_accent_shades(tk),
    )


def _accent_shades(tk: dict[str, str]) -> dict[str, str]:
    """A filled accent button's gradient: lit top-left corner, the accent, then a blend
    into the theme's second colour (accent2) at the bottom-right, with a light rim on
    top. Every shade keeps the button's text as readable as on the plain accent (4.5:1,
    or the accent's own ratio when that's lower): the lit corner lightens less, and the
    blend's end is deepened (away from the text colour) until the text reads."""
    on = tk["on_accent"]
    white, black = "#ffffff", "#000000"
    away = black if _contrast(on, black) > _contrast(on, white) else white

    def lit(base: str) -> str:
        need = min(4.5, _contrast(on, base))
        return next((c for c in (_mix(base, white, 0.2 * (10 - i) / 10) for i in range(11))
                     if _contrast(on, c) >= need), base)

    def blend(base: str) -> str:
        need = min(4.5, _contrast(on, base))
        mixed = _mix(base, tk["accent2"], 0.35)
        return next((c for c in (_mix(mixed, away, i / 20) for i in range(15))
                     if _contrast(on, c) >= need), _mix(mixed, away, 0.7))

    return dict(
        accent_top=lit(tk["accent"]),
        accent_top_hi=lit(tk["accent_hover"]),
        accent_end=blend(tk["accent"]),
        accent_end_hi=blend(tk["accent_hover"]),
        accent_press=_mix(tk["accent"], black, 0.15),
        accent_rim=_rgba(white, 0.30),
        accent_rim_side=_rgba(_mix(tk["accent"], black, 0.25), 0.55),
    )


def accent_fill(hover: bool = False) -> str:
    """A filled accent button's background as a stylesheet value, for widgets that style
    themselves: the same gradient as `#primary`, or the flat accent in outlined themes."""
    if not polished():
        return T["accent_hover" if hover else "accent"]
    s = _accent_shades(T)
    top, mid, end = ((s["accent_top_hi"], T["accent_hover"], s["accent_end_hi"]) if hover
                     else (s["accent_top"], T["accent"], s["accent_end"]))
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {top}, stop:0.3 {mid}, "
            f"stop:1 {end})")


def accent_edge() -> str:
    """The border that goes with accent_fill(): a light rim on top (stylesheet text)."""
    if not polished():
        return f"border:1px solid {T['accent']};"
    s = _accent_shades(T)
    return f"border:1px solid {s['accent_rim_side']}; border-top-color:{s['accent_rim']};"


def polished(name: str | None = None) -> bool:
    """Whether theme `name` (default: the current one) gets POLISH_STYLE's depth."""
    return (name or current_name) not in OUTLINED




def paint_window_bg(p: QPainter, rect, origin: QPointF, width: float, height: float,
                    tk: dict[str, str] | None = None, textured: bool | None = None) -> None:
    """Paint the window background, aligned to its origin, without disk access: the flat
    page colour, or with Textured on, the theme's soft accent glow over it (the style
    kit's textures.paint_glow). `tk`: a theme other than the current one (a preview).
    Opaque widgets use this same background so scrolling leaves no seams."""
    tk = T if tk is None else tk
    textured = textures_on if textured is None else textured
    p.fillRect(rect, QColor(tk["bg"]))
    if not textured or (tk is T and not polished()):
        return
    textures.paint_glow(p, rect, origin, width, height, tk)


def _check_image(colour: str, size: int) -> QImage:
    """A rounded tick, drawn in code so it follows the theme's on-accent colour."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), size * 0.16)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
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
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    base = folder / f"check-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 14), (base.with_name(base.stem + "@2x.png"), 28)):
            if not path.exists():
                _check_image(colour, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _radio_image(ring: str, fill: str, dot: str, size: int) -> QImage:
    """A whole radio circle: a 1px ring (scaled with `size`) around `fill`, plus a centre
    dot when `dot` is set. Kept half a pixel inside the edge so no side gets clipped."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen_w = size / 16
    p.setPen(QPen(QColor(ring), pen_w))
    p.setBrush(QColor(fill))
    r = size / 2 - pen_w / 2 - size / 64
    p.drawEllipse(QPointF(size / 2, size / 2), r, r)
    if dot:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(size / 2, size / 2), size * 0.22, size * 0.22)
    p.end()
    return img


def _radio_url(ring: str, fill: str, dot: str = "") -> str:
    """The radio circle as a file for `image:`, plus a sharp high-DPI copy."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = "-".join(c.lstrip("#") for c in (ring, fill, dot) if c)
    base = folder / f"radio2-{name}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 16), (base.with_name(base.stem + "@2x.png"), 32)):
            if not path.exists():
                _radio_image(ring, fill, dot, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _chevron_image(colour: str, size: int, up: bool) -> QImage:
    """A rounded chevron (dropdown / stepper arrow), drawn in code like the tick."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), size * 0.17)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    tip, ends = (0.34, 0.64) if up else (0.66, 0.36)
    path = QPainterPath(QPointF(size * 0.18, size * ends))
    path.lineTo(QPointF(size * 0.5, size * tip))
    path.lineTo(QPointF(size * 0.82, size * ends))
    p.drawPath(path)
    p.end()
    return img


def _chevron_url(colour: str, size: int, up: bool, side: str = "") -> str:
    """`side` "left" / "right" turns the down chevron on its side (tab-bar scroll arrows)."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = side or ("up" if up else "down")
    base = folder / f"chevron-{name}{size}-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, px in ((base, size), (base.with_name(base.stem + "@2x.png"), size * 2)):
            if not path.exists():
                img = _chevron_image(colour, px, up)
                if side:
                    img = img.transformed(QTransform().rotate(90 if side == "left" else -90))
                img.save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def texture_style(selector: str, tk: dict[str, str] | None = None) -> str:
    """Apply the active tiling texture to a surface, including locally styled panels
    ("" with Textured off)."""
    return textures.texture_style(selector, T if tk is None else tk) if textures_on else ""


# Themes whose controls and cards keep an outline at rest: the others draw buttons,
# boxes and cards as flat fills, which in High Contrast (black on black) vanish.
OUTLINED = {"High Contrast"}
OUTLINE_STYLE = Template("""
QPushButton, QPushButton#danger, QLineEdit, QComboBox, QAbstractSpinBox,
QFrame#chip, QFrame#card QFrame#chip, QFrame#fxcard, QLabel#pill, QPushButton#vchip,
QFrame#card QToolButton#voicetile, QFrame#card QPushButton#voicecat { border:1px solid $border; }
QFrame#card, QFrame#setcard, QFrame#voicebar, QFrame#picked { border:1px solid $border; }
""")


def is_light(name: str | None = None) -> bool:
    """Whether theme `name` (default: the current one) has a light background."""
    c = QColor(THEMES.get(name or current_name, THEMES[DEFAULT])["bg"])
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140


def stylesheet(name: str | None = None) -> str:
    tk = tokens(name)
    tk.setdefault("font", FONT)
    outlined = (name or current_name) in OUTLINED
    # Navigation belongs to the window background, with a quiet inner edge.
    # Outlined themes keep their deliberate surface and strong divider.
    tk["rail_bg"] = tk["panel"] if outlined else _mix(tk["bg"], tk["panel"], 0.18)
    tk["rail_border"] = tk["border"] if outlined else _mix(tk["bg"], tk["border"], 0.35)
    # card titles in the text colour; High Contrast keeps its yellow to scan by
    tk["heading"] = tk["section"] if outlined else tk["text_hi"]
    tk["check"] = _check_url(tk["on_accent"])
    tk["check_off"] = _check_url(tk["muted"])   # ticked but greyed out: on $inset
    tk["radio"] = _radio_url(tk["off"], tk["card"])
    tk["radio_hover"] = _radio_url(tk["border_hi"], tk["card"])
    tk["radio_on"] = _radio_url(tk["accent"], tk["accent"], tk["on_accent"])
    tk["radio_on_hover"] = _radio_url(tk["accent_hi"], tk["accent_hi"], tk["on_accent"])
    tk["radio_off"] = _radio_url(tk["border"], tk["inset"])
    tk["radio_on_off"] = _radio_url(tk["border"], tk["inset"], tk["muted"])
    for key, colour in (("", tk["muted"]), ("_off", tk["off"])):
        tk["down" + key] = _chevron_url(colour, 10, up=False)
        tk["up" + key] = _chevron_url(colour, 10, up=True)
        tk["down_small" + key] = _chevron_url(colour, 8, up=False)
        tk["up_small" + key] = _chevron_url(colour, 8, up=True)
        tk["left" + key] = _chevron_url(colour, 10, False, side="left")
        tk["right" + key] = _chevron_url(colour, 10, False, side="right")
    css = STYLE.substitute(tk)
    if outlined:
        css += OUTLINE_STYLE.substitute(tk)
    else:
        css += POLISH_STYLE.substitute(polish_tokens(tk, is_light(name)))
    css += texture_style("QFrame#card, QFrame#setcard, QFrame#fxcard, QFrame#transport, "
                         "QDialog#transport, QFrame#deck", tk)
    return css


# Text colours code writes straight into a label's rich text or a widget's own stylesheet
# (status(), T["faint"]...): a live theme switch swaps the old theme's for the new one's.
_INLINE_KEYS = ("ok_text", "warn_text", "error_text", "danger_text", "text", "text_hi",
                "muted", "faint", "section", "accent", "accent_hi", "live_text", "accent_text",
                "accent_link")
_TEXT_COLOUR = re.compile(r"(?<![-\w])(color:\s*)(#[0-9a-fA-F]{6})(?![0-9a-fA-F])")


def _recolour_inline(widgets, old: dict[str, str]) -> None:
    """Only `color:` (text), never backgrounds or borders: those can be a sound's own
    colour that merely matches a token.

    Two tokens can share a hex in the old theme and part in the new one; the text
    doesn't say which token wrote it, so that hex goes to the new colour most of those
    tokens agree on, a tie to the one listed first in _INLINE_KEYS (the same result
    every time, whatever order the themes list their tokens in)."""
    votes: dict[str, dict[str, int]] = {}
    for k in _INLINE_KEYS:
        if k in old and k in T:
            new = votes.setdefault(old[k].lower(), {})
            new[T[k]] = new.get(T[k], 0) + 1
    # max() keeps the first of equal counts, and dicts keep _INLINE_KEYS order
    swap = {a: max(c, key=lambda k, c=c: c[k]) for a, c in votes.items()}
    swap = {a: b for a, b in swap.items() if a != b.lower()}
    if not swap:
        return

    def sub(text: str) -> str:
        return _TEXT_COLOUR.sub(lambda m: m[1] + swap.get(m[2].lower(), m[2]), text)
    for w in widgets:
        try:
            css = w.styleSheet()
            if "color" in css and (new := sub(css)) != css:
                w.setStyleSheet(new)
            if not hasattr(w, "textFormat"):   # QLabel: its rich text
                continue
            text = w.text()
            if "color" in text and (new := sub(text)) != text:
                w.setText(new)
        except RuntimeError:   # being deleted
            pass


# App-wide event filters written in Python (Space plays, quiet message boxes) are called
# for every event of every widget, and restyling sends each widget ~10 (font, palette
# and style changes: 20,000+ with Settings open) that none of them wants: a third of a
# theme switch went on them. Installed with app_filter(), they sit out each restyle.
# They also share one filter on the app (_Router) that hands an event only to those
# that asked for its type: Qt calling into Python once an event instead of once a
# filter. Resizing the window sends ~300 events a step: 1-2 ms of each on three filters.
_app_filters: list[QObject] = []


class _Router(QObject):
    """The one app-wide filter: each event goes to the filters that want its type,
    newest first, as Qt asks its own filters."""

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._wants: dict[int, frozenset | None] = {}   # id(filter) -> its types (None: all)
        self._by_type: dict = {}                        # event type -> filters, newest first
        self._every: list[QObject] = []                 # what other types go to

    def add(self, f: QObject, kinds) -> None:
        self._wants[id(f)] = None if kinds is None else frozenset(kinds)
        key = id(f)
        # gone with its owner (a closed window): out of the table, as Qt does with its own
        f.destroyed.connect(lambda *_a: self._drop(key))
        self._build()

    def _drop(self, key: int) -> None:
        if self._wants.pop(key, False) is not False:
            self._build()

    def _build(self) -> None:
        live = [f for f in reversed(_app_filters)
                if id(f) in self._wants and qt_valid(f)]
        self._every = [f for f in live if self._wants[id(f)] is None]
        kinds = set().union(*(k for k in self._wants.values() if k is not None))
        self._by_type = {k: [f for f in live if self._wants[id(f)] is None
                             or k in self._wants[id(f)]] for k in kinds}

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        for f in self._by_type.get(ev.type(), self._every):
            if f.eventFilter(obj, ev):
                return True
        return False


_router: _Router | None = None


def app_filter(app, f: QObject) -> None:
    """app.installEventFilter(f), but `f` is left out while apply() restyles, and it's
    only asked about the event types in its EVENTS (all of them without one)."""
    global _router
    if _router is None or not qt_valid(_router):
        _router = _Router(app)
        app.installEventFilter(_router)
    _app_filters[:] = [g for g in _app_filters if qt_valid(g)] + [f]
    _router.add(f, getattr(f, "EVENTS", None))


def _restyle(app, css: str) -> None:
    live = _router if _router is not None and qt_valid(_router) else None
    if live is not None:
        app.removeEventFilter(live)
    try:
        # cleared first: Qt swapping one app-wide sheet straight for another re-styles
        # every widget the slow way (3 s against 0.6 s with ~2000 widgets); empty and
        # then the new sheet gives the same look. No paint happens in between.
        app.setStyleSheet("")
        app.setStyleSheet(css)
    finally:
        if live is not None:
            app.installEventFilter(live)


def apply(app, name: str, live: str | None = None) -> str:
    """Switch the whole app to theme `name` (live). `live`: the user's own highlight
    colour ("" = the theme's), None = keep the one set already."""
    old = dict(T)
    if live is not None:
        set_live(live)
    name = set_current(name)
    css = stylesheet(name)
    if app.styleSheet() != css:   # the same sheet again (a new window): nothing changes
        _restyle(app, css)
    widgets = app.allWidgets()
    _recolour_inline(widgets, old)
    sheet = live_sheet()
    for w in widgets:   # restyled by apply_live: keep them in step with the new theme
        if w.objectName() in LIVE_NAMES and w.styleSheet():
            w.setStyleSheet(sheet)
    for w in widgets:   # hand-painted widgets read T in paintEvent
        w.update()
    return name


def apply_live(app, colour: str) -> str:
    """Switch only the live highlight to `colour` ("" = the theme's): restyles the
    LIVE_NAMES widgets and repaints, a fraction of a second where apply() takes
    seconds. Returns the colour kept ("" for the theme's, or for a bad one)."""
    old = dict(T)
    set_live(colour)
    T.clear()
    T.update(tokens())
    sheet = live_sheet()
    widgets = app.allWidgets()
    for w in widgets:
        if w.objectName() in LIVE_NAMES:
            w.setStyleSheet(sheet)
    _recolour_inline(widgets, old)
    for w in widgets:   # hand-painted widgets (a live tab's wash) read T in paintEvent
        w.update()
    return live_override


# --------------------------------------------------------------------------- logo

def paint_logo(p: QPainter, rect: QRectF, c1: str, c2: str, inset: float = 0.04):
    """The Onion Board mark: a gradient squircle holding an onion whose layers
    are drawn as sound-wave arcs — onion + soundboard in one shape."""
    s = rect.width()
    x0, y0 = rect.left(), rect.top()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # body
    g = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    body = QPainterPath()
    body.addRoundedRect(QRectF(x0 + s * inset, y0 + s * inset, s * (1 - 2 * inset), s * (1 - 2 * inset)),
                        s * 0.26, s * 0.26)
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
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    leaf = QPainterPath(pt(0, 0.29))
    leaf.cubicTo(pt(0, 0.20), pt(-0.04, 0.15), pt(-0.12, 0.12))
    leaf.moveTo(pt(0, 0.27))
    leaf.cubicTo(pt(0.01, 0.19), pt(0.05, 0.14), pt(0.10, 0.10))
    p.drawPath(leaf)
    # bulb
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(bulb(0.29), fg)
    # layers: inner outlines in the brand gradient, reading like sound waves
    if s >= 20:
        lp = QPen(g, max(1.0, s * 0.032))
        lp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(lp)
        for w in ((0.17, 0.07) if s >= 40 else (0.13,)):
            p.drawPath(bulb(w))
    # roots
    if s >= 32:
        rp = QPen(fg, max(1.0, s * 0.03))
        rp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(rp)
        for dx in (-0.06, 0.0, 0.06):
            p.drawLine(pt(dx * 0.6, 0.81), pt(dx, 0.87))
    p.restore()


BRAND = ("#7c5cff", "#ff4d8d")   # the app icon keeps its own colours in every theme


# Icons Windows draws (taskbar, exe, shortcuts) fill their square edge to edge, like other apps'
# do; with the in-app 4% margin the tile looked smaller and a touch low beside them.
ICON_INSET = 0.01


def logo_pixmap(size: int, c1: str | None = None, c2: str | None = None,
                inset: float = 0.04) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size), c1 or BRAND[0], c2 or BRAND[1], inset)
    p.end()
    return pm


def app_icon(c1: str | None = None, c2: str | None = None) -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(sz, c1, c2, ICON_INSET))
    return icon


def logo_image(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size), *BRAND, inset=ICON_INSET)
    p.end()
    return img
