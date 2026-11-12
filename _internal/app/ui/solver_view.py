"""Tryb „Rozwiąż test” w zakładce Egzamin: gotowy test rozwiązany wyłącznie z notatek.

Kroki: 1) wklejka / plik + zakres + zgadywanie, 2) podgląd rozpoznanych pytań (popraw / usuń / scal),
3) rozwiązywanie w tle z postępem i wynikami na bieżąco, 4) wynik: zwięzła lista do skopiowania + szczegóły."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import exam as EX
from .. import solver as S
from ..storage import list_lectures
from .controls import (ChoiceCombo, GroupSection, Heading, SegmentedControl, Sheet, ToggleSwitch, hbox, label,
                       set_icon, show_if, style_combo)
from .reader import Reader
from .record_tab import _centered
from .theme import T
from .widgets import JobRunner
from ..i18n import tn, tr

KIND_NAMES = {"abcd": lambda: tr("Jednokrotny wybór"), "multi": lambda: tr("Wielokrotny wybór"),
              "pf": lambda: tr("Prawda / fałsz"), "open": lambda: tr("Pytanie otwarte")}
FILTERS = ["all", "notes", "guess", "unknown"]


def _pad(w, m=(12, 10, 12, 10)):
    box = QWidget()
    l = QVBoxLayout(box)
    l.setContentsMargins(*m)
    l.addWidget(w)
    return box


def _clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().hide()            # od razu – usunięcie (deleteLater) przyjdzie później
            it.widget().deleteLater()


class SolverView(QWidget):
    open_lecture = Signal(str, str)
    partial = Signal(object)              # {indeks pytania: wynik} – z wątku zadania, na bieżąco

    def __init__(self, settings, runner: JobRunner):
        super().__init__()
        self.setObjectName("page")
        self.settings = settings
        self.runner = runner
        self.is_recording = lambda: False      # podmieniane przez ExamTab / MainWindow
        self.questions: list[dict] = []        # podgląd (przed rozwiązaniem)
        self.source_name = ""
        self.used_ai = False
        self.test: dict | None = None
        self._job = ""                          # nazwa NASZEGO zadania (runner jest wspólny)
        self._outers = []

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_input())
        self.stack.addWidget(self._build_preview())
        self.stack.addWidget(self._build_result())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._render_result)
        self.partial.connect(lambda _upd: self._render_timer.start())
        runner.progress.connect(self._job_progress)
        runner.finished.connect(self._job_finished)

    # ================================================================== krok 1: wejście
    def _build_input(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(22)
        v.addWidget(Heading(tr("Rozwiąż test"),
                            tr("Wklej gotowy test albo wczytaj go z pliku. Aplikacja odpowie na pytania wyłącznie na "
                               "podstawie Twoich notatek – gdy odpowiedzi w nich nie ma, napisze „nie wiem”."),
                            tr("Nauka")))
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(tr("Wklej pytania…\n\n1. Które organellum odpowiada za oddychanie komórkowe?\n"
                                         "a) rybosom\nb) mitochondrium\nc) lizosom\nd) jądro"))
        self.paste.setMinimumHeight(230)
        self.btn_file = QPushButton(tr("Wczytaj z pliku"))
        set_icon(self.btn_file, "folder", "text", 16)
        self.btn_file.clicked.connect(self._load_file)
        self.file_lbl = label("", "footnote")
        g = GroupSection(tr("Pytania"), tr("Rozpoznaję numerację „1.”, „1)”, „Pytanie 1”, „Zad. 1” i odpowiedzi „a)”, "
                                           "„A.”, „(a)” – także wklejki z Moodle i MS Forms. Pliki: .txt, .docx, .pdf "
                                           "z tekstem."))
        g.add(_pad(self.paste))
        g.add(_pad(hbox(self.btn_file, self.file_lbl, "stretch"), (12, 4, 12, 10)))
        v.addWidget(g)

        self.scope = ChoiceCombo()
        self.scope.setMinimumWidth(300)
        self.speed = SegmentedControl([tr("Szybciej"), tr("Dokładniej")])
        from .exam_tab import SPEEDS, default_speed
        self.speed.set_current(SPEEDS.index(default_speed(self.settings)))
        self._speed_touched = False
        self.speed.changed.connect(lambda _i: setattr(self, "_speed_touched", True))
        self.guess = ToggleSwitch(False)
        g = GroupSection(tr("Zakres i ustawienia"))
        g.add_row(tr("Notatki"), self.scope)
        g.add_row(tr("Tempo"), self.speed, tr("Szybciej – mniejszy model AI. Dokładniej – staranniej, ale dłużej. "
                                              "Najwyżej 25 min."))
        g.add_row(tr("Gdy brak w notatkach – zgadnij z wiedzy ogólnej"), self.guess,
                  tr("Zgadnięte odpowiedzi są oznaczone znakiem zapytania, np. „4 = a?”."))
        v.addWidget(g)

        self.btn_parse = QPushButton(tr("Rozpoznaj pytania"))
        self.btn_parse.setObjectName("big")
        set_icon(self.btn_parse, "list", "on_accent", 17)
        self.btn_parse.clicked.connect(self.recognize)
        self.in_bar = QProgressBar()
        self.in_bar.setTextVisible(False)
        self.in_bar.hide()
        self.in_status = label("", "footnote", wrap=True)
        v.addWidget(hbox(self.btn_parse, "stretch"))
        v.addWidget(self.in_bar)
        v.addWidget(self.in_status)

        self.history = GroupSection(tr("Rozwiązane testy"))
        v.addWidget(self.history)
        v.addStretch()
        return _centered(col, 760)

    def refresh(self):
        cur = self.scope.currentData()
        lectures = [l for l in list_lectures(self.settings.library_path()) if l.notes_path.exists()]
        self.scope.fill_scope(lectures, tr("Wszystkie notatki"), subject_prefix=tr("Cały przedmiot: "), keep=cur)
        i = self.scope.findData(cur) if cur else -1
        if i < 0 and self.settings.last_subject:
            i = self.scope.findData(("subject", self.settings.last_subject))
        self.scope.setCurrentIndex(max(0, i))
        if not self._speed_touched:
            from .exam_tab import SPEEDS, default_speed
            self.speed.set_current(SPEEDS.index(default_speed(self.settings)))
        has = bool(lectures)
        self.btn_parse.setEnabled(not (self.runner.busy and self._job))
        if not has:
            self.in_status.setText(tr("Najpierw potrzebne są wykłady z gotowymi notatkami."))
        self._fill_history()

    def _fill_history(self):
        _clear(self.history.inner)
        self.history._count = 0
        tests = S.list_tests(self.settings.library_path())
        show_if(self.history, tests)
        for t_ in tests[:12]:
            sm = S.summary(t_)
            sub = (f"{t_.get('created', '')} · " + tn(sm["total"], "{n} pytanie", "{n} pytania", "{n} pytań")
                   + tr(" · z notatek: {n}", n=sm["notes"])
                   + (tr(" · niedokończony") if sm["timeout"] else ""))
            b_open = QPushButton(tr("Otwórz"))
            b_open.clicked.connect(lambda _=False, x=t_: self.show_test(x))
            b_del = QPushButton(tr("Usuń"))
            b_del.setObjectName("plain")
            b_del.clicked.connect(lambda _=False, x=t_: self._delete(x))
            self.history.add_row(t_.get("title", tr("Test")), hbox(b_del, b_open, spacing=6), sub)

    def _delete(self, t_):
        if self.test and self.test.get("id") == t_.get("id") and self._job:
            return
        S.delete_test(self.settings.library_path(), t_["id"])
        self._fill_history()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Wczytaj test"), str(Path.home()),
                                              tr("Test (*.txt *.docx *.pdf *.md);;Wszystkie pliki (*)"))
        if not path:
            return
        try:
            text = S.read_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Wczytaj test"), str(e))
            return
        self.paste.setPlainText(text)
        self.source_name = Path(path).stem
        self.file_lbl.setText(Path(path).name)

    def recognize(self):
        text = self.paste.toPlainText().strip()
        if not text:
            QMessageBox.information(self, tr("Rozwiąż test"), tr("Wklej pytania albo wczytaj test z pliku."))
            return
        qs = S.parse_test(text)
        self.used_ai = False
        if S.looks_bad(qs, text):
            self._split_ai(text, fallback=qs)      # parser nie dał rady – pytania dzieli AI
            return
        self.show_preview(qs)

    def _split_ai(self, text: str, fallback: list):
        s = self.settings
        speed = self._speed_key()
        prepare = not self.is_recording()
        self._split_result = None

        def fn(prog, cancel, tok):
            from .exam_tab import exam_llm
            llm, model = exam_llm(s, speed)
            if prepare:
                prog(tr("Zwalniam pamięć po innych modelach i ładuję model AI…"), -1)
                llm.unload_others(model)
                llm.preload(model, EX.EXAM_CTX, EX.KEEP_ALIVE)
            self._split_result = S.split_with_ai(text, llm, model, EX.EXAM_CTX, prog, cancel)
        self._split_fallback = fallback
        name = tr("Rozpoznawanie pytań")
        if not self.runner.run(name, fn, None):
            QMessageBox.information(self, tr("Trwa inne zadanie"), tr("Trwa: {name}. Poczekaj, aż się skończy.",
                                                                       name=self.runner.name))
            return
        self._job = name
        self.btn_parse.setEnabled(False)
        self.btn_ai.setEnabled(False)
        self.in_bar.show()
        self.in_bar.setRange(0, 0)
        self.in_status.setText(tr("Tekst jest nieregularny – pytania rozpoznaje AI…"))
        self.stack.setCurrentIndex(0)

    def _speed_key(self) -> str:
        from .exam_tab import SPEEDS
        return SPEEDS[self.speed.current()]

    # ================================================================== krok 2: podgląd pytań
    def _build_preview(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(36, 26, 36, 24)
        self._outers.append(outer)
        col = QWidget()
        col.setMaximumWidth(900)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        tv.addWidget(label(tr("Sprawdź pytania"), "title2"))
        self.pv_sub = label("", "secondary", wrap=True)
        tv.addWidget(self.pv_sub)
        head.addLayout(tv, 1)
        b_back = QPushButton(tr("Wróć"))
        b_back.setObjectName("plain")
        b_back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        head.addWidget(b_back, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        self.pv_note = label("", "footnote", wrap=True)
        v.addWidget(self.pv_note)
        self.pv_view = Reader(max_width=860, pad=24)
        self.pv_view.internal_link.connect(self._pv_link)
        v.addWidget(self.pv_view, 1)
        self.btn_ai = QPushButton(tr("Rozpoznaj przez AI"))
        self.btn_ai.setToolTip(tr("Gdy pytania są źle podzielone – AI podzieli tekst jeszcze raz."))
        self.btn_ai.clicked.connect(lambda: self._split_ai(self.paste.toPlainText(), self.questions))
        self.btn_solve = QPushButton(tr("Rozwiąż test"))
        self.btn_solve.setObjectName("big")
        set_icon(self.btn_solve, "sparkles", "on_accent", 17)
        self.btn_solve.clicked.connect(self.solve)
        v.addWidget(hbox(self.btn_ai, "stretch", self.btn_solve))
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        return w

    def show_preview(self, qs: list[dict]):
        self.questions = qs
        self._render_preview()
        self.stack.setCurrentIndex(1)

    def _render_preview(self):
        t = T()
        qs = self.questions
        self.pv_sub.setText(S.counts_text(qs) if qs else tr("Nie rozpoznano żadnego pytania."))
        notes = []
        if self.used_ai:
            notes.append(tr("Pytania podzieliło AI – sprawdź, czy niczego nie pominęło."))
        if any(q.get("auto") for q in qs):
            notes.append(tr("Część odpowiedzi nie miała liter – nadałem im kolejno a, b, c…"))
        nums = [q["nr"] for q in qs]
        if len(set(nums)) < len(nums):
            notes.append(tr("Niektóre numery pytań się powtarzają – sprawdź, czy pytanie nie jest rozdzielone."))
        self.pv_note.setText(" ".join(notes))
        show_if(self.pv_note, notes)
        self.btn_solve.setEnabled(bool(qs) and not self.runner.busy)
        link = f"color:{t.accent}; text-decoration:none"
        rows = []
        for i, q in enumerate(qs):
            opts = "<br>".join(f"{html.escape(o[0])})&nbsp; {html.escape(o[1])}" for o in q["options"])
            acts = [f"<a style='{link}' href='#e{i}'>{tr('Popraw')}</a>"]
            if i + 1 < len(qs):
                acts.append(f"<a style='{link}' href='#m{i}'>{tr('Scal z następnym')}</a>")
            acts.append(f"<a style='color:{t.red}; text-decoration:none' href='#d{i}'>{tr('Usuń')}</a>")
            rows.append(
                f"<p style='margin:14px 0 2px 0; color:{t.text3}'>{html.escape(q['nr'])} · {KIND_NAMES[q['kind']]()}</p>"
                f"<p style='margin:0 0 3px 0'><b>{html.escape(q['text']) or '…'}</b></p>"
                + (f"<p style='margin:0 0 3px 0; color:{t.text2}'>{opts}</p>" if opts else "")
                + f"<p style='margin:0'>{' &nbsp;·&nbsp; '.join(acts)}</p>")
        sb = self.pv_view.verticalScrollBar()
        pos = sb.value()
        self.pv_view.setHtml(f"<body style='color:{t.text}; line-height:140%'>{''.join(rows)}</body>")
        sb.setValue(pos)

    def _pv_link(self, anchor: str):
        kind, i = anchor[:1], anchor[1:]
        if not i.isdigit() or int(i) >= len(self.questions):
            return
        i = int(i)
        if kind == "d":
            del self.questions[i]
        elif kind == "m" and i + 1 < len(self.questions):
            self.questions[i:i + 2] = [S.merge(self.questions[i], self.questions[i + 1])]
        elif kind == "e":
            dlg = EditDialog(self.questions[i], self)
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_qs is None:
                return
            self.questions[i:i + 1] = dlg.result_qs
        self._render_preview()

    # ================================================================== krok 3: rozwiązywanie
    def solve(self):
        data = self.scope.currentData()
        if not data or not self.questions:
            return
        s = self.settings
        lib = s.library_path()
        title = self.source_name or (tr("Test – {scope}", scope=self.scope.currentText()))
        test = S.new_test([dict(q) for q in self.questions], data[0], data[1], title, self.guess.isChecked(),
                          self.source_name)
        test["scope_title"] = self.scope.currentText()
        test["speed"] = self._speed_key()
        S.save_test(lib, test)
        self._run(test)

    def _run(self, test: dict):
        s = self.settings
        lib = s.library_path()
        speed = test.get("speed", self._speed_key())
        prepare = not self.is_recording()     # nagrywanie trzyma model notatek na żywo – nie zwalniaj go

        def fn(prog, cancel, tok):
            from .exam_tab import exam_llm
            llm, model = exam_llm(s, speed)
            S.solve_test(lib, test, llm, model, EX.EXAM_CTX, prog, cancel, prepare=prepare,
                         on_results=self.partial.emit, save=lambda x: S.save_test(lib, x))
        name = tr("Rozwiązywanie testu")
        if not self.runner.run(name, fn, None):
            QMessageBox.information(self, tr("Trwa inne zadanie"), tr("Trwa: {name}. Poczekaj, aż się skończy.",
                                                                       name=self.runner.name))
            return
        self._job = name
        self.test = test
        self.res_bar.setRange(0, 0)
        self.res_status.setText(tr("Przygotowuję model AI…"))
        show_if(self.run_box, True)
        self._render_result()
        self.stack.setCurrentIndex(2)

    def _job_progress(self, msg, frac):
        if not self._job or self.runner.name != self._job:
            return
        if self.stack.currentIndex() == 2:
            self.res_status.setText(msg)
            bar = self.res_bar
        else:
            self.in_status.setText(msg)
            bar = self.in_bar
        if frac >= 0:
            bar.setRange(0, 1000)
            bar.setValue(int(frac * 1000))

    def _job_finished(self, ok, msg, _lec):
        job, self._job = self._job, ""
        if not job:
            return
        self.btn_parse.setEnabled(True)
        self.btn_ai.setEnabled(True)
        if job == tr("Rozpoznawanie pytań"):
            self.in_bar.hide()
            qs = getattr(self, "_split_result", None)
            fb = getattr(self, "_split_fallback", []) or []
            if ok and qs and len(qs) >= len(fb):
                self.in_status.setText("")
                self.used_ai = True
                self.show_preview(qs)
            elif fb:
                self.in_status.setText("")
                self.used_ai = False
                self.show_preview(fb)
                self.pv_note.setText(tr("AI nie podzieliło tekstu lepiej ({msg}) – pokazuję wynik zwykłego "
                                        "rozpoznawania.", msg=msg))
                show_if(self.pv_note, True)
            else:
                self.in_status.setText(msg if not ok else tr("Nie rozpoznano żadnego pytania."))
            return
        show_if(self.run_box, False)
        if self.test:
            if not ok and not self.runner.cancel.is_set():
                self.res_note_extra = msg
            S.save_test(self.settings.library_path(), self.test)
        self._render_result()
        self._fill_history()

    # ================================================================== krok 4: wynik
    def _build_result(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(36, 26, 36, 24)
        self._outers.append(outer)
        col = QWidget()
        col.setMaximumWidth(900)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.res_title = label("", "title2", wrap=True)
        self.res_sub = label("", "secondary", wrap=True)
        tv.addWidget(self.res_title)
        tv.addWidget(self.res_sub)
        head.addLayout(tv, 1)
        self.btn_new = QPushButton(tr("Nowy test"))
        self.btn_new.setObjectName("plain")
        self.btn_new.clicked.connect(self._new)
        head.addWidget(self.btn_new, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)

        # postęp (w trakcie)
        self.run_box = QWidget()
        rl = QVBoxLayout(self.run_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.res_bar = QProgressBar()
        self.res_bar.setTextVisible(False)
        self.res_status = label("", "footnote", wrap=True)
        self.btn_cancel = QPushButton(tr("Anuluj"))
        self.btn_cancel.setObjectName("plain")
        self.btn_cancel.clicked.connect(lambda: self.runner.cancel.set())
        rl.addWidget(self.res_bar)
        sl = QHBoxLayout()
        sl.addWidget(self.res_status, 1)
        sl.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignTop)
        rl.addLayout(sl)
        v.addWidget(self.run_box)

        # niedokończony (limit czasu / anulowano)
        self.res_note = label("", "footnote", wrap=True)
        self.btn_resume = QPushButton(tr("Dokończ pozostałe"))
        self.btn_resume.setObjectName("primary")
        self.btn_resume.clicked.connect(lambda: self.test and self._run(self.test))
        self.note_box = hbox(self.res_note, self.btn_resume, spacing=12)
        self.note_box.layout().setStretch(0, 1)
        v.addWidget(self.note_box)

        # zwięzła lista
        card = Sheet(radius=14)
        card.lay.setContentsMargins(18, 14, 18, 14)
        card.lay.setSpacing(8)
        self.card = card
        card.lay.addWidget(label(tr("Odpowiedzi").upper(), "sectionHeader"))
        self.compact_box = QPlainTextEdit()
        self.compact_box.setReadOnly(True)
        self.compact_box.setFixedHeight(84)
        card.lay.addWidget(self.compact_box)
        self.btn_copy = QPushButton(tr("Kopiuj"))
        self.btn_copy.setObjectName("primary")
        set_icon(self.btn_copy, "doc", "on_accent", 15)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_export = QPushButton(tr("Eksportuj .txt"))
        self.btn_export.clicked.connect(self._export)
        self.btn_edit = QPushButton(tr("Popraw pytania"))
        self.btn_edit.setObjectName("plain")
        self.btn_edit.setToolTip(tr("Wróć do listy pytań i rozwiąż test jeszcze raz."))
        self.btn_edit.clicked.connect(self._edit_again)
        card.lay.addWidget(hbox(self.btn_copy, self.btn_export, "stretch", self.btn_edit))
        v.addWidget(card)

        self.filter = SegmentedControl([tr("Wszystkie"), tr("Z notatek"), tr("Zgadnięte"), tr("Nie wiem")])
        self.filter.changed.connect(lambda _i: self._render_result())
        v.addWidget(hbox(self.filter, "stretch"))
        self.res_view = Reader(max_width=860, pad=24)
        self.res_view.internal_link.connect(self._res_link)
        v.addWidget(self.res_view, 1)
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        return w

    def show_test(self, test: dict):
        if self._job and self.test and self.test.get("id") == test.get("id"):
            self.stack.setCurrentIndex(2)        # właśnie się rozwiązuje – pokaż na żywo
            return
        if self._job == tr("Rozwiązywanie testu"):
            QMessageBox.information(self, tr("Trwa inne zadanie"), tr("Trwa: {name}. Poczekaj, aż się skończy.",
                                                                       name=self._job))
            return
        self.test = test
        show_if(self.run_box, False)
        self.filter.set_current(0)
        self._render_result()
        self.stack.setCurrentIndex(2)

    def _render_result(self):
        test = self.test
        if not test:
            return
        t = T()
        running = bool(self._job) and self._job == tr("Rozwiązywanie testu")
        sm = S.summary(test)
        self.res_title.setText(test.get("title", tr("Test")))
        secs = (test.get("stats") or {}).get("seconds")
        sub = [tr("Z notatek: {a} · zgadnięte: {g} · nie wiem: {u}", a=sm["notes"], g=sm["guess"],
                  u=sm["unknown"]) + (tr(" · bez odpowiedzi: {n}", n=sm["timeout"]) if sm["timeout"] and not running
                                      else "")]
        if test.get("scope_title"):
            sub.append(tr("Notatki: {scope}", scope=test["scope_title"]))
        if secs and not running:
            sub.append(tr("czas: {m} min", m=max(1, round(secs / 60))))
        self.res_sub.setText(" · ".join(sub))
        left = sm["timeout"]
        if not running and left:
            why = tr("Nie zdążyłem odpowiedzieć na {n} z {n2} pytań w wyznaczonym czasie.", n=left, n2=sm["total"]) \
                if test.get("timed_out") else tr("Rozwiązywanie przerwane – zostało {n} z {n2} pytań.", n=left,
                                                 n2=sm["total"])
            extra = getattr(self, "res_note_extra", "")
            self.res_note.setText(why + (f" {extra}" if extra else ""))
            self.res_note_extra = ""
        show_if(self.note_box, not running and left)
        self.compact_box.setPlainText(S.compact(test, "…" if running else None))
        for b in (self.btn_copy, self.btn_export):
            b.setEnabled(not running or sm["notes"] + sm["guess"] + sm["unknown"] > 0)
        self.btn_edit.setEnabled(not running)
        self.btn_new.setEnabled(True)

        want = FILTERS[max(0, self.filter.current())]
        link = f"color:{t.accent}; text-decoration:none"
        rows = []
        self._res_src = {}
        for i, (q, r) in enumerate(zip(test["questions"], test.get("results", []))):
            st = (r or {}).get("status") or ("pending" if running else "timeout")
            if want != "all" and not (st == want or want == "unknown" and st in ("unknown", "timeout")):
                continue
            ans = S.answer_label(q, r)
            if st == "notes":
                color, what = t.green, tr("z notatek · pewność: {c}", c=S.conf_name(r.get("confidence")))
            elif st == "guess":
                color, what = t.orange, tr("zgadnięte z wiedzy ogólnej – brak w notatkach")
            elif st == "pending":
                color, what, ans = t.text3, tr("czeka…"), "…"
            elif st == "timeout":
                color, what = t.text3, tr("bez odpowiedzi – zabrakło czasu")
            else:
                color, what = t.text2, tr("brak w notatkach")
            chosen = set((r or {}).get("answer", "").split(",")) if st in ("notes", "guess") else set()
            opts = []
            for o in q["options"]:
                txt = f"{html.escape(o[0])})&nbsp; {html.escape(o[1])}"
                opts.append(f"<span style='color:{color}; font-weight:600'>{txt}</span>" if o[0] in chosen else txt)
            parts = [f"<p style='margin:16px 0 3px 0'><b>{html.escape(q['nr'])}.</b> {html.escape(q['text'])}</p>"]
            if opts:
                parts.append(f"<p style='margin:0 0 4px 0; color:{t.text2}'>{'<br>'.join(opts)}</p>")
            parts.append(f"<p style='margin:0 0 2px 0'><span style='color:{color}; font-weight:700'>"
                         f"{html.escape(ans)}</span>&nbsp;&nbsp;<span style='color:{t.text2}'>{what}</span></p>")
            if r and r.get("quote"):
                src = r.get("source") or {}
                self._res_src[f"s{i}"] = src
                parts.append(f"<p style='margin:0 0 2px 0; color:{t.text2}'><i>„{html.escape(r['quote'])}”</i>"
                             + (f"&nbsp; <a style='{link}' href='#s{i}'>→ {html.escape(src.get('title', ''))}</a>"
                                if src else "") + "</p>")
            if r and r.get("why") and st != "timeout":
                parts.append(f"<p style='margin:0; color:{t.text3}'>{html.escape(r['why'])}</p>")
            rows.append("".join(parts))
        if not rows:
            rows.append(f"<p style='color:{t.text2}'>{tr('Brak pytań w tym widoku.')}</p>")
        sb = self.res_view.verticalScrollBar()
        pos = sb.value()
        self.res_view.setHtml(f"<body style='color:{t.text}; line-height:140%'>{''.join(rows)}</body>")
        sb.setValue(pos)

    def _res_link(self, anchor: str):
        src = getattr(self, "_res_src", {}).get(anchor)
        if src:
            self.open_lecture.emit(src.get("folder", ""), src.get("anchor", ""))

    def _copy(self):
        if not self.test:
            return
        QApplication.clipboard().setText(S.compact(self.test))
        self.btn_copy.setText(tr("Skopiowano"))
        QTimer.singleShot(1600, lambda: self.btn_copy.setText(tr("Kopiuj")))

    def _export(self):
        if not self.test:
            return
        from ..storage import safe_name
        default = str(Path.home() / f"{safe_name(self.test.get('title', 'test'))} – {tr('odpowiedzi')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, tr("Eksportuj odpowiedzi"), default, tr("Tekst (*.txt)"))
        if path:
            Path(path).write_text(S.export_txt(self.test), encoding="utf-8")

    def _edit_again(self):
        if not self.test:
            return
        self.questions = [dict(q) for q in self.test["questions"]]
        self.guess.setChecked(bool(self.test.get("guess")))
        i = self.scope.findData((self.test.get("scope"), self.test.get("value")))
        if i >= 0:
            self.scope.setCurrentIndex(i)
        self.source_name = self.test.get("source_name", "")
        self.used_ai = False
        self.show_preview(self.questions)

    def _new(self):
        if self._job == tr("Rozwiązywanie testu"):
            # zadanie dalej trwa w tle; wynik będzie w „Rozwiązane testy”
            pass
        self.refresh()
        self.stack.setCurrentIndex(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < 700
        for o in self._outers:
            o.setContentsMargins(*((14, 16, 14, 14) if narrow else (36, 26, 36, 24)))
        self.compact_box.setFixedHeight(110 if narrow else 84)


class EditDialog(QDialog):
    """Popraw pytanie: treść i opcje jako zwykły tekst (rozpoznawany jak wklejka) + rodzaj pytania.
    Wpisanie dwóch pytań rozdziela je na dwa."""

    def __init__(self, q: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Popraw pytanie"))
        self.setMinimumWidth(520)
        self.q = q
        self.result_qs = None
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        v.addWidget(label(tr("Numer, treść i odpowiedzi – każda odpowiedź w osobnej linii (a), b), c)…)."),
                          "footnote", wrap=True))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText("\n".join([f"{q['nr']}. {q['text']}"] + [f"{o[0]}) {o[1]}" for o in q["options"]]))
        self.edit.setMinimumHeight(180)
        v.addWidget(self.edit)
        self.kinds = list(S.KINDS)
        self.kind = QComboBox()
        style_combo(self.kind, 260)
        for k in self.kinds:
            self.kind.addItem(KIND_NAMES[k](), k)
        self.kind.setCurrentIndex(self.kinds.index(q["kind"]))
        self._touched = False
        self.kind.currentIndexChanged.connect(lambda _i: setattr(self, "_touched", True))
        v.addWidget(hbox(label(tr("Rodzaj pytania")), self.kind, "stretch", spacing=10))
        ok = QPushButton(tr("Zapisz"))
        ok.setObjectName("primary")
        ok.clicked.connect(self._ok)
        cancel = QPushButton(tr("Anuluj"))
        cancel.setObjectName("plain")
        cancel.clicked.connect(self.reject)
        v.addWidget(hbox("stretch", cancel, ok))

    def _ok(self):
        text = self.edit.toPlainText().strip()
        qs = S.parse_test(text) if text else []
        if not qs:
            QMessageBox.information(self, tr("Popraw pytanie"), tr("Wpisz treść pytania."))
            return
        if len(qs) == 1:
            q = qs[0]
            if not re_has_number(text):
                q["nr"] = self.q["nr"]           # numer zostaje, gdy go nie wpisano
            if self._touched:
                k = self.kinds[self.kind.currentIndex()]
                if k in ("abcd", "multi") and not q["options"]:
                    QMessageBox.information(self, tr("Popraw pytanie"),
                                            tr("Pytanie zamknięte potrzebuje co najmniej dwóch odpowiedzi."))
                    return
                if k == "open":
                    q["options"] = []
                q["kind"] = k
        self.result_qs = qs
        self.accept()


def re_has_number(text: str) -> bool:
    import re
    return bool(re.match(r"^\s*(?:pytanie|zad\.?|zadanie|question)?\s*\d{1,3}\s*[.):]", text, re.IGNORECASE))
