"""Sprzęt i profile wydajności: Lekki / Zrównoważony / Pełna moc.

Wykrywanie działa na samej bibliotece standardowej (rejestr Windows, ctypes, nvidia-smi), więc da się go użyć
w instalatorze, zanim pobiorą się biblioteki aplikacji. Profil to zestaw ustawień: model rozpoznawania mowy,
modele AI, kontekst, notatki na żywo, opisy slajdów i kilka przełączników szybkości."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

BIELIK_11 = "SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M"
BIELIK_45 = "SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0"
QWEN_VL8 = "qwen3-vl:8b-instruct"
QWEN_VL4 = "qwen3-vl:4b-instruct"

ORDER = ["lekki", "zrownowazony", "pelna"]
LABELS = {"lekki": "Lekki", "zrownowazony": "Zrównoważony", "pelna": "Pełna moc"}
FOR = {
    "lekki": "Laptop albo komputer bez mocnej karty graficznej",
    "zrownowazony": "Karta graficzna NVIDIA z 8 GB pamięci",
    "pelna": "Karta graficzna NVIDIA z 12 GB pamięci lub więcej",
}
DESC = {
    "lekki": "Mniejsze modele, bez notatek na żywo i bez opisywania obrazów na slajdach. Notatki powstają po "
             "wykładzie – spokojnie, bez zacinania komputera.",
    "zrownowazony": "Szybszy model mowy, notatki na żywo i gotowe fragmenty z nagrywania zostają w notatce – "
                    "po wykładzie dopisuje się tylko reszta.",
    "pelna": "Najdokładniejsze rozpoznawanie mowy, większy kontekst i dokładniejsze opisy slajdów. Po wykładzie "
             "cała notatka powstaje od nowa mocniejszym modelem.",
}

# pola ustawień, które ustawia profil (whisper_batch nie ma przełącznika – nie wpływa na „Własne”)
FIELDS = ("whisper_model", "whisper_beam", "ollama_model", "live_model", "live_notes", "describe_slides",
          "vision_model", "ollama_ctx", "live_ctx", "reuse_live_notes", "live_chunk_seconds")

WHISPER_GB = {"large-v3": 3.1, "large-v3-turbo": 1.6, "medium": 1.5, "small": 0.5, "base": 0.15}
MODEL_GB = {"bielik-11b": 6.7, "bielik-4.5b": 5.1, "qwen3-vl:8b": 6.1, "qwen3-vl:4b": 3.3, "gemma3:12b": 8.1,
            "qwen3:14b": 9.3}
LIBS_GB = 2.6           # biblioteki aplikacji (z bibliotekami CUDA)
CUDA_LIBS_GB = 1.4      # z tego biblioteki CUDA – niepotrzebne bez karty NVIDIA
OLLAMA_GB = 1.0


# ---------------------------------------------------------------------------
# wykrywanie sprzętu
# ---------------------------------------------------------------------------
def _ram_gb() -> float:
    if sys.platform == "win32":
        import ctypes

        class MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEMSTAT()
        m.dwLength = ctypes.sizeof(MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullTotalPhys / 1024 ** 3
        return 0.0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0.0


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text(errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import platform
    return platform.processor() or "Procesor"


def _nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform == "win32":
        c = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(c) if c.exists() else None
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2 and parts[1].replace(".", "").isdigit():
            out.append({"name": parts[0], "vram_gb": round(float(parts[1]) / 1024, 1), "nvidia": True})
    return out


def _registry_gpus() -> list[dict]:
    """Karty graficzne z rejestru (także AMD i Intel). Pamięć z qwMemorySize – dokładna także powyżej 4 GB."""
    if sys.platform != "win32":
        return []
    out = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                        mem = 0
                        for v in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                raw = winreg.QueryValueEx(k, v)[0]
                                mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else int(raw)
                                if mem:
                                    break
                            except OSError:
                                continue
                except OSError:
                    continue
                if "basic" in name.lower() or "remote" in name.lower() or "virtual" in name.lower():
                    continue
                out.append({"name": name, "vram_gb": round(mem / 1024 ** 3, 1), "nvidia": "nvidia" in name.lower()})
    except Exception:  # noqa: BLE001
        return []
    return out


def detect() -> dict:
    gpus = _nvidia()
    names = {g["name"].lower() for g in gpus}
    for g in _registry_gpus():
        if g["nvidia"] and gpus:          # NVIDIA – dokładniej z nvidia-smi
            continue
        if g["name"].lower() not in names:
            names.add(g["name"].lower())
            gpus.append(g)
    gpus.sort(key=lambda g: (not g["nvidia"], -g["vram_gb"]))
    return {"cpu": _cpu_name(), "threads": os.cpu_count() or 4, "ram_gb": round(_ram_gb(), 1), "gpus": gpus,
            "t": int(time.time())}


def hardware(settings, refresh: bool = False) -> dict:
    """Wynik wykrywania zapamiętany w ustawieniach (nvidia-smi bywa wolne)."""
    hw = getattr(settings, "hw_info", None) or {}
    if refresh or not hw.get("t"):
        hw = detect()
        try:
            settings.hw_info = hw
            settings.save()
        except Exception:  # noqa: BLE001
            pass
    return hw


def nvidia_vram(hw: dict) -> float:
    return max([g["vram_gb"] for g in hw.get("gpus", []) if g.get("nvidia")] + [0.0])


def has_nvidia(hw: dict) -> bool:
    return any(g.get("nvidia") for g in hw.get("gpus", []))


def _short_gpu(name: str) -> str:
    n = re.sub(r"\((R|TM)\)|®|™", "", name)
    n = re.sub(r"\bNVIDIA\s+GeForce\b", "GeForce", n)
    return re.sub(r"\s+", " ", n).strip()


def _short_cpu(name: str) -> str:
    n = re.sub(r"\((R|TM)\)|®|™|\bCPU\b|\bProcessor\b|@.*$|\b\d+(th|st|nd|rd) Gen\b", "", name or "")
    n = re.sub(r"\b\d+-Core\b", "", n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip() or "Procesor"


def describe(hw: dict) -> str:
    """„Intel Core i5-1235U · 16 GB RAM · GeForce RTX 3050 Laptop GPU 4 GB”."""
    parts = [_short_cpu(hw.get("cpu", ""))]
    if hw.get("ram_gb"):
        parts.append(f"{round(hw['ram_gb']):.0f} GB RAM")
    g = (hw.get("gpus") or [None])[0]
    if g:
        parts.append(_short_gpu(g["name"]) + (f" {g['vram_gb']:g} GB".replace(".", ",") if g["vram_gb"] >= 1 else ""))
    else:
        parts.append("bez osobnej karty graficznej")
    return " · ".join(parts)


def recommend(hw: dict) -> tuple[str, str]:
    """(profil, powód w jednym zdaniu)."""
    v = nvidia_vram(hw)
    ram = hw.get("ram_gb", 0)
    if v >= 11.5 and ram >= 15:
        return "pelna", f"Karta NVIDIA ma {_gb(v)} pamięci – zmieszczą się największe modele."
    if v >= 7.5:
        return "zrownowazony", f"Karta NVIDIA ma {_gb(v)} pamięci – wystarczy na szybki model mowy i notatki na żywo."
    if v > 0:
        return "lekki", f"Karta NVIDIA ma tylko {_gb(v)} pamięci – większe modele zwalniałyby komputer."
    return "lekki", "Nie ma karty NVIDIA, więc rozpoznawanie mowy i notatki liczy procesor."


def _gb(x: float) -> str:
    return f"{x:g} GB".replace(".", ",")


def fmt_gb(x: float) -> str:
    """6,7 GB (jedno miejsce po przecinku, polski zapis)."""
    return f"{x:.1f}".replace(".", ",").replace(",0", "") + " GB"


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
def values(key: str, hw: dict) -> dict:
    gpu = has_nvidia(hw)
    if key == "lekki":
        return {"whisper_model": "large-v3-turbo" if gpu else "small", "whisper_beam": 1,
                "whisper_batch": 8 if gpu else 4,
                "ollama_model": BIELIK_45, "live_model": BIELIK_45, "live_notes": False, "describe_slides": False,
                "vision_model": QWEN_VL4, "ollama_ctx": 8192, "live_ctx": 8192, "reuse_live_notes": True,
                "live_chunk_seconds": 30.0}
    if key == "zrownowazony":
        return {"whisper_model": "large-v3-turbo" if gpu else "medium", "whisper_beam": 2,
                "whisper_batch": 8 if gpu else 4,
                "ollama_model": BIELIK_11, "live_model": BIELIK_45, "live_notes": True, "describe_slides": True,
                "vision_model": QWEN_VL4, "ollama_ctx": 8192, "live_ctx": 8192, "reuse_live_notes": True,
                "live_chunk_seconds": 20.0}
    big = nvidia_vram(hw) >= 15.5
    return {"whisper_model": "large-v3" if gpu else "medium", "whisper_beam": 5,
            "whisper_batch": (16 if big else 8) if gpu else 4,
            "ollama_model": BIELIK_11, "live_model": BIELIK_45, "live_notes": True, "describe_slides": True,
            "vision_model": QWEN_VL8, "ollama_ctx": 16384, "live_ctx": 8192, "reuse_live_notes": False,
            "live_chunk_seconds": 20.0}


def apply(settings, key: str, hw: dict | None = None) -> None:
    hw = hw if hw is not None else hardware(settings)
    for k, v in values(key, hw).items():
        setattr(settings, k, v)
    settings.hw_profile = key


def current(settings, hw: dict | None = None) -> str:
    """Profil, któremu odpowiadają obecne ustawienia ('' = własne)."""
    hw = hw if hw is not None else (getattr(settings, "hw_info", None) or {})
    for key in ORDER:
        vals = values(key, hw)
        if all(_eq(getattr(settings, f, None), vals[f]) for f in FIELDS):
            return key
    return ""


def _eq(a, b) -> bool:
    if isinstance(b, float) or isinstance(a, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return a == b


def model_gb(name: str) -> float:
    low = (name or "").lower()
    return next((v for k, v in MODEL_GB.items() if k in low), 5.0)


def models_of(vals: dict) -> list[str]:
    out = [vals["ollama_model"]]
    if vals.get("live_notes"):
        out.append(vals["live_model"])
    if vals.get("describe_slides"):
        out.append(vals["vision_model"])
    return list(dict.fromkeys(m for m in out if m))


def download_gb(key: str, hw: dict, with_libs: bool = True) -> float:
    vals = values(key, hw)
    tot = WHISPER_GB.get(vals["whisper_model"], 1.5) + sum(model_gb(m) for m in models_of(vals))
    if with_libs:
        tot += LIBS_GB - (0 if has_nvidia(hw) else CUDA_LIBS_GB) + OLLAMA_GB
    return round(tot, 1)


def cpu_threads(hw: dict | None = None) -> int:
    n = (hw or {}).get("threads") or os.cpu_count() or 4
    return max(4, min(8, n // 2))


# ---------------------------------------------------------------------------
# Ollama: flash attention i skwantyzowana pamięć kontekstu (mniej pamięci karty = model mieści się w całości)
# ---------------------------------------------------------------------------
OLLAMA_ENV = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}


def ollama_env() -> dict:
    """Zmienne środowiska dla Ollamy. Na Windows zapisuje je też jako zmienne użytkownika (działają od
    następnego uruchomienia Ollamy), chyba że użytkownik ustawił je sam."""
    env = {**os.environ}
    for k, v in OLLAMA_ENV.items():
        env.setdefault(k, v)
    if sys.platform == "win32":
        try:
            import ctypes
            import winreg
            changed = False
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                for name, val in OLLAMA_ENV.items():
                    try:
                        winreg.QueryValueEx(k, name)
                    except OSError:
                        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
                        changed = True
            if changed:      # powiadom Eksploratora, żeby nowe procesy widziały zmienne
                res = ctypes.c_ulong()
                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000,
                                                         ctypes.byref(res))
        except Exception:  # noqa: BLE001
            pass
    return env
