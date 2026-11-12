"""Zmiana źródeł w trakcie nagrywania: okno wyboru dźwięku (ta sama lista co przed nagraniem – szukanie,
wskaźniki poziomu) i okno wyboru ekranu/okna ze slajdami (podgląd + opcjonalnie obszar slajdu)."""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout)

from ..i18n import tr
from .controls import hbox, label, rounded_pixmap, set_icon, show_if
from .widgets import RoiDialog, bgr_to_qpixmap, run_async

log = logging.getLogger(__name__)


def _buttons(dlg: QDialog, ok_text: str) -> tuple[QDialogButtonBox, QPushButton]:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = bb.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setObjectName("primary")
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Anuluj"))
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb, ok


class AudioSwitchDialog(QDialog):
    """Wybór nowego źródła dźwięku. Bieżące źródło jest oznaczone jako „ostatnio używane”."""

    def __init__(self, current, parent=None):
        super().__init__(parent)
        from .audio_picker import AudioSourcePicker, _key
        self._key = _key
        self.current_info = current
        self.setWindowTitle(tr("Zmień źródło dźwięku"))
        self.setMinimumWidth(460)
        head = label(tr("Skąd nagrywać dźwięk?"), "title3")
        info = label(tr("Nagrywanie trwa dalej – nowe źródło włączy się, zanim wyłączy się obecne, więc nic nie "
                        "przepadnie. W transkrypcji pojawi się notka o zmianie."), "footnote", wrap=True)
        self.picker = AudioSourcePicker()
        show_if(self.picker.btn_preview, False)       # odsłuch w trakcie wykładu nagrałby się z głośników
        if current is not None:
            self.picker.set_last_used({"kind": current.kind, "exe": current.exe, "device": current.device_index})
        self.picker.current_changed.connect(self._update_ok)
        bb, self.ok = _buttons(self, tr("Przełącz"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(head)
        lay.addWidget(info)
        lay.addWidget(self.picker)
        lay.addStretch(1)
        lay.addWidget(bb)
        self.ok.setEnabled(False)
        QTimer.singleShot(0, self.picker.refresh)

    def _update_ok(self):
        cur = self.picker.current()
        same = cur is not None and self.current_info is not None and self._key(cur) == self._key(self.current_info)
        self.ok.setEnabled(cur is not None and not same)
        self.ok.setToolTip(tr("To źródło już jest nagrywane.") if same else "")

    def result_info(self):
        return self.picker.current()


class VideoSwitchDialog(QDialog):
    """Wybór nowego ekranu albo okna ze slajdami, z podglądem i (opcjonalnie) zaznaczeniem obszaru slajdu."""

    def __init__(self, current, rois: dict, key_of, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Zmień ekran ze slajdami"))
        self.setMinimumWidth(520)
        self.rois = dict(rois)          # zapamiętane obszary (klucz źródła → roi)
        self.key_of = key_of
        self.current_info = current
        self.sources: list = []
        self._img: np.ndarray | None = None
        self._req = 0
        head = label(tr("Skąd brać slajdy?"), "title3")
        info = label(tr("Złapane slajdy, ich numeracja i czas zostają – kolejne slajdy będą wykrywane w nowym "
                        "źródle."), "footnote", wrap=True)
        self.combo = QComboBox()
        self.combo.setMinimumContentsLength(30)
        self.combo.currentIndexChanged.connect(self._changed)
        self.btn_refresh = QPushButton("")
        self.btn_refresh.setToolTip(tr("Odśwież listę okien"))
        set_icon(self.btn_refresh, "refresh", "text2", 16)
        self.btn_refresh.setFixedWidth(40)
        self.btn_refresh.clicked.connect(self.refresh)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.btn_roi = QPushButton(tr("Zaznacz obszar slajdu…"))
        set_icon(self.btn_roi, "crop", "text2", 16)
        self.btn_roi.clicked.connect(self._pick_roi)
        self.btn_roi_clear = QPushButton(tr("Cały obraz"))
        self.btn_roi_clear.setObjectName("plain")
        self.btn_roi_clear.clicked.connect(self._clear_roi)
        self.roi_label = label("", "footnote", wrap=True)
        bb, self.ok = _buttons(self, tr("Przełącz"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(head)
        lay.addWidget(info)
        lay.addWidget(hbox(self.combo, self.btn_refresh, spacing=4))
        lay.addWidget(self.preview, 1)
        lay.addWidget(hbox(self.btn_roi, self.btn_roi_clear, "stretch"))
        lay.addWidget(self.roi_label)
        lay.addWidget(bb)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        from ..screen_capture import list_monitors, list_windows
        prev = self.current()
        self.sources = list_monitors() + list_windows()
        want = prev or self.current_info
        idx = 0
        if want is not None:
            k = self.key_of(want)
            idx = next((i for i, s in enumerate(self.sources) if self.key_of(s) == k), 0)
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in self.sources:
            self.combo.addItem(s.label.replace("🖥 ", "").replace("🪟 ", tr("Okno: ")))
        self.combo.setCurrentIndex(idx if self.sources else -1)
        self.combo.blockSignals(False)
        self._changed()

    def current(self):
        i = self.combo.currentIndex()
        return self.sources[i] if 0 <= i < len(self.sources) else None

    def _is_current_source(self, info) -> bool:
        return info is not None and self.current_info is not None and self.key_of(info) == self.key_of(self.current_info)

    def _changed(self, *_):
        info = self.current()
        self._img = None
        self.preview.setText(tr("Wczytuję podgląd…") if info else tr("Nie ma żadnego ekranu ani okna."))
        self.ok.setEnabled(False)
        self._render()
        if info is None:
            return
        self._req += 1
        req = self._req
        from ..screen_capture import make_grabber

        def work():
            g = make_grabber(info)
            try:
                return (g.grab() if g else None), (getattr(g, "last_error", "") if g else "")
            finally:
                if g:
                    g.close()

        def done(res):
            if req != self._req:
                return
            self._img, err = res
            if self._img is None:
                self.preview.setText(tr("Nie udało się pobrać podglądu. ") + (err or ""))
            self._render()

        run_async(work, done, lambda e: req == self._req and self.preview.setText(
            tr("Nie udało się pobrać podglądu. ") + str(e)))

    def _render(self):
        info = self.current()
        roi = self.rois.get(self.key_of(info)) if info else None
        has = self._img is not None
        self.btn_roi.setEnabled(has)
        show_if(self.btn_roi_clear, bool(roi))
        same = self._is_current_source(info)
        self.ok.setEnabled(has and not same)
        self.ok.setToolTip(tr("Slajdy już są nagrywane z tego źródła – obszar zmienisz przyciskiem "
                              "„Zmień obszar slajdu”.") if same else "")
        self.roi_label.setText(tr("Slajdy już są nagrywane z tego źródła.") if same else
                               tr("Slajdy będą wykrywane tylko w zaznaczonym obszarze.") if roi else
                               tr("Wykrywanie obejmuje cały obraz. Jeśli obok slajdu jest kamerka lub czat, zaznacz sam slajd."))
        if not has:
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPen
        from .theme import T, qcolor
        dpr = self.devicePixelRatioF() or 1.0
        bw = max(320, min(720, self.width() - 40))
        bh = int(bw * 9 / 16)
        pix = bgr_to_qpixmap(self._img).scaled(int(bw * dpr), int(bh * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        if roi:
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            W, H = pix.width() / dpr, pix.height() / dpr
            r = QRectF(roi[0] * W, roi[1] * H, roi[2] * W, roi[3] * H)
            shade = QColor(0, 0, 0, 130)
            p.fillRect(QRectF(0, 0, W, r.top()), shade)
            p.fillRect(QRectF(0, r.bottom(), W, H - r.bottom()), shade)
            p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
            p.fillRect(QRectF(r.right(), r.top(), W - r.right(), r.height()), shade)
            p.setPen(QPen(qcolor(T().accent), 2.5))
            p.drawRoundedRect(r, 4, 4)
            p.end()
        self.preview.setPixmap(rounded_pixmap(pix, 10))

    def _pick_roi(self):
        info = self.current()
        if info is None or self._img is None:
            return
        key = self.key_of(info)
        dlg = RoiDialog(self._img, self.rois.get(key), self)
        if dlg.exec():
            roi = dlg.result_roi()
            if roi:
                self.rois[key] = tuple(roi)
            else:
                self.rois.pop(key, None)
            self._render()

    def _clear_roi(self):
        info = self.current()
        if info is not None:
            self.rois.pop(self.key_of(info), None)
            self._render()

    def result(self):
        """(źródło, obszar slajdu albo None)."""
        info = self.current()
        return info, (self.rois.get(self.key_of(info)) if info else None)
