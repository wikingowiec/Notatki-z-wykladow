"""Wykłady – nagrywanie wykładów, transkrypcja, slajdy, notatki i fiszki (wszystko lokalnie).

Uruchamiane przez Wykłady.exe (bez okna konsoli). Przy pierwszym uruchomieniu – albo po aktualizacji, która
potrzebuje nowych bibliotek – najpierw pokazuje się ekran przygotowania (notes z postępem), a potem od razu
okno aplikacji, w tym samym procesie."""
from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

BASE = os.path.dirname(os.path.abspath(__file__))
INSTANCE_KEY = "Wyklady-jedno-okno"


def _setup_logging():
    from app.config import log_path
    handlers = [RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s")


def _instance_alive() -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(INSTANCE_KEY)
    ok = s.waitForConnected(200)
    s.abort()
    return ok


def _already_running() -> bool:
    """Drugie kliknięcie Wykłady.exe: pokaż istniejące okno zamiast otwierać nowe."""
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(INSTANCE_KEY)
    if s.waitForConnected(300):
        s.write(b"show")
        s.flush()
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        return True
    return False


def create_app(settings):
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from app.config import APP_NAME
    from app.ui.theme import load_fonts, theme, ui_font

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wyklady.App")
        except Exception:
            pass
    try:        # rozmiar interfejsu (Ustawienia → Wygląd) – działa po ponownym uruchomieniu
        scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        if abs(scale - 1.0) > 0.01 and "QT_SCALE_FACTOR" not in os.environ:
            os.environ["QT_SCALE_FACTOR"] = f"{scale:.2f}"
    except (TypeError, ValueError):
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    load_fonts()
    app.setFont(ui_font(10.5))
    icon = os.path.join(BASE, "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    theme().apply(getattr(settings, "theme_name", "zeszyt"), settings.theme)
    return app


def open_main_window(app, settings, fade_in: bool = False):
    """Okno aplikacji: rozmiar i układ ustalone przed pokazaniem, pasek tytułu w kolorach motywu –
    pojawia się raz, od razu gotowe (bez mignięć)."""
    log = logging.getLogger("main")
    from app.transcriber import setup_cuda_dll_paths
    setup_cuda_dll_paths()        # biblioteki CUDA z pakietów pip – przed importem faster_whisper
    from PySide6.QtNetwork import QLocalServer
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_titlebar

    win = MainWindow(settings)
    win.restore_window_geometry()
    win.winId()                   # natywne okno istnieje → kolor paska tytułu ustawiony przed pokazaniem
    apply_titlebar(win)
    win.prepare_layout()
    if fade_in:
        win.setWindowOpacity(0.0)
    if settings.window_maximized:
        win.showMaximized()
    else:
        win.show()
    if fade_in:
        from PySide6.QtCore import QPropertyAnimation
        a = QPropertyAnimation(win, b"windowOpacity", win)
        a.setDuration(260)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.start()
        win._fade = a

    server = QLocalServer(win)
    QLocalServer.removeServer(INSTANCE_KEY)
    if server.listen(INSTANCE_KEY):
        def on_conn():
            c = server.nextPendingConnection()
            if c:
                c.readyRead.connect(lambda: (c.readAll(), win.bring_to_front()))
        server.newConnection.connect(on_conn)
    win._instance_server = server
    log.info("Start aplikacji")
    return win


def main():
    os.chdir(BASE)
    if BASE not in sys.path:
        sys.path.insert(0, BASE)
    _setup_logging()
    log = logging.getLogger("main")
    from app.config import Settings
    settings = Settings.load()
    app = create_app(settings)
    if "--wait" in sys.argv:          # ponowne uruchomienie po aktualizacji – poczekaj, aż stare okno się zamknie
        import time
        for _ in range(60):
            if not _instance_alive():
                break
            time.sleep(0.1)
    if _already_running():
        return

    from PySide6.QtWidgets import QMessageBox

    def excepthook(t, v, tb):
        log.error("Nieobsłużony wyjątek:\n%s", "".join(traceback.format_exception(t, v, tb)))
        try:
            QMessageBox.critical(None, "Błąd", f"{t.__name__}: {v}\n\nSzczegóły w logu (Ustawienia → Otwórz log).")
        except Exception:
            pass
    sys.excepthook = excepthook

    from app.setup.state import embedded, save_marker, setup_needed
    if "--setup" in sys.argv and embedded():      # ponowne sprawdzenie wszystkiego (np. gdy GPU nie działa)
        save_marker(complete=False, req_hash="", whisper="", ai_done=False)
    if setup_needed():
        from app.setup.window import SetupWindow
        sw = SetupWindow(settings)
        holder = {}

        def done():
            holder["win"] = open_main_window(app, settings, fade_in=True)
        sw.finished.connect(done)
        sw.start()
        holder["setup"] = sw
    else:
        holder = {"win": open_main_window(app, settings)}
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
