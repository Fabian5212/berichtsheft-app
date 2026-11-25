"""Vorher/Nachher-Vergleich: altes v9-Script gegen neue Kernlogik.

    python tools/compare_legacy.py <pfad/zu/berichtsheft_auto.py> <pdf-ordner> [weitere Ordner…]

Das alte Script wird nicht ins Repo übernommen (enthält Namen); es wird nur
von seinem Speicherort importiert. Ausgabe pro Tag: alter Text, neuer Text und
einfache Qualitätsmerkmale (Dozent im Text, Methoden im Text, Länge, Lernfeld).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from berichtsheft.core.config import DEFAULT_IGNORE_LINES, Profile  # noqa: E402
from berichtsheft.core.week import plan_from_paths  # noqa: E402

METHODS = [m for m in DEFAULT_IGNORE_LINES if "/" in m or " " in m] + ["Projektarbeit", "Projektaufgabe", "Rollenspiel"]


def load_legacy(path: Path):
    spec = importlib.util.spec_from_file_location("legacy_v9", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["legacy_v9"] = mod  # nötig für @dataclass
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def flags(text: str, trainers: list[str]) -> str:
    out = []
    surnames = {t.split()[-1] for t in trainers if t}
    if any(s in text for s in surnames):
        out.append("DOZENT")
    if any(m in text for m in METHODS):
        out.append("METHODE")
    if "//" in text:
        out.append("FUSSZEILE")
    if not text.endswith("."):
        out.append("SATZ-ENDE")
    return ",".join(out) or "ok"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    legacy = load_legacy(Path(sys.argv[1]))
    settings = Profile().summarizer_settings()
    totals = {"alt": 0, "neu": 0, "tage": 0}
    for folder in map(Path, sys.argv[2:]):
        pdfs = sorted(folder.glob("*.pdf"))
        plan = plan_from_paths(pdfs, settings)
        old_by_date = {}
        for pdf in pdfs:
            try:
                d = legacy.parse_day_pdf(pdf)
                old_by_date[d.date] = d
            except Exception as exc:  # noqa: BLE001
                print(f"v9-Fehler {pdf.name}: {exc}")
        print(f"\n######## {folder}")
        for code, day in plan.days.items():
            old = old_by_date.get(day.date)
            old_text = old.summary if old else "(v9: nicht verarbeitet)"
            old_lf = (old.lernfeld if old else "") or "—"
            f_old, f_new = flags(old_text, day.trainers), flags(day.text, day.trainers)
            totals["tage"] += 1
            totals["alt"] += f_old == "ok"
            totals["neu"] += f_new == "ok"
            print(f"\n{code} {day.date:%d.%m.%Y}")
            print(f"  v9  [{len(old_text):3}] LF={old_lf:8} {f_old}\n      {old_text}")
            print(f"  neu [{len(day.text):3}] LF={day.lernfeld or '—':8} {f_new}\n      {day.text}")
    print(f"\nTage ohne Auffälligkeiten: v9 {totals['alt']}/{totals['tage']}, neu {totals['neu']}/{totals['tage']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
