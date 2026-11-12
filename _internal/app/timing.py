"""Pomiar czasu kolejnych kroków (do logu) – lekki moduł bez zależności, do użycia także w wątku UI."""
from __future__ import annotations

import logging
import time

log = logging.getLogger("czasy")


class StepTimer:
    """Czasy kolejnych kroków do logu: „Start nagrywania: meta.json 3 ms, engine_for 5 ms, … (razem 120 ms)”."""

    def __init__(self, title: str):
        self.title = title
        self.t0 = self.last = time.perf_counter()
        self.parts: list[str] = []

    def step(self, name: str) -> None:
        now = time.perf_counter()
        self.parts.append(f"{name} {1000 * (now - self.last):.0f} ms")
        self.last = now

    def done(self) -> float:
        total = time.perf_counter() - self.t0
        log.info("%s: %s (razem %.0f ms)", self.title, ", ".join(self.parts), 1000 * total)
        return total
