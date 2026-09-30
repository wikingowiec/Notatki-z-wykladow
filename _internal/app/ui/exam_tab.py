"""Ekran „Egzamin próbny”: tworzenie egzaminu z notatek (przedmiot albo wykład) i rozwiązywanie go."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import exam as EX
from ..mathrender import text_to_html
from ..storage import list_lectures
from .controls import GroupSection, SegmentedControl, ToggleSwitch, hbox, label, set_icon
from .reader import Reader
from .record_tab import _centered
from .theme import T
from .widgets import JobRunner, run_async

LEVELS = [("easy", "Łatwy"), ("medium", "Średni"), ("hard", "Trudny")]


class ExamTab(QWidget):
    open_lecture = Signal(str, str)

    def __init__(self, settings, runner: JobRunner):
        super().__init__()
        self.setObjectName("page")
        self.settings = settings
        self.runner = runner
        self.exam: dict | None = None
        self.order: list[int] = []
        self.pos = 0
        self.answers: dict[int, dict] = {}

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_take())
        self.stack.addWidget(self._build_result())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        runner.progress.connect(self._job_progress)
        runner.finished.connect(self._job_finished)

    # ================================================================== tworzenie
    def _build_setup(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(22)
        from .controls import Heading
        v.addWidget(Heading("Egzamin próbny", "Test z Twoich notatek – z jednego wykładu albo całego przedmiotu. Każde "
                                              "pytanie opiera się na konkretnym fragmencie notatki, więc od razu "
                                              "zobaczysz, skąd jest odpowiedź.", "Nauka"))

        from .controls import ChoiceCombo
        self.scope = ChoiceCombo()
        self.scope.setMinimumWidth(300)
        self.n = QSpinBox()
        self.n.setRange(3, 50)
        self.n.setValue(15)
        g = GroupSection("Zakres")
        g.add_row("Z czego", self.scope)
        g.add_row("Liczba pytań", self.n)
        v.addWidget(g)

        self.t_abcd = ToggleSwitch(True)
        self.t_pf = ToggleSwitch(True)
        self.t_open = ToggleSwitch(True)
        self.level = SegmentedControl([t for _k, t in LEVELS])
        self.level.set_current(1)
        g = GroupSection("Pytania", "Pytania otwarte sprawdza AI, porównując Twoją odpowiedź z notatką.")
        g.add_row("Jednokrotnego wyboru (A–D)", self.t_abcd)
        g.add_row("Prawda / fałsz", self.t_pf)
        g.add_row("Otwarte", self.t_open)
        g.add_row("Poziom", self.level)
        v.addWidget(g)

        self.instr = QPlainTextEdit()
        self.instr.setPlaceholderText("Np. „egzamin obejmuje wykłady 3–6”, „dużo pytań o definicje”, "
                                      "„prowadzący mówił, że będzie zadanie z twierdzenia Lagrange’a”…")
        self.instr.setFixedHeight(90)
        self.use_info = ToggleSwitch(True)
        g = GroupSection("Twoje wskazówki")
        g.add(self._pad(self.instr))
        g.add_row("Uwzględnij informacje o egzaminie z wykładów", self.use_info,
                  "Wzmianki prowadzącego typu „to będzie na egzaminie” i fragmenty zaznaczone jako „Na egzamin”.")
        v.addWidget(g)

        self.btn_make = QPushButton("Utwórz egzamin")
        self.btn_make.setObjectName("big")
        set_icon(self.btn_make, "exam", "on_accent", 17)
        self.btn_make.clicked.connect(self.create)
        self.make_bar = QProgressBar()
        self.make_bar.setTextVisible(False)
        self.make_bar.hide()
        self.make_status = label("", "footnote", wrap=True)
        v.addWidget(hbox(self.btn_make, "stretch"))
        v.addWidget(self.make_bar)
        v.addWidget(self.make_status)

        self.history = GroupSection("Poprzednie egzaminy")
        v.addWidget(self.history)
        v.addStretch()
        return _centered(col, 760)

    @staticmethod
    def _pad(w):
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(12, 10, 12, 10)
        l.addWidget(w)
        return box

    def refresh(self):
        cur = self.scope.currentData()
        lectures = [l for l in list_lectures(self.settings.library_path()) if l.notes_path.exists()]
        self.scope.fill_scope(lectures, "", subject_prefix="Cały przedmiot: ", keep=cur)
        i = self.scope.findData(cur) if cur else -1
        if i < 0 and self.settings.last_subject:
            i = self.scope.findData(("subject", self.settings.last_subject))
        self.scope.setCurrentIndex(max(0, i))
        self.btn_make.setEnabled(self.scope.count() > 0 and not self.runner.busy)
        if not self.scope.count():
            self.make_status.setText("Najpierw potrzebne są wykłady z gotowymi notatkami.")
        self._fill_history()

    def _fill_history(self):
        lay = self.history.inner
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.history._count = 0
        exams = EX.list_exams(self.settings.library_path())
        self.history.setVisible(bool(exams))
        for ex in exams[:12]:
            res = ex.get("results", [])
            best = max((r["score"] for r in res), default=None)
            sub = f"{ex.get('created', '')} · {len(ex['questions'])} pytań" + (f" · najlepszy wynik {best}%" if best is not None else "")
            b_take = QPushButton("Rozwiąż")
            b_take.clicked.connect(lambda _=False, e=ex: self.start(e))
            b_del = QPushButton("Usuń")
            b_del.setObjectName("plain")
            b_del.clicked.connect(lambda _=False, e=ex: self._delete(e))
            self.history.add_row(ex.get("title", "Egzamin"), hbox(b_del, b_take, spacing=6), sub)

    def _delete(self, ex):
        EX.delete_exam(self.settings.library_path(), ex["id"])
        self._fill_history()

    def create(self):
        data = self.scope.currentData()
        if not data:
            return
        types = [k for k, t in (("abcd", self.t_abcd), ("pf", self.t_pf), ("open", self.t_open)) if t.isChecked()]
        if not types:
            QMessageBox.information(self, "Egzamin", "Wybierz przynajmniej jeden rodzaj pytań.")
            return
        spec = EX.ExamSpec(scope=data[0], value=data[1], n=self.n.value(), types=types,
                           level=LEVELS[self.level.current()][0], instructions=self.instr.toPlainText(),
                           use_exam_info=self.use_info.isChecked())
        s = self.settings
        lib = s.library_path()

        def fn(prog, cancel, tok):
            from ..llm import LLMError, Ollama
            llm = Ollama(s.ollama_url)
            if not llm.is_running():
                raise LLMError("Ollama nie działa – uruchom ją i spróbuj ponownie.")
            exam = EX.generate_exam(lib, spec, llm, s.ollama_model, s.ollama_ctx, prog, cancel)
            EX.save_exam(lib, exam)
            self._created = exam
        self._created = None
        if not self.runner.run("Egzamin próbny", fn, None):
            QMessageBox.information(self, "Trwa inne zadanie", f"Trwa: {self.runner.name}. Poczekaj, aż się skończy.")
            return
        self.btn_make.setEnabled(False)
        self.make_bar.show()
        self.make_bar.setRange(0, 0)
        self.make_status.setText("Układam pytania i sprawdzam każde w notatkach…")

    def _job_progress(self, msg, frac):
        if self.runner.name != "Egzamin próbny":
            return
        self.make_status.setText(msg)
        if frac >= 0:
            self.make_bar.setRange(0, 1000)
            self.make_bar.setValue(int(frac * 1000))

    def _job_finished(self, ok, msg, _lec):
        if not self.make_bar.isVisible():
            return
        self.make_bar.hide()
        self.btn_make.setEnabled(True)
        if ok and getattr(self, "_created", None):
            self.make_status.setText("")
            self._fill_history()
            self.start(self._created)
        else:
            self.make_status.setText(msg)

    # ================================================================== rozwiązywanie
    def _build_take(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(36, 30, 36, 24)
        self._outers = [outer]
        col = QWidget()
        col.setMaximumWidth(900)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.take_title = label("", "title2")
        self.take_sub = label("", "secondary")
        tv.addWidget(self.take_title)
        tv.addWidget(self.take_sub)
        head.addLayout(tv, 1)
        b_quit = QPushButton("Zakończ")
        b_quit.clicked.connect(self.finish)
        head.addWidget(b_quit, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        self.take_bar = QProgressBar()
        self.take_bar.setTextVisible(False)
        v.addWidget(self.take_bar)

        from .controls import Sheet
        card = Sheet(radius=20)
        cl = card.lay
        cl.setContentsMargins(44, 32, 44, 36)
        cl.setSpacing(14)
        self.take_card = card
        self.q_kind = label("", "footnote")
        self.q_text = label("", "cardQ", wrap=True)
        self.q_text.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.q_kind)
        cl.addWidget(self.q_text)
        self.opts_box = QWidget()
        self.opts_lay = QVBoxLayout(self.opts_box)
        self.opts_lay.setContentsMargins(0, 6, 0, 0)
        self.opts_lay.setSpacing(8)
        cl.addWidget(self.opts_box)
        self.open_edit = QPlainTextEdit()
        self.open_edit.setPlaceholderText("Twoja odpowiedź…")
        self.open_edit.setFixedHeight(110)
        self.btn_check = QPushButton("Sprawdź odpowiedź")
        self.btn_check.setObjectName("primary")
        self.btn_check.clicked.connect(self._check_open)
        self.open_box = QWidget()
        ol = QVBoxLayout(self.open_box)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(self.open_edit)
        ol.addWidget(self.btn_check, 0, Qt.AlignmentFlag.AlignLeft)
        cl.addWidget(self.open_box)
        self.feedback = label("", "headline", wrap=True)
        self.feedback.setTextFormat(Qt.TextFormat.RichText)
        self.explain = label("", "secondary", wrap=True)
        self.explain.setTextFormat(Qt.TextFormat.RichText)
        self.btn_source = QPushButton("Zobacz w notatce")
        self.btn_source.setObjectName("plain")
        self.btn_source.clicked.connect(self._open_source)
        cl.addWidget(self.feedback)
        cl.addWidget(self.explain)
        cl.addWidget(self.btn_source, 0, Qt.AlignmentFlag.AlignLeft)
        cl.addStretch()
        v.addWidget(card)
        self.btn_next = QPushButton("Dalej")
        self.btn_next.setObjectName("big")
        self.btn_next.setMinimumWidth(220)
        self.btn_next.clicked.connect(self.next)
        v.addWidget(self.btn_next, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        return w

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < 700
        for o in getattr(self, "_outers", []):
            o.setContentsMargins(*((14, 16, 14, 14) if narrow else (36, 30, 36, 24)))
        if hasattr(self, "take_card"):
            self.take_card.lay.setContentsMargins(*((24, 20, 24, 24) if narrow else (44, 32, 44, 36)))

    def start(self, exam: dict, only: list[int] | None = None):
        self.exam = exam
        self.order = only if only is not None else list(range(len(exam["questions"])))
        self.pos = 0
        self.answers = {}
        self.take_title.setText(exam.get("title", "Egzamin"))
        self.stack.setCurrentIndex(1)
        self._show()

    def _show(self):
        q = self.exam["questions"][self.order[self.pos]]
        t = T()
        n = len(self.order)
        self.take_sub.setText(f"Pytanie {self.pos + 1} z {n}")
        self.take_bar.setRange(0, n)
        self.take_bar.setValue(self.pos)
        self.q_kind.setText({"abcd": "Jednokrotny wybór", "pf": "Prawda czy fałsz?", "open": "Pytanie otwarte"}[q["type"]])
        mdir = self._mdir(q)
        self.q_text.setText(text_to_html(q["q"], mdir, t.text))
        while self.opts_lay.count():
            it = self.opts_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.opt_buttons = []
        self.open_box.setVisible(q["type"] == "open")
        self.opts_box.setVisible(q["type"] != "open")
        if q["type"] == "abcd":
            for i, o in enumerate(q["options"]):
                self._add_option(f"{'ABCD'[i]}.  {o}", i)
        elif q["type"] == "pf":
            self._add_option("Prawda", True)
            self._add_option("Fałsz", False)
        else:
            self.open_edit.clear()
            self.open_edit.setEnabled(True)
            self.btn_check.setEnabled(True)
        self.feedback.setText("")
        self.explain.setText("")
        self.btn_source.hide()
        self.btn_next.setEnabled(False)
        self.btn_next.setText("Dalej" if self.pos + 1 < n else "Zobacz wynik")

    def _mdir(self, q):
        from pathlib import Path
        return Path(q.get("source", {}).get("folder", str(self.settings.library_path()))) / "math"

    def _add_option(self, text: str, value):
        b = QPushButton(text)
        b.setObjectName("option")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _=False, v=value, btn=b: self._choose(v, btn))
        self.opts_lay.addWidget(b)
        self.opt_buttons.append((b, value))

    def _choose(self, value, btn):
        qi = self.order[self.pos]
        if qi in self.answers:
            return
        q = self.exam["questions"][qi]
        ok = value == q["correct"]
        self.answers[qi] = {"points": 2 if ok else 0, "given": value}
        for b, v in self.opt_buttons:
            state = "correct" if v == q["correct"] else ("wrong" if b is btn else "")
            b.setProperty("state", state)
            b.style().unpolish(b)
            b.style().polish(b)
        t = T()
        self.feedback.setText(f"<span style='color:{t.green}'>✓ Dobrze</span>" if ok else
                              f"<span style='color:{t.red}'>✗ Źle</span>")
        self._after_answer(q)

    def _check_open(self):
        qi = self.order[self.pos]
        q = self.exam["questions"][qi]
        ans = self.open_edit.toPlainText()
        self.btn_check.setEnabled(False)
        self.open_edit.setEnabled(False)
        self.feedback.setText("Sprawdzam…")
        s = self.settings

        def work():
            from ..llm import Ollama
            return EX.grade_open(q, ans, Ollama(s.ollama_url), s.ollama_model, min(8192, s.ollama_ctx))

        def done(res):
            pts, comment = res
            self.answers[qi] = {"points": pts, "given": ans, "comment": comment}
            t = T()
            color, name = {2: (t.green, "✓ Dobrze"), 1: (t.orange, "◐ Częściowo"), 0: (t.red, "✗ Źle")}[pts]
            self.feedback.setText(f"<span style='color:{color}'>{name}</span>&nbsp;&nbsp;"
                                  f"<span style='font-weight:400'>{html.escape(comment)}</span>")
            self._after_answer(q, show_ref=True)

        def fail(e):
            self.feedback.setText(f"Nie udało się sprawdzić: {e}")
            self.btn_check.setEnabled(True)
            self.open_edit.setEnabled(True)
        run_async(work, done, fail)

    def _after_answer(self, q, show_ref: bool = False):
        t = T()
        mdir = self._mdir(q)
        parts = []
        if show_ref and q.get("answer"):
            parts.append(f"<b>Wzorcowa odpowiedź:</b> {text_to_html(q['answer'], mdir, t.text2)}")
        if q.get("explain"):
            parts.append(text_to_html(q["explain"], mdir, t.text2))
        if q.get("quote"):
            parts.append(f"<i>„{html.escape(q['quote'])}”</i>")
        self.explain.setText("<br><br>".join(parts))
        src = q.get("source", {})
        self.btn_source.setText(f"Zobacz w notatce: {src.get('title', '')}")
        self.btn_source.setVisible(bool(src))
        self.btn_next.setEnabled(True)
        self.btn_next.setFocus()

    def _open_source(self):
        q = self.exam["questions"][self.order[self.pos]]
        src = q.get("source", {})
        if src:
            self.open_lecture.emit(src.get("folder", ""), src.get("anchor", ""))

    def next(self):
        if self.pos + 1 < len(self.order):
            self.pos += 1
            self._show()
        else:
            self.finish()

    # ================================================================== wynik
    def _build_result(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(36, 30, 36, 24)
        self._outers.append(outer)
        col = QWidget()
        col.setMaximumWidth(900)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.res_title = label("", "largeTitle")
        self.res_sub = label("", "secondary", wrap=True)
        v.addWidget(self.res_title)
        v.addWidget(self.res_sub)
        self.res_view = Reader(max_width=820, pad=28)
        self.res_view.internal_link.connect(self._res_link)
        v.addWidget(self.res_view, 1)
        self.btn_retry = QPushButton("Powtórz błędne")
        self.btn_retry.setObjectName("primary")
        self.btn_retry.clicked.connect(self._retry_wrong)
        b_again = QPushButton("Rozwiąż jeszcze raz")
        b_again.clicked.connect(lambda: self.start(self.exam))
        b_new = QPushButton("Nowy egzamin")
        b_new.clicked.connect(lambda: (self.refresh(), self.stack.setCurrentIndex(0)))
        v.addWidget(hbox(self.btn_retry, b_again, b_new, "stretch"))
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        return w

    def finish(self):
        if not self.exam:
            return
        qs = self.exam["questions"]
        answered = [i for i in self.order if i in self.answers]
        total = 2 * len(self.order)
        got = sum(self.answers[i]["points"] for i in answered)
        score = round(100 * got / total) if total else 0
        if answered:
            self.exam.setdefault("results", []).append({"date": EX.time.strftime("%Y-%m-%d %H:%M"), "score": score,
                                                         "answered": len(answered), "of": len(self.order)})
            EX.save_exam(self.settings.library_path(), self.exam)
        self.wrong = [i for i in self.order if self.answers.get(i, {}).get("points", 0) < 2]
        t = T()
        self.res_title.setText(f"Wynik: {score}%")
        self.res_sub.setText(f"Odpowiedziałeś na {len(answered)} z {len(self.order)} pytań. "
                             + ("Świetnie – wszystko dobrze!" if not self.wrong else
                                f"Do powtórki: {len(self.wrong)}. Kliknij temat, żeby otworzyć ten fragment notatki."))
        rows = []
        self._res_src = {}
        for k, i in enumerate(self.wrong):
            q = qs[i]
            src = q.get("source", {})
            self._res_src[f"q{k}"] = src
            a = self.answers.get(i)
            if q["type"] == "abcd":
                correct = q["options"][q["correct"]]
            elif q["type"] == "pf":
                correct = "Prawda" if q["correct"] else "Fałsz"
            else:
                correct = q.get("answer", "")
            mdir = self._mdir(q)
            rows.append(f"<p style='margin:14px 0 4px 0'><b>{text_to_html(q['q'], mdir, t.text)}</b></p>"
                        f"<p style='margin:0 0 4px 0; color:{t.text2}'>"
                        f"{'Brak odpowiedzi' if not a else ''}Poprawnie: {text_to_html(correct, mdir, t.text2)}</p>"
                        f"<p style='margin:0'><a style='color:{t.accent}; text-decoration:none' href='#q{k}'>"
                        f"→ {html.escape(src.get('title', ''))}</a></p>")
        self.res_view.setHtml(f"<body style='color:{t.text}; line-height:145%'>{''.join(rows)}</body>")
        self.btn_retry.setEnabled(bool(self.wrong))
        self.stack.setCurrentIndex(2)

    def _res_link(self, anchor: str):
        src = getattr(self, "_res_src", {}).get(anchor)
        if src:
            self.open_lecture.emit(src.get("folder", ""), src.get("anchor", ""))

    def _retry_wrong(self):
        if self.wrong:
            self.start(self.exam, list(self.wrong))
