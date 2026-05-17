"""
oa_inspect.py
=============
Helpers for the QC Output Review notebook (`03_qc_output_review.ipynb`).

These functions exist for a single notebook (notebook 03 only inspects --
it does not produce data products that other stages consume), so they live
in their own small module rather than swelling `oa_common.py`. The rule of
thumb followed across this refactor: promote a helper to `oa_common.py`
only when the second caller appears.

Everything here is pure: file-system scanning and pandas inventory.
No matplotlib at module scope -- it is imported lazily inside `show_image`
so the inventory + CSV-preview path runs in environments without
matplotlib installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from oa_common import die

__all__ = [
    "list_output_files",
    "filter_inventory",
    "get_csv_files",
    "get_image_files",
    "preview_csv_table",
    "show_image",
]

# File extensions we treat as images for inline display.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def list_output_files(root: Path) -> pd.DataFrame:
    """Walk `root` recursively and return a tidy inventory of every file.

    Columns
    -------
    name           : basename (e.g. "derived.csv")
    suffix         : lowercased extension including the dot (e.g. ".csv")
    parent         : name of the immediate parent folder (e.g. "data")
    relative_path  : path relative to `root` (display-friendly)
    full_path      : absolute string path (for re-opening)
    size_kb        : file size in kilobytes, rounded to 2 dp

    The function fails fast via `die(...)` if `root` does not exist, so the
    failure mode matches every other notebook in this refactor (named
    exit, not an opaque traceback).
    """
    if not root.exists():
        die(f"Output folder not found: {root}")

    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rows.append(
                {
                    "name": p.name,
                    "suffix": p.suffix.lower(),
                    "parent": p.parent.name,
                    "relative_path": str(p.relative_to(root)),
                    "full_path": str(p),
                    "size_kb": round(p.stat().st_size / 1024, 2),
                }
            )
    return pd.DataFrame(rows)


def filter_inventory(df: pd.DataFrame, keyword: Optional[str]) -> pd.DataFrame:
    """Keep rows where `keyword` (case-insensitive) is in name or relative path.

    A `None` or whitespace-only keyword returns the inventory unchanged.
    Matching against `relative_path` (not just `name`) means a keyword like
    `"sheet_0"` correctly catches every file under that sheet's folder.
    """
    if keyword is None or str(keyword).strip() == "":
        return df.copy()

    kw = str(keyword).strip().lower()
    mask = (
        df["name"].str.lower().str.contains(kw, na=False, regex=False)
        | df["relative_path"].str.lower().str.contains(kw, na=False, regex=False)
    )
    return df.loc[mask].copy()


def get_csv_files(df: pd.DataFrame) -> List[Path]:
    """Return CSV paths from the inventory, in inventory order."""
    csv_df = df[df["suffix"].eq(".csv")]
    return [Path(p) for p in csv_df["full_path"].tolist()]


def get_image_files(df: pd.DataFrame) -> List[Path]:
    """Return image paths (.png/.jpg/.jpeg/.webp) from the inventory."""
    img_df = df[df["suffix"].isin(IMAGE_SUFFIXES)]
    return [Path(p) for p in img_df["full_path"].tolist()]


def preview_csv_table(path: Path, nrows: int = 10) -> pd.DataFrame:
    """Read the first `nrows` of a CSV (head only; full file is not loaded).

    Using `nrows=` instead of `read_csv(...).head(n)` avoids parsing the
    whole file just to throw most of it away -- a meaningful difference
    when you point this at a 100k-row QC table.
    """
    return pd.read_csv(path, nrows=nrows)


def show_image(
    path: Path,
    title: Optional[str] = None,
    figsize: tuple[float, float] = (10, 5),
) -> None:
    """Display an image inline using matplotlib.

    matplotlib is imported lazily so that the rest of the inspection
    workflow (inventory + CSV preview) works without it.
    """
    try:
        import matplotlib.image as mpimg
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover - import guard
        die(f"matplotlib is required for `show_image`. Details: {e}")

    img = mpimg.imread(path)
    plt.figure(figsize=figsize)
    plt.imshow(img)
    plt.axis("off")
    if title:
        plt.title(title)
    plt.show()
