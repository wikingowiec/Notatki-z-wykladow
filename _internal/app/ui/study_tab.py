"""Ekran „Fiszki”: przeglądanie fiszek w kategoriach (tematy, definicje, karty) i nauka (powtórki)."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..storage import Lecture, list_lectures
from .controls import (AdaptiveBox, EmptyState, Heading, SegmentedControl, Sheet, ToggleSwitch, hairline, hbox,
                       label, paint_shadow, set_icon)

DECK = Qt.ItemDataRole.UserRole + 1


class DeckDelegate(QStyledItemDelegate):
    """Kafelek kategorii: pasek koloru, nazwa, wykład, liczba fiszek i postęp."""
    SIZE = QSize(262, 132)

    def sizeHint(self, option, index):
        return self.SIZE

    def paint(self, p: QPainter, option, index):
        from .theme import T, display_font, palette_color, qcolor, soft
        t = T()
        d = index.data(DECK)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 6, -6, -8)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        color = palette_color(d.color)
        paint_shadow(p, r, 14, 1.0 if hover else 0.5)
        p.setPen(qcolor(t.accent if hover else t.separator))
        p.setBrush(qcolor(t.surface))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(color)))
        p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 14, 34, 34), 10, 10)
        p.setBrush(qcolor(color))
        p.drawEllipse(QRectF(r.left() + 25, r.top() + 25, 12, 12))
        f = display_font(13.5)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(r.left() + 58, r.top() + 12, r.width() - 70, 24), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.name, Qt.TextElideMode.ElideRight, int(r.width() - 70)))
        f2 = QFont(option.font)
        f2.setPointSizeF(f2.pointSizeF() - 1)
        p.setFont(f2)
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(r.left() + 58, r.top() + 34, r.width() - 70, 18), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.lecture.meta.title, Qt.TextElideMode.ElideRight, int(r.width() - 70)))
        due = d.due()
        info = f"{d.total} fiszek · opanowane {d.known}" + (f" · dziś {due}" if due else "")
        p.drawText(QRectF(r.left() + 16, r.bottom() - 46, r.width() - 32, 18), Qt.AlignmentFlag.AlignVCenter, info)
        bar = QRectF(r.left() + 16, r.bottom() - 22, r.width() - 32, 6)
        p.setBrush(qcolor(t.track))
        p.drawRoundedRect(bar, 3, 3)
        if d.total:
            p.setBrush(qcolor(color))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * d.known / d.total), 6), 3, 3)
        p.restore()


class StudyTab(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.items: list[tuple[Lecture, list, int]] = []   # (wykład, lista fiszek wykładu, indeks)
        self.queue: list[int] = []
        self.cur: int | None = None
        self.done_in_round = 0
        self.round_total = 0

        # --- nagłówek ---
        from .controls import ChoiceCombo
        self.scope = ChoiceCombo()
        self.scope.setMinimumWidth(260)
        self.scope.currentIndexChanged.connect(lambda _i: (setattr(self, "deck", None), self.deck_chip.hide(),
                                                            self.browse.setCurrentIndex(0), self.load()))
        self.only_unknown = ToggleSwitch(True)
        self.only_unknown.toggled.connect(lambda _v: self.load())
        self.btn_shuffle = QPushButton("Od nowa")
        set_icon(self.btn_shuffle, "shuffle", "text2", 16)
        self.btn_shuffle.clicked.connect(self.load)
        self.heading = Heading("Fiszki", "", "Nauka")
        self.stats = self.heading.subtitle
        self.stats.show()
        controls = AdaptiveBox(threshold=600, spacing=10, vspacing=8)
        controls.add(self.scope, 1)
        self.study_controls = hbox(label("Tylko do powtórki dziś", "secondary"), self.only_unknown, self.btn_shuffle,
                                   spacing=10)
        controls.add(self.study_controls, 0, Qt.AlignmentFlag.AlignVCenter, Qt.AlignmentFlag.AlignLeft)
        head = AdaptiveBox(threshold=980, spacing=20, vspacing=14)
        head.add(self.heading, 1)
        head.add(controls, 0, Qt.AlignmentFlag.AlignBottom, None)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)

        # --- karta ---
        self.card = Sheet(radius=20, ruled=True)
        cl = self.card.lay
        cl.setContentsMargins(56, 30, 56, 44)
        cl.setSpacing(18)
        self.source = label("", "footnote")
        self.source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.q = label("", "cardQ", wrap=True)
        self.q.setTextFormat(Qt.TextFormat.RichText)
        self.q.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.q.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.line = hairline()
        self.line.setStyleSheet("background: transparent;")
        self.a = label("", "cardA", wrap=True)
        self.a.setTextFormat(Qt.TextFormat.RichText)
        self.a.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.a.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.source)
        cl.addSpacing(10)
        cl.addStretch(1)
        cl.addWidget(self.q)
        cl.addStretch(1)
        cl.addWidget(self.line)
        cl.addWidget(self.a)
        cl.addStretch(1)

        self.btn_show = QPushButton("Pokaż odpowiedź")
        self.btn_show.setObjectName("primary")
        self.btn_show.setMinimumWidth(220)
        self.btn_show.setMinimumHeight(38)
        self.btn_show.clicked.connect(self.show_answer)
        self.btn_no = QPushButton("Jeszcze nie")
        self.btn_no.setObjectName("destructive")
        self.btn_no.setMinimumSize(170, 38)
        set_icon(self.btn_no, "xmark", "red", 16)
        self.btn_show.setObjectName("big")
        self.btn_no.clicked.connect(lambda: self.answer(False))
        self.btn_yes = QPushButton("Umiem")
        self.btn_yes.setObjectName("positive")
        self.btn_yes.setMinimumSize(170, 38)
        set_icon(self.btn_yes, "check", "green", 16)
        self.btn_yes.clicked.connect(lambda: self.answer(True))
        self.answer_row = QWidget()
        ar = QHBoxLayout(self.answer_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.addStretch()
        ar.addWidget(self.btn_no)
        ar.addSpacing(10)
        ar.addWidget(self.btn_yes)
        ar.addStretch()
        self.hint = label("", "cardHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        study = QWidget()
        sl = QVBoxLayout(study)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        self.card.setMaximumHeight(620)
        sl.addStretch(1)
        sl.addWidget(self.card, 6)
        sl.addWidget(self.btn_show, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addWidget(self.answer_row)
        sl.addWidget(self.hint)
        sl.addStretch(1)

        self.btn_again = QPushButton("Powtórz wszystkie")
        self.btn_again.setObjectName("primary")
        self.btn_again.clicked.connect(self._repeat_all)
        self.empty = EmptyState("cards", "Brak fiszek",
                                "Fiszki powstają automatycznie razem z notatkami z wykładu.")
        self.finished = EmptyState("check", "Na dziś wszystko",
                                   "Powtórzone! Kolejne fiszki wrócą w wyznaczonym dniu (1, 3, 7… dni). "
                                   "Możesz też przejrzeć wszystkie od nowa.", self.btn_again)
        self.stack = QStackedWidget()
        self.stack.addWidget(study)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.finished)

        # --- tryb „Ucz się”: opcjonalnie tylko jedna kategoria ---
        self.deck = None
        self.deck_chip = QPushButton("")
        self.deck_chip.setObjectName("plain")
        set_icon(self.deck_chip, "xmark", "accent", 14)
        self.deck_chip.setToolTip("Ucz się wszystkich kategorii")
        self.deck_chip.clicked.connect(self._clear_deck)
        self.deck_chip.hide()
        study_page = QWidget()
        spl = QVBoxLayout(study_page)
        spl.setContentsMargins(0, 0, 0, 0)
        spl.setSpacing(12)
        spl.addWidget(self.deck_chip, 0, Qt.AlignmentFlag.AlignLeft)
        spl.addWidget(self.progress)
        spl.addWidget(self.stack, 1)

        # --- tryb „Fiszki”: kategorie (kafelki) → kategoria (tematy, definicje, fiszki) ---
        self.grid = QListWidget()
        self.grid.setObjectName("thumbs")
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setMouseTracking(True)
        self.grid.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.grid.setItemDelegate(DeckDelegate(self.grid))
        self.grid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grid.itemClicked.connect(lambda it: self.open_deck(it.data(DECK)))
        from .reader import Reader
        self.deck_view = Reader(max_width=820, pad=30)
        self.deck_title = label("", "title2")
        self.deck_sub = label("", "secondary")
        b_back = QPushButton("Kategorie")
        b_back.setObjectName("back")
        set_icon(b_back, "chevron-left", "accent", 16)
        b_back.clicked.connect(lambda: self.browse.setCurrentIndex(0))
        self.btn_learn_deck = QPushButton("Ucz się tej kategorii")
        self.btn_learn_deck.setObjectName("primary")
        set_icon(self.btn_learn_deck, "play", "on_accent", 14)
        self.btn_learn_deck.clicked.connect(lambda: self.study_deck(self._open_deck))
        dh = AdaptiveBox(threshold=640, spacing=12, vspacing=8)
        dtv = QWidget()
        dtl = QVBoxLayout(dtv)
        dtl.setContentsMargins(0, 0, 0, 0)
        dtl.setSpacing(2)
        dtl.addWidget(self.deck_title)
        dtl.addWidget(self.deck_sub)
        dh.add(dtv, 1)
        dh.add(self.btn_learn_deck, 0, Qt.AlignmentFlag.AlignVCenter, Qt.AlignmentFlag.AlignLeft)
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)
        dl.addWidget(b_back, 0, Qt.AlignmentFlag.AlignLeft)
        dl.addWidget(dh)
        dl.addWidget(self.deck_view, 1)
        self.browse_empty = EmptyState("cards", "Brak fiszek",
                                       "Fiszki powstają automatycznie razem z notatkami z wykładu – pogrupowane "
                                       "w kategorie tematów.")
        self.browse = QStackedWidget()
        self.browse.addWidget(self.grid)
        self.browse.addWidget(detail)
        self.browse.addWidget(self.browse_empty)

        self.mode_seg = SegmentedControl(["Fiszki", "Ucz się"], style="tabs")
        self.mode_seg.changed.connect(self._set_mode)
        self.modes = QStackedWidget()
        self.modes.addWidget(self.browse)
        self.modes.addWidget(study_page)

        col = QWidget()
        col.setMaximumWidth(1100)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        v.addWidget(head)
        v.addWidget(self.mode_seg)
        v.addWidget(self.modes, 1)
        self.study_controls.hide()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 24)
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        self.outer = outer

        for key, fn in ((Qt.Key.Key_Space, self._space), (Qt.Key.Key_1, lambda: self.answer(True)),
                        (Qt.Key.Key_2, lambda: self.answer(False))):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < 700
        self.outer.setContentsMargins(*((14, 16, 14, 14) if narrow else (36, 30, 36, 24)))
        self.card.lay.setContentsMargins(*((30, 22, 30, 30) if narrow else (56, 30, 56, 44)))

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------ tryby
    def _set_mode(self, i: int):
        self.mode_seg.set_current(i)
        self.modes.setCurrentIndex(i)
        self.study_controls.setVisible(i == 1)
        if i == 1:
            self.setFocus()

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

    def refresh_decks(self):
        from ..flashcards import decks_for
        self.grid.clear()
        decks = decks_for(self._lectures_in_scope())
        for d in decks:
            it = QListWidgetItem()
            it.setData(DECK, d)
            it.setToolTip(f"{d.name} – {d.lecture.meta.title}")
            self.grid.addItem(it)
        if self.browse.currentIndex() != 1 or not decks:
            self.browse.setCurrentIndex(0 if decks else 2)

    def open_deck(self, deck):
        from ..flashcards import deck_markdown
        from .library_tab import build_notes
        from .widgets import run_async
        self._open_deck = deck
        self.deck_title.setText(deck.name)
        due = deck.due()
        self.deck_sub.setText(f"{deck.lecture.meta.title} · {deck.total} fiszek · opanowane {deck.known}"
                              + (f" · do powtórki dziś {due}" if due else ""))
        self.browse.setCurrentIndex(1)
        folder, dpr, md = deck.lecture.folder, self.devicePixelRatioF() or 1.0, deck_markdown(deck)
        view = self.deck_view
        view.setHtml("")

        def done(res):
            html_doc, images, _p = res
            view.images = images
            view.setHtml(html_doc)
        run_async(lambda: build_notes(folder, md, dpr, audio=False, toc=False), done)

    def study_deck(self, deck):
        self.deck = deck
        self.deck_chip.setText(f"Tylko: {deck.name}  ·  {deck.lecture.meta.title}")
        self.deck_chip.show()
        self._set_mode(1)
        self.load()

    def _clear_deck(self):
        self.deck = None
        self.deck_chip.hide()
        self.load()

    def refresh_scopes(self, keep: bool = True):
        cur = self.scope.currentData() if keep else None
        lectures = [l for l in list_lectures(self.settings.library_path()) if l.flashcards_path.exists()]
        self.scope.fill_scope(lectures, "Wszystkie fiszki", keep=cur)

    def set_scope_lecture(self, lec: Lecture):
        self.refresh_scopes()
        i = self.scope.findData(("lecture", str(lec.folder)))
        if i >= 0:
            self.scope.setCurrentIndex(i)
        self.deck = None
        self.deck_chip.hide()
        self._set_mode(0)
        self.load()

    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()

    def load(self):
        self.refresh_decks()
        self.items = []
        if self.deck is not None:           # jedna kategoria
            from ..flashcards import decks_for
            d = next((x for x in decks_for([Lecture(self.deck.lecture.folder)]) if x.name == self.deck.name), None)
            for cards, i in (d.entries if d else []):
                self.items.append((d.lecture, cards, i))
        else:
            for l in self._lectures_in_scope():
                cards = l.load_flashcards()
                for i in range(len(cards)):
                    self.items.append((l, cards, i))
        from ..srs import is_due, today
        day = today()
        idx = [k for k, (_l, cards, i) in enumerate(self.items)
               if not self.only_unknown.isChecked() or is_due(cards[i], day)]
        random.shuffle(idx)
        self.queue = idx
        self.round_total = len(idx)
        self.done_in_round = 0
        self.next_card()

    def _repeat_all(self):
        self.only_unknown.setChecked(False)
        self.load()

    def _update_stats(self):
        from ..srs import is_due, today
        day = today()
        total = len(self.items)
        known = sum(1 for _l, cards, i in self.items if cards[i].get("known"))
        due = sum(1 for _l, cards, i in self.items if is_due(cards[i], day))
        self.stats.setText(f"{total} fiszek · do powtórki dziś {due} · opanowane {known}" if total else "")
        self.progress.setRange(0, max(1, self.round_total))
        self.progress.setValue(self.done_in_round)
        self.progress.setVisible(bool(self.round_total))

    def next_card(self):
        self._update_stats()
        if not self.items:
            self.cur = None
            self.stack.setCurrentIndex(1)
            return
        if not self.queue:
            self.cur = None
            self.stack.setCurrentIndex(2)
            return
        self.stack.setCurrentIndex(0)
        self.cur = self.queue.pop(0)
        lec, cards, i = self.items[self.cur]
        self.source.setText(" · ".join(x for x in [lec.meta.subject, lec.meta.title] if x))
        from .theme import subject_color
        self.card.set_strip(subject_color(lec.meta.subject))
        from ..mathrender import text_to_html
        from ..srs import next_label
        from .theme import T
        mdir = lec.folder / "math"
        self.q.setText(text_to_html(cards[i]["q"], mdir, T().text))
        self.a.setText(text_to_html(cards[i]["a"], mdir, T().text))
        self.btn_yes.setText(f"Umiem · {next_label(cards[i])}")
        self.a.hide()
        self.line.hide()
        self.btn_show.show()
        self.answer_row.hide()
        self.hint.setText(f"Karta {self.done_in_round + 1} z {self.round_total}   ·   Spacja – pokaż odpowiedź")

    def _space(self):
        if self.btn_show.isVisible():
            self.show_answer()

    def show_answer(self):
        if self.cur is None:
            return
        self.a.show()
        self.line.show()
        self.btn_show.hide()
        self.answer_row.show()
        self.hint.setText("1 – umiem   ·   2 – jeszcze nie")

    def answer(self, known: bool):
        if self.cur is None or not self.answer_row.isVisible():
            return
        from ..srs import review
        lec, cards, i = self.items[self.cur]
        review(cards[i], known)
        lec.save_flashcards(cards)
        if known:
            self.done_in_round += 1
        else:
            self.queue.insert(min(3, len(self.queue)), self.cur)
        self.next_card()
