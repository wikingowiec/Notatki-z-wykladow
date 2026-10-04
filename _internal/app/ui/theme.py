"""Motywy „Zeszyt”, „Atrament” i „Akademia” (każdy jasny i ciemny).

Wartości pochodzą z tokens.py. Tu powstaje obiekt Tokens (stare nazwy pól + wszystkie nowe tokeny jako
atrybuty), menedżer motywu, fonty, arkusz stylów Qt, kolory przedmiotów, ikony wektorowe i logo."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import tokens as TK

UI_FAMILY = TK.FONT_UI
DISPLAY_FAMILY = TK.FONT_DISPLAY
FONT = ""
FONT_DISPLAY = ""
FONTS_DIR = Path(__file__).with_name("fonts")
_AVAILABLE: set[str] = set()


def load_fonts() -> None:
    """Rejestruje dołączone fonty wszystkich motywów (przed utworzeniem okien)."""
    for f in sorted(FONTS_DIR.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            for fam in QFontDatabase.applicationFontFamilies(fid):
                _AVAILABLE.add(fam)
                _AVAILABLE.add(fam.split(" ")[0] if fam.endswith(("Medium", "SemiBold")) else fam)
    _AVAILABLE.update(QFontDatabase.families())
    _set_families(T())


def _family(name: str, kind: str) -> str:
    if not _AVAILABLE or name in _AVAILABLE:
        return name
    return TK.FALLBACK[kind]


def _set_families(t) -> None:
    global UI_FAMILY, DISPLAY_FAMILY, FONT, FONT_DISPLAY
    UI_FAMILY = _family(t.font_ui, "ui")
    DISPLAY_FAMILY = _family(t.font_display, "display")
    FONT = f"'{UI_FAMILY}', 'Segoe UI Variable Text', 'Segoe UI', 'Helvetica Neue', sans-serif"
    FONT_DISPLAY = f"'{DISPLAY_FAMILY}', 'Georgia', 'Cambria', serif"


def ui_font(pt: float = 10.0, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(UI_FAMILY)
    f.setPointSizeF(pt)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def display_font(pt: float = 20.0, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    f = QFont(DISPLAY_FAMILY)
    f.setPointSizeF(pt)
    f.setWeight(weight)
    return f


def px(name: str) -> float:
    """Rozmiar fontu z TYPE (px) w punktach Qt (96 dpi)."""
    return TK.TYPE[name][1] * 0.75


def mix(a: str, b: str, f: float) -> str:
    """Kolor pomiędzy a i b (f=0 → a, f=1 → b)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * f), round(ca.green() + (cb.green() - ca.green()) * f),
                  round(ca.blue() + (cb.blue() - ca.blue()) * f)).name()


class Tokens:
    """Bieżący motyw. Stare nazwy (window, text2, separator…) + każdy token z tokens.py jako atrybut
    (t.defBg, t.mark, t.streak…) + t.radius, t.font_ui, t.font_display, t.shadows."""

    def __init__(self, name: str, dark: bool):
        d = TK.variant(TK.THEMES.get(name, "A"), dark)
        self.d = d
        self.name, self.dark = name, dark
        self.radius = d["radius"]
        self.font_ui, self.font_display = d["fontUi"], d["fontDisplay"]
        self.shadows = d.get("shadows", True)
        self.window, self.sidebar, self.surface, self.surface2 = d["bg"], d["side"], d["surface"], d["surface2"]
        self.hover = mix(d["bg"], d["ink"], 0.08 if dark else 0.05)
        self.selected = d["sideActive"]
        self.text, self.text2, self.text3 = d["ink"], d["ink2"], d["ink3"]
        self.separator, self.line2 = d["line"], d["line2"]
        self.accent, self.accent_hover, self.accent_pressed = d["accent"], d["accentHover"], d["accentPressed"]
        self.accent_soft, self.accent_text, self.on_accent = d["accentSoft"], d["accentText"], d["accentInk"]
        self.red, self.red_soft, self.red_text, self.on_red = d["rec"], d["recSoft"], d["recText"], d["recInk"]
        self.green, self.green_soft = d["ok"], d["okSoft"]
        self.orange, self.orange_soft = d["streak"], d["wazBg"]
        self.highlight, self.highlight_soft = d["markLine"], d["mark"]
        self.shadow = d["shadow"]
        self.track = mix(d["surface2"], d["line"], 0.75)
        self.subjects = TK.SUBJECTS_DARK if dark else TK.SUBJECTS_LIGHT

    def __getattr__(self, key):          # nowe tokeny: t.defBg, t.mark, t.streak …
        d = self.__dict__.get("d")
        if d is not None and key in d:
            return d[key]
        raise AttributeError(key)

    def r(self, name: str) -> int:
        return self.radius[name]


MODE_COLOR = {"av": 0, "audio": 2, "slides": 1, "files": 4}


def subject_color(name: str | None, dark: bool | None = None) -> str:
    t = T()
    pal = (TK.SUBJECTS_DARK if dark else TK.SUBJECTS_LIGHT) if dark is not None else t.subjects
    if not name:
        return t.text3
    i = int(hashlib.md5(name.strip().lower().encode("utf-8")).hexdigest(), 16) % len(pal)
    return pal[i]


def palette_color(i: int) -> str:
    pal = T().subjects
    return pal[i % len(pal)]


def soft(color: str) -> str:
    """Delikatne tło w danym kolorze."""
    t = T()
    return mix(t.surface, color, 0.22 if t.dark else 0.13)


class Theme(QObject):
    """Menedżer motywu (jeden na aplikację): nazwa motywu + tryb jasny/ciemny/systemowy.
    apply() przestawia paletę, arkusz stylów, fonty i emituje changed (alias themeChanged)."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "system"          # system / light / dark
        self.name = "zeszyt"
        self.t: Tokens = Tokens(self.name, False)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._maybe_update())

    @property
    def themeChanged(self):
        return self.changed

    def system_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        try:
            return hints.colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return False

    def set_mode(self, mode: str):
        self.mode = mode
        self._maybe_update(force=True)

    def set_name(self, name: str):
        self.name = name if name in TK.THEMES else "zeszyt"
        self._maybe_update(force=True)

    def apply(self, name: str | None = None, mode: str | None = None):
        if name is not None:
            self.name = name if name in TK.THEMES else "zeszyt"
        if mode is not None:
            self.mode = mode
        self._maybe_update(force=True)

    def _maybe_update(self, force: bool = False):
        dark = self.system_dark() if self.mode == "system" else self.mode == "dark"
        if not force and dark == self.t.dark and self.name == self.t.name:
            return
        new = Tokens(self.name, dark)
        self.t = new
        _set_families(new)
        _icon_cache.clear()
        _pixmap_cache.clear()
        _logo_cache.clear()
        app = QGuiApplication.instance()
        if app is not None:
            app.setPalette(build_palette(new))
            if hasattr(app, "setStyleSheet"):
                f = app.font()
                f.setFamily(UI_FAMILY)
                app.setFont(f)
                app.setStyleSheet(build_qss(new))
            for w in app.topLevelWidgets() if hasattr(app, "topLevelWidgets") else []:
                apply_titlebar(w)
        self.changed.emit()


THEME: Theme | None = None


def theme() -> Theme:
    global THEME
    if THEME is None:
        THEME = Theme()
    return THEME


def T() -> Tokens:
    return theme().t


def build_palette(t: Tokens) -> QPalette:
    p = QPalette()
    C = QPalette.ColorRole
    for role, col in ((C.Window, t.window), (C.WindowText, t.text), (C.Base, t.surface), (C.AlternateBase, t.surface2),
                      (C.Text, t.text), (C.Button, t.surface2), (C.ButtonText, t.text), (C.ToolTipBase, t.surface),
                      (C.ToolTipText, t.text), (C.PlaceholderText, t.text3), (C.Highlight, t.accent),
                      (C.HighlightedText, t.on_accent), (C.Link, t.accent), (C.Mid, t.separator),
                      (C.Midlight, t.hover), (C.Light, t.surface), (C.Dark, t.separator), (C.Shadow, t.shadow)):
        p.setColor(role, QColor(col))
    p.setColor(QPalette.ColorGroup.Disabled, C.Text, QColor(t.text3))
    p.setColor(QPalette.ColorGroup.Disabled, C.ButtonText, QColor(t.text3))
    p.setColor(QPalette.ColorGroup.Disabled, C.WindowText, QColor(t.text3))
    return p


def apply_titlebar(w) -> None:
    """Windows 10/11: pasek tytułu w kolorach aplikacji (ciemny/jasny, kolor tła)."""
    if sys.platform != "win32":
        return
    try:
        if not w.isWindow() or not w.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return
        import ctypes
        t = T()
        hwnd = int(w.winId())
        dwm = ctypes.windll.dwmapi

        def setattr_(attr, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_):
            c = QColor(hex_)
            return c.red() | (c.green() << 8) | (c.blue() << 16)
        setattr_(20, 1 if t.dark else 0)            # DWMWA_USE_IMMERSIVE_DARK_MODE
        setattr_(35, colorref(t.sidebar))           # DWMWA_CAPTION_COLOR (Windows 11)
        setattr_(36, colorref(t.text))              # DWMWA_TEXT_COLOR
        setattr_(34, colorref(t.separator))         # DWMWA_BORDER_COLOR
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ikony (własne, linie 1.8 px)
# ---------------------------------------------------------------------------
_ICONS = {
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    "books": '<rect x="3" y="4" width="4.5" height="16" rx="1"/><rect x="9.5" y="4" width="4.5" height="16" rx="1"/><path d="M16 5.6l3.6-1 3 14.4-3.6 1z"/>',
    "tray": '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M5.5 5h13l2.5 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z"/>',
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    "cards": '<rect x="3" y="8" width="13" height="12" rx="2"/><path d="M7 8V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
    "sparkles": '<path d="M11 3l1.9 5 5.1 1.9-5.1 1.9L11 17l-1.9-5.2L4 9.9l5.1-1.9z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "share": '<path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11H5.5A1.5 1.5 0 0 0 4 12.5v7A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-7a1.5 1.5 0 0 0-1.5-1.5H18"/>',
    "more": '<circle cx="6" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18" cy="12" r="1.3" fill="currentColor"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4v4h-4"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "display": '<rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "waveform": '<path d="M3 12h1.5M7 8.5v7M10.5 5v14M14 8v8M17.5 10v4M20.5 12h.5"/>',
    "doc": '<path d="M6.5 2.5h7l5 5v12a2 2 0 0 1-2 2h-10a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2z"/><path d="M13.5 2.5v5h5M8.5 13h7M8.5 17h5"/>',
    "photo": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="M21 16l-5-5-8.5 8"/>',
    "text": '<path d="M4 6h16M4 10h16M4 14h11M4 18h7"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "xmark": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5" fill="currentColor"/>',
    "record": '<circle cx="12" cy="12" r="6" fill="currentColor"/>',
    "open": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "import": '<path d="M12 3v12M8 11l4 4 4-4"/><path d="M5 15v3.5A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V15"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    "shuffle": '<path d="M3 7h3.5c4.5 0 6.5 10 11 10H21M3 17h3.5c1.8 0 3-1.6 4-3.5M14 9c1-1.3 2-2 3.5-2H21M18.5 4.5L21 7l-2.5 2.5M18.5 14.5L21 17l-2.5 2.5"/>',
    "screen-audio": '<rect x="2.5" y="4" width="13" height="10" rx="1.8"/><path d="M6 18h6M9 14v4"/><path d="M18.5 8.5a3.5 3.5 0 0 1 0 5M20.8 6.3a6.6 6.6 0 0 1 0 9.4"/>',
    "photos": '<rect x="6.5" y="3" width="15" height="12" rx="2"/><path d="M3 7.5v10A2.5 2.5 0 0 0 5.5 20h11"/><circle cx="11" cy="7.3" r="1.3"/><path d="M21.5 12l-4-4-6 6"/>',
    "speaker": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" stroke-linejoin="round"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "pause": '<rect x="7" y="5.5" width="3.5" height="13" rx="1" fill="currentColor"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1" fill="currentColor"/>',
    "flag": '<path d="M5.5 21V4.5M5.5 4.5h11l-2.5 4 2.5 4h-11"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "exam": '<path d="M7 3.5h10a1.5 1.5 0 0 1 1.5 1.5v14.5a1.5 1.5 0 0 1-1.5 1.5H7a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 7 3.5z"/><path d="M9 8.5l1.5 1.5L13 7.5M9 14.5h6M9 17.5h4"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M12 17v.3"/>',
    "continue": '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v8M8 12h8"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "chevron-left": '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
    "chevron-down": '<path d="M5.5 9.5L12 16l6.5-6.5"/>',
    "chevron-right": '<path d="M9.5 5.5L16 12l-6.5 6.5"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor"/><circle cx="4.5" cy="12" r="1" fill="currentColor"/><circle cx="4.5" cy="18" r="1" fill="currentColor"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "pencil-note": '<path d="M6 3.5h8.5L19 8v6"/><path d="M14 3.5V8h5"/><path d="M6 3.5A1.5 1.5 0 0 0 4.5 5v14A1.5 1.5 0 0 0 6 20.5h6"/><path d="M14.5 21l.6-2.6 5-5a1.4 1.4 0 0 1 2 2l-5 5z"/>',
    "flame": '<path d="M12 21c-3.9 0-6.5-2.6-6.5-6.2 0-3.4 2.4-5.6 3.9-7.8.4 1.6 1.3 2.7 2.4 3.3.2-2.7 1.4-5.2 3.4-7.3.3 3 2.1 4.8 3.4 6.8.9 1.4 1.4 3 1.4 4.8C20 18.3 16.1 21 12 21z"/><path d="M12 21c-1.8 0-3-1.2-3-2.9 0-1.6 1.2-2.6 2-3.7.4 1 1 1.5 1.6 1.7.3-.9.7-1.6 1.3-2.2.6 1.3 1.1 2.4 1.1 3.6 0 2.1-1.3 3.5-3 3.5z"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 10h.5M9.5 10h.5M13 10h.5M17 10h.5M7 14h10"/>',
    "highlighter": '<path d="M9 14.5l-3.5 3.5h5l1.5-1.5"/><path d="M8.5 11.5l4 4 8-8-4-4z"/><path d="M3 21h18"/>',
}


_icon_cache: dict = {}


def svg_icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    """Ikona z pamięci podręcznej – renderowanie SVG przy każdym malowaniu bardzo spowalnia listy."""
    color = color or T().text2
    key = (name, color, size)
    ic = _icon_cache.get(key)
    if ic is None:
        ic = _icon_cache[key] = _render_icon(name, color, size)
    return ic


_pixmap_cache: dict = {}


def icon_pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    key = (name, color, size, dpr)
    pm = _pixmap_cache.get(key)
    if pm is None:
        pm = _pixmap_cache[key] = svg_icon(name, color, size).pixmap(QSize(size, size), dpr)
    return pm


def _render_icon(name: str, color: str, size: int) -> QIcon:
    body = _ICONS.get(name, _ICONS["info"]).replace("currentColor", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(QSize(size * scale, size * scale))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def qcolor(hex_: str, alpha: int | None = None) -> QColor:
    c = QColor(hex_)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# ---------------------------------------------------------------------------
# Logo: kartka z falą dźwięku i czerwoną kropką nagrywania
# ---------------------------------------------------------------------------
def logo_svg(accent: str | None = None, paper: str | None = None, red: str | None = None) -> str:
    t = T()
    accent = accent or (t.accent if not t.dark else mix(t.accent, t.bg, 0.35))
    paper = paper or t.logoPaper
    red = red or (t.rec if not t.dark else t.recText)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="16" fill="{accent}"/>
<rect x="14.5" y="11.5" width="31" height="41" rx="5" fill="{paper}"/>
<g stroke="{accent}" stroke-width="3.2" stroke-linecap="round" fill="none">
<path d="M21 29v4M25.5 25v12M30 21.5v19M34.5 26.5v9M39 29.5v3"/></g>
<g stroke="{accent}" stroke-opacity="0.35" stroke-width="2.4" stroke-linecap="round">
<path d="M21 45.5h18"/></g>
<circle cx="46" cy="15.5" r="7" fill="{red}" stroke="{accent}" stroke-width="3"/>
</svg>"""


_logo_cache: dict = {}


def logo_pixmap(size: int, dpr: float = 2.0) -> QPixmap:
    t = T()
    key = (size, dpr, t.dark, t.name)
    pm = _logo_cache.get(key)
    if pm is None:
        r = QSvgRenderer(QByteArray(logo_svg().encode()))
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, size * dpr, size * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _logo_cache[key] = pm
    return pm


# ---------------------------------------------------------------------------
# Arkusz stylów
# ---------------------------------------------------------------------------
def _asset(name: str, svg: str) -> str:
    """Mały plik SVG dla arkusza stylów (strzałki list rozwijanych) – ścieżka z ukośnikami /."""
    import tempfile
    d = Path(tempfile.gettempdir()) / "wyklady_ui"
    try:
        d.mkdir(exist_ok=True)
        f = d / name
        if not f.exists() or f.read_text(encoding="utf-8") != svg:
            f.write_text(svg, encoding="utf-8")
        return f.as_posix()
    except OSError:
        return ""


def build_qss(t: Tokens) -> str:
    R = t.radius
    pt = lambda name: f"{px(name):.2f}pt"          # noqa: E731
    focus_ring = t.accent
    col = t.text2.lstrip("#")
    arrow = _asset(f"chevron_{col}.svg",
                   f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12" width="12" height="12">'
                   f'<path d="M3 4.5l3 3 3-3" fill="none" stroke="#{col}" stroke-width="1.6" '
                   f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    arrow_css = f"image: url({arrow}); width: 12px; height: 12px;" if arrow else ""
    c3 = t.text3.lstrip("#")
    lens = _asset(f"search_{c3}.svg",
                  f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 18" width="36" height="18">'
                  f'<g transform="translate(12,0) scale(0.75)" fill="none" stroke="#{c3}" stroke-width="2.2" '
                  f'stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/></g></svg>')
    lens_css = (f"background-image: url({lens}); background-repeat: no-repeat; background-position: left center; "
                f"background-origin: border;") if lens else ""
    return f"""
* {{ font-family: {FONT}; font-size: {pt('body')}; color: {t.text}; outline: none; }}
QMainWindow, QDialog {{ background: {t.window}; }}
QWidget#page, QWidget#content, QScrollArea#page > QWidget > QWidget {{ background: {t.window}; }}
QScrollArea {{ background: transparent; border: none; }}
QLabel, QCheckBox {{ background: transparent; }}

/* --- pasek boczny --- */
QWidget#sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.separator}; }}
QListWidget#sidebarList {{ background: transparent; border: none; padding: 0 10px; }}
QListWidget#sidebarList::item {{ border: none; padding: 0; margin: 0; }}
QLabel#appTitle {{ font-family: {FONT_DISPLAY}; font-size: 15.75pt; font-weight: 600; padding: 0 2px; }}
QPushButton#splitMain {{ background: {t.accent}; color: {t.on_accent}; border: none; text-align: left;
    padding: 0 14px; min-height: 44px; border-radius: 0; border-top-left-radius: {R['md']}px;
    border-bottom-left-radius: {R['md']}px; }}
QPushButton#splitMain:hover, QPushButton#splitMic:hover {{ background: {t.accent_hover}; }}
QPushButton#splitMain:pressed, QPushButton#splitMic:pressed {{ background: {t.accent_pressed}; }}
QPushButton#splitMic {{ background: {t.accent}; border: none; border-left: 1px solid {mix(t.accent, t.on_accent, 0.35)};
    min-height: 44px; min-width: 46px; max-width: 46px; padding: 0; border-radius: 0;
    border-top-right-radius: {R['md']}px; border-bottom-right-radius: {R['md']}px; }}
QPushButton#splitMain[rail="true"], QPushButton#splitMic[rail="true"] {{ border-radius: {R['md']}px; border: none;
    padding: 0; min-width: 44px; max-width: 44px; text-align: center; }}
QPushButton#splitMain[active="true"] {{ background: {t.accent_pressed}; }}
QPushButton#recPill {{ background: {t.red_soft}; color: {t.red_text}; border: none; text-align: left; padding: 0 14px;
    min-height: 44px; border-radius: {R['md']}px; font-weight: 700; }}
QPushButton#recPill:hover {{ background: {mix(t.red_soft, t.red, 0.12)}; }}
QPushButton#recPill[rail="true"] {{ text-align: center; padding: 0; min-width: 44px; max-width: 44px; }}
QPushButton#jump {{ min-height: 34px; padding: 0 8px; font-weight: 600; text-align: left; border-radius: {R['sm']}px; }}
QPushButton#jump[kind="def"] {{ border-left: 3px solid {t.defBar}; }}
QPushButton#jump[kind="wz"] {{ border-left: 3px solid {t.wzBar}; }}
QPushButton#jump[kind="prz"] {{ border-left: 3px solid {t.przBar}; }}
QPushButton#jump[kind="waz"] {{ border-left: 3px solid {t.wazBar}; }}
QFrame#flashcard {{ background: {t.surface}; border: 1px solid {t.separator}; border-radius: {R['xl']}px; }}
QFrame#dash {{ border: none; border-top: 2px dashed {t.line2}; background: transparent; }}
QPushButton#rateNo, QPushButton#rateYes {{ min-height: 68px; border-radius: {R['lg']}px; font-size: 11pt;
    text-align: center; padding: 6px 18px; }}
QPushButton#rateNo {{ background: {t.surface}; border: 1px solid {t.line2}; color: {t.text}; }}
QPushButton#rateNo:hover {{ border-color: {t.red}; background: {t.red_soft}; }}
QPushButton#rateYes {{ background: {t.accent}; border: none; color: {t.on_accent}; }}
QPushButton#rateYes:hover {{ background: {t.accent_hover}; }}
QPushButton#chipBtn {{ min-height: 34px; padding: 0 12px; border-radius: 17px; font-weight: 600;
    color: {t.accent_text}; background: {t.surface}; border: 1px solid {t.separator}; }}
QPushButton#chipBtn:hover {{ border-color: {t.accent}; background: {t.accent_soft}; }}
QPushButton#chipBtn:disabled {{ color: {t.text3}; }}
QPushButton#streak {{ background: transparent; border: none; color: {t.text2}; text-align: left; padding: 0 8px;
    min-height: 34px; font-weight: 600; border-radius: {R['sm']}px; }}
QPushButton#streak[rail="true"] {{ padding: 0; text-align: center; }}
QPushButton#streak:hover {{ background: {t.hover}; color: {t.text}; }}
QWidget#jobCard {{ background: {t.surface}; border: 1px solid {t.separator}; border-radius: {R['md']}px; }}

/* --- typografia --- */
QLabel#largeTitle {{ font-family: {FONT_DISPLAY}; font-size: {pt('display')}; font-weight: 600; }}
QLabel#h1 {{ font-family: {FONT_DISPLAY}; font-size: {pt('h1')}; font-weight: 600; }}
QLabel#title2 {{ font-family: {FONT_DISPLAY}; font-size: {pt('h2')}; font-weight: 600; }}
QLabel#title3 {{ font-family: {FONT_DISPLAY}; font-size: {pt('h3')}; font-weight: 600; }}
QLabel#headline {{ font-weight: 600; }}
QLabel#secondary {{ color: {t.text2}; }}
QLabel#footnote {{ color: {t.text2}; font-size: {pt('small')}; }}
QLabel#caption {{ color: {t.text3}; font-size: {pt('caption')}; }}
QLabel#overline {{ color: {t.accent_text}; font-size: {pt('overline')}; font-weight: 700; }}
QLabel#sectionHeader {{ color: {t.text3}; font-size: {pt('overline')}; font-weight: 700;
    padding: 0 0 0 4px; }}
QLabel#timer {{ font-family: {FONT_DISPLAY}; font-size: {pt('timer')}; font-weight: 500; }}
QLabel#cardQ {{ font-family: {FONT_DISPLAY}; font-size: {pt('question')}; font-weight: 600; }}
QLabel#cardA {{ font-size: 14pt; color: {t.text}; }}
QLabel#cardHint {{ color: {t.text3}; font-size: {pt('caption')}; }}
QLabel#errorText {{ color: {t.red_text}; }}
QLabel#recLabel {{ color: {t.red_text}; font-size: {pt('overline')}; font-weight: 700; }}

/* --- grupy i karty --- */
QFrame#group {{ background: {t.surface}; border-radius: {R['lg']}px; border: 1px solid {t.separator}; }}
QFrame#hairline {{ background: {t.separator}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#card {{ background: {t.surface}; border-radius: {R['xl']}px; border: 1px solid {t.separator}; }}
QFrame#banner {{ background: {t.accent_soft}; border-radius: {R['md']}px; border: none; }}
QFrame#warnBanner {{ background: {t.highlight_soft}; border-radius: {R['md']}px; border: none; }}
QFrame#recBar {{ background: {t.surface}; border-radius: {R['lg']}px; border: 1px solid {t.separator}; }}
QFrame#pane {{ background: {t.surface}; border-radius: {R['lg']}px; border: 1px solid {t.separator}; }}

/* --- pola --- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {t.surface2}; border: 1px solid {t.separator}; border-radius: {R['md']}px;
    padding: 0 12px; min-height: 38px; selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {t.line2}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {focus_ring}; padding: 0 11px; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {t.text3}; background: {t.hover}; }}
QLineEdit#search {{ background-color: {t.surface2}; border: 1px solid {t.separator}; border-radius: {R['md']}px;
    padding: 0 10px 0 34px; {lens_css} }}
QLineEdit#search:focus {{ border: 2px solid {focus_ring}; padding: 0 9px 0 33px; background-color: {t.surface}; }}
QLineEdit#bare, QComboBox#bare {{ background: transparent; border: none; padding: 4px 0; min-height: 0; }}
QLineEdit#askInput {{ border-radius: {R['md']}px; padding: 0 14px; min-height: 42px; font-size: 10.75pt; }}
QLineEdit#askInput:focus {{ padding: 0 13px; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ {arrow_css} margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.separator}; border-radius: {R['md']}px;
    padding: 6px; outline: none; selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QComboBox QAbstractItemView::item {{ min-height: 36px; padding: 0 10px; border-radius: {R['sm']}px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}

/* --- przyciski (min. 44 px) --- */
QPushButton, QToolButton {{ background: {t.surface}; border: 1px solid {t.separator}; border-radius: {R['md']}px;
    padding: 0 16px; min-height: 40px; font-weight: 600; }}
QPushButton:hover, QToolButton:hover {{ border-color: {t.line2}; background: {t.surface}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.hover}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.text3}; }}
QPushButton:focus {{ border: 2px solid {t.accent}; padding: 0 15px; }}
QPushButton#primary {{ background: {t.accent}; border: none; color: {t.on_accent}; padding: 0 18px; }}
QPushButton#primary:hover {{ background: {t.accent_hover}; }}
QPushButton#primary:pressed {{ background: {t.accent_pressed}; }}
QPushButton#primary:disabled {{ background: {t.hover}; color: {t.text3}; }}
QPushButton#big {{ background: {t.accent}; border: none; color: {t.on_accent}; font-size: 11pt;
    padding: 0 26px; min-height: 46px; border-radius: {R['md']}px; }}
QPushButton#big:hover {{ background: {t.accent_hover}; }}
QPushButton#big:pressed {{ background: {t.accent_pressed}; }}
QPushButton#big:disabled {{ background: {t.hover}; color: {t.text3}; }}
QPushButton#mark {{ background: {t.mark}; border: 1px solid {t.markLine}; color: {t.text}; }}
QPushButton#mark:checked {{ background: {t.markLine}; border-color: {t.markLine}; color: {t.text}; }}
QPushButton:checked {{ background: {t.accent_soft}; border-color: {t.accent}; }}
QPushButton#mark:hover {{ border-color: {t.text3}; background: {t.mark}; }}
QPushButton#danger {{ background: {t.red}; border: none; color: {t.on_red}; }}
QPushButton#danger:hover {{ background: {mix(t.red, t.text, 0.12)}; }}
QPushButton#destructive {{ background: {t.red_soft}; border: none; color: {t.red_text}; }}
QPushButton#positive {{ background: {t.green_soft}; border: none; color: {t.green}; }}
QPushButton#plain, QToolButton#plain {{ background: transparent; border: none; color: {t.accent_text}; padding: 0 8px;
    min-height: 32px; }}
QPushButton#plain:hover, QToolButton#plain:hover {{ background: {t.accent_soft}; }}
QPushButton#back {{ background: transparent; border: none; color: {t.accent_text}; padding: 0 8px 0 2px; min-height: 32px; }}
QPushButton#back:hover {{ background: {t.accent_soft}; }}
QToolButton#icon {{ background: transparent; border: none; border-radius: {R['md']}px; padding: 0; min-height: 0; }}
QToolButton#icon:hover {{ background: {t.hover}; }}
QToolButton#icon:checked {{ background: {t.accent_soft}; }}
QToolButton#icon::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0; }}

/* --- listy / tekst --- */
QListWidget, QListView, QTextBrowser, QPlainTextEdit {{ background: {t.surface}; border: 1px solid {t.separator};
    border-radius: {R['lg']}px; padding: 6px; selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QListWidget#lectureList, QListWidget#outline {{ background: transparent; border: none; padding: 0; }}
QListWidget#outline::item {{ border-radius: {R['sm']}px; padding: 5px 8px; color: {t.text2}; }}
QListWidget#outline::item:hover {{ background: {t.hover}; color: {t.text}; }}
QListWidget#outline::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QListWidget#thumbs {{ background: transparent; border: none; padding: 0; }}
QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.text}; border-radius: {R['md']}px; }}
QTextBrowser#reader {{ padding: 0; }}
QPlainTextEdit {{ padding: 10px; }}

QProgressBar {{ background: {t.separator}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 2px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.separator}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t.surface}; border: 1px solid {t.line2}; width: 18px; height: 18px;
    margin: -8px 0; border-radius: 9px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.line2}; border-radius: 3px; min-height: 40px; margin: 0 1px; }}
QScrollBar::handle:vertical:hover {{ background: {t.text3}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.line2}; border-radius: 3px; min-width: 40px; margin: 1px 0; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: none; }}

QMenu {{ background: {t.surface}; border: 1px solid {t.separator}; border-radius: {R['md']}px; padding: 6px; }}
QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: {R['sm']}px; }}
QMenu::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QMenu::item:disabled {{ color: {t.text3}; }}
QMenu::separator {{ height: 1px; background: {t.separator}; margin: 5px 8px; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.separator}; padding: 6px 9px;
    border-radius: {R['sm']}px; }}
QSplitter::handle {{ background: transparent; }}
QFrame#footerBar {{ background: {t.surface}; border: none; border-top: 1px solid {t.separator}; }}
QFrame#vline {{ background: {t.separator}; border: none; }}
QWidget#listPane {{ background: {t.window}; }}
QMessageBox {{ background: {t.window}; }}

/* --- odpowiedzi w egzaminie --- */
QPushButton#option {{ text-align: left; padding: 12px 16px; border-radius: {R['md']}px; background: {t.surface};
    border: 1px solid {t.separator}; font-size: 10.75pt; font-weight: 400; }}
QPushButton#option:hover {{ border-color: {t.accent}; background: {t.accent_soft}; }}
QPushButton#option[state="correct"] {{ background: {t.green_soft}; border: 2px solid {t.green}; }}
QPushButton#option[state="wrong"] {{ background: {t.red_soft}; border: 2px solid {t.red}; }}

/* --- kontrolka segmentowa (pigułki) --- */
QFrame#segTrack {{ background: {t.track}; border-radius: {R['md']}px; border: none; }}
QPushButton#seg {{ background: transparent; border: none; border-radius: {R['sm']}px; padding: 0 16px; min-height: 34px;
    color: {t.text2}; }}
QPushButton#seg:hover {{ background: transparent; color: {t.text}; }}
QPushButton#seg:checked {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.separator}; }}
QPushButton#seg:disabled {{ color: {t.text3}; }}

/* --- zakładki (podkreślenie 2 px) --- */
QFrame#tabTrack {{ background: transparent; border: none; border-bottom: 1px solid {t.separator}; }}
QPushButton#tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    padding: 8px 0 10px 0; margin: 0 24px 0 0; min-height: 22px; color: {t.text2}; font-weight: 500; }}
QPushButton#tab[dense="true"] {{ margin: 0 12px 0 0; }}
QPushButton#tab:hover {{ color: {t.text}; background: transparent; }}
QPushButton#tab:checked {{ color: {t.text}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}
QPushButton#tab:disabled {{ color: {t.text3}; }}
"""


def note_css(t: Tokens | None = None) -> str:
    """Domyślny arkusz treści notatki (QTextDocument)."""
    t = t or T()
    return TK.note_css({**t.d, "fontUi": UI_FAMILY, "fontDisplay": DISPLAY_FAMILY})


def note_box(kind: str, label: str, html: str, t: Tokens | None = None) -> str:
    return TK.note_box((t or T()).d, kind, label, html)
