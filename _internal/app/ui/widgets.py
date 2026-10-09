"""Wspólne elementy interfejsu: zadania w tle, praca asynchroniczna, wybór obszaru slajdu."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLayout, QSlider, QVBoxLayout

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

    def set_pixmap(self, pix: QPixmap) -> None:
        """Nowy obraz (np. inna klatka filmu) – zaznaczenie zostaje w tym samym miejscu (w ułamkach)."""
        roi = self.roi()
        self.pix = pix
        self.setPixmap(pix)
        self.setFixedSize(pix.size())
        W, H = pix.width(), pix.height()
        self.rect_sel = QRect(int(roi[0] * W), int(roi[1] * H), int(roi[2] * W), int(roi[3] * H)) if roi else QRect()
        self.update()

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
        from .theme import T as _T
        p.setPen(QPen(QColor(_T().accent), 2))
        p.drawRect(r)
        p.end()

    def roi(self):
        r = self.rect_sel
        if r.isNull() or r.width() < 10 or r.height() < 10:
            return None
        W, H = self.pix.width(), self.pix.height()
        return (r.x() / W, r.y() / H, r.width() / W, r.height() / H)


def _fit_size(parent, max_w: int, max_h: int) -> tuple[int, int]:
    """Największy podgląd, który zmieści się na ekranie razem z opisem i przyciskami (małe laptopy: 768 px)."""
    from PySide6.QtGui import QGuiApplication
    scr = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
    if scr is None:
        return max_w, max_h
    g = scr.availableGeometry()
    return max(320, min(max_w, g.width() - 80)), max(200, min(max_h, g.height() - 300))


class RoiDialog(QDialog):
    """Zaznacz myszką prostokąt, w którym jest prezentacja (np. bez kamerki prowadzącego i czatu)."""

    def __init__(self, img: np.ndarray, roi=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zaznacz obszar slajdu")
        pix = bgr_to_qpixmap(img)
        pix = pix.scaled(*_fit_size(parent, 1150, 680), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.canvas = _RoiCanvas(pix, roi)
        info = QLabel("Przeciągnij myszką prostokąt wokół slajdu. Zmiany poza nim (kamerka, czat, kursor) nie będą "
                      "traktowane jako nowy slajd.")
        info.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Gotowe")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
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


def _fmt_t(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def ask_video_roi(parent, path: str, roi=None, title: str = "") -> tuple[bool, Optional[tuple]]:
    """Krok „Zaznacz obszar slajdu” dla pliku wideo. Zwraca (zatwierdzono, obszar lub None = cały obraz).
    Plik bez obrazu (samo audio) – od razu (True, None)."""
    from pathlib import Path
    from ..jobs import VIDEO_EXT
    from ..slides import video_duration
    if Path(path).suffix.lower() not in VIDEO_EXT:
        return True, None
    dur = video_duration(path)
    if dur is None:
        return True, None
    dlg = VideoRoiDialog(path, dur, roi, parent, title)
    if not dlg.exec():
        return False, roi
    return True, dlg.result_roi()


class VideoRoiDialog(QDialog):
    """Obszar slajdu w pliku wideo: klatka z wybranego momentu (suwak – początek bywa czarny) + zaznaczenie."""
    MAX_W, MAX_H = 1100, 620

    def __init__(self, path: str, duration: float, roi=None, parent=None, title: str = ""):
        super().__init__(parent)
        from pathlib import Path
        self.setWindowTitle(title or "Zaznacz obszar slajdu")
        self.path = path
        self.duration = max(0.0, float(duration or 0))
        self.max_w, self.max_h = _fit_size(parent, self.MAX_W, self.MAX_H)
        blank = QPixmap(min(self.max_w, int(self.max_h * 16 / 9)), min(self.max_h, int(self.max_w * 9 / 16)))
        from .theme import T as _T
        blank.fill(QColor(_T().surface2))
        self.canvas = _RoiCanvas(blank, roi)
        info = QLabel(f"<b>{Path(path).name}</b><br>Przeciągnij myszką prostokąt wokół slajdu – zmiany poza nim "
                      "(kamerka prowadzącego, czat) nie będą traktowane jako nowy slajd. Jeśli kadr jest czarny "
                      "albo nie widać slajdu, przesuń suwak.")
        info.setWordWrap(True)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(1, int(self.duration)))
        self.slider.setValue(int(min(self.duration * 0.1, 120)))   # początek bywa czarny / plansza tytułowa
        self.slider.setEnabled(self.duration > 1)
        self.time_lbl = QLabel()
        self.time_lbl.setObjectName("footnote")
        self.time_lbl.setMinimumWidth(110)
        self.state_lbl = QLabel("")
        self.state_lbl.setObjectName("footnote")
        self._timer = QTimer(self, singleShot=True, interval=180)
        self._timer.timeout.connect(self._load)
        self.slider.valueChanged.connect(self._slider_moved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Gotowe")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        whole = buttons.addButton("Cały obraz", QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        whole.clicked.connect(self._whole)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Moment filmu:"))
        row.addWidget(self.slider, 1)
        row.addWidget(self.time_lbl)
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)   # adjustSize() przycina do 2/3 ekranu
        lay.setSpacing(10)
        lay.addWidget(info)
        lay.addWidget(self.canvas, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(row)
        lay.addWidget(self.state_lbl)
        lay.addWidget(buttons)
        self._req = 0
        self._update_time()
        self._load(first=True)

    def _update_time(self):
        self.time_lbl.setText(f"{_fmt_t(self.slider.value())} / {_fmt_t(self.duration)}")

    def _slider_moved(self, _v):
        self._update_time()
        self._timer.start()

    def _load(self, first: bool = False):
        from ..slides import video_frame_at
        self._req += 1
        req, path, t, dur = self._req, self.path, float(self.slider.value()), self.duration
        self.state_lbl.setText("Wczytywanie klatki…")

        def work():
            img = video_frame_at(path, t)
            if first:          # pierwsze otwarcie: czarny kadr / plansza bez treści – spróbuj dalej w filmie
                for frac in (0.25, 0.5):
                    if img is not None and float(img.std()) >= 8.0:
                        break
                    t2 = dur * frac
                    if t2 > t:
                        img2 = video_frame_at(path, t2)
                        if img2 is not None:
                            img, t_used[0] = img2, t2
            return img

        t_used = [t]

        def done(img):
            if req != self._req:
                return
            try:
                if t_used[0] != t:
                    self.slider.blockSignals(True)
                    self.slider.setValue(int(t_used[0]))
                    self.slider.blockSignals(False)
                    self._update_time()
                if img is None:
                    self.state_lbl.setText("Nie udało się odczytać klatki w tym miejscu – przesuń suwak.")
                    return
                self.state_lbl.setText("")
                pix = bgr_to_qpixmap(img).scaled(self.max_w, self.max_h, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
                self.canvas.set_pixmap(pix)
            except RuntimeError:          # okno już zamknięte
                pass

        def fail(e):
            if req == self._req:
                try:
                    self.state_lbl.setText(f"Nie udało się odczytać filmu: {e}")
                except RuntimeError:
                    pass
        run_async(work, done, fail)

    def _whole(self):
        self.canvas.rect_sel = QRect()
        self.canvas.update()
        self.accept()

    def result_roi(self):
        return self.canvas.roi()


