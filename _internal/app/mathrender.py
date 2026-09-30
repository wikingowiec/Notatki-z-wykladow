"""Wzory matematyczne: LaTeX z notatek ($…$ i $$…$$) renderowany do obrazków (matplotlib mathtext, lokalnie).

Obrazki trafiają do folderu wykładu (math/…png) i są cache'owane, więc renderują się tylko raz.
Gdy wzoru nie da się narysować (nieobsługiwana komenda), pokazujemy go jako kod.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)
_lock = threading.Lock()   # matplotlib nie lubi równoległego rysowania

RENDER_DPI = 200
DISPLAY_DPI = 96 * 1.15      # ~ rozmiar tekstu w czytniku

# $$…$$ (osobny wzór) albo $…$ (w tekście); „$” musi przylegać do treści, żeby nie łapać kwot typu „5 $ i 10 $”
_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_INLINE = re.compile(r"(?<![\\$\w])\$(?!\s)([^$\n]{1,300}?)(?<!\s)\$(?![\w$])")

# zamiana komend, których mathtext nie zna, na obsługiwane odpowiedniki
_FIX = [(r"\\dfrac", r"\\frac"), (r"\\tfrac", r"\\frac"), (r"\\left\.", ""), (r"\\right\.", ""),
        (r"\\text\{", r"\\mathrm{"), (r"\\operatorname\{", r"\\mathrm{"), (r"\\mathbb\{R\}", r"\\mathbb{R}"),
        (r"\\le(?![a-z])", r"\\leq"), (r"\\ge(?![a-z])", r"\\geq"), (r"\\ldots", r"\\dots"),
        (r"\\(?:d|t)?frac(\d)(\d)", r"\\frac{\1}{\2}"), (r"\\,", r"\\ "), (r"\\;", r"\\ "), (r"\\!", "")]


def _clean(tex: str) -> str:
    tex = tex.strip()
    for a, b in _FIX:
        tex = re.sub(a, b, tex)
    return tex


def render(tex: str, out_dir: Path, color: str = "#000000", size: float = 13.0) -> tuple[Path, int, int] | None:
    """Zwraca (plik png, szerokość, wysokość w px ekranu) albo None, gdy się nie da."""
    tex = _clean(tex)
    key = hashlib.sha1(f"t|{tex}|{color}|{size}".encode()).hexdigest()[:16]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{key}.png"
    fail = out_dir / f"{key}.err"
    if fail.exists():
        return None
    if not path.exists():
        try:
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib import mathtext
            from matplotlib.font_manager import FontProperties
            with _lock:            # jak mathtext.math_to_image, ale z przezroczystym tłem (wzór w kolorowej ramce)
                from matplotlib import figure
                prop = FontProperties(size=size)
                parser = mathtext.MathTextParser("path")
                w_, h_, depth, _, _ = parser.parse(f"${tex}$", dpi=72, prop=prop)
                fig = figure.Figure(figsize=(w_ / 72.0, h_ / 72.0))
                fig.text(0, depth / h_, f"${tex}$", fontproperties=prop, color=color)
                fig.savefig(str(path), dpi=RENDER_DPI, format="png", transparent=True)
        except Exception as e:  # noqa: BLE001
            log.info("wzór nieobsługiwany: %s (%s)", tex, e)
            try:
                fail.write_text(str(e)[:200], encoding="utf-8")
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return None
    scale = DISPLAY_DPI / RENDER_DPI
    return path, max(1, int(w * scale)), max(1, int(h * scale))


def protect(md: str) -> tuple[str, list[tuple[str, bool]]]:
    """Wycina wzory z Markdownu (żeby parser nie zepsuł _ i *) i zostawia znaczniki @@MATHn@@."""
    found: list[tuple[str, bool]] = []

    def disp(m):
        found.append((m.group(1), True))
        n = len(found) - 1
        line_start = m.string.rfind("\n", 0, m.start()) + 1
        if m.string[line_start:m.start()].lstrip().startswith(">"):     # wzór w ramce (> **Wzór:** $$…$$)
            return f"\n>\n> @@MATH{n}@@\n>\n> "
        return f"\n\n@@MATH{n}@@\n\n"

    def inl(m):
        found.append((m.group(1), False))
        return f"@@MATH{len(found) - 1}@@"

    md = _DISPLAY.sub(disp, md)
    md = _INLINE.sub(inl, md)
    return md, found


def restore(body_html: str, found: list[tuple[str, bool]], out_dir: Path, color: str,
            src_prefix: str = "") -> str:
    """Wstawia obrazki wzorów w miejsce znaczników. src_prefix: np. „math/” dla eksportu HTML."""
    def repl(m):
        i = int(m.group(1))
        if i >= len(found):
            return m.group(0)
        tex, display = found[i]
        r = render(tex, out_dir, color, 15.0 if display else 13.0)
        if r is None:
            code = f"<code>{html.escape(tex)}</code>"
            return f"<p align='center'>{code}</p>" if display else code
        path, w, h = r
        src = (src_prefix + path.name) if src_prefix else path.as_uri()
        img = f'<img src="{src}" width="{w}" height="{h}" style="vertical-align: middle" />'
        return f"<p align='center'>{img}</p>" if display else img
    body_html = re.sub(r"<p>\s*@@MATH(\d+)@@\s*</p>", lambda m: repl(m) if found[int(m.group(1))][1]
                       else f"<p>{repl(m)}</p>", body_html)
    return re.sub(r"@@MATH(\d+)@@", repl, body_html)


def text_to_html(text: str, out_dir: Path, color: str) -> str:
    """Zwykły tekst (np. fiszka) z wzorami → HTML dla QLabel/QTextBrowser."""
    md, found = protect(text)
    body = html.escape(md).replace("\n", "<br>")
    return restore(body, found, out_dir, color)
