"""Nagrywanie z opóźnieniem (2.3): pole godziny, okienko „Zmień godzinę”, środek ekranu oczekiwania
i powiadomienie systemowe. Logika planu (sprawdzenia, start o czasie) jest w RecordTab – tu tylko widżety."""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QTime, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton, QTimeEdit,
                               QVBoxLayout, QWidget)

from .. import schedule as sch
from ..i18n import tr
from .controls import label, set_icon, show_if
from .theme import T

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------- pole godziny
class TimePicker(QWidget):
    """QTimeEdit (GG:MM) + podpis „dziś, za 8 min” / „jutro o 8:15”. Podpis odświeża się sam, bo czas płynie."""
    changed = Signal()

    def __init__(self, hint_obj: str = "footnote", parent=None):
        super().__init__(parent)
        self.edit = QTimeEdit()
        self.edit.setDisplayFormat("HH:mm")
        self.edit.setAccessibleName(tr("Godzina startu nagrywania"))
        self.edit.setWrapping(True)
        self.edit.setMinimumWidth(88)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.timeChanged.connect(lambda _t: (self._update_hint(), self.changed.emit()))
        self.hint = label("", hint_obj)
        self._hint_ext = None            # podpis może stać gdzie indziej (np. pod przyciskiem startu)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.edit)
        lay.addWidget(self.hint, 1)
        self._t = QTimer(self)
        self._t.setInterval(15000)
        self._t.timeout.connect(self._update_hint)
        self.set_time(sch.next_quarter())

    def use_external_hint(self, lb: QLabel):
        self._hint_ext = lb
        self.hint.hide()
        self._update_hint()

    def set_time(self, at: datetime):
        self.edit.setTime(QTime(at.hour, at.minute))
        self._update_hint()

    def when(self) -> datetime:
        q = self.edit.time()
        return sch.resolve(q.hour(), q.minute())

    def hint_text(self) -> str:
        now = datetime.now()
        at = self.when()
        if at.date() != now.date():
            return sch.when_text(at, now)                     # „jutro o 8:15”
        return tr("dziś, za {left}", left=sch.left_text((at - now).total_seconds()))

    def _update_hint(self):
        (self._hint_ext or self.hint).setText(self.hint_text())

    def showEvent(self, e):
        super().showEvent(e)
        self._update_hint()
        self._t.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._t.stop()


class ChangeTimeDialog(QDialog):
    """„Zmień godzinę” na ekranie oczekiwania."""

    def __init__(self, at: datetime, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Zmień godzinę"))
        self.picker = TimePicker("secondary")
        self.picker.set_time(at)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("Nagrywanie rozpocznie się o godzinie:"), "headline"))
        v.addWidget(self.picker)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Zapisz"))
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Anuluj"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.picker.edit.setFocus()

    def when(self) -> datetime:
        return self.picker.when()


# ---------------------------------------------------------------------------------------------- ekran oczekiwania
class WaitPanel(QWidget):
    """Środek ekranu nagrywania w stanie „zaplanowane”: duże odliczanie, godzina i źródła, przyciski.
    Pytanie (spóźniony start po uśpieniu, brak aplikacji ze źródłem) pokazuje się w ramce pod spodem."""
    start_now = Signal()
    change_time = Signal()
    cancel = Signal()
    answered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.icon = QLabel()
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big = label("", "largeTitle", wrap=True)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setAccessibleName(tr("Czas do startu nagrywania"))
        try:                 # cyfry tabelaryczne – odliczanie sekund nie „skacze”
            from PySide6.QtGui import QFont
            f = self.big.font()
            f.setFeature(QFont.Tag("tnum"), 1)
            self.big.setFont(f)
        except Exception:  # noqa: BLE001
            pass
        self.sub = label("", "secondary", wrap=True)
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note = label("", "footnote", wrap=True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_now = QPushButton(tr("Zacznij teraz"))
        self.btn_now.setObjectName("primary")
        set_icon(self.btn_now, "record", "on_accent", 15)
        self.btn_now.clicked.connect(self.start_now.emit)
        self.btn_time = QPushButton(tr("Zmień godzinę"))
        set_icon(self.btn_time, "clock", "text", 15)
        self.btn_time.clicked.connect(self.change_time.emit)
        self.btn_cancel = QPushButton(tr("Anuluj"))
        self.btn_cancel.setObjectName("plain")
        self.btn_cancel.setToolTip(tr("Anuluj zaplanowane nagrywanie – nic nie zostanie nagrane"))
        self.btn_cancel.clicked.connect(self.cancel.emit)
        for b in (self.btn_now, self.btn_time, self.btn_cancel):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()
        btns.addWidget(self.btn_now)
        btns.addWidget(self.btn_time)
        btns.addWidget(self.btn_cancel)
        btns.addStretch()

        # pytanie: ramka z tekstem i przyciskami odpowiedzi
        self.ask_box = QFrame()
        self.ask_box.setObjectName("warnBanner")
        self.ask_box.setMaximumWidth(640)
        ab = QVBoxLayout(self.ask_box)
        ab.setContentsMargins(18, 14, 16, 14)
        ab.setSpacing(10)
        self.ask_title = label("", "headline", wrap=True)
        self.ask_text = label("", "", wrap=True)
        ab.addWidget(self.ask_title)
        ab.addWidget(self.ask_text)
        self.ask_btns = QHBoxLayout()
        self.ask_btns.setSpacing(8)
        ab.addLayout(self.ask_btns)
        self.ask_key = ""
        show_if(self.ask_box, False)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 24, 16, 24)
        v.setSpacing(10)
        v.addStretch(1)
        v.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(4)
        v.addWidget(self.big)
        v.addWidget(self.sub)
        v.addSpacing(2)
        v.addWidget(self.note)
        v.addSpacing(14)
        v.addLayout(btns)
        v.addSpacing(6)
        ask_row = QHBoxLayout()          # ramka do 640 px, wyśrodkowana (tekst się zawija, nie ucina)
        ask_row.addStretch(1)
        ask_row.addWidget(self.ask_box, 100)
        ask_row.addStretch(1)
        v.addLayout(ask_row)
        v.addStretch(2)
        from .theme import theme
        theme().changed.connect(self._paint_icon)
        self._paint_icon()

    def _paint_icon(self):
        from .theme import icon_pixmap
        self.icon.setPixmap(icon_pixmap("clock", T().accent, 40))

    def set_texts(self, big: str, sub: str, note: str = ""):
        if self.big.text() != big:
            self.big.setText(big)
        self.sub.setText(sub)
        self.note.setText(note)
        show_if(self.note, bool(note))

    def ask(self, key: str, title: str, text: str, answers: list[tuple[str, str, bool]]):
        """answers: [(klucz, napis, główny?)] – kliknięcie wysyła answered(klucz) i chowa pytanie."""
        self.ask_key = key
        self.ask_title.setText(title)
        self.ask_text.setText(text)
        show_if(self.ask_text, bool(text))
        while self.ask_btns.count():
            w = self.ask_btns.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.ask_btns.addStretch()
        for k, text_, primary in answers:
            b = QPushButton(text_)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(lambda _c=False, k=k: self._answer(k))
            self.ask_btns.addWidget(b)
        show_if(self.ask_box, True)
        # przyciski na górze dublowałyby odpowiedzi – zostaje tylko pytanie
        for b in (self.btn_now, self.btn_time, self.btn_cancel):
            show_if(b, False)

    def clear_ask(self):
        self.ask_key = ""
        show_if(self.ask_box, False)
        for b in (self.btn_now, self.btn_time, self.btn_cancel):
            show_if(b, True)

    def _answer(self, key: str):
        self.clear_ask()
        self.answered.emit(key)


# ---------------------------------------------------------------------------------------------- powiadomienie
_tray = None


def notify(title: str, text: str) -> None:
    """Powiadomienie systemowe (dymek Windows / Centrum powiadomień macOS) + mignięcie okna na pasku zadań.
    Ikona w zasobniku pojawia się tylko na czas powiadomienia."""
    global _tray
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        app = QApplication.instance()
        if app is None:
            return
        win = app.activeWindow() or next((w for w in app.topLevelWidgets() if w.isWindow() and w.isVisible()), None)
        if win is not None:
            QApplication.alert(win, 0)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if _tray is None:
            _tray = QSystemTrayIcon(app.windowIcon(), app)
        _tray.setToolTip(app.applicationDisplayName() or app.applicationName())
        _tray.show()
        _tray.showMessage(title, text, app.windowIcon(), 8000)
        QTimer.singleShot(20000, _tray.hide)
    except Exception:  # noqa: BLE001
        log.exception("powiadomienie")
