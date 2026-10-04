"""Nawigacja po notatce: pozycje kotwic w dokumencie, procent przeczytania, „Przejdź do” (kolejne ramki
Definicja / Wzór / Przykład / Ważne) i oś wykładu pod notatką (tematy w kolorach kategorii, zaznaczenia,
bieżące miejsce, klik = przewinięcie)."""
from __future__ import annotations

import re

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from ..storage import fmt_time
from .theme import T, qcolor

KINDS = [("def", "Definicje"), ("wz", "Wzory"), ("prz", "Przykłady"), ("waz", "Ważne")]


def anchor_positions(reader) -> dict[str, float]:
    """Kotwica → położenie (y) w dokumencie czytnika."""
    doc = reader.document()
    lay = doc.documentLayout()
    out: dict[str, float] = {}
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                for name in frag.charFormat().anchorNames():
                    if name not in out:
                        out[name] = lay.blockBoundingRect(block).top()
            it += 1
        block = block.next()
    return out


def section_times(md: str) -> dict[int, tuple[float, float]]:
    """Numer tematu → (początek, koniec) w sekundach – z linii „*24:10–38:00*” pod nagłówkiem."""
    from ..notes_style import _secs
    out = {}
    for m in re.finditer(r"^##\s+(\d+)\.[^\n]*\n\*(\d[\d:]*)\s*[–-]\s*(\d[\d:]*)\*", md, re.MULTILINE):
        out[int(m.group(1))] = (_secs(m.group(2)), _secs(m.group(3)))
    return out


class JumpButtons(QWidget):
    """„Przejdź do”: Definicje 6 · Wzory 3 · Przykłady 3 · Ważne 8 – klik przeskakuje do następnej ramki."""
    jump = Signal(str)

    def __init__(self):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(6)
        self.buttons = {}
        for i, (k, name) in enumerate(KINDS):
            b = QPushButton(name)
            b.setObjectName("jump")
            b.setProperty("kind", k)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=k: self.jump.emit(k))
            g.addWidget(b, i // 2, i % 2)
            self.buttons[k] = b

    def set_counts(self, counts: dict[str, int]):
        for k, name in KINDS:
            n = counts.get(k, 0)
            b = self.buttons[k]
            b.setText(f"{name} {n}" if n else name)
            b.setEnabled(bool(n))
            b.setToolTip(f"Następna ramka: {name.lower()}" if n else f"W tej notatce nie ma: {name.lower()}")


class LectureTimeline(QWidget):
    """Pasek 40 px pod notatką. sections: [(numer, start, koniec, kolor, kotwica, tytuł)], marks: [sekundy]."""
    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sections: list = []
        self.marks: list[float] = []
        self.duration = 0.0
        self.now = 0.0
        self._hover = None

    def set_data(self, sections: list, marks: list[float], duration: float):
        self.sections = sections
        self.marks = marks
        self.duration = max([duration] + [s[2] for s in sections] + [1.0])
        self.update()

    def set_now(self, t: float):
        if abs(t - self.now) > 0.5:
            self.now = t
            self.update()

    def sizeHint(self):
        return QSize(400, 40)

    def _bar(self) -> QRectF:
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance("8:88:88 / 8:88:88") + 16
        return QRectF(4, 16, self.width() - tw - 12, 8)

    def _x(self, t: float) -> float:
        b = self._bar()
        return b.left() + b.width() * min(1.0, max(0.0, t / self.duration))

    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        b = self._bar()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.separator))
        p.drawRoundedRect(b, 4, 4)
        for num, s, e, color, _a, _title in self.sections:
            x0, x1 = self._x(s), self._x(e)
            r = QRectF(x0 + 1, b.top(), max(2.0, x1 - x0 - 2), b.height())
            c = qcolor(color)
            if self._hover is not None and s <= self._hover < e:
                c = c.lighter(118) if t.dark else c.darker(112)
            p.setBrush(c)
            p.drawRoundedRect(r, 3, 3)
        for m in self.marks:
            x = self._x(m)
            p.setBrush(qcolor(t.markLine))
            p.setPen(QPen(qcolor(t.surface), 1.5))
            p.drawEllipse(QRectF(x - 4.5, b.top() - 9, 9, 9))
        x = self._x(self.now)
        p.setPen(QPen(qcolor(t.text), 2))
        p.drawLine(int(x), int(b.top() - 6), int(x), int(b.bottom() + 6))
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() - 0.8)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(b.right() + 10, 0, self.width() - b.right() - 12, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{fmt_time(self.now)} / {fmt_time(self.duration)}")
        p.end()

    def _time_at(self, x: float) -> float:
        b = self._bar()
        return max(0.0, min(1.0, (x - b.left()) / max(1.0, b.width()))) * self.duration

    def mouseMoveEvent(self, e):
        b = self._bar()
        x = e.position().x()
        self._hover = self._time_at(x) if b.left() <= x <= b.right() else None
        sec = next((s for s in self.sections if self._hover is not None and s[1] <= self._hover < s[2]), None)
        self.setToolTip(f"{sec[0]}. {sec[5]} · {fmt_time(self._hover)}" if sec else "")
        self.update()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        b = self._bar()
        if b.left() - 4 <= e.position().x() <= b.right() + 4:
            self.seek.emit(self._time_at(e.position().x()))
