"""Wygląd notatek: zakreślenia ==…==, ramki (Definicja, Wzór, Przykład, Ważne, Na slajdzie), „W skrócie”,
podpisy slajdów i numery tematów.

Notatka zostaje zwykłym Markdownem (da się ją edytować i otworzyć gdziekolwiek):
  ==tekst==                 → zakreślenie
  > **Definicja:** …        → ramka w kolorze rodzaju
  **W skrócie:** …          → wyróżniony akapit na początku tematu
Tu zamieniamy to na HTML – w wersji dla czytnika Qt (tabele z tłem) i dla przeglądarki (CSS)."""
from __future__ import annotations

import html as _html
import re

HIGHLIGHT_RE = re.compile(r"==(?=\S)([^=\n]+?)(?<=\S)==")

# rodzaj ramki: słowa-etykiety (małe litery) → rodzaj
LABELS = {
    "definicja": "def", "definicje": "def", "definition": "def", "definitions": "def",
    "wzór": "formula", "wzory": "formula", "formula": "formula", "formulas": "formula",
    "twierdzenie": "formula", "theorem": "formula",
    "przykład": "example", "przykłady": "example", "example": "example", "examples": "example",
    "ważne": "important", "uwaga": "important", "important": "important", "note": "important",
    "zapamiętaj": "important", "remember": "important", "na egzamin": "important",
    "na slajdzie": "slide", "on the slide": "slide",
    "fiszka": "card", "flashcard": "card",
}
LEAD = ("w skrócie", "in short")


def mark_highlights(md: str) -> str:
    """==tekst== → <mark>tekst</mark> (przed zamianą Markdownu na HTML; wzory muszą być już wycięte)."""
    return HIGHLIGHT_RE.sub(lambda m: f"<mark>{m.group(1)}</mark>", md)


def _colors(t) -> dict:
    """Kolor paska i tło ramki dla każdego rodzaju (z tokenów motywu)."""
    from .ui.theme import _SUBJ_DARK, _SUBJ_LIGHT, mix
    pal = _SUBJ_DARK if t.dark else _SUBJ_LIGHT
    f = 0.16 if t.dark else 0.10

    def pair(c):
        return c, mix(t.surface, c, f)
    return {
        "def": pair(t.accent), "formula": pair(pal[3]), "example": pair(pal[1]),
        "important": pair(t.orange), "slide": pair(pal[5]), "card": pair(pal[6]), "": pair(t.text3),
    }


_LABEL_ALT = "|".join(sorted((re.escape(k) for k in LABELS), key=len, reverse=True))
_BOX_START = re.compile(r"(?=<p>\s*<strong>(?:" + _LABEL_ALT + r")\s*:?\s*</strong>)", re.IGNORECASE)


def split_boxes(inner: str) -> list[str]:
    """Kilka ramek pod rząd Markdown skleja w jeden cytat – rozdzielamy je po etykietach."""
    parts = [p.strip() for p in _BOX_START.split(inner)]
    return [p for p in parts if p]


def _split_label(inner: str):
    """'<p><strong>Definicja:</strong> treść…' → ('Definicja', 'def', '<p>treść…')."""
    m = re.match(r"\s*<p>\s*<strong>([^<]{2,30}?)\s*:?\s*</strong>\s*:?\s*", inner)
    if not m:
        return "", "", inner
    label = m.group(1).strip().rstrip(":")
    kind = LABELS.get(label.lower())
    if kind is None:
        return "", "", inner
    rest = "<p>" + inner[m.end():]
    rest = re.sub(r"^<p>\s*(?:<br\s*/?>\s*)*</p>\s*", "", rest)        # etykieta w osobnej linii
    rest = re.sub(r"^<p>\s*<br\s*/?>\s*", "<p>", rest)
    return label, kind, rest


# ---------------------------------------------------------------------------
# Czytnik w aplikacji (QTextBrowser – podzbiór HTML, bez zaokrągleń i cieni)
# ---------------------------------------------------------------------------
def style_qt(body: str, t, num_colors: dict | None = None) -> str:
    colors = _colors(t)
    hl = _mix_hl(t)
    body = body.replace("<mark>", f'<span style="background-color:{hl};">').replace("</mark>", "</span>")

    def box(m):
        return "".join(one(x) for x in split_boxes(m.group(1)))

    def one(inner):
        label, kind, rest = _split_label(inner)
        bar, bg = colors.get(kind, colors[""])
        rest = re.sub(r"<p>", '<p style="margin:0 0 4px 0;">', rest)
        rest = re.sub(r"<(ul|ol)>", r'<\1 style="margin-top:2px; margin-bottom:2px;">', rest)
        head = (f'<p style="margin:0 0 3px 0; color:{bar}; font-size:8.5pt; font-weight:700;">'
                f'{_html.escape(label.upper())}</p>') if label else ""
        return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px; margin-bottom:14px;">'
                f'<tr><td width="4" bgcolor="{bar}"></td>'
                f'<td bgcolor="{bg}" style="padding:10px 16px 8px 14px;">{head}{rest}</td></tr></table>')
    body = re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>", box, body, flags=re.DOTALL)

    # „W skrócie:” – akapit wprowadzający
    lead_re = re.compile(r"<p>\s*<strong>(" + "|".join(LEAD) + r")\s*:?\s*</strong>\s*:?\s*(.*?)</p>",
                         re.IGNORECASE | re.DOTALL)
    body = lead_re.sub(lambda m: (f'<p style="margin:2px 0 12px 0; font-size:11pt; color:{t.text2};">'
                                  f'<span style="color:{t.accent}; font-weight:700;">{m.group(1)}:</span> '
                                  f'{m.group(2)}</p>'), body)
    # numer tematu w nagłówku sekcji
    body = re.sub(r'(<h2[^>]*>(?:<a name="[^"]*"></a>)?)(\d+)\.\s', lambda m: (
        f'{m.group(1)}<span style="color:{(num_colors or {}).get(int(m.group(2)), t.accent)};">{m.group(2)}.</span> '),
        body)
    # linia czasu pod nagłówkiem sekcji
    body = re.sub(r"<p><em>(\d[\d:]*\s*[–-]\s*\d[\d:]*)</em>", lambda m: (
        f'<p style="color:{t.text3}; font-size:9pt; margin:0 0 10px 0;"><span style="color:{t.text3};">'
        f'{m.group(1)}</span>'), body)
    # podpis pod slajdem
    body = re.sub(r'<p>\s*(<img (?![^>]*src="file:)[^>]*?alt="([^"]*)"[^>]*/?>)\s*</p>', lambda m: (
        f'<p style="margin:14px 0 4px 0; line-height:100%;">{m.group(1)}</p>'
        + (f'<p style="margin:0 0 10px 0; color:{t.text3}; font-size:9pt;">{m.group(2)}</p>'
           if m.group(2) and not m.group(2).isdigit() else "")), body)
    return body


def _mix_hl(t) -> str:
    from .ui.theme import mix
    return mix(t.surface, t.highlight, 0.30 if t.dark else 0.50)


# ---------------------------------------------------------------------------
# Eksport do przeglądarki (pełny CSS)
# ---------------------------------------------------------------------------
WEB_CSS = """
:root{--paper:#FFFEFA;--bg:#F6F3EC;--ink:#1F1D1A;--ink2:#6B655B;--ink3:#A29B8E;--line:#E2DBCE;--accent:#2F6B55;
 --hl:#F8E08A;--def:#2F6B55;--formula:#86569A;--example:#3B5BA5;--important:#B5620C;--slide:#2A7C88}
@media (prefers-color-scheme:dark){:root{--paper:#1B221F;--bg:#141A17;--ink:#ECEFE8;--ink2:#A2ADA6;--ink3:#6C7872;
 --line:#2A3430;--accent:#7FD4AE;--hl:#6B5B22;--def:#7FD4AE;--formula:#CFA2E2;--example:#93ACF2;--important:#F2A64A;
 --slide:#72CBD6}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 'Inter','Segoe UI',system-ui,sans-serif}
main{max-width:820px;margin:32px auto;background:var(--paper);border:1px solid var(--line);border-radius:18px;
 padding:40px 52px;box-shadow:0 6px 24px rgba(60,45,20,.08)}
h1,h2{font-family:'Fraunces',Georgia,'Cambria',serif;font-weight:600;line-height:1.2}
h1{font-size:2.1em;margin:0 0 .2em}
h2{font-size:1.45em;margin:1.8em 0 .3em}
h2 .num{color:var(--accent)}
h3{font-size:1.05em;margin:1.3em 0 .3em}
a{color:var(--accent);text-decoration:none}
em{color:var(--ink2)}
strong{font-weight:650}
mark{background:var(--hl);color:inherit;padding:0 .15em;border-radius:3px}
hr{border:none;border-top:1px solid var(--line);margin:2.2em 0}
figure img{max-width:100%;border:1px solid var(--line);border-radius:10px;display:block}
img[src^="math/"]{display:inline;border:none;vertical-align:middle;max-width:100%}
@media (prefers-color-scheme:dark){img[src^="math/"]{filter:invert(1) hue-rotate(180deg)}}
figure{margin:1.2em 0}
figcaption{color:var(--ink3);font-size:.82em;margin-top:.35em}
.time{color:var(--ink3);font-size:.82em;margin:-.2em 0 .8em}
.lead{font-size:1.07em;color:var(--ink2)}
.lead b{color:var(--accent)}
.box{border-left:4px solid var(--c);background:color-mix(in srgb,var(--c) 9%,var(--paper));border-radius:0 10px 10px 0;
 padding:.7em 1.1em .5em;margin:.8em 0 1.1em}
.box>.label{color:var(--c);font-size:.72em;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.box p{margin:.2em 0 .4em}
.box ul{margin:.2em 0 .4em;padding-left:1.2em}
.def{--c:var(--def)}.formula{--c:var(--formula)}.example{--c:var(--example)}.important{--c:var(--important)}
.slide{--c:var(--slide)}.plain{--c:var(--ink3)}
@media (max-width:700px){main{margin:0;border-radius:0;padding:24px 18px}}
@media print{body{background:#fff}main{box-shadow:none;border:none;margin:0;max-width:none;padding:0}
 h2{page-break-after:avoid}img,.box{page-break-inside:avoid}img{max-height:45vh}}
"""


def style_web(body: str) -> str:
    def one(inner):
        label, kind, rest = _split_label(inner)
        head = f'<div class="label">{_html.escape(label)}</div>' if label else ""
        return f'<div class="box {kind or "plain"}">{head}{rest}</div>'

    def box(m):
        return "".join(one(x) for x in split_boxes(m.group(1)))
    body = re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>", box, body, flags=re.DOTALL)
    body = re.sub(r"<p>\s*<strong>(" + "|".join(LEAD) + r")\s*:?\s*</strong>\s*:?\s*(.*?)</p>",
                  lambda m: f'<p class="lead"><b>{m.group(1)}:</b> {m.group(2)}</p>', body,
                  flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r'(<h2[^>]*>)(\d+)\.\s', r'\1<span class="num">\2.</span> ', body)
    body = re.sub(r"<p><em>(\d[\d:]*\s*[–-]\s*\d[\d:]*)</em>", r'<p class="time">\1', body)
    body = re.sub(r'<p>\s*(<img [^>]*alt="([^"]*)"[^>]*/?>)\s*</p>', lambda m: (
        f'<figure>{m.group(1)}' + (f'<figcaption>{m.group(2)}</figcaption>' if m.group(2) and not m.group(2).isdigit()
                                   else "") + '</figure>'), body)
    return body
