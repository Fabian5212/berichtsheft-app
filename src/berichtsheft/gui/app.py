"""Hauptfenster: PDFs reinziehen -> Vorschau prüfen/bearbeiten -> Berichtsheft erstellen."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..core.config import AppConfig, ConfigError, load_config, save_config
from ..core.docx_writer import TemplateInfo, analyze_template
from ..core.logging_setup import get_logger, log_file_path
from ..core.models import Severity, WeekPlan
from ..core.service import HeaderValues, create_report, output_path, prepare_week, remember_week, suggest_header
from .settings import SettingsWindow
from .setup_wizard import SetupWizard
from .widgets import ERR_COLOR, MUTED, OK_COLOR, WARN_COLOR, DayCard, LogView, parse_user_date

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except Exception:  # noqa: BLE001 – Drag & Drop ist optional
    _DND_AVAILABLE = False

log = get_logger("gui")

APP_TITLE = "Berichtsheft-Assistent"


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / rel


class _Base(ctk.CTk):
    pass


if _DND_AVAILABLE:
    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:  # noqa: BLE001
                self.dnd_ok = False


class MainWindow(_Base):
    def __init__(self, config_path: Path | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x780")
        self.minsize(980, 640)
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self.config_path = config_path
        self.config_obj = self._load_config()
        self.pdfs: list[Path] = []
        self.plan: WeekPlan | None = None
        self.template_info: TemplateInfo | None = None
        self.cards: dict[str, DayCard] = {}
        self.last_output: Path | None = None

        self._build()
        log.info("Start: Drag & Drop %s, Konfiguration %s", "aktiv" if self._dnd_ok() else "inaktiv",
                 self.config_path or "Standard")
        self._refresh_profile()
        self.report_callback_exception = self._on_tk_error  # type: ignore[assignment]
        if not self.config_obj.profile.is_complete:
            self.after(300, self.open_wizard)

    # ------------------------------------------------------------------ #
    # Aufbau
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Kopfzeile
        top = ctk.CTkFrame(self, corner_radius=0)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text=APP_TITLE, font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=10)
        self.profile_label = ctk.CTkLabel(top, text="", text_color=MUTED)
        self.profile_label.grid(row=0, column=1, sticky="w")
        self.profile_menu = ctk.CTkOptionMenu(top, values=["Standard"], command=self._switch_profile, width=150)
        self.profile_menu.grid(row=0, column=2, padx=6)
        ctk.CTkButton(top, text="Einstellungen", width=120, command=self.open_settings).grid(row=0, column=3, padx=(0, 16))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        # Drop-Zone
        self.drop = ctk.CTkFrame(body, height=86, border_width=2, border_color=("gray70", "gray35"))
        self.drop.grid(row=0, column=0, sticky="ew")
        self.drop.grid_columnconfigure(0, weight=1)
        dnd_text = "Klassenbuch-PDFs hierher ziehen" if self._dnd_ok() else "Klassenbuch-PDFs auswählen"
        self.drop_label = ctk.CTkLabel(self.drop, text=f"⬇  {dnd_text}", font=ctk.CTkFont(size=15))
        self.drop_label.grid(row=0, column=0, pady=(14, 0))
        self.drop_sub = ctk.CTkLabel(self.drop, text="eine PDF pro Tag · Mo–Fr derselben Woche", text_color=MUTED)
        self.drop_sub.grid(row=1, column=0, pady=(0, 12))
        btns = ctk.CTkFrame(self.drop, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, padx=14)
        ctk.CTkButton(btns, text="PDFs auswählen …", command=self.choose_pdfs, width=150).grid(row=0, column=0, pady=3)
        ctk.CTkButton(btns, text="Liste leeren", command=self.clear_pdfs, width=150, fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90")).grid(row=1, column=0, pady=3)
        if self._dnd_ok():
            for w in (self.drop, self.drop_label, self.drop_sub):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        # Tage
        self.days_frame = ctk.CTkScrollableFrame(body, label_text="Erkannte Tage")
        self.days_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.days_frame.grid_columnconfigure(0, weight=1)
        self._empty_hint()

        # Rechte Spalte
        side = ctk.CTkFrame(self)
        side.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(10, 0))
        side.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(side, text="Berichtsheft", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        form = ctk.CTkFrame(side, fg_color="transparent")
        form.grid(row=1, column=0, sticky="ew", padx=14)
        self.nr_var, self.vom_var, self.bis_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for i, (label, var) in enumerate([("Nachweis-Nr.", self.nr_var), ("Woche vom", self.vom_var), ("bis", self.bis_var)]):
            ctk.CTkLabel(form, text=label, width=90, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            ctk.CTkEntry(form, textvariable=var, width=120).grid(row=i, column=1, sticky="w", pady=3)
            var.trace_add("write", lambda *_: self._update_filename())
        self.header_note = ctk.CTkLabel(side, text="", text_color=MUTED, wraplength=250, justify="left", anchor="w")
        self.header_note.grid(row=2, column=0, sticky="w", padx=14)

        ctk.CTkLabel(side, text="Dateiname", anchor="w", text_color=MUTED).grid(row=3, column=0, sticky="w", padx=14, pady=(10, 0))
        self.filename_label = ctk.CTkLabel(side, text="–", anchor="w", wraplength=250, justify="left",
                                           font=ctk.CTkFont(weight="bold"))
        self.filename_label.grid(row=4, column=0, sticky="w", padx=14)
        ctk.CTkLabel(side, text="Ordner", anchor="w", text_color=MUTED).grid(row=5, column=0, sticky="w", padx=14, pady=(8, 0))
        out_row = ctk.CTkFrame(side, fg_color="transparent")
        out_row.grid(row=6, column=0, sticky="ew", padx=14)
        out_row.grid_columnconfigure(0, weight=1)
        self.outdir_label = ctk.CTkLabel(out_row, text="–", anchor="w", wraplength=210, justify="left")
        self.outdir_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(out_row, text="…", width=32, command=self.choose_outdir).grid(row=0, column=1)

        self.overwrite_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(side, text="Vorhandene Inhalte überschreiben", variable=self.overwrite_var).grid(row=7, column=0, sticky="w", padx=14, pady=(14, 4))
        self.create_btn = ctk.CTkButton(side, text="Berichtsheft erstellen", height=40,
                                        font=ctk.CTkFont(size=14, weight="bold"), command=self.create, state="disabled")
        self.create_btn.grid(row=8, column=0, sticky="ew", padx=14, pady=(6, 6))
        after = ctk.CTkFrame(side, fg_color="transparent")
        after.grid(row=9, column=0, sticky="ew", padx=14)
        after.grid_columnconfigure((0, 1), weight=1)
        self.open_file_btn = ctk.CTkButton(after, text="Datei öffnen", state="disabled", command=self.open_file)
        self.open_file_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.open_dir_btn = ctk.CTkButton(after, text="Ordner öffnen", state="disabled", command=self.open_dir)
        self.open_dir_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.template_label = ctk.CTkLabel(side, text="", text_color=MUTED, wraplength=250, justify="left", anchor="w",
                                           font=ctk.CTkFont(size=11))
        self.template_label.grid(row=10, column=0, sticky="sw", padx=14, pady=(18, 12))
        side.grid_rowconfigure(10, weight=1)

        # Log
        self.log_view = LogView(self)
        self.log_view.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        self.log_view.add("Bereit." + ("" if self._dnd_ok() else " (Drag & Drop nicht verfügbar – bitte „PDFs auswählen“ nutzen)"))

    def _dnd_ok(self) -> bool:
        return bool(getattr(self, "dnd_ok", False))

    def _empty_hint(self) -> None:
        for w in self.days_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.days_frame, text="Noch keine PDFs. Zieh die Klassenbuch-PDFs der Woche oben in das Feld.",
                     text_color=MUTED).grid(row=0, column=0, pady=40)

    # ------------------------------------------------------------------ #
    # Konfiguration / Profil
    # ------------------------------------------------------------------ #
    def _load_config(self) -> AppConfig:
        try:
            return load_config(self.config_path)
        except ConfigError as exc:
            log.exception("Konfiguration defekt")
            self.after(500, lambda: messagebox.showwarning("Einstellungen", f"{exc}\nEs werden Standardwerte verwendet."))
            return AppConfig()

    def _save_config(self) -> None:
        try:
            save_config(self.config_obj, self.config_path)
        except OSError as exc:
            log.exception("Speichern der Konfiguration fehlgeschlagen")
            self.log_view.add(f"Einstellungen konnten nicht gespeichert werden ({exc.strerror})", "fehler")

    def _refresh_profile(self) -> None:
        p = self.config_obj.profile
        self.profile_label.configure(text=f"Profil: {p.name or '—'}" + (f" · Jahrgang {p.jahrgang}" if p.jahrgang else ""))
        names = list(self.config_obj.profiles)
        self.profile_menu.configure(values=names)
        self.profile_menu.set(self.config_obj.active_profile)
        if len(names) > 1:
            self.profile_menu.grid()
        else:
            self.profile_menu.grid_remove()
        self.outdir_label.configure(text=p.output_dir or "– bitte wählen –")
        self.template_info = analyze_template(Path(p.template_path)) if p.template_path and Path(p.template_path).exists() else None
        if self.template_info:
            self.template_label.configure(text=f"Vorlage: {Path(p.template_path).name}\n{self.template_info.summary()}")
        else:
            self.template_label.configure(text="Keine Vorlage – bitte in den Einstellungen hochladen.")
        if self.pdfs:
            self._process()
        self._update_state()

    def _switch_profile(self, name: str) -> None:
        self.config_obj.active_profile = name
        self._save_config()
        self._refresh_profile()

    def open_wizard(self) -> None:
        SetupWizard(self, self.config_obj, self._wizard_done)

    def _wizard_done(self, cfg: AppConfig) -> None:
        self.config_obj = cfg
        self._save_config()
        self.log_view.add("Profil gespeichert. Jetzt die PDFs der Woche hineinziehen.", "ok")
        self._refresh_profile()

    def open_settings(self) -> None:
        SettingsWindow(self, self.config_obj, self._settings_saved)

    def _settings_saved(self, cfg: AppConfig) -> None:
        self.config_obj = cfg
        self._save_config()
        self.log_view.add("Einstellungen gespeichert.", "ok")
        self._refresh_profile()

    # ------------------------------------------------------------------ #
    # PDFs
    # ------------------------------------------------------------------ #
    def _on_drop(self, event) -> None:
        files = [Path(f) for f in self.tk.splitlist(event.data)]
        self.add_paths(files)

    def choose_pdfs(self) -> None:
        files = filedialog.askopenfilenames(title="Klassenbuch-PDFs auswählen", filetypes=[("PDF", "*.pdf")])
        self.add_paths([Path(f) for f in files])

    def add_paths(self, paths: list[Path]) -> None:
        added = 0
        for p in paths:
            if p.is_dir():
                candidates = sorted(p.glob("*.pdf"))
            else:
                candidates = [p]
            for c in candidates:
                if c.suffix.lower() != ".pdf":
                    self.log_view.add(f"Übersprungen (keine PDF): {c.name}", "warnung")
                    continue
                if c not in self.pdfs:
                    self.pdfs.append(c)
                    added += 1
        if added:
            self.log_view.add(f"{added} PDF(s) hinzugefügt.")
            self._process()

    def clear_pdfs(self) -> None:
        self.pdfs.clear()
        self.plan = None
        self.cards.clear()
        self._empty_hint()
        for v in (self.nr_var, self.vom_var, self.bis_var):
            v.set("")
        self.header_note.configure(text="")
        self._update_state()
        self.log_view.add("Liste geleert.")

    def _process(self) -> None:
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            plan = prepare_week(self.pdfs, self.config_obj.profile)
        finally:
            self.configure(cursor="")
        self.plan = plan
        for issue in plan.issues:
            self.log_view.issue(issue)
        for w in self.days_frame.winfo_children():
            w.destroy()
        self.cards.clear()
        if not plan.days:
            self._empty_hint()
            self.log_view.add("Keine verwertbaren Tage gefunden.", "fehler")
            self._update_state()
            return
        max_chars = self.config_obj.profile.formatting.max_chars
        for i, (code, day) in enumerate(plan.days.items()):
            card = DayCard(self.days_frame, day, max_chars, on_change=self._update_state)
            card.grid(row=i, column=0, sticky="ew", pady=(0, 8))
            self.cards[code] = card
        warn = sum(1 for d in plan.days.values() if not d.ok)
        self.log_view.add(f"{len(plan.days)} Tag(e) erkannt" + (f", {warn} mit Hinweisen" if warn else "") + ".",
                          "warnung" if warn else "ok")
        header = suggest_header(plan, self.template_info, self.config_obj.profile)
        self.nr_var.set(str(header.nachweis_nr) if header.nachweis_nr is not None else "")
        self.vom_var.set(f"{header.vom:%d.%m.%Y}" if header.vom else "")
        self.bis_var.set(f"{header.bis:%d.%m.%Y}" if header.bis else "")
        self.header_note.configure(text="\n".join(header.notes))
        self._update_state()

    # ------------------------------------------------------------------ #
    # Erstellen
    # ------------------------------------------------------------------ #
    def _header(self) -> tuple[HeaderValues | None, str]:
        nr_txt = self.nr_var.get().strip()
        nr = None
        if nr_txt:
            if not re.fullmatch(r"\d{1,4}", nr_txt):
                return None, "Nachweis-Nr. muss eine Zahl sein."
            nr = int(nr_txt)
        vom = parse_user_date(self.vom_var.get()) if self.vom_var.get().strip() else None
        bis = parse_user_date(self.bis_var.get()) if self.bis_var.get().strip() else None
        if self.vom_var.get().strip() and vom is None:
            return None, "„Woche vom“ bitte als TT.MM.JJJJ eingeben."
        if self.bis_var.get().strip() and bis is None:
            return None, "„bis“ bitte als TT.MM.JJJJ eingeben."
        if vom and bis and vom > bis:
            return None, "„Woche vom“ liegt nach „bis“."
        return HeaderValues(nr, vom, bis), ""

    def _update_filename(self) -> None:
        header, err = self._header()
        out = self.config_obj.profile.output_dir
        if header is None:
            self.filename_label.configure(text=err, text_color=ERR_COLOR)
        elif not self.plan:
            self.filename_label.configure(text="–", text_color=("gray10", "gray90"))
        else:
            target = output_path(self.config_obj.profile, Path(out or "."), header)
            exists = bool(out) and target.exists()
            if exists and self.last_output == target:
                self.filename_label.configure(text=target.name + "\n✓ gespeichert", text_color=OK_COLOR)
            else:
                self.filename_label.configure(text=target.name + ("\n(existiert – wird ersetzt)" if exists else ""),
                                              text_color=WARN_COLOR if exists else ("gray10", "gray90"))
        self._update_state()

    def _update_state(self) -> None:
        p = self.config_obj.profile
        ready = bool(self.plan and self.plan.days and self.template_info and self.template_info.usable and p.output_dir)
        header, _ = self._header()
        self.create_btn.configure(state="normal" if ready and header else "disabled")

    def choose_outdir(self) -> None:
        d = filedialog.askdirectory(title="Ausgabeordner wählen")
        if d:
            self.config_obj.profile.output_dir = d
            self._save_config()
            self.outdir_label.configure(text=d)
            self._update_filename()

    def create(self) -> None:
        if not self.plan:
            return
        header, err = self._header()
        if header is None:
            messagebox.showerror("Eingabe prüfen", err)
            return
        p = self.config_obj.profile
        out_dir = Path(p.output_dir)
        target = output_path(p, out_dir, header)
        if target.exists() and not messagebox.askyesno("Datei ersetzen?", f"„{target.name}“ gibt es schon. Ersetzen?"):
            return
        too_long = [c for c, card in self.cards.items() if p.formatting.max_chars and len(card.get_text()) > p.formatting.max_chars]
        if too_long and not messagebox.askyesno(
                "Text zu lang", f"Länger als {p.formatting.max_chars} Zeichen: {', '.join(too_long)}.\nTrotzdem erstellen?"):
            return
        texts = {code: card.get_text() for code, card in self.cards.items()}
        try:
            issues = create_report(Path(p.template_path), target, self.plan, header, p, self.overwrite_var.get(), texts)
        except Exception:  # noqa: BLE001
            log.exception("Erstellen fehlgeschlagen")
            messagebox.showerror("Fehler", "Das Berichtsheft konnte nicht erstellt werden.\n"
                                           f"Details stehen in der Logdatei:\n{log_file_path()}")
            return
        for issue in issues:
            self.log_view.issue(issue)
        if any(i.severity is Severity.ERROR for i in issues):
            messagebox.showerror("Fehler", "\n".join(i.message for i in issues if i.severity is Severity.ERROR))
            return
        remember_week(p, header)
        self._save_config()
        self.last_output = target
        self.open_file_btn.configure(state="normal")
        self.open_dir_btn.configure(state="normal")
        self.log_view.add(f"Fertig: {target}", "ok")
        self._update_filename()

    def open_file(self) -> None:
        if self.last_output and self.last_output.exists():
            self._open(self.last_output)

    def open_dir(self) -> None:
        if self.last_output:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(self.last_output)], check=False)
            else:
                self._open(self.last_output.parent)

    @staticmethod
    def _open(path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    # ------------------------------------------------------------------ #
    def _on_tk_error(self, exc_type, exc, tb) -> None:
        log.error("Unerwarteter Fehler", exc_info=(exc_type, exc, tb))
        self.log_view.add("Unerwarteter Fehler – Details in der Logdatei.", "fehler")
        messagebox.showerror("Unerwarteter Fehler",
                             "Da ist etwas schiefgelaufen. Die Details wurden gespeichert in:\n"
                             f"{log_file_path()}")


def run(config_path: Path | None = None) -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = MainWindow(config_path)
    app.mainloop()


__all__ = ["MainWindow", "run", "OK_COLOR"]
