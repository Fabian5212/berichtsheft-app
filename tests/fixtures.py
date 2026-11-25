"""Erzeugt anonymisierte Test-Dateien.

Die PDFs bilden das Layout der GFN-„Themendokumentation“ nach (gleiche
Spalten, Linien, Schriftgrößen, Kopf-/Fußzeilen, Seitenumbruch), enthalten aber
nur erfundene Namen und Inhalte. Echte Klassenbuch-PDFs gehören nicht ins Repo.

Auch direkt aufrufbar: ``python tests/fixtures.py <zielordner>``
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from docx import Document
from docx.enum.text import WD_BREAK  # noqa: F401  (für Erweiterungen)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

TRAINER = "Mustermann, Max"
TRAINER_DISPLAY = "Max Mustermann"

COL_X = [30, 74, 359, 459, 549]   # Spaltengrenzen wie im Original
LINE_H = 8.4


@dataclass
class FakeLesson:
    topics: list[str]
    methods: list[str] = field(default_factory=lambda: ["Lehr-/Lerngespräch"])


def make_klassenbuch_pdf(
    path: Path,
    date: dt.date,
    lessons: list[FakeLesson],
    title: str = "LF-ZQ9x Musterkurs Systemintegration",
    trainer: str = TRAINER,
    lessons_per_page: int = 8,
    draw_lines: bool = True,
) -> Path:
    """Eine Klassenbuch-PDF im GFN-Layout erzeugen."""
    doc = fitz.open()
    last, first = trainer.split(", ")
    chunks = [lessons[i:i + lessons_per_page] for i in range(0, len(lessons), lessons_per_page)] or [[]]
    number = 1
    for page_idx, chunk in enumerate(chunks):
        page = doc.new_page(width=595, height=842)
        top = 47 if page_idx == 0 else 17
        if page_idx == 0:
            page.insert_text((205.6, 32), "Themendokumentation", fontsize=16, fontname="hebo")
        y = top + 10
        page.insert_text((33, y), "Datum:", fontsize=10, fontname="hebo")
        page.insert_text((80, y), f"{date:%d.%m.%Y}", fontsize=10)
        page.insert_text((150, y), "MaßnahmeNr.:", fontsize=10, fontname="hebo")
        page.insert_text((230, y), "000/000/2025        ,", fontsize=10)
        page.insert_text((33, y + 38), "Raum:", fontsize=10, fontname="hebo")
        page.insert_text((80, y + 38), "unbekannt", fontsize=10)
        page.insert_text((150, y + 38), "Titel:", fontsize=10, fontname="hebo")
        page.insert_text((230, y + 38), title, fontsize=10)
        page.insert_text((33, y + 72), "Unterrichtsbeginn: 08:30", fontsize=7)

        header_top = top + 83
        header_bottom = header_top + 24
        page.insert_text((35.1, header_top + 18), "Stunde", fontsize=10, fontname="hebo")
        page.insert_text((189.6, header_top + 18), "Lehrinhalte", fontsize=10, fontname="hebo")
        page.insert_text((367.7, header_top + 18), "Lernformat/-methodik", fontsize=8, fontname="hebo")
        page.insert_text((487.4, header_top + 18), "Dozent", fontsize=10, fontname="hebo")
        if draw_lines:
            for x0, x1 in zip(COL_X, COL_X[1:]):
                page.draw_line((x0, header_top), (x1, header_top))
                page.draw_line((x0, header_bottom), (x1, header_bottom))
            for x in COL_X:
                page.draw_line((x, header_top), (x, header_bottom))

        row_top = header_bottom
        for lesson in chunk:
            n_lines = max(len(lesson.topics), len(lesson.methods), 1)
            height = max(40.0, n_lines * LINE_H + 8)
            page.insert_text((47.5, row_top + 13.6 + 12), str(number), fontsize=16)
            for i, t in enumerate(lesson.topics):
                page.insert_text((77, row_top + 4.4 + 7 + i * LINE_H), t, fontsize=7)
            for i, m in enumerate(lesson.methods):
                page.insert_text((362, row_top + 4.4 + 7 + i * LINE_H), m, fontsize=7)
            page.insert_text((462, row_top + 4.4 + 7), trainer, fontsize=7)
            bottom = row_top + height
            if draw_lines:
                for x0, x1 in zip(COL_X, COL_X[1:]):
                    page.draw_line((x0, bottom), (x1, bottom))
                for x in COL_X:
                    page.draw_line((x, row_top), (x, bottom))
            row_top = bottom
            number += 1

        page.insert_text((33, 716), f"ME-MUST.MAX // ABCDEFGH // {date:%d%m%Y}150000", fontsize=7)
        page.insert_text((33, 737), f"Hiermit bestätige ich, {first} {last}, den Unterricht in der 1. – 9. "
                                    "Unterrichtseinheit durchgeführt zu haben.", fontsize=7)
        page.insert_text((30, 805), "Unterschrift", fontsize=7)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def standard_day(variant: int = 0) -> list[FakeLesson]:
    """9 Stunden, Stunde 9 auf Seite 2, mit zweizeiliger Methode wie im Original."""
    projects = [
        ["Arbeiten am Projekt", "Planungsphase"],
        ["Arbeiten am Projekt", "Ist-Soll-Analyse, Konzept"],
        ["Arbeiten am Projekt", "Risikoanalyse"],
    ]
    return [
        FakeLesson(["Einweisung in die Agenda", "Grundlagen der Datensicherung"],
                   ["Frontalunterricht/Vortrag", "Lehr-/Lerngespräch"]),
        FakeLesson(["Backups wiederherstellen und prüfen"], ["Aufgaben-", "/Übungsbesprechung"]),
        FakeLesson(["Die verschiedenen Sicherungsarten"], ["Projektarbeit"]),
        *[FakeLesson(t, ["Projektarbeit", "betreute Einzelarbeit"]) for t in projects],
        FakeLesson([f"Vorlagenerstellung Testprotokoll {variant}"], ["Projektaufgabe"]),
        FakeLesson(["Vorlagenerstellung Abnahmeprotokoll"], ["Projektaufgabe"]),
        FakeLesson(["Vorlagenerstellung Benutzerhandbuch", "Vertiefen der Inhalte mit Unterlagen"], ["Rollenspiel"]),
    ]


def make_week(folder: Path, monday: dt.date = dt.date(2026, 6, 15), days: int = 5) -> list[Path]:
    paths = []
    for i in range(days):
        d = monday + dt.timedelta(days=i)
        paths.append(make_klassenbuch_pdf(folder / f"ME-MUST.MAX_TEST_{d:%d%m%Y}.pdf", d, standard_day(i)))
    return paths


# --------------------------------------------------------------------------- #
# Word-Vorlagen
# --------------------------------------------------------------------------- #

def _merge_row(table, row_idx: int, spans: list[int]):
    """Zellen einer Zeile gemäß ``spans`` horizontal verbinden. Gibt die Zellen zurück."""
    row = table.rows[row_idx]
    cells = []
    col = 0
    for span in spans:
        a = row.cells[col]
        if span > 1:
            a = a.merge(row.cells[col + span - 1])
        cells.append(a)
        col += span
    return cells


def _write(cell, text: str, bold: bool = False, size: float | None = None, font: str | None = None):
    cell.text = ""
    run = cell.paragraphs[0].add_run(text)
    run.bold = bold or None
    if size:
        run.font.size = Pt(size)
    if font:
        run.font.name = font


def make_template(path: Path, name: str = "Max Mustermann", nr: str = "7", vom: str = "15.06.",
                  bis: str = "19.06.26", content_font: str | None = None, placeholders: bool = False) -> Path:
    """Blanko-Vorlage im Aufbau der GFN-Berichtshefte (9 Rasterspalten, verbundene Zellen).

    ``placeholders=True`` erzeugt die Beispielvorlage für Endnutzer mit {{…}}-Platzhaltern.
    """
    if placeholders:
        name, nr, vom, bis = "{{NAME}}", "{{NACHWEIS_NR}}", "{{VOM}}", "{{BIS}}"
    doc = Document()
    table = doc.add_table(rows=9, cols=9)
    table.style = "Table Grid"
    r0 = _merge_row(table, 0, [2, 3, 1, 2, 1])
    _write(r0[0], "Name des/der Auszubildenden", bold=True, size=10)
    _write(r0[1], name)
    _write(r0[2], "Klasse: K1", bold=True, size=10)
    _write(r0[3], "Ausbildungsnachweis Nr.", bold=True, size=10)
    _write(r0[4], nr)
    r1 = _merge_row(table, 1, [2, 1, 2, 4])
    _write(r1[0], "Ausbildungsjahr", bold=True, size=10)
    _write(r1[1], "{{JAHRGANG}}" if placeholders else "2026")
    _write(r1[3], "Trainer/Ausbilder: {{DOZENT}}" if placeholders else "Trainer/Ausbilder: Erika Beispiel",
           bold=True, size=10)
    r2 = _merge_row(table, 2, [2, 1, 1, 1, 4])
    _write(r2[0], "Ausbildungswoche vom", bold=True, size=10)
    _write(r2[1], vom)
    _write(r2[2], "bis", bold=True, size=10)
    _write(r2[3], bis)
    r3 = _merge_row(table, 3, [1, 6, 1, 1])
    _write(r3[0], "Tag", bold=True, size=10)
    _write(r3[1], "Themen des Unterrichts beim Bildungsträger", size=10)
    _write(r3[2], "Lernfeld-Nr.", bold=True, size=10)
    _write(r3[3], "Std.", bold=True, size=10)
    for i, code in enumerate(["Mo", "Di", "Mi", "Do", "Fr"]):
        cells = _merge_row(table, 4 + i, [1, 6, 1, 1])
        _write(cells[0], code + " ", bold=True, size=10)
        if content_font:
            # leere Zelle, Formatierung nur an der Absatzmarke (wie in Word üblich)
            p = cells[1].paragraphs[0]._p
            ppr = p.get_or_add_pPr()
            rpr = OxmlElement("w:rPr")
            fonts = OxmlElement("w:rFonts")
            fonts.set(qn("w:ascii"), content_font)
            fonts.set(qn("w:hAnsi"), content_font)
            rpr.append(fonts)
            ppr.append(rpr)
        _write(cells[2], "" if placeholders else "LF-ALT")
        _write(cells[3], "8")
    doc.add_paragraph("Durch die nachfolgende Unterschrift wird die Richtigkeit bestätigt.")
    doc.add_paragraph("")
    doc.add_paragraph(("   {{DATUM}}" if placeholders else "   19.06.2026") + "                   \t\t____________________")
    doc.add_paragraph("Datum, Unterschrift der/des Auszubildenden\t\tDatum, Unterschrift der/des Ausbildenden")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def make_placeholder_template(path: Path, split_runs: bool = True) -> Path:
    """Eigene Vorlage mit Platzhaltern; ``{{NAME}}`` wird absichtlich auf mehrere Runs verteilt."""
    doc = Document()
    p = doc.add_paragraph()
    if split_runs:
        p.add_run("Name: {{NA")
        r = p.add_run("ME")
        r.bold = True
        p.add_run("}} – Jahrgang: {{JAHRGANG}}")
    else:
        p.add_run("Name: {{NAME}} – Jahrgang: {{JAHRGANG}}")
    doc.add_paragraph("Nachweis {{NACHWEIS_NR}} vom {{VOM}} bis {{BIS}} ({{JAHR}}), Dozent: {{DOZENT}}")
    table = doc.add_table(rows=6, cols=3)
    for c, t in zip(table.rows[0].cells, ["Tag", "Tätigkeit", "Lernfeld"]):
        c.text = t
    for i, code in enumerate(["Mo", "Di", "Mi", "Do", "Fr"]):
        cells = table.rows[i + 1].cells
        cells[0].text = code
    doc.add_paragraph("Unbekannt: {{FOO}}")
    section = doc.sections[0]
    section.header.paragraphs[0].text = "Berichtsheft {{NAME}}"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures_out")
    make_week(target / "pdf")
    make_template(target / "Vorlage.docx")
    make_placeholder_template(target / "Vorlage_Platzhalter.docx")
    print(f"Fixtures erzeugt in {target.resolve()}")
