from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402


@pytest.fixture(scope="session")
def fx_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("fixtures")
    fixtures.make_week(d / "week")
    fixtures.make_template(d / "Vorlage.docx")
    fixtures.make_template(d / "Vorlage_Schrift.docx", content_font="Courier New")
    fixtures.make_placeholder_template(d / "Vorlage_Platzhalter.docx")
    return d


@pytest.fixture()
def week_pdfs(fx_dir) -> list[Path]:
    return sorted((fx_dir / "week").glob("*.pdf"))


@pytest.fixture()
def profile():
    from berichtsheft.core.config import Profile
    return Profile(name="Max Mustermann", jahrgang="2025")


@pytest.fixture()
def settings(profile):
    return profile.summarizer_settings()
