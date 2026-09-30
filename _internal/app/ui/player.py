"""Pasek odtwarzacza fragmentów nagrania (odsłuch miejsca z notatki)."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSlider, QToolButton, QWidget

from ..storage import Lecture, fmt_time
from .controls import icon_button, label, set_icon

log = logging.getLogger(__name__)


class PlayerBar(QFrame):
    """Odtwarza fragment [start, end] osi wykładu (także gdy nagranie ma kilka części)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("banner")
        self.lecture: Optional[Lecture] = None
        self.frag_start = 0.0
        self.frag_end: Optional[float] = None
        self.part_offset = 0.0
        self._pending_pos: Optional[float] = None
        self._player = None
        self._audio = None

        self.btn = QToolButton()
        self.btn.setObjectName("icon")
        self.btn.setFixedSize(34, 32)
        self.btn.clicked.connect(self.toggle)
        set_icon(self.btn, "pause", "accent", 18)
        self.title = label("", "headline")
        self.desc = label("", "footnote")
        self.desc.setMaximumWidth(520)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._seek_slider)
        self.time = label("", "secondary")
        self.btn_close = icon_button("xmark", "Zamknij odtwarzacz")
        self.btn_close.clicked.connect(self.close_player)
        text = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        tv = QVBoxLayout(text)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tv.addWidget(self.title)
        tv.addWidget(self.desc)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(10)
        lay.addWidget(self.btn)
        lay.addWidget(text, 2)
        lay.addWidget(self.slider, 3)
        lay.addWidget(self.time)
        lay.addWidget(self.btn_close)
        self.hide()

    # ------------------------------------------------------------------
    def _ensure(self):
        if self._player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.positionChanged.connect(self._on_pos)
            self._player.mediaStatusChanged.connect(self._on_status)
            self._player.playbackStateChanged.connect(self._on_state)
            self._player.errorOccurred.connect(lambda *_: self.desc.setText(
                "Nie udało się odtworzyć nagrania: " + (self._player.errorString() or "")))

    def choose(self, lecture: Lecture, frags: list, anchor_widget: QWidget, pos: Optional[QPoint] = None):
        """Jeden fragment – od razu gra. Kilka – lista z krótkimi opisami do wyboru."""
        if len(frags) == 1:
            f = frags[0]
            self.play(lecture, f.start, f.end, f.desc)
            return
        menu = QMenu(anchor_widget)
        menu.setToolTipsVisible(True)
        for f in frags:
            text = f"▶  {fmt_time(f.start)}–{fmt_time(f.end)}   {f.desc}"
            act = menu.addAction(text if len(text) < 110 else text[:107] + "…")
            act.setToolTip(f.desc)
            act.triggered.connect(lambda _=False, fr=f: self.play(lecture, fr.start, fr.end, fr.desc))
        menu.exec(pos or anchor_widget.mapToGlobal(anchor_widget.rect().center()))

    def play(self, lecture: Lecture, start: float, end: Optional[float] = None, desc: str = ""):
        self._ensure()
        path, local = lecture.locate(start)
        if path is None:
            self.show()
            self.title.setText("Brak nagrania")
            self.desc.setText("Ten wykład nie ma pliku audio.")
            return
        self.lecture = lecture
        self.frag_start, self.frag_end = start, end
        self.part_offset = start - local
        self.title.setText(f"{fmt_time(start)}–{fmt_time(end)}" if end else f"Od {fmt_time(start)}")
        self.desc.setText(desc)
        self.show()
        url = QUrl.fromLocalFile(str(path))
        if self._player.source() != url:
            self._pending_pos = local
            self._player.setSource(url)
        else:
            self._player.setPosition(int(local * 1000))
        self._player.play()

    def _on_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) \
                and self._pending_pos is not None:
            self._player.setPosition(int(self._pending_pos * 1000))
            self._pending_pos = None
            self._player.play()

    def _on_state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        set_icon(self.btn, "pause" if playing else "play", "accent", 18)

    def _span(self) -> tuple[float, float]:
        a = self.frag_start
        b = self.frag_end if self.frag_end else a + 600
        return a, max(b, a + 1)

    def _on_pos(self, ms: int):
        t = self.part_offset + ms / 1000
        a, b = self._span()
        if self.frag_end and t >= self.frag_end:
            self._player.pause()
        if not self.slider.isSliderDown():
            self.slider.setValue(int(1000 * min(1, max(0, (t - a) / (b - a)))))
        self.time.setText(f"{fmt_time(t)}")

    def _seek_slider(self, v: int):
        a, b = self._span()
        t = a + (b - a) * v / 1000
        if self._player:
            self._player.setPosition(int(max(0, t - self.part_offset) * 1000))

    def toggle(self):
        if not self._player:
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            t = self.part_offset + self._player.position() / 1000
            if self.frag_end and t >= self.frag_end - 0.3:
                self._player.setPosition(int(max(0, self.frag_start - self.part_offset) * 1000))
            self._player.play()

    def close_player(self):
        if self._player:
            self._player.stop()
        self.hide()
