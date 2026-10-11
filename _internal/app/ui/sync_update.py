"""Sekcje ustawień: „Notatki na telefonie” (Dysk Google / iCloud / OneDrive) i „Aktualizacje” (GitHub;
w wersji z Microsoft Store – tylko informacja, że aktualizuje ją Store)."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from .. import phone, updater, version
from ..system import IS_STORE, STORE_ID
from .controls import show_if, GroupSection, ToggleSwitch, hbox, label, set_icon
from ..i18n import tr


class PhoneSection(GroupSection):
    def __init__(self, settings, lectures_fn):
        super().__init__(tr("Notatki na telefonie"),
                         tr("Aplikacja zapisuje notatkę jako PDF w formacie telefonu w folderze, który Dysk Google "
                         "(albo iCloud / OneDrive) sam wysyła do chmury. Na telefonie otwierasz ją w aplikacji "
                         "Dysk Google – także bez internetu, jeśli oznaczysz folder „Dostępne offline”."))
        self.s = settings
        self.lectures_fn = lectures_fn
        self.toggle = ToggleSwitch(bool(settings.phone_sync))
        self.toggle.toggled.connect(self._toggled)
        self.add_row(tr("Wysyłaj notatki na telefon"), self.toggle,
                     tr("Po każdej gotowej albo poprawionej notatce PDF podmienia się sam."))
        b_pick = QPushButton(tr("Wybierz…"))
        b_pick.clicked.connect(self._pick)
        self.b_open = QPushButton(tr("Otwórz"))
        self.b_open.clicked.connect(lambda: self.s.phone_dir and QDesktopServices.openUrl(
            QUrl.fromLocalFile(self.s.phone_dir)))
        self.dir_row = self.add_row(tr("Folder"), hbox(self.b_open, b_pick, spacing=6))
        self.dir_row.subtitle.show()

        # pomoc / wykryty dysk
        self.help = QFrame()
        self.help.setObjectName("banner")
        hv = QVBoxLayout(self.help)
        hv.setContentsMargins(16, 12, 16, 14)
        hv.setSpacing(8)
        self.help_title = label("", "headline", wrap=True)
        self.help_text = label("", "", wrap=True)
        self.help_text.setTextFormat(Qt.TextFormat.RichText)
        self.help_btns = QHBoxLayout()
        self.help_btns.setSpacing(8)
        hv.addWidget(self.help_title)
        hv.addWidget(self.help_text)
        hv.addLayout(self.help_btns)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.addWidget(self.help)
        self.add(box)

        self.b_all = QPushButton(tr("Wyślij wszystkie teraz"))
        set_icon(self.b_all, "share", "text2", 15)
        self.b_all.clicked.connect(self.send_all)
        self.status_row = self.add_row(tr("Wszystkie notatki"), self.b_all, "")
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        found = phone.detect()
        self._found = found
        d = self.s.phone_dir
        self.dir_row.subtitle.setText(d or tr("nie wybrano"))
        self.b_open.setEnabled(bool(d) and Path(d).exists())
        while self.help_btns.count():
            it = self.help_btns.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        gd = next((f for f in found if f.kind == "gdrive"), None)
        using = next((f for f in found if d and Path(d).is_relative_to(f.root)), None) if d else None
        if using:
            self.help_title.setText(tr("✓ Notatki trafiają do: {x}", x=using.label.split(' (')[0]))
            self.help_text.setText(tr("Folder <b>{subfolder}</b> – na telefonie znajdziesz go w aplikacji ", subfolder=phone.SUBFOLDER)
                                   + (tr("Dysk Google.") if using.kind == "gdrive" else
                                      tr("Pliki (iCloud Drive).") if using.kind == "icloud" else "OneDrive."))
        elif gd:
            self.help_title.setText(tr("Znaleziono Dysk Google na tym komputerze"))
            self.help_text.setText(tr("{root}<br>Kliknij „Użyj Dysku Google” – notatki będą w folderze <b>{subfolder}</b>.", root=gd.root, subfolder=phone.SUBFOLDER))
            self._btn(tr("Użyj Dysku Google"), lambda: self._use(gd), primary=True)
        else:
            self.help_title.setText(tr("Nie znaleziono Dysku Google na tym komputerze"))
            self.help_text.setText(
                tr("1. Zainstaluj <b>Dysk Google na komputer</b> (za darmo) i zaloguj się kontem Google.<br>2. "
                   "Wróć tutaj i kliknij <b>Sprawdź ponownie</b> – folder ustawi się sam.<br>3. Na telefonie "
                   "zainstaluj aplikację <b>Dysk Google</b> (App Store / Google Play) – notatki będą w folderze "
                   "<b>{subfolder}</b>.", subfolder=phone.SUBFOLDER))
            self._btn(tr("Pobierz Dysk Google"), lambda: QDesktopServices.openUrl(QUrl(phone.GDRIVE_DOWNLOAD)),
                      primary=True)
            self._btn(tr("Sprawdź ponownie"), self.refresh)
        for f in found:
            if f.kind != "gdrive" and not (using and using.root == f.root):
                self._btn(tr("Użyj {name}", name="iCloud Drive" if f.kind == "icloud" else "OneDrive"),
                          lambda _=False, x=f: self._use(x))
        self.help_btns.addStretch()
        err = phone.last_error
        self.status_row.subtitle.setText(tr("Ostatni błąd: {err}", err=err) if err else
                                         tr("Wyślij od razu wszystkie gotowe notatki (np. po włączeniu tej opcji)."))
        self.status_row.subtitle.show()
        self.b_all.setEnabled(phone.enabled(self.s))

    def _btn(self, text, fn, primary=False):
        b = QPushButton(text)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(fn)
        self.help_btns.addWidget(b)

    def _use(self, f: phone.CloudFolder):
        self.s.phone_dir = str(f.target)
        self.s.phone_sync = True
        self.s.save()
        self.toggle.blockSignals(True)
        self.toggle.setChecked(True)
        self.toggle.blockSignals(False)
        self.refresh()
        self._offer_all()

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, tr("Folder na notatki (synchronizowany z chmurą)"),
                                             self.s.phone_dir or str(Path.home()))
        if d:
            self.s.phone_dir = d
            self.s.save()
            self.refresh()

    def _toggled(self, on: bool):
        self.s.phone_sync = on
        if on and not self.s.phone_dir:
            gd = next((f for f in phone.detect() if f.kind == "gdrive"), None)
            if gd:
                self.s.phone_dir = str(gd.target)
        self.s.save()
        self.refresh()
        if on and self.s.phone_dir:
            self._offer_all()

    def _offer_all(self):
        n = sum(1 for l in self.lectures_fn() if l.notes_path.exists())
        if n and QMessageBox.question(self, tr("Notatki na telefon"),
                                      tr("Wysłać teraz wszystkie gotowe notatki ({n})?", n=n)) == QMessageBox.StandardButton.Yes:
            self.send_all()

    def send_all(self):
        from PySide6.QtWidgets import QApplication, QProgressDialog
        lectures = [l for l in self.lectures_fn() if l.notes_path.exists()]
        if not lectures or not phone.enabled(self.s):
            return
        dlg = QProgressDialog(tr("Zapisywanie notatek…"), tr("Przerwij"), 0, len(lectures), self)
        dlg.setWindowTitle(tr("Notatki na telefon"))
        dlg.setMinimumDuration(0)

        def prog(i, n):
            dlg.setValue(i - 1)
            dlg.setLabelText(tr("Notatka {i} z {n}", i=i, n=n))
            QApplication.processEvents()
            return not dlg.wasCanceled()
        done = phone.export_all(lectures, self.s, prog)
        dlg.setValue(len(lectures))
        self.refresh()
        QMessageBox.information(self, tr("Notatki na telefon"),
                                tr("Zapisano {done} z {n} notatek w folderze {phone_dir}.", done=done, n=len(lectures), phone_dir=self.s.phone_dir)
                                + (tr("\n\nBłąd: {last_error}", last_error=phone.last_error) if phone.last_error else ""))


class _Bridge(QObject):
    checked = Signal(object, str)          # UpdateInfo | None, błąd
    progress = Signal(int, int)
    applied = Signal(str)                  # błąd ("" = ok)


class UpdateSection(GroupSection):
    restart_requested = Signal()
    update_available = Signal(str)

    def __init__(self, settings, busy_fn):
        if IS_STORE:
            super().__init__(tr("Aktualizacje przez Microsoft Store"), tr("Nowe wersje instaluje Microsoft Store. Notatki, "
                                                                  "nagrania i ustawienia zostają bez zmian."))
        else:
            super().__init__(tr("Aktualizacje"), tr("Nowe wersje pobierają się z repozytorium na GitHubie. Notatki, nagrania i "
                                             "ustawienia zostają bez zmian."))
        self.s = settings
        self.busy_fn = busy_fn
        self.info = None
        if IS_STORE:
            self.add_row(tr("Wersja aplikacji"), label(version.VERSION, "secondary"))
            b = QPushButton(tr("Otwórz w Microsoft Store"))
            set_icon(b, "open", "accent", 14)
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"ms-windows-store://pdp/?productid={STORE_ID}")))
            self.add_row(tr("Nowe wersje"), b, tr("Store sprawdza i instaluje aktualizacje sam."))
            return
        self.bridge = _Bridge()
        self.bridge.checked.connect(self._checked)
        self.bridge.progress.connect(self._progress)
        self.bridge.applied.connect(self._applied)
        self.add_row(tr("Wersja aplikacji"), label(version.VERSION, "secondary"))
        self.repo = QLineEdit(settings.update_repo or version.REPO)
        self.repo.setPlaceholderText("uzytkownik/wyklady")
        self.repo.setMinimumWidth(240)
        self.repo.editingFinished.connect(self._save_repo)
        self.add_row(tr("Repozytorium na GitHubie"), self.repo, tr("Adres albo „użytkownik/nazwa” – stąd pobierane są "
                                                            "nowe wersje."))
        self.btn = QPushButton(tr("Sprawdź aktualizacje"))
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.check)
        self.st = self.add_row(tr("Stan"), self.btn, "")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 4, 16, 10)
        wl.addWidget(self.bar)
        self.bar_box = wrap
        self.add(wrap)
        wrap.hide()
        self._silent = False

    def _save_repo(self):
        self.s.update_repo = self.repo.text().strip()
        self.s.save()

    def _status(self, text: str):
        self.st.subtitle.setText(text)
        show_if(self.st.subtitle, text)

    # ------------------------------------------------------------------ sprawdzanie
    def check(self, silent: bool = False):
        if IS_STORE:
            return
        self._save_repo()
        if self.info is not None and not silent:
            return self._install()
        repo = updater.repo_of(self.s)
        if not repo:
            if not silent:
                self._status(tr("Wpisz repozytorium, np. „uzytkownik/wyklady”."))
            return
        self._silent = silent
        if not silent:
            self.btn.setEnabled(False)
            self._status(tr("Sprawdzam…"))

        def work():
            try:
                self.bridge.checked.emit(updater.check(repo), "")
            except Exception as e:  # noqa: BLE001
                self.bridge.checked.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, info, err: str):
        self.btn.setEnabled(True)
        if err:
            if not self._silent:
                self._status(tr("Nie udało się sprawdzić: {err}", err=err))
            return
        if info is None:
            if not self._silent:
                self._status(tr("Masz najnowszą wersję ({version}).", version=version.VERSION))
            return
        self.info = info
        self.btn.setText(tr("Zaktualizuj do {version}", version=info.version))
        self._status(tr("Dostępna nowa wersja: {version}.", version=info.version))
        self.update_available.emit(info.version)

    # ------------------------------------------------------------------ instalacja
    def _install(self):
        if self.info.manual:      # tylko pobranie w przeglądarce – instalacja jak za pierwszym razem
            QDesktopServices.openUrl(QUrl(self.info.url))
            self._status(tr("Pobieram wersję {version} w przeglądarce – otwórz plik i przeciągnij Wykłady do Aplikacji.", version=self.info.version))
            return
        ok, why = updater.can_update()
        if not ok:
            QMessageBox.information(self, tr("Aktualizacja"), why)
            return
        busy = self.busy_fn()
        if busy:
            QMessageBox.information(self, tr("Aktualizacja"), busy)
            return
        info = self.info
        notes = f"\n\nCo nowego:\n{info.notes[:1200]}" if info.notes else ""
        if QMessageBox.question(self, tr("Aktualizacja"),
                                tr("Zaktualizować do wersji {version}? Aplikacja uruchomi się ponownie.{notes}", version=info.version, notes=notes)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        self.bar_box.show()
        self.bar.setRange(0, 0)
        self._status(tr("Pobieranie…"))

        def work():
            try:
                z = updater.download(info, lambda d, t: self.bridge.progress.emit(d, t))
                self.bridge.progress.emit(-1, -1)
                updater.apply(z)
                self.bridge.applied.emit("")
            except Exception as e:  # noqa: BLE001
                self.bridge.applied.emit(str(e) or type(e).__name__)
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, d: int, t: int):
        if d < 0:
            self.bar.setRange(0, 0)
            self._status(tr("Podmieniam pliki…"))
        elif t:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * d / t))
            self._status(tr("Pobieranie… {x:.1f} z {x2:.1f} MB", x=d / 1e6, x2=t / 1e6))
        else:
            self._status(tr("Pobieranie… {x:.1f} MB", x=d / 1e6))

    def _applied(self, err: str):
        self.bar_box.hide()
        self.btn.setEnabled(True)
        if err:
            self._status(tr("Aktualizacja nie powiodła się: {err}", err=err))
            QMessageBox.warning(self, "Aktualizacja", f"Nie udało się zaktualizować:\n\n{err}")
            return
        self._status(tr("Zaktualizowano – uruchamiam ponownie…"))
        QTimer.singleShot(400, self.restart_requested.emit)
