// Wykłady.app/Contents/MacOS/WykladyHost – uruchamia wbudowany Python w tym samym procesie.
// Nowe w wersji 2.2.0.
//
// Po co: macOS przypisuje zgody (mikrofon, dźwięk systemu, nagrywanie ekranu) do programu, który działa w procesie.
// Gdy launcher.sh robi „exec python3”, procesem staje się python3 spoza paczki – bez Info.plist z opisami próśb
// (macOS może wtedy zamknąć program przy pierwszym użyciu mikrofonu) i z nazwą „python3” w Ustawieniach.
// Ten program leży w Wykłady.app, więc zgody dostaje „Wykłady”, a Dock i pasek menu dalej pokazują Wykłady.
//
// launcher.sh ustawia:
//   WYKLADY_LIBPYTHON  – pełna ścieżka do libpython3.x.dylib z runtime
//   PYTHONEXECUTABLE   – prawdziwy python3 (sys.executable i ścieżki biblioteki standardowej liczą się od niego)
// Argumenty jak dla python3, np. „WykladyHost …/main.py --debug”.
//
// Budowanie (build_app.sh): clang -O2 -o WykladyHost host.c   (linker sam podpisuje ad hoc – wymagane na arm64)
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    const char *lib = getenv("WYKLADY_LIBPYTHON");
    if (lib == NULL || *lib == '\0') {
        fprintf(stderr, "WykladyHost: brak zmiennej WYKLADY_LIBPYTHON\n");
        return 127;
    }
    // RTLD_GLOBAL: moduły rozszerzeń (.so) szukają symboli Pythona w przestrzeni globalnej
    void *handle = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
    if (handle == NULL) {
        fprintf(stderr, "WykladyHost: %s\n", dlerror());
        return 127;
    }
    int (*py_main)(int, char **) = (int (*)(int, char **))dlsym(handle, "Py_BytesMain");
    if (py_main == NULL) {
        fprintf(stderr, "WykladyHost: brak Py_BytesMain w %s\n", lib);
        return 127;
    }
    return py_main(argc, argv);
}
