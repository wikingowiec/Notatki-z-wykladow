# Wykłady 2.3.0 – materiały do wydania

## 1. Lista zmian – po polsku

### Wersja pełna (opis wydania na GitHubie, wiadomość tagu, strona docs/)

**Nowości**
- **Rozwiąż test z notatek.** W zakładce Egzamin jest nowy tryb „Rozwiąż test”. Wklej pytania albo wczytaj plik (.txt, .docx, .pdf), a aplikacja odpowie na nie wyłącznie na podstawie Twoich notatek, np. „1 = b, 2 = c, 3 = nie wiem”. Każda odpowiedź ma cytat z notatki i poziom pewności. Gdy odpowiedzi nie ma w notatkach, dostajesz „nie wiem” zamiast zgadywania.
- **Nagrywanie o wybranej godzinie.** Ustaw wszystko wcześniej, wybierz „O godzinie” i zostaw laptopa. Nagrywanie ruszy samo, komputer w tym czasie nie zaśnie, a aplikacja wcześniej sprawdzi, czy wszystko działa.
- **Zmiany w trakcie nagrywania.** Źródło dźwięku (np. Teams → mikrofon) i ekran albo okno ze slajdami zmienisz bez przerywania nagrania. Nowy przycisk „Wstrzymaj slajdy” (Ctrl+Shift+S) zatrzymuje zrzuty, a dźwięk nagrywa się dalej.
- **Sprawdzenie przed nagrywaniem.** Gdy nie działa Ollama, brakuje modelu albo karta graficzna nie startuje, zobaczysz jasny komunikat z przyciskiem naprawy. Nagrywać możesz zawsze, a notatki zrobią się później.
- **Fiszki na życzenie.** Fiszki powstają tylko po włączeniu „Zrób fiszki z tego wykładu” albo po kliknięciu „Wygeneruj fiszki” w bibliotece.

**Usprawnienia**
- Ekran nagrywania pojawia się od razu po kliknięciu, bez kilkunastosekundowego zawieszenia.
- Teams, Zoom, przeglądarki i Discord są na liście źródeł dźwięku od razu po uruchomieniu, zanim ktoś zacznie mówić. Lista ma wyszukiwarkę i nie zasłania już przycisków.
- Egzamin próbny powstaje dużo szybciej, maksymalnie w 25 minut. Możesz wybrać „Szybciej” albo „Dokładniej”.
- Kółko myszy przewija stronę i nie zmienia przypadkiem wartości list i suwaków.
- Wersja angielska bez polskich resztek (m.in. „play this part”, „AI description”, terminy powtórek fiszek).

### Wersja krótka („Co nowego” w Microsoft Store, maks. 1500 znaków)

- Nowe: „Rozwiąż test” – wklej pytania, a aplikacja odpowie na nie na podstawie Twoich notatek (z cytatem albo „nie wiem”).
- Nowe: nagrywanie o wybranej godzinie – ustaw wcześniej i zostaw laptopa.
- Zmiana źródła dźwięku i ekranu w trakcie nagrywania oraz przycisk „Wstrzymaj slajdy”.
- Sprawdzenie przed nagrywaniem z jasną podpowiedzią, co naprawić.
- Fiszki tylko na życzenie.
- Szybszy start nagrywania i dużo szybszy egzamin próbny (do 25 min).
- Teams i przeglądarki widoczne na liście dźwięku od razu.
- Poprawki wersji angielskiej i przewijania kółkiem myszy.

## 2. Changelog – English

### Full version (GitHub release, docs/ page)

**New**
- **Solve a test from your notes.** The Exam tab has a new “Solve a test” mode. Paste the questions or load a file (.txt, .docx, .pdf) and the app answers them using only your notes, e.g. “1 = b, 2 = c, 3 = don't know”. Every answer comes with a quote from your notes and a confidence level. If the answer isn't in your notes, you get “don't know” instead of a guess.
- **Scheduled recording.** Set everything up in advance, choose “At a time” and walk away. Recording starts on its own, the computer stays awake, and the app checks beforehand that everything works.
- **Changes while recording.** Switch the audio source (e.g. Teams → microphone) or the screen/window with slides without stopping the recording. The new “Pause slides” button (Ctrl+Shift+S) stops screenshots while audio keeps recording.
- **Pre-recording check.** If Ollama isn't running, a model is missing or the graphics card fails to start, you get a clear message with a fix button. You can always record anyway – notes will be made later.
- **Flashcards on demand.** Flashcards are made only when you turn on “Make flashcards from this lecture” or click “Generate flashcards” in the library.

**Improvements**
- The recording screen appears instantly after clicking, with no 10–15 second freeze.
- Teams, Zoom, browsers and Discord show up in the audio source list as soon as they're running, before anyone speaks. The list has a search box and no longer covers the buttons.
- Practice exams are generated much faster – 25 minutes at most. Choose “Faster” or “More accurate”.
- The mouse wheel scrolls the page instead of accidentally changing drop-downs and sliders.
- The English version no longer has Polish leftovers (e.g. “play this part”, “AI description”, flashcard review dates).

### Short version (Microsoft Store “What's new”, max. 1500 characters)

- New: “Solve a test” – paste the questions and the app answers them from your notes (with a quote, or “don't know”).
- New: scheduled recording – set it up in advance and walk away.
- Switch audio source and screen while recording, plus a “Pause slides” button.
- Pre-recording check with a clear hint on what to fix.
- Flashcards only when you want them.
- Faster recording start and much faster practice exams (up to 25 min).
- Teams and browsers appear in the audio list right away.
- English version and mouse-wheel scrolling fixes.

## 3. Testy na Windowsie przed wydaniem

Najlepiej na czystym koncie albo z kopią zapasową `%APPDATA%\WykladyAI` i biblioteki. Przy każdym punkcie: krok → oczekiwany wynik.

### A. Start i aktualizacja
1. Uruchom Wykłady.exe z obecnej wersji 2.2.x i zaktualizuj z Ustawień (po wypchnięciu tagu v2.3.0). → Po restarcie w Ustawieniach widać 2.3.0, wykłady i ustawienia zostały.
2. Uruchom świeżo rozpakowaną paczkę `Wyklady-2.3.0-Windows.zip`. → Ekran instalacji przechodzi bez błędów, okno główne się otwiera.
3. Sprawdź stronę wydania na GitHubie. → Jedyny .zip to paczka Windows, obok niej .dmg dla Maca.

### B. Lista źródeł dźwięku (etap 1)
4. Włącz Teams bez rozmowy, wejdź w „Nowa notatka”. → Teams jest w grupie „Programy do spotkań i przeglądarki” z podpisem „czeka na dźwięk”, jedna pozycja (nie kilka procesów).
5. Włącz Chrome i odtwórz YouTube. → Chrome pojawia się sam w ciągu kilku sekund, wskaźnik poziomu drga, zaznaczenie nie skacze.
6. Kliknij „Pokaż wszystkie” przy wielu źródłach. → Lista ma pasek przewijania, przyciski są pod listą, każdy wiersz da się kliknąć. Przy ponad 8 źródłach widać pole „Szukaj…”.
7. Nagraj z Teams, zamknij aplikację, otwórz ponownie. → Teams zaznaczony od razu z dopiskiem „ostatnio używane”.
8. Nagraj z Teams, który na początku nic nie gra, a potem dołącz do rozmowy. → Dźwięk z rozmowy jest w nagraniu i w transkrypcji.

### C. Start nagrywania (etapy 1–2)
9. Kliknij „Rozpocznij nagrywanie”. → Ekran nagrywania pojawia się praktycznie od razu („Uruchamiam nagrywanie…”), po kilku sekundach zaczyna płynąć czas. W logu są czasy kroków startu.
10. Kliknij „Anuluj” w trakcie uruchamiania. → Powrót do ustawień z napisem „Nagrywanie anulowane.”, w bibliotece nie ma pustego wykładu.
11. Zamknij Ollamę i wejdź w „Nowa notatka”. → W ciągu ok. 10 s pojawia się baner „Ollama nie działa…”. „Uruchom Ollamę” ją włącza, baner znika sam.
12. Usuń model notatek (`ollama rm …`). → Baner „Brakuje modelu …” z przyciskiem „Pobierz”, pobieranie z postępem.
13. Przy wyłączonej Ollamie rozpocznij nagrywanie. → Karta problemu w stylu aplikacji. „Nagrywaj mimo to” nagrywa dźwięk i slajdy, notatki da się zrobić później.
14. Ustaw Whisper na CUDA na komputerze bez działającej CUDA. → Ostrzeżenie „Transkrypcja pójdzie na procesorze (wolniej)” z przyciskiem „Przełącz na CPU”.

### D. W trakcie nagrywania (etap 3)
15. W trakcie nagrywania zmień dźwięk Teams → mikrofon. → Przerwa krótsza niż 1 s, w transkrypcji notka „zmiana źródła: …”, nagranie trwa dalej. Po zakończeniu odtwarzanie i czasy w notatkach się zgadzają.
16. Zmień monitor ze slajdami. → Pierwszy slajd z nowego ekranu się zapisuje, numeracja slajdów idzie dalej.
17. Naciśnij Ctrl+Shift+S, poprzełączaj okna, naciśnij ponownie. → Przy podglądzie napis „Slajdy wstrzymane”, w tym czasie brak nowych slajdów, po wznowieniu ten sam slajd nie dubluje się.
18. Zwęź okno do ok. 720 px. → Przyciski źródeł są w menu „⋯”, nic się nie ucina.

### E. Nagrywanie o godzinie (etap 4)
19. Wybierz „O godzinie”, ustaw za 2 min, kliknij „Zaplanuj nagrywanie”. → Ekran oczekiwania z odliczaniem, w ostatniej minucie co sekundę, w pasku bocznym „zaplanowane GG:MM”. O czasie nagrywanie rusza samo i pojawia się powiadomienie „Nagrywanie rozpoczęte”.
20. Ustaw godzinę, która już minęła. → Pod polem „jutro o …”.
21. Zaplanuj za 5 min i zostaw komputer bez dotykania (wyłączone usypianie po 1–2 min w opcjach zasilania). → Komputer nie zasypia, nagrywanie startuje. Po anulowaniu albo starcie komputer znowu może zasnąć (`powercfg /requests` nie pokazuje Wykładów).
22. Zaplanuj nagrywanie z Teams przy zamkniętym Teams. → Notka „Czekam na „Microsoft Teams”…”. Gdy Teams nadal nie działa o czasie, pojawia się pytanie o inne źródło (bez startu z niczego).
23. Zamknij okno przy zaplanowanym nagrywaniu. → Pytanie „Masz zaplanowane nagrywanie o …. Zamknąć i anulować?”.
24. Uśpij laptopa przed godziną startu i obudź 5 min po niej. → Start od razu, w transkrypcji „start spóźniony o 5 min”. Przy ponad 15 min spóźnienia: pytanie, czy zacząć.

### F. Egzamin i fiszki (etapy 5–6)
25. Wygeneruj egzamin 30 pytań z jednego wykładu ok. 60–90 min, profil Zrównoważony, „Szybciej”. → Gotowe w 5–10 min (maksymalnie 25 min), postęp z „zostało około … min”.
26. To samo z „Dokładniej”. → Wolniej, ale w limicie 25 min. Jeśli zabrakło czasu: „Udało się ułożyć X z Y pytań w wyznaczonym czasie”.
27. Nagraj nowy wykład bez włączania „Zrób fiszki z tego wykładu”. → Po notatkach brak fiszek, w bibliotece przycisk „Wygeneruj fiszki”, który robi je w tle z postępem i anulowaniem.
28. W wykładzie z fiszkami użyj „⋯ → Dodaj więcej fiszek”. → Nowe fiszki bez powtórzeń starych.

### G. Rozwiąż test (etap 7)
29. Wklej test 20–30 pytań abcd z Moodle (z „Pytanie 1”, „Wybierz jedną odpowiedź” itp.). → Podgląd „Rozpoznano N pytań…” z poprawną numeracją i literami.
30. Wczytaj ten sam test z .docx i z .pdf. → Taki sam podgląd.
31. Rozwiąż test, w którym 3 pytania są spoza notatek. → Na górze „1 = b, 2 = c, …”, pytania spoza notatek = „nie wiem”. Kliknięcie cytatu otwiera właściwe miejsce w notatce. Wynik zgadza się z kluczem w co najmniej ~80% pytań z notatek.
32. Włącz „Gdy brak w notatkach – zgadnij…” i rozwiąż ponownie. → Zgadnięte odpowiedzi ze znakiem zapytania, np. „4 = a?”.
33. „Kopiuj” i „Eksportuj .txt”. → Schowek i plik zawierają listę odpowiedzi. Test widać w historii po restarcie aplikacji.
34. 100 pytań abcd, profil Zrównoważony. → Około 15 min, widać ETA, „Anuluj” działa.

### H. Język angielski i wygląd
35. Ustawienia → Język: English, restart. Przejdź przez Nowa notatka, nagrywanie, oczekiwanie, Egzamin → Solve a test, wykład w bibliotece, Fiszki. → Brak polskich napisów interfejsu (treść notatek zostaje w języku notatki). W notatce: „play this part”, „slide 1”, „AI DESCRIPTION”. Na fiszce: „next review tomorrow / in 3 days”.
36. Pasek boczny bez serii nauki, PL i EN. → „Zacznij serię nauki” / „Start a streak” mieści się w całości.
37. Przewijaj kółkiem stronę Ustawień i Nowej notatki z kursorem nad listami i suwakami. → Strona się przewija, wartości się nie zmieniają.
38. Motywy Zeszyt / Atrament / Akademia, jasny i ciemny. → Baner, karta problemu, ekran oczekiwania i „Rozwiąż test” czytelne w każdym.
