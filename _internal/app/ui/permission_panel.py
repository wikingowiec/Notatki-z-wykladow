"""Zgody macOS (mikrofon, dźwięk aplikacji, nagrywanie ekranu) – wyjaśnienie po polsku i przyciski
„Zezwól” / „Otwórz Ustawienia systemowe” / „Uruchom ponownie”.
Nowe w wersji 2.2.0.

Dwa tryby: na ekranie nagrywania (show_granted=False) widać tylko brakujące zgody potrzebne do wybranego
rodzaju notatki; w Ustawieniach (show_granted=True) – wszystkie trzy ze stanem. Stan odświeża się co 1,5 s,
gdy panel jest widoczny – po powrocie z Ustawień systemowych nic nie trzeba klikać."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from .. import mac_permissions as mp
from .controls import StatusDot, hbox, label, show_if

STATE_TEXT = {mp.GRANTED: "Zgoda udzielona", mp.DENIED: "Brak zgody", mp.UNKNOWN: "macOS jeszcze nie pytał"}
STATE_DOT = {mp.GRANTED: "green", mp.DENIED: "red", mp.UNKNOWN: "orange"}


class _PermRow(QFrame):
    def __init__(self, kind: str, card: bool):
        super().__init__()
        self.kind = kind
        if card:
            self.setObjectName("banner")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*((14, 10, 12, 10) if card else (16, 10, 14, 10)))
        lay.setSpacing(6)
        self.dot = StatusDot("gray")
        self.title = label(mp.TITLE[kind], "headline")
        self.state = label("", "footnote")
        lay.addWidget(hbox(self.dot, self.title, "stretch", self.state, spacing=8))
        self.text = label("", "footnote", wrap=True)
        lay.addWidget(self.text)
        self.btn_ask = QPushButton("Zezwól…")
        self.btn_ask.setObjectName("primary")
        self.btn_settings = QPushButton("Otwórz Ustawienia systemowe")
        self.btn_restart = QPushButton("Uruchom ponownie")
        self.btn_restart.setObjectName("plain")
        self.btn_restart.setToolTip("macOS włącza nagrywanie ekranu dopiero po ponownym uruchomieniu aplikacji")
        self.buttons = hbox(self.btn_ask, self.btn_settings, self.btn_restart, "stretch", spacing=6)
        lay.addWidget(self.buttons)

    def set_state(self, st: str):
        self.dot.set(STATE_DOT[st])
        self.state.setText(STATE_TEXT[st])
        if st == mp.GRANTED:
            self.text.setText(mp.WHY[self.kind])
        elif st == mp.DENIED and self.kind != mp.SCREEN:
            self.text.setText(mp.WHY[self.kind] + "\n" + mp.WHERE[self.kind])
        elif self.kind == mp.SCREEN:
            self.text.setText(mp.WHY[self.kind] + " Kliknij „Zezwól…”, a jeśli macOS nie zapyta – "
                              + mp.WHERE[self.kind][0].lower() + mp.WHERE[self.kind][1:])
        else:
            self.text.setText(mp.WHY[self.kind] + " macOS zapyta o zgodę przy pierwszym nagrywaniu – "
                              "możesz zezwolić już teraz.")
        # odmowy macOS nie pyta drugi raz – zostają Ustawienia (ekran: prośba rejestruje Wykłady na liście)
        show_if(self.btn_ask, st == mp.UNKNOWN or (self.kind == mp.SCREEN and st != mp.GRANTED))
        show_if(self.btn_settings, st != mp.GRANTED)
        show_if(self.btn_restart, self.kind == mp.SCREEN and st != mp.GRANTED)
        show_if(self.buttons, st != mp.GRANTED)


class PermissionPanel(QWidget):
    changed = Signal()                  # któraś zgoda zmieniła stan (np. odśwież listę okien)
    restart_requested = Signal()

    def __init__(self, show_granted: bool = False, parent=None):
        super().__init__(parent)
        self.show_granted = show_granted
        self.needed: list[str] = [mp.MIC, mp.AUDIO, mp.SCREEN] if show_granted else []
        self._states: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.rows: dict[str, _PermRow] = {}
        for kind in (mp.AUDIO, mp.MIC, mp.SCREEN):
            row = _PermRow(kind, card=not show_granted)
            row.btn_ask.clicked.connect(lambda _c=False, k=kind: self._ask(k))
            row.btn_settings.clicked.connect(lambda _c=False, k=kind: self._settings(k))
            row.btn_restart.clicked.connect(self.restart_requested.emit)
            self.rows[kind] = row
            lay.addWidget(row)
            show_if(row, False)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def set_needed(self, kinds: list[str]):
        self.needed = list(kinds)
        self.refresh()

    def refresh(self):
        changed = any_row = False
        for kind, row in self.rows.items():
            st = mp.status(kind)
            if self._states.get(kind) != st:
                changed = changed or kind in self._states
                self._states[kind] = st
            row.set_state(st)
            on = kind in self.needed and (self.show_granted or st != mp.GRANTED)
            show_if(row, on)
            any_row = any_row or on
        show_if(self, any_row)
        if changed:
            self.changed.emit()

    def missing(self) -> list[str]:
        return [k for k in self.needed if mp.status(k) != mp.GRANTED]

    def _ask(self, kind: str):
        mp.request(kind)
        QTimer.singleShot(400, self.refresh)

    def _settings(self, kind: str):
        if kind == mp.SCREEN:
            mp.request(kind)            # dopisuje Wykłady do listy w Ustawieniach (pierwszy raz: prośba systemu)
        mp.open_settings(kind)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()
