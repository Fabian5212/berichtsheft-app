"""Zeigt die erzeugten Tagestexte für einen PDF-Ordner (Entwickler-Werkzeug)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from berichtsheft.core.config import Profile  # noqa: E402
from berichtsheft.core.week import plan_from_paths  # noqa: E402

settings = Profile().summarizer_settings()
for folder in sys.argv[1:]:
    plan = plan_from_paths(Path(folder).glob("*.pdf"), settings)
    print(f"===== {folder}  Woche ab {plan.monday}")
    for i in plan.issues:
        print("  ", i)
    for code, day in plan.days.items():
        print(f"{code} {day.date:%d.%m.} {day.lernfeld} {day.trainers} ({len(day.text)} Zeichen)")
        print("   ", day.text)
        for i in day.issues:
            print("    ->", i)
