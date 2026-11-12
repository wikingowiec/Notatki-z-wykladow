# Wykłady 2.3: prompty dla Claude Code

Masz tu 8 promptów, które wklejasz po kolei. Każdy etap to osobna sesja w Claude Code: po skończonym etapie wpisz `/clear`, przetestuj na Windowsie, zrób commit i dopiero wtedy wklej kolejny prompt.

Kolejność ma znaczenie:
- etap 4 (start o godzinie) korzysta z szybkiego startu z etapu 1 i ze sprawdzania z etapu 2;
- etap 7 (rozwiązywanie testu) korzysta z przyspieszeń z etapu 5.

| Etap | Co robi | Twoje punkty |
|---|---|---|
| 1 | Scroll, lista źródeł dźwięku, natychmiastowe przejście do nagrywania | 1, 2, 4 |
| 2 | Szybkie sprawdzenie przed nagrywaniem i baner „Ollama nie działa” | 5 |
| 3 | Zmiany w trakcie nagrywania: dźwięk, okno, wstrzymanie slajdów | 6 |
| 4 | Nagrywanie o wybranej godzinie | 3 |
| 5 | Szybszy egzamin (maksymalnie 25 min) | 7 |
| 6 | Fiszki na życzenie | 8 |
| 7 | Rozwiązywanie testu z notatek („odwrócony egzamin”) | 9 |
| 8 | Wersja 2.3.0, tłumaczenia, ostatnie sprawdzenie | – |

---

## Etap 1: scroll, lista źródeł dźwięku, szybkie przejście do nagrywania

```
Przeczytaj CLAUDE.md. Robimy wersję 2.3 aplikacji Wykłady. To jest etap 1 z 8: trzy usprawnienia, na które narzekają użytkownicy.

1) KÓŁKO MYSZY NIE ZMIENIA WYBORU
Teraz przewijanie strony kółkiem myszy zmienia wartość listy rozwijanej, pola liczbowego albo suwaka, kiedy kursor przypadkiem
na nim stanie. To ma zniknąć w całej aplikacji:
- Dotyczy QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QSlider oraz własnych kontrolek z ui/controls.py, jeśli reagują na kółko
  (np. SegmentedControl).
- Zrób to w jednym miejscu: filtr zdarzeń zainstalowany na QApplication w main.py albo funkcja w controls.py wołana przy starcie.
  Nie poprawiaj każdego pola z osobna.
- Kółko nad takim polem ma przewijać stronę (zdarzenie przekazane do rodzica albo QScrollArea), a nie stać w miejscu.
- Wartość zmienia się dalej kliknięciem, klawiaturą i strzałkami, gdy pole ma fokus.
- Fokus nie może wpadać do pola od samego najechania kursorem. Ustaw FocusPolicy na StrongFocus.

2) LISTA „ŹRÓDŁO DŹWIĘKU” (ui/audio_picker.py, app/audio_capture.py)
a) Błąd z układem. Po kliknięciu „Pokaż wszystkie” lista wchodzi pod przyciski „Odsłuchaj / Odśwież / Pokaż mniej”. Wiersze są ucięte
   i nie da się ich kliknąć. Wysokość listy jest ustawiana przez setFixedHeight, a karta wokół niej nie rośnie.
   - Ustaw układ tak, żeby przyciski były zawsze pod listą i nigdy jej nie zasłaniały.
   - Lista ma mieć rozsądną maksymalną wysokość i własny pasek przewijania.
   - Każdy wiersz musi dać się kliknąć.
   - Sprawdź zrzutami przy 25 źródłach, przy szerokościach okna 720 i 1366 px, w motywie jasnym i ciemnym.
b) Gdy źródeł jest więcej niż 8, nad listą ma być pole „Szukaj…”, które filtruje po nazwie aplikacji i urządzenia.
c) Teams (i inne programy do wykładów) muszą być widoczne, zanim ktoś zacznie mówić. Teraz lista bierze aplikacje tylko z sesji audio
   Windows (pycaw), więc Teams pojawia się dopiero, gdy wyda dźwięk. Zmień to tak:
   - Dodaj grupę „Programy do spotkań i przeglądarki” na samej górze. Pokazuj w niej uruchomione procesy z tej listy, nawet jeśli
     nic nie grają: ms-teams.exe, Teams.exe, Zoom.exe, msedge.exe, chrome.exe, firefox.exe, opera.exe, brave.exe, Discord.exe,
     Webex (CiscoCollabHost.exe, webexmta.exe), slack.exe.
   - Listę procesów bierz bez nowych zależności, np. przez ctypes (CreateToolhelp32Snapshot albo EnumProcesses), w tle,
     bez blokowania UI.
   - Teams, przeglądarki i Discord mają wiele procesów. Pokazuj jedną pozycję na aplikację i nagrywaj z procesu-korzenia
     z flagą INCLUDE_TARGET_PROCESS_TREE.
   - Sprawdź w wasapi_process_loopback.py i audio_capture.py, czy nagrywanie procesu, który jeszcze nic nie gra, działa. Powinno,
     bo process loopback łapie dźwięk, gdy się pojawi. Jeśli nie da się tego sprawdzić na Linuksie, napisz, co mam przetestować.
   - Taki wiersz ma podpis „czeka na dźwięk” zamiast „teraz cisza”. Gdy dźwięk się pojawi, wskaźnik poziomu po prostu zaczyna drgać.
   - Zapamiętuj ostatnio wybraną aplikację po nazwie exe (jest już settings.last_rec). Gdy przy następnym nagrywaniu jest uruchomiona,
     zaznacz ją od razu i dopisz „ostatnio używane”.
   - Lista ma się sama odświeżać co kilka sekund, gdy jest widoczna, bez zmiany zaznaczenia i bez skakania pozycji.
   - Mac (mac_audio.py) ma działać jak dotąd. Jeśli łatwo dodać to samo na Macu, zrób to, ale nie kosztem Windowsa.

3) NATYCHMIASTOWE PRZEJŚCIE DO EKRANU NAGRYWANIA (ui/record_tab.py start(), app/session.py start())
Po kliknięciu „Rozpocznij nagrywanie” aplikacja zamarza na 10–15 s i dopiero potem pokazuje ekran nagrywania. W tle wszystko
działa, ale użytkownik myśli, że przycisk nie zadziałał.
- Najpierw zmierz, co blokuje wątek UI. Dodaj do logu czasy kolejnych kroków (import faster_whisper / ctranslate2, engine_for,
  AudioRecorder.start, make_grabber, SlideStore / OCR, live notes, zapisy plików). Podaj mi wyniki.
- Potem przebuduj start tak:
  - W wątku UI zostaje tylko to, co szybkie: zebranie ustawień, Lecture.create i przełączenie stacka na ekran nagrywania
    w stanie „Uruchamiam nagrywanie…”. Pokaż szkielet paneli, puls przy kropce nagrywania i nieaktywne przyciski oprócz „Anuluj”.
  - Cięższe kroki z RecordingSession.start() idą do wątku roboczego. Wynik wraca do UI sygnałem Qt.
  - Gdy start się uda: zwykły widok nagrywania, timer od faktycznego startu dźwięku.
  - Gdy start się nie uda: powrót do ekranu ustawień z komunikatem i takim samym sprzątaniem jak teraz (usunięcie folderu nowego
    wykładu, przywrócenie stanu kontynuowanego wykładu).
- Dodatkowo, gdy użytkownik wchodzi na „Nowa notatka”, zaimportuj w tle faster_whisper i ctranslate2 (sam import, bez ładowania
  modelu). Dzięki temu późniejszy start będzie szybszy.
- Cel: ekran nagrywania widać w mniej niż 0,3 s od kliknięcia.

Zasady:
- Teksty UI przez tr(); angielskie tłumaczenia dopisz w app/i18n_en.py.
- Kolory przez T(). Bez kolorów na sztywno.
- `python -m pyflakes _internal/app _internal/main.py` ma być czyste.
- Zrzuty ekranu offscreen (QT_QPA_PLATFORM=offscreen) listy źródeł i stanu „Uruchamiam nagrywanie…”.
- Bez commita. Na koniec podaj: listę zmienionych plików, co dokładnie mam sprawdzić na Windowsie (Teams przed rozmową, Chrome,
  czas startu) i propozycję opisu commita.
```

---

## Etap 2: szybkie sprawdzenie przed nagrywaniem i baner Ollamy

```
Przeczytaj CLAUDE.md. Etap 2 z 8 wersji 2.3. Etap 1 (natychmiastowe przejście do ekranu nagrywania) jest już zrobiony.

CEL
Przed rozpoczęciem nagrywania aplikacja szybko sprawdza, czy wszystko działa. Jeśli tak, użytkownik niczego nie widzi i nagrywanie
startuje normalnie. Jeśli nie, dostaje jasny komunikat, co nie działa i jak to naprawić.

1) NOWY MODUŁ app/healthcheck.py
Funkcja run_checks(settings, audio, video, live_notes: bool) -> list[Problem].
Problem to: klucz, tytuł, opis, kroki naprawy (lista), opcjonalna akcja naprawy i flaga „krytyczny”.
Sprawdzenia mają iść równolegle, w tle, łącznie maksymalnie około 3 s:
- Transkrypcja:
  - faster_whisper i ctranslate2 się importują;
  - pliki wybranego modelu Whispera są na dysku (bez ładowania całego modelu);
  - jeśli whisper_device to cuda albo auto z NVIDIA, sprawdź, czy CUDA naprawdę się inicjalizuje
    (ctranslate2.get_cuda_device_count() i biblioteki cuBLAS/cuDNN).
  - Gdy CUDA nie działa: ostrzeżenie „Transkrypcja pójdzie na procesorze (wolniej)” z akcją „Przełącz na CPU”. To nie jest
    błąd krytyczny.
- Ollama:
  - serwer odpowiada (ollama_local.is_up);
  - potrzebne modele są pobrane (/api/tags): ollama_model, live_model (gdy notatki na żywo), vision_model (gdy opis slajdów).
  - Gdy notatki na żywo są włączone, zrób jedno krótkie wywołanie live_model z num_predict=1 i keep_alive, żeby model był od razu
    załadowany. To wywołanie może trwać dłużej i nie blokuje startu.
- Źródło dźwięku wciąż istnieje (proces działa albo urządzenie jest podłączone).
- Źródło slajdów daje jeden zrzut ekranu.
- Jest miejsce na dysku w folderze biblioteki (ostrzeżenie poniżej 2 GB).

2) PODPIĘCIE DO STARTU NAGRYWANIA
- Sprawdzenie rusza równolegle z przejściem do ekranu „Uruchamiam nagrywanie…” z etapu 1.
- Gdy wszystko OK: nic nie pokazuj.
- Gdy coś nie działa: na ekranie nagrywania pokaż kartę (nie systemowy QMessageBox) w stylu aplikacji, np.
  „Transkrypcja nie działa”. Pod nią: krótko dlaczego, kroki naprawy po kolei i przyciski:
  - akcja naprawy, jeśli istnieje: „Uruchom Ollamę”, „Pobierz model”, „Przełącz na CPU”, „Wybierz inne źródło”;
  - „Nagrywaj mimo to”;
  - „Anuluj”.
- Zasada nadrzędna: nagranie wykładu jest najważniejsze. Gdy nie działa tylko AI (Ollama albo Whisper), „Nagrywaj mimo to” nagrywa
  dźwięk i slajdy, a transkrypcja i notatki zrobią się później. Napisz to w komunikacie wprost.
- Komunikat ma być zrozumiały dla studenta, bez żargonu. Przykład:
  „Ollama nie jest uruchomiona – bez niej nie powstaną notatki. Kliknij „Uruchom Ollamę” albo otwórz Ollamę z menu Start.”

3) BANER NA EKRANIE „NOWA NOTATKA”
- Gdy ekran nowej notatki jest widoczny, sprawdzaj Ollamę co około 10 s, w tle i tanio (tylko is_up i lista modeli, raz na jakiś
  czas).
- Gdy nie działa: dobrze widoczny baner na górze strony w kolorach ostrzegawczych motywu:
  „Ollama nie działa – notatki i odpowiedzi na pytania nie powstaną” z przyciskiem „Uruchom Ollamę” (ollama_local.start) i postępem.
- Gdy brakuje modelu: „Brakuje modelu X” z przyciskiem „Pobierz”. Użyj istniejącej logiki pobierania z setup/installer.py, jeśli się da.
- Baner znika sam, gdy wszystko wróci do normy.
- Taki sam, mniejszy baner dodaj w panelu pytań do notatek (ask_panel / ask_tab).

Zasady jak zwykle: tr() i tłumaczenia EN w i18n_en.py, kolory przez T(), pyflakes czysty, zrzuty offscreen karty problemu i banera
(jasny i ciemny motyw, 720 i 1366 px). Sprawdzenia mają działać także na Macu albo zostać tam pominięte bez błędu.
Bez commita: lista plików, co sprawdzić na Windowsie (wyłączona Ollama, usunięty model, brak CUDA) i propozycja opisu commita.
```

---

## Etap 3: zmiany w trakcie nagrywania

```
Przeczytaj CLAUDE.md. Etap 3 z 8 wersji 2.3: zmiany w trakcie nagrywania wykładu (app/session.py, ui/record_tab.py, ui/live_view.py).

1) ZMIANA ŹRÓDŁA DŹWIĘKU W TRAKCIE
- Na ekranie nagrywania dodaj przycisk „Dźwięk: <nazwa>”. Kliknięcie otwiera wysuwany panel albo popup z AudioSourcePicker
  (ten sam co w ustawieniach, z wyszukiwaniem i wskaźnikami poziomu).
- Po wyborze: RecordingSession.switch_audio(info).
  - Zatrzymaj obecny AudioRecorder, zamknij plik części i zacznij nową część (lecture.new_part_file(), meta.parts). Offset ma być
    zgodny z czasem wykładu, żeby oś czasu, transkrypcja i slajdy się nie rozjechały.
  - LiveTranscriber ma dalej działać, bez ponownego ładowania Whispera.
  - Przerwa w nagraniu ma być jak najkrótsza (poniżej 1 s). Zanotuj ją w meta.
- W transkrypcji wstaw notkę „zmiana źródła: Teams → Chrome”.
- Gdy nowe źródło nie da się otworzyć: wróć do poprzedniego i pokaż komunikat. Nagranie nie może się przerwać.

2) ZMIANA OKNA / EKRANU ZE SLAJDAMI W TRAKCIE
- Przycisk „Slajdy: <nazwa>” otwiera wybór ekranu albo okna (ta sama lista co w ustawieniach) i opcjonalnie zaznaczenie obszaru
  (jest już btn_live_roi i set_roi).
- RecordingSession.switch_video(info, roi): podmień grabber w SlideRecorder. Zachowaj SlideStore, numerację slajdów i oś czasu.
  Pierwszy kadr z nowego źródła nie może zostać fałszywie uznany za duplikat ani zgubiony.

3) PRZYCISK „WSTRZYMAJ SLAJDY”
- Przełącznik „Wstrzymaj slajdy / Wznów slajdy” działa niezależnie od pauzy całego nagrania. Dźwięk i transkrypcja idą dalej.
- Przydaje się, gdy prowadzący pokazuje coś, czego nie chcemy w notatkach, albo gdy użytkownik przełącza okna.
- W czasie wstrzymania przy podglądzie slajdu ma być widoczny napis „Slajdy wstrzymane”.
- Po wznowieniu bieżący ekran porównaj z ostatnim zapisanym slajdem, żeby nie dublować.
- Dodaj skrót klawiszowy, np. Ctrl+Shift+S, i pokaż go w podpowiedzi.

Układ: przyciski mają się mieścić we wszystkich trybach ekranu nagrywania (szeroki / średni / wąski). W wąskim schowaj je do menu „⋯”.
Zasady jak zwykle: tr() + i18n_en.py, T(), pyflakes, zrzuty offscreen trzech trybów szerokości.
Bez commita: lista plików, co sprawdzić na Windowsie (zmiana Teams → mikrofon w trakcie, zmiana monitora, wstrzymanie slajdów)
i propozycja opisu commita.
```

---

## Etap 4: nagrywanie o wybranej godzinie

```
Przeczytaj CLAUDE.md. Etap 4 z 8 wersji 2.3: nagrywanie z opóźnieniem. Etapy 1–3 są zrobione (szybki start, healthcheck.py,
zmiany źródeł w trakcie).

JAK MA DZIAŁAĆ
1) Na ekranie „Nowa notatka”, przy przycisku startu, dodaj wybór „Rozpocznij: Teraz | O godzinie”.
   - Domyślnie zawsze „Teraz”.
   - Po wybraniu „O godzinie” pojawia się pole godziny (QTimeEdit, HH:MM). Domyślnie najbliższy pełny kwadrans.
   - Gdy wpisana godzina już minęła, chodzi o jutro. Pokaż to pod polem: „jutro o 8:15”.
   - Przycisk zmienia napis na „Zaplanuj nagrywanie”.
2) Użytkownik ustawia wszystko jak zwykle (dźwięk, slajdy, tytuł, przedmiot) i klika przycisk. Nagrywanie się nie włącza.
   Aplikacja przechodzi na ten sam ekran co przy nagrywaniu, w stanie oczekiwania:
   - na środku duży napis „Nagrywanie rozpocznie się za 10 min”, a pod nim „o 10:15 · Teams · slajdy: Ekran 1”;
   - w ostatniej minucie odliczanie co sekundę;
   - przyciski „Zacznij teraz”, „Zmień godzinę”, „Anuluj”;
   - w pasku bocznym przy „Nowa notatka” informacja „zaplanowane 10:15”.
3) W czasie oczekiwania:
   - zaraz po zaplanowaniu uruchom sprawdzenie z healthcheck.py. Gdy coś nie działa, pokaż kartę problemu od razu, żeby był czas
     to naprawić;
   - około 2 min przed startem sprawdź jeszcze raz i rozgrzej modele (Whisper w tle, live_model w Ollamie z keep_alive), żeby start
     był natychmiastowy;
   - jeśli wybrana aplikacja (np. Teams) jeszcze nie działa, poczekaj na nią. W chwili startu, gdy jej nadal nie ma, pokaż komunikat
     i daj wybór innego źródła. Nie startuj z niczego bez pytania;
   - komputer nie może zasnąć: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) na Windowsie, `caffeinate` na Macu.
     Wyłącz to po starcie albo po anulowaniu. Nagrywanie ma swoje własne ustawienie;
   - zamknięcie okna aplikacji pyta: „Masz zaplanowane nagrywanie o 10:15. Zamknąć i anulować?”.
4) O czasie: start dokładnie tą samą ścieżką co zwykłe „Rozpocznij nagrywanie”, z tymi samymi ustawieniami. Do tego powiadomienie
   systemowe (QSystemTrayIcon.showMessage albo to, czego aplikacja już używa): „Nagrywanie rozpoczęte”.
5) Gdy komputer jednak spał i obudził się po czasie:
   - do 15 min spóźnienia zacznij od razu i dopisz w transkrypcji notkę „start spóźniony o X min”;
   - powyżej 15 min zapytaj, czy zacząć.
6) Używaj zegara ściennego (datetime) do wyznaczenia chwili startu, ale sprawdzaj go timerem co sekundę, żeby zmiana czasu i
   wybudzenie działały poprawnie. Timer nie może blokować UI.

Plan oczekiwania trzymaj tylko w pamięci, bez zapisu do pliku. Po restarcie aplikacji plan znika i to jest OK. Napisz to w opisie.
Zasady jak zwykle: tr() + i18n_en.py, T(), pyflakes, zrzuty offscreen ekranu oczekiwania (10 min, 45 s, problem z healthcheck)
w jasnym i ciemnym motywie. Bez commita: lista plików, co sprawdzić na Windowsie (zaplanuj za 2 min, uśpij ekran, zostaw laptopa)
i propozycja opisu commita.
```

---

## Etap 5: egzamin ma powstawać w maksymalnie 25 minut

```
Przeczytaj CLAUDE.md. Etap 5 z 8 wersji 2.3: generowanie egzaminu (app/exam.py generate_exam, ui/exam_tab.py) trwa u użytkownika
około 3 godzin. Ma trwać maksymalnie 25 minut, a najlepiej 5–10 minut dla 20–30 pytań.

1) NAJPIERW POMIAR
Dodaj do logu dla każdej partii: liczbę znaków i tokenów promptu, num_ctx, czas odpowiedzi (prompt_eval i eval z odpowiedzi Ollamy),
ile pytań przyszło, ile odrzucono i z jakiego powodu (_normalize, verify_quote, duplikat). Podejrzenia do sprawdzenia w kodzie:
- każda partia wysyła do 8 fragmentów, około 0,55·num_ctx·3 znaków przy num_ctx 16384, do modelu 11B. Przy częściowym offloadzie
  na CPU jedna partia może trwać kilka minut;
- verify_quote odrzuca dużo pytań (cytat lekko zmieniony przez model), więc pętla robi aż n//2+6 partii;
- k=min(6, …) pytań na partię to mało;
- egzamin startuje, gdy w Ollamie jest jeszcze załadowany inny model albo inny num_ctx, więc model się przeładowuje.

2) POPRAWKI (dobierz po pomiarze, opisz, co dało ile)
- Mniejszy kontekst: stały num_ctx około 8192 na całe zadanie, mniej fragmentów na partię (2–4) i więcej pytań z partii (8–10),
  z limitem num_predict. Model odpowiada wtedy szybciej i rzadziej się myli.
- Luźniejsza weryfikacja cytatu: dopasowanie przybliżone (np. 80% słów cytatu po normalizacji występuje we fragmencie), zamiast
  odrzucania pytania. Nie może przepuścić pytań wymyślonych spoza notatek.
- Przed startem zwolnij inne modele (unload) i trzymaj model egzaminu załadowany (keep_alive) do końca.
- Budżet czasu: twardy limit 25 min. Gdy się kończy, egzamin zapisuje się z tym, co jest, a użytkownik dostaje informację
  „Udało się ułożyć 24 z 30 pytań w wyznaczonym czasie”.
- Postęp z szacowanym czasem: „Układam pytania… 12/30 · zostało około 4 min”. Szacunek liczony z czasu dotychczasowych partii.
- Na profilu Lekki albo przy braku NVIDIA domyślnie użyj live_model (4.5B) do układania pytań abcd. W oknie tworzenia egzaminu
  dodaj wybór „Szybciej / Dokładniej”. Domyślny zależy od profilu.
- Pytania abcd i prawda/fałsz można brać też z istniejących fiszek wykładu jako szkielet. Rozważ to, jeśli przyspiesza.
- Ocena pytań otwartych (grade_open) też ma być szybka: mały kontekst, ten sam załadowany model.

3) SPRAWDZENIE
Napisz skrypt w scratchpadzie (nie w repo), który na fałszywym LLM (mock z opóźnieniem proporcjonalnym do długości promptu) porówna
starą i nową wersję: liczba wywołań, łączna długość promptów, odsetek odrzuconych pytań. Podaj wyniki. Prawdziwy czas sprawdzę
na Windowsie. Napisz dokładnie, jaki egzamin mam wygenerować i ile ma to trwać.

Zasady jak zwykle: tr() + i18n_en.py, T(), pyflakes. Bez commita: lista plików, wyniki pomiaru i propozycja opisu commita.
```

---

## Etap 6: fiszki na życzenie

```
Przeczytaj CLAUDE.md. Etap 6 z 8 wersji 2.3: fiszki mają powstawać tylko wtedy, gdy użytkownik ich chce.

1) W ustawieniach nagrywania na ekranie „Nowa notatka” (i w imporcie z plików) dodaj przełącznik „Zrób fiszki z tego wykładu”.
   - Domyślnie wyłączony. Nowe pole w Settings: auto_flashcards: bool = False. Istniejący użytkownicy też dostają False.
   - Wybór zapamiętuj w settings.last_rec jak inne opcje.
   - Zapisuj go w meta wykładu (np. meta.make_flashcards).
2) notes_pipeline.generate(): gdy meta.make_flashcards jest False, pomiń krok fiszek. Postęp i ETA mają to uwzględniać (krok
   znika z listy kroków). Obecne fiszki wykładu, jeśli już są, zostają.
3) W widoku wykładu w bibliotece (library_tab):
   - gdy fiszek nie ma: przycisk „Wygeneruj fiszki”;
   - gdy są: w menu „⋯” opcja „Dodaj więcej fiszek”.
   - Uruchamia to tylko krok fiszek z gotowego notes.md (bez ponownej transkrypcji i notatek), jako zadanie w tle przez jobs.py,
     z postępem, anulowaniem i ETA.
   - Wydziel z notes_pipeline funkcję generate_flashcards(lecture, settings, …), której używa i pipeline, i ten przycisk. Logika
     „bez powtórzeń” z łączeniem ze starymi fiszkami ma zostać.
4) Zakładka nauki (study_tab) i licznik „Ucz się · N fiszek”: gdy wykład nie ma fiszek, pokaż krótką podpowiedź z przyciskiem
   „Wygeneruj fiszki” zamiast pustego miejsca.
5) Seria nauki i cel dzienny mają działać bez zmian.

Zasady jak zwykle: tr() + i18n_en.py (tn() dla liczebników), T(), pyflakes, zrzuty offscreen widoku wykładu bez fiszek i z fiszkami.
Bez commita: lista plików, co sprawdzić na Windowsie i propozycja opisu commita.
```

---

## Etap 7: rozwiązywanie testu z notatek („odwrócony egzamin”)

```
Przeczytaj CLAUDE.md. Etap 7 z 8 wersji 2.3: największa nowa funkcja. Etap 5 (szybszy egzamin) jest zrobiony. Korzystaj z jego
ustawień modelu, kontekstu i budżetu czasu.

POMYSŁ
Użytkownik wkleja albo wczytuje gotowy test, np. 100 pytań abcd z biologii. Aplikacja rozpoznaje pytania, odpowiada na nie WYŁĄCZNIE
na podstawie notatek z wybranego zakresu i zwraca zwięzłą listę: „1 = b, 2 = c, 3 = nie wiem…”. Gdy odpowiedzi nie ma w notatkach,
zwraca „nie wiem”, a nie zgaduje.

1) GDZIE W APLIKACJI
- W zakładce „Egzamin” dodaj drugi tryb „Rozwiąż test” obok obecnego „Sprawdź się”, np. SegmentedControl na górze. Nie rób nowej
  pozycji w pasku bocznym.
- Krok 1, wejście:
  - duże pole tekstowe „Wklej pytania”;
  - przycisk „Wczytaj z pliku” (.txt, .docx, .pdf z warstwą tekstu; do odczytu użyj bibliotek, które już są w requirements,
    a jeśli trzeba dodać nową, zapytaj mnie najpierw);
  - zakres notatek jak w egzaminie: wykład / przedmiot / wszystko;
  - przełącznik „Gdy brak w notatkach – zgadnij z wiedzy ogólnej”, domyślnie wyłączony. Zgadnięte odpowiedzi oznaczaj osobno,
    np. „4 = a?”.
- Krok 2, podgląd rozpoznanych pytań: „Rozpoznano 100 pytań (96 abcd, 4 otwarte)”, lista z numerem, treścią i opcjami.
  Można poprawić, usunąć albo scalić pytanie, zanim ruszy rozwiązywanie.
- Krok 3, rozwiązywanie w tle (jobs.py), z postępem, ETA i anulowaniem. Wyniki pojawiają się na bieżąco.
- Krok 4, wynik:
  - na górze zwięzła lista „1 = b, 2 = c, 3 = nie wiem, …” z przyciskiem „Kopiuj”, w formacie do wklejenia;
  - poniżej szczegóły każdego pytania: wybrana odpowiedź, pewność (wysoka / średnia / niska), cytat z notatki z linkiem do miejsca
    w notatce (jak źródła w egzaminie i w pytaniach do notatek);
  - eksport do .txt;
  - historia rozwiązanych testów zapisywana w bibliotece, obok egzaminów.

2) ROZPOZNAWANIE PYTAŃ (nowy moduł app/solver.py)
- Najpierw parser regułowy, bez AI:
  - numeracja „1.”, „1)”, „Pytanie 1”, „Zad. 1”;
  - opcje „a)”, „A.”, „(a)”, „a.”, „A:” i warianty w nowych liniach albo w jednej linii;
  - pytania wielokrotnego wyboru („zaznacz wszystkie poprawne”);
  - prawda/fałsz;
  - pytania otwarte (brak opcji).
  - Napisz testy parsera na kilku formatach (w tym wklejka z Moodle / MS Forms z dodatkowymi śmieciami) w scratchpadzie
    albo jako lekki test w repo, jeśli jest katalog testów.
- Gdy parser nie daje rady (mało pytań albo nieregularny tekst): AI dzieli tekst na pytania partiami, z JSON-em.
- Zachowaj oryginalną numerację i oryginalne litery odpowiedzi z testu. Wynik ma używać tych samych liter.

3) ODPOWIADANIE
- Dla każdego pytania znajdź w notatkach z zakresu najlepsze fragmenty: qa.rank / select_context (treść pytania + wszystkie opcje
  jako zapytanie).
- Pytaj model partiami (np. 4–6 pytań na wywołanie, każde z własnymi fragmentami). Stały num_ctx, ten sam załadowany model, limit
  num_predict. JSON na każde pytanie: {nr, odpowiedź: "b" | "a,c" | "nie wiem", pewność, cytat, krótkie uzasadnienie}.
- Potwierdzenie: cytat musi się znaleźć we fragmencie (qa.verify_quote albo przybliżone dopasowanie z etapu 5). Bez potwierdzenia
  odpowiedź zamienia się na „nie wiem”, chyba że włączone jest zgadywanie (wtedy „?”).
- Wynik ma być deterministyczny: temperature 0.
- Cel czasu: 100 pytań abcd w około 15 min na profilu Zrównoważony. Pokaż ETA. Budżet czasu i informacja, ile zostało bez
  odpowiedzi, jak w egzaminie.

4) JAKOŚĆ
- Przygotuj w scratchpadzie mały zestaw testowy: notatka + 15 pytań z kluczem, w tym 3 pytania spoza notatek.
- Sprawdź na fałszywym LLM, że przepływ, parsowanie, numeracja i „nie wiem” działają.
- Napisz, jak mam sprawdzić prawdziwą trafność na Windowsie.

Zasady jak zwykle: tr() + i18n_en.py, T(), pyflakes, zrzuty offscreen wszystkich 4 kroków (jasny i ciemny motyw, 720 i 1366 px).
Duże UI rób etapami i pokazuj zrzuty. Bez commita: lista plików i propozycja opisu commita.
```

---

## Etap 8: wersja 2.3.0 i sprzątanie

```
Przeczytaj CLAUDE.md. Ostatni etap wersji 2.3.

1) Podbij VERSION w _internal/app/version.py na 2.3.0.
2) Przejrzyj wszystkie nowe teksty z etapów 1–7. Każdy ma przechodzić przez tr() / tn() i mieć tłumaczenie w i18n_en.py.
   Przy okazji popraw znane resztki po polsku w wersji EN: „odtwórz fragment”, „slajd”, „OPIS AI”, „jutro” oraz ucięty przycisk
   „Zacznij serię…”.
3) Uruchom pyflakes i zrób zrzuty offscreen głównych ekranów (Nowa notatka, ekran nagrywania, oczekiwanie na start, Egzamin →
   Rozwiąż test, wykład w bibliotece) w PL i EN, w jasnym i ciemnym motywie. Pokaż mi je.
4) Przygotuj krótką listę zmian 2.3.0 po polsku i po angielsku. Przyda się do opisu wydania na GitHubie, do „Co nowego” w Sklepie
   Microsoft i do strony docs/.
5) Przygotuj listę testów do zrobienia na Windowsie przed wydaniem (punkt po punkcie, z oczekiwanym wynikiem).

Bez commita i bez taga. Wydanie zrobię sam: commit, push, a potem tag v2.3.0. Na koniec lista plików i propozycja opisu commita.
```

---

Po wydaniu 2.3.0 na GitHubie trzeba zbudować nową paczkę do Sklepu: `msix\build_msix.ps1` z wersją 2.3.0.0, a potem nowe zgłoszenie w Partner Center.
