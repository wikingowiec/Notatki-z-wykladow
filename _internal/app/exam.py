"""Egzamin próbny: pytania z notatek (jednego wykładu albo całego przedmiotu), z weryfikacją źródła.

Każde pytanie musi mieć cytat z notatki, na którym się opiera (dosłowny albo prawie dosłowny – match_quote) –
pytania bez potwierdzonego cytatu są odrzucane (żeby egzamin nie sprawdzał rzeczy, których nie było na wykładach).
Układanie ma twardy limit czasu (TIME_BUDGET_S): po nim egzamin zapisuje się z pytaniami, które już są.
"""
from __future__ import annotations

import json
import logging
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .notes_doc import Chunk, chunks
from .llm import Cancelled
from .qa import _norm, verify_quote
from .storage import Lecture, list_lectures
from .i18n import tr

log = logging.getLogger(__name__)

# i18n: nie – prompt / treść notatki / styl
TYPES = {"abcd": "jednokrotnego wyboru (4 odpowiedzi A–D, dokładnie jedna poprawna)",
         "pf": "prawda/fałsz",
         "open": "otwarte (krótka odpowiedź własnymi słowami)"}
# i18n: nie – prompt / treść notatki / styl
LEVELS = {"easy": "łatwe – podstawowe definicje i fakty",
          "medium": "średnie – zrozumienie i zastosowanie",
          "hard": "trudne – łączenie wiadomości, przykłady, subtelne różnice"}


@dataclass
class ExamSpec:
    scope: str                   # "subject" / "lecture"
    value: str                   # nazwa przedmiotu albo ścieżka folderu wykładu
    n: int = 15
    types: list = field(default_factory=lambda: ["abcd", "pf", "open"])
    level: str = "medium"
    instructions: str = ""
    use_exam_info: bool = True
    speed: str = "accurate"      # "fast" – mniejszy model (live_model), "accurate" – model notatek


def scope_lectures(library: Path, spec: ExamSpec) -> list[Lecture]:
    out = []
    for lec in list_lectures(library):
        if not lec.notes_path.exists():
            continue
        if spec.scope == "subject" and lec.meta.subject != spec.value:
            continue
        if spec.scope == "lecture" and str(lec.folder) != spec.value:
            continue
        out.append(lec)
    return sorted(out, key=lambda l: l.meta.created)


def collect(lectures: list[Lecture]) -> tuple[list[Chunk], list[str], list[tuple]]:
    """Fragmenty notatek (z tytułem wykładu), informacje o egzaminie, źródła (folder, kotwica)."""
    parts, info, src = [], [], []
    for lec in lectures:
        md = lec.read_text(lec.notes_path)
        for c in chunks(md):
            low = c.title.lower()
            # i18n: nie – prompt / treść notatki / styl
            if low.startswith(("spis treści", "contents", "pytania kontrolne", "review questions")):
                continue
            parts.append(Chunk(c.anchor, f"{lec.meta.title} › {c.title}", c.time, c.text))
            src.append((str(lec.folder), c.anchor, "★" in c.title or "egzamin" in low or "exam" in low))
        try:
            data = json.loads((lec.folder / "exam_info.json").read_text(encoding="utf-8"))
            info += [f"{lec.meta.title}: {x}" for x in data.get("items", [])]
        except Exception:
            pass
    return parts, info, src


# Stałe zadania. Mały, STAŁY kontekst na całe zadanie (układanie i ocena pytań otwartych) – zmiana num_ctx
# przeładowuje model w Ollamie, a mniejszy kontekst = mniejszy bufor KV, więc więcej modelu mieści się na karcie.
EXAM_CTX = 8192
KEEP_ALIVE = "30m"           # model egzaminu zostaje w pamięci do końca (także do sprawdzania pytań otwartych)
TIME_BUDGET_S = 25 * 60      # twardy limit czasu układania egzaminu
MAX_FRAGS = 4                # fragmentów notatek w jednej partii
FRAG_BUDGET = 9000           # znaków fragmentów w partii (~3 tys. tokenów)
FRAG_MAX = 4000              # dłuższy fragment – w partii tylko jego kawałek
PER_BATCH = 8                # pytań z jednej partii
TOK_PER_Q = 190              # limit odpowiedzi: tyle tokenów na pytanie (+ zapas)
QUOTE_MATCH = 0.8            # cytat przybliżony: tyle jego słów musi być w jednym miejscu fragmentu
# i18n: nie – nazwy powodów odrzucenia do logu
REJECT = {"format": "zły format", "no_quote": "brak cytatu", "quote": "cytat niepotwierdzony",
          "duplicate": "duplikat", "extra": "nadmiar"}

# i18n: nie – prompt / treść notatki / styl
PROMPT = """Jesteś egzaminatorem. Na podstawie poniższych fragmentów notatek z wykładów ułóż {k} pytań egzaminacyjnych.

Rodzaje pytań do użycia: {types}.
Poziom trudności: {level}.
{instructions}{exam_info}
ZASADY:
- Pytaj wyłącznie o treści zawarte we fragmentach – nic spoza nich. Każde pytanie o coś innego.
- W polu "cytat" przepisz SŁOWO W SŁOWO jedno zdanie notatki (najwyżej 30 słów), z którego wynika poprawna odpowiedź; w polu "fragment" numer fragmentu.
- Jednokrotnego wyboru: 4 odpowiedzi w polu "opcje", błędne mają być wiarygodne; "poprawna" to indeks 0–3.
- Prawda/fałsz: "poprawna" = true albo false; zdanie w polu "pytanie"; bez pola "opcje".
- Otwarte: w polu "odpowiedz" wzorcowa krótka odpowiedź; bez pola "opcje".
- W polu "wyjasnienie" jedno zdanie, dlaczego taka odpowiedź jest poprawna.
- Wzory zapisuj w LaTeX ($…$). Pisz w języku notatek.

FRAGMENTY:
{fragments}

Zwróć wyłącznie JSON:
{{"pytania": [{{"typ": "abcd|pf|open", "pytanie": "…", "opcje": ["…","…","…","…"], "poprawna": 0, "odpowiedz": "…", "wyjasnienie": "…", "cytat": "…", "fragment": 1}}]}}"""


def _salvage(raw: str, keys: tuple = ("pytanie", "question")) -> list[dict]:
    """Pełne obiekty pytań z uciętej odpowiedzi (limit tokenów albo koniec czasu) – reszta JSON-a może być urwana.
    keys – obiekt jest brany, gdy ma któreś z tych pól."""
    out, stack, in_str, esc = [], [], False, False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            if not stack:
                continue                     # obiekt główny (cały JSON był poprawny – tu nie trafiamy)
            try:
                d = json.loads(raw[start:i + 1])
            except Exception:
                continue
            if isinstance(d, dict) and any(k in d for k in keys):
                out.append(d)
    return out


def _parse_questions(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            return _salvage(raw)
    items = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
        if not items and ("pytanie" in data or "question" in data):
            items = [data]
    elif isinstance(data, list):
        items = data
    return [x for x in items if isinstance(x, dict)]


def _normalize(q: dict, allowed: list) -> Optional[dict]:
    typ = str(q.get("typ") or q.get("type") or "").lower()
    typ = {"abcd": "abcd", "wybor": "abcd", "wybór": "abcd", "mc": "abcd", "pf": "pf", "tf": "pf",
           "prawda/fałsz": "pf", "open": "open", "otwarte": "open", "otwarta": "open"}.get(typ, typ)
    text = str(q.get("pytanie") or q.get("question") or "").strip()
    if typ not in allowed or not text:
        return None
    out = {"type": typ, "q": text, "explain": str(q.get("wyjasnienie") or q.get("explanation") or "").strip(),
           "quote": str(q.get("cytat") or q.get("quote") or "").strip()}
    try:
        out["hint"] = int(q.get("fragment")) - 1
    except (TypeError, ValueError):
        out["hint"] = None
    if typ == "abcd":
        opts = [str(x).strip() for x in (q.get("opcje") or q.get("options") or []) if str(x).strip()]
        try:
            corr = int(q.get("poprawna", q.get("correct", -1)))
        except (TypeError, ValueError):
            return None
        if len(opts) != 4 or not 0 <= corr < 4 or len(set(o.lower() for o in opts)) < 4:
            return None
        # przetasuj, żeby poprawna nie była zawsze pod tą samą literą
        order = list(range(4))
        random.shuffle(order)
        out["options"] = [re.sub(r"^[A-Da-d][).:]\s*", "", opts[i]) for i in order]
        out["correct"] = order.index(corr)
    elif typ == "pf":
        val = q.get("poprawna", q.get("correct"))
        if isinstance(val, str):
            val = val.strip().lower() in ("true", "prawda", "tak", "p", "1")
        if not isinstance(val, bool):
            return None
        out["correct"] = val
    else:
        # i18n: nie – prompt / treść notatki / styl
        ans = str(q.get("odpowiedz") or q.get("odpowiedź") or q.get("answer") or "").strip()
        if not ans:
            return None
        out["answer"] = ans
    return out


def _stem(w: str) -> str:
    """Prosty „rdzeń” słowa (bez ostatniej litery, najwyżej 6 liter) – „funkcji” = „funkcja”, „ciągłą” = „ciągła”
    (model często zmienia odmianę). Krótkie słowa i liczby – bez zmian."""
    if any(ch.isdigit() for ch in w) or len(w) <= 4:
        return w
    return w[:min(6, len(w) - 1)]


def match_quote(quote: str, texts: list[str], hint: Optional[int] = None) -> tuple[Optional[int], str]:
    """Indeks fragmentu, z którego pochodzi cytat, i rodzaj dopasowania ("exact" / "approx"), albo (None, "").

    Najpierw ścisła weryfikacja z qa.verify_quote. Potem przybliżona: co najmniej 80% słów cytatu (po normalizacji
    i z rdzeniem słowa) w jednym miejscu fragmentu, a wszystkie liczby z cytatu muszą być we fragmencie. Cytat
    wymyślony (spoza notatek) nie ma szans – jego słowa nie występują razem w żadnym miejscu fragmentu."""
    if not quote:
        return None, ""
    order = list(range(len(texts)))
    if hint in order:
        order.remove(hint)
        order.insert(0, hint)
    j = verify_quote(quote, [texts[i] for i in order])
    if j is not None:
        return order[j], "exact"
    words = [w for w in _norm(quote).split() if len(w) >= 3 or any(ch.isdigit() for ch in w)]
    if len(words) < 5:
        return None, ""
    nums = {w for w in words if any(ch.isdigit() for ch in w)}
    qs = [_stem(w) for w in words]
    need = math.ceil(QUOTE_MATCH * len(qs))
    win = 2 * len(qs) + 6
    step = max(1, len(qs) // 2)
    for i in order:
        raw_words = _norm(texts[i]).split()
        if nums and not nums <= set(raw_words):
            continue                         # liczby muszą się zgadzać co do joty
        tw = [_stem(w) for w in raw_words]
        vocab = set(tw)
        if sum(1 for w in qs if w in vocab) < need:
            continue
        for start in range(0, max(1, len(tw) - win + step), step):
            seg = set(tw[start:start + win])
            if sum(1 for w in qs if w in seg) >= need:
                return i, "approx"
    return None, ""


def _pick(parts: list[Chunk], weights: list[float], uses: list[int]) -> list[tuple[int, str]]:
    """2–4 fragmenty do partii: najpierw najrzadziej użyte (ważne liczą się podwójnie/potrójnie), razem do
    FRAG_BUDGET znaków. Za długi fragment – losowy kawałek od akapitu."""
    order = sorted(range(len(parts)), key=lambda i: (uses[i] + random.random()) / weights[i])
    out, size = [], 0
    for i in order:
        text = parts[i].text
        if len(text) > FRAG_MAX:
            paras = text.split("\n\n")
            k = random.randrange(len(paras))
            piece = []
            while k < len(paras) and sum(len(p) + 2 for p in piece) + len(paras[k]) <= FRAG_MAX:
                piece.append(paras[k])
                k += 1
            text = "\n\n".join(piece) or text[:FRAG_MAX]
        L = len(text) + len(parts[i].title) + 20
        if size + L > FRAG_BUDGET and out:
            continue
        out.append((i, text))
        size += L
        uses[i] += 1
        if len(out) >= MAX_FRAGS:
            break
    return sorted(out)


class _Deadline:
    """„cancel” dla llm.chat: przerwij, gdy użytkownik anuluje albo minie limit czasu."""

    def __init__(self, cancel: Optional[threading.Event], until: float):
        self.cancel, self.until = cancel, until

    def user(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()

    def is_set(self) -> bool:
        return self.user() or time.monotonic() >= self.until

    def left(self) -> float:
        return self.until - time.monotonic()


def _eta_text(done: int, n: int, secs: Optional[float]) -> str:
    if secs is None:
        return tr("Układam pytania… {n}/{n2} · szacuję czas…", n=done, n2=n)
    if secs < 60:
        return tr("Układam pytania… {n}/{n2} · zostało mniej niż minuta", n=done, n2=n)
    return tr("Układam pytania… {n}/{n2} · zostało około {m} min", n=done, n2=n, m=round(secs / 60))


def generate_exam(library: Path, spec: ExamSpec, llm, model: str, num_ctx: int = EXAM_CTX,
                  progress: Optional[Callable[[str, float], None]] = None,
                  cancel: Optional[threading.Event] = None, budget_s: float = TIME_BUDGET_S,
                  prepare: bool = True) -> dict:
    """num_ctx – stały na całe zadanie (domyślnie EXAM_CTX; większy nic tu nie daje, a spowalnia).
    prepare=True: przed startem zwolnij inne modele i załaduj model egzaminu (keep_alive do końca)."""
    prog = progress or (lambda m, f: None)
    lectures = scope_lectures(library, spec)
    if not lectures:
        raise RuntimeError(tr("W wybranym zakresie nie ma wykładów z gotowymi notatkami."))
    parts, info, src = collect(lectures)
    if not parts:
        raise RuntimeError(tr("Notatki są puste."))
    num_ctx = min(num_ctx, EXAM_CTX)
    t_start = time.monotonic()
    dl = _Deadline(cancel, t_start + budget_s)
    if prepare:
        prog(tr("Zwalniam pamięć po innych modelach i ładuję model AI…"), -1)
        freed = llm.unload_others(model) if hasattr(llm, "unload_others") else []
        load_s = llm.preload(model, num_ctx, KEEP_ALIVE) if hasattr(llm, "preload") else 0.0
        log.info("Egzamin: model %s, num_ctx %d, zwolnione: %s, ładowanie %.1f s", model, num_ctx,
                 ", ".join(freed) or "–", load_s)
    # fragmenty zaznaczone jako ważne / na egzamin trafiają do partii częściej
    weights = [3.0 if src[i][2] else 1.0 for i in range(len(parts))]
    uses = [0] * len(parts)
    types = [t for t in spec.types if t in TYPES] or ["abcd"]
    questions: list[dict] = []
    seen: set[str] = set()
    rej = dict.fromkeys(REJECT, 0)
    total = {"calls": 0, "chars": 0, "returned": 0, "approx": 0}
    batch_s: list[float] = []
    gen_s = 0.0               # czas zakończonych partii (do szacunku)
    timed_out = False
    max_batches = -(-spec.n // 4) + 4
    while len(questions) < spec.n and len(batch_s) < max_batches:
        if dl.user():
            break
        if dl.left() <= 0 or (batch_s and dl.left() < 0.5 * (sum(batch_s) / len(batch_s))):
            timed_out = True          # następna partia i tak nie zdąży
            break
        chosen = _pick(parts, weights, uses)
        k = min(PER_BATCH, spec.n - len(questions) + 2)
        frags = "\n\n".join(f"[{j}] ({parts[i].title})\n{text}" for j, (i, text) in enumerate(chosen, 1))
        # i18n: nie – prompt
        prompt = PROMPT.format(
            k=k, types=", ".join(TYPES[t] for t in types), level=LEVELS.get(spec.level, LEVELS["medium"]),
            instructions=(f"Dodatkowe wskazówki studenta: {spec.instructions.strip()}\n" if spec.instructions.strip() else ""),
            exam_info=(("Informacje o egzaminie podane przez prowadzącego (uwzględnij je):\n- " + "\n- ".join(info[:15]) + "\n")
                       if spec.use_exam_info and info else ""),
            fragments=frags)
        done_q = len(questions)
        per_q = gen_s / done_q if done_q else None
        t_b = time.monotonic()

        def eta() -> Optional[float]:
            if per_q is None:
                return None
            return max(0.0, min((spec.n - done_q) * per_q - (time.monotonic() - t_b), dl.left()))
        prog(_eta_text(done_q, spec.n, eta()), done_q / max(1, spec.n))
        got: list[str] = []
        last = [t_b]

        def on_tok(tok: str) -> None:
            got.append(tok)
            now = time.monotonic()
            if now - last[0] > 2.0:
                last[0] = now
                prog(_eta_text(done_q, spec.n, eta()), done_q / max(1, spec.n))
        try:
            raw = llm.chat(model, [{"role": "user", "content": prompt}], num_ctx=num_ctx, temperature=0.5,
                           json_mode=True, cancel=dl, keep_alive=KEEP_ALIVE, on_token=on_tok,
                           num_predict=TOK_PER_Q * k + 150, stop_json=True)
        except Cancelled:
            if dl.user():
                raise
            timed_out = True
            raw = "".join(got)        # koniec czasu w trakcie partii – bierzemy pełne pytania, które już przyszły
        dt = time.monotonic() - t_b
        batch_s.append(dt)
        texts = [parts[i].title + "\n" + text for i, text in chosen]
        items = _parse_questions(raw)
        b_rej = dict.fromkeys(rej, 0)
        b_ok = b_approx = 0
        for q in items:
            if len(questions) >= spec.n:
                b_rej["extra"] += 1
                continue
            nq = _normalize(q, types)
            if not nq:
                b_rej["format"] += 1
                continue
            if not nq["quote"]:
                b_rej["no_quote"] += 1
                continue
            j, how = match_quote(nq["quote"], texts, nq.pop("hint", None))
            if j is None:
                b_rej["quote"] += 1        # brak potwierdzenia w notatce – pytanie odrzucone
                continue
            key = re.sub(r"\W+", "", nq["q"].lower())[:80]
            if key in seen:
                b_rej["duplicate"] += 1
                continue
            seen.add(key)
            b_approx += how == "approx"
            gi = chosen[j][0]
            nq["source"] = {"folder": src[gi][0], "anchor": src[gi][1], "title": parts[gi].title}
            questions.append(nq)
            b_ok += 1
        if not timed_out:
            gen_s += dt
        for r_, v in b_rej.items():
            rej[r_] += v
        total["calls"] += 1
        total["chars"] += len(prompt)
        total["returned"] += len(items)
        total["approx"] += b_approx
        st = getattr(llm, "last_stats", None) or {}
        log.info("Egzamin partia %d: %d fragm., prompt %d znaków (~%d tok., prompt_eval %s tok. w %s s), "
                 "num_ctx %d, k %d, odpowiedź %s tok. w %s s (pierwszy token po %s s, ładowanie %s s, %s), "
                 "razem %.1f s; pytań %d, przyjęte %d (w tym cytat przybliżony %d), odrzucone: %s",
                 len(batch_s), len(chosen), len(prompt), len(prompt) // 3, st.get("prompt_eval_count", "?"),
                 _f(st.get("prompt_eval_s")), num_ctx, k, st.get("eval_count", st.get("chunks", "?")),
                 _f(st.get("eval_s")), _f(st.get("first_s")), _f(st.get("load_s")),
                 "przerwane po JSON" if st.get("stopped_json") else st.get("done_reason", "?"),
                 dt, len(items), b_ok, b_approx, ", ".join(f"{REJECT[r_]} {v}" for r_, v in b_rej.items() if v) or "0")
        if timed_out:
            break
    elapsed = time.monotonic() - t_start
    log.info("Egzamin gotowy: %d/%d pytań w %.0f s, %d partii, prompty razem %d znaków, przyszło %d, "
             "odrzucone %d (%s)%s", len(questions), spec.n, elapsed, total["calls"], total["chars"],
             total["returned"], sum(rej.values()), ", ".join(f"{REJECT[r_]} {v}" for r_, v in rej.items() if v) or "0",
             " – koniec czasu" if timed_out else "")
    if not questions:
        if timed_out:
            raise RuntimeError(tr("W wyznaczonym czasie nie udało się ułożyć żadnego pytania. "
                                  "Wybierz „Szybciej” albo mniejszy zakres."))
        raise RuntimeError(tr("Nie udało się ułożyć pytań potwierdzonych w notatkach. Spróbuj ponownie."))
    random.shuffle(questions)
    title = (spec.value if spec.scope == "subject" else lectures[0].meta.title)
    return {"id": time.strftime("%Y%m%d-%H%M%S"), "title": title, "scope": spec.scope, "value": spec.value,
            "created": time.strftime("%Y-%m-%d %H:%M"), "spec": spec.__dict__, "questions": questions,
            "results": [], "model": model, "wanted": spec.n, "timed_out": timed_out and len(questions) < spec.n,
            "stats": {"seconds": round(elapsed), "calls": total["calls"], "prompt_chars": total["chars"],
                      "returned": total["returned"], "rejected": rej, "approx_quotes": total["approx"]}}


def _f(x) -> str:
    return f"{x:.1f}" if isinstance(x, (int, float)) else "?"


# i18n: nie – prompt / treść notatki / styl
GRADE_PROMPT = """Oceń odpowiedź studenta na pytanie otwarte, porównując ją ze wzorcem z notatek.

PYTANIE: {q}
WZORCOWA ODPOWIEDŹ: {ref}
FRAGMENT NOTATKI: "{quote}"
ODPOWIEDŹ STUDENTA: {ans}

Oceń tylko merytorykę (nie styl). Punkty: 2 = poprawna i pełna, 1 = częściowo poprawna, 0 = błędna lub brak.
Zwróć wyłącznie JSON: {{"punkty": 0|1|2, "komentarz": "1–2 zdania: co dobrze, czego brakuje"}}"""


def grade_open(q: dict, answer: str, llm, model: str, num_ctx: int = EXAM_CTX) -> tuple[int, str]:
    """Ocena pytania otwartego: krótki prompt, ten sam model i num_ctx co przy układaniu (bez przeładowania)."""
    if not answer.strip():
        return 0, tr("Brak odpowiedzi.")
    raw = llm.chat(model, [{"role": "user", "content": GRADE_PROMPT.format(
        q=q["q"], ref=q.get("answer", ""), quote=q.get("quote", ""), ans=answer.strip()[:3000])}],
        num_ctx=min(num_ctx, EXAM_CTX), temperature=0.0, json_mode=True, keep_alive=KEEP_ALIVE,
        num_predict=250, stop_json=True)
    try:
        d = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:
            d = {}
    try:
        pts = max(0, min(2, int(d.get("punkty", d.get("points", 0)))))
    except (TypeError, ValueError):
        pts = 0
    return pts, str(d.get("komentarz") or d.get("comment") or "").strip()


# ---------------------------------------------------------------------------
def exams_dir(library: Path) -> Path:
    p = Path(library) / ".egzaminy"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_exam(library: Path, exam: dict) -> None:
    (exams_dir(library) / f"{exam['id']}.json").write_text(json.dumps(exam, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")


def list_exams(library: Path) -> list[dict]:
    out = []
    for f in sorted(exams_dir(library).glob("*.json"), reverse=True):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def delete_exam(library: Path, exam_id: str) -> None:
    (exams_dir(library) / f"{exam_id}.json").unlink(missing_ok=True)
