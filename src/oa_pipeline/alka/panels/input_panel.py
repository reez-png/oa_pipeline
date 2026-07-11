"""
alka.panels.input_panel — data file and output folder selection.

One responsibility: let the user choose the input workbook and the output
folder, keeping both in sync with AppState. Plain labels, obvious Browse
buttons — the first thing a new user sees, so it stays simple.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

from ..state import AppState


class InputPanel(ttk.LabelFrame):
    def __init__(self, master, state: AppState, **kw):
        super().__init__(master, text="Data", padding=8, **kw)
        self.state = state

        pad = {"padx": 4, "pady": 3}

        ttk.Label(self, text="Input workbook (.xlsx):").grid(
            row=0, column=0, sticky="w", **pad)
        self.input_var = tk.StringVar(value=str(state.input_xlsx or ""))
        ttk.Entry(self, textvariable=self.input_var, width=54).grid(
            row=0, column=1, sticky="we", **pad)
        ttk.Button(self, text="Browse…", command=self._pick_input).grid(
            row=0, column=2, **pad)

        ttk.Label(self, text="Output folder:").grid(
            row=1, column=0, sticky="w", **pad)
        self.output_var = tk.StringVar(value=str(state.output_dir or ""))
        ttk.Entry(self, textvariable=self.output_var, width=54).grid(
            row=1, column=1, sticky="we", **pad)
        ttk.Button(self, text="Browse…", command=self._pick_output).grid(
            row=1, column=2, **pad)

        self.columnconfigure(1, weight=1)

        self.input_var.trace_add("write", self._sync)
        self.output_var.trace_add("write", self._sync)

    def _pick_input(self):
        path = filedialog.askopenfilename(
            title="Choose the input workbook",
            filetypes=[("Excel workbook", "*.xlsx *.xls *.xlsm"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)

    def _pick_output(self):
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.output_var.set(path)

    def _sync(self, *_):
        self.state.input_xlsx = Path(self.input_var.get()) if self.input_var.get() else None
        self.state.output_dir = Path(self.output_var.get()) if self.output_var.get() else None