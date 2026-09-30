"""Czytnik notatek: QTextBrowser z obrazami z pamięci, odnośnikami wewnętrznymi i odsłuchem fragmentów.

Szerokość czytania: na szerokich ekranach tekst trzyma wygodną szerokość kolumny (marginesy rosną),
na wąskich – obrazy slajdów zmniejszają się do szerokości okna."""
from __future__ import annotations

from PySide6.QtCore import QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QTextCursor, QTextDocument
from PySide6.QtWidgets import QTextBrowser


class Reader(QTextBrowser):
    """QTextBrowser z obrazami podanymi z pamięci (bez wczytywania z dysku w wątku interfejsu).

    Odnośniki: #sec-3 → przewinięcie, play:N → sygnał play_requested(lista fragmentów),
    seek:SEKUNDY → sygnał seek_requested (np. klik w czas w transkrypcji)."""
    internal_link = Signal(str)
    play_requested = Signal(list)
    seek_requested = Signal(float)

    def __init__(self, max_width: int = 780, pad: int = 30):
        super().__init__()
        self.setObjectName("reader")
        self.images: dict[str, QImage] = {}
        self.plays: dict = {}
        self.max_width = max_width
        self.pad = pad
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._clicked)
        self._fit = QTimer(self)
        self._fit.setSingleShot(True)
        self._fit.setInterval(60)
        self._fit.timeout.connect(self._fit_images)
        self._last_avail = -1

    # ------------------------------------------------------------------ szerokość czytania
    def setHtml(self, text: str):
        super().setHtml(text)
        self._last_avail = -1
        self._apply_width()

    def clear(self):
        super().clear()
        self._apply_width()

    def append(self, text: str):
        super().append(text)
        fmt = self.document().rootFrame().frameFormat()
        if fmt.leftMargin() == 0:
            self._apply_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_width()

    def _apply_width(self):
        vw = self.viewport().width()
        side = max(self.pad if vw > 520 else 14, (vw - self.max_width) // 2)
        doc = self.document()
        root = doc.rootFrame()
        fmt = root.frameFormat()
        if fmt.leftMargin() != side or fmt.rightMargin() != side:
            fmt.setLeftMargin(side)
            fmt.setRightMargin(side)
            fmt.setTopMargin(22 if vw > 520 else 12)
            fmt.setBottomMargin(28)
            root.setFrameFormat(fmt)
        avail = vw - 2 * side - 8
        if avail != self._last_avail:
            self._last_avail = avail
            self._fit.start()

    def _fit_images(self):
        """Obrazy slajdów (img:…) nie szersze niż kolumna tekstu."""
        avail = self._last_avail
        if avail <= 0:
            return
        doc = self.document()
        block = doc.begin()
        cursor = None
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    if cf.isImageFormat():
                        imf = cf.toImageFormat()
                        name = imf.name()
                        if name.startswith("img:"):
                            img = self.images.get(name)
                            natural = int(imf.property(0x100001) or 0) or int(imf.width()) or 640
                            if not imf.property(0x100001):
                                imf.setProperty(0x100001, natural)
                            want = min(natural, avail)
                            if int(imf.width()) != want:
                                imf.setWidth(want)
                                if img is not None and not img.isNull() and img.width():
                                    dpr = img.devicePixelRatio() or 1.0
                                    imf.setHeight(want * (img.height() / dpr) / (img.width() / dpr))
                                if cursor is None:
                                    cursor = QTextCursor(doc)
                                cursor.setPosition(frag.position())
                                cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                                cursor.setCharFormat(imf)
                it += 1
            block = block.next()

    # ------------------------------------------------------------------
    def loadResource(self, rtype, url):
        if rtype == QTextDocument.ResourceType.ImageResource.value or rtype == QTextDocument.ResourceType.ImageResource:
            key = url.toString()
            img = self.images.get(key)
            if img is not None:
                return img
            if key == "icon:speaker":
                from .theme import T, svg_icon
                dpr = self.devicePixelRatioF() or 1.0
                img = svg_icon("speaker", T().accent, 16).pixmap(QSize(16, 16), dpr).toImage()
                self.images[key] = img
                return img
        return super().loadResource(rtype, url)

    def _clicked(self, url: QUrl):
        scheme = url.scheme()
        if scheme == "play":
            try:
                frags = self.plays.get(int(url.path()), [])
            except ValueError:
                frags = []
            if frags:
                self.play_requested.emit(frags)
        elif scheme == "seek":
            try:
                self.seek_requested.emit(float(url.path()))
            except ValueError:
                pass
        elif scheme in ("", "file") and url.fragment() and not url.path():
            self.scrollToAnchor(url.fragment())
            self.internal_link.emit(url.fragment())
        elif scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
        elif url.fragment():
            self.scrollToAnchor(url.fragment())

