"""Text from outside the app (web titles, channel and station names, names in imported
boards, backups and packs) shown as exactly what it says.

Qt reads label, tooltip and message-box text that looks like HTML as HTML (AutoText).
A name like `<img src=//host/a.png>` then has Windows open \\\\host\\a.png over the
network, the proxy, Tor and Offline mode notwithstanding, and markup can garble or
spoof the text around it. Every name that reaches one goes through here (a QLabel of
its own: setTextFormat(Qt.TextFormat.PlainText) instead)."""
from __future__ import annotations

import html


def plain_tip(text: str) -> str:
    """`text` as rich text that says exactly `text` (a tooltip or QMessageBox.question
    has no plain-text switch): escaped, in a paragraph, its line breaks kept."""
    return f"<p>{html.escape(text).replace(chr(10), '<br>')}</p>" if text else ""
