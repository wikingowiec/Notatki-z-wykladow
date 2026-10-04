"""Elementy ekranu nagrywania: transkrypcja z zaznaczeniami i separatorami slajdów, bieżący slajd z tekstem,
podpowiedź o prawie identycznych slajdach, „szkielet” notatki, która właśnie się pisze."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..storage import fmt_time
from .controls import label, rounded_pixmap, set_icon
from .theme import T


def slide_title(text: str, limit: int = 42) -> str:
    """Pierwsza sensowna linia tekstu slajdu – do separatora w transkrypcji."""
    for line in (text or "").splitlines():
        t = re.sub(r"^[\s\-•*·]+", "", line).strip()
        if len(t) >= 3:
            return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def _marked(seg: dict, marks: list[dict]) -> bool:
    for m in marks:
        end = m.get("end")
        if seg["end"] >= m["start"] and (end is None or seg["start"] <= end):
            return True
    return False


def transcript_html(items: list[dict], marks: list[dict], slide_texts: dict, live: bool) -> str:
    """items: {"kind": "seg", start, end, text} albo {"kind": "slide", index, t}. Ostatni fragment mowy jest
    „bieżący” (kolor ink2 i kursor), dopóki nie przyjdzie następny."""
    t = T()
    out = []
    last_seg = max((i for i, x in enumerate(items) if x["kind"] == "seg"), default=-1)
    for i, it in enumerate(items):
        if it["kind"] == "note":
            out.append(f"<p style='margin:14px 0 10px 0; color:{t.accent_text}; font-weight:700;'>"
                       f"— {html.escape(it['text'])} —</p>")
            continue
        if it["kind"] == "slide":
            title = slide_title(slide_texts.get(it["index"], ""))
            cap = " · ".join(x for x in (f"Slajd {it['index']}", title, fmt_time(it["t"])) if x)
            out.append(f"<p style='margin:14px 0 10px 0; color:{t.accent_text}; font-size:9pt; font-weight:700;'>"
                       f"<span style='color:{t.line2}'>———</span>&nbsp; {html.escape(cap)} &nbsp;"
                       f"<span style='color:{t.line2}'>———</span></p>")
            continue
        cur = live and i == last_seg
        marked = _marked(it, marks)
        txt = html.escape(it["text"].strip())
        if cur:
            txt += f"<span style='color:{t.accent}'>&nbsp;▍</span>"
        tag = (f"&nbsp;&nbsp;<span style='color:{t.wazText}; font-size:8pt; font-weight:700;'>WAŻNE</span>"
               if marked else "")
        bg = f"background-color:{t.mark};" if marked else ""
        col = t.text2 if cur else t.text
        out.append(f"<table width='100%' cellspacing='0' cellpadding='0' style='margin:0 0 7px 0;'><tr>"
                   f"<td width='50' valign='top' style='color:{t.text3}; font-size:9pt; padding-top:2px;'>"
                   f"{fmt_time(it['start'])}</td>"
                   f"<td style='{bg} color:{col}; padding:{'3px 6px' if marked else '0'};'>{txt}{tag}</td></tr></table>")
    return f"<body style='color:{t.text}; line-height:150%'>{''.join(out)}</body>"


def skeleton_html(text: str) -> str:
    """Fragment notatki w trakcie pisania: przerywana ramka z szarymi paskami."""
    t = T()
    bars = "".join(
        f"<table width='100%' cellspacing='0' cellpadding='0' style='margin:0 0 10px 0;'><tr>"
        f"<td width='{w}%' style='background-color:{t.separator}; font-size:4pt;'>&nbsp;</td>"
        f"<td style='font-size:4pt;'>&nbsp;</td></tr></table>"
        for w in (46, 92, 84, 70))
    return (f"<table width='100%' border='1' cellspacing='0' cellpadding='16' "
            f"style='border-style:dashed; border-color:{t.line2}; margin-top:18px;'><tr><td>"
            f"<p style='margin:0 0 12px 0; color:{t.text3}; font-size:8.5pt; font-weight:700;'>PISZĘ NASTĘPNY FRAGMENT</p>"
            f"{bars}<p style='margin:6px 0 0 0; color:{t.text3};'>{html.escape(text)}</p></td></tr></table>")


class CurrentSlide(QWidget):
    """Bieżący slajd (duży), podpis, „Tekst ze slajdu” z przyciskiem Kopiuj."""
    open_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self.index = 0
        self.text = ""
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setCursor(Qt.CursorShape.PointingHandCursor)
        self.img.setToolTip("Powiększ")
        self.img.mousePressEvent = lambda _e: self.index and self.open_requested.emit(self.index)
        self.cap = label("", "caption")
        self.head = label("TEKST ZE SLAJDU", "sectionHeader")
        self.b_copy = QPushButton("Kopiuj")
        self.b_copy.setObjectName("plain")
        set_icon(self.b_copy, "doc", "accent_text", 14)
        self.b_copy.clicked.connect(self._copy)
        self.body = label("", "footnote", wrap=True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        from PySide6.QtWidgets import QBoxLayout
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.head, 1)
        h.addWidget(self.b_copy)
        self.left = QWidget()
        lv = QVBoxLayout(self.left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(self.img)
        lv.addWidget(self.cap)
        self.right = QWidget()
        rv = QVBoxLayout(self.right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)
        rv.addLayout(h)
        rv.addWidget(self.body)
        rv.addStretch(1)
        self.main = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self.main.setContentsMargins(0, 0, 0, 0)
        self.main.setSpacing(10)
        self.main.addWidget(self.left)
        self.main.addWidget(self.right, 1)
        self.horizontal = False
        self._pm = QPixmap()
        self.set_slide(None)

    def set_slide(self, info):
        if info is None:
            self.index, self.text = 0, ""
            self._pm = QPixmap()
            self.img.setText("Pierwszy slajd pojawi się tutaj.")
            self.img.setStyleSheet(f"color:{T().text3}; border:1px dashed {T().line2}; border-radius:{T().r('md')}px;")
            self.img.setFixedHeight(150)
            self.cap.setText("")
            self.body.setText("")
            self.b_copy.setEnabled(False)
            return
        self.img.setStyleSheet("")
        self.index, self.text = info.index, info.text or ""
        self._pm = QPixmap(info.path)
        self.cap.setText(info.caption)
        self.body.setText(html.escape(self.text.strip())[:900].replace("\n", "<br>") if self.text.strip() else
                          f"<span style='color:{T().text3}'>Odczytuję tekst…</span>")
        self.b_copy.setEnabled(bool(self.text.strip()))
        self._fit()

    def set_horizontal(self, on: bool):
        """Wąskie okno: slajd z lewej (220 px), tekst obok."""
        from PySide6.QtWidgets import QBoxLayout
        self.horizontal = on
        self.main.setDirection(QBoxLayout.Direction.LeftToRight if on else QBoxLayout.Direction.TopToBottom)
        self.left.setFixedWidth(220) if on else (self.left.setMinimumWidth(0), self.left.setMaximumWidth(16777215))
        self.body.setMaximumHeight(110 if on else 16777215)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        if self._pm.isNull():
            return
        dpr = self.devicePixelRatioF() or 1.0
        w = max(120, 220 if self.horizontal else self.width())
        h = int(w * self._pm.height() / max(1, self._pm.width()))
        pm = self._pm.scaled(int(w * dpr), int(h * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.img.setFixedHeight(h)
        self.img.setPixmap(rounded_pixmap(pm))

    def _copy(self):
        QApplication.clipboard().setText(self.text.strip())
        self.b_copy.setText("Skopiowano ✓")
        QTimer.singleShot(1500, lambda: self.b_copy.setText("Kopiuj"))


class DupHint(QFrame):
    """„Slajdy 4 i 5 to prawie to samo. Usuń 5”."""
    delete = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("warnBanner")
        self.index = 0
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 6, 6)
        h.setSpacing(6)
        self.text = label("", "footnote", wrap=True)
        self.b_del = QPushButton("Usuń")
        self.b_del.setObjectName("plain")
        self.b_del.clicked.connect(lambda: (self.hide(), self.delete.emit(self.index)))
        b_x = QPushButton("")
        b_x.setObjectName("plain")
        b_x.setToolTip("Zostaw oba")
        set_icon(b_x, "xmark", "text2", 14)
        b_x.setFixedWidth(34)
        b_x.clicked.connect(self.hide)
        h.addWidget(self.text, 1)
        h.addWidget(self.b_del)
        h.addWidget(b_x)
        self.hide()

    def offer(self, a: int, b: int):
        self.index = b
        self.text.setText(f"Slajdy {a} i {b} to prawie to samo.")
        self.b_del.setText(f"Usuń {b}")
        self.show()


def near_duplicate(path_a: str, path_b: str, text_a: str, text_b: str) -> bool:
    """Luźniejsze niż automatyczne łączenie: podobny obraz albo prawie ten sam tekst → zapytaj użytkownika."""
    try:
        import cv2
        import numpy as np
        from ..slides import _jaccard, dhash, hash_dist, text_tokens

        def load(p):
            data = np.fromfile(p, dtype=np.uint8)
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
        a, b = load(path_a), load(path_b)
        if a is None or b is None:
            return False
        d = hash_dist(dhash(a), dhash(b))
        ta, tb = text_tokens(text_a), text_tokens(text_b)
        if len(ta) >= 4 and len(tb) >= 4:
            j = _jaccard(ta, tb)
            return j >= 0.75 or (j >= 0.5 and d <= 0.15)
        return d <= 0.10
    except Exception:  # noqa: BLE001
        return False
