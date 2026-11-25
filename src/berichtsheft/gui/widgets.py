"""Wiederverwendbare Bausteine der Oberfläche."""

from __future__ import annotations

import datetime as dt
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from ..core.models import DayEntry, Issue, Severity

WEEKDAY_LONG = {"Mo": "Montag", "Di": "Dienstag", "Mi": "Mittwoch", "Do": "Donnerstag", "Fr": "Freitag"}
OK_COLOR = ("#1b7f3b", "#4cc274")
WARN_COLOR = ("#b26a00", "#f0b44c")
ERR_COLOR = ("#b3261e", "#f2867e")
MUTED = ("gray40", "gray65")


def parse_user_date(text: str) -> dt.date | None:
    """``15.06.2026`` / ``15.06.26`` / ``2026-06-15`` -> date, sonst None."""
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class DayCard(ctk.CTkFrame):
    """Ein Tag: Kopfzeile mit Status, editierbarer Text, Zeichenzähler."""

    def __init__(self, master, day: DayEntry, max_chars: int, on_change: Callable[[], None] | None = None):
        super().__init__(master, corner_radius=8)
        self.day = day
        self.max_chars = max_chars
        self.generated_text = day.text
        self._on_change = on_change
        self.grid_columnconfigure(0, weight=1)

        status_ok = day.ok
        symbol = "✓" if status_ok else "⚠"
        color = OK_COLOR if status_ok else WARN_COLOR
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text=symbol, text_color=color, font=ctk.CTkFont(size=16, weight="bold"), width=20).grid(row=0, column=0)
        title = f"{WEEKDAY_LONG.get(day.day_code, day.day_code)}, {day.date:%d.%m.%Y}"
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(weight="bold"), anchor="w").grid(row=0, column=1, sticky="w", padx=(6, 0))
        meta = " · ".join(x for x in [day.lernfeld or "Lernfeld ?", ", ".join(day.trainers)] if x)
        ctk.CTkLabel(head, text=meta, text_color=MUTED, anchor="e").grid(row=0, column=2, sticky="e")

        self.text = ctk.CTkTextbox(self, height=92, wrap="word")
        self.text.grid(row=1, column=0, sticky="ew", padx=10)
        self.text.insert("1.0", day.text)
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<KeyRelease>", lambda _e: self._update_counter())

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 8))
        foot.grid_columnconfigure(0, weight=1)
        issues = [i for i in day.issues]
        info = "  ".join(f"{'⚠' if i.severity is not Severity.INFO else 'ℹ'} {i.message}" for i in issues)
        files = ", ".join(p.name for p in day.sources)
        ctk.CTkLabel(foot, text=info or files, text_color=WARN_COLOR if not status_ok else MUTED,
                     anchor="w", justify="left", wraplength=560, font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(foot, text="Zurücksetzen", width=100, height=24, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.reset).grid(row=0, column=1, padx=(6, 6))
        self.counter = ctk.CTkLabel(foot, text="", width=80, anchor="e", font=ctk.CTkFont(size=11))
        self.counter.grid(row=0, column=2, sticky="e")
        self._update_counter()

    def _modified(self, _event=None) -> None:
        self.text.edit_modified(False)
        self._update_counter()

    def _update_counter(self) -> None:
        n = len(self.get_text())
        over = self.max_chars and n > self.max_chars
        self.counter.configure(text=f"{n} / {self.max_chars}" if self.max_chars else f"{n} Zeichen",
                               text_color=ERR_COLOR if over else MUTED)
        if self._on_change:
            self._on_change()

    def get_text(self) -> str:
        return self.text.get("1.0", "end").strip()

    def reset(self) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.generated_text)
        self._update_counter()


class LogView(ctk.CTkTextbox):
    """Statusbereich statt Konsolenausgabe."""

    def __init__(self, master, **kw):
        super().__init__(master, height=110, wrap="word", font=ctk.CTkFont(size=12), **kw)
        self.configure(state="disabled")
        self.tag_config("fehler", foreground="#d0342c")
        self.tag_config("warnung", foreground="#c77c02")
        self.tag_config("ok", foreground="#2e9e55")

    def add(self, text: str, tag: str = "") -> None:
        self.configure(state="normal")
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.insert("end", f"{stamp}  {text}\n", tag or ())
        self.see("end")
        self.configure(state="disabled")

    def issue(self, issue: Issue) -> None:
        tag = {Severity.ERROR: "fehler", Severity.WARNING: "warnung", Severity.INFO: ""}[issue.severity]
        self.add(str(issue), tag)

    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


class LabeledEntry(ctk.CTkFrame):
    def __init__(self, master, label: str, value: str = "", width: int = 260, placeholder: str = ""):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text=label, width=170, anchor="w").grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar(value=value)
        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width, placeholder_text=placeholder)
        self.entry.grid(row=0, column=1, sticky="ew")

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)


def lines_from_text(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
