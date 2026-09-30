"""Slajdy w interfejsie: miniatury z „×” (usuń) i podglądem po kliknięciu, duży podgląd, tekst wszystkich slajdów."""
from __future__ import annotations

import html
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..storage import fmt_time
from .controls import show_if, label, set_icon
from .reader import Reader
from .theme import T, qcolor

INDEX = Qt.ItemDataRole.UserRole
PATH = Qt.ItemDataRole.UserRole + 1
TIME = Qt.ItemDataRole.UserRole + 2
TEXT = Qt.ItemDataRole.UserRole + 3
PIX = Qt.ItemDataRole.UserRole + 4


@dataclass
class SlideInfo:
    index: int
    path: str
    t: float
    text: str = ""

    @property
    def caption(self) -> str:
        return f"Slajd {self.index} · {fmt_time(self.t)}"


# ---------------------------------------------------------------------------
class _ThumbDelegate(QStyledItemDelegate):
    def __init__(self, view: "SlideThumbs"):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        s = self.view.thumb
        return QSize(s.width() + 16, s.height() + 38)

    def _img_rect(self, r) -> QRectF:
        s = self.view.thumb
        return QRectF(r.left() + 8, r.top() + 6, s.width(), s.height())

    def x_rect(self, r) -> QRectF:
        ir = self._img_rect(r)
        return QRectF(ir.right() - 30, ir.top() + 6, 24, 24)

    def paint(self, p: QPainter, option, index):
        t = T()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect
        ir = self._img_rect(r)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(ir, 10, 10)
        pm = index.data(PIX)
        p.fillPath(path, qcolor(t.hover))
        if isinstance(pm, QPixmap) and not pm.isNull():
            p.setClipPath(path)
            dpr = pm.devicePixelRatio() or 1.0
            w, h = pm.width() / dpr, pm.height() / dpr
            sc = min(ir.width() / w, ir.height() / h)
            tr = QRectF(0, 0, w * sc, h * sc)
            tr.moveCenter(ir.center())
            p.drawPixmap(tr, pm, QRectF(0, 0, pm.width(), pm.height()))
            p.setClipping(False)
        p.setPen(QPen(qcolor(t.accent if hover else t.separator), 2 if hover else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(ir.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        if self.view.deletable:
            xr = self.x_rect(r)
            over_x = hover and xr.contains(self.view.viewport().mapFromGlobal(self.view.cursor().pos()).toPointF())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170) if not over_x else qcolor(t.red))
            p.drawEllipse(xr)
            pen = QPen(QColor("white"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            c = xr.center()
            d = 5
            p.drawLine(c.x() - d, c.y() - d, c.x() + d, c.y() + d)
            p.drawLine(c.x() + d, c.y() - d, c.x() - d, c.y() + d)
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() - 0.8)
        p.setFont(f)
        p.setPen(qcolor(t.text2))
        t_ = index.data(TIME)
        cap = f"Slajd {index.data(INDEX)}" + (f" · {fmt_time(t_)}" if t_ is not None and self.view.show_time else "")
        p.drawText(QRectF(ir.left(), ir.bottom() + 4, ir.width(), 22), Qt.AlignmentFlag.AlignHCenter, cap)
        p.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self.view.deletable and self.x_rect(option.rect).contains(event.position()):
                self.view.delete_requested.emit(int(index.data(INDEX)))
            else:
                self.view.open_requested.emit(int(index.data(INDEX)))
            return True
        return False


class SlideThumbs(QListWidget):
    """Siatka (albo pasek) miniatur slajdów. Kliknięcie → podgląd, „×” w rogu → usuń."""
    open_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, thumb: QSize = QSize(232, 130), deletable: bool = True, show_time: bool = True):
        super().__init__()
        self.setObjectName("thumbs")
        self.thumb = thumb
        self.deletable = deletable
        self.show_time = show_time
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(_ThumbDelegate(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_thumb_size(self, s: QSize):
        self.thumb = s
        self.doItemsLayout()

    def _pixmap(self, path: str) -> QPixmap:
        pm = QPixmap(path)
        if pm.isNull():
            return pm
        dpr = self.devicePixelRatioF() or 1.0
        return pm.scaled(int(self.thumb.width() * dpr * 1.2), int(self.thumb.height() * dpr * 1.2),
                         Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def add_slide(self, index: int, path: str, t: float | None, text: str = "", pixmap: QPixmap | None = None):
        it = QListWidgetItem()
        it.setData(INDEX, index)
        it.setData(PATH, path)
        it.setData(TIME, t)
        it.setData(TEXT, text)
        it.setData(PIX, pixmap if pixmap is not None else self._pixmap(path))
        it.setToolTip((text or "")[:500] or "Kliknij, aby powiększyć")
        self.addItem(it)
        return it

    def find(self, index: int):
        for i in range(self.count()):
            if self.item(i).data(INDEX) == index:
                return self.item(i)
        return None

    def update_slide(self, index: int, path: str = "", text: str | None = None):
        it = self.find(index)
        if it is None:
            return
        if path:
            it.setData(PATH, path)
            it.setData(PIX, self._pixmap(path))
        if text is not None:
            it.setData(TEXT, text)
            it.setToolTip(text[:500])

    def remove_slide(self, index: int):
        it = self.find(index)
        if it is not None:
            self.takeItem(self.row(it))

    def infos(self) -> list[SlideInfo]:
        return [SlideInfo(int(self.item(i).data(INDEX)), self.item(i).data(PATH) or "",
                          float(self.item(i).data(TIME) or 0), self.item(i).data(TEXT) or "")
                for i in range(self.count())]

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        self.viewport().update()


# ---------------------------------------------------------------------------
class SlidePreview(QDialog):
    """Powiększony slajd: strzałki / ← → przewijają, Delete usuwa, Esc zamyka."""

    def __init__(self, slides: list[SlideInfo], pos: int, parent=None, on_delete=None, extra_buttons=()):
        super().__init__(parent)
        self.setWindowTitle("Podgląd slajdu")
        self.slides = slides
        self.pos = max(0, min(pos, len(slides) - 1))
        self.on_delete = on_delete
        self.setModal(True)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setMinimumSize(400, 240)
        self.cap = label("", "headline")
        self.txt = label("", "footnote", wrap=True)
        self.txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.txt.setMaximumHeight(90)
        b_prev = QPushButton()
        set_icon(b_prev, "chevron-left", "text2", 18)
        b_prev.setToolTip("Poprzedni (←)")
        b_prev.clicked.connect(lambda: self.go(-1))
        b_next = QPushButton()
        set_icon(b_next, "chevron-right", "text2", 18)
        b_next.setToolTip("Następny (→)")
        b_next.clicked.connect(lambda: self.go(1))
        row = QHBoxLayout()
        row.addWidget(b_prev)
        row.addWidget(b_next)
        row.addSpacing(10)
        row.addWidget(self.cap, 1)
        for text, fn in extra_buttons:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f(self.current()))
            row.addWidget(b)
        if on_delete:
            self.b_del = QPushButton("Usuń slajd")
            self.b_del.setObjectName("destructive")
            set_icon(self.b_del, "trash", "red", 15)
            self.b_del.clicked.connect(self._delete)
            row.addWidget(self.b_del)
        b_close = QPushButton("Zamknij")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(self.img, 1)
        v.addWidget(self.txt)
        v.addLayout(row)
        for key, fn in ((Qt.Key.Key_Left, lambda: self.go(-1)), (Qt.Key.Key_Right, lambda: self.go(1)),
                        (Qt.Key.Key_Delete, self._delete)):
            QShortcut(QKeySequence(key), self, activated=fn)
        scr = (parent.screen() if parent else QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(int(scr.width() * 0.78), int(scr.height() * 0.82))
        self._show()

    def current(self) -> SlideInfo | None:
        return self.slides[self.pos] if self.slides else None

    def go(self, d: int):
        if self.slides:
            self.pos = (self.pos + d) % len(self.slides)
            self._show()

    def _show(self):
        s = self.current()
        if s is None:
            self.accept()
            return
        self.cap.setText(s.caption + f"   ({self.pos + 1} z {len(self.slides)})")
        self.txt.setText(s.text or "")
        show_if(self.txt, s.text)
        self._pm = QPixmap(s.path)
        self._fit()

    def _fit(self):
        if getattr(self, "_pm", None) is None or self._pm.isNull():
            self.img.setText("Nie można wczytać obrazu.")
            return
        dpr = self.devicePixelRatioF() or 1.0
        size = self.img.size() * dpr
        pm = self._pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.img.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _delete(self):
        s = self.current()
        if s is None or not self.on_delete:
            return
        if self.on_delete(s.index) is False:
            return
        del self.slides[self.pos]
        if not self.slides:
            self.accept()
            return
        self.pos = min(self.pos, len(self.slides) - 1)
        self._show()


# ---------------------------------------------------------------------------
def slides_plain_text(slides: list[SlideInfo]) -> str:
    out = []
    for s in slides:
        if s.text.strip():
            out.append(f"{s.caption}\n{s.text.strip()}")
    return "\n\n".join(out)


def slides_text_html(slides: list[SlideInfo], empty: str = "") -> str:
    t = T()
    parts = []
    for s in slides:
        if not s.text.strip():
            continue
        body = "<br>".join(html.escape(line) for line in s.text.strip().splitlines())
        top = 16 if parts else 0
        parts.append(f"<p style='margin:{top}px 0 4px 0; color:{t.accent}; font-weight:600'>{html.escape(s.caption)}</p>"
                     f"<p style='margin:0 0 6px 0; line-height:150%'>{body}</p>")
    if not parts:
        parts.append(f"<p style='color:{t.text3}'>{html.escape(empty or 'Tekst slajdów pojawi się tutaj, gdy zostanie odczytany.')}</p>")
    return f"<body style='color:{t.text}; line-height:155%'>{''.join(parts)}</body>"


class SlideTextPanel(QWidget):
    """Cały tekst ze slajdów w jednym miejscu – z przyciskiem „Kopiuj wszystko”."""

    def __init__(self, title: str = "Tekst slajdów"):
        super().__init__()
        self.slides: list[SlideInfo] = []
        self.head = label(title, "headline")
        self.b_copy = QPushButton("Kopiuj wszystko")
        self.b_copy.setObjectName("plain")
        set_icon(self.b_copy, "doc", "accent", 15)
        self.b_copy.clicked.connect(self.copy)
        self.view = Reader(max_width=760, pad=20)
        h = QHBoxLayout()
        h.setContentsMargins(2, 0, 0, 0)
        h.addWidget(self.head, 1)
        h.addWidget(self.b_copy)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addLayout(h)
        v.addWidget(self.view, 1)
        self.set_slides([])

    def set_slides(self, slides: list[SlideInfo]):
        self.slides = list(slides)
        sb = self.view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20
        self.view.setHtml(slides_text_html(self.slides))
        if at_bottom:
            sb.setValue(sb.maximum())
        self.b_copy.setEnabled(any(s.text.strip() for s in self.slides))

    def copy(self):
        QApplication.clipboard().setText(slides_plain_text(self.slides))
        self.b_copy.setText("Skopiowano ✓")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.b_copy.setText("Kopiuj wszystko"))
