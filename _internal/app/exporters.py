"""Eksport: HTML (do przeglądarki/druku), PDF, fiszki do Anki, podgląd w aplikacji."""
from __future__ import annotations

import html
import re
from pathlib import Path

from .storage import Lecture

CSS = """
body{font-family:'Segoe UI',system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;
     line-height:1.6;color:#1f2328;background:#fff}
h1{border-bottom:2px solid #e5e7eb;padding-bottom:6px}
h2{margin-top:32px;color:#1d4ed8}\nh2 + ul a, ul a{text-decoration:none}
h3{color:#0f172a}
img{max-width:100%;border:1px solid #d0d7de;border-radius:8px;margin:8px 0}
code{background:#f3f4f6;padding:1px 4px;border-radius:4px}
hr{border:none;border-top:1px solid #e5e7eb;margin:32px 0}
@media (prefers-color-scheme: dark){body{background:#0d1117;color:#e6edf3}h2{color:#7aa2ff}h3{color:#e6edf3}
 code{background:#1f2937}img{border-color:#30363d}h1{border-color:#30363d}}
@media print{h2{page-break-after:avoid}img{page-break-inside:avoid;max-height:45vh}}
"""


def md_to_html(md: str) -> str:
    try:
        import markdown
        return markdown.markdown(md, extensions=["extra", "sane_lists", "nl2br"])
    except Exception:
        return "<pre>" + html.escape(md) + "</pre>"


def anchorize(body: str) -> str:
    """QTextBrowser przewija do kotwic <a name>, a nie do id – dodajemy oba."""
    return re.sub(r'<h([1-3]) id="([\w-]+)">', r'<h\1 id="\2"><a name="\2"></a>', body)


def export_html(lecture: Lecture) -> Path:
    from .mathrender import protect, restore
    from .notes_doc import with_toc
    from .notes_style import WEB_CSS, mark_highlights, style_web
    md, maths = protect(with_toc(lecture.read_text(lecture.notes_path)))
    body = style_web(md_to_html(mark_highlights(md)))
    body = restore(body, maths, lecture.folder / "math", "#1f2328", src_prefix="math/")
    from .notes_pipeline import notes_lang
    lang = notes_lang(lecture)
    doc = (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{html.escape(lecture.meta.title)}</title><style>{WEB_CSS}</style></head>"
           f"<body><main>{body}</main></body></html>")
    lecture.html_path.write_text(doc, encoding="utf-8")
    return lecture.html_path


# ---------------------------------------------------------------------------
# PDF (A4 i wąska strona na telefon) – QTextDocument rysowany strona po stronie
# ---------------------------------------------------------------------------
PDF_TEXT = "Literata"         # treść – szeryfowy font do czytania (osadzany w PDF)
PDF_HEAD = "Nunito Sans"      # nagłówki, etykiety ramek, stopka
# wymiary w mm: strona, marginesy (lewy/prawy, góra, dół – w dolnym jest stopka), stopień pisma
PDF_A4 = dict(page=(210, 297), side=24, top=20, bottom=22, pt=11.0, h1=21, h2=15, h3=12, img=0.82)
PDF_PHONE = dict(page=(90, 185), side=6, top=7, bottom=12, pt=10.0, h1=17, h2=13, h3=11, img=1.0)
MM = 96 / 25.4                # układ tekstu liczymy w pikselach 96 dpi


def _ensure_pdf_fonts() -> None:
    """Fonty z ui/fonts – w aplikacji są już wczytane, ale eksport bywa wołany też bez okna."""
    from PySide6.QtGui import QFontDatabase
    if PDF_TEXT in QFontDatabase.families() and PDF_HEAD in QFontDatabase.families():
        return
    for f in sorted((Path(__file__).parent / "ui" / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def print_html(md: str, folder: Path, col_px: float, spec: dict) -> tuple[str, dict]:
    """HTML do druku (podzbiór HTML Qt) + obrazy slajdów {klucz: QImage} do doc.addResource."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from .mathrender import protect, restore
    from .notes_doc import with_toc
    from .notes_style import mark_highlights, style_qt
    from .ui.theme import Tokens, mix
    t = Tokens("zeszyt", False)
    folder = Path(folder)
    md, maths = protect(with_toc(md))
    body = anchorize(md_to_html(mark_highlights(md)))

    # slajdy: wczytujemy sami (oryginały mają ~3000 px) i zmniejszamy do ~220 dpi na papierze
    img_w = int(col_px * spec["img"])
    images: dict = {}

    def img(m):
        src = re.search(r'src="([^"]+)"', m.group(1))
        if not src or src.group(1).startswith(("file:", "http")):
            return m.group(0)
        file = html.unescape(src.group(1))
        im = QImage(str(folder / file))
        if im.isNull():
            return ""
        im = im.scaledToWidth(min(im.width(), int(img_w * 2.3)), Qt.TransformationMode.SmoothTransformation)
        key = f"pdfimg:{file}"
        images[key] = im
        alt = re.search(r'alt="([^"]*)"', m.group(1))
        h = round(img_w * im.height() / max(1, im.width()))
        return f'<img src="{key}" alt="{alt.group(1) if alt else ""}" width="{img_w}" height="{h}" />'
    body = re.sub(r"<img ([^>]*?)/?>", img, body)
    body = style_qt(body, t, figures=False)
    body = restore(body, maths, folder / "math", t.text)

    math_w = int(col_px - 36)            # wzory bywają w ramkach – zostawiamy miejsce na pasek i wcięcie

    def fit(m):              # wzory szersze niż kolumna – proporcjonalnie mniejsze
        w, h = int(m.group(2)), int(m.group(3))
        if w <= math_w:
            return m.group(0)
        return f'{m.group(1)} width="{math_w}" height="{max(1, int(h * math_w / w))}"'
    body = re.sub(r'(<img src="file:[^"]+") width="(\d+)" height="(\d+)"', fit, body)

    # druk: tła ramek jaśniejsze niż w aplikacji, pasek zostaje w kolorze rodzaju
    body = re.sub(r'<td bgcolor="(#[0-9a-fA-F]{6})" style="padding',
                  lambda m: f'<td bgcolor="{mix("#ffffff", m.group(1), 0.55)}" style="padding', body)
    body = body.replace(f"background-color:{t.mark};", f"background-color:{mix('#ffffff', t.mark, 0.7)};")
    # etykiety ramek, czas tematu, podpisy – krojem nagłówków; „W skrócie” w stopniu treści
    sans = f"font-family:'{PDF_HEAD}';"
    body = body.replace("font-size:8.5pt; font-weight:700;", f"{sans} font-size:7.5pt; font-weight:800;")
    body = body.replace("font-size:11.5pt;", "")
    body = body.replace('<p style="font-size:9.5pt; margin:0 0 12px 0;">',
                        f'<p style="{sans} font-size:8.5pt; margin:0 0 10px 0;">')
    body = body.replace('<p style="margin:14px 0 4px 0; line-height:100%;">',
                        '<p align="center" style="margin:12px 0 3px 0; line-height:100%;">')
    body = body.replace('<p style="margin:0 0 10px 0; color:', f'<p align="center" style="{sans} margin:0 0 12px 0; color:')
    # padding komórek w px – na wąskiej stronie mniejsze
    if spec is PDF_PHONE:
        body = body.replace("padding:10px 16px 8px 14px;", "padding:7px 9px 5px 9px;")
        body = body.replace("padding:9px 16px 9px 14px;", "padding:7px 9px 7px 9px;")
    # Qt stawia kropkę punktu tuż przy tekście (odstęp = jedna spacja) – dokładamy wąską spację
    body = re.sub(r"<li>(\s*<p[^>]*>)?", lambda m: f"<li>{m.group(1) or ''}&#8201;", body)
    pt = spec["pt"]
    # Qt liczy procent interlinii od naturalnej wysokości wiersza fontu, a nie od stopnia – przeliczamy na 1,45 em
    from PySide6.QtGui import QFont, QFontMetricsF
    f = QFont(PDF_TEXT)
    f.setPointSizeF(pt)
    em = pt * 96 / 72                    # 1 em w px; marginesy Qt przyjmuje tylko w px (pt → po cichu 0)
    lh = round(145 / max(0.8, QFontMetricsF(f).height() / em))
    css = (f"body{{font-family:'{PDF_TEXT}',Georgia,serif;font-size:{pt}pt;line-height:{lh}%;color:{t.text}}}"
           f"p{{margin-top:0;margin-bottom:{em * 0.6:.0f}px}}"
           f"ul,ol{{margin-top:0;margin-bottom:{em * 0.6:.0f}px}} li{{margin-bottom:{em * 0.15:.0f}px}}"
           f"h1,h2,h3{{font-family:'{PDF_HEAD}';color:{t.text};line-height:120%}}"
           f"h1{{font-size:{spec['h1']}pt;font-weight:800;margin-top:{em * 1.6:.0f}px;margin-bottom:{em * 0.5:.0f}px}}"
           f"h2{{font-size:{spec['h2']}pt;font-weight:700;margin-top:{em * 1.9:.0f}px;margin-bottom:{em * 0.35:.0f}px}}"
           f"h3{{font-size:{spec['h3']}pt;font-weight:700;margin-top:{em * 1.2:.0f}px;margin-bottom:{em * 0.2:.0f}px}}"
           f"a{{color:{t.accent};text-decoration:none}} em{{color:{t.text2}}}"
           f"strong,b{{font-weight:700}}")
    return f"<html><head><style>{css}</style></head><body>{body}</body></html>", images


def _keep_together(doc, page_h: float) -> None:
    """Qt sam nie zna „page-break-inside: avoid” ani „nagłówek razem z treścią” – po złożeniu tekstu
    sprawdzamy granice stron i wstawiamy podział strony przed nagłówkiem / ramką, która by się rozjechała."""
    from PySide6.QtGui import QTextCursor, QTextFormat
    lay = doc.documentLayout()
    before = QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore

    def page_top(y):
        return (y // page_h) * page_h

    def crosses(top, bottom):
        return top > page_top(top) + 2 and bottom > page_top(top) + page_h

    def item(block):
        """(początek, koniec, tabela|None, czy obraz) elementu zaczynającego się tym blokiem."""
        tbl = QTextCursor(block).currentTable()
        if tbl is not None:
            r = lay.frameBoundingRect(tbl)
            return r.top(), r.bottom(), tbl, False
        r = lay.blockBoundingRect(block)
        is_img = "￼" in block.text() and block.layout().lineCount() == 1
        return r.top(), r.bottom(), None, is_img

    def after(block, tbl):
        return doc.findBlock(tbl.lastPosition() + 1) if tbl is not None else block.next()

    def relayout():
        # po zmianie formatu Qt przelicza tylko kawałek – reszta bloków rysowała się w starych miejscach
        doc.markContentsDirty(0, doc.characterCount())

    block, small = doc.begin(), 32
    while block.isValid():
        top, bottom, tbl, is_img = item(block)
        heading = tbl is None and block.blockFormat().headingLevel() > 0
        if heading or is_img:
            # nagłówek ciągnie za sobą krótkie wiersze (czas tematu, kolejne nagłówki) i początek treści;
            # obraz – swój podpis
            need, nb = bottom, after(block, tbl)
            for _ in range(4):
                if not nb.isValid():
                    break
                ntop, nbot, ntbl, nimg = item(nb)
                nh = nbot - ntop
                if nh < small or (nb.blockFormat().headingLevel() > 0 and ntbl is None):
                    need = nbot
                    nb = after(nb, ntbl)
                    continue
                if heading:
                    need = ntop + (nh if (ntbl is not None or nimg) and nh < page_h * 0.5 else min(nh, 48))
                break
            if crosses(top, need) and need - top < page_h * 0.6:
                c = QTextCursor(block)
                f = block.blockFormat()
                f.setPageBreakPolicy(before)
                c.setBlockFormat(f)
                relayout()
        elif tbl is not None and crosses(top, bottom) and bottom - top < page_h * 0.45:
            f = tbl.format()             # ramka (Definicja, Wzór…) w całości na następnej stronie
            f.setPageBreakPolicy(before)
            tbl.setFormat(f)
            relayout()
        block = after(block, tbl)


def export_anki(lecture: Lecture, out: Path | None = None) -> Path:
    """Plik tekstowy do importu w Anki (Plik → Importuj): pytanie<TAB>odpowiedź."""
    out = out or (lecture.folder / "fiszki_anki.txt")
    tag = re.sub(r"\s+", "_", (lecture.meta.subject or "wyklad").strip())
    lines = ["#separator:tab", "#html:false", "#tags column:3"]
    for c in lecture.load_flashcards():
        q = c["q"].replace("\t", " ").replace("\n", " ")
        a = c["a"].replace("\t", " ").replace("\n", " ")
        lines.append(f"{q}\t{a}\t{tag}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def export_pdf(lecture: Lecture, out: Path, mobile: bool = False) -> Path:
    """PDF przez silnik Qt (bez dodatkowych programów). mobile=True – wąska strona do czytania na telefonie."""
    from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, QUrl
    from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPen,
                               QTextDocument, QTextOption)
    from PySide6.QtPrintSupport import QPrinter
    from .ui.theme import Tokens
    _ensure_pdf_fonts()
    spec = PDF_PHONE if mobile else PDF_A4
    pw, ph = spec["page"]
    col_w = (pw - 2 * spec["side"]) * MM
    col_h = (ph - spec["top"] - spec["bottom"]) * MM

    doc = QTextDocument()
    doc.setBaseUrl(QUrl.fromLocalFile(str(lecture.folder) + "/"))
    # bez hintingu i z metrykami projektowymi – inaczej odstępy liter liczone dla ekranu rozjeżdżają się w druku
    base = QFont(PDF_TEXT)
    base.setPointSizeF(spec["pt"])
    base.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    doc.setDefaultFont(base)
    opt = QTextOption()
    opt.setUseDesignMetrics(True)
    doc.setDefaultTextOption(opt)
    doc.setDocumentMargin(0)
    doc.setPageSize(QSizeF(col_w, col_h))
    body, images = print_html(lecture.read_text(lecture.notes_path), lecture.folder, col_w, spec)
    for key, im in images.items():
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), im)
    doc.setHtml(body)
    _keep_together(doc, col_h)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setDocName(lecture.meta.title)
    printer.setCreator("Wykłady")
    size = (QPageSize(QSizeF(pw, ph), QPageSize.Unit.Millimeter, "Telefon") if mobile
            else QPageSize(QPageSize.PageSizeId.A4))
    printer.setFullPage(True)            # marginesy i stopkę rysujemy sami
    printer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                                      QPageLayout.Unit.Millimeter))

    t = Tokens("zeszyt", False)
    foot = QFont(PDF_HEAD)
    foot.setPointSizeF(7.0 if mobile else 8.0)
    foot.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    fm = QFontMetricsF(foot, printer)                     # stopka rysowana w punktach drukarki
    title = lecture.meta.title or "Notatki"
    pages = max(1, doc.pageCount())
    x0, y0 = spec["side"] * MM, spec["top"] * MM
    p = QPainter(printer)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scale = printer.resolution() / 96
    fx, fw = x0 * scale, col_w * scale
    fy = (ph - spec["bottom"] * 0.5) * MM * scale         # linia bazowa stopki
    ly = fy - fm.ascent() - 2.0 * MM * scale
    for i in range(pages):
        if i:
            printer.newPage()
        p.save()
        p.scale(scale, scale)
        p.translate(x0, y0 - i * col_h)
        doc.drawContents(p, QRectF(0, i * col_h, col_w, col_h))
        p.restore()
        # stopka: cienka linia, tytuł wykładu z lewej, „3 / 12” z prawej
        p.setPen(QPen(QColor(t.line), 0.5 * scale))
        p.drawLine(QPointF(fx, ly), QPointF(fx + fw, ly))
        p.setFont(foot)
        p.setPen(QColor(t.text3))
        num = f"{i + 1} / {pages}"
        nw = fm.horizontalAdvance(num)
        p.drawText(QPointF(fx + fw - nw, fy), num)
        p.drawText(QPointF(fx, fy), fm.elidedText(title, Qt.TextElideMode.ElideRight, fw - nw - 6 * MM * scale))
    p.end()
    return out
