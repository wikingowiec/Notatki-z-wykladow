"""Ustawienia aplikacji (settings.json w %APPDATA%/WykladyAI, na Macu w ~/Library/Application Support/WykladyAI)."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

APP_NAME = "Wykłady"
APP_ID = "WykladyAI"


def _appdata_dir() -> Path:
    from .system import data_dir
    return data_dir()


def _default_library() -> str:
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    old = docs / "Wykłady AI"          # biblioteka z poprzedniej wersji – nie gubimy nagrań
    new = docs / "Wykłady"
    return str(old if old.exists() and not new.exists() else new)


@dataclass
class Settings:
    # Biblioteka
    library_dir: str = field(default_factory=_default_library)

    # Transkrypcja (faster-whisper)
    whisper_model: str = "large-v3"          # large-v3 / large-v3-turbo / medium / small
    whisper_device: str = "auto"             # auto / cuda / cpu
    language: str = "auto"                   # "auto" (wykryj), "pl", "en", … – język, w którym mówi prowadzący
    live_chunk_seconds: float = 20.0         # co ile sekund transkrybować na żywo
    whisper_beam: int = 5                    # 1 = najszybciej, 5 = najdokładniej
    whisper_batch: int = 8                   # ile fragmentów naraz przy transkrypcji pliku
    whisper_backend: str = "faster-whisper"  # silnik mowy; na Macu w przyszłości "mlx" (mlx-whisper na GPU Apple)

    # Wydajność: profil sprzętu (lekki / zrownowazony / pelna, "" = własne) i wynik wykrywania sprzętu
    hw_profile: str = ""
    hw_info: dict = field(default_factory=dict)

    # Slajdy
    slide_interval: float = 1.0              # co ile sekund sprawdzać ekran
    slide_sensitivity: float = 0.05          # ułamek zmienionych pikseli uznawany za nowy slajd
    slide_stable_seconds: float = 1.5        # ile sekund obraz musi stać, żeby zapisać slajd
    ocr_enabled: bool = True                 # OCR slajdów (Windows OCR / Apple Vision, jeśli dostępny)

    # Audio
    audio_backend: str = "auto"              # auto / proctap / native

    # AI (Ollama)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M"
    ollama_ctx: int = 16384
    auto_generate_notes: bool = True
    live_notes: bool = True                  # notatki tworzone w trakcie nagrywania
    live_model: str = "SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0"   # lżejszy model do notatek na żywo
    auto_stop_minutes: int = 10              # zapytaj o zakończenie po tylu minutach ciszy (0 = wyłączone)
    live_ctx: int = 8192                     # kontekst modelu w trakcie nagrywania (mniej pamięci GPU)
    reuse_live_notes: bool = False           # po wykładzie zostaw fragmenty napisane na żywo (szybciej)
    flashcards_per_section: int = 4
    notes_language: str = ""                 # domyślny język notatek: "" = jak wykład, "pl", "en", …
    describe_slides: bool = True             # opisuj obrazy/schematy/wykresy na slajdach (model widzący obrazy)
    vision_model: str = "qwen3-vl:8b-instruct"

    # Wygląd: system / light / dark
    theme: str = "system"                   # tryb: system / light / dark
    theme_name: str = "zeszyt"               # motyw: zeszyt / atrament / akademia
    window_geometry: str = ""                # położenie i rozmiar okna (zapamiętane przy zamknięciu)
    window_maximized: bool = False
    # Notatki na telefon: PDF do folderu synchronizowanego z chmurą (Dysk Google / iCloud / OneDrive)
    phone_sync: bool = False
    phone_dir: str = ""
    # Aktualizacje z GitHuba (np. "uzytkownik/wyklady")
    update_repo: str = ""
    ui_scale: float = 1.0                    # rozmiar interfejsu (0.9 – 1.5), po ponownym uruchomieniu

    # Ostatnio użyte
    last_subject: str = ""
    last_rec: dict = field(default_factory=dict)  # „nagraj jak ostatnio”: rodzaj, dźwięk, ekran, obszar slajdu
    daily_goal: int = 20                     # cel dzienny fiszek

    @classmethod
    def path(cls) -> Path:
        return _appdata_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except Exception:
            pass
        return s

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def library_path(self) -> Path:
        p = Path(self.library_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def log_path() -> Path:
    return _appdata_dir() / "app.log"
