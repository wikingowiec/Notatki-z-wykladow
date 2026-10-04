"""Karta profilu wydajności (Lekki / Zrównoważony / Pełna moc) – w Ustawieniach i w instalatorze.

Rysowana QPainterem w kolorach bieżącego motywu: nazwa, „kreski mocy” (1–3), dla jakiego sprzętu, opis,
ile trzeba pobrać, znaczek „Polecany” i zaznaczenie."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import perf
from . import theme as TH
from .theme import T, qcolor


class ProfileCard(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, compact: bool = False):
        super().__init__()
        self.key = key
        self.compact = compact
        self.selected = False
        self.recommended = False
        self.size_text = ""
        self.title = perf.LABELS.get(key, key)
        self.level = perf.ORDER.index(key) + 1 if key in perf.ORDER else 0
        self.for_text = perf.FOR.get(key, "")
        self.desc = perf.DESC.get(key, "")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 160 if compact else 206)
        self.setAccessibleName(f"Profil {self.title}")

    def set_state(self, selected: bool | None = None, recommended: bool | None = None, size_text: str | None = None):
        if selected is not None:
            self.selected = selected
        if recommended is not None:
            self.recommended = recommended
        if size_text is not None:
            self.size_text = size_text
        self.update()

    def sizeHint(self):
        return QSize(250, 160 if self.compact else 216)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w: int) -> int:
        fu = QFont(TH.UI_FAMILY)
        fu.setPixelSize(12)
        fm = QFontMetrics(fu)
        desc_h = 0 if self.compact else fm.boundingRect(0, 0, max(80, w - 40), 1000,
                                                         int(Qt.TextFlag.TextWordWrap), self.desc).height()
        return int(26 + 30 + 8 + 36 + 8 + desc_h + 12 + 18 + 16)

    def mousePressEvent(self, _e):
        self.clicked.emit(self.key)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit(self.key)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rad = t.r("lg")
        r = QRectF(self.rect()).adjusted(1.5, 11.5, -1.5, -1.5)    # miejsce na znaczek „Polecany” nad ramką
        p.setPen(QPen(qcolor(t.accent if self.selected else t.line), 2.4 if self.selected else 1))
        p.setBrush(qcolor(t.accent_soft if self.selected else t.surface))
        p.drawRoundedRect(r, rad, rad)
        if self.hasFocus():
            p.setPen(QPen(qcolor(t.accent, 120), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(4, 4, -4, -4), max(2, rad - 3), max(2, rad - 3))
        x, y, w = r.left() + 18, r.top() + 14, r.width() - 36

        # kreski mocy
        for i in range(3):
            h = 8 + i * 5
            bar = QRectF(x + i * 7, y + 26 - h, 4.5, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent if i < self.level else t.line2))
            p.drawRoundedRect(bar, 1.5, 1.5)
        # nazwa
        right = r.right() - 14
        tw = right - (x + 28) - (30 if self.selected else 0)
        f = QFont(TH.DISPLAY_FAMILY)
        f.setWeight(QFont.Weight.DemiBold)
        for px in (21, 20, 19, 18, 17, 16):        # długa nazwa w wąskiej karcie – mniejszy font zamiast „…”
            f.setPixelSize(px)
            if QFontMetrics(f).horizontalAdvance(self.title) <= tw:
                break
        p.setFont(f)
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(x + 28, y, tw, 30), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, int(tw)))
        if self.selected:
            c = QRectF(right - 22, y + 4, 22, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent))
            p.drawEllipse(c)
            p.setPen(QPen(qcolor(t.on_accent), 2))
            p.drawPolyline([c.center() + d for d in (QPointF(-5, 0), QPointF(-1.5, 3.5), QPointF(5, -3.5))])
            right -= 30
        y += 38

        fu = QFont(TH.UI_FAMILY)
        fu.setPixelSize(13)
        fu.setWeight(QFont.Weight.DemiBold)
        p.setFont(fu)
        p.setPen(qcolor(t.text2))
        fh = QFontMetrics(fu).boundingRect(0, 0, int(w), 200, int(Qt.TextFlag.TextWordWrap), self.for_text).height()
        p.drawText(QRectF(x, y, w, fh + 2), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, self.for_text)
        y += fh + 8
        fu.setWeight(QFont.Weight.Normal)
        fu.setPixelSize(12)
        p.setFont(fu)
        if not self.compact:
            p.setPen(qcolor(t.text3))
            dh = QFontMetrics(fu).boundingRect(0, 0, int(w), 1000, int(Qt.TextFlag.TextWordWrap), self.desc).height()
            p.drawText(QRectF(x, y, w, dh + 2), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft, self.desc)
        if self.size_text:
            fu.setWeight(QFont.Weight.DemiBold)
            p.setFont(fu)
            p.setPen(qcolor(t.text3))
            p.drawText(QRectF(x, r.bottom() - 30, w, 18), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(self.size_text, Qt.TextElideMode.ElideRight, int(w)))
        if self.recommended:      # znaczek na górnej krawędzi karty
            fb = QFont(TH.UI_FAMILY)
            fb.setPixelSize(11)
            fb.setWeight(QFont.Weight.Bold)
            fb.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
            p.setFont(fb)
            txt = "POLECANY"
            bw = p.fontMetrics().horizontalAdvance(txt) + 22
            badge = QRectF(r.right() - 18 - bw, r.top() - 10, bw, 21)
            p.setPen(QPen(qcolor(t.surface), 2))
            p.setBrush(qcolor(t.green))
            p.drawRoundedRect(badge, 10.5, 10.5)
            p.setPen(qcolor(t.on_accent))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, txt)
        p.end()
