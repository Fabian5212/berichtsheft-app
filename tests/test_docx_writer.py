import datetime as dt

from docx import Document
from docx.oxml.ns import qn

from berichtsheft.core.docx_writer import (
    DayContent,
    ReportData,
    WriteOptions,
    analyze_template,
    build_filename,
    fill_template,
)


def _data(**kw):
    days = {c: DayContent(dt.date(2026, 6, 15 + i), f"Text für {c}.", "LF-ZQ9x")
            for i, c in enumerate(["Mo", "Di", "Mi", "Do", "Fr"])}
    base = dict(nachweis_nr=12, vom=dt.date(2026, 6, 15), bis=dt.date(2026, 6, 19), days=days,
                trainers=["Max Mustermann"], profile_values={"NAME": "Erika Neu", "JAHRGANG": "2025"},
                signature_date=dt.date(2026, 6, 19))
    base.update(kw)
    return ReportData(**base)


def _row_texts(path):
    t = Document(str(path)).tables[0]
    return [[c.text for c in r.cells] for r in t.rows]


# --- Analyse ------------------------------------------------------------------

def test_analyze_gfn_template(fx_dir):
    info = analyze_template(fx_dir / "Vorlage.docx")
    assert list(info.day_rows) == ["Mo", "Di", "Mi", "Do", "Fr"]
    assert info.nachweis_nr == 7
    assert info.vom == dt.date(2026, 6, 15)   # "15.06." ohne Jahr -> Jahr aus "bis"
    assert info.bis == dt.date(2026, 6, 19)
    assert info.column_method == "Kopfzeile"
    assert info.has_signature_date
    assert info.summary().startswith("5 Tageszeilen gefunden")


def test_analyze_placeholder_template(fx_dir):
    info = analyze_template(fx_dir / "Vorlage_Platzhalter.docx")
    assert {"NAME", "JAHRGANG", "VOM", "BIS", "NACHWEIS_NR", "JAHR", "DOZENT"} <= set(info.placeholders)
    assert info.unknown_placeholders == ["FOO"]
    assert "Platzhalter: NAME" in info.summary()


def test_analyze_not_a_docx(tmp_path):
    bad = tmp_path / "x.docx"
    bad.write_text("kein word")
    info = analyze_template(bad)
    assert not info.usable and info.issues


# --- Befüllen -----------------------------------------------------------------

def test_fill_day_rows_and_lernfeld(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(), WriteOptions(overwrite_existing=True))
    rows = _row_texts(out)
    assert rows[4][1] == "Text für Mo."
    assert rows[4][7] == "LF-ZQ9x"
    assert rows[4][8] == "8"          # Std. bleibt
    assert rows[8][1] == "Text für Fr."


def test_merged_cells_stay_merged(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(), WriteOptions())
    before = Document(str(fx_dir / "Vorlage.docx")).tables[0]._tbl
    after = Document(str(out)).tables[0]._tbl
    assert [len(tr.tc_lst) for tr in before.tr_lst] == [len(tr.tc_lst) for tr in after.tr_lst]


def test_content_font_size_and_bold(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(), WriteOptions(content_font_size=8, content_bold=True,
                                                                       lernfeld_font_size=12))
    row = Document(str(out)).tables[0].rows[4]
    run = row.cells[1].paragraphs[0].runs[0]
    assert run.font.size.pt == 8 and run.bold
    assert row.cells[7].paragraphs[0].runs[0].font.size.pt == 12


def test_template_font_is_kept(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage_Schrift.docx", out, _data(),
                  WriteOptions(content_font_size=None, content_bold=None))
    run = Document(str(out)).tables[0].rows[4].cells[1].paragraphs[0].runs[0]
    fonts = run._r.find(qn("w:rPr")).find(qn("w:rFonts"))
    assert fonts.get(qn("w:ascii")) == "Courier New"


def test_header_fields(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(), WriteOptions())
    rows = _row_texts(out)
    assert rows[0][8] == "12"
    assert rows[0][2] == "Erika Neu"
    assert rows[2][2] == "15.06."        # Stil der Vorlage (ohne Jahr) bleibt
    assert rows[2][4] == "19.06.26"
    assert rows[1][5] == "Trainer/Ausbilder: Max Mustermann"   # Dozent aus den PDFs
    assert rows[1][2] == "2025"                                  # Jahrgang aus dem Profil
    # Formatierung der Kopfzelle (fett, 10 pt) bleibt
    run = Document(str(out)).tables[0].rows[1].cells[5].paragraphs[0].runs[0]
    assert run.bold and run.font.size.pt == 10


def test_header_fields_can_be_disabled(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(), WriteOptions(write_header_fields=False))
    assert _row_texts(out)[0][8] == "7"


def test_signature_date(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage.docx", out, _data(signature_date=dt.date(2026, 6, 18)), WriteOptions())
    texts = [p.text for p in Document(str(out)).paragraphs]
    assert any("18.06.2026" in t for t in texts)


def test_existing_content_not_overwritten(fx_dir, tmp_path):
    first = tmp_path / "1.docx"
    fill_template(fx_dir / "Vorlage.docx", first, _data(), WriteOptions())
    second = tmp_path / "2.docx"
    data = _data()
    data.days["Mo"] = DayContent(dt.date(2026, 6, 15), "NEU", "LF-ZQ9x")
    issues = fill_template(first, second, data, WriteOptions(overwrite_existing=False))
    assert _row_texts(second)[4][1] == "Text für Mo."
    assert any("nicht überschrieben" in i.message for i in issues)
    fill_template(first, second, data, WriteOptions(overwrite_existing=True))
    assert _row_texts(second)[4][1] == "NEU"


def test_placeholders_split_runs_header_and_body(fx_dir, tmp_path):
    out = tmp_path / "out.docx"
    fill_template(fx_dir / "Vorlage_Platzhalter.docx", out, _data(), WriteOptions())
    doc = Document(str(out))
    body = [p.text for p in doc.paragraphs]
    assert body[0] == "Name: Erika Neu – Jahrgang: 2025"
    assert body[1] == "Nachweis 12 vom 15.06.2026 bis 19.06.2026 (2026), Dozent: Max Mustermann"
    assert "{{FOO}}" in body[-1]            # unbekannte bleiben stehen
    assert doc.sections[0].header.paragraphs[0].text == "Berichtsheft Erika Neu"
    assert doc.tables[0].rows[1].cells[1].text == "Text für Mo."
    assert doc.tables[0].rows[1].cells[2].text == "LF-ZQ9x"


# --- Dateiname ----------------------------------------------------------------

def test_build_filename():
    name = build_filename("Berichtsheft Woche {NR} ({VOM}-{BIS}).docx", 55, dt.date(2026, 6, 29), dt.date(2026, 7, 3))
    assert name == "Berichtsheft Woche 55 (29.06.26-03.07.26).docx"


def test_build_filename_without_dates_and_bad_chars():
    assert build_filename("Woche {NR} ({VOM}-{BIS})", 3, None, None) == "Woche 3.docx"
    assert build_filename("a/b:c {NR}.docx", 1, None, None) == "a-b-c 1.docx"


def test_example_template_from_docs(tmp_path):
    from pathlib import Path
    tpl = Path(__file__).resolve().parents[1] / "docs" / "Beispielvorlage_Platzhalter.docx"
    out = tmp_path / "out.docx"
    fill_template(tpl, out, _data(), WriteOptions())
    doc = Document(str(out))
    rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
    assert rows[0][2] == "Erika Neu" and rows[0][8] == "12"
    assert rows[1][2] == "2025"
    assert rows[2][2] == "15.06.2026" and rows[2][4] == "19.06.2026"
    assert rows[1][5] == "Trainer/Ausbilder: Max Mustermann"
    assert rows[4][1] == "Text für Mo."
    assert "{{" not in "".join(p.text for p in doc.paragraphs)
