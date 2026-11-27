"""PDFs einer Woche zusammenführen und prüfen."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .models import WORKDAY_CODES, DayEntry, Issue, Lesson, ParsedPdf, Severity, WeekPlan
from .pdf_parser import KlassenbuchParser, DEFAULT_PARSERS, PdfParseError, parse_pdf
from .summarizer import SummarizerSettings, summarize


def monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


@dataclass
class ParseResult:
    parsed: list[ParsedPdf] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def parse_many(paths: Iterable[Path], parsers: Iterable[KlassenbuchParser] = DEFAULT_PARSERS) -> ParseResult:
    """Alle PDFs lesen. Fehler pro Datei werden gesammelt, nie geworfen."""
    result = ParseResult()
    parser_list = tuple(parsers)
    for path in paths:
        try:
            pdf = parse_pdf(path, parser_list)
        except PdfParseError as exc:
            result.issues.append(Issue(Severity.ERROR, str(exc), path.name))
            continue
        except Exception as exc:  # noqa: BLE001 – unerwartet, aber App soll weiterlaufen
            result.issues.append(Issue(Severity.ERROR, f"Unerwarteter Fehler beim Lesen ({type(exc).__name__})", path.name))
            continue
        result.parsed.append(pdf)
    return result


def _lesson_key(lesson: Lesson) -> tuple:
    return (lesson.number, tuple(lesson.topics))


def available_weeks(parsed: list[ParsedPdf]) -> list[tuple[dt.date, int]]:
    """Alle Wochen (Montag, Anzahl PDFs) in den PDFs, neueste zuerst. Wochenenden zählen nicht."""
    weeks = Counter(monday_of(p.date) for p in parsed if p.date.weekday() < 5)
    return sorted(weeks.items(), key=lambda kv: kv[0], reverse=True)


def build_week(parsed: list[ParsedPdf], settings: SummarizerSettings, base_issues: list[Issue] | None = None,
               monday: dt.date | None = None) -> WeekPlan:
    """Tage Mo–Fr bilden, doppelte/fremde Tage melden und Texte erzeugen.

    ``monday`` wählt bei PDFs aus mehreren Wochen die gewünschte Woche aus
    (z. B. wenn ein ganzer Ordner hineingezogen wurde). Ohne Angabe wird die
    Woche mit den meisten PDFs genommen, bei Gleichstand die neueste.
    """
    issues: list[Issue] = list(base_issues or [])
    if not parsed:
        return WeekPlan(None, {}, issues)

    # Wochenende melden und aussortieren
    workdays: list[ParsedPdf] = []
    for pdf in parsed:
        if pdf.date.weekday() >= 5:
            issues.append(Issue(Severity.WARNING, f"{pdf.date:%d.%m.%Y} ist ein Wochenende – nicht übernommen", pdf.path.name))
        else:
            workdays.append(pdf)
    if not workdays:
        return WeekPlan(None, {}, issues)

    # Mehrere Wochen? -> gewählte Woche, sonst die mit den meisten PDFs (bei Gleichstand die neueste)
    weeks = Counter(monday_of(p.date) for p in workdays)
    if monday is None or monday not in weeks:
        monday, _ = max(weeks.items(), key=lambda kv: (kv[1], kv[0]))
    if len(weeks) > 1:
        others = sorted(w for w in weeks if w != monday)
        names = ", ".join(f"{w:%d.%m.}–{w + dt.timedelta(days=4):%d.%m.%Y}" for w in others)
        issues.append(Issue(
            Severity.WARNING,
            f"PDFs aus {len(weeks)} Wochen gefunden. Verwendet wird {monday:%d.%m.}–{monday + dt.timedelta(days=4):%d.%m.%Y}; "
            f"nicht verwendet: {names}",
        ))
    in_week = [p for p in workdays if monday_of(p.date) == monday]

    # Mehrere PDFs pro Tag zusammenführen
    by_date: dict[dt.date, list[ParsedPdf]] = {}
    for p in in_week:
        by_date.setdefault(p.date, []).append(p)

    days: dict[str, DayEntry] = {}
    for date, pdfs in sorted(by_date.items()):
        pdfs.sort(key=lambda p: (min((l.number for l in p.lessons), default=0), p.path.name))
        day_issues: list[Issue] = []
        lessons: list[Lesson] = []
        seen: set[tuple] = set()
        duplicates = 0
        for p in pdfs:
            for lesson in p.lessons:
                k = _lesson_key(lesson)
                if k in seen:
                    duplicates += 1
                    continue
                seen.add(k)
                lessons.append(lesson)
        if len(pdfs) > 1:
            if duplicates and duplicates == sum(len(p.lessons) for p in pdfs[1:]):
                day_issues.append(Issue(Severity.WARNING, f"{len(pdfs)} PDFs mit identischem Inhalt für diesen Tag – doppelt?"))
            else:
                day_issues.append(Issue(Severity.INFO, f"{len(pdfs)} PDFs für diesen Tag zusammengeführt"))
        lessons.sort(key=lambda l: l.number)

        lernfelder = [p.lernfeld for p in pdfs if p.lernfeld]
        lernfeld = "/".join(dict.fromkeys(lernfelder))
        trainers: list[str] = []
        for p in pdfs:
            for t in p.trainers:
                if t not in trainers:
                    trainers.append(t)
        for p in pdfs:
            day_issues.extend(i for i in p.issues if i.severity is not Severity.INFO)
        if not lernfeld:
            day_issues.append(Issue(Severity.WARNING, "Lernfeld nicht erkannt"))

        text, text_issues = summarize(lessons, trainers, settings)
        day_issues.extend(text_issues)
        entry = DayEntry(date, lernfeld, trainers, lessons, [p.path for p in pdfs], text, day_issues)
        days[entry.day_code] = entry

    missing = [c for c in WORKDAY_CODES if c not in days]
    if missing:
        issues.append(Issue(Severity.INFO, "Keine PDF für: " + ", ".join(missing)))
    return WeekPlan(monday, days, issues)


def plan_from_paths(paths: Iterable[Path], settings: SummarizerSettings,
                    parsers: Iterable[KlassenbuchParser] = DEFAULT_PARSERS) -> WeekPlan:
    res = parse_many(sorted(paths), parsers)
    return build_week(res.parsed, settings, res.issues)
