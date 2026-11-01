"""The app style sheet's text: Qt style sheet templates filled with a theme's colour
tokens by theme.stylesheet()."""
from __future__ import annotations

from string import Template


STYLE = Template("""
QWidget { background:$bg; color:$text; font-family:'$font'; font-size:10pt; }
QDialog { background:$bg; }
QDialog#setupcard { border:1px solid $border; border-radius:16px; }
QFrame#card { background:$panel; border-radius:12px; }
QFrame#card QWidget { background:transparent; }
QFrame#card QDialog { background:$bg; }   /* a dialog opened from a card: not see-through (black) */
QFrame#card[interactive="true"] { border:1px solid transparent; }
QFrame#card[interactive="true"][hovered="true"] { background-color:$card_hi; border-color:$border_hi; }
QFrame#card[interactive="true"]:focus { background-color:$card_hi; border-color:$accent; }
QFrame#card[interactive="true"][playing="true"] { background-color:$card_hi; border:2px solid $accent; }
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
QFrame#oops { background:$panel; border:1px solid $border; border-radius:12px; }
QFrame#oops[tone="error"] { border:2px solid $error_text; }
QFrame#oops QLabel { background:transparent; border:none; padding:0; }
QLabel#oopstitle { font-size:11pt; font-weight:700; color:$text_hi; }
QLabel#oopstitle[tone="error"] { color:$error_text; }
QLabel#oopsline { color:$text; }
QLabel#eqlabel { color:$muted; font-size:8pt; }
QLabel#empty { color:$muted; font-size:15px; padding:8px 40px 40px 40px; }
QFrame#card QLabel#stepbox { background:$bg; border-radius:8px; padding:8px; margin-top:6px; }
QFrame#card QFrame#micflow { background:$bg; border:1px solid $border; border-radius:10px; }
QFrame#card QFrame#cleansettings { background:$bg; border:1px solid $border; border-radius:10px; }
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
/* the store's down: grey, one edge colour all round (the accent's lit top edge on grey
   looked cut off) */
QWidget#storebar QPushButton#primary:disabled { background:$btn; color:$muted;
    border-color:$border; }
QFrame#soundstoolbar { background:$panel; background-image:none; border:none;
    border-radius:12px; }
QFrame#soundstoolbar QLabel, QFrame#soundstoolbar QSlider { background:transparent; }
QFrame#soundstoolbar QPushButton { background:transparent; border:1px solid transparent;
    border-radius:9px; padding:0 10px; }
QFrame#soundstoolbar QPushButton:hover { background:$btn_hover; }
QFrame#soundstoolbar QPushButton:pressed { background:$btn_press; }
QFrame#soundstoolbar QPushButton:focus { border-color:$accent; }
QFrame#soundstoolbar QPushButton#soundadd { color:$accent_link; font-weight:600; }
/* Qt centres a menu button's icon + words in the room left of the arrow, which left
   18px blank before the icon (Search online looked far from the search box) and 6px
   after the arrow; no left padding brings that to 12px */
QFrame#soundstoolbar QPushButton[toolbarMenu="true"] { padding-left:0; padding-right:20px; }
QFrame#viewtoggle { background:$field; border:1px solid $border; border-radius:10px; }
QFrame#viewtoggle QPushButton#viewbtn, QFrame#soundstoolbar QFrame#viewtoggle QPushButton#viewbtn {
    background:transparent; border:1px solid transparent; border-radius:7px; padding:0;
    min-height:0; }
QFrame#viewtoggle QPushButton#viewbtn:hover:!checked,
QFrame#soundstoolbar QFrame#viewtoggle QPushButton#viewbtn:hover:!checked { background:$btn_hover; }
QFrame#viewtoggle QPushButton#viewbtn:checked,
QFrame#soundstoolbar QFrame#viewtoggle QPushButton#viewbtn:checked { background:$accent; }
QFrame#viewtoggle QPushButton#viewbtn:focus,
QFrame#soundstoolbar QFrame#viewtoggle QPushButton#viewbtn:focus { border:1px solid $text_hi; }
QLineEdit#soundssearch { background:$field; border:1px solid $border; border-radius:10px;
    padding:0 10px 0 4px; }
QLineEdit#soundssearch:hover { border-color:$border_hi; }
QLineEdit#soundssearch:focus { border-color:$accent; }
QPushButton#danger { background:$danger_bg; border:1px solid transparent; color:$danger_text; font-weight:600; }
QPushButton#danger:hover { background:$danger_hover; }
QPushButton#danger[quiet="true"] { background:transparent; }
QPushButton#danger[quiet="true"]:hover { background:$danger_bg; }
QPushButton#danger:focus { border-color:$accent; }
QPushButton#danger[mini="true"] { padding:0 6px; }   /* the mini player's "■ All": fits its narrowest row */
QPushButton#small, QPushButton#danger[small="true"] { padding:2px 8px; font-size:8pt; }
QPushButton#backhome { background:$danger_bg; border:2px solid $danger_text; color:$danger_text;
    font-weight:600; font-size:10pt; padding:5px 13px 5px 9px; border-radius:8px;
    margin:5px; }   /* room for the glow ytsearch.BackHome paints around it */
QPushButton#backhome:hover { background:$danger_hover; }
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
QFrame#railoutput QFrame#railoutputpanel { background:transparent; border:none; }
QFrame#railoutput QFrame#railoutputpanel[open="true"] { background:$btn; border-radius:8px; }
QFrame#railoutputpanel[open="true"] QPushButton#railoutputsetup[action="true"]:hover {
    background:$panel; }   /* the card's own: its words' colours are made for it */
QFrame#railoutput QPushButton#railoutputsetup { background:transparent;
    border:1px solid transparent; border-radius:6px; padding:0; }
QFrame#railoutput QPushButton#railoutputsetup[action="true"]:hover { background:$btn_hover; }
QFrame#railoutput QPushButton#railoutputsetup:focus { border-color:$accent; }
QFrame#railoutput QFrame#railoutputstrip { background:$warn_bg; border:none;
    border-radius:8px; }
QFrame#railoutputstrip QPushButton#railoutputsetup { border-radius:8px; }
QPushButton#railupdate { background:transparent; border:none; padding:0; }   /* painted: updatecard.UpdateCard */
QPushButton#railupdatecopy { background:transparent; border:1px solid transparent;
    border-radius:6px; padding:2px 6px; color:$accent_link; font-size:8.5pt; font-weight:600; }
QPushButton#railupdatecopy:hover { background:$panel; }
QPushButton#railupdatecopy:focus { border-color:$accent; }
QFrame#sidebar[compact="true"] QToolButton#railtab,
QFrame#sidebar[compact="true"] QPushButton { padding-top:2px; padding-bottom:2px; }
QPushButton#settings { padding:6px 14px; font-weight:600; }
QPushButton#langbutton { padding-left:7px; }   /* ui/settings/langpick.py: the round coin sits near its edge */
QFrame#transport, QFrame#deck { background:$panel; border-radius:12px; }
QDialog#transport { background:$panel; }
QDialog[popover="true"] { background:$panel; border:1px solid $border; }
QWidget#effectsbody, QWidget#effectchips { background:transparent; }
QWidget#effectchips QPushButton[listen="true"] { padding-right:30px; }
QPushButton#chipplay { border-radius:10px; background:$accent_tint; border:none; padding:0; }
QPushButton#chipplay:hover { background:$accent_tint_hi; }
QPushButton#chipplay[playing="true"] { background:$accent; }
QDialog#settingspage, QDialog#packspage { background:transparent; }
QFrame#card QLabel#packart, QDialog#packspage QLabel#packart { background:$accent_tint;
    border-radius:12px; }
QPushButton#filterchip { border-radius:13px; padding:4px 12px; min-height:18px; font-size:8.5pt;
    background:$btn; border:1px solid transparent; color:$text; }
QPushButton#filterchip:hover { background:$btn_hover; }
QPushButton#filterchip:checked { background:$accent; border-color:$accent; color:$on_accent; }
QPushButton#filterchip:focus { border-color:$accent; }
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
QPushButton#upnextchip { background:$panel; border:1px solid transparent; border-radius:14px;
    padding:0; }
QPushButton#upnextchip:hover { background:$btn_hover; }
QPushButton#upnextchip:focus { border-color:$accent; }
QFrame#chip QPushButton#chipname { font-weight:600; }
QFrame#chip QPushButton#chipstop { border-radius:12px; padding:0; }
QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; }
QLabel#iconlabel { background:transparent; }
QFrame#card QLabel#sourcepic { background:$inset; border-radius:8px; }   /* ui/sounds/sourcedialog.py: no thumbnail */
QPushButton#pill { border-radius:15px; padding:5px 14px; font-weight:600; }
QPushButton#pill[state="ok"] { color:$live_text; background:transparent; }
QPushButton#onair { border-radius:15px; padding:5px 14px; font-weight:700;
    background:$danger_bg; border:1px solid transparent; color:$danger_text; }
QPushButton#onair:checked { background:$live; border:1px solid transparent; color:$on_live; }
QPushButton#onair:checked:hover { background:$live_hover; }
QWidget#decktop { background:transparent; }
QWidget#editplayerpart { background:transparent; }   /* Edit sound's player: its texture shows */
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
QFrame#tipbar { background:$panel; border:1px solid $border_hi; border-radius:10px; }
QFrame#tipbar QLabel { background:transparent; color:$text; }
QFrame#tipbar QPushButton#primary { padding:2px 8px; font-size:8pt; }   /* as small as Just me */
/* the bars across the top of the window (ui/kit/topbar.py, DESIGN.md "Top bars") */
QFrame#topbar { background:$panel; border:1px solid $border; border-left:4px solid $accent_text;
    border-radius:8px; }
QFrame#topbar[tone="warn"] { border-left-color:$warn_text; }
QFrame#topbar[tone="ok"] { border-left-color:$ok_text; }
QFrame#topbar QLabel { background:transparent; color:$text; }
QFrame#topbar QLabel#topbarwords { font-size:9pt; }
QFrame#topbar QPushButton#primary, QFrame#topbar QPushButton#topbarbtn {
    min-height:28px; max-height:28px; padding:0 12px; font-size:9pt; font-weight:600; border-radius:6px; }
QFrame#topbar QPushButton#primary[roomy="true"] { min-height:0; max-height:16777215px; }   /* beside a text box, as tall as its line */
QFrame#topbar QPushButton#topbarbtn { background:$btn; color:$text; border:1px solid $border; }
QFrame#topbar QPushButton#topbarbtn:hover { background:$btn_hover; }
QFrame#topbar QPushButton#topbarclose { background:transparent; border:none; border-radius:13px; padding:0; }
QFrame#topbar QPushButton#topbarclose:hover { background:$btn_hover; }
QFrame#topbar QPlainTextEdit#enjoysaid { background:$field; color:$text; border:1px solid $border;
    border-radius:8px; padding:4px 6px 1px 6px; }   /* the words centred on their cap height */
QFrame#topbar QPlainTextEdit#enjoysaid:focus { border-color:$accent; }
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
QLineEdit:hover, QComboBox:hover { background:$card_hi; border-color:$border_hi; }
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
/* the line above outranks plain :hover, so a box in a card never lit up (and card_hi
   is 1.01:1 on card_ctl in Dark): the edge brightens too, as a spin box's does */
QFrame#card QComboBox:enabled:hover, QFrame#card QLineEdit:enabled:hover {
    background:$card_hi; border-color:$border_hi; }
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
QListWidget#settingscategories { font-weight:600; }   /* as the rail's tabs */
QListWidget#settingscategories::item { padding:4px; border-radius:8px; color:$muted; }
QListWidget#settingscategories::item:selected { background:$nav_sel; color:$text_hi; }
QListWidget#settingscategories::item:hover:!selected { background:$inset; color:$text; }
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
QMenu::indicator { left:5px; }   /* the tick under the icons, not 5 px left of them */
QMenu::separator { height:1px; background:$border; margin:5px 8px; }
QFrame#tabcard { background:$card_hi; border:1px solid transparent; border-radius:10px; margin:3px 4px; }
QFrame#tabcard:hover { border-color:$border_hi; background:$btn_hover; }
/* inside a textured card the box is see-through: a hovered one lifts with a see-through
   wash, so the card's texture and the buttons on the box still show */
QFrame#setcard QFrame#tabcard:hover { background:$box_hover; }
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
QPushButton[nudge="true"] { background:$accent_tint; border-color:$accent; color:$accent_text; }
QPushButton[nudge="true"]:hover { background:$accent_tint_hi; }
QPushButton#resetfx[nudge="true"] { color:$text; }   /* Edit sound: readable on every tint */
QPushButton#voicetile { text-align:left; padding:9px 10px; border-radius:10px; }
QPushButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QPushButton#voicetile[art="true"] { padding:5px 10px 5px 6px; }
QPushButton#voicetile:hover:!checked { border-color:$border_hi; }
/* the Voice tab: its row of tabs, the voice changer's picture cards, the picked voice */
QPushButton#voicetab { border-radius:10px; padding:9px 16px; background:$btn; border:1px solid $border; font-weight:600; font-size:10pt; }
QFrame#voicetabrule { background:$border; border:none; }
QWidget#setupsbar { background:transparent; }
QFrame#setupsstrip { border:1px solid $border; border-radius:10px; background:$bg; }
QLabel#setupstitle { color:$muted; font-size:8.5pt; font-weight:600; background:transparent; }
QWidget#setupsbar QPushButton#voicecat { border-radius:12px; padding:3px 10px; min-height:16px; font-size:8.5pt; background:$btn; border:1px solid transparent; color:$text; }
QWidget#setupsbar QPushButton#voicecat:hover:!checked { background:$btn_hover; }
QWidget#setupsbar QPushButton#voicecat:checked { background:$accent; border-color:$accent_hi; color:$on_accent; font-weight:600; }
QPushButton#voicetab:hover:!checked { background:$btn_hover; border-color:$border_hi; }
QPushButton#voicetab:checked { background:$accent; color:$on_accent; border-color:$accent_hi; }
QFrame#card QToolButton#voicetile { background:$card; color:$text; border:1px solid transparent; border-radius:12px; padding:8px 4px 6px 4px; font-size:8.5pt; }
QFrame#card QToolButton#voicetile:hover:!checked { background:$btn_hover; border-color:$border_hi; }
QFrame#card QToolButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QFrame#card QToolButton#voicetile[missing="true"]:!checked { color:$muted; }
QFrame#card QToolButton#voicetile:focus { border-color:$accent; }
QFrame#card QToolButton#voicetile:checked:focus { border-color:$text_hi; }
QFrame#card QFrame#picked { background:$inset; border-radius:10px; }
QFrame#card QPushButton#voicecat { border-radius:12px; padding:4px 12px; min-height:16px; font-size:8.5pt; background:$btn; border:1px solid transparent; color:$text; }
QFrame#card QPushButton#voicecat:hover:!checked { background:$btn_hover; }
QFrame#card QPushButton#voicecat:checked { background:$accent; border-color:$accent_hi; color:$on_accent; font-weight:600; }
QFrame#card QPushButton#voicepick { background:$field; border:1px solid $border; border-radius:10px;
    padding:0 28px 0 12px; text-align:left; font-weight:600; color:$text_hi; }
QFrame#card QPushButton#voicepick:hover, QFrame#card QLineEdit#voicesearch:hover { border-color:$border_hi; }
QFrame#card QPushButton#voicepick:focus, QFrame#card QPushButton#voicepick:open,
QFrame#card QLineEdit#voicesearch:focus { border-color:$accent; }
QFrame#card QPushButton#voicepick::menu-indicator { right:10px; }
QFrame#card QLineEdit#voicesearch { background:$field; border:1px solid $border; border-radius:10px;
    padding:0 8px 0 2px; }
QMenu#voicepickmenu::item { padding:8px 16px 8px 12px; min-width:170px; }
QFrame#card QToolButton#voicestar { background:transparent; border:none; border-radius:11px; padding:0; }
QFrame#card QToolButton#voicestar:hover { background:$card; border:1px solid $border_hi; }
QFrame#card QToolButton#voicestar[picked="true"]:hover { background:$btn_hover; border:none; }
QFrame#card QFrame#voicebox { background:$inset; border:1px solid $border; border-radius:8px; }
QFrame#picked[pinned="true"] { background:$panel; border-radius:12px; }
QFrame#picked QLabel#pickedname { color:$text_hi; font-size:11pt; font-weight:700; }
QFrame#picked QLabel#pickedkind { color:$muted; font-size:11pt; }
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
QFrame#fxcard[hero="true"] { background-color:$card; }
QFrame#fxcard[fresh="true"] { background-color:$card_hi; border:2px solid $accent_hi; }
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
QPushButton#vchip { background:$inset; border:1px solid transparent; border-radius:13px; padding:4px 24px 4px 11px; color:$muted; font-size:9pt; font-weight:600; min-height:0; }
QToolButton#vchipx { background:transparent; border:none; border-radius:9px; padding:0; }
QToolButton#vchipx:hover { background:$btn_hover; }
QPushButton#vchip:hover { color:$text; }
QPushButton#vchip[state="on"] { color:$live_text; border-color:$live_border; }
QPushButton#vchip[state="warn"] { color:$warn_text; border-color:$warn_text; background:$warn_bg; }
QLabel#achscore { background:$inset; border:1px solid $live_border; border-radius:8px; padding:2px 12px; color:$live_text; font-size:10pt; font-weight:700; }
QLabel#pill { background:$inset; border:1px solid transparent; border-radius:10px; padding:3px 10px; color:$muted; font-size:8.5pt; font-weight:600; }
QLabel#pill[slow="true"] { color:$warn_text; border-color:$warn_text; }
QLabel#pill[on="true"] { color:$live_text; border-color:$live_border; }
QLabel#pill[tone="muted"] { border-color:$muted; }
QLabel#pill[tone="ok"] { color:$live_text; border-color:$live_border; }
QLabel#pill[tone="warn"] { color:$warn_text; border-color:$warn_text; }
QLabel#pill[tone="error"] { color:$error_text; border-color:$error_text; }
QLabel#pill[tone="beta"] { color:$bg; background:$ok_text; border-color:$ok_text; border-radius:7px; padding:1px 8px; font-weight:700; }   /* ui/store/storetab.py: the green Beta tag */
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
/* in a card too (an app row's Record): the card's accent fill had its white icon on Hacker's green */
QFrame#card QPushButton#rec:checked { background:#d32f2f; border:1px solid #ff6b6b; color:white; }
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
/* Settings > Look: a group's soft box and the thin line between its settings */
QFrame#setcard QFrame#lookgroup { background:$inset; border-radius:10px; }
QFrame#setcard QFrame#lookrule { background:$border; }
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
QFrame#setcard QLineEdit:hover, QFrame#setcard QComboBox:hover { background:$card; border-color:$border_hi; }
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
QTreeWidget#cliplist { background:$inset; color:$text; border:none; border-radius:8px;
    padding:4px; outline:0; }   /* ui/apps/clipshelf.py: rows are painted by ClipRowDelegate */
QTreeWidget#cliplist::item, QTreeWidget#cliplist::item:hover,
QTreeWidget#cliplist::item:selected { background:transparent; border:none; }
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
/* a card that pops up over the board (Up next's list): an edge, and its names from the left */
QFrame#card[popup="true"] { border:1px solid $border_hi; }
QFrame#card[popup="true"] QPushButton#chipname { text-align:left; }
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
QFrame#card[interactive="true"][hovered="true"] { background-color:$card_hi; border-color:$border_hi; }
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
/* every accent-filled on-state (tabs, mode tiles, chips) gets the main button's gloss */
QPushButton:checked, QFrame#card QPushButton:checked, QFrame#setcard QPushButton:checked,
QFrame#viewtoggle QPushButton#viewbtn:checked,
QFrame#soundstoolbar QFrame#viewtoggle QPushButton#viewbtn:checked,
QPushButton#chipplay[playing="true"], QPushButton#voicetile:checked,
QFrame#card QToolButton#voicetile:checked, QWidget#setupsbar QPushButton#voicecat:checked,
QFrame#card QPushButton#voicecat:checked, QPushButton#voicetab:checked,
QPushButton#subchip:checked {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top, stop:0.3 $accent,
        stop:1 $accent_end); }
QPushButton:checked:hover, QPushButton#voicetile:checked:hover,
QFrame#card QToolButton#voicetile:checked:hover,
QWidget#setupsbar QPushButton#voicecat:checked:hover,
QFrame#card QPushButton#voicecat:checked:hover, QPushButton#voicetab:checked:hover,
QPushButton#subchip:checked:hover {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_top_hi,
        stop:0.3 $accent_hover, stop:1 $accent_end_hi); }
QPushButton#onair:checked, QPushButton#power:checked, QFrame#card QPushButton#power:checked,
QFrame#setcard QPushButton#power:checked, QPushButton#live:checked,
QFrame#card QPushButton#live:checked {
    background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $live_top, stop:1 $live); }
""")


OUTLINE_STYLE = Template("""
QPushButton, QPushButton#danger, QLineEdit, QComboBox, QAbstractSpinBox,
QFrame#chip, QFrame#card QFrame#chip, QFrame#fxcard, QLabel#pill, QPushButton#vchip,
QFrame#card QToolButton#voicetile, QFrame#card QPushButton#voicecat,
QWidget#setupsbar QPushButton#voicecat, QPushButton#filterchip { border:1px solid $border; }
QFrame#card, QFrame#setcard, QFrame#voicebar, QFrame#picked { border:1px solid $border; }
""")
