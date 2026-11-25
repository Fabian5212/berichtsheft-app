# Entwicklung

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q          # Tests
.venv\Scripts\python app.py                # GUI starten
.venv\Scripts\python cli.py --help         # CLI
```

EXE bauen: `build.bat` oder `powershell -ExecutionPolicy Bypass -File build.ps1`. Das Skript installiert die Abhängigkeiten, führt die Tests aus und erzeugt `dist\Berichtsheft-Assistent.exe` (PyInstaller, `berichtsheft.spec`, onefile, ohne Konsole).

## Projektstruktur

```
src/berichtsheft/
├─ core/                  # komplette Logik, ohne GUI testbar
│  ├─ models.py           # Datentypen: Lesson, ParsedPdf, DayEntry, WeekPlan, Issue
│  ├─ pdf_parser.py       # PDF lesen: Parser-Protokoll, GFN-Parser, Textmodus-Fallback
│  ├─ summarizer.py       # bereinigen, bündeln, formulieren, kürzen
│  ├─ week.py             # PDFs zu einer Woche zusammenführen + Prüfungen
│  ├─ docx_writer.py      # Vorlage analysieren, Platzhalter, Tageszeilen füllen
│  ├─ config.py           # Profile/Einstellungen (%APPDATA%\Berichtsheft\config.json)
│  ├─ service.py          # Ablauf PDFs → Woche → DOCX (von GUI und CLI genutzt)
│  └─ logging_setup.py
├─ gui/                   # CustomTkinter + tkinterdnd2
│  ├─ app.py              # Hauptfenster
│  ├─ setup_wizard.py     # Ersteinrichtung
│  ├─ settings.py         # Einstellungsfenster + Formularbausteine
│  └─ widgets.py          # Tageskarte, Log-Bereich
├─ cli.py                 # CLI, kompatibel zum alten berichtsheft_auto.py (v9)
└─ __main__.py            # Einstieg (GUI, oder --cli)
tests/
├─ fixtures.py            # erzeugt anonymisierte PDFs/Vorlagen im GFN-Layout
├─ test_*.py
└─ test_real_samples.py   # optional mit echten PDFs (BERICHTSHEFT_SAMPLES=…)
tools/
├─ show_week.py           # Tagestexte für einen PDF-Ordner anzeigen
├─ compare_legacy.py      # Vorher/Nachher gegen das alte v9-Script
└─ gui_smoke.py           # GUI automatisch durchklicken, Screenshots nur vom App-Fenster
```

Grundsätze: Die Logik in `core/` hat keine GUI-Abhängigkeit und keinen globalen Zustand, Einstellungen werden explizit übergeben. Fehler werden als `Issue` gesammelt (verständlicher Text). Tracebacks gehen nur ins Logfile.

## Wie der GFN-Parser funktioniert

Die Klassenbuch-PDF ist eine Tabelle `Stunde | Lehrinhalte | Lernformat/-methodik | Dozent`. Der Parser liest die Zeilen samt Position (`page.get_text("dict")`):

1. **Spalten:** Er sucht die vier Überschriften und nimmt die senkrechten Tabellenlinien, die die Kopfzeile kreuzen, als Spaltengrenzen. Ohne Linien schätzt er die Grenzen aus den Positionen der Überschriften.
2. **Zeilen:** Die große Zahl in der Stunde-Spalte markiert eine Stunde. Die Zeile beginnt an der waagerechten Linie über der Zahl.
3. **Kopf/Fuß:** Alles über der Tabellenüberschrift und ab der Fußzeile (`… // … //`, „Hiermit bestätige …“) wird ignoriert.
4. **Mehrseitig:** Alle Seiten werden gelesen. Eine Stunde, die auf der nächsten Seite weitergeht, wird angehängt.
5. **Zelleninhalt:** Jede Zeile ist ein eigener Punkt. Endet eine Zeile auf `-` („Aufgaben-“ + „/Übungsbesprechung“) oder bricht sie am Zellenrand um, wird sie mit der nächsten verbunden.

Dozent und Methoden landen in eigenen Feldern und so nie im Text. Findet der Parser die Tabelle nicht, übernimmt `GfnTextModeParser`, der alte v9-Algorithmus über die Textreihenfolge.

## Einen neuen PDF-Parser hinzufügen

1. In `core/pdf_parser.py` eine Klasse mit dem `KlassenbuchParser`-Protokoll schreiben:

   ```python
   class MeinTraegerParser:
       name = "Mein Bildungsträger"

       def can_parse(self, doc: fitz.Document) -> bool:
           return "Mein Träger – Anwesenheit" in doc[0].get_text("text")

       def parse(self, doc: fitz.Document, path: Path) -> ParsedPdf:
           ...  # Datum, Lernfeld, Stunden (Lesson) und Dozent:innen auslesen
           return ParsedPdf(path, date, lernfeld, title, trainers, lessons, self.name, issues)
   ```

   Bei Problemen `PdfParseError("verständliche Meldung")` werfen und keine anderen Exceptions durchlassen.
2. Die Klasse in `DEFAULT_PARSERS` **vor** dem Textmodus-Fallback eintragen.
3. In `tests/fixtures.py` eine Funktion ergänzen, die eine anonymisierte Beispiel-PDF im neuen Layout erzeugt (`fitz` → `page.insert_text`, `page.draw_line`), und Tests in `tests/test_pdf_parser.py` schreiben.

Summarizer, Wochenlogik und Writer arbeiten nur mit `ParsedPdf`/`Lesson` und brauchen keine Änderung.

## Tests

- Fixtures entstehen beim Testlauf in einem temporären Ordner. Es werden keine echten PDFs eingecheckt (`.gitignore` sperrt `*.pdf`/`*.docx` außer `docs/`).
- Regressionstests aus der v9-Zeit stehen in `test_summarizer.py`: „wiederherstellen“ bleibt heil, keine abgeschnittenen Sätze, „Außerdem wurden die …“ statt „… Die …“.
- Mit echten Klassenbuch-PDFs (lokal):

  ```powershell
  $env:BERICHTSHEFT_SAMPLES = "C:\Pfad\zu\Klassenbuch-PDFs"
  .venv\Scripts\python -m pytest tests/test_real_samples.py
  .venv\Scripts\python tools/compare_legacy.py C:\Pfad\berichtsheft_auto.py C:\Pfad\PDFs
  ```

## Release

```powershell
build.ps1
gh release create v1.0.0 dist\Berichtsheft-Assistent.exe --title "v1.0.0" --notes "…"
```
