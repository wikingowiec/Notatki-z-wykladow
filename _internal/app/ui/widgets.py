"""Wspólne elementy interfejsu: zadania w tle, praca asynchroniczna, wybór obszaru slajdu."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

log = logging.getLogger(__name__)


def bgr_to_qpixmap(img: np.ndarray) -> QPixmap:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy()
    return QPixmap.fromImage(qimg)


# ---------------------------------------------------------------------------
# Praca w tle bez blokowania interfejsu
# ---------------------------------------------------------------------------
class _Bridge(QObject):
    done = Signal(object, object)   # (callback, wynik)


_bridge: Optional[_Bridge] = None
_pool: Optional[QThreadPool] = None


class _Task(QRunnable):
    def __init__(self, fn, cb, err_cb):
        super().__init__()
        self.fn, self.cb, self.err_cb = fn, cb, err_cb
        self.setAutoDelete(True)

    def run(self):
        try:
            res = self.fn()
        except Exception as e:  # noqa: BLE001
            log.exception("run_async")
            if self.err_cb:
                _bridge.done.emit(self.err_cb, e)
            return
        if self.cb:
            _bridge.done.emit(self.cb, res)


def run_async(fn: Callable, callback: Optional[Callable] = None, on_error: Optional[Callable] = None) -> None:
    """Wykonuje fn() w puli wątków, a callback(wynik) w wątku interfejsu."""
    global _bridge, _pool
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(lambda cb, res: cb(res), Qt.ConnectionType.QueuedConnection)
        _pool = QThreadPool()
        _pool.setMaxThreadCount(3)
    _pool.start(_Task(fn, callback, on_error))


# ---------------------------------------------------------------------------
class JobRunner(QObject):
    """Uruchamia jedno zadanie naraz w wątku w tle i raportuje postęp sygnałami."""
    progress = Signal(str, float)
    token = Signal(str)
    finished = Signal(bool, str, object)
    started = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.cancel = threading.Event()
        self.lecture = None
        self.name = ""

    def run(self, name: str, fn: Callable, lecture=None) -> bool:
        """fn(progress, cancel, token) – wykonywana w wątku."""
        if self.busy:
            return False
        self.busy = True
        self.name = name
        self.cancel = threading.Event()
        self.lecture = lecture
        self.started.emit(name, lecture)
        cancel = self.cancel

        def target():
            ok, msg = True, f"{name}: zakończono"
            try:
                fn(self.progress.emit, cancel, self.token.emit)
                if cancel.is_set():
                    ok, msg = False, f"{name}: anulowano"
            except Exception as e:  # noqa: BLE001
                if cancel.is_set():
                    ok, msg = False, f"{name}: anulowano"
                else:
                    log.exception(name)
                    ok, msg = False, f"{name}: {e}"
            finally:
                self.busy = False
            self.finished.emit(ok, msg, lecture)

        threading.Thread(target=target, name=f"job:{name}", daemon=True).start()
        return True


# ---------------------------------------------------------------------------
class _RoiCanvas(QLabel):
    def __init__(self, pix: QPixmap, roi=None):
        super().__init__()
        self.pix = pix
        self.setPixmap(pix)
        self.setFixedSize(pix.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._start: Optional[QPoint] = None
        self.rect_sel = QRect()
        if roi:
            x, y, w, h = roi
            W, H = pix.width(), pix.height()
            self.rect_sel = QRect(int(x * W), int(y * H), int(w * W), int(h * H))

    def mousePressEvent(self, e):
        self._start = e.position().toPoint()
        self.rect_sel = QRect(self._start, self._start)
        self.update()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self.rect_sel = QRect(self._start, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        self._start = None
        self.rect_sel = self.rect_sel.intersected(QRect(0, 0, self.pix.width(), self.pix.height()))
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rect_sel.isNull() or self.rect_sel.width() < 3:
            return
        p = QPainter(self)
        shade = QColor(0, 0, 0, 120)
        r = self.rect_sel
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, r.top(), shade)
        p.fillRect(0, r.bottom(), W, H - r.bottom(), shade)
        p.fillRect(0, r.top(), r.left(), r.height(), shade)
        p.fillRect(r.right(), r.top(), W - r.right(), r.height(), shade)
        p.setPen(QPen(QColor("#4f8cff"), 2))
        p.drawRect(r)
        p.end()

    def roi(self):
        r = self.rect_sel
        if r.isNull() or r.width() < 10 or r.height() < 10:
            return None
        W, H = self.pix.width(), self.pix.height()
        return (r.x() / W, r.y() / H, r.width() / W, r.height() / H)


class RoiDialog(QDialog):
    """Zaznacz myszką prostokąt, w którym jest prezentacja (np. bez kamerki prowadzącego i czatu)."""

    def __init__(self, img: np.ndarray, roi=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zaznacz obszar slajdu")
        pix = bgr_to_qpixmap(img)
        pix = pix.scaled(1150, 680, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.canvas = _RoiCanvas(pix, roi)
        info = QLabel("Przeciągnij myszką prostokąt wokół slajdu. Zmiany poza nim (kamerka, czat, kursor) nie będą "
                      "traktowane jako nowy slajd.")
        info.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        reset = buttons.addButton("Cały obraz", QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        reset.clicked.connect(self._reset)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(buttons)
        self._cleared = False

    def _reset(self):
        self.canvas.rect_sel = QRect()
        self.canvas.update()

    def result_roi(self):
        return self.canvas.roi()


