"""Ekran „Biblioteka” (układ jak w Notatkach Apple): lista wykładów | szczegóły wykładu.

Płynność: nic ciężkiego nie dzieje się w wątku interfejsu.
  * obrazy slajdów – miniatury JPG wczytywane w tle,
  * notatki / transkrypcja – HTML budowany w tle, zakładki renderowane dopiero przy otwarciu,
  * lista wykładów i wyszukiwanie – z pamięci podręcznej (pliki czytane tylko po zmianie).
"""
from __future__ import annotations

import html
import logging
import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (QApplication, QFileDialog, QStyledItemDelegate, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import jobs
from ..exporters import anchorize, export_anki, export_html, export_pdf, md_to_html
from ..notes_doc import with_toc
from ..storage import Lecture, card_stats, fmt_time, list_lectures, notes_lower, slides_info
from .controls import (show_if, AdaptiveBox, EmptyState, LectureDelegate, SegmentedControl, StatusPill, SubjectChip, hbox,
                       icon_button, label, set_icon)
from .theme import T, theme
from .ask_panel import AskPanel
from .reader import Reader
from .widgets import JobRunner, run_async

log = logging.getLogger(__name__)

NOTES, SLIDES, TRANSCRIPT, CARDS, ASK, CHEAT, EXAM = range(7)
READER_IMG_W = 640
GRID_ICON = QSize(264, 149)


def reader_css() -> str:
    from .theme import DISPLAY_FAMILY, UI_FAMILY
    t = T()
    disp = f"'{DISPLAY_FAMILY}', Georgia, serif"
    return (f"body {{ color:{t.text}; font-family:'{UI_FAMILY}'; font-size:11.6pt; line-height:170%; }}"
            f"h1 {{ font-family:{disp}; font-size:24pt; font-weight:600; margin:2px 0 4px 0; line-height:120%; }}"
            f"h2 {{ font-family:{disp}; font-size:18.75pt; font-weight:600; margin:30px 0 4px 0; line-height:125%; }}"
            f"h3 {{ font-family:{disp}; font-size:13.5pt; font-weight:600; margin:18px 0 4px 0; }}"
            f"p {{ margin:0 0 10px 0; }}"
            f"em {{ color:{t.text2}; }} a {{ color:{t.accent_text}; text-decoration:none; font-weight:600; }}"
            f" li {{ margin-bottom:5px; }}"
            f"strong, b {{ font-weight:600; }}"
            f"code {{ background:{t.hover}; }}"
            f"blockquote {{ color:{t.text2}; margin:8px 0 8px 12px; }}"
            f"table {{ border-color:{t.separator}; }} th {{ background:{t.hover}; }}")


def lecture_date(lec: Lecture) -> str:
    c = lec.meta.created
    return f"{c[8:10]}.{c[5:7]}.{c[0:4]}" if len(c) >= 10 else ""


def plural_lectures(n: int) -> str:
    if n == 0:
        return "Brak wykładów"
    if n == 1:
        return "1 wykład"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} wykłady"
    return f"{n} wykładów"


def _sig(lec: Lecture) -> tuple:
    def mt(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0
    return (str(lec.folder), mt(lec.folder / "meta.json"), mt(lec.notes_path), mt(lec.slides_json),
            mt(lec.flashcards_path), mt(lec.transcript_path), mt(lec.folder / "qa.json"), T().dark)


# ---------------------------------------------------------------------------
# Prace w tle (bez widżetów – tylko dane i QImage, które są bezpieczne poza wątkiem interfejsu)
# ---------------------------------------------------------------------------
def strip_title(md: str) -> str:
    """Bez tytułu i linii „przedmiot · data · czas” na początku – pokazuje je nagłówek nad notatką."""
    lines = md.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and re.match(r"^\*[^*].*\*\s*$", lines[i].strip()):
            i += 1
        return "\n".join(lines[i:]).lstrip("\n")
    return md


def build_notes(folder: Path, md: str, dpr: float, audio: bool = True, toc: bool = True,
                no_title: bool = False) -> tuple[str, dict, dict]:
    """Notatka → HTML dla czytnika. W tle: miniatury slajdów, wzory, ikonki odsłuchu przy punktach.
    Zwraca (html, obrazy {klucz: QImage}, fragmenty do odsłuchu {n: [Fragment]})."""
    from ..audio_links import annotate
    from ..mathrender import protect, restore
    from ..slides import ensure_thumb
    t = T()
    plays: dict = {}
    from ..topics import load_categories, section_colors
    from .theme import palette_color
    cats = load_categories(Lecture(folder), md)
    num_colors = {n: palette_color(ci) for n, ci in section_colors(cats).items()}
    md = with_toc(md, include_toc=toc, categories=cats)
    if no_title:
        md = strip_title(md)
    lec_ = Lecture(folder)
    slide_t0: dict = {}
    for ev in lec_.load_slides().get("events", []):
        slide_t0.setdefault(int(ev["index"]), float(ev["t"]))
    seek = bool(audio and lec_.audio_parts())
    if audio:
        lec = Lecture(folder)
        segs = lec.load_segments()
        if segs and lec.audio_parts():
            slide_times = [e["t"] for e in lec.load_slides().get("events", [])]
            md, plays = annotate(md, segs, lec.meta.duration, slide_times)
    from ..notes_style import mark_highlights, style_qt
    md, maths = protect(md)
    md = mark_highlights(md)
    body = anchorize(md_to_html(md))
    images: dict[str, QImage] = {}

    def repl(m):
        attrs = m.group(1)
        src = re.search(r'src="([^"]+)"', attrs)
        if not src:
            return m.group(0)
        file = html.unescape(src.group(1))
        key = f"img:{file}"
        if key not in images:
            thumb = ensure_thumb(folder, file)
            img = QImage(str(thumb)) if thumb else QImage()
            if not img.isNull():
                w = int(READER_IMG_W * dpr)
                img = img.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
                img.setDevicePixelRatio(dpr)
            images[key] = img
        alt = re.search(r'alt="([^"]*)"', attrs)
        im = images.get(key)
        hh = ""
        if im is not None and not im.isNull() and im.width():
            hh = f' height="{round(READER_IMG_W * im.height() / im.width())}"'
        return f'<img src="{key}" alt="{alt.group(1) if alt else ""}" width="{READER_IMG_W}"{hh} />'

    body = re.sub(r"<img ([^>]*?)/?>", repl, body)
    body = style_qt(body, t, num_colors, slide_times=slide_t0, seek=seek)
    # wzory → obrazki (wczytane tu, w tle)
    body = restore(body, maths, Path(folder) / "math", t.text)

    def math_img(m):
        uri, w = m.group(1), int(m.group(2))
        key = "math:" + uri.rsplit("/", 1)[-1]
        if key not in images:
            img = QImage(QUrl(uri).toLocalFile())
            if not img.isNull():
                img.setDevicePixelRatio(max(1.0, img.width() / max(1, w)))
            images[key] = img
        return f'<img src="{key}" width="{w}"'
    body = re.sub(r'<img src="(file:[^"]+)" width="(\d+)"', math_img, body)
    # ikonki odsłuchu
    if plays:
        spk = "icon:speaker"      # rysowana w wątku interfejsu (Reader.loadResource)
        body = re.sub(r"\s*@@PLAY(\d+)@@",
                      lambda m: f'&nbsp;<a href="play:{m.group(1)}"><img src="{spk}" width="15" height="15" /></a>', body)
    else:
        body = re.sub(r"\s*@@PLAY\d+@@", "", body)
    return f"<html><head><style>{reader_css()}</style></head><body>{body}</body></html>", images, plays


def build_grid_icons(folder: Path, files: list[str], dpr: float) -> list[QImage]:
    from ..slides import ensure_thumb
    out = []
    for f in files:
        thumb = ensure_thumb(folder, f)
        img = QImage(str(thumb)) if thumb else QImage()
        if not img.isNull():
            img = img.scaled(int(GRID_ICON.width() * dpr), int(GRID_ICON.height() * dpr),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            img.setDevicePixelRatio(dpr)
        out.append(img)
    return out


def build_transcript(lec: Lecture) -> str:
    t = T()
    segs = lec.load_segments()
    if not segs:
        return (f"<p style='color:{t.text2}'>Brak transkrypcji. Użyj „Więcej → Transkrybuj ponownie z nagrania”.</p>")
    rows = "".join(f"<p style='margin:0 0 8px 0'><a href='seek:{s['start']}' style='color:{t.text3}; "
                   f"text-decoration:none'>{fmt_time(s['start'])}</a>"
                   f"&nbsp;&nbsp;{html.escape(s['text'])}</p>" for s in segs)
    return f"<body style='color:{t.text}; line-height:160%'>{rows}</body>"


# ---------------------------------------------------------------------------
def _placeholder_icon() -> QIcon:
    pm = QPixmap(GRID_ICON)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(T().hover))
    p.drawRoundedRect(0, 0, GRID_ICON.width(), GRID_ICON.height(), T().r("sm"), T().r("sm"))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
class OutlineDelegate(QStyledItemDelegate):
    """Spis treści obok notatki: nagłówki kategorii w kolorze, tematy z kolorowym paskiem, pełne tytuły
    (do dwóch linii), czas z prawej."""
    TIME = Qt.ItemDataRole.UserRole + 10
    LEVEL = Qt.ItemDataRole.UserRole + 11      # 0 = kategoria, 1 = sekcja główna, 2 = temat
    COLOR = Qt.ItemDataRole.UserRole + 12

    def _text_rect_w(self) -> int:
        return max(80, self.parent().viewport().width() - 26 - 50)

    def sizeHint(self, option, index):
        from PySide6.QtGui import QFontMetrics
        lvl = index.data(self.LEVEL)
        lvl = 1 if lvl is None else lvl
        if lvl == 0:
            return QSize(200, 34)
        fm = QFontMetrics(option.font)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        r = fm.boundingRect(0, 0, self._text_rect_w(), 200, int(Qt.TextFlag.TextWordWrap), text)
        lines = min(2, max(1, round(r.height() / max(1, fm.lineSpacing()))))
        return QSize(200, 12 + lines * fm.lineSpacing())

    def paint(self, p: QPainter, option, index):
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QStyle
        from .theme import qcolor, soft
        t = T()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(0, 1, -6, -1)
        hover = option.state & QStyle.StateFlag.State_MouseOver
        lvl = index.data(self.LEVEL)
        lvl = 1 if lvl is None else lvl
        color = index.data(self.COLOR) or t.text3
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if lvl == 0:
            f = QFont(option.font)
            f.setWeight(QFont.Weight.Bold)
            f.setPointSizeF(f.pointSizeF() - 0.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(soft(color)))
            pill = QRectF(r.left() + 2, r.top() + 7, r.width() - 4, r.height() - 9)
            p.drawRoundedRect(pill, T().r("sm"), T().r("sm"))
            p.setBrush(qcolor(color))
            p.drawEllipse(QRectF(pill.left() + 10, pill.center().y() - 4, 8, 8))
            p.setFont(f)
            p.setPen(qcolor(t.text))
            cnt = index.data(self.TIME) or ""
            p.drawText(pill.adjusted(26, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(pill.width() - 60)))
            p.setPen(qcolor(t.text3))
            p.drawText(pill.adjusted(0, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, cnt)
            p.restore()
            return
        sel = option.state & QStyle.StateFlag.State_Selected
        if sel or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft if sel else t.hover))
            p.drawRoundedRect(r, t.r("sm"), t.r("sm"))
        x = r.left() + (22 if lvl == 2 else 10)
        if lvl == 2:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(color))
            p.drawRoundedRect(QRectF(r.left() + 10, r.top() + 6, 3, r.height() - 12), 1.5, 1.5)
        tm = index.data(self.TIME) or ""
        fs = QFont(option.font)
        fs.setPointSizeF(option.font.pointSizeF() - 1)
        p.setFont(fs)
        tw = p.fontMetrics().horizontalAdvance(tm) + 10 if tm else 0
        if tm:
            p.setPen(qcolor(t.text3))
            p.drawText(QRectF(r.right() - tw - 4, r.top() + 5, tw, 20), Qt.AlignmentFlag.AlignRight, tm)
        f = QFont(option.font)
        if lvl == 1:
            f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.text if (hover or lvl == 1) else t.text2))
        tr = QRectF(x, r.top() + 5, r.right() - x - max(tw, 46), r.height() - 8)
        fm = p.fontMetrics()
        lines, rest = [], text
        for _ in range(2):          # najwyżej dwie linie, dopiero druga z wielokropkiem
            if not rest:
                break
            if fm.horizontalAdvance(rest) <= tr.width() or len(lines) == 1:
                lines.append(fm.elidedText(rest, Qt.TextElideMode.ElideRight, int(tr.width())))
                rest = ""
                break
            cut = len(rest)
            while cut > 1 and fm.horizontalAdvance(rest[:cut]) > tr.width():
                cut = rest.rfind(" ", 0, cut - 1) if rest.rfind(" ", 0, cut - 1) > 0 else cut - 1
            lines.append(rest[:cut].rstrip())
            rest = rest[cut:].lstrip()
        p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "\n".join(lines))
        p.restore()


class LibraryTab(QWidget):
    study_requested = Signal(object)      # Lecture
    continue_requested = Signal(object)   # Lecture – nagraj kolejną część
    new_from_files = Signal()             # „Importuj nagranie” → Nowa notatka / Z pliku
    exam_requested = Signal(object)       # Lecture – egzamin próbny z tego wykładu
    library_changed = Signal()

    def __init__(self, settings, runner: JobRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings
        self.runner = runner
        self.current: Lecture | None = None
        self.subject_filter: str | None = None
        self._sig: tuple | None = None
        self._gen = 0
        self._rendered: set[int] = set()
        self._pending_anchor: str | None = None

        # ================= lista =================
        self.list_title = label("Wszystkie wykłady", "title2")
        self.list_count = label("", "footnote")
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Szukaj w tytułach i notatkach")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(lambda: self.refresh())
        self.search.textChanged.connect(lambda _t: self._search_timer.start())

        self.list_filter = SegmentedControl(["Wszystkie", "Do nauki", "W toku"])
        self.list_filter.changed.connect(lambda _i: self.refresh())
        self.list_filter.setToolTip("Do nauki – są fiszki do powtórki dziś · W toku – nagrywanie albo praca AI")
        self.list = QListWidget()
        self.list.setObjectName("lectureList")
        self.list.setItemDelegate(LectureDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemClicked.connect(lambda _it: self._open_detail())

        self.btn_import = QPushButton("Notatka z pliku (m4a, mp3, wideo)…")
        self.btn_import.setObjectName("plain")
        self.btn_import.setToolTip("Plik audio lub wideo (mp3, m4a, wav, mp4, mkv…), np. nagranie z e-learningu")
        set_icon(self.btn_import, "import", "accent", 16)
        self.btn_import.clicked.connect(self.new_from_files.emit)

        left = QWidget()
        left.setObjectName("listPane")
        left.setFixedWidth(316)
        self.left = left
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 22, 10, 12)
        ll.setSpacing(8)
        self.list_title.setContentsMargins(6, 0, 0, 0)
        self.list_count.setContentsMargins(6, 0, 0, 4)
        ll.addWidget(self.list_title)
        ll.addWidget(self.list_count)
        self.btn_glossary = QPushButton("Słownik terminów przedmiotu…")
        self.btn_glossary.setObjectName("plain")
        self.btn_glossary.setToolTip("Nazwiska i terminy, które mają być dobrze rozpoznawane w nagraniach tego przedmiotu")
        self.btn_glossary.clicked.connect(self.edit_glossary)
        self.btn_glossary.hide()
        ll.addWidget(self.btn_glossary, 0, Qt.AlignmentFlag.AlignLeft)
        ll.addWidget(self.search)
        ll.addWidget(self.list_filter)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.btn_import, 0, Qt.AlignmentFlag.AlignLeft)

        # ================= szczegóły: nagłówek =================
        # [przedmiot · data · czas · slajdy · tematy]  /  Tytuł (32 px)      [Ucz się · 16 fiszek] [⤴] […]
        self.title = label("", "h1", wrap=True)
        self.meta = label("", "secondary", wrap=True)
        self.pill = StatusPill()
        self.error = label("", "errorText", wrap=True)

        self.btn_notes = QPushButton("Generuj notatki")
        self.btn_notes.setObjectName("primary")
        set_icon(self.btn_notes, "sparkles", "on_accent", 16)
        self.btn_notes.clicked.connect(lambda: self.generate_notes())
        self.btn_learn = QPushButton("Ucz się")
        self.btn_learn.setObjectName("primary")
        set_icon(self.btn_learn, "play", "on_accent", 14)
        self.btn_learn.clicked.connect(lambda: self.current and self.study_requested.emit(self.current))
        self.btn_share = icon_button("share", "Eksportuj")
        m = QMenu(self)
        m.addAction("Otwórz w przeglądarce (HTML)", self.export_html)
        m.addAction("Zapisz jako PDF…", self.export_pdf)
        m.addAction("Fiszki do Anki…", self.export_anki)
        m.addSeparator()
        m.addAction("Kopiuj notatki (Markdown)", self.copy_md)
        self.btn_share.setMenu(m)
        self.btn_share.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_more = icon_button("more", "Więcej")
        mm = QMenu(self)
        self.act_regen = mm.addAction("Generuj ponownie", lambda: self.generate_notes())
        mm.addSeparator()
        mm.addAction("Kontynuuj nagrywanie (kolejna część)", lambda: self.current and
                     self.continue_requested.emit(self.current))
        mm.addAction("Edytuj notatki", self.edit_notes)
        mm.addAction("Dodaj zdjęcia slajdów…", self.add_photos)
        mm.addSeparator()
        mm.addAction("Zmień tytuł i przedmiot…", self.rename)
        mm.addAction("Transkrybuj ponownie z nagrania", lambda: self.retranscribe())
        mm.addAction("Otwórz nagranie audio", self.open_audio)
        mm.addAction("Pokaż w folderze", self.open_folder)
        mm.addSeparator()
        mm.addAction("Usuń wykład…", self.delete)
        self.btn_more.setMenu(mm)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.btn_back = QPushButton("Wykłady")
        self.btn_back.setObjectName("back")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        set_icon(self.btn_back, "chevron-left", "accent", 16)
        self.btn_back.clicked.connect(self._back)
        self.btn_back.hide()
        self.subject_chip = SubjectChip()
        text_w = QWidget()
        head_text = QVBoxLayout(text_w)
        head_text.setContentsMargins(0, 0, 0, 0)
        head_text.setSpacing(6)
        ml = QHBoxLayout()
        ml.setSpacing(8)
        ml.addWidget(self.subject_chip)
        ml.addWidget(self.pill)
        ml.addWidget(self.meta, 1)
        head_text.addLayout(ml)
        head_text.addWidget(self.title)
        head_text.addWidget(self.error)
        actions = hbox(self.btn_learn, self.btn_notes, self.btn_share, self.btn_more, spacing=4)
        actions.layout().insertSpacing(2, 6)
        head = AdaptiveBox(threshold=760, spacing=16, vspacing=10)
        head.add(text_w, 1)
        head.add(actions, 0, Qt.AlignmentFlag.AlignTop, Qt.AlignmentFlag.AlignLeft)
        self.head = head

        self.seg = SegmentedControl(["Notatki", "Ściąga", "Zapytaj", "Slajdy", "Transkrypcja", "Fiszki", "Egzamin"],
                                    style="tabs")
        self._seg_to_page = [NOTES, CHEAT, ASK, SLIDES, TRANSCRIPT, CARDS, EXAM]
        self.seg.short = {"Transkrypcja": "Tekst", "Notatki": "Notatki", "Egzamin": "Test"}
        self.seg.changed.connect(lambda i: self._show_page(self._seg_to_page[i]))

        # --- baner zadania ---
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 12, 12)
        bl.setSpacing(8)
        self.job_label = label("", "headline")
        self.job_bar = QProgressBar()
        self.job_bar.setTextVisible(False)
        self.btn_ai = QPushButton("Pokaż, co pisze AI")
        self.btn_ai.setObjectName("plain")
        self.btn_ai.clicked.connect(self._toggle_ai)
        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.setObjectName("plain")
        self.btn_cancel.clicked.connect(lambda: self.runner.cancel.set())
        r1 = QHBoxLayout()
        r1.addWidget(self.job_label, 1)
        r1.addWidget(self.btn_ai)
        r1.addWidget(self.btn_cancel)
        bl.addLayout(r1)
        bl.addWidget(self.job_bar)
        self.ai_log = QPlainTextEdit()
        self.ai_log.setReadOnly(True)
        self.ai_log.setMaximumHeight(170)
        self.ai_log.hide()
        bl.addWidget(self.ai_log)
        self.banner.hide()

        # ================= strony =================
        # Notatki
        self.notes_view = Reader(max_width=640, pad=34)
        self.notes_empty_btn = QPushButton("Generuj notatki")
        self.notes_empty_btn.setObjectName("primary")
        self.notes_empty_btn.clicked.connect(lambda: self.generate_notes())
        self.notes_empty = EmptyState("sparkles", "Brak notatek",
                                      "Lokalny model AI przygotuje podsumowanie, notatki według slajdów i fiszki. "
                                      "Nic nie jest wysyłane do internetu.", self.notes_empty_btn)
        self.notes_stack = QStackedWidget()
        self.notes_stack.addWidget(self.notes_view)
        self.notes_stack.addWidget(self.notes_empty)
        from PySide6.QtGui import QFont
        self.editor = QPlainTextEdit()
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(10.5)
        self.editor.setFont(mono)
        self.btn_save_edit = QPushButton("Zapisz zmiany")
        self.btn_save_edit.setObjectName("primary")
        self.btn_save_edit.clicked.connect(self.save_edit)
        self.btn_cancel_edit = QPushButton("Anuluj")
        self.btn_cancel_edit.clicked.connect(self.cancel_edit)
        ew = QWidget()
        el = QVBoxLayout(ew)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(8)
        erow = QHBoxLayout()
        erow.addWidget(label("Edycja notatki (Markdown): # nagłówki, - punkty, **pogrubienie**, wzory $x^2$.",
                             "footnote"), 1)
        erow.addWidget(self.btn_cancel_edit)
        erow.addWidget(self.btn_save_edit)
        el.addLayout(erow)
        el.addWidget(self.editor, 1)
        self.notes_stack.addWidget(ew)          # indeks 2 = edycja
        # spis treści obok notatki (szeroki ekran)
        self.outline = QListWidget()
        self.outline.setObjectName("outline")
        self.outline.setItemDelegate(OutlineDelegate(self.outline))
        self.outline.setMouseTracking(True)
        self.outline.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.outline.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.outline.itemClicked.connect(self._outline_jump)
        from .note_nav import JumpButtons, LectureTimeline
        self.read_label = label("Przeczytano 0%", "caption")
        self.read_bar = QProgressBar()
        self.read_bar.setTextVisible(False)
        self.read_bar.setRange(0, 100)
        self.jump_btns = JumpButtons()
        self.jump_btns.jump.connect(self._jump_kind)
        self.outline_box = QWidget()
        ob = QVBoxLayout(self.outline_box)
        ob.setContentsMargins(6, 4, 0, 0)
        ob.setSpacing(8)
        ob.addWidget(label("W TEJ NOTATCE", "sectionHeader"))
        ob.addWidget(self.read_label)
        ob.addWidget(self.read_bar)
        ob.addSpacing(4)
        ob.addWidget(self.outline, 1)
        ob.addWidget(label("PRZEJDŹ DO", "sectionHeader"))
        ob.addWidget(self.jump_btns)
        self.outline_box.setFixedWidth(248)
        self.outline.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.outline_box.hide()
        self._outline_on = False
        self.timeline = LectureTimeline()
        self.timeline.seek.connect(self._timeline_seek)
        self.timeline.hide()
        self._positions: dict | None = None
        self._sec_info: list = []
        self.notes_view.verticalScrollBar().valueChanged.connect(self._on_note_scroll)
        self.notes_view.verticalScrollBar().rangeChanged.connect(lambda *_: self._invalidate_positions())
        # --- 21:9: stały panel „Zapytaj notatkę” + „W tym miejscu wykładu” (Ctrl+J zwija) ---
        self.side_ask = AskPanel(settings, busy_hint=lambda: self.runner.busy)
        self.side_ask.compact = True
        self.side_ask.internal_link.connect(lambda a: self.notes_view.scrollToAnchor(a))
        self.side_ask.seek_requested.connect(
            lambda t: self.current and self.player.play(self.current, t, None, "Odpowiedź"))
        self.side_ask.answered.connect(self._side_actions_state)
        self.qa_card = QPushButton("Zrób z tego fiszkę")
        self.qa_example = QPushButton("Podaj przykład")
        self.qa_simple = QPushButton("Wyjaśnij prościej")
        for b, fn, ic in ((self.qa_card, self._qa_to_card, "cards"), (self.qa_example, self._qa_example, "sparkles"),
                          (self.qa_simple, self._qa_simpler, "text")):
            b.setObjectName("chipBtn")
            set_icon(b, ic, "accent_text", 14)
            b.clicked.connect(fn)
        self.qa_status = label("", "caption", wrap=True)
        b_hide = QPushButton("")
        b_hide.setObjectName("plain")
        b_hide.setToolTip("Zwiń panel (Ctrl+J)")
        set_icon(b_hide, "xmark", "text2", 14)
        b_hide.setFixedWidth(36)
        b_hide.clicked.connect(self.toggle_side)
        self.place_img = QLabel()
        self.place_img.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.place_cap = label("", "caption")
        self.place_text = label("", "footnote", wrap=True)
        self.place_text.setTextFormat(Qt.TextFormat.RichText)
        self.place_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.place_text.linkActivated.connect(
            lambda u: u.startswith("seek:") and self.current and
            self.player.play(self.current, float(u[5:]), None, "Transkrypcja"))
        self.side_box = QWidget()
        sbl = QVBoxLayout(self.side_box)
        sbl.setContentsMargins(4, 4, 0, 0)
        sbl.setSpacing(8)
        hh = QHBoxLayout()
        hh.addWidget(label("ZAPYTAJ NOTATKĘ", "sectionHeader"), 1)
        hh.addWidget(label("Ctrl J", "caption"))
        hh.addWidget(b_hide)
        sbl.addLayout(hh)
        sbl.addWidget(self.side_ask, 3)
        qrow = QHBoxLayout()
        qrow.setSpacing(6)
        for b in (self.qa_card, self.qa_example, self.qa_simple):
            qrow.addWidget(b)
        qrow.addStretch()
        sbl.addLayout(qrow)
        sbl.addWidget(self.qa_status)
        sbl.addSpacing(6)
        sbl.addWidget(label("W TYM MIEJSCU WYKŁADU", "sectionHeader"))
        prow = QHBoxLayout()
        prow.setSpacing(12)
        pl = QVBoxLayout()
        pl.setSpacing(4)
        pl.addWidget(self.place_img)
        pl.addWidget(self.place_cap)
        pl.addStretch()
        prow.addLayout(pl)
        prow.addWidget(self.place_text, 1)
        sbl.addLayout(prow, 2)
        self.side_box.setFixedWidth(540)
        self.side_box.hide()
        self._side_hidden = False
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(250)
        self._place_timer.timeout.connect(self._update_place)
        from PySide6.QtGui import QKeySequence, QShortcut
        sc = QShortcut(QKeySequence("Ctrl+J"), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.toggle_side)

        notes_col = QWidget()
        ncl = QVBoxLayout(notes_col)
        ncl.setContentsMargins(0, 0, 0, 0)
        ncl.setSpacing(8)
        ncl.addWidget(self.notes_stack, 1)
        ncl.addWidget(self.timeline)
        notes_page = QWidget()
        npl = QHBoxLayout(notes_page)
        npl.setContentsMargins(0, 0, 0, 0)
        npl.setSpacing(18)
        npl.addWidget(notes_col, 1)
        npl.addWidget(self.outline_box)
        npl.addWidget(self.side_box)

        # Slajdy: miniatury (klik = powiększenie, × = usuń) albo cały tekst do skopiowania
        from .slide_views import SlideTextPanel, SlideThumbs
        self.slides_view = SlideThumbs(GRID_ICON, deletable=True)
        self.slides_view.open_requested.connect(self._preview_slide)
        self.slides_view.delete_requested.connect(lambda i: self._delete_slide(i, ask=True))
        self.slides_text = SlideTextPanel("Tekst ze wszystkich slajdów")
        self.slides_mode = SegmentedControl(["Miniatury", "Tekst"])
        self.slides_inner = QStackedWidget()
        self.slides_inner.addWidget(self.slides_view)
        self.slides_inner.addWidget(self.slides_text)
        self.slides_mode.changed.connect(self.slides_inner.setCurrentIndex)
        sw_ = QWidget()
        swl = QVBoxLayout(sw_)
        swl.setContentsMargins(0, 0, 0, 0)
        swl.setSpacing(10)
        swl.addWidget(self.slides_mode, 0, Qt.AlignmentFlag.AlignLeft)
        swl.addWidget(self.slides_inner, 1)
        self.slides_empty = EmptyState("photo", "Brak slajdów", "Ten wykład był nagrany bez źródła slajdów.")
        self.slides_stack = QStackedWidget()
        self.slides_stack.addWidget(sw_)
        self.slides_stack.addWidget(self.slides_empty)

        # Transkrypcja
        self.transcript_view = Reader(max_width=820, pad=30)

        # Fiszki
        self.cards_summary = label("", "headline")
        self.cards_sub = label("", "secondary")
        self.btn_study = QPushButton("Ucz się")
        self.btn_study.setObjectName("primary")
        set_icon(self.btn_study, "play", "on_accent", 14)
        self.btn_study.clicked.connect(lambda: self.current and self.study_requested.emit(self.current))
        self.cards_view = Reader(max_width=820, pad=30)
        self.cards_empty = EmptyState("cards", "Brak fiszek", "Fiszki powstają automatycznie razem z notatkami.")
        self.cards_stack = QStackedWidget()
        self.cards_stack.addWidget(self.cards_view)
        self.cards_stack.addWidget(self.cards_empty)
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)
        ch = QHBoxLayout()
        ctext = QVBoxLayout()
        ctext.setSpacing(2)
        ctext.addWidget(self.cards_summary)
        ctext.addWidget(self.cards_sub)
        ch.addLayout(ctext, 1)
        ch.addWidget(self.btn_study)
        cl.addLayout(ch)
        cl.addWidget(self.cards_stack, 1)

        # Zapytaj
        self.ask_panel = AskPanel(settings, busy_hint=lambda: self.runner.busy)
        self.ask_panel.internal_link.connect(self._jump_to_notes)
        self.ask_stack = self.ask_panel

        # Ściąga: definicje, wzory, przykłady, ważne – po tematach, z odnośnikiem do notatki
        self.cheat_filter = SegmentedControl(["Wszystko", "Definicje", "Wzory", "Przykłady", "Ważne"])
        self.cheat_filter.changed.connect(lambda _i: self._render_cheat())
        self.cheat_view = Reader(max_width=820, pad=30)
        self.cheat_view.internal_link.connect(
            lambda a: a.startswith("note-") and self._jump_to_notes(a[5:]))
        self.cheat_empty = EmptyState("list", "Ściąga jest pusta",
                                      "Ściąga zbiera definicje, wzory, przykłady i ważne rzeczy z ramek w notatce. "
                                      "Starsze notatki nie mają ramek – kliknij „Generuj ponownie”.")
        self.cheat_stack = QStackedWidget()
        self.cheat_stack.addWidget(self.cheat_view)
        self.cheat_stack.addWidget(self.cheat_empty)
        chw = QWidget()
        chl = QVBoxLayout(chw)
        chl.setContentsMargins(0, 0, 0, 0)
        chl.setSpacing(10)
        chl.addWidget(self.cheat_filter, 0, Qt.AlignmentFlag.AlignLeft)
        chl.addWidget(self.cheat_stack, 1)

        # Egzamin próbny z tego wykładu
        b_exam = QPushButton("Przygotuj egzamin")
        b_exam.setObjectName("primary")
        set_icon(b_exam, "exam", "on_accent", 16)
        b_exam.clicked.connect(lambda: self.current and self.exam_requested.emit(self.current))
        self.exam_page = EmptyState("exam", "Egzamin próbny z tego wykładu",
                                    "Pytania A–D, prawda/fałsz i otwarte – każde sprawdzone w tej notatce. "
                                    "Liczbę pytań i poziom wybierzesz na następnym ekranie.", b_exam)

        self.pages = QStackedWidget()
        for w in (notes_page, self.slides_stack, self.transcript_view, cw, self.ask_stack, chw, self.exam_page):
            self.pages.addWidget(w)       # indeksy = NOTES, SLIDES, TRANSCRIPT, CARDS, ASK, CHEAT, EXAM

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(30, 22, 30, 18)
        dl.setSpacing(12)
        self.detail_lay = dl
        dl.addWidget(self.btn_back, 0, Qt.AlignmentFlag.AlignLeft)
        dl.addWidget(head)
        dl.addWidget(self.banner)
        dl.addWidget(self.seg)
        dl.addWidget(self.pages, 1)
        from .player import PlayerBar
        self.player = PlayerBar()
        dl.addWidget(self.player)
        self.notes_view.play_requested.connect(
            lambda frags: self.current and self.player.choose(self.current, frags, self.notes_view, QCursor.pos()))
        self.notes_view.seek_requested.connect(
            lambda t: self.current and self.player.play(self.current, t, None, "Notatka"))
        self.transcript_view.seek_requested.connect(
            lambda t: self.current and self.player.play(self.current, t, None, "Transkrypcja"))

        self.detail_empty = EmptyState("books", "Wybierz wykład",
                                       "Tu zobaczysz notatki, slajdy, transkrypcję i fiszki wybranego wykładu.")
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(detail)

        sep = QFrame()
        sep.setObjectName("vline")
        sep.setFixedWidth(1)
        self.sep = sep
        self._compact = None
        self._show_detail = False
        self._list_w = 310
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(left)
        lay.addWidget(sep)
        lay.addWidget(self.detail_stack, 1)

        runner.started.connect(self._job_started)
        runner.progress.connect(self._job_progress)
        runner.token.connect(self._job_token)
        runner.finished.connect(self._job_finished)
        theme().changed.connect(lambda: self._load(self.current, force=True))
        self.refresh()

    def _dpr(self) -> float:
        return self.devicePixelRatioF() or 1.0

    # ------------------------------------------------------------------ lista
    def edit_glossary(self):
        from ..storage import load_glossary, save_glossary
        subj = self.subject_filter
        if not subj:
            return
        cur = load_glossary(self.settings.library_path(), subj)
        text, ok = QInputDialog.getMultiLineText(
            self, f"Słownik: {subj}",
            "Terminy, nazwiska i skróty z tego przedmiotu (oddzielone przecinkami lub w osobnych liniach).\n"
            "Pomagają poprawnie rozpoznawać je w nagraniach. Terminy ze slajdów dodają się same.", cur)
        if ok:
            save_glossary(self.settings.library_path(), subj, text)

    def set_filter(self, subject: str | None):
        if subject == self.subject_filter and self.list.count():
            return
        self.subject_filter = subject
        self._show_detail = False
        self._apply_layout()
        show_if(self.btn_glossary, subject)
        self.list_title.setText("Wszystkie wykłady" if subject is None else (subject or "Bez przedmiotu"))
        self.refresh()

    def refresh(self, select_folder: str | None = None):
        from datetime import date, datetime, timedelta
        from ..storage import card_stats
        if not isinstance(select_folder, str):
            select_folder = str(self.current.folder) if self.current else None
        q = self.search.text().strip().lower()
        flt = self.list_filter.current()
        self.list.setUpdatesEnabled(False)
        self.list.blockSignals(True)
        self.list.clear()
        to_select = None
        count = 0
        monday = date.today() - timedelta(days=date.today().weekday())
        group_shown = set()
        for lec in list_lectures(self.settings.library_path()):
            m = lec.meta
            if self.subject_filter is not None and m.subject != self.subject_filter:
                continue
            if q and q not in f"{m.title} {m.subject}".lower() and q not in notes_lower(lec):
                continue
            busy = self._job_is_for(lec) or m.status in ("nagrywanie", "przetwarzanie")
            n_cards, due = card_stats(lec)
            if flt == 1 and not due:
                continue
            if flt == 2 and not busy:
                continue
            try:
                d = datetime.fromisoformat(m.created).date()
            except Exception:  # noqa: BLE001
                d = monday - timedelta(days=1)
            grp = "Ten tydzień" if d >= monday else "Wcześniej"
            if grp not in group_shown:
                group_shown.add(grp)
                h = QListWidgetItem()
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                h.setData(LectureDelegate.ROLE, {"header": grp})
                self.list.addItem(h)
            count += 1
            progress = None
            if self._job_is_for(lec):
                frac = getattr(self, "_job_frac", -1.0)
                status = (f"AI {int(frac * 100)}%" if frac >= 0 else "AI pracuje", "blue")
                progress = frac
            elif m.status == "nagrywanie":
                status = ("Nagrywanie", "red")
            elif lec.notes_path.exists():
                status = ("Gotowe", "blue") if m.status != "błąd" else ("Błąd", "red")
            else:
                status = ("Bez notatek", "gray") if m.status != "błąd" else ("Błąd", "red")
            cards_txt = (f"{n_cards} fiszek" if n_cards != 1 else "1 fiszka") if n_cards else ""
            sub = " · ".join(x for x in [lecture_date(lec), fmt_time(m.duration) if m.duration else "", cards_txt,
                                         m.subject if self.subject_filter is None and not cards_txt else ""] if x)
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, str(lec.folder))
            it.setData(LectureDelegate.ROLE, {"title": m.title, "sub": sub, "pill": status, "subject": m.subject,
                                              "progress": progress})
            it.setToolTip(m.title + (f" · do powtórki dziś: {due}" if due else ""))
            self.list.addItem(it)
            if select_folder and str(lec.folder) == select_folder:
                to_select = (it, lec)
        self.list.blockSignals(False)
        self.list.setUpdatesEnabled(True)
        self.list_count.setText(plural_lectures(count) if not flt else
                                f"{plural_lectures(count)} · filtr: {['', 'do nauki', 'w toku'][flt]}")
        if to_select:
            self.list.blockSignals(True)
            self.list.setCurrentItem(to_select[0])
            self.list.blockSignals(False)
            self._load(to_select[1])
        else:
            self._load(None)

    def select(self, lecture: Lecture):
        self._show_detail = True
        self._apply_layout()
        if self.subject_filter is not None and lecture.meta.subject != self.subject_filter:
            self.subject_filter = None
            self.list_title.setText("Wszystkie wykłady")
        self.refresh(str(lecture.folder))
        self._apply_layout()

    def _on_select(self, item, _prev):
        folder = item.data(Qt.ItemDataRole.UserRole) if item else None
        lec = next((l for l in list_lectures(self.settings.library_path()) if str(l.folder) == folder), None) \
            if folder else None
        self._load(lec)
        self._open_detail()

    # ------------------------------------------------------------------ szczegóły
    def _load(self, lec: Lecture | None, force: bool = False):
        if lec is None or not lec.folder.exists():
            self.current = None
            self._sig = None
            self.detail_stack.setCurrentIndex(0)
            return
        sig = _sig(lec)
        same = (not force and self.current is not None and self._sig == sig)
        self.current = lec
        self._update_header()
        if same:
            return
        self._sig = sig
        self._gen += 1
        self._rendered.clear()
        self._apply_side()
        if self.side_box.isVisible():
            self._load_side()
        self.detail_stack.setCurrentIndex(1)
        self._show_page(self.pages.currentIndex())

    def _update_header(self):
        from ..storage import card_stats
        from ..topics import sections_of
        lec = self.current
        if not lec:
            return
        m = lec.meta
        self.title.setText(m.title)
        n_slides = len(slides_info(lec).get("slides", []))
        busy_here = self._job_is_for(lec)
        has_notes = lec.notes_path.exists()
        n_topics = len(sections_of(lec.read_text(lec.notes_path))) if has_notes else 0
        n_cards, due = card_stats(lec)
        if busy_here:
            self.pill.set("AI pracuje", "blue")
        elif m.status == "błąd":
            self.pill.set("Błąd", "red")
        elif not has_notes:
            self.pill.set("Bez notatek", "gray")
        else:
            self.pill.set("", "gray")
        self.subject_chip.set(m.subject)
        parts = [lecture_date(lec), fmt_time(m.duration) if m.duration else "",
                 (f"{n_slides} slajdów" if n_slides != 1 else "1 slajd") if n_slides else "",
                 (f"{n_topics} tematów" if n_topics != 1 else "1 temat") if n_topics else ""]
        self.meta.setText(" · ".join(x for x in parts if x))
        self.meta.setToolTip(f"Model notatek: {m.notes_model}" if m.notes_model else "")
        self.error.setText(f"Ostatnia próba nie powiodła się: {m.error}" if m.error and not busy_here else "")
        show_if(self.error, self.error.text())
        # główny przycisk: nauka z fiszek; bez notatek – generowanie
        self.btn_learn.setText(f"Ucz się · {n_cards} fiszek" if n_cards != 1 else "Ucz się · 1 fiszka")
        self.btn_learn.setToolTip(f"Do powtórki dziś: {due}" if due else "Wszystkie fiszki tego wykładu")
        show_if(self.btn_learn, n_cards)
        show_if(self.btn_notes, not has_notes)
        self.btn_notes.setEnabled(not self.runner.busy)
        self.act_regen.setText("Generuj ponownie" if has_notes else "Generuj notatki")
        self.act_regen.setEnabled(not self.runner.busy)
        self.notes_empty_btn.setEnabled(not self.runner.busy)
        self.banner.setVisible(busy_here)
        names = ["Notatki", "Ściąga", "Zapytaj", f"Slajdy {n_slides}" if n_slides else "Slajdy", "Transkrypcja",
                 f"Fiszki {n_cards}" if n_cards else "Fiszki", "Egzamin"]
        for i, name in enumerate(names):
            self.seg.set_text(i, name)

    def _show_page(self, page: int):
        self.pages.setCurrentIndex(page)
        if self.current is None or page in self._rendered:
            return
        self._rendered.add(page)
        {NOTES: self._render_notes, SLIDES: self._render_slides, TRANSCRIPT: self._render_transcript,
         CARDS: self._render_cards, ASK: self._render_ask, CHEAT: self._render_cheat,
         EXAM: lambda: None}[page]()

    def _render_notes(self):
        lec, gen = self.current, self._gen
        if not lec.notes_path.exists():
            self.notes_stack.setCurrentIndex(1)
            return
        self.notes_stack.setCurrentIndex(0)
        self.notes_view.setHtml(f"<p style='color:{T().text3}'>Wczytywanie notatek…</p>")
        md = lec.read_text(lec.notes_path)
        folder, dpr = lec.folder, self._dpr()
        toc = not self._outline_on
        self._fill_outline(md)

        def done(res):
            if gen != self._gen:
                return
            html_doc, images, plays = res
            sb = self.notes_view.verticalScrollBar()
            self.notes_view.images = images
            self.notes_view.plays = plays
            self.notes_view.setHtml(html_doc)
            sb.setValue(0)
            self._after_notes(md)
            if self._pending_anchor:
                QTimer.singleShot(30, lambda a=self._pending_anchor: self.notes_view.scrollToAnchor(a))
                self._pending_anchor = None
        run_async(lambda: build_notes(folder, md, dpr, toc=toc, no_title=True), done)

    def _render_slides(self):
        from .slide_views import SlideInfo
        lec, gen = self.current, self._gen
        slides = slides_info(lec).get("slides", [])
        self.slides_view.setUpdatesEnabled(False)
        self.slides_view.clear()
        for s_ in slides:
            self.slides_view.add_slide(s_["index"], str(lec.folder / s_["file"]), s_.get("t"),
                                       (s_.get("vision") or {}).get("text") or s_.get("ocr") or "", pixmap=QPixmap())
        self.slides_view.setUpdatesEnabled(True)
        self.slides_stack.setCurrentIndex(0 if slides else 1)
        self.slides_text.set_slides([SlideInfo(s_["index"], str(lec.folder / s_["file"]), float(s_.get("t") or 0),
                                               (s_.get("vision") or {}).get("text") or s_.get("ocr") or "")
                                     for s_ in slides])
        if not slides:
            return
        files = [s_["file"] for s_ in slides]
        folder, dpr = lec.folder, self._dpr()

        def done(images):
            if gen != self._gen:
                return
            from .slide_views import PIX
            for i, img in enumerate(images):
                if i < self.slides_view.count() and not img.isNull():
                    self.slides_view.item(i).setData(PIX, QPixmap.fromImage(img))
            self.slides_view.viewport().update()
        run_async(lambda: build_grid_icons(folder, files, dpr), done)

    def _preview_slide(self, index: int):
        from .slide_views import SlidePreview
        infos = self.slides_view.infos()
        pos = next((k for k, x in enumerate(infos) if x.index == index), 0)
        SlidePreview(infos, pos, self, on_delete=lambda i: self._delete_slide(i, ask=True),
                     extra_buttons=[("Otwórz plik", lambda si: si and QDesktopServices.openUrl(
                         QUrl.fromLocalFile(si.path)))]).exec()

    def _delete_slide(self, index: int, ask: bool = True) -> bool:
        lec = self.current
        if not lec:
            return False
        if self._job_is_for(lec):
            QMessageBox.information(self, "Usuń slajd", "Poczekaj, aż skończy się zadanie dla tego wykładu.")
            return False
        if ask and QMessageBox.question(self, "Usuń slajd", f"Usunąć slajd {index}? Zniknie też z notatki.") \
                != QMessageBox.StandardButton.Yes:
            return False
        from ..slides import delete_slide
        if not delete_slide(lec, index):
            return False
        self.slides_view.remove_slide(index)
        self.slides_text.set_slides(self.slides_view.infos())
        self._rendered.discard(NOTES)
        self._sig = None
        return True

    def _render_transcript(self):
        lec, gen = self.current, self._gen
        self.transcript_view.setHtml(f"<p style='color:{T().text3}'>Wczytywanie…</p>")

        def done(doc):
            if gen == self._gen:
                self.transcript_view.setHtml(doc)
        run_async(lambda: build_transcript(lec), done)

    def _render_cards(self):
        from ..flashcards import deck_markdown, decks_for
        lec, gen = self.current, self._gen
        cards = lec.load_flashcards()
        known = sum(1 for c in cards if c.get("known"))
        decks = decks_for([lec])
        self.cards_summary.setText(f"{len(cards)} fiszek w {len(decks)} kategoriach" if cards else "Brak fiszek")
        self.cards_sub.setText(f"Opanowane: {known} z {len(cards)}" if cards else "")
        self.btn_study.setEnabled(bool(cards))
        self.cards_stack.setCurrentIndex(0 if cards else 1)
        if not cards:
            return
        md = "\n".join(f"# {d.name}\n\n{deck_markdown(d)}\n" for d in decks)
        folder, dpr = lec.folder, self._dpr()

        def done(res):
            if gen != self._gen:
                return
            html_doc, images, _p = res
            self.cards_view.images = images
            self.cards_view.setHtml(html_doc)
        run_async(lambda: build_notes(folder, md, dpr, audio=False, toc=False), done)

    # ------------------------------------------------------------------ ściąga
    def _render_cheat(self):
        from .. import cheatsheet as CS
        lec, gen = self.current, self._gen
        if lec is None:
            return
        md = lec.read_text(lec.notes_path) if lec.notes_path.exists() else ""
        items = CS.extract(md)
        cnt = CS.counts(items)
        names = ["Wszystko"] + [f"{CS.KINDS[k]} {cnt[k]}" if cnt[k] else CS.KINDS[k] for k in CS.KINDS]
        for b, n in zip(self.cheat_filter.buttons, names):
            b.setText(n)
        self.cheat_filter.buttons[0].setText(f"Wszystko {len(items)}" if items else "Wszystko")
        if not items:
            self.cheat_stack.setCurrentIndex(1)
            return
        self.cheat_stack.setCurrentIndex(0)
        only = ["", *CS.KINDS][self.cheat_filter.current()]
        doc = CS.to_markdown(items, only)
        folder, dpr = lec.folder, self._dpr()
        view = self.cheat_view

        def done(res):
            if gen != self._gen:
                return
            html_doc, images, _p = res
            view.images = images
            view.setHtml(html_doc)
        run_async(lambda: build_notes(folder, doc, dpr, audio=False, toc=False), done)

    # ------------------------------------------------------------------ spis treści obok notatki
    def _fill_outline(self, md: str):
        """Tematy pogrupowane w kategorie (każda w swoim kolorze), pełne tytuły bez „Krótki tytuł tematu”."""
        from ..notes_doc import headings
        from ..topics import clean_title, load_categories
        from .theme import palette_color
        self.outline.clear()
        hs = headings(md)
        cats = load_categories(self.current, md) if self.current is not None else []
        cat_of = {n: ci for ci, c in enumerate(cats) for n in c["sections"]}
        shown_cat = None
        nested = any(x.level == 1 for x in hs)
        for h in hs:
            m = re.match(r"^(\d+)\.\s*(★\s*)?(.*)$", h.label.strip())
            num = int(m.group(1)) if m else 0
            label = f"{num}. {(m.group(2) or '')}{clean_title(m.group(3))}" if m else h.label
            if m and num in cat_of and cat_of[num] != shown_cat:
                shown_cat = cat_of[num]
                c = cats[shown_cat]
                head = QListWidgetItem(c["name"])
                head.setData(Qt.ItemDataRole.UserRole, h.anchor)
                head.setData(OutlineDelegate.LEVEL, 0)
                head.setData(OutlineDelegate.COLOR, palette_color(shown_cat))
                head.setData(OutlineDelegate.TIME, str(len(c["sections"])))
                head.setToolTip(f"{c['name']} – tematy: {len(c['sections'])}")
                self.outline.addItem(head)
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, h.anchor)
            it.setData(OutlineDelegate.TIME, h.time)
            if m:
                it.setData(OutlineDelegate.LEVEL, 2)
                if num in cat_of:
                    it.setData(OutlineDelegate.COLOR, palette_color(cat_of[num]))
            else:
                it.setData(OutlineDelegate.LEVEL, 2 if (nested and h.level >= 2) else 1)
            it.setToolTip(label + (f" · {h.time}" if h.time else ""))
            self.outline.addItem(it)

    def _outline_jump(self, it):
        anchor = it.data(Qt.ItemDataRole.UserRole)
        if anchor:
            self.notes_stack.setCurrentIndex(0)
            self.notes_view.scrollToAnchor(anchor)

    # ------------------------------------------------------------------ 21:9: panel „Zapytaj notatkę”
    def _apply_side(self):
        on = getattr(self, "_side_wide", False) and not self._side_hidden and self.current is not None \
            and self.current.notes_path.exists()
        if on != self.side_box.isVisible():
            self.side_box.setVisible(on)
            if on:
                self._load_side()

    def toggle_side(self):
        if not getattr(self, "_side_wide", False):
            self.seg.set_current(2, emit=True)           # węższe okno – zakładka „Zapytaj”
            return
        self._side_hidden = not self._side_hidden
        self._apply_side()

    def _load_side(self):
        from ..topics import sections_of
        from .note_nav import section_times
        lec = self.current
        if lec is None or not lec.notes_path.exists():
            return
        md = lec.read_text(lec.notes_path)
        times = section_times(md)
        self.side_ask.anchor_times = {a: times[n][0] for n, _t, a, _tm in sections_of(md) if n in times} \
            if lec.audio_parts() else {}
        self.side_ask.set_source(lambda: lec.read_text(lec.notes_path), lec.folder / "qa.json",
                                 self.settings.ollama_ctx)
        self._side_actions_state()
        self.qa_status.setText("")
        self._update_place()

    def _last_answer(self) -> dict | None:
        hist = self.side_ask.history()
        return next((a for a in reversed(hist) if a.get("status") in ("odpowiedz", "czesciowo")), None)

    def _side_actions_state(self):
        ok = self._last_answer() is not None
        for b in (self.qa_card, self.qa_example, self.qa_simple):
            b.setEnabled(ok)
            b.setToolTip("" if ok else "Najpierw zadaj pytanie")

    def _qa_example(self):
        a = self._last_answer()
        if a:
            self.side_ask.ask_text(f"Podaj przykład do pytania: {a['question']}")

    def _qa_simpler(self):
        a = self._last_answer()
        if a:
            self.side_ask.ask_text(f"Wyjaśnij prościej, krótko i bez żargonu: {a['question']}")

    def _qa_to_card(self):
        """Ostatnia odpowiedź → nowa fiszka w kategorii tematu, z którego pochodzi cytat."""
        from ..topics import category_of, load_categories, sections_of
        from .note_nav import section_times
        a = self._last_answer()
        lec = self.current
        if not a or lec is None:
            return
        md = lec.read_text(lec.notes_path)
        anchor = (a.get("quotes") or [{}])[0].get("anchor", "")
        secs = sections_of(md)
        num, title = next(((n, t) for n, t, an, _tm in secs if an == anchor), (0, ""))
        cats = load_categories(lec, md)
        times = section_times(md)
        q = a["question"]
        for pre in ("Podaj przykład do pytania: ", "Wyjaśnij prościej, krótko i bez żargonu: "):
            q = q.replace(pre, "")
        cards = lec.load_flashcards()
        if any(c.get("q", "").strip().lower() == q.strip().lower() for c in cards):
            self.qa_status.setText("Taka fiszka już jest.")
            return
        cards.append({"q": q, "a": a.get("answer", ""), "section": num, "t": times.get(num, (0.0, 0.0))[0],
                      "known": 0, "category": category_of(cats, num) if num else "", "topic": title,
                      "source": "zapytaj"})
        lec.save_flashcards(cards)
        cat = category_of(cats, num) if num else ""
        self.qa_status.setText("Dodano fiszkę" + (f" do kategorii „{cat}”." if cat else "."))
        self._update_header()
        self.library_changed.emit()

    def _update_place(self):
        """„W tym miejscu wykładu”: slajd i fragment transkrypcji z miejsca, które właśnie czytasz."""
        if not self.side_box.isVisible() or self.current is None:
            return
        from ..storage import fmt_time
        lec = self.current
        t_now = self.timeline.now
        ev = [e for e in lec.load_slides().get("events", []) if e["t"] <= t_now + 1]
        slide = None
        if ev:
            idx = ev[-1]["index"]
            slide = next((x for x in lec.load_slides().get("slides", []) if x["index"] == idx), None)
        if slide:
            from ..slides import ensure_thumb
            th = ensure_thumb(lec.folder, slide["file"])
            pm = QPixmap(str(th)) if th else QPixmap()
            if not pm.isNull():
                dpr = self._dpr()
                pm = pm.scaledToWidth(int(200 * dpr), Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                from .controls import rounded_pixmap
                self.place_img.setPixmap(rounded_pixmap(pm))
            self.place_cap.setText(f"Slajd {slide['index']} · {fmt_time(ev[-1]['t'])}")
        else:
            self.place_img.clear()
            self.place_cap.setText("")
        segs = [sg for sg in lec.load_segments() if t_now - 15 <= sg["start"] <= t_now + 45]
        t = T()
        if segs:
            self.place_text.setText("".join(
                f"<p style='margin:0 0 6px 0'><a href='seek:{sg['start']}' style='color:{t.text3}; "
                f"text-decoration:none'>{fmt_time(sg['start'])}</a>&nbsp; {html.escape(sg['text'])}</p>"
                for sg in segs[:6]))
        else:
            self.place_text.setText(f"<span style='color:{t.text3}'>Brak transkrypcji w tym miejscu.</span>")

    # ------------------------------------------------------------------ nawigacja po notatce
    def _after_notes(self, md: str):
        """Po wczytaniu notatki: oś wykładu, liczby ramek do „Przejdź do”, pozycje tematów."""
        from ..topics import load_categories, section_colors, sections_of
        from .note_nav import section_times
        from .theme import palette_color
        lec = self.current
        if lec is None:
            return
        cats = load_categories(lec, md)
        colors = section_colors(cats)
        times = section_times(md)
        self._sec_info = [(n, *times[n], palette_color(colors.get(n, 0)), a, title)
                          for n, title, a, _tm in sections_of(md) if n in times]
        timeline = bool(self._sec_info) and not (lec.meta.kind == "files" and not lec.audio_parts())
        marks = [float(m.get("start", 0)) for m in lec.load_marks()]
        self.timeline.set_data(self._sec_info, marks, float(lec.meta.duration or 0))
        self.timeline.setVisible(timeline)
        self._invalidate_positions()
        QTimer.singleShot(80, self._update_counts)

    def _invalidate_positions(self):
        self._positions = None

    def _pos(self) -> dict:
        if self._positions is None:
            from .note_nav import anchor_positions
            self._positions = anchor_positions(self.notes_view)
        return self._positions

    def _update_counts(self):
        pos = self._pos()
        self.jump_btns.set_counts({k: sum(1 for a in pos if a.startswith(f"box-{k}-"))
                                   for k in ("def", "wz", "prz", "waz")})
        self._on_note_scroll(self.notes_view.verticalScrollBar().value())

    def _on_note_scroll(self, v: int):
        sb = self.notes_view.verticalScrollBar()
        pct = 100 if sb.maximum() <= 0 else int(round(100 * v / sb.maximum()))
        self.read_label.setText(f"Przeczytano {pct}%")
        self.read_bar.setValue(pct)
        if self.current is None:
            return
        pos = self._pos()
        y = v + min(260, int(self.notes_view.viewport().height() * 0.35))
        cur_row, best = -1, -1.0
        for i in range(self.outline.count()):
            it = self.outline.item(i)
            if (it.data(OutlineDelegate.LEVEL) or 0) == 0:
                continue
            ay = pos.get(it.data(Qt.ItemDataRole.UserRole))
            if ay is not None and best <= ay <= y:
                cur_row, best = i, ay
        if cur_row >= 0 and self.outline.currentRow() != cur_row:
            self.outline.blockSignals(True)
            self.outline.setCurrentRow(cur_row)
            self.outline.scrollToItem(self.outline.item(cur_row))
            self.outline.blockSignals(False)
        info = sorted((pos.get(a), s, e) for _n, s, e, _c, a, _t in self._sec_info if pos.get(a) is not None)
        end_y = sb.maximum() + self.notes_view.viewport().height()
        for k, (ay, s, e) in enumerate(info):
            nxt = info[k + 1][0] if k + 1 < len(info) else end_y
            if y < nxt or k == len(info) - 1:
                frac = 0.0 if y < ay else min(1.0, (y - ay) / max(1.0, nxt - ay))
                self.timeline.set_now(s + frac * (e - s))
                break
        if self.side_box.isVisible():
            self._place_timer.start()

    def _timeline_seek(self, t: float):
        pos = self._pos()
        info = sorted((pos.get(a), s, e) for _n, s, e, _c, a, _t in self._sec_info if pos.get(a) is not None)
        sb = self.notes_view.verticalScrollBar()
        end_y = sb.maximum() + self.notes_view.viewport().height()
        for k, (ay, s, e) in enumerate(info):
            if t < e or k == len(info) - 1:
                nxt = info[k + 1][0] if k + 1 < len(info) else end_y
                frac = 0.0 if e <= s else max(0.0, min(1.0, (t - s) / (e - s)))
                self.notes_stack.setCurrentIndex(0)
                sb.setValue(int(ay + frac * (nxt - ay) - 60))
                return

    def _jump_kind(self, kind: str):
        ys = sorted(y for a, y in self._pos().items() if a.startswith(f"box-{kind}-"))
        if not ys:
            return
        sb = self.notes_view.verticalScrollBar()
        cur = sb.value() + 60
        nxt = next((y for y in ys if y > cur + 4), ys[0])
        sb.setValue(int(nxt - 50))

    # ------------------------------------------------------------------ układ: wąski / zwykły / szeroki
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        self._list_w = 340 if w >= 1700 else (300 if w >= 1100 else 280)
        compact = w - self._list_w < 580
        self._compact = compact
        self._apply_layout()
        outline = (not compact) and (w - self._list_w) >= 1050
        self._side_wide = (not compact) and w >= 1950        # okno ≥ ~2200 px (21:9)
        self._apply_side()
        if outline != self._outline_on:
            self._outline_on = outline
            self.outline_box.setVisible(outline)
            if self.current is not None and NOTES in self._rendered:
                self._rendered.discard(NOTES)
                if self.pages.currentIndex() == NOTES:
                    self._show_page(NOTES)
        m = (16, 12, 16, 12) if w < 700 else (30, 22, 30, 18)
        self.detail_lay.setContentsMargins(*m)

    def _apply_layout(self):
        if self._compact is None:
            return
        if self._compact:
            self.left.setMinimumWidth(0)
            self.left.setMaximumWidth(16777215)
            show_detail = self._show_detail and self.current is not None
            self.left.setVisible(not show_detail)
            self.sep.hide()
            self.detail_stack.setVisible(show_detail)
            self.btn_back.setVisible(True)
        else:
            self.left.setFixedWidth(self._list_w)
            self.left.show()
            self.sep.show()
            self.detail_stack.show()
            self.btn_back.hide()

    def _open_detail(self):
        if self._compact and self.current is not None:
            self._show_detail = True
            self._apply_layout()

    def _back(self):
        self._show_detail = False
        self._apply_layout()

    # ------------------------------------------------------------------ pytania do notatki
    def _render_ask(self):
        lec = self.current
        if lec.notes_path.exists():
            self.ask_panel.set_source(lambda: lec.read_text(lec.notes_path), lec.folder / "qa.json",
                                      self.settings.ollama_ctx)
        else:
            self.ask_panel.set_source(None, None, 0)

    def _jump_to_notes(self, anchor: str):
        self._pending_anchor = anchor
        self.seg.set_current(0)
        if NOTES in self._rendered:
            self.pages.setCurrentIndex(NOTES)
            self.notes_view.scrollToAnchor(anchor)
            self._pending_anchor = None
        else:
            self._show_page(NOTES)

    def add_photos(self):
        lec = self.current
        if not lec:
            return
        from ..photos import PHOTO_EXT
        pat = " ".join(f"*{e}" for e in PHOTO_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, "Zdjęcia slajdów", str(Path.home()),
                                                f"Zdjęcia ({pat});;Wszystkie pliki (*.*)")
        if not paths:
            return
        s = self.settings

        def fn(prog, cancel, tok):
            n = jobs.add_photos(lec, paths, s, prog, cancel, True)
            if n and s.auto_generate_notes and not cancel.is_set() and (lec.load_segments() or lec.notes_path.exists()):
                jobs.generate_notes(lec, s, prog, cancel, tok, use_cache=True)
        self._run("Dodawanie zdjęć slajdów", fn, lec)

    # ------------------------------------------------------------------ edycja notatek
    def edit_notes(self):
        lec = self.current
        if not lec or not lec.notes_path.exists():
            return
        if self._job_is_for(lec):
            return QMessageBox.information(self, "Edycja", "Poczekaj, aż skończy się generowanie notatek.")
        self.seg.set_current(0, emit=True)
        self.editor.setPlainText(lec.read_text(lec.notes_path))
        self.notes_stack.setCurrentIndex(2)
        self.editor.setFocus()

    def save_edit(self):
        lec = self.current
        if not lec:
            return
        lec.notes_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        lec.meta.edited = True
        lec.save_meta()
        try:
            export_html(lec)
        except Exception:
            pass
        self._load(lec, force=True)
        self._phone(lec)

    def cancel_edit(self):
        self.notes_stack.setCurrentIndex(0 if self.current and self.current.notes_path.exists() else 1)

    def _job_is_for(self, lec: Lecture | None) -> bool:
        return bool(lec and self.runner.busy and self.runner.lecture
                    and str(self.runner.lecture.folder) == str(lec.folder))

    # ------------------------------------------------------------------ zadania
    def _run(self, name: str, fn, lecture: Lecture) -> bool:
        if not self.runner.run(name, fn, lecture):
            QMessageBox.information(self, "Trwa inne zadanie", f"Trwa: {self.runner.name}. Poczekaj, aż się skończy.")
            return False
        return True

    def generate_notes(self, lecture: Lecture | None = None, use_cache: bool = False):
        lec = lecture if isinstance(lecture, Lecture) else self.current
        if not lec:
            return
        if lec.meta.edited and lec.notes_path.exists() and not isinstance(lecture, Lecture):
            if QMessageBox.question(self, "Generuj ponownie",
                                    "Notatki były ręcznie poprawiane. Nowe notatki zastąpią Twoje zmiany "
                                    "(kopia zostanie zapisana jako notes_poprawione.md). Kontynuować?") \
                    != QMessageBox.StandardButton.Yes:
                return
            try:
                shutil.copy(lec.notes_path, lec.folder / "notes_poprawione.md")
            except OSError:
                pass
        if not lec.load_segments() and not lec.load_slides().get("slides"):
            QMessageBox.warning(self, "Notatki", "Ten wykład nie ma jeszcze transkrypcji. "
                                                 "Użyj „Więcej → Transkrybuj ponownie z nagrania”.")
            return
        s = self.settings
        self.ai_log.clear()
        self._run("Generowanie notatek",
                  lambda prog, cancel, tok: jobs.generate_notes(lec, s, prog, cancel, tok, use_cache=use_cache), lec)

    def retranscribe(self, lecture: Lecture | None = None, then_notes: bool = False):
        lec = lecture if isinstance(lecture, Lecture) else self.current
        if not lec:
            return
        if not isinstance(lecture, Lecture) and lec.load_segments():
            if QMessageBox.question(self, "Transkrypcja", "Zastąpić obecną transkrypcję nową, zrobioną z pliku nagrania?") \
                    != QMessageBox.StandardButton.Yes:
                return
        s = self.settings

        def fn(prog, cancel, tok):
            jobs.transcribe_lecture(lec, s, prog, cancel)
            if then_notes and not cancel.is_set():
                jobs.generate_notes(lec, s, prog, cancel, tok)
        self._run("Transkrypcja", fn, lec)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz nagranie wykładu", str(Path.home()),
            "Audio/Wideo (*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mkv *.webm *.mov *.avi);;Wszystkie (*.*)")
        if not path:
            return
        title, ok = QInputDialog.getText(self, "Importuj nagranie", "Tytuł wykładu:", text=Path(path).stem)
        if not ok:
            return
        subject, ok = QInputDialog.getText(self, "Importuj nagranie", "Przedmiot:",
                                           text=self.subject_filter or self.settings.last_subject)
        if not ok:
            return
        lec = Lecture.create(self.settings.library_path(), title, subject)
        s = self.settings

        def fn(prog, cancel, tok):
            jobs.import_file(path, lec, s, prog, cancel)
            if s.auto_generate_notes and not cancel.is_set():
                jobs.generate_notes(lec, s, prog, cancel, tok)
        if self._run("Import nagrania", fn, lec):
            self.library_changed.emit()
            self.select(lec)

    def _job_started(self, name, lecture):
        self._job_frac = -1.0
        self.job_label.setText(name + "…")
        self.job_bar.setRange(0, 0)
        self.refresh()

    def _job_progress(self, msg: str, frac: float):
        self._job_frac = frac
        lec = self.runner.lecture
        if lec is not None:          # procent i pasek przy wykładzie na liście
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == str(lec.folder):
                    d = dict(it.data(LectureDelegate.ROLE) or {})
                    d["pill"] = (f"AI {int(frac * 100)}%" if frac >= 0 else "AI pracuje", "blue")
                    d["progress"] = frac
                    it.setData(LectureDelegate.ROLE, d)
                    break
        self.job_label.setText(msg)
        if frac < 0:
            self.job_bar.setRange(0, 0)
        else:
            self.job_bar.setRange(0, 1000)
            self.job_bar.setValue(int(frac * 1000))

    def _job_token(self, tok: str):
        if not self.ai_log.isVisible():
            self._token_buf = getattr(self, "_token_buf", "") + tok
            return
        buf = getattr(self, "_token_buf", "")
        self._token_buf = ""
        c = self.ai_log.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        c.insertText(buf + tok)
        self.ai_log.setTextCursor(c)
        self.ai_log.ensureCursorVisible()

    def _toggle_ai(self):
        vis = not self.ai_log.isVisible()
        self.ai_log.setVisible(vis)
        if vis and getattr(self, "_token_buf", ""):
            self._job_token("")
        self.btn_ai.setText("Ukryj podgląd" if vis else "Pokaż, co pisze AI")

    def _phone(self, lec):
        """Notatka na telefon (PDF do folderu Dysku Google / iCloud / OneDrive), jeśli włączone."""
        from .. import phone
        if lec is not None and phone.enabled(self.settings) and lec.notes_path.exists():
            QTimer.singleShot(0, lambda: phone.export_lecture(Lecture(lec.folder), self.settings))

    def _job_finished(self, ok: bool, msg: str, lecture):
        self._token_buf = ""
        if ok and lecture is not None:
            self._phone(lecture)
        self.refresh()
        self.library_changed.emit()
        if ok and self.current and lecture and str(self.current.folder) == str(lecture.folder):
            self.seg.set_current(0, emit=True)
        if not ok and "anulowano" not in msg:
            QMessageBox.warning(self, "Nie udało się", msg)

    # ------------------------------------------------------------------ akcje
    def open_folder(self):
        if self.current:
            if sys.platform == "win32":
                os.startfile(str(self.current.folder))  # noqa: S606
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current.folder)))

    def open_audio(self):
        if self.current and self.current.audio_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current.audio_path)))

    def export_html(self):
        if not self.current or not self.current.notes_path.exists():
            return QMessageBox.information(self, "Eksport", "Najpierw wygeneruj notatki.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_html(self.current))))

    def export_pdf(self):
        if not self.current or not self.current.notes_path.exists():
            return QMessageBox.information(self, "Eksport", "Najpierw wygeneruj notatki.")
        default = str(Path.home() / "Documents" / f"{self.current.folder.name}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz PDF", default, "PDF (*.pdf)")
        if path:
            export_pdf(self.current, Path(path))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def export_anki(self):
        if not self.current or not card_stats(self.current)[0]:
            return QMessageBox.information(self, "Eksport", "Ten wykład nie ma fiszek.")
        default = str(Path.home() / "Documents" / f"Fiszki - {self.current.folder.name}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Fiszki do Anki", default, "Tekst (*.txt)")
        if path:
            export_anki(self.current, Path(path))
            QMessageBox.information(self, "Anki", "Zapisano. W Anki wybierz Plik → Importuj i wskaż ten plik.")

    def copy_md(self):
        if self.current:
            QApplication.clipboard().setText(self.current.read_text(self.current.notes_path))

    def rename(self):
        if not self.current:
            return
        m = self.current.meta
        title, ok = QInputDialog.getText(self, "Tytuł", "Tytuł wykładu:", text=m.title)
        if not ok:
            return
        subject, ok = QInputDialog.getText(self, "Przedmiot", "Przedmiot:", text=m.subject)
        if not ok:
            return
        m.title, m.subject = title.strip() or m.title, subject.strip()
        self.current.save_meta()
        self._phone(self.current)
        self.refresh()
        self.library_changed.emit()

    def delete(self):
        if not self.current:
            return
        if self._job_is_for(self.current):
            return QMessageBox.information(self, "Usuń", "Trwa zadanie dla tego wykładu.")
        box = QMessageBox(self)
        box.setWindowTitle("Usuń wykład")
        box.setText(f"Usunąć „{self.current.meta.title}”?")
        box.setInformativeText("Nagranie, slajdy, notatki i fiszki zostaną trwale usunięte.")
        delete_btn = box.addButton("Usuń", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is delete_btn:
            from .. import phone
            phone.remove_lecture(self.current)
            shutil.rmtree(self.current.folder, ignore_errors=True)
            self.current = None
            self.refresh()
            self.library_changed.emit()
