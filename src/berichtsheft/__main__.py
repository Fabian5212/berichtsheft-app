"""Startpunkt der Desktop-App (auch für PyInstaller)."""

from __future__ import annotations

import sys


def _run_cli(argv: list[str]) -> int:
    """``Berichtsheft-Assistent.exe --cli --template … --pdfdir …``

    Die EXE hat kein Konsolenfenster; Ausgaben gehen daher zusätzlich nach
    ``%APPDATA%\Berichtsheft\cli-ausgabe.txt``.
    """
    from berichtsheft import cli
    from berichtsheft.core.config import app_data_dir

    if sys.stdout is None or sys.stderr is None:
        out_file = app_data_dir() / "cli-ausgabe.txt"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        stream = open(out_file, "w", encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stderr = stream
    return cli.main(argv)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(_run_cli(sys.argv[2:]))

    from berichtsheft.core.logging_setup import get_logger, setup_logging

    setup_logging()
    log = get_logger()
    try:
        from berichtsheft.gui.app import run

        run()
    except Exception:  # noqa: BLE001 – letzter Schutz: Traceback ins Log, freundliche Meldung
        log.exception("Absturz beim Start")
        try:
            from tkinter import messagebox

            from berichtsheft.core.logging_setup import log_file_path

            messagebox.showerror("Berichtsheft-Assistent",
                                 f"Die App konnte nicht gestartet werden.\nDetails: {log_file_path()}")
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
