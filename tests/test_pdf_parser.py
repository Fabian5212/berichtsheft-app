import datetime as dt

import fitz
import pytest

import fixtures
from berichtsheft.core.pdf_parser import (
    GfnKlassenbuchParser,
    PdfParseError,
    parse_lernfeld,
    parse_pdf,
    trainer_display_name,
)


def test_header_fields(week_pdfs):
    pdf = parse_pdf(week_pdfs[0])
    assert pdf.date == dt.date(2026, 6, 15)
    assert pdf.day_code == "Mo"
    assert pdf.lernfeld == "LF-ZQ9x"
    assert pdf.trainers == [fixtures.TRAINER_DISPLAY]
    assert pdf.parser_name == GfnKlassenbuchParser.name


def test_all_lessons_including_second_page(week_pdfs):
    pdf = parse_pdf(week_pdfs[0])
    assert [l.number for l in pdf.lessons] == list(range(1, 10))
    assert pdf.lessons[-1].topics[0] == "Vorlagenerstellung Benutzerhandbuch"


def test_topics_contain_no_trainer_method_or_footer(week_pdfs):
    pdf = parse_pdf(week_pdfs[0])
    all_topics = " | ".join(t for l in pdf.lessons for t in l.topics)
    for bad in ("Mustermann", "Projektarbeit", "Lehr-/Lerngespräch", "Rollenspiel", "//", "Hiermit", "Unterschrift"):
        assert bad not in all_topics


def test_multiline_method_is_joined(week_pdfs):
    pdf = parse_pdf(week_pdfs[0])
    assert pdf.lessons[1].methods == ["Aufgaben-/Übungsbesprechung"]
    assert pdf.lessons[0].topics == ["Einweisung in die Agenda", "Grundlagen der Datensicherung"]


def test_trainer_from_column_not_from_text(tmp_path):
    # Ein "Nachname, Vorname"-Muster im Lehrinhalt darf nicht als Dozent erkannt werden
    lessons = [fixtures.FakeLesson(["Müller, Anna stellt Projekt vor"])]
    path = fixtures.make_klassenbuch_pdf(tmp_path / "a.pdf", dt.date(2026, 6, 15), lessons, trainer="Beispiel, Erika")
    pdf = parse_pdf(path)
    assert pdf.trainers == ["Erika Beispiel"]


def test_columns_without_table_lines(tmp_path):
    path = fixtures.make_klassenbuch_pdf(tmp_path / "nolines.pdf", dt.date(2026, 6, 16),
                                         fixtures.standard_day(), draw_lines=False)
    pdf = parse_pdf(path)
    assert len(pdf.lessons) == 9
    assert "Mustermann" not in " ".join(t for l in pdf.lessons for t in l.topics)


@pytest.mark.parametrize("title,expected", [
    ("LF-ZQ3b Microsoft Azure Administrator", "LF-ZQ3b"),
    ("LF12bV2 Kundenspezifische Systemintegration durchführen", "LF12bV2"),
    ("LF 09 Netzwerke", "LF09"),
    ("Ohne Lernfeld", ""),
])
def test_parse_lernfeld(title, expected):
    assert parse_lernfeld(title) == expected


def test_trainer_display_name():
    assert trainer_display_name("Beispiel, Erika") == "Erika Beispiel"
    assert trainer_display_name("Max Muster") == "Max Muster"


def test_broken_file_gives_readable_error(tmp_path):
    bad = tmp_path / "kaputt.pdf"
    bad.write_bytes(b"das ist keine pdf")
    with pytest.raises(PdfParseError, match="PDF"):
        parse_pdf(bad)


def test_foreign_pdf_gives_readable_error(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Rechnung Nr. 4711")
    path = tmp_path / "rechnung.pdf"
    doc.save(str(path))
    with pytest.raises(PdfParseError, match="Format"):
        parse_pdf(path)
