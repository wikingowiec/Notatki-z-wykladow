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

from ..screen_capture import VideoSourceInfo, list_monitors, list_windows, make_grabber
from ..session import RecordingSession
from ..storage import Lecture, fmt_time, list_lectures
from .ask_panel import AskPanel
from .audio_picker import AudioSourcePicker
from .reader import Reader
from .controls import (show_if, ModeCard, SegmentedControl, GroupSection, LevelMeter, PulseDot, RecordButton, ToggleSwitch, hbox, icon_button, label,
                       rounded_pixmap, set_icon)
from .theme import T, qcolor, theme
from .widgets import RoiDialog, ask_video_roi, bgr_to_qpixmap, run_async

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



def short_audio(label: str) -> str:
    """„Microsoft Teams  (gra teraz)  [PID 4412]” → „Teams” (stare etykiety miały też emoji na początku)."""
    import re as _re
    t = _re.split(r"\s{2,}|\(|\[", (label or "").lstrip("🔊🖥🎤 "))[0].strip()
    for pre in ("Microsoft ", "Google "):
        if t.startswith(pre) and len(t) > len(pre) + 2:
            t = t[len(pre):]
    if t.lower().startswith("cały dźwięk"):
        return "dźwięk systemu"
    return t[:22]


def short_video(info) -> str:
    import re as _re
    if info.kind == "monitor":
        return f"Monitor {info.index}"
    t = _re.sub(r"\s+", " ", info.title or info.label or "okno").strip()
    return ("Okno: " + t)[:26]


class RecordTab(QWidget):
    segments_signal = Signal(list)
    slide_signal = Signal(int, bool, str, float, bool)
    status_signal = Signal(str)
    video_status_signal = Signal(str)
    stopped_signal = Signal(object, bool)
    files_requested = Signal(object, list, list, bool, dict)   # wykład, nagrania, zdjęcia, prostowanie, obszary slajdów
    notes_update_signal = Signal()
    notes_status_signal = Signal(str)
    recording_finished = Signal(object, bool)      # do MainWindow
    recording_state = Signal(bool)                 # do paska bocznego
    last_rec_changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.session: RecordingSession | None = None
        self.rois: dict[str, tuple] = {}
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
        self.audio_picker = AudioSourcePicker()
        self.audio_picker.loaded.connect(self._apply_audio)
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
                                              "w tle) nie trafią do nagrania. Aplikacja z wykładem sama pojawi się na "
                                              "górze listy, gdy zacznie grać. Na zajęciach stacjonarnych wybierz mikrofon.")
        self.row_audio = self.g_audio.add_row("Źródło dźwięku")
        self.g_audio.add(self.audio_picker)
        self.g_slides = GroupSection("Slajdy")
        self.row_video = self.g_slides.add_row("Ekran lub okno", hbox(self.video_combo, self.btn_refresh_video, spacing=4))
        # uwaga pod polem, gdy ostatnio użytego źródła teraz nie ma (Ctrl+Shift+R)
        for r in (self.row_audio, self.row_video):
            r.subtitle.setObjectName("fieldWarn")
        self._want_audio: dict | None = None
        self._want_video: dict | None = None
        self.audio_picker.picked.connect(lambda: self._forget_want("audio"))
        self.video_combo.activated.connect(lambda _i: self._forget_want("video"))
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
        self.btn_file_roi = QPushButton("Obszar slajdu…")
        self.btn_file_roi.setObjectName("plain")
        set_icon(self.btn_file_roi, "crop", "text2", 14)
        self.btn_file_roi.setToolTip("Zaznacz, w której części filmu jest slajd (bez kamerki prowadzącego i czatu)")
        self.btn_file_roi.clicked.connect(lambda: self._edit_file_roi(self.audio_files.currentItem()))
        self.btn_file_roi.setEnabled(False)
        self.audio_files.currentItemChanged.connect(
            lambda it, _p: self.btn_file_roi.setEnabled(it is not None and self._is_video_item(it)))
        self.audio_files.itemDoubleClicked.connect(self._edit_file_roi)
        ga = GroupSection("Nagranie", "Dyktafon z iPhone'a (.m4a), mp3, wav albo wideo (mp4, mov). Kilka plików = kolejne "
                                      "części jednego wykładu (w podanej kolejności). Pliki możesz też przeciągnąć tutaj.")
        wa = QWidget()
        la = QVBoxLayout(wa)
        la.setContentsMargins(12, 10, 12, 10)
        la.addWidget(self.audio_files)
        la.addWidget(hbox(b_add_a, b_del_a, "stretch", self.btn_file_roi))
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
        videos = []
        for p in paths:
            if p in existing:
                continue
            it = QListWidgetItem(_P(p).name)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.audio_files.addItem(it)
            if self._is_video_item(it):
                videos.append(it)
        if videos:      # krok „Zaznacz obszar slajdu” – po zamknięciu okna wyboru / upuszczeniu plików
            QTimer.singleShot(0, lambda: self._ask_file_rois(videos))

    _ROI_ROLE = Qt.ItemDataRole.UserRole + 1

    @staticmethod
    def _is_video_item(it) -> bool:
        from pathlib import Path as _P
        from ..jobs import VIDEO_EXT
        return _P(it.data(Qt.ItemDataRole.UserRole) or "").suffix.lower() in VIDEO_EXT

    def _ask_file_rois(self, items):
        for k, it in enumerate(items, 1):
            title = "Zaznacz obszar slajdu" + (f" ({k}/{len(items)})" if len(items) > 1 else "")
            try:
                if not self._edit_file_roi(it, title):
                    break
            except RuntimeError:          # pozycja usunięta z listy
                continue

    def _edit_file_roi(self, it, title: str = "") -> bool:
        if it is None or not self._is_video_item(it):
            return False
        from pathlib import Path as _P
        path = it.data(Qt.ItemDataRole.UserRole)
        ok, roi = ask_video_roi(self, path, it.data(self._ROI_ROLE), title)
        if ok:
            it.setData(self._ROI_ROLE, tuple(roi) if roi else None)
            it.setText(_P(path).name + ("  ·  slajd: zaznaczony obszar" if roi else "  ·  slajd: cały obraz"))
        return ok

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
        rois = {}
        for i in range(self.audio_files.count()):
            it = self.audio_files.item(i)
            if it.data(self._ROI_ROLE):
                rois[it.data(Qt.ItemDataRole.UserRole)] = tuple(it.data(self._ROI_ROLE))
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
        self.files_requested.emit(lecture, audio, photos, self.straighten_cb.isChecked(), rois)
        self.audio_files.clear()
        self.photo_files.clear()
        self.title.clear()
        self.cancel_continue()

    # ------------------------------------------------------------------ widok: nagrywanie
    def _build_live(self) -> QWidget:
        from PySide6.QtGui import QAction, QKeySequence, QShortcut
        from PySide6.QtWidgets import QMenu, QToolButton
        from ..storage import MARK_KINDS
        from .live_view import CurrentSlide, DupHint
        from .slide_views import SlideThumbs
        w = QWidget()
        w.setObjectName("content")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 18, 24, 18)
        v.setSpacing(10)
        self.live_v = v

        # --- nagłówek: [● NAGRYWANIE / tytuł / źródła]   [poziom] [czas] [Zaznacz ważne ▾] [pauza] [Zakończ] ---
        frame = QFrame()
        frame.setObjectName("recBar")
        fv = QVBoxLayout(frame)
        fv.setContentsMargins(20, 14, 16, 14)
        fv.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.dot = PulseDot("red")
        info = QVBoxLayout()
        info.setSpacing(2)
        self.rec_label = label("NAGRYWANIE", "recLabel")
        self.live_title = label("", "title2")
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
        self.meter = LevelMeter(28)
        self.meter.setToolTip("Poziom dźwięku – powinien się ruszać, gdy prowadzący mówi")
        self.meter.setMinimumWidth(110)
        self.meter.setMaximumWidth(170)
        self.time_label = label("00:00", "timer")
        try:                 # cyfry tabelaryczne – czas nie „skacze” przy zmianie cyfr
            from PySide6.QtGui import QFont as _QF
            tf = self.time_label.font()
            tf.setFeature(_QF.Tag("tnum"), 1)
            self.time_label.setFont(tf)
        except Exception:  # noqa: BLE001
            pass
        self._mark_kind = "important"
        self.btn_mark = QPushButton("Zaznacz ważne")
        self.btn_mark.setObjectName("mark")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setToolTip("Zaznacz ważny fragment (Ctrl+M): kliknij, gdy się zaczyna – zaznaczenie obejmie też "
                                 "ostatnie ~20 s – i kliknij ponownie, gdy się kończy.")
        set_icon(self.btn_mark, "highlighter", "text", 16)
        self.btn_mark.toggled.connect(self._toggle_mark)
        self.btn_mark_kind = QToolButton()
        self.btn_mark_kind.setObjectName("icon")
        self.btn_mark_kind.setToolTip("Rodzaj zaznaczenia")
        self.btn_mark_kind.setFixedSize(30, 44)
        set_icon(self.btn_mark_kind, "chevron-down", "text2", 14)
        self.btn_mark_kind.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        km = QMenu(self.btn_mark_kind)
        for k, name in MARK_KINDS.items():
            act = QAction(name, km)
            act.triggered.connect(lambda _c=False, k=k: self._set_mark_kind(k))
            km.addAction(act)
        self.btn_mark_kind.setMenu(km)
        self.btn_pause = QPushButton("")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setToolTip("Pauza – dźwięk, transkrypcja i slajdy się zatrzymują, czas stoi")
        self.btn_pause.setFixedSize(46, 44)
        set_icon(self.btn_pause, "pause", "text", 18)
        self.btn_pause.toggled.connect(self._toggle_pause)
        self.btn_stop = QPushButton("Zakończ")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setToolTip("Zakończ nagrywanie – notatki zrobią się same")
        set_icon(self.btn_stop, "stop", "on_red", 16)
        self.btn_stop.clicked.connect(self.stop)
        for b_ in (self.btn_mark, self.btn_mark_kind, self.btn_pause, self.btn_stop):
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools = QWidget()
        tl = QHBoxLayout(self.tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tl.addWidget(self.meter, 1)
        tl.addSpacing(6)
        tl.addWidget(self.time_label)
        tl.addSpacing(6)
        self.tools_b = QWidget()                 # na wąskim oknie trafiają do dolnego paska
        self.tools_b_lay = QHBoxLayout(self.tools_b)
        self.tools_b_lay.setContentsMargins(0, 0, 0, 0)
        self.tools_b_lay.setSpacing(8)
        mk_ = QHBoxLayout()
        mk_.setSpacing(0)
        mk_.addWidget(self.btn_mark, 1)
        mk_.addWidget(self.btn_mark_kind)
        self.tools_b_lay.addLayout(mk_, 1)
        self.tools_b_lay.addWidget(self.btn_pause)
        self.tools_b_lay.addWidget(self.btn_stop)
        tl.addWidget(self.tools_b)
        top.addLayout(info, 1)
        self.top_tools_slot = QHBoxLayout()
        top.addLayout(self.top_tools_slot)
        fv.addLayout(top)
        self.bottom_tools_slot = QHBoxLayout()
        fv.addLayout(self.bottom_tools_slot)
        self.rec_frame = frame
        frame.installEventFilter(self)
        v.addWidget(frame)
        sc = QShortcut(QKeySequence("Ctrl+M"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(lambda: self.session is not None and self.btn_mark.isVisible() and self.btn_mark.toggle())

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

        self.status = label("", "footnote", wrap=True)
        self.video_status = label("", "footnote", wrap=True)
        sv_ = QVBoxLayout()
        sv_.setContentsMargins(6, 0, 6, 0)
        sv_.setSpacing(2)
        sv_.addWidget(self.status)
        sv_.addWidget(self.video_status)
        v.addLayout(sv_)

        def col_head(title: str, extra: QWidget | None = None):
            h = QHBoxLayout()
            h.setContentsMargins(2, 0, 0, 0)
            h.setSpacing(8)
            lb = label(title, "sectionHeader")
            h.addWidget(lb)
            h.addStretch(1)
            if extra is not None:
                h.addWidget(extra)
            return h, lb

        # 1) transkrypcja
        self.transcript = Reader(max_width=720, pad=18)
        self.transcript.verticalScrollBar().valueChanged.connect(self._transcript_scrolled)
        self.col_t = QWidget()
        ct = QVBoxLayout(self.col_t)
        ct.setContentsMargins(0, 0, 0, 0)
        ct.setSpacing(8)
        self.t_follow = QPushButton("↓ Na bieżąco")
        self.t_follow.setObjectName("plain")
        self.t_follow.clicked.connect(lambda: self._scroll_transcript(True))
        self.t_follow.hide()
        h, _ = col_head("TRANSKRYPCJA", self.t_follow)
        ct.addLayout(h)
        ct.addWidget(self.transcript, 1)

        # 2) notatki na żywo + pytania
        self.live_notes_view = Reader(max_width=760, pad=22)
        self.live_notes_view.internal_link.connect(lambda a: None)
        self.live_notes_status = label("", "caption", wrap=True)
        self.live_ask_field = QLineEdit()
        self.live_ask_field.setObjectName("askInput")
        self.live_ask_field.setPlaceholderText("Zapytaj o to, co już padło na wykładzie…  (Ctrl K)")
        self.live_ask_field.returnPressed.connect(self._ask_from_field)
        notes_page = QWidget()
        nl = QVBoxLayout(notes_page)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(8)
        nl.addWidget(self.live_notes_view, 1)
        nl.addWidget(self.live_notes_status)
        nl.addWidget(self.live_ask_field)
        self.live_ask = AskPanel(self.settings, live=True)
        self.live_ask.internal_link.connect(self._live_jump)
        ask_page = QWidget()
        al = QVBoxLayout(ask_page)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        self.btn_ask_back = QPushButton("Notatki")
        self.btn_ask_back.setObjectName("back")
        set_icon(self.btn_ask_back, "chevron-left", "accent_text", 16)
        self.btn_ask_back.clicked.connect(lambda: self._show_notes_page(0))
        al.addWidget(self.btn_ask_back, 0, Qt.AlignmentFlag.AlignLeft)
        al.addWidget(self.live_ask, 1)
        self.notes_stack = QStackedWidget()
        self.notes_stack.addWidget(notes_page)
        self.notes_stack.addWidget(ask_page)
        self.col_n = QWidget()
        cn = QVBoxLayout(self.col_n)
        cn.setContentsMargins(0, 0, 0, 0)
        cn.setSpacing(8)
        h, self.notes_head = col_head("NOTATKI NA ŻYWO")
        cn.addLayout(h)
        cn.addWidget(self.notes_stack, 1)

        # 3) slajdy: bieżący + tekst + miniatury (2 kolumny)
        self.cur_slide = CurrentSlide()
        self.cur_slide.open_requested.connect(self._preview_slide)
        self.dup_hint = DupHint()
        self.dup_hint.delete.connect(lambda i: self._delete_slide(i))
        self.slides = SlideThumbs(QSize(118, 66), deletable=True)
        self.slides.open_requested.connect(self._preview_slide)
        self.slides.delete_requested.connect(self._delete_slide)
        self.col_s = QWidget()
        cs = QVBoxLayout(self.col_s)
        cs.setContentsMargins(0, 0, 0, 0)
        cs.setSpacing(8)
        self.btn_live_roi = QPushButton("Zmień obszar slajdu")
        self.btn_live_roi.setObjectName("plain")
        self.btn_live_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        set_icon(self.btn_live_roi, "crop", "text2", 14)
        self.btn_live_roi.setToolTip("Zaznacz na nowo, gdzie na ekranie jest slajd – nagrywanie trwa dalej, "
                                     "złapane slajdy zostają")
        self.btn_live_roi.clicked.connect(self._change_live_roi)
        h, self.slides_title = col_head("SLAJDY · 0", self.btn_live_roi)
        cs.addLayout(h)
        cs.addWidget(self.cur_slide)
        cs.addWidget(self.dup_hint)
        cs.addWidget(self.slides, 1)
        self.col_s.setFixedWidth(304)

        split = QSplitter()
        split.setHandleWidth(18)
        split.setChildrenCollapsible(False)
        split.addWidget(self.col_t)
        split.addWidget(self.col_n)
        split.addWidget(self.col_s)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 6)
        split.setStretchFactor(2, 0)
        self.live_split = split

        # wąskie okno (9:16): zakładki zamiast kolumn
        self.live_seg = SegmentedControl(["Transkrypcja", "Notatki AI", "Zapytaj"], style="tabs")
        self.live_seg.changed.connect(self._narrow_tab)
        self.narrow_stack = QStackedWidget()
        self.narrow_box = QWidget()
        nb = QVBoxLayout(self.narrow_box)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.setSpacing(8)
        nb.addWidget(self.live_seg)
        nb.addWidget(self.narrow_stack, 1)
        from PySide6.QtWidgets import QBoxLayout
        self.alt = QWidget()                     # średnie / wąskie okno: zakładki + slajdy
        self.alt_lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.alt)
        self.alt_lay.setContentsMargins(0, 0, 0, 0)
        self.alt_lay.setSpacing(18)
        self.alt.hide()
        self.live_body = QVBoxLayout()
        self.live_body.setSpacing(10)
        self.live_body.addWidget(split, 1)
        self.live_body.addWidget(self.alt, 1)
        v.addLayout(self.live_body, 1)
        self.bottom_bar = QFrame()               # 9:16 – duże przyciski na dole
        self.bottom_bar.setObjectName("footerBar")
        self.bottom_lay = QHBoxLayout(self.bottom_bar)
        self.bottom_lay.setContentsMargins(14, 10, 14, 10)
        self.bottom_bar.hide()
        self.live_outer = w
        self._live_mode = None
        self._titems: list[dict] = []
        self._tmarks: list[dict] = []
        self._t_follow = True
        self._cur_slide_index = 0
        return w

    # ------------------------------------------------------------------ układ ekranu nagrywania
    def _relayout_live(self):
        """Szeroko (≥ 1200 px): trzy kolumny. Średnio: zakładki | slajdy. Wąsko (< 820 px albo pionowo, 9:16):
        kompaktowy nagłówek, bieżący slajd z tekstem obok, zakładki i dolny pasek z dużymi przyciskami."""
        if not hasattr(self, "live_split"):
            return
        w, h = self.width(), self.height()
        if w < 820 or h > w * 1.1:
            mode = "narrow"
        elif w < 1200:
            mode = "medium"
        else:
            mode = "wide"
        if mode != self._live_mode:
            self._live_mode = mode
            from PySide6.QtWidgets import QBoxLayout
            if mode == "wide":
                self.live_split.insertWidget(0, self.col_t)
                self.live_split.insertWidget(1, self.col_n)
                self.live_split.insertWidget(2, self.col_s)
                self.alt.hide()
                self.live_split.show()
                for c in (self.col_t, self.col_n, self.col_s):
                    c.show()
                tot = max(600, self.live_split.width() - 304)
                self.live_split.setSizes([int(tot * 0.45), int(tot * 0.55), 304])
            else:
                self.narrow_stack.addWidget(self.col_t)
                self.narrow_stack.addWidget(self.col_n)
                if mode == "medium":
                    self.alt_lay.setDirection(QBoxLayout.Direction.LeftToRight)
                    self.alt_lay.addWidget(self.narrow_box, 1)
                    self.alt_lay.addWidget(self.col_s)
                else:
                    self.alt_lay.setDirection(QBoxLayout.Direction.TopToBottom)
                    self.alt_lay.addWidget(self.col_s)
                    self.alt_lay.addWidget(self.narrow_box, 1)
                self.live_split.hide()
                self.alt.show()
                self.narrow_box.show()
                self._narrow_tab(self.live_seg.current())
            narrow = mode == "narrow"
            # kolumna slajdów
            self.cur_slide.set_horizontal(narrow)
            self.slides.setVisible(not narrow)
            if narrow:
                self.col_s.setMinimumWidth(0)
                self.col_s.setMaximumWidth(16777215)
                self.col_s.setMaximumHeight(200)
            else:
                self.col_s.setMaximumHeight(16777215)
                self.col_s.setFixedWidth(304)
                self.slides.setWrapping(True)
            # przyciski: w nagłówku albo w dolnym pasku (56 px)
            if narrow:
                self.bottom_lay.addWidget(self.tools_b)
                self.live_v.addWidget(self.bottom_bar)
                self.bottom_bar.show()
            else:
                self.tools.layout().addWidget(self.tools_b)
                self.bottom_bar.hide()
            for b in (self.btn_mark, self.btn_pause, self.btn_stop, self.btn_mark_kind):
                b.setMinimumHeight(56 if narrow else 44)
                b.setMaximumHeight(56 if narrow else 44)
            if narrow:
                self.btn_pause.setMinimumWidth(110)
                self.btn_pause.setMaximumWidth(16777215)
            else:
                self.btn_pause.setFixedWidth(46)
            self._pause_text()
            self.live_sub.setVisible(not narrow)
        self._place_tools()

    def _pause_text(self):
        narrow = self._live_mode == "narrow"
        paused = self.is_paused()
        self.btn_pause.setText(("Wznów" if paused else "Pauza") if narrow else "")

    def _narrow_tab(self, i: int):
        self.live_seg.set_current(i)
        if self._live_mode != "narrow":
            return
        self.narrow_stack.setCurrentWidget(self.col_t if i == 0 else self.col_n)
        if i >= 1:
            self.notes_stack.setCurrentIndex(i - 1)

    def _show_notes_page(self, i: int):
        self.notes_stack.setCurrentIndex(i)
        if self._live_mode == "narrow":
            self.live_seg.set_current(1 + i)

    def _ask_from_field(self):
        q = self.live_ask_field.text().strip()
        if len(q) < 4:
            return
        self.live_ask_field.clear()
        self._show_notes_page(1)
        self.live_ask.input.setText(q)
        self.live_ask.ask()

    def focus_ask(self):
        """Ctrl+K w trakcie nagrywania – pole „Zapytaj o to, co już padło…”."""
        if self._live_mode == "narrow":
            self._narrow_tab(1)
        self._show_notes_page(0)
        self.live_ask_field.setFocus()

    def _place_tools(self):
        """Nagłówek: narzędzia w jednym rzędzie albo (wąsko) w drugim rzędzie pod spodem."""
        fw = self.rec_frame.width()
        compact = fw < 980 and self._live_mode != "narrow"
        if getattr(self, "_tools_compact", None) != compact:
            self._tools_compact = compact
            (self.bottom_tools_slot if compact else self.top_tools_slot).addWidget(self.tools)
            self.meter.setMaximumWidth(16777215 if compact else 170)

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
        self.audio_picker.refresh()

    def _apply_audio(self):
        self._match_want_audio()
        active = sum(1 for s in self.audio_picker.sources if s.kind == "process" and s.active)
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
        self._match_want_video()
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

    def _change_live_roi(self):
        """W trakcie nagrywania: nowy obszar slajdu na aktualnej klatce – nagranie się nie przerywa."""
        sess = self.session
        if sess is None or sess.slide_rec is None:
            return
        img = sess.current_frame()
        if img is None:
            QMessageBox.information(self, "Obszar slajdu", "Nie ma jeszcze zrzutu ekranu – spróbuj za chwilę.")
            return
        dlg = RoiDialog(img, sess.roi, self)
        if not dlg.exec() or self.session is not sess:
            return
        roi = dlg.result_roi()
        if (tuple(roi) if roi else None) == (tuple(sess.roi) if sess.roi else None):
            return
        sess.set_roi(roi)
        key = getattr(self, "_live_roi_key", None)
        if key:                        # zapamiętaj na następne nagranie z tego źródła
            if roi:
                self.rois[key] = tuple(roi)
            else:
                self.rois.pop(key, None)
        lr = self.settings.last_rec or {}
        if lr.get("video") and lr["video"].get("key") == key:
            lr["roi"] = list(roi) if roi else None
            self.settings.save()
        self.video_status.setText("Obszar slajdu zmieniony – kolejne slajdy będą wykrywane w nowym obszarze."
                                  if roi else "Slajdy są teraz wykrywane na całym obrazie.")

    def _clear_roi(self):
        info = self._current_video()
        if info:
            self.rois.pop(self._video_key(info), None)
            self._render_preview()

    # ------------------------------------------------------------------ nagraj jak ostatnio
    def quick_label(self) -> str:
        """„Teams + Monitor 1” – co wypełni Ctrl+Shift+R (pusty tekst, gdy jeszcze nic nie nagrywano)."""
        lr = self.settings.last_rec or {}
        parts = [x.get("label", "").lstrip("🔊🖥🎤 ") for x in (lr.get("audio"), lr.get("video")) if x]
        return " + ".join(p for p in parts if p)

    def quick_prepare(self):
        """Wypełnia formularz nowej notatki ostatnimi ustawieniami. Nagrywanie startuje dopiero po „Start”.
        Źródło, którego teraz nie ma, jest opisane pod swoim polem (i wybierze się samo po odświeżeniu listy)."""
        if self.session is not None:
            return
        self.cancel_continue()
        self.title.clear()
        lr = self.settings.last_rec or {}
        mode = lr.get("mode")
        if mode not in self.modes:
            self._set_status("Najpierw nagraj coś raz zwykłym sposobem – potem Ctrl+Shift+R wypełni te same ustawienia.")
            return
        self.modes[mode].setChecked(True)
        self.subject.setEditText(lr.get("subject", self.settings.last_subject) or "")
        want_v = lr.get("video") if mode in ("av", "slides") else None
        if want_v and lr.get("roi"):
            self.rois[want_v["key"]] = tuple(lr["roi"])
        self._want_audio = lr.get("audio") if mode in ("av", "audio") else None
        self._want_video = want_v
        if self._want_audio:
            self._match_want_audio()       # od razu z obecnej listy, potem jeszcze raz po odświeżeniu w tle
            self.refresh_audio()
        if self._want_video:
            self.refresh_video()

    def _forget_want(self, which: str):
        """Ręczny wybór na liście – zapomnij o „jak ostatnio” i schowaj uwagę pod polem."""
        setattr(self, f"_want_{which}", None)
        self._field_warn(self.row_audio if which == "audio" else self.row_video, "")

    def _field_warn(self, row, text: str):
        row.subtitle.setText(text)
        show_if(row.subtitle, text)

    def _match_want_audio(self):
        want = self._want_audio
        if not want:
            self._field_warn(self.row_audio, "")
            return
        idx = -1
        for i, s_ in enumerate(self.audio_picker.sources):
            if s_.kind != want.get("kind"):
                continue
            if s_.kind == "process" and (s_.exe or "").lower() != (want.get("exe") or "").lower():
                continue
            if s_.kind == "mic" and want.get("device", -1) >= 0 and s_.device_index != want["device"]:
                continue
            idx = i
            if s_.active:
                break
        if idx >= 0:
            self.audio_picker.set_current(idx)
            self._field_warn(self.row_audio, "")
        else:
            name = want.get("label") or "ostatnie źródło dźwięku"
            self._field_warn(self.row_audio, f"Ostatnio było „{name}”, teraz nie gra – włącz wykład i odśwież listę.")

    def _match_want_video(self):
        want = self._want_video
        if not want:
            self._field_warn(self.row_video, "")
            return
        idx = next((i for i, v in enumerate(self._video_sources) if self._video_key(v) == want.get("key")), -1)
        if idx >= 0:
            self.video_combo.setCurrentIndex(idx)
            self._field_warn(self.row_video, "")
        else:
            name = want.get("label") or "ostatni ekran"
            todo = "otwórz to okno" if str(want.get("key", "")).startswith("window:") else "podłącz ten ekran"
            self._field_warn(self.row_video, f"Ostatnio było „{name}”, teraz jest niedostępne – {todo} i odśwież listę.")

    # ------------------------------------------------------------------ nagrywanie
    def is_recording(self) -> bool:
        return self.session is not None

    def start(self):
        if self.session is not None:
            return
        mode = self.mode
        audio = None
        if mode in ("av", "audio"):
            audio = self.audio_picker.current()
            if audio is None:
                QMessageBox.warning(self, "Nagrywanie", "Wybierz źródło dźwięku.")
                return
            self.audio_picker.stop_monitor()      # zwolnij mikrofon, zanim otworzy go nagrywanie
        video = self._current_video() if mode in ("av", "slides") else None
        if video and video.kind == "none":
            video = None
        if mode == "slides" and video is None:
            QMessageBox.warning(self, "Nagrywanie", "Wybierz ekran albo okno ze slajdami.")
            return
        roi = self.rois.get(self._video_key(video)) if video else None
        subject = self.subject.currentText().strip()
        self.settings.last_subject = subject
        self.settings.last_rec = {
            "mode": mode,
            "audio": ({"kind": audio.kind, "exe": audio.exe, "label": short_audio(audio.label),
                       "device": audio.device_index} if audio else None),
            "video": ({"key": self._video_key(video), "label": short_video(video)} if video else None),
            "roi": list(roi) if roi else None,
            "subject": subject,
        }
        self.settings.save()
        self._want_audio = self._want_video = None
        self._field_warn(self.row_audio, "")
        self._field_warn(self.row_video, "")
        self.last_rec_changed.emit()
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
        self.cur_slide.set_slide(None)
        self.dup_hint.hide()
        self._cur_slide_index = 0
        self._titems, self._tmarks, self._t_follow = [], [], True
        self.slides_title.setText("SLAJDY · 0")
        self.video_status.setText("")
        self.meter.reset()
        self._live_roi_key = self._video_key(video) if video else None
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
            if self.audio_picker.isVisible():
                self.audio_picker.start_monitor()
            return
        self.session = sess
        self._last_sound = 0.0
        self._autostop_deadline = None
        self._autostop_snooze = 0.0
        self.autostop.hide()
        self.btn_mark.blockSignals(True)
        self.btn_mark.setChecked(False)
        self._set_mark_kind("important")
        self.btn_mark.blockSignals(False)
        self.btn_pause.blockSignals(True)
        self.btn_pause.setChecked(False)
        self.btn_pause.blockSignals(False)
        self.rec_label.setText("NAGRYWANIE")
        self._marks_count = 0
        self.live_title.setText(lecture.meta.title + (f"  ·  część {sess.part_index}" if sess.is_continuation else ""))
        src = audio.label if audio else ""
        self.live_sub.setText(" · ".join(x for x in [subject, f"dźwięk: {src}" if audio else "bez dźwięku",
                                                      f"slajdy: {self.video_combo.currentText()}" if video else "bez slajdów"] if x))
        if audio is None:
            self._set_status("Zrzuty slajdów – notatka powstanie z ich treści po zakończeniu.")
        else:
            self._set_status("Ładowanie modelu rozpoznawania mowy…" if sess.live else
                             "Nagrywanie – transkrypcja zrobi się po zakończeniu.")
        for w_ in (self.meter, self.btn_mark, self.btn_mark_kind):
            w_.setVisible(audio is not None)
        show_if(self.btn_live_roi, sess.slide_rec is not None)
        self._has_text = False
        if continuing:            # pokaż dotychczasową transkrypcję – nowa część dopisze się pod nią
            self._titems = [dict(x, kind="seg") for x in lecture.load_segments()[-40:]]
            self._titems.append({"kind": "note", "text": f"część {sess.part_index}"})
        self._render_transcript()
        self._setup_live_panels(sess)
        self.btn_stop.setEnabled(True)
        self.stack.setCurrentIndex(1)
        self._live_mode = None
        QTimer.singleShot(0, self._relayout_live)
        self.timer.start()
        self.recording_state.emit(True)

    def _setup_live_panels(self, sess):
        t = T()
        self.live_notes_view.images = {}
        on = sess.live_notes_enabled
        self.live_seg.buttons[0].setEnabled(sess.audio_info is not None)
        self.live_seg.buttons[2].setEnabled(sess.live)
        self.live_ask_field.setEnabled(sess.live)
        self.live_ask_field.setPlaceholderText("Zapytaj o to, co już padło na wykładzie…  (Ctrl K)" if sess.live else
                                              "Pytania działają, gdy włączona jest transkrypcja na żywo.")
        self._show_notes_page(0)
        self.notes_head.setText("NOTATKI NA ŻYWO" if on else "NOTATKI")
        if on:
            self.live_notes_view.setHtml(
                f"<body style='color:{t.text2}'><p>Pierwszy fragment notatek pojawi się po zmianie slajdu albo po "
                "kilku minutach mowy. Kolejne będą się dopisywać w trakcie wykładu.</p>"
                + self._skeleton() + "</body>")
            self.live_notes_status.setText("Ładowanie…")
        else:
            self.live_notes_view.setHtml(
                f"<body style='color:{t.text2}'><p><b style='color:{t.text}'>Notatki na żywo są wyłączone.</b></p>"
                "<p>Notatka powstanie po zakończeniu nagrywania. Możesz je włączyć w opcjach przed nagraniem "
                "(„Notatki i pytania na żywo”).</p></body>")
            self.live_notes_status.setText("")
        lec = sess.lecture

        def get_md():
            ln = sess.live_notes
            if ln is not None:
                return ln.qa_markdown()
            segs = lec.load_segments()     # bez notatek na żywo – pytania do samej transkrypcji
            from ..live_notes import LIVE_HEADING
            return f"# {lec.meta.title}\n\n## {LIVE_HEADING}\n\n" + " ".join(x["text"] for x in segs[-400:])
        self.live_ask.set_source(get_md, lec.folder / "qa.json", int(self.settings.live_ctx))
        if self._live_mode == "narrow":
            self._narrow_tab(0 if sess.audio_info is not None else 1)

    def _skeleton(self) -> str:
        from .live_view import skeleton_html
        s = self.session
        ln = getattr(s, "live_notes", None) if s is not None else None
        if ln is not None and getattr(ln, "busy", False):
            return skeleton_html("Piszę ten fragment…")
        mins = 0
        try:
            from ..notes_pipeline import MAX_WORDS
            words = len((getattr(ln, "open_text", "") or "").split()) if ln is not None else 0
            mins = max(1, round((MAX_WORDS - words) / 140))
        except Exception:  # noqa: BLE001
            pass
        return skeleton_html(f"Piszę po zmianie slajdu albo za ~{mins} min" if mins else
                             "Piszę po zmianie slajdu albo za kilka minut")

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
            if self.session is not None and self.session.live_notes_enabled:
                html_doc = html_doc.replace("</body>", self._skeleton() + "</body>") if "</body>" in html_doc \
                    else html_doc + self._skeleton()
            sb = view.verticalScrollBar()
            at_bottom = sb.value() >= sb.maximum() - 30
            pos = sb.value()
            view.images = images
            view.setHtml(html_doc)
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum() if at_bottom else pos))
        from .library_tab import build_notes
        run_async(lambda: build_notes(folder, md, dpr, audio=False), done)

    def _live_jump(self, anchor: str):
        if anchor.startswith("sec-") and self.session is not None and self.session.live_notes_enabled:
            self._show_notes_page(0)
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
    def _set_mark_kind(self, kind: str):
        from ..storage import MARK_KINDS
        self._mark_kind = kind
        if not self.btn_mark.isChecked():
            self.btn_mark.setText("Zaznacz ważne" if kind == "important" else f"Zaznacz: {MARK_KINDS.get(kind, kind)}")

    def _toggle_mark(self, on: bool):
        s = self.session
        if not s:
            return
        from ..storage import MARK_KINDS
        if on:
            if s.paused:
                self.btn_pause.setChecked(False)
            mk = s.start_mark(self._mark_kind)
            self._tmarks.append({"start": mk["start"], "end": None, "kind": mk["kind"]})
            self.btn_mark.setText("Zakończ zaznaczanie")
            self.btn_mark_kind.setEnabled(False)
            self._set_status(f"Zaznaczanie od {fmt_time(mk['start'])} ({MARK_KINDS.get(mk['kind'])}) – kliknij "
                             "„Zakończ zaznaczanie” (Ctrl+M), gdy fragment się skończy.")
        else:
            mk = s.end_mark()
            self.btn_mark_kind.setEnabled(True)
            self._set_mark_kind(self._mark_kind)
            if self._tmarks and self._tmarks[-1]["end"] is None:
                self._tmarks[-1]["end"] = mk["end"] if mk else s.now()
            if mk:
                self._marks_count += 1
                self._set_status(f"Zaznaczono {fmt_time(mk['start'])}–{fmt_time(mk['end'])} · "
                                 f"{MARK_KINDS.get(mk['kind'])}. W notatce pojawi się ramka „Ważne” z tym fragmentem.")
        self._render_transcript()

    # ------------------------------------------------------------------ pauza
    def is_paused(self) -> bool:
        return bool(self.session is not None and getattr(self.session, "paused", False))

    def _toggle_pause(self, on: bool):
        s = self.session
        if not s or not hasattr(s, "pause"):
            return
        if on:
            if self.btn_mark.isChecked():
                self.btn_mark.setChecked(False)
            s.pause()
            self.rec_label.setText("PAUZA")
            self._pause_text()
            set_icon(self.btn_pause, "play", "text", 18)
            self.btn_pause.setToolTip("Wznów nagrywanie")
            self._set_status("Pauza – dźwięk, transkrypcja i slajdy nie są nagrywane. Czas stoi.")
        else:
            s.resume()
            self.rec_label.setText("NAGRYWANIE")
            self._pause_text()
            set_icon(self.btn_pause, "pause", "text", 18)
            self.btn_pause.setToolTip("Pauza – dźwięk, transkrypcja i slajdy się zatrzymują, czas stoi")
            self._set_status("Nagrywanie wznowione.")
            import time as _t
            self._last_sound = _t.monotonic()
        self._render_transcript()
        self.recording_state.emit(True)

    # ------------------------------------------------------------------ auto-stop
    def _check_autostop(self):
        s = self.session
        minutes = int(getattr(self.settings, "auto_stop_minutes", 0) or 0)
        if not s or minutes <= 0 or s.audio_info is None or getattr(s, "paused", False):
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
        paused = getattr(s, "paused", False)
        self.meter.push(0.0 if paused else (s.level_db() + 60) / 60)
        if self._ticks % 5 == 0:
            self.time_label.setText(fmt_time(s.now()))
            if not paused:
                self.dot.blink()
        if self._ticks % 300 == 0 and s.live_notes_enabled:
            self._on_notes_update()
            if s.whisper_ready and s.pending_seconds() > 90:
                self._set_status(f"Transkrypcja nie nadąża (opóźnienie {int(s.pending_seconds())} s) – nadrobi po zakończeniu.")
            if s.recorder and s.recorder.error:
                self._set_status(f"Błąd dźwięku: {s.recorder.error}")
        if self._ticks % 10 == 0:
            self._check_autostop()

    def _on_segments(self, segs: list):
        for sg in segs:
            self._titems.append({"kind": "seg", "start": sg["start"], "end": sg["end"], "text": sg["text"]})
        self._has_text = True
        self._render_transcript()

    def _render_transcript(self):
        from .live_view import transcript_html
        t = T()
        s = self.session
        if s is not None and s.audio_info is None:
            self.transcript.setHtml(f"<p style='color:{t.text2}'>Tryb „Tylko slajdy” – bez dźwięku i transkrypcji. "
                                    "Złapane slajdy widać po prawej; notatka powstanie z ich treści.</p>")
            return
        items = self._titems[-500:]
        if not any(x["kind"] == "seg" for x in items):
            self.transcript.setHtml(self._placeholder_html())
            return
        texts = {x.index: x.text for x in self.slides.infos()}
        doc = transcript_html(items, self._tmarks, texts,
                              live=bool(s is not None and s.live and not getattr(s, "paused", False)))
        sb = self.transcript.verticalScrollBar()
        pos = sb.value()
        self._render_lock = True
        self.transcript.setHtml(doc)
        self._render_lock = False
        if self._t_follow:
            QTimer.singleShot(0, lambda: self._scroll_transcript(True))
        else:
            sb.setValue(pos)

    def _scroll_transcript(self, follow: bool):
        sb = self.transcript.verticalScrollBar()
        self._t_follow = follow
        self._render_lock = True
        if follow:
            sb.setValue(sb.maximum())
        self._render_lock = False
        self.t_follow.setVisible(not follow)

    def _transcript_scrolled(self, v: int):
        if getattr(self, "_render_lock", False):
            return
        sb = self.transcript.verticalScrollBar()
        follow = v >= sb.maximum() - 24
        if follow != self._t_follow:
            self._t_follow = follow
            self.t_follow.setVisible(not follow and self.session is not None)

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
            prev = self.slides.infos()[-1] if self.slides.count() else None
            self.slides.add_slide(index, path, t, self._slide_text_of(index))
            self.slides.scrollToBottom()
            self._titems.append({"kind": "slide", "index": index, "t": t})
            if prev is not None:
                self._check_duplicate(prev.index, index)
        elif not is_new:
            self._set_status(f"Powrót do slajdu {index} ({fmt_time(t)}).")
            self._titems.append({"kind": "slide", "index": index, "t": t})
        if not updated:
            self._cur_slide_index = index
        self._slides_changed()

    def _check_duplicate(self, a: int, b: int):
        from .live_view import near_duplicate
        infos = {x.index: x for x in self.slides.infos()}
        ia, ib = infos.get(a), infos.get(b)
        if not ia or not ib:
            return

        def done(same):
            if same and b in {x.index for x in self.slides.infos()}:
                self.dup_hint.offer(a, b)
        # tekst slajdu bywa gotowy chwilę później – sprawdzamy po 3 s
        QTimer.singleShot(3000, lambda: run_async(
            lambda: near_duplicate(ia.path, ib.path, self._slide_text_of(a), self._slide_text_of(b)), done))

    def _slides_changed(self):
        self.slides_title.setText(f"SLAJDY · {self.slides.count()}")
        infos = self.slides.infos()
        for x in infos:
            if not x.text:
                x.text = self._slide_text_of(x.index)
        cur = next((x for x in infos if x.index == self._cur_slide_index), infos[-1] if infos else None)
        self.cur_slide.set_slide(cur)
        self._render_transcript()

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
            self._titems = [x for x in self._titems if not (x["kind"] == "slide" and x["index"] == index)]
            if self.dup_hint.index == index:
                self.dup_hint.hide()
            if self._cur_slide_index == index:
                self._cur_slide_index = 0
            self._slides_changed()
            self._set_status(f"Usunięto slajd {index}. Jeśli ten sam obraz wróci (np. kamerka), nie zapisze się ponownie.")
        return ok

    def _on_video_status(self, text: str):
        self.video_status.setText((text + " – przywróć okno albo wybierz cały monitor.") if text else "")


    def open_files_mode(self):
        if self.session is None:
            self.modes["files"].setChecked(True)
