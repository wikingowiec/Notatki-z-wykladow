"""Wersja aplikacji i skąd brać aktualizacje.

Przy wydawaniu nowej wersji: podbij VERSION, wyślij zmiany na GitHuba i wypchnij tag v<VERSION> – GitHub Actions
(.github/workflows/release.yml) zbuduje paczkę i utworzy „Release”. Tag musi być równy VERSION.
REPO to „użytkownik/repozytorium” (można też wpisać w Ustawieniach)."""
VERSION = "2.2.0"
REPO = "wikingowiec/Notatki-z-wykladow"
BRANCH = "main"

AUTHOR = "Wiktor Wystrychowski"
LINKS = {
    "GitHub": "https://github.com/wikingowiec",
    "LinkedIn": "https://www.linkedin.com/in/wystrychowski/",
    "Portfolio": "https://www.wystrychowski.pl/",
}
