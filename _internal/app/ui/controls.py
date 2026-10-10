"""Kontrolki: przełącznik, kontrolka segmentowa / zakładki, grupy ustawień, karty wyboru, przycisk nagrywania,
miernik, arkusze (karty z cieniem), elastyczne układy dla wąskich i szerokich okien."""
from __future__ import annotations

import weakref

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from .theme import T, display_font, icon_pixmap, palette_color, qcolor, soft, svg_icon, theme

# ---------------------------------------------------------------------------
# Ikony zależne od motywu
# ---------------------------------------------------------------------------
_icon_refs: list = []


def show_if(w, on) -> None:
    """setVisible bez migających okien: widżet bez rodzica po setVisible(True) staje się osobnym oknem
    (na Windows widać wtedy przy starcie dziesiątki pustych okienek „Wykłady”)."""
    if not on:
        w.hide()
    elif w.parentWidget() is not None:
        w.show()
    else:            # pokaże się sam razem z rodzicem, gdy trafi do układu
        w.setAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide, False)
        w.setAttribute(Qt.WidgetAttribute.WA_WState_Hidden, False)


def set_icon(w, name: str, role: str = "text2", size: int = 18):
    """Ustawia ikonę i zapamiętuje ją, by przemalować po zmianie motywu (role = nazwa tokenu koloru)."""
    color = role if role.startswith("#") else getattr(T(), role)
    w.setIcon(svg_icon(name, color, size))
    w.setIconSize(QSize(size, size))
    _icon_refs[:] = [x for x in _icon_refs if x[0]() is not None and x[0]() is not w]
    _icon_refs.append((weakref.ref(w), name, role, size))


def _refresh_icons():
    alive = []
    for ref, name, role, size in _icon_refs:
        w = ref()
        if w is None:
            continue
        try:
            color = role if role.startswith("#") else getattr(T(), role)
            w.setIcon(svg_icon(name, color, size))
            alive.append((ref, name, role, size))
        except RuntimeError:
            pass
    _icon_refs[:] = alive


theme().changed.connect(_refresh_icons)


def icon_button(name: str, tooltip: str, role: str = "text2", size: int = 18) -> QToolButton:
    b = QToolButton()
    b.setObjectName("icon")
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedSize(40, 40)
    set_icon(b, name, role, size)
    return b


def label(text: str = "", obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if obj in ("sectionHeader", "overline", "recLabel"):
        f = lb.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        lb.setFont(f)
    lb.setWordWrap(wrap)
    return lb


def hairline() -> QFrame:
    f = QFrame()
    f.setObjectName("hairline")
    return f


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ---------------------------------------------------------------------------
# Układy elastyczne
# ---------------------------------------------------------------------------
class AdaptiveBox(QWidget):
    """Rząd, który przy małej szerokości zamienia się w kolumnę (np. nagłówek: tytuł | przyciski)."""

    def __init__(self, threshold: int = 640, spacing: int = 12, vspacing: int | None = None, parent=None):
        super().__init__(parent)
        self.threshold = threshold
        self.hspacing = spacing
        self.vspacing = spacing if vspacing is None else vspacing
        self.lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(spacing)
        self.vertical = False
        self._align: dict = {}

    def add(self, w, stretch: int = 0, align_h=None, align_v=None):
        """align_h – wyrównanie w układzie poziomym, align_v – w pionowym."""
        self._align[id(w)] = (w, align_h, align_v)
        self.lay.addWidget(w, stretch)
        self._apply_align()
        return w

    def add_stretch(self):
        self.lay.addStretch()

    def _apply_align(self):
        for w, ah, av in self._align.values():
            a = av if self.vertical else ah
            self.lay.setAlignment(w, a if a is not None else Qt.AlignmentFlag(0))

    def set_vertical(self, v: bool):
        if v == self.vertical:
            return
        self.vertical = v
        self.lay.setDirection(QBoxLayout.Direction.TopToBottom if v else QBoxLayout.Direction.LeftToRight)
        self.lay.setSpacing(self.vspacing if v else self.hspacing)
        self._apply_align()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.set_vertical(self.width() < self.threshold)


def paint_shadow(p: QPainter, r: QRectF, radius: float, strength: float = 1.0):
    """Miękki cień pod kartą (kilka półprzezroczystych warstw – tanio, bez QGraphicsEffect)."""
    t = T()
    if not t.shadows:          # Akademia: zamiast cieni ramka 1 px (rysuje ją sama karta)
        return
    base = 0.9 if t.dark else 0.55
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i, (grow, dy, a) in enumerate(((1, 1, 16), (3, 3, 9), (6, 6, 5), (10, 9, 3))):
        c = qcolor(t.shadow)
        c.setAlpha(int(a * base * strength * (2.2 if t.dark else 1)))
        p.setBrush(c)
        p.drawRoundedRect(r.adjusted(-grow, -grow + dy, grow, grow + dy), radius + grow, radius + grow)
    p.restore()


class Sheet(QFrame):
    """Arkusz papieru: zaokrąglona karta z cieniem; opcjonalnie pasek koloru i linie jak na fiszce."""
    PAD = 12

    def __init__(self, radius: float | None = None, ruled: bool = False, parent=None):
        super().__init__(parent)
        self._radius = radius

        self.ruled = ruled
        self.strip = ""
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.lay = QVBoxLayout(self)
        p = self.PAD
        self.lay.setContentsMargins(p, p - 4, p, p + 4)


    @property
    def radius(self) -> float:
        return T().r("xl") if self._radius is None else self._radius

    def set_strip(self, color: str):
        self.strip = color
        self.update()

    def sheet_rect(self) -> QRectF:
        p = self.PAD
        return QRectF(self.rect()).adjusted(p, p - 4, -p, -p - 4)

    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.sheet_rect()
        paint_shadow(p, r, self.radius)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, qcolor(t.surface))
        p.save()
        p.setClipPath(path)
        if self.ruled:
            line = qcolor(t.separator)
            line.setAlpha(90 if t.dark else 120)
            p.setPen(QPen(line, 1))
            y = r.top() + 92
            while y < r.bottom() - 10:
                p.drawLine(int(r.left()), int(y), int(r.right()), int(y))
                y += 36
            if self.strip:
                p.setPen(QPen(qcolor(self.strip, 170), 1.6))
                p.drawLine(int(r.left()), int(r.top() + 52), int(r.right()), int(r.top() + 52))
        if self.strip:
            p.fillRect(QRectF(r.left(), r.top(), r.width(), 6), qcolor(self.strip))
        p.restore()
        p.setPen(QPen(qcolor(t.separator), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        p.end()


# ---------------------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    """Przełącznik."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 25)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)   # nie „pos” – to pozycja widżetu w oknie!
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_pos(self):
        return self._pos

    def set_pos(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_pos, set_pos)

    def sizeHint(self):
        return QSize(42, 25)

    def paintEvent(self, _e):
        t = T()
        if self._anim.state() != QPropertyAnimation.State.Running:     # zmiana stanu z kodu (bez animacji)
            self._pos = 1.0 if self.isChecked() else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off = qcolor(t.line2)
        on = qcolor(t.accent)
        c = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            c.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0.5, 42, 24), 12, 12)
        x = 2.5 + self._pos * 17
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QRectF(x, 3.3, 20, 20))
        p.setBrush(qcolor(t.surface if not t.dark else t.ink))
        p.drawEllipse(QRectF(x, 2.5, 20, 20))
        p.end()


# ---------------------------------------------------------------------------
class SegmentedControl(QFrame):
    """Wybór jednej z kilku opcji: „pill” (pigułki na tle) albo „tabs” (zakładki z podkreśleniem)."""
    changed = Signal(int)

    def __init__(self, items: list[str], parent=None, style: str = "pill"):
        super().__init__(parent)
        tabs = style == "tabs"
        self.setObjectName("tabTrack" if tabs else "segTrack")
        lay = QHBoxLayout(self)
        m = 0 if tabs else 3
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(0 if tabs else 2)
        self.tabs = tabs
        self.short: dict[str, str] = {}      # krótsze nazwy zakładek, gdy brakuje miejsca
        self._dense = None
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, text in enumerate(items):
            b = QPushButton(text)
            b.setObjectName("tab" if tabs else "seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if not tabs:
                f = QFont(b.font())
                f.setWeight(QFont.Weight.DemiBold)
                b.setMinimumWidth(QFontMetrics(f).horizontalAdvance(text) + 38)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        if tabs:
            lay.addStretch()
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(QSizePolicy.Policy.Expanding if tabs else QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Fixed)

    def current(self) -> int:
        return self.group.checkedId()

    def set_text(self, i: int, text: str):
        """Zmienia nazwę zakładki (np. z liczbą: „Slajdy 3”) – z zachowaniem dopasowania do szerokości."""
        b = self.buttons[i]
        b.setProperty("full", text)
        b.setText(text)
        self._fit(force=True)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(60, super().minimumSizeHint().height()) if self.tabs else super().minimumSizeHint()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.tabs:
            self._fit()

    def _fit(self, force: bool = False):
        """Zakładki: normalne odstępy → ciaśniej → krótsze nazwy. Tekst nigdy nie jest ucinany."""
        fm = QFontMetrics(self.buttons[0].font())
        full = [b.property("full") or b.text() for b in self.buttons]
        for b, f in zip(self.buttons, full):
            b.setProperty("full", f)

        def need(names, gap):
            return sum(fm.horizontalAdvance(n) + 12 + gap for n in names)
        w = self.width()
        if need(full, 24) <= w:
            mode, names = "normal", full
        elif need(full, 12) <= w:
            mode, names = "dense", full
        else:
            mode, names = "short", [self.short.get(n.split(" ")[0], n) + (" " + n.split(" ", 1)[1] if " " in n and
                                    n.split(" ")[0] in self.short else "") for n in full]
        if mode == self._dense and not force:
            return
        self._dense = mode
        for b, n in zip(self.buttons, names):
            b.setText(n)
            b.setToolTip(b.property("full") if n != b.property("full") else "")
            b.setProperty("dense", mode != "normal")
            b.style().unpolish(b)
            b.style().polish(b)

    def set_current(self, i: int, emit: bool = False):
        if 0 <= i < len(self.buttons):
            self.buttons[i].setChecked(True)
            if emit:
                self.changed.emit(i)


# ---------------------------------------------------------------------------
class Row(QWidget):
    """Wiersz w grupie: Tytuł / podtytuł ........ kontrolka. Gdy brakuje miejsca – kontrolka pod tytułem."""
    STACK_BELOW = 520

    def __init__(self, title: str, widget: QWidget | None = None, subtitle: str = "", stretch_widget: bool = False):
        super().__init__()
        self.setMinimumHeight(48)
        self.widget = widget
        self.stretch_widget = stretch_widget
        self.lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.lay.setContentsMargins(16, 9, 14, 9)
        self.lay.setSpacing(14)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label(title)
        texts.addWidget(self.title)
        self.subtitle = label(subtitle, "footnote", wrap=True)
        show_if(self.subtitle, subtitle)
        texts.addWidget(self.subtitle)
        self.lay.addLayout(texts, 0 if stretch_widget else 1)
        self.stacked = False
        if widget is not None:
            if stretch_widget:
                self.lay.addWidget(widget, 1)
            else:
                self.lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        want = self.width() < self.STACK_BELOW and self.widget is not None and \
            self.widget.sizeHint().width() > self.width() * 0.45
        if want != self.stacked:
            self.stacked = want
            self.lay.setDirection(QBoxLayout.Direction.TopToBottom if want else QBoxLayout.Direction.LeftToRight)
            self.lay.setSpacing(8 if want else 14)
            if self.widget is not None and not self.stretch_widget:
                self.lay.setAlignment(self.widget, Qt.AlignmentFlag.AlignLeft if want else
                                      Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class GroupSection(QWidget):
    """Sekcja: nagłówek, zaokrąglona karta z wierszami oddzielonymi linią, stopka."""

    def __init__(self, title: str = "", footer: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        if title:
            lay.addWidget(label(title.upper(), "sectionHeader"))
        self.frame = QFrame()
        self.frame.setObjectName("group")
        self.inner = QVBoxLayout(self.frame)
        self.inner.setContentsMargins(0, 2, 0, 2)
        self.inner.setSpacing(0)
        lay.addWidget(self.frame)
        self.footer = label(footer, "footnote", wrap=True)
        self.footer.setContentsMargins(6, 0, 6, 0)
        show_if(self.footer, footer)
        lay.addWidget(self.footer)
        self._count = 0

    def add(self, w: QWidget) -> QWidget:
        if self._count:
            h = hairline()
            wrap = QWidget()
            hl = QHBoxLayout(wrap)
            hl.setContentsMargins(16, 0, 0, 0)
            hl.addWidget(h)
            self.inner.addWidget(wrap)
        self.inner.addWidget(w)
        self._count += 1
        return w

    def add_row(self, title: str, widget: QWidget | None = None, subtitle: str = "", stretch: bool = False) -> Row:
        return self.add(Row(title, widget, subtitle, stretch))


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for x in widgets:
        if x == "stretch":
            lay.addStretch()
        else:
            lay.addWidget(x)
    return w


# ---------------------------------------------------------------------------
STATUS = {
    "gotowy": ("Gotowe", "green"),
    "nagrany": ("Bez notatek", "gray"),
    "nowy": ("Bez notatek", "gray"),
    "przetwarzanie": ("W toku", "orange"),
    "nagrywanie": ("Nagrywanie", "red"),
    "błąd": ("Błąd", "red"),
}


def lecture_status(lec) -> tuple[str, str]:
    st = lec.meta.status
    if st not in ("przetwarzanie", "nagrywanie", "błąd") and lec.notes_path.exists():
        st = "gotowy"
    return STATUS.get(st, ("", "gray"))


def pill_colors(kind: str):
    t = T()
    return {
        "green": (t.green_soft, t.green), "orange": (t.orange_soft, t.orange), "red": (t.red_soft, t.red),
        "blue": (t.accent_soft, t.accent), "gray": (t.hover, t.text2),
    }.get(kind, (t.hover, t.text2))


def draw_pill(p: QPainter, right: float, cy: float, text: str, kind: str, font: QFont) -> float:
    bg, fg = pill_colors(kind)
    f = QFont(font)
    f.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 16
    h = p.fontMetrics().height() + 5
    r = QRectF(right - w, cy - h / 2, w, h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qcolor(bg))
    p.drawRoundedRect(r, h / 2, h / 2)
    p.setPen(qcolor(fg))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
    return w


class StatusPill(QWidget):
    def __init__(self, text: str = "", kind: str = "gray"):
        super().__init__()
        self.text, self.kind = text, kind
        self.setFixedHeight(22)

    def set(self, text: str, kind: str):
        self.text, self.kind = text, kind
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        f.setWeight(QFont.Weight.DemiBold)
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(text) + 20)
        show_if(self, text)
        self.update()

    def paintEvent(self, _e):
        if not self.text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_pill(p, self.width() - 1, self.height() / 2, self.text, self.kind, self.font())
        p.end()


class SubjectChip(QWidget):
    """Kropka w kolorze przedmiotu + nazwa przedmiotu."""

    def __init__(self):
        super().__init__()
        self.text = ""
        self.setFixedHeight(22)

    def set(self, text: str):
        from .theme import subject_color
        self.text = text
        self.color = subject_color(text)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(text) + 32 if text else 0)
        show_if(self, text)
        self.update()

    def paintEvent(self, _e):
        if not self.text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(self.color)))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(qcolor(self.color))
        p.drawEllipse(QRectF(9, r.center().y() - 4, 8, 8))
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        f.setPointSizeF(f.pointSizeF() - 0.5)
        p.setFont(f)
        p.setPen(qcolor(T().text))
        p.drawText(r.adjusted(22, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)
        p.end()


# ---------------------------------------------------------------------------
class RecordButton(QAbstractButton):
    """Duży okrągły przycisk: czerwone koło → zaokrąglony kwadrat podczas nagrywania."""

    def __init__(self, size: int = 76):
        super().__init__()
        self._size = size
        self.recording = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Nagrywanie")

    def set_recording(self, on: bool):
        self.recording = on
        self.update()

    def paintEvent(self, _e):
        t = T()
        s = self._size
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = qcolor(t.red)
        halo = qcolor(t.red, 45 if self.underMouse() else 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, s, s))
        p.setPen(QPen(qcolor(t.surface), 3))
        p.setBrush(qcolor(t.surface))
        p.drawEllipse(QRectF(5, 5, s - 10, s - 10))
        if self.underMouse():
            red = red.lighter(110)
        if not self.isEnabled():
            red.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(red)
        if self.recording:
            q = s * 0.34
            p.drawRoundedRect(QRectF((s - q) / 2, (s - q) / 2, q, q), 6, 6)
        else:
            d = s - 20
            p.drawEllipse(QRectF(10, 10, d, d))
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class LevelMeter(QWidget):
    """Poziom dźwięku – słupki fali."""

    def __init__(self, bars: int = 28):
        super().__init__()
        self.bars = bars
        self.history = [0.0] * bars
        self.setFixedHeight(36)
        self.setMinimumWidth(bars * 5)

    def push(self, level: float):
        self.history = self.history[1:] + [max(0.0, min(1.0, level))]
        self.update()

    def reset(self):
        self.history = [0.0] * self.bars
        self.update()

    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width() / self.bars
        h = self.height()
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(self.history):
            bh = max(4.0, v * h)
            c = qcolor(t.red if v > 0.92 else t.accent)
            if v < 0.02:
                c = qcolor(t.selected)
            else:
                c.setAlpha(int(110 + 145 * (i + 1) / self.bars))
            p.setBrush(c)
            bw = max(2.0, w * 0.5)
            p.drawRoundedRect(QRectF(i * w + (w - bw) / 2, (h - bh) / 2, bw, bh), bw / 2, bw / 2)
        p.end()


class PulseDot(QWidget):
    def __init__(self, color_role: str = "red"):
        super().__init__()
        self.role = color_role
        self.setFixedSize(14, 14)
        self.on = True

    def blink(self):
        self.on = not self.on
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = qcolor(getattr(T(), self.role))
        p.setPen(Qt.PenStyle.NoPen)
        if self.on:
            p.setBrush(qcolor(getattr(T(), self.role), 60))
            p.drawEllipse(QRectF(0, 0, 14, 14))
        p.setBrush(c)
        p.drawEllipse(QRectF(3, 3, 8, 8))
        p.end()


class StatusDot(QWidget):
    def __init__(self, kind: str = "gray"):
        super().__init__()
        self.kind = kind
        self.setFixedSize(10, 10)

    def set(self, kind: str):
        self.kind = kind
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(pill_colors(self.kind)[1]))
        p.drawEllipse(QRectF(1, 1, 8, 8))
        p.end()


# ---------------------------------------------------------------------------
class IconBadge(QWidget):
    """Ikona w miękkim kółku (puste stany, nagłówki)."""

    def __init__(self, icon: str, size: int = 76, role: str = "accent"):
        super().__init__()
        self.icon, self.role, self.s = icon, role, size
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        t = T()
        color = getattr(t, self.role, t.accent)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(color)))
        p.drawEllipse(QRectF(0, 0, self.s, self.s))
        isz = int(self.s * 0.44)
        pm = icon_pixmap(self.icon, color, isz, self.devicePixelRatioF())
        p.drawPixmap(int((self.s - isz) / 2), int((self.s - isz) / 2), pm)
        p.end()


class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, text: str = "", button: QPushButton | None = None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.addStretch(2)
        self.icon = IconBadge(icon, 78)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(10)
        t = label(title, "title3")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setWordWrap(True)
        self.title = t
        lay.addWidget(t)
        self.text = label(text, "secondary", wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setMaximumWidth(440)
        self.text.setMinimumWidth(240)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.text, 4)
        row.addStretch(1)
        lay.addLayout(row)
        if button is not None:
            lay.addSpacing(10)
            lay.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)


# ---------------------------------------------------------------------------
class LectureDelegate(QStyledItemDelegate):
    """Wiersz listy wykładów: kwadracik przedmiotu, tytuł, data · czas · fiszki, status („Gotowe”, „AI 55%”
    z cienkim paskiem, „Bez notatek”). Wiersz z kluczem „header” to nagłówek grupy („Ten tydzień”)."""
    ROLE = Qt.ItemDataRole.UserRole + 1   # dict z danymi

    def sizeHint(self, option, index):
        d = index.data(self.ROLE) or {}
        return QSize(260, 34 if d.get("header") else 72)

    def paint(self, p: QPainter, option, index):
        from .theme import subject_color
        t = T()
        d = index.data(self.ROLE) or {}
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(option.font)
        if d.get("header"):
            f = QFont(font)
            f.setPointSizeF(font.pointSizeF() - 2.2)
            f.setWeight(QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
            p.setFont(f)
            p.setPen(qcolor(t.text3))
            p.drawText(QRectF(option.rect).adjusted(16, 10, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       d["header"].upper())
            p.restore()
            return
        r = QRectF(option.rect).adjusted(6, 3, -6, -3)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        if sel:
            paint_shadow(p, r, t.r("md"), 0.7)
            p.setPen(QPen(qcolor(t.separator), 1))
            p.setBrush(qcolor(t.surface))
            p.drawRoundedRect(r, t.r("md"), t.r("md"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.hover))
            p.drawRoundedRect(r, t.r("md"), t.r("md"))
        color = subject_color(d.get("subject") or "")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(color))
        p.drawRoundedRect(QRectF(r.left() + 12, r.top() + 18, 9, 9), 2, 2)
        pill_w = 0.0
        if d.get("pill"):
            text, kind = d["pill"]
            pill_w = draw_pill(p, r.right() - 12, r.top() + 22, text, kind, font) + 8
        f1 = QFont(font)
        f1.setWeight(QFont.Weight.DemiBold)
        f1.setPointSizeF(font.pointSizeF() + 0.3)
        p.setFont(f1)
        p.setPen(qcolor(t.text))
        x0 = r.left() + 30
        title_rect = QRectF(x0, r.top() + 11, r.right() - 12 - x0 - pill_w, 22)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("title", ""), Qt.TextElideMode.ElideRight, int(title_rect.width())))
        f2 = QFont(font)
        f2.setPointSizeF(font.pointSizeF() - 1.2)
        p.setFont(f2)
        p.setPen(qcolor(t.text2))
        sub_rect = QRectF(x0, r.top() + 35, r.right() - 12 - x0, 18)
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("sub", ""), Qt.TextElideMode.ElideRight, int(sub_rect.width())))
        prog = d.get("progress")
        if prog is not None:
            bar = QRectF(x0, r.bottom() - 9, r.right() - 12 - x0, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.separator))
            p.drawRoundedRect(bar, 1.5, 1.5)
            if prog >= 0:
                p.setBrush(qcolor(t.accent))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(3.0, bar.width() * min(1.0, prog)), 3), 1.5, 1.5)
        p.restore()


def rounded_pixmap(pix, radius: float | None = None):
    radius = T().r("md") if radius is None else radius
    from PySide6.QtGui import QPixmap
    out = QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    dpr = pix.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, pix.width() / dpr, pix.height() / dpr), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


class ModeCard(QAbstractButton):
    """Karta wyboru rodzaju notatki: kolorowy kafelek z ikoną, tytuł i opis.
    Układ poziomy (kafelek z lewej) albo pionowy (kafelek u góry) – zależnie od szerokości."""

    def __init__(self, icon: str, title: str, desc: str, color_index: int = 0):
        super().__init__()
        self.icon_name, self.title, self.desc = icon, title, desc
        self.color_index = color_index
        self.vertical = False
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(96)
        self.setAccessibleName(title)
        self.soon = ""          # np. „Wkrótce na Macu” – karta wyszarzona, bez wyboru

    def set_soon(self, text: str, tip: str = ""):
        """Rodzaj niedostępny w tym systemie: wyszarzona karta z dopiskiem w rogu."""
        self.soon = text
        self.setEnabled(not text)
        self.setCursor(Qt.CursorShape.ArrowCursor if text else Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)
        self.update()

    def set_vertical(self, v: bool):
        self.vertical = v
        self._fit_height()
        self.update()

    peers: list = []

    def _needed(self) -> int:
        if self.vertical:
            return 150
        f2 = QFont(self.font())            # opis ma się zmieścić w całości
        f2.setPointSizeF(self.font().pointSizeF() - 0.8)
        tw = max(80, self.width() - 3 - 3 - 16 - 44 - 14 - 14)
        br = QFontMetrics(f2).boundingRect(0, 0, tw, 400, int(Qt.TextFlag.TextWordWrap), self.desc)
        return max(96, 16 + 22 + 2 + br.height() + 22 + (self._soon_size()[1] + 6 if self.soon else 0))

    def _soon_font(self) -> QFont:
        f3 = QFont(self.font())
        f3.setPointSizeF(self.font().pointSizeF() - 1.5)
        f3.setWeight(QFont.Weight.DemiBold)
        return f3

    def _soon_size(self) -> tuple[int, int]:
        fm = QFontMetrics(self._soon_font())
        return fm.horizontalAdvance(self.soon) + 16, fm.height() + 6

    def _fit_height(self):
        h = max([c._needed() for c in self.peers] or [self._needed()]) if self in self.peers else self._needed()
        for c in (self.peers if self in self.peers else [self]):
            if c.height() != h:
                c.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    def sizeHint(self):
        return QSize(260, self.height())

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        t = T()
        color = palette_color(self.color_index)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 2, -3, -5)
        on = self.isChecked()
        hover = self.underMouse() and not self.soon
        if self.soon:
            p.setOpacity(0.55)
        if on or hover:
            paint_shadow(p, r, 16, 1.0 if on else 0.6)
        p.setPen(QPen(qcolor(t.accent if on else t.separator), 2 if on else 1))
        p.setBrush(qcolor(t.surface))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), T().r("lg"), T().r("lg"))
        tile = 44
        tx, ty = (r.left() + 16, r.top() + 16) if self.vertical else (r.left() + 16, r.top() + (r.height() - tile) / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(color)))
        p.drawRoundedRect(QRectF(tx, ty, tile, tile), T().r("md"), T().r("md"))
        pm = icon_pixmap(self.icon_name, color, 24, self.devicePixelRatioF())
        p.drawPixmap(int(tx + (tile - 24) / 2), int(ty + (tile - 24) / 2), pm)
        if on:       # znaczek w rogu
            c = QRectF(r.right() - 30, r.top() + 12, 18, 18)
            p.setBrush(qcolor(t.accent))
            p.drawEllipse(c)
            cp = icon_pixmap("check", t.on_accent, 12, self.devicePixelRatioF())
            p.drawPixmap(int(c.left() + 3), int(c.top() + 3), cp)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        f.setPointSizeF(f.pointSizeF() + 0.5)
        f2 = QFont(self.font())
        f2.setPointSizeF(self.font().pointSizeF() - 0.8)
        if self.vertical:
            text_r = QRectF(r.left() + 16, ty + tile + 10, r.width() - 32, 22)
            desc_r = QRectF(r.left() + 16, text_r.bottom() + 2, r.width() - 32, r.bottom() - text_r.bottom() - 8)
        else:
            x = tx + tile + 14
            text_r = QRectF(x, r.top() + 16, r.right() - x - 36, 22)
            dy = self._soon_size()[1] + 6 if self.soon else 0      # dopisek „Wkrótce…” pod tytułem
            desc_r = QRectF(x, text_r.bottom() + 2 + dy, r.right() - x - 14, r.bottom() - text_r.bottom() - 10 - dy)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setFont(f2)
        p.setPen(qcolor(t.text2))
        p.drawText(desc_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.desc)
        if self.soon:            # dopisek (w pełnym kolorze): pionowo w rogu, poziomo pod tytułem
            p.setOpacity(1.0)
            p.setFont(self._soon_font())
            pw, ph = self._soon_size()
            pill = QRectF(r.right() - pw - 10, r.top() + 10, pw, ph) if self.vertical else                 QRectF(text_r.left(), text_r.bottom() + 4, pw, ph)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft))
            p.drawRoundedRect(pill, ph / 2, ph / 2)
            p.setPen(qcolor(t.accent_text))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.soon)
        p.end()


class Heading(QWidget):
    """Nagłówek ekranu: nadtytuł (np. data), tytuł szeryfowy, podtytuł."""

    def __init__(self, title: str, subtitle: str = "", overline: str = ""):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        self.overline = label(overline.upper(), "overline")
        show_if(self.overline, overline)
        self.title = label(title, "largeTitle", wrap=True)
        self.subtitle = label(subtitle, "secondary", wrap=True)
        show_if(self.subtitle, subtitle)
        v.addWidget(self.overline)
        v.addWidget(self.title)
        v.addWidget(self.subtitle)


def title_font_for(size: float) -> QFont:
    return display_font(size)


# ---------------------------------------------------------------------------
# Listy rozwijane z kolorami (zakres: wszystkie / przedmiot / wykład)
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QComboBox, QStyleOptionComboBox, QStylePainter  # noqa: E402

C_COLOR = Qt.ItemDataRole.UserRole + 20
C_TAG = Qt.ItemDataRole.UserRole + 21


class _ChoiceDelegate(QStyledItemDelegate):
    """Pozycja listy: kolorowa kropka, tekst, mała etykieta rodzaju z prawej; wyższe wiersze."""

    def sizeHint(self, option, index):
        return QSize(max(260, option.rect.width()), 36)

    def paint(self, p: QPainter, option, index):
        t = T()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        sel = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        if sel:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft))
            p.drawRoundedRect(r, T().r("sm"), T().r("sm"))
        color = index.data(C_COLOR)
        x = r.left() + 12
        if color:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(color))
            p.drawEllipse(QRectF(x, r.center().y() - 5, 10, 10))
            x += 20
        tag = index.data(C_TAG) or ""
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() - 1.5)
        f.setWeight(QFont.Weight.DemiBold)
        tw = 0
        if tag:
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(tag) + 16
            tr = QRectF(r.right() - tw - 8, r.center().y() - 10, tw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.hover))
            p.drawRoundedRect(tr, T().r("md"), T().r("md"))
            p.setPen(qcolor(t.text2))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, tag)
        p.setFont(option.font)
        p.setPen(qcolor(t.text))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rr = QRectF(x, r.top(), r.right() - x - tw - 16, r.height())
        p.drawText(rr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rr.width())))
        p.restore()


def style_combo(c: QComboBox, min_popup: int = 340):
    """Każda lista rozwijana: wyższe, czytelne pozycje (także te bez kolorów)."""
    c.setItemDelegate(_ChoiceDelegate(c))
    c.setMaxVisibleItems(14)
    c.view().setMinimumWidth(min_popup)
    c.view().setMouseTracking(True)
    return c


class ChoiceCombo(QComboBox):
    """Lista rozwijana z kropką w kolorze przedmiotu i etykietą („Przedmiot”, „Wykład”)."""

    def __init__(self, min_popup: int = 380):
        super().__init__()
        style_combo(self, min_popup)
        self.setMinimumHeight(36)

    def add(self, text: str, data=None, color: str | None = None, tag: str = ""):
        self.addItem(text, data)
        i = self.count() - 1
        self.setItemData(i, color, C_COLOR)
        self.setItemData(i, tag, C_TAG)

    def fill_scope(self, lectures, all_label: str = "Wszystkie wykłady", subjects: bool = True,
                   subject_prefix: str = "", keep=None):
        """Zakres: wszystkie / każdy przedmiot / każdy wykład (z kolorami przedmiotów)."""
        from .theme import subject_color
        self.blockSignals(True)
        self.clear()
        if all_label:
            self.add(all_label, ("all", ""), None, "")
        if subjects:
            for s in sorted({l.meta.subject for l in lectures if l.meta.subject}):
                self.add(subject_prefix + s, ("subject", s), subject_color(s), "Przedmiot")
        for l in lectures:
            self.add(l.meta.title, ("lecture", str(l.folder)), subject_color(l.meta.subject), "Wykład")
        i = self.findData(keep) if keep else -1
        self.setCurrentIndex(max(0, i))
        self.blockSignals(False)

    def paintEvent(self, _e):
        """Zamknięta lista: kropka koloru + tekst + etykieta (jak w rozwiniętej)."""
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        i = self.currentIndex()
        if i < 0:
            return
        t = T()
        color = self.itemData(i, C_COLOR)
        tag = self.itemData(i, C_TAG) or ""
        r = QRectF(self.rect()).adjusted(12, 0, -32, 0)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = r.left()
        if color:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(color))
            p.drawEllipse(QRectF(x, r.center().y() - 5, 10, 10))
            x += 18
        tw = 0
        if tag:
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() - 1.5)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(tag) + 16
            tr = QRectF(r.right() - tw, r.center().y() - 10, tw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.hover))
            p.drawRoundedRect(tr, T().r("md"), T().r("md"))
            p.setPen(qcolor(t.text2))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, tag)
        p.setFont(self.font())
        p.setPen(qcolor(t.text if self.isEnabled() else t.text3))
        rr = QRectF(x, r.top(), r.right() - x - tw - 8, r.height())
        p.drawText(rr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rr.width())))
