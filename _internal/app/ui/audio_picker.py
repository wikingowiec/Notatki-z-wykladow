"""Wybór źródła dźwięku: lista „Programy do spotkań i przeglądarki / Grają teraz / Urządzenia / Pozostałe”
z poziomem na żywo, polem „Szukaj…” (gdy źródeł jest dużo), przyciskami „Odsłuchaj”, „Odśwież” i „Pokaż wszystkie”.
Lista sama się odświeża co kilka sekund, gdy jest widoczna – bez zmiany zaznaczenia i bez przewijania."""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..audio_capture import LevelMonitor, PLAYING, list_audio_sources, play_preview, record_preview, source_key
from .controls import hbox, label, set_icon, show_if
from .theme import T, icon_pixmap, qcolor
from .widgets import run_async
from ..i18n import tr

R_IDX = Qt.ItemDataRole.UserRole          # indeks w liście źródeł; -1 = nagłówek grupy
PREVIEW_S = 4
ROW_H, HEAD_H = 44, 26
MAX_ROWS = 6                              # wyżej lista ma własny pasek przewijania
SEARCH_FROM = 9                           # pole „Szukaj…” od tylu źródeł
AUTO_REFRESH_MS = 4000
ICONS = {"process": "speaker", "system": "display", "mic": "mic"}


def _key(s) -> tuple:
    """Tożsamość źródła między odświeżeniami (PID się zmienia po ponownym uruchomieniu aplikacji, exe – nie)."""
    return (s.kind, (s.exe or "").lower(), s.device_index)


class _SourceDelegate(QStyledItemDelegate):
    """Wiersz: ikona, nazwa, szara druga linijka, z prawej mały wskaźnik poziomu (5 słupków)."""

    def __init__(self, picker: "AudioSourcePicker"):
        super().__init__(picker.list)
        self.picker = picker

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), HEAD_H if index.data(R_IDX) == -1 else ROW_H)

    def paint(self, p: QPainter, option, index):
        t = T()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        idx = index.data(R_IDX)
        if idx == -1:                                    # nagłówek grupy
            f = QFont(option.font)
            f.setPointSizeF(f.pointSizeF() - 1.5)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(qcolor(t.text3))
            p.drawText(r.adjusted(14, 0, -8, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       p.fontMetrics().elidedText(text.upper(), Qt.TextElideMode.ElideRight, int(r.width() - 22)))
            p.restore()
            return
        if not (0 <= idx < len(self.picker.sources)):
            p.restore()
            return
        info = self.picker.sources[idx]
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        box = r.adjusted(4, 2, -4, -2)
        if sel or hov:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft if sel else t.hover))
            p.drawRoundedRect(box, t.r("sm"), t.r("sm"))
        dpr = self.picker.devicePixelRatioF()
        role = t.accent if sel or info.active else t.text3
        p.drawPixmap(QRectF(box.left() + 10, box.center().y() - 9, 18, 18),
                     icon_pixmap(ICONS.get(info.kind, "speaker"), role, 18, dpr), QRectF())
        # wskaźnik poziomu
        level = self.picker.shown_level(info)
        mw = 34
        meter = QRectF(box.right() - mw - 12, box.center().y() - 8, mw, 16)
        if self.picker.measurable(info):          # niewybrany mikrofon – bez wskaźnika (nie mierzymy go)
            self._meter(p, meter, level)
        # teksty
        x = box.left() + 38
        tw = meter.left() - x - 10
        f = QFont(option.font)
        if sel:
            f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        fm = p.fontMetrics()
        p.drawText(QRectF(x, box.top() + 3, tw, box.height() / 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   fm.elidedText(text, Qt.TextElideMode.ElideRight, int(tw)))
        f2 = QFont(option.font)
        f2.setPointSizeF(f2.pointSizeF() - 1.5)
        p.setFont(f2)
        p.setPen(qcolor(t.green if info.active and info.kind == "process" else t.text3))
        sub = info.detail
        if self.picker.is_last_used(info):
            sub = (sub + " · " if sub else "") + tr("ostatnio używane")
        sub = sub or (" " if info.kind != "mic" else "")
        p.drawText(QRectF(x, box.center().y() + 1, tw, box.height() / 2 - 3),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, int(tw)))
        p.restore()

    @staticmethod
    def _meter(p: QPainter, r: QRectF, level: float):
        """5 słupków rosnących w prawo; skala logarytmiczna (−50…0 dB), żeby było widać też cichą mowę."""
        t = T()
        n, gap = 5, 2.0
        bw = (r.width() - gap * (n - 1)) / n
        lit = 0 if level <= 0 else max(0.0, min(1.0, (20 * math.log10(max(level, 1e-5)) + 50) / 50)) * n
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            h = r.height() * (0.35 + 0.65 * (i + 1) / n)
            bar = QRectF(r.left() + i * (bw + gap), r.bottom() - h, bw, h)
            if i < lit - 0.25:
                c = qcolor(t.red if i == n - 1 else t.green)
            else:
                c = qcolor(t.track)
            p.setBrush(c)
            p.drawRoundedRect(bar, 1.2, 1.2)


class AudioSourcePicker(QWidget):
    """Lista źródeł dźwięku. Lista zbiera się w tle; poziomy czyta LevelMonitor, gdy widżet jest widoczny."""

    picked = Signal()             # wybór myszką/klawiaturą (nie przez kod)
    loaded = Signal()             # nowa lista po odświeżeniu
    current_changed = Signal()    # zmiana wybranego źródła (także przez kod) – np. inne zgody na Macu

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sources: list = []
        self.show_all = False
        self.monitor = LevelMonitor()
        self._levels: dict[str, float] = {}
        self._loading = False
        self._previewing = False
        self._auto_refresh_at = 0
        self._cur = -1
        self._last_used: dict | None = None    # {"kind", "exe", "device"} z settings.last_rec
        self._user_picked = False              # ręczny wybór – „ostatnio używane” już go nie nadpisze
        self._rows_sig: tuple | None = None

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Szukaj…"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr("Szukaj źródła dźwięku"))
        self.search.textChanged.connect(lambda _t: self._rebuild())
        show_if(self.search, False)

        self.list = QListWidget()
        self.list.setObjectName("sourceList")
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.list.setItemDelegate(_SourceDelegate(self))
        self.list.itemClicked.connect(self._clicked)
        self.list.currentRowChanged.connect(self._row_changed)

        self.btn_preview = QPushButton(tr("Odsłuchaj"))
        set_icon(self.btn_preview, "headphones", "text2", 16)
        self.btn_preview.clicked.connect(self.preview)
        self.btn_refresh = QPushButton(tr("Odśwież"))
        set_icon(self.btn_refresh, "refresh", "text2", 16)
        self.btn_refresh.setToolTip(tr("Zbierz listę jeszcze raz (np. po włączeniu wykładu)"))
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_all = QPushButton(tr("Pokaż wszystkie"))
        self.btn_all.setObjectName("plain")
        self.btn_all.clicked.connect(self._toggle_all)
        self.status = label("", "footnote", wrap=True)
        show_if(self.status, False)

        # pole szukania, lista i przyciski jeden pod drugim – układ zna wysokość listy, więc przyciski
        # zawsze stoją pod nią (nigdy na niej)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 12)
        lay.setSpacing(8)
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        lay.addWidget(hbox(self.btn_preview, self.btn_refresh, "stretch", self.btn_all, spacing=6))
        lay.addWidget(self.status)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._tick)
        self.auto_timer = QTimer(self)              # samoczynne odświeżanie, gdy lista jest widoczna
        self.auto_timer.setInterval(AUTO_REFRESH_MS)
        self.auto_timer.timeout.connect(lambda: self._previewing or self.refresh(quiet=True))

    # ------------------------------------------------------------------ lista
    def set_last_used(self, audio: dict | None):
        """Ostatnio nagrywane źródło (settings.last_rec["audio"]) – zaznaczane od razu, gdy jest na liście."""
        self._last_used = dict(audio) if audio else None
        self.list.viewport().update()

    def is_last_used(self, info) -> bool:
        lu = self._last_used
        if not lu or info.kind != lu.get("kind"):
            return False
        if info.kind == "process":
            return bool(info.exe) and info.exe.lower() == (lu.get("exe") or "").lower()
        if info.kind == "mic":
            return info.device_index == lu.get("device", -1)
        return True

    def refresh(self, quiet: bool = False):
        """quiet – samoczynne odświeżenie w tle (przycisk „Odśwież” nie miga)."""
        if self._loading:
            return
        self._loading = True
        if not quiet:
            self.btn_refresh.setEnabled(False)

        def work():
            try:
                import comtypes
                comtypes.CoInitialize()
            except Exception:
                pass
            return list_audio_sources()

        def fail(_e):
            self._loading = False
            self.btn_refresh.setEnabled(True)
        run_async(work, self.set_sources, fail)

    def set_sources(self, sources):
        self._loading = False
        self.btn_refresh.setEnabled(True)
        prev = self.current()
        prev_key = _key(prev) if prev else None
        self.sources = list(sources)
        self._cur = -1
        self.monitor.set_known(s.pid for s in self.sources if s.kind == "process")
        idx = -1
        if prev_key:
            idx = next((i for i, s in enumerate(self.sources) if _key(s) == prev_key), -1)
        if idx < 0 and not self._user_picked:      # ostatnio używane, jeśli jest uruchomione
            idx = next((i for i, s in enumerate(self.sources) if self.is_last_used(s)), -1)
        if idx < 0:
            idx = next((i for i, s in enumerate(self.sources) if s.kind == "process" and s.active), 0)
        self._cur = idx if 0 <= idx < len(self.sources) else -1
        many = len(self.sources) >= SEARCH_FROM
        if not many and self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        show_if(self.search, many)
        self._rebuild()
        self._row_changed()
        self.loaded.emit()

    def _groups(self):
        q = self.search.text().strip().lower() if not self.search.isHidden() else ""
        cur = self.current_index()
        if q:              # szukanie obejmuje też schowane źródła
            def match(s):
                return q in s.label.lower() or q in (s.exe or "").lower() or q in (s.detail or "").lower()
            ok = [i for i, s in enumerate(self.sources) if match(s)]
            meeting = [i for i in ok if self.sources[i].group == "meeting"]
            playing = [i for i in ok if self.sources[i].kind == "process" and not self.sources[i].group and
                       not self.sources[i].hidden]
            devices = [i for i in ok if self.sources[i].kind != "process"]
            rest = [i for i in ok if self.sources[i].kind == "process" and not self.sources[i].group and
                    self.sources[i].hidden]
        else:
            meeting = [i for i, s in enumerate(self.sources) if s.group == "meeting"]
            playing = [i for i, s in enumerate(self.sources) if s.kind == "process" and not s.group and not s.hidden]
            devices = [i for i, s in enumerate(self.sources) if s.kind != "process" and (self.show_all or not s.hidden)]
            rest = [i for i, s in enumerate(self.sources) if s.kind == "process" and not s.group and s.hidden]
            if not self.show_all:        # wybrane źródło nie znika z listy, nawet gdy jest „schowane”
                rest = [i for i in rest if i == cur]
                devices += [cur] if cur >= 0 and self.sources[cur].kind != "process" and cur not in devices else []
        return [(tr("Programy do spotkań i przeglądarki"), meeting), (tr("Grają teraz"), playing),
                (tr("Urządzenia"), devices), (tr("Pozostałe aplikacje"), rest)]

    def _rebuild(self):
        """Odbudowuje wiersze tylko wtedy, gdy coś się zmieniło – przewinięcie listy zostaje na miejscu."""
        cur = self.current_index()
        rows = []
        for title, idxs in self._groups():
            if idxs:
                rows.append((-1, title))
                rows += [(i, self.sources[i].label) for i in idxs]
        sig = tuple((i, text, _key(self.sources[i]) if i >= 0 else None) for i, text in rows)
        if sig != self._rows_sig:
            self._rows_sig = sig
            scroll = self.list.verticalScrollBar().value()
            self.list.setUpdatesEnabled(False)
            self.list.blockSignals(True)
            self.list.clear()
            for i, text in rows:
                it = QListWidgetItem(text)
                it.setData(R_IDX, i)
                if i == -1:
                    it.setFlags(Qt.ItemFlag.NoItemFlags)
                    it.setSizeHint(QSize(0, HEAD_H))
                else:
                    it.setSizeHint(QSize(0, ROW_H))
                self.list.addItem(it)
            self.list.blockSignals(False)
            self._sync_height(rows)
            self.list.verticalScrollBar().setValue(scroll)
            self.list.setUpdatesEnabled(True)
        self._select_item(cur)
        self.list.viewport().update()
        hidden = sum(1 for s in self.sources if s.hidden)
        searching = bool(self.search.text().strip())
        self.btn_all.setText(tr("Pokaż mniej") if self.show_all else tr("Pokaż wszystkie ({hidden})", hidden=hidden))
        show_if(self.btn_all, (hidden > 0 or self.show_all) and not searching)
        self._update_buttons()

    def _sync_height(self, rows):
        """Lista ma wysokość treści, najwyżej MAX_ROWS wierszy – dalej przewija się sama. Przyciski są pod nią
        w tym samym układzie, a karta wokół rośnie razem z nią."""
        content = sum(HEAD_H if i == -1 else ROW_H for i, _ in rows) or ROW_H
        fw = 2 * self.list.frameWidth()
        cap = HEAD_H * 2 + ROW_H * MAX_ROWS
        self.list.setFixedHeight(min(content, cap) + fw + 4)
        self.list.updateGeometry()
        w = self
        while w is not None and not w.isWindow():       # karta, kolumna i przewijana strona przeliczają wysokość
            w.updateGeometry()
            if w.layout() is not None:
                w.layout().invalidate()
            w = w.parentWidget()

    def _toggle_all(self):
        self.show_all = not self.show_all
        self._rebuild()

    # ------------------------------------------------------------------ wybór
    def current_index(self) -> int:
        return self._cur if 0 <= self._cur < len(self.sources) else -1

    def current(self):
        i = self.current_index()
        return self.sources[i] if i >= 0 else None

    def set_current(self, idx: int):
        if not (0 <= idx < len(self.sources)):
            return
        self._cur = idx
        if self._item_for(idx) is None:      # schowane źródło – lista pokaże je mimo to (patrz _groups)
            self._rebuild()
        self._select_item(idx)
        self._row_changed()

    def _select_item(self, idx: int):
        self.list.blockSignals(True)
        it = self._item_for(idx)
        if it is not None:
            self.list.setCurrentItem(it)
        else:
            self.list.clearSelection()
        self.list.blockSignals(False)

    def _item_for(self, idx: int):
        if idx < 0:
            return None
        for r in range(self.list.count()):
            if self.list.item(r).data(R_IDX) == idx:
                return self.list.item(r)
        return None

    def _clicked(self, it):
        if it is not None and isinstance(it.data(R_IDX), int) and it.data(R_IDX) >= 0:
            self._user_picked = True
            self.picked.emit()

    def _row_changed(self, *_):
        it = self.list.currentItem()
        i = it.data(R_IDX) if it is not None else -1
        if isinstance(i, int) and i >= 0:
            self._cur = i
        self.monitor.set_source(self.current())
        self._update_buttons()
        self.current_changed.emit()

    def _update_buttons(self):
        info = self.current()
        mic = info is not None and info.kind == "mic"
        self.btn_preview.setEnabled(info is not None and not mic and not self._previewing)
        self.btn_preview.setToolTip(tr("Przy mikrofonie odsłuch dawałby sprzężenie (pisk) – sprawdź wskaźnik poziomu "
                                    "przy nazwie: powinien skakać, gdy mówisz.") if mic else
                                    tr("Nagra {preview_s} s z tego źródła i od razu je odtworzy – usłyszysz dokładnie to, co trafi "
                                       "do nagrania.", preview_s=PREVIEW_S))

    # ------------------------------------------------------------------ poziomy na żywo
    def measurable(self, info) -> bool:
        """Windows: mikrofon tylko wybrany (inaczej system pokazywałby, że wszystkie są w użyciu).
        Mac: tylko wybrane źródło i tylko po udzieleniu zgody (macOS nie ma mierników bez nagrywania)."""
        return self.monitor.measurable(info, self.current())

    def shown_level(self, info) -> float:
        return self._levels.get(source_key(info), 0.0)

    def _tick(self):
        raw = self.monitor.levels
        lv = {}
        for k in set(raw) | set(self._levels):       # szybki wzrost, powolne opadanie
            new = raw.get(k, 0.0)
            old = self._levels.get(k, 0.0)
            lv[k] = new if new >= old else max(new, old * 0.82)
        self._levels = lv
        self.list.viewport().update()
        # aplikacja zaczęła grać, a nie ma jej na liście (albo jest schowana) → odśwież, najwyżej co 3 s
        self._auto_refresh_at = max(0, self._auto_refresh_at - 1)
        starting = set(self.monitor.new_playing)
        for s in self.sources:
            if s.kind == "process" and s.hidden and raw.get(source_key(s), 0.0) >= PLAYING * 5:
                starting.add(s.pid)
        if starting and not self._auto_refresh_at and not self._loading and not self._previewing:
            self._auto_refresh_at = 3000 // self.timer.interval()
            self.refresh(quiet=True)

    def start_monitor(self):
        if not self.monitor.running:
            self.monitor.set_source(self.current())
            self.monitor.start()
        self.timer.start()
        self.auto_timer.start()

    def stop_monitor(self):
        """Zwalnia mikrofon i mierniki – wołane m.in. tuż przed startem nagrywania."""
        self.timer.stop()
        self.auto_timer.stop()
        self.monitor.stop(wait=False)          # wątek UI nie czeka – mikrofon zamknie się za chwilę
        self._levels = {}
        self.list.viewport().update()

    def showEvent(self, e):
        super().showEvent(e)
        self.start_monitor()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.stop_monitor()

    # ------------------------------------------------------------------ odsłuch
    def preview(self):
        info = self.current()
        if info is None or info.kind == "mic" or self._previewing:
            return
        self._previewing = True
        self._update_buttons()
        self.btn_preview.setText(tr("Słucham {preview_s} s…", preview_s=PREVIEW_S))
        self._say(tr("Nagrywam {preview_s} sekundy z „{label}”…", preview_s=PREVIEW_S, label=info.label))

        def recorded(res):
            audio, rate = res
            peak = float(abs(audio).max()) if audio.size else 0.0
            if peak < 1e-3:
                self._preview_done(tr("Nic nie było słychać. ") + (
                    tr("Ta aplikacja teraz nie gra – włącz wykład i spróbuj jeszcze raz.") if info.kind == "process"
                    else tr("Na komputerze nic teraz nie gra.")))
                return
            self.btn_preview.setText(tr("Odtwarzam…"))
            self._say(tr("Odtwarzam to, co się nagrało – tak będzie brzmiało nagranie wykładu."))
            run_async(lambda: play_preview(audio, rate),
                      lambda _r: self._preview_done(tr("Odsłuch zakończony. Jeśli było słychać wykład – możesz nagrywać.")),
                      lambda e: self._preview_done(tr("Nie udało się odtworzyć: {e}", e=e)))

        run_async(lambda: record_preview(info, PREVIEW_S), recorded,
                  lambda e: self._preview_done(tr("Nie udało się nagrać z tego źródła: {e}", e=e)))

    def _preview_done(self, text: str):
        self._previewing = False
        self.btn_preview.setText(tr("Odsłuchaj"))
        self._update_buttons()
        self._say(text)

    def _say(self, text: str):
        self.status.setText(text)
        show_if(self.status, bool(text))
