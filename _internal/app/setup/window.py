"""Ekran przygotowania aplikacji: otwarty notes na spirali.

Lewa strona – lista kroków (odhaczane na bieżąco), prawa – duży procent i opis tego, co się teraz dzieje.
Co kilka sekund przewraca się kartka. Na koniec notes się zamyka i otwiera się okno aplikacji."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ..ui.theme import DISPLAY_FAMILY, T, UI_FAMILY, icon_pixmap, logo_pixmap, mix, qcolor

FLIP_EVERY = 4.2      # s między przewróceniami kartki
FLIP_TIME = 1.15
CLOSE_TIME = 1.25


def _ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class NotebookView(QWidget):
    """Rysuje notes (bez widżetów w środku – tylko QPainter, płynnie w 60 kl./s)."""
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.percent = 0.0
        self.shown_percent = 0.0
        self.detail = ""
        self.steps: list[list] = []          # [tytuł, stan]
        self.error = ""
        self.phase = "working"               # working / closing / closed
        self.t0 = time.monotonic()
        self.close_t0 = 0.0
        self.setMinimumSize(420, 260)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ------------------------------------------------------------------
    def start_closing(self):
        if self.phase == "working":
            self.phase = "closing"
            self.close_t0 = time.monotonic()

    def _tick(self):
        self.shown_percent += (self.percent - self.shown_percent) * 0.12
        if self.phase == "closing" and time.monotonic() - self.close_t0 > CLOSE_TIME:
            self.phase = "closed"
            QTimer.singleShot(1100, self.closed.emit)       # przesunięcie na środek + chwila z okładką
        self.update()

    # ------------------------------------------------------------------ geometria
    def _book(self) -> QRectF:
        W, H = self.width(), self.height()
        bw = min(W * 0.94, H * 1.62)
        bh = bw / 1.62
        return QRectF((W - bw) / 2, (H - bh) / 2, bw, bh)

    # ------------------------------------------------------------------ rysowanie
    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        book = self._book()
        cover = QColor("#2F6B55" if not t.dark else "#357A60")
        paper = QColor(t.surface if t.dark else "#FFFEF8")
        spine = book.center().x()
        m = book.width() * 0.018
        left = QRectF(book.left() + m, book.top() + m, spine - book.left() - m - 4, book.height() - 2 * m)
        right = QRectF(spine + 4, book.top() + m, book.right() - m - spine - 4, book.height() - 2 * m)

        if self.phase == "closed":
            self._closed(p, book, cover)
            p.end()
            return

        # cień i okładka
        close_f = _ease((time.monotonic() - self.close_t0) / CLOSE_TIME) if self.phase == "closing" else 0.0
        self._shadow(p, book if close_f < 0.5 else QRectF(book.left(), book.top(), spine - book.left() + 6,
                                                         book.height()), 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cover)
        if close_f < 0.5:
            p.drawRoundedRect(book, 14, 14)
        else:          # prawa połowa okładki już przerzucona
            p.drawRoundedRect(QRectF(book.left(), book.top(), spine - book.left() + 6, book.height()), 14, 14)
        # kartki pod spodem (grubość bloku)
        for k in (3, 2, 1):
            c = QColor(paper).darker(100 + k * 5)
            p.setBrush(c)
            p.drawRoundedRect(left.adjusted(-k, k * 1.2, 0, k * 1.2), 6, 6)
            if close_f < 0.5:
                p.drawRoundedRect(right.adjusted(0, k * 1.2, k, k * 1.2), 6, 6)
        self._page(p, left, paper, t, side="left")
        if close_f < 0.5:
            self._page(p, right, paper, t, side="right")
            self._right_content(p, right, t)
        self._left_content(p, left, t)

        # przewracana kartka / zamykanie
        if self.phase == "closing":
            self._flip(p, spine, right, close_f, paper, cover, t, closing=True)
        else:
            cyc = (time.monotonic() - self.t0) % FLIP_EVERY
            if cyc < FLIP_TIME and not self.error and self.shown_percent < 0.995:
                self._flip(p, spine, right, _ease(cyc / FLIP_TIME), paper, cover, t)
        self._rings(p, spine, book, m)
        p.end()

    def _shadow(self, p, r: QRectF, rad: float):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i, (g, a) in enumerate(((2, 26), (6, 14), (12, 7), (20, 3))):
            p.setBrush(QColor(0, 0, 0, a * (2 if T().dark else 1)))
            p.drawRoundedRect(r.adjusted(-g, -g + g * 0.6, g, g + g * 0.6), rad + g, rad + g)
        p.restore()

    def _page(self, p, r: QRectF, paper: QColor, t, side: str):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        g = QLinearGradient(r.topLeft(), r.topRight())
        dark = QColor(paper).darker(108)
        if side == "left":
            g.setColorAt(0, paper)
            g.setColorAt(0.9, paper)
            g.setColorAt(1, dark)
        else:
            g.setColorAt(0, dark)
            g.setColorAt(0.1, paper)
            g.setColorAt(1, paper)
        p.setBrush(g)
        p.drawRoundedRect(r, 6, 6)
        # linie jak w zeszycie
        line = qcolor(t.accent if not t.dark else "#5B7FA8", 38 if not t.dark else 55)
        p.setPen(QPen(line, 1))
        step = max(18.0, r.height() / 13)
        y = r.top() + step * 2.1
        while y < r.bottom() - step * 0.5:
            p.drawLine(QPointF(r.left() + 10, y), QPointF(r.right() - 10, y))
            y += step
        if side == "left":
            p.setPen(QPen(qcolor(t.red, 90), 1.2))
            x = r.left() + r.width() * 0.13
            p.drawLine(QPointF(x, r.top() + 6), QPointF(x, r.bottom() - 6))
        p.restore()

    def _rings(self, p, spine: float, book: QRectF, m: float):
        p.save()
        n = 11
        top, bot = book.top() + m + 18, book.bottom() - m - 18
        for i in range(n):
            y = top + (bot - top) * i / (n - 1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawEllipse(QPointF(spine - 11, y + 1), 3.2, 3.2)
            p.drawEllipse(QPointF(spine + 11, y + 1), 3.2, 3.2)
            pen = QPen(QColor("#8C8F94"), 3.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(spine - 11, y), QPointF(spine + 11, y))
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.2))
            p.drawLine(QPointF(spine - 8, y - 1), QPointF(spine + 8, y - 1))
        p.restore()

    def _left_content(self, p, r: QRectF, t):
        p.save()
        step = max(18.0, r.height() / 13)
        x0 = r.left() + r.width() * 0.13 + 12
        f = QFont(DISPLAY_FAMILY)
        f.setPointSizeF(max(11.0, step * 0.62))
        f.setItalic(True)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.accent))
        p.drawText(QRectF(x0, r.top() + step * 0.45, r.right() - x0 - 8, step * 1.5),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Przygotowanie")
        fi = QFont(UI_FAMILY)
        fi.setPointSizeF(max(8.5, step * 0.42))
        now = time.monotonic()
        y = r.top() + step * 2.1
        for title, st in self.steps:
            row = QRectF(x0, y + step * 0.25, r.right() - x0 - 10, step * 0.95)
            cy = row.center().y() + step * 0.12
            cx = x0 + step * 0.32
            rad = step * 0.26
            p.setPen(Qt.PenStyle.NoPen)
            fb = QFont(fi)
            if st == "done" or st == "skipped":
                p.setBrush(qcolor(t.accent))
                p.drawEllipse(QPointF(cx, cy), rad, rad)
                pm = icon_pixmap("check", t.on_accent, int(rad * 1.5), self.devicePixelRatioF())
                p.drawPixmap(int(cx - rad * 0.75), int(cy - rad * 0.75), pm)
                p.setPen(qcolor(t.text2))
            elif st == "warn":
                p.setBrush(qcolor(t.orange))
                p.drawEllipse(QPointF(cx, cy), rad, rad)
                p.setPen(qcolor("#FFFFFF"))
                p.setFont(fb)
                p.drawText(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), Qt.AlignmentFlag.AlignCenter, "!")
                p.setPen(qcolor(t.text2))
            elif st in ("active", "error"):
                pulse = 0.5 + 0.5 * math.sin(now * 5)
                c = qcolor(t.red if st == "error" else t.accent)
                c.setAlpha(int(70 + 80 * pulse))
                p.setBrush(c)
                p.drawEllipse(QPointF(cx, cy), rad * (1.0 + 0.25 * pulse), rad * (1.0 + 0.25 * pulse))
                p.setBrush(qcolor(t.red if st == "error" else t.accent))
                p.drawEllipse(QPointF(cx, cy), rad * 0.5, rad * 0.5)
                fb.setWeight(QFont.Weight.DemiBold)
                p.setPen(qcolor(t.text))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(qcolor(t.text3), 1.4))
                p.drawEllipse(QPointF(cx, cy), rad * 0.8, rad * 0.8)
                p.setPen(qcolor(t.text3))
            p.setFont(fb)
            p.drawText(QRectF(cx + rad + 8, row.top(), row.right() - cx - rad - 8, row.height() + step * 0.24),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight,
                                                  int(row.right() - cx - rad - 8)))
            y += step
        p.restore()

    def _right_content(self, p, r: QRectF, t):
        p.save()
        inner = r.adjusted(r.width() * 0.08, 0, -r.width() * 0.08, 0)
        if self.error:
            f = QFont(DISPLAY_FAMILY)
            f.setPointSizeF(max(14.0, r.height() * 0.07))
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(qcolor(t.red))
            p.drawText(QRectF(inner.left(), r.top() + r.height() * 0.1, inner.width(), r.height() * 0.16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Coś poszło nie tak")
            fi = QFont(UI_FAMILY)
            fi.setPointSizeF(max(8.5, r.height() * 0.031))
            p.setFont(fi)
            p.setPen(qcolor(t.text))
            p.drawText(QRectF(inner.left(), r.top() + r.height() * 0.28, inner.width(), r.height() * 0.5),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                       self.error)
            p.restore()
            return
        pct = int(round(self.shown_percent * 100))
        f = QFont(DISPLAY_FAMILY)
        f.setPointSizeF(max(28.0, r.height() * 0.2))
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(t.text))
        big = QRectF(inner.left(), r.top() + r.height() * 0.16, inner.width(), r.height() * 0.36)
        p.drawText(big, Qt.AlignmentFlag.AlignCenter, f"{pct}%")
        # podkreślenie jak zakreślaczem pod procentem
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(f"{pct}%")
        hl = qcolor(t.highlight, 120 if not t.dark else 70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hl)
        p.drawRoundedRect(QRectF(big.center().x() - w / 2 - 6, big.bottom() - r.height() * 0.07, w + 12,
                                 r.height() * 0.05), 4, 4)
        fi = QFont(UI_FAMILY)
        fi.setPointSizeF(max(8.5, r.height() * 0.034))
        p.setFont(fi)
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(inner.left(), big.bottom() + r.height() * 0.05, inner.width(), r.height() * 0.3),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.detail)
        p.restore()

    def _flip(self, p, spine: float, right: QRectF, f: float, paper: QColor, cover: QColor, t, closing=False):
        """Kartka (albo – przy zamykaniu – prawa połowa z okładką) obracana wokół grzbietu."""
        a = math.pi * f
        c = math.cos(a)
        pw = right.width() + (right.left() - spine) + (8 if closing else 0)
        top, bot = right.top() - (8 if closing else 0), right.bottom() + (8 if closing else 0)
        xe = spine + pw * c
        lift = math.sin(a) * pw * 0.07
        # cień rzucany na stronę pod spodem
        p.save()
        if c > 0:
            g = QLinearGradient(QPointF(xe, 0), QPointF(xe + 40, 0))
            g.setColorAt(0, QColor(0, 0, 0, int(50 * math.sin(a))))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRect(QRectF(xe, top, 40, bot - top))
        path = QPainterPath()
        path.moveTo(spine, top)
        path.quadTo(QPointF((spine + xe) / 2, top - lift * 0.9), QPointF(xe, top - lift))
        path.lineTo(xe, bot + lift)
        path.quadTo(QPointF((spine + xe) / 2, bot + lift * 0.9), QPointF(spine, bot))
        path.closeSubpath()
        front = c > 0
        if closing and not front:
            base = cover
        elif closing:
            base = paper
        else:
            base = paper
        g = QLinearGradient(QPointF(spine, 0), QPointF(xe, 0))
        shade = 1.0 - 0.18 * math.sin(a)
        c1 = QColor(base).darker(int(100 / max(0.6, shade)) + 6)
        c2 = QColor(base).darker(int(100 / max(0.6, shade)))
        g.setColorAt(0, c1)
        g.setColorAt(0.25, c2)
        g.setColorAt(1, QColor(base).lighter(103))
        p.setPen(QPen(QColor(0, 0, 0, 25), 1))
        p.setBrush(g)
        p.drawPath(path)
        if not (closing and not front):     # linie na kartce
            p.setClipPath(path)
            line = qcolor(t.accent if not t.dark else "#5B7FA8", 30)
            p.setPen(QPen(line, 1))
            step = max(18.0, right.height() / 13)
            y = right.top() + step * 2.1
            x0, x1 = sorted((spine, xe))
            while y < right.bottom() - step * 0.5:
                p.drawLine(QPointF(x0 + 6, y), QPointF(x1 - 6, y))
                y += step
        p.restore()

    def _closed(self, p, book: QRectF, cover: QColor):
        """Zamknięty notes na środku z tytułem na okładce."""
        k = min(1.0, (time.monotonic() - self.close_t0 - CLOSE_TIME) / 0.4)
        k = _ease(k)
        half = QRectF(book.left(), book.top(), book.width() / 2 + 6, book.height())
        dx = (book.center().x() - half.center().x()) * k
        r = half.translated(dx, 0)
        self._shadow(p, r, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cover)
        p.drawRoundedRect(r, 14, 14)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRect(QRectF(r.right() - 16, r.top() + 6, 3, r.height() - 12))
        pm = logo_pixmap(int(r.height() * 0.22), self.devicePixelRatioF())
        s = int(r.height() * 0.22)
        p.drawPixmap(int(r.center().x() - s / 2), int(r.top() + r.height() * 0.26), pm)
        f = QFont(DISPLAY_FAMILY)
        f.setPointSizeF(max(16.0, r.height() * 0.085))
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#F6F3EC"))
        p.drawText(QRectF(r.left(), r.top() + r.height() * 0.52, r.width(), r.height() * 0.16),
                   Qt.AlignmentFlag.AlignCenter, "Wykłady")


class SetupWindow(QWidget):
    """Okno bez ramki (ok. ¼ ekranu): nagłówek, notes, pasek postępu."""
    finished = Signal()

    def __init__(self, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Wykłady – przygotowanie")
        self.settings = settings
        from .installer import Installer
        self.inst = Installer(settings)
        first = not (self.inst.marker.get("complete"))
        self._drag = None

        self.logo = QLabel()
        self.logo.setPixmap(logo_pixmap(30, self.devicePixelRatioF() or 2.0))
        title = QLabel("Wykłady")
        title.setObjectName("title3")
        f = QFont(DISPLAY_FAMILY)
        f.setPointSizeF(17)
        f.setWeight(QFont.Weight.DemiBold)
        title.setFont(f)
        self.sub = QLabel("Przygotowuję wszystko do pierwszego wykładu" if first else
                          "Doinstalowuję nowości po aktualizacji")
        self.sub.setObjectName("secondary")
        b_min = QToolButton()
        b_min.setObjectName("icon")
        b_min.setText("–")
        b_min.setToolTip("Zminimalizuj")
        b_min.clicked.connect(self.showMinimized)
        b_close = QToolButton()
        b_close.setObjectName("icon")
        from ..ui.theme import svg_icon
        b_close.setIcon(svg_icon("xmark", T().text2, 16))
        b_close.setToolTip("Przerwij")
        b_close.clicked.connect(self._ask_close)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(self.logo)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(title)
        tv.addWidget(self.sub)
        head.addLayout(tv, 1)
        head.addWidget(b_min, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(b_close, 0, Qt.AlignmentFlag.AlignTop)

        self.book = NotebookView()
        self.book.steps = [[s.title, "pending"] for s in self.inst.steps]
        self.book.closed.connect(self._closed)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.hint = QLabel("Przy pierwszym uruchomieniu pobiera się ok. 20 GB (biblioteki i lokalne modele AI) – "
                           "to może potrwać od kilkunastu minut do godziny. Możesz w tym czasie korzystać z komputera."
                           if first else "To zajmie chwilę.")
        self.hint.setObjectName("footnote")
        self.hint.setWordWrap(True)
        self.btn_retry = QPushButton("Spróbuj ponownie")
        self.btn_retry.setObjectName("primary")
        self.btn_retry.clicked.connect(self._retry)
        self.btn_quit = QPushButton("Zamknij")
        self.btn_quit.clicked.connect(QApplication.quit)
        self.err_row = QWidget()
        er = QHBoxLayout(self.err_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.addStretch()
        er.addWidget(self.btn_quit)
        er.addWidget(self.btn_retry)
        self.err_row.hide()

        v = QVBoxLayout(self)
        v.setContentsMargins(40, 34, 40, 34)
        v.setSpacing(14)
        v.addLayout(head)
        v.addWidget(self.book, 1)
        v.addWidget(self.bar)
        v.addWidget(self.hint)
        v.addWidget(self.err_row)

        self.inst.step_changed.connect(self._step)
        self.inst.progress.connect(self._progress)
        self.inst.failed.connect(self._failed)
        self.inst.completed.connect(self._completed)

        scr = QApplication.primaryScreen().availableGeometry()
        w = int(min(1180, max(700, scr.width() * 0.5)))
        h = int(min(760, max(500, scr.height() * 0.52)))
        self.setGeometry(scr.left() + (scr.width() - w) // 2, scr.top() + (scr.height() - h) // 2, w, h)

    # ------------------------------------------------------------------
    def start(self):
        self.show()
        self.inst.start()

    def _step(self, i: int, st: str):
        if 0 <= i < len(self.book.steps):
            self.book.steps[i][1] = st

    def _progress(self, frac: float, detail: str):
        self.book.percent = frac
        self.book.detail = detail
        self.bar.setValue(int(frac * 1000))

    def _failed(self, msg: str):
        self.book.error = msg
        self.err_row.show()

    def _retry(self):
        self.book.error = ""
        self.err_row.hide()
        from .installer import Installer
        old = self.inst
        self.inst = Installer(self.settings)
        self.inst.step_changed.connect(self._step)
        self.inst.progress.connect(self._progress)
        self.inst.failed.connect(self._failed)
        self.inst.completed.connect(self._completed)
        del old
        self.inst.start()

    def _completed(self):
        self.book.percent = 1.0
        self.book.detail = "Gotowe! Otwieram aplikację…"
        self.bar.setValue(1000)
        QTimer.singleShot(700, self.book.start_closing)

    def _closed(self):
        self.finished.emit()          # okno aplikacji się buduje i pojawia
        from PySide6.QtCore import QPropertyAnimation
        a = QPropertyAnimation(self, b"windowOpacity", self)
        a.setDuration(300)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.finished.connect(self.close)
        a.start()
        self._fade = a

    def _ask_close(self):
        if self.book.phase != "working":
            return
        if QMessageBox.question(self, "Przerwać?", "Przerwać przygotowanie? Dokończy się przy następnym "
                                                   "uruchomieniu aplikacji.") == QMessageBox.StandardButton.Yes:
            self.inst.stop()
            QApplication.quit()

    # ------------------------------------------------------------------ tło okna i przesuwanie
    def paintEvent(self, _e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(14, 12, -14, -16)
        for g, a in ((1, 30), (4, 16), (8, 8), (12, 4)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a * (2 if t.dark else 1)))
            p.drawRoundedRect(r.adjusted(-g, -g + 3, g, g + 3), 22 + g, 22 + g)
        p.setBrush(qcolor(t.window))
        p.setPen(QPen(qcolor(mix(t.window, t.text, 0.12)), 1))
        p.drawRoundedRect(r, 22, 22)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None
