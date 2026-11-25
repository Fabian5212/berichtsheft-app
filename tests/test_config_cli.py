import datetime as dt
import json

import pytest
from docx import Document

from berichtsheft import cli
from berichtsheft.core.config import (
    AppConfig,
    ConfigError,
    Profile,
    import_template,
    load_config,
    save_config,
)


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig()
    cfg.profile.name = "Erika"
    cfg.profile.formatting.max_chars = 300
    cfg.profile.replacements.append({"wrong": "Fehler", "right": "Richtig", "regex": False, "ignore_case": False})
    cfg.profiles["Zweitprofil"] = Profile(name="Max")
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.profile.name == "Erika"
    assert loaded.profile.formatting.max_chars == 300
    assert loaded.profile.summarizer_settings().replacements[-1].wrong == "Fehler"
    assert set(loaded.profiles) == {"Standard", "Zweitprofil"}


def test_config_tolerates_unknown_and_missing_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"profiles": {"A": {"name": "X", "unbekannt": 1}}}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.active_profile == "A" and cfg.profile.name == "X"
    assert cfg.profile.formatting.max_chars == 430


def test_broken_config_is_backed_up(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
    assert (tmp_path / "config.defekt.json").exists()


def test_missing_config_gives_defaults(tmp_path):
    assert load_config(tmp_path / "nix.json").profile.name == ""


def test_import_template(tmp_path, fx_dir):
    target = import_template(fx_dir / "Vorlage.docx", tmp_path / "data")
    assert target.exists() and target.parent.name == "vorlagen"


@pytest.mark.parametrize("mode,kw,monday,expected", [
    ("increment", dict(last_nachweis_nr=54, last_week_monday="2026-06-22"), dt.date(2026, 6, 29), 55),
    ("increment", dict(last_nachweis_nr=54, last_week_monday="2026-06-22"), dt.date(2026, 7, 13), 57),
    ("increment", dict(last_nachweis_nr=54, last_week_monday="2026-06-22"), dt.date(2026, 6, 22), 54),
    ("increment", dict(last_nachweis_nr=54), dt.date(2026, 6, 29), 55),
    ("from_start", dict(ausbildungsbeginn="2025-06-04"), dt.date(2025, 6, 2), 1),
    ("from_start", dict(ausbildungsbeginn="2025-06-04"), dt.date(2026, 6, 29), 57),
    ("template", dict(last_nachweis_nr=54), dt.date(2026, 6, 29), None),
])
def test_suggest_nachweis_nr(mode, kw, monday, expected):
    assert Profile(nachweis_mode=mode, **kw).suggest_nachweis_nr(monday) == expected


# --- CLI (altes Verhalten) ----------------------------------------------------

def test_cli_like_v9(fx_dir, tmp_path, capsys):
    rc = cli.main(["--no-config", "--template", str(fx_dir / "Vorlage.docx"), "--pdfdir", str(fx_dir / "week"),
                   "--outdir", str(tmp_path), "--overwrite"])
    assert rc == 0
    out = tmp_path / "Berichtsheft Woche 7 (15.06.26-19.06.26).docx"
    assert out.exists()
    rows = Document(str(out)).tables[0].rows
    assert rows[4].cells[1].text.startswith("Behandelt wurden")
    assert rows[4].cells[7].text == "LF-ZQ9x"
    assert rows[1].cells[5].text == "Trainer/Ausbilder: Erika Beispiel"   # Kopf bleibt ohne --fill-header
    assert "Fertig:" in capsys.readouterr().out


def test_cli_fill_header(fx_dir, tmp_path):
    rc = cli.main(["--no-config", "--template", str(fx_dir / "Vorlage.docx"), "--pdfdir", str(fx_dir / "week"),
                   "--out", str(tmp_path / "x.docx"), "--fill-header", "--nr", "9"])
    assert rc == 0
    rows = Document(str(tmp_path / "x.docx")).tables[0].rows
    assert rows[0].cells[8].text == "9"
    assert rows[1].cells[5].text == "Trainer/Ausbilder: Max Mustermann"


def test_cli_errors(tmp_path):
    assert cli.main(["--template", str(tmp_path / "fehlt.docx")]) == 1
