"""Wersje językowe interfejsu: polski i angielski (bez Qt Linguist).

Teksty w kodzie są po polsku i same są kluczem:  tr("Nowa notatka"),  tr("Zapisano {n} z {total}", n=3, total=5).
Angielskie odpowiedniki są w i18n_en.py (słownik EN: polski tekst → angielski). Brak tłumaczenia = tekst polski
i ostrzeżenie w logu (raz na tekst) – nic się nie wysypuje. Brakujące tłumaczenia wypisuje
_internal/tools/i18n_check.py.

Język wybiera się raz, przy starcie (set_language w main.py, przed zbudowaniem okien): Ustawienia → Ogólne →
„Język aplikacji” (settings.ui_language: "" = jak system, "pl", "en"); „jak system” = polski dla polskiego
Windowsa/macOS, angielski dla każdego innego. Zmiana działa po ponownym uruchomieniu.

Nie dotyczy treści notatek, fiszek, transkrypcji i promptów – te mają własny język (Język wykładu / notatek)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

log = logging.getLogger(__name__)
LANGS = ("pl", "en")
_lang: Optional[str] = None
_missing: set[str] = set()


# ---------------------------------------------------------------------------------------------- język
def system_language() -> str:
    """'pl' dla polskiego systemu, 'en' dla każdego innego (QLocale.system(), zapasowo moduł locale)."""
    try:
        from PySide6.QtCore import QLocale
        return "pl" if QLocale.system().language() == QLocale.Language.Polish else "en"
    except Exception:  # noqa: BLE001 – PySide6 jeszcze niezainstalowane
        pass
    try:
        import locale
        code = (locale.getlocale()[0] or "").lower()
        return "pl" if code.startswith(("pl", "polish")) else "en"
    except Exception:  # noqa: BLE001
        return "pl"


def set_language(code: str = "") -> str:
    """Ustawia język interfejsu ("" = jak system). Wywołać przed zbudowaniem okien."""
    global _lang
    _lang = code if code in LANGS else system_language()
    try:        # liczby w polach Qt (QDoubleSpinBox: „8,00 s” / „8.00 s”) według języka interfejsu
        from PySide6.QtCore import QLocale
        QLocale.setDefault(QLocale(QLocale.Language.Polish, QLocale.Country.Poland) if _lang == "pl"
                           else QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    except Exception:  # noqa: BLE001
        pass
    return _lang


def lang() -> str:
    if _lang is None:
        set_language("")
    return _lang  # type: ignore[return-value]


def is_en() -> bool:
    return lang() == "en"


# ---------------------------------------------------------------------------------------------- teksty
def _en() -> dict:
    from .i18n_en import EN
    return EN


def tr(text: str, **kw) -> str:
    """Tekst w języku interfejsu. Parametry wstawiane jak w str.format: tr("Wersja {v}", v="2.2")."""
    out = text
    if lang() == "en" and text:
        t = _en().get(text)
        if t is None:
            if text not in _missing:
                _missing.add(text)
                log.warning("Brak tłumaczenia (en): %r", text)
        else:
            out = t
    if kw:
        try:
            return out.format(**kw)
        except (KeyError, IndexError, ValueError):
            log.warning("Zły tekst do wstawienia parametrów: %r", out)
            return text.format(**kw)
    return out


def pl_form(n: int) -> int:
    """Polska odmiana przez liczby: 0 = jeden (1 fiszka), 1 = kilka (2 fiszki), 2 = wiele (5 fiszek)."""
    n = abs(int(n))
    if n == 1:
        return 0
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return 1
    return 2


def tn(n: int, one: str, few: str, many: str, **kw) -> str:
    """Tekst z liczbą i odmianą: tn(n, "{n} fiszka", "{n} fiszki", "{n} fiszek").
    Po angielsku: EN_PLURAL["{n} fiszka"] = ("{n} card", "{n} cards"). Liczba wstawiana jako {n} (z separatorem)."""
    kw.setdefault("n", n)
    if lang() == "en":
        from .i18n_en import EN_PLURAL
        pair = EN_PLURAL.get(one)
        if pair is not None:
            return pair[0 if abs(int(n)) == 1 else 1].format(**kw)
        if one not in _missing:
            _missing.add(one)
            log.warning("Brak tłumaczenia (en, liczba mnoga): %r", one)
    return (one, few, many)[pl_form(n)].format(**kw)


def lang_name(code: str) -> str:
    """Nazwa języka notatek/wykładu w języku interfejsu: „angielski” / „English”."""
    from .prompts import LANG_EN, LANG_PL
    return (LANG_EN if lang() == "en" else LANG_PL).get(code, code)


# ---------------------------------------------------------------------------------------------- liczby i daty
def num(x: float, digits: int = 1) -> str:
    """6,7 (pl) / 6.7 (en)."""
    s = f"{x:.{digits}f}"
    return s.replace(".", ",") if lang() == "pl" else s


def gb(n_bytes: float) -> str:
    """Rozmiar: „6,7 GB” / „6.7 GB”, poniżej 1 GB w MB."""
    return f"{num(n_bytes / 1e9)} GB" if n_bytes >= 1e9 else f"{n_bytes / 1e6:.0f} MB"


PL_DAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
PL_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
                 "października", "listopada", "grudnia"]
PL_MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
             "październik", "listopad", "grudzień"]
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


def date_long(d: Optional[date] = None, weekday: bool = True) -> str:
    """„sobota, 10 października” / „Saturday, October 10” (bez dnia tygodnia: „10 października” / „October 10”)."""
    d = d or date.today()
    if lang() == "en":
        s = f"{EN_MONTHS[d.month - 1]} {d.day}"
        return f"{EN_DAYS[d.weekday()]}, {s}" if weekday else s
    s = f"{d.day} {PL_MONTHS_GEN[d.month - 1]}"
    return f"{PL_DAYS[d.weekday()]}, {s}" if weekday else s


def date_short(d) -> str:
    """10.10.2026 (pl) / 10/10/2026 (en: miesiąc/dzień/rok). Przyjmuje date, datetime albo „2026-10-10…”."""
    if isinstance(d, str):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d)
        if not m:
            return ""
        y, mo, da = m.groups()
    else:
        y, mo, da = f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"
    return f"{mo}/{da}/{y}" if lang() == "en" else f"{da}.{mo}.{y}"


PL_DAYS_SHORT = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]
EN_DAYS_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def day_name(i: int, short: bool = False) -> str:
    """Nazwa dnia tygodnia (0 = poniedziałek); short: „Pn” / „Mo”."""
    if short:
        return (EN_DAYS_SHORT if lang() == "en" else PL_DAYS_SHORT)[i]
    return (EN_DAYS if lang() == "en" else PL_DAYS)[i]


def month_name(m: int) -> str:
    """Nazwa miesiąca w mianowniku (1 = styczeń / January)."""
    return (EN_MONTHS if lang() == "en" else PL_MONTHS)[m - 1]


def datetime_short(dt: datetime) -> str:
    return f"{date_short(dt)} {dt:%H:%M}"
