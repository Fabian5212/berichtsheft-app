"""Kommandozeile – kompatibel zum alten ``berichtsheft_auto.py`` (v9).

    python cli.py --template "00_Vorlage/Berichtsheft Blanko Woche  ().docx" --pdfdir 01_Klassenbuch --overwrite

Wie früher:
* Nachweis-Nr. und Zeitraum kommen aus der Vorlage; fehlen sie dort, werden
  sie aus den PDF-Daten berechnet.
* Die Kopfzeilen der Vorlage bleiben unverändert (außer mit ``--fill-header``).
* Ignorierliste, Ersetzungen und Formatierung kommen aus dem App-Profil, falls
  vorhanden (``--config``), sonst aus den Standardwerten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core.config import ConfigError, Profile, default_config_path, load_config
from .core.docx_writer import analyze_template
from .core.models import Severity
from .core.service import HeaderValues, create_report, output_path, prepare_week


def _profile(config: str | None, use_config: bool) -> Profile:
    if not use_config:
        return Profile()
    path = Path(config) if config else default_config_path()
    try:
        return load_config(path).profile
    except ConfigError as exc:
        print(f"WARNUNG: {exc} – verwende Standardwerte", file=sys.stderr)
        return Profile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Berichtsheft automatisch aus Klassenbuch-PDFs befüllen")
    parser.add_argument("--template", default="00_Vorlage/Berichtsheft Blanko Woche  ().docx", help="Vorbereitete Berichtsheft-DOCX")
    parser.add_argument("--pdfdir", default="01_Klassenbuch", help="Ordner mit Klassenbuch-PDFs")
    parser.add_argument("--out", default=None, help="Ausgabe-DOCX. Wenn leer, wird der Dateiname automatisch erstellt.")
    parser.add_argument("--outdir", default="02_Ausgabe", help="Ausgabeordner für den automatischen Dateinamen")
    parser.add_argument("--overwrite", action="store_true", help="Vorhandene Tagesinhalte überschreiben")
    parser.add_argument("--fill-header", action="store_true", help="Nachweis-Nr./Zeitraum/Name/Dozent in die Kopfzellen schreiben")
    parser.add_argument("--nr", type=int, default=None, help="Nachweis-Nr. erzwingen")
    parser.add_argument("--config", default=None, help="Pfad zur config.json der App (Standard: %%APPDATA%%\\Berichtsheft)")
    parser.add_argument("--no-config", action="store_true", help="App-Einstellungen ignorieren, nur Standardwerte")
    args = parser.parse_args(argv)

    template = Path(args.template)
    pdfdir = Path(args.pdfdir)
    if not template.exists():
        print(f"FEHLER: Vorlage nicht gefunden: {template}", file=sys.stderr)
        return 1
    if not pdfdir.exists():
        print(f"FEHLER: PDF-Ordner nicht gefunden: {pdfdir}", file=sys.stderr)
        return 1
    pdfs = sorted(pdfdir.glob("*.pdf"))
    if not pdfs:
        print(f"FEHLER: Keine PDFs in {pdfdir} gefunden", file=sys.stderr)
        return 1

    profile = _profile(args.config, not args.no_config)
    profile.write_header_fields = args.fill_header
    info = analyze_template(template)
    for issue in info.issues:
        print(f"{issue.severity.value.upper()}: {issue}", file=sys.stderr)
    if not info.usable:
        return 1
    print(f"Vorlage: {info.summary()}")

    plan = prepare_week(pdfs, profile)
    for issue in plan.issues:
        print(str(issue), file=sys.stderr if issue.severity is not Severity.INFO else sys.stdout)
    if not plan.days:
        print("FEHLER: Keine verwertbaren PDFs gefunden", file=sys.stderr)
        return 1
    for code, day in plan.days.items():
        files = ", ".join(p.name for p in day.sources)
        print(f"OK: {files} -> {code} {day.date:%d.%m.%Y} | {day.lernfeld} | {', '.join(day.trainers)}")
        print(f"    {day.text}")
        for issue in day.issues:
            print(f"    {issue}")

    # wie v9: Werte der Vorlage haben Vorrang, PDFs füllen Lücken.
    # Mit --fill-header wird der Zeitraum aus den PDFs genommen und eingetragen.
    if args.fill_header:
        vom, bis = plan.monday or info.vom, plan.friday or info.bis
    else:
        vom, bis = info.vom or plan.monday, info.bis or plan.friday
        if info.vom and plan.monday and info.vom != plan.monday:
            print(f"WARNUNG: Vorlage ist für die Woche ab {info.vom:%d.%m.%Y}, die PDFs sind aus der Woche ab "
                  f"{plan.monday:%d.%m.%Y}. Mit --fill-header werden Nr./Zeitraum aus den PDFs eingetragen.",
                  file=sys.stderr)
    header = HeaderValues(
        nachweis_nr=args.nr if args.nr is not None else info.nachweis_nr,
        vom=vom,
        bis=bis,
    )
    if header.nachweis_nr is None:
        header.nachweis_nr = profile.suggest_nachweis_nr(plan.monday)
    out = Path(args.out) if args.out else output_path(profile, Path(args.outdir), header)
    issues = create_report(template, out, plan, header, profile, args.overwrite)
    for issue in issues:
        print(str(issue), file=sys.stderr if issue.severity is Severity.ERROR else sys.stdout)
    if any(i.severity is Severity.ERROR for i in issues):
        return 1
    print(f"\nFertig: {out}")
    print("Bitte Datei öffnen, kurz prüfen und dann wie gewohnt speichern/abgeben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
