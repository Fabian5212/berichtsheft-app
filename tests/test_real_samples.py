"""Optionaler Test mit echten Klassenbuch-PDFs (werden NICHT ins Repo committet).

    set BERICHTSHEFT_SAMPLES=C:\Pfad\zu\Klassenbuch-PDFs
    pytest tests/test_real_samples.py
"""

import os
from pathlib import Path

import pytest

from berichtsheft.core.config import DEFAULT_IGNORE_LINES
from berichtsheft.core.week import parse_many

SAMPLES = os.environ.get("BERICHTSHEFT_SAMPLES")
pytestmark = pytest.mark.skipif(not SAMPLES, reason="BERICHTSHEFT_SAMPLES nicht gesetzt")


def _pdfs():
    return sorted(Path(SAMPLES).rglob("*.pdf")) if SAMPLES else []


@pytest.mark.parametrize("pdf", _pdfs(), ids=lambda p: p.name)
def test_real_pdf(pdf, settings):
    from berichtsheft.core.summarizer import summarize

    res = parse_many([pdf])
    assert not res.issues, res.issues
    parsed = res.parsed[0]
    assert parsed.lernfeld, "Lernfeld nicht erkannt"
    assert parsed.trainers, "Dozent nicht erkannt"
    assert parsed.lessons, "keine Stunden"
    text, _ = summarize(parsed.lessons, parsed.trainers, settings)
    assert len(text) <= settings.max_chars
    assert text.endswith(".")
    for t in parsed.trainers:
        for part in t.split():
            assert part not in text, f"Dozent im Text: {part}"
    for method in DEFAULT_IGNORE_LINES:
        assert f" {method} " not in f" {text} ", f"Methode im Text: {method}"
    assert "//" not in text
