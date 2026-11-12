"""Ekran „Nagrywanie”: przygotowanie (źródła) → nagrywanie na żywo (transkrypcja + slajdy)."""
from __future__ import annotations

import html
import logging
import shutil
import threading
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..storage import Lecture, fmt_time, list_lectures
from ..system import IS_MAC, LIVE_RECORDING
from .ask_panel import AskPanel
from .live_view import short_audio, short_video, switch_note
from .reader import Reader
from .controls import (show_if, ModeCard, SegmentedControl, GroupSection, LevelMeter, PulseDot, RecordButton, ToggleSwitch, hbox, icon_button, label,
                       rounded_pixmap, set_icon)
from .theme import T, qcolor, theme
from .widgets import RoiDialog, ask_video_roi, bgr_to_qpixmap, run_async
from ..i18n import tr
from ..timing import StepTimer

if TYPE_CHECKING:     # moduły nagrywania (WASAPI / Core Audio, zrzuty ekranu) ładują się tylko z nagrywaniem na żywo
    from ..screen_capture import VideoSourceInfo
    from ..session import RecordingSession

log = logging.getLogger(__name__)
SOON_TIP = (tr("Nagrywanie na żywo na Macu wymaga macOS 14.4 (Sonoma) lub nowszego. Zaktualizuj system albo dodaj "
            "nagranie lub wideo z pliku."))


class _NoAudioPicker(QWidget):
    """Zamiennik wyboru dźwięku tam, gdzie nie ma nagrywania na żywo (macOS starszy niż 14.4) – nic nie wylicza
    i nic nie nagrywa."""
    loaded = Signal()
    picked = Signal()
    current_changed = Signal()
    sources: list = []

    def refresh(self):
        pass

    def current(self):
        return None

    def set_current(self, _i: int):
        pass

    def start_monitor(self):
        pass

    def stop_monitor(self):
        pass


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


def today_line() -> str:
    """„sobota, 10 października” / „Saturday, October 10”."""
    from ..i18n import date_long
    return date_long()


def greeting() -> str:
    import datetime as _dt
    h = _dt.datetime.now().hour
    if 5 <= h < 12:
        return tr("Dzień dobry! Co dziś notujemy?")
    if 12 <= h < 18:
        return tr("Miłego popołudnia! Co dziś notujemy?")
    return tr("Dobry wieczór! Co dziś notujemy?")





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
    start_done = Signal(object)                    # wynik uruchamiania nagrywania w tle
    health_done = Signal(object, object)           # (próba startu, lista Problem) – sprawdzenie przed nagrywaniem
    health_fixed = Signal(str, object)             # (klucz problemu, nowe problemy albo None = błąd naprawy)
    health_progress = Signal(str, str, float)      # (klucz problemu, opis, postęp 0–1 / -1)
    schedule_state = Signal(str)                   # zaplanowane nagrywanie: „10:15” / „jutro 8:15”, "" = brak planu

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.session: RecordingSession | None = None
        self._pending: dict | None = None           # nagrywanie się uruchamia (wątek roboczy)
        self._start_thread: threading.Thread | None = None
        self._cleanups: list = []                    # (wątek, folder) – sprzątanie po anulowanym starcie
        self._preloaded = False
        self._attempt: dict | None = None            # ostatnia próba startu (także po starcie – karta problemu)
        self._fix_key = ""                           # problem naprawiany przez OllamaWatch (postęp na karcie)
        # zaplanowane nagrywanie (2.3) – tylko w pamięci, po restarcie aplikacji znika (zob. schedule.py)
        self._plan: dict | None = None
        self._plan_timer = QTimer(self)
        self._plan_timer.setInterval(1000)           # zegar ścienny sprawdzany co sekundę (uśpienie, zmiana czasu)
        self._plan_timer.timeout.connect(self._plan_tick)
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
        self.start_done.connect(self._on_start_done)
        self.health_done.connect(self._on_health_done)
        self.health_fixed.connect(self._on_health_fixed)
        self.health_progress.connect(lambda k, text, f: self.problem_card.set_busy(k, text, f))
        self.notes_update_signal.connect(self._on_notes_update)
        self.notes_status_signal.connect(self.live_notes_status.setText)
        theme().changed.connect(self._render_preview)

        self._prev_timer = QTimer(self)
        self._prev_timer.setSingleShot(True)
        self._prev_timer.setInterval(120)
        self._prev_timer.timeout.connect(self._render_preview)
        self.refresh_subjects()
        if LIVE_RECORDING:
            QTimer.singleShot(150, self.refresh_audio)
            QTimer.singleShot(200, self.refresh_video)

    # ------------------------------------------------------------------ widok: przygotowanie
    def _build_setup(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(22)

        from .controls import Heading
        self.heading = Heading(tr("Nowa notatka"), greeting() + tr(" Wybierz rodzaj notatki – transkrypcja i notatki "
                               "zrobią się same."), today_line())
        self.setup_title = self.heading.title
        # Ollama nie działa / brakuje modelu – baner na górze, sprawdzany w tle co ok. 10 s (healthcheck, 2.3)
        from .health_ui import OllamaBanner, OllamaWatch
        from ..healthcheck import needed_models
        self.ollama_banner = OllamaBanner(self.settings, lambda: needed_models(
            self.settings, bool(self.settings.live_notes and getattr(self, "live_cb", None) is not None
                                and self.live_cb.isChecked() and self.live_notes_cb.isChecked()),
            getattr(self, "mode", "av") in ("av", "slides", "files")))
        v.addWidget(self.ollama_banner)
        self._watch = OllamaWatch.get(self.settings)
        self._watch.changed.connect(self._watch_changed)
        v.addWidget(self.heading)

        from PySide6.QtWidgets import QGridLayout
        from ..ui.theme import MODE_COLOR
        self.modes = {
            "av": ModeCard("screen-audio", tr("Dźwięk + slajdy"), tr("Nagrywa dźwięk wykładu i łapie slajdy z ekranu."),
                           MODE_COLOR["av"]),
            "audio": ModeCard("mic", tr("Tylko dźwięk"), tr("Nagranie z aplikacji albo mikrofonu – notatki z tego, co mówi "
                              "prowadzący."), MODE_COLOR["audio"]),
            "slides": ModeCard("display", tr("Tylko slajdy"), tr("Zrzuty slajdów z ekranu – notatki z treści slajdów."),
                               MODE_COLOR["slides"]),
            "files": ModeCard("import", tr("Z pliku"), tr("Nagranie z Dyktafonu (m4a), mp3 lub wideo + zdjęcia slajdów."),
                              MODE_COLOR["files"]),
        }
        peers = list(self.modes.values())
        for c in peers:
            c.peers = peers
        if not LIVE_RECORDING:
            for key in ("av", "audio", "slides"):
                self.modes[key].set_soon(tr("Wymaga macOS 14.4"), SOON_TIP)
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
        btn_cc = QPushButton(tr("Nowa notatka zamiast tego"))
        btn_cc.setObjectName("plain")
        btn_cc.clicked.connect(self.cancel_continue)
        cb.addWidget(self.cont_text, 1)
        cb.addWidget(btn_cc)
        self.cont_banner.hide()
        v.addWidget(self.cont_banner)
        # Mac: brakujące zgody (mikrofon, dźwięk aplikacji, ekran) z wyjaśnieniem i przyciskiem do Ustawień
        self.perm_panel = None
        if IS_MAC and LIVE_RECORDING:
            from .permission_panel import PermissionPanel
            self.perm_panel = PermissionPanel()
            self.perm_panel.changed.connect(self._perms_changed)
            self.perm_panel.restart_requested.connect(self._restart_app)
            v.addWidget(self.perm_panel)

        # Wykład
        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("np. Analiza matematyczna – wykład 3"))
        self.title.setMinimumWidth(300)
        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.lineEdit().setPlaceholderText(tr("np. Analiza matematyczna"))
        self.subject.setMinimumWidth(300)
        g1 = GroupSection(tr("Wykład"), tr("Pusty tytuł = data i godzina. Przedmiot grupuje wykłady w bibliotece."))
        g1.add_row(tr("Tytuł"), self.title)
        g1.add_row(tr("Przedmiot"), self.subject)
        self.g_lecture = g1

        # Źródła
        if LIVE_RECORDING:
            from .audio_picker import AudioSourcePicker
            self.audio_picker = AudioSourcePicker()
        else:
            self.audio_picker = _NoAudioPicker()
        self.audio_picker.loaded.connect(self._apply_audio)
        if hasattr(self.audio_picker, "set_last_used"):     # zaznacz od razu, gdy ta aplikacja jest uruchomiona
            self.audio_picker.set_last_used((self.settings.last_rec or {}).get("audio"))
        self._audio_active = None
        self.audio_picker.current_changed.connect(self._update_perms)
        self.video_combo = QComboBox()
        self.video_combo.setMinimumWidth(200)
        self.video_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.video_combo.setMinimumContentsLength(30)
        self.btn_refresh_video = icon_button("refresh", tr("Odśwież listę ekranów i okien"))
        self.btn_refresh_video.clicked.connect(self.refresh_video)
        self.video_combo.currentIndexChanged.connect(self._video_changed)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.btn_roi = QPushButton(tr("Zaznacz obszar slajdu…"))
        set_icon(self.btn_roi, "crop", "text2", 16)
        self.btn_roi.clicked.connect(self.pick_roi)
        self.btn_roi_clear = QPushButton(tr("Cały obraz"))
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

        self.g_audio = GroupSection(tr("Dźwięk"), tr("Dźwięk nagrywa się tylko z wybranej aplikacji – inne programy (np. muzyka "
                                              "w tle) nie trafią do nagrania. Aplikacja z wykładem sama pojawi się na "
                                              "górze listy, gdy zacznie grać. Na zajęciach stacjonarnych wybierz mikrofon."))
        self.row_audio = self.g_audio.add_row(tr("Źródło dźwięku"))
        self.g_audio.add(self.audio_picker)
        self.g_slides = GroupSection(tr("Slajdy"))
        self.row_video = self.g_slides.add_row(tr("Ekran lub okno"), hbox(self.video_combo, self.btn_refresh_video, spacing=4))
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
        g3 = GroupSection(tr("Opcje"))
        self.lang_combo = QComboBox()
        for code, name in [("auto", tr("Wykryj automatycznie")), ("pl", tr("Polski")), ("en", tr("Angielski")),
                           ("de", tr("Niemiecki")), ("es", tr("Hiszpański")), ("fr", tr("Francuski"))]:
            self.lang_combo.addItem(name, code)
        i = self.lang_combo.findData(self.settings.language)
        self.lang_combo.setCurrentIndex(max(0, i))
        g3.add_row(tr("Język wykładu"), self.lang_combo, tr("Język, w którym mówi prowadzący – w nim powstanie transkrypcja."))
        from ..prompts import NOTES_LANGS
        self.notes_lang_combo = QComboBox()
        for code, name in [("", tr("Jak wykład"))] + [(c, tr(n)) for c, n in NOTES_LANGS]:
            self.notes_lang_combo.addItem(name, code)
        self.set_notes_lang(self.settings.notes_language)
        g3.add_row(tr("Język notatek"), self.notes_lang_combo,
                   tr("Notatki, fiszki i podsumowanie powstaną w tym języku – np. wykład po angielsku, notatki po polsku. "
                   "Terminy fachowe dostaną oryginał w nawiasie."))
        self.row_live = g3.add_row(tr("Transkrypcja na żywo"), self.live_cb,
                   tr("Tekst pojawia się w trakcie wykładu. Wyłącz, by odciążyć kartę graficzną – transkrypcja zrobi się po zakończeniu."))
        self.live_notes_cb = ToggleSwitch(self.settings.live_notes)
        self.row_live_notes = g3.add_row(tr("Notatki i pytania na żywo"), self.live_notes_cb,
                   tr("AI pisze notatki z każdego zakończonego fragmentu (po zmianie slajdu albo co kilka minut), "
                   "a Ty możesz zadawać pytania w trakcie wykładu. Mocniej obciąża kartę graficzną."))
        self.cards_cb = ToggleSwitch(bool((self.settings.last_rec or {}).get("make_flashcards",
                                                                             self.settings.auto_flashcards)))
        self.row_cards = g3.add_row(tr("Zrób fiszki z tego wykładu"), self.cards_cb,
                   tr("Fiszki do nauki powstaną razem z notatkami. Wyłączone – szybciej; fiszki zrobisz później "
                   "jednym kliknięciem w widoku wykładu."))
        self.live_cb.toggled.connect(self.live_notes_cb.setEnabled)
        self.live_cb.toggled.connect(lambda _on: self.ollama_banner.refresh())
        self.live_notes_cb.toggled.connect(lambda _on: self.ollama_banner.refresh())
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
        self.btn_start.setToolTip(tr("Rozpocznij nagrywanie"))
        self.btn_start.clicked.connect(self.start)
        footer = QFrame()
        footer.setObjectName("footerBar")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 10, 20, 10)
        fl.setSpacing(16)
        cap = QVBoxLayout()
        cap.setSpacing(2)
        self.start_caption = label(tr("Rozpocznij nagrywanie"), "headline")
        cap.addWidget(self.start_caption)
        # „Rozpocznij: Teraz | O godzinie” (2.3) – domyślnie zawsze „Teraz”
        from .schedule_view import TimePicker
        self.when_seg = SegmentedControl([tr("Teraz"), tr("O godzinie")])
        self.when_seg.changed.connect(self._when_changed)
        self.when_picker = TimePicker()
        self.when_hint = label("", "footnote")
        self.when_picker.use_external_hint(self.when_hint)
        self.when_row = QWidget()
        wr = QVBoxLayout(self.when_row)
        wr.setContentsMargins(0, 2, 0, 2)
        wr.setSpacing(3)
        wr.addWidget(hbox(label(tr("Rozpocznij:"), "footnote"), self.when_seg, self.when_picker, "stretch", spacing=8))
        wr.addWidget(self.when_hint)
        show_if(self.when_picker, False)
        show_if(self.when_hint, False)
        cap.addWidget(self.when_row)
        self.setup_status = label(tr("Nagrywanie możesz zakończyć w dowolnym momencie."), "footnote", wrap=True)
        self.setup_status.setMaximumWidth(420)
        cap.addWidget(self.setup_status)
        self.btn_create = QPushButton(tr("Utwórz notatkę"))
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
        first = "av" if LIVE_RECORDING else "files"
        self.modes[first].setChecked(True)
        self.set_mode(first)
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
        b_add_a = QPushButton(tr("Dodaj nagranie…"))
        set_icon(b_add_a, "plus", "text2", 14)
        b_add_a.clicked.connect(self._pick_audio)
        b_del_a = QPushButton(tr("Usuń"))
        b_del_a.setObjectName("plain")
        b_del_a.clicked.connect(lambda: [self.audio_files.takeItem(self.audio_files.row(i))
                                         for i in self.audio_files.selectedItems()])
        self.btn_file_roi = QPushButton(tr("Obszar slajdu…"))
        self.btn_file_roi.setObjectName("plain")
        set_icon(self.btn_file_roi, "crop", "text2", 14)
        self.btn_file_roi.setToolTip(tr("Zaznacz, w której części filmu jest slajd (bez kamerki prowadzącego i czatu)"))
        self.btn_file_roi.clicked.connect(lambda: self._edit_file_roi(self.audio_files.currentItem()))
        self.btn_file_roi.setEnabled(False)
        self.audio_files.currentItemChanged.connect(
            lambda it, _p: self.btn_file_roi.setEnabled(it is not None and self._is_video_item(it)))
        self.audio_files.itemDoubleClicked.connect(self._edit_file_roi)
        ga = GroupSection(tr("Nagranie"), tr("Dyktafon z iPhone'a (.m4a), mp3, wav albo wideo (mp4, mov). Kilka plików = kolejne "
                                      "części jednego wykładu (w podanej kolejności). Pliki możesz też przeciągnąć tutaj."))
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
        b_add_p = QPushButton(tr("Dodaj zdjęcia…"))
        set_icon(b_add_p, "photos", "text2", 14)
        b_add_p.clicked.connect(self._pick_photos)
        b_del_p = QPushButton(tr("Usuń"))
        b_del_p.setObjectName("plain")
        b_del_p.clicked.connect(lambda: [self.photo_files.takeItem(self.photo_files.row(i))
                                         for i in self.photo_files.selectedItems()])
        self.straighten_cb = ToggleSwitch(True)
        gp = GroupSection(tr("Zdjęcia slajdów (opcjonalnie)"),
                          tr("Zdjęcia z telefonu (JPG, HEIC, PNG). Każde zostanie dopasowane do miejsca w nagraniu – po "
                          "godzinie zrobienia zdjęcia, a gdy się nie da, po treści slajdu. Bez nagrania notatka powstanie "
                          "z samych zdjęć."))
        wp = QWidget()
        lp = QVBoxLayout(wp)
        lp.setContentsMargins(12, 10, 12, 10)
        lp.addWidget(self.photo_files)
        lp.addWidget(hbox(b_add_p, b_del_p, "stretch"))
        gp.add(wp)
        gp.add_row(tr("Wyprostuj zdjęcia"), self.straighten_cb, tr("Wykrywa slajd na zdjęciu i prostuje perspektywę."))
        v.addWidget(ga)
        v.addWidget(gp)
        self.files_box = box
        self.setAcceptDrops(True)
        return box

    def _pick_audio(self):
        from pathlib import Path as _P
        from ..jobs import AUDIO_EXT
        pat = " ".join(f"*{e}" for e in AUDIO_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Wybierz nagranie"), str(_P.home()),
                                                tr("Nagrania ({pat});;Wszystkie pliki (*.*)", pat=pat))
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
            title = tr("Zaznacz obszar slajdu") + (f" ({k}/{len(items)})" if len(items) > 1 else "")
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
            it.setText(_P(path).name + (tr("  ·  slajd: zaznaczony obszar") if roi else tr("  ·  slajd: cały obraz")))
        return ok

    def _pick_photos(self):
        from pathlib import Path as _P
        from ..photos import PHOTO_EXT
        pat = " ".join(f"*{e}" for e in PHOTO_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Wybierz zdjęcia slajdów"), str(_P.home()),
                                                tr("Zdjęcia ({pat});;Wszystkie pliki (*.*)", pat=pat))
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
        if getattr(self, "ollama_banner", None) is not None:      # inny rodzaj = inne potrzebne modele
            self.ollama_banner.refresh()
        rec = mode in ("av", "audio", "slides")
        self.g_audio.setVisible(mode in ("av", "audio"))
        self.g_slides.setVisible(mode in ("av", "slides"))
        self.files_box.setVisible(mode == "files")
        self.row_live.setVisible(mode in ("av", "audio"))
        self.row_live_notes.setVisible(mode in ("av", "audio"))
        self.btn_start.setVisible(rec)
        self.btn_create.setVisible(not rec)
        self.start_caption.setVisible(rec)
        show_if(self.when_row, rec and LIVE_RECORDING)
        self._update_start_caption()
        self.setup_status.setText({
            "av": tr("Nagrywanie możesz zakończyć w dowolnym momencie."),
            "audio": tr("Nagrywanie możesz zakończyć w dowolnym momencie."),
            "slides": tr("Notatka powstanie z tekstu na slajdach (bez dźwięku)."),
            "files": tr("Transkrypcja i notatki zrobią się w tle – postęp zobaczysz w bibliotece."),
        }[mode])
        if mode in ("av", "slides") and self._preview_img is None:
            QTimer.singleShot(50, self._video_changed)
        self._update_perms()

    # ------------------------------------------------------------------ zgody macOS
    def _update_perms(self):
        if self.perm_panel is None:
            return
        from ..mac_permissions import needed
        cur = self.audio_picker.current()
        self.perm_panel.set_needed(needed(self.mode, cur.kind if cur is not None else None))

    def _perms_changed(self):
        """Po udzieleniu zgody: lista okien i podgląd ekranu są już dostępne."""
        if self.session is None:
            self.refresh_video()

    def _restart_app(self):
        w = self.window()
        if hasattr(w, "_restart_after_update"):
            w._restart_after_update()

    def _mac_permissions_ok(self, audio, video) -> bool:
        """Przed startem nagrywania na Macu: brak zgody = nagranie ciszy albo pustego ekranu – lepiej powiedzieć od razu.
        Gdy macOS jeszcze nie pytał, prośba pojawi się sama przy starcie."""
        if not IS_MAC:
            return True
        from .. import mac_permissions as mp
        kinds = mp.needed(self.mode, audio.kind if audio is not None else None)
        if video is None and mp.SCREEN in kinds:
            kinds.remove(mp.SCREEN)
        for kind in kinds:
            if mp.status(kind) != mp.DENIED:
                continue
            if kind == mp.SCREEN:
                mp.request(kind)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("Potrzebna zgoda macOS"))
            box.setText(mp.TITLE[kind])
            box.setInformativeText(mp.WHY[kind] + "\n\n" + mp.WHERE[kind])
            open_btn = box.addButton(tr("Otwórz Ustawienia systemowe"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Anuluj"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                mp.open_settings(kind)
            return False
        return True

    def create_from_files(self):
        audio = [self.audio_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.audio_files.count())]
        photos = [self.photo_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.photo_files.count())]
        rois = {}
        for i in range(self.audio_files.count()):
            it = self.audio_files.item(i)
            if it.data(self._ROI_ROLE):
                rois[it.data(Qt.ItemDataRole.UserRole)] = tuple(it.data(self._ROI_ROLE))
        if not audio and not photos:
            QMessageBox.information(self, tr("Nowa notatka"), tr("Dodaj nagranie albo zdjęcia slajdów."))
            return
        subject = self.subject.currentText().strip()
        self.settings.last_subject = subject
        self.settings.save()
        if self.continue_lecture is not None:
            lecture = self.continue_lecture
            if lecture.meta.make_flashcards != self.cards_cb.isChecked():
                lecture.meta.make_flashcards = self.cards_cb.isChecked()
                lecture.save_meta()
        else:
            lecture = Lecture.create(self.settings.library_path(), self.title.text(), subject)
            lecture.meta.kind = "files"
            lang = self.lang_combo.currentData()
            if lang not in ("", "auto"):
                lecture.meta.language = lang
            lecture.meta.notes_language = self._remember_notes_lang()
            lecture.meta.make_flashcards = self._remember_cards()
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
        self.rec_label = label(tr("NAGRYWANIE"), "recLabel")
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
        self.meter.setToolTip(tr("Poziom dźwięku – powinien się ruszać, gdy prowadzący mówi"))
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
        self.btn_mark = QPushButton(tr("Zaznacz ważne"))
        self.btn_mark.setObjectName("mark")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setToolTip(tr("Zaznacz ważny fragment (Ctrl+M): kliknij, gdy się zaczyna – zaznaczenie obejmie też "
                                 "ostatnie ~20 s – i kliknij ponownie, gdy się kończy."))
        set_icon(self.btn_mark, "highlighter", "text", 16)
        self.btn_mark.toggled.connect(self._toggle_mark)
        self.btn_mark_kind = QToolButton()
        self.btn_mark_kind.setObjectName("icon")
        self.btn_mark_kind.setToolTip(tr("Rodzaj zaznaczenia"))
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
        self.btn_pause.setToolTip(tr("Pauza – dźwięk, transkrypcja i slajdy się zatrzymują, czas stoi"))
        self.btn_pause.setFixedSize(46, 44)
        set_icon(self.btn_pause, "pause", "text", 18)
        self.btn_pause.toggled.connect(self._toggle_pause)
        self.btn_stop = QPushButton(tr("Zakończ"))
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setToolTip(tr("Zakończ nagrywanie – notatki zrobią się same"))
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
        # wąskie okno: zmiana źródeł i „Wstrzymaj slajdy” schowane w menu „⋯”
        self.btn_more = QToolButton()
        self.btn_more.setObjectName("icon")
        self.btn_more.setToolTip(tr("Źródła i slajdy"))
        self.btn_more.setAccessibleName(tr("Źródła i slajdy"))
        self.btn_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_more.setFixedSize(40, 40)
        set_icon(self.btn_more, "more", "text", 18)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.btn_more)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.btn_more.setMenu(self.more_menu)
        self.btn_more.hide()
        tl.addWidget(self.btn_more)
        top.addLayout(info, 1)
        self.top_tools_slot = QHBoxLayout()
        top.addLayout(self.top_tools_slot)
        fv.addLayout(top)
        self.bottom_tools_slot = QHBoxLayout()
        fv.addLayout(self.bottom_tools_slot)
        # źródła w trakcie nagrywania: [Dźwięk: Teams ▾] [Slajdy: Monitor 1 ▾] [Wstrzymaj slajdy]
        self.btn_src_audio = QPushButton("")
        self.btn_src_audio.setObjectName("chipBtn")
        set_icon(self.btn_src_audio, "speaker", "accent_text", 14)
        self.btn_src_audio.clicked.connect(self._switch_audio)
        self.btn_src_video = QPushButton("")
        self.btn_src_video.setObjectName("chipBtn")
        set_icon(self.btn_src_video, "display", "accent_text", 14)
        self.btn_src_video.clicked.connect(self._switch_video)
        self.btn_hold = QPushButton(tr("Wstrzymaj slajdy"))
        self.btn_hold.setObjectName("chipBtn")
        self.btn_hold.setCheckable(True)
        set_icon(self.btn_hold, "pause", "accent_text", 14)
        self.btn_hold.toggled.connect(self._toggle_hold)
        for b_ in (self.btn_src_audio, self.btn_src_video, self.btn_hold):
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
        self.src_row = hbox(self.btn_src_audio, self.btn_src_video, self.btn_hold, "stretch", spacing=8)
        fv.addWidget(self.src_row)
        self._switching = ""             # "audio" / "video" – trwa zmiana źródła
        self._src_names = {"audio": "", "video": ""}
        self._update_hold_tip()
        self.rec_frame = frame
        frame.installEventFilter(self)
        v.addWidget(frame)
        # karta „coś nie działa” po sprawdzeniu przed nagrywaniem (healthcheck)
        from .health_ui import ProblemCard
        self.problem_card = ProblemCard()
        self.problem_card.action.connect(self._health_action)
        self.problem_card.proceed.connect(self._health_proceed)
        self.problem_card.cancel.connect(self._health_cancel)
        self.problem_card.shown.connect(self._problem_shown)
        # karta dostaje całe miejsce pod paskiem (z przewijaniem) – panele wracają po decyzji
        self.problem_scroll = QScrollArea()
        self.problem_scroll.setObjectName("page")
        self.problem_scroll.setWidgetResizable(True)
        self.problem_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ps_host = QWidget()
        ps_lay = QVBoxLayout(ps_host)
        ps_lay.setContentsMargins(0, 0, 0, 0)
        ps_lay.addWidget(self.problem_card)
        ps_lay.addStretch(1)
        self.problem_scroll.setWidget(ps_host)
        self.problem_scroll.hide()
        # zaplanowane nagrywanie (2.3): odliczanie na środku zamiast paneli; karta problemu może stać pod spodem
        from .schedule_view import WaitPanel
        self.wait_panel = WaitPanel()
        self.wait_panel.start_now.connect(lambda: self._plan_fire(now=True))
        self.wait_panel.change_time.connect(self._plan_change_time)
        self.wait_panel.cancel.connect(lambda: self._cancel_plan(tr("Zaplanowane nagrywanie anulowane.")))
        self.wait_panel.answered.connect(self._plan_answer)
        self.wait_panel.hide()
        v.addWidget(self.wait_panel, 1)
        v.addWidget(self.problem_scroll, 1)
        sc = QShortcut(QKeySequence("Ctrl+M"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(lambda: self.session is not None and self.btn_mark.isVisible() and self.btn_mark.toggle())
        sc2 = QShortcut(QKeySequence("Ctrl+Shift+S"), self)       # na Macu Qt zamienia Ctrl na ⌘
        sc2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc2.activated.connect(self._hold_shortcut)

        self.autostop = QFrame()
        self.autostop.setObjectName("warnBanner")
        ab = QHBoxLayout(self.autostop)
        ab.setContentsMargins(16, 10, 12, 10)
        self.autostop_text = label("", "headline", wrap=True)
        b_keep = QPushButton(tr("Nagrywaj dalej"))
        b_keep.setObjectName("primary")
        b_keep.clicked.connect(self._autostop_cancel)
        b_now = QPushButton(tr("Zakończ teraz"))
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
        self.t_follow = QPushButton(tr("↓ Na bieżąco"))
        self.t_follow.setObjectName("plain")
        self.t_follow.clicked.connect(lambda: self._scroll_transcript(True))
        self.t_follow.hide()
        h, _ = col_head(tr("TRANSKRYPCJA"), self.t_follow)
        ct.addLayout(h)
        ct.addWidget(self.transcript, 1)

        # 2) notatki na żywo + pytania
        self.live_notes_view = Reader(max_width=760, pad=22)
        self.live_notes_view.internal_link.connect(lambda a: None)
        self.live_notes_status = label("", "caption", wrap=True)
        self.live_ask_field = QLineEdit()
        self.live_ask_field.setObjectName("askInput")
        self.live_ask_field.setPlaceholderText(tr("Zapytaj o to, co już padło na wykładzie…  (Ctrl K)"))
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
        self.btn_ask_back = QPushButton(tr("Notatki"))
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
        h, self.notes_head = col_head(tr("NOTATKI NA ŻYWO"))
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
        self.btn_live_roi = QPushButton(tr("Zmień obszar slajdu"))
        self.btn_live_roi.setObjectName("plain")
        self.btn_live_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        set_icon(self.btn_live_roi, "crop", "text2", 14)
        self.btn_live_roi.setToolTip(tr("Zaznacz na nowo, gdzie na ekranie jest slajd – nagrywanie trwa dalej, "
                                     "złapane slajdy zostają"))
        self.btn_live_roi.clicked.connect(self._change_live_roi)
        h, self.slides_title = col_head(tr("SLAJDY · 0"), self.btn_live_roi)
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
        self.live_seg = SegmentedControl([tr("Transkrypcja"), tr("Notatki AI"), tr("Zapytaj")], style="tabs")
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
        self.live_panels = QWidget()             # panele transkrypcji / notatek / slajdów (chowane pod kartą problemu)
        self.live_body = QVBoxLayout(self.live_panels)
        self.live_body.setContentsMargins(0, 0, 0, 0)
        self.live_body.setSpacing(10)
        self.live_body.addWidget(split, 1)
        self.live_body.addWidget(self.alt, 1)
        v.addWidget(self.live_panels, 1)
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
            # przyciski: w nagłówku albo w dolnym pasku (56 px); w oczekiwaniu na start pasek jest pusty
            if narrow:
                self.bottom_lay.addWidget(self.tools_b)
                self.live_v.addWidget(self.bottom_bar)
                show_if(self.bottom_bar, self._plan is None)
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
            self.live_sub.setVisible(not narrow and bool(self.live_sub.text()))
            self._update_src_buttons()
        # zegar nigdy nie jest ściskany (w wąskim oknie obok stoi jeszcze przycisk „⋯”); czcionka zależy od motywu
        self.time_label.ensurePolished()
        self.time_label.setMinimumWidth(self.time_label.fontMetrics().horizontalAdvance(
            self.time_label.text() or "00:00") + 6)
        self._place_tools()

    # ------------------------------------------------------------------ zmiana źródeł w trakcie nagrywania
    @staticmethod
    def _hold_keys() -> str:
        return "⌘⇧S" if IS_MAC else "Ctrl+Shift+S"

    def _update_hold_tip(self):
        held = self.btn_hold.isChecked()
        self.btn_hold.setText(tr("Wznów slajdy") if held else tr("Wstrzymaj slajdy"))
        set_icon(self.btn_hold, "play" if held else "pause", "accent_text", 14)
        self.btn_hold.setToolTip(
            tr("Wznów zrzuty slajdów ({keys}). Bieżący ekran porówna się z ostatnim slajdem – nic się nie zdubluje.",
               keys=self._hold_keys()) if held else
            tr("Wstrzymaj zrzuty slajdów ({keys}) – np. gdy prowadzący pokazuje coś, czego nie chcesz w notatkach, "
               "albo gdy przełączasz okna. Dźwięk i transkrypcja nagrywają się dalej.", keys=self._hold_keys()))

    @staticmethod
    def _elide_chip(b: QPushButton, text: str, max_w: int = 250):
        fm = b.fontMetrics()
        avail = max_w - b.iconSize().width() - 36
        b.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, avail))
        b.setMaximumWidth(max_w)

    def _update_src_buttons(self):
        """Napisy i widoczność przycisków źródeł: w szerokim i średnim trybie rząd pod tytułem, w wąskim menu „⋯”."""
        if not hasattr(self, "src_row"):
            return
        s = self.session
        running = s is not None and self._pending is None
        has_audio = bool(s is not None and getattr(s, "recorder", None) is not None)
        has_video = bool(s is not None and getattr(s, "slide_rec", None) is not None)
        starting = self._pending is not None
        p = self._pending or {}
        show_audio = has_audio or (starting and p.get("audio") is not None)
        show_video = has_video or (starting and p.get("video") is not None)
        narrow = self._live_mode == "narrow"
        a_name, v_name = self._src_names["audio"], self._src_names["video"]
        self._elide_chip(self.btn_src_audio, tr("Przełączam dźwięk…") if self._switching == "audio" else
                         tr("Dźwięk: {name}", name=a_name))
        self._elide_chip(self.btn_src_video, tr("Przełączam slajdy…") if self._switching == "video" else
                         tr("Slajdy: {name}", name=v_name))
        self.btn_src_audio.setToolTip(tr("Nagrywasz dźwięk z: {name}. Kliknij, żeby przełączyć na inne źródło "
                                         "(np. z Teams na mikrofon) – nagranie się nie przerwie.", name=a_name))
        self.btn_src_video.setToolTip(tr("Slajdy z: {name}. Kliknij, żeby wybrać inny ekran albo okno – złapane "
                                         "slajdy zostają.", name=v_name))
        busy = bool(self._switching)
        self.btn_src_audio.setEnabled(running and has_audio and not busy)
        self.btn_src_video.setEnabled(running and has_video and not busy)
        self.btn_hold.setEnabled(running and has_video)
        show_if(self.btn_src_audio, show_audio)
        show_if(self.btn_src_video, show_video)
        show_if(self.btn_hold, show_video)
        show_if(self.src_row, (show_audio or show_video) and not narrow)
        show_if(self.btn_more, (show_audio or show_video) and narrow)
        self.btn_more.setEnabled(running)

    def _fill_more_menu(self):
        """Menu „⋯” w wąskim oknie – te same polecenia co rząd przycisków w szerszym."""
        from PySide6.QtGui import QAction
        m = self.more_menu
        m.clear()
        s = self.session
        busy = bool(self._switching)
        if s is not None and s.recorder is not None:
            a = QAction(tr("Dźwięk: {name}…", name=self._src_names["audio"]), m)
            a.setEnabled(not busy)
            a.triggered.connect(self._switch_audio)
            m.addAction(a)
        if s is not None and s.slide_rec is not None:
            a = QAction(tr("Slajdy: {name}…", name=self._src_names["video"]), m)
            a.setEnabled(not busy)
            a.triggered.connect(self._switch_video)
            m.addAction(a)
            a = QAction(tr("Zmień obszar slajdu"), m)
            a.triggered.connect(self._change_live_roi)
            m.addAction(a)
            m.addSeparator()
            # skrót tylko jako podpis (po \t) – działa przez QShortcut, więc bez konfliktu „niejednoznaczny skrót”
            a = QAction((tr("Wznów slajdy") if self.btn_hold.isChecked() else tr("Wstrzymaj slajdy"))
                        + "\t" + self._hold_keys(), m)
            a.triggered.connect(self.btn_hold.toggle)
            m.addAction(a)

    def _hold_shortcut(self):
        s = self.session
        if s is not None and s.slide_rec is not None and self.stack.currentIndex() == 1 and self.btn_hold.isEnabled():
            self.btn_hold.toggle()

    def _toggle_hold(self, on: bool):
        s = self.session
        self._update_hold_tip()
        if s is None or s.slide_rec is None:
            self.cur_slide.set_held(False)
            return
        s.hold_slides(on)
        self.cur_slide.set_held(on, tr("wznów: {keys}", keys=self._hold_keys()))
        self._set_status(tr("Slajdy wstrzymane – dźwięk i transkrypcja nagrywają się dalej. Wznów przyciskiem "
                            "„Wznów slajdy” ({keys}).", keys=self._hold_keys()) if on else
                         tr("Slajdy wznowione – jeśli na ekranie jest ten sam slajd co przed przerwą, nie zapisze się "
                            "drugi raz."))

    def _switch_audio(self):
        s = self.session
        if s is None or s.recorder is None or self._switching:
            return
        from .source_switch import AudioSwitchDialog
        dlg = AudioSwitchDialog(s.audio_info, self)
        ok = dlg.exec()
        info = dlg.result_info() if ok else None
        monitor = getattr(dlg.picker, "monitor", None)
        dlg.picker.stop_monitor()
        if info is None or self.session is not s:
            return
        old = s.audio_info
        self._switching = "audio"
        self._update_src_buttons()
        self._set_status(tr("Przełączam dźwięk na „{name}”… Nagrywanie trwa.", name=short_audio(info.label)))

        def work():
            if monitor is not None:         # zwolnij mikrofon miernika, zanim otworzy go nagrywanie
                monitor.stop()
            return s.switch_audio(info)

        def done(entry):
            self._switching = ""
            if self.session is not s:
                return
            self._src_names["audio"] = short_audio(info.label)
            self._titems.append({"kind": "note", "text": switch_note(entry)})
            self._render_transcript()
            self._update_src_buttons()
            self._set_status(tr("Dźwięk nagrywa się teraz z „{name}”.", name=short_audio(info.label)))

        def fail(e):
            self._switching = ""
            if self.session is not s:
                return
            self._update_src_buttons()
            prev = short_audio(old.label) if old else ""
            self._set_status(tr("Nie udało się przełączyć dźwięku – nagrywanie trwa dalej z „{name}”.", name=prev))
            QMessageBox.warning(self, tr("Zmiana źródła dźwięku"),
                                tr("Nie udało się otworzyć „{name}”:\n{e}\n\nNagrywanie trwa dalej z „{prev}”.",
                                   name=short_audio(info.label), e=e, prev=prev))
        run_async(work, done, fail)

    def _switch_video(self):
        s = self.session
        if s is None or s.slide_rec is None or self._switching:
            return
        from .source_switch import VideoSwitchDialog
        dlg = VideoSwitchDialog(s.video_info, self.rois, self._video_key, self)
        if not dlg.exec() or self.session is not s:
            return
        info, roi = dlg.result()
        if info is None:
            return
        self.rois = dlg.rois
        self._switching = "video"
        self._update_src_buttons()
        self._set_status(tr("Przełączam slajdy na „{name}”…", name=short_video(info)))

        def done(entry):
            self._switching = ""
            if self.session is not s:
                return
            self._live_roi_key = self._video_key(info)
            self._src_names["video"] = short_video(info)
            self._titems.append({"kind": "note", "text": switch_note(entry)})
            self._render_transcript()
            self._update_src_buttons()
            self.video_status.setText("")
            self._set_status(tr("Slajdy wykrywają się teraz z „{name}”. Wcześniejsze slajdy zostały.",
                                name=short_video(info)) +
                             (" " + tr("Zrzuty są wstrzymane – wznów je, gdy będziesz gotowy.") if self.btn_hold.isChecked() else ""))

        def fail(e):
            self._switching = ""
            if self.session is not s:
                return
            self._update_src_buttons()
            QMessageBox.warning(self, tr("Zmiana ekranu ze slajdami"),
                                tr("Nie udało się przełączyć na „{name}”:\n{e}\n\nSlajdy dalej wykrywają się z "
                                   "poprzedniego źródła.", name=short_video(info), e=e))
        run_async(lambda: s.switch_video(info, roi), done, fail)

    def _pause_text(self):
        narrow = self._live_mode == "narrow"
        paused = self.is_paused()
        self.btn_pause.setText((tr("Wznów") if paused else tr("Pauza")) if narrow else "")

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
            self.subject.setItemData(k, tr("Przedmiot"), C_TAG)
        self.subject.setEditText(cur)

    def refresh_audio(self):
        """Lista źródeł dźwięku jest zbierana w tle (wyliczanie sesji audio potrafi trwać)."""
        self.audio_picker.refresh()

    def _apply_audio(self):
        if self._plan is not None:          # zaplanowane nagrywanie czeka na aplikację (np. Teams)?
            self._plan_sources_changed()
        self._match_want_audio()
        active = any(s.kind == "process" and (s.active or s.group == "meeting") for s in self.audio_picker.sources)
        if active == self._audio_active:       # lista odświeża się co kilka sekund – podpis zmieniamy tylko przy zmianie
            return
        self._audio_active = active
        self.setup_status.setText(tr("Nagrywanie możesz zakończyć w dowolnym momencie.") if active else
                                  tr("Żadna aplikacja teraz nie gra – włącz dźwięk wykładu i odśwież listę."))

    def showEvent(self, e):
        super().showEvent(e)
        if LIVE_RECORDING and not self._preloaded:
            self._preloaded = True
            QTimer.singleShot(1200, self._preload)

    @staticmethod
    def _preload():
        """Import bibliotek nagrywania i rozpoznawania mowy w tle (sam import, bez modelu) – po wejściu na
        „Nowa notatka”, żeby późniejszy start nagrywania nie czekał na wczytanie plików z dysku."""
        def work():
            steps = StepTimer("Wstępne wczytanie bibliotek")  # i18n: nie
            for name in ("ctranslate2", "faster_whisper", "app.session"):
                try:
                    __import__(name)
                    steps.step(name)
                except Exception as e:  # noqa: BLE001
                    steps.step(f"{name} – błąd {e.__class__.__name__}")  # i18n: nie
            steps.done()
        threading.Thread(target=work, name="Preload", daemon=True).start()

    def refresh_video(self):
        prev = self.video_combo.currentText()
        if LIVE_RECORDING:
            from ..screen_capture import list_monitors, list_windows
            self._video_sources = list_monitors() + list_windows()
        else:
            self._video_sources = []
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

        from ..screen_capture import make_grabber

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
                self.roi_label.setText(tr("Nie udało się pobrać podglądu. ") + (err or ""))
            self._render_preview()
        run_async(work, done)

    def _grab_now(self):
        info = self._current_video()
        if not info or info.kind == "none":
            return
        from ..screen_capture import make_grabber
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
            self.roi_label.setText(tr("Nie udało się pobrać podglądu. ") + (getattr(g, "last_error", "") or ""))
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
        self.roi_label.setText(tr("Slajdy będą wykrywane tylko w zaznaczonym obszarze.") if roi else
                               tr("Wykrywanie obejmuje cały obraz. Jeśli obok slajdu jest kamerka lub czat, zaznacz sam slajd."))
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
            QMessageBox.information(self, tr("Obszar slajdu"), tr("Nie ma jeszcze zrzutu ekranu – spróbuj za chwilę."))
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
        self.video_status.setText(tr("Obszar slajdu zmieniony – kolejne slajdy będą wykrywane w nowym obszarze.")
                                  if roi else tr("Slajdy są teraz wykrywane na całym obrazie."))

    def _clear_roi(self):
        info = self._current_video()
        if info:
            self.rois.pop(self._video_key(info), None)
            self._render_preview()

    # ------------------------------------------------------------------ język notatek
    def set_notes_lang(self, code: str):
        i = self.notes_lang_combo.findData(code or "")
        self.notes_lang_combo.setCurrentIndex(max(0, i))

    def _remember_notes_lang(self) -> str:
        """Wybrany język notatek ("" = jak wykład) – zapamiętany w last_rec na następny raz."""
        code = self.notes_lang_combo.currentData() or ""
        lr = self.settings.last_rec or {}
        lr["notes_language"] = code
        self.settings.last_rec = lr
        self.settings.save()
        return code

    def _remember_cards(self) -> bool:
        """„Zrób fiszki z tego wykładu” – zapamiętane w last_rec na następny raz."""
        on = self.cards_cb.isChecked()
        lr = self.settings.last_rec or {}
        lr["make_flashcards"] = on
        self.settings.last_rec = lr
        self.settings.save()
        return on

    # ------------------------------------------------------------------ nagraj jak ostatnio
    def quick_label(self) -> str:
        """„Teams + Monitor 1” – co wypełni Ctrl+Shift+R (pusty tekst, gdy jeszcze nic nie nagrywano)."""
        lr = self.settings.last_rec or {}
        parts = [x.get("label", "").lstrip("🔊🖥🎤 ") for x in (lr.get("audio"), lr.get("video")) if x]
        return " + ".join(p for p in parts if p)

    def quick_prepare(self):
        """Wypełnia formularz nowej notatki ostatnimi ustawieniami. Nagrywanie startuje dopiero po „Start”.
        Źródło, którego teraz nie ma, jest opisane pod swoim polem (i wybierze się samo po odświeżeniu listy)."""
        if self.session is not None or self._plan is not None:
            return
        self.cancel_continue()
        self.title.clear()
        if not LIVE_RECORDING:        # Mac: bez nagrywania na żywo – nowa notatka z pliku
            self.modes["files"].setChecked(True)
            return
        lr = self.settings.last_rec or {}
        mode = lr.get("mode")
        if mode not in self.modes:
            keys = "⌘⇧R" if IS_MAC else "Ctrl+Shift+R"
            self._set_status(tr("Najpierw nagraj coś raz zwykłym sposobem – potem {keys} wypełni te same ustawienia.", keys=keys))
            return
        self.modes[mode].setChecked(True)
        self.subject.setEditText(lr.get("subject", self.settings.last_subject) or "")
        self.set_notes_lang(lr.get("notes_language", self.settings.notes_language))
        self.cards_cb.setChecked(bool(lr.get("make_flashcards", self.settings.auto_flashcards)))
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

    def _find_audio(self, want: dict | None) -> int:
        """Pozycja źródła {kind, exe, device} na obecnej liście (−1 = nie ma). Aplikacja po nazwie pliku (.exe), nie
        po PID – po ponownym uruchomieniu Teams to wciąż „to samo” źródło. Grająca ma pierwszeństwo."""
        if not want:
            return -1
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
        return idx

    def _match_want_audio(self):
        want = self._want_audio
        if not want:
            self._field_warn(self.row_audio, "")
            return
        idx = self._find_audio(want)
        if idx >= 0:
            self.audio_picker.set_current(idx)
            self._field_warn(self.row_audio, "")
        else:
            name = want.get("label") or tr("ostatnie źródło dźwięku")
            self._field_warn(self.row_audio, tr("Ostatnio było „{name}”, teraz nie gra – włącz wykład i odśwież listę.", name=name))

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
            name = want.get("label") or tr("ostatni ekran")
            todo = tr("otwórz to okno") if str(want.get("key", "")).startswith("window:") else tr("podłącz ten ekran")
            self._field_warn(self.row_video, tr("Ostatnio było „{name}”, teraz jest niedostępne – {todo} i odśwież listę.", name=name, todo=todo))

    # ------------------------------------------------------------------ nagrywanie
    def is_recording(self) -> bool:
        return self.session is not None or self._pending is not None

    def start(self):
        """Kliknięcie przycisku startu. „Teraz”: od razu _launch. „O godzinie”: te same ustawienia zostają
        zapamiętane w planie (tylko w pamięci), a _launch ruszy o czasie."""
        if self.session is not None or self._pending is not None or self._plan is not None or not LIVE_RECORDING:
            return
        scheduled = self.when_seg.current() == 1 and not self.when_row.isHidden()
        cfg = self._collect(scheduled)
        if cfg is None:
            return
        if scheduled:
            self._schedule(cfg, self.when_picker.when())
            return
        self._launch(cfg)

    def _collect(self, scheduled: bool = False) -> dict | None:
        """Ustawienia nagrywania z formularza (z ostrzeżeniem, gdy czegoś brakuje). Przy planowaniu źródło
        „jak ostatnio”, którego teraz nie ma (np. Teams jeszcze zamknięty), też się liczy – plan na nie poczeka."""
        mode = self.mode
        audio = audio_spec = None
        if mode in ("av", "audio"):
            want = self._want_audio
            if scheduled and want and self._find_audio(want) < 0:
                audio_spec = dict(want)
            else:
                audio = self.audio_picker.current()
                if audio is None:
                    QMessageBox.warning(self, tr("Nagrywanie"), tr("Wybierz źródło dźwięku."))
                    return None
                audio_spec = self._audio_spec(audio)
        video = video_spec = None
        if mode in ("av", "slides"):
            want = self._want_video
            if scheduled and want and not any(self._video_key(v) == want.get("key") for v in self._video_sources):
                video_spec = dict(want)
            else:
                video = self._current_video()
                if video and video.kind == "none":
                    video = None
                if video is not None:
                    video_spec = {"key": self._video_key(video), "label": short_video(video)}
        if mode == "slides" and video_spec is None:
            QMessageBox.warning(self, tr("Nagrywanie"), tr("Wybierz ekran albo okno ze slajdami."))
            return None
        from types import SimpleNamespace
        a_check = audio if audio is not None else (SimpleNamespace(kind=audio_spec["kind"]) if audio_spec else None)
        if not self._mac_permissions_ok(a_check, video if video is not None else video_spec):
            return None
        return {"mode": mode, "audio": audio, "audio_spec": audio_spec, "video": video, "video_spec": video_spec,
                "roi": self.rois.get(video_spec["key"]) if video_spec else None,
                "title": self.title.text(), "subject": self.subject.currentText().strip(),
                "notes_language": self.notes_lang_combo.currentData() or "",
                "make_flashcards": self.cards_cb.isChecked(),
                "language": self.lang_combo.currentData(),
                "live": self.live_cb.isChecked(),
                "live_notes": self.live_cb.isChecked() and self.live_notes_cb.isChecked(),
                "continue_lecture": self.continue_lecture}

    @staticmethod
    def _audio_spec(audio) -> dict:
        return {"kind": audio.kind, "exe": audio.exe, "label": short_audio(audio.label), "device": audio.device_index}

    def _start_busy(self, cont) -> bool:
        """Poprzednie (anulowane) uruchamianie jeszcze się sprząta – nowe musi chwilę poczekać."""
        self._cleanups = [(th, f) for th, f in self._cleanups if th.is_alive()]
        busy_folder = cont is not None and any(f == cont.folder for _th, f in self._cleanups)
        return busy_folder or (self._start_thread is not None and self._start_thread.is_alive())

    def _launch(self, cfg: dict, late_min: int = 0) -> bool:
        """Start nagrywania w dwóch krokach – wspólny dla „Teraz” i zaplanowanego. W wątku UI tylko to, co szybkie:
        ustawienia, nowy folder wykładu i przejście na ekran nagrywania w stanie „Uruchamiam nagrywanie…”. Dźwięk,
        ekran, slajdy i silnik mowy uruchamiają się w wątku roboczym – wynik wraca sygnałem start_done
        (_on_start_done). late_min – zaplanowany start po uśpieniu komputera (notka w transkrypcji)."""
        if self.session is not None or self._pending is not None:
            return False
        if self._start_busy(cfg["continue_lecture"]):
            self.setup_status.setText(tr("Kończę poprzednie uruchamianie – spróbuj za chwilę."))
            return False
        steps = StepTimer("Start nagrywania – wątek UI")  # i18n: nie
        mode, audio, video, roi, subject = cfg["mode"], cfg["audio"], cfg["video"], cfg["roi"], cfg["subject"]
        self.settings.last_subject = subject
        self.settings.last_rec = {
            "mode": mode,
            "audio": self._audio_spec(audio) if audio else None,
            "video": ({"key": self._video_key(video), "label": short_video(video)} if video else None),
            "roi": list(roi) if roi else None,
            "subject": subject,
            "notes_language": cfg["notes_language"],
            # kontynuacja pokazuje stan tamtego wykładu – nie zmienia zapamiętanego wyboru dla nowych
            "make_flashcards": bool((self.settings.last_rec or {}).get("make_flashcards", self.settings.auto_flashcards)
                                    if cfg["continue_lecture"] is not None else cfg.get("make_flashcards", False)),
        }
        self.settings.save()
        if audio is not None and hasattr(self.audio_picker, "set_last_used"):
            self.audio_picker.set_last_used(self.settings.last_rec["audio"])
        self._want_audio = self._want_video = None
        self._field_warn(self.row_audio, "")
        self._field_warn(self.row_video, "")
        self.last_rec_changed.emit()
        steps.step("ustawienia")
        lecture = cfg["continue_lecture"]
        continuing = lecture is not None
        pending = {"continuing": continuing, "cancelled": False, "sess": None, "err": "",
                   "audio": audio, "video": video, "subject": subject, "clicked": steps.t0, "late_min": late_min}
        if continuing:
            pending.update(parts_before=[dict(p) for p in (lecture.meta.parts or [])],
                           duration_before=lecture.meta.duration, status_before=lecture.meta.status)
            if "make_flashcards" in cfg and lecture.meta.make_flashcards != bool(cfg["make_flashcards"]):
                lecture.meta.make_flashcards = bool(cfg["make_flashcards"])
                lecture.save_meta()
        else:
            lecture = Lecture.create(self.settings.library_path(), cfg["title"], subject)
            lecture.meta.kind = mode
            lecture.meta.notes_language = cfg["notes_language"]
            lecture.meta.make_flashcards = bool(cfg.get("make_flashcards", False))
            lecture.save_meta()
        pending["lecture"] = lecture
        steps.step("Lecture.create")
        live = cfg["live"]
        live_notes = cfg["live_notes"]
        language = self._language_for(cfg)
        self._pending = pending
        self._show_starting(lecture, audio, video, subject, live and audio is not None, live_notes and audio is not None)
        steps.step("ekran nagrywania")
        cb = dict(on_segments=self.segments_signal.emit,
                  on_slide=lambda ev, path: self.slide_signal.emit(ev.index, ev.is_new, path or "", ev.t, ev.updated),
                  on_status=self.status_signal.emit, on_video_status=self.video_status_signal.emit,
                  on_notes_update=self.notes_update_signal.emit, on_notes_status=self.notes_status_signal.emit)
        settings = self.settings
        monitor = getattr(self.audio_picker, "monitor", None)

        def work():
            sess = None
            try:
                if monitor is not None:          # zwolnij mikrofon miernika, zanim otworzy go nagrywanie
                    monitor.stop()
                from ..session import RecordingSession
                sess = RecordingSession(lecture, settings, audio, video, roi, live_transcription=live,
                                        live_notes=live_notes, language=language, **cb)
                pending["sess"] = sess
                sess.start()
            except Exception as e:  # noqa: BLE001
                log.exception("start")
                pending["err"] = str(e) or e.__class__.__name__
                if sess is not None:
                    try:
                        if sess.slide_rec:
                            sess.slide_rec.stop()
                        if sess.recorder:
                            sess.recorder.stop()
                    except Exception:  # noqa: BLE001
                        log.exception("start: sprzątanie")
            self.start_done.emit(pending)

        self._start_thread = threading.Thread(target=work, name="RecordingStart", daemon=True)
        self._start_thread.start()
        self._attempt = pending
        self._start_healthcheck(pending, audio, video, live_notes)
        steps.done()
        return True

    def _language_for(self, cfg: dict) -> str:
        """Język wykładu dla sesji (kontynuacja trzyma się języka wykrytego wcześniej)."""
        lec = cfg["continue_lecture"]
        lang = (lec.meta.language or cfg["language"]) if lec is not None else cfg["language"]
        return lang or self.settings.language

    def _show_starting(self, lecture, audio, video, subject: str, live: bool, notes_on: bool):
        """Ekran nagrywania od razu po kliknięciu: szkielet paneli, pulsująca kropka, aktywne tylko „Anuluj”."""
        from .live_view import skeleton_html
        t = T()
        self.transcript.clear()
        self.slides.clear()
        self.cur_slide.set_slide(None)
        self.dup_hint.hide()
        self._cur_slide_index = 0
        self._titems, self._tmarks, self._t_follow = [], [], True
        self.slides_title.setText(tr("SLAJDY · 0"))
        self.video_status.setText("")
        self.meter.reset()
        self.time_label.setText("00:00")
        self._live_roi_key = self._video_key(video) if video else None
        self.autostop.hide()
        self.problem_card.set_problems([])
        self.rec_label.setText(tr("URUCHAMIAM NAGRYWANIE…"))
        self.live_title.setText(lecture.meta.title)
        # źródła widać na przyciskach pod tytułem – w podtytule zostaje przedmiot i to, czego nie nagrywamy
        self.live_sub.setText(" · ".join(x for x in [subject, "" if audio else tr("bez dźwięku"),
                                                      "" if video else tr("bez slajdów")] if x))
        self._src_names = {"audio": short_audio(audio.label) if audio else "",
                           "video": short_video(video) if video else ""}
        self._switching = ""
        self.btn_hold.blockSignals(True)
        self.btn_hold.setChecked(False)
        self.btn_hold.blockSignals(False)
        self._update_hold_tip()
        self.cur_slide.set_held(False)
        self._set_status(tr("Uruchamiam nagrywanie…"))
        for w_ in (self.meter, self.btn_mark, self.btn_mark_kind):
            w_.setVisible(audio is not None)
        for b_ in (self.btn_mark, self.btn_mark_kind, self.btn_pause):
            b_.setEnabled(False)
        self.btn_mark.blockSignals(True)
        self.btn_mark.setChecked(False)
        self._set_mark_kind("important")
        self.btn_mark.blockSignals(False)
        self.btn_pause.blockSignals(True)
        self.btn_pause.setChecked(False)
        self.btn_pause.blockSignals(False)
        show_if(self.btn_live_roi, False)
        self.btn_stop.setText(tr("Anuluj"))
        self.btn_stop.setToolTip(tr("Przerwij uruchamianie – nic nie zostanie nagrane"))
        set_icon(self.btn_stop, "xmark", "on_red", 16)
        self.btn_stop.setEnabled(True)
        self._has_text = False
        self._setup_live_panels(lecture, audio is not None, live, notes_on)
        self.live_ask_field.setEnabled(False)
        self.transcript.setHtml(f"<body style='color:{t.text2}'>" + skeleton_html(tr("Pierwszy fragment tekstu pojawi się po około 20–30 sekundach mowy."), tr("TRANSKRYPCJA")) + "</body>")
        self.stack.setCurrentIndex(1)
        self._live_mode = None
        self._update_src_buttons()
        QTimer.singleShot(0, self._relayout_live)
        self._ticks = 0
        self.timer.start()
        self.recording_state.emit(True)

    def _on_start_done(self, pending: dict):
        sess, err = pending.get("sess"), pending.get("err")
        if pending.get("handled"):
            return
        pending["handled"] = True
        if self._pending is pending:
            self._pending = None
        if pending["cancelled"]:            # „Anuluj” w trakcie uruchamiania – zatrzymaj i posprzątaj w tle
            def undo():
                if sess is not None and not err:
                    try:
                        sess.stop()
                    except Exception:  # noqa: BLE001
                        log.exception("anulowanie: stop")
                self._undo_start(pending)
            th = threading.Thread(target=undo, name="RecordingCancel", daemon=True)
            th.start()
            self._cleanups.append((th, pending["lecture"].folder))
            return
        if err:
            self._undo_start(pending)
            self._show_start_failed(pending)
            return
        self._started(sess, pending)

    @staticmethod
    def _undo_start(pending: dict):
        """Sprzątanie po nieudanym / anulowanym starcie: nowy wykład znika, kontynuowany wraca do stanu sprzed próby
        (bez pliku nowej części)."""
        lecture, sess = pending["lecture"], pending.get("sess")
        try:
            if pending["continuing"]:
                m = lecture.meta
                m.parts, m.duration, m.status = (pending["parts_before"], pending["duration_before"],
                                                 pending["status_before"])
                lecture.save_meta()
                new = getattr(sess, "part_file", None) if sess is not None else None
                if new and new not in {p_.get("file") for p_ in pending["parts_before"]}:
                    (lecture.folder / new).unlink(missing_ok=True)
            else:
                shutil.rmtree(lecture.folder, ignore_errors=True)
        except Exception:  # noqa: BLE001
            log.exception("sprzątanie po starcie")

    def _back_to_setup(self):
        """Powrót do ekranu ustawień (start nieudany albo anulowany)."""
        self.timer.stop()
        self.problem_card.set_problems([])
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText(tr("Zakończ"))
        self.btn_stop.setToolTip(tr("Zakończ nagrywanie – notatki zrobią się same"))
        set_icon(self.btn_stop, "stop", "on_red", 16)
        self.stack.setCurrentIndex(0)
        self.recording_state.emit(False)
        if self.audio_picker.isVisible():
            self.audio_picker.start_monitor()

    def _cancel_start(self):
        p = self._pending
        if p is None:
            return
        p["cancelled"] = True
        self._pending = None
        self._back_to_setup()
        self.setup_status.setText(tr("Nagrywanie anulowane."))

    # ------------------------------------------------------------------ zaplanowane nagrywanie (2.3)
    # Plan żyje tylko w pamięci (self._plan). Chwila startu to data i godzina z zegara ściennego; timer co sekundę
    # porównuje ją z datetime.now(), więc uśpienie komputera i zmiana czasu niczego nie rozjeżdżają.
    def has_plan(self) -> bool:
        return self._plan is not None

    def plan_when_text(self) -> str:
        """„o 10:15” / „jutro o 8:15” – np. do pytania przy zamykaniu okna."""
        from .. import schedule as sch
        return sch.when_text(self._plan["at"]) if self._plan else ""

    def _when_changed(self, i: int):
        from .. import schedule as sch
        on = i == 1
        if on:
            self.when_picker.set_time(sch.next_quarter())
        show_if(self.when_picker, on)
        show_if(self.when_hint, on)
        self._update_start_caption()

    def _reset_when(self):
        """Po starcie albo anulowaniu planu formularz wraca do „Teraz”."""
        self.when_seg.buttons[0].setChecked(True)
        self._when_changed(0)

    def _update_start_caption(self):
        scheduled = self.when_seg.current() == 1 and self.mode != "files"
        text = tr("Zaplanuj nagrywanie") if scheduled else (
            tr("Rozpocznij zrzuty slajdów") if self.mode == "slides" else tr("Rozpocznij nagrywanie"))
        self.start_caption.setText(text)
        self.btn_start.setToolTip(text)
        self.btn_start.setAccessibleName(text)
        self.btn_start.set_scheduled(scheduled)

    def _schedule(self, cfg: dict, at):
        """„Zaplanuj nagrywanie”: ekran oczekiwania, od razu sprawdzenie (żeby był czas na naprawę), komputer nie zaśnie."""
        from .. import schedule as sch
        self._plan = {"scheduled": True, "cancelled": False, "cfg": cfg, "at": at, "audio": cfg["audio"],
                      "video": cfg["video"], "warmed": False, "due": False, "late_ok": False, "start_now": False,
                      "retry_at": 0.0, "refreshed": False, "wait_src": False, "last_list": 0.0}
        self._attempt = self._plan
        sch.awake().hold("plan")
        self._show_waiting()
        self._plan_resolve()
        self._plan_check(warm=False)
        self.schedule_state.emit(sch.short_when(at))
        self._plan_timer.start()
        self._plan_tick()                        # pierwszy tick od razu (może też od razu wystartować)
        log.info("Zaplanowane nagrywanie: %s (%s)", at.isoformat(timespec="minutes"), cfg["mode"])

    def _show_waiting(self):
        """Ten sam ekran co nagrywanie: pasek z tytułem na górze, odliczanie na środku zamiast paneli."""
        cfg = self._plan["cfg"]
        cont = cfg["continue_lecture"]
        self.timer.stop()
        self.autostop.hide()
        self.problem_card.set_problems([])
        self.wait_panel.clear_ask()
        self.rec_label.setText(tr("ZAPLANOWANE NAGRYWANIE"))
        self.live_title.setText(cfg["title"].strip() or (cont.meta.title if cont is not None else tr("Nowa notatka")))
        self.live_sub.setText(cfg["subject"])
        self._set_status("")
        self.video_status.setText("")
        self._set_wait_mode(True)
        self.stack.setCurrentIndex(1)

    def _set_wait_mode(self, on: bool):
        show_if(self.wait_panel, on)
        show_if(self.dot, not on)
        show_if(self.tools, not on)
        show_if(self.live_panels, not on and self.problem_card.isHidden())
        if on:
            for w_ in (self.src_row, self.btn_more, self.bottom_bar):
                show_if(w_, False)
        else:
            self._live_mode = None          # przyciski nagrywania wracają na swoje miejsce (także dolny pasek)
            self._relayout_live()
            self._update_src_buttons()

    def _plan_tick(self):
        """Co sekundę (QTimer, bez blokowania): odliczanie, odświeżanie źródeł, przygotowanie ok. 2 min przed, start."""
        import time as _t
        from datetime import datetime
        from .. import schedule as sch
        p = self._plan
        if p is None:
            self._plan_timer.stop()
            return
        left = (p["at"] - datetime.now()).total_seconds()
        mono = _t.monotonic()
        every = 3 if (p["due"] or left < sch.PREPARE_S + 30) else 10
        if mono - p["last_list"] >= every:      # czy aplikacja / okno już są? (lista dźwięku zbiera się w tle)
            p["last_list"] = mono
            self.audio_picker.refresh(quiet=True)
            self._plan_refresh_video()
            if p["due"] and p["wait_src"]:
                self._plan_try_fire()
                return
        if not p["warmed"] and left <= sch.PREPARE_S:
            p["warmed"] = True
            self._plan_prepare()
        if p["due"]:
            if p["retry_at"] and mono >= p["retry_at"]:
                p["retry_at"] = 0.0
                self._plan_try_fire()
            return
        if left <= 0:
            p["due"] = True
            late = -left
            if late > sch.LATE_OK_S and not p["late_ok"]:
                self._plan_ask_late(late)
            else:
                self._plan_try_fire()
            return
        self._plan_texts(left)

    def _plan_texts(self, left: float, big: str = ""):
        from .. import schedule as sch
        p = self._plan
        cfg = p["cfg"]
        parts = [sch.when_text(p["at"])]
        if cfg["audio_spec"]:
            parts.append(cfg["audio_spec"].get("label") or tr("dźwięk"))
        if cfg["video_spec"]:
            parts.append(tr("slajdy: {name}", name=cfg["video_spec"].get("label") or ""))
        note = self._plan_missing()
        if not note and not big:             # przy pytaniu / starcie zostaje tylko informacja o brakującym źródle
            note = (tr("Wszystko gotowe – nagrywanie ruszy samo.") if p["warmed"] else
                    tr("Komputer nie zaśnie do startu – zostaw aplikację otwartą. Ekran może się wygasić."))
        self.wait_panel.set_texts(big or sch.countdown_text(left), " · ".join(parts), note)

    def _plan_missing(self) -> str:
        """Opis brakującego źródła ("" = wszystko jest)."""
        p = self._plan
        cfg = p["cfg"]
        a, v = cfg["audio_spec"], cfg["video_spec"]
        if a and p["audio"] is None:
            name = a.get("label") or tr("wybrana aplikacja")
            if a.get("kind") == "process":
                return tr("Czekam na „{name}” – uruchom ją przed startem, nagrywanie zacznie się samo.", name=name)
            return tr("Źródło dźwięku „{name}” jest teraz niedostępne – podłącz je przed startem.", name=name)
        if v and p["video"] is None:
            name = v.get("label") or ""
            if str(v.get("key", "")).startswith("window:"):
                return tr("Okno „{name}” jest teraz niedostępne – otwórz je przed startem.", name=name)
            return tr("Ekran „{name}” jest teraz niedostępny – podłącz go przed startem.", name=name)
        return ""

    def _plan_resolve(self):
        """Źródła z planu na obecnych listach (Teams po ponownym uruchomieniu ma nowy PID – szukamy po .exe)."""
        p = self._plan
        cfg = p["cfg"]
        a = v = None
        if cfg["audio_spec"]:
            idx = self._find_audio(cfg["audio_spec"])
            a = self.audio_picker.sources[idx] if idx >= 0 else None
        if cfg["video_spec"]:
            key = cfg["video_spec"].get("key")
            v = next((x for x in self._video_sources if self._video_key(x) == key), None)
        p["audio"], p["video"] = a, v

    def _plan_refresh_video(self):
        """Lista ekranów i okien dla planu (bez przebudowy pola wyboru na ukrytym formularzu)."""
        p = self._plan
        if p is None or not p["cfg"]["video_spec"] or not LIVE_RECORDING:
            return
        try:
            from ..screen_capture import list_monitors, list_windows
            self._video_sources = list_monitors() + list_windows()
        except Exception:  # noqa: BLE001
            log.exception("lista ekranów (plan)")
        self._plan_resolve()

    def _plan_sources_changed(self):
        """Nowa lista dźwięku – może aplikacja z planu już działa."""
        from datetime import datetime
        p = self._plan
        self._plan_resolve()
        if p["due"]:
            if (p["wait_src"] or p["retry_at"]) and not self._plan_missing():
                p["retry_at"] = 0.0
                self._plan_try_fire()
            return
        self._plan_texts((p["at"] - datetime.now()).total_seconds())

    def _plan_check(self, warm: bool = True):
        """Sprawdzenie z healthcheck.py w tle. Brakującego źródła nie zgłaszamy – na nie plan czeka (notka pod
        odliczaniem). warm=True (ok. 2 min przed) ładuje też model notatek na żywo w Ollamie (keep_alive)."""
        p = self._plan
        if p is None:
            return
        self._start_healthcheck(p, p["audio"], p["video"], p["cfg"]["live_notes"], warm=warm)

    def _plan_health_done(self, probs: list):
        if not probs or self._fix_key:          # naprawa trwa – nie podmieniaj karty pod ręką
            return
        self.problem_card.set_problems(probs, waiting=True)

    def _plan_prepare(self):
        """Ok. 2 min przed startem: drugie sprawdzenie i rozgrzanie modeli, żeby start był natychmiastowy."""
        p = self._plan
        cfg = p["cfg"]
        self.audio_picker.refresh(quiet=True)
        self._plan_refresh_video()
        self._plan_check(warm=True)
        if cfg["live"] and cfg["audio_spec"]:
            try:
                from ..transcriber import prewarm
                prewarm(self.settings, self._language_for(cfg), low_vram=cfg["live_notes"])
            except Exception:  # noqa: BLE001
                log.exception("rozgrzanie Whispera")
        if cfg["live_notes"] and cfg["audio_spec"] and p["audio"] is None:
            # sprawdzenie bez źródła dźwięku nie rozgrzeje modelu notatek na żywo – zrób to osobno
            settings = self.settings

            def work():
                from .. import ollama_local
                from ..healthcheck import warm_up
                if settings.live_model and ollama_local.quick_is_up(settings.ollama_url, timeout=1.5):
                    warm_up(settings.ollama_url, settings.live_model, int(getattr(settings, "live_ctx", 8192)))
            threading.Thread(target=work, name="PlanWarmUp", daemon=True).start()

    def _plan_try_fire(self):
        """Pora startu: źródła są → start; nie ma → chwila na odświeżenie listy, potem pytanie (nigdy start z niczego)."""
        import time as _t
        p = self._plan
        if p is None:
            return
        self._plan_refresh_video()
        self._plan_resolve()
        if not self._plan_missing():
            self._plan_launch()
            return
        if not p["refreshed"]:                   # lista dźwięku mogła być sprzed kilku sekund – odśwież i daj 4 s
            p["refreshed"] = True
            p["retry_at"] = _t.monotonic() + 4
            self.audio_picker.refresh(quiet=True)
            self._plan_texts(0, tr("Uruchamiam nagrywanie…"))
            return
        if p["wait_src"]:
            self._plan_texts(0, tr("Czekam na źródło…"))
            return
        self._plan_ask_source()

    def _plan_ask_late(self, late: float):
        from .. import schedule as sch
        from .schedule_view import notify
        p = self._plan
        n = sch.late_minutes(late)
        self._plan_texts(0, tr("Nagrywanie się nie rozpoczęło"))
        self.wait_panel.ask("late", tr("Zaplanowany start ({time}) minął {n} min temu", time=sch.clock(p["at"]), n=n),
                            tr("Komputer był chyba uśpiony. Zacząć nagrywanie teraz?"),
                            [("late_go", tr("Zacznij teraz"), True), ("cancel", tr("Anuluj"), False)])
        notify(tr("Zaplanowane nagrywanie"), tr("Start minął {n} min temu – zacząć teraz?", n=n))

    def _plan_ask_source(self):
        from .schedule_view import notify
        p = self._plan
        cfg = p["cfg"]
        audio_missing = bool(cfg["audio_spec"]) and p["audio"] is None
        spec = cfg["audio_spec"] if audio_missing else cfg["video_spec"]
        name = (spec or {}).get("label") or ""
        title = (tr("Pora nagrywania, ale „{name}” nadal nie działa", name=name) if audio_missing else
                 tr("Pora nagrywania, ale „{name}” jest niedostępne", name=name))
        self._plan_texts(0, tr("Nagrywanie się nie rozpoczęło"))
        self.wait_panel.ask("source", title,
                            tr("Bez źródła nagrywanie się nie zacznie. Uruchom aplikację – nagrywanie ruszy samo, "
                               "gdy się pojawi – albo wybierz inne źródło."),
                            [("wait", tr("Czekaj dalej"), True), ("pick", tr("Wybierz inne źródło"), False),
                             ("cancel", tr("Anuluj"), False)])
        notify(tr("Nagrywanie się nie rozpoczęło"), title)

    def _plan_answer(self, key: str):
        p = self._plan
        if p is None:
            return
        if key == "late_go":
            p["late_ok"] = True
            self._plan_try_fire()
        elif key == "wait":
            p["wait_src"] = True
            self._plan_texts(0, tr("Czekam na źródło…"))
        elif key == "pick":
            audio = bool(p["cfg"]["audio_spec"]) and p["audio"] is None
            self._cancel_plan(tr("Wybierz inne źródło i zaplanuj nagrywanie jeszcze raz."))
            QTimer.singleShot(0, lambda: self._point_to_source(audio))
        else:
            self._cancel_plan(tr("Zaplanowane nagrywanie anulowane."))

    def _plan_fire(self, now: bool = False):
        """„Zacznij teraz” – bez czekania na godzinę (źródła i tak muszą być)."""
        p = self._plan
        if p is None:
            return
        p["due"] = True
        p["start_now"] = now
        self.wait_panel.clear_ask()
        self._plan_try_fire()

    def _plan_launch(self):
        """O czasie: dokładnie ta sama ścieżka co „Rozpocznij nagrywanie” (_launch) z ustawieniami z planu."""
        import time as _t
        from datetime import datetime
        from .. import schedule as sch
        from .schedule_view import notify
        p = self._plan
        cfg = dict(p["cfg"], audio=p["audio"], video=p["video"])
        if self._start_busy(cfg["continue_lecture"]):       # poprzednie uruchamianie jeszcze się sprząta
            p["retry_at"] = _t.monotonic() + 1
            return
        late_s = 0.0 if p["start_now"] else (datetime.now() - p["at"]).total_seconds()
        late_min = sch.late_minutes(late_s) if late_s >= sch.LATE_NOTE_S else 0
        self._end_plan()
        self._reset_when()
        if self._launch(cfg, late_min=late_min):
            lec = self._pending["lecture"] if self._pending else None
            text = lec.meta.title if lec is not None else ""
            if late_min:
                text = tr("{title} · start spóźniony o {n} min", title=text, n=late_min)
            notify(tr("Nagrywanie rozpoczęte"), text)
        else:
            self._back_to_setup()

    def _plan_change_time(self):
        from .. import schedule as sch
        from .schedule_view import ChangeTimeDialog
        p = self._plan
        if p is None:
            return
        dlg = ChangeTimeDialog(p["at"], self)
        if not dlg.exec() or self._plan is not p:        # w trakcie okienka plan mógł już ruszyć
            return
        p["at"] = dlg.when()
        p.update(due=False, late_ok=False, start_now=False, retry_at=0.0, refreshed=False, wait_src=False)
        from datetime import datetime
        if (p["at"] - datetime.now()).total_seconds() > sch.PREPARE_S + 60 and p["warmed"]:
            p["warmed"] = False                          # do startu daleko – rozgrzeje się jeszcze raz przed nim
            from ..transcriber import drop_warm
            drop_warm()
        self.wait_panel.clear_ask()
        self.schedule_state.emit(sch.short_when(p["at"]))
        self._plan_tick()

    def _end_plan(self):
        """Koniec oczekiwania (start albo anulowanie): timer stoi, komputer może znów zasnąć."""
        from .. import schedule as sch
        p = self._plan
        if p is None:
            return
        p["cancelled"] = True
        self._plan = None
        if self._attempt is p:
            self._attempt = None
        self._plan_timer.stop()
        sch.awake().release("plan")
        self.wait_panel.clear_ask()
        self.problem_card.set_problems([])
        self._set_wait_mode(False)
        self.schedule_state.emit("")

    def _cancel_plan(self, msg: str = "", keep_when: bool = False, to_setup: bool = True):
        if self._plan is None:
            return
        log.info("Zaplanowane nagrywanie anulowane")
        self._end_plan()
        from ..transcriber import drop_warm
        drop_warm()
        if not keep_when:
            self._reset_when()
        if to_setup:
            self._back_to_setup()
        if msg:
            self.setup_status.setText(msg)

    # ------------------------------------------------------------------ sprawdzenie przed nagrywaniem (2.3)
    def _start_healthcheck(self, pending: dict, audio, video, live_notes: bool, warm: bool = True):
        """Rusza razem z uruchamianiem nagrywania. Wszystko OK – nic nie widać; problem – karta na ekranie nagrywania.
        warm=False – bez ładowania modelu notatek na żywo (sprawdzenie zaraz po zaplanowaniu, start jest daleko)."""
        settings = self.settings

        def work():
            from ..healthcheck import run_checks
            try:
                probs = run_checks(settings, audio, video, live_notes, warm=warm)
            except Exception:  # noqa: BLE001
                log.exception("sprawdzenie przed nagrywaniem")
                probs = []
            self.health_done.emit(pending, probs)
        threading.Thread(target=work, name="Healthcheck", daemon=True).start()

    def _problem_shown(self, on: bool):
        show_if(self.problem_scroll, on)
        show_if(self.live_panels, not on and self._plan is None)
        if not on:
            QTimer.singleShot(0, self._relayout_live)

    def _attempt_alive(self, pending: dict) -> bool:
        """Ta próba startu wciąż jest na ekranie (uruchamia się, już nagrywa albo pokazuje, czemu się nie udała)."""
        return pending is self._attempt and not pending["cancelled"] and (
            self._pending is pending or self.session is not None or bool(pending.get("failed")))

    def _on_health_done(self, pending: dict, probs: list):
        if pending.get("scheduled"):             # sprawdzenie w czasie oczekiwania na zaplanowany start
            if pending is self._plan:
                self._plan_health_done(probs)
            return
        pending["health"] = probs
        if not self._attempt_alive(pending) or not probs:
            return
        if pending.get("failed"):        # start już się nie udał – konkretny powód ze sprawdzenia zamiast ogólnego
            rec = [p_ for p_ in probs if p_.area in ("audio", "slides")]
            if rec:
                self.problem_card.set_problems(rec, failed=True)
            return
        self.problem_card.set_problems(probs, running=self.session is not None)

    def _show_start_failed(self, pending: dict):
        """Start nie wyszedł (np. źródło dźwięku zniknęło) – karta z powodem zamiast okienka systemowego."""
        from ..healthcheck import Problem
        pending["failed"] = True
        self.timer.stop()
        self.recording_state.emit(False)
        self.rec_label.setText(tr("NIE UDAŁO SIĘ ROZPOCZĄĆ"))
        self.dot.on = False
        self.dot.update()
        self.btn_stop.setEnabled(False)
        self._set_status("")
        rec = [p_ for p_ in (pending.get("health") or []) if p_.area in ("audio", "slides")]
        if not rec:
            audio = pending.get("audio")
            rec = [Problem("start_error", tr("Nie udało się rozpocząć nagrywania"),
                           tr("Powód: {err}", err=pending.get("err") or "?"),
                           [tr("Sprawdź, czy wybrane źródło dźwięku i ekran są wciąż dostępne."),
                            tr("Kliknij „Wybierz inne źródło” albo spróbuj jeszcze raz.")],
                           "pick_audio" if audio is not None else "pick_video", tr("Wybierz inne źródło"),
                           True, "audio" if audio is not None else "slides")]
        self.problem_card.set_problems(rec, failed=True)

    def _health_proceed(self):
        """„Nagrywaj mimo to” – karta znika, nagrywanie idzie dalej (AI dorobi transkrypcję i notatki później)."""
        from ..healthcheck import ai_only
        p = self._attempt
        probs = self.problem_card.problems
        self.problem_card.set_problems([])
        if p is not None:
            p["proceed"] = True
        if probs and ai_only(probs) and self.session is not None and self.session.audio_info is not None:
            self._set_status(tr("Nagrywanie trwa – transkrypcja i notatki zrobią się po zakończeniu, gdy AI zadziała."))

    def _health_cancel(self):
        if self._plan is not None:               # „Anuluj nagrywanie” na karcie w czasie oczekiwania
            self._cancel_plan(tr("Zaplanowane nagrywanie anulowane."))
            return
        p = self._attempt
        if p is None or p.get("failed"):
            self._back_to_setup()
            return
        if self._pending is p:                   # wciąż się uruchamia
            self._cancel_start()
            return
        if self.session is not None:             # już nagrywa – zatrzymaj i usuń to, co zdążyło się zapisać
            self._discard_session(p)
            self.setup_status.setText(tr("Nagrywanie anulowane."))

    def _discard_session(self, pending: dict):
        sess, self.session = self.session, None
        pending["cancelled"] = True

        def undo():
            try:
                sess.stop()
            except Exception:  # noqa: BLE001
                log.exception("anulowanie po starcie: stop")
            self._undo_start(pending)
        th = threading.Thread(target=undo, name="RecordingDiscard", daemon=True)
        th.start()
        self._cleanups.append((th, pending["lecture"].folder))
        self.autostop.hide()
        self._back_to_setup()

    def _health_action(self, action: str, key: str):
        from .. import healthcheck as hc
        kind, _, arg = action.partition(":")
        card = self.problem_card
        if kind == "start_ollama":
            self._fix_key = key
            card.set_busy(key, tr("Uruchamiam Ollamę…"))
            self._watch.start_ollama(on_done=lambda ok: self._ollama_fixed(key, ok))
        elif kind == "install_ollama":
            from .health_ui import open_ollama_download
            open_ollama_download()
        elif kind == "pull":
            self._fix_key = key
            card.set_busy(key, tr("Pobieram model {name}…", name=hc._short(arg)), 0.0)
            self._watch.pull([arg], on_done=lambda ok: self._pull_fixed(key, ok))
        elif kind == "cpu":
            hc.switch_to_cpu(self.settings)
            self._remove_problem(key)
        elif kind == "whisper":
            card.set_busy(key, tr("Pobieram model rozpoznawania mowy…"), 0.0)

            def work():
                try:
                    hc.download_whisper(arg, progress=lambda f: self.health_progress.emit(
                        key, tr("Pobieram model rozpoznawania mowy · {x}%", x=round(100 * f)), f))
                    self.health_fixed.emit(key, [])
                except Exception:  # noqa: BLE001
                    log.exception("pobieranie modelu Whisper")
                    self.health_fixed.emit(key, None)
            threading.Thread(target=work, name="WhisperDownload", daemon=True).start()
        elif kind in ("pick_audio", "pick_video"):
            if self._plan is not None:       # w oczekiwaniu: wróć do formularza z zachowaną godziną
                self._cancel_plan(tr("Wybierz inne źródło i zaplanuj nagrywanie jeszcze raz."), keep_when=True)
            self._health_cancel()
            if self.stack.currentIndex() != 0:
                self._back_to_setup()
            QTimer.singleShot(0, lambda: self._point_to_source(kind == "pick_audio"))

    def _point_to_source(self, audio: bool):
        """Po „Wybierz inne źródło”: odśwież listę i pokaż, które pole poprawić."""
        if audio:
            self.refresh_audio()
            self._field_warn(self.row_audio, tr("Wybierz źródło dźwięku, które teraz działa."))
        else:
            self.refresh_video()
            self._field_warn(self.row_video, tr("Wybierz ekran albo okno, które jest teraz widoczne."))

    def _watch_changed(self):
        """Postęp uruchamiania Ollamy / pobierania modelu na karcie problemu."""
        w = self._watch
        if self._fix_key and w.busy:
            self.problem_card.set_busy(self._fix_key, w.busy_text, w.busy_frac)

    def _ollama_fixed(self, key: str, ok: bool):
        self._fix_key = ""
        if not ok:
            self.problem_card.set_busy(key, tr("Nie udało się uruchomić Ollamy – otwórz ją z {where}.",
                                               where=tr("folderu Aplikacje") if IS_MAC else tr("menu Start")),
                                       busy=False)
            return
        p = self._attempt
        settings = self.settings
        live_notes = bool(p and p.get("audio") is not None and self.live_cb.isChecked()
                          and self.live_notes_cb.isChecked())
        slides = bool(p and p.get("video") is not None)

        def work():               # Ollama działa – czy ma potrzebne modele?
            from ..healthcheck import check_ollama
            try:
                self.health_fixed.emit(key, check_ollama(settings, live_notes, slides))
            except Exception:  # noqa: BLE001
                log.exception("sprawdzenie modeli")
                self.health_fixed.emit(key, [])
        threading.Thread(target=work, name="HealthRecheck", daemon=True).start()

    def _pull_fixed(self, key: str, ok: bool):
        self._fix_key = ""
        if ok:
            self._remove_problem(key)
        else:
            self.problem_card.set_busy(key, self._watch.error or tr("Nie udało się pobrać modelu."), busy=False)

    def _on_health_fixed(self, key: str, probs):
        card = self.problem_card
        if not card.problems:
            return
        if probs is None:
            card.set_busy(key, tr("Nie udało się pobrać modelu. Sprawdź internet i spróbuj ponownie."), busy=False)
            return
        rest = [p_ for p_ in card.problems if p_.key != key]
        keys = {p_.key for p_ in rest}
        new = rest + [p_ for p_ in probs if p_.key not in keys]
        if not new:
            self._remove_problem(key)
        else:
            card.set_problems(new, failed=card.failed, running=card.running)

    def _remove_problem(self, key: str):
        """Naprawione – gdy nic nie zostało, karta znika, a nagrywanie idzie dalej bez pytania."""
        if self.problem_card.remove(key):
            self._health_proceed()
            if self.session is not None:
                self._set_status(tr("Naprawione – wszystko działa."))

    def _started(self, sess, pending: dict):
        """Dźwięk już płynie – zwykły widok nagrywania; zegar liczy od faktycznego startu dźwięku (sess.t0)."""
        import time as _t
        audio, lecture = pending["audio"], pending["lecture"]
        self.session = sess
        self._last_sound = 0.0
        self._autostop_deadline = None
        self._autostop_snooze = 0.0
        self.rec_label.setText(tr("NAGRYWANIE"))
        self.dot.on = True
        self.dot.update()
        self._marks_count = 0
        self.live_title.setText(lecture.meta.title + (tr("  ·  część {part_index}", part_index=sess.part_index) if sess.is_continuation else ""))
        if audio is None:
            self._set_status(tr("Zrzuty slajdów – notatka powstanie z ich treści po zakończeniu."))
        elif not sess.whisper_ready and not sess.whisper_error:   # inaczej status ustawił już wątek modelu
            self._set_status(tr("Ładowanie modelu rozpoznawania mowy…") if sess.live else
                             tr("Nagrywanie – transkrypcja zrobi się po zakończeniu."))
        for b_ in (self.btn_mark, self.btn_mark_kind, self.btn_pause):
            b_.setEnabled(True)
        show_if(self.btn_live_roi, sess.slide_rec is not None)
        self._update_src_buttons()
        self.btn_stop.setText(tr("Zakończ"))
        self.btn_stop.setToolTip(tr("Zakończ nagrywanie – notatki zrobią się same"))
        set_icon(self.btn_stop, "stop", "on_red", 16)
        self.btn_stop.setEnabled(True)
        self.live_ask_field.setEnabled(sess.live)
        if pending["continuing"]:     # pokaż dotychczasową transkrypcję – nowa część dopisze się pod nią
            self._titems = [dict(x, kind="seg") for x in sess.lecture.load_segments()[-40:]] + self._titems
            self._titems.append({"kind": "note", "text": tr("część {part_index}", part_index=sess.part_index)})
        if pending.get("late_min"):   # zaplanowany start po uśpieniu – notka w transkrypcji (meta.switches)
            entry = {"t": round(sess.offset, 2), "kind": "late", "minutes": int(pending["late_min"])}
            try:
                sess._note_switch(entry)
            except Exception:  # noqa: BLE001
                log.exception("notka o spóźnionym starcie")
            self._titems.append({"kind": "note", "text": switch_note(entry)})
        from ..transcriber import drop_warm
        drop_warm()                   # rozgrzany silnik, którego sesja nie wzięła (np. inne ustawienia) – zwolnij
        self._render_transcript()
        self.time_label.setText(fmt_time(sess.now()))
        if self.problem_card.problems:
            self.problem_card.set_running(True)
        log.info("Start nagrywania: od kliknięcia do działającego nagrania %.0f ms",
                 1000 * (_t.perf_counter() - pending["clicked"]))
        self.recording_state.emit(True)

    def _setup_live_panels(self, lec, has_audio: bool, live: bool, on: bool):
        t = T()
        self.live_notes_view.images = {}
        self.live_seg.buttons[0].setEnabled(has_audio)
        self.live_seg.buttons[2].setEnabled(live)
        self.live_ask_field.setEnabled(live)
        self.live_ask_field.setPlaceholderText(tr("Zapytaj o to, co już padło na wykładzie…  (Ctrl K)") if live else
                                              tr("Pytania działają, gdy włączona jest transkrypcja na żywo."))
        self._show_notes_page(0)
        self.notes_head.setText(tr("NOTATKI NA ŻYWO") if on else tr("NOTATKI"))
        if on:
            self.live_notes_view.setHtml(
                tr("<body style='color:{text2}'><p>Pierwszy fragment notatek pojawi się po zmianie slajdu albo "
                   "po kilku minutach mowy. Kolejne będą się dopisywać w trakcie wykładu.</p>", text2=t.text2)
                + self._skeleton() + "</body>")
            self.live_notes_status.setText(tr("Ładowanie…"))
        else:
            self.live_notes_view.setHtml(
                tr("<body style='color:{text2}'><p><b style='color:{text}'>Notatki na żywo są "
                   "wyłączone.</b></p><p>Notatka powstanie po zakończeniu nagrywania. Możesz je włączyć w "
                   "opcjach przed nagraniem („Notatki i pytania na żywo”).</p></body>", text2=t.text2, text=t.text))
            self.live_notes_status.setText("")

        def get_md():
            ln = getattr(self.session, "live_notes", None)
            if ln is not None:
                return ln.qa_markdown()
            segs = lec.load_segments()     # bez notatek na żywo – pytania do samej transkrypcji
            from ..live_notes import LIVE_HEADING
            return f"# {lec.meta.title}\n\n## {LIVE_HEADING}\n\n" + " ".join(x["text"] for x in segs[-400:])
        from ..notes_pipeline import notes_lang
        self.live_ask.set_source(get_md, lec.folder / "qa.json", int(self.settings.live_ctx),
                                 lang=lambda: notes_lang(lec))
        if self._live_mode == "narrow":
            self._narrow_tab(0 if has_audio else 1)

    def _skeleton(self) -> str:
        from .live_view import skeleton_html
        s = self.session
        ln = getattr(s, "live_notes", None) if s is not None else None
        if ln is not None and getattr(ln, "busy", False):
            return skeleton_html(tr("Piszę ten fragment…"))
        mins = 0
        try:
            from ..notes_pipeline import MAX_WORDS
            words = len((getattr(ln, "open_text", "") or "").split()) if ln is not None else 0
            mins = max(1, round((MAX_WORDS - words) / 140))
        except Exception:  # noqa: BLE001
            pass
        return skeleton_html(tr("Piszę po zmianie slajdu albo za ~{mins} min", mins=mins) if mins else
                             tr("Piszę po zmianie slajdu albo za kilka minut"))

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
        return (tr("<p style='color:{text3}'>Pierwszy fragment tekstu pojawi się po około 20–30 sekundach od "
                   "rozpoczęcia mowy.</p>", text3=T().text3))

    def stop(self):
        if self._pending is not None:        # „Anuluj” w trakcie uruchamiania
            self._cancel_start()
            return
        if self.session is None:
            return
        sess = self.session
        self.problem_card.set_problems([])
        self.btn_stop.setEnabled(False)
        for b_ in (self.btn_src_audio, self.btn_src_video, self.btn_hold, self.btn_more):
            b_.setEnabled(False)
        self._set_status(tr("Kończenie – zapisywanie nagrania i dokończenie transkrypcji…"))

        def work():
            try:
                sess.stop()
            except Exception:
                log.exception("stop")
                sess.needs_file_transcription = True
            self.stopped_signal.emit(sess.lecture, getattr(sess, "needs_file_transcription", False))

        threading.Thread(target=work, daemon=True).start()

    def stop_blocking(self):
        self._cancel_plan(to_setup=False)          # zamknięcie okna anuluje plan (komputer może znów zasnąć)
        p = self._pending
        if p is not None:                     # zamknięcie okna w trakcie uruchamiania
            p["cancelled"] = True
            self._pending = None
            if self._start_thread is not None:
                self._start_thread.join(20)
            if not p.get("handled"):
                p["handled"] = True
                if p.get("sess") is not None and not p.get("err"):
                    try:
                        p["sess"].stop()
                    except Exception:
                        log.exception("stop_blocking: start")
                self._undo_start(p)
        for th, _f in self._cleanups:            # sprzątanie po anulowanych startach
            th.join(20)
        if self.session:
            try:
                self.session.stop()
            except Exception:
                log.exception("stop_blocking")
            self.session = None

    def _on_stopped(self, lecture, needs_file):
        self.timer.stop()
        self.problem_card.set_problems([])
        self.session = None
        self.stack.setCurrentIndex(0)
        self.title.clear()
        self.cancel_continue()
        self.autostop.hide()
        self.refresh_subjects()
        self.setup_status.setText(tr("Zapisano „{title}” ({fmt_time}).", title=lecture.meta.title, fmt_time=fmt_time(lecture.meta.duration)))
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
        self.setup_title.setText(tr("Kontynuacja notatki"))
        self.cont_text.setText(tr("<b>{escape}</b> – część {n}. Nagranie, slajdy albo zdjęcia dopiszą się do tej samej notatki "
                                  "(czas biegnie dalej od {fmt_time}). Możesz wybrać dowolny rodzaj poniżej.", escape=html.escape(lecture.meta.title), n=n, fmt_time=fmt_time(lecture.meta.duration)))
        self.cont_banner.show()
        self.title.setText(lecture.meta.title)
        self.subject.setEditText(lecture.meta.subject)
        self.title.setEnabled(False)
        self.subject.setEnabled(False)
        self.cards_cb.setChecked(bool(lecture.meta.make_flashcards))

    def cancel_continue(self):
        was = self.continue_lecture is not None
        self.continue_lecture = None
        self.cont_banner.hide()
        self.setup_title.setText(tr("Nowa notatka"))
        self.title.setEnabled(True)
        self.subject.setEnabled(True)
        self.title.clear()
        if was:
            self.cards_cb.setChecked(bool((self.settings.last_rec or {}).get("make_flashcards",
                                                                             self.settings.auto_flashcards)))

    # ------------------------------------------------------------------ zaznaczanie ważnych fragmentów
    def _set_mark_kind(self, kind: str):
        from ..storage import MARK_KINDS
        self._mark_kind = kind
        if not self.btn_mark.isChecked():
            self.btn_mark.setText(tr("Zaznacz ważne") if kind == "important" else tr("Zaznacz: {get}", get=MARK_KINDS.get(kind, kind)))

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
            self.btn_mark.setText(tr("Zakończ zaznaczanie"))
            self.btn_mark_kind.setEnabled(False)
            self._set_status(tr("Zaznaczanie od {fmt_time} ({get}) – kliknij „Zakończ zaznaczanie” (Ctrl+M), gdy fragment "
                                "się skończy.", fmt_time=fmt_time(mk['start']), get=MARK_KINDS.get(mk['kind'])))
        else:
            mk = s.end_mark()
            self.btn_mark_kind.setEnabled(True)
            self._set_mark_kind(self._mark_kind)
            if self._tmarks and self._tmarks[-1]["end"] is None:
                self._tmarks[-1]["end"] = mk["end"] if mk else s.now()
            if mk:
                self._marks_count += 1
                self._set_status(tr("Zaznaczono {fmt_time}–{fmt_time2} · {get}. W notatce pojawi się ramka „Ważne” z tym "
                                    "fragmentem.", fmt_time=fmt_time(mk['start']), fmt_time2=fmt_time(mk['end']), get=MARK_KINDS.get(mk['kind'])))
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
            self.rec_label.setText(tr("PAUZA"))
            self._pause_text()
            set_icon(self.btn_pause, "play", "text", 18)
            self.btn_pause.setToolTip(tr("Wznów nagrywanie"))
            self._set_status(tr("Pauza – dźwięk, transkrypcja i slajdy nie są nagrywane. Czas stoi."))
        else:
            s.resume()
            self.rec_label.setText(tr("NAGRYWANIE"))
            self._pause_text()
            set_icon(self.btn_pause, "pause", "text", 18)
            self.btn_pause.setToolTip(tr("Pauza – dźwięk, transkrypcja i slajdy się zatrzymują, czas stoi"))
            self._set_status(tr("Nagrywanie wznowione."))
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
                    reason = tr("Aplikacja, z której nagrywasz dźwięk, została zamknięta.")
                    self._autostop_closed = True
            except Exception:
                pass
        silent = now - self._last_sound
        if not reason and silent >= minutes * 60 and now >= self._autostop_snooze:
            reason = tr("Od {x} min nic nie słychać – wygląda na to, że wykład się skończył.", x=int(silent // 60))
        if reason and self._autostop_deadline is None:
            self._autostop_deadline = now + 60
            self._autostop_reason = reason
            self.autostop.show()
        if self._autostop_deadline is not None:
            if s.level_db() > -45 and not getattr(self, "_autostop_closed", False):
                self._autostop_cancel()        # znowu słychać wykład
                return
            left = int(self._autostop_deadline - now)
            self.autostop_text.setText(tr("{autostop_reason} Nagrywanie zakończy się za {x} s.", autostop_reason=self._autostop_reason, x=max(0, left)))
            if left <= 0:
                self.autostop.hide()
                self._autostop_deadline = None
                self.stop()

    def _autostop_cancel(self):
        import time as _t
        self._autostop_deadline = None
        self._autostop_closed = False
        self.autostop.hide()
        self._last_sound = _t.monotonic()
        self._autostop_snooze = _t.monotonic() + 5 * 60

    # ------------------------------------------------------------------
    def elapsed_text(self) -> str:
        return fmt_time(self.session.elapsed()) if self.session else ""

    def _tick(self):
        s = self.session
        if not s:
            if self._pending is not None:      # „Uruchamiam nagrywanie…” – kropka pulsuje szybciej
                self._ticks += 1
                if self._ticks % 3 == 0:
                    self.dot.blink()
            return
        self._ticks += 1
        paused = getattr(s, "paused", False)
        self.meter.push(0.0 if paused else (s.level_db() + 60) / 60)
        if self._ticks % 5 == 0:
            txt = fmt_time(s.now())
            if len(txt) != len(self.time_label.text()):      # 59:59 → 1:00:00 – zegar dostaje więcej miejsca
                self.time_label.setMinimumWidth(self.time_label.fontMetrics().horizontalAdvance(txt) + 6)
            self.time_label.setText(txt)
            if not paused:
                self.dot.blink()
        if self._ticks % 300 == 0 and s.live_notes_enabled:
            self._on_notes_update()
            if s.whisper_ready and s.pending_seconds() > 90:
                self._set_status(tr("Transkrypcja nie nadąża (opóźnienie {x} s) – nadrobi po zakończeniu.", x=int(s.pending_seconds())))
            if s.recorder and s.recorder.error:
                self._set_status(tr("Błąd dźwięku: {error}", error=s.recorder.error))
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
            self.transcript.setHtml(tr("<p style='color:{text2}'>Tryb „Tylko slajdy” – bez dźwięku i transkrypcji. Złapane slajdy "
                                       "widać po prawej; notatka powstanie z ich treści.</p>", text2=t.text2))
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
            self._set_status(tr("Slajd {index} uzupełniony (animacja) – zrzut podmieniony.", index=index))
        elif is_new and path:
            prev = self.slides.infos()[-1] if self.slides.count() else None
            self.slides.add_slide(index, path, t, self._slide_text_of(index))
            self.slides.scrollToBottom()
            self._titems.append({"kind": "slide", "index": index, "t": t})
            if prev is not None:
                self._check_duplicate(prev.index, index)
        elif not is_new:
            self._set_status(tr("Powrót do slajdu {index} ({fmt_time}).", index=index, fmt_time=fmt_time(t)))
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
        self.slides_title.setText(tr("SLAJDY · {count}", count=self.slides.count()))
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
            self._set_status(tr("Usunięto slajd {index}. Jeśli ten sam obraz wróci (np. kamerka), nie zapisze się ponownie.", index=index))
        return ok

    def _on_video_status(self, text: str):
        self.video_status.setText((text + tr(" – przywróć okno albo wybierz cały monitor.")) if text else "")


    def open_files_mode(self):
        if self.session is None:
            self.modes["files"].setChecked(True)
