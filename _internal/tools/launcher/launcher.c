/*
 * Wykłady.exe – program startowy (bez okna konsoli).
 *
 *  - Zwykłe uruchomienie: odpala _internal\runtime\python\pythonw.exe _internal\main.py i znika.
 *    Jeśli aplikacja nie pokaże okna w ~0,4 s, na chwilę pojawia się małe okienko „Otwieranie…”.
 *  - Pierwsze uruchomienie (brak wbudowanego Pythona): małe okno z postępem – pobiera Pythona (wersja
 *    „embeddable” z python.org), pip i bibliotekę okienek (PySide6). Dalszą część instalacji (biblioteki,
 *    modele AI) pokazuje już ekran z notesem w samej aplikacji.
 *  - „Wykłady.exe --debug” uruchamia aplikację z konsolą (do diagnozy).
 *
 * Kompilacja (dowolny system, przez zig):
 *   python -m ziglang cc -target x86_64-windows-gnu -municode -Os launcher.c launcher.rc -o Wykłady.exe
 *       -Wl,--subsystem,windows -lwininet -lgdi32 -luser32 -lshell32 -ldwmapi
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wininet.h>
#include <shellapi.h>
#include <dwmapi.h>
#include <stdio.h>
#include <wchar.h>

#define PY_URL   L"https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
#define PIP_URL  L"https://bootstrap.pypa.io/get-pip.py"
#define WM_STAGE_DONE (WM_APP + 1)

static wchar_t g_dir[MAX_PATH], g_internal[MAX_PATH], g_runtime[MAX_PATH], g_pydir[MAX_PATH];
static wchar_t g_pyw[MAX_PATH], g_py[MAX_PATH], g_main[MAX_PATH], g_ok[MAX_PATH], g_dl[MAX_PATH];
static HWND g_hwnd;
static volatile double g_progress = 0.0, g_target = 0.0;
static wchar_t g_status[512] = L"Przygotowuję…";
static wchar_t g_error[1024] = L"";
static volatile int g_mode = 0;            /* 0 = instalacja, 1 = otwieranie */
static HANDLE g_child = NULL;
static DWORD g_child_pid = 0;
static HFONT g_ftitle, g_ftext, g_fbig, g_fsmall;
static HICON g_icon;
static int g_dpi = 96;
static volatile LONG g_cancel = 0;
static HANDLE g_proc_running = NULL;

static int S(int v) { return MulDiv(v, g_dpi, 96); }

static BOOL exists(const wchar_t *p) { return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES; }

static void set_status(const wchar_t *s) {
    lstrcpynW(g_status, s, 511);
    if (g_hwnd) InvalidateRect(g_hwnd, NULL, FALSE);
}

/* ------------------------------------------------------------------ pobieranie (WinINet) */
static BOOL download(const wchar_t *url, const wchar_t *dest, double p0, double p1, const wchar_t *label) {
    HINTERNET net = InternetOpenW(L"Wyklady", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    if (!net) { swprintf(g_error, 1024, L"Brak dostępu do internetu (%lu).", GetLastError()); return FALSE; }
    HINTERNET h = InternetOpenUrlW(net, url, NULL, 0,
                                   INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_SECURE, 0);
    if (!h) {
        swprintf(g_error, 1024, L"Nie udało się połączyć z serwerem (%lu).\nSprawdź połączenie z internetem.", GetLastError());
        InternetCloseHandle(net);
        return FALSE;
    }
    DWORD total = 0, sz = sizeof(total), idx = 0;
    HttpQueryInfoW(h, HTTP_QUERY_CONTENT_LENGTH | HTTP_QUERY_FLAG_NUMBER, &total, &sz, &idx);
    HANDLE f = CreateFileW(dest, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) {
        swprintf(g_error, 1024, L"Nie można zapisać pliku w folderze aplikacji (%lu).", GetLastError());
        InternetCloseHandle(h); InternetCloseHandle(net);
        return FALSE;
    }
    static BYTE buf[1 << 16];
    DWORD got = 0, done = 0, wr;
    BOOL ok = TRUE;
    while (InternetReadFile(h, buf, sizeof(buf), &got) && got > 0) {
        if (g_cancel) { ok = FALSE; break; }
        if (!WriteFile(f, buf, got, &wr, NULL)) { ok = FALSE; break; }
        done += got;
        if (total) {
            g_target = g_progress = p0 + (p1 - p0) * ((double)done / total);
            wchar_t s[256];
            swprintf(s, 256, L"%ls · %.1f z %.1f MB", label, done / 1e6, total / 1e6);
            set_status(s);
        }
    }
    CloseHandle(f);
    InternetCloseHandle(h);
    InternetCloseHandle(net);
    if (ok && done < 1000) { ok = FALSE; }
    if (!ok && !g_error[0]) lstrcpyW(g_error, L"Pobieranie zostało przerwane. Sprawdź połączenie z internetem.");
    return ok;
}

/* ------------------------------------------------------------------ procesy bez okna */
static BOOL run_hidden(const wchar_t *cmdline, double p_end, const wchar_t *what) {
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    wchar_t cmd[4096];
    lstrcpynW(cmd, cmdline, 4096);
    g_target = p_end;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, g_runtime, &si, &pi)) {
        swprintf(g_error, 1024, L"%ls – nie udało się uruchomić (%lu).", what, GetLastError());
        return FALSE;
    }
    g_proc_running = pi.hProcess;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    g_proc_running = NULL;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (g_cancel) return FALSE;
    if (code != 0) {
        swprintf(g_error, 1024, L"%ls – błąd (kod %lu).\nSprawdź połączenie z internetem i uruchom ponownie.", what, code);
        return FALSE;
    }
    g_progress = p_end;
    return TRUE;
}

static BOOL write_pth(void) {
    WIN32_FIND_DATAW fd;
    wchar_t pat[MAX_PATH], path[MAX_PATH];
    swprintf(pat, MAX_PATH, L"%ls\\python*._pth", g_pydir);
    HANDLE fh = FindFirstFileW(pat, &fd);
    if (fh == INVALID_HANDLE_VALUE) { lstrcpyW(g_error, L"Nie znaleziono pliku ._pth w pobranym Pythonie."); return FALSE; }
    FindClose(fh);
    swprintf(path, MAX_PATH, L"%ls\\%ls", g_pydir, fd.cFileName);
    /* nazwa archiwum biblioteki standardowej: python312._pth -> python312.zip */
    char zipname[64] = {0};
    WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1, zipname, sizeof(zipname), NULL, NULL);
    char *dot = strrchr(zipname, '.');
    if (dot) strcpy(dot, ".zip");
    char content[512];
    snprintf(content, sizeof(content), "%s\r\n.\r\nLib\\site-packages\r\n..\\..\r\nimport site\r\n", zipname);
    HANDLE f = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) { lstrcpyW(g_error, L"Nie można zapisać ustawień Pythona."); return FALSE; }
    DWORD wr;
    WriteFile(f, content, (DWORD)strlen(content), &wr, NULL);
    CloseHandle(f);
    return TRUE;
}

static void rmtree_dl(void) {
    wchar_t p[MAX_PATH];
    swprintf(p, MAX_PATH, L"%ls\\python.zip", g_dl); DeleteFileW(p);
    swprintf(p, MAX_PATH, L"%ls\\get-pip.py", g_dl); DeleteFileW(p);
    RemoveDirectoryW(g_dl);
}

static DWORD WINAPI stage1(LPVOID arg) {
    (void)arg;
    wchar_t zip[MAX_PATH], getpip[MAX_PATH], cmd[4096], sys32[MAX_PATH];
    BOOL ok = FALSE;
    CreateDirectoryW(g_runtime, NULL);
    CreateDirectoryW(g_pydir, NULL);
    CreateDirectoryW(g_dl, NULL);
    swprintf(zip, MAX_PATH, L"%ls\\python.zip", g_dl);
    swprintf(getpip, MAX_PATH, L"%ls\\get-pip.py", g_dl);
    GetSystemDirectoryW(sys32, MAX_PATH);
    do {
        if (!exists(g_py)) {
            set_status(L"Pobieram Pythona");
            if (!download(PY_URL, zip, 0.02, 0.24, L"Pobieram Pythona")) break;
            set_status(L"Rozpakowuję…");
            swprintf(cmd, 4096, L"\"%ls\\tar.exe\" -xf \"%ls\" -C \"%ls\"", sys32, zip, g_pydir);
            if (!run_hidden(cmd, 0.28, L"Rozpakowywanie")) {
                g_error[0] = 0;       /* starszy Windows bez tar.exe – PowerShell */
                swprintf(cmd, 4096, L"powershell -NoProfile -WindowStyle Hidden -Command \"Expand-Archive -Force "
                         L"-LiteralPath '%ls' -DestinationPath '%ls'\"", zip, g_pydir);
                if (!run_hidden(cmd, 0.28, L"Rozpakowywanie")) break;
            }
        }
        if (!write_pth()) break;
        swprintf(cmd, 4096, L"\"%ls\" -c \"import pip\"", g_py);
        {
            STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi; DWORD code = 1;
            if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, g_runtime, &si, &pi)) {
                WaitForSingleObject(pi.hProcess, INFINITE); GetExitCodeProcess(pi.hProcess, &code);
                CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
            }
            if (code != 0) {
                if (!download(PIP_URL, getpip, 0.28, 0.32, L"Pobieram instalator pakietów")) break;
                set_status(L"Instaluję menedżer pakietów (pip)…");
                swprintf(cmd, 4096, L"\"%ls\" \"%ls\" --no-warn-script-location --disable-pip-version-check", g_py, getpip);
                if (!run_hidden(cmd, 0.45, L"Instalacja pip")) break;
            }
        }
        set_status(L"Pobieram bibliotekę okien (PySide6, ok. 80 MB)…");
        swprintf(cmd, 4096, L"\"%ls\" -m pip install --no-warn-script-location --disable-pip-version-check "
                 L"PySide6-Essentials", g_py);
        if (!run_hidden(cmd, 0.97, L"Instalacja PySide6")) break;
        HANDLE f = CreateFileW(g_ok, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (f != INVALID_HANDLE_VALUE) CloseHandle(f);
        rmtree_dl();
        g_target = g_progress = 1.0;
        set_status(L"Gotowe – otwieram aplikację…");
        ok = TRUE;
    } while (0);
    PostMessageW(g_hwnd, WM_STAGE_DONE, ok, 0);
    return 0;
}

/* ------------------------------------------------------------------ uruchomienie aplikacji */
static BOOL launch_app(BOOL debug, const wchar_t *extra) {
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    wchar_t cmd[4096];
    swprintf(cmd, 4096, L"\"%ls\" \"%ls\" %ls", debug ? g_py : g_pyw, g_main, extra ? extra : L"");
    AllowSetForegroundWindow(ASFW_ANY);
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, debug ? CREATE_NEW_CONSOLE : 0, NULL, g_internal, &si, &pi)) {
        wchar_t msg[1024];
        swprintf(msg, 1024, L"Nie udało się uruchomić aplikacji (%lu).\n\n%ls", GetLastError(), cmd);
        MessageBoxW(NULL, msg, L"Wykłady", MB_ICONERROR);
        return FALSE;
    }
    g_child = pi.hProcess;
    g_child_pid = pi.dwProcessId;
    CloseHandle(pi.hThread);
    return TRUE;
}

static BOOL CALLBACK find_child_window(HWND w, LPARAM lp) {
    DWORD pid = 0;
    GetWindowThreadProcessId(w, &pid);
    if (pid == g_child_pid && IsWindowVisible(w) && GetWindow(w, GW_OWNER) == NULL) {
        *(BOOL *)lp = TRUE;
        return FALSE;
    }
    return TRUE;
}

static BOOL child_has_window(void) {
    BOOL found = FALSE;
    EnumWindows(find_child_window, (LPARAM)&found);
    return found;
}

/* ------------------------------------------------------------------ okno postępu (GDI) */
static void fill_round(HDC dc, RECT r, int rad, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c);
    HPEN pen = CreatePen(PS_SOLID, 1, c);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, pen);
    RoundRect(dc, r.left, r.top, r.right, r.bottom, rad, rad);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(b); DeleteObject(pen);
}

static void paint(HWND w) {
    PAINTSTRUCT ps;
    HDC wdc = BeginPaint(w, &ps);
    RECT rc; GetClientRect(w, &rc);
    HDC dc = CreateCompatibleDC(wdc);
    HBITMAP bmp = CreateCompatibleBitmap(wdc, rc.right, rc.bottom);
    HGDIOBJ obmp = SelectObject(dc, bmp);
    COLORREF paper = RGB(0xF6, 0xF3, 0xEC), ink = RGB(0x1F, 0x1D, 0x1A), ink2 = RGB(0x6B, 0x65, 0x5B);
    COLORREF accent = RGB(0x2F, 0x6B, 0x55), track = RGB(0xE9, 0xE3, 0xD7), red = RGB(0xD2, 0x45, 0x2F);
    HBRUSH bg = CreateSolidBrush(paper);
    FillRect(dc, &rc, bg);
    DeleteObject(bg);
    SetBkMode(dc, TRANSPARENT);
    int pad = S(28);
    if (g_icon) DrawIconEx(dc, pad, pad, g_icon, S(40), S(40), 0, NULL, DI_NORMAL);
    SelectObject(dc, g_ftitle);
    SetTextColor(dc, ink);
    RECT t = { pad + S(52), pad - S(4), rc.right - pad, pad + S(30) };
    DrawTextW(dc, L"Wykłady", -1, &t, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    SelectObject(dc, g_ftext);
    SetTextColor(dc, ink2);
    RECT t2 = { pad + S(52), pad + S(26), rc.right - pad, pad + S(48) };
    DrawTextW(dc, g_mode ? L"Otwieranie…" : L"Pierwsze uruchomienie – przygotowuję aplikację", -1, &t2,
              DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS);
    /* zamknij */
    if (!g_mode) {
        SelectObject(dc, g_ftext);
        RECT x = { rc.right - S(40), S(10), rc.right - S(10), S(40) };
        DrawTextW(dc, L"\u00D7", -1, &x, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    }
    if (!g_mode) {
        wchar_t pct[16];
        swprintf(pct, 16, L"%d%%", (int)(g_progress * 100 + 0.5));
        SelectObject(dc, g_fbig);
        SetTextColor(dc, ink);
        RECT b = { pad, S(92), rc.right - pad, S(170) };
        DrawTextW(dc, pct, -1, &b, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
        SelectObject(dc, g_ftext);
        SetTextColor(dc, g_error[0] ? red : ink2);
        RECT st = { pad, S(172), rc.right - pad, rc.bottom - S(62) };
        DrawTextW(dc, g_error[0] ? g_error : g_status, -1, &st, DT_LEFT | DT_WORDBREAK | DT_END_ELLIPSIS);
        RECT tr = { pad, rc.bottom - S(52), rc.right - pad, rc.bottom - S(46) };
        fill_round(dc, tr, S(6), track);
        RECT fr = tr;
        fr.right = tr.left + (LONG)((tr.right - tr.left) * g_progress);
        if (fr.right > fr.left + S(6)) fill_round(dc, fr, S(6), g_error[0] ? red : accent);
        SelectObject(dc, g_fsmall);
        SetTextColor(dc, ink2);
        RECT h = { pad, rc.bottom - S(38), rc.right - pad, rc.bottom - S(14) };
        DrawTextW(dc, L"Potem otworzy się ekran instalacji bibliotek i modeli AI.", -1, &h,
                  DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS);
    } else {
        /* otwieranie: trzy kropki */
        int n = (GetTickCount() / 300) % 4;
        for (int i = 0; i < 3; i++) {
            RECT d = { pad + S(52) + i * S(14), S(96), pad + S(52) + i * S(14) + S(8), S(104) };
            fill_round(dc, d, S(8), i < n ? accent : track);
        }
    }
    BitBlt(wdc, 0, 0, rc.right, rc.bottom, dc, 0, 0, SRCCOPY);
    SelectObject(dc, obmp);
    DeleteObject(bmp);
    DeleteDC(dc);
    EndPaint(w, &ps);
}

static LRESULT CALLBACK wndproc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_PAINT: paint(w); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_TIMER:
        if (wp == 2) { DestroyWindow(w); return 0; }
        if (g_progress < g_target) g_progress += (g_target - g_progress) * 0.004 + 0.0002;
        if (g_mode && g_child) {
            if (child_has_window() || WaitForSingleObject(g_child, 0) == WAIT_OBJECT_0) DestroyWindow(w);
        }
        InvalidateRect(w, NULL, FALSE);
        return 0;
    case WM_NCHITTEST: {
        LRESULT hit = DefWindowProcW(w, m, wp, lp);
        if (hit == HTCLIENT) {
            POINT pt = { (short)LOWORD(lp), (short)HIWORD(lp) };
            ScreenToClient(w, &pt);
            RECT rc; GetClientRect(w, &rc);
            if (!(pt.x > rc.right - S(44) && pt.y < S(44))) return HTCAPTION;
        }
        return hit;
    }
    case WM_LBUTTONUP:
        if (!g_mode && MessageBoxW(w, L"Przerwać przygotowanie aplikacji? Dokończy się przy następnym uruchomieniu.",
                                   L"Wykłady", MB_YESNO | MB_ICONQUESTION) == IDYES) {
            InterlockedExchange(&g_cancel, 1);
            if (g_proc_running) TerminateProcess(g_proc_running, 1);
            ExitProcess(1);
        }
        return 0;
    case WM_STAGE_DONE:
        if (wp) {
            if (launch_app(FALSE, L"")) { g_mode = 1; }
            else DestroyWindow(w);
        } else if (!g_cancel) {
            wchar_t msg[1400];
            swprintf(msg, 1400, L"Nie udało się przygotować aplikacji.\n\n%ls\n\nUruchom Wykłady ponownie – "
                     L"przygotowanie zacznie się od miejsca, w którym przerwało.", g_error);
            MessageBoxW(w, msg, L"Wykłady", MB_ICONWARNING);
            DestroyWindow(w);
        }
        return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(w, m, wp, lp);
}

static HFONT mkfont(const wchar_t *face, int px, int weight, BOOL italic) {
    return CreateFontW(-S(px), 0, 0, 0, weight, italic, 0, 0, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                       CLEARTYPE_QUALITY, DEFAULT_PITCH, face);
}

static void make_window(HINSTANCE inst, int mode) {
    g_mode = mode;
    typedef BOOL(WINAPI * SetCtx)(HANDLE);
    SetCtx f = (SetCtx)GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetProcessDpiAwarenessContext");
    if (f) f((HANDLE)-4);            /* PER_MONITOR_AWARE_V2 */
    HDC sdc = GetDC(NULL);
    g_dpi = GetDeviceCaps(sdc, LOGPIXELSX);
    ReleaseDC(NULL, sdc);
    wchar_t font[MAX_PATH];
    swprintf(font, MAX_PATH, L"%ls\\app\\ui\\fonts\\Fraunces-SemiBold.ttf", g_internal);
    BOOL fr = AddFontResourceExW(font, FR_PRIVATE, 0) > 0;
    swprintf(font, MAX_PATH, L"%ls\\app\\ui\\fonts\\Inter-Regular.ttf", g_internal);
    BOOL fi = AddFontResourceExW(font, FR_PRIVATE, 0) > 0;
    g_ftitle = mkfont(fr ? L"Fraunces SemiBold" : L"Georgia", 26, fr ? FW_NORMAL : FW_BOLD, FALSE);
    g_fbig = mkfont(fr ? L"Fraunces SemiBold" : L"Georgia", 64, fr ? FW_NORMAL : FW_BOLD, FALSE);
    g_ftext = mkfont(fi ? L"Inter" : L"Segoe UI", 15, FW_NORMAL, FALSE);
    g_fsmall = mkfont(fi ? L"Inter" : L"Segoe UI", 12, FW_NORMAL, FALSE);
    g_icon = (HICON)LoadImageW(inst, MAKEINTRESOURCEW(1), IMAGE_ICON, S(40), S(40), LR_DEFAULTCOLOR);

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(1));
    wc.lpszClassName = L"WykladyStart";
    RegisterClassW(&wc);
    int ww = S(mode ? 360 : 540), wh = S(mode ? 140 : 330);
    RECT wa;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &wa, 0);
    int x = wa.left + (wa.right - wa.left - ww) / 2, y = wa.top + (wa.bottom - wa.top - wh) / 2;
    g_hwnd = CreateWindowExW(mode ? WS_EX_TOOLWINDOW : 0, wc.lpszClassName, L"Wykłady", WS_POPUP, x, y, ww, wh,
                             NULL, NULL, inst, NULL);
    int corner = 2;                  /* DWMWCP_ROUND (Windows 11) */
    DwmSetWindowAttribute(g_hwnd, 33, &corner, sizeof(corner));
    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);
    SetTimer(g_hwnd, 1, 33, NULL);
}

static void message_loop(void) {
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)prev; (void)show;
    GetModuleFileNameW(NULL, g_dir, MAX_PATH);
    wchar_t old[MAX_PATH + 8];
    swprintf(old, MAX_PATH + 8, L"%ls.old", g_dir);          /* po aktualizacji */
    DeleteFileW(old);
    wchar_t *slash = wcsrchr(g_dir, L'\\');
    if (slash) *slash = 0;
    swprintf(g_internal, MAX_PATH, L"%ls\\_internal", g_dir);
    swprintf(g_runtime, MAX_PATH, L"%ls\\runtime", g_internal);
    swprintf(g_pydir, MAX_PATH, L"%ls\\python", g_runtime);
    swprintf(g_pyw, MAX_PATH, L"%ls\\pythonw.exe", g_pydir);
    swprintf(g_py, MAX_PATH, L"%ls\\python.exe", g_pydir);
    swprintf(g_main, MAX_PATH, L"%ls\\main.py", g_internal);
    swprintf(g_ok, MAX_PATH, L"%ls\\stage1.ok", g_runtime);
    swprintf(g_dl, MAX_PATH, L"%ls\\pobrane", g_runtime);

    if (!exists(g_main)) {
        MessageBoxW(NULL, L"Brakuje plików aplikacji (folder _internal).\n\nRozpakuj całe archiwum z aplikacją "
                    L"i uruchom Wykłady.exe z rozpakowanego folderu.", L"Wykłady", MB_ICONERROR);
        return 1;
    }
    BOOL debug = cmdline && wcsstr(cmdline, L"--debug") != NULL;

    if (exists(g_pyw) && exists(g_ok)) {
        if (!launch_app(debug, cmdline)) return 1;
        if (debug) return 0;
        /* szybki start – bez okienka; wolny – „Otwieranie…” do czasu pojawienia się okna aplikacji */
        for (int i = 0; i < 8; i++) {
            if (child_has_window() || WaitForSingleObject(g_child, 50) == WAIT_OBJECT_0) return 0;
        }
        make_window(inst, 1);
        SetTimer(g_hwnd, 2, 30000, NULL);         /* awaryjnie – nie wisi w nieskończoność */
        message_loop();
        return 0;
    }
    make_window(inst, 0);
    CreateThread(NULL, 0, stage1, NULL, 0, NULL);
    message_loop();
    return 0;
}
