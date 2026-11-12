"""Nagrywanie z opóźnieniem (nowe w 2.3): chwila startu, teksty odliczania i blokada usypiania komputera. Bez Qt.

Plan oczekiwania jest trzymany tylko w pamięci (RecordTab._plan) – nic nie trafia do pliku. Po zamknięciu albo
restarcie aplikacji plan znika i to jest zamierzone: nagrywanie nie ruszy „samo z siebie” po ponownym uruchomieniu.

Chwila startu to zwykła data i godzina z zegara ściennego (datetime, czas lokalny). Interfejs porównuje ją z
datetime.now() co sekundę, więc zmiana czasu (letni/zimowy) i wybudzenie komputera po uśpieniu liczą się poprawnie –
nie ma jednego długiego odliczania, które po uśpieniu by się rozjechało."""
from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional

from .i18n import tr

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

PREPARE_S = 120          # ok. 2 min przed startem: drugie sprawdzenie i rozgrzanie modeli
LATE_OK_S = 15 * 60      # komputer spał: do 15 min spóźnienia start od razu, później pytanie
LATE_NOTE_S = 60         # od minuty spóźnienia notka w transkrypcji „start spóźniony o X min”


# ---------------------------------------------------------------------------------------------- czas
def next_quarter(now: Optional[datetime] = None) -> datetime:
    """Najbliższy pełny kwadrans po `now` (10:07 → 10:15, 10:15:00 → 10:30)."""
    now = now or datetime.now()
    base = now.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=(now.minute // 15 + 1) * 15)


def resolve(hour: int, minute: int, now: Optional[datetime] = None) -> datetime:
    """Godzina z pola → konkretna chwila. Godzina, która już minęła (albo właśnie trwa), oznacza jutro."""
    now = now or datetime.now()
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at <= now:
        at += timedelta(days=1)
    return at


def clock(at: datetime) -> str:
    """„8:15”, „10:15”."""
    return f"{at.hour}:{at.minute:02d}"


def when_text(at: datetime, now: Optional[datetime] = None) -> str:
    """„o 10:15” (dziś) / „jutro o 8:15”."""
    now = now or datetime.now()
    if at.date() == now.date():
        return tr("o {time}", time=clock(at))
    if at.date() == (now + timedelta(days=1)).date():
        return tr("jutro o {time}", time=clock(at))
    from .i18n import date_short
    try:
        day = date_short(at)
    except Exception:  # noqa: BLE001
        day = at.strftime("%d.%m")
    return tr("{day} o {time}", day=day, time=clock(at))


def short_when(at: datetime, now: Optional[datetime] = None) -> str:
    """Do paska bocznego: „10:15” albo „jutro 8:15”."""
    now = now or datetime.now()
    return clock(at) if at.date() == now.date() else tr("jutro {time}", time=clock(at))


def left_text(sec: float) -> str:
    """Krótki czas do startu: „45 s”, „10 min”, „2 godz. 5 min”."""
    s = max(0, int(math.ceil(sec)))
    if s < 60:
        return tr("{n} s", n=s)
    mins = max(1, int(round(s / 60)))          # 10 min 5 s → „10 min”, 9 min 40 s → „10 min”
    if mins < 60:
        return tr("{n} min", n=mins)
    h, m = divmod(mins, 60)
    return tr("{h} godz. {m} min", h=h, m=m) if m else tr("{h} godz.", h=h)


def countdown_text(sec: float) -> str:
    """Duży napis na ekranie oczekiwania. W ostatniej minucie sekundy (odświeżane co sekundę)."""
    return tr("Nagrywanie rozpocznie się za {left}", left=left_text(sec))


def late_minutes(sec: float) -> int:
    return max(1, int(round(sec / 60)))


# ---------------------------------------------------------------------------------------------- uśpienie
class KeepAwake:
    """Komputer nie zaśnie, dopóki ktoś trzyma blokadę (hold/release z nazwą, np. „plan”). Ekran może się wygasić.

    Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED). Flaga należy do wątku, który ją ustawił –
    hold/release wołać zawsze z wątku interfejsu (żyje tak długo jak aplikacja).
    Mac: `caffeinate -i -w <pid>` – kończy się sam, gdy aplikacja się zamknie albo padnie."""
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001

    def __init__(self):
        self._holders: set[str] = set()
        self._proc: Optional[subprocess.Popen] = None

    @property
    def active(self) -> bool:
        return bool(self._holders)

    def hold(self, who: str) -> None:
        first = not self._holders
        self._holders.add(who)
        if first:
            self._on()

    def release(self, who: str) -> None:
        if who not in self._holders:
            return
        self._holders.discard(who)
        if not self._holders:
            self._off()

    def _on(self) -> None:
        try:
            if IS_WIN:
                import ctypes
                ok = ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED)
                log.info("Blokada uśpienia włączona (%s)", "OK" if ok else "błąd")
            elif IS_MAC:
                self._proc = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log.info("Blokada uśpienia włączona (caffeinate %s)", self._proc.pid)
        except Exception:  # noqa: BLE001 – bez blokady plan dalej działa (po wybudzeniu start się nadrobi)
            log.exception("blokada uśpienia")

    def _off(self) -> None:
        try:
            if IS_WIN:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
            elif self._proc is not None:
                self._proc.terminate()
                try:
                    self._proc.wait(2)
                except Exception:  # noqa: BLE001
                    self._proc.kill()
            log.info("Blokada uśpienia wyłączona")
        except Exception:  # noqa: BLE001
            log.exception("blokada uśpienia – wyłączenie")
        self._proc = None


_awake: Optional[KeepAwake] = None


def awake() -> KeepAwake:
    global _awake
    if _awake is None:
        _awake = KeepAwake()
    return _awake
