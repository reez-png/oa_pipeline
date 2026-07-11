"""
alka.figures — open the figures notebook on a run's output.

Design decision (safety): we never edit the user's master notebook in place.
Instead we COPY it next to the run's output, set INPUT in the copy to the run's
analysis_ready.csv, and open that copy in Jupyter. The original notebook — with
all its narrative and precision work — is never touched, so a bad edit can only
affect a throwaway per-run copy.

Jupyter launch tries JupyterLab first, then classic Notebook.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Matches the notebook's `INPUT = Path(...)` assignment (raw or plain string),
# capturing any trailing comment so we can preserve it.
_INPUT_RE = re.compile(
    r'^(?P<indent>\s*)INPUT\s*=\s*Path\([^\)]*\)(?P<comment>\s*#.*)?$',
    re.MULTILINE,
)


def _find_notebook(project_root: Path) -> Optional[Path]:
    """Locate the figures notebook. Prefers the extended one."""
    candidates = [
        project_root / "notebooks" / "oa_figures_extended.ipynb",
        project_root / "notebooks" / "oa_figures.ipynb",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _analysis_ready(out_dir: Path) -> Optional[Path]:
    p = Path(out_dir) / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    return p if p.exists() else None


def _point_input_at(nb_text_cell_source: str, csv_path: Path) -> tuple[str, bool]:
    """Rewrite the INPUT assignment to the given csv. Returns (new_source, changed)."""
    # Use a raw string with forward slashes — valid on Windows and avoids escape
    # issues from backslashes.
    posix = csv_path.as_posix()
    replacement = (
        r'\g<indent>INPUT  = Path(r"' + posix + r'")'
        r'\g<comment>'
    )
    new, n = _INPUT_RE.subn(replacement, nb_text_cell_source)
    return new, (n > 0)


def prepare_figures_notebook(project_root: Path, out_dir: Path) -> tuple[Optional[Path], str]:
    """Copy the figures notebook beside the output, point INPUT at the run's CSV.

    Returns (path_to_prepared_copy, message). On any problem returns (None, why).
    """
    try:
        import nbformat
    except Exception:  # noqa: BLE001
        return None, "nbformat not available; cannot prepare the figures notebook."

    master = _find_notebook(project_root)
    if master is None:
        return None, "No figures notebook found in notebooks/."

    csv = _analysis_ready(out_dir)
    if csv is None:
        return None, "No analysis_ready.csv found for this run."

    # copy destination: beside the output, timestamped so runs don't clobber
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest_dir = Path(out_dir)
    dest = dest_dir / f"figures_{stamp}.ipynb"

    try:
        nb = nbformat.read(str(master), as_version=4)
        changed_any = False
        for cell in nb.cells:
            if cell.cell_type == "code":
                src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                if "INPUT" in src and "Path(" in src:
                    new_src, changed = _point_input_at(src, csv)
                    if changed:
                        cell["source"] = new_src
                        changed_any = True
                        break
        nbformat.write(nb, str(dest))
    except Exception as exc:  # noqa: BLE001
        return None, f"Could not prepare notebook copy: {exc}"

    if not changed_any:
        # still usable, but warn that INPUT wasn't auto-set
        return dest, (f"Opened a copy, but could not auto-set INPUT — set it to:\n{csv}")
    return dest, f"Prepared figures notebook pointing at this run's output:\n{dest}"


def _jupyter_available() -> Optional[str]:
    """Return the name of an available Jupyter frontend, or None."""
    import importlib.util
    for mod in ("jupyterlab", "notebook"):
        if importlib.util.find_spec(mod) is not None:
            return mod
    return None


def launch_jupyter(notebook_path: Path, project_root: Path) -> tuple[bool, str]:
    """Launch JupyterLab (preferred) or classic Notebook on the given file."""
    which = _jupyter_available()
    if which is None:
        return False, ("Jupyter is not installed in this environment. Install it "
                       "with:  pip install jupyterlab   — or open the prepared "
                       "notebook manually in your editor.")
    py = sys.executable  # the venv's python
    # order attempts to match what's actually installed
    if which == "jupyterlab":
        attempts = [[py, "-m", "jupyterlab", str(notebook_path)],
                    [py, "-m", "jupyter", "lab", str(notebook_path)]]
    else:
        attempts = [[py, "-m", "notebook", str(notebook_path)],
                    [py, "-m", "jupyter", "notebook", str(notebook_path)]]
    last_err = ""
    for cmd in attempts:
        try:
            subprocess.Popen(cmd, cwd=str(project_root),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Launched {which} on the prepared notebook."
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue
    return False, f"Could not launch {which} ({last_err})."


def open_figures(project_root: Path, out_dir: Path) -> tuple[bool, str]:
    """Full flow: prepare the notebook copy and launch Jupyter on it."""
    dest, msg = prepare_figures_notebook(project_root, out_dir)
    if dest is None:
        return False, msg
    ok, launch_msg = launch_jupyter(dest, project_root)
    return ok, msg + "\n" + launch_msg