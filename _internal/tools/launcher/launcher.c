/*
 * Wykłady.exe – program startowy (bez okna konsoli).
 *
 *  - Zwykłe uruchomienie: odpala runtime\python\pythonw.exe _internal\main.py i znika.
 *    Jeśli aplikacja nie pokaże okna w ~0,4 s, na chwilę pojawia się małe okienko „Otwieranie…”.
 *  - Pierwsze uruchomienie (brak wbudowanego Pythona): małe okno z postępem – pobiera Pythona (wersja
 *    „embeddable” z python.org, sprawdzana rozmiarem, nagłówkiem „PK” i SHA-256), rozpakowuje go sam (miniz),
 *    instaluje pip i bibliotekę okienek (PySide6). Dalszą część instalacji (biblioteki, modele AI) pokazuje już
 *    ekran z notesem w samej aplikacji.
 *  - Każdy krok, kod wyjścia i wyjście procesów potomnych trafia do runtime\launcher.log. Przy błędzie okno ma
 *    przyciski „Otwórz log” i „Kopiuj szczegóły”.
 *  - „Wykłady.exe --debug” uruchamia aplikację z konsolą (do diagnozy).
 *  - Teksty po polsku albo po angielsku – jak interfejs aplikacji (detect_english).
 *  - Wersja z Microsoft Store (paczka MSIX „SlideScribe”, folder instalacji tylko do odczytu): Python, biblioteki
 *    i ustawienia w prywatnym folderze paczki (zob. store_paths), nazwa w okienkach „SlideScribe”.
 *
 * Kompilacja: python _internal/tools/launcher/build_launcher.py (zig cc, działa na każdym systemie).
 * miniz.c / miniz.h – biblioteka ZIP/deflate (MIT, github.com/richgel999/miniz 3.0.2), licencja w miniz-LICENSE.txt.
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
#include <shlobj.h>
#include <dwmapi.h>
#include <bcrypt.h>
#include <winioctl.h>
#include <objbase.h>
#include <stdio.h>
#include <stdarg.h>
#include <wchar.h>

#define MINIZ_NO_STDIO
#define MINIZ_NO_TIME
#define MINIZ_NO_ARCHIVE_WRITING_APIS
#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.c"

#ifndef APP_VERSION
#define APP_VERSION "?"
#endif

#define PY_URL   L"https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
#define PY_SIZE  11133606ULL           /* python.org: MD5 fe8ef205f2e9c3ba44d0cf9954e1abd3 */
#define PY_SHA256 "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
#define PIP_URL  L"https://bootstrap.pypa.io/get-pip.py"
#define WM_STAGE_DONE (WM_APP + 1)
#define TRIES 3

static wchar_t g_dir[MAX_PATH], g_internal[MAX_PATH], g_runtime[MAX_PATH], g_pydir[MAX_PATH], g_data[MAX_PATH];
static wchar_t g_pyw[MAX_PATH], g_py[MAX_PATH], g_main[MAX_PATH], g_ok[MAX_PATH], g_dl[MAX_PATH];
static wchar_t g_logpath[MAX_PATH], g_family[256] = L"", g_pkgfull[256] = L"", g_winver[128] = L"";
static HANDLE g_log = INVALID_HANDLE_VALUE;
static HWND g_hwnd;
static volatile double g_progress = 0.0, g_target = 0.0;
static wchar_t g_status[512] = L"";
static wchar_t g_error[1024] = L"";
static wchar_t g_step[128] = L"";
static wchar_t g_note[1024] = L"";          /* z store_paths – do logu, gdy już jest otwarty */
static volatile int g_mode = 0;            /* 0 = instalacja, 1 = otwieranie */
static volatile int g_failed = 0;          /* okno błędu z przyciskami */
static DWORD g_copied = 0;                 /* kiedy kliknięto „Kopiuj szczegóły” */
static HANDLE g_child = NULL;
static DWORD g_child_pid = 0;
static HFONT g_ftitle, g_ftext, g_fbig, g_fsmall;
static HICON g_icon;
static int g_dpi = 96;
static volatile LONG g_cancel = 0;
static HANDLE g_proc_running = NULL;
static BOOL g_store = FALSE;               /* działa z paczki MSIX (Microsoft Store) */
static BOOL g_en = FALSE;                  /* teksty po angielsku (ustawienie aplikacji albo język Windowsa) */
#define TR(pl, en) (g_en ? (en) : (pl))
static const wchar_t *g_name = L"Wykłady";

static int S(int v) { return MulDiv(v, g_dpi, 96); }

static BOOL exists(const wchar_t *p) { return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES; }

static void set_status(const wchar_t *s) {
    lstrcpynW(g_status, s, 511);
    if (g_hwnd) InvalidateRect(g_hwnd, NULL, FALSE);
}

/* ------------------------------------------------------------------ log (runtime\launcher.log, UTF-8) */
static void log_open(void) {
    SHCreateDirectoryExW(NULL, g_runtime, NULL);
    swprintf(g_logpath, MAX_PATH, L"%ls\\launcher.log", g_runtime);
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (GetFileAttributesExW(g_logpath, GetFileExInfoStandard, &fa) && fa.nFileSizeLow > 1000000) {
        wchar_t old[MAX_PATH + 4];
        swprintf(old, MAX_PATH + 4, L"%ls.1", g_logpath);
        MoveFileExW(g_logpath, old, MOVEFILE_REPLACE_EXISTING);
    }
    /* dziedziczony uchwyt: procesy potomne (tar, python, pip) piszą swoje wyjście prosto do logu */
    SECURITY_ATTRIBUTES sa = { sizeof(sa), NULL, TRUE };
    g_log = CreateFileW(g_logpath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &sa,
                        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}

static void lg(const wchar_t *fmt, ...) {
    if (g_log == INVALID_HANDLE_VALUE) return;
    wchar_t line[3000];
    SYSTEMTIME t;
    GetLocalTime(&t);
    int n = swprintf(line, 3000, L"%04d-%02d-%02d %02d:%02d:%02d  ", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    va_list ap;
    va_start(ap, fmt);
    vswprintf(line + n, 3000 - n - 3, fmt, ap);
    va_end(ap);
    lstrcatW(line, L"\r\n");
    char buf[9000];
    int len = WideCharToMultiByte(CP_UTF8, 0, line, -1, buf, sizeof(buf), NULL, NULL);
    DWORD wr;
    if (len > 1) WriteFile(g_log, buf, len - 1, &wr, NULL);
}

/* błąd do okna i do logu */
static void fail(const wchar_t *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vswprintf(g_error, 1024, fmt, ap);
    va_end(ap);
    lg(L"BŁĄD [%ls]: %ls", g_step, g_error);
}

static void windows_version(void) {
    typedef LONG(WINAPI * RtlGetVer)(OSVERSIONINFOW *);
    RtlGetVer f = (RtlGetVer)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion");
    OSVERSIONINFOW v = { sizeof(v) };
    if (f) f(&v);
    wchar_t disp[32] = L"";
    DWORD ubr = 0, sz = sizeof(disp), sz2 = sizeof(ubr);
    RegGetValueW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"DisplayVersion",
                 RRF_RT_REG_SZ, NULL, disp, &sz);
    RegGetValueW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"UBR",
                 RRF_RT_REG_DWORD, NULL, &ubr, &sz2);
    swprintf(g_winver, 128, L"Windows %lu.%lu.%lu.%lu %ls", v.dwMajorVersion, v.dwMinorVersion, v.dwBuildNumber, ubr, disp);
}

/* ------------------------------------------------------------------ pobieranie (WinINet) */
static BOOL download(const wchar_t *url, const wchar_t *dest, double p0, double p1, const wchar_t *label) {
    lg(L"pobieram %ls -> %ls", url, dest);
    g_target = g_progress = p0;
    HINTERNET net = InternetOpenW(L"Wyklady", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    if (!net) { fail(TR(L"Brak dostępu do internetu (%lu).", L"No internet access (%lu)."), GetLastError()); return FALSE; }
    HINTERNET h = InternetOpenUrlW(net, url, NULL, 0,
                                   INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_SECURE, 0);
    if (!h) {
        fail(TR(L"Nie udało się połączyć z serwerem (%lu).\nSprawdź połączenie z internetem.", L"Couldn't connect to the server (%lu).\nCheck your internet connection."), GetLastError());
        InternetCloseHandle(net);
        return FALSE;
    }
    DWORD status = 0, total = 0, sz = sizeof(DWORD), idx = 0;
    HttpQueryInfoW(h, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &sz, &idx);
    sz = sizeof(DWORD); idx = 0;
    HttpQueryInfoW(h, HTTP_QUERY_CONTENT_LENGTH | HTTP_QUERY_FLAG_NUMBER, &total, &sz, &idx);
    lg(L"  HTTP %lu, rozmiar %lu B", status, total);
    if (status != 200) {
        fail(TR(L"Serwer odpowiedział błędem (HTTP %lu).", L"The server returned an error (HTTP %lu)."), status);
        InternetCloseHandle(h); InternetCloseHandle(net);
        return FALSE;
    }
    HANDLE f = CreateFileW(dest, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) {
        fail(TR(L"Nie można zapisać pliku %ls (%lu).", L"Couldn't save the file %ls (%lu)."), dest, GetLastError());
        InternetCloseHandle(h); InternetCloseHandle(net);
        return FALSE;
    }
    static BYTE buf[1 << 16];
    DWORD got = 0, done = 0, wr;
    BOOL ok = TRUE, read_ok;
    while ((read_ok = InternetReadFile(h, buf, sizeof(buf), &got)) && got > 0) {
        if (g_cancel) { ok = FALSE; break; }
        if (!WriteFile(f, buf, got, &wr, NULL)) { fail(TR(L"Błąd zapisu na dysk (%lu).", L"Disk write error (%lu)."), GetLastError()); ok = FALSE; break; }
        done += got;
        if (total) {
            g_target = g_progress = p0 + (p1 - p0) * ((double)done / total);
            wchar_t s[256];
            swprintf(s, 256, TR(L"%ls · %.1f z %.1f MB", L"%ls · %.1f of %.1f MB"), label, done / 1e6, total / 1e6);
            set_status(s);
        }
    }
    if (ok && !read_ok) lg(L"  przerwane odczytem (%lu)", GetLastError());
    CloseHandle(f);
    InternetCloseHandle(h);
    InternetCloseHandle(net);
    lg(L"  pobrano %lu B", done);
    if (ok && (done < 1000 || (total && done != total))) ok = FALSE;
    if (!ok && !g_error[0]) fail(TR(L"Pobieranie zostało przerwane. Sprawdź połączenie z internetem.", L"The download was interrupted. Check your internet connection."));
    return ok;
}

/* ------------------------------------------------------------------ sprawdzenie pobranego Pythona */
static BOOL sha256_file(const wchar_t *path, char hex[65]) {
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hh = NULL;
    BOOL ok = FALSE;
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return FALSE;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) == 0 &&
        BCryptCreateHash(alg, &hh, NULL, 0, NULL, 0, 0) == 0) {
        static BYTE buf[1 << 16];
        DWORD got;
        while (ReadFile(f, buf, sizeof(buf), &got, NULL) && got > 0) BCryptHashData(hh, buf, got, 0);
        BYTE d[32];
        if (BCryptFinishHash(hh, d, 32, 0) == 0) {
            for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", d[i]);
            ok = TRUE;
        }
    }
    if (hh) BCryptDestroyHash(hh);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    CloseHandle(f);
    return ok;
}

static BOOL verify_python_zip(const wchar_t *zip) {
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (!GetFileAttributesExW(zip, GetFileExInfoStandard, &fa)) { fail(TR(L"Brak pobranego pliku (%lu).", L"The downloaded file is missing (%lu)."), GetLastError()); return FALSE; }
    unsigned long long size = ((unsigned long long)fa.nFileSizeHigh << 32) | fa.nFileSizeLow;
    BYTE head[4] = {0};
    DWORD got = 0;
    HANDLE f = CreateFileW(zip, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) { ReadFile(f, head, 4, &got, NULL); CloseHandle(f); }
    char hex[65] = "";
    sha256_file(zip, hex);
    lg(L"sprawdzam %ls: %llu B, nagłówek %02X %02X %02X %02X, SHA-256 %hs", zip, size, head[0], head[1], head[2], head[3], hex);
    if (size != PY_SIZE) { fail(TR(L"Pobrany plik ma zły rozmiar (%llu B zamiast %llu B).", L"The downloaded file has the wrong size (%llu B instead of %llu B)."), size, PY_SIZE); return FALSE; }
    if (head[0] != 'P' || head[1] != 'K') { fail(TR(L"Pobrany plik nie jest archiwum ZIP.", L"The downloaded file isn't a ZIP archive.")); return FALSE; }
    if (strcmp(hex, PY_SHA256) != 0) { fail(TR(L"Pobrany plik jest uszkodzony (zła suma SHA-256).", L"The downloaded file is damaged (wrong SHA-256).")); return FALSE; }
    return TRUE;
}

/* pobiera python.zip (do 3 prób); plik z poprzedniego, przerwanego uruchomienia używa ponownie, jeśli jest dobry */
static BOOL get_python_zip(const wchar_t *zip) {
    if (exists(zip)) {
        if (verify_python_zip(zip)) { lg(L"python.zip z poprzedniego uruchomienia jest poprawny"); return TRUE; }
        g_error[0] = 0;
        DeleteFileW(zip);
    }
    for (int i = 1; i <= TRIES && !g_cancel; i++) {
        g_error[0] = 0;
        swprintf(g_step, 128, L"pobieranie Pythona, próba %d z %d", i, TRIES);
        if (download(PY_URL, zip, 0.02, 0.24, TR(L"Pobieram Pythona", L"Downloading Python")) && verify_python_zip(zip))
            return TRUE;
        DeleteFileW(zip);
        if (i < TRIES) {
            set_status(TR(L"Ponawiam pobieranie…", L"Retrying the download…"));
            Sleep(1500 * i);
        }
    }
    return FALSE;
}

/* ------------------------------------------------------------------ rozpakowywanie ZIP (miniz, bez programów systemowych) */
static BOOL write_all(const wchar_t *path, const void *data, size_t n) {
    HANDLE f = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return FALSE;
    DWORD wr = 0;
    BOOL ok = n == 0 || (WriteFile(f, data, (DWORD)n, &wr, NULL) && wr == n);
    CloseHandle(f);
    return ok;
}

static BOOL unzip(const wchar_t *zip, const wchar_t *dest) {
    lg(L"rozpakowuję (miniz) %ls -> %ls", zip, dest);
    HANDLE f = CreateFileW(zip, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) { fail(TR(L"Nie można otworzyć %ls (%lu).", L"Couldn't open %ls (%lu)."), zip, GetLastError()); return FALSE; }
    DWORD size = GetFileSize(f, NULL), got = 0;
    void *mem = HeapAlloc(GetProcessHeap(), 0, size ? size : 1);
    BOOL rd = mem && ReadFile(f, mem, size, &got, NULL) && got == size;
    CloseHandle(f);
    if (!rd) { fail(TR(L"Nie można odczytać %ls.", L"Couldn't read %ls."), zip); if (mem) HeapFree(GetProcessHeap(), 0, mem); return FALSE; }
    mz_zip_archive za;
    memset(&za, 0, sizeof(za));
    BOOL ok = FALSE;
    if (!mz_zip_reader_init_mem(&za, mem, size, 0)) {
        fail(TR(L"Archiwum jest uszkodzone (%hs).", L"The archive is damaged (%hs)."), mz_zip_get_error_string(mz_zip_get_last_error(&za)));
        HeapFree(GetProcessHeap(), 0, mem);
        return FALSE;
    }
    mz_uint n = mz_zip_reader_get_num_files(&za), done = 0;
    for (mz_uint i = 0; i < n; i++) {
        char name[512];
        wchar_t wname[512], path[MAX_PATH * 2];
        mz_zip_reader_get_filename(&za, i, name, sizeof(name));
        if (strstr(name, "..") || name[0] == '/' || name[0] == '\\' || strchr(name, ':')) {   /* bez wychodzenia poza folder */
            lg(L"  pomijam podejrzaną ścieżkę: %hs", name);
            continue;
        }
        MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 512);
        for (wchar_t *c = wname; *c; c++) if (*c == L'/') *c = L'\\';
        swprintf(path, MAX_PATH * 2, L"%ls\\%ls", dest, wname);
        if (mz_zip_reader_is_file_a_directory(&za, i)) { SHCreateDirectoryExW(NULL, path, NULL); continue; }
        wchar_t *sl = wcsrchr(path, L'\\');
        if (sl) { *sl = 0; SHCreateDirectoryExW(NULL, path, NULL); *sl = L'\\'; }
        size_t len = 0;
        void *data = mz_zip_reader_extract_to_heap(&za, i, &len, 0);
        if (!data) {
            fail(TR(L"Nie udało się rozpakować %hs (%hs).", L"Couldn't unpack %hs (%hs)."), name, mz_zip_get_error_string(mz_zip_get_last_error(&za)));
            goto out;
        }
        BOOL w = write_all(path, data, len);
        mz_free(data);
        if (!w) { fail(TR(L"Nie można zapisać %ls (%lu).", L"Couldn't write %ls (%lu)."), path, GetLastError()); goto out; }
        done++;
    }
    lg(L"  rozpakowano %u plików", done);
    ok = TRUE;
out:
    mz_zip_reader_end(&za);
    HeapFree(GetProcessHeap(), 0, mem);
    return ok;
}

/* ------------------------------------------------------------------ procesy bez okna (wyjście do logu) */
static BOOL run_logged(const wchar_t *cmdline, DWORD *code) {
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    wchar_t cmd[4096];
    lstrcpynW(cmd, cmdline, 4096);
    lg(L"uruchamiam: %ls", cmd);
    BOOL inherit = g_log != INVALID_HANDLE_VALUE;
    if (inherit) {
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdInput = NULL;
        si.hStdOutput = si.hStdError = g_log;
    }
    *code = 1;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, inherit, CREATE_NO_WINDOW, NULL, g_runtime, &si, &pi)) {
        DWORD e = GetLastError();
        lg(L"  nie udało się uruchomić (%lu)", e);
        SetLastError(e);
        return FALSE;
    }
    g_proc_running = pi.hProcess;
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, code);
    g_proc_running = NULL;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    lg(L"  kod wyjścia: %lu", *code);
    return TRUE;
}

static BOOL run_hidden(const wchar_t *cmdline, double p_end, const wchar_t *what) {
    DWORD code;
    g_target = p_end;
    lstrcpynW(g_step, what, 128);
    if (!run_logged(cmdline, &code)) {
        fail(TR(L"%ls – nie udało się uruchomić (%lu).", L"%ls – couldn't start (%lu)."), what, GetLastError());
        return FALSE;
    }
    if (g_cancel) return FALSE;
    if (code != 0) {
        fail(TR(L"%ls – błąd (kod %lu).\nSzczegóły są w logu.", L"%ls – error (code %lu).\nDetails are in the log."), what, code);
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
    if (fh == INVALID_HANDLE_VALUE) { fail(TR(L"Nie znaleziono pliku ._pth w pobranym Pythonie.", L"No ._pth file found in the downloaded Python.")); return FALSE; }
    FindClose(fh);
    swprintf(path, MAX_PATH, L"%ls\\%ls", g_pydir, fd.cFileName);
    /* nazwa archiwum biblioteki standardowej: python312._pth -> python312.zip */
    char zipname[64] = {0};
    WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1, zipname, sizeof(zipname), NULL, NULL);
    char *dot = strrchr(zipname, '.');
    if (dot) strcpy(dot, ".zip");
    /* ..\.. = _internal w wersji z GitHuba; w wersji ze Store main.py sam dopisuje swój folder do sys.path */
    char content[512];
    snprintf(content, sizeof(content), "%s\r\n.\r\nLib\\site-packages\r\n..\\..\r\nimport site\r\n", zipname);
    if (!write_all(path, content, strlen(content))) { fail(TR(L"Nie można zapisać ustawień Pythona.", L"Couldn't save the Python settings.")); return FALSE; }
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
    DWORD code;
    lg(L"--- pierwsze uruchomienie: przygotowanie Pythona");
    SHCreateDirectoryExW(NULL, g_pydir, NULL);
    SHCreateDirectoryExW(NULL, g_dl, NULL);
    swprintf(zip, MAX_PATH, L"%ls\\python.zip", g_dl);
    swprintf(getpip, MAX_PATH, L"%ls\\get-pip.py", g_dl);
    GetSystemDirectoryW(sys32, MAX_PATH);
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");      /* polskie znaki w logu z pip */
    do {
        if (!exists(g_py)) {
            set_status(TR(L"Pobieram Pythona", L"Downloading Python"));
            if (!get_python_zip(zip)) break;
            set_status(TR(L"Rozpakowuję…", L"Unpacking…"));
            lstrcpyW(g_step, L"rozpakowywanie");
            g_target = 0.28;
            if (!unzip(zip, g_pydir) || !exists(g_py)) {
                /* zapas: programy systemowe (pracują na tych samych, prawdziwych ścieżkach – zob. store_paths) */
                lg(L"miniz nie dał rady – próbuję tar.exe");
                swprintf(cmd, 4096, L"\"%ls\\tar.exe\" -xf \"%ls\" -C \"%ls\"", sys32, zip, g_pydir);
                if (!run_logged(cmd, &code) || code != 0 || !exists(g_py)) {
                    lg(L"tar.exe nie dał rady – próbuję PowerShell Expand-Archive");
                    swprintf(cmd, 4096, L"powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command \"Expand-Archive -Force "
                             L"-LiteralPath '%ls' -DestinationPath '%ls'\"", zip, g_pydir);
                    if (!run_logged(cmd, &code) || code != 0 || !exists(g_py)) {
                        if (!g_error[0]) fail(TR(L"Nie udało się rozpakować Pythona.", L"Couldn't unpack Python."));
                        break;
                    }
                }
                g_error[0] = 0;
            }
            g_progress = 0.28;
        }
        lstrcpyW(g_step, L"ustawienia Pythona");
        if (!write_pth()) break;
        /* czy Python działa (i czy widzi paczkę MSIX – tylko do logu) */
        swprintf(cmd, 4096, L"\"%ls\" -c \"import sys,os,ctypes;from ctypes import wintypes as w;n=w.UINT(256);"
                 L"b=ctypes.create_unicode_buffer(256);r=ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n),b);"
                 L"print('python',sys.version.split()[0],'| pakiet MSIX:',b.value if r==0 else 'brak (%%d)'%%r,'| exe:',sys.executable)\"", g_py);
        lstrcpyW(g_step, L"test Pythona");
        if (!run_logged(cmd, &code) || code != 0) {
            fail(TR(L"Pobrany Python nie uruchamia się (kod %lu).\nSzczegóły są w logu.", L"The downloaded Python doesn't start (code %lu).\nDetails are in the log."), code);
            break;
        }
        swprintf(cmd, 4096, L"\"%ls\" -c \"import pip\"", g_py);
        if (!run_logged(cmd, &code) || code != 0) {
            BOOL got = FALSE;
            for (int i = 1; i <= TRIES && !got && !g_cancel; i++) {
                g_error[0] = 0;
                swprintf(g_step, 128, L"pobieranie get-pip.py, próba %d z %d", i, TRIES);
                got = download(PIP_URL, getpip, 0.28, 0.32, TR(L"Pobieram instalator pakietów", L"Downloading the package installer"));
                if (!got && i < TRIES) Sleep(1500 * i);
            }
            if (!got) break;
            g_error[0] = 0;
            set_status(TR(L"Instaluję menedżer pakietów (pip)…", L"Installing the package manager (pip)…"));
            swprintf(cmd, 4096, L"\"%ls\" \"%ls\" --no-warn-script-location --disable-pip-version-check", g_py, getpip);
            if (!run_hidden(cmd, 0.45, TR(L"Instalacja pip", L"Installing pip"))) break;
        }
        set_status(TR(L"Pobieram bibliotekę okien (PySide6, ok. 80 MB)…", L"Downloading the window library (PySide6, about 80 MB)…"));
        swprintf(cmd, 4096, L"\"%ls\" -m pip install --no-warn-script-location --disable-pip-version-check "
                 L"--progress-bar off PySide6-Essentials", g_py);
        if (!run_hidden(cmd, 0.97, TR(L"Instalacja PySide6", L"Installing PySide6"))) break;
        if (!write_all(g_ok, "", 0)) lg(L"nie można zapisać %ls (%lu)", g_ok, GetLastError());
        rmtree_dl();
        g_target = g_progress = 1.0;
        set_status(TR(L"Gotowe – otwieram aplikację…", L"Done – opening the app…"));
        lg(L"przygotowanie Pythona zakończone");
        ok = TRUE;
    } while (0);
    SetEnvironmentVariableW(L"PYTHONIOENCODING", NULL);
    PostMessageW(g_hwnd, WM_STAGE_DONE, ok, 0);
    return 0;
}

/* ------------------------------------------------------------------ język okienek */
/* Ustawienia → Ogólne → „Język aplikacji” (settings.json: "ui_language": "pl" / "en"), a przy „jak system”
   i przy pierwszym uruchomieniu – język Windowsa (polski → polski, każdy inny → angielski), jak app/i18n.py. */
static BOOL detect_english(void) {
    static char buf[1 << 16];
    wchar_t path[MAX_PATH];
    DWORD rd = 0;
    swprintf(path, MAX_PATH, L"%ls\\settings.json", g_data);
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        ReadFile(f, buf, sizeof(buf) - 1, &rd, NULL);
        CloseHandle(f);
        buf[rd] = 0;
        if (strstr(buf, "\"ui_language\": \"en\"")) return TRUE;
        if (strstr(buf, "\"ui_language\": \"pl\"")) return FALSE;
    }
    return PRIMARYLANGID(LANGIDFROMLCID(GetUserDefaultLCID())) != LANG_POLISH;   /* jak QLocale.system() */
}

/* ------------------------------------------------------------------ paczka MSIX (Microsoft Store) */
static BOOL running_from_store(void) {
    typedef LONG(WINAPI * GetPkg)(UINT32 *, PWSTR);
    HMODULE k32 = GetModuleHandleW(L"kernel32.dll");
    GetPkg full = (GetPkg)GetProcAddress(k32, "GetCurrentPackageFullName");
    GetPkg fam = (GetPkg)GetProcAddress(k32, "GetCurrentPackageFamilyName");
    if (full) {
        UINT32 n = 256;
        if (full(&n, g_pkgfull) != ERROR_SUCCESS) g_pkgfull[0] = 0;
    }
    if (fam && g_pkgfull[0]) {
        UINT32 n = 256;
        if (fam(&n, g_family) != ERROR_SUCCESS) g_family[0] = 0;
    }
    if (wcsncmp(g_pkgfull, L"Wikingowiec.SlideScribe_", 24) == 0) return TRUE;
    g_pkgfull[0] = g_family[0] = 0;
    wchar_t low[MAX_PATH];
    lstrcpynW(low, g_dir, MAX_PATH);
    CharLowerW(low);
    if (wcsstr(low, L"\\windowsapps\\") == NULL) return FALSE;
    /* bez tożsamości paczki (np. uruchomiony z zewnątrz): rodzina z nazwy folderu
       Wikingowiec.SlideScribe_2.2.3.0_x64__qhcs83qhyfg08 -> Wikingowiec.SlideScribe_qhcs83qhyfg08 */
    const wchar_t *leaf = wcsrchr(g_dir, L'\\');
    leaf = leaf ? leaf + 1 : g_dir;
    const wchar_t *us = wcschr(leaf, L'_'), *pub = wcsstr(leaf, L"__");
    if (us && pub) swprintf(g_family, 256, L"%.*ls_%ls", (int)(us - leaf), leaf, pub + 2);
    return TRUE;
}

/*
 * Gdzie wersja ze Store trzyma Pythona, biblioteki i ustawienia.
 *
 * Folder instalacji (WindowsApps) jest tylko do odczytu. Zapisy procesu z paczki do %LOCALAPPDATA% i %APPDATA%
 * Windows przekierowuje („wirtualizacja”) do %LOCALAPPDATA%\Packages\<rodzina>\LocalCache\Local|Roaming, ale ten
 * widok ma TYLKO proces z tożsamością paczki. Procesy potomne – tar.exe, powershell.exe, a w testach także
 * python.exe – działają bez tożsamości paczki (Windows 10 22H2: GetCurrentPackageFullName = 15700) i widzą
 * prawdziwy %LOCALAPPDATA%. W wersji 2.2.2 launcher zapisał więc python.zip do wirtualnego
 * %LOCALAPPDATA%\WykladyAI\runtime\pobrane, a tar.exe i Expand-Archive nie mogły go znaleźć („kod 1”).
 *
 * Dlatego używamy wprost PRAWDZIWEJ ścieżki w folderze danych paczki:
 *   %LOCALAPPDATA%\Packages\<rodzina>\LocalCache\Local\WykladyAI\runtime   (Python, biblioteki, launcher.log)
 *   %LOCALAPPDATA%\Packages\<rodzina>\LocalCache\Roaming\WykladyAI          (settings.json, app.log)
 * - ten sam plik widzą launcher (z paczką) i wszystkie procesy potomne (bez paczki) – nic nie jest
 *   przekierowywane, bo to już jest docelowe miejsce;
 * - to dokładnie te foldery, do których wirtualizacja odkładała pliki w 2.2.x – nic nie trzeba przenosić;
 * - Windows usuwa je przy odinstalowaniu paczki (wymóg Store), a wersja z GitHuba ich nie dotyka.
 *
 * Krótka ścieżka: …\Packages\Wikingowiec.SlideScribe_qhcs83qhyfg08\LocalCache\Local\WykladyAI\runtime\python\Lib\
 * site-packages ma ~130 znaków, a niektóre pliki PySide6 / CUDA dokładają kolejne 140 – pip przekraczał limit
 * 260 znaków (MAX_PATH; długie ścieżki w Windowsie włącza tylko administrator). Dlatego Python i pip pracują
 * przez dowiązanie katalogu (junction, bez uprawnień administratora) %USERPROFILE%\.slidescribe ->
 * LocalCache\Local\WykladyAI. Limit dotyczy tylko podanej ścieżki, pliki fizycznie są w folderze paczki
 * (po odinstalowaniu zostaje najwyżej puste dowiązanie). Python nie rozwija dowiązania (sys.prefix zostaje krótki).
 *
 * Ścieżki dostaje też Python (WYKLADY_RUNTIME / WYKLADY_DATA / WYKLADY_PACKAGE_FAMILY, app/system.py liczy je
 * tak samo, gdyby zmiennych nie było).
 */
typedef struct {
    DWORD ReparseTag;
    WORD ReparseDataLength, Reserved;
    WORD SubstituteNameOffset, SubstituteNameLength, PrintNameOffset, PrintNameLength;
    WCHAR PathBuffer[1];
} MOUNT_POINT_DATA;

/* pełna, ostateczna ścieżka folderu (po rozwinięciu dowiązań); „” gdy nie istnieje */
static void final_path(const wchar_t *p, wchar_t *out) {
    out[0] = 0;
    HANDLE h = CreateFileW(p, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                           FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    if (!GetFinalPathNameByHandleW(h, out, MAX_PATH * 2, 0)) out[0] = 0;
    CloseHandle(h);
}

static BOOL make_junction(const wchar_t *link, const wchar_t *target) {
    if (!CreateDirectoryW(link, NULL)) return FALSE;
    HANDLE h = CreateFileW(link, GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
                           FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (h == INVALID_HANDLE_VALUE) { RemoveDirectoryW(link); return FALSE; }
    static BYTE buf[4096];
    memset(buf, 0, sizeof(buf));
    MOUNT_POINT_DATA *r = (MOUNT_POINT_DATA *)buf;
    wchar_t sub[MAX_PATH + 8];
    swprintf(sub, MAX_PATH + 8, L"\\??\\%ls", target);
    WORD sl = (WORD)(wcslen(sub) * 2), pl = (WORD)(wcslen(target) * 2);
    r->ReparseTag = IO_REPARSE_TAG_MOUNT_POINT;
    r->SubstituteNameLength = sl;
    r->PrintNameOffset = sl + 2;
    r->PrintNameLength = pl;
    memcpy(r->PathBuffer, sub, sl + 2);
    memcpy((BYTE *)r->PathBuffer + sl + 2, target, pl + 2);
    r->ReparseDataLength = (WORD)(8 + sl + 2 + pl + 2);
    DWORD ret;
    BOOL ok = DeviceIoControl(h, FSCTL_SET_REPARSE_POINT, buf, r->ReparseDataLength + 8, NULL, 0, &ret, NULL);
    DWORD e = GetLastError();
    CloseHandle(h);
    if (!ok) { RemoveDirectoryW(link); SetLastError(e); }
    return ok;
}

/* %USERPROFILE%\.slidescribe -> target; FALSE = nie da się (wtedy zostaje długa ścieżka) */
static BOOL short_link(const wchar_t *link, const wchar_t *target) {
    static wchar_t a[MAX_PATH * 2], b[MAX_PATH * 2];
    DWORD attr = GetFileAttributesW(link);
    if (attr != INVALID_FILE_ATTRIBUTES) {
        if (!(attr & FILE_ATTRIBUTE_REPARSE_POINT)) { swprintf(g_note, 1024, L"%ls to zwykły folder – zostaje długa ścieżka", link); return FALSE; }
        final_path(link, a);
        final_path(target, b);
        if (a[0] && lstrcmpiW(a, b) == 0) return TRUE;
        RemoveDirectoryW(link);                 /* stare / puste dowiązanie (np. po ponownej instalacji) */
    }
    if (!make_junction(link, target)) { swprintf(g_note, 1024, L"nie udało się utworzyć dowiązania %ls (%lu) – zostaje długa ścieżka", link, GetLastError()); return FALSE; }
    SetFileAttributesW(link, FILE_ATTRIBUTE_HIDDEN);
    swprintf(g_note, 1024, L"utworzono dowiązanie %ls -> %ls", link, target);
    return TRUE;
}

static void store_paths(void) {
    wchar_t local[MAX_PATH] = L"", pkg[MAX_PATH], base[MAX_PATH];
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH)) {
        GetEnvironmentVariableW(L"USERPROFILE", local, MAX_PATH);
        lstrcatW(local, L"\\AppData\\Local");
    }
    swprintf(pkg, MAX_PATH, L"%ls\\Packages\\%ls", local, g_family);
    if (g_family[0] && exists(pkg)) {
        swprintf(base, MAX_PATH, L"%ls\\LocalCache", pkg);
        swprintf(g_runtime, MAX_PATH, L"%ls\\Local\\WykladyAI\\runtime", base);
        swprintf(g_data, MAX_PATH, L"%ls\\Roaming\\WykladyAI", base);
        SHCreateDirectoryExW(NULL, g_runtime, NULL);
        wchar_t prof[MAX_PATH] = L"", link[MAX_PATH], target[MAX_PATH];
        if (GetEnvironmentVariableW(L"USERPROFILE", prof, MAX_PATH)) {
            swprintf(link, MAX_PATH, L"%ls\\.slidescribe", prof);
            swprintf(target, MAX_PATH, L"%ls\\Local\\WykladyAI", base);
            if (short_link(link, target)) swprintf(g_runtime, MAX_PATH, L"%ls\\runtime", link);
        }
    } else {                 /* awaryjnie (nie powinno się zdarzyć): zwykłe foldery użytkownika */
        swprintf(g_runtime, MAX_PATH, L"%ls\\WykladyAI\\runtime", local);
        wchar_t roam[MAX_PATH] = L"";
        GetEnvironmentVariableW(L"APPDATA", roam, MAX_PATH);
        swprintf(g_data, MAX_PATH, L"%ls\\WykladyAI", roam);
    }
    SHCreateDirectoryExW(NULL, g_runtime, NULL);
    SHCreateDirectoryExW(NULL, g_data, NULL);
    wchar_t pyc[MAX_PATH];
    swprintf(pyc, MAX_PATH, L"%ls\\pycache", g_runtime);
    SetEnvironmentVariableW(L"PYTHONPYCACHEPREFIX", pyc);     /* dziedziczy pythonw.exe */
    SetEnvironmentVariableW(L"WYKLADY_RUNTIME", g_runtime);
    SetEnvironmentVariableW(L"WYKLADY_DATA", g_data);
    SetEnvironmentVariableW(L"WYKLADY_PACKAGE_FAMILY", g_family[0] ? g_family : L"msix");
    g_name = L"SlideScribe";
}

/* ------------------------------------------------------------------ szczegóły błędu (schowek) */
static void copy_details(HWND w) {
    static wchar_t txt[12000];
    int n = swprintf(txt, 12000, L"%ls %hs – %ls\r\n%ls: %ls\r\n\r\n%ls\r\nKrok: %ls\r\nMSIX: %ls (%ls)\r\n"
                     L"Program: %ls\r\nRuntime: %ls\r\nUstawienia: %ls\r\nLog: %ls\r\n\r\n--- ostatnie wpisy logu ---\r\n",
                     g_name, APP_VERSION, TR(L"nie udało się przygotować aplikacji", L"setup failed"),
                     TR(L"Błąd", L"Error"), g_error, g_winver, g_step, g_store ? L"tak" : L"nie",
                     g_pkgfull[0] ? g_pkgfull : (g_family[0] ? g_family : L"-"), g_dir, g_runtime, g_data, g_logpath);
    /* ostatnie ~6 KB logu */
    HANDLE f = CreateFileW(g_logpath, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        static char buf[6001];
        DWORD size = GetFileSize(f, NULL), got = 0;
        if (size > 6000) SetFilePointer(f, -6000, NULL, FILE_END);
        ReadFile(f, buf, 6000, &got, NULL);
        buf[got] = 0;
        CloseHandle(f);
        MultiByteToWideChar(CP_UTF8, 0, buf, -1, txt + n, 12000 - n - 1);
    }
    size_t len = (wcslen(txt) + 1) * sizeof(wchar_t);
    if (!OpenClipboard(w)) return;
    EmptyClipboard();
    HGLOBAL g = GlobalAlloc(GMEM_MOVEABLE, len);
    if (g) {
        memcpy(GlobalLock(g), txt, len);
        GlobalUnlock(g);
        SetClipboardData(CF_UNICODETEXT, g);
    }
    CloseClipboard();
    g_copied = GetTickCount();
}

static void open_log(HWND w) {
    INT_PTR r = (INT_PTR)ShellExecuteW(w, L"open", g_logpath, NULL, NULL, SW_SHOWNORMAL);
    lg(L"otwieram log (ShellExecute: %d)", (int)r);
    if (r <= 32) {          /* brak skojarzenia .log – Notatnik */
        wchar_t args[MAX_PATH + 4];
        swprintf(args, MAX_PATH + 4, L"\"%ls\"", g_logpath);
        ShellExecuteW(w, L"open", L"notepad.exe", args, NULL, SW_SHOWNORMAL);
    }
}

/* ------------------------------------------------------------------ uruchomienie aplikacji */
static BOOL launch_app(BOOL debug, const wchar_t *extra) {
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    wchar_t cmd[4096];
    swprintf(cmd, 4096, L"\"%ls\" \"%ls\" %ls", debug ? g_py : g_pyw, g_main, extra ? extra : L"");
    AllowSetForegroundWindow(ASFW_ANY);
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, debug ? CREATE_NEW_CONSOLE : 0, NULL, g_internal, &si, &pi)) {
        DWORD e = GetLastError();
        lg(L"BŁĄD: nie udało się uruchomić aplikacji (%lu): %ls", e, cmd);
        wchar_t msg[1024];
        swprintf(msg, 1024, TR(L"Nie udało się uruchomić aplikacji (%lu).\n\n%ls\n\nLog: %ls", L"Couldn't start the app (%lu).\n\n%ls\n\nLog: %ls"), e, cmd, g_logpath);
        MessageBoxW(NULL, msg, g_name, MB_ICONERROR);
        return FALSE;
    }
    lg(L"start aplikacji (pid %lu)", pi.dwProcessId);
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

/* przyciski okna błędu: 0 = Otwórz log, 1 = Kopiuj szczegóły, 2 = Zamknij */
static RECT button_rect(HWND w, int i) {
    RECT rc; GetClientRect(w, &rc);
    int pad = S(28), top = rc.bottom - S(64), bot = rc.bottom - S(24);
    RECT r = { pad, top, pad + S(132), bot };
    if (i == 1) { r.left = pad + S(144); r.right = r.left + S(176); }
    if (i == 2) { r.right = rc.right - pad; r.left = r.right - S(112); }
    return r;
}

static int hit_button(HWND w, POINT pt) {
    for (int i = 0; i < 3; i++) {
        RECT r = button_rect(w, i);
        if (PtInRect(&r, pt)) return i;
    }
    return -1;
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
    DrawTextW(dc, g_name, -1, &t, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    SelectObject(dc, g_ftext);
    SetTextColor(dc, g_failed ? red : ink2);
    RECT t2 = { pad + S(52), pad + S(26), rc.right - pad, pad + S(48) };
    DrawTextW(dc, g_failed ? TR(L"Nie udało się przygotować aplikacji", L"Couldn't prepare the app")
                  : g_mode ? TR(L"Otwieranie…", L"Opening…") : TR(L"Pierwsze uruchomienie – przygotowuję aplikację", L"First launch – getting the app ready"), -1, &t2,
              DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS);
    /* zamknij */
    if (!g_mode) {
        SetTextColor(dc, ink2);
        RECT x = { rc.right - S(40), S(10), rc.right - S(10), S(40) };
        DrawTextW(dc, L"×", -1, &x, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    }
    if (g_failed) {
        wchar_t msg[1600];
        swprintf(msg, 1600, TR(L"%ls\n\nUruchom %ls ponownie – przygotowanie zacznie się od miejsca, w którym przerwało. "
                               L"Jeśli błąd się powtarza, kliknij „Kopiuj szczegóły” i wyślij je autorowi.",
                               L"%ls\n\nStart %ls again – setup will continue where it stopped. "
                               L"If the error keeps coming back, click “Copy details” and send them to the author."), g_error, g_name);
        SetTextColor(dc, ink);
        RECT st = { pad, S(96), rc.right - pad, rc.bottom - S(76) };
        DrawTextW(dc, msg, -1, &st, DT_LEFT | DT_WORDBREAK | DT_EDITCONTROL);   /* łamie też długie ścieżki */
        const wchar_t *labels[3] = {
            TR(L"Otwórz log", L"Open log"),
            (g_copied && GetTickCount() - g_copied < 2500) ? TR(L"Skopiowano ✓", L"Copied ✓") : TR(L"Kopiuj szczegóły", L"Copy details"),
            TR(L"Zamknij", L"Close") };
        for (int i = 0; i < 3; i++) {
            RECT b = button_rect(w, i);
            fill_round(dc, b, S(10), i == 2 ? accent : track);
            SetTextColor(dc, i == 2 ? paper : ink);
            DrawTextW(dc, labels[i], -1, &b, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        }
    } else if (!g_mode) {
        wchar_t pct[16];
        swprintf(pct, 16, L"%d%%", (int)(g_progress * 100 + 0.5));
        SelectObject(dc, g_fbig);
        SetTextColor(dc, ink);
        RECT b = { pad, S(92), rc.right - pad, S(170) };
        DrawTextW(dc, pct, -1, &b, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
        SelectObject(dc, g_ftext);
        SetTextColor(dc, ink2);
        RECT st = { pad, S(172), rc.right - pad, rc.bottom - S(62) };
        DrawTextW(dc, g_status, -1, &st, DT_LEFT | DT_WORDBREAK | DT_END_ELLIPSIS);
        RECT tr = { pad, rc.bottom - S(52), rc.right - pad, rc.bottom - S(46) };
        fill_round(dc, tr, S(6), track);
        RECT fr = tr;
        fr.right = tr.left + (LONG)((tr.right - tr.left) * g_progress);
        if (fr.right > fr.left + S(6)) fill_round(dc, fr, S(6), accent);
        SelectObject(dc, g_fsmall);
        SetTextColor(dc, ink2);
        RECT h = { pad, rc.bottom - S(38), rc.right - pad, rc.bottom - S(14) };
        DrawTextW(dc, TR(L"Potem otworzy się ekran instalacji bibliotek i modeli AI.", L"Next, a screen for installing libraries and AI models will open."), -1, &h,
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

static void show_failure(HWND w) {
    g_failed = 1;
    RECT wr; GetWindowRect(w, &wr);
    int ww = wr.right - wr.left, wh = S(400);
    SetWindowPos(w, NULL, wr.left, wr.top - (wh - (wr.bottom - wr.top)) / 2, ww, wh, SWP_NOZORDER);
    SetForegroundWindow(w);
    InvalidateRect(w, NULL, FALSE);
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
            if (g_failed && hit_button(w, pt) >= 0) return HTCLIENT;
            if (!(pt.x > rc.right - S(44) && pt.y < S(44))) return HTCAPTION;
        }
        return hit;
    }
    case WM_SETCURSOR:
        if (g_failed && LOWORD(lp) == HTCLIENT) { SetCursor(LoadCursor(NULL, IDC_HAND)); return TRUE; }
        break;
    case WM_KEYDOWN:
        if (g_failed && wp == VK_ESCAPE) DestroyWindow(w);
        return 0;
    case WM_LBUTTONUP:
        if (g_failed) {
            POINT pt = { (short)LOWORD(lp), (short)HIWORD(lp) };
            int b = hit_button(w, pt);
            if (b == 0) open_log(w);
            else if (b == 1) copy_details(w);
            else DestroyWindow(w);            /* „Zamknij” albo × */
            InvalidateRect(w, NULL, FALSE);
            return 0;
        }
        if (!g_mode && MessageBoxW(w, TR(L"Przerwać przygotowanie aplikacji? Dokończy się przy następnym uruchomieniu.", L"Stop preparing the app? It will continue next time."),
                                   g_name, MB_YESNO | MB_ICONQUESTION) == IDYES) {
            InterlockedExchange(&g_cancel, 1);
            lg(L"przerwane przez użytkownika");
            if (g_proc_running) TerminateProcess(g_proc_running, 1);
            ExitProcess(1);
        }
        return 0;
    case WM_STAGE_DONE:
        if (wp) {
            if (launch_app(FALSE, L"")) { g_mode = 1; }
            else DestroyWindow(w);
        } else if (!g_cancel) {
            if (!g_error[0]) lstrcpyW(g_error, TR(L"Nieznany błąd.", L"Unknown error."));
            show_failure(w);
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
    g_hwnd = CreateWindowExW(mode ? WS_EX_TOOLWINDOW : 0, wc.lpszClassName, g_name, WS_POPUP, x, y, ww, wh,
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
    {
        wchar_t roam[MAX_PATH] = L"";
        GetEnvironmentVariableW(L"APPDATA", roam, MAX_PATH);
        swprintf(g_data, MAX_PATH, L"%ls\\WykladyAI", roam);
    }
    g_store = running_from_store();
    if (g_store) store_paths();
    swprintf(g_pydir, MAX_PATH, L"%ls\\python", g_runtime);
    swprintf(g_pyw, MAX_PATH, L"%ls\\pythonw.exe", g_pydir);
    swprintf(g_py, MAX_PATH, L"%ls\\python.exe", g_pydir);
    swprintf(g_main, MAX_PATH, L"%ls\\main.py", g_internal);
    swprintf(g_ok, MAX_PATH, L"%ls\\stage1.ok", g_runtime);
    swprintf(g_dl, MAX_PATH, L"%ls\\pobrane", g_runtime);

    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);   /* dla ShellExecute */
    g_en = detect_english();
    lstrcpyW(g_status, TR(L"Przygotowuję…", L"Preparing…"));
    log_open();
    windows_version();
    lg(L"=== %ls %hs | %ls | MSIX: %ls", g_name, APP_VERSION, g_winver,
       g_store ? (g_pkgfull[0] ? g_pkgfull : L"tak (bez tożsamości paczki)") : L"nie");
    lg(L"program: %ls | runtime: %ls | ustawienia: %ls", g_dir, g_runtime, g_data);
    if (g_note[0]) lg(L"%ls", g_note);

    if (!exists(g_main)) {
        lg(L"BŁĄD: brak %ls", g_main);
        MessageBoxW(NULL, TR(L"Brakuje plików aplikacji (folder _internal).\n\nRozpakuj całe archiwum z aplikacją "
                             L"i uruchom Wykłady.exe z rozpakowanego folderu.",
                             L"App files are missing (the _internal folder).\n\nExtract the whole app archive "
                             L"and run Wykłady.exe from the extracted folder."), g_name, MB_ICONERROR);
        return 1;
    }
    BOOL debug = cmdline && wcsstr(cmdline, L"--debug") != NULL;

    if (exists(g_pyw) && exists(g_ok)) {
        BOOL ok = launch_app(debug, cmdline);
        CloseHandle(g_log);
        g_log = INVALID_HANDLE_VALUE;
        if (!ok) return 1;
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
