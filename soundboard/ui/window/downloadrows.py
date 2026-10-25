"""Part of the download card (ui/window/downloadbar.py `DownloadBar`): the list under the running
pick: the picks waiting, up next, added and failed, one row each, and retrying a failed one."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import theme
from soundboard.ui.kit.widgets import fmt_time
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.window.downloadbits import QUEUE_ROWS, ROW_THUMB, THUMB_W, _QueueRow
from soundboard.ui.window.downloadparts import ElideLabel, pretty_title

if TYPE_CHECKING:
    from typing import Any

    _Base = QFrame
else:
    _Base = object


class DownloadRows(_Base):
    if TYPE_CHECKING:   # what DownloadBar has that these use
        _added: Any
        _clear_and_hide: Any
        _corner: Any
        _failed: Any
        _forget: Any
        _icon_button: Any
        _mini: Any
        _picture: Any
        _queue: Any
        _room: Any
        _shown_rows: Any
        _sound_buttons: Any
        _sync_head: Any
        _tight: Any
        _up_next: Any
        _wind_down: Any
        cancel_requested: Any
        front_requested: Any
        kind: Any
        lbl_status: Any
        retry_requested: Any
        room_changed: Any
        rows: Any
        scroll_area: Any
        sound_for: Any
        stage: Any
        thumb_lookup: Any
        up_next_drop: Any
        url: Any

    def _others_failed(self) -> list[dict]:
        """The picks that failed, but not the one on the running row (it says so itself)."""
        return [f for f in self._failed if f["url"] != self.url]

    def _others_added(self) -> list[dict]:
        return [a for a in self._added if a["url"] != self.url]

    def _fill_rows(self):
        """The list under the running row, rebuilt: the picks waiting (a click makes one
        next up), the ones that failed (each with Retry), then the ones added already,
        newest first. A handful of rows (the queue is capped)."""
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget() if item else None
            if w is not None:   # hidden now: it's only freed later, and mustn't show till then
                w.hide()
                w.deleteLater()
        failed = self._others_failed()
        added = self._others_added()[::-1]
        nxt = [{"url": u, "title": t} for t, u in self._up_next if u != self.url]
        picks = ([(q, "next") for q in nxt] + [(q, "wait") for q in self._queue]
                 + [(f, "failed") for f in failed] + [(a, "added") for a in added])
        rows = [self._row(q, how, first=(how == "wait" and i == 0))
                for i, (q, how) in enumerate(picks)]
        for row in rows:
            self.rows.addWidget(row)
        self.rows.addStretch(1)
        self.scroll_area.setVisible(bool(picks) and self._room == "open")
        shown = rows[:QUEUE_ROWS]
        full = (sum(r.sizeHint().height() for r in shown)
                + max(0, len(shown) - 1) * self.rows.spacing())
        # as tall as the first few rows (more scroll)
        self.scroll_area.setFixedHeight(full)
        if len(shown) != self._shown_rows:   # taller or shorter: the window fits it again
            self._shown_rows = len(shown)
            self.room_changed.emit()

    def _row(self, q: dict, how: str, first: bool) -> QFrame:
        row = _QueueRow()
        row.setObjectName("queuerow")
        row.setProperty("how", how)
        row.setAttribute(Qt.WidgetAttribute.WA_Hover)
        if how == "wait" and not first:   # the first one is next up already
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(_("Download this one next"))
            row.clicked.connect(lambda u=q["url"]: self.front_requested.emit(u))
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 6, 6)
        rl.setSpacing(12)
        if not self._tight:   # centred under the running row's picture, titles in line
            if not self._corner:
                rl.addSpacing(THUMB_W)   # under Bun's column (the card's: under Bun)
            pic = QLabel()
            pic.setFixedSize(THUMB_W, ROW_THUMB[1])
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pic.setPixmap(self._picture(self.thumb_lookup(q["url"]), *ROW_THUMB, 6))
            rl.addWidget(pic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        title = ElideLabel()
        name = pretty_title(q.get("title", "")) or _("Sound")
        title.setText(name)
        title.setToolTip(plain_tip(name))
        title.setObjectName("queuetitle")
        title.setProperty("waiting", how == "wait")
        col.addWidget(title)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        why = QLabel({"next": _("Up next"), "wait": _("Waiting to add"),
                      "failed": _("Couldn't download"),
                      "added": _("✓ Added to your sounds")}[how])
        why.setObjectName("downloadmeta" if how in ("wait", "next") else "downloadstatus")
        theme.set_tone(why, {"failed": "error", "added": "ok"}.get(how, ""))
        line.addWidget(why)
        secs = q.get("seconds") or 0
        if secs and how != "failed":
            length = QLabel(fmt_time(secs))
            length.setObjectName("downloadmeta")
            line.addWidget(length)
        line.addStretch(1)
        col.addLayout(line)
        rl.addLayout(col, 1)
        if how == "failed":
            again = QPushButton(_("Retry"))
            again.setObjectName("retrybutton")
            again.setCursor(Qt.CursorShape.PointingHandCursor)
            again.clicked.connect(lambda _c=False, u=q["url"]: self._retry(u))
            rl.addWidget(again, 0, Qt.AlignmentFlag.AlignVCenter)
        if how == "added" and not self._mini and self.sound_for(q["url"]):
            play, show = self._sound_buttons(lambda u=q["url"]: u)
            play.show()
            show.show()
            rl.addWidget(play, 0, Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(show, 0, Qt.AlignmentFlag.AlignVCenter)
        if how != "added":
            x = self._icon_button("close", _("Remove"), 24)
            x.clicked.connect(lambda _c=False, u=q["url"], h=how:
                              self._forget(u) if h == "failed"
                              else self.up_next_drop.emit(u) if h == "next"
                              else (usage.used("dl-cancel"), self.cancel_requested.emit(u)))
            rl.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _waits(self) -> bool:
        """The running row's Play is downloaded, but waits in Up next for the song
        playing now: it mustn't say Playing (a click seemed to do nothing)."""
        return (self.kind == "play" and self.stage == "done"
                and any(u == self.url for _t, u in self._up_next))

    def _say_play(self):
        if self._waits():
            ahead = next(i for i, (_t, u) in enumerate(self._up_next) if u == self.url)
            self.lbl_status.setText(_("Up next · {n} before it", n=ahead) if ahead
                                    else _("Up next"))
            theme.set_tone(self.lbl_status, "")
        else:
            self.lbl_status.setText(_("▶ Playing"))
            theme.set_tone(self.lbl_status, "ok")

    def set_playing(self, url: str):
        """A Play started (linkbar.played): the one that waited in Up next plays now."""
        if url != self.url or self.kind != "play" or self.stage != "done":
            return
        if self._alone():
            self._clear_and_hide()
            return
        self._say_play()
        self._sync_head()
        if not self._up_next and not self._others_failed():
            self._wind_down(7000)

    def _alone(self) -> bool:
        """Nothing else on the list: no pick waiting, none in Up next, none failed. A
        Play that started playing then has nothing to say the player bar doesn't."""
        return not (self._queue or self._up_next or self._failed)

    def _retry(self, url: str):
        """Retry: the failed pick is picked again (it starts, or waits its turn)."""
        item = next((f for f in self._failed if f["url"] == url), None)
        if item is None:
            return
        self._forget(url)
        usage.used("dl-retry")
        self.retry_requested.emit(dict(item))
