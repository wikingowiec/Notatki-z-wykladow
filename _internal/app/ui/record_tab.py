"""Ekran „Nagrywanie”: przygotowanie (źródła) → nagrywanie na żywo (transkrypcja + slajdy)."""
from __future__ import annotations

import html
import logging
import shutil
import threading

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..audio_capture import list_audio_sources
from ..screen_capture import VideoSourceInfo, list_monitors, list_windows, make_grabber
from ..session import RecordingSession
from ..storage import Lecture, fmt_time, list_lectures
from .ask_panel import AskPanel
from .reader import Reader
from .controls import (show_if, ModeCard, SegmentedControl, GroupSection, LevelMeter, PulseDot, RecordButton, ToggleSwitch, hbox, icon_button, label,
                       rounded_pixmap, set_icon)
from .theme import T, qcolor, theme
from .widgets import RoiDialog, bgr_to_qpixmap, run_async

log = logging.getLogger(__name__)


class _Host(QWidget):
    """Tło przewijanej strony: marginesy maleją w wąskim oknie."""

    def __init__(self, inner: QWidget):
        super().__init__()
        self.setObjectName("content")
        self.lay = QHBoxLayout(self)
        self.lay.addStretch()
        self.lay.addWidget(inner, 10)
        self.lay.addStretch()
        self._m = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = (16, 18) if self.width() < 640 else (36, 30)
        if m != self._m:
            self._m = m
            self.lay.setContentsMargins(m[0], m[1], m[0], m[1] + 8)


def _centered(inner: QWidget, max_w: int = 700) -> QScrollArea:
    """Kolumna o maks. szerokości wyśrodkowana w przewijanym obszarze."""
    inner.setMaximumWidth(max_w)
    inner.setMinimumWidth(280)
    host = _Host(inner)
    sc = QScrollArea()
    sc.setObjectName("page")
    sc.setWidgetResizable(True)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sc.setWidget(host)
    return sc


PL_DAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
PL_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
             "października", "listopada", "grudnia"]


def today_line() -> str:
    import datetime as _dt
    d = _dt.date.today()
    return f"{PL_DAYS[d.weekday()]}, {d.day} {PL_MONTHS[d.month - 1]}"


def greeting() -> str:
    import datetime as _dt
    h = _dt.datetime.now().hour
    if 5 <= h < 12:
        return "Dzień dobry! Co dziś notujemy?"
    if 12 <= h < 18:
        return "Miłego popołudnia! Co dziś notujemy?"
    return "Dobry wieczór! Co dziś notujemy?"


class RecordTab(QWidget):
    segments_signal = Signal(list)
    slide_signal = Signal(int, bool, str, float, bool)
    status_signal = Signal(str)
    video_status_signal = Signal(str)
    stopped_signal = Signal(object, bool)
    files_requested = Signal(object, list, list, bool)   # wykład, nagrania, zdjęcia, prostowanie
    notes_update_signal = Signal()
    notes_status_signal = Signal(str)
    recording_finished = Signal(object, bool)      # do MainWindow
    recording_state = Signal(bool)                 # do paska bocznego

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.session: RecordingSession | None = None
        self.rois: dict[str, tuple] = {}
        self._audio_sources = []
        self._video_sources = []
        self._preview_img: np.ndarray | None = None

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_live())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self._ticks = 0

        self.segments_signal.connect(self._on_segments)
        self.slide_signal.connect(self._on_slide)
        self.status_signal.connect(self._set_status)
        self.video_status_signal.connect(self._on_video_status)
        self.stopped_signal.connect(self._on_stopped)
        self.notes_update_signal.connect(self._on_notes_update)
        self.notes_status_signal.connect(self.live_notes_status.setText)
        theme().changed.connect(self._render_preview)

        self._prev_timer = QTimer(self)
        self._prev_timer.setSingleShot(True)
        self._prev_timer.setInterval(120)
        self._prev_timer.timeout.connect(self._render_preview)
        self.refresh_subjects()
        QTimer.singleShot(150, self.refresh_audio)
        QTimer.singleShot(200, self.refresh_video)

    # ------------------------------------------------------------------ widok: przygotowanie
    def _build_setup(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(22)

        from .controls import Heading
        self.heading = Heading("Nowa notatka", greeting() + " Wybierz rodzaj notatki – transkrypcja, notatki i "
                               "fiszki zrobią się same.", today_line())
        self.setup_title = self.heading.title
        v.addWidget(self.heading)

        from PySide6.QtWidgets import QGridLayout
        from ..ui.theme import MODE_COLOR
        self.modes = {
            "av": ModeCard("screen-audio", "Dźwięk + slajdy", "Nagrywa dźwięk wykładu i łapie slajdy z ekranu.",
                           MODE_COLOR["av"]),
            "audio": ModeCard("mic", "Tylko dźwięk", "Nagranie z aplikacji albo mikrofonu – notatki z tego, co mówi "
                              "prowadzący.", MODE_COLOR["audio"]),
            "slides": ModeCard("display", "Tylko slajdy", "Zrzuty slajdów z ekranu – notatki z treści slajdów.",
                               MODE_COLOR["slides"]),
            "files": ModeCard("import", "Z pliku", "Nagranie z Dyktafonu (m4a), mp3 lub wideo + zdjęcia slajdów.",
                              MODE_COLOR["files"]),
        }
        peers = list(self.modes.values())
        for c in peers:
            c.peers = peers
        self.mode_grid = QGridLayout()
        self.mode_grid.setSpacing(8)
        self._mode_cols = 0
        for key, card in self.modes.items():
            card.toggled.connect(lambda on, m=key: on and self.set_mode(m))
        v.addLayout(self.mode_grid)
        self.mode = "av"
        # baner kontynuacji (kolejna część tego samego wykładu)
        self.continue_lecture: Lecture | None = None
        self.cont_banner = QFrame()
        self.cont_banner.setObjectName("banner")
        cb = QHBoxLayout(self.cont_banner)
        cb.setContentsMargins(14, 10, 10, 10)
        self.cont_text = label("", "", wrap=True)
        btn_cc = QPushButton("Nowa notatka zamiast tego")
        btn_cc.setObjectName("plain")
        btn_cc.clicked.connect(self.cancel_continue)
        cb.addWidget(self.cont_text, 1)
        cb.addWidget(btn_cc)
        self.cont_banner.hide()
        v.addWidget(self.cont_banner)

        # Wykład
        self.title = QLineEdit()
        self.title.setPlaceholderText("np. Analiza matematyczna – wykład 3")
        self.title.setMinimumWidth(300)
        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.lineEdit().setPlaceholderText("np. Analiza matematyczna")
        self.subject.setMinimumWidth(300)
        g1 = GroupSection("Wykład", "Pusty tytuł = data i godzina. Przedmiot grupuje wykłady w bibliotece.")
        g1.add_row("Tytuł", self.title)
        g1.add_row("Przedmiot", self.subject)
        self.g_lecture = g1

        # Źródła
        self.audio_combo = QComboBox()
        self.audio_combo.setMinimumWidth(200)
        self.audio_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.audio_combo.setMinimumContentsLength(30)
        self.btn_refresh_audio = icon_button("refresh", "Odśwież listę aplikacji")
        self.btn_refresh_audio.clicked.connect(self.refresh_audio)
        self.video_combo = QComboBox()
        self.video_combo.setMinimumWidth(200)
        self.video_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.video_combo.setMinimumContentsLength(30)
        self.btn_refresh_video = icon_button("refresh", "Odśwież listę ekranów i okien")
        self.btn_refresh_video.clicked.connect(self.refresh_video)
        self.video_combo.currentIndexChanged.connect(self._video_changed)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.btn_roi = QPushButton("Zaznacz obszar slajdu…")
        set_icon(self.btn_roi, "crop", "text2", 16)
        self.btn_roi.clicked.connect(self.pick_roi)
        self.btn_roi_clear = QPushButton("Cały obraz")
        self.btn_roi_clear.setObjectName("plain")
        self.btn_roi_clear.clicked.connect(self._clear_roi)
        self.roi_label = label("", "footnote", wrap=True)
        prev_box = QWidget()
        pv = QVBoxLayout(prev_box)
        pv.setContentsMargins(14, 10, 14, 12)
        pv.setSpacing(8)
        pv.addWidget(self.preview)
        pv.addWidget(hbox(self.btn_roi, self.btn_roi_clear, "stretch"))
        pv.addWidget(self.roi_label)
        self.preview_box = prev_box

        self.g_audio = GroupSection("Dźwięk", "Dźwięk nagrywa się tylko z wybranej aplikacji – inne programy (np. muzyka "
                                              "w tle) nie trafią do nagrania. Aplikacja z wykładem pojawi się na górze "
                                              "listy, gdy zacznie grać. Na zajęciach stacjonarnych wybierz mikrofon.")
        self.g_audio.add_row("Źródło dźwięku", hbox(self.audio_combo, self.btn_refresh_audio, spacing=4))
        self.g_slides = GroupSection("Slajdy")
        self.g_slides.add_row("Ekran lub okno", hbox(self.video_combo, self.btn_refresh_video, spacing=4))
        self.g_slides.add(prev_box)
        self._build_files()

        # Opcje
        self.live_cb = ToggleSwitch(True)
        g3 = GroupSection("Opcje")
        self.lang_combo = QComboBox()
        for code, name in [("auto", "Wykryj automatycznie"), ("pl", "Polski"), ("en", "Angielski"),
                           ("de", "Niemiecki"), ("es", "Hiszpański"), ("fr", "Francuski")]:
            self.lang_combo.addItem(name, code)
        i = self.lang_combo.findData(self.settings.language)
        self.lang_combo.setCurrentIndex(max(0, i))
        g3.add_row("Język wykładu", self.lang_combo, "Notatki powstaną w tym języku.")
        self.row_live = g3.add_row("Transkrypcja na żywo", self.live_cb,
                   "Tekst pojawia się w trakcie wykładu. Wyłącz, by odciążyć kartę graficzną – transkrypcja zrobi się po zakończeniu.")
        self.live_notes_cb = ToggleSwitch(self.settings.live_notes)
        self.row_live_notes = g3.add_row("Notatki i pytania na żywo", self.live_notes_cb,
                   "AI pisze notatki z każdego zakończonego fragmentu (po zmianie slajdu albo co kilka minut), "
                   "a Ty możesz zadawać pytania w trakcie wykładu. Mocniej obciąża kartę graficzną.")
        self.live_cb.toggled.connect(self.live_notes_cb.setEnabled)
        self.g_opts = g3

        # dwie kolumny na szerokim ekranie, jedna na zwykłym i wąskim
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(26)
        lw_, rw_ = QWidget(), QWidget()
        self.col_left = QVBoxLayout(lw_)
        self.col_right = QVBoxLayout(rw_)
        for c in (self.col_left, self.col_right):
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(24)
        self.col_right_w = rw_
        bl.addWidget(lw_, 1)
        bl.addWidget(rw_, 1)
        v.addWidget(body)
        v.addStretch()
        self.setup_col = col
        self._two_cols = None
        self._arrange(False)
        scroll = _centered(col, 780)

        # stały pasek na dole – przycisk nagrywania zawsze widoczny
        self.btn_start = RecordButton(62)
        self.btn_start.setToolTip("Rozpocznij nagrywanie")
        self.btn_start.clicked.connect(self.start)
        footer = QFrame()
        footer.setObjectName("footerBar")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 10, 20, 10)
        fl.setSpacing(16)
        cap = QVBoxLayout()
        cap.setSpacing(2)
        self.start_caption = label("Rozpocznij nagrywanie", "headline")
        cap.addWidget(self.start_caption)
        self.setup_status = label("Nagrywanie możesz zakończyć w dowolnym momencie.", "footnote", wrap=True)
        self.setup_status.setMaximumWidth(420)
        cap.addWidget(self.setup_status)
        self.btn_create = QPushButton("Utwórz notatkę")
        self.btn_create.setObjectName("big")
        self.btn_create.setMinimumSize(220, 44)
        set_icon(self.btn_create, "sparkles", "on_accent", 17)
        self.btn_create.clicked.connect(self.create_from_files)
        fl.addStretch()
        fl.addWidget(self.btn_start)
        fl.addWidget(self.btn_create)
        fl.addLayout(cap)
        fl.addStretch()
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(scroll, 1)
        pl.addWidget(footer)
        self.modes["av"].setChecked(True)
        self.set_mode("av")
        return page

    # ------------------------------------------------------------------ układ zależny od szerokości
    def _arrange(self, two: bool):
        """Szeroki ekran: Wykład + Opcje po lewej, źródła po prawej. Inaczej jedna kolumna."""
        if two == self._two_cols:
            return
        self._two_cols = two
        for lay in (self.col_left, self.col_right):
            while lay.count():
                lay.takeAt(0)
        left = [self.g_lecture, self.g_opts] if two else \
            [self.g_lecture, self.g_audio, self.g_slides, self.files_box, self.g_opts]
        right = [self.g_audio, self.g_slides, self.files_box] if two else []
        for w_ in left:
            self.col_left.addWidget(w_)
        self.col_left.addStretch()
        for w_ in right:
            self.col_right.addWidget(w_)
        self.col_right.addStretch()
        self.col_right_w.setVisible(two)

    def _layout_modes(self, cols: int):
        if cols == self._mode_cols:
            return
        self._mode_cols = cols
        for c in self.modes.values():
            self.mode_grid.removeWidget(c)
        for k, c in enumerate(self.modes.values()):
            self.mode_grid.addWidget(c, k // cols, k % cols)
            c.set_vertical(cols == 4)
        for i in range(4):
            self.mode_grid.setColumnStretch(i, 1 if i < cols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        wide = w >= 1320
        self.setup_col.setMaximumWidth(1280 if wide else 780)
        self._arrange(wide)
        avail = min(w - 72, 1280 if wide else 780)
        self._layout_modes(4 if avail >= 1000 else (2 if avail >= 470 else 1))
        self._relayout_live()
        if hasattr(self, "_prev_timer"):
            self._prev_timer.start()

    # ------------------------------------------------------------------ notatka z plików
    def _build_files(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(24)
        # nagrania
        self.audio_files = QListWidget()
        self.audio_files.setMaximumHeight(110)
        self.audio_files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        b_add_a = QPushButton("Dodaj nagranie…")
        set_icon(b_add_a, "plus", "text2", 14)
        b_add_a.clicked.connect(self._pick_audio)
        b_del_a = QPushButton("Usuń")
        b_del_a.setObjectName("plain")
        b_del_a.clicked.connect(lambda: [self.audio_files.takeItem(self.audio_files.row(i))
                                         for i in self.audio_files.selectedItems()])
        ga = GroupSection("Nagranie", "Dyktafon z iPhone'a (.m4a), mp3, wav albo wideo (mp4, mov). Kilka plików = kolejne "
                                      "części jednego wykładu (w podanej kolejności). Pliki możesz też przeciągnąć tutaj.")
        wa = QWidget()
        la = QVBoxLayout(wa)
        la.setContentsMargins(12, 10, 12, 10)
        la.addWidget(self.audio_files)
        la.addWidget(hbox(b_add_a, b_del_a, "stretch"))
        ga.add(wa)
        # zdjęcia slajdów
        self.photo_files = QListWidget()
        self.photo_files.setObjectName("thumbs")
        self.photo_files.setViewMode(QListWidget.ViewMode.IconMode)
        self.photo_files.setIconSize(QSize(128, 96))
        self.photo_files.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.photo_files.setMovement(QListWidget.Movement.Static)
        self.photo_files.setSpacing(6)
        self.photo_files.setMinimumHeight(130)
        self.photo_files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        b_add_p = QPushButton("Dodaj zdjęcia…")
        set_icon(b_add_p, "photos", "text2", 14)
        b_add_p.clicked.connect(self._pick_photos)
        b_del_p = QPushButton("Usuń")
        b_del_p.setObjectName("plain")
        b_del_p.clicked.connect(lambda: [self.photo_files.takeItem(self.photo_files.row(i))
                                         for i in self.photo_files.selectedItems()])
        self.straighten_cb = ToggleSwitch(True)
        gp = GroupSection("Zdjęcia slajdów (opcjonalnie)",
                          "Zdjęcia z telefonu (JPG, HEIC, PNG). Każde zostanie dopasowane do miejsca w nagraniu – po "
                          "godzinie zrobienia zdjęcia, a gdy się nie da, po treści slajdu. Bez nagrania notatka powstanie "
                          "z samych zdjęć.")
        wp = QWidget()
        lp = QVBoxLayout(wp)
        lp.setContentsMargins(12, 10, 12, 10)
        lp.addWidget(self.photo_files)
        lp.addWidget(hbox(b_add_p, b_del_p, "stretch"))
        gp.add(wp)
        gp.add_row("Wyprostuj zdjęcia", self.straighten_cb, "Wykrywa slajd na zdjęciu i prostuje perspektywę.")
        v.addWidget(ga)
        v.addWidget(gp)
        self.files_box = box
        self.setAcceptDrops(True)
        return box

    def _pick_audio(self):
        from pathlib import Path as _P
        from ..jobs import AUDIO_EXT
        pat = " ".join(f"*{e}" for e in AUDIO_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, "Wybierz nagranie", str(_P.home()),
                                                f"Nagrania ({pat});;Wszystkie pliki (*.*)")
        self._add_audio(paths)

    def _add_audio(self, paths):
        from pathlib import Path as _P
        existing = {self.audio_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.audio_files.count())}
        for p in paths:
            if p in existing:
                continue
            it = QListWidgetItem(_P(p).name)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.audio_files.addItem(it)

    def _pick_photos(self):
        from pathlib import Path as _P
        from ..photos import PHOTO_EXT
        pat = " ".join(f"*{e}" for e in PHOTO_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, "Wybierz zdjęcia slajdów", str(_P.home()),
                                                f"Zdjęcia ({pat});;Wszystkie pliki (*.*)")
        self._add_photos(paths)

    def _add_photos(self, paths):
        from pathlib import Path as _P
        existing = {self.photo_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.photo_files.count())}
        new = [p for p in paths if p not in existing]
        items = []
        for p in new:
            it = QListWidgetItem(_P(p).name)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.photo_files.addItem(it)
            items.append(it)
        if not new:
            return

        def work():      # miniatury w tle (HEIC/duże zdjęcia wczytują się chwilę)
            from ..photos import load_photo
            from PySide6.QtGui import QImage
            out = []
            for p in new:
                img, _t = load_photo(_P(p))
                if img is None:
                    out.append(QImage())
                    continue
                import cv2
                h, w = img.shape[:2]
                s_ = 240 / max(h, w)
                small = cv2.cvtColor(cv2.resize(img, (int(w * s_), int(h * s_))), cv2.COLOR_BGR2RGB).copy()
                out.append(QImage(small.data, small.shape[1], small.shape[0], small.strides[0],
                                  QImage.Format.Format_RGB888).copy())
            return out

        def done(imgs):
            for it, img in zip(items, imgs):
                try:
                    if not img.isNull():
                        it.setIcon(QIcon(QPixmap.fromImage(img)))
                except RuntimeError:
                    pass
        run_async(work, done)

    def dragEnterEvent(self, e):
        if self.session is None and e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        from pathlib import Path as _P
        from ..jobs import AUDIO_EXT
        from ..photos import PHOTO_EXT
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        audio = [p for p in paths if _P(p).suffix.lower() in AUDIO_EXT]
        photos = [p for p in paths if _P(p).suffix.lower() in PHOTO_EXT]
        if audio or photos:
            self.modes["files"].setChecked(True)
            self._add_audio(audio)
            self._add_photos(photos)

    def set_mode(self, mode: str):
        """Dopasowuje formularz do rodzaju notatki."""
        self.mode = mode
        rec = mode in ("av", "audio", "slides")
        self.g_audio.setVisible(mode in ("av", "audio"))
        self.g_slides.setVisible(mode in ("av", "slides"))
        self.files_box.setVisible(mode == "files")
        self.row_live.setVisible(mode in ("av", "audio"))
        self.row_live_notes.setVisible(mode in ("av", "audio"))
        self.btn_start.setVisible(rec)
        self.btn_create.setVisible(not rec)
        self.start_caption.setVisible(rec)
        self.start_caption.setText("Rozpocznij zrzuty slajdów" if mode == "slides" else "Rozpocznij nagrywanie")
        self.setup_status.setText({
            "av": "Nagrywanie możesz zakończyć w dowolnym momencie.",
            "audio": "Nagrywanie możesz zakończyć w dowolnym momencie.",
            "slides": "Notatka powstanie z tekstu na slajdach (bez dźwięku).",
            "files": "Transkrypcja i notatki zrobią się w tle – postęp zobaczysz w bibliotece.",
        }[mode])
        if mode in ("av", "slides") and self._preview_img is None:
            QTimer.singleShot(50, self._video_changed)

    def create_from_files(self):
        audio = [self.audio_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.audio_files.count())]
        photos = [self.photo_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.photo_files.count())]
        if not audio and not photos:
            QMessageBox.information(self, "Nowa notatka", "Dodaj nagranie albo zdjęcia slajdów.")
            return
        subject = self.subject.currentText().strip()
        self.settings.last_subject = subject
        self.settings.save()
        if self.continue_lecture is not None:
            lecture = self.continue_lecture
        else:
            lecture = Lecture.create(self.settings.library_path(), self.title.text(), subject)
            lecture.meta.kind = "files"
            lang = self.lang_combo.currentData()
            if lang not in ("", "auto"):
                lecture.meta.language = lang
            lecture.save_meta()
        self.files_requested.emit(lecture, audio, photos, self.straighten_cb.isChecked())
        self.audio_files.clear()
        self.photo_files.clear()
        self.title.clear()
        self.cancel_continue()

    # ------------------------------------------------------------------ widok: nagrywanie
    def _build_live(self) -> QWidget:
        w = QWidget()
        w.setObjectName("content")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 18, 24, 18)
        v.setSpacing(10)
        self.live_v = v

        # --- pasek nagrywania: [● NAGRYWANIE / tytuł] [zaznaczanie, poziom] [czas] [stop] ---
        frame = QFrame()
        frame.setObjectName("recBar")
        fv = QVBoxLayout(frame)
        fv.setContentsMargins(20, 12, 14, 12)
        fv.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(16)
        self.dot = PulseDot("red")
        info = QVBoxLayout()
        info.setSpacing(1)
        self.rec_label = label("NAGRYWANIE", "recLabel")
        self.live_title = label("", "title3")
        self.live_sub = label("", "footnote")
        self.live_sub.setMinimumWidth(80)
        rl_ = QHBoxLayout()
        rl_.setSpacing(6)
        rl_.addWidget(self.dot)
        rl_.addWidget(self.rec_label)
        rl_.addStretch()
        info.addLayout(rl_)
        info.addWidget(self.live_title)
        info.addWidget(self.live_sub)
        self.meter = LevelMeter(32)
        self.meter.setToolTip("Poziom dźwięku – powinien się ruszać, gdy prowadzący mówi")
        self.time_label = label("00:00", "timer")
        self.btn_stop = RecordButton(58)
        self.btn_stop.set_recording(True)
        self.btn_stop.setToolTip("Zakończ nagrywanie")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_mark = QPushButton("Zaznacz")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setToolTip("Zaznacz ważny fragment: kliknij, gdy się zaczyna (zaznaczenie obejmie też "
                                 "ostatnie ~20 s), i kliknij ponownie, gdy się kończy.")
        set_icon(self.btn_mark, "highlighter", "accent", 16)
        self.btn_mark.toggled.connect(self._toggle_mark)
        self.mark_kind = QComboBox()
        from ..storage import MARK_KINDS
        for k, name in MARK_KINDS.items():
            self.mark_kind.addItem(name, k)
        self.mark_kind.setToolTip("Rodzaj zaznaczenia")
        self.tools = QWidget()
        tl = QHBoxLayout(self.tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tl.addWidget(self.mark_kind)
        tl.addWidget(self.btn_mark)
        tl.addSpacing(8)
        tl.addWidget(self.meter, 1)
        top.addLayout(info, 1)
        self.top_tools_slot = QHBoxLayout()
        top.addLayout(self.top_tools_slot)
        top.addWidget(self.time_label)
        top.addWidget(self.btn_stop)
        fv.addLayout(top)
        self.bottom_tools_slot = QHBoxLayout()
        fv.addLayout(self.bottom_tools_slot)
        self.rec_frame = frame
        frame.installEventFilter(self)
        v.addWidget(frame)

        self.autostop = QFrame()
        self.autostop.setObjectName("warnBanner")
        ab = QHBoxLayout(self.autostop)
        ab.setContentsMargins(16, 10, 12, 10)
        self.autostop_text = label("", "headline", wrap=True)
        b_keep = QPushButton("Nagrywaj dalej")
        b_keep.setObjectName("primary")
        b_keep.clicked.connect(self._autostop_cancel)
        b_now = QPushButton("Zakończ teraz")
        b_now.clicked.connect(lambda: (self.autostop.hide(), self.stop()))
        ab.addWidget(self.autostop_text, 1)
        ab.addWidget(b_now)
        ab.addWidget(b_keep)
        self.autostop.hide()
        v.addWidget(self.autostop)

        self.status = label("", "secondary", wrap=True)
        self.video_status = label("", "footnote", wrap=True)
        sv_ = QVBoxLayout()
        sv_.setContentsMargins(6, 0, 6, 0)
        sv_.setSpacing(2)
        sv_.addWidget(self.status)
        sv_.addWidget(self.video_status)
        v.addLayout(sv_)

        self.transcript = Reader(max_width=720, pad=22)
        from .slide_views import SlideTextPanel, SlideThumbs
        self.slides = SlideThumbs(QSize(232, 130), deletable=True)
        self.slides.open_requested.connect(self._preview_slide)
        self.slides.delete_requested.connect(self._delete_slide)
        self.slide_text = SlideTextPanel("Tekst ze slajdów")
        # transkrypcja mowy i tekst slajdów obok siebie
        self.tsplit = QSplitter(Qt.Orientation.Horizontal)
        self.tsplit.setHandleWidth(12)
        self.tsplit.setChildrenCollapsible(False)
        tw_ = QWidget()
        twl = QVBoxLayout(tw_)
        twl.setContentsMargins(0, 0, 0, 0)
        twl.setSpacing(6)
        self.transcript_head = label("Mowa", "headline")
        self.transcript_head.setContentsMargins(2, 0, 0, 0)
        self.transcript_head.setFixedHeight(max(30, self.slide_text.b_copy.sizeHint().height()))
        self.slide_text.head.setFixedHeight(self.transcript_head.height())
        twl.addWidget(self.transcript_head)
        twl.addWidget(self.transcript, 1)
        self.tsplit.addWidget(tw_)
        self.tsplit.addWidget(self.slide_text)
        self.tsplit.setSizes([600, 400])

        # notatki na żywo i pytania
        self.live_notes_view = Reader(max_width=760, pad=26)
        self.live_notes_view.internal_link.connect(lambda a: None)
        self.live_notes_status = label("", "footnote", wrap=True)
        nw = QWidget()
        nl = QVBoxLayout(nw)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)
        nl.addWidget(self.live_notes_view, 1)
        nl.addWidget(self.live_notes_status)
        self.live_ask = AskPanel(self.settings, live=True)
        self.live_ask.internal_link.connect(self._live_jump)
        self.tpage = QWidget()                  # strona „Transkrypcja” (na szerokim ekranie osobna kolumna)
        self.tpage_lay = QVBoxLayout(self.tpage)
        self.tpage_lay.setContentsMargins(0, 0, 0, 0)
        self.tpage_lay.addWidget(self.tsplit)
        self.live_pages = QStackedWidget()
        self.live_pages.addWidget(self.tpage)
        self.live_pages.addWidget(nw)
        self.live_pages.addWidget(self.live_ask)
        self.live_seg = SegmentedControl(["Transkrypcja", "Notatki", "Zapytaj"], style="tabs")
        self.live_seg.changed.connect(self.live_pages.setCurrentIndex)
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addWidget(self.live_seg)
        ll.addWidget(self.live_pages, 1)
        # osobna kolumna transkrypcji (szeroki ekran)
        self.tcol = QWidget()
        tcl = QVBoxLayout(self.tcol)
        tcl.setContentsMargins(0, 0, 0, 0)
        tcl.setSpacing(10)
        th = label("Transkrypcja", "headline")
        th.setContentsMargins(2, 9, 0, 10)
        tcl.addWidget(th)
        self.tcol_lay = QVBoxLayout()
        tcl.addLayout(self.tcol_lay, 1)
        self.tcol.hide()
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.slides_title = label("SLAJDY · 0", "sectionHeader")
        self.slides_title.setContentsMargins(4, 12, 0, 8)
        rl.addWidget(self.slides_title)
        rl.addWidget(self.slides, 1)
        self.slides_col = rw
        split = QSplitter()
        split.setHandleWidth(16)
        split.setChildrenCollapsible(False)
        split.addWidget(self.tcol)
        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 3)
        self.live_split = split
        self._live_mode = None
        v.addWidget(split, 1)
        return w

    def _relayout_live(self):
        """Szeroki (21:9): transkrypcja | notatki/pytania | slajdy.  Zwykły: zakładki | slajdy.
        Wąski / pionowy (9:16): zakładki na górze, pasek slajdów pod spodem."""
        if not hasattr(self, "live_split"):
            return
        w, h = self.width(), self.height()
        mode = "wide" if w >= 1500 else ("narrow" if (w < 900 or h > w * 1.1) else "regular")
        if mode != self._live_mode:
            self._live_mode = mode
            wide, narrow = mode == "wide", mode == "narrow"
            # transkrypcja: własna kolumna albo zakładka
            (self.tcol_lay if wide else self.tpage_lay).addWidget(self.tsplit)
            self.tsplit.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
            self.tcol.setVisible(wide)
            self.live_seg.buttons[0].setVisible(not wide)
            if wide and self.live_seg.current() == 0:
                on = self.live_seg.buttons[1].isEnabled()
                self.live_seg.set_current(1 if on else 2, emit=True)
            self.live_split.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
            if narrow:
                self.slides.setFlow(QListWidget.Flow.LeftToRight)
                self.slides.setWrapping(False)
                self.slides.set_thumb_size(QSize(200, 113))
                self.slides_col.setMaximumHeight(200)
                self.slides_col.setMinimumHeight(170)
                self.live_split.setSizes([900, 190])
            else:
                self.slides.setFlow(QListWidget.Flow.LeftToRight)
                self.slides.setWrapping(True)
                self.slides.set_thumb_size(QSize(232, 130))
                self.slides_col.setMaximumHeight(16777215)
                self.slides_col.setMinimumHeight(0)
                self.live_split.setSizes([520, 640, 300] if wide else [0, 700, 320])
        self._place_tools()

    def _place_tools(self):
        """Pasek nagrywania: narzędzia w jednym rzędzie albo (wąsko) w drugim rzędzie pod spodem."""
        fw = self.rec_frame.width()
        compact = fw < 900
        if getattr(self, "_tools_compact", None) != compact:
            self._tools_compact = compact
            (self.bottom_tools_slot if compact else self.top_tools_slot).addWidget(self.tools)
            self.meter.setMinimumWidth(120 if compact else 150)
            self.meter.setMaximumWidth(16777215 if compact else 240)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "rec_frame", None) and ev.type() == QEvent.Type.Resize:
            self._place_tools()
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------ źródła
    def refresh_subjects(self):
        subs = sorted({l.meta.subject for l in list_lectures(self.settings.library_path()) if l.meta.subject})
        cur = self.subject.currentText() or self.settings.last_subject
        self.subject.clear()
        from .controls import C_COLOR, C_TAG
        from .theme import subject_color
        for k, s_ in enumerate(subs):
            self.subject.addItem(s_)
            self.subject.setItemData(k, subject_color(s_), C_COLOR)
            self.subject.setItemData(k, "Przedmiot", C_TAG)
        self.subject.setEditText(cur)

    def refresh_audio(self):
        """Lista źródeł dźwięku jest zbierana w tle (wyliczanie sesji audio Windows potrafi trwać)."""
        self.btn_refresh_audio.setEnabled(False)

        def work():
            try:
                import comtypes
                comtypes.CoInitialize()
            except Exception:
                pass
            return list_audio_sources()

        def fail(_e):
            self.btn_refresh_audio.setEnabled(True)
        run_async(work, self._apply_audio, fail)

    def _apply_audio(self, sources):
        self.btn_refresh_audio.setEnabled(True)
        prev = self.audio_combo.currentText()
        self._audio_sources = sources
        self.audio_combo.clear()
        for s in self._audio_sources:
            self.audio_combo.addItem(s.label.replace("🔊 ", "").replace("🖥 ", "").replace("🎤 ", ""))
        idx = self.audio_combo.findText(prev)
        if idx < 0:
            idx = next((i for i, s in enumerate(self._audio_sources) if s.kind == "process" and s.active), 0)
        self.audio_combo.setCurrentIndex(idx)
        active = sum(1 for s in self._audio_sources if s.active)
        self.setup_status.setText("Nagrywanie możesz zakończyć w dowolnym momencie." if active else
                                  "Żadna aplikacja teraz nie gra – włącz dźwięk wykładu i odśwież listę.")

    def refresh_video(self):
        prev = self.video_combo.currentText()
        self._video_sources = list_monitors() + list_windows()
        self.video_combo.blockSignals(True)
        self.video_combo.clear()
        for s in self._video_sources:
            self.video_combo.addItem(s.label.replace("🖥 ", "").replace("🪟 ", "Okno: "))
        idx = self.video_combo.findText(prev)
        self.video_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.video_combo.blockSignals(False)
        self._video_changed()

    def _video_key(self, info: VideoSourceInfo) -> str:
        return f"monitor:{info.index}" if info.kind == "monitor" else f"window:{info.title}"

    def _current_video(self) -> VideoSourceInfo | None:
        i = self.video_combo.currentIndex()
        return self._video_sources[i] if 0 <= i < len(self._video_sources) else None

    def _video_changed(self, *_):
        info = self._current_video()
        has = bool(info and info.kind != "none")
        self.preview_box.setVisible(has)
        self._preview_img = None
        if has:
            QTimer.singleShot(50, self._grab_preview)

    def _grab_preview(self):
        """Podgląd w tle – przełączanie źródeł nie przycina interfejsu."""
        info = self._current_video()
        if not info or info.kind == "none":
            return
        self._preview_req = getattr(self, "_preview_req", 0) + 1
        req = self._preview_req

        def work():
            g = make_grabber(info)
            try:
                return (g.grab() if g else None), (getattr(g, "last_error", "") if g else "")
            finally:
                if g:
                    g.close()

        def done(res):
            if req != self._preview_req:
                return
            img, err = res
            self._preview_img = img
            if img is None:
                self.roi_label.setText("Nie udało się pobrać podglądu. " + (err or ""))
            self._render_preview()
        run_async(work, done)

    def _grab_now(self):
        info = self._current_video()
        if not info or info.kind == "none":
            return
        g = make_grabber(info)
        img = None
        try:
            img = g.grab() if g else None
        except Exception:
            log.exception("preview")
        finally:
            if g:
                g.close()
        self._preview_img = img
        if img is None:
            self.roi_label.setText("Nie udało się pobrać podglądu. " + (getattr(g, "last_error", "") or ""))
        self._render_preview()

    def _render_preview(self):
        info = self._current_video()
        if self._preview_img is None or not info or info.kind == "none":
            self.preview.clear()
            return
        roi = self.rois.get(self._video_key(info))
        dpr = self.devicePixelRatioF() or 1.0
        pw = self.preview_box.width()
        bw = max(240, min(820, pw - 28)) if pw > 120 else 560
        bh = int(min(bw * 9 / 16, 360))
        pix = bgr_to_qpixmap(self._preview_img).scaled(int(bw * dpr), int(bh * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        if roi:
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            W, H = pix.width() / dpr, pix.height() / dpr
            r = QRectF(roi[0] * W, roi[1] * H, roi[2] * W, roi[3] * H)
            shade = QColor(0, 0, 0, 130)
            p.fillRect(QRectF(0, 0, W, r.top()), shade)
            p.fillRect(QRectF(0, r.bottom(), W, H - r.bottom()), shade)
            p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
            p.fillRect(QRectF(r.right(), r.top(), W - r.right(), r.height()), shade)
            p.setPen(QPen(qcolor(T().accent), 2.5))
            p.drawRoundedRect(r, 4, 4)
            p.end()
        self.preview.setPixmap(rounded_pixmap(pix, 10))
        self.roi_label.setText("Slajdy będą wykrywane tylko w zaznaczonym obszarze." if roi else
                               "Wykrywanie obejmuje cały obraz. Jeśli obok slajdu jest kamerka lub czat, zaznacz sam slajd.")
        show_if(self.btn_roi_clear, roi)

    def pick_roi(self):
        info = self._current_video()
        if not info or info.kind == "none":
            return
        self._grab_now()
        if self._preview_img is None:
            QMessageBox.warning(self, "Podgląd", "Nie udało się zrobić zrzutu tego źródła.")
            return
        key = self._video_key(info)
        dlg = RoiDialog(self._preview_img, self.rois.get(key), self)
        if dlg.exec():
            roi = dlg.result_roi()
            if roi:
                self.rois[key] = roi
            else:
                self.rois.pop(key, None)
            self._render_preview()

    def _clear_roi(self):
        info = self._current_video()
        if info:
            self.rois.pop(self._video_key(info), None)
            self._render_preview()

    # ------------------------------------------------------------------ nagrywanie
    def is_recording(self) -> bool:
        return self.session is not None

    def start(self):
        if self.session is not None:
            return
        mode = self.mode
        audio = None
        if mode in ("av", "audio"):
            i = self.audio_combo.currentIndex()
            if not (0 <= i < len(self._audio_sources)):
                QMessageBox.warning(self, "Nagrywanie", "Wybierz źródło dźwięku.")
                return
            audio = self._audio_sources[i]
        video = self._current_video() if mode in ("av", "slides") else None
        if video and video.kind == "none":
            video = None
        if mode == "slides" and video is None:
            QMessageBox.warning(self, "Nagrywanie", "Wybierz ekran albo okno ze slajdami.")
            return
        roi = self.rois.get(self._video_key(video)) if video else None
        subject = self.subject.currentText().strip()
        self.settings.last_subject = subject
        self.settings.save()
        continuing = self.continue_lecture is not None
        if continuing:
            lecture = self.continue_lecture
            parts_before = [dict(p) for p in (lecture.meta.parts or [])]
            duration_before = lecture.meta.duration
            status_before = lecture.meta.status
        else:
            lecture = Lecture.create(self.settings.library_path(), self.title.text(), subject)
            lecture.meta.kind = mode
            lecture.save_meta()
        self.transcript.clear()
        self.slides.clear()
        self.slide_text.set_slides([])
        self.slides_title.setText("SLAJDY · 0")
        self.video_status.setText("")
        self.meter.reset()
        sess = RecordingSession(
            lecture, self.settings, audio, video, roi, live_transcription=self.live_cb.isChecked(),
            on_segments=self.segments_signal.emit,
            on_slide=lambda ev, path: self.slide_signal.emit(ev.index, ev.is_new, path or "", ev.t, ev.updated),
            on_status=self.status_signal.emit,
            on_video_status=self.video_status_signal.emit,
            live_notes=self.live_cb.isChecked() and self.live_notes_cb.isChecked(),
            on_notes_update=self.notes_update_signal.emit,
            on_notes_status=self.notes_status_signal.emit,
            language=(lecture.meta.language or self.lang_combo.currentData()) if continuing else self.lang_combo.currentData(),
        )
        try:
            sess.start()
        except Exception as e:  # noqa: BLE001
            log.exception("start")
            try:
                if sess.slide_rec:
                    sess.slide_rec.stop()
                if sess.recorder:
                    sess.recorder.stop()
            except Exception:
                pass
            if continuing:        # przywróć stan wykładu sprzed próby
                lecture.meta.parts, lecture.meta.duration, lecture.meta.status = parts_before, duration_before, status_before
                lecture.save_meta()
            else:
                shutil.rmtree(lecture.folder, ignore_errors=True)
            QMessageBox.critical(self, "Nie udało się rozpocząć nagrywania", str(e))
            return
        self.session = sess
        self._last_sound = 0.0
        self._autostop_deadline = None
        self._autostop_snooze = 0.0
        self.autostop.hide()
        self.btn_mark.blockSignals(True)
        self.btn_mark.setChecked(False)
        self.btn_mark.setText("Zaznacz")
        self.btn_mark.blockSignals(False)
        self._marks_count = 0
        self.live_title.setText(lecture.meta.title + (f"  ·  część {sess.part_index}" if sess.is_continuation else ""))
        src = self.audio_combo.currentText() if audio else ""
        self.live_sub.setText(" · ".join(x for x in [subject, f"dźwięk: {src}" if audio else "bez dźwięku",
                                                      f"slajdy: {self.video_combo.currentText()}" if video else "bez slajdów"] if x))
        if audio is None:
            self._set_status("Zrzuty slajdów – notatka powstanie z ich treści po zakończeniu.")
        else:
            self._set_status("Ładowanie modelu rozpoznawania mowy…" if sess.live else
                             "Nagrywanie – transkrypcja zrobi się po zakończeniu.")
        for w_ in (self.meter, self.btn_mark, self.mark_kind):
            w_.setVisible(audio is not None)
        self.transcript.setHtml(self._placeholder_html())
        self._has_text = False
        if continuing:            # pokaż dotychczasową transkrypcję – nowa część dopisze się pod nią
            self._on_segments(lecture.load_segments()[-40:])
            self.transcript.append(f"<p style='color:{T().accent}'><b>— część {sess.part_index} —</b></p>")
        self._setup_live_panels(sess)
        self.btn_stop.setEnabled(True)
        self.stack.setCurrentIndex(1)
        self._live_mode = None
        QTimer.singleShot(0, self._relayout_live)
        self.timer.start()
        self.recording_state.emit(True)

    def _setup_live_panels(self, sess):
        t = T()
        self.live_seg.set_current(0, emit=True)
        self.live_notes_view.images = {}
        on = sess.live_notes_enabled
        self.live_seg.buttons[1].setEnabled(on)
        self.live_seg.buttons[2].setEnabled(sess.live)
        self.live_seg.buttons[0].setEnabled(sess.audio_info is not None)
        if sess.audio_info is None:
            self.transcript.setHtml(f"<p style='color:{t.text2}'>Tryb „Tylko slajdy” – bez dźwięku i transkrypcji. "
                                    "Złapane slajdy widać po prawej; notatka powstanie z ich treści.</p>")
        if on:
            self.live_notes_view.setHtml(
                f"<div style='color:{t.text2}'><p style='font-size:12pt; color:{t.text}'><b>Notatki na żywo</b></p>"
                "<p>Pierwszy fragment notatek pojawi się po zmianie slajdu albo po kilku minutach mowy. "
                "Kolejne będą się dopisywać w trakcie wykładu.</p></div>")
            self.live_notes_status.setText("Ładowanie…")
        lec = sess.lecture

        def get_md():
            ln = sess.live_notes
            if ln is not None:
                return ln.qa_markdown()
            segs = lec.load_segments()     # bez notatek na żywo – pytania do samej transkrypcji
            from ..live_notes import LIVE_HEADING
            return f"# {lec.meta.title}\n\n## {LIVE_HEADING}\n\n" + " ".join(x["text"] for x in segs[-400:])
        self.live_ask.set_source(get_md, lec.folder / "qa.json", int(self.settings.live_ctx))
        if self._live_mode == "wide":
            self.live_seg.set_current(1 if on else 2, emit=True)

    def _on_notes_update(self):
        s = self.session
        if not s:
            return
        lec = s.lecture
        md = lec.read_text(lec.notes_path)
        folder, dpr = lec.folder, self.devicePixelRatioF() or 1.0
        view = self.live_notes_view

        def done(res):
            html_doc, images, _plays = res
            sb = view.verticalScrollBar()
            at_bottom = sb.value() >= sb.maximum() - 30
            pos = sb.value()
            view.images = images
            view.setHtml(html_doc)
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum() if at_bottom else pos))
        from .library_tab import build_notes
        run_async(lambda: build_notes(folder, md, dpr, audio=False), done)

    def _live_jump(self, anchor: str):
        if anchor.startswith("sec-") and self.live_seg.buttons[1].isEnabled():
            self.live_seg.set_current(1, emit=True)
            QTimer.singleShot(50, lambda: self.live_notes_view.scrollToAnchor(anchor))

    def _placeholder_html(self) -> str:
        return (f"<p style='color:{T().text3}'>Pierwszy fragment tekstu pojawi się po około 20–30 sekundach "
                "od rozpoczęcia mowy.</p>")

    def stop(self):
        if self.session is None:
            return
        sess = self.session
        self.btn_stop.setEnabled(False)
        self._set_status("Kończenie – zapisywanie nagrania i dokończenie transkrypcji…")

        def work():
            try:
                sess.stop()
            except Exception:
                log.exception("stop")
                sess.needs_file_transcription = True
            self.stopped_signal.emit(sess.lecture, getattr(sess, "needs_file_transcription", False))

        threading.Thread(target=work, daemon=True).start()

    def stop_blocking(self):
        if self.session:
            try:
                self.session.stop()
            except Exception:
                log.exception("stop_blocking")
            self.session = None

    def _on_stopped(self, lecture, needs_file):
        self.timer.stop()
        self.session = None
        self.stack.setCurrentIndex(0)
        self.title.clear()
        self.cancel_continue()
        self.autostop.hide()
        self.refresh_subjects()
        self.setup_status.setText(f"Zapisano „{lecture.meta.title}” ({fmt_time(lecture.meta.duration)}).")
        self.recording_state.emit(False)
        self.recording_finished.emit(lecture, needs_file)

    def _set_status(self, text: str):
        self.status.setText(text)

    # ------------------------------------------------------------------ kontynuacja
    def prepare_continue(self, lecture: Lecture):
        """Następne nagranie dopisze kolejną część do tego wykładu (np. po przerwie)."""
        if self.session is not None:
            return
        self.continue_lecture = lecture
        n = len(lecture.audio_parts()) + 1
        kind = lecture.meta.kind if lecture.meta.kind in self.modes else "av"
        self.modes[kind].setChecked(True)
        self.setup_title.setText("Kontynuacja notatki")
        self.cont_text.setText(f"<b>{html.escape(lecture.meta.title)}</b> – część {n}. Nagranie, slajdy albo zdjęcia "
                               f"dopiszą się do tej samej notatki (czas biegnie dalej od "
                               f"{fmt_time(lecture.meta.duration)}). Możesz wybrać dowolny rodzaj poniżej.")
        self.cont_banner.show()
        self.title.setText(lecture.meta.title)
        self.subject.setEditText(lecture.meta.subject)
        self.title.setEnabled(False)
        self.subject.setEnabled(False)

    def cancel_continue(self):
        self.continue_lecture = None
        self.cont_banner.hide()
        self.setup_title.setText("Nowa notatka")
        self.title.setEnabled(True)
        self.subject.setEnabled(True)
        self.title.clear()

    # ------------------------------------------------------------------ zaznaczanie ważnych fragmentów
    def _toggle_mark(self, on: bool):
        s = self.session
        if not s:
            return
        from ..storage import MARK_KINDS
        if on:
            mk = s.start_mark(self.mark_kind.currentData())
            self.btn_mark.setText("Zakończ zaznaczanie")
            self.btn_mark.setObjectName("destructive")
            self.mark_kind.setEnabled(False)
            self._set_status(f"Zaznaczanie od {fmt_time(mk['start'])} ({MARK_KINDS.get(mk['kind'])}) – kliknij "
                             "„Zakończ zaznaczanie”, gdy fragment się skończy.")
        else:
            mk = s.end_mark()
            self.btn_mark.setText("Zaznacz")
            self.btn_mark.setObjectName("")
            self.mark_kind.setEnabled(True)
            if mk:
                self._marks_count += 1
                self._set_status(f"Zaznaczono {fmt_time(mk['start'])}–{fmt_time(mk['end'])} · "
                                 f"{MARK_KINDS.get(mk['kind'])}. Ten fragment dostanie osobną notatkę i więcej fiszek.")
        self.btn_mark.style().unpolish(self.btn_mark)
        self.btn_mark.style().polish(self.btn_mark)

    # ------------------------------------------------------------------ auto-stop
    def _check_autostop(self):
        s = self.session
        minutes = int(getattr(self.settings, "auto_stop_minutes", 0) or 0)
        if not s or minutes <= 0 or s.audio_info is None:
            return
        import time as _t
        now = _t.monotonic()
        if s.level_db() > -50:
            self._last_sound = now
        if not self._last_sound:
            self._last_sound = now
        reason = ""
        info = s.audio_info
        if info.kind == "process" and info.pid:
            try:
                import psutil
                if not psutil.pid_exists(info.pid):
                    reason = "Aplikacja, z której nagrywasz dźwięk, została zamknięta."
            except Exception:
                pass
        silent = now - self._last_sound
        if not reason and silent >= minutes * 60 and now >= self._autostop_snooze:
            reason = f"Od {int(silent // 60)} min nic nie słychać – wygląda na to, że wykład się skończył."
        if reason and self._autostop_deadline is None:
            self._autostop_deadline = now + 60
            self._autostop_reason = reason
            self.autostop.show()
        if self._autostop_deadline is not None:
            if s.level_db() > -45 and "zamknięta" not in self._autostop_reason:
                self._autostop_cancel()        # znowu słychać wykład
                return
            left = int(self._autostop_deadline - now)
            self.autostop_text.setText(f"{self._autostop_reason} Nagrywanie zakończy się za {max(0, left)} s.")
            if left <= 0:
                self.autostop.hide()
                self._autostop_deadline = None
                self.stop()

    def _autostop_cancel(self):
        import time as _t
        self._autostop_deadline = None
        self.autostop.hide()
        self._last_sound = _t.monotonic()
        self._autostop_snooze = _t.monotonic() + 5 * 60

    # ------------------------------------------------------------------
    def elapsed_text(self) -> str:
        return fmt_time(self.session.elapsed()) if self.session else ""

    def _tick(self):
        s = self.session
        if not s:
            return
        self._ticks += 1
        self.meter.push((s.level_db() + 60) / 60)
        if self._ticks % 5 == 0:
            self.time_label.setText(fmt_time(s.now()))
            self.dot.blink()
            if s.whisper_ready and s.pending_seconds() > 90:
                self._set_status(f"Transkrypcja nie nadąża (opóźnienie {int(s.pending_seconds())} s) – nadrobi po zakończeniu.")
            if s.recorder and s.recorder.error:
                self._set_status(f"Błąd dźwięku: {s.recorder.error}")
        if self._ticks % 10 == 0:
            self._check_autostop()

    def _on_segments(self, segs: list):
        t = T()
        if not getattr(self, "_has_text", False):
            self.transcript.clear()
            self._has_text = True
        mk = self.session.open_mark if self.session else None
        for sg in segs:
            marked = bool(mk and sg["end"] >= mk["start"])
            star = f"<span style='color:{t.orange}'>★</span> " if marked else ""
            self.transcript.append(
                f"<p style='margin:0 0 8px 0'><span style='color:{t.text3}'>{fmt_time(sg['start'])}</span>"
                f"&nbsp;&nbsp;{star}{html.escape(sg['text'])}</p>")
        sb = self.transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _slide_text_of(self, index: int) -> str:
        s = self.session
        try:
            return s.slide_text(index) if s is not None and hasattr(s, "slide_text") else ""
        except Exception:  # noqa: BLE001
            return ""

    def _on_slide(self, index: int, is_new: bool, path: str, t: float, updated: bool = False):
        if updated and path:
            self.slides.update_slide(index, path, self._slide_text_of(index))
            self._set_status(f"Slajd {index} uzupełniony (animacja) – zrzut podmieniony.")
        elif is_new and path:
            self.slides.add_slide(index, path, t, self._slide_text_of(index))
            self.slides.scrollToBottom()
        elif not is_new:
            self._set_status(f"Powrót do slajdu {index} ({fmt_time(t)}).")
        self._slides_changed()

    def _slides_changed(self):
        self.slides_title.setText(f"SLAJDY · {self.slides.count()}")
        self.slide_text.set_slides(self.slides.infos())

    def _preview_slide(self, index: int):
        from .slide_views import SlidePreview
        infos = self.slides.infos()
        pos = next((k for k, x in enumerate(infos) if x.index == index), 0)
        SlidePreview(infos, pos, self, on_delete=lambda i: self._delete_slide(i, ask=False)).exec()

    def _delete_slide(self, index: int, ask: bool = False) -> bool:
        s = self.session
        ok = False
        try:
            ok = bool(s.delete_slide(index)) if s is not None and hasattr(s, "delete_slide") else False
        except Exception:  # noqa: BLE001
            log.exception("usuwanie slajdu")
        if s is None or not hasattr(s, "delete_slide"):
            ok = True               # podgląd bez sesji (np. zrzuty ekranu) – tylko z listy
        if ok:
            self.slides.remove_slide(index)
            self._slides_changed()
            self._set_status(f"Usunięto slajd {index}. Jeśli ten sam obraz wróci (np. kamerka), nie zapisze się ponownie.")
        return ok

    def _on_video_status(self, text: str):
        self.video_status.setText((text + " – przywróć okno albo wybierz cały monitor.") if text else "")


    def open_files_mode(self):
        if self.session is None:
            self.modes["files"].setChecked(True)
