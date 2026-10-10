#!/bin/bash
# Buduje Wykłady.app (bez Pythona i bibliotek – pobierają się przy pierwszym uruchomieniu).
# Nowe w wersji 2.2.0.
#
#   bash _internal/tools/macos/build_app.sh dist      → dist/Wykłady.app
#
# Wymaga macOS (sips, iconutil, plutil, clang). Ikona .icns powstaje z _internal/icon.ico – przez Pillow, jeśli jest
# (python3 -c "import PIL"), inaczej przez sips.
#
# Układ paczki:
#   Wykłady.app/Contents/Info.plist
#   Wykłady.app/Contents/MacOS/Wyklady               ← launcher.sh
#   Wykłady.app/Contents/MacOS/WykladyHost           ← host.c (Python w procesie Wykłady.app – zgody macOS)
#   Wykłady.app/Contents/Resources/icon.icns
#   Wykłady.app/Contents/Resources/_internal/...     ← main.py, app/, requirements-mac.txt, tools/macos/bootstrap.py
set -euo pipefail

OUT="${1:-dist}"
HERE="$(cd "$(dirname "$0")" && pwd)"
INTERNAL="$(cd "$HERE/../.." && pwd)"
ROOT="$(cd "$INTERNAL/.." && pwd)"
VER="$(sed -nE 's/^VERSION *= *"([^"]+)".*/\1/p' "$INTERNAL/app/version.py")"
[ -n "$VER" ] || { echo "Brak VERSION w _internal/app/version.py" >&2; exit 1; }

mkdir -p "$OUT"
APP="$OUT/Wykłady.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 1. program startowy
cp "$HERE/launcher.sh" "$APP/Contents/MacOS/Wyklady"
chmod 755 "$APP/Contents/MacOS/Wyklady"
# Python uruchamiany w procesie z paczki: zgody (mikrofon, dźwięk systemu, ekran) dostaje „Wykłady”.
# Linker podpisuje plik ad hoc (wymagane na arm64) – to nie jest podpis całej paczki, aktualizator dalej działa.
clang -O2 -arch arm64 -mmacosx-version-min=12.0 -o "$APP/Contents/MacOS/WykladyHost" "$HERE/host.c"
chmod 755 "$APP/Contents/MacOS/WykladyHost"

# 2. pliki aplikacji (bez runtime, pamięci podręcznej Pythona i programu startowego Windows)
rsync -a --exclude 'runtime/' --exclude '__pycache__/' --exclude '*.pyc' --exclude 'tools/launcher/' \
    "$INTERNAL/" "$APP/Contents/Resources/_internal/"
cp "$ROOT/README.md" "$APP/Contents/Resources/README.md" 2>/dev/null || true

# 3. ikona z icon.ico
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ICONSET="$TMP/icon.iconset"
mkdir -p "$ICONSET"
if python3 -c "import PIL" 2>/dev/null; then
    python3 - "$INTERNAL/icon.ico" "$ICONSET" <<'EOF'
import sys
from PIL import Image
ico = Image.open(sys.argv[1])
big = max(ico.info.get("sizes") or [ico.size])
ico.size = big                       # największy obraz z pliku .ico
src = ico.convert("RGBA")
for s in (16, 32, 128, 256, 512):
    for scale, suffix in ((1, ""), (2, "@2x")):
        px = s * scale
        src.resize((px, px), Image.LANCZOS).save(f"{sys.argv[2]}/icon_{s}x{s}{suffix}.png")
EOF
else
    sips -s format png "$INTERNAL/icon.ico" --out "$TMP/icon.png" >/dev/null
    for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
fi
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns"

# 4. Info.plist
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>                <string>Wykłady</string>
    <key>CFBundleDisplayName</key>         <string>Wykłady</string>
    <key>CFBundleIdentifier</key>          <string>pl.wystrychowski.wyklady</string>
    <key>CFBundleExecutable</key>          <string>Wyklady</string>
    <key>CFBundleIconFile</key>            <string>icon</string>
    <key>CFBundlePackageType</key>         <string>APPL</string>
    <key>CFBundleShortVersionString</key>  <string>$VER</string>
    <key>CFBundleVersion</key>             <string>$VER</string>
    <key>CFBundleDevelopmentRegion</key>   <string>pl</string>
    <key>LSMinimumSystemVersion</key>      <string>12.0</string>
    <key>LSApplicationCategoryType</key>   <string>public.app-category.education</string>
    <key>NSHighResolutionCapable</key>     <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key> <true/>
    <key>NSDocumentsFolderUsageDescription</key>
    <string>Wykłady zapisują nagrania i notatki w folderze Dokumenty/Wykłady.</string>
    <key>NSDownloadsFolderUsageDescription</key>
    <string>Wykłady otwierają nagrania i zdjęcia slajdów, które wybierzesz.</string>
    <key>NSDesktopFolderUsageDescription</key>
    <string>Wykłady otwierają nagrania i zdjęcia slajdów, które wybierzesz.</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Wykłady nagrywają mikrofon w trakcie nagrywania wykładu na sali. Dźwięk zostaje na tym Macu.</string>
    <key>NSAudioCaptureUsageDescription</key>
    <string>Wykłady nagrywają dźwięk wybranej aplikacji (np. Teams, Zoom, przeglądarka), żeby zrobić transkrypcję i notatki. Dźwięk zostaje na tym Macu.</string>
    <key>NSScreenCaptureUsageDescription</key>
    <string>Wykłady robią zrzuty wybranego ekranu albo okna, żeby złapać slajdy z wykładu. Obraz zostaje na tym Macu.</string>
</dict>
</plist>
EOF
plutil -lint "$APP/Contents/Info.plist" >/dev/null

# 5. bez atrybutów z budowania. Celowo BEZ podpisu (nawet „ad hoc”): program startowy to skrypt, a aktualizator
#    podmienia pliki w paczce – naruszony podpis dawałby komunikat „aplikacja jest uszkodzona”.
xattr -cr "$APP" 2>/dev/null || true

echo "Zbudowano $APP (wersja $VER)"
