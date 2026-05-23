"""
common.py
=========
Shared utilities for the OA ocean acidification preprocessing pipeline.

Import as:

    from oa_pipeline.common import ...

This module contains reusable helpers used across the notebook and script
pipeline. Keeping these helpers in one importable module makes the workflow
more reproducible, easier to test, and easier to maintain.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Optional

import pandas as pd

__all__ = [
    "die",
    "utc_stamp",
    "canonical_colname",
    "normalize_columns",
    "resolve_col",
    "safe_str_series",
    "has_value_series",
    "safe_sheet_name",
    "fmt",
    "read_excel_sheets",
    "print_quick_summary",
    "write_html_table",
    "write_text",
    "write_json",
    "write_manifest",
    "ensure_dir",
    "sanitize_name",
    "deep_update",
    "load_config",
    "coerce_numeric",
    "coerce_datetime",
    "percent_missing",
    "make_missingness_table",
    "write_csv_and_parquet",
    "md_table_from_df",
    "first_existing",
    "existing_columns",
    "coalesce_numeric_series",
    "coalesce_string_series",
    "empty_float_series",
    "empty_string_series",
    "empty_bool_series",
    "safe_upper",
    "value_counts_frame",
    "build_flag_summary",
    "robust_outlier_flags",
    "build_corrections_table",
]


# =============================================================================
# Error handling
# =============================================================================


def die(msg: str, code: int = 2) -> None:
    """Print a clear error to stderr and stop execution."""
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    raise SystemExit(code)


# =============================================================================
# Timestamps
# =============================================================================


def utc_stamp() -> str:
    """Return a UTC timestamp string for manifests and reports."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# =============================================================================
# Column hygiene and alias resolution
# =============================================================================


def canonical_colname(value: object) -> str:
    """Return a forgiving canonical key for column alias matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def normalize_columns(
    df: pd.DataFrame,
    fail_on_duplicates: bool = True,
    fail_on_canonical_duplicates: bool = False,
) -> pd.DataFrame:
    """Strip whitespace from column labels and optionally reject duplicates.

    Excel files often contain accidental trailing spaces in headers. Removing
    those spaces is useful, but it can create duplicate names such as "TA" and
    "TA ". In a scientific pipeline, duplicated chemistry fields should fail
    loudly instead of being allowed to pass into downstream calculations.

    When fail_on_canonical_duplicates is True, columns that collapse to the same
    alphanumeric canonical key are also rejected. This stricter mode can catch
    ambiguous pairs such as "TA", "ta", and "T A" during input loading.
    """
    out = df.copy()
    cleaned = [str(c).strip() for c in out.columns]

    if fail_on_duplicates:
        counts: dict[str, int] = {}
        for col in cleaned:
            counts[col] = counts.get(col, 0) + 1

        duplicates = sorted([col for col, count in counts.items() if count > 1])
        if duplicates:
            die(
                "Duplicate column names after whitespace cleanup: "
                + ", ".join(duplicates)
            )

    if fail_on_canonical_duplicates:
        canon_map: dict[str, list[str]] = {}

        for col in cleaned:
            key = canonical_colname(col)
            if key:
                canon_map.setdefault(key, []).append(col)

        ambiguous = {
            key: sorted(set(cols))
            for key, cols in canon_map.items()
            if len(set(cols)) > 1
        }

        if ambiguous:
            details = "; ".join(
                f"{key}: {cols}" for key, cols in sorted(ambiguous.items())
            )
            die(f"Ambiguous column names after canonical cleanup: {details}")

    out.columns = cleaned
    return out


def _build_column_maps(
    df: pd.DataFrame,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Build exact, lower case, and canonical lookup maps for columns."""
    exact_map: dict[str, list[str]] = {}
    lower_map: dict[str, list[str]] = {}
    canon_map: dict[str, list[str]] = {}

    for col in df.columns:
        col_text = str(col)
        exact_map.setdefault(col_text, []).append(col_text)
        lower_map.setdefault(col_text.lower(), []).append(col_text)
        canon_map.setdefault(canonical_colname(col_text), []).append(col_text)

    return exact_map, lower_map, canon_map


def _single_match(
    mapping: dict[str, list[str]],
    key: str,
    requested: str,
) -> str | None:
    """Return one match and reject ambiguous matches."""
    matches = mapping.get(key, [])

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        die(
            f"Ambiguous column alias for '{requested}'. "
            f"Matches: {matches}"
        )

    return None


def _resolve_col_optional(df: pd.DataFrame, name: str) -> str | None:
    """Resolve a column name, returning None only when there is no match."""
    requested = str(name)
    exact_map, lower_map, canon_map = _build_column_maps(df)

    exact_match = _single_match(exact_map, requested, requested)
    if exact_match is not None:
        return exact_match

    lower_match = _single_match(lower_map, requested.lower(), requested)
    if lower_match is not None:
        return lower_match

    canon_match = _single_match(canon_map, canonical_colname(requested), requested)
    if canon_match is not None:
        return canon_match

    return None


def resolve_col(df: pd.DataFrame, name: str) -> str:
    """Return the single actual dataframe column matching name.

    Matching is attempted in this order:

    1. Exact match.
    2. Case insensitive match.
    3. Alphanumeric canonical match.

    Ambiguous matches stop the pipeline because silently choosing one pH, TA,
    DIC, salinity, or temperature column can corrupt scientific outputs.
    """
    match = _resolve_col_optional(df, name)
    if match is not None:
        return match

    die(f"Column '{name}' not found. Available columns: {list(df.columns)}")
    return ""


def first_existing(df: pd.DataFrame, candidates) -> str | None:
    """Return the first candidate that resolves unambiguously to a column."""
    for candidate in candidates:
        resolved = _resolve_col_optional(df, str(candidate))
        if resolved is not None:
            return resolved
    return None


def existing_columns(df: pd.DataFrame, candidates) -> list[str]:
    """Return all candidates that resolve unambiguously, preserving order."""
    out: list[str] = []

    for candidate in candidates:
        resolved = _resolve_col_optional(df, str(candidate))
        if resolved is not None and resolved not in out:
            out.append(resolved)

    return out


def safe_str_series(s: pd.Series) -> pd.Series:
    """Convert a Series to stripped nullable strings with missing values as empty text."""
    return s.astype("string").fillna("").str.strip()


def has_value_series(s: pd.Series) -> pd.Series:
    """Return True where a Series has a non missing and non blank value.

    This treats Excel style blank strings as missing while preserving normal
    numeric missingness semantics for numeric columns.
    """
    if pd.api.types.is_string_dtype(s) or s.dtype == object:
        text = s.astype("string").str.strip()
        return s.notna() & text.ne("").fillna(False)

    return s.notna()


def safe_upper(s: pd.Series) -> pd.Series:
    """Return a stripped uppercase nullable string view of a Series."""
    return safe_str_series(s).str.upper()


# =============================================================================
# Safe names and scalar formatting
# =============================================================================


def sanitize_name(text: str, max_len: int = 120) -> str:
    """Return a safer file or folder name.

    Handles empty names, whitespace, path hostile characters, repeated
    underscores, leading or trailing dots, and reserved Windows device names.
    """
    value = str(text).strip()
    value = re.sub(r'[<>:"/\\|?*\s]+', "_", value)
    value = re.sub(r"_+", "_", value).strip("._")

    if not value:
        value = "unnamed"

    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    if value.upper() in reserved:
        value = f"{value}_file"

    return value[:max_len]


def safe_sheet_name(sheet_name: str) -> str:
    """Make an Excel sheet name safe for use as a folder name."""
    return sanitize_name(sheet_name)


def fmt(x: object, nd: int = 4) -> str:
    """Format a scalar for reports and log lines."""
    try:
        if x is None:
            return "NA"
        if pd.isna(x):  # type: ignore[arg-type]
            return "NA"
        if isinstance(x, (int, float)):
            return f"{float(x):.{nd}f}"
        return str(x)
    except Exception:
        return str(x)


# =============================================================================
# Excel I/O
# =============================================================================


def _coerce_sheet_selector(sheet: str | int) -> str | int:
    """Convert simple numeric sheet strings such as "0" to integer indexes."""
    if isinstance(sheet, str):
        text = sheet.strip()
        if text.lower() == "all":
            return "all"
        if text.isdigit():
            return int(text)
        return text
    return sheet


def read_excel_sheets(xlsx_path: Path, sheet: str | int) -> dict[str, pd.DataFrame]:
    """Read one sheet or all sheets from an Excel workbook.

    The returned dictionary uses the real Excel sheet name, not merely the
    numeric sheet index. Exact sheet names win before numeric index
    interpretation, so a sheet named "01" is read as the sheet named "01"
    rather than sheet index 1.
    """
    xlsx_path = Path(xlsx_path)

    if not xlsx_path.exists():
        die(f"Excel file not found: {xlsx_path}")

    excel = pd.ExcelFile(xlsx_path, engine="openpyxl")

    if isinstance(sheet, str):
        text = sheet.strip()

        if text.lower() == "all":
            return {
                str(name): normalize_columns(pd.read_excel(excel, sheet_name=name))
                for name in excel.sheet_names
            }

        if text in excel.sheet_names:
            sheet_name = text
        elif text.isdigit():
            selector = int(text)
            if selector < 0 or selector >= len(excel.sheet_names):
                die(
                    f"Sheet index {selector} is out of range. "
                    f"Workbook has {len(excel.sheet_names)} sheets."
                )
            sheet_name = excel.sheet_names[selector]
        else:
            die(
                f"Sheet '{text}' not found. "
                f"Available sheets: {excel.sheet_names}"
            )
            sheet_name = ""
    elif isinstance(sheet, int):
        if sheet < 0 or sheet >= len(excel.sheet_names):
            die(
                f"Sheet index {sheet} is out of range. "
                f"Workbook has {len(excel.sheet_names)} sheets."
            )
        sheet_name = excel.sheet_names[sheet]
    else:
        die(f"Unsupported sheet selector type: {type(sheet).__name__}")
        sheet_name = ""

    df = pd.read_excel(excel, sheet_name=sheet_name)
    return {sheet_name: normalize_columns(df)}


# =============================================================================
# Console previews and HTML table writer
# =============================================================================


def print_quick_summary(df: pd.DataFrame, name: str, preview_rows: int = 15) -> None:
    """Print a compact dataframe overview."""
    print(f"\n=== SHEET: {name} ===")
    print(f"Rows: {len(df):,} | Cols: {df.shape[1]}")
    print("\nColumns:")
    for c in df.columns:
        print(f" - {c}")
    print("\nPreview:")
    print(df.head(preview_rows).to_string(index=False))


def write_html_table(
    df: pd.DataFrame,
    out_html: Path,
    max_rows: Optional[int] = None,
    title: Optional[str] = None,
) -> None:
    """Write a single page HTML table with escaped cell content."""
    out_html.parent.mkdir(parents=True, exist_ok=True)

    if max_rows is not None:
        df_show = df.head(max_rows)
        note = f"<p><b>NOTE:</b> showing first {max_rows:,} rows.</p>"
    else:
        df_show = df
        note = "<p><b>NOTE:</b> showing ALL rows.</p>"

    safe_title = escape(str(title or out_html.stem))

    html = (
        "<html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:Arial, sans-serif; margin:16px}"
        "table{border-collapse:collapse; font-size:12px}"
        "td,th{border:1px solid #ccc; padding:4px; vertical-align:top}"
        "thead th{position:sticky; top:0; background:#f7f7f7}"
        "</style>"
        "</head><body>"
        f"<h3>{safe_title}</h3>"
        f"<p><b>Generated:</b> {utc_stamp()}</p>"
        f"{note}"
        + df_show.to_html(index=False, escape=True)
        + "</body></html>"
    )

    out_html.write_text(html, encoding="utf-8")


# =============================================================================
# Text, JSON, manifest, paths, and config loading
# =============================================================================


def write_text(path: Path, text: str) -> None:
    """Write a text or markdown file, creating parent folders as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Mapping[str, Any]) -> None:
    """Write a JSON document with stable indentation and unicode preserved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a JSON manifest or provenance log."""
    write_json(path, payload)


def ensure_dir(path: Path) -> Path:
    """Create path and parents if needed, then return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def deep_update(
    base: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a recursive dictionary merge where override wins.

    Empty configs are treated as empty dictionaries. Non mapping config
    objects fail clearly because config files must have dictionary style keys.
    The returned object does not share nested dictionaries or lists with the
    input defaults.
    """
    out: dict[str, Any] = deepcopy(dict(base or {}))

    if override is None:
        return out

    if not isinstance(override, Mapping):
        die(
            "Config override must be a mapping or dictionary, got "
            f"{type(override).__name__}"
        )

    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_update(out[key], value)  # type: ignore[arg-type]
        else:
            out[key] = deepcopy(value)

    return out


def load_config(
    config_path: str | Path | None,
    default: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load JSON, YAML, or no config, then merge it over defaults.

    Accepted no config values are None, an empty string, "None", and "null".
    Empty YAML and JSON null are treated as empty dictionaries.
    """
    base = deepcopy(dict(default or {}))

    if config_path is None:
        return base

    path_text = str(config_path).strip()
    if path_text == "" or path_text.lower() in {"none", "null"}:
        return base

    path = Path(path_text)
    if not path.exists():
        die(f"Config file not found: {path}")

    suffix = path.suffix.lower()

    try:
        if suffix == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError:
                die(
                    "YAML config requested but PyYAML is not installed. "
                    "Install with: python -m pip install pyyaml"
                )
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            die(
                f"Unsupported config format: {path.suffix}. "
                "Use .json, .yaml, or .yml."
            )
    except SystemExit:
        raise
    except Exception as exc:
        die(f"Could not read config file {path}: {exc}")

    if loaded is None:
        loaded = {}

    if not isinstance(loaded, Mapping):
        die(f"Config file must contain a dictionary at the top level: {path}")

    return deep_update(base, loaded)


# =============================================================================
# Coercion and missingness helpers
# =============================================================================


def coerce_numeric(df: pd.DataFrame, cols) -> None:
    """In place conversion of selected columns to numeric values."""
    for c in cols:
        resolved = _resolve_col_optional(df, str(c))
        if resolved is not None:
            df[resolved] = pd.to_numeric(df[resolved], errors="coerce")


def coerce_datetime(df: pd.DataFrame, col: str, utc: bool = True) -> None:
    """In place conversion of a datetime column.

    UTC is the default because cruise records, bottle records, CTD casts, and
    sensor logs should be comparable across machines and time zones.
    """
    resolved = _resolve_col_optional(df, col)
    if resolved is not None:
        df[resolved] = pd.to_datetime(df[resolved], errors="coerce", utc=utc)


def percent_missing(s: pd.Series) -> float:
    """Return percentage of missing or blank values in a Series."""
    n = len(s)
    if n == 0:
        return 0.0

    missing = ~has_value_series(s)
    return float(missing.sum()) / float(n) * 100.0


def make_missingness_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return a one row per column inventory of dtype and missingness.

    Blank strings are counted as missing because they are common in Excel files.
    """
    rows = []

    for c in df.columns:
        missing_mask = ~has_value_series(df[c])

        rows.append(
            {
                "column": c,
                "dtype": str(df[c].dtype),
                "n_missing": int(missing_mask.sum()),
                "pct_missing": (
                    round(float(missing_mask.mean() * 100.0), 2)
                    if len(df)
                    else 0.0
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["pct_missing", "column"],
        ascending=[False, True],
    )


# =============================================================================
# Typed empty Series
# =============================================================================


def empty_float_series(index: pd.Index) -> pd.Series:
    """Return an all missing Float64 Series with the supplied index."""
    return pd.Series(pd.NA, index=index, dtype="Float64")


def empty_string_series(index: pd.Index) -> pd.Series:
    """Return an all missing nullable string Series with the supplied index."""
    return pd.Series(pd.NA, index=index, dtype="string")


def empty_bool_series(index: pd.Index) -> pd.Series:
    """Return an all missing nullable boolean Series with the supplied index."""
    return pd.Series(pd.NA, index=index, dtype="boolean")


# =============================================================================
# Column coalescing with row level provenance
# =============================================================================


def coalesce_numeric_series(
    df: pd.DataFrame,
    cols: list,
) -> tuple[pd.Series, pd.Series]:
    """Coalesce numeric columns in order and record the source column per row."""
    resolved_cols = existing_columns(df, cols)
    if not resolved_cols:
        return empty_float_series(df.index), empty_string_series(df.index)

    vals = [
        pd.to_numeric(df[c], errors="coerce").astype("Float64")
        for c in resolved_cols
    ]

    out = vals[0].copy()
    src = pd.Series(resolved_cols[0], index=df.index, dtype="string")

    for c, s in zip(resolved_cols[1:], vals[1:]):
        take = out.isna() & s.notna()
        out = out.where(~take, s)
        src = src.where(~take, c)

    src = src.where(out.notna(), pd.NA)
    return out, src


def coalesce_string_series(
    df: pd.DataFrame,
    cols: list,
) -> tuple[pd.Series, pd.Series]:
    """Coalesce string columns in order and record the source column per row."""
    resolved_cols = existing_columns(df, cols)
    if not resolved_cols:
        return empty_string_series(df.index), empty_string_series(df.index)

    vals = [safe_str_series(df[c]).replace("", pd.NA) for c in resolved_cols]

    out = vals[0].copy()
    src = pd.Series(resolved_cols[0], index=df.index, dtype="string")

    for c, s in zip(resolved_cols[1:], vals[1:]):
        take = out.isna() & s.notna()
        out = out.where(~take, s)
        src = src.where(~take, c)

    src = src.where(out.notna(), pd.NA)
    return out.astype("string"), src


# =============================================================================
# Report helpers
# =============================================================================


def value_counts_frame(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Return value counts of a column as a tidy dataframe."""
    resolved = resolve_col(df, col)
    vc = df[resolved].value_counts(dropna=False)
    out = vc.rename_axis(resolved).reset_index(name="count")
    total = out["count"].sum()
    out["pct"] = (out["count"] / total * 100.0).round(2) if total else 0.0
    return out


def md_table_from_df(df: pd.DataFrame, max_rows: int = 100) -> str:
    """Render a DataFrame as Markdown, falling back to a code block."""
    head = df.head(max_rows).copy()
    if head.empty:
        return "_(No rows)_"

    try:
        return head.to_markdown(index=False)
    except Exception:
        return "```\n" + head.to_string(index=False) + "\n```"


def build_flag_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Inventory every flag column in a dataframe."""
    flag_cols = [c for c in df.columns if str(c).startswith("flag_")]
    rows = []

    for col in flag_cols:
        s = df[col]

        if str(s.dtype) == "boolean":
            true_mask = s.fillna(False)
        elif s.dtype == bool:
            true_mask = s
        else:
            true_mask = safe_upper(s).isin(["TRUE", "T", "YES", "Y", "1"])

        rows.append(
            {
                "flag": col,
                "n_true": int(true_mask.sum()),
                "n_na": int(s.isna().sum()),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["flag", "n_true", "n_na"])

    return pd.DataFrame(rows).sort_values("n_true", ascending=False)


# =============================================================================
# Mixed I/O: CSV plus optional Parquet
# =============================================================================


def write_csv_and_parquet(
    df: pd.DataFrame,
    csv_path: Path,
    parquet_path: Path,
    write_parquet: bool = True,
) -> tuple[bool, Optional[str]]:
    """Write CSV always and Parquet optionally.

    CSV settings are explicit for stable output across machines. Temporary
    files are used so a crash is less likely to leave a half written final file.
    """
    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_csv = csv_path.with_suffix(csv_path.suffix + ".tmp")

    try:
        df.to_csv(
            tmp_csv,
            index=False,
            encoding="utf-8",
            na_rep="",
            lineterminator="\n",
            date_format="%Y-%m-%dT%H:%M:%SZ",
        )
        tmp_csv.replace(csv_path)
    except Exception:
        if tmp_csv.exists():
            tmp_csv.unlink()
        raise

    if not write_parquet:
        return False, "Parquet disabled by configuration"

    tmp_parquet = parquet_path.with_suffix(parquet_path.suffix + ".tmp")

    try:
        df.to_parquet(tmp_parquet, index=False)
        tmp_parquet.replace(parquet_path)
        return True, None
    except Exception as exc:
        if tmp_parquet.exists():
            tmp_parquet.unlink()
        return False, str(exc)


# =============================================================================
# Robust statistics and correction tables
# =============================================================================


def robust_outlier_flags(
    x: pd.Series,
    mad_k: float = 3.5,
    max_abs: Optional[float] = None,
    min_n: int = 5,
) -> pd.Series:
    """Flag possible outliers using MAD and optional absolute limits.

    This produces screening flags, not automatic scientific rejection. The MAD
    rule is disabled when there are too few valid values.
    """
    mad_k = float(mad_k)
    min_n = int(min_n)

    if not math.isfinite(mad_k) or mad_k <= 0:
        die(f"mad_k must be a positive finite number, got {mad_k!r}")

    if min_n < 1:
        die(f"min_n must be >= 1, got {min_n!r}")

    if max_abs is not None:
        max_abs = float(max_abs)
        if not math.isfinite(max_abs) or max_abs < 0:
            die(f"max_abs must be non negative when supplied, got {max_abs!r}")

    xx = pd.to_numeric(x, errors="coerce")
    valid_n = int(xx.notna().sum())

    if valid_n < int(min_n):
        mad_rule = pd.Series(False, index=xx.index)
    else:
        med = xx.median()
        mad = (xx - med).abs().median()

        if pd.isna(mad) or mad == 0:
            mad_rule = pd.Series(False, index=xx.index)
        else:
            sigma = 1.4826 * mad
            mad_rule = (xx - med).abs() > (float(mad_k) * sigma)

    abs_rule = pd.Series(False, index=xx.index)

    if max_abs is not None:
        abs_rule = xx.abs() > float(max_abs)

    return (mad_rule | abs_rule).fillna(False)


def build_corrections_table(
    df_qc: pd.DataFrame,
    group_by: Optional[str],
    diff_col: str,
    min_n: int,
) -> pd.DataFrame:
    """Compute correction statistics after excluding flagged outliers."""
    outlier_col = f"{diff_col}_is_outlier"

    missing = [c for c in [diff_col, outlier_col] if c not in df_qc.columns]
    if missing:
        die(
            "Cannot build corrections table because required columns are missing: "
            + ", ".join(missing)
        )

    work = df_qc.copy()
    work[diff_col] = pd.to_numeric(work[diff_col], errors="coerce")
    outlier = work[outlier_col].fillna(False).astype(bool)

    ok = work.loc[~outlier & work[diff_col].notna()].copy()

    overall_n = int(ok[diff_col].notna().sum())
    overall_mean = float(ok[diff_col].mean()) if overall_n > 0 else float("nan")
    overall_sd = float(ok[diff_col].std(ddof=1)) if overall_n > 1 else float("nan")

    if group_by and group_by in ok.columns:
        grp = (
            ok[[group_by, diff_col]]
            .groupby(group_by, dropna=False)[diff_col]
            .agg(["count", "mean", "std"])
            .rename(columns={"count": "n", "mean": "correction", "std": "sd"})
            .reset_index()
        )

        grp["group_has_min_n"] = grp["n"] >= int(min_n)
        grp["correction"] = pd.to_numeric(
            grp["correction"],
            errors="coerce",
        ).astype("Float64")

        grp.loc[~grp["group_has_min_n"], "correction"] = pd.NA

        grp["overall_n"] = overall_n
        grp["overall_correction"] = overall_mean
        grp["overall_sd"] = overall_sd

        return grp

    return pd.DataFrame(
        {
            "overall_n": [overall_n],
            "overall_correction": [overall_mean],
            "overall_sd": [overall_sd],
        }
    )
