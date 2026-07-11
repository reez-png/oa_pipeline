"""
alka.app — the Alka window: assemble panels, wire the Run button.

Deliberately thin. This file's job is to lay out the panels and connect the
Run button to the runner. It holds almost no logic of its own — the logic
lives in the panels (UI), config_writer (config), and runner (execution). Open
this file to see the *shape* of the app; open a panel or module to see what a
piece *does*.

Launch with:
    python -m oa_pipeline.alka.app
or from the project root:
    python src/oa_pipeline/alka/app.py
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

from .state import AppState
from . import runner
from . import results as results_reader
from .open_folder import open_in_file_browser
from . import figures as figures_launcher
from .scrollable import ScrollableFrame
from .panels.input_panel import InputPanel
from .panels.options_panel import OptionsPanel
from .panels.results_panel import ResultsPanel


APP_TITLE = "Alka — OA carbonate pipeline"


class AlkaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = AppState()
        self._cancel = threading.Event()

        root.title(APP_TITLE)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # The upper content (data, options, buttons, results) can grow tall —
        # especially the results panel — so it lives in a scrollable area. The
        # log sits below with its own scroll and a fixed height.
        outer = ttk.Frame(root, padding=(10, 10, 10, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self._scroll = ScrollableFrame(outer)
        self._scroll.grid(row=0, column=0, sticky="nsew")
        frm = self._scroll.body
        frm.columnconfigure(0, weight=1)

        # --- panels ---
        self.input_panel = InputPanel(frm, self.state)
        self.input_panel.grid(row=0, column=0, sticky="we", pady=(0, 6))

        self.options_panel = OptionsPanel(frm, self.state)
        self.options_panel.grid(row=1, column=0, sticky="we", pady=(0, 6))

        # --- buttons ---
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="we", pady=(2, 6))
        self.run_btn = ttk.Button(btns, text="Run pipeline", command=self._run)
        self.run_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self._cancel_run,
                                     state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(btns, text="Open output folder",
                                   command=self._open_output, state="disabled")
        self.open_btn.pack(side="left", padx=4)
        self.figures_btn = ttk.Button(btns, text="Open figures notebook",
                                      command=self._open_figures, state="disabled")
        self.figures_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="Quit", command=root.destroy).pack(side="right", padx=4)

        # --- progress + results (inside the scroll area) ---
        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=3, column=0, sticky="we", pady=(0, 4))

        self.results_panel = ResultsPanel(frm)
        self.results_panel.grid(row=4, column=0, sticky="we", pady=(0, 6))
        # (hidden until a run finishes)

        # --- log (outside the scroll area, fixed height, own scrollbar) ---
        log_frame = ttk.Frame(root, padding=(10, 0, 10, 10))
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self.log = scrolledtext.ScrolledText(log_frame, height=12, width=90,
                                             state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)

        # --- resolve environment and report ---
        problems = runner.resolve_environment(self.state)
        if problems:
            self._log("Environment problems:")
            for p in problems:
                self._log("  - " + p)
        else:
            self._log(f"Environment looks good. Project: {self.state.project_root}")

    # --- helpers ---
    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _thread_log(self, text: str):
        # called from the worker thread; marshal to the UI thread
        self.root.after(0, self._log, text)

    def _run(self):
        ok, why = self.state.ready_to_run()
        if not ok:
            self._log("Cannot run: " + why)
            return
        self._cancel.clear()
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.start(12)
        self._log("")
        self._log("=== Starting pipeline ===")

        def on_finish(rc: int, summary: str):
            def done():
                self.progress.stop()
                self.run_btn.configure(state="normal")
                self.cancel_btn.configure(state="disabled")
                self.state.is_running = False
                self._log("")
                if rc == 0:
                    self._log("=== Pipeline finished OK ===")
                    if summary:
                        self._log(summary)
                    # enable "Open output folder" now that there is output
                    if self.state.output_dir:
                        self.open_btn.configure(state="normal")
                        if not self.state.dry_run:
                            self.figures_btn.configure(state="normal")
                    # populate the structured results panel (unless dry-run)
                    if not self.state.dry_run and self.state.output_dir:
                        try:
                            vs = results_reader.read_verdicts(self.state.output_dir)
                            self.results_panel.show(vs)
                            ps = results_reader.read_precision(self.state.output_dir)
                            self.results_panel.show_precision(ps)
                        except Exception as exc:  # noqa: BLE001
                            self._log(f"(results panel: {exc})")
                else:
                    self._log(f"=== Pipeline exited with code {rc} ===")
            self.root.after(0, done)

        runner.run_pipeline(
            self.state,
            on_output=self._thread_log,
            on_finish=on_finish,
            cancel_event=self._cancel,
        )

    def _cancel_run(self):
        self._cancel.set()
        self._log("Cancelling…")

    def _open_output(self):
        if not self.state.output_dir:
            self._log("No output folder selected.")
            return
        ok, msg = open_in_file_browser(self.state.output_dir)
        if not ok:
            self._log(msg)

    def _open_figures(self):
        if not (self.state.project_root and self.state.output_dir):
            self._log("Cannot open figures: project root or output not set.")
            return
        self._log("Preparing figures notebook…")
        ok, msg = figures_launcher.open_figures(
            self.state.project_root, self.state.output_dir)
        for line in msg.split("\n"):
            self._log("  " + line)
        if ok:
            self._log("  (Jupyter is opening in your browser — run the notebook there.)")


def main():
    root = tk.Tk()
    AlkaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()