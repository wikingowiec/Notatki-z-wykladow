"""Polecenia dla modelu AI i stałe teksty notatek – w języku wykładu.

Notatka powstaje w języku, w którym prowadzony był wykład (wykrytym przez Whisper).
Pełne wersje: polska i angielska; dla innych języków angielskie polecenia z prośbą o pisanie w danym języku.
"""
from __future__ import annotations

from dataclasses import dataclass

LANG_NAMES = {"pl": "polski", "en": "English", "de": "Deutsch", "es": "español", "fr": "français",
              "it": "italiano", "uk": "українська", "cs": "čeština", "ru": "русский"}

MATH_PL = ("Wzory zapisuj w LaTeX: w tekście $…$, osobne wzory w osobnej linii $$…$$ "
           "(np. $\\int_a^b f(x)\\,dx$). Jeśli prowadzący dyktuje wzór słownie („x kwadrat plus dwa x”), zapisz go "
           "jako wzór ($x^2 + 2x$). Nie wymyślaj wzorów, których nie było.")
MATH_EN = ("Write formulas in LaTeX: inline $…$, display formulas on their own line as $$…$$ "
           "(e.g. $\\int_a^b f(x)\\,dx$). If the lecturer dictates a formula in words (\"x squared plus two x\"), "
           "write it as a formula ($x^2 + 2x$). Never invent formulas that were not given.")


@dataclass
class Texts:
    lang: str
    system: str
    section_task: list
    marked_hint: str
    flashcards: str
    summary: str
    condense: str
    mark_note: str
    exam_extract: str
    # teksty w notatce
    detailed: str
    toc: str
    marked: str
    exam_info: str
    live_banner: str
    no_speech: str
    fragment: str
    revisit: str
    subject: str
    lecture: str
    fragment_of: str
    slide_ocr: str
    transcript: str
    time: str
    slide_visuals: str = ""
    on_slide: str = "Na slajdzie"
    slide_word: str = "Slajd"
    vision: str = ""


PL = Texts(
    lang="pl",
    system=("Jesteś doświadczonym asystentem akademickim. Na podstawie automatycznej transkrypcji wykładu "
            "(mogą w niej być błędy rozpoznawania mowy) oraz tekstu ze slajdów tworzysz rzetelne materiały do nauki "
            "w języku polskim. Poprawiasz oczywiste przekłamania transkrypcji na podstawie kontekstu i slajdów. "
            "Nie wymyślasz faktów, których nie ma w materiale. Piszesz zwięźle i konkretnie. " + MATH_PL),
    section_task=[
        "Napisz przejrzyste notatki z tego fragmentu w Markdown, w tym układzie:",
        "",
        "- pierwsza linia: nagłówek `### ` z konkretnym tytułem tematu tego fragmentu (3–7 słów, np. "
        "`### Percepcja wzrokowa` albo `### Model pamięci roboczej Baddeleya`) – bez słów „tytuł” czy „temat”,",
        "- druga linia: **W skrócie:** jedno–dwa zdania, o czym jest ten fragment i po co to jest,",
        "",
        "- najważniejsze informacje w punktach, uporządkowane logicznie (szczegóły jako podpunkty z wcięciem),",
        "- nazwy pojęć i kluczowe słowa wyróżnij **pogrubieniem**,",
        "- 1–3 najważniejsze fakty całego fragmentu (to, co trzeba zapamiętać) otocz znakami ==zakreślenia==,",
        "",
        "Potem – tylko jeśli coś takiego faktycznie było w materiale – dodaj ramki (każda w osobnym akapicie):",
        "> **Definicja:** **pojęcie** — dokładna definicja.",
        "> **Wzór:** $$wzór$$ oraz co oznaczają symbole.",
        "> **Przykład:** krótki przykład lub zadanie podane przez prowadzącego.",
        "> **Ważne:** to, co prowadzący podkreślił jako ważne, typowy błąd albo rzecz „na egzamin”.",
        "",
        "Zasady:",
        "- zachowaj wzory, liczby, nazwiska, daty, przykłady i wyliczenia podane przez prowadzącego,",
        "- jeśli na slajdzie są obrazy, schematy, wykresy lub tabele (opis poniżej), wyjaśnij w punktach, co z nich wynika,",
        "- pomiń sprawy organizacyjne, powtórzenia, przejęzyczenia i dygresje niezwiązane z tematem,",
        "- pisz zwięźle, pełnymi myślami, bez lania wody; nie powtarzaj tego samego w punktach i w ramkach.",
        "Nie pisz wstępu ani komentarza od siebie – tylko notatki.",
    ],
    marked_hint="UWAGA: student zaznaczył ten fragment jako: {kinds}. Opisz go szczególnie dokładnie i niczego nie pomijaj.",
    flashcards=("Na podstawie poniższych notatek z wykładu przygotuj {k} fiszek do nauki.\n"
                "Każda fiszka to konkretne pytanie i krótka, poprawna odpowiedź (1–3 zdania). "
                "Sprawdzaj rozumienie pojęć, definicji, zależności i faktów – nie pytaj o sprawy organizacyjne. "
                "Wzory zapisuj w LaTeX ($…$).\n"
                'Zwróć wyłącznie JSON w formacie: {{"fiszki": [{{"pytanie": "...", "odpowiedz": "..."}}]}}\n\n'
                'NOTATKI:\n"""\n{notes}\n"""'),
    summary=("Poniżej są notatki z kolejnych części wykładu „{title}”{subject}.\n\n\"\"\"\n{notes}\n\"\"\"\n\n"
             "Na ich podstawie przygotuj w Markdown dokładnie te sekcje:\n"
             "## Podsumowanie\n(zwięzłe streszczenie całego wykładu, 5–10 zdań w jednym–dwóch akapitach; "
             "najważniejszą myśl wykładu otocz ==zakreśleniem==)\n"
             "## Najważniejsze zagadnienia\n(lista 5–10 punktów; każdy zaczyna się od **pogrubionego tematu**, "
             "potem krótkie wyjaśnienie)\n"
             "## Kluczowe pojęcia\n(lista: **pojęcie** — krótka definicja)\n"
             "## Pytania kontrolne\n(5–8 pytań sprawdzających zrozumienie, bez odpowiedzi, lista numerowana)\n"
             "Pisz po polsku i nie dodawaj nic poza tymi sekcjami."),
    condense=("Skróć poniższe notatki z wykładu do około 40% długości. Zachowaj wszystkie kluczowe informacje, "
              "definicje, wzory i przykłady. Użyj punktów w Markdown. Nie dodawaj komentarza.\n\n\"\"\"\n{notes}\n\"\"\""),
    mark_note=("Student zaznaczył podczas wykładu fragment jako: {kind}. Poniżej transkrypcja tego fragmentu "
               "({time}).\n\n\"\"\"\n{text}\n\"\"\"\n\n"
               "Napisz w Markdown krótką, ale dokładną notatkę tylko o tym fragmencie: zacznij od jednego zdania "
               "„o czym to jest”, potem najważniejsze informacje w punktach. Nie dodawaj nagłówków ani informacji "
               "spoza fragmentu."),
    exam_extract=("Poniżej fragmenty wykładu, w których prowadzący mógł mówić o egzaminie, kolokwium, zaliczeniu "
                  "albo o tym, co jest szczególnie ważne do zapamiętania.\n\n{snippets}\n\n"
                  "Wypisz wyłącznie konkretne informacje, które faktycznie padły: co będzie na egzaminie/kolokwium, "
                  "zakres, forma, terminy, zasady zaliczenia, rzeczy wskazane jako ważne. Każdą informację podaj "
                  "z czasem w nawiasie kwadratowym, np. [12:30]. Jeśli nic takiego nie padło, zwróć pustą listę.\n"
                  'Zwróć wyłącznie JSON: {{"informacje": ["…", "…"]}}'),
    detailed="Notatki szczegółowe", toc="Spis treści", marked="Zaznaczone fragmenty",
    exam_info="Informacje o egzaminie i zaliczeniu",
    live_banner=("> **Notatki tworzone na żywo.** Kolejne fragmenty dopisują się po zmianie slajdu albo co kilka "
                 "minut. Pełna notatka, podsumowanie i fiszki powstaną po zakończeniu nagrania."),
    no_speech="*(brak treści mówionej w tym fragmencie)*", fragment="Fragment wykładu",
    revisit="powrót do slajdu", subject="Przedmiot", lecture="Wykład", fragment_of="Fragment",
    slide_ocr="TEKST ZE SLAJDU", transcript="TRANSKRYPCJA FRAGMENTU", time="czas",
    slide_visuals="OBRAZY NA SLAJDZIE (opis)", on_slide="Na slajdzie", slide_word="Slajd",
    vision=("To jest slajd z wykładu{subject}. Przeczytaj go i opisz.\n"
            "Zwróć wyłącznie JSON:\n"
            '{{"tekst": "cała treść tekstowa slajdu w kolejności czytania (punkty zachowaj jako linie „- ”, '
            'wzory zapisz w LaTeX $…$)", '
            '"elementy": [{{"rodzaj": "zdjęcie | schemat | wykres | diagram | tabela | rysunek | mapa | kod | wzór", '
            '"opis": "co dokładnie przedstawia i co z tego wynika – 1–3 zdania po polsku"}}]}}\n'
            "W „elementy” opisz tylko elementy graficzne: zdjęcia, schematy, wykresy, diagramy, tabele, rysunki, "
            "mapy, fragmenty kodu i duże wzory. Przy wykresie podaj osie i trend, przy schemacie – elementy i "
            "powiązania, przy tabeli – co zestawia. Logo uczelni, tło i dekoracje pomiń. Jeśli slajd to sam tekst, "
            "zwróć pustą listę „elementy”. Nie zgaduj – opisuj tylko to, co widać."),
)

EN = Texts(
    lang="en",
    system=("You are an experienced academic assistant. From an automatic lecture transcript (it may contain speech "
            "recognition errors) and slide text you create reliable study materials in English. You fix obvious "
            "transcription errors using context and slides. You never invent facts that are not in the material. "
            "You write concisely and to the point. " + MATH_EN),
    section_task=[
        "Write clear notes for this part in Markdown, in this layout:",
        "",
        "- first line: a `### ` heading with the concrete topic of this part (3–7 words, e.g. "
        "`### Visual perception`) – without words like \"title\" or \"topic\",",
        "- second line: **In short:** one or two sentences on what this part is about and why it matters,",
        "",
        "- the key information as bullet points in a logical order (details as indented sub-points),",
        "- put names of concepts and key words in **bold**,",
        "- wrap the 1–3 most important facts of the whole part (what must be remembered) in ==highlight== marks,",
        "",
        "Then – only if such things actually appear in the material – add boxes (each as a separate paragraph):",
        "> **Definition:** **term** — precise definition.",
        "> **Formula:** $$formula$$ and what the symbols mean.",
        "> **Example:** a short example or exercise given by the lecturer.",
        "> **Important:** what the lecturer stressed, a typical mistake or something \"for the exam\".",
        "",
        "Rules:",
        "- keep formulas, numbers, names, dates, examples and enumerations given by the lecturer,",
        "- if the slide has pictures, diagrams, charts or tables (described below), explain what they show,",
        "- skip organisational matters, repetitions, slips of the tongue and off-topic digressions,",
        "- be concise; do not repeat the same thing in bullets and boxes.",
        "Do not write an introduction or your own comments – only the notes.",
    ],
    marked_hint="NOTE: the student marked this part as: {kinds}. Describe it with extra care and do not skip anything.",
    flashcards=("Based on the lecture notes below, create {k} study flashcards.\n"
                "Each flashcard is a specific question with a short, correct answer (1–3 sentences). Test understanding "
                "of concepts, definitions, relationships and facts – no organisational questions. Write formulas in "
                "LaTeX ($…$).\n"
                'Return JSON only: {{"flashcards": [{{"question": "...", "answer": "..."}}]}}\n\n'
                'NOTES:\n"""\n{notes}\n"""'),
    summary=("Below are notes from consecutive parts of the lecture \"{title}\"{subject}.\n\n\"\"\"\n{notes}\n\"\"\"\n\n"
             "Based on them, write exactly these Markdown sections:\n"
             "## Summary\n(a concise summary of the whole lecture, 5–10 sentences; wrap the single most important "
             "idea in ==highlight== marks)\n"
             "## Key topics\n(5–10 bullets, each starting with a **bold topic** and a short explanation)\n"
             "## Key terms\n(list: **term** — short definition)\n"
             "## Review questions\n(5–8 questions checking understanding, no answers)\n"
             "Write in English and add nothing beyond these sections."),
    condense=("Shorten the lecture notes below to about 40% of their length. Keep all key information, definitions, "
              "formulas and examples. Use Markdown bullet points. No comments.\n\n\"\"\"\n{notes}\n\"\"\""),
    mark_note=("During the lecture the student marked a part as: {kind}. Below is the transcript of that part "
               "({time}).\n\n\"\"\"\n{text}\n\"\"\"\n\n"
               "Write a short but precise Markdown note about this part only: start with one sentence on what it is "
               "about, then the key information as bullet points. No headings, nothing beyond this part."),
    exam_extract=("Below are lecture excerpts where the lecturer may have talked about the exam, midterm, passing "
                  "requirements or what is especially important to remember.\n\n{snippets}\n\n"
                  "List only concrete information that was actually said: what will be on the exam, scope, format, "
                  "dates, passing rules, things pointed out as important. Give each item with its time in square "
                  "brackets, e.g. [12:30]. If nothing like that was said, return an empty list.\n"
                  'Return JSON only: {{"items": ["…", "…"]}}'),
    detailed="Detailed notes", toc="Contents", marked="Marked parts", exam_info="Exam and course information",
    live_banner=("> **Live notes.** New parts are added after each slide change or every few minutes. The full notes, "
                 "summary and flashcards will be created when the recording ends."),
    no_speech="*(no speech in this part)*", fragment="Lecture part", revisit="back to slide",
    subject="Subject", lecture="Lecture", fragment_of="Part", slide_ocr="SLIDE TEXT",
    transcript="TRANSCRIPT OF THIS PART", time="time",
    slide_visuals="PICTURES ON THE SLIDE (description)", on_slide="On the slide", slide_word="Slide",
    vision=("This is a slide from a lecture{subject}. Read it and describe it.\n"
            "Return JSON only:\n"
            '{{"text": "all text on the slide in reading order (keep bullets as lines starting with „- ”, formulas '
            'in LaTeX $…$)", '
            '"elements": [{{"kind": "photo | diagram | chart | table | drawing | map | code | formula", '
            '"description": "what exactly it shows and what follows from it – 1–3 sentences"}}]}}\n'
            "In \"elements\" describe only graphical elements: photos, diagrams, charts, tables, drawings, maps, code "
            "and large formulas. For a chart give the axes and the trend, for a diagram the parts and connections, "
            "for a table what it compares. Skip logos, backgrounds and decorations. If the slide is text only, "
            "return an empty \"elements\" list. Do not guess – describe only what is visible."),
)

MARK_NAMES = {
    "pl": {"important": "Ważne", "exam": "Na egzamin", "interesting": "Ciekawe", "unclear": "Niejasne"},
    "en": {"important": "Important", "exam": "For the exam", "interesting": "Interesting", "unclear": "Unclear"},
}

# słowa-klucze wzmianek o egzaminie (wyszukiwane w transkrypcji)
EXAM_PATTERNS = {
    "pl": r"egzamin|kolokwi|zaliczeni|zaliczy|kartkówk|sprawdzian|na teście|będzie na|trzeba umieć|musicie (?:znać|umieć|pamiętać)|"
          r"warto zapamiętać|zapamiętajcie|ważne jest|to jest ważne|bardzo ważn|termin oddania|punkt(?:ów|y) za",
    "en": r"\bexam|midterm|final test|\bquiz|will be on the|you need to know|you must know|remember this|"
          r"important to remember|this is important|deadline|grading|pass the course",
}


def texts(lang: str) -> Texts:
    if lang == "pl":
        return PL
    if lang == "en" or not lang:
        return EN if lang == "en" else PL
    # inne języki: angielskie polecenia + prośba o pisanie w języku wykładu
    name = LANG_NAMES.get(lang, lang)
    from dataclasses import replace
    extra = f" IMPORTANT: write everything in the language of the lecture ({name})."
    return replace(EN, lang=lang, system=EN.system + extra,
                   summary=EN.summary.replace("Write in English", f"Write in {name}"),
                   vision=EN.vision + f" Write the descriptions in {name}.")


def mark_names(lang: str) -> dict:
    return MARK_NAMES.get(lang, MARK_NAMES["en"] if lang and lang != "pl" else MARK_NAMES["pl"])
