"""
alka.panels.options_panel — the run-options section of the window.

One file, one responsibility: render the option controls and keep them in sync
with AppState. The new capability — "Compute carbonate chemistry internally" —
lives here as a clearly-labelled checkbox with a plain-language explanation, so
a user never has to hand-edit YAML.

Advanced/rarely-touched options (sheet index, parquet, viewer, review, dry-run)
are grouped under an "Advanced" area so the default view stays simple for the
non-expert users this tool targets.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..state import AppState


class OptionsPanel(ttk.LabelFrame):
    def __init__(self, master, state: AppState, **kw):
        super().__init__(master, text="Options", padding=8, **kw)
        self.state = state

        # --- primary, user-facing capability toggle ---
        self.carbonate_var = tk.BooleanVar(value=state.compute_carbonate_internally)
        cb = ttk.Checkbutton(
            self,
            text="Compute carbonate chemistry internally (recommended)",
            variable=self.carbonate_var,
            command=self._on_carbonate_toggle,
        )
        cb.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            self,
            text=("Uses the pipeline's own PyCO2SYS calculation from "
                  "reference-material-corrected alkalinity, so DIC / Ω / pCO₂ are "
                  "consistent with the corrected TA. Leave on unless you are "
                  "supplying externally-computed chemistry."),
            wraplength=520, foreground="#555", font=("", 8),
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(0, 6))

        # --- advanced options (collapsed by default) ---
        self.show_advanced = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Advanced options", variable=self.show_advanced,
            command=self._toggle_advanced,
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        self.adv = ttk.Frame(self)
        self.adv.grid(row=3, column=0, columnspan=3, sticky="we")
        self.adv.grid_remove()  # hidden until toggled

        ttk.Label(self.adv, text="Sheet index:").grid(row=0, column=0, sticky="w")
        self.sheet_var = tk.StringVar(value=state.sheet)
        ttk.Entry(self.adv, textvariable=self.sheet_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 16))

        self.no_parquet_var = tk.BooleanVar(value=state.no_parquet)
        ttk.Checkbutton(self.adv, text="Skip Parquet (CSV only)",
                        variable=self.no_parquet_var).grid(row=0, column=2, sticky="w")

        self.viewer_var = tk.BooleanVar(value=state.include_viewer)
        ttk.Checkbutton(self.adv, text="Include viewer (NB 01)",
                        variable=self.viewer_var).grid(row=1, column=0, columnspan=2, sticky="w")

        self.review_var = tk.BooleanVar(value=state.include_review)
        ttk.Checkbutton(self.adv, text="Include review (NB 03)",
                        variable=self.review_var).grid(row=1, column=2, sticky="w")

        self.dry_run_var = tk.BooleanVar(value=state.dry_run)
        ttk.Checkbutton(self.adv, text="Dry run (show steps, write nothing)",
                        variable=self.dry_run_var).grid(row=2, column=0, columnspan=3, sticky="w")

        for var, attr in [
            (self.sheet_var, "sheet"), (self.no_parquet_var, "no_parquet"),
            (self.viewer_var, "include_viewer"), (self.review_var, "include_review"),
            (self.dry_run_var, "dry_run"),
        ]:
            var.trace_add("write", self._sync_advanced)

    # --- event handlers keep AppState authoritative ---
    def _on_carbonate_toggle(self):
        self.state.compute_carbonate_internally = self.carbonate_var.get()

    def _toggle_advanced(self):
        if self.show_advanced.get():
            self.adv.grid()
        else:
            self.adv.grid_remove()

    def _sync_advanced(self, *_):
        self.state.sheet = self.sheet_var.get()
        self.state.no_parquet = self.no_parquet_var.get()
        self.state.include_viewer = self.viewer_var.get()
        self.state.include_review = self.review_var.get()
        self.state.dry_run = self.dry_run_var.get()