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
from .panels.input_panel import InputPanel
from .panels.options_panel import OptionsPanel


APP_TITLE = "Alka — OA carbonate pipeline"


class AlkaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = AppState()
        self._cancel = threading.Event()

        root.title(APP_TITLE)
        frm = ttk.Frame(root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

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
        ttk.Button(btns, text="Quit", command=root.destroy).pack(side="right", padx=4)

        # --- log ---
        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=3, column=0, sticky="we", pady=(0, 4))
        self.log = scrolledtext.ScrolledText(frm, height=18, width=90, state="disabled")
        self.log.grid(row=4, column=0, sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(4, weight=1)

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


def main():
    root = tk.Tk()
    AlkaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()