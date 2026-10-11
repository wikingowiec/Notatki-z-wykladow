"""Okno potwierdzenia odinstalowania: co usunąć (pola do zaznaczenia), ile miejsca zajmuje każda pozycja (liczone
w tle) i ile miejsca się zwolni. Notatki i nagrania są domyślnie odznaczone – po zaznaczeniu jest jeszcze jedno
pytanie z liczbą wykładów."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..config import APP_NAME
from ..i18n import gb, tn, tr
from ..system import IS_MAC, IS_STORE, IS_WIN
from .controls import CheckBox, GroupSection, label, show_if


def _size_text(n) -> str:
    if n is None:
        return tr("liczę…")
    if 0 < n < 1e6:
        return "< 1 MB"
    return gb(n)


class _ItemRow(QWidget):
    """Pole do zaznaczenia z tytułem, opisem i rozmiarem po prawej. Kliknięcie w cały wiersz zaznacza pole."""
    toggled = Signal()

    def __init__(self, item):
        super().__init__()
        self.item = item
        self.box = CheckBox(item.checked)
        self.box.setEnabled(item.enabled)
        self.box.toggled.connect(lambda _on: self.toggled.emit())
        self.title = label(item.title)
        self.desc = label(item.desc, "footnote", wrap=True)
        show_if(self.desc, item.desc)
        self.warn = label("", "errorText", wrap=True)
        if item.danger:
            self.warn.setText(tr("Tego nie da się cofnąć.") + (" " + tn(item.count, "{n} wykład", "{n} wykłady",
                                                                       "{n} wykładów") if item.count else ""))
        show_if(self.warn, item.danger)
        self.size = label(_size_text(item.size), "secondary")
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.size.setMinimumWidth(70)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(self.title)
        texts.addWidget(self.desc)
        texts.addWidget(self.warn)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 16, 10)
        h.setSpacing(12)
        h.addWidget(self.box, 0, Qt.AlignmentFlag.AlignTop)
        h.addLayout(texts, 1)
        h.addWidget(self.size, 0, Qt.AlignmentFlag.AlignTop)
        if not item.enabled:
            self.title.setObjectName("secondary")
            self.size.setText("")
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.box.isEnabled() and e.button() == Qt.MouseButton.LeftButton and not self.box.underMouse():
            self.box.toggle()
        super().mouseReleaseEvent(e)

    def checked(self) -> bool:
        # pole może być zablokowane jako zaznaczone (runtime razem z plikami programu) – liczy się wtedy dalej
        return self.item.enabled and self.box.isChecked()

    def set_size(self, n: int):
        self.item.size = n
        if self.item.enabled:
            self.size.setText(_size_text(n))


class UninstallDialog(QDialog):
    sized = Signal(str, object)          # klucz pozycji, rozmiar w bajtach

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from ..uninstall import DRY, Plan
        self.setWindowTitle(tr("Odinstaluj aplikację"))
        self.setMinimumWidth(600)
        self.plan = Plan(settings)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(10)
        v.addWidget(label(tr("Odinstalować {app}?", app=APP_NAME), "title3"))
        intro = tr("Zaznacz, co usunąć. Usuwamy tylko to, co zainstalowała aplikacja – programy i modele, które były "
                   "na komputerze wcześniej, zostają.")
        if DRY:
            intro += " " + tr("Tryb próbny: nic nie zostanie usunięte, lista trafi do logu.")
        v.addWidget(label(intro, "secondary", wrap=True))
        v.addSpacing(4)
        g = GroupSection()
        self.rows: dict[str, _ItemRow] = {}
        for it in self.plan.items:
            r = _ItemRow(it)
            r.toggled.connect(self._changed)
            g.add(r)
            self.rows[it.key] = r
        v.addWidget(g)
        self.total = label("", "title3")
        self.total_note = label("", "footnote", wrap=True)
        v.addSpacing(4)
        v.addWidget(self.total)
        v.addWidget(self.total_note)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        b_cancel = QPushButton(tr("Anuluj"))
        b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(tr("Odinstaluj"))
        self.b_ok.setObjectName("danger")
        self.b_ok.setMinimumWidth(140)
        self.b_ok.clicked.connect(self._confirm)
        row.addWidget(b_cancel)
        row.addWidget(self.b_ok)
        v.addSpacing(6)
        v.addLayout(row)
        b_cancel.setDefault(True)
        self.resize(640, 10)
        self.sized.connect(self._on_size)
        self._changed()
        threading.Thread(target=self._measure, name="rozmiary", daemon=True).start()

    # ------------------------------------------------------------------ wysokość z zawijanymi opisami
    def _fit_height(self):
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            need = lay.totalHeightForWidth(self.width())
            if need != self.minimumHeight():
                self.setMinimumHeight(need)
                if self.height() < need:
                    self.resize(self.width(), need)

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_height()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    def _measure(self):
        for it in self.plan.items:
            try:
                n = self.plan.measure(it.key)
            except Exception:  # noqa: BLE001
                n = 0
            self.sized.emit(it.key, n)

    def _on_size(self, key: str, n):
        r = self.rows.get(key)
        if r is not None:
            r.set_size(int(n))
        self._changed()

    def _changed(self):
        # Windows (wersja z GitHuba): runtime leży w _internal – znika razem z plikami programu
        prog, rt = self.rows.get("program"), self.rows.get("runtime")
        if IS_WIN and not IS_STORE and not IS_MAC and prog is not None and rt is not None:
            if prog.checked():
                rt.box.setChecked(True)
            rt.box.setEnabled(not prog.box.isChecked())
            rt.desc.setText(tr("Usuwa się razem z plikami programu.") if prog.box.isChecked() else rt.item.desc)
        sel = [r for r in self.rows.values() if r.checked()]
        known = sum(r.item.size or 0 for r in sel)
        pending = any(r.item.size is None for r in sel)
        self.b_ok.setEnabled(bool(sel))
        if not sel:
            self.total.setText(tr("Nic nie zaznaczono"))
        elif pending:
            self.total.setText(tr("Zwolnisz ok. {x} – liczę dalej…", x=gb(known)) if known else tr("Liczę rozmiar…"))
        else:
            self.total.setText(tr("Zwolnisz ok. {x}", x=gb(known)))
        lib = self.rows.get("library")
        self.total_note.setText(tr("Twoje notatki, nagrania i fiszki zostają w folderze {path}.", path=self.plan.lib)
                                if lib is None or not lib.checked() else
                                tr("Razem z notatkami, nagraniami i fiszkami."))
        if IS_STORE and sel:
            self.total_note.setText(self.total_note.text() + " " +
                                    tr("Sam pakiet SlideScribe usuniesz na końcu w Ustawieniach Windows."))
        self._fit_height()

    def keys(self) -> list[str]:
        return [k for k, r in self.rows.items() if r.checked()]

    def _confirm(self):
        lib = self.rows.get("library")
        if lib is not None and lib.checked():
            n = lib.item.count
            msg = (tr("Usunąć na zawsze {lectures} z folderu {path}? Razem z nagraniami, slajdami, notatkami i "
                      "fiszkami. Tego nie da się cofnąć.",
                      lectures=tn(n, "{n} wykład", "{n} wykłady", "{n} wykładów"), path=self.plan.lib)
                   if n else tr("Usunąć na zawsze folder {path} z notatkami i fiszkami? Tego nie da się cofnąć.",
                                path=self.plan.lib))
            box = QMessageBox(QMessageBox.Icon.Warning, tr("Usunąć notatki i nagrania?"), msg,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.button(QMessageBox.StandardButton.Yes).setText(tr("Usuń na zawsze"))
            box.button(QMessageBox.StandardButton.No).setText(tr("Anuluj"))
            box.setDefaultButton(QMessageBox.StandardButton.No)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
        # rozmiary jeszcze liczone – Uninstaller policzy brakujące sam
        self.accept()
