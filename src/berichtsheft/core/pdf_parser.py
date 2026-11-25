"""Klassenbuch-PDFs lesen.

Standard ist der GFN-Parser (``GfnKlassenbuchParser``). Er erkennt die Tabelle
"Stunde | Lehrinhalte | Lernformat/-methodik | Dozent" über die Position der
Texte auf der Seite und nicht über die Textreihenfolge. Dadurch landen Dozent,
Methoden, Kopf- und Fußzeilen nie im Tagestext, egal wie der Dozent heißt.

Weitere Formate lassen sich ergänzen: Klasse mit ``name``, ``can_parse`` und
``parse`` schreiben und in ``DEFAULT_PARSERS`` eintragen (siehe DEVELOPMENT.md).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import fitz  # PyMuPDF

from .models import Issue, Lesson, ParsedPdf, Severity


class PdfParseError(Exception):
    """Verständlicher Fehler beim Lesen einer PDF."""


class KlassenbuchParser(Protocol):
    name: str

    def can_parse(self, doc: fitz.Document) -> bool: ...

    def parse(self, doc: fitz.Document, path: Path) -> ParsedPdf: ...


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
# LF-ZQ3b, LF12bV2, LF 12b, LF09 ...
LERNFELD_RE = re.compile(r"\bLF[-\s]?[0-9A-Za-z]*\d[0-9A-Za-z]*\b")
TRAINER_RE = re.compile(r"^\s*([A-ZÄÖÜ][\wäöüß'\-]+(?:[ -][A-ZÄÖÜ][\wäöüß'\-]+)*),\s*([A-ZÄÖÜ][\wäöüß'\-]+(?:[ -][A-ZÄÖÜ][\wäöüß'\-]+)*)\s*$")
FOOTER_RE = re.compile(r"(//.*//)|^Hiermit bestätige|^Unterschrift\b", re.I)


def parse_lernfeld(text: str) -> str:
    """Lernfeld-Kürzel aus einem Titel lesen (``LF12bV2 Kundenspez…`` -> ``LF12bV2``)."""
    m = LERNFELD_RE.search(text)
    return m.group(0).replace(" ", "") if m else ""


def trainer_display_name(raw: str) -> str:
    """``Mustermann, Max`` -> ``Max Mustermann``. Andere Formate bleiben unverändert."""
    m = TRAINER_RE.match(raw)
    if m:
        return f"{m.group(2)} {m.group(1)}"
    return raw.strip()


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def _page_lines(page: fitz.Page) -> list[_Line]:
    lines: list[_Line] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _norm_space("".join(s["text"] for s in spans))
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            size = max((s["size"] for s in spans), default=0.0)
            lines.append(_Line(text, x0, y0, x1, y1, size))
    lines.sort(key=lambda l: (round(l.y0, 1), l.x0))
    return lines


def _segments(page: fitz.Page) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Horizontale (y, x0, x1) und vertikale (x, y0, y1) Linien der Seite."""
    horiz: list[tuple[float, float, float]] = []
    vert: list[tuple[float, float, float]] = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 0.5:
                    horiz.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 0.5:
                    vert.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif item[0] == "re":
                r = item[1]
                horiz += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                vert += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    return horiz, vert


def _value_right_of(lines: list[_Line], label: str) -> str:
    """Wert rechts neben einem Label in derselben Zeile (Kopfbereich)."""
    for lab in lines:
        if lab.text.startswith(label):
            rest = lab.text[len(label):].strip()
            if rest:
                return rest
            candidates = [l for l in lines if l is not lab and abs(l.yc - lab.yc) < 3 and l.x0 > lab.x1 - 1]
            if candidates:
                return min(candidates, key=lambda l: l.x0).text
    return ""


# --------------------------------------------------------------------------- #
# GFN-Klassenbuch (Themendokumentation)
# --------------------------------------------------------------------------- #

HEADER_KEYS = ("Stunde", "Lehrinhalte", "Lernformat", "Dozent")


@dataclass
class _Columns:
    header_y1: float
    bounds: list[float]  # linke Kanten der Spalten 0..3 plus rechte Kante

    def index(self, line: _Line) -> int:
        x = line.x0 + 1
        for i in range(len(self.bounds) - 1, -1, -1):
            if x >= self.bounds[i]:
                return min(i, 3)
        return -1


class GfnKlassenbuchParser:
    """Parser für die GFN-„Themendokumentation“ (Klassenbuch-Export)."""

    name = "GFN-Klassenbuch"

    def can_parse(self, doc: fitz.Document) -> bool:
        first = doc[0].get_text("text") if len(doc) else ""
        return "Datum:" in first and all(k in first for k in ("Stunde", "Lehrinhalte", "Dozent"))

    # -- Spalten ----------------------------------------------------------- #
    @staticmethod
    def _find_columns(page: fitz.Page, lines: list[_Line]) -> _Columns | None:
        headers: dict[str, _Line] = {}
        for line in lines:
            for key in HEADER_KEYS:
                if line.text.startswith(key) and key not in headers:
                    headers[key] = line
        if len(headers) < 4:
            return None
        hs = [headers[k] for k in HEADER_KEYS]
        if max(h.yc for h in hs) - min(h.yc for h in hs) > 5:
            return None
        header_y1 = max(h.y1 for h in hs)
        header_yc = sum(h.yc for h in hs) / 4

        # 1. Wahl: senkrechte Tabellenlinien, die die Kopfzeile kreuzen
        _, vert = _segments(page)
        xs = sorted({round(x, 1) for x, y0, y1 in vert if y0 - 1 <= header_yc <= y1 + 1})
        merged: list[float] = []
        for x in xs:
            if not merged or x - merged[-1] > 3:
                merged.append(x)
        if len(merged) >= 5:
            # die 5 Linien, zwischen denen die vier Überschriften liegen
            bounds: list[float] = []
            for h in hs:
                left = [x for x in merged if x <= h.x0 + 1]
                if not left:
                    break
                bounds.append(left[-1])
            right = [x for x in merged if x >= hs[-1].x1 - 1]
            if len(bounds) == 4 and right and bounds == sorted(set(bounds)):
                return _Columns(header_y1, bounds + [right[0]])

        # 2. Wahl (ohne Linien): Spaltengrenze kurz hinter dem Ende der vorigen Überschrift
        bounds = [hs[0].x0 - 5] + [h.x1 + 3 for h in hs[:-1]]
        bounds[1] = min(bounds[1], hs[1].x0)
        return _Columns(header_y1, bounds + [10_000])

    # -- eine Seite -------------------------------------------------------- #
    def _parse_page(self, page: fitz.Page, lessons: dict[int, Lesson], issues: list[Issue], src: str) -> None:
        lines = _page_lines(page)
        cols = self._find_columns(page, lines)
        if cols is None:
            raise PdfParseError("Tabelle (Stunde / Lehrinhalte / Lernformat / Dozent) nicht gefunden")

        body = [l for l in lines if l.y0 >= cols.header_y1 - 0.5]
        footer_y = min((l.y0 for l in body if FOOTER_RE.search(l.text)), default=float("inf"))
        body = [l for l in body if l.y0 < footer_y - 0.5]

        numbers = sorted(
            (l for l in body if cols.index(l) == 0 and re.fullmatch(r"\d{1,2}", l.text)),
            key=lambda l: l.y0,
        )
        if not numbers:
            return

        horiz, _ = _segments(page)
        stunde_left, stunde_right = cols.bounds[0], cols.bounds[1]

        def row_top(num: _Line) -> float:
            # nächste waagerechte Linie in der Stunde-Spalte oberhalb der Zahl
            cands = [y for y, x0, x1 in horiz if x0 <= stunde_left + 3 and x1 >= stunde_right - 3 and num.y0 - 40 <= y <= num.y0]
            return max(cands) if cands else num.y0 - 14

        tops = [row_top(n) for n in numbers]
        for idx, num in enumerate(numbers):
            top = tops[idx]
            bottom = tops[idx + 1] if idx + 1 < len(numbers) else footer_y
            nr = int(num.text)
            in_row = [l for l in body if top - 0.5 <= l.yc < bottom and l is not num]
            topics = _join_cell_lines([l for l in in_row if cols.index(l) == 1], cols.bounds[2])
            methods = _join_cell_lines([l for l in in_row if cols.index(l) == 2], cols.bounds[3], hyphen_only=True)
            trainer_lines = [l.text for l in in_row if cols.index(l) == 3]
            trainer = _norm_space(" ".join(trainer_lines))
            if nr in lessons:
                # Stunde über Seitenumbruch fortgesetzt
                lessons[nr].topics += topics
                lessons[nr].methods += methods
                lessons[nr].trainer = lessons[nr].trainer or trainer
            else:
                lessons[nr] = Lesson(nr, topics, methods, trainer)
            if not topics:
                issues.append(Issue(Severity.INFO, f"Stunde {nr} hat keinen Lehrinhalt", src))

    def parse(self, doc: fitz.Document, path: Path) -> ParsedPdf:
        first_lines = _page_lines(doc[0])
        raw_date = _value_right_of(first_lines, "Datum:")
        m = DATE_RE.search(raw_date) or DATE_RE.search(doc[0].get_text("text"))
        if not m:
            raise PdfParseError("Kein Datum gefunden (Feld „Datum:“)")
        day, month, year = map(int, m.groups())
        try:
            date = dt.date(year, month, day)
        except ValueError as exc:
            raise PdfParseError(f"Ungültiges Datum {m.group(0)}") from exc

        title = _value_right_of(first_lines, "Titel:")
        issues: list[Issue] = []
        lessons: dict[int, Lesson] = {}
        for page in doc:
            self._parse_page(page, lessons, issues, path.name)

        ordered = [lessons[k] for k in sorted(lessons)]
        trainers: list[str] = []
        for lesson in ordered:
            name = trainer_display_name(lesson.trainer) if lesson.trainer else ""
            if name and name not in trainers:
                trainers.append(name)
        lernfeld = parse_lernfeld(title)
        if not lernfeld:
            issues.append(Issue(Severity.WARNING, "Kein Lernfeld im Titel gefunden", path.name))
        if not ordered:
            issues.append(Issue(Severity.WARNING, "Keine Unterrichtsstunden gefunden", path.name))
        return ParsedPdf(path, date, lernfeld, title, trainers, ordered, self.name, issues)


def _join_cell_lines(lines: list[_Line], col_right: float, hyphen_only: bool = False) -> list[str]:
    """Zeilen einer Zelle zu Einträgen zusammensetzen.

    Jede Zeile im Klassenbuch ist normalerweise ein eigener Punkt. Ausnahmen:
    Endet eine Zeile auf ``-`` (``Aufgaben-`` + ``/Übungsbesprechung``) oder
    reicht sie bis an den Zellenrand (automatischer Umbruch), wird die nächste
    Zeile angehängt.
    """
    out: list[str] = []
    prev: _Line | None = None
    for line in sorted(lines, key=lambda l: (l.y0, l.x0)):
        text = line.text
        if out and prev is not None:
            if out[-1].endswith("-") and not out[-1].endswith(" -"):
                out[-1] = out[-1] + text
                prev = line
                continue
            if not hyphen_only and prev.x1 >= col_right - 12 and text[:1].islower():
                out[-1] = f"{out[-1]} {text}"
                prev = line
                continue
        out.append(text)
        prev = line
    return out


# --------------------------------------------------------------------------- #
# Fallback: alter Textmodus (für PDFs ohne erkennbare Tabellengeometrie)
# --------------------------------------------------------------------------- #

LEGACY_SKIP_PREFIXES = ("Datum:", "Raum:", "MaßnahmeNr", "Titel:", "Unterrichtsbeginn", "Themendokumentation")
LEGACY_SKIP_EXACT = {"Stunde", "Lehrinhalte", "Lernformat/-methodik", "Dozent"}


class GfnTextModeParser:
    """Der v9-Algorithmus über die Textreihenfolge, aber ohne festen Dozentennamen.

    Wird nur benutzt, wenn der Tabellenparser die Spalten nicht findet.
    Methoden-Wörter werden über die Ignorierliste der Einstellungen gefiltert.
    """

    name = "GFN-Klassenbuch (Textmodus)"

    def can_parse(self, doc: fitz.Document) -> bool:
        return "Datum:" in (doc[0].get_text("text") if len(doc) else "")

    def parse(self, doc: fitz.Document, path: Path) -> ParsedPdf:
        text = "\n".join(page.get_text("text") for page in doc)
        m = re.search(r"Datum:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if not m:
            raise PdfParseError("Kein Datum gefunden (Feld „Datum:“)")
        day, month, year = map(int, m.groups())
        date = dt.date(year, month, day)
        tm = re.search(r"Titel:\s*(.+)", text)
        title = tm.group(1).strip() if tm else ""
        lines = [_norm_space(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        trainers_raw = [l for l in lines if TRAINER_RE.match(l)]
        trainer_set = set(trainers_raw)
        lessons: dict[int, Lesson] = {}
        i = 0
        while i < len(lines):
            if re.fullmatch(r"\d{1,2}", lines[i]):
                nr = int(lines[i])
                i += 1
                chunk: list[str] = []
                while i < len(lines) and not re.fullmatch(r"\d{1,2}", lines[i]):
                    line = lines[i]
                    if FOOTER_RE.search(line):
                        break
                    if not (line in trainer_set or line.startswith(LEGACY_SKIP_PREFIXES) or line in LEGACY_SKIP_EXACT):
                        chunk.append(line)
                    i += 1
                trainer = next((t for t in trainers_raw), "")
                if nr in lessons:
                    lessons[nr].topics += chunk
                else:
                    lessons[nr] = Lesson(nr, chunk, [], trainer)
                continue
            i += 1
        trainers: list[str] = []
        for t in trainers_raw:
            name = trainer_display_name(t)
            if name not in trainers:
                trainers.append(name)
        issues = [Issue(Severity.INFO, "Tabelle nicht erkannt, Textmodus verwendet – bitte Text prüfen", path.name)]
        return ParsedPdf(path, date, parse_lernfeld(title), title, trainers,
                         [lessons[k] for k in sorted(lessons)], self.name, issues)


DEFAULT_PARSERS: tuple[KlassenbuchParser, ...] = (GfnKlassenbuchParser(), GfnTextModeParser())


def parse_pdf(path: Path, parsers: Iterable[KlassenbuchParser] = DEFAULT_PARSERS) -> ParsedPdf:
    """Eine PDF mit dem ersten passenden Parser lesen.

    Wirft ``PdfParseError`` mit einer verständlichen Meldung.
    """
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # beschädigte Datei, kein PDF ...
        raise PdfParseError("Datei ist keine lesbare PDF") from exc
    with doc:
        if doc.needs_pass:
            raise PdfParseError("PDF ist passwortgeschützt")
        if len(doc) == 0:
            raise PdfParseError("PDF ist leer")
        last_error: PdfParseError | None = None
        for parser in parsers:
            if not parser.can_parse(doc):
                continue
            try:
                return parser.parse(doc, path)
            except PdfParseError as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise PdfParseError("Unbekanntes Format – keine GFN-Themendokumentation (Klassenbuch)")
