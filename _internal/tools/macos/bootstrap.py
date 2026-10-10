"""Pierwsze uruchomienie na Macu: małe okno z postępem, w tle „pip install PySide6-Essentials”.
Nowe w wersji 2.2.0.

Uruchamiane przez Contents/MacOS/Wyklady wbudowanym Pythonem, zanim jest PySide6 – dlatego okno jest w tkinter
(jest w python-build-standalone). Gdy tkinter nie działa, instalacja idzie bez okna (z powiadomieniem).
Argument: ścieżka znacznika, który powstaje po udanej instalacji. Kod wyjścia 0 = gotowe."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

PAPER, INK, INK2, ACCENT, RED = "#F6F3EC", "#1F1D1A", "#6B655B", "#2F6B55", "#D2452F"
PIP = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
       "--progress-bar", "raw", "PySide6-Essentials"]


def run_pip(events: "queue.Queue", stop: threading.Event) -> None:
    """Instaluje PySide6 i wysyła do okna: ("p", 0..1, opis), ("ok",) albo ("err", opis)."""
    tail: list[str] = []
    try:
        p = subprocess.Popen(PIP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                             env={**os.environ, "PYTHONUTF8": "1", "PIP_NO_COLOR": "1"})
    except OSError as e:
        events.put(("err", str(e)))
        return
    total = 0.0
    for line in p.stdout:
        if stop.is_set():
            p.kill()
            return
        line = line.rstrip()
        tail = (tail + [line])[-12:]
        m = re.match(r"Progress (\d+) of (\d+)", line)
        if m:
            done, tot = float(m.group(1)), float(m.group(2))
            if tot > 5e6:                      # duży plik = PySide6 – po nim liczymy postęp
                total = tot
                events.put(("p", 0.05 + 0.85 * done / tot, f"Pobieram bibliotekę okien · {done / 1e6:.0f} z {tot / 1e6:.0f} MB"))
        elif line.startswith("Installing collected packages"):
            events.put(("p", 0.93, "Instaluję…"))
        elif line.startswith("Collecting") and not total:
            events.put(("p", 0.03, "Sprawdzam, co pobrać…"))
    rc = p.wait()
    if rc == 0:
        events.put(("ok",))
    else:
        msg = "\n".join(x for x in tail if x.strip())[-500:]
        if "Could not" in msg or "NewConnection" in msg or "Temporary failure" in msg:
            msg = "Brak połączenia z internetem. Sprawdź sieć i uruchom Wykłady ponownie."
        events.put(("err", msg or f"kod błędu {rc}"))


def headless(marker: Path) -> int:
    subprocess.run(["/usr/bin/osascript", "-e", 'display notification "Instaluję bibliotekę okien (ok. 100 MB)…" '
                    'with title "Wykłady – pierwsze uruchomienie"'], capture_output=True)
    ev: queue.Queue = queue.Queue()
    run_pip(ev, threading.Event())
    while not ev.empty():
        e = ev.get()
        if e[0] == "ok":
            marker.write_text("ok")
            return 0
        if e[0] == "err":
            print(e[1], file=sys.stderr)
    return 1


def main() -> int:
    marker = Path(sys.argv[1])
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
    except Exception:  # noqa: BLE001
        return headless(marker)

    root.title("Wykłady")
    root.configure(bg=PAPER)
    root.resizable(False, False)
    w, h = 520, 230
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    pad = {"padx": 28}
    tk.Label(root, text="Wykłady", font=("Georgia", 24, "bold"), fg=INK, bg=PAPER).pack(anchor="w", pady=(24, 0), **pad)
    tk.Label(root, text="Pierwsze uruchomienie – przygotowuję aplikację", font=("Helvetica", 13), fg=INK2,
             bg=PAPER).pack(anchor="w", **pad)
    status = tk.Label(root, text="Uruchamiam instalator…", font=("Helvetica", 13), fg=INK2, bg=PAPER, justify="left",
                      wraplength=w - 56)
    status.pack(anchor="w", pady=(18, 6), **pad)
    style = ttk.Style(root)
    try:
        style.configure("W.Horizontal.TProgressbar", troughcolor="#E9E3D7", background=ACCENT)
    except tk.TclError:
        pass
    bar = ttk.Progressbar(root, style="W.Horizontal.TProgressbar", maximum=1000, length=w - 56)
    bar.pack(anchor="w", **pad)
    tk.Label(root, text="Potem otworzy się ekran instalacji bibliotek i modeli AI.", font=("Helvetica", 11), fg=INK2,
             bg=PAPER).pack(anchor="w", pady=(10, 0), **pad)

    ev: queue.Queue = queue.Queue()
    stop = threading.Event()
    result = {"code": 1}
    threading.Thread(target=run_pip, args=(ev, stop), daemon=True).start()

    def poll():
        while not ev.empty():
            e = ev.get()
            if e[0] == "p":
                bar["value"] = int(e[1] * 1000)
                status.config(text=e[2])
            elif e[0] == "ok":
                marker.write_text("ok")
                result["code"] = 0
                bar["value"] = 1000
                status.config(text="Gotowe – otwieram aplikację…")
                root.after(400, root.destroy)
                return
            elif e[0] == "err":
                status.config(text="Nie udało się przygotować aplikacji:\n" + e[1][-300:], fg=RED)
                tk.Button(root, text="Zamknij", command=root.destroy).pack(anchor="e", pady=10, **pad)
                root.geometry(f"{w}x{h + 120}")
                return
        root.after(150, poll)

    def on_close():
        stop.set()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(150, poll)
    root.lift()
    root.attributes("-topmost", True)
    root.after(800, lambda: root.attributes("-topmost", False))
    root.mainloop()
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
