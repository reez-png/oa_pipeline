"""
alka.state — the app's settings in one place.

A single dataclass holding everything the GUI panels read and write, so there
are no globals scattered across the code. Panels take an AppState, read from it
to render, and write to it on user action. The runner reads from it to build the
command. When you need to know "what's the current input path?", it's here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppState:
    # --- paths ---
    project_root: Optional[Path] = None
    input_xlsx: Optional[Path] = None
    output_dir: Optional[Path] = None

    # --- basic run options (mirror the existing launcher) ---
    sheet: str = "0"
    no_parquet: bool = False
    include_viewer: bool = False
    include_review: bool = False
    dry_run: bool = False

    # --- new capability toggles (exposed as GUI controls) ---
    compute_carbonate_internally: bool = False

    # --- resolved environment (filled at startup) ---
    bash_exe: Optional[str] = None
    python_exe: Optional[str] = None

    # --- transient run state ---
    is_running: bool = False
    last_config_dir: Optional[Path] = None  # set by config_writer before a run

    def ready_to_run(self) -> tuple[bool, str]:
        """Cheap pre-run validation. Returns (ok, reason_if_not)."""
        if self.input_xlsx is None or not Path(self.input_xlsx).exists():
            return False, "Choose an input workbook that exists."
        if self.output_dir is None:
            return False, "Choose an output folder."
        if self.project_root is None:
            return False, "Project root not found (place Alka in the project folder)."
        if self.bash_exe is None:
            return False, "bash not found (install Git Bash on Windows)."
        return True, ""