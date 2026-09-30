"""Ekran „Zapytaj” w sekcji Nauka: pytania do notatek jednego wykładu, całego przedmiotu albo wszystkich."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..notes_doc import Chunk, chunks
from ..storage import list_lectures
from .ask_panel import AskPanel


class AskTab(QWidget):
    open_lecture = Signal(str, str)      # folder, kotwica

    def __init__(self, settings, busy_hint=None):
        super().__init__()
        self.setObjectName("page")
        self.settings = settings
        self._map: dict[str, tuple[str, str]] = {}

        from .controls import ChoiceCombo
        self.scope = ChoiceCombo()
        self.scope.setMinimumWidth(300)
        self.scope.currentIndexChanged.connect(lambda _i: self._apply())
        self.panel = AskPanel(settings, busy_hint=busy_hint)
        self.panel.hint.setText("Odpowiedzi pochodzą wyłącznie z notatek z wybranego zakresu – każda z cytatem i "
                                "odnośnikiem do wykładu. Jeśli czegoś w nich nie ma, zobaczysz to wprost.")
        self.panel.internal_link.connect(self._link)

        from .controls import AdaptiveBox, Heading
        head = AdaptiveBox(threshold=820, spacing=16, vspacing=12)
        head.add(Heading("Zapytaj", "Pytania do notatek z wielu wykładów – np. przy zadaniach domowych albo przed "
                                    "kolokwium."), 1)
        head.add(self.scope, 0, Qt.AlignmentFlag.AlignBottom, Qt.AlignmentFlag.AlignLeft)
        col = QWidget()
        col.setMaximumWidth(1000)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)
        v.addWidget(head)
        v.addWidget(self.panel, 1)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 24)
        outer.addStretch()
        outer.addWidget(col, 20)
        outer.addStretch()
        self.outer = outer

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = (16, 16, 16, 14) if self.width() < 700 else (36, 30, 36, 24)
        self.outer.setContentsMargins(*m)

    def refresh(self):
        cur = self.scope.currentData()
        lectures = [l for l in list_lectures(self.settings.library_path()) if l.notes_path.exists()]
        self.scope.fill_scope(lectures, "Wszystkie wykłady", keep=cur)
        self.scope.blockSignals(True)
        i = self.scope.findData(cur) if cur else -1
        if i < 0 and self.settings.last_subject:
            i = self.scope.findData(("subject", self.settings.last_subject))
        self.scope.setCurrentIndex(max(0, i))
        self.scope.blockSignals(False)
        self._apply()

    def _apply(self):
        kind, val = self.scope.currentData() or ("all", "")
        lib = self.settings.library_path()
        key = re.sub(r"\W+", "_", f"{kind}_{Path(val).name if kind == 'lecture' else val}")[:80]
        hist = lib / ".pytania"
        hist.mkdir(exist_ok=True)
        self._scope = (kind, val)

        def get_parts():
            return self._collect(kind, val)
        self.panel.set_source(get_parts, hist / f"{key}.json", int(self.settings.ollama_ctx))
        self.panel.empty.text.setText("W tym zakresie nie ma jeszcze notatek.")

    def _collect(self, kind: str, val: str) -> list[Chunk]:
        parts: list[Chunk] = []
        mapping = {}
        for k, lec in enumerate(list_lectures(self.settings.library_path())):
            if not lec.notes_path.exists():
                continue
            if kind == "subject" and lec.meta.subject != val:
                continue
            if kind == "lecture" and str(lec.folder) != val:
                continue
            for c in chunks(lec.read_text(lec.notes_path)):
                anchor = f"L{k}-{c.anchor}"
                mapping[anchor] = (str(lec.folder), c.anchor)
                parts.append(Chunk(anchor, f"{lec.meta.title} › {c.title}", c.time, c.text))
        self._map.update(mapping)
        return parts

    def _link(self, anchor: str):
        if anchor not in self._map:
            self._collect(*getattr(self, "_scope", ("all", "")))
        if anchor in self._map:
            folder, a = self._map[anchor]
            self.open_lecture.emit(folder, a)
