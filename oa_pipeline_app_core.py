"""
oa_pipeline_app_core.py — GUI-independent logic for the desktop launcher
========================================================================

These functions contain all the real behaviour of the desktop app (project
discovery, command building, environment checks, verdict summarising) with no
dependency on Tkinter, so they can be unit-tested in a headless environment and
reused by any front end. `oa_pipeline_app.py` imports from here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


STAGE_FILES = [
    "02_ta_ph_qc.ipynb",
    "04_stage1a.ipynb",
    "05_stage1b.ipynb",
    "06_stage2.ipynb",
    "07_stage3.ipynb",
    "08_stage4.ipynb",
]


def find_project_root(start: Path) -> Path | None:
    """Walk up from `start` looking for run_pipeline.sh + notebooks/."""
    for candidate in [start, *start.parents]:
        if (candidate / "run_pipeline.sh").exists() and (
            candidate / "notebooks"
        ).is_dir():
            return candidate
    return None


def find_bash() -> str | None:
    """Locate bash; on Windows fall back to common Git Bash locations."""
    found = shutil.which("bash")
    if found:
        return found
    for p in [
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
        Path("C:/Program Files (x86)/Git/bin/bash.exe"),
    ]:
        if p.exists():
            return str(p)
    return None


def find_python() -> str:
    """Python interpreter the pipeline should use for Papermill."""
    return os.environ.get("PYTHON_BIN") or sys.executable or "python"


def package_importable(python_exe: str) -> bool:
    """Check oa_pipeline is importable by the chosen interpreter."""
    try:
        r = subprocess.run(
            [python_exe, "-c", "import oa_pipeline"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


def kernel_available(python_exe: str) -> bool:
    """Best-effort check that a Jupyter python3 kernel exists for Papermill."""
    try:
        r = subprocess.run(
            [python_exe, "-m", "jupyter", "kernelspec", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0 and "python3" in r.stdout
    except Exception:
        return False


def build_command(
    bash_exe: str,
    project_root: Path,
    xlsx: Path,
    out_dir: Path,
    sheet: str,
    no_parquet: bool,
    include_viewer: bool,
    include_review: bool,
    dry_run: bool,
) -> list[str]:
    """Assemble the run_pipeline.sh command."""
    cmd = [
        bash_exe,
        "./run_pipeline.sh",
        str(xlsx),
        str(out_dir),
        "--sheet",
        str(sheet),
    ]
    if no_parquet:
        cmd.append("--no-parquet")
    if include_viewer:
        cmd.append("--include-viewer")
    if include_review:
        cmd.append("--include-review")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def environment_problems(project_root: Path | None, bash_exe: str | None,
                         python_exe: str) -> list[str]:
    """Return a list of human-readable setup problems (empty if all good)."""
    problems: list[str] = []
    if not project_root:
        problems.append(
            "Could not find the project root (run_pipeline.sh + notebooks/). "
            "Place the app in the project folder."
        )
        return problems
    if not bash_exe:
        problems.append(
            "bash was not found. On Windows install Git Bash; "
            "on macOS/Linux it is built in."
        )
    if not package_importable(python_exe):
        problems.append(
            f"oa_pipeline is not importable by {python_exe}. "
            'Run: pip install -e ".[all]"'
        )
    if not kernel_available(python_exe):
        problems.append(
            "No Jupyter 'python3' kernel detected. Run: "
            f"{python_exe} -m pip install ipykernel && "
            f"{python_exe} -m ipykernel install --user --name python3"
        )
    return problems


def summarize_verdicts(out_dir: Path) -> str:
    """Read the final analysis_ready.csv and summarise verdict counts."""
    final = out_dir / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    if not final.exists():
        return "No final analysis_ready.csv was produced."
    try:
        import csv

        counts: dict[str, int] = {}
        with final.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            field = reader.fieldnames or []
            col = "analysis_audit_status" if "analysis_audit_status" in field else None
            if col is None:
                return f"Final file written: {final}"
            for row in reader:
                v = (row.get(col) or "").strip() or "(blank)"
                counts[v] = counts.get(v, 0) + 1
        total = sum(counts.values())
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
        return f"Final verdicts ({total} sample rows) -> {parts}\nFile: {final}"
    except Exception as exc:
        return f"Final file written: {final} (could not summarise: {exc})"
