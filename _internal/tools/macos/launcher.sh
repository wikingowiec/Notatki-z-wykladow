#!/bin/bash
# Wykłady.app/Contents/MacOS/Wyklady – program startowy na macOS (odpowiednik Wykłady.exe).
# Nowe w wersji 2.2.0.
#
#  - Zwykłe uruchomienie: wbudowany Python z ~/Library/Application Support/WykladyAI/runtime uruchamia
#    Contents/Resources/_internal/main.py (exec – ten sam proces, więc Dock pokazuje ikonę Wykłady.app).
#    Python działa wewnątrz Contents/MacOS/WykladyHost (host.c): zgody macOS (mikrofon, dźwięk systemu, ekran)
#    trafiają wtedy do „Wykłady” z opisami z Info.plist. Gdy WykladyHost nie działa – zwykły python3.
#  - Pierwsze uruchomienie: pobiera Pythona (python-build-standalone, arm64), potem bootstrap.py w małym okienku
#    instaluje bibliotekę okien (PySide6). Dalszą część (biblioteki, model mowy, Ollama, modele AI) pokazuje już
#    ekran z notesem w samej aplikacji – ten sam co na Windows.
#  - Diagnoza: w Terminalu „/Applications/Wykłady.app/Contents/MacOS/Wyklady --debug” (komunikaty w Terminalu).
set -u

PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20250604/cpython-3.12.11+20250604-aarch64-apple-darwin-install_only_stripped.tar.gz"

HERE="$(cd "$(dirname "$0")" && pwd)"
INTERNAL="$HERE/../Resources/_internal"
SUPPORT="$HOME/Library/Application Support/WykladyAI"
RUNTIME="$SUPPORT/runtime"
PY="$RUNTIME/python/bin/python3"
OK="$RUNTIME/python/.wyklady-ok"          # znacznik: Python i PySide6 gotowe

alert() {   # okno z komunikatem (działa bez Pythona)
    /usr/bin/osascript -e "display dialog \"$1\" with title \"Wykłady\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1
}

# język komunikatów jak interfejs aplikacji: settings.json („ui_language”), a przy „jak system” – język macOS
EN=1
if grep -q '"ui_language": "pl"' "$SUPPORT/settings.json" 2>/dev/null; then
    EN=0
elif ! grep -q '"ui_language": "en"' "$SUPPORT/settings.json" 2>/dev/null \
        && /usr/bin/defaults read -g AppleLanguages 2>/dev/null | sed -n 2p | grep -qiE '^[[:space:]]*"?pl'; then
    EN=0
fi
T() { if [ "$EN" = "1" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
    alert "$(T "Wykłady na Macu wymagają układu Apple (M1, M2, M3, M4). Ten Mac ma procesor Intel." \
               "Wykłady on a Mac requires Apple silicon (M1, M2, M3, M4). This Mac has an Intel processor.")"
    exit 1
fi

if [ ! -x "$PY" ] || [ ! -f "$OK" ]; then
    mkdir -p "$RUNTIME" || { alert "$(T "Nie można utworzyć folderu $RUNTIME." "Couldn't create the folder $RUNTIME.")"; exit 1; }
    if [ ! -x "$PY" ]; then
        NOTE="$(T "Pobieram Pythona (ok. 16 MB) – za chwilę pojawi się okno przygotowania." \
                  "Downloading Python (about 16 MB) – the setup window will appear shortly.")"
        TITLE="$(T "Wykłady – pierwsze uruchomienie" "Wykłady – first launch")"
        /usr/bin/osascript -e "display notification \"$NOTE\" with title \"$TITLE\"" >/dev/null 2>&1
        TMP="$(mktemp -d)"
        if ! /usr/bin/curl -fsSL --retry 3 -o "$TMP/python.tar.gz" "$PY_URL"; then
            rm -rf "$TMP"
            alert "$(T "Nie udało się pobrać Pythona. Sprawdź połączenie z internetem i uruchom Wykłady ponownie." \
                       "Couldn't download Python. Check your internet connection and open Wykłady again.")"
            exit 1
        fi
        rm -rf "$RUNTIME/python"
        if ! /usr/bin/tar -xzf "$TMP/python.tar.gz" -C "$RUNTIME"; then
            rm -rf "$TMP" "$RUNTIME/python"
            alert "$(T "Nie udało się rozpakować Pythona (za mało miejsca na dysku?)." \
                       "Couldn't unpack Python (not enough disk space?).")"
            exit 1
        fi
        rm -rf "$TMP"
    fi
    # okienko z postępem instalacji PySide6 (tkinter z wbudowanego Pythona); kod 0 = gotowe
    if ! "$PY" "$INTERNAL/tools/macos/bootstrap.py" "$OK"; then
        exit 1
    fi
fi
[ "${WYKLADY_BOOTSTRAP_ONLY:-}" = "1" ] && exit 0      # test w GitHub Actions: tylko Python + PySide6

cd "$INTERNAL" || exit 1
HOST="$HERE/WykladyHost"
LIBPY="$(ls "$RUNTIME"/python/lib/libpython3.*.dylib 2>/dev/null | head -n 1)"
if [ -x "$HOST" ] && [ -n "$LIBPY" ] &&    WYKLADY_LIBPYTHON="$LIBPY" PYTHONEXECUTABLE="$PY" "$HOST" -c "import encodings, ctypes" >/dev/null 2>&1; then
    export WYKLADY_LIBPYTHON="$LIBPY" PYTHONEXECUTABLE="$PY"
    exec "$HOST" "$INTERNAL/main.py" "$@"
fi
exec "$PY" "$INTERNAL/main.py" "$@"
