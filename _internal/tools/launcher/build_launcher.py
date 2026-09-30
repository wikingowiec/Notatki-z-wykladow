"""Buduje Wykłady.exe (program startowy) – działa na Linuksie, macOS i Windowsie dzięki kompilatorowi zig.

    pip install ziglang
    python _internal/tools/launcher/build_launcher.py
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTERNAL = HERE.parents[1]
ROOT = INTERNAL.parent


def main():
    ver = re.search(r'VERSION\s*=\s*"([\d.]+)"', (INTERNAL / "app" / "version.py").read_text(encoding="utf-8")).group(1)
    nums = (ver.split(".") + ["0", "0", "0", "0"])[:4]
    build = HERE / "build"
    build.mkdir(exist_ok=True)
    shutil.copy(INTERNAL / "icon.ico", build / "icon.ico")
    shutil.copy(HERE / "launcher.manifest", build / "launcher.manifest")
    rc = f'''#pragma code_page(65001)
#include <windows.h>
1 ICON "icon.ico"
1 24 "launcher.manifest"
VS_VERSION_INFO VERSIONINFO
FILEVERSION {",".join(nums)}
PRODUCTVERSION {",".join(nums)}
FILEOS VOS_NT_WINDOWS32
FILETYPE VFT_APP
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "041504B0"
    BEGIN
      VALUE "CompanyName", "Wyklady"
      VALUE "FileDescription", "Wykłady"
      VALUE "FileVersion", "{ver}"
      VALUE "InternalName", "Wyklady"
      VALUE "OriginalFilename", "Wyklady.exe"
      VALUE "ProductName", "Wykłady"
      VALUE "ProductVersion", "{ver}"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0415, 1200
  END
END
'''
    (build / "launcher.rc").write_text(rc, encoding="utf-8")
    shutil.copy(HERE / "launcher.c", build / "launcher.c")
    out = ROOT / "Wykłady.exe"
    cmd = [sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-municode", "-Os", "-s",
           "launcher.c", "launcher.rc", "-o", str(out), "-Wl,--subsystem,windows",
           "-lwininet", "-lgdi32", "-luser32", "-lshell32", "-ldwmapi"]
    subprocess.run(cmd, cwd=build, check=True)
    for f in ROOT.glob("Wykłady.pdb"):
        f.unlink()
    shutil.rmtree(build, ignore_errors=True)
    print("OK:", out, out.stat().st_size, "B")


if __name__ == "__main__":
    main()
