"""Dopasowanie punktów notatki do miejsc w nagraniu (do odsłuchiwania fragmentów).

Dla każdego punktu notatki szukamy w transkrypcji (w czasie danej sekcji) okien 3 kolejnych segmentów,
które zawierają najwięcej słów z tego punktu. Kilka odległych trafień = lista fragmentów do wyboru.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .qa import _stems

_H2 = re.compile(r"^##\s+")
_H1 = re.compile(r"^#\s+")
_TIME = re.compile(r"^\*\s*(\d[\d:]*)\s*[–-]\s*(\d[\d:]*)\s*\*")
_BULLET = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.+)$")
WIN = 3


def parse_time(s: str) -> float:
    parts = [int(x) for x in s.split(":")]
    t = 0
    for p in parts:
        t = t * 60 + p
    return float(t)


@dataclass
class Fragment:
    start: float
    end: float
    desc: str


class _Index:
    def __init__(self, segs: list[dict]):
        self.segs = segs
        self.win = []
        for i in range(len(segs)):
            w = segs[i:i + WIN]
            self.win.append((w[0]["start"], w[-1]["end"], set(_stems(" ".join(x["text"] for x in w)))))

    def find(self, text: str, lo: float, hi: float, max_frag: int = 4) -> list[Fragment]:
        q = set(_stems(text))
        if len(q) < 2:
            return []
        cands = []
        for i, (a, b, st) in enumerate(self.win):
            if b < lo or a > hi:
                continue
            hit = len(q & st)
            if hit < 2:
                continue
            score = hit / len(q)
            if score >= 0.45:
                cands.append((score, i))
        cands.sort(reverse=True)
        chosen: list[tuple[float, float, int]] = []
        for score, i in cands:
            a, b, _ = self.win[i]
            if any(not (b + 20 < x or a - 20 > y) for x, y, _ in chosen):
                continue
            chosen.append((a, b, i))
            if len(chosen) >= max_frag:
                break
        out = []
        for a, b, i in sorted(chosen):
            words = " ".join(x["text"] for x in self.segs[i:i + WIN]).split()
            desc = " ".join(words[:14]) + ("…" if len(words) > 14 else "")
            out.append(Fragment(max(0.0, a - 1.5), b + 1.0, desc))
        return out


def section_parts(segs: list[dict], lo: float, hi: float, slide_times: list[float]) -> list[Fragment]:
    """Cała sekcja podzielona na części (po slajdach albo co ~3 min) z krótkim opisem."""
    cuts = [lo] + [t for t in slide_times if lo + 20 < t < hi - 20] + [hi]
    if len(cuts) == 2 and hi - lo > 300:
        n = int((hi - lo) // 180) + 1
        cuts = [lo + (hi - lo) * k / n for k in range(n + 1)]
    out = []
    for a, b in zip(cuts, cuts[1:]):
        words = " ".join(s["text"] for s in segs if s["end"] > a and s["start"] < b).split()
        if not words:
            continue
        out.append(Fragment(a, b, " ".join(words[:14]) + ("…" if len(words) > 14 else "")))
    return out


def annotate(md: str, segs: list[dict], duration: float, slide_times: list[float]) -> tuple[str, dict]:
    """Dopisuje znaczniki @@PLAYn@@ do punktów i linii czasu sekcji. Zwraca (markdown, {n: [Fragment]})."""
    if not segs:
        return md, {}
    idx = _Index(segs)
    end_all = max(duration, segs[-1]["end"])
    plays: dict[int, list[Fragment]] = {}
    lines = md.splitlines()
    lo, hi = 0.0, end_all
    in_code = False
    for k, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        if _H1.match(line) and k > 0:
            lo, hi = 0.0, end_all
            continue
        mk = re.match(r"^###\s+★.*?(\d[\d:]*)\s*[–-]\s*(\d[\d:]*)", line)
        if mk:      # zaznaczony fragment: odsłuch całego zaznaczenia, punkty szukane w jego okolicy
            lo, hi = parse_time(mk.group(1)), parse_time(mk.group(2))
            n = len(plays)
            plays[n] = [Fragment(max(0.0, lo - 2), hi + 2, line.lstrip("# ").strip())]
            lines[k] = line.rstrip() + f" @@PLAY{n}@@"
            lo, hi = lo - 30, hi + 30
            continue
        if _H2.match(line):
            lo, hi = 0.0, end_all
            continue
        tm = _TIME.match(line.strip())
        if tm:
            lo, hi = parse_time(tm.group(1)), parse_time(tm.group(2))
            parts = section_parts(segs, lo, hi, slide_times)
            if parts:
                n = len(plays)
                plays[n] = parts
                lines[k] = line.rstrip() + f" @@PLAY{n}@@"
            continue
        b = _BULLET.match(line)
        if b and "@@PLAY" not in line:
            frags = idx.find(b.group(2), lo - 5, hi + 5)
            if frags:
                n = len(plays)
                plays[n] = frags
                lines[k] = line.rstrip() + f" @@PLAY{n}@@"
    return "\n".join(lines), plays
