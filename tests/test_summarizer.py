import re

from berichtsheft.core.models import Lesson
from berichtsheft.core.summarizer import Replacement, SummarizerSettings, clean_line, summarize


def L(n, *topics, trainer="Mustermann, Max"):
    return Lesson(n, list(topics), [], trainer)


def sentences_complete(text: str) -> bool:
    return text.endswith(".") and "…" not in text and "..." not in text


# --- bekannte Regressionen aus v6–v9 ---------------------------------------

def test_wiederherstellen_is_not_broken(settings):
    text, _ = summarize([L(1, "Backups wiederherstellen"), L(2, "Wiederherstellen einer VM")], [], settings)
    assert "wiederherstellen" in text.lower()
    assert "wiederhErstellen" not in text and "WiederhErstellen" not in text


def test_wiederhErstellen_typo_is_fixed(settings):
    assert clean_line("Daten wiederhErstellen", settings.replacements) == "Daten wiederherstellen"


def test_ausserdem_wurden_lowercase_article(settings):
    lessons = [L(1, "Grundlagen zu VMs"), L(2, "Verbinden mit VMs"), L(3, "Speicher für VMs"),
               L(4, "Die verschiedenen Gruppen von VMs"), L(5, "Die Größen von VMs")]
    text, _ = summarize(lessons, [], settings)
    assert "Außerdem wurden" in text
    assert "Außerdem wurden Die" not in text
    assert re.search(r"Außerdem wurden (die|verschiedene)", text)


def test_no_cut_sentences_when_too_long(settings):
    words = ["Netzwerk", "Speicher", "Datenbank", "Firewall", "Backup", "Monitoring", "Skripting", "Cloud", "Linux"]
    long = [L(i, f"{w}themen mit ausführlicher Übung und vielen Details zum Thema", f"{w} im Labor vertiefen")
            for i, w in enumerate(words, 1)]
    text, issues = summarize(long, [], settings)
    assert len(text) <= settings.max_chars
    assert sentences_complete(text)
    assert all(re.search(r"\w$", s.strip()) or s.strip().endswith("?") for s in text.split(".")[:-1])
    assert any("gekürzt" in str(i) for i in issues)


def test_shortening_keeps_every_lesson_if_possible(settings):
    lessons = [L(i, f"Thema {i} Hauptpunkt", f"Detail {i}a lang lang lang", f"Detail {i}b lang lang lang")
               for i in range(1, 10)]
    text, _ = summarize(lessons, [], settings)
    for i in range(1, 10):
        assert f"Thema {i} Hauptpunkt" in text


# --- Filter -----------------------------------------------------------------

def test_trainer_is_removed_automatically(settings):
    text, _ = summarize([L(1, "Netzwerke", "Mustermann, Max"), L(2, "Max Mustermann")], ["Max Mustermann"], settings)
    assert "Mustermann" not in text


def test_ignore_list(settings):
    settings.ignore_lines.append("Pause")
    text, _ = summarize([L(1, "Subnetting"), L(2, "Pause")], [], settings)
    assert "Pause" not in text


def test_rueckblick_dropped_and_vertiefen_sentence(settings):
    text, _ = summarize([L(1, "Rückblick auf die Themen von gestern"), L(2, "DNS"),
                         L(3, "Vertiefen der Inhalte mit Labs")], [], settings)
    assert "Rückblick" not in text
    assert text.endswith("vertieft.")


def test_only_vertiefen(settings):
    text, _ = summarize([L(1, "Vertiefen der Inhalte")], [], settings)
    assert text == settings.phrases.only_deepen


def test_empty_day(settings):
    text, issues = summarize([], [], settings)
    assert text == settings.phrases.empty
    assert issues


# --- Bündeln ----------------------------------------------------------------

def test_repeated_heading_is_grouped(settings):
    lessons = [L(1, "Einführung"), L(2, "Arbeiten am Projekt", "Planung"),
               L(3, "Arbeiten am Projekt", "Umsetzung, Test"), L(4, "Arbeiten am Projekt", "Dokumentation")]
    text, _ = summarize(lessons, [], settings)
    assert "Arbeiten am Projekt: Planung, Umsetzung, Test und Dokumentation." in text
    assert text.count("Arbeiten am Projekt") == 1


def test_identical_lessons_are_not_treated_as_heading(settings):
    lessons = [L(1, "Antrag schreiben", "Thema wählen"), L(2, "Antrag schreiben", "Thema wählen"), L(3, "Abgabe")]
    text, _ = summarize(lessons, [], settings)
    assert "Antrag schreiben:" not in text
    assert text.count("Thema wählen") == 1


def test_common_prefix_is_grouped(settings):
    lessons = [L(1, "Vorlagenerstellung Testprotokoll"), L(2, "Vorlagenerstellung Abnahmeprotokoll"),
               L(3, "Vorlagenerstellung Benutzerhandbuch")]
    text, _ = summarize(lessons, [], settings)
    assert "Vorlagenerstellung: Testprotokoll, Abnahmeprotokoll und Benutzerhandbuch." in text


def test_contained_duplicates_removed(settings):
    text, _ = summarize([L(1, "Zeitliche Abläufe"), L(2, "Zeitliche Abläufe PSP")], [], settings)
    assert text.count("Zeitliche Abläufe") == 1


def test_nominalized_verb_capitalized(settings):
    text, _ = summarize([L(1, "erstellen von Ressourcen"), L(2, "erweiterte Bearbeitung")], [], settings)
    assert "Erstellen von Ressourcen" in text
    assert "erweiterte Bearbeitung" in text


def test_continuation_line_joined(settings):
    text, _ = summarize([L(1, "Projektanlagen erstellen", "wie z. B. Nutzwertanalyse")], [], settings)
    assert "Projektanlagen erstellen wie z. B. Nutzwertanalyse" in text


# --- Ersetzungen --------------------------------------------------------------

def test_replacement_whole_words_only():
    r = Replacement("Gui", "GUI")
    assert r.apply("Gui und Guide") == "GUI und Guide"


def test_default_typos(settings):
    assert clean_line("Grundllagen der Ruten", settings.replacements) == "Grundlagen der Routen"
    assert clean_line("Poqwershellscripts", settings.replacements) == "PowerShell-Skripts"
    assert clean_line("S.M.A.R.T Ziele", settings.replacements) == "S.M.A.R.T Ziele"


def test_punctuation_normalized():
    assert clean_line("testen , dokumentieren,") == "testen, dokumentieren"
    assert clean_line("Kosten--/Ressourcenplan") == "Kosten-/Ressourcenplan"


def test_max_chars_zero_means_unlimited():
    s = SummarizerSettings(max_chars=0)
    text, issues = summarize([L(i, "x" * 100 + str(i)) for i in range(10)], [], s)
    assert len(text) > 1000 and not issues
