"""Gemeinsame Datentypen der Kernlogik (ohne GUI-Abhängigkeiten)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

WEEKDAY_CODES: tuple[str, ...] = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
WORKDAY_CODES: tuple[str, ...] = WEEKDAY_CODES[:5]


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warnung"
    ERROR = "fehler"


@dataclass(frozen=True)
class Issue:
    """Eine verständliche Meldung für Nutzer:innen (kein Traceback)."""

    severity: Severity
    message: str
    source: str = ""

    def __str__(self) -> str:
        prefix = {Severity.INFO: "Info", Severity.WARNING: "Warnung", Severity.ERROR: "Fehler"}[self.severity]
        src = f" [{self.source}]" if self.source else ""
        return f"{prefix}{src}: {self.message}"


@dataclass
class Lesson:
    """Eine Unterrichtsstunde (Zeile der Klassenbuch-Tabelle)."""

    number: int
    topics: list[str]
    methods: list[str] = field(default_factory=list)
    trainer: str = ""


@dataclass
class ParsedPdf:
    """Ergebnis des Parsens einer Klassenbuch-PDF."""

    path: Path
    date: dt.date
    lernfeld: str = ""
    title: str = ""
    trainers: list[str] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)
    parser_name: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def day_code(self) -> str:
        return WEEKDAY_CODES[self.date.weekday()]


@dataclass
class DayEntry:
    """Alle Informationen für eine Tageszeile im Berichtsheft."""

    date: dt.date
    lernfeld: str
    trainers: list[str]
    lessons: list[Lesson]
    sources: list[Path]
    text: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def day_code(self) -> str:
        return WEEKDAY_CODES[self.date.weekday()]

    @property
    def ok(self) -> bool:
        return not any(i.severity is not Severity.INFO for i in self.issues)


@dataclass
class WeekPlan:
    """Zusammengeführte Woche: Tage Mo–Fr plus Meldungen."""

    monday: dt.date | None
    days: dict[str, DayEntry] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def friday(self) -> dt.date | None:
        return self.monday + dt.timedelta(days=4) if self.monday else None

    @property
    def trainers(self) -> list[str]:
        seen: list[str] = []
        for code in WORKDAY_CODES:
            day = self.days.get(code)
            if day:
                for t in day.trainers:
                    if t and t not in seen:
                        seen.append(t)
        return seen

    @property
    def last_day(self) -> dt.date | None:
        dates = [d.date for d in self.days.values()]
        return max(dates) if dates else None
