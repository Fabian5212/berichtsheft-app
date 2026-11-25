"""Startet das CLI ohne Installation: ``py -3.12 cli.py --template ... --pdfdir ...``"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from berichtsheft.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
