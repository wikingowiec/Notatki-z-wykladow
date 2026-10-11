"""Panel „Zapytaj”: pytania do notatki (w bibliotece i w trakcie wykładu)."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .. import qa
from .controls import EmptyState, label, set_icon
from .reader import Reader
from . import theme as _th
from .theme import T
from .widgets import run_async
from ..i18n import tr

HINT = (tr("Odpowiedzi pochodzą wyłącznie z notatki. Jeśli czegoś w niej nie ma, zobaczysz to wprost – AI nie zgaduje. "
        "Każda odpowiedź ma cytat i odnośnik do fragmentu notatki."))
HINT_LIVE = (tr("W trakcie wykładu AI szuka odpowiedzi w gotowych fragmentach notatek i w transkrypcji ostatnich minut. "
             "Jeśli czegoś jeszcze nie było, zobaczysz to wprost – AI nie zgaduje."))


class AskPanel(QStackedWidget):
    internal_link = Signal(str)
    seek_requested = Signal(float)
    answered = Signal()

    def __init__(self, settings, live: bool = False, busy_hint: Optional[Callable[[], bool]] = None):
        super().__init__()
        self.settings = settings
        self.live = live
        self.busy_hint = busy_hint or (lambda: False)
        self.get_md: Optional[Callable[[], str]] = None
        self.history_path: Optional[Path] = None
        self.num_ctx = 0
        self.lang: Callable[[], str] | str = ""     # język notatek – w nim odpowiada model
        self.anchor_times: dict = {}      # kotwica tematu → sekunda nagrania (link „▶ 44:58”)
        self.compact = False
        self._asking = False
        self._token = 0

        self.view = Reader(max_width=760, pad=28)
        self.view.internal_link.connect(self.internal_link.emit)
        self.view.seek_requested.connect(self.seek_requested.emit)
        self.input = QLineEdit()
        self.input.setObjectName("askInput")
        self.input.setPlaceholderText(tr("Zadaj pytanie, np. „Jak brzmi twierdzenie o wartości średniej?”"))
        self.input.returnPressed.connect(self.ask)
        self.btn = QPushButton(tr("Zapytaj"))
        self.btn.setObjectName("primary")
        set_icon(self.btn, "search", "on_accent", 15)
        self.btn.clicked.connect(self.ask)
        self.btn_clear = QPushButton(tr("Wyczyść"))
        self.btn_clear.setObjectName("plain")
        self.btn_clear.clicked.connect(self.clear)
        self.hint = label(HINT_LIVE if live else HINT, "footnote", wrap=True)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn)
        row.addWidget(self.btn_clear)
        lay.addLayout(row)
        lay.addWidget(self.hint)
        self.empty = EmptyState("search", tr("Najpierw potrzebne są notatki"),
                                tr("Pytania zadajesz do gotowej notatki. Wygeneruj ją przyciskiem „Generuj notatki”."))
        self.addWidget(w)
        self.addWidget(self.empty)

    # ------------------------------------------------------------------
    def set_source(self, get_md: Optional[Callable[[], str]], history_path: Optional[Path], num_ctx: int,
                   lang: Callable[[], str] | str = ""):
        self._token += 1
        self.get_md, self.history_path, self.num_ctx, self.lang = get_md, history_path, num_ctx, lang
        self._asking = False
        self.btn.setEnabled(True)
        self.input.setEnabled(True)
        self.setCurrentIndex(0 if get_md else 1)
        if get_md:
            self.render(qa.load_history(history_path) if history_path else [])

    def render(self, items: list[dict], pending: str | None = None):
        t = T()
        if not items and not pending:
            intro = (tr("Pytaj w trakcie wykładu – np. gdy coś Ci umknęło. Źródłem są gotowe fragmenty notatek "
                     "i transkrypcja ostatnich minut.") if self.live else
                     tr("Wpisz pytanie z zadania lub ćwiczeń. Odpowiedź powstaje tylko na podstawie tej notatki "
                     "i zawsze pokazuje cytat, na którym się opiera."))
            self.view.setHtml(
                f"<div style='color:{t.text2}; line-height:160%'><p style='font-family:\"{_th.DISPLAY_FAMILY}\"; "
                f"font-size:16pt; font-weight:600; color:{t.text}'>{tr('Zapytaj notatkę')}</p>"
                f"<p>{intro}</p><p>{tr('Przykłady: <i>„Czym jest całka oznaczona?”</i>, <i>„Jakie warunki musi spełniać funkcja…?”</i>')}</p></div>")
            return
        badge = {
            "odpowiedz": (t.green, tr("Odpowiedź z notatki")),
            "czesciowo": (t.orange, tr("Częściowo w notatce")),
            "brak": (t.text2, tr("Brak w notatce")),
            "niepewne": (t.text2, tr("Nie potwierdzono w notatce")),
            "blad": (t.red, tr("Błąd")),
        }
        link = f"style='color:{t.accent}; text-decoration:none'"
        parts = []
        for a in items:
            color, name = badge.get(a.get("status"), (t.text2, a.get("status", "")))
            parts.append(f"<p style='margin:22px 0 6px 0; font-family:\"{_th.DISPLAY_FAMILY}\"; font-size:13pt; "
                         f"font-weight:600'>{html.escape(a['question'])}</p>")
            parts.append(f"<p style='margin:0 0 6px 0'><span style='color:{color}; font-weight:600'>● {name}</span></p>")
            st = a.get("status")
            if st in ("odpowiedz", "czesciowo") and a.get("answer"):
                parts.append(f"<p style='margin:0 0 8px 0'>{html.escape(a['answer'])}</p>")
                for q in a.get("quotes", []):
                    tm = self.anchor_times.get(q["anchor"])
                    play = ""
                    if tm is not None:
                        from ..storage import fmt_time
                        play = f" · <a {link} href='seek:{tm}'>▶ {fmt_time(tm)}</a>"
                    parts.append(f"<p style='margin:0 0 6px 16px; color:{t.text2}'><i>„{html.escape(q['text'])}”</i> "
                                 f"— <a {link} href='#{q['anchor']}'>{html.escape(q['title'])}</a>{play}</p>")
            elif st == "brak":
                parts.append(tr("<p style='margin:0 0 6px 0'>Tej informacji nie ma w notatce, więc nie podaję odpowiedzi.</p>"))
            elif st == "niepewne":
                parts.append(tr("<p style='margin:0 0 6px 0'>Nie udało się potwierdzić odpowiedzi cytatem z notatki – "
                             "najpewniej tej informacji w niej nie ma. Nie podaję odpowiedzi, żeby nie wprowadzić "
                             "Cię w błąd.</p>"))
            elif st == "blad":
                parts.append(f"<p style='color:{t.red}'>{html.escape(a.get('answer', ''))}</p>")
            if a.get("missing") and st != "blad":
                parts.append(f"<p style='margin:0 0 6px 0; color:{t.text2}'>{html.escape(a['missing'])}</p>")
            if st in ("brak", "niepewne") and a.get("related"):
                links = " · ".join(f"<a {link} href='#{r['anchor']}'>{html.escape(r['title'])}</a>" for r in a["related"])
                parts.append(tr("<p style='margin:0 0 6px 0; color:{text2}'>Najbliższe tematy w notatce: {links}</p>", text2=t.text2, links=links))
        if pending:
            parts.append(tr("<p style='margin:22px 0 6px 0; font-family:\"{display_family}\"; font-size:13pt; "
                            "font-weight:600'>{escape}</p><p style='color:{text2}'>Szukam odpowiedzi w notatce…</p>", display_family=_th.DISPLAY_FAMILY, escape=html.escape(pending), text2=t.text2))
        self.view.setHtml(f"<body style='color:{t.text}; line-height:160%'>{''.join(parts)}</body>")
        sb = self.view.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    def history(self) -> list[dict]:
        return qa.load_history(self.history_path) if self.history_path else []

    def ask_text(self, q: str):
        self.input.setText(q)
        self.ask()

    def ask(self):
        q = self.input.text().strip()
        if len(q) < 4 or not self.get_md or self._asking:
            return
        self._asking = True
        self.btn.setEnabled(False)
        self.input.setEnabled(False)
        path, token, get_md, ctx = self.history_path, self._token, self.get_md, self.num_ctx
        lang = self.lang() if callable(self.lang) else self.lang
        history = qa.load_history(path) if path else []
        self.render(history, pending=q)
        s = self.settings
        if self.busy_hint():
            self.hint.setText(tr("Model AI jest teraz zajęty innym zadaniem – odpowiedź pojawi się, gdy będzie wolny."))

        def work():
            from ..llm import Ollama
            llm = Ollama(s.ollama_url)
            if not llm.is_running():
                a = qa.Answer(question=q, status="blad", answer=tr("Ollama nie działa – uruchom ją i spróbuj ponownie."))
            else:
                a = qa.ask(get_md(), q, llm, s.ollama_model, num_ctx=ctx,
                           keep_alive="30m" if self.live else "10m", lang=lang)
            return qa.to_dict(a)

        def done(ans: dict):
            history.append(ans)
            if path:
                try:
                    qa.save_history(path, history)
                except OSError:
                    pass
            self.hint.setText(HINT_LIVE if self.live else HINT)
            if token != self._token:      # w międzyczasie wybrano inny wykład
                return
            self._asking = False
            self.btn.setEnabled(True)
            self.input.setEnabled(True)
            self.input.clear()
            self.render(history)
            self.input.setFocus()
            self.answered.emit()

        def failed(e):
            done(qa.to_dict(qa.Answer(question=q, status="blad", answer=tr("Nie udało się: {e}", e=e))))
        run_async(work, done, failed)

    def clear(self):
        if self.history_path:
            try:
                self.history_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.render([])
