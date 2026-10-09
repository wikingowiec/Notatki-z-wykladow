"""Główne okno: pasek boczny (jak w aplikacjach macOS) + ekrany."""
from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from ..config import APP_NAME
from ..storage import card_stats, fmt_time, list_lectures
from .controls import label
from .library_tab import LibraryTab
from .record_tab import RecordTab
from .settings_tab import SettingsTab
from .study_tab import StudyTab
from .theme import T, apply_titlebar, icon_pixmap, logo_pixmap, qcolor, soft, subject_color, theme
from .widgets import JobRunner

log = logging.getLogger(__name__)

KIND = Qt.ItemDataRole.UserRole + 1
ICON = Qt.ItemDataRole.UserRole + 2
COUNT = Qt.ItemDataRole.UserRole + 3
KEY = Qt.ItemDataRole.UserRole + 4
ALERT = Qt.ItemDataRole.UserRole + 5
COLOR = Qt.ItemDataRole.UserRole + 6

SIDEBAR_W = 240
RAIL_W = 64


class SidebarDelegate(QStyledItemDelegate):
    """Pasek boczny: przycisk „Nowa notatka”, sekcje, przedmioty z kolorową kropką.
    W trybie szyny (wąskie okno) – same ikony."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rail = False

    def sizeHint(self, option, index):
        kind = index.data(KIND)
        if kind == "header":
            return QSize(60, 16 if self.rail else 34)
        if kind == "primary":
            return QSize(60, 54)
        return QSize(60, 38 if self.rail else 36)

    def paint(self, p: QPainter, option, index):
        t = T()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        font = QFont(option.font)
        kind = index.data(KIND)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        dpr = p.device().devicePixelRatioF()
        if kind == "header":
            if self.rail:
                p.setPen(QPen(qcolor(t.separator), 1))
                y = r.center().y()
                p.drawLine(int(r.center().x() - 12), int(y), int(r.center().x() + 12), int(y))
            else:
                f = QFont(font)
                f.setPointSizeF(font.pointSizeF() - 1.5)
                f.setWeight(QFont.Weight.Bold)
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
                p.setFont(f)
                p.setPen(qcolor(t.text3))
                p.drawText(r.adjusted(10, 10, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           text.upper())
            p.restore()
            return

        if kind == "primary":
            rec = bool(index.data(ALERT))
            rr = r.adjusted(0, 4, 0, -10)
            if rec:
                bg, fg = qcolor(t.red_soft), qcolor(t.red)
            elif sel:
                bg, fg = qcolor(t.accent), qcolor(t.on_accent)
            else:
                bg, fg = qcolor(t.accent_soft if not hover else t.selected), qcolor(t.accent if not t.dark else t.text)
                if hover:
                    fg = qcolor(t.text)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            if self.rail:
                d = 42
                c = QRectF(rr.center().x() - d / 2, rr.center().y() - d / 2, d, d)
                p.drawRoundedRect(c, T().r("md"), T().r("md"))
                if rec:
                    p.setBrush(fg)
                    p.drawEllipse(QRectF(c.center().x() - 6, c.center().y() - 6, 12, 12))
                else:
                    pm = icon_pixmap("plus", fg.name(), 20, dpr)
                    p.drawPixmap(int(c.center().x() - 10), int(c.center().y() - 10), pm)
            else:
                p.drawRoundedRect(rr, T().r("md"), T().r("md"))
                if rec:
                    p.setBrush(fg)
                    p.drawEllipse(QRectF(rr.left() + 16, rr.center().y() - 5, 10, 10))
                else:
                    pm = icon_pixmap("plus", fg.name(), 18, dpr)
                    p.drawPixmap(int(rr.left() + 12), int(rr.center().y() - 9), pm)
                f = QFont(font)
                f.setWeight(QFont.Weight.DemiBold)
                p.setFont(f)
                p.setPen(fg)
                label_ = "Nagrywanie" if rec else text
                p.drawText(rr.adjusted(40, 0, -12, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label_)
                if rec and index.data(COUNT):
                    p.drawText(rr.adjusted(0, 0, -14, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                               str(index.data(COUNT)).replace("● ", ""))
            p.restore()
            return

        rr = r.adjusted(0, 1, 0, -1)
        if self.rail:
            rr = QRectF(r.center().x() - 22, r.top() + 1, 44, r.height() - 2)
        if sel or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.selected if sel else t.hover))
            p.drawRoundedRect(rr, T().r("md"), T().r("md"))
        color = index.data(COLOR)
        icon = index.data(ICON)
        icon_x = rr.center().x() - 9 if self.rail else rr.left() + 11
        if color:
            if self.rail:
                sq = QRectF(rr.center().x() - 13, rr.center().y() - 13, 26, 26)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(soft(color)))
                p.drawRoundedRect(sq, T().r("sm"), T().r("sm"))
                f = QFont(font)
                f.setWeight(QFont.Weight.Bold)
                p.setFont(f)
                p.setPen(qcolor(color))
                p.drawText(sq, Qt.AlignmentFlag.AlignCenter, (text[:1] or "?").upper())
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(color))
                p.drawRoundedRect(QRectF(icon_x + 4.5, rr.center().y() - 4.5, 9, 9), 2, 2)
        elif icon:
            pm = icon_pixmap(icon, t.accent if sel else t.text2, 18, dpr)
            p.drawPixmap(int(icon_x), int(rr.center().y() - 9), pm)
        count = str(index.data(COUNT) or "")
        alert = bool(index.data(ALERT))
        if self.rail:
            if count and alert:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(t.accent))
                p.drawEllipse(QRectF(rr.right() - 12, rr.top() + 5, 8, 8))
            p.restore()
            return
        f = QFont(font)
        if sel:
            f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        cw = 0
        if count:
            fc = QFont(font)
            fc.setPointSizeF(font.pointSizeF() - 1)
            fc.setWeight(QFont.Weight.DemiBold if alert else QFont.Weight.Normal)
            p.setFont(fc)
            cw = p.fontMetrics().horizontalAdvance(count) + (16 if alert else 4)
            cr = QRectF(rr.right() - 10 - cw, rr.center().y() - 10, cw, 20)
            if alert:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(t.accent))
                p.drawRoundedRect(cr, T().r("md"), T().r("md"))
                p.setPen(qcolor(t.on_accent))
            else:
                p.setPen(qcolor(t.text3))
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, count)
            p.setFont(f)
        p.setPen(qcolor(t.text))
        tr = rr.adjusted(40, 0, -cw - 16, 0)
        p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(tr.width())))
        p.restore()


def _fmt_left(sec: float) -> str:
    if sec < 60:
        return "minuta"
    m = round(sec / 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 880)
        self.setMinimumSize(520, 560)
        self.runner = JobRunner()
        self._rail = None

        self.record = RecordTab(settings)
        self.library = LibraryTab(settings, self.runner)
        self.study = StudyTab(settings)
        from .ask_tab import AskTab
        from .exam_tab import ExamTab
        self.ask_tab = AskTab(settings, busy_hint=lambda: self.runner.busy)
        self.exam_tab = ExamTab(settings, self.runner)
        self.settings_tab = SettingsTab(settings)
        self.pages = QStackedWidget()
        for w in (self.record, self.library, self.study, self.ask_tab, self.exam_tab, self.settings_tab):
            self.pages.addWidget(w)

        # ---------------- pasek boczny ----------------
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(SIDEBAR_W)
        self.side = side
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 18, 0, 14)
        sv.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(20, 0, 12, 10)
        head.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(30, 30)
        self._paint_logo()
        theme().changed.connect(self._paint_logo)
        head.addWidget(self.logo)
        self.app_title = label(APP_NAME, "appTitle")
        head.addWidget(self.app_title, 1)
        self.side_head = head
        sv.addLayout(head)

        # „Nowa notatka” | mikrofon („nagraj jak ostatnio”), w trakcie nagrywania – pozycja „● Nagrywanie 48:12”
        quick = QWidget()
        ql = QVBoxLayout(quick)
        ql.setContentsMargins(12, 0, 12, 6)
        ql.setSpacing(6)
        from PySide6.QtWidgets import QBoxLayout, QPushButton
        from .controls import set_icon
        self.split = QWidget()
        self.split_lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.split)
        self.split_lay.setContentsMargins(0, 0, 0, 0)
        self.split_lay.setSpacing(0)
        self.btn_new = QPushButton("Nowa notatka")
        self.btn_new.setObjectName("splitMain")
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setToolTip("Nowa notatka – nagranie albo pliki")
        set_icon(self.btn_new, "plus", "on_accent", 18)
        self.btn_new.clicked.connect(lambda: self._select_key(("record", None)))
        self.btn_mic = QPushButton()
        self.btn_mic.setObjectName("splitMic")
        self.btn_mic.setCursor(Qt.CursorShape.PointingHandCursor)
        set_icon(self.btn_mic, "mic", "on_accent", 18)
        self.btn_mic.clicked.connect(self.quick_record)
        self.split_lay.addWidget(self.btn_new, 1)
        self.split_lay.addWidget(self.btn_mic)
        self.quick_caption = label("", "caption", wrap=True)
        self.quick_caption.setContentsMargins(4, 0, 4, 0)
        self.rec_pill = QPushButton("")
        self.rec_pill.setObjectName("recPill")
        self.rec_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rec_pill.setToolTip("Wróć do nagrywania")
        self.rec_pill.clicked.connect(lambda: self._select_key(("record", None)))
        self.rec_pill.hide()
        # bez fokusu: ukrycie przycisku z fokusem przenosi go na listę, a ta wybiera 1. pozycję (skok do biblioteki)
        for b in (self.btn_new, self.btn_mic, self.rec_pill):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ql.addWidget(self.split)
        ql.addWidget(self.rec_pill)
        ql.addWidget(self.quick_caption)
        sv.addWidget(quick)

        self.delegate = SidebarDelegate()
        self.nav = QListWidget()
        self.nav.setObjectName("sidebarList")
        self.nav.setItemDelegate(self.delegate)
        self.nav.setMouseTracking(True)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.currentItemChanged.connect(self._nav_changed)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # fokus z klawiatury wybierałby 1. pozycję listy
        sv.addWidget(self.nav, 1)

        # karta zadania w tle
        self.job_card = QFrame()
        self.job_card.setObjectName("jobCard")
        jl = QVBoxLayout(self.job_card)
        jl.setContentsMargins(12, 10, 12, 11)
        jl.setSpacing(6)
        self.job_over = label("AI PRACUJE W TLE", "overline")
        self.job_title = label("", "headline", wrap=True)
        self.job_msg = label("", "caption", wrap=True)
        self.job_bar = QProgressBar()
        self.job_bar.setTextVisible(False)
        self.job_eta = label("", "caption")
        jl.addWidget(self.job_over)
        jl.addWidget(self.job_title)
        jl.addWidget(self.job_msg)
        jl.addWidget(self.job_bar)
        jl.addWidget(self.job_eta)
        self.job_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.job_card.mousePressEvent = lambda _e: self._show_job_lecture()
        self.job_card.hide()
        jw = QWidget()
        jwl = QVBoxLayout(jw)
        jwl.setContentsMargins(12, 0, 12, 0)
        jwl.addWidget(self.job_card)
        sv.addWidget(jw)

        self.streak = QPushButton("")
        self.streak.setObjectName("streak")
        self.streak.setCursor(Qt.CursorShape.PointingHandCursor)
        self.streak.clicked.connect(lambda: self._select_key(("study", None)))
        self.streak.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sw = QWidget()
        swl = QVBoxLayout(sw)
        swl.setContentsMargins(12, 0, 12, 0)
        swl.addWidget(self.streak)
        sv.addWidget(sw)

        self.delegate_bottom = SidebarDelegate()
        self.nav_bottom = QListWidget()
        self.nav_bottom.setObjectName("sidebarList")
        self.nav_bottom.setItemDelegate(self.delegate_bottom)
        self.nav_bottom.setMouseTracking(True)
        self.nav_bottom.setFixedHeight(42)
        self.nav_bottom.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_bottom.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        it = QListWidgetItem("Ustawienia")
        it.setData(KIND, "item")
        it.setData(ICON, "settings")
        it.setData(KEY, ("settings", None))
        it.setToolTip("Ustawienia")
        self.nav_bottom.addItem(it)
        self.nav_bottom.currentItemChanged.connect(self._nav_bottom_changed)
        self.nav_bottom.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sv.addWidget(self.nav_bottom)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(side)
        cl.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        # ---------------- sygnały ----------------
        self.record.recording_finished.connect(self._after_recording)
        self.record.recording_state.connect(self._recording_state)
        self.record.last_rec_changed.connect(self._update_quick)
        self.study.reviewed.connect(self._update_streak)
        self.study.open_note.connect(self.open_lecture_at)
        self.study.play_at.connect(lambda lec, t: (self.open_lecture_at(str(lec.folder)),
                                                  self.library.player.play(lec, t, None, "Fiszka")))
        self.library.study_requested.connect(self._study_lecture)
        self.library.continue_requested.connect(self._continue_lecture)
        self.library.new_from_files.connect(self._new_from_files)
        self.library.exam_requested.connect(self._exam_lecture)
        self.record.files_requested.connect(self._import_files)
        self.ask_tab.open_lecture.connect(self.open_lecture_at)
        self.exam_tab.open_lecture.connect(self.open_lecture_at)
        self.library.library_changed.connect(self.rebuild_nav)
        self.settings_tab.saved.connect(self._settings_saved)
        self.runner.started.connect(self._job_started)
        self.runner.progress.connect(self._job_progress)
        self.runner.finished.connect(self._job_finished)
        theme().changed.connect(self._theme_changed)

        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._update_rec_item)
        self._lib_dir = settings.library_dir

        self.rebuild_nav()
        self._update_quick()
        self._update_streak()
        self._job_t0 = 0.0
        from PySide6.QtGui import QKeySequence, QShortcut
        for seq, fn in (("Ctrl+Shift+R", self.quick_record), ("Ctrl+K", self.quick_jump)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)
        self._select_key(("library", None) if list_lectures(settings.library_path()) else ("record", None))
        QTimer.singleShot(800, self._recover)
        # wszystkie listy rozwijane: wyższe, czytelne pozycje
        from PySide6.QtWidgets import QComboBox
        from .controls import ChoiceCombo, style_combo
        for c in self.findChildren(QComboBox):
            if not isinstance(c, ChoiceCombo):
                style_combo(c, max(260, c.minimumWidth()))
        # aktualizacje: sprawdzanie w tle po starcie, znaczek przy „Ustawieniach”
        self.settings_tab.busy_fn = self._busy_reason
        self.settings_tab.updates.update_available.connect(self._update_badge)
        self.settings_tab.updates.restart_requested.connect(self._restart_after_update)
        QTimer.singleShot(6000, lambda: self.settings_tab.updates.check(silent=True))

    # ------------------------------------------------------------------ nawigacja
    def rebuild_nav(self):
        cur = self.nav.currentItem().data(KEY) if self.nav.currentItem() else None
        lectures = list_lectures(self.settings.library_path())
        subjects: dict[str, int] = {}
        for l in lectures:
            subjects[l.meta.subject] = subjects.get(l.meta.subject, 0) + 1
        cards = unknown = 0
        for l in lectures:
            n, u = card_stats(l)
            cards += n
            unknown += u

        self.nav.blockSignals(True)
        self.nav.clear()

        def add(text, kind="item", icon=None, key=None, count="", color=None, alert=False):
            it = QListWidgetItem(text)
            it.setData(KIND, kind)
            it.setData(ICON, icon)
            it.setData(KEY, key)
            it.setData(COUNT, count)
            it.setData(COLOR, color)
            it.setData(ALERT, alert)
            it.setToolTip(text + (f" ({count})" if count else ""))
            if kind == "header":
                it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.nav.addItem(it)
            return it

        add("Biblioteka", "header")
        add("Wszystkie wykłady", icon="books", key=("library", None), count=str(len(lectures)) if lectures else "")
        for s in sorted(k for k in subjects if k):
            add(s, key=("library", s), count=str(subjects[s]), color=subject_color(s))
        if "" in subjects and len(subjects) > 1:
            add("Bez przedmiotu", icon="folder", key=("library", ""), count=str(subjects[""]))
        add("Nauka", "header")
        add("Fiszki", icon="cards", key=("study", None), count=str(unknown) if unknown else "", alert=bool(unknown))
        add("Zapytaj", icon="question", key=("ask", None))
        add("Egzamin próbny", icon="exam", key=("exam", None))
        self.nav.blockSignals(False)
        if cur:
            self._select_key(cur, silent=True)
        self._update_rec_item()

    def _select_key(self, key, silent: bool = False):
        if key and key[0] == "record":
            for lst in (self.nav, self.nav_bottom):
                lst.blockSignals(True)
                lst.clearSelection()
                lst.setCurrentItem(None)
                lst.blockSignals(False)
            self._set_new_active(True)
            if not silent:
                self._open(key)
            return
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            if it.data(KEY) == key:
                if silent:
                    self.nav.blockSignals(True)
                self.nav.setCurrentItem(it)
                self.nav.blockSignals(False)
                if not silent:
                    self._open(key)
                return
        if key and key[0] == "settings":
            self.nav_bottom.setCurrentRow(0)

    def _nav_changed(self, item, _prev):
        if item is None or item.data(KEY) is None:
            return
        self._set_new_active(False)
        self.nav_bottom.blockSignals(True)
        self.nav_bottom.clearSelection()
        self.nav_bottom.setCurrentItem(None)
        self.nav_bottom.blockSignals(False)
        self._open(item.data(KEY))

    def _nav_bottom_changed(self, item, _prev):
        if item is None:
            return
        self._set_new_active(False)
        self.nav.blockSignals(True)
        self.nav.clearSelection()
        self.nav.setCurrentItem(None)
        self.nav.blockSignals(False)
        self._open(("settings", None))

    def _open(self, key):
        page, arg = key
        if page == "record":
            self.pages.setCurrentWidget(self.record)
        elif page == "library":
            self.library.set_filter(arg)
            self.pages.setCurrentWidget(self.library)
        elif page == "ask":
            self.ask_tab.refresh()
            self.pages.setCurrentWidget(self.ask_tab)
        elif page == "exam":
            if self.exam_tab.stack.currentIndex() == 0:
                self.exam_tab.refresh()
            self.pages.setCurrentWidget(self.exam_tab)
        elif page == "study":
            self.study.refresh_scopes()
            self.study.load()
            self.pages.setCurrentWidget(self.study)
        elif page == "settings":
            self.pages.setCurrentWidget(self.settings_tab)

    # ------------------------------------------------------------------ wygląd i układ
    def _paint_logo(self):
        self.logo.setPixmap(logo_pixmap(30, self.devicePixelRatioF() or 2.0))

    def _theme_changed(self):
        self.rebuild_nav()
        self.nav.viewport().update()
        self.nav_bottom.viewport().update()
        apply_titlebar(self)

    def showEvent(self, e):
        super().showEvent(e)
        apply_titlebar(self)
        self._relayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self):
        """Wąskie albo pionowe okno (np. monitor 9:16) → pasek boczny jako szyna z ikonami (64 px)."""
        from PySide6.QtWidgets import QBoxLayout  # noqa: F401
        w, h = self.width(), self.height()
        rail = w < 1100 or (h > w * 1.15 and w < 1400)
        if rail == self._rail:
            return
        self._rail = rail
        self.delegate.rail = rail
        self.delegate_bottom.rail = rail
        self.side.setFixedWidth(RAIL_W if rail else SIDEBAR_W)
        self.app_title.setVisible(not rail)
        self.side_head.setContentsMargins(23 if rail else 20, 0, 12, 10)
        self.nav.setStyleSheet("QListWidget#sidebarList { padding: 0 6px; }" if rail else "")
        for w_ in (self.job_title, self.job_msg, self.job_over, self.job_eta):
            w_.setVisible(not rail)
        self.split_lay.setDirection(QBoxLayout.Direction.TopToBottom if rail else QBoxLayout.Direction.LeftToRight)
        self.split_lay.setSpacing(6 if rail else 0)
        self.split.setProperty("rail", rail)
        for b in (self.btn_new, self.btn_mic, self.rec_pill, self.streak):
            b.setProperty("rail", rail)
            b.style().unpolish(b)
            b.style().polish(b)
        self.btn_new.setText("" if rail else "Nowa notatka")
        self._update_quick()
        self._update_streak()
        self._update_rec_item()
        for lst in (self.nav, self.nav_bottom):
            lst.doItemsLayout()
            lst.viewport().update()

    # ------------------------------------------------------------------ nagrywanie
    def _recording_state(self, on: bool):
        if on:
            self._rec_timer.start()
        else:
            self._rec_timer.stop()
        self._update_rec_item()

    def _update_rec_item(self):
        try:
            rec = self.record.is_recording()
        except RuntimeError:
            return
        self.split.setVisible(not rec)
        self.rec_pill.setVisible(rec)
        self.quick_caption.setVisible(not rec and not self._rail and bool(self.quick_caption.text()))
        if rec:
            tm = self.record.elapsed_text()
            paused = self.record.is_paused()
            word, sym = ("Pauza", "❚❚") if paused else ("Nagrywanie", "●")
            self.rec_pill.setText(sym if self._rail else f"{sym}   {word}   {tm}")
            self.rec_pill.setToolTip(f"Nagrywanie {tm} – wróć do nagrywania")

    def _set_new_active(self, on: bool):
        for b in (self.btn_new, self.rec_pill):
            if bool(b.property("active")) != on:
                b.setProperty("active", on)
                b.style().unpolish(b)
                b.style().polish(b)

    # ------------------------------------------------------------------ nagraj jak ostatnio
    def _update_quick(self):
        q = self.record.quick_label()
        self.btn_mic.setToolTip("Nowa notatka z ostatnimi ustawieniami (Ctrl+Shift+R)" + (f" – {q}" if q else "")
                                + "\nNagrywanie zacznie się dopiero po kliknięciu przycisku nagrywania.")
        self.quick_caption.setText(f"Ctrl Shift R — ustawienia jak ostatnio ({q})" if q else
                                   "Ctrl Shift R — ustawienia jak ostatnio")
        self.quick_caption.setVisible(not self._rail and not self.record.is_recording())

    def quick_record(self):
        """Otwiera nową notatkę z ostatnimi ustawieniami – start dopiero po „Start” (w trakcie: wraca do nagrywania)."""
        self._select_key(("record", None))
        if not self.record.is_recording():
            self.record.quick_prepare()

    # ------------------------------------------------------------------ szybkie przejście (Ctrl+K)
    def quick_jump(self):
        if self.pages.currentWidget() is self.record and self.record.is_recording():
            self.record.focus_ask()          # w trakcie nagrywania: pytanie do tego, co już padło
            return
        from .quick_jump import QuickJump
        dlg = QuickJump(self.settings, self)
        dlg.chosen.connect(self._jump_to)
        dlg.popup()

    def _jump_to(self, kind: str, a: str, b: str):
        if kind == "page":
            self._select_key((a, None))
        elif kind == "lecture":
            self.open_lecture_at(a, b)

    # ------------------------------------------------------------------ seria dni
    def _update_streak(self):
        from .. import study_stats
        from .controls import set_icon
        try:
            st = study_stats.summary(self.settings.library_path())
        except Exception:  # noqa: BLE001
            st = {"streak": 0, "today": 0}
        n = st["streak"]
        if self._rail:
            self.streak.setText(str(n) if n else "")
        elif n:
            self.streak.setText(f"{n} {study_stats.days_word(n)} nauki z rzędu")
        else:
            self.streak.setText("Zacznij serię – powtórz fiszki")
        self.streak.setToolTip(f"Seria: {n} {study_stats.days_word(n)} z rzędu · dziś ocenione fiszki: {st['today']}")
        set_icon(self.streak, "flame", "streak" if n else "text3", 18)

    def _after_recording(self, lecture, needs_file_transcription: bool):
        self.rebuild_nav()
        self._select_key(("library", None))
        self.library.select(lecture)
        auto = self.settings.auto_generate_notes
        if needs_file_transcription:
            self.library.retranscribe(lecture, then_notes=auto)
        elif auto:
            if lecture.load_segments() or lecture.load_slides().get("slides"):
                self.library.generate_notes(lecture, use_cache=True)   # fragmenty zrobione na żywo nie liczą się drugi raz
            else:
                QMessageBox.information(self, "Nie rozpoznano mowy",
                                        "W nagraniu nie rozpoznano mowy. Sprawdź, czy wybrano właściwe źródło dźwięku – "
                                        "pasek poziomu powinien się ruszać, gdy prowadzący mówi.")

    # ------------------------------------------------------------------ nawigacja do notatki / kontynuacja
    def open_lecture_at(self, folder: str, anchor: str = ""):
        lec = next((l for l in list_lectures(self.settings.library_path()) if str(l.folder) == folder), None)
        if not lec:
            return
        self._select_key(("library", None))
        self.library.select(lec)
        if anchor:
            self.library._jump_to_notes(anchor)

    def _new_from_files(self):
        if self.record.is_recording():
            QMessageBox.information(self, "Trwa nagrywanie", "Najpierw zakończ bieżące nagrywanie.")
            return
        self.record.open_files_mode()
        self._select_key(("record", None))

    def _import_files(self, lecture, audio: list, photos: list, straighten: bool, rois: dict | None = None):
        from .. import jobs
        s = self.settings

        def fn(prog, cancel, tok):
            jobs.import_files(lecture, audio, photos, s, prog, cancel, straighten, rois=rois)
            if s.auto_generate_notes and not cancel.is_set():
                jobs.generate_notes(lecture, s, prog, cancel, tok, use_cache=True)
        self.rebuild_nav()
        self._select_key(("library", None))
        if self.library._run("Nowa notatka z plików", fn, lecture):
            self.library.select(lecture)

    def _continue_lecture(self, lecture):
        if self.record.is_recording():
            QMessageBox.information(self, "Trwa nagrywanie", "Najpierw zakończ bieżące nagrywanie.")
            return
        if self.runner.busy and self.runner.lecture and str(self.runner.lecture.folder) == str(lecture.folder):
            QMessageBox.information(self, "Trwa zadanie", "Poczekaj, aż skończy się przetwarzanie tego wykładu.")
            return
        self.record.prepare_continue(lecture)
        self._select_key(("record", None))

    # ------------------------------------------------------------------ odzyskiwanie po awarii
    def _recover(self):
        from ..recovery import find_and_repair
        from .widgets import run_async
        lib = self.settings.library_path()
        run_async(lambda: find_and_repair(lib), self._recovered)

    def _recovered(self, items):
        if not items:
            return
        self.library.refresh()
        self.rebuild_nav()
        for r in items:
            lec = r.lecture
            if r.kind == "processing":
                msg = (f"Generowanie notatek dla „{lec.meta.title}” zostało przerwane (aplikacja się zamknęła).\n\n"
                       "Wygenerować notatki teraz?")
            elif not r.ok:
                QMessageBox.warning(self, "Przerwane nagranie",
                                    f"Nagranie „{lec.meta.title}” zostało przerwane i nie udało się go w pełni "
                                    f"odczytać.\n\n{r.message}")
                continue
            else:
                msg = (f"Aplikacja została zamknięta w trakcie nagrywania „{lec.meta.title}”.\n\n"
                       f"Nagranie ({fmt_time(r.duration)}) zostało uratowane. "
                       + ("Dokończyć transkrypcję i zrobić notatki?" if r.needs_transcription else
                          "Zrobić teraz notatki?"))
            if QMessageBox.question(self, "Odzyskane nagranie", msg) == QMessageBox.StandardButton.Yes:
                self._select_key(("library", None))
                self.library.select(lec)
                if r.kind == "recording" and r.needs_transcription:
                    self.library.retranscribe(lec, then_notes=True)
                else:
                    self.library.generate_notes(lec, use_cache=True)
                break          # kolejne zadania można uruchomić później z biblioteki

    def _exam_lecture(self, lecture):
        self._select_key(("exam", None), silent=True)
        self.pages.setCurrentWidget(self.exam_tab)
        self.exam_tab.preselect(str(lecture.folder))

    def _study_lecture(self, lecture):
        self._select_key(("study", None), silent=True)
        self.pages.setCurrentWidget(self.study)
        self.study.set_scope_lecture(lecture)

    def _settings_saved(self):
        if not self.record.is_recording():
            self.record.live_notes_cb.setChecked(self.settings.live_notes)
        if self.settings.library_dir != self._lib_dir:
            self._lib_dir = self.settings.library_dir
            self.rebuild_nav()
            self.library.refresh()
            self.record.refresh_subjects()

    # ------------------------------------------------------------------ zadania w tle
    def _job_started(self, name, lecture):
        import time as _t
        self._job_t0 = _t.monotonic()
        self._job_name = name
        self._job_lecture = lecture
        self.job_title.setText(name)
        self.job_msg.setText(lecture.meta.title if lecture else "")
        self.job_eta.setText("")
        self.job_card.setToolTip(name + (f" – {lecture.meta.title}" if lecture else ""))
        self.job_bar.setRange(0, 0)
        self.job_card.show()

    def _job_progress(self, msg: str, frac: float):
        import time as _t
        lec = self.runner.lecture or getattr(self, "_job_lecture", None)
        self.job_title.setText(msg or self._job_name)
        self.job_msg.setText(lec.meta.title if lec else "")
        self.job_card.setToolTip(f"{self._job_name}\n{msg}")
        if frac < 0:
            self.job_bar.setRange(0, 0)
            self.job_eta.setText("")
        else:
            self.job_bar.setRange(0, 1000)
            self.job_bar.setValue(int(frac * 1000))
            el = _t.monotonic() - self._job_t0
            if frac >= 0.04 and el > 8:
                left = el * (1 - frac) / frac
                self.job_eta.setText(f"{int(frac * 100)}% · zostało ok. {_fmt_left(left)}")
            else:
                self.job_eta.setText(f"{int(frac * 100)}%")

    def _job_finished(self, ok, msg, lecture):
        self.job_card.hide()
        self.rebuild_nav()

    def _show_job_lecture(self):
        if self.runner.lecture:
            self._select_key(("library", None))
            self.library.select(self.runner.lecture)

    # ------------------------------------------------------------------ aktualizacje
    def _busy_reason(self) -> str:
        if self.record.is_recording():
            return "Trwa nagrywanie – zaktualizuj po jego zakończeniu."
        if self.runner.busy:
            return f"Trwa: {self.runner.name}. Zaktualizuj, gdy się skończy."
        return ""

    def _update_badge(self, ver: str):
        it = self.nav_bottom.item(0)
        it.setData(COUNT, "nowa wersja")
        it.setData(ALERT, True)
        it.setToolTip(f"Ustawienia – dostępna wersja {ver}")
        self.nav_bottom.viewport().update()

    def _restart_after_update(self):
        from .. import updater
        self._save_window_geometry()
        updater.restart()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ------------------------------------------------------------------ okno: rozmiar, pokazanie
    def restore_window_geometry(self):
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QGuiApplication
        g = self.settings.window_geometry
        if g:
            try:
                if self.restoreGeometry(QByteArray.fromHex(g.encode("ascii"))):
                    return
            except Exception:  # noqa: BLE001
                pass
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        av = scr.availableGeometry()
        w, h = min(av.width(), max(900, int(av.width() * 0.8))), min(av.height(), max(640, int(av.height() * 0.85)))
        self.resize(w, h)
        self.move(av.left() + (av.width() - w) // 2, av.top() + (av.height() - h) // 2)
        if av.width() < 1280 or av.height() < 760:
            self.settings.window_maximized = True

    def prepare_layout(self):
        """Układ (pasek boczny, kolumny) ustalony przed pierwszym pokazaniem okna."""
        self._relayout()

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _save_window_geometry(self):
        try:
            self.settings.window_maximized = self.isMaximized()
            self.settings.window_geometry = bytes(self.saveGeometry().toHex()).decode("ascii")
            self.settings.save()
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, e):
        if self.record.is_recording():
            if QMessageBox.question(self, "Trwa nagrywanie",
                                    "Zakończyć nagrywanie i zamknąć aplikację? Nagranie zostanie zapisane.") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.record.stop_blocking()
        if self.runner.busy:
            if QMessageBox.question(self, "Trwa zadanie", f"Trwa: {self.runner.name}. Przerwać i zamknąć?") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.runner.cancel.set()
        self._save_window_geometry()
        e.accept()
