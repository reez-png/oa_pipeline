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

from ..results import VerdictSummary, PrecisionSummary, ordered_counts
from ..tooltip import attach as attach_tooltip


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

        # precision sub-section (populated separately, below the verdicts)
        self._precision_frame = ttk.Frame(self)
        self._precision_frame.grid(row=3, column=0, sticky="w", pady=(8, 0))

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

    def show_precision(self, prec: "PrecisionSummary"):
        """Render the duplicate-precision sub-section beneath the verdicts."""
        for w in self._precision_frame.winfo_children():
            w.destroy()

        f = self._precision_frame
        heading = ttk.Label(f, text="Duplicate precision  ⓘ", font=("", 10, "bold"))
        heading.grid(row=0, column=0, columnspan=4, sticky="w")
        # hover explanation of the whole process (supplementary — essentials stay visible)
        attach_tooltip(
            heading,
            "How this is computed:\n"
            "• Field duplicates are two samples from the same site/depth, paired by "
            "sample_id (a/b).\n"
            "• For each pair we take the within-pair standard deviation (SD).\n"
            "• Precision = 2.2 × (SD / √n) across all pairs (GOA-ON Cookbook, "
            "SOP 22/23).\n"
            "• Field duplicates capture TOTAL uncertainty: site variability + "
            "handling + analysis (not analytical error alone).\n"
            "• 'above tolerance' means precision exceeds the weather-quality target "
            "— a data-quality finding to review, not a run error.",
            wraplength=380,
        )

        if not prec.available:
            ttk.Label(f, text=prec.message or "Precision not available.",
                      foreground="#777", font=("", 8), wraplength=520).grid(
                          row=1, column=0, columnspan=4, sticky="w")
            self.grid()
            return

        # Build a clear, units-bearing statement of what we compare against.
        tol_bits = []
        for row in prec.rows:
            unit = "" if row.variable == "PH" else " µmol/kg"
            tol_bits.append(f"{row.variable} ≤ {row.tolerance:g}{unit}")
        tol_text = ", ".join(tol_bits)
        ttk.Label(
            f,
            text=(f"{prec.duplicate_type.capitalize()} duplicates, "
                  f"{prec.quality_tier}-quality tier ({prec.n_pairs} pairs). "
                  f"Precision = 2.2·SD/√n, compared against the {prec.quality_tier} "
                  f"tolerance: {tol_text}."),
            foreground="#555", font=("", 8), wraplength=520, justify="left").grid(
                row=1, column=0, columnspan=4, sticky="w", pady=(0, 4))

        # header row — now shows the workings (SD, n) behind each precision value
        headers = ["Variable", "SD", "n", "Precision", "Tolerance (max)", "Status"]
        for c, txt in enumerate(headers):
            ttk.Label(f, text=txt, font=("", 9, "underline")).grid(
                row=2, column=c, sticky="w", padx=(0, 12))

        r = 3
        any_above = False
        for row in prec.rows:
            if row.within_tolerance:
                status_txt, status_color = "within", "#1a7f37"
            else:
                status_txt, status_color = "above tolerance", "#9a6700"
                any_above = True
            ttk.Label(f, text=row.variable).grid(row=r, column=0, sticky="w", padx=(0, 12))
            ttk.Label(f, text=f"{row.sd_pooled:.3g}").grid(row=r, column=1, sticky="w", padx=(0, 12))
            ttk.Label(f, text=str(row.n_pairs)).grid(row=r, column=2, sticky="w", padx=(0, 12))
            prec_lbl = ttk.Label(f, text=f"{row.precision:.3g}", font=("", 9, "bold"))
            prec_lbl.grid(row=r, column=3, sticky="w", padx=(0, 12))
            # per-row tooltip showing the exact arithmetic
            attach_tooltip(
                prec_lbl,
                f"{row.variable}: precision = 2.2 × (SD / √n)\n"
                f"= 2.2 × ({row.sd_pooled:.3g} / √{row.n_pairs})\n"
                f"= {row.precision:.3g}\n"
                f"(mean {row.variable} signal ≈ {row.mean_signal:.4g})",
                wraplength=300,
            )
            ttk.Label(f, text=f"{row.tolerance:.3g}").grid(row=r, column=4, sticky="w", padx=(0, 12))
            ttk.Label(f, text=status_txt, foreground=status_color).grid(row=r, column=5, sticky="w")
            r += 1

        # button to reveal the per-pair differences (the data behind the summary)
        self._pairs_visible = False
        self._pairs_detail = ttk.Frame(f)
        toggle = ttk.Button(
            f, text="Show duplicate pairs ▾",
            command=lambda: self._toggle_pairs(prec, toggle),
        )
        toggle.grid(row=r, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._pairs_detail.grid(row=r + 1, column=0, columnspan=6, sticky="w")
        self._pairs_detail.grid_remove()
        caveat_row = r + 2

        if any_above:
            ttk.Label(
                f,
                text=("Some variables are above the weather-quality tolerance. "
                      "For field duplicates this reflects total uncertainty "
                      "(site variability + handling + analysis), and is a data-"
                      "quality finding to review — not a pipeline error."),
                foreground="#555", font=("", 8), wraplength=520, justify="left").grid(
                    row=caveat_row, column=0, columnspan=6, sticky="w", pady=(4, 0))
        self.grid()

    def _toggle_pairs(self, prec, toggle_btn):
        """Reveal/hide the per-pair difference detail (the data behind the summary)."""
        self._pairs_visible = not getattr(self, "_pairs_visible", False)
        if not self._pairs_visible:
            self._pairs_detail.grid_remove()
            toggle_btn.configure(text="Show duplicate pairs ▾")
            return
        # build the detail on first show
        for w in self._pairs_detail.winfo_children():
            w.destroy()
        ttk.Label(self._pairs_detail,
                  text="Per-pair absolute differences (worst first). "
                       "Large single pairs drive the precision figure:",
                  foreground="#555", font=("", 8), wraplength=520).grid(
                      row=0, column=0, columnspan=4, sticky="w", pady=(2, 2))
        col = 0
        for var, pairs in prec.pairs_by_var.items():
            box = ttk.Frame(self._pairs_detail)
            box.grid(row=1, column=col, sticky="nw", padx=(0, 18))
            ttk.Label(box, text=var, font=("", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
            unit = "" if var == "PH" else " µmol/kg"
            for i, p in enumerate(pairs[:8], start=1):  # cap at 8 worst for space
                site = p.station or p.sample_id[-8:]
                ttk.Label(box, text=site, font=("", 8)).grid(row=i, column=0, sticky="w", padx=(0, 8))
                ttk.Label(box, text=f"{p.diff:.3g}{unit}", font=("", 8)).grid(row=i, column=1, sticky="w")
            col += 1
        self._pairs_detail.grid()
        toggle_btn.configure(text="Hide duplicate pairs ▴")