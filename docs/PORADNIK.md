# Poradnik

Po lewej jest pasek boczny:

| Pasek boczny | Co tam jest |
|---|---|
| **Nowa notatka** | Nowe nagranie albo notatka z plików. W trakcie nagrywania obok pozycji widać czerwoną kropkę i czas. |
| **Biblioteka → Wszystkie wykłady / przedmioty** | Lista wykładów, a po prawej notatki, slajdy, transkrypcja i fiszki wybranego wykładu. |
| **Nauka → Fiszki** | Nauka z fiszek: ze wszystkich, z jednego przedmiotu albo z jednego wykładu. Liczba obok to fiszki do opanowania. |
| **Ustawienia** (na dole) | Zmiany zapisują się od razu. |

Gdy AI pracuje w tle, na dole paska bocznego pojawia się karta postępu. Kliknięcie jej przenosi do tego wykładu.

## Jak wyglądają notatki
Każdy temat wykładu ma ten sam, czytelny układ:
- **W skrócie**: jedno–dwa zdania, o czym jest fragment,
- punkty z **pogrubionymi pojęciami**; 1–3 najważniejsze fakty są podświetlone jak zakreślaczem,
- kolorowe ramki: **Definicja**, **Wzór**, **Przykład**, **Ważne** (to, co prowadzący podkreślał),
- pod każdym slajdem podpis, a gdy na slajdzie jest zdjęcie, schemat, wykres albo tabela, ramka **Na slajdzie** z opisem, co przedstawia.

Opisy slajdów robi drugi lokalny model, który „widzi” obrazy (Qwen3-VL 8B, ok. 6 GB, pobiera się przy instalacji albo sam przy pierwszym użyciu). Przy okazji dokładniej odczytuje tekst i wzory ze slajdów. Dodaje ok. 5 s na slajd po wykładzie. Wyłączysz to w Ustawienia → Notatki AI → „Opisuj obrazy na slajdach”.

Starsze notatki dostaną nowy układ po kliknięciu **Generuj ponownie**. Eksport do HTML i PDF ma ten sam wygląd (HTML także w trybie ciemnym). W edycji notatki zakreślenie to `==tekst==`, a ramka to akapit zaczynający się od `> **Definicja:**` (albo Wzór, Przykład, Ważne).

## Wygląd i układ okna
- **Jasny motyw** wygląda jak papier z zeszytu, a **ciemny** jak zielona tablica (Ustawienia → Wygląd). Każdy przedmiot ma własny kolor: kropkę w pasku bocznym, pasek na liście wykładów i górny pasek fiszki.
- Układ sam dopasowuje się do okna:
  - **szeroki monitor (21:9)**: formularz „Nowa notatka” w dwóch kolumnach; w trakcie nagrywania transkrypcja, notatki i slajdy obok siebie; obok notatki w bibliotece spis treści,
  - **zwykły (16:9)**: układ jak dotąd,
  - **pionowy (9:16) albo wąskie okno**: pasek boczny zwija się do samych ikon (przedmioty jako kolorowe literki), biblioteka pokazuje najpierw listę, a po kliknięciu notatkę z przyciskiem „‹ Wykłady”; slajdy w trakcie nagrywania są w pasku pod notatkami.
- **Rozmiar interfejsu** (Ustawienia → Ogólne): 90–150%, np. większy na dużym monitorze. Zmiana działa po ponownym uruchomieniu.

## Nowa notatka: rodzaje
Na górze karty wybierasz rodzaj notatki:

| Rodzaj | Co robi |
|---|---|
| **Dźwięk + slajdy** | Nagrywa dźwięk wykładu i łapie slajdy z ekranu (jak dotąd). |
| **Tylko dźwięk** | Tylko nagranie z aplikacji albo mikrofonu. Notatki powstają z tego, co mówi prowadzący. |
| **Tylko slajdy** | Bez dźwięku. Aplikacja robi zrzuty kolejnych slajdów, odczytuje z nich tekst i robi notatki z treści slajdów. |
| **Z pliku** | Wgrywasz własne nagranie i opcjonalnie zdjęcia slajdów. |

## Z pliku (Dyktafon z iPhone'a, mp3, wideo)
1. Wybierz **Z pliku** i kliknij **„Dodaj nagranie…”** albo przeciągnij pliki do okna. Działa m.in. `.m4a` (Dyktafon z iPhone'a), `.mp3`, `.wav`, `.mp4`, `.mov`. Kilka plików to kolejne części jednego wykładu, w podanej kolejności.
2. Opcjonalnie dodaj **zdjęcia slajdów** z telefonu (JPG, PNG albo **HEIC** z iPhone'a).
   - **„Wyprostuj zdjęcia”** wycina slajd ze zdjęcia robionego pod kątem i prostuje perspektywę. Gdy nie jest pewne, gdzie jest slajd, zostawia zdjęcie bez zmian.
   - Aplikacja sama ustala, do którego momentu nagrania pasuje zdjęcie. Najpierw porównuje **godzinę zrobienia zdjęcia** z godziną nagrania. Gdy plik nie ma metadanych, dopasowuje zdjęcia **po treści**: porównuje tekst ze slajdu z tym, co w danej chwili mówi prowadzący, zachowując kolejność zdjęć. Zdjęcia bez tekstu trafiają między sąsiadów.
   - Najlepiej przerzucaj pliki z iPhone'a tak, żeby zachowały datę, np. AirDrop, iCloud albo kabel.
3. Kliknij **„Utwórz notatkę”**. Transkrypcja i notatki robią się w tle, a postęp widać w bibliotece.

Same zdjęcia bez nagrania też działają: powstanie notatka z treści slajdów.
Zdjęcia możesz też dołożyć do istniejącego wykładu: **więcej (…) → „Dodaj zdjęcia slajdów…”**. Notatki odświeżą się same.

## Nagrywanie
1. Włącz wykład, żeby **dźwięk już leciał**. Aplikacja pojawi się wtedy na liście z dopiskiem „gra teraz”.
2. **Dźwięk**: wybierz aplikację z wykładem (np. Teams albo Chrome). Na wykładzie stacjonarnym wybierz mikrofon.
   - Chrome nagrywa się w całości, ze wszystkimi kartami. To, co chcesz oglądać w tle, puszczaj w innej przeglądarce lub aplikacji.
3. **Slajdy**: wybierz monitor albo okno. Pod spodem zobaczysz podgląd. Kliknij **„Zaznacz obszar slajdu”** i obrysuj sam slajd, bez kamerki i czatu.
   - Wybrane okno może być zasłonięte, ale **nie zminimalizowane**.
4. Kliknij czerwony przycisk na dole. Pasek poziomu dźwięku powinien się ruszać, gdy prowadzący mówi.
5. W trakcie nagrywania:
   - kliknięcie miniatury slajdu po prawej **powiększa** go,
   - **„×”** w rogu miniatury **usuwa** niechciany zrzut (np. kamerkę prowadzącego). Jeśli ten sam obraz wróci, aplikacja go pominie,
   - w karcie **Transkrypcja** obok mowy widać na żywo **tekst ze slajdów**.
   
   Aplikacja rozpoznaje **powroty do wcześniejszego slajdu** (nie robi drugiej kopii) i **slajdy z animacją**, na których punkty pojawiają się po kolei: zostaje jeden slajd w pełnej wersji.
6. Kliknij kwadratowy przycisk, żeby zakończyć. Aplikacja przejdzie do wykładu w bibliotece i sama zrobi notatki oraz fiszki.

## Biblioteka
- U góry wykładu możesz przełączać między: **Notatki | Ściąga | Zapytaj | Slajdy | Transkrypcja | Fiszki**.
- **Ściąga** zbiera z notatki wszystkie **definicje, wzory, przykłady i ważne rzeczy**, pogrupowane po tematach. Przyciski u góry filtrują rodzaj, a **„pokaż w notatce”** przenosi do miejsca, z którego pochodzi dany fragment.
- **Slajdy**: kliknięcie miniatury powiększa slajd (strzałki ← → przełączają, Delete usuwa). **Tekst** pokazuje cały tekst odczytany ze slajdów w jednym miejscu, z przyciskiem **Kopiuj wszystko**.
- **Generuj notatki / Generuj ponownie** tworzy notatki od nowa, np. po zmianie modelu AI.
- Ikony obok przycisku: folder wykładu, **eksport** (HTML, PDF, Anki, Markdown) i **więcej** (zmiana nazwy, ponowna transkrypcja, usunięcie).
- **Notatka z pliku…** (na dole listy) otwiera „Nowa notatka → Z pliku”. Z pliku wideo aplikacja też wyciągnie slajdy.

## Odzyskiwanie po awarii
Jeśli aplikacja albo komputer wyłączą się w trakcie nagrywania, po ponownym uruchomieniu nagranie zostanie naprawione, a aplikacja zaproponuje dokończenie transkrypcji i notatek.

## Autostop
Gdy przez 10 minut nic nie słychać (czas zmienisz w Ustawieniach) albo zamkniesz aplikację z wykładem, pojawi się komunikat i po 60 s nagrywanie się zakończy. Możesz to anulować przyciskiem „Nagrywaj dalej”.

## Notatki i pytania na żywo
Gdy włączona jest opcja **„Notatki i pytania na żywo”** (w Opcjach przed nagraniem albo w Ustawieniach), AI pisze notatki **w trakcie wykładu**. Każdy zakończony fragment trafia do notatki po zmianie slajdu albo po kilku minutach mowy.
- W widoku nagrywania przełączasz się między **Transkrypcja | Notatki | Zapytaj**.
- **Zapytaj** działa już w trakcie wykładu. Źródłem są gotowe fragmenty notatek i transkrypcja ostatnich minut, a obowiązują te same zabezpieczenia przed zgadywaniem.
- W trakcie wykładu pracuje **lżejszy model (Bielik 4.5B)**. Po kliknięciu „Zakończ” cała notatka powstaje od nowa **mocniejszym modelem (Bielik 11B)**, więc jest lepsza niż wersja na żywo. Oba modele wybierzesz w Ustawieniach.
- Jeśli transkrypcja zacznie nie nadążać, wyłącz tę opcję albo wybierz Whisper `large-v3-turbo`.

## Przerwa w wykładzie: kontynuacja
W wykładzie w bibliotece kliknij ikonę **⊕ Kontynuuj nagrywanie** (albo „⋯ → Kontynuuj nagrywanie”). Druga część (i każda następna) dopisuje się do **tej samej notatki**, a czas biegnie dalej. Ta funkcja przydaje się też, gdy nagrywanie zostało przez przypadek przerwane.

## Zaznaczanie ważnych fragmentów
Podczas nagrywania kliknij **Zaznacz**, gdy zaczyna się coś ważnego, i **Zakończ zaznaczanie**, gdy fragment się skończy. Zaznaczenie obejmuje też ~20 s wstecz. Rodzaje: *Ważne, Na egzamin, Ciekawe, Niejasne*. W notatce pojawi się sekcja **Zaznaczone fragmenty** z osobnym omówieniem każdego z nich. Te fragmenty dostają więcej fiszek i są częściej wybierane do egzaminu próbnego.

## Informacje o egzaminie
Aplikacja sama wyszukuje w wykładzie wzmianki typu „to będzie na egzaminie”, „na kolokwium”, „warto zapamiętać” i zbiera je w sekcji **Informacje o egzaminie i zaliczeniu** (każda z godziną).

## Odsłuchiwanie fragmentów
Przy punktach notatki i przy czasie każdej sekcji jest **ikona głośnika**. Kliknięcie odtwarza miejsce w nagraniu, w którym o tym mówiono. Jeśli temat pojawiał się w kilku miejscach, wyskoczy lista fragmentów z krótkimi opisami. W transkrypcji kliknięcie godziny odtwarza nagranie od tego momentu.

## Edycja notatek
Ikona **ołówka** otwiera edytor notatki. Przy ponownym generowaniu Twoja wersja zostaje zachowana jako kopia.

## Wzory
Wzory matematyczne są zapisywane w LaTeX i wyświetlane jako prawdziwe wzory w aplikacji, w eksporcie HTML i w PDF.

## Język wykładu
Notatki, fiszki i podsumowanie powstają w języku wykładu: wykład po angielsku da notatki po angielsku. Język jest wykrywany automatycznie. Możesz go też wybrać przed nagraniem.

## Słownik terminów przedmiotu
W bibliotece wybierz przedmiot w pasku bocznym i kliknij **Słownik terminów przedmiotu**. Wpisz nazwiska i terminy, które mają być dobrze rozpoznawane, np. „Lagrange, Jacobian, całka Riemanna”. Terminy ze slajdów dodają się same w trakcie wykładu.

## Zapytaj notatkę
W wykładzie otwórz kartę **Zapytaj** i wpisz pytanie, np. z zadania domowego. AI odpowiada **wyłącznie na podstawie tej notatki**:
- każda odpowiedź ma **dosłowny cytat** z notatki i odnośnik do fragmentu. Kliknięcie odnośnika przenosi do tego miejsca w notatce,
- aplikacja **sprawdza, czy cytat naprawdę jest w notatce**. Jeśli nie ma potwierdzenia, zamiast odpowiedzi zobaczysz „Nie potwierdzono w notatce”,
- jeśli w notatce czegoś nie ma, zobaczysz **„Brak w notatce”** i podpowiedź, które tematy są najbliżej,
- jeśli w odpowiedzi pojawią się liczby albo sformułowania spoza notatki, dostanie ona znacznik **„Częściowo”** z ostrzeżeniem.

## Spis treści i kategorie
AI łączy podobne tematy wykładu w **kategorie** (np. „Sumy całkowe”, „Twierdzenia”). Każda kategoria ma swój kolor: w spisie treści obok notatki, przy numerach tematów, w ściądze i w fiszkach. Spis pokazuje pełne tytuły tematów i godzinę; kliknięcie przewija notatkę. W starszych notatkach kategorie wyliczają się z tytułów.

## Zapytaj (Nauka)
Pytania do notatek **całego przedmiotu** albo wszystkich wykładów naraz, z tymi samymi zabezpieczeniami przed zgadywaniem. Każda odpowiedź ma cytat z odnośnikiem do konkretnego wykładu.

## Egzamin próbny (Nauka)
Wybierz zakres (cały przedmiot albo jeden wykład), liczbę i rodzaj pytań (A–D, prawda/fałsz, otwarte) oraz poziom. W polu **Twoje wskazówki** możesz napisać, jak ma wyglądać egzamin, np. „obejmuje wykłady 3–6”. Aplikacja uwzględnia też informacje o egzaminie z wykładów. Każde pytanie jest sprawdzane w notatkach, a pytania bez potwierdzenia są odrzucane. Pytania otwarte ocenia AI. Po teście zobaczysz wynik, listę błędów z odnośnikami do notatek i przycisk „Powtórz błędne”.

## Fiszki
Karta **Fiszki** ma dwa tryby:
- **Fiszki**: kafelki **kategorii** (z postępem). Po kliknięciu widać tematy kategorii, ich definicje i wzory oraz fiszki. Przycisk **„Ucz się tej kategorii”** zaczyna naukę tylko z niej.
- **Ucz się**: klasyczna nauka z powtórkami.

Liczba fiszek zależy od długości wykładu (zamiast stu kilkudziesięciu przypadkowych), podobne pytania są usuwane, a każda fiszka należy do tematu i kategorii.

Fiszki działają jak powtórki w Anki. Gdy klikniesz „Umiem”, fiszka wróci za 1, potem 3, 7, 16… dni. Gdy klikniesz „Jeszcze nie”, wróci jeszcze dziś. Liczba przy „Fiszki” w pasku bocznym to fiszki **do powtórki dziś**.

Spacja pokazuje odpowiedź, **1** oznacza „umiem”, **2** oznacza „jeszcze nie”. Fiszki, których jeszcze nie umiesz, wracają w tej samej rundzie.

---

## Ustawienia, które warto znać
| Ustawienie | Co robi |
|---|---|
| Model Whisper | `large-v3` jest najdokładniejszy. `large-v3-turbo` jest szybszy i prawie tak samo dobry. |
| Próg zmiany slajdu | Ile procent slajdu musi się zmienić, żeby był to nowy slajd. Gdy łapie za dużo, zwiększ wartość. Gdy gubi slajdy, zmniejsz ją. |
| Wygląd | Systemowy (dopasowuje się do jasnego lub ciemnego motywu Windows), Jasny albo Ciemny. |
| Model AI | Domyślnie **Bielik 11B** (polski). Alternatywy: `gemma3:12b`, `qwen3:14b`. Model pobierzesz przyciskiem „Pobierz”. |
| Notatki po nagraniu | Wyłącz, jeśli wolisz generować notatki ręcznie, np. wieczorem. |

Gdzie są pliki: `Dokumenty\Wykłady\<data> <tytuł>\`, w folderze każdego wykładu: `audio.opus`, `transcript.jsonl`, `slides\`, `notes.md`, `notes.html`, `flashcards.json`.

---

## Gdy coś nie działa
- **Brak dźwięku z aplikacji (pasek stoi):** w *Ustawieniach* zmień „Przechwytywanie dźwięku aplikacji” na inną opcję albo wybierz „Cały dźwięk systemowy”.
- **Transkrypcja jest wolna, „nie nadąża”:** w *Ustawieniach* kliknij „Sprawdź GPU”. Jeśli GPU nie działa, uruchom `Wykłady.exe --setup` (ponowne sprawdzenie i doinstalowanie bibliotek). Możesz też wybrać `large-v3-turbo`.
- **Okno daje czarne slajdy:** wybierz cały monitor zamiast okna.
- **Brak notatek, błąd Ollamy:** sprawdź, czy Ollama jest uruchomiona (ikonka lamy w zasobniku systemowym).
- Uruchom **`Wykłady.exe --debug`** (np. z wiersza poleceń albo skrótu z dopisanym `--debug`), żeby zobaczyć komunikaty w konsoli. Log znajdziesz też w *Ustawienia → Otwórz log*. Treść błędu możesz wkleić do rozmowy z Claude.

> Pamiętaj o zasadach uczelni dotyczących nagrywania zajęć. Nagrania i notatki zachowaj do własnej nauki.
