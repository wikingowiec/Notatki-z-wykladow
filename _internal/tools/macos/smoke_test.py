"""Test dymny paczki na Macu (GitHub Actions, macos-14): aplikacja startuje bez ekranu, otwiera bibliotekę z przykładowym
wykładem i zapisuje zrzuty. Sprawdza też wykrywanie Maca, OCR Apple Vision, wybór paczki .dmg w aktualizatorze
i moduły nagrywania na żywo (Core Audio, ScreenCaptureKit, zgody) – bez nagrywania i bez próśb o zgodę.
Nowe w wersji 2.2.0.

    python smoke_test.py <folder _internal z Wykłady.app> <folder na zrzuty>

Uruchamiać wbudowanym Pythonem z bibliotekami z requirements-mac.txt. HOME warto podmienić na pusty folder
(ustawienia i biblioteka lądują wtedy w nim). Kod wyjścia 0 = wszystko działa."""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

INTERNAL = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(INTERNAL))
os.chdir(INTERNAL)
MAC = sys.platform == "darwin"
problems: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK   " if ok else "BŁĄD ") + name + (f" – {detail}" if detail else ""), flush=True)
    if not ok:
        problems.append(name)


def settle(app, seconds: float = 2.0) -> None:
    """Czeka na zadania w tle (wczytywanie notatek, miniatury) i przetwarza zdarzenia."""
    import time
    from PySide6.QtCore import QThreadPool
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        QThreadPool.globalInstance().waitForDone(50)
        app.processEvents()


def sample_lecture(library: Path):
    from app.storage import Lecture
    lec = Lecture.create(library, "Analiza matematyczna – wykład 3", "Analiza matematyczna")
    lec.meta.duration = 1520.0
    lec.meta.status = "gotowy"
    lec.meta.kind = "files"
    lec.meta.language = "pl"
    lec.save_meta()
    lec.write_segments([
        {"start": 0.0, "end": 6.5, "text": "Dzień dobry, dzisiaj zajmiemy się granicą ciągu."},
        {"start": 6.5, "end": 14.0, "text": "Ciąg jest zbieżny, jeśli jego wyrazy zbliżają się do jednej liczby."},
        {"start": 14.0, "end": 22.0, "text": "Przykładem jest ciąg jeden przez n, którego granica wynosi zero."},
    ])
    (lec.folder / "notes.md").write_text(
        "# Granica ciągu\n\n"
        "## Definicja\n\n"
        "> **Definicja.** Ciąg $a_n$ jest **zbieżny** do $g$, jeśli dla każdego $\\varepsilon > 0$ istnieje $N$, "
        "że dla $n > N$ zachodzi $|a_n - g| < \\varepsilon$.\n\n"
        "## Przykłady\n\n"
        "- $\\lim_{n\\to\\infty} \\frac{1}{n} = 0$\n"
        "- ciąg $(-1)^n$ nie ma granicy\n\n"
        "## Twierdzenie o trzech ciągach\n\n"
        "Jeśli $a_n \\le b_n \\le c_n$ i skrajne ciągi mają tę samą granicę, to środkowy też ją ma.\n",
        encoding="utf-8")
    (lec.folder / "summary.md").write_text("Wykład o granicy ciągu: definicja, przykłady, twierdzenie o trzech "
                                           "ciągach.\n", encoding="utf-8")
    (lec.folder / "flashcards.json").write_text(json.dumps([
        {"q": "Kiedy ciąg jest zbieżny?", "a": "Gdy jego wyrazy dowolnie blisko zbliżają się do jednej liczby.",
         "known": False},
        {"q": "Ile wynosi granica 1/n?", "a": "0", "known": False},
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    return lec


def live_modules() -> None:
    """Moduły nagrywania na Macu: listy źródeł i stany zgód (nic nie nagrywa, o nic nie prosi)."""
    from app import mac_audio, mac_permissions as mp
    from app.audio_capture import LevelMonitor, list_audio_sources
    from app.screen_capture import list_monitors, list_windows, make_grabber
    check("Core Audio process taps", mac_audio.has_process_taps())
    try:
        import objc
        objc.lookUpClass("CATapDescription")
        check("klasa CATapDescription", True)
    except Exception as e:  # noqa: BLE001
        check("klasa CATapDescription", False, str(e))
    try:
        srcs = list_audio_sources()
        kinds = sorted({s.kind for s in srcs})
        check("lista źródeł dźwięku", any(s.kind == "system" for s in srcs), f"{len(srcs)} źródeł: {kinds}")
        print("     mikrofony:", [s.label for s in srcs if s.kind == "mic"])
    except Exception as e:  # noqa: BLE001
        check("lista źródeł dźwięku", False, repr(e))
    check("miernik poziomu (wersja Mac)", LevelMonitor is mac_audio.LevelMonitor)
    states = {k: mp.status(k) for k in (mp.MIC, mp.AUDIO, mp.SCREEN)}
    check("stany zgód", all(v in (mp.GRANTED, mp.DENIED, mp.UNKNOWN) for v in states.values()), json.dumps(states))
    try:
        mons = list_monitors()
        check("lista ekranów", isinstance(mons, list), "; ".join(m.label for m in mons))
        wins = list_windows()           # bez zgody na ekran – pusta lista, bez prośby
        check("lista okien bez prośby o zgodę", isinstance(wins, list), f"{len(wins)} okien")
        if mons:
            g = make_grabber(mons[0])
            img = g.grab()
            check("zrzut ekranu albo komunikat o zgodzie", img is not None or bool(g.last_error),
                  "obraz %s" % (img.shape,) if img is not None else g.last_error)
            g.close()
    except Exception as e:  # noqa: BLE001
        check("ekrany i okna", False, repr(e))


def main() -> int:
    from app import system
    check("system rozpoznany jako macOS", system.IS_MAC == MAC, system.system_name())
    if MAC:
        live_ok = system.mac_version() >= system.MAC_LIVE_MIN
        check("nagrywanie na żywo zgodnie z wersją macOS", system.LIVE_RECORDING == live_ok,
              ".".join(map(str, system.mac_version())))
        check("ustawienia w Application Support", "Library/Application Support/WykladyAI" in str(system.data_dir()))
        if system.LIVE_RECORDING:
            live_modules()

    from app import perf
    hw = perf.detect()
    print("     sprzęt:", json.dumps(hw, ensure_ascii=False))
    if MAC:
        check("wykrycie Maca (sysctl)", bool(hw.get("apple")) and hw.get("ram_gb", 0) > 0, perf.describe(hw))
        key, why = perf.recommend(hw)
        check("profil dobrany", key in perf.ORDER, f"{perf.LABELS[key]} – {why}")
        check("wątki Whispera = rdzenie wydajnościowe", perf.cpu_threads(hw) >= 2, str(perf.cpu_threads(hw)))

    from app import updater
    rel = {"assets": [{"name": "Wyklady-9.9.9-Windows.zip", "browser_download_url": "https://x/w.zip"},
                      {"name": "Wyklady-9.9.9-Mac.dmg", "browser_download_url": "https://x/m.dmg"}]}
    check("aktualizator wybiera .dmg na Macu", updater.release_asset(rel, "darwin") == ("https://x/m.dmg", False))
    check("aktualizator wybiera .zip na Windows", updater.release_asset(rel, "win32")[0] == "https://x/w.zip")

    from app.config import Settings
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from app.ui.theme import load_fonts, theme, ui_font
    load_fonts()
    app.setFont(ui_font(10.5))

    if MAC:     # OCR: tekst narysowany przez Qt → Apple Vision
        import numpy as np
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter
        img = QImage(1400, 500, QImage.Format.Format_RGB888)
        img.fill(QColor("white"))
        p = QPainter(img)
        f = QFont("Helvetica")
        f.setPixelSize(64)
        p.setFont(f)
        p.setPen(QColor("black"))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "Granica ciągu\nTwierdzenie o trzech ciągach")
        p.end()
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(500, img.bytesPerLine())[:, :1400 * 3]
        arr = arr.reshape(500, 1400, 3)[:, :, ::-1].copy()
        from app.ocr import ocr_image
        text = ocr_image(arr)
        check("OCR Apple Vision", "granica" in text.lower() or "twierdzenie" in text.lower(), repr(text[:80]))

    s = Settings()
    s.library_dir = str(Path.home() / "Documents" / "Wykłady")
    s.hw_info = hw
    key, _ = perf.recommend(hw)
    perf.apply(s, key, hw)
    lec = sample_lecture(s.library_path())

    from app.ui.main_window import MainWindow
    shots = [("zeszyt", "light", 1366, 860, "library"), ("atrament", "dark", 1366, 860, "library-dark"),
             ("zeszyt", "light", 720, 860, "library-720"), ("zeszyt", "light", 1366, 860, "record"),
             ("zeszyt", "light", 1366, 860, "settings")]
    for name, mode, w, h, what in shots:
        theme().apply(name, mode)
        win = MainWindow(s)
        win.resize(w, h)
        win.prepare_layout()
        win.show()
        if what.startswith("library"):
            win.open_lecture_at(str(lec.folder))
        elif what == "record":
            win._select_key(("record", None))
        else:
            win._select_key(("settings", None))
        settle(app)
        path = OUT / f"{what}.png"
        ok = win.grab().save(str(path))
        check(f"zrzut {what}", ok and path.stat().st_size > 10_000, str(path))
        if what == "record" and MAC:
            from app.system import LIVE_RECORDING
            cards = win.record.modes
            if LIVE_RECORDING:
                check("karty nagrywania aktywne, wybrane „Dźwięk + slajdy”",
                      not any(cards[k].soon for k in ("av", "audio", "slides")) and cards["av"].isChecked())
                check("panel zgód macOS na ekranie nagrywania", win.record.perm_panel is not None)
            else:
                check("karty nagrywania wyszarzone, „Z pliku” aktywne",
                      all(cards[k].soon for k in ("av", "audio", "slides")) and cards["files"].isChecked())
        win.close()
        settle(app, 0.5)
        win.deleteLater()
        app.processEvents()

    print()
    if problems:
        print("Nie przeszło:", ", ".join(problems))
        return 1
    print("Wszystko działa.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
