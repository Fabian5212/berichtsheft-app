"""Automatischer GUI-Rauchtest mit Screenshots (Entwickler-Werkzeug).

    python tools/gui_smoke.py <ausgabeordner> [pdf-ordner] [vorlage.docx]

Ohne PDF-Ordner/Vorlage werden die anonymisierten Fixtures verwendet.
Die App läuft mit einer temporären Konfiguration, die echte bleibt unberührt.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

from PIL import Image  # noqa: E402

import fixtures  # noqa: E402
from berichtsheft.core.config import AppConfig, Profile, save_config  # noqa: E402


def capture_window(widget) -> "Image.Image | None":
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    hdc_win = user32.GetWindowDC(hwnd)
    hdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
    gdi32.SelectObject(hdc, bmp)
    user32.PrintWindow(hwnd, hdc, 2)  # PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(hdc, bmp, 0, height, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(hwnd, hdc_win)
    return Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old_file in (out / "ausgabe").glob("*.docx"):  # sonst fragt die App "Datei ersetzen?"
        old_file.unlink()
    tmp = Path(tempfile.mkdtemp())
    pdf_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else tmp / "pdf"
    template = Path(sys.argv[3]) if len(sys.argv) > 3 else tmp / "Vorlage.docx"
    if len(sys.argv) <= 2:
        # Ordner mit zwei Wochen in Unterordnern (testet Ordner-Drop + Wochenauswahl)
        import datetime as dt
        fixtures.make_week(pdf_dir / "KW25", dt.date(2026, 6, 15))
        fixtures.make_week(pdf_dir / "KW26", dt.date(2026, 6, 22), days=3)
    if len(sys.argv) <= 3:
        fixtures.make_template(template)

    cfg_path = tmp / "config.json"
    cfg = AppConfig(profiles={"Standard": Profile(name="Max Mustermann", jahrgang="2025",
                                                  template_path=str(template), output_dir=str(out / "ausgabe"),
                                                  last_nachweis_nr=6, last_week_monday="2026-06-08")})
    save_config(cfg, cfg_path)

    import customtkinter as ctk

    from berichtsheft.gui.app import MainWindow

    ctk.set_appearance_mode(sys.argv[4] if len(sys.argv) > 4 else "light")
    app = MainWindow(cfg_path)
    app.outdir_label.configure(text="Dokumente/Berichtshefte")  # neutraler Pfad für Screenshots
    results: list[str] = []

    def shot(name: str, widget=None) -> None:
        """Nur das App-Fenster aufnehmen (PrintWindow), nicht den Bildschirm."""
        w = widget or app
        w.update()
        img = capture_window(w)
        if img is not None:
            img.save(out / f"{name}.png")
            results.append(name)

    def step1() -> None:
        shot("01_leer")
        app.add_paths([pdf_dir])  # ganzer Ordner, wie beim Hineinziehen
        app.after(600, step2)

    def step2() -> None:
        shot("02_vorschau")
        app.create()
        app.after(600, step3)

    def step3() -> None:
        shot("03_erstellt")
        if len(app.week_choices) > 1:  # Woche umschalten testen
            other = [k for k, v in app.week_choices.items() if v != app.plan.monday][0]
            app._choose_week(other)
            results.append(f"Woche gewechselt -> {app.plan.monday} ({len(app.plan.days)} Tage)")
        app.open_settings()
        app.after(900, step4)

    def step4() -> None:
        win = [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        if win:
            if hasattr(win[-1], "outdir"):
                win[-1].outdir.var.set("Dokumente/Berichtshefte")  # neutraler Pfad, wird nicht gespeichert
            shot("04_einstellungen", win[-1])
            win[-1].destroy()
        app.open_wizard()
        app.after(900, step5)

    def step5() -> None:
        win = [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        if win:
            shot("05_assistent", win[-1])
            win[-1].destroy()
        app.after(200, app.destroy)

    app.after(800, step1)
    app.mainloop()
    created = list((out / "ausgabe").glob("*.docx"))
    print("Screenshots:", results)
    print("Erstellt:", [c.name for c in created])
    return 0 if created else 1


if __name__ == "__main__":
    sys.exit(main())
