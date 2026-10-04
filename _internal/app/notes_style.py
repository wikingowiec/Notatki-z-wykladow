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
    """(pasek, tło, kolor etykiety) dla każdego rodzaju ramki – z tokenów motywu (defBg/defBar/defText …)."""
    from .ui.theme import mix
    d = t.d

    def tok(k):
        return d[f"{k}Bar"], d[f"{k}Bg"], d.get(f"{k}Text", d["ink3"])
    f = 0.16 if t.dark else 0.10
    sl, cd = t.subjects[5], t.subjects[6]
    return {
        "def": tok("def"), "formula": tok("wz"), "example": tok("prz"), "important": tok("waz"),
        "slide": (sl, mix(t.surface, sl, f), sl), "card": (cd, mix(t.surface, cd, f), cd),
        "lead": tok("tldr"), "": tok("tldr"),
    }


_LABEL_ALT = "|".join(sorted((re.escape(k) for k in list(LABELS) + list(LEAD)), key=len, reverse=True))
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
KIND_ANCHOR = {"def": "def", "formula": "wz", "example": "prz", "important": "waz"}


def _slide_figures(body: str, t, slide_times: dict, img_w: int) -> str:
    """Slajd w notatce: obraz ~300 px, obok „Slajd 6 · 31:05” i „OPIS AI” z opisem z ramki „Na slajdzie”."""
    from .storage import fmt_time
    on_slide = "|".join(k for k, v in LABELS.items() if v == "slide")
    pat = re.compile(r'<p>\s*(<img (?![^>]*src="file:)[^>]*?alt="([^"]*)"[^>]*?/?>)\s*</p>\s*'
                     r'(<blockquote>\s*(<p>\s*<strong>(?:' + on_slide + r')\s*:?\s*</strong>.*?)</blockquote>)?',
                     re.IGNORECASE | re.DOTALL)

    def fig(m):
        img, alt = m.group(1), m.group(2)
        desc, rest_boxes = "", ""
        if m.group(4):            # kilka ramek sklejonych w jeden cytat – opis to tylko „Na slajdzie”
            parts = split_boxes(m.group(4))
            _l, _k, desc = _split_label(parts[0])
            desc = desc.strip()
            if len(parts) > 1:
                rest_boxes = "<blockquote>" + "".join(parts[1:]) + "</blockquote>"
        wm, hm = re.search(r'width="(\d+)"', img), re.search(r'height="(\d+)"', img)
        if wm and hm:
            img = img.replace(hm.group(0), f'height="{round(int(hm.group(1)) * img_w / max(1, int(wm.group(1))))}"')
        img = re.sub(r'width="\d+"', f'width="{img_w}"', img)
        num = re.search(r"(\d+)", alt or "")
        cap = alt or ""
        if num and int(num.group(1)) in slide_times:
            cap = f"{alt} · {fmt_time(slide_times[int(num.group(1))])}"
        desc = re.sub(r"<p>", '<p style="margin:0 0 4px 0; line-height:150%;">', desc)
        right = (f'<p style="margin:0 0 8px 0; color:{t.text2}; font-size:9.5pt; font-weight:600;">{_html.escape(cap)}</p>'
                 + (f'<p style="margin:0 0 3px 0; color:{t.text3}; font-size:8pt; font-weight:700;">OPIS AI</p>'
                    f'<div style="color:{t.text2}; font-size:10pt;">{desc}</div>' if desc else ""))
        return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:14px 0 16px 0;"><tr>'
                f'<td width="{img_w}" valign="top"><p style="margin:0; line-height:100%;">{img}</p></td><td width="16"></td>'
                f'<td valign="top">{right}</td></tr></table>' + rest_boxes)
    return pat.sub(fig, body)


def style_qt(body: str, t, num_colors: dict | None = None, slide_times: dict | None = None,
             seek: bool = False, slide_w: int = 300, figures: bool = True) -> str:
    """Notatka w czytniku aplikacji: ramki „pasek + tło” (tabele), zakreślenia, nagłówki tematów z kolorowym
    numerem, wiersz „24:10–38:00 · ▶ odtwórz fragment · slajdy 5–6”, slajdy z opisem AI obok."""
    colors = _colors(t)
    body = body.replace("<mark>", f'<span style="background-color:{t.mark};">').replace("</mark>", "</span>")
    if figures:
        body = _slide_figures(body, t, slide_times or {}, slide_w)
    counter: dict = {}

    def box(m):
        return "".join(one(x) for x in split_boxes(m.group(1)))

    def one(inner):
        lm = re.match(r"\s*<p>\s*<strong>(" + "|".join(LEAD) + r")\s*:?\s*</strong>\s*:?\s*", inner, re.IGNORECASE)
        if lm:                     # „W skrócie” w ramce → ramka tldr
            bar, bg, _l = colors["lead"]
            rest = "<p>" + inner[lm.end():]
            rest = re.sub(r"<p>", '<p style="margin:0 0 2px 0; font-size:11.5pt;">', rest)
            return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:4px; margin-bottom:16px;">'
                    f'<tr><td width="3" bgcolor="{bar}"></td><td bgcolor="{bg}" style="padding:9px 16px 9px 14px;">'
                    f'<p style="margin:0 0 3px 0; color:{t.text3}; font-size:8.5pt; font-weight:700;">'
                    f'{lm.group(1).upper()}</p>{rest}</td></tr></table>')
        label, kind, rest = _split_label(inner)
        bar, bg, lab = colors.get(kind, colors[""])
        rest = re.sub(r"<p>", '<p style="margin:0 0 4px 0;">', rest)
        rest = re.sub(r"<(ul|ol)>", r'<\1 style="margin-top:2px; margin-bottom:2px;">', rest)
        anchor = ""
        if kind in KIND_ANCHOR:
            k = KIND_ANCHOR[kind]
            counter[k] = counter.get(k, 0) + 1
            anchor = f'<a name="box-{k}-{counter[k]}"></a>'
        head = (f'<p style="margin:0 0 4px 0; color:{lab}; font-size:8.5pt; font-weight:700;">'
                f'{anchor}{_html.escape(label.upper())}</p>') if label else anchor
        return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px; margin-bottom:16px;">'
                f'<tr><td width="3" bgcolor="{bar}"></td>'
                f'<td bgcolor="{bg}" style="padding:10px 16px 8px 14px;">{head}{rest}</td></tr></table>')
    body = re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>", box, body, flags=re.DOTALL)

    # „W skrócie:” – ramka tldr na początku tematu
    bar, bg, _lab = colors["lead"]
    lead_re = re.compile(r"<p>\s*<strong>(" + "|".join(LEAD) + r")\s*:?\s*</strong>\s*:?\s*(.*?)</p>",
                         re.IGNORECASE | re.DOTALL)
    body = lead_re.sub(lambda m: (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:4px; margin-bottom:16px;">'
        f'<tr><td width="3" bgcolor="{bar}"></td><td bgcolor="{bg}" style="padding:9px 16px 9px 14px;">'
        f'<span style="color:{t.text3}; font-size:8.5pt; font-weight:700;">{m.group(1).upper()}</span><br>'
        f'<span style="font-size:11.5pt;">{m.group(2)}</span></td></tr></table>'), body)
    # numer tematu w kolorze kategorii
    body = re.sub(r'(<h2[^>]*>(?:<a name="[^"]*"></a>)?)(\d+)\.\s', lambda m: (
        f'{m.group(1)}<span style="color:{(num_colors or {}).get(int(m.group(2)), t.accent)};">{m.group(2)}.</span> '),
        body)

    # wiersz pod nagłówkiem tematu: czas · ▶ odtwórz fragment · slajdy 5–6
    def time_line(chunk: str) -> str:
        nums = sorted({int(x) for x in re.findall(r'alt="[^"]*?(\d+)"', chunk)})
        sl = ""
        if nums:
            sl = f"slajd {nums[0]}" if len(nums) == 1 else f"slajdy {nums[0]}–{nums[-1]}"

        def repl(m):
            parts = [f'<span style="color:{t.text3};">{m.group(1)}</span>']
            if seek:
                start = _secs(m.group(1).split("–")[0].split("-")[0].strip())
                parts.append(f'<a href="seek:{start}" style="color:{t.accent_text}; font-weight:600; '
                             f'text-decoration:none;">▶ odtwórz fragment</a>')
            if sl:
                parts.append(f'<span style="color:{t.text3};">{sl}</span>')
            sep = f'<span style="color:{t.text3};"> · </span>'
            return f'<p style="font-size:9.5pt; margin:0 0 12px 0;">{sep.join(parts)}'
        return re.sub(r"<p><em>(\d[\d:]*\s*[–-]\s*\d[\d:]*)</em>", repl, chunk, count=1)
    pieces = re.split(r"(?=<h2)", body)
    body = "".join(time_line(pc) if pc.startswith("<h2") else pc for pc in pieces)
    # podpis pod pozostałymi obrazami
    body = re.sub(r'<p>\s*(<img (?![^>]*src="file:)[^>]*?alt="([^"]*)"[^>]*/?>)\s*</p>', lambda m: (
        f'<p style="margin:14px 0 4px 0; line-height:100%;">{m.group(1)}</p>'
        + (f'<p style="margin:0 0 10px 0; color:{t.text3}; font-size:9pt;">{m.group(2)}</p>'
           if m.group(2) and not m.group(2).isdigit() else "")), body)
    return body


def _secs(s: str) -> float:
    parts = [float(x) for x in s.split(":") if x.strip().replace(".", "").isdigit()]
    v = 0.0
    for x in parts:
        v = v * 60 + x
    return v


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
