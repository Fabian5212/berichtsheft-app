"""Einstellungsfenster und gemeinsame Formularteile (auch für den Assistenten)."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from ..core.config import (
    DEFAULT_IGNORE_LINES,
    DEFAULT_LOW_PRIORITY,
    AppConfig,
    Profile,
    default_replacements,
    import_template,
)
from ..core.docx_writer import analyze_template
from ..core.models import Severity
from .widgets import ERR_COLOR, MUTED, OK_COLOR, WARN_COLOR, LabeledEntry, lines_from_text, parse_user_date

PERSONAL_FIELDS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("beruf", "Ausbildungsberuf"),
    ("betrieb", "Ausbildungsbetrieb"),
    ("bildungstraeger", "Bildungsträger"),
    ("ausbilder", "Ausbilder:in"),
    ("klasse", "Klasse"),
]


class PersonalForm(ctk.CTkFrame):
    def __init__(self, master, profile: Profile):
        super().__init__(master, fg_color="transparent")
        self.entries: dict[str, LabeledEntry] = {}
        for i, (key, label) in enumerate(PERSONAL_FIELDS):
            e = LabeledEntry(self, label + (" *" if key == "name" else ""), getattr(profile, key))
            e.grid(row=i, column=0, sticky="ew", pady=3)
            self.entries[key] = e
        self.grid_columnconfigure(0, weight=1)

    def apply(self, profile: Profile) -> None:
        for key, e in self.entries.items():
            setattr(profile, key, e.get())


class TemplatePicker(ctk.CTkFrame):
    """Vorlage auswählen, in den App-Ordner kopieren und Prüfbericht anzeigen."""

    def __init__(self, master, current: str = "", on_change: Callable[[str], None] | None = None):
        super().__init__(master, fg_color="transparent")
        self.path = current
        self._on_change = on_change
        self.grid_columnconfigure(0, weight=1)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        self.path_label = ctk.CTkLabel(row, text=self._short(current) or "Noch keine Vorlage", anchor="w")
        self.path_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(row, text="Vorlage hochladen …", command=self.choose, width=160).grid(row=0, column=1, padx=(8, 0))
        self.report = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=520)
        self.report.grid(row=1, column=0, sticky="w", pady=(6, 0))
        if current:
            self._show_report(Path(current))

    @staticmethod
    def _short(path: str) -> str:
        return Path(path).name if path else ""

    def choose(self) -> None:
        file = filedialog.askopenfilename(
            title="Blanko-Vorlage auswählen", filetypes=[("Word-Dokument", "*.docx")], parent=self.winfo_toplevel()
        )
        if not file:
            return
        info = analyze_template(Path(file))
        if not info.usable:
            msg = "\n".join(i.message for i in info.issues) or "Vorlage nicht verwendbar."
            messagebox.showerror("Vorlage nicht verwendbar", msg, parent=self.winfo_toplevel())
            return
        try:
            target = import_template(Path(file))
        except OSError as exc:
            messagebox.showerror("Kopieren fehlgeschlagen", f"Die Vorlage konnte nicht kopiert werden:\n{exc.strerror}",
                                 parent=self.winfo_toplevel())
            return
        self.path = str(target)
        self.path_label.configure(text=self._short(self.path))
        self._show_report(target)
        if self._on_change:
            self._on_change(self.path)

    def _show_report(self, path: Path) -> None:
        if not path.exists():
            self.report.configure(text="⚠ Vorlage nicht mehr vorhanden – bitte neu hochladen", text_color=WARN_COLOR)
            return
        info = analyze_template(path)
        lines = [("✓ " if info.usable else "✗ ") + info.summary()]
        lines += [f"⚠ {i.message}" for i in info.issues]
        color = OK_COLOR if info.usable and not info.issues else (WARN_COLOR if info.usable else ERR_COLOR)
        self.report.configure(text="\n".join(lines), text_color=color)


class NachweisForm(ctk.CTkFrame):
    def __init__(self, master, profile: Profile):
        super().__init__(master, fg_color="transparent")
        self.mode = tk.StringVar(value=profile.nachweis_mode)
        ctk.CTkRadioButton(self, text="Letzte Nr. automatisch +1 pro Woche", variable=self.mode, value="increment").grid(row=0, column=0, sticky="w", pady=3)
        self.last = LabeledEntry(self, "   Letzte Nachweis-Nr.", str(profile.last_nachweis_nr or ""), width=80)
        self.last.grid(row=1, column=0, sticky="w")
        ctk.CTkRadioButton(self, text="Aus dem Ausbildungsbeginn berechnen", variable=self.mode, value="from_start").grid(row=2, column=0, sticky="w", pady=(10, 3))
        start = ""
        if profile.ausbildungsbeginn:
            try:
                start = dt.date.fromisoformat(profile.ausbildungsbeginn).strftime("%d.%m.%Y")
            except ValueError:
                start = ""
        self.start = LabeledEntry(self, "   Ausbildungsbeginn", start, width=110, placeholder="TT.MM.JJJJ")
        self.start.grid(row=3, column=0, sticky="w")
        ctk.CTkRadioButton(self, text="Nummer aus der Vorlage übernehmen", variable=self.mode, value="template").grid(row=4, column=0, sticky="w", pady=(10, 3))
        ctk.CTkLabel(self, text="Die Nummer lässt sich vor dem Erstellen immer noch von Hand ändern.",
                     text_color=MUTED).grid(row=5, column=0, sticky="w", pady=(8, 0))

    def apply(self, profile: Profile) -> str | None:
        """Übernehmen. Gibt eine Fehlermeldung zurück oder None."""
        profile.nachweis_mode = self.mode.get()
        last = self.last.get()
        if last:
            if not last.isdigit():
                return "Die letzte Nachweis-Nr. muss eine Zahl sein."
            if int(last) != profile.last_nachweis_nr:
                profile.last_nachweis_nr = int(last)
                profile.last_week_monday = ""
        start = self.start.get()
        if start:
            d = parse_user_date(start)
            if d is None:
                return "Ausbildungsbeginn bitte als TT.MM.JJJJ eingeben."
            profile.ausbildungsbeginn = d.isoformat()
        elif profile.nachweis_mode == "from_start":
            return "Bitte den Ausbildungsbeginn eintragen."
        return None


class OutputDirPicker(ctk.CTkFrame):
    def __init__(self, master, current: str):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Ausgabeordner", width=170, anchor="w").grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar(value=current)
        ctk.CTkEntry(self, textvariable=self.var).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(self, text="…", width=32, command=self.choose).grid(row=0, column=2, padx=(6, 0))

    def choose(self) -> None:
        d = filedialog.askdirectory(title="Ausgabeordner wählen", parent=self.winfo_toplevel())
        if d:
            self.var.set(d)

    def get(self) -> str:
        return self.var.get().strip()


# --------------------------------------------------------------------------- #
# Ersetzungstabelle
# --------------------------------------------------------------------------- #

class ReplacementTable(ctk.CTkFrame):
    def __init__(self, master, rows: list[dict]):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        for i, (t, w) in enumerate([("falsch", 220), ("richtig", 220), ("Regex", 60), ("", 30)]):
            ctk.CTkLabel(head, text=t, width=w, anchor="w", font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=2)
        self.body = ctk.CTkScrollableFrame(self, height=300)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.rows: list[tuple[tk.StringVar, tk.StringVar, tk.BooleanVar, ctk.CTkFrame]] = []
        for r in rows:
            self.add_row(str(r.get("wrong", "")), str(r.get("right", "")), bool(r.get("regex", False)))
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ctk.CTkButton(btns, text="+ Zeile", width=90, command=lambda: self.add_row("", "", False)).grid(row=0, column=0)
        ctk.CTkButton(btns, text="Standardwerte", width=120, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.reset).grid(row=0, column=1, padx=6)
        ctk.CTkLabel(btns, text="Ersetzt nur ganze Wörter. Regex nur für Fortgeschrittene.", text_color=MUTED).grid(row=0, column=2, padx=6)

    def add_row(self, wrong: str, right: str, regex: bool) -> None:
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.pack(fill="x", pady=1)
        w, r, x = tk.StringVar(value=wrong), tk.StringVar(value=right), tk.BooleanVar(value=regex)
        ctk.CTkEntry(frame, textvariable=w, width=220).grid(row=0, column=0, padx=2)
        ctk.CTkEntry(frame, textvariable=r, width=220).grid(row=0, column=1, padx=2)
        ctk.CTkCheckBox(frame, text="", variable=x, width=60).grid(row=0, column=2, padx=2)
        entry = (w, r, x, frame)
        ctk.CTkButton(frame, text="✕", width=30, fg_color="transparent", text_color=ERR_COLOR,
                      command=lambda: self.remove(entry)).grid(row=0, column=3, padx=2)
        self.rows.append(entry)

    def remove(self, entry) -> None:
        entry[3].destroy()
        self.rows.remove(entry)

    def reset(self) -> None:
        for e in list(self.rows):
            self.remove(e)
        for r in default_replacements():
            self.add_row(r.wrong, r.right, r.regex)

    def get(self) -> list[dict]:
        return [{"wrong": w.get(), "right": r.get(), "regex": x.get(), "ignore_case": False}
                for w, r, x, _ in self.rows if w.get()]


# --------------------------------------------------------------------------- #
# Einstellungsfenster
# --------------------------------------------------------------------------- #

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, config: AppConfig, on_save: Callable[[AppConfig], None]):
        super().__init__(master)
        self.title("Einstellungen")
        self.geometry("760x640")
        self.minsize(680, 560)
        self.transient(master)
        self.config_copy = copy.deepcopy(config)
        self._on_save = on_save
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        ctk.CTkLabel(top, text="Profil:").grid(row=0, column=0)
        self.profile_var = tk.StringVar(value=self.config_copy.active_profile)
        self.profile_menu = ctk.CTkOptionMenu(top, variable=self.profile_var, values=list(self.config_copy.profiles),
                                              command=self._switch_profile)
        self.profile_menu.grid(row=0, column=1, padx=6)
        ctk.CTkButton(top, text="Neues Profil", width=110, command=self._new_profile).grid(row=0, column=2, padx=3)
        ctk.CTkButton(top, text="Löschen", width=80, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self._delete_profile).grid(row=0, column=3, padx=3)

        self.tabs_holder = ctk.CTkFrame(self, fg_color="transparent")
        self.tabs_holder.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.tabs_holder.grid_columnconfigure(0, weight=1)
        self.tabs_holder.grid_rowconfigure(0, weight=1)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))
        ctk.CTkButton(bottom, text="Abbrechen", fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.destroy).grid(row=0, column=0, padx=6)
        ctk.CTkButton(bottom, text="Speichern", command=self._save).grid(row=0, column=1)

        self._build_tabs()
        self.after(100, self.grab_set)

    # -- Aufbau ------------------------------------------------------------ #
    def _build_tabs(self) -> None:
        for child in self.tabs_holder.winfo_children():
            child.destroy()
        p = self.config_copy.profile
        tabs = ctk.CTkTabview(self.tabs_holder)
        tabs.grid(row=0, column=0, sticky="nsew")
        for name in ("Profil", "Nachweis-Nr.", "Formatierung", "Zeilen ignorieren", "Ersetzungen"):
            tabs.add(name)

        t = tabs.tab("Profil")
        t.grid_columnconfigure(0, weight=1)
        self.personal = PersonalForm(t, p)
        self.personal.grid(row=0, column=0, sticky="ew", pady=(4, 10))
        ctk.CTkLabel(t, text="Blanko-Vorlage", font=ctk.CTkFont(weight="bold"), anchor="w").grid(row=1, column=0, sticky="w")
        self.template = TemplatePicker(t, p.template_path)
        self.template.grid(row=2, column=0, sticky="ew", pady=(2, 10))
        self.outdir = OutputDirPicker(t, p.output_dir)
        self.outdir.grid(row=3, column=0, sticky="ew", pady=3)
        self.pattern = LabeledEntry(t, "Dateiname", p.filename_pattern)
        self.pattern.grid(row=4, column=0, sticky="ew", pady=3)
        ctk.CTkLabel(t, text="Platzhalter im Dateinamen: {NR} {VOM} {BIS} {JAHR}", text_color=MUTED).grid(row=5, column=0, sticky="w")

        t = tabs.tab("Nachweis-Nr.")
        self.nachweis = NachweisForm(t, p)
        self.nachweis.grid(row=0, column=0, sticky="w", pady=6)

        t = tabs.tab("Formatierung")
        f = p.formatting
        self.content_size = LabeledEntry(t, "Schriftgröße Tagestext", self._num(f.content_font_size), width=70)
        self.content_size.grid(row=0, column=0, sticky="w", pady=3)
        self.content_bold = tk.BooleanVar(value=f.content_bold)
        ctk.CTkCheckBox(t, text="Tagestext fett", variable=self.content_bold).grid(row=1, column=0, sticky="w", pady=3)
        self.lf_size = LabeledEntry(t, "Schriftgröße Lernfeld", self._num(f.lernfeld_font_size), width=70)
        self.lf_size.grid(row=2, column=0, sticky="w", pady=3)
        self.lf_bold = tk.BooleanVar(value=f.lernfeld_bold)
        ctk.CTkCheckBox(t, text="Lernfeld fett", variable=self.lf_bold).grid(row=3, column=0, sticky="w", pady=3)
        self.max_chars = LabeledEntry(t, "Max. Zeichen pro Tag", str(f.max_chars), width=70)
        self.max_chars.grid(row=4, column=0, sticky="w", pady=3)
        ctk.CTkLabel(t, text="Schriftgröße 0 = wie in der Vorlage · Max. Zeichen 0 = ohne Grenze",
                     text_color=MUTED).grid(row=5, column=0, sticky="w", pady=(0, 10))
        self.write_header = tk.BooleanVar(value=p.write_header_fields)
        ctk.CTkCheckBox(t, text="Nachweis-Nr., Zeitraum, Name und Dozent in die Kopfzeilen der Vorlage schreiben",
                        variable=self.write_header).grid(row=6, column=0, sticky="w", pady=3)
        self.write_lf = tk.BooleanVar(value=p.write_lernfeld)
        ctk.CTkCheckBox(t, text="Lernfeld aus dem Klassenbuch eintragen", variable=self.write_lf).grid(row=7, column=0, sticky="w", pady=3)
        self.sig_date = tk.BooleanVar(value=p.update_signature_date)
        ctk.CTkCheckBox(t, text="Datum bei der Unterschrift auf den letzten Unterrichtstag setzen",
                        variable=self.sig_date).grid(row=8, column=0, sticky="w", pady=3)
        self.write_hours = tk.BooleanVar(value=p.write_hours)
        ctk.CTkCheckBox(t, text="Spalte „Std.“ überschreiben mit:", variable=self.write_hours).grid(row=9, column=0, sticky="w", pady=3)
        self.hours = ctk.CTkEntry(t, width=60)
        self.hours.insert(0, p.hours_per_day)
        self.hours.grid(row=9, column=1, sticky="w")

        t = tabs.tab("Zeilen ignorieren")
        t.grid_columnconfigure((0, 1), weight=1)
        t.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(t, text="Zeilen ignorieren (eine pro Zeile)", anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(t, text="Beim Kürzen zuerst weglassen (Stichwörter)", anchor="w").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.ignore = ctk.CTkTextbox(t)
        self.ignore.insert("1.0", "\n".join(p.ignore_lines))
        self.ignore.grid(row=1, column=0, sticky="nsew")
        self.low = ctk.CTkTextbox(t)
        self.low.insert("1.0", "\n".join(p.low_priority))
        self.low.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        btns = ctk.CTkFrame(t, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ctk.CTkButton(btns, text="Standardwerte", width=120, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self._reset_lists).grid(row=0, column=0)
        ctk.CTkLabel(btns, text="Der Dozent wird automatisch herausgefiltert.", text_color=MUTED).grid(row=0, column=1, padx=8)

        t = tabs.tab("Ersetzungen")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(0, weight=1)
        self.replacements = ReplacementTable(t, p.replacements)
        self.replacements.grid(row=0, column=0, sticky="nsew")

    @staticmethod
    def _num(v: float) -> str:
        return str(int(v)) if float(v).is_integer() else str(v)

    def _reset_lists(self) -> None:
        self.ignore.delete("1.0", "end")
        self.ignore.insert("1.0", "\n".join(DEFAULT_IGNORE_LINES))
        self.low.delete("1.0", "end")
        self.low.insert("1.0", "\n".join(DEFAULT_LOW_PRIORITY))

    # -- Profile ------------------------------------------------------------ #
    def _collect(self) -> str | None:
        p = self.config_copy.profile
        self.personal.apply(p)
        p.template_path = self.template.path
        p.output_dir = self.outdir.get()
        p.filename_pattern = self.pattern.get() or Profile().filename_pattern
        err = self.nachweis.apply(p)
        if err:
            return err
        try:
            p.formatting.content_font_size = float(self.content_size.get().replace(",", ".") or 0)
            p.formatting.lernfeld_font_size = float(self.lf_size.get().replace(",", ".") or 0)
            p.formatting.max_chars = int(self.max_chars.get() or 0)
        except ValueError:
            return "Schriftgrößen und Zeichenzahl müssen Zahlen sein."
        p.formatting.content_bold = self.content_bold.get()
        p.formatting.lernfeld_bold = self.lf_bold.get()
        p.write_header_fields = self.write_header.get()
        p.write_lernfeld = self.write_lf.get()
        p.update_signature_date = self.sig_date.get()
        p.write_hours = self.write_hours.get()
        p.hours_per_day = self.hours.get().strip()
        p.ignore_lines = lines_from_text(self.ignore.get("1.0", "end"))
        p.low_priority = lines_from_text(self.low.get("1.0", "end"))
        p.replacements = self.replacements.get()
        return None

    def _switch_profile(self, name: str) -> None:
        err = self._collect()
        if err:
            messagebox.showerror("Eingabe prüfen", err, parent=self)
            self.profile_var.set(self.config_copy.active_profile)
            return
        self.config_copy.active_profile = name
        self._build_tabs()

    def _new_profile(self) -> None:
        dialog = ctk.CTkInputDialog(text="Name des neuen Profils:", title="Neues Profil")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        if name in self.config_copy.profiles:
            messagebox.showerror("Profil existiert", f"„{name}“ gibt es schon.", parent=self)
            return
        err = self._collect()
        if err:
            messagebox.showerror("Eingabe prüfen", err, parent=self)
            return
        base = self.config_copy.profile
        new = Profile(formatting=dataclasses.replace(base.formatting), ignore_lines=list(base.ignore_lines),
                      low_priority=list(base.low_priority), replacements=copy.deepcopy(base.replacements))
        self.config_copy.profiles[name] = new
        self.config_copy.active_profile = name
        self.profile_menu.configure(values=list(self.config_copy.profiles))
        self.profile_var.set(name)
        self._build_tabs()

    def _delete_profile(self) -> None:
        if len(self.config_copy.profiles) <= 1:
            messagebox.showinfo("Nicht möglich", "Das letzte Profil kann nicht gelöscht werden.", parent=self)
            return
        name = self.config_copy.active_profile
        if not messagebox.askyesno("Profil löschen", f"Profil „{name}“ wirklich löschen?", parent=self):
            return
        del self.config_copy.profiles[name]
        self.config_copy.active_profile = next(iter(self.config_copy.profiles))
        self.profile_menu.configure(values=list(self.config_copy.profiles))
        self.profile_var.set(self.config_copy.active_profile)
        self._build_tabs()

    def _save(self) -> None:
        err = self._collect()
        if err:
            messagebox.showerror("Eingabe prüfen", err, parent=self)
            return
        if not self.config_copy.profile.name.strip():
            messagebox.showerror("Eingabe prüfen", "Bitte einen Namen eintragen.", parent=self)
            return
        self._on_save(self.config_copy)
        self.destroy()


__all__ = ["SettingsWindow", "PersonalForm", "TemplatePicker", "NachweisForm", "OutputDirPicker", "Severity"]
