"""Widoczne skutki sprawdzenia (nowe w 2.3): karta problemu na ekranie nagrywania i baner „Ollama nie działa”.

OllamaWatch – jeden na aplikację. Co ok. 10 s, w tle i tylko gdy któryś baner jest na widocznej stronie, pyta Ollamę,
czy działa i jakie ma modele. Uruchamia Ollamę i pobiera modele (llm.Ollama.pull – jak instalator, z zapamiętaniem
modelu do odinstalowania). Banery tylko wyświetlają jego stan, więc postęp pobierania widać w każdym z nich.

ProblemCard – lista problemów z healthcheck.run_checks: dlaczego, kroki naprawy, przycisk akcji naprawy oraz
„Nagrywaj mimo to” / „Anuluj”. Same akcje wykonuje ekran nagrywania (sygnał action)."""
from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import healthcheck as hc
from ..i18n import tn, tr
from .controls import label, repolish, set_icon, show_if
from .theme import T

log = logging.getLogger(__name__)
POLL_MS = 10_000


# ---------------------------------------------------------------------------------------------- stan Ollamy
class OllamaWatch(QObject):
    changed = Signal()
    _result = Signal(object)
    _progress = Signal(str, float)
    _finished = Signal(str, str)          # rodzaj zadania, błąd ("" = OK)

    _inst: Optional["OllamaWatch"] = None

    @classmethod
    def get(cls, settings) -> "OllamaWatch":
        if cls._inst is None:
            cls._inst = cls(settings)
        return cls._inst

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.up: Optional[bool] = None            # None = jeszcze nie wiadomo
        self.installed = True
        self.have: Optional[set[str]] = None
        self.busy = ""                            # "" / "start" / "pull"
        self.busy_text = ""
        self.busy_frac = -1.0
        self.error = ""
        self.pulling: list[str] = []
        self._checking = False
        self._last = 0.0
        self._hosts: list = []                    # weakref do banerów
        self._result.connect(self._on_result)
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # -- banery
    def register(self, banner) -> None:
        self._hosts.append(weakref.ref(banner))

    def _any_visible(self) -> bool:
        alive = [r for r in self._hosts if r() is not None]
        self._hosts = alive
        return any(r().host_visible() for r in alive)

    def _tick(self):
        if self._any_visible():
            self.check()

    def check(self, force: bool = False) -> None:
        """Tanie sprawdzenie w tle: proces/serwer + lista modeli. Bez force – nie częściej niż co 3 s."""
        if self._checking or self.busy == "start" or (not force and time.monotonic() - self._last < 3):
            return
        self._checking = True
        url = self.settings.ollama_url

        def work():
            from .. import ollama_local
            res = {"up": False, "installed": True, "have": None}
            try:
                res["up"] = ollama_local.quick_is_up(url, timeout=2)
                if res["up"]:
                    res["have"] = hc.ollama_tags(url, timeout=3)
                else:
                    res["installed"] = ollama_local.find_ollama() is not None
            except Exception:  # noqa: BLE001
                log.exception("Sprawdzenie Ollamy")
            self._result.emit(res)
        threading.Thread(target=work, name="OllamaWatch", daemon=True).start()

    def _on_result(self, res: dict):
        self._checking = False
        self._last = time.monotonic()
        changed = (res["up"], res["installed"], res["have"]) != (self.up, self.installed, self.have)
        self.up, self.installed = res["up"], res["installed"]
        if res["have"] is not None or not res["up"]:
            self.have = res["have"]
        if self.up and self.error and self.busy == "":
            self.error = ""
            changed = True
        if changed:
            self.changed.emit()

    def missing(self, models: list[str]) -> list[str]:
        if not self.up or self.have is None:
            return []
        return hc.missing_models(self.have, models)

    # -- naprawy
    def start_ollama(self, on_done: Optional[Callable[[bool], None]] = None) -> None:
        if self.busy:
            return
        self.busy, self.busy_text, self.busy_frac, self.error = "start", tr("Uruchamiam Ollamę…"), -1.0, ""
        self.changed.emit()
        url = self.settings.ollama_url
        self._on_done = on_done

        def work():
            from .. import ollama_local
            ok = False
            try:
                ok = ollama_local.start(url, wait=25)
            except Exception:  # noqa: BLE001
                log.exception("Uruchamianie Ollamy")
            self._finished.emit("start", "" if ok else tr("Nie udało się uruchomić Ollamy."))
        threading.Thread(target=work, name="OllamaStart", daemon=True).start()

    def pull(self, models: list[str], on_done: Optional[Callable[[bool], None]] = None) -> None:
        if self.busy or not models:
            return
        self.busy, self.busy_frac, self.error, self.pulling = "pull", 0.0, "", list(models)
        self.busy_text = tr("Pobieram model {name}…", name=hc._short(models[0]))
        self.changed.emit()
        url = self.settings.ollama_url
        self._on_done = on_done

        def work():
            from ..llm import Ollama
            llm = Ollama(url)
            err = ""
            for m in models:
                name = hc._short(m)
                try:
                    llm.pull(m, progress=lambda _st, f, name=name: self._progress.emit(
                        tr("Pobieram model {name}", name=name) + (f" · {round(100 * f)}%" if f >= 0 else "…"), f))
                except Exception as e:  # noqa: BLE001
                    log.warning("Pobieranie %s: %s", m, e)
                    err = tr("Nie udało się pobrać modelu {name}. Sprawdź internet i spróbuj ponownie.", name=name)
                    break
            self._finished.emit("pull", err)
        threading.Thread(target=work, name="OllamaPull", daemon=True).start()

    def _on_progress(self, text: str, frac: float):
        self.busy_text, self.busy_frac = text, frac
        self.changed.emit()

    def _on_finished(self, kind: str, err: str):
        self.busy, self.busy_text, self.busy_frac, self.error, self.pulling = "", "", -1.0, err, []
        cb, self._on_done = getattr(self, "_on_done", None), None
        self.changed.emit()
        self.check(force=True)
        if cb is not None:
            cb(not err)


def open_ollama_download():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(hc.OLLAMA_DOWNLOAD_URL))


# ---------------------------------------------------------------------------------------------- baner
class OllamaBanner(QFrame):
    """Baner „Ollama nie działa” / „Brakuje modelu X” – sam się pokazuje i znika. compact – mniejszy (panel pytań).
    models() → [(model, rola)] potrzebne w tym miejscu (healthcheck.needed_models)."""

    def __init__(self, settings, models: Callable[[], list[tuple[str, str]]], compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("healthBanner")
        self.settings = settings
        self.models = models
        self.compact = compact
        self.watch = OllamaWatch.get(settings)
        self.watch.register(self)
        self.watch.changed.connect(self._render)
        self._host: Optional[QWidget] = None

        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.title = label("", "warnTitle", wrap=True)
        self.sub = label("", "footnote", wrap=True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.btn = QPushButton("")
        self.btn.setObjectName("primary")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._act)
        self._action = ""

        texts = QVBoxLayout()
        texts.setSpacing(2 if compact else 4)
        texts.addWidget(self.title)
        texts.addWidget(self.sub)
        texts.addWidget(self.bar)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*((12, 8, 10, 8) if compact else (16, 12, 14, 12)))
        lay.setSpacing(10 if compact else 14)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(texts, 1)
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignVCenter)
        show_if(self, False)
        from .theme import theme
        theme().changed.connect(self._render)
        QTimer.singleShot(0, self._attach)

    # -- widoczność strony, na której jest baner (sam baner bywa ukryty)
    def _attach(self):
        self._host = self.parentWidget()
        if self._host is not None:
            self._host.installEventFilter(self)
            if self._host.isVisible():
                self.watch.check()

    def eventFilter(self, obj, ev):
        if obj is self._host and ev.type() == QEvent.Type.Show:
            QTimer.singleShot(200, self.watch.check)
        return False

    def host_visible(self) -> bool:
        h = self._host
        try:
            return h is not None and h.isVisible()
        except RuntimeError:          # widżet już usunięty
            return False

    def refresh(self):
        self._render()

    # --
    def _render(self):
        from .theme import icon_pixmap
        w = self.watch
        t = T()
        self.icon.setPixmap(icon_pixmap("warning", t.wazBar, 20))
        models = [m for m, _r in self.models()]
        if not models:
            show_if(self, False)
            return
        roles = dict(self.models())
        action, title, sub, btn = "", "", "", ""
        if w.busy == "start":
            title, sub = tr("Uruchamiam Ollamę…"), tr("To potrwa kilka sekund.")
        elif w.up is False:
            if not w.installed:
                action, btn = "install", tr("Pobierz Ollamę")
                title = tr("Ollama nie jest zainstalowana – notatki i odpowiedzi na pytania nie powstaną")
                sub = tr("Pobierz ją ze strony ollama.com, zainstaluj i uruchom.")
            else:
                action, btn = "start", tr("Uruchom Ollamę")
                title = (tr("Ollama nie działa – odpowiedzi na pytania nie powstaną") if self.compact else
                         tr("Ollama nie działa – notatki i odpowiedzi na pytania nie powstaną"))
                sub = w.error or (tr("Kliknij „Uruchom Ollamę” albo otwórz ją z {where}.",
                                     where=tr("folderu Aplikacje") if hc.IS_MAC else tr("menu Start")))
                if not self.compact and not w.error:
                    sub += " " + tr("Nagrywać możesz i bez niej – notatki zrobią się później.")
        else:
            miss = w.missing(models)
            if w.busy == "pull" or miss:
                action, btn = "pull", tr("Pobierz")
                names = ", ".join(hc._short(m) for m in (miss or w.pulling))
                title = (tn(len(miss or w.pulling), "Brakuje modelu {names}", "Brakuje modeli: {names}",
                            "Brakuje modeli: {names}", names=names))
                if w.busy == "pull":
                    sub = w.busy_text
                elif w.error:
                    sub = w.error
                else:
                    why = hc.model_problem(miss[0], roles.get(miss[0], "notes")).desc if len(miss) == 1 else \
                        tr("Bez nich część notatek nie powstanie.")
                    gb = sum(hc.model_gb(m) for m in miss)
                    sub = why + " " + tr("Do pobrania ok. {gb} GB.", gb=hc.i18n_gb(gb))
        if not title:
            show_if(self, False)
            return
        self._action = action
        self.title.setText(title)
        self.sub.setText(sub)
        show_if(self.sub, bool(sub) and not (self.compact and w.busy == "" and not w.error and action == "start"))
        busy = bool(w.busy)
        show_if(self.bar, busy)
        if busy:
            if w.busy_frac >= 0:
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(1000 * w.busy_frac))
            else:
                self.bar.setRange(0, 0)           # bez znanego postępu – pasek „w ruchu”
        self.btn.setText(btn)
        show_if(self.btn, bool(btn) and not busy)        # w trakcie – zamiast przycisku pasek postępu
        show_if(self, True)

    def _act(self):
        if self._action == "start":
            self.watch.start_ollama()
        elif self._action == "install":
            open_ollama_download()
        elif self._action == "pull":
            self.watch.pull(self.watch.missing([m for m, _r in self.models()]))


# ---------------------------------------------------------------------------------------------- karta problemu
class ProblemCard(QFrame):
    """Karta na ekranie nagrywania: co nie działa, dlaczego, jak naprawić. Sygnały: action(id, klucz problemu),
    proceed („Nagrywaj mimo to”), cancel („Anuluj”)."""
    action = Signal(str, str)
    proceed = Signal()
    cancel = Signal()
    shown = Signal(bool)              # karta się pokazała / schowała

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("problemCard")
        self.problems: list[hc.Problem] = []
        self.failed = False
        self.running = False
        self.waiting = False          # zaplanowane nagrywanie – do startu jest jeszcze czas na naprawę
        self._items: dict[str, dict] = {}

        self.icon = QLabel()
        self.icon.setFixedSize(26, 26)
        self.title = label("", "title3", wrap=True)
        self.lead = label("", "secondary", wrap=True)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        hv = QVBoxLayout()
        hv.setSpacing(4)
        hv.addWidget(self.title)
        hv.addWidget(self.lead)
        head.addLayout(hv, 1)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.note = label("", "footnote", wrap=True)
        self.btn_cancel = QPushButton(tr("Anuluj"))
        self.btn_cancel.setObjectName("plain")
        self.btn_cancel.clicked.connect(self.cancel.emit)
        self.btn_go = QPushButton(tr("Nagrywaj mimo to"))
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self.proceed.emit)
        for b in (self.btn_cancel, self.btn_go):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(self.note, 1)
        foot.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignBottom)
        foot.addWidget(self.btn_go, 0, Qt.AlignmentFlag.AlignBottom)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 18, 16)
        v.setSpacing(12)
        v.addLayout(head)
        v.addLayout(self.list)
        v.addLayout(foot)
        from .theme import theme
        theme().changed.connect(self._render)
        show_if(self, False)

    # --
    def set_problems(self, problems: list[hc.Problem], failed: bool = False, running: bool = False,
                     waiting: bool = False):
        """failed – nagrywanie się nie rozpoczęło (nie ma „Nagrywaj mimo to”); running – dźwięk już się nagrywa;
        waiting – nagrywanie jest zaplanowane i jeszcze nie ruszyło (karta przypomina, że jest czas na naprawę)."""
        self.problems, self.failed, self.running, self.waiting = list(problems), failed, running, waiting
        self._render()

    def set_running(self, on: bool):
        self.running = on
        self._render_texts()

    def remove(self, key: str) -> bool:
        """Usuń naprawiony problem; True, gdy nic już nie zostało."""
        self.problems = [p for p in self.problems if p.key != key]
        self._render()
        return not self.problems

    def set_busy(self, key: str, text: str, frac: float = -1.0, busy: bool = True):
        it = self._items.get(key)
        if it is None:
            return
        it["status"].setText(text)
        show_if(it["status"], bool(text))
        show_if(it["bar"], busy)
        if busy:
            if frac >= 0:
                it["bar"].setRange(0, 1000)
                it["bar"].setValue(int(1000 * frac))
            else:
                it["bar"].setRange(0, 0)
        if it["btn"] is not None:
            it["btn"].setEnabled(not busy)

    def _clear(self):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w is not None:          # schowaj od razu – inaczej do usunięcia widać go w starym miejscu
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._items = {}

    def _render(self):
        from .theme import icon_pixmap
        t = T()
        self._clear()
        crit = self.failed or any(p.critical for p in self.problems)
        self.setProperty("crit", "true" if crit else "false")
        repolish(self)
        self.icon.setPixmap(icon_pixmap("warning", t.red if crit else t.wazBar, 26))
        single = len(self.problems) == 1
        for p in self.problems:
            box = QFrame()
            box.setObjectName("problemItem")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(14, 10, 12, 10)
            bl.setSpacing(4)
            if not single:
                bl.addWidget(label(p.title, "errTitle" if p.critical else "warnTitle", wrap=True))
            if p.desc:
                bl.addWidget(label(p.desc, "", wrap=True))
            if p.steps:
                steps = label("<br>".join(f"<b>{i}.</b>&nbsp;{s}" for i, s in enumerate(p.steps, 1)), "secondary",
                              wrap=True)
                steps.setTextFormat(Qt.TextFormat.RichText)
                bl.addWidget(steps)
            status = label("", "footnote", wrap=True)
            status.hide()
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.hide()
            btn = None
            row = QHBoxLayout()
            row.setSpacing(10)
            if p.action:
                btn = QPushButton(p.action_label)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                set_icon(btn, {"start_ollama": "play", "cpu": "check"}.get(p.action.split(":")[0], "chevron-right"),
                         "text", 14)
                btn.clicked.connect(lambda _c=False, a=p.action, k=p.key: self.action.emit(a, k))
                row.addWidget(btn)
            rv = QVBoxLayout()
            rv.setSpacing(4)
            rv.addWidget(status)
            rv.addWidget(bar)
            row.addLayout(rv, 1)
            bl.addSpacing(4)
            bl.addLayout(row)
            self.list.addWidget(box)
            self._items[p.key] = {"status": status, "bar": bar, "btn": btn}
        self._render_texts()
        on = bool(self.problems)
        if on != (not self.isHidden()):
            show_if(self, on)
            self.shown.emit(on)

    def _render_texts(self):
        ps = self.problems
        if not ps:
            return
        ai = hc.ai_only(ps)
        if len(ps) == 1:
            self.title.setText(ps[0].title)
        elif self.failed:
            self.title.setText(tr("Nie udało się rozpocząć nagrywania"))
        else:
            self.title.setText(tn(len(ps), "Przed nagrywaniem: {n} problem", "Przed nagrywaniem: {n} problemy",
                                  "Przed nagrywaniem: {n} problemów"))
        if self.failed:
            lead = tr("Nagrywanie się nie rozpoczęło. Napraw problem i spróbuj jeszcze raz.")
        elif self.waiting:
            lead = tr("Do startu jest jeszcze czas – napraw to teraz, żeby nagrywanie ruszyło bez kłopotów. "
                      "Zaplanowany start i tak nastąpi o czasie.")
        elif ai:
            lead = tr("Nagranie wykładu jest najważniejsze – „Nagrywaj mimo to” nagra dźwięk i slajdy, a transkrypcja "
                      "i notatki zrobią się później, gdy AI zadziała.")
        else:
            lead = tr("Bez naprawy nagranie może być niepełne. Napraw problem albo nagrywaj mimo to.")
        self.lead.setText(lead)
        self.note.setText(tr("Dźwięk już się nagrywa w tle – nic nie tracisz, gdy czytasz ten komunikat.")
                          if self.running and not self.failed else "")
        # pusty podpis zostaje w układzie – trzyma przyciski po prawej
        show_if(self.btn_go, not self.failed)
        self.btn_go.setText(tr("Czekaj mimo to") if self.waiting else tr("Nagrywaj mimo to"))
        self.btn_cancel.setText(tr("Wróć") if self.failed else
                                tr("Anuluj nagrywanie") if self.waiting else tr("Anuluj"))
        self.btn_cancel.setToolTip("" if self.failed else
                                   tr("Anuluj zaplanowane nagrywanie – nic nie zostanie nagrane") if self.waiting else
                                   tr("Przerwij – nic nie zostanie zapisane"))
