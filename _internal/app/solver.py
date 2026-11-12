"""„Rozwiąż test”: gotowy test (np. 100 pytań abcd) rozwiązany WYŁĄCZNIE na podstawie notatek z wybranego zakresu.

Kroki:
  1. Odczyt (wklejka, .txt, .docx, .pdf z warstwą tekstu) i rozpoznanie pytań – najpierw parser regułowy
     (parse_test), a gdy nie daje rady – AI dzieli tekst na pytania partiami (split_with_ai).
     Oryginalna numeracja i oryginalne litery odpowiedzi zostają (wynik używa tych samych liter).
  2. Dla każdego pytania najlepsze kawałki notatek (BM25 na rdzeniach słów jak w qa.rank; zapytanie = treść + opcje).
  3. Model odpowiada partiami (PER_BATCH pytań, każde z własnymi fragmentami), temperatura 0, stały num_ctx
     i ten sam załadowany model co egzamin (exam.EXAM_CTX / KEEP_ALIVE / TIME_BUDGET_S).
  4. Potwierdzenie: cytat musi być we fragmencie (exam.match_quote – dokładnie albo w przybliżeniu) i dotyczyć
     pytania. Bez potwierdzenia → „nie wiem”, a przy włączonym zgadywaniu – odpowiedź oznaczona „?”.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree as ET

from . import exam as EX
from .llm import Cancelled
from .qa import _stems
from .i18n import tr

log = logging.getLogger(__name__)

PER_BATCH = 5                # pytań w jednym wywołaniu modelu
PIECE = 900                  # długość kawałka notatki (znaki) – do wyszukiwania i do promptu
Q_PIECES = 3                 # najwyżej tyle kawałków na pytanie
Q_BUDGET = 2400              # znaków kawałków na pytanie
POOL_BUDGET = 11000          # znaków kawałków w jednej partii (~3,7 tys. tokenów; razem z pytaniami < EXAM_CTX)
TOK_PER_Q = 150              # limit odpowiedzi: tyle tokenów na pytanie (+ zapas)
SPLIT_CHUNK = 3500           # dzielenie tekstu przez AI: tyle znaków na wywołanie
KINDS = ("abcd", "multi", "pf", "open")


# =====================================================================================================================
# Odczyt plików
# =====================================================================================================================
FILE_EXT = (".txt", ".md", ".docx", ".pdf")


def read_file(path) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md", ""):
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "cp1250", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    if ext == ".docx":
        return _read_docx(p)
    if ext == ".pdf":
        return _read_pdf(p)
    raise RuntimeError(tr("Nie umiem odczytać plików {ext}. Wybierz .txt, .docx albo .pdf.", ext=ext or "?"))


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _roman(n: int) -> str:
    out = ""
    for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                 (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += s
            n -= v
    return out


def _fmt_num(n: int, fmt: str) -> str:
    if fmt == "lowerLetter":
        return chr(ord("a") + (n - 1) % 26)
    if fmt == "upperLetter":
        return chr(ord("A") + (n - 1) % 26)
    if fmt == "lowerRoman":
        return _roman(n)
    if fmt == "upperRoman":
        return _roman(n).upper()
    if fmt in ("bullet", "none"):
        return ""
    return str(n)


def _read_docx(p: Path) -> str:
    """Tekst akapitów (także w tabelach) z odtworzoną automatyczną numeracją Worda („1.”, „a)”) – w testach
    numery pytań i litery odpowiedzi to zwykle lista numerowana, której nie ma w samym tekście."""
    try:
        with zipfile.ZipFile(p) as z:
            doc = ET.fromstring(z.read("word/document.xml"))
            try:
                numxml = ET.fromstring(z.read("word/numbering.xml"))
            except KeyError:
                numxml = None
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise RuntimeError(tr("Nie udało się odczytać pliku Word: {e}", e=e)) from e
    levels: dict = {}                 # abstractNumId → {ilvl: (start, fmt, lvlText)}
    nums: dict = {}                   # numId → (abstractNumId, {ilvl: start})
    if numxml is not None:
        for a in numxml.iter(_W + "abstractNum"):
            lv = {}
            for l in a.iter(_W + "lvl"):
                il = int(l.get(_W + "ilvl", "0"))
                st = l.find(_W + "start")
                fm = l.find(_W + "numFmt")
                tx = l.find(_W + "lvlText")
                lv[il] = (int(st.get(_W + "val", "1")) if st is not None else 1,
                          fm.get(_W + "val", "decimal") if fm is not None else "decimal",
                          tx.get(_W + "val", "") if tx is not None else "")
            levels[a.get(_W + "abstractNumId")] = lv
        for n in numxml.iter(_W + "num"):
            ab = n.find(_W + "abstractNumId")
            over = {}
            for o in n.iter(_W + "lvlOverride"):
                so = o.find(_W + "startOverride")
                if so is not None:
                    over[int(o.get(_W + "ilvl", "0"))] = int(so.get(_W + "val", "1"))
            nums[n.get(_W + "numId")] = (ab.get(_W + "val") if ab is not None else None, over)
    counters: dict = {}               # numId → {ilvl: licznik}
    out = []
    for para in doc.iter(_W + "p"):
        texts = []
        for el in para.iter():
            if el.tag == _W + "t":
                texts.append(el.text or "")
            elif el.tag == _W + "tab":
                texts.append(" ")
            elif el.tag in (_W + "br", _W + "cr"):
                texts.append("\n")
        text = "".join(texts)
        prefix = ""
        np_ = para.find(f"{_W}pPr/{_W}numPr")
        if np_ is not None and text.strip():
            nid_el, il_el = np_.find(_W + "numId"), np_.find(_W + "ilvl")
            nid = nid_el.get(_W + "val") if nid_el is not None else None
            il = int(il_el.get(_W + "val", "0")) if il_el is not None else 0
            ab, over = nums.get(nid, (None, {}))
            lv = levels.get(ab, {})
            if nid and nid != "0" and lv:
                c = counters.setdefault(nid, {})
                start = over.get(il, lv.get(il, (1, "", ""))[0])
                c[il] = c.get(il, start - 1) + 1
                for deeper in [k for k in c if k > il]:
                    del c[deeper]
                _st, fmt, lvl_text = lv.get(il, (1, "decimal", f"%{il + 1}."))
                if fmt == "bullet":
                    prefix = "• "
                elif fmt != "none":
                    def sub(m):
                        k = int(m.group(1)) - 1
                        f = lv.get(k, (1, "decimal", ""))[1]
                        return _fmt_num(c.get(k, lv.get(k, (1,))[0]), f)
                    prefix = re.sub(r"%(\d)", sub, lvl_text or f"%{il + 1}.") + " "
        out.append(prefix + text)
    return "\n".join(out)


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader     # opcjonalna biblioteka (nie ma jej w requirements)
    except ImportError as e:
        raise RuntimeError(tr("Odczyt PDF nie jest jeszcze dostępny. Otwórz PDF, zaznacz cały tekst (Ctrl+A), "
                              "skopiuj i wklej go w pole „Wklej pytania”.")) from e
    try:
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(tr("Nie udało się odczytać pliku PDF: {e}", e=e)) from e
    if not text.strip():
        raise RuntimeError(tr("Ten PDF nie ma warstwy tekstu (to skan). Wklej pytania jako tekst."))
    return text


# =====================================================================================================================
# Rozpoznawanie pytań – parser regułowy
# =====================================================================================================================
# Pytanie: {"nr": "12", "text": "…", "kind": "abcd|multi|pf|open", "options": [["a", "…"], …], "auto": bool}
#   auto=True – litery nadane przez program (w teście opcje nie miały liter, np. MS Forms).
#   pf bez opcji – odpowiedź „P” / „F”.

# i18n: nie – wzorce tekstu testów (Moodle, MS Forms, Google Forms – po polsku i angielsku)
_JUNK = re.compile(r"^(?:" + "|".join([
    r"nie udzielono (?:jeszcze )?odpowiedzi", r"not (?:yet )?answered", r"odpowied[zź] zapisana", r"answer saved",
    r"(?:punkty|punkt[óo]w|points|pkt\.?|marked out of|marks?|ocena|grade)\s*[:.]?\s*[\d,./ ]*(?:(?:z|out of)\s*[\d,.]+)?",
    r"(?:uzyskano|max(?:imum)?\.?|maks(?:ymalnie)?\.?)\s*[\d,.]+.*", r"\(?\s*[\d,.]+\s*(?:pkt\.?|punkt(?:y|ów)?|points?|pts?\.?)\s*\)?",
    r"oznacz pytanie", r"flag(?:ged)? question", r"usu[nń] flag[eę]", r"remove flag", r"tre[sś][cć] pytania",
    r"question text", r"wyczy[sś][cć] (?:m[oó]j wyb[oó]r|zaznaczenie|wyb[oó]r)", r"clear (?:my )?(?:choice|selection)",
    r"\*+", r"wymagane", r"required", r"wprowad[zź] (?:swoj[aą] )?odpowied[zź]\.?", r"enter your answer\.?",
    r"twoja odpowied[zź]:?", r"your answer:?", r"(?:nast[eę]pna|poprzednia) strona", r"(?:next|previous) page",
    r"zako[nń]cz (?:podej[sś]cie|test).*", r"finish (?:attempt|review).*", r"przejd[zź] do.*", r"pozosta[lł]y czas.*",
    r"time left.*", r"nawigacja .*quiz.*", r"quiz navigation", r"\d+\s*/\s*\d+", r"strona \d+(?: z \d+)?",
    r"page \d+(?: of \d+)?", r"(?:prawid[lł]owa|poprawna) odpowied[zź] (?:to|jest)\b.*",
    r"the correct answers? (?:is|are)\b.*", r"(?:tw[oó]j )?wynik:\s*[\d,.%/ ]+", r"(?:single|multiple) choice",
    r"pytanie (?:jednokrotnego|wielokrotnego) wyboru", r"(?:wybierz|zaznacz) (?:jedn[aą]|odpowied[zź]).{0,25}:",
    r"select one:?", r"choose one:?", r"select one or more:?", r"(?:wybierz|zaznacz) co najmniej jedn[aą].{0,20}:?",
    r"inne:?", r"other:?", r"opcja \d+",
]) + r")$", re.IGNORECASE)
# i18n: nie – wzorce tekstu testów
_MULTI = re.compile(r"co najmniej jedn|wszystkie (?:poprawne|prawid|w[lł]a[sś]ciwe)|wielokrotnego wyboru|wi[eę]cej "
                    r"ni[zż] jedn|kilka (?:poprawnych|odpowiedzi)|jedn[aą] lub wi[eę]cej|one or more|select all|"
                    r"choose all|all that apply|more than one|multiple (?:answers|correct)", re.IGNORECASE)
# i18n: nie – wzorce tekstu testów
_PF_TEXT = re.compile(r"prawda\s*(?:/|czy|lub|albo|-)\s*fa[lł]sz|\(\s*p\s*/\s*f\s*\)|\bp\s*/\s*f\b|true\s*(?:/|or)\s*false"
                      r"|\(\s*t\s*/\s*f\s*\)|\bt\s*/\s*f\b", re.IGNORECASE)
# i18n: nie – wzorce tekstu testów
_PF_WORDS = {"prawda": "P", "true": "P", "tak": "P", "p": "P", "t": "P", "fałsz": "F", "falsz": "F", "false": "F",
             "nie": "F", "f": "F"}
# i18n: nie – wzorce tekstu testów
_START_WORD = re.compile(r"^(?:pytanie|pyt\.|zadanie|zad\.|question|quest\.|q|nr\.?)\s*(\d{1,3})\s*[.):\-–]?\s*(.*)$",
                         re.IGNORECASE)
_START_NUM = re.compile(r"^(\d{1,3})\s*[.)](?!\d)\s*(.*)$")
_OPT = re.compile(r"^(?:\(([a-hA-H])\)|([a-hA-H])\s*\)|([a-hA-H])\s*[.:](?=\s|$))\s*(.*)$")
_BULLET = re.compile(r"^[○◯◦●•☐□■▢⚪◻▪❍-]\s*(.+)$")
# i18n: nie – wzorce / klucze JSON z promptu
_PTS_TAIL = re.compile(r"\s*[\(\[]\s*[\d,.]+\s*(?:pkt\.?|punkt(?:y|ów)?|points?|pts?\.?)\s*[\)\]]\s*\*?\s*$|\s+\*$",
                       re.IGNORECASE)


def _opt_letter(m) -> Optional[str]:
    return (m.group(1) or m.group(2) or m.group(3)) if m else None


def _clean(text: str) -> list[str]:
    text = (text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").replace("\t", " ")
            .replace("​", "").replace("﻿", ""))
    return [re.sub(r" {2,}", " ", l).strip() for l in text.split("\n")]


def _fold(s: str) -> str:
    return re.sub(r"[\s.:;!]+$", "", s.strip().lower())


def _starts(lines: list[str]) -> list[tuple[int, str, str]]:
    """Początki pytań: (nr linii, numer, reszta linii). Numery muszą rosnąć (dopuszczalne luki) – „2.” w środku
    treści po pytaniu 7 nie jest nowym pytaniem."""
    out: list[tuple[int, str, str]] = []
    last = 0
    for i, l in enumerate(lines):
        m = _START_WORD.match(l) or _START_NUM.match(l)
        if not m:
            continue
        n = int(m.group(1))
        if out and not (last < n <= last + 25):
            continue
        if not out and n > 25:
            continue
        rest = m.group(2).strip()
        # „1)” z samym jednym słowem jako opcja listy w treści – zostaw (pytanie ma treść albo stoi samo)
        out.append((i, str(n), rest))
        last = n
    return out


def _inline_options(text: str) -> tuple[str, list]:
    """„Co to jest X? a) foo b) bar c) baz” → („Co to jest X?”, [[a, foo], [b, bar], [c, baz]])."""
    for pat, need in ((r"(?:(?<=\s)|^)\(?([a-hA-H])\)\s+", 2), (r"(?:(?<=\s)|^)([a-hA-H])[.:]\s+", 3)):
        ms = list(re.finditer(pat, text))
        best: list = []
        for k, m in enumerate(ms):
            if m.group(1).lower() != "a":
                continue
            seq = [m]
            for m2 in ms[k + 1:]:
                if m2.group(1).lower() == chr(ord(seq[-1].group(1).lower()) + 1) and \
                        m2.group(1).isupper() == m.group(1).isupper():
                    seq.append(m2)
            if len(seq) > len(best):
                best = seq
        if len(best) >= need:
            q = text[:best[0].start()].strip()
            opts = []
            for k, m in enumerate(best):
                end = best[k + 1].start() if k + 1 < len(best) else len(text)
                opts.append([m.group(1), text[m.end():end].strip(" ;,")])
            if all(o[1] for o in opts):
                return q, opts
    return text, []


def _block(nr: str, lines: list[str]) -> Optional[dict]:
    """Jedno pytanie z jego linii (bez śmieci): treść, opcje i rodzaj."""
    instr = " ".join(lines)
    multi = bool(_MULTI.search(instr))
    body = [l for l in lines if l and not _JUNK.match(l)]
    body = [_PTS_TAIL.sub("", l) for l in body]
    body = [l for l in body if l]
    if not body:
        return None
    q_lines: list[str] = []
    opts: list = []
    expect = None                    # następna oczekiwana litera
    pending = None                   # litera stojąca sama w linii (Moodle: „a.” / „mitochondrium”)
    auto = False
    for l in body:
        m = _OPT.match(l)
        letter = _opt_letter(m)
        if m and (expect is None and letter.lower() == "a" or
                  expect is not None and letter == expect):
            txt = (m.group(4) or "").strip()
            if txt:
                opts.append([letter, txt])
            else:
                pending = letter
            expect = chr(ord(letter) + 1)
            continue
        if pending:
            opts.append([pending, l])
            pending = None
            continue
        b = _BULLET.match(l)
        if b and (not opts or auto):
            if not opts and not q_lines:
                q_lines.append(l)
                continue
            auto = True
            opts.append([chr(ord("a") + len(opts)), b.group(1).strip()])
            continue
        if opts:
            opts[-1][1] += " " + l     # opcja w kilku liniach
        else:
            q_lines.append(l)
    if pending:
        opts.append([pending, ""])
    opts = [o for o in opts if o[1]]
    text = " ".join(q_lines).strip()
    if len(opts) < 2:               # pojedyncza „opcja” (np. „A. Einstein uważał…”) to część treści
        text = " ".join(body).strip()
        opts, auto = [], False
        text, opts = _inline_options(text)
    if not opts and len(q_lines) >= 2 and {_PF_WORDS.get(_fold(l)) for l in q_lines[-2:]} == {"P", "F"}:
        # Moodle / Forms: „Prawda” i „Fałsz” jako dwie ostatnie linie – pytanie prawda/fałsz bez liter
        return {"nr": nr, "text": " ".join(q_lines[:-2]).strip() or text, "kind": "pf", "options": [], "auto": False}
    if not opts and len(q_lines) >= 3:
        # MS Forms / Google Forms: opcje bez liter, każda w osobnej linii pod pytaniem
        head = None
        for k in range(len(q_lines) - 2, -1, -1):
            if re.search(r"[?:]\s*(?:\([^)]*\)\s*)*$", q_lines[k]):     # „…? (zaznacz wszystkie poprawne)”
                head = k
                break
        cand = q_lines[head + 1:] if head is not None else []
        if 2 <= len(cand) <= 8 and all(len(c) <= 140 and not c.endswith("?") for c in cand):
            text = " ".join(q_lines[:head + 1])
            opts = [[chr(ord("a") + k), c] for k, c in enumerate(cand)]
            auto = True
    if not text and not opts:
        return None
    kind = "multi" if multi else "abcd"
    if opts:
        words = {_fold(o[1]) for o in opts}
        if len(opts) == 2 and words <= set(_PF_WORDS) and {_PF_WORDS[w] for w in words} == {"P", "F"}:
            kind = "pf"
            if auto:
                opts, auto = [], False      # „Prawda / Fałsz” bez liter – odpowiedź słowem
    elif _PF_TEXT.search(text):
        kind = "pf"
        text = text.strip()
    else:
        kind = "open"
    if kind in ("abcd", "multi") and not opts:
        kind = "open"
    return {"nr": nr, "text": text, "kind": kind, "options": opts, "auto": auto}


def parse_test(text: str) -> list[dict]:
    """Parser regułowy (bez AI). Pytania numerowane („1.”, „1)”, „Pytanie 1”, „Zad. 1”) – albo, gdy numerów
    nie ma, bloki „treść + opcje a) b) c)” oddzielone od siebie."""
    lines = _clean(text)
    starts = _starts(lines)
    blocks: list[tuple[str, list[str]]] = []
    if len(starts) >= 1:
        for k, (i, nr, rest) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
            blocks.append((nr, ([rest] if rest else []) + lines[i + 1:end]))
    else:
        # bez numeracji: nowe pytanie zaczyna się po opcjach (pierwsza linia nie-opcja po „ostatniej” opcji)
        cur: list[str] = []
        seen_opt = False
        for l in lines:
            is_opt = bool(_OPT.match(l)) or bool(_BULLET.match(l))
            if l and not is_opt and seen_opt and not _JUNK.match(l) and (not cur or not cur[-1]):
                blocks.append(("", cur))
                cur, seen_opt = [], False
            cur.append(l)
            seen_opt = seen_opt or is_opt
        if cur:
            blocks.append(("", cur))
        if len(blocks) == 1:          # jeden blok bez opcji – pytania w osobnych akapitach (oddzielone pustą linią)
            paras, cur = [], []
            for l in lines:
                if not l:
                    if cur:
                        paras.append(cur)
                    cur = []
                elif not _JUNK.match(l):
                    cur.append(l)
            if cur:
                paras.append(cur)
            if len(paras) > 1:
                blocks = [("", p) for p in paras]
    out = []
    for nr, bl in blocks:
        q = _block(nr, bl)
        if q:
            out.append(q)
    for k, q in enumerate(out, 1):
        if not q["nr"]:
            q["nr"] = str(k)
    return out


def looks_bad(questions: list[dict], text: str) -> bool:
    """Czy parser „nie dał rady” (wtedy pytania dzieli AI): nic nie znalazł, znalazł dużo mniej pytań niż jest
    znaków zapytania, albo pytania są podejrzanie długie (wszystko w jednym bloku)."""
    body = text.strip()
    n = len(questions)
    if n == 0:
        return len(body) > 30
    qmarks = len(re.findall(r"\?(?=\s|$)", body))
    if qmarks >= 4 and n < 0.5 * qmarks:
        return True
    if len(body) / n > 1500:
        return True
    return sum(1 for q in questions if len(q["text"]) > 900) > max(1, n // 5)


def counts(questions: list[dict]) -> dict:
    c = Counter(q["kind"] for q in questions)
    return {k: c.get(k, 0) for k in KINDS}


def counts_text(questions: list[dict]) -> str:
    """„Rozpoznano 100 pytań (96 abcd, 4 otwarte)”."""
    from .i18n import tn
    c = counts(questions)
    names = {"abcd": lambda n: tr("{n} abcd", n=n),
             "multi": lambda n: tn(n, "{n} wielokrotnego wyboru", "{n} wielokrotnego wyboru", "{n} wielokrotnego wyboru"),
             "pf": lambda n: tr("{n} prawda/fałsz", n=n),
             "open": lambda n: tn(n, "{n} otwarte", "{n} otwarte", "{n} otwartych")}
    parts = [names[k](c[k]) for k in KINDS if c[k]]
    head = tn(len(questions), "Rozpoznano {n} pytanie", "Rozpoznano {n} pytania", "Rozpoznano {n} pytań")
    return head + (f" ({', '.join(parts)})" if parts else "")


def merge(a: dict, b: dict) -> dict:
    """Scal dwa pytania (np. parser rozdzielił jedno na dwa): treść + opcje drugiego dołączone do pierwszego."""
    text = (a["text"] + " " + b["text"]).strip()
    opts = [list(o) for o in a["options"]]
    letters = {o[0].lower() for o in opts}
    for o in b["options"]:
        if o[0].lower() in letters:
            o = [chr(ord("a") + len(opts)) if not o[0].isupper() else chr(ord("A") + len(opts)), o[1]]
        opts.append(list(o))
    kind = a["kind"] if a["kind"] != "open" else (b["kind"] if opts else "open")
    if opts and kind == "open":
        kind = "abcd"
    return {"nr": a["nr"], "text": text, "kind": kind, "options": opts, "auto": a.get("auto") or b.get("auto")}


# =====================================================================================================================
# Rozpoznawanie pytań – AI (gdy parser nie daje rady)
# =====================================================================================================================
# i18n: nie – prompt
SPLIT_PROMPT = """Poniżej jest fragment testu (np. skopiowany ze strony albo z dokumentu). Wypisz z niego wszystkie pytania.

ZASADY:
- Zachowaj oryginalne numery pytań i oryginalne litery odpowiedzi (np. "a", "B"). Gdy odpowiedzi nie mają liter, nadaj im kolejno a, b, c…
- Przepisz treść pytań i odpowiedzi dokładnie, bez poprawiania. NIE odpowiadaj na pytania.
- Pomiń teksty techniczne strony: punkty, „Oznacz pytanie”, „Wybierz jedną odpowiedź”, nawigację, „Wymagane”.
- "typ": "abcd" (jedna poprawna odpowiedź), "wiele" (zaznacz wszystkie poprawne), "pf" (prawda/fałsz bez liter), "otwarte" (bez odpowiedzi do wyboru).
- Pytanie urwane na końcu fragmentu – pomiń.

TEKST:
{text}

Zwróć wyłącznie JSON:
{{"pytania": [{{"nr": "1", "tresc": "…", "typ": "abcd", "opcje": [["a", "…"], ["b", "…"]]}}]}}"""


def _split_chunks(text: str, size: int = SPLIT_CHUNK) -> list[str]:
    """Kawałki ~size znaków, cięte na pustych liniach albo przed linią z numerem pytania."""
    lines = _clean(text)
    out, cur, n = [], [], 0
    for l in lines:
        boundary = not l or bool(_START_WORD.match(l) or _START_NUM.match(l))
        if n > size and boundary and cur:
            out.append("\n".join(cur).strip())
            cur, n = [], 0
        cur.append(l)
        n += len(l) + 1
    if "\n".join(cur).strip():
        out.append("\n".join(cur).strip())
    return out


def _from_ai(d: dict) -> Optional[dict]:
    # i18n: nie – klucze JSON z promptu
    text = str(d.get("tresc") or d.get("treść") or d.get("pytanie") or d.get("question") or "").strip()
    if not text:
        return None
    opts = []
    raw = d.get("opcje") or d.get("options") or []
    if isinstance(raw, dict):
        raw = list(raw.items())
    for k, o in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(o, (list, tuple)) and len(o) >= 2:
            letter, t = str(o[0]).strip(" .)(:"), str(o[1]).strip()
        else:
            letter, t = chr(ord("a") + k), str(o).strip()
            m = _OPT.match(t)
            if m and (m.group(4) or "").strip():
                letter, t = _opt_letter(m), m.group(4).strip()
        if t:
            opts.append([letter[:2] or chr(ord("a") + k), t])
    # i18n: nie – klucze JSON z promptu
    typ = str(d.get("typ") or d.get("type") or "").lower()
    kind = {"abcd": "abcd", "wiele": "multi", "multi": "multi", "pf": "pf", "otwarte": "open", "open": "open"}.get(typ, "")
    if not kind:
        kind = "abcd" if opts else ("pf" if _PF_TEXT.search(text) else "open")
    if kind in ("abcd", "multi") and len(opts) < 2:
        kind = "open"
        opts = []
    if kind == "pf" and opts and not ({_fold(o[1]) for o in opts} <= set(_PF_WORDS)):
        kind = "abcd"
    nr = re.sub(r"\D", "", str(d.get("nr") or d.get("numer") or ""))
    return {"nr": nr, "text": text, "kind": kind, "options": opts, "auto": False}


def split_with_ai(text: str, llm, model: str, num_ctx: int = EX.EXAM_CTX,
                  progress: Optional[Callable[[str, float], None]] = None,
                  cancel: Optional[threading.Event] = None) -> list[dict]:
    prog = progress or (lambda m, f: None)
    parts = _split_chunks(text)
    out: list[dict] = []
    seen: set = set()
    for k, chunk in enumerate(parts):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        prog(tr("AI rozpoznaje pytania… część {k} z {n}", k=k + 1, n=len(parts)), k / max(1, len(parts)))
        raw = llm.chat(model, [{"role": "user", "content": SPLIT_PROMPT.format(text=chunk)}], num_ctx=num_ctx,
                       temperature=0.0, json_mode=True, cancel=cancel, keep_alive=EX.KEEP_ALIVE,
                       num_predict=int(len(chunk) / 2.2) + 300, stop_json=True)
        # i18n: nie – wzorce / klucze JSON z promptu
        for d in EX._parse_questions(raw) or EX._salvage(raw, ("tresc", "treść")):
            q = _from_ai(d)
            if not q:
                continue
            key = (q["nr"], re.sub(r"\W+", "", q["text"].lower())[:60])
            if key in seen or (q["nr"] and any(x["nr"] == q["nr"] for x in out)):
                continue
            seen.add(key)
            out.append(q)
    for k, q in enumerate(out, 1):
        if not q["nr"]:
            q["nr"] = str(k)
    return out


# =====================================================================================================================
# Wyszukiwanie fragmentów notatek
# =====================================================================================================================
def _pieces(text: str, size: int = PIECE) -> list[str]:
    """Sekcja notatki → kawałki ~size znaków (akapity razem; za długi akapit – po liniach / zdaniach)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for p in paras:
        if len(p) <= size * 1.3:
            units.append(p)
            continue
        for l in p.split("\n"):
            if len(l) <= size * 1.3:
                units.append(l)
            else:
                units += [s for s in re.split(r"(?<=[.!?])\s+", l) if s.strip()]
    out, cur = [], ""
    for u in units:
        if cur and len(cur) + len(u) + 2 > size:
            out.append(cur)
            cur = ""
        cur = (cur + "\n\n" + u) if cur else u
    if cur:
        out.append(cur)
    return out


class NoteIndex:
    """BM25 na rdzeniach słów (jak qa.rank), ale z gotowym indeksem – liczony raz na cały test, a nie na pytanie."""

    def __init__(self, parts, src):
        self.parts, self.src = parts, src
        self.pieces: list[tuple[int, str]] = []
        for pi, c in enumerate(parts):
            for t in _pieces(c.text):
                self.pieces.append((pi, t))
        self.docs = [Counter(_stems(parts[pi].title + " " + t)) for pi, t in self.pieces]
        self.lens = [sum(d.values()) for d in self.docs]
        n = len(self.docs) or 1
        self.avg = sum(self.lens) / n or 1
        df = Counter(t for d in self.docs for t in d)
        self.idf = {t: math.log(1 + (n - v + 0.5) / (v + 0.5)) for t, v in df.items()}
        self.post: dict[str, list[int]] = {}
        for i, d in enumerate(self.docs):
            for t in d:
                self.post.setdefault(t, []).append(i)

    def search(self, query: str) -> list[tuple[float, int]]:
        q = set(_stems(query))
        scores: dict[int, float] = {}
        for t in q:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.post[t]:
                tf = self.docs[i][t]
                scores[i] = scores.get(i, 0.0) + idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * self.lens[i] / self.avg))
        return sorted(((s, i) for i, s in scores.items() if s > 0), key=lambda x: (-x[0], x[1]))

    def for_question(self, q: dict) -> list[int]:
        """Najlepsze kawałki dla pytania (treść + wszystkie opcje jako zapytanie), razem do Q_BUDGET znaków."""
        query = q["text"] + " " + " ".join(o[1] for o in q["options"])
        out, used = [], 0
        top = None
        for s, i in self.search(query):
            if top is None:
                top = s
            if s < 0.35 * top and out:
                break
            L = len(self.pieces[i][1])
            if used + L > Q_BUDGET and out:
                continue
            out.append(i)
            used += L
            if len(out) >= Q_PIECES:
                break
        return out

    def title(self, i: int) -> str:
        return self.parts[self.pieces[i][0]].title

    def text(self, i: int) -> str:
        return self.pieces[i][1]

    def source(self, i: int) -> dict:
        pi = self.pieces[i][0]
        return {"folder": self.src[pi][0], "anchor": self.src[pi][1], "title": self.parts[pi].title}


# =====================================================================================================================
# Odpowiadanie
# =====================================================================================================================
# i18n: nie – prompt
KIND_PROMPT = {"abcd": "jednokrotny wybór – podaj jedną literę",
               "multi": "wielokrotny wybór – podaj WSZYSTKIE poprawne litery po przecinku, np. \"a,c\"",
               "pf": "prawda/fałsz – podaj literę",
               "pf_words": "prawda/fałsz – odpowiedz \"prawda\" albo \"fałsz\"",
               "open": "otwarte – krótka odpowiedź (najwyżej 25 słów)"}

# i18n: nie – prompt
SOLVE_PROMPT = """Rozwiązujesz test WYŁĄCZNIE na podstawie fragmentów notatek z wykładów. Przy każdym pytaniu podane są numery fragmentów, które go dotyczą.

ZASADY:
- Odpowiedź wybierz tylko wtedy, gdy wynika z fragmentów. Nie używaj własnej wiedzy.
- Gdy fragmenty nie rozstrzygają pytania, wpisz "odpowiedz": "nie wiem". Błędna odpowiedź jest gorsza niż „nie wiem”.{guess}
- Używaj liter odpowiedzi DOKŁADNIE takich jak w pytaniu.
- "cytat": przepisz SŁOWO W SŁOWO jedno zdanie fragmentu (najwyżej 30 słów), z którego wynika odpowiedź; "fragment": jego numer.
- "pewnosc": "wysoka" (fragment mówi to wprost), "srednia" (trzeba wywnioskować), "niska".
- "uzasadnienie": jedno krótkie zdanie. Pisz w języku pytań.

FRAGMENTY NOTATEK:
{fragments}

PYTANIA:
{questions}

Zwróć wyłącznie JSON z odpowiedzią na każde pytanie (pole "id" jak przy pytaniu):
{{"odpowiedzi": [{{"id": "Q1", "odpowiedz": "b", "pewnosc": "wysoka", "fragment": 1, "cytat": "…", "uzasadnienie": "…"{guess_field}}}]}}"""
# i18n: nie – prompt
GUESS_RULE = ("\n- Gdy wpisujesz \"nie wiem\", w polu \"zgaduje\" podaj najbardziej prawdopodobną odpowiedź z wiedzy "
              "ogólnej (w tym samym formacie). Gdy odpowiedź jest w notatkach, pole \"zgaduje\" zostaw puste.")

# i18n: nie – odpowiedzi modelu
_DONT_KNOW = re.compile(r"^\s*(?:nie wiem|nie wiadomo|brak|brak danych|brak informacji|nieznana|\?+|-+|n/?a|none|"
                        r"unknown|don'?t know|i don'?t know|null)\s*\.?\s*$", re.IGNORECASE)
_CONF = {"wysoka": "high", "high": "high", "srednia": "medium", "średnia": "medium", "medium": "medium",
         "niska": "low", "low": "low"}
_RANK = {"high": 2, "medium": 1, "low": 0}


def _letters(q: dict) -> dict:
    return {o[0].lower(): o[0] for o in q["options"]}


def normalize_answer(raw, q: dict) -> Optional[str]:
    """Odpowiedź modelu → „b” / „a,c” / „P” / „F” / tekst (otwarte); None = „nie wiem” albo nieprawidłowa."""
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = ",".join(str(x) for x in raw)
    s = str(raw).strip()
    if not s or _DONT_KNOW.match(s):
        return None
    if q["options"]:
        letters = _letters(q)
        low = s.lower()
        # i18n: nie – wzorce / klucze JSON z promptu
        found = re.findall(r"(?<![a-ząćęłńóśźż0-9])([a-h])(?![a-ząćęłńóśźż0-9])", low)
        if not found:              # model przepisał treść odpowiedzi zamiast litery
            for o in q["options"]:
                if _fold(o[1]) == _fold(s):
                    found = [o[0].lower()]
                    break
        found = list(dict.fromkeys(found))
        if not found or any(f not in letters for f in found):
            return None
        if q["kind"] != "multi" and len(found) != 1:
            return None
        return ",".join(letters[f] for f in sorted(found))
    if q["kind"] == "pf":
        w = _fold(s).split()[0] if _fold(s) else ""
        return _PF_WORDS.get(w)
    return re.sub(r"\s+", " ", s)[:300]


def _relevant(quote: str, q: dict, ans: str) -> bool:
    """Cytat musi dotyczyć pytania: ma wspólne słowa z treścią pytania albo z wybraną odpowiedzią."""
    qs = set(_stems(quote))
    chosen = " ".join(o[1] for o in q["options"] if o[0] in ans.split(",")) if q["options"] else ans
    ref = set(_stems(q["text"] + " " + chosen))
    need = 2 if len(qs) >= 6 else 1
    return len(qs & ref) >= need


def _parse_answers(raw: str) -> list[dict]:
    items = EX._parse_questions(raw)
    # i18n: nie – wzorce / klucze JSON z promptu
    items = [x for x in items if "id" in x or "odpowiedz" in x or "odpowiedź" in x]
    return items or EX._salvage(raw, ("id", "odpowiedz"))


def _q_block(qid: str, q: dict, frag_nums: list[int]) -> str:
    kind = "pf_words" if q["kind"] == "pf" and not q["options"] else q["kind"]
    # i18n: nie – prompt
    head = f"[{qid}] {KIND_PROMPT[kind]}; fragmenty: {', '.join(map(str, frag_nums)) or 'brak'}"
    lines = [head, q["text"]]
    lines += [f"{o[0]}) {o[1]}" for o in q["options"]]
    return "\n".join(lines)


def _eta_text(done: int, n: int, secs: Optional[float]) -> str:
    if secs is None:
        return tr("Rozwiązuję test… {n}/{n2} · szacuję czas…", n=done, n2=n)
    if secs < 60:
        return tr("Rozwiązuję test… {n}/{n2} · zostało mniej niż minuta", n=done, n2=n)
    return tr("Rozwiązuję test… {n}/{n2} · zostało około {m} min", n=done, n2=n, m=round(secs / 60))


def _empty(status: str) -> dict:
    return {"status": status, "answer": "", "confidence": "", "quote": "", "why": "", "source": None}


def new_test(questions: list[dict], scope: str, value: str, title: str, guess: bool, source_name: str = "") -> dict:
    return {"id": time.strftime("%Y%m%d-%H%M%S"), "title": title, "created": time.strftime("%Y-%m-%d %H:%M"),
            "scope": scope, "value": value, "guess": guess, "source_name": source_name, "model": "",
            "questions": questions, "results": [None] * len(questions), "timed_out": False, "stats": {}}


def solve_test(library: Path, test: dict, llm, model: str, num_ctx: int = EX.EXAM_CTX,
               progress: Optional[Callable[[str, float], None]] = None,
               cancel: Optional[threading.Event] = None, budget_s: float = EX.TIME_BUDGET_S,
               prepare: bool = True, on_results: Optional[Callable[[dict], None]] = None,
               save: Optional[Callable[[dict], None]] = None) -> dict:
    """Rozwiązuje pytania testu, które nie mają jeszcze wyniku (można dokończyć test przerwany albo ucięty
    limitem czasu). test["results"][i] = {"status": notes|guess|unknown|timeout, "answer", "confidence",
    "quote", "why", "source", "match"}. on_results({indeks: wynik}) – wyniki partii na bieżąco."""
    prog = progress or (lambda m, f: None)
    lectures = EX.scope_lectures(library, EX.ExamSpec(scope=test["scope"], value=test["value"]))   # "all" = wszystkie
    if not lectures:
        raise RuntimeError(tr("W wybranym zakresie nie ma wykładów z gotowymi notatkami."))
    parts, _info, src = EX.collect(lectures)
    if not parts:
        raise RuntimeError(tr("Notatki są puste."))
    qs = test["questions"]
    results = test.setdefault("results", [None] * len(qs))
    if len(results) != len(qs):
        results[:] = (results + [None] * len(qs))[:len(qs)]
    guess = bool(test.get("guess"))
    num_ctx = min(num_ctx, EX.EXAM_CTX)
    t_start = time.monotonic()
    dl = EX._Deadline(cancel, t_start + budget_s)
    test["model"] = model
    if prepare:
        prog(tr("Zwalniam pamięć po innych modelach i ładuję model AI…"), -1)
        freed = llm.unload_others(model) if hasattr(llm, "unload_others") else []
        load_s = llm.preload(model, num_ctx, EX.KEEP_ALIVE) if hasattr(llm, "preload") else 0.0
        log.info("Test: model %s, num_ctx %d, zwolnione: %s, ładowanie %.1f s", model, num_ctx,
                 ", ".join(freed) or "–", load_s)
    prog(tr("Szukam w notatkach fragmentów do pytań…"), -1)
    index = NoteIndex(parts, src)
    todo = [i for i, r in enumerate(results) if r is None or r.get("status") == "timeout"]
    n_all = len(qs)
    stats = test.setdefault("stats", {})
    stats.setdefault("calls", 0)
    picks: dict[int, list[int]] = {}
    no_frag = []
    for i in todo:
        picks[i] = index.for_question(qs[i])
        if not picks[i] and not guess:
            no_frag.append(i)
    if no_frag:                       # nic w notatkach nie pasuje – „nie wiem” bez pytania modelu
        upd = {}
        for i in no_frag:
            results[i] = _empty("unknown")
            results[i]["why"] = tr("W notatkach z tego zakresu nie ma nic na ten temat.")
            upd[i] = results[i]
        todo = [i for i in todo if i not in upd]
        if on_results:
            on_results(upd)
    # partie: kolejne pytania, aż PER_BATCH albo POOL_BUDGET znaków fragmentów
    batches: list[list[int]] = []
    cur: list[int] = []
    pool: set = set()
    for i in todo:
        new = set(picks[i]) - pool
        size = sum(len(index.text(p)) for p in pool | new)
        if cur and (len(cur) >= PER_BATCH or size > POOL_BUDGET):
            batches.append(cur)
            cur, pool = [], set()
            new = set(picks[i])
        cur.append(i)
        pool |= new
    if cur:
        batches.append(cur)
    timed_out = False
    gen_s, gen_n = 0.0, 0
    done = sum(1 for r in results if r is not None and r.get("status") != "timeout")
    for b_no, batch in enumerate(batches):
        if dl.user():
            break
        if dl.left() <= 0 or (gen_n and dl.left() < 0.5 * gen_s / gen_n * len(batch)):
            timed_out = True
            break
        pool_ids: list[int] = []
        for i in batch:
            for p in picks[i]:
                if p not in pool_ids:
                    pool_ids.append(p)
        num = {p: k for k, p in enumerate(pool_ids, 1)}
        frags = "\n\n".join(f"[{num[p]}] ({index.title(p)})\n{index.text(p)}" for p in pool_ids) or "(brak)"  # i18n: nie
        qtext = "\n\n".join(_q_block(f"Q{k}", qs[i], [num[p] for p in picks[i]]) for k, i in enumerate(batch, 1))
        prompt = SOLVE_PROMPT.format(guess=GUESS_RULE if guess else "", fragments=frags, questions=qtext,
                                     guess_field=', "zgaduje": ""' if guess else "")
        per_q = gen_s / gen_n if gen_n else None
        t_b = time.monotonic()
        left_n = sum(len(b) for b in batches[b_no:])

        def eta() -> Optional[float]:
            if per_q is None:
                return None
            return max(0.0, min(left_n * per_q - (time.monotonic() - t_b), dl.left()))
        prog(_eta_text(done, n_all, eta()), done / max(1, n_all))
        got: list[str] = []
        last = [t_b]

        def on_tok(tok: str) -> None:
            got.append(tok)
            now = time.monotonic()
            if now - last[0] > 2.0:
                last[0] = now
                prog(_eta_text(done, n_all, eta()), done / max(1, n_all))
        try:
            raw = llm.chat(model, [{"role": "user", "content": prompt}], num_ctx=num_ctx, temperature=0.0,
                           json_mode=True, cancel=dl, keep_alive=EX.KEEP_ALIVE, on_token=on_tok,
                           num_predict=TOK_PER_Q * len(batch) + 120, stop_json=True)
        except Cancelled:
            if dl.user():
                if save:
                    save(test)          # to, co już jest, zostaje – test można potem dokończyć
                raise
            timed_out = True
            raw = "".join(got)
        dt = time.monotonic() - t_b
        items = _parse_answers(raw)
        by_id = {}
        for k, d in enumerate(items):
            qid = str(d.get("id") or "").strip().upper().lstrip("[").rstrip("]")
            if not re.fullmatch(r"Q\d+", qid):
                qid = f"Q{k + 1}"
            by_id.setdefault(qid, d)
        texts = [index.title(p) + "\n" + index.text(p) for p in pool_ids]
        upd = {}
        b_stat = Counter()
        for k, i in enumerate(batch, 1):
            d = by_id.get(f"Q{k}")
            if d is None:
                if timed_out:
                    continue             # nie zdążyło przyjść – zostaje do dokończenia
                r = _empty("unknown")
                r["why"] = tr("Model nie podał odpowiedzi na to pytanie.")
                b_stat["missing"] += 1
            else:
                r = _judge(qs[i], d, picks[i], num, texts, pool_ids, index, guess)
                b_stat[r["status"]] += 1
            results[i] = r
            upd[i] = r
            done += 1
        if not timed_out:
            gen_s += dt
            gen_n += len(batch)
        stats["calls"] += 1
        if on_results and upd:
            on_results(upd)
        if save:
            save(test)
        st = getattr(llm, "last_stats", None) or {}
        log.info("Test partia %d/%d: %d pytań, %d fragm., prompt %d znaków (prompt_eval %s tok. w %s s), "
                 "odpowiedź %s tok. w %s s, razem %.1f s; %s", b_no + 1, len(batches), len(batch), len(pool_ids),
                 len(prompt), st.get("prompt_eval_count", "?"), EX._f(st.get("prompt_eval_s")),
                 st.get("eval_count", st.get("chunks", "?")), EX._f(st.get("eval_s")), dt,
                 ", ".join(f"{k} {v}" for k, v in b_stat.items()) or "0")
        if timed_out:
            break
    if timed_out:
        for i, r in enumerate(results):
            if r is None:
                results[i] = _empty("timeout")
    test["timed_out"] = timed_out
    elapsed = time.monotonic() - t_start
    stats["seconds"] = round(stats.get("seconds", 0) + elapsed)
    c = Counter((r or {}).get("status", "pending") for r in results)
    stats["counts"] = dict(c)
    log.info("Test gotowy: %d pytań w %.0f s: %s%s", n_all, elapsed, dict(c), " – koniec czasu" if timed_out else "")
    if save:
        save(test)
    return test


def _judge(q: dict, d: dict, own: list[int], num: dict, texts: list[str], pool_ids: list[int],
           index: NoteIndex, guess: bool) -> dict:
    """Ocena odpowiedzi modelu na jedno pytanie: poprawny format, cytat potwierdzony we fragmencie i dotyczący
    pytania. Inaczej „nie wiem” (albo zgadnięta odpowiedź „?”, gdy zgadywanie jest włączone)."""
    # i18n: nie – klucze JSON z promptu
    ans = normalize_answer(d.get("odpowiedz", d.get("odpowiedź", d.get("answer"))), q)
    quote = str(d.get("cytat") or d.get("quote") or "").strip()
    why = str(d.get("uzasadnienie") or d.get("why") or "").strip()
    # i18n: nie – wzorce / klucze JSON z promptu
    conf = _CONF.get(str(d.get("pewnosc") or d.get("pewność") or "").strip().lower(), "medium")
    r = _empty("unknown")
    r["why"] = why
    if ans is not None and quote:
        try:
            hint = int(d.get("fragment")) - 1
        except (TypeError, ValueError):
            hint = None
        # najpierw własne fragmenty pytania, potem reszta partii
        order = [num[p] - 1 for p in own] + [k for k in range(len(texts)) if k not in [num[p] - 1 for p in own]]
        j, how = EX.match_quote(quote, [texts[k] for k in order], order.index(hint) if hint in order else None)
        if j is not None and _relevant(quote, q, ans):
            p = pool_ids[order[j]]
            if how == "approx" and conf == "high":
                conf = "medium"
            r.update(status="notes", answer=ans, confidence=conf, quote=quote, source=index.source(p), match=how)
            return r
        r["why"] = tr("Odpowiedź nie ma potwierdzenia w notatkach.") + (f" {why}" if why else "")
    if guess:
        g = ans if ans is not None else normalize_answer(d.get("zgaduje") or d.get("guess"), q)
        if g is not None:
            r.update(status="guess", answer=g, confidence="low")
            return r
    if ans is None and not r["why"]:
        r["why"] = tr("Fragmenty notatek nie rozstrzygają tego pytania.")
    return r


# =====================================================================================================================
# Wynik: zwięzła lista, eksport, zapis
# =====================================================================================================================
def answer_label(q: dict, r: Optional[dict]) -> str:
    """„b”, „a,c”, „prawda”, „„krótka odpowiedź””, „nie wiem”, „a?” (zgadnięte)."""
    if not r or r.get("status") not in ("notes", "guess") or not r.get("answer"):
        return tr("nie wiem")
    a = r["answer"]
    if q["kind"] == "pf" and not q["options"]:
        a = tr("prawda") if a == "P" else tr("fałsz")
    elif not q["options"]:
        short = a if len(a) <= 80 else a[:77].rstrip() + "…"
        a = f"„{short}”"
    return a + ("?" if r["status"] == "guess" else "")


def compact(test: dict, pending: Optional[str] = None) -> str:
    """„1 = b, 2 = c, 3 = nie wiem, 4 = a?” – do wklejenia. pending – znak dla pytań jeszcze bez wyniku (w trakcie
    rozwiązywania); domyślnie „nie wiem”."""
    return ", ".join(f"{q['nr']} = {pending if r is None and pending else answer_label(q, r)}"
                     for q, r in zip(test["questions"], test.get("results", [])))


def summary(test: dict) -> dict:
    c = Counter((r or {}).get("status", "pending") for r in test.get("results", []))
    return {"notes": c.get("notes", 0), "guess": c.get("guess", 0), "unknown": c.get("unknown", 0),
            "timeout": c.get("timeout", 0) + c.get("pending", 0), "total": len(test["questions"])}


def conf_name(c: str) -> str:
    return {"high": tr("wysoka"), "medium": tr("średnia"), "low": tr("niska")}.get(c, "")


def export_txt(test: dict) -> str:
    s = summary(test)
    out = [test.get("title", ""), f"{test.get('created', '')} · {test.get('model', '')}", "",
           tr("Odpowiedzi z notatek: {a} · zgadnięte: {g} · nie wiem: {u}", a=s["notes"], g=s["guess"],
              u=s["unknown"] + s["timeout"]), "", compact(test), "", "-" * 60, ""]
    for q, r in zip(test["questions"], test.get("results", [])):
        out.append(f"{q['nr']}. {q['text']}")
        for o in q["options"]:
            out.append(f"   {o[0]}) {o[1]}")
        line = tr("   Odpowiedź: {a}", a=answer_label(q, r))
        if r and r.get("confidence"):
            line += tr(" (pewność: {c})", c=conf_name(r["confidence"]))
        out.append(line)
        if r and r.get("quote"):
            src = (r.get("source") or {}).get("title", "")
            out.append(f"   „{r['quote']}”" + (f" – {src}" if src else ""))
        if r and r.get("status") == "timeout":
            out.append(tr("   Nie zdążyłem odpowiedzieć (koniec czasu)."))
        elif r and r.get("why"):
            out.append(f"   {r['why']}")
        out.append("")
    return "\n".join(out)


def tests_dir(library: Path) -> Path:
    p = Path(library) / ".testy"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_test(library: Path, test: dict) -> None:
    path = tests_dir(library) / f"{test['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(test, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def list_tests(library: Path) -> list[dict]:
    out = []
    for f in sorted(tests_dir(library).glob("*.json"), reverse=True):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def delete_test(library: Path, test_id: str) -> None:
    (tests_dir(library) / f"{test_id}.json").unlink(missing_ok=True)
