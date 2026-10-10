"""Pytania do notatki: odpowiedzi WYŁĄCZNIE na podstawie notatki, z weryfikacją cytatów.

Zabezpieczenia przed halucynacjami:
  1. Model dostaje tylko fragmenty notatki i twarde zasady (brak informacji => „brak”).
  2. Temperatura 0, odpowiedź w ustalonym formacie JSON.
  3. Model musi podać DOSŁOWNE cytaty z notatki. Program sprawdza, czy te cytaty naprawdę w niej są.
     Odpowiedź bez potwierdzonego cytatu nie jest pokazywana jako odpowiedź.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Optional

from .notes_doc import Chunk, chunks

SYSTEM_QA = """Jesteś asystentem, który odpowiada na pytania studenta WYŁĄCZNIE na podstawie podanych fragmentów notatki z wykładu.

ZASADY BEZWZGLĘDNE:
1. Korzystaj tylko z informacji zapisanych we fragmentach notatki. Nie używaj własnej wiedzy – nawet jeśli znasz odpowiedź.
2. Jeśli fragmenty nie zawierają informacji potrzebnej do odpowiedzi, ustaw "status": "brak". Nie zgaduj, nie domyślaj się, nie uzupełniaj.
3. Jeśli fragmenty odpowiadają tylko na część pytania, ustaw "status": "czesciowo", odpowiedz tylko na tę część i w polu "brakuje" napisz, czego w notatce nie ma.
4. Każde twierdzenie w odpowiedzi musi być poparte cytatem. W polu "cytaty" skopiuj DOSŁOWNIE (słowo w słowo) zdania lub punkty z fragmentów, na których się opierasz.
5. Nie wymyślaj wzorów, liczb, dat, nazwisk ani definicji, których nie ma we fragmentach.
6. Jeśli nie masz pewności – wybierz "brak". Błędna odpowiedź jest gorsza niż brak odpowiedzi.
7. Pisz po polsku, zwięźle i konkretnie.

Zwróć wyłącznie JSON w formacie:
{"status": "odpowiedz" | "czesciowo" | "brak", "odpowiedz": "…", "fragmenty": [numery fragmentów], "cytaty": ["dosłowny cytat", "…"], "brakuje": "czego brakuje w notatce (dla czesciowo/brak)"}"""


# ---------------------------------------------------------------------------
# Wyszukiwanie fragmentów (BM25 na „rdzeniach” słów – prosto, ale działa dla polskiej odmiany)
# ---------------------------------------------------------------------------
_STOP = set("""a aby ale albo ani bez by być był była było były czy dla do gdy gdzie i ich jak jaka jaki jakie
jest jeśli jego jej już ku lub ma mają na nad nie niż o od oraz po pod przez przy się są ta tak także te
ten to tu tych tylko w we z za ze że który która które którzy co czym czego kiedy dlaczego ile jakim jakiej""".split())


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l")


def _stems(text: str) -> list[str]:
    words = re.findall(r"[a-ząćęłńóśźż0-9]+", text.lower())
    return [_fold(w)[:6] for w in words if len(w) >= 3 and w not in _STOP]


def rank(question: str, parts: list[Chunk]) -> list[tuple[float, int]]:
    docs = [_stems(p.title + " " + p.text) for p in parts]
    q = set(_stems(question))
    n = len(docs) or 1
    avg = sum(len(d) for d in docs) / n or 1
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        scores.append((s, i))
    return sorted(scores, reverse=True)


def select_context(question: str, parts: list[Chunk], budget_tokens: int) -> list[int]:
    """Cała notatka, jeśli się mieści – inaczej najlepiej pasujące fragmenty (w kolejności z notatki)."""
    est = lambda c: int(len(c.title) + len(c.text)) // 3 + 10  # noqa: E731
    if sum(est(c) for c in parts) <= budget_tokens:
        return list(range(len(parts)))
    chosen, used = [], 0
    for score, i in rank(question, parts):
        if score <= 0 and chosen:
            break
        if used + est(parts[i]) > budget_tokens:
            continue
        chosen.append(i)
        used += est(parts[i])
    return sorted(chosen)


# ---------------------------------------------------------------------------
# Weryfikacja cytatów
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = re.sub(r"[*_`#>\[\]()]", " ", s.lower())
    s = s.replace("„", " ").replace("”", " ").replace('"', " ").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, texts: list[str]) -> Optional[int]:
    """Zwraca indeks fragmentu, w którym cytat naprawdę występuje (dokładnie albo prawie dokładnie), inaczej None."""
    nq = _norm(quote)
    if len(nq) < 8:
        return None
    normed = [_norm(t) for t in texts]
    for i, t in enumerate(normed):
        if nq in t:
            return i
    q_words = [w for w in nq.split() if len(w) >= 3 or any(ch.isdigit() for ch in w)]
    q_nums = [w for w in q_words if any(ch.isdigit() for ch in w)]
    if len(q_words) < 4 or q_nums:      # cytaty z liczbami muszą pasować dokładnie (sprawdzone wyżej)
        return None
    for i, t in enumerate(normed):
        words = t.split()
        vocab = set(words)
        if sum(1 for w in q_words if w in vocab) / len(q_words) < 0.85:
            continue
        if any(n not in vocab for n in q_nums):     # liczby w cytacie muszą się zgadzać co do joty
            continue
        # słowa muszą też występować blisko siebie (w jednym miejscu notatki), a nie rozrzucone po całej sekcji
        win = len(q_words) * 2 + 4
        pos = {}
        for k, w in enumerate(words):
            pos.setdefault(w, []).append(k)
        for start in (pos.get(q_words[0], []) + pos.get(q_words[-1], [])):
            lo, hi = max(0, start - win), start + win
            seg = set(words[lo:hi])
            if all(n in seg for n in q_nums) and sum(1 for w in q_words if w in seg) / len(q_words) >= 0.85:
                return i
    return None


# ---------------------------------------------------------------------------
@dataclass
class Answer:
    question: str
    status: str                      # odpowiedz / czesciowo / brak / niepewne / blad
    answer: str = ""
    quotes: list = field(default_factory=list)       # [{"text", "anchor", "title"}] – tylko potwierdzone
    sources: list = field(default_factory=list)      # [{"anchor", "title", "time"}]
    missing: str = ""
    related: list = field(default_factory=list)      # najbliższe fragmenty, gdy brak odpowiedzi
    t: float = 0.0


def _parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def ask(md, question: str, llm, model: str, num_ctx: int = 16384,
        cancel: Optional[threading.Event] = None, keep_alive: str = "10m", lang: str = "") -> Answer:
    """md: tekst notatki albo gotowa lista fragmentów (np. z wielu wykładów przedmiotu)."""
    parts = md if isinstance(md, list) else chunks(md)
    ans = Answer(question=question.strip(), status="brak", t=time.time())
    if not parts:
        ans.status, ans.answer = "blad", "Ta notatka jest pusta."
        return ans
    budget = int(num_ctx * 0.6) - 800
    idx = select_context(question, parts, budget)
    ranked = [i for s, i in rank(question, parts) if s > 0]
    ctx = [parts[i] for i in idx]

    blocks = []
    for k, c in enumerate(ctx, 1):
        head = c.title + (f", {c.time}" if c.time else "")
        blocks.append(f"[F{k}] ({head})\n{c.text}")
    user = ("FRAGMENTY NOTATKI:\n\n" + "\n\n".join(blocks) +
            f"\n\nPYTANIE STUDENTA: {question.strip()}\n\n"
            "Odpowiedz zgodnie z zasadami. Jeśli odpowiedzi nie ma we fragmentach, zwróć status \"brak\".")
    system = SYSTEM_QA
    if lang and lang != "pl":           # odpowiedź w języku notatek (klucze JSON zostają te same)
        from .prompts import LANG_EN
        name = LANG_EN.get(lang, lang)
        system = system.replace("7. Pisz po polsku, zwięźle i konkretnie.",
                                f"7. Pisz w języku notatek ({name}), zwięźle i konkretnie.")
        system += (f"\n\nThe notes are in {name}. Write \"odpowiedz\" and \"brakuje\" in {name}; "
                   "quotes must be copied verbatim from the notes.")
    raw = llm.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   num_ctx=num_ctx, temperature=0.0, json_mode=True, cancel=cancel, keep_alive=keep_alive)
    data = _parse(raw)
    status = str(data.get("status", "")).lower().replace("ę", "e").replace("ź", "z")
    status = {"odpowiedź": "odpowiedz", "czesciowa": "czesciowo", "częściowo": "czesciowo"}.get(status, status)
    text = str(data.get("odpowiedz") or data.get("odpowiedź") or "").strip()
    ans.missing = str(data.get("brakuje") or "").strip()
    ans.related = [{"anchor": parts[i].anchor, "title": parts[i].title, "time": parts[i].time} for i in ranked[:3]]

    if status not in ("odpowiedz", "czesciowo") or not text:
        ans.status = "brak"
        return ans

    # weryfikacja cytatów
    texts = [c.title + "\n" + c.text for c in ctx]
    quotes = data.get("cytaty") or []
    if isinstance(quotes, str):
        quotes = [quotes]
    verified, bad = [], 0
    for q in quotes:
        i = verify_quote(str(q), texts)
        if i is None:
            bad += 1
        else:
            verified.append({"text": str(q).strip(), "anchor": ctx[i].anchor, "title": ctx[i].title})
    if not verified:
        ans.status = "niepewne"
        ans.missing = ans.missing or "Model nie wskazał fragmentu notatki, który potwierdza odpowiedź."
        return ans
    ans.status = status if bad == 0 else "czesciowo"
    if bad and not ans.missing:
        ans.missing = "Część odpowiedzi nie ma potwierdzenia w notatce – sprawdź w źródle."
    # czy odpowiedź nie wychodzi poza notatkę (słowa i liczby, których w niej nie ma)
    ctx_all = " ".join(texts)
    ctx_stems = set(_stems(ctx_all + " " + question))
    a_stems = _stems(text)
    coverage = sum(1 for w in a_stems if w in ctx_stems) / len(a_stems) if a_stems else 1.0
    ctx_nums = set(re.findall(r"\d+(?:[.,]\d+)?", ctx_all + " " + question))
    foreign_nums = [n for n in re.findall(r"\d+(?:[.,]\d+)?", text) if n not in ctx_nums]
    if coverage < 0.6 or foreign_nums:
        ans.status = "czesciowo"
        ans.missing = ("Odpowiedź zawiera " + (f"liczby ({', '.join(foreign_nums[:3])}), których " if foreign_nums
                                              else "sformułowania, których ") +
                       "nie ma w notatce – traktuj ją ostrożnie i sprawdź w źródle.")
    ans.answer = text
    ans.quotes = verified
    seen = []
    for q in verified:
        if q["anchor"] not in [s["anchor"] for s in seen]:
            c = next(c for c in ctx if c.anchor == q["anchor"])
            seen.append({"anchor": c.anchor, "title": c.title, "time": c.time})
    ans.sources = seen
    return ans


def load_history(path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(path, items: list[dict]) -> None:
    path.write_text(json.dumps(items[-100:], ensure_ascii=False, indent=2), encoding="utf-8")


def to_dict(a: Answer) -> dict:
    return asdict(a)
