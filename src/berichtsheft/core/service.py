"""Ablauf "PDFs -> Woche -> Word-Datei", gemeinsam genutzt von GUI und CLI."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from .config import Profile
from .docx_writer import DayContent, ReportData, TemplateInfo, WriteOptions, analyze_template, build_filename, fill_template
from .models import Issue, Severity, WeekPlan
from .week import plan_from_paths


def prepare_week(pdf_paths: list[Path], profile: Profile) -> WeekPlan:
    return plan_from_paths(pdf_paths, profile.summarizer_settings())


@dataclass
class HeaderValues:
    nachweis_nr: int | None
    vom: dt.date | None
    bis: dt.date | None
    notes: list[str] = field(default_factory=list)


def suggest_header(plan: WeekPlan, template: TemplateInfo | None, profile: Profile) -> HeaderValues:
    """Nachweis-Nr. und Zeitraum vorschlagen.

    Zeitraum: aus den PDFs (Mo–Fr der Woche), sonst aus der Vorlage.
    Nachweis-Nr.: je nach Profil-Einstellung, sonst aus der Vorlage.
    """
    notes: list[str] = []
    vom, bis = plan.monday, plan.friday
    if vom is None and template is not None:
        vom, bis = template.vom, template.bis
        if vom:
            notes.append("Zeitraum aus der Vorlage übernommen")
    nr = profile.suggest_nachweis_nr(plan.monday)
    if nr is None and template is not None and template.nachweis_nr is not None:
        nr = template.nachweis_nr
        notes.append("Nachweis-Nr. aus der Vorlage übernommen")
    return HeaderValues(nr, vom, bis, notes)


def write_options(profile: Profile, overwrite: bool) -> WriteOptions:
    f = profile.formatting
    return WriteOptions(
        overwrite_existing=overwrite,
        content_font_size=f.content_font_size or None,
        content_bold=f.content_bold,
        lernfeld_font_size=f.lernfeld_font_size or None,
        lernfeld_bold=f.lernfeld_bold,
        write_lernfeld=profile.write_lernfeld,
        write_header_fields=profile.write_header_fields,
        write_hours=profile.write_hours,
        hours_value=profile.hours_per_day,
        update_signature_date=profile.update_signature_date,
    )


def output_path(profile: Profile, out_dir: Path, header: HeaderValues) -> Path:
    return out_dir / build_filename(profile.filename_pattern, header.nachweis_nr, header.vom, header.bis)


def create_report(
    template_path: Path,
    out_path: Path,
    plan: WeekPlan,
    header: HeaderValues,
    profile: Profile,
    overwrite: bool,
    texts: dict[str, str] | None = None,
) -> list[Issue]:
    """Word-Datei erzeugen. ``texts`` überschreibt die generierten Tagestexte (GUI-Bearbeitung)."""
    days: dict[str, DayContent] = {}
    for code, day in plan.days.items():
        text = (texts or {}).get(code, day.text)
        days[code] = DayContent(day.date, text.strip(), day.lernfeld)
    data = ReportData(
        nachweis_nr=header.nachweis_nr,
        vom=header.vom,
        bis=header.bis,
        days=days,
        trainers=plan.trainers,
        profile_values=profile.placeholder_values(),
        signature_date=plan.last_day or header.bis,
    )
    try:
        return fill_template(template_path, out_path, data, write_options(profile, overwrite))
    except PermissionError:
        return [Issue(Severity.ERROR, f"„{out_path.name}“ ist gesperrt – ist die Datei noch in Word geöffnet?")]
    except FileNotFoundError:
        return [Issue(Severity.ERROR, f"Vorlage nicht gefunden: {template_path}")]


def remember_week(profile: Profile, header: HeaderValues) -> None:
    """Nach erfolgreichem Erstellen: Nr. und Woche fürs nächste Mal merken."""
    if header.nachweis_nr is not None:
        profile.last_nachweis_nr = header.nachweis_nr
    if header.vom is not None:
        monday = header.vom - dt.timedelta(days=header.vom.weekday())
        profile.last_week_monday = monday.isoformat()


__all__ = [
    "HeaderValues", "prepare_week", "suggest_header", "create_report", "output_path",
    "remember_week", "write_options", "analyze_template",
]
