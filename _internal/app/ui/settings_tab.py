"""Ekran „Ustawienia” w stylu Ustawień systemowych macOS. Zmiany zapisują się od razu."""
from __future__ import annotations

import threading

from PySide6.QtCore import QPointF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..config import log_path
from ..llm import Ollama
from .controls import GroupSection, SegmentedControl, StatusDot, ToggleSwitch, hbox, label
from .record_tab import _centered
from . import tokens as TK
from .. import perf
from ..system import IS_MAC, LIVE_RECORDING, system_name
from .theme import theme

VISION_MODELS = [
    ("qwen3-vl:8b-instruct", "Qwen3-VL 8B – czyta schematy, wykresy i wzory (polecany), ~6 GB"),
    ("gemma3:12b", "Gemma 3 12B – dobry polski, ~8 GB"),
    ("qwen3-vl:4b-instruct", "Qwen3-VL 4B – szybszy, słabsze karty, ~3 GB"),
]
RECOMMENDED_MODELS = [
    ("SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M", "Bielik 11B – polski model (polecany), ~7 GB"),
    ("gemma3:12b", "Gemma 3 12B – bardzo dobry polski, ~8 GB"),
    ("qwen3:14b", "Qwen3 14B – mocny, ~9 GB"),
    ("SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0", "Bielik 4.5B – lżejszy i szybszy, ~5 GB"),
]
THEMES = [("system", "Jak system"), ("light", "Jasny"), ("dark", "Ciemny")]


class ThemeCard(QWidget):
    """Karta wyboru motywu: nazwa w foncie motywu, próbki kolorów, nazwy fontów. Rysuje się w kolorach
    swojego motywu (jasnych albo ciemnych – jak aktualny tryb)."""
    clicked = Signal(str)

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(f"Motyw {TK.THEME_LABELS[name]}")

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(260, 156)

    def mousePressEvent(self, e):
        self.clicked.emit(self.name)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit(self.name)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont, QPainter, QPen
        from .theme import T, _family, qcolor
        cur = T()
        v = TK.variant(TK.THEMES[self.name], cur.dark)
        rad = v["radius"]["lg"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(qcolor(cur.accent if self.selected else v["line"]), 2.4 if self.selected else 1))
        p.setBrush(qcolor(v["bg"]))
        p.drawRoundedRect(r, rad, rad)
        x, y = r.left() + 18, r.top() + 16
        f = QFont(_family(v["fontDisplay"], "display"))
        f.setPixelSize(24)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(v["ink"]))
        p.drawText(QRectF(x, y, r.width() - 60, 32), Qt.AlignmentFlag.AlignVCenter, TK.THEME_LABELS[self.name])
        if self.selected:
            c = QRectF(r.right() - 36, y + 4, 22, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(cur.accent))
            p.drawEllipse(c)
            p.setPen(QPen(qcolor(cur.on_accent), 2))
            p.drawPolyline([c.center() + d for d in (QPointF(-5, 0), QPointF(-1.5, 3.5), QPointF(5, -3.5))])
        y += 42
        sw = 22
        for k, key in enumerate(("accent", "surface", "mark", "defBg", "rec")):
            p.setPen(QPen(qcolor(v["line2"]), 1))
            p.setBrush(qcolor(v[key]))
            rr = max(3, v["radius"]["xs"])
            p.drawRoundedRect(QRectF(x + k * (sw + 8), y, sw, sw), rr, rr)
        y += sw + 14
        fu = QFont(_family(v["fontUi"], "ui"))
        fu.setPixelSize(13)
        fu.setWeight(QFont.Weight.DemiBold)
        p.setFont(fu)
        p.setPen(qcolor(v["ink2"]))
        p.drawText(QRectF(x, y, r.width() - 36, 18), Qt.AlignmentFlag.AlignVCenter,
                   f"{v['fontDisplay']} + {v['fontUi']}")
        fu.setWeight(QFont.Weight.Normal)
        fu.setPixelSize(12)
        p.setFont(fu)
        p.setPen(qcolor(v["ink3"]))
        p.drawText(QRectF(x, y + 20, r.width() - 36, 18), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(TK.THEME_NOTES[self.name], Qt.TextElideMode.ElideRight,
                                              int(r.width() - 36)))
        p.end()


def combo(items: list[tuple[str, str]], value, width: int = 260) -> QComboBox:
    c = QComboBox()
    for data, text in items:
        c.addItem(text, data)
    i = c.findData(value)
    if i >= 0:
        c.setCurrentIndex(i)
    c.setMinimumWidth(width)
    return c


class SettingsTab(QWidget):
    ollama_status_signal = Signal(str, list)
    pull_progress = Signal(str, float)
    pull_done = Signal(bool, str)
    gpu_result = Signal(str, str)
    hw_ready = Signal(dict)
    whisper_have = Signal(bool)
    saved = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.s = settings
        self._loading = True
        self.busy_fn = lambda: ""

        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(26)
        from .controls import Heading
        v.addWidget(Heading("Ustawienia", "Zmiany zapisują się od razu. Wszystko działa na tym komputerze."))

        # ---------------- Ogólne ----------------
        self.appearance = SegmentedControl([t for _m, t in THEMES])
        self.appearance.set_current(next((i for i, (m, _t) in enumerate(THEMES) if m == self.s.theme), 0))
        self.appearance.changed.connect(self._theme_changed)
        self.lib_path = label(self.s.library_dir, "secondary")
        self.lib_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        b_lib = QPushButton("Zmień…")
        b_lib.clicked.connect(self._pick_lib)
        b_open = QPushButton("Otwórz")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.s.library_dir)))
        self.auto = ToggleSwitch(self.s.auto_generate_notes)
        self.scale = combo([(0.9, "90%"), (1.0, "100% – domyślny"), (1.1, "110%"), (1.25, "125%"), (1.5, "150%")],
                           None, 180)
        i = min(range(self.scale.count()), key=lambda k: abs(self.scale.itemData(k) - float(self.s.ui_scale or 1.0)))
        self.scale.setCurrentIndex(i)
        self.scale.currentIndexChanged.connect(self._scale_changed)
        from .controls import AdaptiveBox
        gw = GroupSection("Wygląd", "Motyw zmienia kolory, fonty i zaokrąglenia. Zmiana działa od razu.")
        cards = AdaptiveBox(threshold=640, spacing=12)
        self.theme_cards = {}
        for n in TK.THEMES:
            c = ThemeCard(n)
            c.clicked.connect(self._theme_name_changed)
            cards.add(c, 1)
            self.theme_cards[n] = c
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 16, 16, 16)
        wl.addWidget(cards)
        gw.add(wrap)
        gw.add_row("Tryb", self.appearance, f"Jasny – papier, ciemny – tablica. „Jak system” – zgodnie z {system_name()}.")
        self._mark_theme()
        v.addWidget(gw)
        g = GroupSection("Ogólne")
        self.scale_row = g.add_row("Rozmiar interfejsu", self.scale,
                                   "Większy na dużym monitorze, mniejszy na małym ekranie. Działa po ponownym uruchomieniu.")
        r = g.add_row("Folder biblioteki", hbox(b_open, b_lib, spacing=6))
        r.subtitle.setText(self.s.library_dir)
        r.subtitle.show()
        self.lib_row = r
        self.goal = QSpinBox()
        self.goal.setRange(5, 300)
        self.goal.setSingleStep(5)
        self.goal.setSuffix(" fiszek")
        self.goal.setValue(int(getattr(self.s, "daily_goal", 20) or 20))
        self.goal.valueChanged.connect(lambda v: (setattr(self.s, "daily_goal", int(v)), self.s.save()))
        g.add_row("Cel dzienny", self.goal, "Ile fiszek dziennie chcesz powtórzyć – pierścień na ekranie Fiszki.")
        g.add_row("Notatki po nagraniu", self.auto,
                  "Po zakończeniu nagrania automatycznie twórz notatki, podsumowanie i fiszki.")
        v.addWidget(g)

        # ---------------- Wydajność ----------------
        from .profile_card import ProfileCard
        gp = GroupSection("Wydajność", "Profil dobiera modele i tryby pracy do mocy komputera. Pojedyncze ustawienia "
                                       "możesz potem zmieniać niżej – wtedy profil zmienia się na „Własne”.")
        b_hw = QPushButton("Sprawdź ponownie")
        b_hw.clicked.connect(lambda: self._detect_hw(True))
        self.hw_row = gp.add_row("Twój komputer", b_hw)
        self.hw_row.subtitle.setText("Sprawdzam sprzęt…")
        self.hw_row.subtitle.show()
        pcards = AdaptiveBox(threshold=640, spacing=12)
        self.profile_cards = {}
        for k in perf.ORDER:
            c = ProfileCard(k)
            c.clicked.connect(self._profile_clicked)
            pcards.add(c, 1)
            self.profile_cards[k] = c
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(16, 16, 16, 12)
        pl.addWidget(pcards)
        gp.add(pw)
        self.btn_get = QPushButton("Pobierz brakujące")
        self.btn_get.setObjectName("primary")
        self.btn_get.clicked.connect(self._pull_missing)
        self.btn_get.hide()
        self.perf_row = gp.add_row("Profil", self.btn_get)
        self.perf_row.subtitle.show()
        self.perf_bar = QProgressBar()
        self.perf_bar.setTextVisible(False)
        self.perf_bar.setRange(0, 1000)
        gp.add(self._wrap(self.perf_bar))
        self.hw = perf.hardware(self.s) if getattr(self.s, "hw_info", None) else {}
        self._missing: list[str] = []
        v.addWidget(gp)

        # ---------------- Telefon ----------------
        from ..storage import list_lectures
        from .sync_update import PhoneSection, UpdateSection
        self.phone = PhoneSection(self.s, lambda: list_lectures(self.s.library_path()))
        v.addWidget(self.phone)

        # ---------------- Transkrypcja ----------------
        self.w_model = combo([("large-v3", "large-v3 – najdokładniejszy"),
                              ("large-v3-turbo", "large-v3-turbo – szybszy"),
                              ("medium", "medium – słabsze karty"), ("small", "small – najszybszy")], self.s.whisper_model)
        self.lang = combo([("auto", "Wykryj automatycznie"), ("pl", "Polski"), ("en", "Angielski"), ("de", "Niemiecki"),
                           ("es", "Hiszpański"), ("fr", "Francuski")], self.s.language)
        self.beam = combo([(1, "Szybko"), (2, "Zrównoważona"), (5, "Najdokładniej")],
                          int(getattr(self.s, "whisper_beam", 5)), 200)
        devices = [("auto", "Automatycznie"), ("cpu", "Procesor")] if IS_MAC else \
            [("auto", "Automatycznie"), ("cuda", "Karta graficzna (CUDA)"), ("cpu", "Procesor")]
        self.w_device = combo(devices, self.s.whisper_device)
        self.chunk = QSpinBox()
        self.chunk.setRange(8, 60)
        self.chunk.setSuffix(" s")
        self.chunk.setValue(int(self.s.live_chunk_seconds))
        self.gpu_dot = StatusDot("gray")
        self.gpu_text = label("Nie sprawdzono", "secondary")
        b_gpu = QPushButton("Sprawdź")
        b_gpu.clicked.connect(self._check_gpu)
        g = GroupSection("Transkrypcja", "Rozpoznawanie mowy (Whisper) działa lokalnie na komputerze.")
        g.add_row("Język wykładów", self.lang, "Język, w którym mówi prowadzący. Transkrypcja zawsze zostaje w tym "
                                              "języku – język notatek ustawisz w „Notatki AI”.")
        g.add_row("Model", self.w_model, "Dokładniejszy model = lepszy tekst, ale wolniejsza transkrypcja." if IS_MAC
                  else "Dokładniejszy model = lepszy tekst, ale większe obciążenie karty.")
        g.add_row("Dokładność", self.beam, "„Szybko” rozpoznaje mowę ok. 2× szybciej kosztem drobnych pomyłek.")
        g.add_row("Urządzenie", self.w_device, "Na Macu mowę rozpoznaje procesor (rdzenie wydajnościowe)." if IS_MAC
                  else "")
        if LIVE_RECORDING:
            g.add_row("Fragment na żywo co", self.chunk, "Co ile sekund dopisywać tekst podczas wykładu.")
        if not IS_MAC:          # CUDA – tylko karty NVIDIA (Windows)
            g.add_row("Karta graficzna", hbox(self.gpu_dot, self.gpu_text, b_gpu, spacing=8))
        v.addWidget(g)

        # ---------------- Slajdy ----------------
        self.sens = QSlider(Qt.Orientation.Horizontal)
        self.sens.setRange(1, 25)
        self.sens.setValue(max(1, round(self.s.slide_sensitivity * 100)))
        self.sens.setFixedWidth(180)
        self.sens_val = label("", "secondary")
        self.sens_val.setMinimumWidth(40)
        self.sens.valueChanged.connect(lambda x: self.sens_val.setText(f"{x}%"))
        self.sens_val.setText(f"{self.sens.value()}%")
        self.stable = QDoubleSpinBox()
        self.stable.setRange(0.0, 10.0)
        self.stable.setSingleStep(0.5)
        self.stable.setSuffix(" s")
        self.stable.setValue(self.s.slide_stable_seconds)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.3, 5.0)
        self.interval.setSingleStep(0.1)
        self.interval.setSuffix(" s")
        self.interval.setValue(self.s.slide_interval)
        self.ocr = ToggleSwitch(self.s.ocr_enabled)
        g = GroupSection("Wykrywanie slajdów")
        g.add_row("Próg zmiany slajdu", hbox(self.sens, self.sens_val, spacing=8),
                  "Jaka część obrazu musi się zmienić. Łapie za dużo – zwiększ. Gubi slajdy – zmniejsz.")
        g.add_row("Slajd musi stać przez", self.stable, "Chroni przed zapisywaniem przejść i animacji.")
        if LIVE_RECORDING:
            g.add_row("Sprawdzaj ekran co", self.interval)
        g.add_row("Odczytuj tekst ze slajdów", self.ocr,
                  f"OCR {'Apple Vision' if IS_MAC else 'Windows'} – treść slajdów trafia do notatek.")
        v.addWidget(g)

        # ---------------- Dźwięk ----------------
        backends = [("auto", "Automatycznie"), ("sck", "ScreenCaptureKit")] if IS_MAC else             [("auto", "Automatycznie"), ("proctap", "proc-tap"), ("native", "Wbudowany (WASAPI)")]
        self.audio_backend = combo(backends, self.s.audio_backend)
        g = GroupSection("Dźwięk", "Zmień, jeśli przy nagrywaniu wybranej aplikacji pasek poziomu dźwięku stoi w miejscu."
                         + (" „Automatycznie” = Core Audio (macOS 14.4+), a gdy się nie uda – ScreenCaptureKit."
                            if IS_MAC else ""))
        g.add_row("Przechwytywanie aplikacji", self.audio_backend)
        self.autostop = QSpinBox()
        self.autostop.setRange(0, 60)
        self.autostop.setSuffix(" min")
        self.autostop.setSpecialValueText("wyłączony")
        self.autostop.setValue(int(self.s.auto_stop_minutes))
        g.add_row("Autostop po ciszy", self.autostop,
                  "Gdy tyle minut nic nie słychać albo zamkniesz aplikację z wykładem, nagrywanie zakończy się "
                  "po 60 s (możesz to anulować).")
        v.addWidget(g)
        g.setVisible(LIVE_RECORDING)    # przechwytywanie dźwięku – Windows i macOS 14.4+

        # ---------------- Zgody macOS ----------------
        if IS_MAC and LIVE_RECORDING:
            from .permission_panel import PermissionPanel
            g = GroupSection("Zgody macOS", "macOS pyta o zgodę osobno na mikrofon, dźwięk aplikacji i nagrywanie "
                                            "ekranu. Wszystko zostaje na tym Macu.")
            self.perms = PermissionPanel(show_granted=True)
            self.perms.restart_requested.connect(self._restart_app)
            g.add(self.perms)
            v.addWidget(g)

        # ---------------- AI ----------------
        self.ai_dot = StatusDot("gray")
        self.ai_text = label("Sprawdzanie…", "secondary", wrap=True)
        self.ai_text.setOpenExternalLinks(True)
        b_ai = QPushButton("Odśwież")
        b_ai.clicked.connect(self.check_ollama)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(260)
        self.btn_pull = QPushButton("Pobierz")
        self.btn_pull.clicked.connect(lambda: self._pull(self.model))
        self.pull_bar = QProgressBar()
        self.pull_bar.setTextVisible(False)
        self.pull_bar.setRange(0, 1000)
        self.pull_bar.hide()
        self.ctx = combo([(8192, "8 tys. tokenów"), (16384, "16 tys. tokenów"), (32768, "32 tys. tokenów")],
                         self.s.ollama_ctx, 200)
        self.cards = QSpinBox()
        self.cards.setRange(1, 10)
        self.cards.setValue(self.s.flashcards_per_section)
        self.live_notes = ToggleSwitch(self.s.live_notes)
        self.live_model = QComboBox()
        self.live_model.setEditable(True)
        self.live_model.setMinimumWidth(260)
        self.btn_pull_live = QPushButton("Pobierz")
        self.btn_pull_live.clicked.connect(lambda: self._pull(self.live_model))
        self.url = QLineEdit(self.s.ollama_url)
        self.url.setMinimumWidth(260)
        g = GroupSection("Notatki AI", "Notatki tworzy lokalny model w programie Ollama – bez internetu i bez opłat. "
                                       "Polecane: " + "; ".join(d for _m, d in RECOMMENDED_MODELS) + ".")
        g.add_row("Stan", hbox(self.ai_dot, self.ai_text, b_ai, spacing=8), stretch=True)
        from ..prompts import NOTES_LANGS
        self.notes_lang = combo([("", "Jak wykład")] + NOTES_LANGS, self.s.notes_language or "")
        g.add_row("Język notatek", self.notes_lang,
                  "Domyślny język notatek, fiszek i podsumowania. „Jak wykład” – w języku, w którym mówi prowadzący. "
                  "Inny język: terminy fachowe dostaną oryginał w nawiasie, a cytaty i definicje słowo w słowo "
                  "zostaną w oryginale. Możesz to zmienić przy każdej notatce.")
        self.model_row = g.add_row("Model notatek (po wykładzie)", hbox(self.model, self.btn_pull, spacing=6))
        self.model_row.subtitle.setText("Mocniejszy model – pełna notatka, podsumowanie, fiszki, pytania i egzaminy.")
        self.model_row.subtitle.show()
        lm = g.add_row("Model na żywo (w trakcie)", hbox(self.live_model, self.btn_pull_live, spacing=6))
        lm.subtitle.setText("Lżejszy model do notatek w trakcie nagrywania – zostawia miejsce na karcie dla "
                            "rozpoznawania mowy. Po zakończeniu notatka powstaje od nowa mocniejszym modelem.")
        lm.subtitle.show()
        g.add(self._wrap(self.pull_bar))
        self.reuse = ToggleSwitch(bool(getattr(self.s, "reuse_live_notes", False)))
        live_rows = [lm]
        live_rows.append(g.add_row("Notatki i pytania na żywo", self.live_notes,
                  "Notatki powstają w trakcie nagrywania, a pytania można zadawać od razu. Whisper działa wtedy w "
                  "oszczędniejszym trybie, żeby oba modele zmieściły się w pamięci karty graficznej."))
        live_rows.append(g.add_row("Szybkie zakończenie", self.reuse,
                  "Fragmenty napisane w trakcie nagrywania zostają w notatce – po wykładzie dopisuje się tylko reszta, "
                  "fiszki i podsumowanie. Dużo szybciej, ale te fragmenty pisał lżejszy model."))
        if not LIVE_RECORDING:      # Mac: bez nagrywania na żywo
            for row in live_rows:
                row.setVisible(False)
        self.describe = ToggleSwitch(bool(getattr(self.s, "describe_slides", True)))
        self.vision_model = QComboBox()
        self.vision_model.setEditable(True)
        self.vision_model.setMinimumWidth(260)
        for m_, d_ in VISION_MODELS:
            self.vision_model.addItem(d_, m_)
        i_ = self.vision_model.findData(self.s.vision_model)
        if i_ >= 0:
            self.vision_model.setCurrentIndex(i_)
        else:
            self.vision_model.setEditText(self.s.vision_model)
        g.add_row("Opisuj obrazy na slajdach", self.describe,
                  "Zdjęcia, schematy, wykresy i tabele ze slajdów dostają opis w notatkach („Na slajdzie”), a model "
                  "dokładniej odczytuje tekst i wzory. Dodaje ok. 5 s na slajd po wykładzie.")
        g.add_row("Model do slajdów (widzi obrazy)", self.vision_model,
                  "Pobiera się sam przy pierwszym użyciu.")
        self.describe.toggled.connect(self.vision_model.setEnabled)
        self.vision_model.setEnabled(self.describe.isChecked())
        g.add_row("Fiszek na fragment wykładu", self.cards)
        g.add_row("Kontekst modelu", self.ctx, "Więcej = model widzi dłuższe fragmenty, ale zużywa więcej pamięci karty.")
        g.add_row("Adres serwera Ollama", self.url)
        v.addWidget(g)

        # ---------------- Aktualizacje ----------------
        self.updates = UpdateSection(self.s, lambda: self.busy_fn())
        v.addWidget(self.updates)

        # ---------------- Pomoc ----------------
        b_log = QPushButton("Otwórz log")
        b_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path()))))
        debug = ("w Terminalu wpisz „/Applications/Wykłady.app/Contents/MacOS/Wyklady --debug” (komunikaty w oknie "
                 "Terminala)" if IS_MAC else "uruchom „Wykłady.exe --debug” (okno z komunikatami)")
        g = GroupSection("Pomoc", f"Gdy coś nie działa, {debug} albo prześlij treść logu.")
        g.add_row("Dziennik zdarzeń", b_log)
        v.addWidget(g)

        # ---------------- O aplikacji ----------------
        v.addWidget(self._about())
        v.addStretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_centered(col, 720))

        # auto-zapis
        for w in (self.auto, self.ocr, self.live_notes, self.describe, self.reuse):
            w.toggled.connect(self.save)
        self.vision_model.currentIndexChanged.connect(self.save)
        self.vision_model.editTextChanged.connect(self.save)
        for w in (self.w_model, self.lang, self.notes_lang, self.w_device, self.audio_backend, self.ctx, self.beam):
            w.currentIndexChanged.connect(self.save)
        for w in (self.chunk, self.cards):
            w.valueChanged.connect(self.save)
        for w in (self.stable, self.interval):
            w.valueChanged.connect(self.save)
        self.sens.valueChanged.connect(self.save)
        self.model.currentTextChanged.connect(self.save)
        self.live_model.currentTextChanged.connect(self.save)
        self.autostop.valueChanged.connect(self.save)
        self.url.editingFinished.connect(self.save)

        self.ollama_status_signal.connect(self._on_ollama_status)
        self.pull_progress.connect(self._on_pull_progress)
        self.pull_done.connect(self._on_pull_done)
        self.gpu_result.connect(self._on_gpu)
        self.hw_ready.connect(self._on_hw)
        self.whisper_have.connect(self._on_whisper_have)
        self._fill_models([])
        self._loading = False
        self._update_profiles()
        QTimer.singleShot(400, self.check_ollama)
        QTimer.singleShot(200, lambda: self._detect_hw(False))

    def _restart_app(self):
        """Mac: zgoda na nagrywanie ekranu działa dopiero po ponownym uruchomieniu."""
        w = self.window()
        if hasattr(w, "_restart_after_update"):
            w._restart_after_update()

    def _about(self) -> QWidget:
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
        from .. import version
        from .controls import set_icon
        from .theme import logo_pixmap
        box = QFrame()
        box.setObjectName("group")
        h = QHBoxLayout(box)
        h.setContentsMargins(20, 18, 20, 18)
        h.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(46, self.devicePixelRatioF() or 2.0))
        h.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(4)
        v.addWidget(label(f"Wykłady {version.VERSION}", "title3"))
        txt = label(f"Aplikacja stworzona przez <b>{version.AUTHOR}</b> wyłącznie w celach osobistych – do własnej "
                    "nauki. Udostępniana bez gwarancji. Wszystko działa lokalnie: nagrania, notatki i fiszki nie opuszczają "
                    "Twojego komputera. Pamiętaj o zasadach uczelni dotyczących nagrywania zajęć.", "secondary", wrap=True)
        txt.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(txt)
        links = QHBoxLayout()
        links.setSpacing(6)
        icons = {"GitHub": "share", "LinkedIn": "open", "Portfolio": "open"}
        for name, url in version.LINKS.items():
            b = QPushButton(name)
            b.setObjectName("plain")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(url)
            set_icon(b, icons.get(name, "open"), "accent", 14)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links.addWidget(b)
        if version.REPO:
            b = QPushButton("Strona projektu")
            b.setObjectName("plain")
            set_icon(b, "books", "accent", 14)
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{version.REPO}")))
            links.addWidget(b)
        links.addStretch()
        v.addLayout(links)
        h.addLayout(v, 1)
        return box

    @staticmethod
    def _wrap(w):
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(14, 6, 14, 8)
        l.addWidget(w)
        box.setVisible(False)
        w._box = box
        return box

    # ------------------------------------------------------------------
    def _theme_changed(self, i: int):
        self.s.theme = THEMES[i][0]
        self.s.save()
        theme().set_mode(self.s.theme)
        self._mark_theme()

    def _theme_name_changed(self, name: str):
        self.s.theme_name = name
        self.s.save()
        theme().set_name(name)
        self._mark_theme()

    def _mark_theme(self):
        for n, c in self.theme_cards.items():
            c.selected = n == getattr(self.s, "theme_name", "zeszyt")
            c.update()

    def _scale_changed(self, _i: int):
        new = float(self.scale.currentData())
        if abs(new - float(self.s.ui_scale or 1.0)) < 0.01:
            return
        self.s.ui_scale = new
        self.s.save()
        self.scale_row.subtitle.setText("Zapisano – nowy rozmiar będzie widoczny po ponownym uruchomieniu aplikacji.")

    def _pick_lib(self):
        d = QFileDialog.getExistingDirectory(self, "Folder biblioteki", self.s.library_dir)
        if d:
            self.s.library_dir = d
            self.lib_row.subtitle.setText(d)
            self.save()

    def _fill_combo(self, combo: QComboBox, installed: list[str], fallback: str):
        cur = self._combo_model(combo) if combo.count() else fallback
        combo.blockSignals(True)
        combo.clear()
        names = list(installed) + [m for m, _d in RECOMMENDED_MODELS if m not in installed]
        for n in names:
            combo.addItem(n + ("" if n in installed else "  (do pobrania)"), n)
        i = combo.findData(cur)
        if i >= 0:
            combo.setCurrentIndex(i)
        else:
            combo.setEditText(cur)
        combo.blockSignals(False)

    def _fill_models(self, installed: list[str]):
        self._fill_combo(self.model, installed, self.s.ollama_model)
        self._fill_combo(self.live_model, installed, self.s.live_model)
        self._installed = installed

    @staticmethod
    def _combo_model(combo: QComboBox) -> str:
        data = combo.currentData()
        text = combo.currentText().replace("  (do pobrania)", "").strip()
        return str(data) if data and text == str(data) else text

    def current_model(self) -> str:
        return self._combo_model(self.model)

    def check_ollama(self):
        url = self.url.text().strip() or self.s.ollama_url

        def work():
            llm = Ollama(url)
            self.ollama_status_signal.emit("up" if llm.is_running() else "down", llm.list_models())
        threading.Thread(target=work, daemon=True).start()

    def _on_ollama_status(self, state: str, models: list):
        self._ollama_up = state != "down"
        self._fill_models(models)
        self._update_profiles()
        has = lambda m: m in models or f"{m}:latest" in models  # noqa: E731
        main, live = self.current_model(), self._combo_model(self.live_model)
        self.btn_pull.setEnabled(state != "down" and not has(main))
        self.btn_pull_live.setEnabled(state != "down" and not has(live))
        if state == "down":
            self.ai_dot.set("red")
            self.ai_text.setText("Ollama nie działa. Zainstaluj ją (<a href='https://ollama.com/download'>ollama.com</a>) "
                                 "albo uruchom install.bat.")
        elif has(main) and has(live):
            self.ai_dot.set("green")
            self.ai_text.setText("Gotowe – oba modele są pobrane.")
        else:
            missing = [m for m in (main, live) if not has(m)]
            self.ai_dot.set("orange")
            self.ai_text.setText("Ollama działa, ale brakuje modelu: " + ", ".join(dict.fromkeys(missing)) + ".")

    def _pull(self, combo: QComboBox):
        model = self._combo_model(combo)
        url = self.url.text().strip()
        self.btn_pull.setEnabled(False)
        self.btn_pull_live.setEnabled(False)
        self.pull_bar._box.show()

        def work():
            try:
                Ollama(url).pull(model, progress=lambda st, f: self.pull_progress.emit(st, f))
                self.pull_done.emit(True, model)
            except Exception as e:  # noqa: BLE001
                self.pull_done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_pull_progress(self, status: str, frac: float):
        self.ai_text.setText(f"Pobieranie: {status}")
        if self._pulling_many:
            self.perf_row.subtitle.setText(f"Pobieranie: {status}")
        for bar in (self.pull_bar, self.perf_bar):
            if frac < 0:
                bar.setRange(0, 0)
            else:
                bar.setRange(0, 1000)
                bar.setValue(int(frac * 1000))

    def _on_pull_done(self, ok: bool, msg: str):
        self.pull_bar._box.hide()
        self.perf_bar._box.hide()
        self._pulling_many = False
        self.btn_get.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "Pobieranie modelu", msg)
        self.check_ollama()
        self._check_whisper()

    # ------------------------------------------------------------------ profile wydajności
    _pulling_many = False
    _ollama_up = False
    _whisper_ok = True

    def _detect_hw(self, refresh: bool):
        if refresh:
            self.hw_row.subtitle.setText("Sprawdzam sprzęt…")

        def work():
            try:
                hw = perf.hardware(self.s, refresh=refresh or not getattr(self.s, "hw_info", None))
            except Exception:  # noqa: BLE001
                hw = {}
            self.hw_ready.emit(hw)
        threading.Thread(target=work, daemon=True).start()
        self._check_whisper()

    def _on_hw(self, hw: dict):
        self.hw = hw
        if hw:
            key, why = perf.recommend(hw)
            self.hw_row.subtitle.setText(f"{perf.describe(hw)}<br>Polecany profil: <b>{perf.LABELS[key]}</b>. {why}")
            self.hw_row.subtitle.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.hw_row.subtitle.setText("Nie udało się sprawdzić sprzętu.")
        self._update_profiles()

    def _check_whisper(self):
        name = self.s.whisper_model

        def work():
            try:
                from faster_whisper.utils import download_model
                download_model(name, local_files_only=True)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            self.whisper_have.emit(ok)
        threading.Thread(target=work, daemon=True).start()

    def _on_whisper_have(self, ok: bool):
        self._whisper_ok = ok
        self._update_profiles()

    def _needed_models(self) -> list[str]:
        s = self.s
        out = [s.ollama_model] + ([s.live_model] if s.live_notes else []) + \
              ([s.vision_model] if s.describe_slides else [])
        return list(dict.fromkeys(m for m in out if m))

    def _update_profiles(self):
        if not hasattr(self, "profile_cards"):
            return
        hw = self.hw or {}
        rec = perf.recommend(hw)[0] if hw else ""
        cur = perf.current(self.s, hw) if hw else (getattr(self.s, "hw_profile", "") or "")
        for k, c in self.profile_cards.items():
            gb = perf.download_gb(k, hw, with_libs=False)
            c.set_state(selected=k == cur, recommended=k == rec, size_text=f"Do pobrania ok. {perf.fmt_gb(gb)}")
        if self._pulling_many:
            return
        installed = getattr(self, "_installed", [])
        has = lambda m: m in installed or f"{m}:latest" in installed  # noqa: E731
        self._missing = [m for m in self._needed_models() if not has(m)] if self._ollama_up else []
        parts = []
        if not cur:
            parts.append("<b>Własne ustawienia</b> – coś zmieniono ręcznie. Kliknij profil, żeby wrócić do gotowego "
                         "zestawu.")
        else:
            parts.append(f"<b>{perf.LABELS[cur]}</b>.")
        todo = [(m.split("/")[-1], perf.model_gb(m)) for m in self._missing]
        if not self._whisper_ok:
            todo.insert(0, (f"model mowy {self.s.whisper_model}", perf.WHISPER_GB.get(self.s.whisper_model, 1.5)))
        if todo:
            tot = sum(g for _n, g in todo)
            parts.append("Do pobrania: " + ", ".join(n for n, _g in todo) + f" – ok. {perf.fmt_gb(tot)}.")
        elif self._ollama_up:
            parts.append("Wszystkie modele są pobrane.")
        if not self._ollama_up:
            parts.append("Ollama nie działa – modele AI pobiorą się, gdy ją uruchomisz.")
        self.perf_row.subtitle.setTextFormat(Qt.TextFormat.RichText)
        self.perf_row.subtitle.setText(" ".join(parts))
        self.btn_get.setVisible(bool(todo))

    def _profile_clicked(self, key: str):
        if self._pulling_many:
            return
        if not self.hw:
            self.hw = perf.hardware(self.s)
        perf.apply(self.s, key, self.hw)
        self.s.save()
        self._load_widgets()
        self.saved.emit()
        self._whisper_ok = True
        self._update_profiles()
        self.check_ollama()
        self._check_whisper()

    def _load_widgets(self):
        """Kontrolki niżej po zmianie profilu (bez zapisu po drodze)."""
        s = self.s
        self._loading = True
        try:
            for c, val in ((self.w_model, s.whisper_model), (self.beam, int(s.whisper_beam)), (self.ctx, int(s.ollama_ctx))):
                i = c.findData(val)
                if i >= 0:
                    c.setCurrentIndex(i)
            self.chunk.setValue(int(s.live_chunk_seconds))
            self.live_notes.setChecked(bool(s.live_notes))
            self.describe.setChecked(bool(s.describe_slides))
            self.reuse.setChecked(bool(s.reuse_live_notes))
            i = self.vision_model.findData(s.vision_model)
            if i >= 0:
                self.vision_model.setCurrentIndex(i)
            else:
                self.vision_model.setEditText(s.vision_model)
            for c, val in ((self.model, s.ollama_model), (self.live_model, s.live_model)):
                c.blockSignals(True)
                i = c.findData(val)
                if i < 0:
                    c.addItem(val + "  (do pobrania)", val)
                    i = c.count() - 1
                c.setCurrentIndex(i)
                c.blockSignals(False)
        finally:
            self._loading = False

    def _pull_missing(self):
        models = list(self._missing)
        whisper = None if self._whisper_ok else self.s.whisper_model
        if not models and not whisper:
            return
        url = self.url.text().strip() or self.s.ollama_url
        self._pulling_many = True
        self.btn_get.setEnabled(False)
        self.btn_pull.setEnabled(False)
        self.btn_pull_live.setEnabled(False)
        self.perf_bar._box.show()

        def work():
            try:
                if whisper:
                    self.pull_progress.emit(f"model mowy {whisper}…", -1)
                    from faster_whisper.utils import download_model
                    download_model(whisper)
                for k, m in enumerate(models, 1):
                    short = m.split("/")[-1]
                    pre = f"{short} ({k}/{len(models)})" if len(models) > 1 else short
                    Ollama(url).pull(m, progress=lambda st, f, pre=pre: self.pull_progress.emit(f"{pre} · {st}", f))
                self.pull_done.emit(True, "")
            except Exception as e:  # noqa: BLE001
                self.pull_done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _check_gpu(self):
        self.gpu_text.setText("Sprawdzanie…")

        def work():
            try:
                from ..transcriber import cuda_available
                import ctranslate2
                n = ctranslate2.get_cuda_device_count()
                if cuda_available():
                    self.gpu_result.emit("green", "Działa – transkrypcja na karcie graficznej.")
                elif n > 0:
                    self.gpu_result.emit("orange", "Brak bibliotek CUDA – uruchom ponownie install.bat.")
                else:
                    self.gpu_result.emit("red", "Nie wykryto karty NVIDIA – użyty zostanie procesor.")
            except Exception as e:  # noqa: BLE001
                self.gpu_result.emit("red", f"Błąd: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _on_gpu(self, kind: str, text: str):
        self.gpu_dot.set(kind)
        self.gpu_text.setText(text)

    def save(self, *_):
        if self._loading:
            return
        s = self.s
        s.whisper_model = self.w_model.currentData()
        s.whisper_device = self.w_device.currentData()
        s.language = self.lang.currentData()
        s.notes_language = self.notes_lang.currentData() or ""
        s.live_chunk_seconds = float(self.chunk.value())
        s.whisper_beam = int(self.beam.currentData())
        s.reuse_live_notes = self.reuse.isChecked()
        s.slide_sensitivity = self.sens.value() / 100
        s.slide_stable_seconds = self.stable.value()
        s.slide_interval = self.interval.value()
        s.ocr_enabled = self.ocr.isChecked()
        s.audio_backend = self.audio_backend.currentData()
        s.ollama_url = self.url.text().strip() or s.ollama_url
        s.ollama_model = self.current_model() or s.ollama_model
        s.live_model = self._combo_model(self.live_model) or s.live_model
        s.auto_stop_minutes = self.autostop.value()
        s.ollama_ctx = int(self.ctx.currentData())
        s.flashcards_per_section = self.cards.value()
        s.auto_generate_notes = self.auto.isChecked()
        s.live_notes = self.live_notes.isChecked()
        s.describe_slides = self.describe.isChecked()
        vt = self.vision_model.currentText().strip()
        vi = self.vision_model.findText(vt)
        vm = self.vision_model.itemData(vi) if vi >= 0 else vt.split()[0] if vt else ""
        if vm:
            s.vision_model = vm
        s.hw_profile = perf.current(s, self.hw)
        s.save()
        self.saved.emit()
        self._update_profiles()
        if self.sender() in (self.model, self.live_model, self.url):
            self._on_ollama_status("up" if self.ai_dot.kind != "red" else "down", getattr(self, "_installed", []))
