"""Angielskie tłumaczenia interfejsu: polski tekst z kodu → angielski (zob. i18n.py).

Brakujące wpisy wypisuje: python _internal/tools/i18n_check.py --stub
Parametry w nawiasach klamrowych ({n}, {title}…) muszą zostać takie same jak w tekście polskim."""

EN: dict[str, str] = {
    # ------------------------------------------------------------------ pasek boczny, okno główne
    "Nowa notatka": "New note",
    "Nowa notatka – nagranie albo pliki": "New note – recording or files",
    "Nowa notatka z nagrania, wideo albo zdjęć slajdów": "New note from a recording, video or photos of slides",
    "Nowa notatka z plików": "New note from files",
    "Nowa notatka z ostatnimi ustawieniami ({keys})": "New note with the last settings ({keys})",
    "\nNagrywanie zacznie się dopiero po kliknięciu przycisku nagrywania.":
        "\nRecording starts only when you click the record button.",
    "{keys} — ustawienia jak ostatnio ({q})": "{keys} — same settings as last time ({q})",
    "{keys} — ustawienia jak ostatnio": "{keys} — same settings as last time",
    "Wróć do nagrywania": "Back to recording",
    "Nagrywanie {tm} – wróć do nagrywania": "Recording {tm} – back to recording",
    "Nagrywanie": "Recording",
    "Pauza": "Paused",
    "AI PRACUJE W TLE": "AI WORKING IN THE BACKGROUND",
    "{x}% · zostało ok. {fmt_left}": "{x}% · about {fmt_left} left",
    "minuta": "a minute",
    "Ustawienia": "Settings",
    "Biblioteka": "Library",
    "Wszystkie wykłady": "All lectures",
    "Bez przedmiotu": "No subject",
    "Nauka": "Study",
    "Fiszki": "Flashcards",
    "Fiszka": "Flashcard",
    "Zapytaj": "Ask",
    "Egzamin próbny": "Practice exam",
    "Zacznij serię – powtórz fiszki": "Start a study streak",
    "nowa wersja": "new version",
    "Ustawienia – dostępna wersja {ver}": "Settings – version {ver} available",
    "Trwa nagrywanie": "Recording in progress",
    "Najpierw zakończ bieżące nagrywanie.": "Stop the current recording first.",
    "Trwa zadanie": "Task in progress",
    "Poczekaj, aż skończy się przetwarzanie tego wykładu.": "Wait until this lecture has finished processing.",
    "Trwa nagrywanie – zaktualizuj po jego zakończeniu.": "Recording in progress – update when it's finished.",
    "Trwa: {name}. Zaktualizuj, gdy się skończy.": "In progress: {name}. Update when it's done.",
    "Zakończyć nagrywanie i zamknąć aplikację? Nagranie zostanie zapisane.":
        "Stop recording and close the app? The recording will be saved.",
    "Trwa: {name}. Przerwać i zamknąć?": "In progress: {name}. Stop it and close?",
    "Nie rozpoznano mowy": "No speech recognized",
    "W nagraniu nie rozpoznano mowy. Sprawdź, czy wybrano właściwe źródło dźwięku – pasek poziomu powinien się "
    "ruszać, gdy prowadzący mówi.":
        "No speech was recognized in the recording. Check that the right audio source is selected – the level bar "
        "should move when the lecturer speaks.",
    "Odzyskane nagranie": "Recovered recording",
    "Generowanie notatek dla „{title}” zostało przerwane (aplikacja się zamknęła).\n\nWygenerować notatki teraz?":
        "Generating notes for “{title}” was interrupted (the app closed).\n\nGenerate the notes now?",
    "Aplikacja została zamknięta w trakcie nagrywania „{title}”.\n\nNagranie ({fmt_time}) zostało uratowane. ":
        "The app closed while recording “{title}”.\n\nThe recording ({fmt_time}) was saved. ",
    "Dokończyć transkrypcję i zrobić notatki?": "Finish the transcript and make notes?",
    "Zrobić teraz notatki?": "Make notes now?",

    # ------------------------------------------------------------------ Ctrl+K
    "nagranie albo pliki": "recording or files",
    "nauka z powtórkami": "spaced repetition",
    "pytania do notatek": "questions about your notes",
    "sprawdź się": "test yourself",
    "Szukaj wykładu, tematu albo ekranu…": "Search lectures, topics or screens…",
    "↑ ↓ wybór · Enter otwórz · Esc zamknij": "↑ ↓ select · Enter open · Esc close",
    "Ekran": "Screen",
    "Wykład": "Lecture",
    "Temat": "Topic",
    "Nic nie pasuje – spróbuj innego słowa.": "No matches – try another word.",

    # ------------------------------------------------------------------ kontrolki, stany wykładu
    "Gotowe": "Done",
    "Bez notatek": "No notes",
    "W toku": "In progress",
    "Błąd": "Error",
    "Przedmiot": "Subject",
    "Profil {title}": "{title} profile",
    "POLECANY": "RECOMMENDED",

    # ------------------------------------------------------------------ profile sprzętu (perf.py)
    "Lekki": "Light",
    "Zrównoważony": "Balanced",
    "Pełna moc": "Full power",
    "Laptop albo komputer bez mocnej karty graficznej": "Laptop or PC without a powerful graphics card",
    "Karta graficzna NVIDIA z 8 GB pamięci": "NVIDIA graphics card with 8 GB of memory",
    "Karta graficzna NVIDIA z 12 GB pamięci lub więcej": "NVIDIA graphics card with 12 GB of memory or more",
    "Mniejsze modele, bez notatek na żywo i bez opisywania obrazów na slajdach. Notatki powstają po wykładzie – "
    "spokojnie, bez zacinania komputera.":
        "Smaller models, no live notes and no image descriptions for slides. Notes are created after the lecture – "
        "calmly, without slowing your computer down.",
    "Szybszy model mowy, notatki na żywo i gotowe fragmenty z nagrywania zostają w notatce – po wykładzie dopisuje "
    "się tylko reszta.":
        "Faster speech model and live notes; parts written during the recording stay in the note – only the rest is "
        "added after the lecture.",
    "Najdokładniejsze rozpoznawanie mowy, większy kontekst i dokładniejsze opisy slajdów. Po wykładzie cała notatka "
    "powstaje od nowa mocniejszym modelem.":
        "Most accurate speech recognition, larger context and more detailed slide descriptions. After the lecture "
        "the whole note is rewritten by a stronger model.",
    "Mac z 8 GB pamięci": "Mac with 8 GB of memory",
    "Mac z 16–24 GB pamięci": "Mac with 16–24 GB of memory",
    "Mac z 32 GB pamięci lub więcej": "Mac with 32 GB of memory or more",
    "Mniejsze modele i bez opisywania obrazów na slajdach. Notatki powstają spokojnie, bez zacinania Maca.":
        "Smaller models and no image descriptions for slides. Notes are created calmly, without slowing your Mac down.",
    "Szybki i dokładny model mowy, mocniejszy model notatek i opisy obrazów na slajdach.":
        "Fast and accurate speech model, a stronger notes model and image descriptions for slides.",
    "Najdokładniejsze rozpoznawanie mowy, większy kontekst i dokładniejsze opisy slajdów – cała notatka mocniejszymi "
    "modelami.":
        "Most accurate speech recognition, larger context and more detailed slide descriptions – the whole note by "
        "stronger models.",
    "Procesor": "Processor",
    "bez osobnej karty graficznej": "no dedicated graphics card",
    "{x:.0f} GB pamięci wspólnej": "{x:.0f} GB unified memory",
    "GPU {n} rdzeni": "{n}-core GPU",
    "Mac ma {r} GB pamięci wspólnej – zmieszczą się największe modele.":
        "Your Mac has {r} GB of unified memory – the largest models will fit.",
    "Mac ma {r} GB pamięci wspólnej – wystarczy na mocniejszy model notatek.":
        "Your Mac has {r} GB of unified memory – enough for a stronger notes model.",
    "Mac ma {r} GB pamięci wspólnej – większe modele zwalniałyby komputer.":
        "Your Mac has {r} GB of unified memory – larger models would slow it down.",
    "Karta NVIDIA ma {gb} pamięci – zmieszczą się największe modele.":
        "Your NVIDIA card has {gb} of memory – the largest models will fit.",
    "Karta NVIDIA ma {gb} pamięci – wystarczy na szybki model mowy i notatki na żywo.":
        "Your NVIDIA card has {gb} of memory – enough for the fast speech model and live notes.",
    "Karta NVIDIA ma tylko {gb} pamięci – większe modele zwalniałyby komputer.":
        "Your NVIDIA card has only {gb} of memory – larger models would slow the computer down.",
    "Nie ma karty NVIDIA, więc rozpoznawanie mowy i notatki liczy procesor.":
        "There's no NVIDIA card, so the processor handles speech recognition and notes.",

    # ------------------------------------------------------------------ zgody macOS
    "Zgoda udzielona": "Allowed",
    "Brak zgody": "Not allowed",
    "macOS jeszcze nie pytał": "macOS hasn't asked yet",
    "Zezwól…": "Allow…",
    "Otwórz Ustawienia systemowe": "Open System Settings",
    "Uruchom ponownie": "Restart",
    "macOS włącza nagrywanie ekranu dopiero po ponownym uruchomieniu aplikacji":
        "macOS turns on screen recording only after the app restarts",
    " Kliknij „Zezwól…”, a jeśli macOS nie zapyta – ": " Click “Allow…”, and if macOS doesn't ask – ",
    " macOS zapyta o zgodę przy pierwszym nagrywaniu – możesz zezwolić już teraz.":
        " macOS will ask for permission on the first recording – you can allow it now.",

    # ------------------------------------------------------------------ Ustawienia
    "Zmiany zapisują się od razu. Wszystko działa na tym komputerze.":
        "Changes are saved right away. Everything runs on this computer.",
    "Wygląd": "Appearance",
    "Motyw zmienia kolory, fonty i zaokrąglenia. Zmiana działa od razu.":
        "The theme changes colors, fonts and corner rounding. Takes effect immediately.",
    "Motyw {x}": "{x} theme",
    "Tryb": "Mode",
    "Jak system": "System",
    "Jasny": "Light",
    "Ciemny": "Dark",
    "Jasny – papier, ciemny – tablica. „Jak system” – zgodnie z {system_name}.":
        "Light – paper, dark – blackboard. “System” follows {system_name}.",
    "Ogólne": "General",
    "Zmiana działa po ponownym uruchomieniu aplikacji.": "Takes effect after restarting the app.",
    "Zapisano – nowy język będzie widoczny po ponownym uruchomieniu aplikacji.":
        "Saved – the new language will appear after restarting the app.",
    "Rozmiar interfejsu": "Interface size",
    "100% – domyślny": "100% – default",
    "Większy na dużym monitorze, mniejszy na małym ekranie. Działa po ponownym uruchomieniu.":
        "Larger on a big monitor, smaller on a small screen. Takes effect after a restart.",
    "Zapisano – nowy rozmiar będzie widoczny po ponownym uruchomieniu aplikacji.":
        "Saved – the new size will appear after restarting the app.",
    "Folder biblioteki": "Library folder",
    "Zmień…": "Change…",
    "Otwórz": "Open",
    "Cel dzienny": "Daily goal",
    " fiszek": " cards",
    "Ile fiszek dziennie chcesz powtórzyć – pierścień na ekranie Fiszki.":
        "How many cards you want to review each day – the ring on the Flashcards screen.",
    "Notatki po nagraniu": "Notes after recording",
    "Po zakończeniu nagrania automatycznie twórz notatki, podsumowanie i fiszki.":
        "Automatically create notes, a summary and flashcards when a recording ends.",
    "Wydajność": "Performance",
    "Profil dobiera modele i tryby pracy do mocy komputera. Pojedyncze ustawienia możesz potem zmieniać niżej – "
    "wtedy profil zmienia się na „Własne”.":
        "A profile matches models and modes to your computer's power. You can change individual settings below – "
        "the profile then becomes “Custom”.",
    "Twój komputer": "Your computer",
    "Sprawdzam sprzęt…": "Checking hardware…",
    "Sprawdź ponownie": "Check again",
    "Nie udało się sprawdzić sprzętu.": "Couldn't check the hardware.",
    "{describe}<br>Polecany profil: <b>{x}</b>. {why}": "{describe}<br>Recommended profile: <b>{x}</b>. {why}",
    "Profil": "Profile",
    "Pobierz brakujące": "Download missing",
    "Do pobrania ok. {fmt_gb}": "About {fmt_gb} to download",
    "<b>Własne ustawienia</b> – coś zmieniono ręcznie. Kliknij profil, żeby wrócić do gotowego zestawu.":
        "<b>Custom settings</b> – something was changed manually. Click a profile to go back to a preset.",
    "Do pobrania: {items} – ok. {size}.": "To download: {items} – about {size}.",
    "model mowy {whisper_model}": "speech model {whisper_model}",
    "model mowy {whisper}…": "speech model {whisper}…",
    "Wszystkie modele są pobrane.": "All models are downloaded.",
    "Ollama nie działa – modele AI pobiorą się, gdy ją uruchomisz.":
        "Ollama isn't running – AI models will download once you start it.",
    "Transkrypcja": "Transcription",
    "Rozpoznawanie mowy (Whisper) działa lokalnie na komputerze.": "Speech recognition (Whisper) runs locally on "
                                                                   "your computer.",
    "Język wykładów": "Lecture language",
    "Język, w którym mówi prowadzący. Transkrypcja zawsze zostaje w tym języku – język notatek ustawisz w „Notatki "
    "AI”.":
        "The language the lecturer speaks. The transcript always stays in this language – set the notes language "
        "under “AI notes”.",
    "Wykryj automatycznie": "Detect automatically",
    "Polski": "Polish",
    "Angielski": "English",
    "Niemiecki": "German",
    "Hiszpański": "Spanish",
    "Francuski": "French",
    "Model": "Model",
    "large-v3 – najdokładniejszy": "large-v3 – most accurate",
    "large-v3-turbo – szybszy": "large-v3-turbo – faster",
    "medium – słabsze karty": "medium – weaker GPUs",
    "small – najszybszy": "small – fastest",
    "Dokładniejszy model = lepszy tekst, ale wolniejsza transkrypcja.":
        "A more accurate model = better text, but slower transcription.",
    "Dokładniejszy model = lepszy tekst, ale większe obciążenie karty.":
        "A more accurate model = better text, but more load on the graphics card.",
    "Dokładność": "Accuracy",
    "Szybko": "Fast",
    "Zrównoważona": "Balanced",
    "Najdokładniej": "Most accurate",
    "„Szybko” rozpoznaje mowę ok. 2× szybciej kosztem drobnych pomyłek.":
        "“Fast” recognizes speech about 2× faster at the cost of small mistakes.",
    "Urządzenie": "Device",
    "Automatycznie": "Automatic",
    "Karta graficzna (CUDA)": "Graphics card (CUDA)",
    "Na Macu mowę rozpoznaje procesor (rdzenie wydajnościowe).":
        "On a Mac, speech is recognized by the processor (performance cores).",
    "Fragment na żywo co": "Live chunk every",
    "Co ile sekund dopisywać tekst podczas wykładu.": "How often (in seconds) to add text during the lecture.",
    "Karta graficzna": "Graphics card",
    "Nie sprawdzono": "Not checked",
    "Sprawdź": "Check",
    "Działa – transkrypcja na karcie graficznej.": "Works – transcription runs on the graphics card.",
    "Brak bibliotek CUDA – uruchom ponownie install.bat.": "CUDA libraries missing – run install.bat again.",
    "Nie wykryto karty NVIDIA – użyty zostanie procesor.": "No NVIDIA card detected – the processor will be used.",
    "Błąd: {e}": "Error: {e}",
    "Wykrywanie slajdów": "Slide detection",
    "Próg zmiany slajdu": "Slide change threshold",
    "Jaka część obrazu musi się zmienić. Łapie za dużo – zwiększ. Gubi slajdy – zmniejsz.":
        "How much of the image must change. Catching too much – increase. Missing slides – decrease.",
    "Slajd musi stać przez": "Slide must stay for",
    "Chroni przed zapisywaniem przejść i animacji.": "Prevents saving transitions and animations.",
    "Sprawdzaj ekran co": "Check the screen every",
    "Odczytuj tekst ze slajdów": "Read text from slides",
    "OCR {x} – treść slajdów trafia do notatek.": "{x} OCR – slide text goes into the notes.",
    "Dźwięk": "Audio",
    "Zmień, jeśli przy nagrywaniu wybranej aplikacji pasek poziomu dźwięku stoi w miejscu.":
        "Change this if the audio level bar doesn't move when recording the selected app.",
    " „Automatycznie” = Core Audio (macOS 14.4+), a gdy się nie uda – ScreenCaptureKit.":
        " “Automatic” = Core Audio (macOS 14.4+), falling back to ScreenCaptureKit.",
    "Przechwytywanie aplikacji": "App audio capture",
    "Wbudowany (WASAPI)": "Built-in (WASAPI)",
    "wyłączony": "off",
    "Autostop po ciszy": "Auto-stop after silence",
    "Gdy tyle minut nic nie słychać albo zamkniesz aplikację z wykładem, nagrywanie zakończy się po 60 s (możesz "
    "to anulować).":
        "If nothing is heard for this many minutes or you close the lecture app, recording stops after 60 s (you "
        "can cancel it).",
    "Zgody macOS": "macOS permissions",
    "macOS pyta o zgodę osobno na mikrofon, dźwięk aplikacji i nagrywanie ekranu. Wszystko zostaje na tym Macu.":
        "macOS asks separately for the microphone, app audio and screen recording. Everything stays on this Mac.",
    "Sprawdzanie…": "Checking…",
    "Odśwież": "Refresh",
    "Pobierz": "Download",
    "8 tys. tokenów": "8K tokens",
    "16 tys. tokenów": "16K tokens",
    "32 tys. tokenów": "32K tokens",
    "Notatki AI": "AI notes",
    "Notatki tworzy lokalny model w programie Ollama – bez internetu i bez opłat. Polecane: ":
        "Notes are written by a local model in Ollama – no internet, no fees. Recommended: ",
    "Bielik 11B – polski model (polecany), ~7 GB": "Bielik 11B – Polish model (recommended), ~7 GB",
    "Gemma 3 12B – bardzo dobry polski, ~8 GB": "Gemma 3 12B – very good multilingual, ~8 GB",
    "Qwen3 14B – mocny, ~9 GB": "Qwen3 14B – strong, ~9 GB",
    "Bielik 4.5B – lżejszy i szybszy, ~5 GB": "Bielik 4.5B – lighter and faster, ~5 GB",
    "Qwen3-VL 8B – czyta schematy, wykresy i wzory (polecany), ~6 GB":
        "Qwen3-VL 8B – diagrams, charts, formulas (recommended), ~6 GB",
    "Gemma 3 12B – dobry polski, ~8 GB": "Gemma 3 12B – good multilingual, ~8 GB",
    "Qwen3-VL 4B – szybszy, słabsze karty, ~3 GB": "Qwen3-VL 4B – faster, weaker GPUs, ~3 GB",
    "Stan": "Status",
    "Ollama nie działa. Zainstaluj ją (<a href='https://ollama.com/download'>ollama.com</a>) albo uruchom "
    "install.bat.":
        "Ollama isn't running. Install it (<a href='https://ollama.com/download'>ollama.com</a>) or run install.bat.",
    "Gotowe – oba modele są pobrane.": "Ready – both models are downloaded.",
    "Ollama działa, ale brakuje modelu: ": "Ollama is running, but a model is missing: ",
    "(do pobrania)": "(to download)",
    "Pobieranie: {status}": "Downloading: {status}",
    "Język notatek": "Notes language",
    "Jak wykład": "Same as lecture",
    "Domyślny język notatek, fiszek i podsumowania. „Jak wykład” – w języku, w którym mówi prowadzący. Inny język: "
    "terminy fachowe dostaną oryginał w nawiasie, a cytaty i definicje słowo w słowo zostaną w oryginale. Możesz to "
    "zmienić przy każdej notatce.":
        "Default language of notes, flashcards and the summary. “Same as lecture” – the language the lecturer speaks. "
        "Another language: technical terms get the original in brackets, and verbatim quotes and definitions stay in "
        "the original. You can change it for each note.",
    "Model notatek (po wykładzie)": "Notes model (after the lecture)",
    "Mocniejszy model – pełna notatka, podsumowanie, fiszki, pytania i egzaminy.":
        "The stronger model – full note, summary, flashcards, questions and exams.",
    "Model na żywo (w trakcie)": "Live model (during the lecture)",
    "Lżejszy model do notatek w trakcie nagrywania – zostawia miejsce na karcie dla rozpoznawania mowy. Po "
    "zakończeniu notatka powstaje od nowa mocniejszym modelem.":
        "A lighter model for notes while recording – leaves room on the graphics card for speech recognition. "
        "Afterwards the note is rewritten by the stronger model.",
    "Notatki i pytania na żywo": "Live notes and questions",
    "Notatki powstają w trakcie nagrywania, a pytania można zadawać od razu. Whisper działa wtedy w oszczędniejszym "
    "trybie, żeby oba modele zmieściły się w pamięci karty graficznej.":
        "Notes are written while recording and you can ask questions right away. Whisper then runs in a lighter mode "
        "so both models fit in the graphics card's memory.",
    "Szybkie zakończenie": "Quick finish",
    "Fragmenty napisane w trakcie nagrywania zostają w notatce – po wykładzie dopisuje się tylko reszta, fiszki i "
    "podsumowanie. Dużo szybciej, ale te fragmenty pisał lżejszy model.":
        "Parts written during the recording stay in the note – after the lecture only the rest, flashcards and the "
        "summary are added. Much faster, but those parts were written by the lighter model.",
    "Opisuj obrazy na slajdach": "Describe images on slides",
    "Zdjęcia, schematy, wykresy i tabele ze slajdów dostają opis w notatkach („Na slajdzie”), a model dokładniej "
    "odczytuje tekst i wzory. Dodaje ok. 5 s na slajd po wykładzie.":
        "Photos, diagrams, charts and tables on slides get a description in the notes (“On the slide”), and text and "
        "formulas are read more accurately. Adds about 5 s per slide after the lecture.",
    "Model do slajdów (widzi obrazy)": "Slide model (sees images)",
    "Pobiera się sam przy pierwszym użyciu.": "Downloads automatically on first use.",
    "Fiszek na fragment wykładu": "Cards per lecture part",
    "Kontekst modelu": "Model context",
    "Więcej = model widzi dłuższe fragmenty, ale zużywa więcej pamięci karty.":
        "More = the model sees longer passages, but uses more graphics memory.",
    "Adres serwera Ollama": "Ollama server address",
    "Pomoc": "Help",
    "Otwórz log": "Open log",
    "Dziennik zdarzeń": "Log file",
    "Gdy coś nie działa, prześlij treść logu.": "If something doesn't work, send the contents of the log.",
    "Gdy coś nie działa, {debug} albo prześlij treść logu.":
        "If something doesn't work, {debug} or send the contents of the log.",
    "w Terminalu wpisz „/Applications/Wykłady.app/Contents/MacOS/Wyklady --debug” (komunikaty w oknie Terminala)":
        "type “/Applications/Wykłady.app/Contents/MacOS/Wyklady --debug” in Terminal (messages appear in the "
        "Terminal window)",
    "uruchom „Wykłady.exe --debug” (okno z komunikatami)": "run “Wykłady.exe --debug” (a window with messages)",
    "Aplikacja stworzona przez <b>{author}</b> wyłącznie w celach osobistych – do własnej nauki. Udostępniana bez "
    "gwarancji. Wszystko działa lokalnie: nagrania, notatki i fiszki nie opuszczają Twojego komputera. Pamiętaj o "
    "zasadach uczelni dotyczących nagrywania zajęć.":
        "An app made by <b>{author}</b> for personal use – for the author's own studying. Provided without warranty. "
        "Everything runs locally: recordings, notes and flashcards never leave your computer. Please follow your "
        "school's rules on recording classes.",
    "Strona projektu": "Project page",

    # ------------------------------------------------------------------ Ustawienia: telefon, aktualizacje
    "Notatki na telefonie": "Notes on your phone",
    "Aplikacja zapisuje notatkę jako PDF w formacie telefonu w folderze, który Dysk Google (albo iCloud / OneDrive) "
    "sam wysyła do chmury. Na telefonie otwierasz ją w aplikacji Dysk Google – także bez internetu, jeśli oznaczysz "
    "folder „Dostępne offline”.":
        "The app saves each note as a phone-sized PDF in a folder that Google Drive (or iCloud / OneDrive) uploads to "
        "the cloud. On your phone you open it in the Google Drive app – even offline if you mark the folder "
        "“Available offline”.",
    "Wysyłaj notatki na telefon": "Send notes to your phone",
    "Po każdej gotowej albo poprawionej notatce PDF podmienia się sam.":
        "The PDF updates itself after each finished or edited note.",
    "Wybierz…": "Choose…",
    "Folder": "Folder",
    "Wyślij wszystkie teraz": "Send all now",
    "Wszystkie notatki": "All notes",
    "nie wybrano": "not selected",
    "✓ Notatki trafiają do: {x}": "✓ Notes go to: {x}",
    "Folder <b>{subfolder}</b> – na telefonie znajdziesz go w aplikacji ":
        "Folder <b>{subfolder}</b> – on your phone you'll find it in the app ",
    "Dysk Google.": "Google Drive.",
    "Pliki (iCloud Drive).": "Files (iCloud Drive).",
    "Znaleziono Dysk Google na tym komputerze": "Google Drive found on this computer",
    "{root}<br>Kliknij „Użyj Dysku Google” – notatki będą w folderze <b>{subfolder}</b>.":
        "{root}<br>Click “Use Google Drive” – notes will go to the <b>{subfolder}</b> folder.",
    "Użyj Dysku Google": "Use Google Drive",
    "Nie znaleziono Dysku Google na tym komputerze": "Google Drive not found on this computer",
    "1. Zainstaluj <b>Dysk Google na komputer</b> (za darmo) i zaloguj się kontem Google.<br>2. Wróć tutaj i "
    "kliknij <b>Sprawdź ponownie</b> – folder ustawi się sam.<br>3. Na telefonie zainstaluj aplikację <b>Dysk "
    "Google</b> (App Store / Google Play) – notatki będą w folderze <b>{subfolder}</b>.":
        "1. Install <b>Google Drive for desktop</b> (free) and sign in with your Google account.<br>2. Come back here "
        "and click <b>Check again</b> – the folder will be set automatically.<br>3. On your phone install the "
        "<b>Google Drive</b> app (App Store / Google Play) – notes will be in the <b>{subfolder}</b> folder.",
    "Pobierz Dysk Google": "Get Google Drive",
    "Użyj {name}": "Use {name}",
    "Ostatni błąd: {err}": "Last error: {err}",
    "Wyślij od razu wszystkie gotowe notatki (np. po włączeniu tej opcji).":
        "Send all finished notes right away (e.g. after turning this on).",
    "Folder na notatki (synchronizowany z chmurą)": "Folder for notes (synced with the cloud)",
    "Notatki na telefon": "Notes on your phone",
    "Wysłać teraz wszystkie gotowe notatki ({n})?": "Send all finished notes now ({n})?",
    "Zapisywanie notatek…": "Saving notes…",
    "Przerwij": "Stop",
    "Notatka {i} z {n}": "Note {i} of {n}",
    "Zapisano {done} z {n} notatek w folderze {phone_dir}.": "Saved {done} of {n} notes in {phone_dir}.",
    "\n\nBłąd: {last_error}": "\n\nError: {last_error}",
    "Aktualizacje przez Microsoft Store": "Updates via Microsoft Store",
    "Nowe wersje instaluje Microsoft Store. Notatki, nagrania i ustawienia zostają bez zmian.":
        "New versions are installed by the Microsoft Store. Notes, recordings and settings stay as they are.",
    "Aktualizacje": "Updates",
    "Nowe wersje pobierają się z repozytorium na GitHubie. Notatki, nagrania i ustawienia zostają bez zmian.":
        "New versions are downloaded from the GitHub repository. Notes, recordings and settings stay as they are.",
    "Wersja aplikacji": "App version",
    "Otwórz w Microsoft Store": "Open in Microsoft Store",
    "Nowe wersje": "New versions",
    "Store sprawdza i instaluje aktualizacje sam.": "The Store checks for and installs updates automatically.",
    "Repozytorium na GitHubie": "GitHub repository",
    "Adres albo „użytkownik/nazwa” – stąd pobierane są nowe wersje.":
        "URL or “user/name” – new versions are downloaded from here.",
    "Sprawdź aktualizacje": "Check for updates",
    "Wpisz repozytorium, np. „uzytkownik/wyklady”.": "Enter a repository, e.g. “user/lectures”.",
    "Sprawdzam…": "Checking…",
    "Nie udało się sprawdzić: {err}": "Couldn't check: {err}",
    "Masz najnowszą wersję ({version}).": "You have the latest version ({version}).",
    "Zaktualizuj do {version}": "Update to {version}",
    "Dostępna nowa wersja: {version}.": "New version available: {version}.",
    "Pobieram wersję {version} w przeglądarce – otwórz plik i przeciągnij Wykłady do Aplikacji.":
        "Downloading version {version} in your browser – open the file and drag Wykłady to Applications.",
    "Aktualizacja": "Update",
    "Zaktualizować do wersji {version}? Aplikacja uruchomi się ponownie.{notes}":
        "Update to version {version}? The app will restart.{notes}",
    "Pobieranie…": "Downloading…",
    "Podmieniam pliki…": "Replacing files…",
    "Pobieranie… {x:.1f} z {x2:.1f} MB": "Downloading… {x:.1f} of {x2:.1f} MB",
    "Pobieranie… {x:.1f} MB": "Downloading… {x:.1f} MB",
    "Aktualizacja nie powiodła się: {err}": "Update failed: {err}",
    "Zaktualizowano – uruchamiam ponownie…": "Updated – restarting…",

    # ------------------------------------------------------------------ nagrywanie: ekran wyboru
    "Dzień dobry! Co dziś notujemy?": "Good morning! What are we taking notes on today?",
    "Miłego popołudnia! Co dziś notujemy?": "Good afternoon! What are we taking notes on today?",
    "Dobry wieczór! Co dziś notujemy?": "Good evening! What are we taking notes on today?",
    " Wybierz rodzaj notatki – transkrypcja, notatki i fiszki zrobią się same.":
        " Choose the kind of note – the transcript, notes and flashcards will be made for you.",
    "Nagrywanie na żywo na Macu wymaga macOS 14.4 (Sonoma) lub nowszego. Zaktualizuj system albo dodaj nagranie lub "
    "wideo z pliku.":
        "Live recording on a Mac requires macOS 14.4 (Sonoma) or later. Update macOS or add a recording or video "
        "from a file.",
    "Wymaga macOS 14.4": "Requires macOS 14.4",
    "Dźwięk + slajdy": "Audio + slides",
    "Nagrywa dźwięk wykładu i łapie slajdy z ekranu.": "Records the lecture audio and captures slides from the screen.",
    "Tylko dźwięk": "Audio only",
    "Nagranie z aplikacji albo mikrofonu – notatki z tego, co mówi prowadzący.":
        "Recording from an app or microphone – notes from what the lecturer says.",
    "Tylko slajdy": "Slides only",
    "Zrzuty slajdów z ekranu – notatki z treści slajdów.": "Slide screenshots – notes from the slide content.",
    "Z pliku": "From file",
    "Nagranie z Dyktafonu (m4a), mp3 lub wideo + zdjęcia slajdów.":
        "A voice recording (m4a), mp3 or video + photos of slides.",
    "Nowa notatka zamiast tego": "New note instead",
    "Kontynuacja notatki": "Continue a note",
    "<b>{escape}</b> – część {n}. Nagranie, slajdy albo zdjęcia dopiszą się do tej samej notatki (czas biegnie "
    "dalej od {fmt_time}). Możesz wybrać dowolny rodzaj poniżej.":
        "<b>{escape}</b> – part {n}. The recording, slides or photos will be added to the same note (time continues "
        "from {fmt_time}). You can choose any kind below.",
    "Pusty tytuł = data i godzina. Przedmiot grupuje wykłady w bibliotece.":
        "Empty title = date and time. The subject groups lectures in the library.",
    "Tytuł": "Title",
    "np. Analiza matematyczna – wykład 3": "e.g. Calculus – lecture 3",
    "np. Analiza matematyczna": "e.g. Calculus",
    "Dźwięk nagrywa się tylko z wybranej aplikacji – inne programy (np. muzyka w tle) nie trafią do nagrania. "
    "Aplikacja z wykładem sama pojawi się na górze listy, gdy zacznie grać. Na zajęciach stacjonarnych wybierz "
    "mikrofon.":
        "Audio is recorded only from the selected app – other programs (e.g. background music) won't get into the "
        "recording. The lecture app moves to the top of the list once it starts playing. For in-person classes, "
        "choose the microphone.",
    "Źródło dźwięku": "Audio source",
    "Slajdy": "Slides",
    "Ekran lub okno": "Screen or window",
    "Odśwież listę ekranów i okien": "Refresh the list of screens and windows",
    "Zaznacz obszar slajdu…": "Select slide area…",
    "Zaznacz obszar slajdu": "Select slide area",
    "Cały obraz": "Full image",
    "Opcje": "Options",
    "Język wykładu": "Lecture language",
    "Język, w którym mówi prowadzący – w nim powstanie transkrypcja.":
        "The language the lecturer speaks – the transcript will be in this language.",
    "Notatki, fiszki i podsumowanie powstaną w tym języku – np. wykład po angielsku, notatki po polsku. Terminy "
    "fachowe dostaną oryginał w nawiasie.":
        "Notes, flashcards and the summary will be in this language – e.g. a lecture in Polish, notes in English. "
        "Technical terms get the original in brackets.",
    "Transkrypcja na żywo": "Live transcription",
    "Tekst pojawia się w trakcie wykładu. Wyłącz, by odciążyć kartę graficzną – transkrypcja zrobi się po "
    "zakończeniu.":
        "Text appears during the lecture. Turn it off to ease the load on the graphics card – the transcript will be "
        "made afterwards.",
    "AI pisze notatki z każdego zakończonego fragmentu (po zmianie slajdu albo co kilka minut), a Ty możesz zadawać "
    "pytania w trakcie wykładu. Mocniej obciąża kartę graficzną.":
        "AI writes notes for each finished part (after a slide change or every few minutes) and you can ask questions "
        "during the lecture. Puts more load on the graphics card.",
    "Rozpocznij nagrywanie": "Start recording",
    "Rozpocznij zrzuty slajdów": "Start capturing slides",
    "Nagrywanie możesz zakończyć w dowolnym momencie.": "You can stop recording at any time.",
    "Notatka powstanie z tekstu na slajdach (bez dźwięku).": "The note will be made from the slide text (no audio).",
    "Transkrypcja i notatki zrobią się w tle – postęp zobaczysz w bibliotece.":
        "The transcript and notes will be made in the background – you'll see progress in the library.",
    "Utwórz notatkę": "Create note",
    "Dodaj nagranie…": "Add recording…",
    "Usuń": "Remove",
    "Obszar slajdu…": "Slide area…",
    "Zaznacz, w której części filmu jest slajd (bez kamerki prowadzącego i czatu)":
        "Mark where in the video the slide is (without the lecturer's camera and chat)",
    "Nagranie": "Recording",
    "Dyktafon z iPhone'a (.m4a), mp3, wav albo wideo (mp4, mov). Kilka plików = kolejne części jednego wykładu (w "
    "podanej kolejności). Pliki możesz też przeciągnąć tutaj.":
        "iPhone Voice Memos (.m4a), mp3, wav or video (mp4, mov). Several files = consecutive parts of one lecture "
        "(in the given order). You can also drag files here.",
    "Dodaj zdjęcia…": "Add photos…",
    "Zdjęcia slajdów (opcjonalnie)": "Photos of slides (optional)",
    "Zdjęcia z telefonu (JPG, HEIC, PNG). Każde zostanie dopasowane do miejsca w nagraniu – po godzinie zrobienia "
    "zdjęcia, a gdy się nie da, po treści slajdu. Bez nagrania notatka powstanie z samych zdjęć.":
        "Photos from your phone (JPG, HEIC, PNG). Each one is matched to a point in the recording – by the time it "
        "was taken or, failing that, by the slide content. Without a recording the note is made from the photos alone.",
    "Wyprostuj zdjęcia": "Straighten photos",
    "Wykrywa slajd na zdjęciu i prostuje perspektywę.": "Detects the slide in the photo and corrects the perspective.",
    "Wybierz nagranie": "Choose a recording",
    "Nagrania ({pat});;Wszystkie pliki (*.*)": "Recordings ({pat});;All files (*.*)",
    "Wybierz zdjęcia slajdów": "Choose photos of slides",
    "Zdjęcia ({pat});;Wszystkie pliki (*.*)": "Photos ({pat});;All files (*.*)",
    "  ·  slajd: zaznaczony obszar": "  ·  slide: selected area",
    "  ·  slajd: cały obraz": "  ·  slide: full image",
    "Dodaj nagranie albo zdjęcia slajdów.": "Add a recording or photos of slides.",
    "Potrzebna zgoda macOS": "macOS permission needed",
    "Anuluj": "Cancel",
    "Żadna aplikacja teraz nie gra – włącz dźwięk wykładu i odśwież listę.":
        "No app is playing right now – start the lecture audio and refresh the list.",
    "Nie udało się pobrać podglądu. ": "Couldn't get a preview. ",
    "Slajdy będą wykrywane tylko w zaznaczonym obszarze.": "Slides will be detected only in the selected area.",
    "Wykrywanie obejmuje cały obraz. Jeśli obok slajdu jest kamerka lub czat, zaznacz sam slajd.":
        "Detection covers the full image. If there's a camera or chat next to the slide, select just the slide.",
    "Obszar slajdu": "Slide area",
    "Nie ma jeszcze zrzutu ekranu – spróbuj za chwilę.": "No screenshot yet – try again in a moment.",
    "Najpierw nagraj coś raz zwykłym sposobem – potem {keys} wypełni te same ustawienia.":
        "Record something the usual way first – then {keys} will fill in the same settings.",
    "ostatnie źródło dźwięku": "last audio source",
    "Ostatnio było „{name}”, teraz nie gra – włącz wykład i odśwież listę.":
        "Last time it was “{name}”, which isn't playing now – start the lecture and refresh the list.",
    "ostatni ekran": "last screen",
    "otwórz to okno": "open that window",
    "podłącz ten ekran": "connect that screen",
    "Ostatnio było „{name}”, teraz jest niedostępne – {todo} i odśwież listę.":
        "Last time it was “{name}”, which isn't available now – {todo} and refresh the list.",
    "Cały dźwięk": "All system audio",
    "dźwięk systemu": "system audio",
    "Monitor {index}": "Monitor {index}",
    "Okno: ": "Window: ",
    "okno": "window",

    # ------------------------------------------------------------------ nagrywanie: w trakcie
    "NAGRYWANIE": "RECORDING",
    "PAUZA": "PAUSED",
    "  ·  część {part_index}": "  ·  part {part_index}",
    "część {part_index}": "part {part_index}",
    "dźwięk: {src}": "audio: {src}",
    "bez dźwięku": "no audio",
    "slajdy: {src}": "slides: {src}",
    "bez slajdów": "no slides",
    "Zrzuty slajdów – notatka powstanie z ich treści po zakończeniu.":
        "Slide screenshots – the note will be made from their content afterwards.",
    "Ładowanie modelu rozpoznawania mowy…": "Loading the speech recognition model…",
    "Nagrywanie – transkrypcja zrobi się po zakończeniu.": "Recording – the transcript will be made afterwards.",
    "Poziom dźwięku – powinien się ruszać, gdy prowadzący mówi": "Audio level – it should move when the lecturer speaks",
    "Zaznacz ważne": "Mark important",
    "Zaznacz ważny fragment (Ctrl+M): kliknij, gdy się zaczyna – zaznaczenie obejmie też ostatnie ~20 s – i kliknij "
    "ponownie, gdy się kończy.":
        "Mark an important part (Ctrl+M): click when it starts – the mark also covers the last ~20 s – and click again "
        "when it ends.",
    "Rodzaj zaznaczenia": "Mark type",
    "Zaznacz: {get}": "Mark: {get}",
    "Zakończ zaznaczanie": "Stop marking",
    "Zaznaczanie od {fmt_time} ({get}) – kliknij „Zakończ zaznaczanie” (Ctrl+M), gdy fragment się skończy.":
        "Marking from {fmt_time} ({get}) – click “Stop marking” (Ctrl+M) when the part ends.",
    "Zaznaczono {fmt_time}–{fmt_time2} · {get}. W notatce pojawi się ramka „Ważne” z tym fragmentem.":
        "Marked {fmt_time}–{fmt_time2} · {get}. An “Important” box with this part will appear in the note.",
    "Pauza – dźwięk, transkrypcja i slajdy się zatrzymują, czas stoi":
        "Pause – audio, transcript and slides stop, the clock stops",
    "Wznów": "Resume",
    "Wznów nagrywanie": "Resume recording",
    "Pauza – dźwięk, transkrypcja i slajdy nie są nagrywane. Czas stoi.":
        "Paused – audio, transcript and slides aren't being recorded. The clock is stopped.",
    "Nagrywanie wznowione.": "Recording resumed.",
    "Zakończ": "Stop",
    "Zakończ nagrywanie – notatki zrobią się same": "Stop recording – notes will be made automatically",
    "Nagrywaj dalej": "Keep recording",
    "Zakończ teraz": "Stop now",
    "Aplikacja, z której nagrywasz dźwięk, została zamknięta.": "The app you're recording audio from was closed.",
    "Od {x} min nic nie słychać – wygląda na to, że wykład się skończył.":
        "Nothing has been heard for {x} min – it looks like the lecture is over.",
    "{autostop_reason} Nagrywanie zakończy się za {x} s.": "{autostop_reason} Recording will stop in {x} s.",
    "↓ Na bieżąco": "↓ Live",
    "TRANSKRYPCJA": "TRANSCRIPT",
    "Zapytaj o to, co już padło na wykładzie…  (Ctrl K)": "Ask about what's been said so far…  (Ctrl K)",
    "Pytania działają, gdy włączona jest transkrypcja na żywo.": "Questions work when live transcription is on.",
    "Notatki": "Notes",
    "NOTATKI NA ŻYWO": "LIVE NOTES",
    "NOTATKI": "NOTES",
    "Ładowanie…": "Loading…",
    "Zmień obszar slajdu": "Change slide area",
    "Zaznacz na nowo, gdzie na ekranie jest slajd – nagrywanie trwa dalej, złapane slajdy zostają":
        "Select again where the slide is on screen – recording continues, captured slides stay",
    "SLAJDY · 0": "SLIDES · 0",
    "SLAJDY · {count}": "SLIDES · {count}",
    "Obszar slajdu zmieniony – kolejne slajdy będą wykrywane w nowym obszarze.":
        "Slide area changed – next slides will be detected in the new area.",
    "Slajdy są teraz wykrywane na całym obrazie.": "Slides are now detected on the full image.",
    "<body style='color:{text2}'><p>Pierwszy fragment notatek pojawi się po zmianie slajdu albo po kilku minutach "
    "mowy. Kolejne będą się dopisywać w trakcie wykładu.</p>":
        "<body style='color:{text2}'><p>The first part of the notes will appear after a slide change or a few minutes "
        "of speech. More will be added during the lecture.</p>",
    "<body style='color:{text2}'><p><b style='color:{text}'>Notatki na żywo są wyłączone.</b></p><p>Notatka powstanie "
    "po zakończeniu nagrywania. Możesz je włączyć w opcjach przed nagraniem („Notatki i pytania na żywo”).</p></body>":
        "<body style='color:{text2}'><p><b style='color:{text}'>Live notes are off.</b></p><p>The note will be made "
        "after the recording ends. You can turn them on in the options before recording (“Live notes and "
        "questions”).</p></body>",
    "<p style='color:{text3}'>Pierwszy fragment tekstu pojawi się po około 20–30 sekundach od rozpoczęcia mowy.</p>":
        "<p style='color:{text3}'>The first text will appear about 20–30 seconds after speech starts.</p>",
    "<p style='color:{text2}'>Tryb „Tylko slajdy” – bez dźwięku i transkrypcji. Złapane slajdy widać po prawej; "
    "notatka powstanie z ich treści.</p>":
        "<p style='color:{text2}'>“Slides only” mode – no audio or transcript. Captured slides appear on the right; "
        "the note will be made from their content.</p>",
    "Piszę ten fragment…": "Writing this part…",
    "Piszę po zmianie slajdu albo za ~{mins} min": "Writing after a slide change or in ~{mins} min",
    "Piszę po zmianie slajdu albo za kilka minut": "Writing after a slide change or in a few minutes",
    "Kończenie – zapisywanie nagrania i dokończenie transkrypcji…":
        "Finishing – saving the recording and completing the transcript…",
    "Zapisano „{title}” ({fmt_time}).": "Saved “{title}” ({fmt_time}).",
    "Transkrypcja nie nadąża (opóźnienie {x} s) – nadrobi po zakończeniu.":
        "Transcription is falling behind ({x} s delay) – it will catch up afterwards.",
    "Błąd dźwięku: {error}": "Audio error: {error}",
    "Slajd {index} uzupełniony (animacja) – zrzut podmieniony.": "Slide {index} completed (animation) – screenshot "
                                                                 "replaced.",
    "Powrót do slajdu {index} ({fmt_time}).": "Back to slide {index} ({fmt_time}).",
    "Usunięto slajd {index}. Jeśli ten sam obraz wróci (np. kamerka), nie zapisze się ponownie.":
        "Slide {index} removed. If the same image comes back (e.g. a camera), it won't be saved again.",
    " – przywróć okno albo wybierz cały monitor.": " – restore the window or choose the whole monitor.",

    # ------------------------------------------------------------------ nagrywanie: podgląd na żywo, slajdy
    "Slajd {x}": "Slide {x}",
    "WAŻNE": "IMPORTANT",
    "PISZĘ NASTĘPNY FRAGMENT": "WRITING THE NEXT PART",
    "Powiększ": "Enlarge",
    "TEKST ZE SLAJDU": "SLIDE TEXT",
    "Kopiuj": "Copy",
    "Skopiowano ✓": "Copied ✓",
    "Zostaw oba": "Keep both",
    "Slajdy {a} i {b} to prawie to samo.": "Slides {a} and {b} are almost the same.",
    "Usuń {b}": "Remove {b}",
    "Pierwszy slajd pojawi się tutaj.": "The first slide will appear here.",
    "<span style='color:{text3}'>Odczytuję tekst…</span>": "<span style='color:{text3}'>Reading text…</span>",

    # ------------------------------------------------------------------ wybór dźwięku, obszar slajdu
    "Odsłuchaj": "Listen",
    "Zbierz listę jeszcze raz (np. po włączeniu wykładu)": "Rebuild the list (e.g. after starting the lecture)",
    "Pokaż wszystkie": "Show all",
    "Pokaż wszystkie ({hidden})": "Show all ({hidden})",
    "Pokaż mniej": "Show less",
    "Grają teraz": "Playing now",
    "Urządzenia": "Devices",
    "Pozostałe aplikacje": "Other apps",
    "Przy mikrofonie odsłuch dawałby sprzężenie (pisk) – sprawdź wskaźnik poziomu przy nazwie: powinien skakać, gdy "
    "mówisz.":
        "Listening to a microphone would cause feedback (squealing) – check the level indicator next to its name: it "
        "should jump when you speak.",
    "Nagra {preview_s} s z tego źródła i od razu je odtworzy – usłyszysz dokładnie to, co trafi do nagrania.":
        "Records {preview_s} s from this source and plays it back right away – you'll hear exactly what goes into "
        "the recording.",
    "Słucham {preview_s} s…": "Listening {preview_s} s…",
    "Nagrywam {preview_s} sekundy z „{label}”…": "Recording {preview_s} seconds from “{label}”…",
    "Nic nie było słychać. ": "Nothing was heard. ",
    "Ta aplikacja teraz nie gra – włącz wykład i spróbuj jeszcze raz.":
        "This app isn't playing right now – start the lecture and try again.",
    "Na komputerze nic teraz nie gra.": "Nothing is playing on the computer right now.",
    "Odtwarzam…": "Playing…",
    "Odtwarzam to, co się nagrało – tak będzie brzmiało nagranie wykładu.":
        "Playing what was recorded – this is how the lecture recording will sound.",
    "Odsłuch zakończony. Jeśli było słychać wykład – możesz nagrywać.":
        "Playback finished. If you heard the lecture – you're ready to record.",
    "Nie udało się odtworzyć: {e}": "Couldn't play it back: {e}",
    "Nie udało się nagrać z tego źródła: {e}": "Couldn't record from this source: {e}",
    "Przeciągnij myszką prostokąt wokół slajdu. Zmiany poza nim (kamerka, czat, kursor) nie będą traktowane jako "
    "nowy slajd.":
        "Drag a rectangle around the slide. Changes outside it (camera, chat, cursor) won't count as a new slide.",
    "<b>{name}</b><br>Przeciągnij myszką prostokąt wokół slajdu – zmiany poza nim (kamerka prowadzącego, czat) nie "
    "będą traktowane jako nowy slajd. Jeśli kadr jest czarny albo nie widać slajdu, przesuń suwak.":
        "<b>{name}</b><br>Drag a rectangle around the slide – changes outside it (the lecturer's camera, chat) won't "
        "count as a new slide. If the frame is black or no slide is visible, move the slider.",
    "Moment filmu:": "Video position:",
    "Wczytywanie klatki…": "Loading frame…",
    "Nie udało się odczytać klatki w tym miejscu – przesuń suwak.": "Couldn't read a frame here – move the slider.",
    "Nie udało się odczytać filmu: {e}": "Couldn't read the video: {e}",
    "{name}: zakończono": "{name}: done",

    # ------------------------------------------------------------------ dźwięk, ekran, transkrypcja (komunikaty)
    "gra teraz": "playing now",
    "teraz cisza": "silent now",
    "jeszcze nic nie grała": "hasn't played anything yet",
    "Cały dźwięk systemowy": "All system audio",
    "wszystko, co słychać": "everything you hear",
    "domyślny": "default",
    "urządzenie wirtualne": "virtual device",
    "Mikrofon: {name}": "Microphone: {name}",
    "WASAPI: {x}": "WASAPI: {x}",
    "Nie udało się przechwycić dźwięku aplikacji.\n": "Couldn't capture the app's audio.\n",
    "\n\nSpróbuj opcji „Cały dźwięk systemowy”.": "\n\nTry the “All system audio” option.",
    "🖥 Monitor {i}  ({x}×{x2})": "🖥 Monitor {i}  ({x}×{x2})",
    "Okno zostało zamknięte": "The window was closed",
    "Okno jest zminimalizowane": "The window is minimized",
    "PrintWindow nie powiodło się": "PrintWindow failed",
    "Błąd zrzutu ekranu: {e}": "Screenshot error: {e}",
    "Transkrypcja na żywo działa ({device})": "Live transcription is running ({device})",
    "⚠ Transkrypcja na żywo niedostępna: {e}. Nagranie trwa – transkrypcja zostanie zrobiona z pliku.":
        "⚠ Live transcription unavailable: {e}. Recording continues – the transcript will be made from the file.",
    "Zatrzymywanie nagrywania…": "Stopping the recording…",
    "Kończenie transkrypcji ostatnich fragmentów…": "Finishing the transcript of the last parts…",
    "Nagranie zapisane": "Recording saved",
    "Ładowanie modelu Whisper {model_name} ({device})… przy pierwszym uruchomieniu model się pobiera (~3 GB)":
        "Loading the Whisper model {model_name} ({device})… on first use the model is downloaded (~3 GB)",
    "Nie udało się załadować modelu Whisper: {last}": "Couldn't load the Whisper model: {last}",
    "Przekroczono czas aktywacji przechwytywania dźwięku procesu": "Timed out activating process audio capture",
    "Aktywacja przechwytywania nie powiodła się (HRESULT 0x{x:08X}). Wymagany Windows 10 w wersji 2004 lub nowszej.":
        "Capture activation failed (HRESULT 0x{x:08X}). Windows 10 version 2004 or later is required.",
    "Nie udało się zainicjalizować przechwytywania: {last_exc}": "Couldn't initialize capture: {last_exc}",
    "Notatki na żywo wyłączone: Ollama nie działa. Notatki powstaną po zakończeniu.":
        "Live notes off: Ollama isn't running. Notes will be made afterwards.",
    "Notatki na żywo wyłączone: model AI nie jest pobrany (Ustawienia → Notatki AI).":
        "Live notes off: the AI model isn't downloaded (Settings → AI notes).",
    "Notatki na żywo: czekam na pierwszy pełny fragment (zmiana slajdu albo kilka minut mowy).":
        "Live notes: waiting for the first full part (a slide change or a few minutes of speech).",
    "Notatki na żywo: błąd ({e}) – spróbuję ponownie.": "Live notes: error ({e}) – will try again.",
    "Notatki na żywo: piszę fragment {i}…": "Live notes: writing part {i}…",
    "Notatki na żywo: gotowe fragmenty – {done_sections}. Następny po zmianie slajdu albo po kilku minutach.":
        "Live notes: parts done – {done_sections}. Next one after a slide change or a few minutes.",

    # ------------------------------------------------------------------ biblioteka: lista wykładów
    "Brak wykładów": "No lectures",
    "Wykłady": "Lectures",
    "Szukaj w tytułach i notatkach": "Search titles and notes",
    "Wszystkie": "All",
    "Do nauki": "To study",
    "Do nauki – są fiszki do powtórki dziś · W toku – nagrywanie albo praca AI":
        "To study – cards due today · In progress – recording or AI at work",
    "Ten tydzień": "This week",
    "Wcześniej": "Earlier",
    " · do powtórki dziś: {due}": " · due today: {due}",
    "Notatka z pliku (m4a, mp3, wideo)…": "Note from a file (m4a, mp3, video)…",
    "Plik audio lub wideo (mp3, m4a, wav, mp4, mkv…), np. nagranie z e-learningu":
        "An audio or video file (mp3, m4a, wav, mp4, mkv…), e.g. an e-learning recording",
    "Słownik terminów przedmiotu…": "Subject glossary…",
    "Nazwiska i terminy, które mają być dobrze rozpoznawane w nagraniach tego przedmiotu":
        "Names and terms that should be recognized correctly in this subject's recordings",
    "Słownik: {subj}": "Glossary: {subj}",
    "Terminy, nazwiska i skróty z tego przedmiotu (oddzielone przecinkami lub w osobnych liniach).\nPomagają "
    "poprawnie rozpoznawać je w nagraniach. Terminy ze slajdów dodają się same.":
        "Terms, names and abbreviations from this subject (separated by commas or on separate lines).\nThey help "
        "recognize them correctly in recordings. Terms from slides are added automatically.",

    # ------------------------------------------------------------------ biblioteka: wykład
    "Wybierz wykład": "Choose a lecture",
    "Tu zobaczysz notatki, slajdy, transkrypcję i fiszki wybranego wykładu.":
        "Here you'll see the notes, slides, transcript and flashcards of the selected lecture.",
    "Generuj notatki": "Generate notes",
    "Generuj ponownie": "Regenerate",
    "Generuj ponownie w języku": "Regenerate in language",
    "Generuj notatki w języku": "Generate notes in language",
    "Jak wykład ({get})": "Same as lecture ({get})",
    "Ucz się": "Study",
    "Eksportuj": "Export",
    "Otwórz w przeglądarce (HTML)": "Open in browser (HTML)",
    "Zapisz jako PDF…": "Save as PDF…",
    "Fiszki do Anki…": "Flashcards for Anki…",
    "Kopiuj notatki (Markdown)": "Copy notes (Markdown)",
    "Więcej": "More",
    "Kontynuuj nagrywanie (kolejna część)": "Continue recording (next part)",
    "Edytuj notatki": "Edit notes",
    "Dodaj zdjęcia slajdów…": "Add photos of slides…",
    "Zmień tytuł i przedmiot…": "Change title and subject…",
    "Transkrybuj ponownie z nagrania": "Re-transcribe from the recording",
    "Otwórz nagranie audio": "Open audio recording",
    "Pokaż w folderze": "Show in folder",
    "Usuń wykład…": "Delete lecture…",
    "Usuń wykład": "Delete lecture",
    "Usunąć „{title}”?": "Delete “{title}”?",
    "Nagranie, slajdy, notatki i fiszki zostaną trwale usunięte.":
        "The recording, slides, notes and flashcards will be permanently deleted.",
    "Trwa zadanie dla tego wykładu.": "A task is running for this lecture.",
    "Model notatek: {notes_model}": "Notes model: {notes_model}",
    "Wykład: {get}, notatki: {get2}": "Lecture: {get}, notes: {get2}",
    "Ostatnia próba nie powiodła się: {error}": "The last attempt failed: {error}",
    "Do powtórki dziś: {due}": "Due today: {due}",
    "Wszystkie fiszki tego wykładu": "All flashcards of this lecture",
    "Ściąga": "Cheat sheet",
    "Egzamin": "Exam",
    "Slajdy {n_slides}": "Slides {n_slides}",
    "Fiszki {n_cards}": "Flashcards {n_cards}",
    "Tekst": "Text",
    "Test": "Test",
    "Pokaż, co pisze AI": "Show what the AI is writing",
    "Ukryj podgląd": "Hide preview",
    "Brak notatek": "No notes",
    "Lokalny model AI przygotuje podsumowanie, notatki według slajdów i fiszki. Nic nie jest wysyłane do internetu.":
        "A local AI model will prepare a summary, notes following the slides and flashcards. Nothing is sent to the "
        "internet.",
    "Zapisz zmiany": "Save changes",
    "Edycja notatki (Markdown): # nagłówki, - punkty, **pogrubienie**, wzory $x^2$.":
        "Editing the note (Markdown): # headings, - bullets, **bold**, formulas $x^2$.",
    "Edycja": "Editing",
    "Poczekaj, aż skończy się generowanie notatek.": "Wait until the notes have finished generating.",
    "Notatki były ręcznie poprawiane. Nowe notatki zastąpią Twoje zmiany (kopia zostanie zapisana jako "
    "notes_poprawione.md). Kontynuować?":
        "The notes were edited by hand. New notes will replace your changes (a copy will be saved as "
        "notes_poprawione.md). Continue?",
    "Generowanie notatek": "Generating notes",
    "Trwa inne zadanie": "Another task is running",
    "Trwa: {name}. Poczekaj, aż się skończy.": "In progress: {name}. Wait until it's done.",
    "Zastąpić obecną transkrypcję nową, zrobioną z pliku nagrania?":
        "Replace the current transcript with a new one made from the recording file?",
    "Wybierz nagranie wykładu": "Choose the lecture recording",
    "Audio/Wideo (*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mkv *.webm *.mov *.avi);;Wszystkie (*.*)":
        "Audio/Video (*.mp3 *.m4a *.wav *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mkv *.webm *.mov *.avi);;All (*.*)",
    "Importuj nagranie": "Import recording",
    "Tytuł wykładu:": "Lecture title:",
    "Import nagrania": "Importing recording",
    "Zdjęcia slajdów": "Photos of slides",
    "Dodawanie zdjęć slajdów": "Adding photos of slides",
    "Eksport": "Export",
    "Najpierw wygeneruj notatki.": "Generate the notes first.",
    "Zapisz PDF": "Save PDF",
    "Ten wykład nie ma fiszek.": "This lecture has no flashcards.",
    "Fiszki - {title}.txt": "Flashcards - {title}.txt",
    "Fiszki do Anki": "Flashcards for Anki",
    "Tekst (*.txt)": "Text (*.txt)",
    "Zapisano. W Anki wybierz Plik → Importuj i wskaż ten plik.": "Saved. In Anki choose File → Import and pick this file.",

    # ------------------------------------------------------------------ czytnik notatki
    "Przeczytano 0%": "0% read",
    "Przeczytano {pct}%": "{pct}% read",
    "W TEJ NOTATCE": "IN THIS NOTE",
    "PRZEJDŹ DO": "GO TO",
    "ZAPYTAJ NOTATKĘ": "ASK THE NOTE",
    "W TYM MIEJSCU WYKŁADU": "AT THIS POINT IN THE LECTURE",
    "Odpowiedź": "Answer",
    "Zrób z tego fiszkę": "Make a flashcard",
    "Podaj przykład": "Give an example",
    "Wyjaśnij prościej": "Explain more simply",
    "Najpierw zadaj pytanie": "Ask a question first",
    "Taka fiszka już jest.": "This flashcard already exists.",
    "Dodano fiszkę": "Flashcard added",
    " do kategorii „{cat}”.": " to the “{cat}” category.",
    "Zwiń panel (Ctrl+J)": "Collapse panel (Ctrl+J)",
    "<p style='color:{text3}'>Wczytywanie notatek…</p>": "<p style='color:{text3}'>Loading notes…</p>",
    "<p style='color:{text3}'>Wczytywanie…</p>": "<p style='color:{text3}'>Loading…</p>",
    "<p style='color:{text2}'>Brak transkrypcji. Użyj „Więcej → Transkrybuj ponownie z nagrania”.</p>":
        "<p style='color:{text2}'>No transcript. Use “More → Re-transcribe from the recording”.</p>",
    "<span style='color:{text3}'>Brak transkrypcji w tym miejscu.</span>":
        "<span style='color:{text3}'>No transcript at this point.</span>",
    "Notatka": "Note",
    "Definicje": "Definitions",
    "Wzory": "Formulas",
    "Przykłady": "Examples",
    "Ważne": "Important",
    "Następna ramka: {lower}": "Next box: {lower}",
    "W tej notatce nie ma: {lower}": "This note has no {lower}",
    "Wszystko": "All",
    "Wszystko {n}": "All {n}",
    "Ściąga jest pusta": "The cheat sheet is empty",
    "Ściąga zbiera definicje, wzory, przykłady i ważne rzeczy z ramek w notatce. Starsze notatki nie mają ramek – "
    "kliknij „Generuj ponownie”.":
        "The cheat sheet collects definitions, formulas, examples and important points from the boxes in the note. "
        "Older notes have no boxes – click “Regenerate”.",
    "Brak slajdów": "No slides",
    "Ten wykład był nagrany bez źródła slajdów.": "This lecture was recorded without a slide source.",
    "Tekst ze wszystkich slajdów": "Text from all slides",
    "Miniatury": "Thumbnails",
    "Usuń slajd": "Delete slide",
    "Usunąć slajd {index}? Zniknie też z notatki.": "Delete slide {index}? It will also disappear from the note.",
    "Poczekaj, aż skończy się zadanie dla tego wykładu.": "Wait until the task for this lecture is finished.",
    "Otwórz plik": "Open file",
    "Slajd {x} · {fmt_time}": "Slide {x} · {fmt_time}",
    "Slajd {index} · {fmt_time}": "Slide {index} · {fmt_time}",
    "Slajd {data}": "Slide {data}",
    "Brak fiszek": "No flashcards",
    "Fiszki powstają automatycznie razem z notatkami.": "Flashcards are created automatically with the notes.",
    "Opanowane: {known} z {n}": "Mastered: {known} of {n}",
    "Przygotuj egzamin": "Prepare an exam",
    "Egzamin próbny z tego wykładu": "Practice exam from this lecture",
    "Pytania A–D, prawda/fałsz i otwarte – każde sprawdzone w tej notatce. Liczbę pytań i poziom wybierzesz na "
    "następnym ekranie.":
        "Multiple-choice, true/false and open questions – each checked against this note. You'll choose the number "
        "of questions and the level on the next screen.",

    # ------------------------------------------------------------------ slajdy, odtwarzacz
    "Kliknij, aby powiększyć": "Click to enlarge",
    "Podgląd slajdu": "Slide preview",
    "Poprzedni (←)": "Previous (←)",
    "Następny (→)": "Next (→)",
    "Zamknij": "Close",
    "({i} z {n})": "({i} of {n})",
    "Nie można wczytać obrazu.": "Couldn't load the image.",
    "Tekst slajdów": "Slide text",
    "Kopiuj wszystko": "Copy all",
    "Zamknij odtwarzacz": "Close player",
    "Nie udało się odtworzyć nagrania: ": "Couldn't play the recording: ",
    "Brak nagrania": "No recording",
    "Ten wykład nie ma pliku audio.": "This lecture has no audio file.",

    # ------------------------------------------------------------------ Zapytaj
    "Odpowiedzi pochodzą wyłącznie z notatki. Jeśli czegoś w niej nie ma, zobaczysz to wprost – AI nie zgaduje. "
    "Każda odpowiedź ma cytat i odnośnik do fragmentu notatki.":
        "Answers come only from the note. If something isn't in it, you'll be told plainly – the AI doesn't guess. "
        "Every answer has a quote and a link to the part of the note.",
    "W trakcie wykładu AI szuka odpowiedzi w gotowych fragmentach notatek i w transkrypcji ostatnich minut. Jeśli "
    "czegoś jeszcze nie było, zobaczysz to wprost – AI nie zgaduje.":
        "During the lecture the AI looks for answers in the finished parts of the notes and the transcript of the "
        "last minutes. If something hasn't come up yet, you'll be told plainly – the AI doesn't guess.",
    "Zadaj pytanie, np. „Jak brzmi twierdzenie o wartości średniej?”":
        "Ask a question, e.g. “What does the mean value theorem say?”",
    "Wyczyść": "Clear",
    "Najpierw potrzebne są notatki": "Notes are needed first",
    "Pytania zadajesz do gotowej notatki. Wygeneruj ją przyciskiem „Generuj notatki”.":
        "You ask questions about a finished note. Generate it with the “Generate notes” button.",
    "Pytaj w trakcie wykładu – np. gdy coś Ci umknęło. Źródłem są gotowe fragmenty notatek i transkrypcja ostatnich "
    "minut.":
        "Ask during the lecture – e.g. when you missed something. The sources are the finished parts of the notes and "
        "the transcript of the last minutes.",
    "Wpisz pytanie z zadania lub ćwiczeń. Odpowiedź powstaje tylko na podstawie tej notatki i zawsze pokazuje cytat, "
    "na którym się opiera.":
        "Type a question from your homework or exercises. The answer is based only on this note and always shows the "
        "quote it relies on.",
    "Zapytaj notatkę": "Ask the note",
    "Przykłady: <i>„Czym jest całka oznaczona?”</i>, <i>„Jakie warunki musi spełniać funkcja…?”</i>":
        "Examples: <i>“What is a definite integral?”</i>, <i>“What conditions must the function meet…?”</i>",
    "Odpowiedź z notatki": "Answer from the note",
    "Częściowo w notatce": "Partly in the note",
    "Brak w notatce": "Not in the note",
    "Nie potwierdzono w notatce": "Not confirmed in the note",
    "<p style='margin:0 0 6px 0'>Tej informacji nie ma w notatce, więc nie podaję odpowiedzi.</p>":
        "<p style='margin:0 0 6px 0'>This information isn't in the note, so no answer is given.</p>",
    "<p style='margin:0 0 6px 0'>Nie udało się potwierdzić odpowiedzi cytatem z notatki – najpewniej tej informacji "
    "w niej nie ma. Nie podaję odpowiedzi, żeby nie wprowadzić Cię w błąd.</p>":
        "<p style='margin:0 0 6px 0'>The answer couldn't be confirmed with a quote from the note – most likely the "
        "information isn't there. No answer is given so as not to mislead you.</p>",
    "<p style='margin:0 0 6px 0; color:{text2}'>Najbliższe tematy w notatce: {links}</p>":
        "<p style='margin:0 0 6px 0; color:{text2}'>Closest topics in the note: {links}</p>",
    "<p style='margin:22px 0 6px 0; font-family:\"{display_family}\"; font-size:13pt; font-weight:600'>{escape}</p>"
    "<p style='color:{text2}'>Szukam odpowiedzi w notatce…</p>":
        "<p style='margin:22px 0 6px 0; font-family:\"{display_family}\"; font-size:13pt; font-weight:600'>{escape}</p>"
        "<p style='color:{text2}'>Looking for the answer in the note…</p>",
    "Model AI jest teraz zajęty innym zadaniem – odpowiedź pojawi się, gdy będzie wolny.":
        "The AI model is busy with another task – the answer will appear when it's free.",
    "Ollama nie działa – uruchom ją i spróbuj ponownie.": "Ollama isn't running – start it and try again.",
    "Nie udało się: {e}": "Failed: {e}",
    "Odpowiedzi pochodzą wyłącznie z notatek z wybranego zakresu – każda z cytatem i odnośnikiem do wykładu. Jeśli "
    "czegoś w nich nie ma, zobaczysz to wprost.":
        "Answers come only from the notes in the selected range – each with a quote and a link to the lecture. If "
        "something isn't in them, you'll be told plainly.",
    "Pytania do notatek z wielu wykładów – np. przy zadaniach domowych albo przed kolokwium.":
        "Questions about notes from many lectures – e.g. for homework or before a test.",
    "W tym zakresie nie ma jeszcze notatek.": "There are no notes in this range yet.",
    "Ta notatka jest pusta.": "This note is empty.",
    "Model nie wskazał fragmentu notatki, który potwierdza odpowiedź.":
        "The model didn't point to a part of the note that confirms the answer.",
    "Część odpowiedzi nie ma potwierdzenia w notatce – sprawdź w źródle.":
        "Part of the answer isn't confirmed by the note – check the source.",
    "Odpowiedź zawiera liczby ({nums}), których nie ma w notatce – traktuj ją ostrożnie i sprawdź w źródle.":
        "The answer contains numbers ({nums}) that aren't in the note – treat it with caution and check the source.",
    "Odpowiedź zawiera sformułowania, których nie ma w notatce – traktuj ją ostrożnie i sprawdź w źródle.":
        "The answer contains wording that isn't in the note – treat it with caution and check the source.",

    # ------------------------------------------------------------------ zadania w tle (postęp, błędy)
    "Brak pliku audio do transkrypcji.": "No audio file to transcribe.",
    "Transkrypcja części {k}/{n}": "Transcribing part {k}/{n}",
    "Dekodowanie dźwięku…": "Decoding audio…",
    "Plik: {name}": "File: {name}",
    "Wykrywanie slajdów w wideo…": "Detecting slides in the video…",
    "Ollama nie działa. Zainstaluj ją z https://ollama.com/download i uruchom, a potem kliknij „Generuj notatki”.":
        "Ollama isn't running. Install it from https://ollama.com/download, start it, then click “Generate notes”.",
    "Pobieranie modelu {model} (jednorazowo)…": "Downloading model {model} (one time)…",
    "Pobieranie modelu: {st}": "Downloading model: {st}",
    "Pobieranie modelu do opisu slajdów {vision} (jednorazowo, ~6 GB)…":
        "Downloading the slide description model {vision} (one time, ~6 GB)…",
    "Pobieranie modelu do slajdów: {st}": "Downloading slide model: {st}",
    "Wczytywanie nagrania {k}/{n}: {name}": "Loading recording {k}/{n}: {name}",
    "Zdjęcia slajdów: {k}/{n} (prostowanie i odczyt tekstu)": "Photos of slides: {k}/{n} (straightening and reading text)",
    "Zdjęcia slajdów ({n})": "Photos of slides ({n})",
    "Generowanie notatek zostało przerwane (aplikacja się zamknęła).":
        "Generating notes was interrupted (the app closed).",
    "Nie udało się odczytać nagrania: {e}": "Couldn't read the recording: {e}",
    "Opisywanie slajdów: {k}/{n}": "Describing slides: {k}/{n}",
    "Nie udało się pobrać modelu {model}: {x}": "Couldn't download model {model}: {x}",
    "Brak połączenia z Ollamą. Czy Ollama jest uruchomiona?": "No connection to Ollama. Is Ollama running?",
    "Ollama zwróciła błąd {status_code}: {x}": "Ollama returned error {status_code}: {x}",
    "Opisy slajdów pominięte ({x}) – notatki z tekstu slajdów.": "Slide descriptions skipped ({x}) – notes from slide text.",
    "Brak transkrypcji i tekstu ze slajdów – nie ma z czego zrobić notatek.":
        "No transcript and no slide text – there's nothing to make notes from.",
    "Notatki: fragment {i}/{n}": "Notes: part {i}/{n}",
    "Nagłówki tematów w języku notatek…": "Topic headings in the notes language…",
    "Zaznaczone fragmenty: {j}/{n}": "Marked parts: {j}/{n}",
    "Szukam informacji o egzaminie…": "Looking for exam information…",
    "Porządkuję tematy w kategorie…": "Grouping topics into categories…",
    "Fiszki: fragment {i}/{n}": "Flashcards: part {i}/{n}",
    "Podsumowanie wykładu…": "Lecture summary…",
    "Podsumowanie: skracanie części {j}/{n}": "Summary: condensing part {j}/{n}",
    "Zapisywanie…": "Saving…",
    "Dysk Google ({c})": "Google Drive ({c})",
    "Na egzamin": "For the exam",
    "Ciekawe": "Interesting",
    "Niejasne": "Unclear",
    "Wykład {now:%d.%m.%Y %H:%M}": "Lecture {now:%m/%d/%Y %H:%M}",

    # ------------------------------------------------------------------ fiszki
    "{due} dziś": "{due} today",
    "na dziś gotowe": "done for today",
    "{known} opanowane · {learning} w nauce · {new} nowe": "{known} mastered · {learning} learning · {new} new",
    "Zacznij serię": "Start a streak",
    "Cel dzienny: {goal} ocenionych fiszek (zmiana w Ustawieniach)": "Daily goal: {goal} rated cards (change in Settings)",
    "cel osiągnięty ✓": "goal reached ✓",
    "cel dzienny": "daily goal",
    "Edytuj kartę": "Edit card",
    "PYTANIE": "QUESTION",
    "ODPOWIEDŹ": "ANSWER",
    "Wzory piszesz jak w notatce, np. $x^2$. Zakreślenie: ==tekst==.":
        "Write formulas like in the note, e.g. $x^2$. Highlight: ==text==.",
    "Zapisz": "Save",
    "NAUKA": "STUDY",
    "Ucz się wszystkich": "Study all",
    "Ucz się wszystkich · {due}": "Study all · {due}",
    "KATEGORIE": "CATEGORIES",
    "Przeglądaj": "Browse",
    "Zakończ sesję": "End session",
    "Spacja – pokaż odpowiedź": "Space – show answer",
    "E — edytuj kartę": "E — edit card",
    "Pokaż odpowiedź · Spacja": "Show answer · Space",
    "Spacja – odpowiedź · 1 / 2 – ocena · Ctrl+Z – cofnij · E – edytuj":
        "Space – answer · 1 / 2 – rate · Ctrl+Z – undo · E – edit",
    "Powtórz wszystkie": "Review all",
    "Powtórz wszystkie · {n}": "Review all · {n}",
    "Fiszki powstają automatycznie razem z notatkami z wykładu – pogrupowane w kategorie.":
        "Flashcards are created automatically with the lecture notes – grouped into categories.",
    "Na dziś wszystko": "All done for today",
    "Kolejne fiszki wrócą w wyznaczonym dniu (1, 3, 7… dni). Możesz też powtórzyć wszystkie od nowa.":
        "Cards come back on their scheduled day (1, 3, 7… days). You can also review them all again.",
    "Wszystkie fiszki": "All flashcards",
    "Wszystkie kategorie": "All categories",
    "Wszystkie kategorie · {due}": "All categories · {due}",
    "<p style='color:{text3}'>Brak fiszek w tym zakresie.</p>": "<p style='color:{text3}'>No flashcards in this range.</p>",
    "{due} do powtórki dziś": "{due} due today",
    "{total} wszystkie": "{total} total",
    "{name} · karta {i} z {n}": "{name} · card {i} of {n}",
    "Sesja zakończona": "Session finished",
    "Ocenione w tej sesji: {done}. ": "Rated this session: {done}. ",
    "Jeszcze nie · 1\nwróci w tej sesji": "Not yet · 1\ncomes back this session",
    "Umiem · 2\nnastępna powtórka {nl}": "I know it · 2\nnext review {nl}",
    "Z notatki:": "From the note:",

    # ------------------------------------------------------------------ egzamin próbny
    "Łatwy": "Easy",
    "Średni": "Medium",
    "Trudny": "Hard",
    "Test z Twoich notatek – z jednego wykładu albo całego przedmiotu. Każde pytanie opiera się na konkretnym "
    "fragmencie notatki, więc od razu zobaczysz, skąd jest odpowiedź.":
        "A test from your notes – from one lecture or a whole subject. Every question is based on a specific part of "
        "a note, so you'll see right away where the answer comes from.",
    "Zakres": "Scope",
    "Z czego": "From",
    "Cały przedmiot: ": "Whole subject: ",
    "Liczba pytań": "Number of questions",
    "Pytania": "Questions",
    "Pytania otwarte sprawdza AI, porównując Twoją odpowiedź z notatką.":
        "Open questions are graded by the AI by comparing your answer with the note.",
    "Jednokrotnego wyboru (A–D)": "Multiple choice (A–D)",
    "Prawda / fałsz": "True / false",
    "Otwarte": "Open",
    "Poziom": "Level",
    "Np. „egzamin obejmuje wykłady 3–6”, „dużo pytań o definicje”, „prowadzący mówił, że będzie zadanie z "
    "twierdzenia Lagrange’a”…":
        "E.g. “the exam covers lectures 3–6”, “lots of questions on definitions”, “the lecturer said there will be a "
        "problem on Lagrange's theorem”…",
    "Twoje wskazówki": "Your hints",
    "Uwzględnij informacje o egzaminie z wykładów": "Use exam information from the lectures",
    "Wzmianki prowadzącego typu „to będzie na egzaminie” i fragmenty zaznaczone jako „Na egzamin”.":
        "Lecturer remarks like “this will be on the exam” and parts marked “For the exam”.",
    "Utwórz egzamin": "Create exam",
    "Poprzednie egzaminy": "Previous exams",
    "Najpierw potrzebne są wykłady z gotowymi notatkami.": "You need lectures with finished notes first.",
    " · najlepszy wynik {best}%": " · best score {best}%",
    "Rozwiąż": "Take",
    "Wybierz przynajmniej jeden rodzaj pytań.": "Choose at least one question type.",
    "Układam pytania i sprawdzam każde w notatkach…": "Writing questions and checking each one against the notes…",
    "Twoja odpowiedź…": "Your answer…",
    "Sprawdź odpowiedź": "Check answer",
    "Zobacz w notatce": "See in note",
    "Zobacz w notatce: {get}": "See in note: {get}",
    "Dalej": "Next",
    "Zobacz wynik": "See result",
    "Pytanie {x} z {n}": "Question {x} of {n}",
    "Jednokrotny wybór": "Multiple choice",
    "Prawda czy fałsz?": "True or false?",
    "Pytanie otwarte": "Open question",
    "Prawda": "True",
    "Fałsz": "False",
    "<span style='color:{green}'>✓ Dobrze</span>": "<span style='color:{green}'>✓ Correct</span>",
    "<span style='color:{red}'>✗ Źle</span>": "<span style='color:{red}'>✗ Wrong</span>",
    "✓ Dobrze": "✓ Correct",
    "◐ Częściowo": "◐ Partly",
    "✗ Źle": "✗ Wrong",
    "Nie udało się sprawdzić: {e}": "Couldn't check: {e}",
    "<b>Wzorcowa odpowiedź:</b> {text_to_html}": "<b>Model answer:</b> {text_to_html}",
    "Powtórz błędne": "Retry wrong ones",
    "Rozwiąż jeszcze raz": "Take again",
    "Nowy egzamin": "New exam",
    "Wynik: {score}%": "Score: {score}%",
    "Odpowiedziałeś na {n} z {n2} pytań. ": "You answered {n} of {n2} questions. ",
    "Świetnie – wszystko dobrze!": "Great – all correct!",
    "Do powtórki: {n}. Kliknij temat, żeby otworzyć ten fragment notatki.":
        "To review: {n}. Click a topic to open that part of the note.",
    "Poprawnie:": "Correct:",
    "Brak odpowiedzi": "No answer",
    "W wybranym zakresie nie ma wykładów z gotowymi notatkami.": "There are no lectures with finished notes in the "
                                                                "selected range.",
    "Notatki są puste.": "The notes are empty.",
    "Układam pytania… ({n}/{n2})": "Writing questions… ({n}/{n2})",
    "Nie udało się ułożyć pytań potwierdzonych w notatkach. Spróbuj ponownie.":
        "Couldn't write questions confirmed by the notes. Try again.",
    "Brak odpowiedzi.": "No answer.",

    # ------------------------------------------------------------------ motywy
    "Zielony, papierowy – domyślny.": "Green, papery – the default.",
    "Granatowy, miękki, zaokrąglony.": "Navy, soft, rounded.",
    "Bordowy, książkowy, ostre rogi.": "Burgundy, bookish, sharp corners.",

    # ------------------------------------------------------------------ ekran przygotowania (pierwsze uruchomienie)
    "Przygotowanie": "Setup",
    "Przygotowuję wszystko do pierwszego wykładu": "Getting everything ready for your first lecture",
    "Doinstalowuję nowości po aktualizacji": "Installing what's new after the update",
    "Najpierw dopasujmy aplikację do Twojego komputera": "First, let's match the app to your computer",
    "Na jaki komputer przygotować aplikację?": "What kind of computer should the app be set up for?",
    "Sprawdzam procesor, pamięć i kartę graficzną…": "Checking the processor, memory and graphics card…",
    "Wybrano automatycznie po sprawdzeniu sprzętu.": "Chosen automatically after checking your hardware.",
    "Ten profil może być za ciężki dla tego komputera – notatki będą powstawać wolno.":
        "This profile may be too heavy for this computer – notes will be slow.",
    "Lżejszy niż polecany – szybciej, ale notatki mogą być trochę mniej dokładne.":
        "Lighter than recommended – faster, but notes may be a little less accurate.",
    "{msg} Pobierze się ok. {gb}. Profil zmienisz później w Ustawieniach → Wydajność.":
        "{msg} About {gb} will be downloaded. You can change the profile later in Settings → Performance.",
    "Zainstaluj": "Install",
    "Zainstaluj · {x}": "Install · {x}",
    "Zminimalizuj": "Minimize",
    "Przy pierwszym uruchomieniu pobiera się ok. 20 GB (biblioteki i lokalne modele AI) – to może potrwać od "
    "kilkunastu minut do godziny. Możesz w tym czasie korzystać z komputera.":
        "On first launch about 20 GB is downloaded (libraries and local AI models) – this can take from 15 minutes "
        "to an hour. You can keep using your computer meanwhile.",
    "Pobiera się ok. {fmt_gb} (biblioteki i lokalne modele AI) – to może potrwać od kilkunastu minut do godziny. "
    "Możesz w tym czasie korzystać z komputera.":
        "Downloading about {fmt_gb} (libraries and local AI models) – this can take from 15 minutes to an hour. You "
        "can keep using your computer meanwhile.",
    "To zajmie chwilę.": "This will take a moment.",
    "Coś poszło nie tak": "Something went wrong",
    "Spróbuj ponownie": "Try again",
    "Gotowe! Otwieram aplikację…": "Done! Opening the app…",
    "Przerwać?": "Stop?",
    "Przerwać przygotowanie? Dokończy się przy następnym uruchomieniu aplikacji.":
        "Stop the setup? It will continue the next time you open the app.",
    "Biblioteki aplikacji": "App libraries",
    "Model rozpoznawania mowy": "Speech recognition model",
    "Ollama – lokalne AI": "Ollama – local AI",
    "Modele AI do notatek": "AI models for notes",
    "Skrót na pulpicie": "Desktop shortcut",
    "Brak połączenia z internetem. Sprawdź sieć i spróbuj ponownie.":
        "No internet connection. Check your network and try again.",
    "Za mało miejsca na dysku. Zwolnij kilka GB i spróbuj ponownie.": "Not enough disk space. Free up a few GB and try "
                                                                    "again.",
    "kod błędu {rc}": "error code {rc}",
    "Sprawdzam: {x}": "Checking: {x}",
    "Pobieram biblioteki: {x} · {gb} z {gb2}": "Downloading libraries: {x} · {gb} of {gb2}",
    "Instaluję biblioteki…": "Installing libraries…",
    "Odczyt tekstu ze slajdów (OCR)…": "Reading text from slides (OCR)…",
    "Pobieram model rozpoznawania mowy · {gb} z {gb2}": "Downloading the speech recognition model · {gb} of {gb2}",
    "Pobieram Ollamę · {gb} z {total}": "Downloading Ollama · {gb} of {total}",
    "Pobieram Ollamę · {gb}": "Downloading Ollama · {gb}",
    "Instaluję Ollamę…": "Installing Ollama…",
    "Rozpakowuję Ollamę…": "Unpacking Ollama…",
    "Uruchamiam Ollamę…": "Starting Ollama…",
    "Ollama nie odpowiada.": "Ollama isn't responding.",
    "Nie udało się zainstalować Ollamy – pobierz ją z ollama.com/download.":
        "Couldn't install Ollama – download it from ollama.com/download.",
    "Ollama nie działa – modele pobiorą się przy pierwszych notatkach.":
        "Ollama isn't running – the models will download with your first notes.",
    "Pobieram model {short} · {gb} z {total}": "Downloading model {short} · {gb} of {total}",
    "Pobieram model {short}": "Downloading model {short}",
    "Nie pobrano: {models} – pobiorą się przy pierwszych notatkach.":
        "Not downloaded: {models} – they'll download with your first notes.",
    "W tym pliku nie ma ścieżki dźwiękowej.": "This file has no audio track.",
    "Szczegóły w logu (Ustawienia → Otwórz log).": "Details in the log (Settings → Open log).",

    # ------------------------------------------------------------------ aktualizator (wersja z GitHuba)
    "Nie ustawiono repozytorium na GitHubie (np. „uzytkownik/wyklady”).": "No GitHub repository set (e.g. “user/lectures”).",
    "GitHub odpowiedział błędem {code}.": "GitHub returned error {code}.",
    "W repozytorium nie ma pliku _internal/app/version.py.": "The repository has no _internal/app/version.py file.",
    "Anulowano.": "Cancelled.",
    "Tę wersję aktualizuje Microsoft Store.": "This version is updated by the Microsoft Store.",
    "Aktualizacja działa w aplikacji uruchomionej z Wykłady.app.": "Updating works in the app launched from Wykłady.app.",
    "Wykłady działają prosto z pobranego pliku. Przeciągnij Wykłady do folderu Aplikacje, uruchom je stamtąd i "
    "zaktualizuj ponownie.":
        "Wykłady is running straight from the downloaded file. Drag Wykłady to the Applications folder, open it from "
        "there and update again.",
    "Aktualizacja działa w wersji zainstalowanej z Wykłady.exe (folder z plikiem Wykłady.exe i podfolderem _internal).":
        "Updating works in the version installed from Wykłady.exe (the folder with Wykłady.exe and the _internal "
        "subfolder).",
    "Brak uprawnień do zapisu w Wykłady.app – przeciągnij aplikację do folderu Aplikacje.":
        "No permission to write to Wykłady.app – drag the app to the Applications folder.",
    "Brak uprawnień do zapisu w folderze aplikacji – przenieś go np. do Dokumentów.":
        "No permission to write to the app folder – move it, e.g. to Documents.",
    "Pobrana paczka nie wygląda na aplikację Wykłady (brak _internal/app).":
        "The downloaded package doesn't look like the Wykłady app (no _internal/app).",
    "Nie znaleziono Wykłady.app.": "Wykłady.app not found.",
    "Nie udało się otworzyć pobranego pliku .dmg: {x}": "Couldn't open the downloaded .dmg file: {x}",
    "Pobrana paczka nie wygląda na aplikację Wykłady (brak Wykłady.app).":
        "The downloaded package doesn't look like the Wykłady app (no Wykłady.app).",

    # ------------------------------------------------------------------ macOS: dźwięk, ekran, zgody
    "rozmiar właściwości": "property size",
    "właściwość": "property",
    "{what}: błąd Core Audio {txt}": "{what}: Core Audio error {txt}",
    "Core Audio: {get_str}": "Core Audio: {get_str}",
    "Urządzenie {d}": "Device {d}",
    "start urządzenia": "device start",
    "urządzenie zbiorcze": "aggregate device",
    "Core Audio (aplikacja)": "Core Audio (app)",
    "Core Audio (cały system)": "Core Audio (whole system)",
    "Ten macOS nie ma process taps (potrzebny macOS 14.4 lub nowszy)":
        "This macOS has no process taps (macOS 14.4 or later required)",
    "Ta aplikacja jeszcze nic nie grała": "This app hasn't played anything yet",
    "ScreenCaptureKit nie odpowiedział": "ScreenCaptureKit didn't respond",
    "ScreenCaptureKit: {err}": "ScreenCaptureKit: {err}",
    "ScreenCaptureKit: {x}": "ScreenCaptureKit: {x}",
    "ScreenCaptureKit: {localizeddescription}": "ScreenCaptureKit: {localizeddescription}",
    "ScreenCaptureKit: brak ekranu": "ScreenCaptureKit: no display",
    "ScreenCaptureKit nie widzi tej aplikacji": "ScreenCaptureKit can't see this app",
    "ScreenCaptureKit (aplikacja)": "ScreenCaptureKit (app)",
    "ScreenCaptureKit (cały system)": "ScreenCaptureKit (whole system)",
    "Nie udało się przechwycić dźwięku {what}.\n": "Couldn't capture audio from {what}.\n",
    "\n\nSprawdź zgody w Ustawieniach systemowych → Prywatność i ochrona → Nagrywanie ekranu i dźwięku systemu.":
        "\n\nCheck the permissions in System Settings → Privacy & Security → Screen & System Audio Recording.",
    "\nMożesz też spróbować opcji „Cały dźwięk systemowy”.": "\nYou can also try the “All system audio” option.",
    "Brak zgody na nagrywanie ekranu – zezwól w Ustawieniach systemowych i uruchom Wykłady ponownie":
        "No screen recording permission – allow it in System Settings and restart Wykłady",
    "brak listy okien": "no window list",
    "🖥 Monitor {i}": "🖥 Monitor {i}",
    "Ekran został odłączony": "The display was disconnected",
    "Okno jest zminimalizowane albo niedostępne": "The window is minimized or unavailable",
    "pusty zrzut": "empty screenshot",
    "Nie udało się złapać okna: {e}": "Couldn't capture the window: {e}",
    "Nie udało się zrobić zrzutu ekranu: {e}": "Couldn't take a screenshot: {e}",
    "Dostęp do mikrofonu": "Microphone access",
    "Nagrywanie dźwięku aplikacji": "App audio recording",
    "Nagrywanie ekranu (slajdy)": "Screen recording (slides)",
    "Wykłady nagrywają mikrofon tylko w trakcie nagrywania, a dźwięk zostaje na tym Macu.":
        "Wykłady records the microphone only while recording, and the audio stays on this Mac.",
    "Żeby nagrać wykład z Teams, Zooma albo przeglądarki, macOS musi pozwolić Wykładom słuchać dźwięku wybranej "
    "aplikacji. Nic nie wychodzi poza tego Maca.":
        "To record a lecture from Teams, Zoom or a browser, macOS must allow Wykłady to listen to the selected app's "
        "audio. Nothing leaves this Mac.",
    "Slajdy są łapane ze zrzutów wybranego ekranu albo okna. macOS wymaga na to zgody na nagrywanie ekranu.":
        "Slides are captured from screenshots of the selected screen or window. macOS requires screen recording "
        "permission for this.",
    "Ustawienia systemowe › Prywatność i ochrona › Mikrofon › włącz „Wykłady”.":
        "System Settings › Privacy & Security › Microphone › turn on “Wykłady”.",
    "Ustawienia systemowe › Prywatność i ochrona › Nagrywanie ekranu i dźwięku systemu › w części „Tylko nagrywanie "
    "dźwięku systemu” włącz „Wykłady”.":
        "System Settings › Privacy & Security › Screen & System Audio Recording › under “System Audio Recording Only” "
        "turn on “Wykłady”.",
    "Ustawienia systemowe › Prywatność i ochrona › Nagrywanie ekranu i dźwięku systemu › włącz „Wykłady”, potem "
    "uruchom Wykłady ponownie.":
        "System Settings › Privacy & Security › Screen & System Audio Recording › turn on “Wykłady”, then restart "
        "Wykłady.",

    # ------------------------------------------------------------------ odinstalowanie
    "Odinstaluj": "Uninstall",
    "Odinstaluj aplikację": "Uninstall the app",
    "Odinstaluj aplikację…": "Uninstall the app…",
    "Usuń aplikację z komputera": "Remove the app from this computer",
    "Usuwa biblioteki, modele AI i ustawienia – tylko to, co zainstalowała aplikacja. Przed usunięciem zobaczysz "
    "listę i zdecydujesz, co zostaje. Notatki i nagrania domyślnie zostają.":
        "Removes libraries, AI models and settings – only what the app installed. Before anything is removed you "
        "will see a list and decide what stays. Your notes and recordings stay by default.",
    "Trwa pobieranie modeli – odinstaluj, gdy się skończy.": "Models are downloading – uninstall when it finishes.",
    "Trwa nagrywanie – zakończ je, zanim odinstalujesz aplikację.":
        "Recording in progress – stop it before uninstalling the app.",
    "Trwa: {name}. Odinstaluj aplikację, gdy się skończy (albo przerwij zadanie).":
        "In progress: {name}. Uninstall the app when it finishes (or cancel the task).",
    "Odinstalować {app}?": "Uninstall {app}?",
    "Zaznacz, co usunąć. Usuwamy tylko to, co zainstalowała aplikacja – programy i modele, które były na komputerze "
    "wcześniej, zostają.":
        "Choose what to remove. Only things the app installed are removed – programs and models that were on this "
        "computer before stay.",
    "Tryb próbny: nic nie zostanie usunięte, lista trafi do logu.":
        "Dry run: nothing will be removed, the list goes to the log.",
    "liczę…": "counting…",
    "Nic nie zaznaczono": "Nothing selected",
    "Liczę rozmiar…": "Counting the size…",
    "Zwolnisz ok. {x}": "You will free about {x}",
    "Zwolnisz ok. {x} – liczę dalej…": "You will free about {x} – still counting…",
    "Twoje notatki, nagrania i fiszki zostają w folderze {path}.":
        "Your notes, recordings and flashcards stay in {path}.",
    "Razem z notatkami, nagraniami i fiszkami.": "Including your notes, recordings and flashcards.",
    "Sam pakiet SlideScribe usuniesz na końcu w Ustawieniach Windows.":
        "You will remove the SlideScribe package itself at the end, in Windows Settings.",
    "Tego nie da się cofnąć.": "This cannot be undone.",
    "Usuwa się razem z plikami programu.": "Removed together with the program files.",
    "Usunąć notatki i nagrania?": "Delete notes and recordings?",
    "Usunąć na zawsze {lectures} z folderu {path}? Razem z nagraniami, slajdami, notatkami i fiszkami. Tego nie da "
    "się cofnąć.":
        "Permanently delete {lectures} from {path}? Including recordings, slides, notes and flashcards. This cannot "
        "be undone.",
    "Usunąć na zawsze folder {path} z notatkami i fiszkami? Tego nie da się cofnąć.":
        "Permanently delete the folder {path} with your notes and flashcards? This cannot be undone.",
    "Usuń na zawsze": "Delete permanently",
    "Biblioteki aplikacji i Python": "App libraries and Python",
    "Pobrane przy pierwszym uruchomieniu (folder runtime).": "Downloaded on first launch (the runtime folder).",
    "Modele rozpoznawania mowy (Whisper)": "Speech recognition models (Whisper)",
    "Modele AI pobrane przez aplikację (Ollama)": "AI models downloaded by the app (Ollama)",
    "Ollama": "Ollama",
    "Zainstalowana przez aplikację.": "Installed by the app.",
    "Była na komputerze przed aplikacją albo zainstalowano ją osobno – zostaje.":
        "It was on this computer before the app or was installed separately – it stays.",
    "Ustawienia, log, pamięć podręczna": "Settings, log, cache",
    "Ustawienia aplikacji, dziennik zdarzeń i pliki tymczasowe.": "App settings, event log and temporary files.",
    "Skróty na pulpicie i w menu Start": "Desktop and Start menu shortcuts",
    "Pliki programu": "Program files",
    "Wykłady.app trafi do Kosza.": "Wykłady.app will be moved to the Trash.",
    "Moje notatki, nagrania i fiszki": "My notes, recordings and flashcards",
    "{app} – odinstalowywanie": "{app} – uninstalling",
    "Usuwam to, co zainstalowała aplikacja": "Removing what the app installed",
    "tryb próbny – nic nie jest usuwane": "dry run – nothing is removed",
    "Odinstalowywanie": "Uninstalling",
    "Nie wyłączaj komputera – to potrwa chwilę.": "Don't turn off the computer – this will take a moment.",
    "Gotowe – zwolniono {x}": "Done – {x} freed",
    "Nie wszystko się udało – {title}: {note}": "Not everything worked – {title}: {note}",
    "Python i biblioteki": "Python and libraries",
    "Modele mowy (Whisper)": "Speech models (Whisper)",
    "Modele AI (Ollama)": "AI models (Ollama)",
    "Ustawienia i log": "Settings and log",
    "Skróty": "Shortcuts",
    "Notatki i nagrania": "Notes and recordings",
    "szczegóły w logu": "details in the log",
    "Reszta plików usunie się sama zaraz po zamknięciu aplikacji.":
        "The remaining files will be removed automatically right after the app closes.",
    "Na koniec usuń sam pakiet: po kliknięciu „Zamknij” otworzą się Ustawienia Windows – kliknij SlideScribe → "
    "Odinstaluj.":
        "Finally, remove the package itself: after you click “Close”, Windows Settings will open – click "
        "SlideScribe → Uninstall.",
    "Wszystko usunięte.": "Everything removed.",
    "Sprzątanie po zamknięciu": "Cleanup after closing",
    "Zatrzymuję Ollamę i zwalniam modele…": "Stopping Ollama and unloading models…",
    "Usuwam modele AI…": "Removing AI models…",
    "Przenoszę Ollamę do Kosza…": "Moving Ollama to the Trash…",
    "Usuwam pozostałości Ollamy…": "Removing Ollama leftovers…",
    "Odinstalowuję Ollamę…": "Uninstalling Ollama…",
    "Deinstalator Ollamy nie skończył – usuń Ollamę w Ustawieniach Windows → Aplikacje.":
        "The Ollama uninstaller didn't finish – remove Ollama in Windows Settings → Apps.",
    "Usuwam model mowy {x}…": "Removing speech model {x}…",
    "Usuwam wykład: {x}": "Deleting lecture: {x}",
    "Usuwam notatki…": "Deleting notes…",
    "Usuwam skróty…": "Removing shortcuts…",
    "Usuwam ustawienia i log…": "Removing settings and log…",
    "Python i biblioteki usuną się po zamknięciu aplikacji": "Python and libraries will be removed after the app closes",
    "To folder z kodem źródłowym (git) – pliki programu zostają.":
        "This is a source code folder (git) – program files stay.",
    "Przenoszę Wykłady.app do Kosza…": "Moving Wykłady.app to the Trash…",
    "Pliki programu usuną się po zamknięciu aplikacji": "Program files will be removed after the app closes",
}

# liczba mnoga: pierwsza polska forma z tn(...) → (1 sztuka, wiele)
EN_PLURAL: dict[str, tuple[str, str]] = {
    "{n} dzień nauki z rzędu": ("{n}-day study streak", "{n}-day study streak"),
    "Seria: {n} dzień z rzędu · dziś ocenione fiszki: {today}": ("Streak: {n} day · cards reviewed today: {today}",
                                                                 "Streak: {n} days · cards reviewed today: {today}"),
    "{n} wykład": ("{n} lecture", "{n} lectures"),
    "{n} fiszka": ("{n} card", "{n} cards"),
    "{n} slajd": ("{n} slide", "{n} slides"),
    "{n} temat": ("{n} topic", "{n} topics"),
    "{n} kategoria": ("{n} category", "{n} categories"),
    "Ucz się · {n} fiszka": ("Study · {n} card", "Study · {n} cards"),
    "Plik: {name} ({n} slajd)": ("File: {name} ({n} slide)", "File: {name} ({n} slides)"),
    "dzień": ("day", "days"),
    "{n} pytanie": ("{n} question", "{n} questions"),
    "rekord: {n} dzień": ("best: {n} day", "best: {n} days"),
    "{n} dzień z rzędu": ("{n} day in a row", "{n} days in a row"),
    "{n} opanowana": ("{n} mastered", "{n} mastered"),
}
