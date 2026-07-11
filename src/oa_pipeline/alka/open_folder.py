"""
alka.open_folder — open a folder in the system file browser.

Cross-platform (Windows Explorer / macOS Finder / Linux xdg-open). Isolated so
the GUI code doesn't carry platform branching, and so it can be swapped/tested
independently. Returns (ok, message).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def open_in_file_browser(path: Path) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"Folder does not exist: {p}"
    try:
        if sys.platform.startswith("win"):
            # os.startfile is the canonical Windows way; fall back to explorer.
            import os
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True, f"Opened {p}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not open folder: {exc}"