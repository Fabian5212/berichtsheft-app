"""Ersteinrichtung: persönliche Daten -> Vorlage hochladen -> Nachweis-Nr./Ausgabeordner."""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from ..core.config import AppConfig
from .settings import NachweisForm, OutputDirPicker, PersonalForm, TemplatePicker
from .widgets import MUTED

STEPS = ("Persönliche Daten", "Blanko-Vorlage", "Nachweis-Nr. & Ablage")


class SetupWizard(ctk.CTkToplevel):
    def __init__(self, master, config: AppConfig, on_finish: Callable[[AppConfig], None]):
        super().__init__(master)
        self.title("Ersteinrichtung")
        self.geometry("680x540")
        self.minsize(620, 500)
        self.transient(master)
        self.config_obj = config
        self.profile = config.profile
        self._on_finish = on_finish
        self.step = 0
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="Willkommen beim Berichtsheft-Assistenten",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 0))
        self.step_label = ctk.CTkLabel(self, text="", text_color=MUTED)
        self.step_label.grid(row=1, column=0, sticky="w", padx=20)

        self.pages: list[ctk.CTkFrame] = []
        # Seite 1
        p1 = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(p1, text="Diese Angaben werden in deine Vorlage eingesetzt (Platzhalter wie {{NAME}}).",
                     anchor="w", wraplength=600, justify="left").pack(fill="x", pady=(0, 10))
        self.personal = PersonalForm(p1, self.profile)
        self.personal.pack(fill="x")
        self.pages.append(p1)
        # Seite 2
        p2 = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(p2, text=(
            "Lade deine leere Berichtsheft-Vorlage (.docx) hoch. Sie wird in den App-Ordner kopiert.\n\n"
            "Erkannt werden Tageszeilen mit „Mo“, „Di“ … in der ersten Spalte sowie die Felder "
            "„Ausbildungsnachweis Nr.“, „vom“ und „bis“. Alternativ kannst du Platzhalter wie "
            "{{NAME}}, {{VOM}}, {{BIS}}, {{NACHWEIS_NR}} in die Vorlage schreiben."),
            anchor="w", wraplength=600, justify="left").pack(fill="x", pady=(0, 12))
        self.template = TemplatePicker(p2, self.profile.template_path)
        self.template.pack(fill="x")
        self.pages.append(p2)
        # Seite 3
        p3 = ctk.CTkFrame(self, fg_color="transparent")
        self.nachweis = NachweisForm(p3, self.profile)
        self.nachweis.pack(fill="x")
        default_out = self.profile.output_dir or str(Path.home() / "Documents" / "Berichtshefte")
        self.outdir = OutputDirPicker(p3, default_out)
        self.outdir.pack(fill="x", pady=(16, 0))
        self.pages.append(p3)

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=3, column=0, sticky="ew", padx=20, pady=16)
        nav.grid_columnconfigure(0, weight=1)
        self.back_btn = ctk.CTkButton(nav, text="Zurück", width=100, fg_color="transparent", border_width=1,
                                      text_color=("gray10", "gray90"), command=self._back)
        self.back_btn.grid(row=0, column=1, padx=6)
        self.next_btn = ctk.CTkButton(nav, text="Weiter", width=120, command=self._next)
        self.next_btn.grid(row=0, column=2)
        self._show()
        self.after(100, self.grab_set)

    def _show(self) -> None:
        for p in self.pages:
            p.grid_forget()
        self.pages[self.step].grid(row=2, column=0, sticky="nsew", padx=20, pady=12)
        self.step_label.configure(text=f"Schritt {self.step + 1} von {len(STEPS)}: {STEPS[self.step]}")
        self.back_btn.configure(state="normal" if self.step else "disabled")
        self.next_btn.configure(text="Fertig" if self.step == len(STEPS) - 1 else "Weiter")

    def _back(self) -> None:
        if self.step:
            self.step -= 1
            self._show()

    def _next(self) -> None:
        if self.step == 0:
            self.personal.apply(self.profile)
            if not self.profile.name.strip():
                messagebox.showerror("Name fehlt", "Bitte mindestens deinen Namen eintragen.", parent=self)
                return
        elif self.step == 1:
            if not self.template.path:
                messagebox.showerror("Vorlage fehlt", "Bitte eine Blanko-Vorlage hochladen.", parent=self)
                return
            self.profile.template_path = self.template.path
        elif self.step == 2:
            err = self.nachweis.apply(self.profile)
            if err:
                messagebox.showerror("Eingabe prüfen", err, parent=self)
                return
            self.profile.output_dir = self.outdir.get()
            self._on_finish(self.config_obj)
            self.destroy()
            return
        self.step += 1
        self._show()

    def _cancel(self) -> None:
        if messagebox.askyesno("Abbrechen?", "Ersteinrichtung abbrechen? Die App braucht ein Profil und eine Vorlage.",
                               parent=self):
            self.destroy()
