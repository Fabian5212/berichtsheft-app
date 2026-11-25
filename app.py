"""Startet die Desktop-App ohne Installation: ``py -3.12 app.py``"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from berichtsheft.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
