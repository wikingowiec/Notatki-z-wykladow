"""Sprawdza tłumaczenia interfejsu (app/i18n.py, app/i18n_en.py).

    python _internal/tools/i18n_check.py            # brakujące tłumaczenia + polskie teksty bez tr()
    python _internal/tools/i18n_check.py --stub     # brakujące tłumaczenia jako gotowe wpisy do i18n_en.py

Teksty, które celowo zostają po polsku (np. treść notatek, nazwy folderów), oznacz komentarzem „# i18n: nie”
w tej samej linii albo w linii nad instrukcją, w której jest tekst – albo dodaj plik do POMIŃ."""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
# treść notatek / prompty / język notatki (nie interfejsu) – nie tłumaczymy
POMIŃ = {"prompts.py", "i18n.py", "i18n_en.py", "notes_style.py", "cheatsheet.py", "notes_doc.py", "topics.py",
         "mathrender.py"}
PL_CHARS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
PL_WORDS = re.compile(r"\b(nie|jest|się|na|do|w|z|ze|oraz|lub|albo|brak|plik|pliki|wykład|wykłady|notatki|"
                      r"notatka|fiszki|ustawienia|pobierz|otwórz|zapisz|usuń|dodaj|zamknij|anuluj|gotowe|błąd|"
                      r"tak|ok\.|min|sek|godz|dziś|teraz|model|nagranie|slajd|slajdy|egzamin|pytanie|pytania|"
                      r"odpowiedź|kategoria|kategorie|temat|tematy|start|stop|pauza|zapytaj|nauka|wróć|dalej|"
                      r"wstecz|szukaj|wszystkie|przedmiot|tytuł|data|czas)\b", re.I)


def load_en():
    spec = importlib.util.spec_from_file_location("i18n_en", APP / "i18n_en.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.EN, m.EN_PLURAL


def _fn(n: ast.Call) -> str:
    f = n.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def scan(path: Path):
    src = path.read_text(encoding="utf-8")
    lines = src.split("\n")
    tree = ast.parse(src)
    keys, plurals, loose = [], [], []
    inside = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            inside.add(id(n.body[0].value))
        if not isinstance(n, ast.Call):
            continue
        name = _fn(n)
        if name == "tr" and n.args and isinstance(n.args[0], ast.Constant):
            keys.append((n.args[0].value, n.lineno))
        if name == "tn" and len(n.args) >= 4 and all(isinstance(a, ast.Constant) for a in n.args[1:4]):
            plurals.append((n.args[1].value, n.lineno))
        if name in ("tr", "tn", "getLogger") or (isinstance(n.func, ast.Attribute) and name in
                                                 ("debug", "info", "warning", "error", "exception", "critical")):
            for a in ast.walk(n):
                inside.add(id(a))
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if k is not None:
                    inside.add(id(k))
    stmt_line = {}                      # węzeł → pierwsza linia instrukcji, w której jest
    for st in ast.walk(tree):
        if isinstance(st, ast.stmt):
            for x in ast.walk(st):
                stmt_line[id(x)] = st.lineno     # najgłębsza instrukcja nadpisuje (walk idzie od zewnątrz)

    def marked(n) -> bool:
        lines_ = {n.lineno, stmt_line.get(id(n), n.lineno)}
        return any("i18n: nie" in lines[ln - 1] or (ln > 1 and "i18n: nie" in lines[ln - 2]) for ln in lines_)

    for n in ast.walk(tree):
        if id(n) in inside:
            continue
        if isinstance(n, ast.JoinedStr):
            for a in ast.walk(n):
                inside.add(id(a))
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            text = n.value
        else:
            continue
        t = text.strip()
        if not t or marked(n):
            continue
        if any(c in PL_CHARS for c in t) or (" " in t and PL_WORDS.search(t)):
            loose.append((t, n.lineno))
    return keys, plurals, loose


def duplicates() -> list[str]:
    """Ten sam polski tekst dwa razy w słowniku (Python zostawia ostatni – łatwo o pomyłkę)."""
    import collections
    tree = ast.parse((APP / "i18n_en.py").read_text(encoding="utf-8"))
    keys = [k.value for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.value, ast.Dict)
            for k in n.value.keys if isinstance(k, ast.Constant)]
    return [k for k, c in collections.Counter(keys).items() if c > 1]


def shadowed() -> list[str]:
    """Funkcje, w których zmienna lokalna nazywa się tr / tn – wtedy tr("…") w tej funkcji się wysypie."""
    out = []
    for p in sorted(APP.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            if not isinstance(fn, ast.Lambda):
                names |= {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            for bad in names & {"tr", "tn"}:
                out.append(f"{p.relative_to(APP)}:{fn.lineno} – zmienna lokalna „{bad}” zasłania funkcję {bad}()")
    return out


def bad_params(en: dict, en_pl: dict) -> list[str]:
    """Angielski tekst musi mieć te same parametry {…} co polski – inaczej str.format się wysypie."""
    import string

    def names(t: str) -> set:
        try:
            return {f for _l, f, _s, _c in string.Formatter().parse(t) if f is not None}
        except ValueError as e:
            return {f"<zły format: {e}>"}
    out = []
    for k, v in en.items():
        if names(k) != names(v):
            out.append(f"{k[:70]!r}: {sorted(names(k))} ≠ {sorted(names(v))}")
    for k, pair in en_pl.items():
        for v in pair:
            if not names(v) <= names(k) | {"n"}:
                out.append(f"{k[:70]!r} (mn.): {sorted(names(v))}")
    return out


def main():
    stub = "--stub" in sys.argv
    en, en_pl = load_en()
    for k in duplicates():
        print(f"UWAGA – tekst dwa razy w i18n_en.py: {k!r}")
    for w in shadowed():
        print("BŁĄD –", w)
    for w in bad_params(en, en_pl):
        print("BŁĄD – parametry:", w)
    all_keys, missing, missing_pl, loose_all = set(), [], [], []
    for p in sorted(APP.rglob("*.py")) + [APP.parent / "main.py"]:
        if p.name in POMIŃ:
            continue
        rel = p.relative_to(APP.parent) if p.parent == APP.parent else p.relative_to(APP)
        keys, plurals, loose = scan(p)
        for k, ln in keys:
            all_keys.add(k)
            if k not in en:
                missing.append((k, f"{rel}:{ln}"))
        for k, ln in plurals:
            all_keys.add(k)
            if k not in en_pl:
                missing_pl.append((k, f"{rel}:{ln}"))
        loose_all += [(t, f"{rel}:{ln}") for t, ln in loose]
    seen = set()
    missing = [(k, w) for k, w in missing if not (k in seen or seen.add(k))]
    if stub:
        for k, w in missing:
            print(f"    {k!r}: {k!r},   # {w}")
        for k, w in missing_pl:
            print(f"    {k!r}: ({k!r}, {k!r}),   # {w}")
        return
    print(f"Teksty w tr()/tn(): {len(all_keys)}, tłumaczenia: {len(en)} + {len(en_pl)} (liczba mnoga)")
    print(f"\nBrak tłumaczenia ({len(missing)} + {len(missing_pl)}):")
    for k, w in missing + missing_pl:
        print(f"  {w:32} {k[:90]!r}")
    unused = [k for k in en if k not in all_keys] + [k for k in en_pl if k not in all_keys]
    print(f"\nNieużywane tłumaczenia ({len(unused)}):")
    for k in unused:
        print(f"  {k[:100]!r}")
    print(f"\nPolskie teksty bez tr() ({len(loose_all)}) – przetłumacz albo oznacz „# i18n: nie”:")
    for t, w in loose_all:
        print(f"  {w:32} {t[:90]!r}")
    sys.exit(1 if missing or missing_pl else 0)


if __name__ == "__main__":
    main()
