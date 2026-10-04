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
    lang = lecture.meta.language or "pl"
    doc = (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{html.escape(lecture.meta.title)}</title><style>{WEB_CSS}</style></head>"
           f"<body><main>{body}</main></body></html>")
    lecture.html_path.write_text(doc, encoding="utf-8")
    return lecture.html_path


def preview_html(md: str, img_width: int = 620, folder: Path | None = None, base_pt: float = 10.5) -> str:
    """HTML do QTextBrowser/PDF (podzbiór HTML – szerokość obrazów ustawiamy atrybutem)."""
    from .mathrender import protect, restore
    from .notes_doc import with_toc
    from .notes_style import mark_highlights, style_qt
    from .ui.theme import Tokens
    LIGHT = Tokens("zeszyt", False)
    md, maths = protect(with_toc(md))
    body = anchorize(md_to_html(mark_highlights(md)))
    body = re.sub(r'<img ([^>]*?)/?>', lambda m: f'<img {m.group(1)} width="{img_width}" />', body)
    body = style_qt(body, LIGHT, figures=False)
    if folder is not None:
        body = restore(body, maths, Path(folder) / "math", "#000000")

        def fit(m):          # wzory szersze niż strona – proporcjonalnie mniejsze
            w, h = int(m.group(2)), int(m.group(3))
            if w <= img_width:
                return m.group(0)
            return f'{m.group(1)} width="{img_width}" height="{max(1, int(h * img_width / w))}"'
        body = re.sub(r'(<img src="file:[^"]+") width="(\d+)" height="(\d+)"', fit, body)
    t = LIGHT
    return ("<html><head><style>"
            f"body{{font-family:'Inter','Segoe UI';font-size:{base_pt}pt;line-height:155%;color:{t.text}}}"
            "h1{font-family:'Fraunces',Georgia,serif;font-size:21pt;font-weight:600}"
            "h2{font-family:'Fraunces',Georgia,serif;font-size:14.5pt;font-weight:600;margin-top:20px}"
            f"h3{{font-size:11.5pt}} a{{color:{t.accent};text-decoration:none}} em{{color:{t.text2}}}"
            "</style></head><body>" + body + "</body></html>")


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
    from PySide6.QtCore import QUrl, QMarginsF
    from PySide6.QtGui import QTextDocument, QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter
    md = lecture.read_text(lecture.notes_path)
    doc = QTextDocument()
    doc.setBaseUrl(QUrl.fromLocalFile(str(lecture.folder) + "/"))
    doc.setHtml(preview_html(md, img_width=270 if mobile else 560, folder=lecture.folder,
                             base_pt=10.0 if mobile else 10.5))
    doc.setDocumentMargin(0)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setDocName(lecture.meta.title)
    if mobile:           # proporcje ekranu telefonu, marginesy małe
        from PySide6.QtCore import QSizeF
        size = QPageSize(QSizeF(90, 185), QPageSize.Unit.Millimeter, "Telefon")
        printer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(6, 8, 6, 8),
                                          QPageLayout.Unit.Millimeter))
        # układ tekstu w pikselach 96 dpi na obszarze strony (inaczej Qt robi wąską kolumnę)
        from PySide6.QtCore import QSizeF as _Q
        doc.setPageSize(_Q((90 - 12) / 25.4 * 96, (185 - 16) / 25.4 * 96))
    else:
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                          QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter))
    doc.print_(printer)
    return out
