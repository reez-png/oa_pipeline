"""
alka.panels.results_panel — show the run's verdict summary after completion.

Populated by the app's finish callback with a VerdictSummary. Renders the
PASS / REVIEW / FAIL counts as coloured rows with a total, plus a one-line note
on whether the internal carbonate calculation ran. Hidden until there is a
result to show.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..results import VerdictSummary, ordered_counts


class ResultsPanel(ttk.LabelFrame):
    def __init__(self, master, **kw):
        super().__init__(master, text="Results", padding=8, **kw)
        self._rows_frame = ttk.Frame(self)
        self._rows_frame.grid(row=0, column=0, sticky="w")
        self._note = ttk.Label(self, text="", foreground="#555", font=("", 8),
                               wraplength=520, justify="left")
        self._note.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._path = ttk.Label(self, text="", foreground="#777", font=("", 8),
                               wraplength=520, justify="left")
        self._path.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.grid_remove()  # hidden until a result arrives

    def show(self, summary: VerdictSummary):
        # clear old rows
        for w in self._rows_frame.winfo_children():
            w.destroy()

        if not summary.found:
            ttk.Label(self._rows_frame, text=summary.message,
                      foreground="#b3261e").grid(row=0, column=0, sticky="w")
            self._note.configure(text="")
            self._path.configure(text="")
            self.grid()
            return

        if not summary.counts:
            ttk.Label(self._rows_frame, text=summary.message or "No verdicts found.",
                      foreground="#9a6700").grid(row=0, column=0, sticky="w")
        else:
            # header
            ttk.Label(self._rows_frame,
                      text=f"{summary.total} sample rows",
                      font=("", 10, "bold")).grid(row=0, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 4))
            r = 1
            for verdict, count, color in ordered_counts(summary):
                ttk.Label(self._rows_frame, text=f"{verdict}",
                          foreground=color, font=("", 11, "bold")).grid(
                              row=r, column=0, sticky="w", padx=(0, 12))
                ttk.Label(self._rows_frame, text=str(count),
                          foreground=color, font=("", 11)).grid(
                              row=r, column=1, sticky="w")
                r += 1

        # provenance note
        if summary.carbonate_internal is True:
            self._note.configure(
                text="Carbonate chemistry computed internally (PyCO₂SYS) from "
                     "reference-material-corrected TA.")
        elif summary.carbonate_internal is False:
            self._note.configure(
                text="Carbonate chemistry taken from the input (internal "
                     "calculation was not enabled).")
        else:
            self._note.configure(text="")

        self._path.configure(
            text=f"File: {summary.final_path}" if summary.final_path else "")
        self.grid()