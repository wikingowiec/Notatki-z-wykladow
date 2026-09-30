"""Egzamin próbny: pytania z notatek (jednego wykładu albo całego przedmiotu), z weryfikacją źródła.

Każde pytanie musi mieć dosłowny cytat z notatki, na którym się opiera – pytania bez potwierdzonego cytatu
są odrzucane (żeby egzamin nie sprawdzał rzeczy, których nie było na wykładach).
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .notes_doc import Chunk, chunks
from .qa import verify_quote
from .storage import Lecture, list_lectures

TYPES = {"abcd": "jednokrotnego wyboru (4 odpowiedzi A–D, dokładnie jedna poprawna)",
         "pf": "prawda/fałsz",
         "open": "otwarte (krótka odpowiedź własnymi słowami)"}
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


PROMPT = """Jesteś egzaminatorem. Na podstawie poniższych fragmentów notatek z wykładów ułóż {k} pytań egzaminacyjnych.

Rodzaje pytań do użycia: {types}.
Poziom trudności: {level}.
{instructions}{exam_info}
ZASADY:
- Pytaj wyłącznie o treści zawarte we fragmentach – nic spoza nich.
- Do każdego pytania podaj w polu "cytat" DOSŁOWNY fragment notatki (słowo w słowo), z którego wynika poprawna odpowiedź, i numer fragmentu w polu "fragment".
- Pytania jednokrotnego wyboru: 4 odpowiedzi w polu "opcje", błędne odpowiedzi mają być wiarygodne; "poprawna" to indeks 0–3.
- Prawda/fałsz: pole "poprawna" = true albo false; zdanie w polu "pytanie".
- Otwarte: w polu "odpowiedz" wzorcowa krótka odpowiedź.
- W polu "wyjasnienie" 1–2 zdania, dlaczego taka odpowiedź jest poprawna.
- Wzory zapisuj w LaTeX ($…$). Pisz w języku notatek.

FRAGMENTY:
{fragments}

Zwróć wyłącznie JSON:
{{"pytania": [{{"typ": "abcd|pf|open", "pytanie": "…", "opcje": ["…","…","…","…"], "poprawna": 0, "odpowiedz": "…", "wyjasnienie": "…", "cytat": "…", "fragment": 1}}]}}"""


def _parse_questions(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}
    items = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
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
        ans = str(q.get("odpowiedz") or q.get("odpowiedź") or q.get("answer") or "").strip()
        if not ans:
            return None
        out["answer"] = ans
    return out


def generate_exam(library: Path, spec: ExamSpec, llm, model: str, num_ctx: int,
                  progress: Optional[Callable[[str, float], None]] = None,
                  cancel: Optional[threading.Event] = None) -> dict:
    prog = progress or (lambda m, f: None)
    lectures = scope_lectures(library, spec)
    if not lectures:
        raise RuntimeError("W wybranym zakresie nie ma wykładów z gotowymi notatkami.")
    parts, info, src = collect(lectures)
    if not parts:
        raise RuntimeError("Notatki są puste.")
    # fragmenty zaznaczone jako ważne / na egzamin trafiają do losowania częściej
    weights = [3.0 if src[i][2] else 1.0 for i in range(len(parts))]
    types = [t for t in spec.types if t in TYPES] or ["abcd"]
    budget_chars = int(num_ctx * 0.55 * 3)
    questions: list[dict] = []
    seen: set[str] = set()
    used_batches = 0
    pool = list(range(len(parts)))
    while len(questions) < spec.n and used_batches < spec.n // 2 + 6:
        if cancel is not None and cancel.is_set():
            break
        used_batches += 1
        # losowy zestaw fragmentów mieszczący się w kontekście
        chosen, size = [], 0
        cand = pool[:]
        random.shuffle(cand)
        cand.sort(key=lambda i: -weights[i] * random.random())
        for i in cand:
            L = len(parts[i].text) + len(parts[i].title) + 20
            if size + L > budget_chars and chosen:
                continue
            chosen.append(i)
            size += L
            if len(chosen) >= 8:
                break
        chosen.sort()
        k = min(6, spec.n - len(questions) + 1)
        frags = "\n\n".join(f"[{j}] ({parts[i].title})\n{parts[i].text}" for j, i in enumerate(chosen, 1))
        prompt = PROMPT.format(
            k=k, types=", ".join(TYPES[t] for t in types), level=LEVELS.get(spec.level, LEVELS["medium"]),
            instructions=(f"Dodatkowe wskazówki studenta: {spec.instructions.strip()}\n" if spec.instructions.strip() else ""),
            exam_info=(("Informacje o egzaminie podane przez prowadzącego (uwzględnij je):\n- " + "\n- ".join(info[:15]) + "\n")
                       if spec.use_exam_info and info else ""),
            fragments=frags)
        prog(f"Układam pytania… ({len(questions)}/{spec.n})", len(questions) / max(1, spec.n))
        raw = llm.chat(model, [{"role": "user", "content": prompt}], num_ctx=num_ctx, temperature=0.5,
                       json_mode=True, cancel=cancel)
        texts = [parts[i].title + "\n" + parts[i].text for i in chosen]
        for q in _parse_questions(raw):
            nq = _normalize(q, types)
            if not nq:
                continue
            j = verify_quote(nq["quote"], texts) if nq["quote"] else None
            if j is None:
                continue       # brak potwierdzenia w notatce – pytanie odrzucone
            key = re.sub(r"\W+", "", nq["q"].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            gi = chosen[j]
            nq["source"] = {"folder": src[gi][0], "anchor": src[gi][1], "title": parts[gi].title}
            questions.append(nq)
            if len(questions) >= spec.n:
                break
    if not questions:
        raise RuntimeError("Nie udało się ułożyć pytań potwierdzonych w notatkach. Spróbuj ponownie.")
    random.shuffle(questions)
    title = (spec.value if spec.scope == "subject" else lectures[0].meta.title)
    return {"id": time.strftime("%Y%m%d-%H%M%S"), "title": title, "scope": spec.scope, "value": spec.value,
            "created": time.strftime("%Y-%m-%d %H:%M"), "spec": spec.__dict__, "questions": questions,
            "results": []}


GRADE_PROMPT = """Oceń odpowiedź studenta na pytanie otwarte, porównując ją ze wzorcem z notatek.

PYTANIE: {q}
WZORCOWA ODPOWIEDŹ: {ref}
FRAGMENT NOTATKI: "{quote}"
ODPOWIEDŹ STUDENTA: {ans}

Oceń tylko merytorykę (nie styl). Punkty: 2 = poprawna i pełna, 1 = częściowo poprawna, 0 = błędna lub brak.
Zwróć wyłącznie JSON: {{"punkty": 0|1|2, "komentarz": "1–2 zdania: co dobrze, czego brakuje"}}"""


def grade_open(q: dict, answer: str, llm, model: str, num_ctx: int = 8192) -> tuple[int, str]:
    if not answer.strip():
        return 0, "Brak odpowiedzi."
    raw = llm.chat(model, [{"role": "user", "content": GRADE_PROMPT.format(
        q=q["q"], ref=q.get("answer", ""), quote=q.get("quote", ""), ans=answer.strip())}],
        num_ctx=num_ctx, temperature=0.0, json_mode=True)
    try:
        d = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        d = json.loads(m.group(0)) if m else {}
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
