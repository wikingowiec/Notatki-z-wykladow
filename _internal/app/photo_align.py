"""Dopasowanie serii zdjęć slajdów do nagrania po treści (gdy brakuje godzin w metadanych).

Zdjęcia mają znaną kolejność (czas zrobienia albo numer w nazwie pliku), więc szukamy takiego przypisania do
fragmentów transkrypcji, które zachowuje kolejność i najlepiej zgadza się treścią (słowa ze slajdu ↔ to, co mówi
prowadzący). Zdjęcia z pewną godziną (EXIF + czas nagrania) są „kotwicami”. Zdjęcia bez tekstu i bez dopasowania
trafiają równomiernie pomiędzy sąsiadów."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""i oraz a w we z ze na do od po za przez dla to jest są był była było być nie tak jak że czy co
który która które którego tego ten ta te tym tych się sie o u przy pod nad lub albo ale też tez jego jej ich
the a an of to in on for and or is are be as by with this that these from at it""".split())
WINDOW = 60.0      # s
STEP = 20.0


def tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-ząćęłńóśźż0-9]{3,}", (text or "").lower()):
        if w in STOP:
            continue
        out.append(w[:6])          # prosty „rdzeń” – odmiana polskich słów
    return out


def natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def windows(segs: list[dict], duration: float) -> list[tuple[float, Counter]]:
    end = max([duration] + [s["end"] for s in segs] + [1.0])
    out = []
    t = 0.0
    while t < end:
        txt = " ".join(s["text"] for s in segs if s["end"] > t and s["start"] < t + WINDOW)
        out.append((t, Counter(tokens(txt))))
        t += STEP
    return out


def align(photo_texts: list[str], segs: list[dict], duration: float,
          anchors: dict[int, float] | None = None) -> list[tuple[float, str]]:
    """Zwraca dla każdego zdjęcia (czas w s, sposób: „czas zdjęcia” / „treść” / „kolejność”)."""
    n = len(photo_texts)
    anchors = anchors or {}
    if n == 0:
        return []
    wins = windows(segs, duration) if segs else []
    if not wins:
        return [(anchors.get(i, (duration * i / n) if duration else float(i)),
                 "czas zdjęcia" if i in anchors else "kolejność") for i in range(n)]
    m = len(wins)
    # waga słów: rzadkie w całym wykładzie ważą więcej
    df = Counter()
    for _t, c in wins:
        df.update(set(c))
    idf = {w: math.log((m + 1) / (1 + d)) + 0.2 for w, d in df.items()}
    ptoks = [Counter(tokens(t)) for t in photo_texts]
    score = [[0.0] * m for _ in range(n)]
    for i, pc in enumerate(ptoks):
        if not pc:
            continue
        norm = sum(idf.get(w, 1.0) for w in pc) or 1.0
        for j, (_t, wc) in enumerate(wins):
            score[i][j] = sum(idf.get(w, 1.0) for w in pc if w in wc) / norm
    # kotwice: wolno tylko okna w pobliżu ich czasu
    allowed = []
    for i in range(n):
        if i in anchors:
            a = anchors[i]
            allowed.append({j for j, (t, _c) in enumerate(wins) if abs(t + WINDOW / 2 - a) <= WINDOW})
        else:
            allowed.append(None)
    NEG = -1e9
    # programowanie dynamiczne: best[i][j] = najlepsza suma, gdy zdjęcie i jest w oknie j (kolejność zachowana)
    best = [[NEG] * m for _ in range(n)]
    back = [[-1] * m for _ in range(n)]
    for i in range(n):
        run_best, run_arg = NEG, -1
        for j in range(m):
            if i > 0 and best[i - 1][j] > run_best:
                run_best, run_arg = best[i - 1][j], j
            if allowed[i] is not None and j not in allowed[i]:
                continue
            prev = 0.0 if i == 0 else run_best
            if prev <= NEG / 2:
                continue
            best[i][j] = prev + score[i][j] + (1.0 if allowed[i] is not None else 0.0)
            back[i][j] = run_arg
    j = max(range(m), key=lambda k: best[n - 1][k])
    if best[n - 1][j] <= NEG / 2:          # sprzeczne kotwice – bez nich
        return align(photo_texts, segs, duration, None)
    pos = [0] * n
    for i in range(n - 1, -1, -1):
        pos[i] = j
        j = back[i][j]
    out: list[tuple[float, str]] = []
    for i in range(n):
        if i in anchors:
            out.append((anchors[i], "czas zdjęcia"))
        elif score[i][pos[i]] >= 0.12:
            out.append((wins[pos[i]][0] + WINDOW * 0.25, "treść"))
        else:
            out.append((None, "kolejność"))
    # bez dopasowania: równo między sąsiadami
    end = max([duration] + [s["end"] for s in segs])
    i = 0
    while i < n:
        if out[i][0] is not None:
            i += 1
            continue
        k = i
        while k < n and out[k][0] is None:
            k += 1
        lo = out[i - 1][0] if i > 0 else 0.0
        hi = out[k][0] if k < n else end
        cnt = k - i
        for q in range(cnt):
            out[i + q] = (lo + (hi - lo) * (q + 1) / (cnt + 1), "kolejność")
        i = k
    # ściśle rosnąco (dwa zdjęcia nie w tej samej sekundzie)
    fixed = []
    last = -1.0
    for t, how in out:
        t = max(t, last + 0.5)
        fixed.append((round(t, 1), how))
        last = t
    return fixed
