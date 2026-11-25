import datetime as dt
import shutil

import fixtures
from berichtsheft.core.models import Severity
from berichtsheft.core.week import build_week, monday_of, parse_many, plan_from_paths


def test_full_week(week_pdfs, settings):
    plan = plan_from_paths(week_pdfs, settings)
    assert plan.monday == dt.date(2026, 6, 15)
    assert plan.friday == dt.date(2026, 6, 19)
    assert list(plan.days) == ["Mo", "Di", "Mi", "Do", "Fr"]
    assert plan.trainers == [fixtures.TRAINER_DISPLAY]
    assert all(d.lernfeld == "LF-ZQ9x" for d in plan.days.values())
    assert not [i for i in plan.issues if i.severity is not Severity.INFO]


def test_two_pdfs_same_day_are_merged(tmp_path, settings):
    d = dt.date(2026, 6, 15)
    a = fixtures.make_klassenbuch_pdf(tmp_path / "vormittag.pdf", d, [fixtures.FakeLesson(["Thema A"])])
    b = fixtures.make_klassenbuch_pdf(tmp_path / "nachmittag.pdf", d, [fixtures.FakeLesson(["Thema B"])],
                                      title="LF-ZQ9x Musterkurs", trainer="Beispiel, Erika")
    plan = plan_from_paths([a, b], settings)
    day = plan.days["Mo"]
    assert len(day.sources) == 2
    assert "Thema A" in day.text and "Thema B" in day.text
    assert sorted(day.trainers) == ["Erika Beispiel", "Max Mustermann"]


def test_identical_duplicate_is_reported(tmp_path, week_pdfs, settings):
    copy = tmp_path / "kopie.pdf"
    shutil.copyfile(week_pdfs[0], copy)
    plan = plan_from_paths([week_pdfs[0], copy], settings)
    assert any("doppelt" in i.message for i in plan.days["Mo"].issues)
    assert plan.days["Mo"].text.count("Grundlagen der Datensicherung") == 1


def test_weekend_is_reported(tmp_path, settings):
    sat = fixtures.make_klassenbuch_pdf(tmp_path / "sa.pdf", dt.date(2026, 6, 20), [fixtures.FakeLesson(["X"])])
    plan = plan_from_paths([sat], settings)
    assert not plan.days
    assert any("Wochenende" in i.message for i in plan.issues)


def test_other_week_is_warned_and_ignored(tmp_path, week_pdfs, settings):
    other = fixtures.make_klassenbuch_pdf(tmp_path / "alt.pdf", dt.date(2026, 6, 8), [fixtures.FakeLesson(["Alt"])])
    plan = plan_from_paths([*week_pdfs, other], settings)
    assert plan.monday == dt.date(2026, 6, 15)
    assert any("mehreren Wochen" in i.message for i in plan.issues)
    assert "Alt" not in plan.days["Mo"].text


def test_missing_days_info(week_pdfs, settings):
    plan = plan_from_paths(week_pdfs[:3], settings)
    assert any("Do, Fr" in i.message for i in plan.issues)


def test_bad_pdf_does_not_stop_others(tmp_path, week_pdfs, settings):
    bad = tmp_path / "kaputt.pdf"
    bad.write_bytes(b"x")
    res = parse_many([bad, week_pdfs[0]])
    assert len(res.parsed) == 1
    assert res.issues[0].severity is Severity.ERROR and res.issues[0].source == "kaputt.pdf"
    plan = build_week(res.parsed, settings, res.issues)
    assert "Mo" in plan.days


def test_monday_of():
    assert monday_of(dt.date(2026, 6, 19)) == dt.date(2026, 6, 15)
