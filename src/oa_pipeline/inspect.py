"""
inspect.py
==========
Helpers for the QC Output Review notebook.

Import as:

    from oa_pipeline.inspect import ...

These functions support Notebook 03, which inspects pipeline outputs but does
not create downstream scientific data products. The helpers are intentionally
small and focused on file inventory, CSV preview, and image display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from .common import die

__all__ = [
    "IMAGE_SUFFIXES",
    "INVENTORY_COLUMNS",
    "list_output_files",
    "filter_inventory",
    "get_csv_files",
    "get_image_files",
    "preview_csv_table",
    "show_image",
]


# File extensions treated as images for inline display.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


# Stable inventory schema. Keeping this fixed prevents downstream functions
# from failing when an output folder exists but contains no files.
INVENTORY_COLUMNS = [
    "name",
    "suffix",
    "parent",
    "relative_path",
    "full_path",
    "size_kb",
]


def _require_inventory_columns(df: pd.DataFrame, required: set[str]) -> None:
    """Fail clearly if an inventory dataframe lacks required columns."""
    missing = required.difference(df.columns)
    if missing:
        die(f"Inventory is missing required columns: {sorted(missing)}")


def _normalise_suffixes(suffixes: Optional[Iterable[str]]) -> Optional[set[str]]:
    """Normalise suffix filters to lowercase dot-prefixed extensions."""
    if suffixes is None:
        return None

    normalised: set[str] = set()
    for suffix in suffixes:
        text = str(suffix).strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = f".{text}"
        normalised.add(text)

    return normalised


def list_output_files(
    root: Path,
    suffixes: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Walk root recursively and return a tidy inventory of files.

    Parameters
    ----------
    root:
        Output directory to scan.

    suffixes:
        Optional iterable of suffixes to keep, for example:
        {".csv", ".json", ".md", ".png"}. Suffixes are matched
        case-insensitively. Values may be provided with or without the leading
        dot.

    Returns
    -------
    pandas.DataFrame
        Columns are always:
        name, suffix, parent, relative_path, full_path, size_kb.
    """
    root = Path(root).expanduser()

    if not root.exists():
        die(f"Output folder not found: {root}")

    if not root.is_dir():
        die(f"Output path is not a folder: {root}")

    root = root.resolve()
    suffix_filter = _normalise_suffixes(suffixes)

    rows = []

    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        die(f"Could not scan output folder {root}: {exc}")

    for path in paths:
        try:
            if not path.is_file():
                continue

            suffix = path.suffix.lower()

            if suffix_filter is not None and suffix not in suffix_filter:
                continue

            try:
                size_kb = round(path.stat().st_size / 1024, 2)
            except OSError:
                size_kb = pd.NA

            rows.append(
                {
                    "name": path.name,
                    "suffix": suffix,
                    "parent": path.parent.name,
                    "relative_path": str(path.relative_to(root)),
                    "full_path": str(path.resolve()),
                    "size_kb": size_kb,
                }
            )
        except OSError:
            # A file may disappear or become inaccessible during scanning.
            # Skip it rather than failing the whole review notebook.
            continue

    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def filter_inventory(df: pd.DataFrame, keyword: Optional[str]) -> pd.DataFrame:
    """Keep rows where keyword occurs in file name or relative path.

    A None, empty, or whitespace only keyword returns the inventory unchanged.
    Matching is case insensitive and treats the keyword as literal text rather
    than as a regular expression.
    """
    if keyword is None or str(keyword).strip() == "":
        return df.copy()

    _require_inventory_columns(df, {"name", "relative_path"})

    kw = str(keyword).strip().lower()

    mask = (
        df["name"]
        .astype("string")
        .str.lower()
        .str.contains(kw, na=False, regex=False)
        | df["relative_path"]
        .astype("string")
        .str.lower()
        .str.contains(kw, na=False, regex=False)
    )

    return df.loc[mask].copy()


def get_csv_files(df: pd.DataFrame) -> List[Path]:
    """Return CSV paths from an inventory dataframe."""
    _require_inventory_columns(df, {"suffix", "full_path"})

    csv_df = df[df["suffix"].astype("string").str.lower().eq(".csv")]
    return [Path(path) for path in csv_df["full_path"].tolist()]


def get_image_files(df: pd.DataFrame) -> List[Path]:
    """Return image paths from an inventory dataframe."""
    _require_inventory_columns(df, {"suffix", "full_path"})

    img_df = df[df["suffix"].astype("string").str.lower().isin(IMAGE_SUFFIXES)]
    return [Path(path) for path in img_df["full_path"].tolist()]


def preview_csv_table(path: Path, nrows: int = 10) -> pd.DataFrame:
    """Read the first nrows of a CSV without loading the full file."""
    path = Path(path).expanduser()

    if not path.exists():
        die(f"CSV file not found: {path}")

    if not path.is_file():
        die(f"CSV path is not a file: {path}")

    if path.suffix.lower() != ".csv":
        die(f"Expected a .csv file, got: {path}")

    try:
        nrows_int = int(nrows)
    except Exception:
        die(f"nrows must be an integer, got: {nrows!r}")
        return pd.DataFrame()  # unreachable, keeps type checkers satisfied

    if nrows_int < 1:
        die(f"nrows must be at least 1, got: {nrows}")

    try:
        return pd.read_csv(path, nrows=nrows_int)
    except Exception as exc:
        die(f"Could not read CSV preview from {path}: {exc}")
        return pd.DataFrame()  # unreachable


def show_image(
    path: Path,
    title: Optional[str] = None,
    figsize: tuple[float, float] = (10, 5),
) -> None:
    """Display an image inline using matplotlib."""
    path = Path(path).expanduser()

    if not path.exists():
        die(f"Image file not found: {path}")

    if not path.is_file():
        die(f"Image path is not a file: {path}")

    if path.suffix.lower() not in IMAGE_SUFFIXES:
        die(
            f"Unsupported image type: {path.suffix}. "
            f"Expected one of {sorted(IMAGE_SUFFIXES)}"
        )

    try:
        import matplotlib.image as mpimg
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        die(f"matplotlib is required for show_image. Details: {exc}")

    try:
        img = mpimg.imread(path)
    except Exception as exc:
        die(f"Could not read image file {path}: {exc}")

    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(img)
    ax.axis("off")

    if title:
        ax.set_title(title)

    plt.show()
    plt.close(fig)
