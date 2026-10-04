"""Szybkie przejście (Ctrl+K): wykłady, tematy z notatek i ekrany aplikacji w jednym polu wyszukiwania."""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QDialog, QFrame, QLineEdit, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QVBoxLayout)

from .controls import label, paint_shadow
from .theme import T, icon_pixmap, qcolor, soft, subject_color

DATA = Qt.ItemDataRole.UserRole + 1
PAGES = [
    ("Nowa notatka", "record", "plus", "nagranie albo pliki"),
    ("Wszystkie wykłady", "library", "books", "biblioteka"),
    ("Fiszki", "study", "cards", "nauka z powtórkami"),
    ("Zapytaj", "ask", "question", "pytania do notatek"),
    ("Egzamin próbny", "exam", "exam", "sprawdź się"),
    ("Ustawienia", "settings", "settings", "motyw, modele, aktualizacje"),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("ł", "l"))
    return "".join(c for c in s if not unicodedata.combining(c))


class _Delegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 52)

    def paint(self, p: QPainter, option, index):
        t = T()
        d = index.data(DATA)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if sel or hov:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft if sel else t.hover))
            p.drawRoundedRect(r, t.r("sm"), t.r("sm"))
        ic = QRectF(r.left() + 10, r.center().y() - 15, 30, 30)
        color = d.get("color") or t.accent
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(soft(color)))
        p.drawRoundedRect(ic, t.r("sm"), t.r("sm"))
        dpr = p.device().devicePixelRatioF()
        p.drawPixmap(int(ic.center().x() - 9), int(ic.center().y() - 9), icon_pixmap(d["icon"], color, 18, dpr))
        tag = d.get("tag", "")
        f = QFont(option.font)
        f.setPointSizeF(option.font.pointSizeF() - 1.5)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(tag) + 16
        p.setPen(qcolor(t.text3))
        p.drawText(QRectF(r.right() - tw - 6, r.top(), tw, r.height()), Qt.AlignmentFlag.AlignCenter, tag)
        tx = ic.right() + 12
        avail = int(r.right() - tw - 12 - tx)
        f = QFont(option.font)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(tx, r.top() + 6, avail, 20), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d["title"], Qt.TextElideMode.ElideRight, avail))
        f = QFont(option.font)
        f.setPointSizeF(option.font.pointSizeF() - 1.2)
        p.setFont(f)
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(tx, r.top() + 26, avail, 18), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("sub", ""), Qt.TextElideMode.ElideRight, avail))
        p.restore()


class QuickJump(QDialog):
    """Okienko na środku u góry okna: pole wyszukiwania + lista wyników. Enter otwiera, Esc zamyka."""
    chosen = Signal(str, str, str)       # rodzaj („page” / „lecture”), a, b

    def __init__(self, settings, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(True)
        self.settings = settings
        self.box = QFrame(self)
        self.box.setObjectName("pane")
        v = QVBoxLayout(self.box)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setObjectName("askInput")
        self.edit.setPlaceholderText("Szukaj wykładu, tematu albo ekranu…")
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        self.list = QListWidget()
        self.list.setObjectName("lectureList")
        self.list.setItemDelegate(_Delegate(self.list))
        self.list.setMouseTracking(True)
        self.list.itemActivated.connect(self._accept)
        self.list.itemClicked.connect(self._accept)
        self.hint = label("↑ ↓ wybór · Enter otwórz · Esc zamknij", "caption")
        v.addWidget(self.edit)
        v.addWidget(self.list, 1)
        v.addWidget(self.hint)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)
        outer.addWidget(self.box)
        self.items = self._index()
        self._filter("")

    # ------------------------------------------------------------------ dane
    def _index(self) -> list[dict]:
        from ..storage import list_lectures
        from ..topics import sections_of
        out = [{"kind": "page", "a": key, "b": "", "title": name, "sub": sub, "icon": icon, "tag": "Ekran"}
               for name, key, icon, sub in PAGES]
        for lec in list_lectures(self.settings.library_path()):
            m = lec.meta
            col = subject_color(m.subject) if m.subject else T().accent
            date = ".".join(reversed((m.created or "")[:10].split("-"))) if m.created else ""
            out.append({"kind": "lecture", "a": str(lec.folder), "b": "", "title": m.title, "icon": "doc",
                        "sub": " · ".join(x for x in (m.subject, date) if x), "tag": "Wykład", "color": col})
            try:
                md = lec.read_text(lec.notes_path) if lec.notes_path.exists() else ""
            except Exception:  # noqa: BLE001
                md = ""
            for num, title, anchor, tm in sections_of(md):
                out.append({"kind": "lecture", "a": str(lec.folder), "b": anchor, "title": f"{num}. {title}",
                            "icon": "list", "sub": m.title + (f" · {tm}" if tm else ""), "tag": "Temat",
                            "color": col, "topic": True})
        for d in out:
            d["key"] = _norm(d["title"] + " " + d["sub"])
        return out

    def _filter(self, text: str):
        words = _norm(text).split()
        self.list.clear()
        res = []
        for d in self.items:
            if words and not all(w in d["key"] for w in words):
                continue
            if not words and d.get("topic"):
                continue
            score = 0 if (words and _norm(d["title"]).startswith(words[0])) else 1
            res.append((score, d))
        res.sort(key=lambda x: x[0])
        for _s, d in res[:60]:
            it = QListWidgetItem(d["title"])
            it.setData(DATA, d)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.hint.setText("Nic nie pasuje – spróbuj innego słowa." if not self.list.count() else
                          "↑ ↓ wybór · Enter otwórz · Esc zamknij")

    # ------------------------------------------------------------------ klawiatura
    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._accept(it)
                return True
        return super().eventFilter(obj, e)

    def _accept(self, it):
        d = it.data(DATA)
        self.close()
        self.chosen.emit(d["kind"], d["a"], d["b"])

    def popup(self):
        par = self.parentWidget()
        w = min(660, max(420, par.width() - 80)) if par else 620
        h = min(520, max(320, (par.height() - 120) if par else 480))
        self.resize(w, h)
        if par:
            g = par.geometry()
            self.move(g.left() + (g.width() - w) // 2, g.top() + 70)
        self.show()
        self.edit.setFocus()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_shadow(p, QRectF(self.box.geometry()), T().r("lg"), 1.6)
        p.end()
