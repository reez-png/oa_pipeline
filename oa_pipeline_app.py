#!/usr/bin/env python3
"""
oa_pipeline_app.py — desktop launcher for the OA preprocessing pipeline
=======================================================================

A point-and-click front end for users who do not want to touch a shell or
Python. It wraps the same `run_pipeline.sh` the command-line workflow uses, so
results are identical — this only provides buttons, a file picker, a progress
log, and a verdict summary.

How a user runs it
------------------
- Windows:  double-click `oa_pipeline_app.py`  (or `python oa_pipeline_app.py`)
- macOS:    `python3 oa_pipeline_app.py`
- Linux:    `python3 oa_pipeline_app.py`

It must sit in the project root (the folder containing `run_pipeline.sh`,
`notebooks/`, `src/oa_pipeline/`). It checks that for you on launch.

No third-party packages are required for the GUI itself: Tkinter ships with
the standard CPython installer. The pipeline it launches still needs the
project installed (`pip install -e ".[all]"`) and a Jupyter kernel — the app
detects missing pieces and tells the user exactly what to do, rather than
failing with a traceback.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# Tkinter is in the standard library; give a clear message if a stripped
# Python lacks it rather than crashing.
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:  # pragma: no cover - environment dependent
    sys.stderr.write(
        "This launcher needs Tkinter, which is part of the standard Python "
        "installer.\nOn Debian/Ubuntu: sudo apt install python3-tk\n"
        f"Import error: {exc}\n"
    )
    sys.exit(1)


APP_TITLE = "OA Pipeline Runner"


# ---------------------------------------------------------------------------
# Logic lives in oa_pipeline_app_core (GUI-independent, unit-tested).
# ---------------------------------------------------------------------------

from oa_pipeline_app_core import (  # noqa: E402
    STAGE_FILES,
    build_command,
    environment_problems,
    find_bash,
    find_project_root,
    find_python,
    kernel_available,
    package_importable,
    summarize_verdicts,
)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


class PipelineApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x620")
        self.root.minsize(680, 560)

        self.project_root = find_project_root(Path(__file__).resolve().parent)
        self.bash_exe = find_bash()
        self.python_exe = find_python()
        self.proc: subprocess.Popen | None = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self.xlsx_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.config_dir_var = tk.StringVar()
        self.use_config_var = tk.BooleanVar(value=False)
        self.sheet_var = tk.StringVar(value="0")
        self.no_parquet_var = tk.BooleanVar(value=False)
        self.viewer_var = tk.BooleanVar(value=False)
        self.review_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)

        self._build_widgets()
        self._prefill_defaults()
        self._check_environment()
        self.root.after(100, self._drain_log)

    # -- layout --------------------------------------------------------------

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        title = ttk.Label(
            frm, text="Ocean Acidification Pipeline", font=("", 15, "bold")
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w")
        subtitle = ttk.Label(
            frm,
            text="Pick your Excel workbook and an output folder, then click Run.",
            foreground="#555",
        )
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # Workbook row
        ttk.Label(frm, text="Input workbook (.xlsx):").grid(
            row=2, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.xlsx_var, width=58).grid(
            row=2, column=1, sticky="we", **pad
        )
        ttk.Button(frm, text="Browse…", command=self._pick_xlsx).grid(
            row=2, column=2, **pad
        )

        # Output row
        ttk.Label(frm, text="Output folder:").grid(
            row=3, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.out_var, width=58).grid(
            row=3, column=1, sticky="we", **pad
        )
        ttk.Button(frm, text="Browse…", command=self._pick_out).grid(
            row=3, column=2, **pad
        )

        # Config folder row (optional per-stage YAML/JSON overrides)
        ttk.Checkbutton(
            frm,
            text="Use config folder:",
            variable=self.use_config_var,
            command=self._toggle_config_row,
        ).grid(row=4, column=0, sticky="w", **pad)
        self.config_entry = ttk.Entry(
            frm, textvariable=self.config_dir_var, width=58, state="disabled"
        )
        self.config_entry.grid(row=4, column=1, sticky="we", **pad)
        self.config_btn = ttk.Button(
            frm, text="Browse…", command=self._pick_config, state="disabled"
        )
        self.config_btn.grid(row=4, column=2, **pad)

        # Options
        opts = ttk.LabelFrame(frm, text="Options", padding=8)
        opts.grid(row=5, column=0, columnspan=3, sticky="we", **pad)
        ttk.Label(opts, text="Sheet index:").grid(row=0, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.sheet_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 16)
        )
        ttk.Checkbutton(
            opts, text="Skip Parquet (CSV only)", variable=self.no_parquet_var
        ).grid(row=0, column=2, sticky="w", padx=6)
        ttk.Checkbutton(
            opts, text="Include viewer (NB 01)", variable=self.viewer_var
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            opts, text="Include review (NB 03)", variable=self.review_var
        ).grid(row=1, column=2, sticky="w", padx=6)
        ttk.Checkbutton(
            opts,
            text="Dry run (show steps, write nothing)",
            variable=self.dry_run_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w")

        # Buttons
        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=3, sticky="we", pady=(4, 4))
        self.run_btn = ttk.Button(btns, text="Run pipeline", command=self._run)
        self.run_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(
            btns, text="Cancel", command=self._cancel, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=4)
        ttk.Button(
            btns, text="Open output folder", command=self._open_output
        ).pack(side="left", padx=4)
        ttk.Button(btns, text="Quit", command=self.root.destroy).pack(
            side="right", padx=4
        )

        # Progress + status
        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=3, sticky="we", **pad)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=self.status_var, foreground="#1F4E79").grid(
            row=8, column=0, columnspan=3, sticky="w", padx=8
        )

        # Log
        logfrm = ttk.LabelFrame(frm, text="Progress log", padding=4)
        logfrm.grid(row=9, column=0, columnspan=3, sticky="nsew", **pad)
        self.log = tk.Text(logfrm, height=14, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logfrm, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(9, weight=1)

    # -- helpers -------------------------------------------------------------

    def _prefill_defaults(self) -> None:
        if not self.project_root:
            return
        example = self.project_root / "examples" / "example_data.xlsx"
        if example.exists():
            self.xlsx_var.set(str(example))
        self.out_var.set(str(self.project_root / "outputs" / "gui_run"))

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _check_environment(self) -> None:
        problems = environment_problems(
            self.project_root, self.bash_exe, self.python_exe
        )
        if problems:
            self.status_var.set("Setup needed — see log.")
            self._append("Setup checks found issues:\n\n")
            for p in problems:
                self._append(f"  • {p}\n\n")
            self._append(
                "You can still try Run; the pipeline will report the exact "
                "error if something is missing.\n\n"
            )
        else:
            self._append(
                f"Environment looks good.\n  Project: {self.project_root}\n"
                f"  bash:    {self.bash_exe}\n  python:  {self.python_exe}\n\n"
            )

    def _pick_xlsx(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an Excel workbook",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self.xlsx_var.set(path)

    def _pick_out(self) -> None:
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.out_var.set(path)

    def _pick_config(self) -> None:
        path = filedialog.askdirectory(
            title="Choose a config folder (per-stage YAML/JSON)"
        )
        if path:
            self.config_dir_var.set(path)

    def _toggle_config_row(self) -> None:
        state = "normal" if self.use_config_var.get() else "disabled"
        self.config_entry.configure(state=state)
        self.config_btn.configure(state=state)
        if self.use_config_var.get() and not self.config_dir_var.get():
            # Default to the project's configs/ folder if it exists.
            if self.project_root:
                default = self.project_root / "configs"
                if default.is_dir():
                    self.config_dir_var.set(str(default))

    def _open_output(self) -> None:
        out = Path(self.out_var.get()).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(out)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(out)])
            else:
                subprocess.run(["xdg-open", str(out)])
        except Exception as exc:
            messagebox.showinfo("Output folder", f"{out}\n\n({exc})")

    # -- run / cancel --------------------------------------------------------

    def _run(self) -> None:
        if not self.project_root:
            messagebox.showerror(APP_TITLE, "Project root not found.")
            return
        if not self.bash_exe:
            messagebox.showerror(APP_TITLE, "bash not found (see log).")
            return
        xlsx = Path(self.xlsx_var.get()).expanduser()
        if not xlsx.exists():
            messagebox.showerror(APP_TITLE, f"Workbook not found:\n{xlsx}")
            return
        out_dir = Path(self.out_var.get()).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        config_dir: Path | None = None
        if self.use_config_var.get():
            cd_text = self.config_dir_var.get().strip()
            if cd_text:
                config_dir = Path(cd_text).expanduser()
                if not config_dir.is_dir():
                    messagebox.showerror(
                        APP_TITLE, f"Config folder not found:\n{config_dir}"
                    )
                    return

        cmd = build_command(
            self.bash_exe,
            self.project_root,
            xlsx,
            out_dir,
            self.sheet_var.get().strip() or "0",
            self.no_parquet_var.get(),
            self.viewer_var.get(),
            self.review_var.get(),
            self.dry_run_var.get(),
            config_dir=config_dir,
        )

        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.start(12)
        self.status_var.set("Running… this can take a minute or two.")
        self._append("\n" + "=" * 64 + "\nRunning:\n  " + " ".join(cmd) + "\n\n")

        env = dict(os.environ)
        env["PYTHON_BIN"] = self.python_exe

        def worker() -> None:
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                assert self.proc.stdout is not None
                for line in self.proc.stdout:
                    self.log_queue.put(line)
                code = self.proc.wait()
                self.log_queue.put(f"\n[exit code {code}]\n")
                if code == 0 and not self.dry_run_var.get():
                    self.log_queue.put(
                        "\n" + summarize_verdicts(out_dir) + "\n"
                    )
                self.log_queue.put(
                    "__DONE_OK__\n" if code == 0 else "__DONE_FAIL__\n"
                )
            except Exception as exc:  # pragma: no cover - GUI path
                self.log_queue.put(f"\nLauncher error: {exc}\n__DONE_FAIL__\n")

        threading.Thread(target=worker, daemon=True).start()

    def _cancel(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append("\nCancellation requested…\n")

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE_OK__\n":
                    self._finish(True)
                elif line == "__DONE_FAIL__\n":
                    self._finish(False)
                else:
                    self._append(line)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _finish(self, ok: bool) -> None:
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status_var.set("Done." if ok else "Finished with errors — see log.")


def main() -> None:
    root = tk.Tk()
    PipelineApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()