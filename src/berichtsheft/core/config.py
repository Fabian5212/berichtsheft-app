"""Profil und Einstellungen.

Gespeichert als JSON in ``%APPDATA%\\Berichtsheft\\config.json``::

    {
      "version": 1,
      "active_profile": "Standard",
      "profiles": { "Standard": { ...Profile... } }
    }

Alles, was früher im Script fest eingebaut war (Ignorierliste, Tippfehler,
Schriftgrößen, Maximallänge), ist hier pro Profil einstellbar.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .summarizer import Phrases, Replacement, SummarizerSettings

APP_NAME = "Berichtsheft"
CONFIG_VERSION = 1


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def default_config_path() -> Path:
    return app_data_dir() / "config.json"


# --------------------------------------------------------------------------- #
# Standardwerte (früher hart codiert)
# --------------------------------------------------------------------------- #

DEFAULT_IGNORE_LINES: list[str] = [
    # Methoden aus dem GFN-Klassenbuch (nur relevant, wenn die Spalten nicht erkannt werden)
    "Lehr-/Lerngespräch",
    "Frontalunterricht/Vortrag",
    "Präsentation/Demonstration",
    "betreute Einzelarbeit",
    "Gruppenarbeit",
    "Aufgaben-/Übungsbesprechung",
    "Lernerfolgskontrolle/Prüfung",
    "Rollenspiel",
    "Fallstudie",
    "n/a",
    # Tabellenkopf
    "Stunde",
    "Lehrinhalte",
    "Lernformat/-methodik",
    "Dozent",
    "Unterschrift",
]

DEFAULT_LOW_PRIORITY: list[str] = [
    "Agenda",
    "Wiederholung",
    "Ausblick",
    "Kurzvorstellung",
    "Frage- und Antwortrunde",
    "Einweisung in die Abläufe",
]


def default_replacements() -> list[Replacement]:
    plain = [
        # aus TYPO_FIXES (v9)
        ("Verwnden", "Verwenden"),
        ("verwnden", "verwenden"),
        ("Vertiefenmder", "Vertiefen der"),
        ("Maschienen", "Maschinen"),
        ("Bespechen", "Besprechen"),
        ("Poqwershellscripts", "PowerShell-Skripts"),
        ("Poqwershellscript", "PowerShell-Skript"),
        ("Powershellscripts", "PowerShell-Skripts"),
        ("Powershell", "PowerShell"),
        ("PowerShell-Scripts", "PowerShell-Skripts"),
        ("PowerShell-Script", "PowerShell-Skript"),
        ("Gui", "GUI"),
        ("Estellen", "Erstellen"),
        ("dateifreigaben", "Dateifreigaben"),
        # aus clean_line (v9)
        ("Horizontale, - Vertikale", "horizontale und vertikale"),
        ("Horizontale,- Vertikale", "horizontale und vertikale"),
        ("Sichern eine", "Sichern einer"),
        ("Zuständigkeiten bei SaaS, PaaS, IaaS", "Zuständigkeiten bei SaaS, PaaS und IaaS"),
        # neu
        ("Grundllagen", "Grundlagen"),
        ("Ruten", "Routen"),
        ("Anlayse", "Analyse"),
        ("GANT", "Gantt"),
        ("zB", "z. B."),
        ("ggf", "ggf."),
        ("hilfe", "Hilfe"),
    ]
    regex = [
        (r"wiederh[Ee]rstellen", "wiederherstellen"),
        (r"Wiederh[Ee]rstellen", "Wiederherstellen"),
        (r"\bggf\.\.", "ggf."),
    ]
    out = [Replacement(w, r) for w, r in plain]
    out += [Replacement(w, r, regex=True) for w, r in regex]
    return out


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class Formatting:
    content_font_size: float = 8.0     # 0 = Schriftgröße der Vorlage übernehmen
    content_bold: bool = True
    lernfeld_font_size: float = 12.0
    lernfeld_bold: bool = True
    max_chars: int = 430               # 0 = ohne Begrenzung


@dataclass
class Profile:
    # Persönliche Daten – bewusst nur Name und Jahrgang; Dozent, Woche und Datum kommen aus den PDFs
    name: str = ""
    jahrgang: str = ""                 # landet im Feld "Ausbildungsjahr" bzw. {{JAHRGANG}}
    # Dateien
    template_path: str = ""
    output_dir: str = ""
    filename_pattern: str = "Berichtsheft Woche {NR} ({VOM}-{BIS}).docx"
    # Nachweis-Nr.
    nachweis_mode: str = "increment"   # increment | from_start | template
    last_nachweis_nr: int = 0
    last_week_monday: str = ""         # ISO-Datum der zuletzt erstellten Woche
    ausbildungsbeginn: str = ""        # ISO-Datum, Nachweis-Nr. 1 = diese Woche
    # Vorlage befüllen
    write_header_fields: bool = True   # Nr./vom/bis/Name/Dozent in die Kopfzellen schreiben
    write_lernfeld: bool = True
    write_hours: bool = False
    hours_per_day: str = ""            # leer = aus Vorlage lassen
    update_signature_date: bool = True
    # Texte
    formatting: Formatting = field(default_factory=Formatting)
    ignore_lines: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_LINES))
    low_priority: list[str] = field(default_factory=lambda: list(DEFAULT_LOW_PRIORITY))
    replacements: list[dict[str, Any]] = field(
        default_factory=lambda: [dataclasses.asdict(r) for r in default_replacements()]
    )
    phrases: dict[str, str] = field(default_factory=lambda: dataclasses.asdict(Phrases()))

    # -- abgeleitete Werte ------------------------------------------------ #
    def summarizer_settings(self) -> SummarizerSettings:
        reps = []
        for r in self.replacements:
            try:
                reps.append(Replacement(str(r.get("wrong", "")), str(r.get("right", "")),
                                        bool(r.get("regex", False)), bool(r.get("ignore_case", False))))
            except AttributeError:
                continue
        known = {f.name for f in dataclasses.fields(Phrases)}
        phrases = Phrases(**{k: v for k, v in self.phrases.items() if k in known})
        return SummarizerSettings(
            max_chars=self.formatting.max_chars,
            replacements=reps,
            ignore_lines=list(self.ignore_lines),
            low_priority=list(self.low_priority),
            phrases=phrases,
        )

    @property
    def is_complete(self) -> bool:
        return bool(self.name.strip()) and bool(self.template_path) and Path(self.template_path).exists()

    def placeholder_values(self) -> dict[str, str]:
        return {
            "NAME": self.name,
            "JAHRGANG": self.jahrgang,
        }

    def suggest_nachweis_nr(self, monday: dt.date | None) -> int | None:
        """Vorschlag für die Nachweis-Nr. der Woche ab ``monday``."""
        if monday is None:
            return None
        if self.nachweis_mode == "from_start" and self.ausbildungsbeginn:
            try:
                start = dt.date.fromisoformat(self.ausbildungsbeginn)
            except ValueError:
                return None
            start_monday = start - dt.timedelta(days=start.weekday())
            return (monday - start_monday).days // 7 + 1
        if self.nachweis_mode == "increment" and self.last_nachweis_nr:
            if self.last_week_monday:
                try:
                    last = dt.date.fromisoformat(self.last_week_monday)
                    if monday == last:
                        return self.last_nachweis_nr
                    weeks = (monday - last).days // 7
                    if weeks > 0:
                        return self.last_nachweis_nr + weeks
                except ValueError:
                    pass
            return self.last_nachweis_nr + 1
        return None


@dataclass
class AppConfig:
    active_profile: str = "Standard"
    profiles: dict[str, Profile] = field(default_factory=lambda: {"Standard": Profile()})
    version: int = CONFIG_VERSION

    @property
    def profile(self) -> Profile:
        if self.active_profile not in self.profiles:
            self.profiles[self.active_profile] = Profile()
        return self.profiles[self.active_profile]


# --------------------------------------------------------------------------- #
# Laden / Speichern
# --------------------------------------------------------------------------- #

def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Dataclass robust aus dict bauen: unbekannte Felder ignorieren, fehlende = Standard."""
    kwargs: dict[str, Any] = {}
    fields = {f.name: f for f in dataclasses.fields(cls)}
    for name, f in fields.items():
        if name not in data:
            continue
        value = data[name]
        if name == "formatting" and isinstance(value, dict):
            value = _from_dict(Formatting, value)
        kwargs[name] = value
    return cls(**kwargs)


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    profiles_raw = data.get("profiles") or {}
    profiles = {
        str(name): _from_dict(Profile, p) for name, p in profiles_raw.items() if isinstance(p, dict)
    } or {"Standard": Profile()}
    active = str(data.get("active_profile") or next(iter(profiles)))
    return AppConfig(active_profile=active, profiles=profiles, version=int(data.get("version", CONFIG_VERSION)))


def config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "active_profile": cfg.active_profile,
        "profiles": {name: dataclasses.asdict(p) for name, p in cfg.profiles.items()},
    }


def load_config(path: Path | None = None) -> AppConfig:
    path = path or default_config_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # kaputte Datei sichern und mit Standardwerten weitermachen
        backup = path.with_suffix(".defekt.json")
        try:
            shutil.copyfile(path, backup)
        except OSError:
            pass
        raise ConfigError(f"Einstellungen konnten nicht gelesen werden (Sicherung: {backup.name})") from exc
    return config_from_dict(data if isinstance(data, dict) else {})


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config_to_dict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class ConfigError(Exception):
    pass


def import_template(src: Path, data_dir: Path | None = None) -> Path:
    """Vorlage in den App-Datenordner kopieren und den neuen Pfad zurückgeben."""
    data_dir = data_dir or app_data_dir()
    target_dir = data_dir / "vorlagen"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src.name
    if src.resolve() != target.resolve():
        shutil.copyfile(src, target)
    return target
