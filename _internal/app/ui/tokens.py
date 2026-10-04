"""Tokeny projektu „Wykłady” — kierunek A (Zeszyt 2.0) + warianty Atrament i Akademia.

Źródło prawdy dla kolorów, fontów, odstępów i promieni. Widgety biorą je przez theme.T().

Użycie (PySide6):
    from wyklady_tokens import LIGHT, DARK, qss, note_css, note_box
    app.setStyleSheet(qss(LIGHT))
    browser.document().setDefaultStyleSheet(note_css(LIGHT))

Rozmiary podane w px (QFont.setPixelSize). Nazwy kolorów są takie same
w obu motywach — przełączenie motywu = podmiana słownika.
"""

# ---------------------------------------------------------------- kolory
LIGHT = {
    "bg": "#F4F1EA",          # tło okna (papier)
    "side": "#EBE6DB",        # pasek boczny
    "sideActive": "#DFD8C9",  # aktywna pozycja w pasku
    "surface": "#FFFDF8",     # karty, kartka notatki
    "surface2": "#F5F1E8",    # pola tekstowe, „W skrócie”
    "line": "#E1DACB",        # obramowania 1 px
    "line2": "#CFC6B3",       # mocniejsze linie, przerywane ramki
    "ink": "#1E2320",         # tekst główny
    "ink2": "#4F5650",        # tekst drugorzędny
    "ink3": "#676C66",        # podpisy (min. 4,5:1 na bg)
    "accent": "#2F6B55",
    "accentHover": "#255A47",
    "accentPressed": "#1F4C3C",
    "accentInk": "#FFFFFF",   # tekst na accent
    "accentSoft": "#DCE8E0",
    "accentText": "#24563F",  # linki i statusy na jasnym tle
    "mark": "#F6E1A0",        # zakreślenie / „Zaznacz ważne”
    "markLine": "#D9B44A",
    "rec": "#BF3F2C",
    "recInk": "#FFFFFF",
    "recSoft": "#F5DDD6",
    "recText": "#A3331F",
    "streak": "#C9681E",
    "kbd": "rgba(30,35,32,18)",  # tło skrótów klawiszowych
    # ramki w notatce: tło / pasek / etykieta
    "defBg": "#E4EEE8", "defBar": "#2F6B55", "defText": "#24563F",
    "wzBg": "#EEE6F2", "wzBar": "#86569A", "wzText": "#6E4580",
    "przBg": "#E5EBF6", "przBar": "#3B5BA5", "przText": "#2F4C8C",
    "wazBg": "#F7E7DD", "wazBar": "#B4553A", "wazText": "#93432C",
    "tldrBg": "#F5F1E8", "tldrBar": "#676C66",
    "ok": "#2F7A4A", "okSoft": "#E1F0E3",          # „umiem”, dobra odpowiedź
    "shadow": "#282314",
    "logoPaper": "#FFFDF7",
}

DARK = {
    "bg": "#141816",
    "side": "#0F1211",
    "sideActive": "#202724",
    "surface": "#1B201E",
    "surface2": "#222826",
    "line": "#2D3431",
    "line2": "#3D4641",
    "ink": "#E7EBE7",
    "ink2": "#B0B8B2",
    "ink3": "#8E9791",
    "accent": "#6DBE9A",
    "accentHover": "#86CDAD",
    "accentPressed": "#5AA886",
    "accentInk": "#0D1A14",
    "accentSoft": "#203A2F",
    "accentText": "#8DD2B2",
    "mark": "#5A4913",
    "markLine": "#8C7425",
    "rec": "#E8664F",
    "recInk": "#1A0C09",
    "recSoft": "#3A1F1A",
    "recText": "#F08A76",
    "streak": "#F09A4A",
    "kbd": "rgba(255,255,255,20)",
    "defBg": "#1C2E26", "defBar": "#6DBE9A", "defText": "#8DD2B2",
    "wzBg": "#29212E", "wzBar": "#C08BD3", "wzText": "#D4AEE2",
    "przBg": "#1D2436", "przBar": "#8BA3E0", "przText": "#ADC0EC",
    "wazBg": "#33231C", "wazBar": "#E08B6E", "wazText": "#EDAA92",
    "tldrBg": "#222826", "tldrBar": "#8E9791",
    "ok": "#86D69A", "okSoft": "#1B3424",
    "shadow": "#000000",
    "logoPaper": "#FFFDF7",
}

# Przedmioty i kategorie tematów (ta sama kolejność w obu motywach).
SUBJECTS_LIGHT = ["#2F6B55", "#3B5BA5", "#B4553A", "#86569A",
                  "#A77C16", "#2A7C88", "#A2466A", "#5D6B2C"]
SUBJECTS_DARK = ["#6DBE9A", "#8BA3E0", "#E08B6E", "#C08BD3",
                 "#D9B04A", "#5FB7C2", "#E089AC", "#A9B86A"]

# ------------------------------------------------------------ typografia
FONT_DISPLAY = "Fraunces"   # nagłówki, zegar, pytania fiszek
FONT_UI = "Inter"           # interfejs i treść notatki
FONT_MATH = "Cambria Math"  # wzory (fallback: STIX Two Math)

TYPE = {  # nazwa: (rodzina, px, waga, interlinia, odstęp liter w em)
    "display":   (FONT_DISPLAY, 36, 600, 1.10, -0.01),
    "h1":        (FONT_DISPLAY, 32, 600, 1.15, -0.01),
    "question":  (FONT_DISPLAY, 31, 600, 1.25, 0.0),
    "h2":        (FONT_DISPLAY, 25, 600, 1.25, 0.0),
    "h3":        (FONT_DISPLAY, 18, 600, 1.30, 0.0),
    "timer":     (FONT_DISPLAY, 42, 500, 1.00, 0.0),   # cyfry tabelaryczne
    "noteBody":  (FONT_UI, 15.5, 400, 1.70, 0.0),
    "body":      (FONT_UI, 14, 400, 1.45, 0.0),
    "button":    (FONT_UI, 14, 600, 1.20, 0.0),
    "small":     (FONT_UI, 12.5, 400, 1.40, 0.0),
    "caption":   (FONT_UI, 12, 400, 1.35, 0.0),
    "overline":  (FONT_UI, 11, 700, 1.30, 0.09),       # WIELKIE LITERY
}

# --------------------------------------------------- odstępy i promienie
SPACE = {"xxs": 2, "xs": 4, "sm": 8, "md": 12, "lg": 16,
         "xl": 20, "2xl": 24, "3xl": 32, "4xl": 48}

RADIUS = {"xs": 5,    # klawisze, małe znaczniki
          "sm": 8,    # pozycje menu, chipy
          "md": 11,   # przyciski, pola
          "lg": 14,   # karty, kartka notatki
          "xl": 20,   # karta fiszki
          "full": 999}

# QGraphicsDropShadowEffect: (blur, offsetX, offsetY, RGBA)
SHADOW = {
    "card": (20, 0, 6, (40, 35, 20, 15)),
    "lift": (40, 0, 18, (40, 35, 20, 26)),   # fiszka
    "darkCard": (4, 0, 1, (0, 0, 0, 90)),
}

LAYOUT = {
    "sidebar": 240, "lectureList": 316, "toc": 248, "dock21x9": 540,
    "noteMeasure": 640, "control": 44, "controlLarge": 48,
    "bpCollapseSidebar": 1100,   # < 1100 px: pasek boczny jako menu
    "bpSingleColumn": 820,       # < 820 px: układ jednokolumnowy (9:16)
}

ANIM_MS = {"fast": 120, "base": 180, "slow": 260}  # QPropertyAnimation, OutCubic


# ------------------------------------------------------------- QSS bazowy
def qss(t: dict) -> str:
    r = t.get("radius", RADIUS)
    fu = t.get("fontUi", FONT_UI)
    return f"""
QWidget {{ background: {t['bg']}; color: {t['ink']}; font-family: "{fu}"; font-size: 14px; }}
QFrame#Sidebar {{ background: {t['side']}; border-right: 1px solid {t['line']}; }}
QFrame#Card, QTextBrowser#Note {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: {r['lg']}px; }}
QLabel[role="overline"] {{ color: {t['ink3']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="caption"] {{ color: {t['ink3']}; font-size: 12px; }}
QPushButton {{ min-height: 44px; padding: 0 16px; border-radius: {r['md']}px;
    border: 1px solid {t['line']}; background: {t['surface']}; color: {t['ink']}; font-weight: 600; }}
QPushButton:hover {{ border-color: {t['line2']}; }}
QPushButton[variant="primary"] {{ background: {t['accent']}; color: {t['accentInk']}; border: none; }}
QPushButton[variant="primary"]:hover {{ background: {t['accentHover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {t['accentPressed']}; }}
QPushButton[variant="mark"] {{ background: {t['mark']}; border: 1px solid {t['markLine']}; }}
QPushButton[variant="danger"] {{ background: {t['rec']}; color: {t['recInk']}; border: none; }}
QPushButton:focus {{ outline: none; border: 2px solid {t['accent']}; }}
QLineEdit {{ min-height: 40px; padding: 0 12px; border-radius: {r['md']}px;
    border: 1px solid {t['line']}; background: {t['surface2']}; selection-background-color: {t['accentSoft']}; }}
QLineEdit:focus {{ border: 2px solid {t['accent']}; }}
QListView#NavList::item {{ min-height: 34px; padding: 0 10px; border-radius: {r['sm']}px; }}
QListView#NavList::item:selected {{ background: {t['sideActive']}; color: {t['ink']}; font-weight: 600; }}
QTabBar::tab {{ padding: 8px 0 10px; margin-right: 24px; color: {t['ink2']}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['ink']}; border-bottom-color: {t['accent']}; font-weight: 600; }}
QProgressBar {{ max-height: 4px; border: none; border-radius: 2px; background: {t['line']}; }}
QProgressBar::chunk {{ border-radius: 2px; background: {t['accent']}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {t['line2']}; border-radius: 4px; min-height: 40px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


# ------------------------------------------------- treść notatki (QTextBrowser)
def note_css(t: dict) -> str:
    """Domyślny arkusz dla QTextDocument (obsługuje tylko prosty CSS)."""
    return f"""
body {{ font-family: "{t.get('fontUi', FONT_UI)}"; font-size: 15.5px; color: {t['ink']}; }}
p, li {{ line-height: 170%; }}
h2 {{ font-family: "{t.get('fontDisplay', FONT_DISPLAY)}"; font-size: 25px; font-weight: 600; margin-top: 28px; margin-bottom: 4px; }}
h3 {{ font-family: "{t.get('fontDisplay', FONT_DISPLAY)}"; font-size: 18px; font-weight: 600; margin-top: 18px; }}
.meta {{ color: {t['ink3']}; font-size: 12.5px; }}
.mark {{ background-color: {t['mark']}; }}
.label {{ font-size: 11px; font-weight: 700; }}
.math {{ font-family: "{FONT_MATH}"; font-style: italic; font-size: 21px; }}
a {{ color: {t['accentText']}; text-decoration: none; font-weight: 600; }}
"""


def note_box(t: dict, kind: str, label: str, html: str) -> str:
    """Ramka „tło + pasek z boku” jako tabela 2-kolumnowa (działa w QTextBrowser).
    kind: 'def' | 'wz' | 'prz' | 'waz' | 'tldr'"""
    bg, bar = t[f"{kind}Bg"], t[f"{kind}Bar"]
    lab_col = t.get(f"{kind}Text", t["ink3"])
    head = f'<span class="label" style="color:{lab_col}">{label}</span><br>' if label else ""
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin: 14px 0;">'
            f'<tr><td width="3" style="background-color:{bar}"></td>'
            f'<td style="background-color:{bg}; padding: 10px 16px;">{head}{html}</td></tr></table>')


# ------------------------------------------------ motywy
# "A" = Zeszyt (domyślny, LIGHT/DARK powyżej), "A1" = Atrament, "A3" = Akademia.
# Każdy wariant = nadpisanie LIGHT/DARK + fonty + mnożnik promieni.
# Użycie: t = variant("A1", dark=False); app.setStyleSheet(qss(t))
VARIANTS = {
    "A1": {  # Atrament — ciepły, miękki, granatowy
        "fontDisplay": "Literata", "fontUi": "Nunito Sans", "radiusScale": 1.4,
        "light": {"bg": "#F7F3EA", "side": "#EFE8DA", "sideActive": "#E4DAC6", "surface": "#FFFCF6",
                  "surface2": "#F6F0E4", "line": "#E5DCCB", "line2": "#D2C6B0", "ink": "#1F2433",
                  "ink2": "#4B5163", "ink3": "#62677A", "accent": "#2B4C7E", "accentHover": "#233F69",
                  "accentPressed": "#1C3356", "accentSoft": "#DFE6F1", "accentText": "#24406B",
                  "mark": "#FBE3A4", "markLine": "#DDB04C", "streak": "#C4601A",
                  "defBg": "#E3E9F3", "defBar": "#2B4C7E", "defText": "#24406B",
                  "przBg": "#E4EFE8", "przBar": "#2F6B55", "przText": "#24563F"},
        "dark": {"bg": "#141822", "side": "#10131B", "sideActive": "#1F2433", "surface": "#1A1F2B",
                 "surface2": "#212736", "line": "#2C3344", "line2": "#3B4357", "ink": "#E8EAF0",
                 "ink2": "#B3B8C6", "ink3": "#9096A6", "accent": "#8FB0E8", "accentHover": "#A6C1EE",
                 "accentPressed": "#7A9BD6", "accentInk": "#0E1626", "accentSoft": "#22304A",
                 "accentText": "#A9C3EF", "mark": "#5B4A18", "markLine": "#8C7427",
                 "defBg": "#1E2942", "defBar": "#8FB0E8", "defText": "#A9C3EF",
                 "przBg": "#1C2E26", "przBar": "#6DBE9A", "przText": "#8DD2B2"},
    },
    "A3": {  # Akademia — klasyczny, książkowy, bordo, obramowania zamiast cieni
        "fontDisplay": "Spectral", "fontUi": "Public Sans", "radiusScale": 0.4,
        "light": {"bg": "#F5F4F0", "side": "#ECEAE4", "sideActive": "#E0DDD3", "surface": "#FFFFFF",
                  "surface2": "#F7F6F2", "line": "#DCD8CE", "line2": "#C2BCAE", "ink": "#1D1B1A",
                  "ink2": "#4E4A46", "ink3": "#65605A", "accent": "#7A2E3A", "accentHover": "#682631",
                  "accentPressed": "#561F28", "accentSoft": "#F1E1E3", "accentText": "#6A2532",
                  "mark": "#F3E2A6", "markLine": "#C9A443", "streak": "#A8521A",
                  "defBg": "#F1E6E8", "defBar": "#7A2E3A", "defText": "#6A2532"},
        "dark": {"bg": "#161414", "side": "#110F0F", "sideActive": "#251F20", "surface": "#1C1A19",
                 "surface2": "#232020", "line": "#322D2C", "line2": "#463F3D", "ink": "#ECE8E4",
                 "ink2": "#B9B2AC", "ink3": "#9A938C", "accent": "#D98C98", "accentHover": "#E3A2AC",
                 "accentPressed": "#C97784", "accentInk": "#22090E", "accentSoft": "#3A2026",
                 "accentText": "#E6A5AF", "mark": "#574616", "markLine": "#8C7327",
                 "defBg": "#331F24", "defBar": "#D98C98", "defText": "#E6A5AF"},
        "shadows": False,
    },
}


def variant(name: str = "A", dark: bool = False) -> dict:
    """Zwraca słownik kolorów + 'fontDisplay', 'fontUi', 'radius' dla wariantu."""
    base = dict(DARK if dark else LIGHT)
    v = VARIANTS.get(name)
    k = 1.0
    base["shadows"] = True
    if v:
        base.update(v["dark" if dark else "light"])
        k = v["radiusScale"]
        base["shadows"] = v.get("shadows", True)
        base["fontDisplay"], base["fontUi"] = v["fontDisplay"], v["fontUi"]
    else:
        base["fontDisplay"], base["fontUi"] = FONT_DISPLAY, FONT_UI
    base["radius"] = {n: (r if n == "full" else max(2, round(r * k))) for n, r in RADIUS.items()}
    return base


THEMES = {"zeszyt": "A", "atrament": "A1", "akademia": "A3"}  # nazwa w Ustawieniach -> klucz
THEME_LABELS = {"zeszyt": "Zeszyt", "atrament": "Atrament", "akademia": "Akademia"}
THEME_NOTES = {"zeszyt": "Zielony, papierowy – domyślny.",
               "atrament": "Granatowy, miękki, zaokrąglony.",
               "akademia": "Bordowy, książkowy, ostre rogi."}
FALLBACK = {"display": "Georgia", "ui": "Segoe UI"}
