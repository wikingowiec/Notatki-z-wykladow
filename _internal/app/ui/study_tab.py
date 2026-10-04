"""Ekran „Fiszki”: seria dni i cel dzienny, kategorie z postępem (opanowane / w nauce / nowe), nauka z kartą,
interwałami na przyciskach, cofaniem oceny i edycją karty; podgląd kategorii (tematy, definicje, fiszki)."""
from __future__ import annotations

import copy
import html
import random

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..storage import Lecture, list_lectures
from .controls import AdaptiveBox, EmptyState, SegmentedControl, label, paint_shadow, set_icon, show_if
from .theme import T, mix, palette_color, qcolor

DECK = Qt.ItemDataRole.UserRole + 1


# ---------------------------------------------------------------------------
# Liczby kart w kategorii
# ---------------------------------------------------------------------------
def card_state(c: dict) -> str:
    if c.get("known"):
        return "known"
    if int(c.get("reps", 0) or 0) or int(c.get("lapses", 0) or 0):
        return "learning"
    return "new"


def deck_counts(deck) -> dict:
    out = {"known": 0, "learning": 0, "new": 0}
    for cards, i in deck.entries:
        out[card_state(cards[i])] += 1
    return out


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return f"1 {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


# ---------------------------------------------------------------------------
# Kafelki kategorii (lewa kolumna)
# ---------------------------------------------------------------------------
class DeckDelegate(QStyledItemDelegate):
    """Kolor kategorii, nazwa, wykład, „N dziś”, pasek opanowane / w nauce / nowe i podpis z liczbami."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.active_key = None

    def sizeHint(self, option, index):
        return QSize(300, 112)

    def paint(self, p: QPainter, option, index):
        t = T()
        d = index.data(DECK)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 4, -4, -6)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        active = d.key == self.active_key
        color = palette_color(d.color)
        paint_shadow(p, r, t.r("lg"), 0.9 if hover or active else 0.45)
        p.setPen(QPen(qcolor(color if active else (t.line2 if hover else t.separator)), 2 if active else 1))
        p.setBrush(qcolor(t.surface))
        p.drawRoundedRect(r, t.r("lg"), t.r("lg"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(color))
        p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 17, 10, 10), 2.5, 2.5)
        due = d.due()
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() - 1.0)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        due_txt = f"{due} dziś" if due else "na dziś gotowe"
        dw = p.fontMetrics().horizontalAdvance(due_txt) + 16
        pill = QRectF(r.right() - dw - 12, r.top() + 11, dw, 22)
        p.setBrush(qcolor(t.accent_soft if due else t.hover))
        p.drawRoundedRect(pill, 11, 11)
        p.setPen(qcolor(t.accent_text if due else t.text3))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, due_txt)
        from .theme import display_font
        fd = display_font(12.5)
        p.setFont(fd)
        p.setPen(qcolor(t.text))
        tw = int(pill.left() - r.left() - 40)
        p.drawText(QRectF(r.left() + 32, r.top() + 10, tw, 24), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.name, Qt.TextElideMode.ElideRight, tw))
        f2 = QFont(option.font)
        f2.setPointSizeF(f2.pointSizeF() - 1.4)
        p.setFont(f2)
        p.setPen(qcolor(t.text3))
        p.drawText(QRectF(r.left() + 32, r.top() + 33, r.width() - 46, 16), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.lecture.meta.title, Qt.TextElideMode.ElideRight, int(r.width() - 46)))
        # pasek segmentowy: opanowane | w nauce | nowe
        c = deck_counts(d)
        tot = max(1, d.total)
        bar = QRectF(r.left() + 14, r.top() + 60, r.width() - 28, 7)
        x = bar.left()
        for key, col in (("known", color), ("learning", mix(t.surface, color, 0.5)), ("new", t.separator)):
            w = bar.width() * c[key] / tot
            if w > 0.5:
                p.setBrush(qcolor(col))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(x, bar.top(), max(3.0, w - 2), bar.height()), 3, 3)
                x += w
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(r.left() + 14, r.top() + 72, r.width() - 28, 18), Qt.AlignmentFlag.AlignVCenter,
                   f"{c['known']} opanowane · {c['learning']} w nauce · {c['new']} nowe")
        p.restore()


# ---------------------------------------------------------------------------
# Seria dni i cel dzienny (nagłówek)
# ---------------------------------------------------------------------------
class StreakCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("pane")
        self.data = {"streak": 0, "best": 0, "week": []}
        self.setFixedSize(250, 78)

    def set_data(self, d: dict):
        self.data = d
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        from .theme import display_font, icon_pixmap
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n, best = self.data.get("streak", 0), self.data.get("best", 0)
        p.drawPixmap(14, 14, icon_pixmap("flame", t.streak if n else t.text3, 22, self.devicePixelRatioF() or 1))
        p.setFont(display_font(12.5))
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(44, 10, 200, 24), Qt.AlignmentFlag.AlignVCenter,
                   plural(n, "dzień", "dni", "dni") + " z rzędu" if n else "Zacznij serię")
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() - 1.6)
        p.setFont(f)
        p.setPen(qcolor(t.text3))
        p.drawText(QRectF(44, 32, 200, 14), Qt.AlignmentFlag.AlignVCenter, f"rekord: {plural(best, 'dzień', 'dni', 'dni')}")
        x = 14
        for name, done, today in self.data.get("week", []):
            r = QRectF(x, 52, 26, 16)
            p.setPen(QPen(qcolor(t.streak), 1.6) if today else Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.streak if done else t.separator))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
            p.setPen(qcolor(t.on_accent if done else t.text3))
            f2 = QFont(f)
            f2.setPointSizeF(f.pointSizeF() - 1)
            f2.setWeight(QFont.Weight.DemiBold)
            p.setFont(f2)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, name)
            p.setFont(f)
            x += 32
        p.end()


class GoalRing(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("pane")
        self.done, self.goal = 0, 20
        self.setFixedSize(176, 78)

    def set_data(self, done: int, goal: int):
        self.done, self.goal = done, max(1, goal)
        self.setToolTip(f"Cel dzienny: {goal} ocenionych fiszek (zmiana w Ustawieniach)")
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        from .theme import display_font
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(14, 13, 52, 52)
        p.setPen(QPen(qcolor(t.separator), 6))
        p.drawEllipse(ring)
        frac = min(1.0, self.done / self.goal)
        if frac > 0:
            pen = QPen(qcolor(t.accent), 6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, -int(360 * 16 * frac))
        p.setFont(display_font(12.5))
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(76, 12, 100, 28), Qt.AlignmentFlag.AlignVCenter, f"{self.done} / {self.goal}")
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() - 1.6)
        p.setFont(f)
        p.setPen(qcolor(t.text3))
        p.drawText(QRectF(76, 38, 100, 16), Qt.AlignmentFlag.AlignVCenter,
                   "cel osiągnięty ✓" if self.done >= self.goal else "cel dzienny")
        p.end()


class SessionBar(QWidget):
    """Pasek sesji: każda karta to odcinek (zrobiona / do powtórki / bieżąca / czeka)."""

    def __init__(self):
        super().__init__()
        self.states: list[str] = []
        self.setFixedHeight(8)

    def set_states(self, states: list[str]):
        self.states = states
        self.update()

    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.states)
        if not n:
            return
        w = self.width()
        cols = {"done": t.accent, "again": t.markLine, "current": t.line2, "todo": t.separator}
        if n > 48:                       # dużo kart – jeden ciągły pasek
            done = sum(1 for s in self.states if s in ("done", "again"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.separator))
            p.drawRoundedRect(QRectF(0, 0, w, 8), 4, 4)
            p.setBrush(qcolor(t.accent))
            p.drawRoundedRect(QRectF(0, 0, max(8.0, w * done / n), 8), 4, 4)
            return
        gap = 3
        seg = (w - gap * (n - 1)) / n
        for i, s in enumerate(self.states):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(cols.get(s, t.separator)))
            p.drawRoundedRect(QRectF(i * (seg + gap), 0, max(2.0, seg), 8), 3, 3)
        p.end()


class CardEditor(QDialog):
    def __init__(self, card: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edytuj kartę")
        self.resize(560, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(8)
        v.addWidget(label("PYTANIE", "sectionHeader"))
        self.q = QPlainTextEdit(card.get("q", ""))
        self.q.setMaximumHeight(110)
        v.addWidget(self.q)
        v.addWidget(label("ODPOWIEDŹ", "sectionHeader"))
        self.a = QPlainTextEdit(card.get("a", ""))
        v.addWidget(self.a, 1)
        v.addWidget(label("Wzory piszesz jak w notatce, np. $x^2$. Zakreślenie: ==tekst==.", "caption"))
        row = QHBoxLayout()
        row.addStretch()
        b_c = QPushButton("Anuluj")
        b_c.clicked.connect(self.reject)
        b_s = QPushButton("Zapisz")
        b_s.setObjectName("primary")
        b_s.clicked.connect(self.accept)
        row.addWidget(b_c)
        row.addWidget(b_s)
        v.addLayout(row)


# ---------------------------------------------------------------------------
class StudyTab(QWidget):
    reviewed = Signal()
    open_note = Signal(str, str)          # folder wykładu, kotwica tematu
    play_at = Signal(object, float)       # wykład, sekunda nagrania

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.items: list[tuple[Lecture, list, int]] = []   # (wykład, lista fiszek wykładu, indeks)
        self.queue: list[int] = []
        self.cur: int | None = None
        self.order: list[int] = []        # karty sesji w kolejności (do paska)
        self.state: dict[int, str] = {}
        self.history: list = []           # do cofania ocen (Ctrl+Z)
        self.deck = None
        self.reviewed_today = 0

        # ---------------- nagłówek: tytuł + seria + cel ----------------
        self.title = label("Fiszki", "largeTitle")
        self.stats = label("", "secondary")
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label("NAUKA", "overline"))
        tl.addWidget(self.title)
        tl.addWidget(self.stats)
        tw = QWidget()
        tw.setLayout(tl)
        self.streak = StreakCard()
        self.goal = GoalRing()
        cards_row = QWidget()
        cr = QHBoxLayout(cards_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(12)
        cr.addWidget(self.streak)
        cr.addWidget(self.goal)
        head = AdaptiveBox(threshold=860, spacing=12, vspacing=12)
        head.add(tw, 1)
        head.add(cards_row, 0, Qt.AlignmentFlag.AlignBottom, Qt.AlignmentFlag.AlignLeft)

        # ---------------- lewa kolumna: kategorie ----------------
        from .controls import ChoiceCombo
        self.scope = ChoiceCombo()
        self.scope.setMinimumWidth(200)
        self.scope.currentIndexChanged.connect(lambda _i: (setattr(self, "deck", None), self.load()))
        self.grid = QListWidget()
        self.grid.setObjectName("lectureList")
        self.deck_delegate = DeckDelegate(self.grid)
        self.grid.setItemDelegate(self.deck_delegate)
        self.grid.setMouseTracking(True)
        self.grid.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.grid.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.grid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grid.itemClicked.connect(lambda it: self.select_deck(it.data(DECK)))
        self.btn_all = QPushButton("Ucz się wszystkich")
        self.btn_all.setObjectName("primary")
        set_icon(self.btn_all, "play", "on_accent", 14)
        self.btn_all.clicked.connect(self._learn_all)
        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        ll.addWidget(label("KATEGORIE", "sectionHeader"))
        ll.addWidget(self.scope)
        ll.addWidget(self.grid, 1)
        ll.addWidget(self.btn_all)
        self.left.setFixedWidth(350)

        # ---------------- prawa część: nauka / przeglądanie ----------------
        self.mode_seg = SegmentedControl(["Ucz się", "Przeglądaj"], style="tabs")
        self.mode_seg.changed.connect(self._mode_changed)
        from .controls import ChoiceCombo as _CC
        self.deck_combo = _CC()
        self.deck_combo.setMinimumWidth(220)
        self.deck_combo.activated.connect(self._deck_combo_chosen)
        self.deck_combo.hide()
        self.session_title = label("", "headline")
        self.btn_end = QPushButton("Zakończ sesję")
        self.btn_end.setObjectName("plain")
        self.btn_end.clicked.connect(self.end_session)
        self.session_bar = SessionBar()
        sh = QHBoxLayout()
        sh.setSpacing(10)
        sh.addWidget(self.session_title, 1)
        sh.addWidget(self.btn_end)

        # karta
        self.card = QFrame()
        self.card.setObjectName("flashcard")
        self.card.setMaximumWidth(760)
        self.card.setMinimumHeight(320)
        self._lift()
        from .theme import theme
        theme().changed.connect(self._lift)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(44, 30, 44, 22)
        cl.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("PYTANIE", "sectionHeader"))
        top.addStretch(1)
        self.chip = QLabel_()
        top.addWidget(self.chip)
        cl.addLayout(top)
        self.q = label("", "cardQ", wrap=True)
        self.q.setTextFormat(Qt.TextFormat.RichText)
        self.q.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.q)
        cl.addSpacing(6)
        self.dash = QFrame()
        self.dash.setObjectName("dash")
        self.dash.setFixedHeight(2)
        cl.addWidget(self.dash)
        cl.addSpacing(4)
        self.a_head = label("ODPOWIEDŹ", "sectionHeader")
        cl.addWidget(self.a_head)
        self.a = label("", "cardA", wrap=True)
        self.a.setTextFormat(Qt.TextFormat.RichText)
        self.a.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.a)
        self.a_hint = label("Spacja – pokaż odpowiedź", "caption")
        cl.addWidget(self.a_hint)
        cl.addStretch(1)
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.src = label("", "caption")
        self.src.setTextFormat(Qt.TextFormat.RichText)
        self.src.setOpenExternalLinks(False)
        self.src.linkActivated.connect(self._src_link)
        self.btn_edit = QPushButton("E — edytuj kartę")
        self.btn_edit.setObjectName("plain")
        self.btn_edit.clicked.connect(self.edit_card)
        foot.addWidget(self.src, 1)
        foot.addWidget(self.btn_edit)
        cl.addLayout(foot)
        self.card_wrap = QWidget()
        cw = QHBoxLayout(self.card_wrap)
        cw.setContentsMargins(14, 8, 14, 14)
        cw.addStretch()
        cw.addWidget(self.card, 20)
        cw.addStretch()

        self.btn_show = QPushButton("Pokaż odpowiedź · Spacja")
        self.btn_show.setObjectName("big")
        self.btn_show.setMinimumWidth(280)
        self.btn_show.clicked.connect(self.show_answer)
        self.btn_no = QPushButton("")
        self.btn_no.setObjectName("rateNo")
        self.btn_no.clicked.connect(lambda: self.answer(False))
        self.btn_yes = QPushButton("")
        self.btn_yes.setObjectName("rateYes")
        self.btn_yes.clicked.connect(lambda: self.answer(True))
        for b in (self.btn_no, self.btn_yes):
            b.setMinimumHeight(68)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.answer_row = QWidget()
        ar = QHBoxLayout(self.answer_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(12)
        ar.addWidget(self.btn_no, 1)
        ar.addWidget(self.btn_yes, 1)
        self.answer_wrap = QWidget()
        aw = QHBoxLayout(self.answer_wrap)
        aw.setContentsMargins(14, 0, 14, 0)
        aw.addStretch()
        aw.addWidget(self.answer_row, 20)
        aw.addStretch()
        self.answer_row.setMaximumWidth(760)
        self.keys = label("Spacja – odpowiedź · 1 / 2 – ocena · Ctrl+Z – cofnij · E – edytuj", "caption")
        self.keys.setAlignment(Qt.AlignmentFlag.AlignCenter)

        study = QWidget()
        sl = QVBoxLayout(study)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        sl.addLayout(sh)
        sl.addWidget(self.session_bar)
        sl.addWidget(self.card_wrap)
        sl.addWidget(self.btn_show, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addWidget(self.answer_wrap)
        sl.addWidget(self.keys)
        sl.addStretch(1)

        self.btn_again = QPushButton("Powtórz wszystkie")
        self.btn_again.setObjectName("primary")
        self.btn_again.clicked.connect(self._repeat_all)
        self.empty = EmptyState("cards", "Brak fiszek",
                                "Fiszki powstają automatycznie razem z notatkami z wykładu – pogrupowane w kategorie.")
        self.finished = EmptyState("check", "Na dziś wszystko",
                                   "Kolejne fiszki wrócą w wyznaczonym dniu (1, 3, 7… dni). "
                                   "Możesz też powtórzyć wszystkie od nowa.", self.btn_again)
        self.stack = QStackedWidget()
        self.stack.addWidget(study)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.finished)

        from .reader import Reader
        self.deck_view = Reader(max_width=720, pad=26)
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.stack)
        self.right_stack.addWidget(self.deck_view)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        mrow = QHBoxLayout()
        mrow.setSpacing(10)
        mrow.addWidget(self.mode_seg, 1)
        mrow.addWidget(self.deck_combo)
        rl.addLayout(mrow)
        rl.addWidget(self.right_stack, 1)

        self.body = AdaptiveBox(threshold=560, spacing=28, vspacing=16)
        self.body.add(self.left, 0)
        self.body.add(right, 1)

        v = QVBoxLayout(self)
        v.setContentsMargins(36, 28, 36, 20)
        v.setSpacing(18)
        v.addWidget(head)
        v.addWidget(self.body, 1)
        self.outer = v

        keys = ((Qt.Key.Key_Space, self._space), (Qt.Key.Key_1, lambda: self.answer(False)),
                (Qt.Key.Key_2, lambda: self.answer(True)), (Qt.Key.Key_E, self.edit_card),
                (QKeySequence.StandardKey.Undo, self.undo))
        for key, fn in keys:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _lift(self):
        """Cień karty (tokens.SHADOW["lift"]); w motywie bez cieni – tylko ramka."""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from . import tokens as TK
        t = T()
        if not t.shadows:
            self.card.setGraphicsEffect(None)
            return
        blur, dx, dy, rgba = TK.SHADOW["lift"] if not t.dark else TK.SHADOW["darkCard"]
        eff = QGraphicsDropShadowEffect(self.card)
        eff.setBlurRadius(blur)
        eff.setOffset(dx, dy)
        eff.setColor(QColor(*rgba))
        self.card.setGraphicsEffect(eff)

    # ------------------------------------------------------------------ układ
    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < 980
        self.outer.setContentsMargins(*((14, 16, 14, 12) if narrow else (36, 28, 36, 20)))
        self.card.layout().setContentsMargins(*((22, 20, 22, 16) if narrow else (44, 30, 44, 22)))
        self.left.setVisible(not narrow)          # wąsko: kategorie z listy rozwijanej obok zakładek
        self.deck_combo.setVisible(narrow)
        self.card.setMinimumHeight(240 if narrow else 320)

    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()
        self._update_header()

    # ------------------------------------------------------------------ zgodność ze starszym API
    def _set_mode(self, i: int):
        """0 = przeglądaj kategorię, 1 = ucz się."""
        self._mode_changed(1 if i == 0 else 0)

    def _mode_changed(self, i: int):
        self.mode_seg.set_current(i)
        self.right_stack.setCurrentIndex(i)
        if i == 1:
            self._render_deck()
        else:
            self.setFocus()

    def open_deck(self, deck):
        self.deck = deck
        self.deck_delegate.active_key = deck.key
        self.grid.viewport().update()
        self._mode_changed(1)

    def study_deck(self, deck):
        self.select_deck(deck)

    # ------------------------------------------------------------------ zakres i kategorie
    def _lectures_in_scope(self):
        kind, val = self.scope.currentData() or ("all", "")
        out = []
        for l in list_lectures(self.settings.library_path()):
            if kind == "subject" and l.meta.subject != val:
                continue
            if kind == "lecture" and str(l.folder) != val:
                continue
            out.append(l)
        return out

    def refresh_scopes(self, keep: bool = True):
        cur = self.scope.currentData() if keep else None
        lectures = [l for l in list_lectures(self.settings.library_path()) if l.flashcards_path.exists()]
        self.scope.blockSignals(True)
        self.scope.fill_scope(lectures, "Wszystkie fiszki", keep=cur)
        self.scope.blockSignals(False)

    def set_scope_lecture(self, lec: Lecture):
        self.refresh_scopes()
        i = self.scope.findData(("lecture", str(lec.folder)))
        self.scope.blockSignals(True)
        if i >= 0:
            self.scope.setCurrentIndex(i)
        self.scope.blockSignals(False)
        self.deck = None
        self._mode_changed(0)
        self.load()

    def refresh_decks(self):
        from ..flashcards import decks_for
        self.grid.clear()
        self.decks = decks_for(self._lectures_in_scope())
        for d in self.decks:
            it = QListWidgetItem()
            it.setData(DECK, d)
            it.setToolTip(f"{d.name} – {d.lecture.meta.title}")
            self.grid.addItem(it)
        due = sum(d.due() for d in self.decks)
        self.btn_all.setText(f"Ucz się wszystkich · {due}" if due else "Ucz się wszystkich")
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.add(f"Wszystkie kategorie · {due}", None, None, "")
        for d in self.decks:
            self.deck_combo.add(f"{d.name} · {d.due()}", d.key, palette_color(d.color), d.lecture.meta.title[:18])
        k = self.deck.key if self.deck else None
        self.deck_combo.setCurrentIndex(max(0, self.deck_combo.findData(k)) if k else 0)
        self.deck_combo.blockSignals(False)
        self.deck_delegate.active_key = self.deck.key if self.deck else None

    def select_deck(self, deck):
        """Klik w kategorię: aktywna (ramka w jej kolorze) i nauka tylko z niej."""
        if self.deck is not None and deck is not None and self.deck.key == deck.key and \
                self.right_stack.currentIndex() == 0:
            self.deck = None              # drugi klik – z powrotem wszystkie
        else:
            self.deck = deck
        self.deck_delegate.active_key = self.deck.key if self.deck else None
        self.grid.viewport().update()
        if self.right_stack.currentIndex() == 1:
            self._render_deck()
        else:
            self._mode_changed(0)
            self.load(keep_decks=True)

    def _deck_combo_chosen(self, i: int):
        key = self.deck_combo.itemData(i)
        d = next((x for x in getattr(self, "decks", []) if x.key == key), None)
        if d is None:
            self._learn_all()
        else:
            self.deck = None
            self.select_deck(d)

    def _learn_all(self):
        self.deck = None
        self.deck_delegate.active_key = None
        self.grid.viewport().update()
        self._mode_changed(0)
        self.load(keep_decks=True)

    def _render_deck(self):
        from ..flashcards import deck_markdown
        from .library_tab import build_notes
        from .widgets import run_async
        decks = [self.deck] if self.deck else getattr(self, "decks", [])
        if not decks:
            self.deck_view.setHtml(f"<p style='color:{T().text3}'>Brak fiszek w tym zakresie.</p>")
            return
        md = "\n".join(f"# {d.name}\n\n*{d.lecture.meta.title}*\n\n{deck_markdown(d)}\n" for d in decks)
        folder, dpr = decks[0].lecture.folder, self.devicePixelRatioF() or 1.0
        view = self.deck_view

        def done(res):
            html_doc, images, _p = res
            view.images = images
            view.setHtml(html_doc)
        run_async(lambda: build_notes(folder, md, dpr, audio=False, toc=False), done)

    # ------------------------------------------------------------------ sesja
    def load(self, keep_decks: bool = False):
        if not keep_decks:
            self.refresh_decks()
        self.items = []
        if self.deck is not None:
            from ..flashcards import decks_for
            d = next((x for x in decks_for([Lecture(self.deck.lecture.folder)]) if x.name == self.deck.name), None)
            for cards, i in (d.entries if d else []):
                self.items.append((d.lecture, cards, i))
        else:
            for l in self._lectures_in_scope():
                cards = l.load_flashcards()
                for i in range(len(cards)):
                    self.items.append((l, cards, i))
        self._start(only_due=True)

    def _start(self, only_due: bool):
        from ..srs import is_due, today
        day = today()
        idx = [k for k, (_l, cards, i) in enumerate(self.items) if not only_due or is_due(cards[i], day)]
        random.shuffle(idx)
        self.queue = list(idx)
        self.order = list(idx)
        self.state = {k: "todo" for k in idx}
        self.history = []
        self.next_card()

    def _repeat_all(self):
        self._start(only_due=False)

    def end_session(self):
        self.queue = []
        self.cur = None
        self.next_card()

    def _update_header(self):
        from .. import study_stats
        from ..srs import is_due, today
        try:
            st = study_stats.summary(self.settings.library_path())
        except Exception:  # noqa: BLE001
            st = {"streak": 0, "best": 0, "today": 0, "week": []}
        self.streak.set_data(st)
        self.goal.set_data(st.get("today", 0), int(getattr(self.settings, "daily_goal", 20) or 20))
        day = today()
        all_items = [(c, i) for l in self._lectures_in_scope() for c in [l.load_flashcards()] for i in range(len(c))]
        total = len(all_items)
        known = sum(1 for c, i in all_items if c[i].get("known"))
        due = sum(1 for c, i in all_items if is_due(c[i], day))
        self.stats.setText(f"{due} do powtórki dziś · {plural(known, 'opanowana', 'opanowane', 'opanowanych')} · "
                           f"{total} wszystkie" if total else "Brak fiszek")

    def _bar(self):
        states = [("current" if k == self.cur else self.state.get(k, "todo")) for k in self.order]
        self.session_bar.set_states(states)
        done = sum(1 for k in self.order if self.state.get(k) == "done")
        name = self.deck.name if self.deck else "Wszystkie kategorie"
        n = len(self.order)
        self.session_title.setText(f"{name} · karta {min(n, done + 1)} z {n}" if n else name)

    def next_card(self):
        self._update_header()
        if not self.items:
            self.cur = None
            self.stack.setCurrentIndex(1)
            return
        if not self.queue:
            self.cur = None
            done = sum(1 for v in self.state.values() if v == "done")
            self.finished.title.setText("Sesja zakończona" if done else "Na dziś wszystko")
            self.finished.text.setText(
                (f"Ocenione w tej sesji: {done}. " if done else "") +
                "Kolejne fiszki wrócą w wyznaczonym dniu (1, 3, 7… dni). Możesz też powtórzyć wszystkie od nowa.")
            self.btn_again.setText(f"Powtórz wszystkie · {len(self.items)}")
            self.stack.setCurrentIndex(2)
            return
        self.stack.setCurrentIndex(0)
        self.cur = self.queue.pop(0)
        self._show_card(answer=False)

    def _show_card(self, answer: bool):
        from ..mathrender import text_to_html
        from ..srs import next_label
        from ..notes_style import mark_highlights
        t = T()
        lec, cards, i = self.items[self.cur]
        c = cards[i]
        mdir = lec.folder / "math"
        self.q.setText(text_to_html(c["q"], mdir, t.text))
        a_html = text_to_html(c["a"], mdir, t.text)
        a_html = mark_highlights(a_html).replace("<mark>", f"<span style='background-color:{t.mark};'>") \
            .replace("</mark>", "</span>")
        self.a.setText(a_html)
        cat = c.get("category") or ""
        color = palette_color(self._deck_color(lec, cat))
        self.chip.set(cat, color)
        topic = c.get("topic") or ""
        sec = int(c.get("section") or 0)
        parts = []
        if topic or sec:
            parts.append(f"Z notatki: <a href='note:{sec}' style='color:{t.accent_text}; text-decoration:none;'>"
                         f"{html.escape((str(sec) + '. ') if sec else '')}{html.escape(topic) or lec.meta.title}</a>")
        else:
            parts.append(f"Z notatki: <a href='note:0' style='color:{t.accent_text}; text-decoration:none;'>"
                         f"{html.escape(lec.meta.title)}</a>")
        if c.get("t") is not None and lec.audio_parts():
            from ..storage import fmt_time
            parts.append(f"<a href='play:{float(c.get('t') or 0)}' style='color:{t.accent_text}; "
                         f"text-decoration:none;'>▶ {fmt_time(float(c.get('t') or 0))}</a>")
        self.src.setText(" · ".join(parts))
        self.btn_no.setText("Jeszcze nie · 1\nwróci w tej sesji")
        nl = next_label(c)
        self.btn_yes.setText(f"Umiem · 2\nnastępna powtórka {nl}")
        for w in (self.a_head, self.a):
            w.setVisible(answer)
        self.a_hint.setVisible(not answer)
        self.btn_show.setVisible(not answer)
        self._revealed = answer
        self.answer_wrap.setVisible(answer)
        self.answer_row.setVisible(answer)
        self._bar()

    def _deck_color(self, lec, cat: str) -> int:
        for d in getattr(self, "decks", []):
            if d.name == cat and str(d.lecture.folder) == str(lec.folder):
                return d.color
        return 0

    def _space(self):
        if not getattr(self, "_revealed", False) and self.cur is not None and self.right_stack.currentIndex() == 0:
            self.show_answer()

    def show_answer(self):
        if self.cur is None:
            return
        self._show_card(answer=True)

    def answer(self, known: bool):
        if self.cur is None or not getattr(self, '_revealed', False):
            return
        from ..srs import review
        lec, cards, i = self.items[self.cur]
        self.history.append((self.cur, copy.deepcopy(cards[i]), list(self.queue), dict(self.state)))
        review(cards[i], known)
        lec.save_flashcards(cards)
        try:
            from .. import study_stats
            study_stats.record_review(self.settings.library_path())
            self.reviewed.emit()
        except Exception:  # noqa: BLE001
            pass
        if known:
            self.state[self.cur] = "done"
        else:
            self.state[self.cur] = "again"
            self.queue.insert(min(3, len(self.queue)), self.cur)
        self.next_card()

    def undo(self):
        """Ctrl+Z: cofa ostatnią ocenę (karta wraca z odsłoniętą odpowiedzią)."""
        if not self.history:
            return
        k, before, queue, state = self.history.pop()
        lec, cards, i = self.items[k]
        cards[i].clear()
        cards[i].update(before)
        lec.save_flashcards(cards)
        try:
            from .. import study_stats
            study_stats.record_review(self.settings.library_path(), -1)
            self.reviewed.emit()
        except Exception:  # noqa: BLE001
            pass
        if self.cur is not None and self.cur != k:
            queue.insert(0, self.cur) if self.cur not in queue else None
        self.queue = [x for x in queue if x != k]
        self.state = state
        self.cur = k
        self.stack.setCurrentIndex(0)
        self._update_header()
        self._show_card(answer=True)

    def edit_card(self):
        if self.cur is None or self.right_stack.currentIndex() != 0 or self.stack.currentIndex() != 0:
            return
        lec, cards, i = self.items[self.cur]
        dlg = CardEditor(cards[i], self)
        if dlg.exec():
            q, a = dlg.q.toPlainText().strip(), dlg.a.toPlainText().strip()
            if q and a:
                cards[i]["q"], cards[i]["a"] = q, a
                lec.save_flashcards(cards)
                self._show_card(answer=getattr(self, "_revealed", False))

    def _src_link(self, link: str):
        if self.cur is None:
            return
        lec, cards, i = self.items[self.cur]
        if link.startswith("play:"):
            self.play_at.emit(lec, float(link[5:]))
        elif link.startswith("note:"):
            sec = int(link[5:] or 0)
            anchor = ""
            if sec:
                from ..topics import sections_of
                md = lec.read_text(lec.notes_path) if lec.notes_path.exists() else ""
                anchor = next((a for n, _t, a, _tm in sections_of(md) if n == sec), "")
            self.open_note.emit(str(lec.folder), anchor)


class QLabel_(QWidget):
    """Chip kategorii na karcie: kolorowy kwadracik + nazwa."""

    def __init__(self):
        super().__init__()
        self.text, self.color = "", ""
        self.setFixedHeight(24)

    def set(self, text: str, color: str):
        self.text, self.color = text, color
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        from PySide6.QtGui import QFontMetrics
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(text) + 34 if text else 0)
        show_if(self, text)
        self.update()

    def paintEvent(self, _e):
        from .theme import soft
        if not self.text:
            return
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(self.color)))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(qcolor(self.color))
        p.drawRoundedRect(QRectF(10, r.center().y() - 4, 8, 8), 2, 2)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        f.setPointSizeF(f.pointSizeF() - 0.8)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        p.drawText(r.adjusted(24, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, self.text)
        p.end()
