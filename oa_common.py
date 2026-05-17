"""
oa_common.py
============
Shared utilities for the OA (ocean acidification) preprocessing pipeline.

This module is imported by every notebook in the chain (01 -> 08). It holds
the small helpers that previously got copy-pasted into every section of the
monolithic notebook (`die`, `utc_stamp`, `normalize_columns`, ...).

Why a module instead of redefining these in each notebook
---------------------------------------------------------
- Pimentel et al. (2019), in a study of 1.16M public notebooks, found that
  only ~10% used local module imports, and that this lack of modularization
  tracked with lower reproducibility scores. Summary in the Towards Data
  Science article on reproducible notebooks (2024).
- "Ten Simple Rules for Reproducible Research in Jupyter Notebooks"
  (Rule 7: "Build a pipeline") explicitly recommends moving reusable code
  out of cells into importable Python files. Rule 4 (modularize) is even
  more direct.
- Single source of truth: if `utc_stamp` needs a new format, we change it
  once and every notebook picks it up.

This file grows as each subsequent notebook is refactored. Notebook 01 needs
the helpers below; later notebooks will add canonical-schema helpers,
range-policy dataclasses, etc.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

__all__ = [
    "die",
    "utc_stamp",
    "normalize_columns",
    "resolve_col",
    "safe_str_series",
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


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def die(msg: str, code: int = 2) -> None:
    """Print a clear error to stderr and stop execution.

    Used at the top of each notebook to fail fast when an input file is
    missing or a parameter is malformed, rather than continuing into a
    confusing downstream traceback.
    """
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def utc_stamp() -> str:
    """Return a UTC timestamp string suitable for manifests and reports.

    UTC (not local time) so manifests from different machines are
    comparable. ISO-like format so they sort lexicographically.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Column hygiene
# ---------------------------------------------------------------------------

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from every column label.

    Excel workbooks frequently ship with trailing spaces in headers
    ('Salinity ' vs 'Salinity'); without this, downstream alias resolution
    misses them silently.
    """
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def resolve_col(df: pd.DataFrame, name: str) -> str:
    """Return the actual column name in `df` that matches `name`.

    Tries exact match first, then a case-insensitive fallback. Fails fast
    via `die(...)` if neither resolves -- this is intentional: a missing
    column in a QC step is a configuration error, not something to silently
    skip.
    """
    if name in df.columns:
        return name
    lower_map = {str(c).lower(): c for c in df.columns}
    key = str(name).lower()
    if key in lower_map:
        return lower_map[key]
    die(f"Column '{name}' not found. Available columns: {list(df.columns)}")
    return ""  # unreachable; keeps type-checkers happy


def safe_str_series(s: pd.Series) -> pd.Series:
    """Coerce a Series to whitespace-stripped strings, with NaN -> ''.

    Used for tag / category columns where you want to compare to a
    literal string (e.g. tag.str.startswith('RM')) without `<NA>` blowing
    up the comparison.
    """
    return s.astype("string").fillna("").str.strip()


# ---------------------------------------------------------------------------
# Safe filenames
# ---------------------------------------------------------------------------

def safe_sheet_name(sheet_name: str) -> str:
    """Make a sheet name safe to use as a file or folder name.

    Replaces characters that break paths on Windows (\\, :, /, spaces).
    """
    bad = {" ": "_", "/": "_", "\\": "_", ":": "_"}
    s = str(sheet_name)
    for k, v in bad.items():
        s = s.replace(k, v)
    return s


def fmt(x: object, nd: int = 4) -> str:
    """Format a scalar for reports / log lines.

    Returns 'NA' for None or NaN, fixed-point for numerics, str() for the
    rest. Centralised so every report formats numbers the same way.
    """
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


# ---------------------------------------------------------------------------
# Excel I/O
# ---------------------------------------------------------------------------

def read_excel_sheets(xlsx_path: Path, sheet: str | int) -> Dict[str, pd.DataFrame]:
    """Read one sheet or all sheets from an .xlsx file.

    `sheet` may be:
      - an int (zero-based sheet index)
      - an exact sheet name
      - the literal string 'all' (case-insensitive) for every sheet
    """
    if isinstance(sheet, str) and sheet.lower() == "all":
        dfs = pd.read_excel(xlsx_path, sheet_name=None, engine="openpyxl")
        return {str(k): v for k, v in dfs.items()}
    df = pd.read_excel(xlsx_path, sheet_name=sheet, engine="openpyxl")
    return {str(sheet): df}


# ---------------------------------------------------------------------------
# Console previews
# ---------------------------------------------------------------------------

def print_quick_summary(df: pd.DataFrame, name: str, preview_rows: int = 15) -> None:
    """One-screen overview of a dataframe: shape, columns, and a head sample."""
    print(f"\n=== SHEET: {name} ===")
    print(f"Rows: {len(df):,} | Cols: {df.shape[1]}")
    print("\nColumns:")
    for c in df.columns:
        print(f" - {c}")
    print("\nPreview:")
    print(df.head(preview_rows).to_string(index=False))


# ---------------------------------------------------------------------------
# HTML table writer
# ---------------------------------------------------------------------------

def write_html_table(
    df: pd.DataFrame,
    out_html: Path,
    max_rows: Optional[int] = None,
    title: Optional[str] = None,
) -> None:
    """Write a single-page, sticky-header, scrollable HTML table.

    Useful for browsing a sheet in a regular browser without opening Excel.
    """
    out_html.parent.mkdir(parents=True, exist_ok=True)

    if max_rows is not None:
        df_show = df.head(max_rows)
        note = f"<p><b>NOTE:</b> showing first {max_rows:,} rows.</p>"
    else:
        df_show = df
        note = "<p><b>NOTE:</b> showing ALL rows.</p>"

    html = (
        "<html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:Arial, sans-serif; margin:16px}"
        "table{border-collapse:collapse; font-size:12px}"
        "td,th{border:1px solid #ccc; padding:4px; vertical-align:top}"
        "thead th{position:sticky; top:0; background:#f7f7f7}"
        "</style>"
        "</head><body>"
        f"<h3>{title or out_html.stem}</h3>"
        f"<p><b>Generated:</b> {utc_stamp()}</p>"
        f"{note}"
        + df_show.to_html(index=False, escape=False)
        + "</body></html>"
    )
    out_html.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON manifest / provenance
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Text + JSON writers, path helpers
# ---------------------------------------------------------------------------

def write_text(path: Path, text: str) -> None:
    """Write a plain-text or markdown file, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    """Write a JSON document with stable indentation and unicode preserved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def write_manifest(path: Path, payload: Dict[str, Any]) -> None:
    """Write a JSON manifest (provenance log) at `path`.

    Manifests are the right home for: input path, parameters used,
    timestamp, list of outputs, package versions. Keeping this information
    here (rather than in filenames) is what keeps the filenames short.

    Equivalent to write_json; kept as a distinct name so callers signal
    intent at the call site.
    """
    write_json(path, payload)


def ensure_dir(path: Path) -> Path:
    """Create `path` (and parents) if needed, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_name(text: str) -> str:
    """Strip filename-hostile characters from a string.

    Replaces `<>:"/\\|?*` and spaces with underscores. Use for any
    string that will become part of a file or folder name.
    """
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in str(text))
    return out.replace(" ", "_")


def deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive dict merge: `override` wins, nested dicts merge in place.

    Used by the config loader so a user can supply a partial YAML/JSON
    file that overrides only the keys they care about, without having to
    restate the full default config.
    """
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Coercion + missingness helpers (Stage 1A+ all use these)
# ---------------------------------------------------------------------------

def coerce_numeric(df: pd.DataFrame, cols) -> None:
    """In-place: convert each named column to numeric, coercing errors to NaN."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def coerce_datetime(df: pd.DataFrame, col: str) -> None:
    """In-place: convert `col` to datetime, coercing errors to NaT."""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")


def percent_missing(s: pd.Series) -> float:
    """Percentage of NaN in a Series (0.0 for empty series)."""
    n = len(s)
    if n == 0:
        return 0.0
    return float(s.isna().sum()) / float(n) * 100.0


def make_missingness_table(df: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-column inventory: dtype, n_missing, pct_missing.

    Sorted with worst columns first so a quick `.head()` shows you the
    fields most in trouble.
    """
    rows = []
    for c in df.columns:
        rows.append(
            {
                "column": c,
                "dtype": str(df[c].dtype),
                "n_missing": int(df[c].isna().sum()),
                "pct_missing": round(percent_missing(df[c]), 2),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["pct_missing", "column"], ascending=[False, True]
    )


def first_existing(df: pd.DataFrame, candidates) -> Optional[str]:
    """Return the first name in `candidates` that exists as a column of `df`.

    Tries three increasingly forgiving matches in order:
      1. Exact equality (`"ph_co2sys" -> "ph_co2sys"`).
      2. Case-insensitive (`"ph_co2sys" -> "pH_CO2SYS"`).
      3. Alphanumeric-canonical (`"ph_co2sys" -> "pH co2 sys"` via
         stripping everything that is not a letter or digit).

    Returns None if no candidate matches. This is the core of canonical
    alias resolution (see `oa_schema.py`): every canonical column has a
    list of historical aliases, and we pick whichever one the workbook
    actually carries.
    """
    import re

    lower_map = {str(c).lower(): c for c in df.columns}
    canon = lambda s: re.sub(r"[^a-z0-9]+", "", str(s).lower())
    canon_map = {canon(c): c for c in df.columns}

    for cand in candidates:
        if cand in df.columns:
            return cand
        key = str(cand).lower()
        if key in lower_map:
            return lower_map[key]
        ckey = canon(cand)
        if ckey in canon_map:
            return canon_map[ckey]
    return None


def existing_columns(df: pd.DataFrame, candidates) -> list:
    """Return every name in `candidates` that resolves to a column in `df`.

    Like `first_existing` but returns the *full ordered list* of
    matches, not just the first one. Order is preserved from
    `candidates` (which is the precedence order for coalescing).
    Duplicates are dropped while preserving order.
    """
    lower_map = {str(c).lower(): c for c in df.columns}
    out = []
    for cand in candidates:
        if cand in df.columns:
            out.append(cand)
        else:
            key = str(cand).lower()
            if key in lower_map:
                out.append(lower_map[key])
    seen = set()
    unique = []
    for c in out:
        if c not in seen:
            unique.append(c)
            seen.add(c)
    return unique


# ---------------------------------------------------------------------------
# Typed empty Series (handy when building dataframes column-by-column)
# ---------------------------------------------------------------------------

def empty_float_series(index: pd.Index) -> pd.Series:
    """All-NA Float64 Series indexed like `index`."""
    return pd.Series(index=index, dtype="Float64")


def empty_string_series(index: pd.Index) -> pd.Series:
    """All-NA nullable-string Series indexed like `index`."""
    return pd.Series(pd.NA, index=index, dtype="string")


def empty_bool_series(index: pd.Index) -> pd.Series:
    """All-NA nullable-bool Series indexed like `index`."""
    return pd.Series(pd.NA, index=index, dtype="boolean")


def safe_upper(s: pd.Series) -> pd.Series:
    """Whitespace-stripped uppercased nullable-string view of `s`.

    Useful for normalising status / category text before equality
    comparisons (e.g. `safe_upper(s).eq("FAIL")`).
    """
    return safe_str_series(s).str.upper()


# ---------------------------------------------------------------------------
# Column coalescing (best-source picker with row-level provenance)
# ---------------------------------------------------------------------------

def coalesce_numeric_series(
    df: pd.DataFrame, cols: list
) -> tuple[pd.Series, pd.Series]:
    """SQL-style COALESCE across numeric columns, with per-row source.

    Walks `cols` in order. For each row, the output value is the first
    non-NA found across the candidate columns. The companion `source`
    Series records which column that value came from (NA if none).

    This is the workhorse of Stage 1B's "best-source" fields
    (`ta_best_umolkg`, `ph_best`, etc.): given the historical evolution
    of column names (`ta_corrected_umolkg` from QC -> `ta_umol_kg` from
    Stage 1A -> raw `ta`/`TA` from somewhere else), we pick the most
    trustworthy value per row and keep a row-level audit trail of where
    it came from.

    See: SQL `COALESCE(...)` and the PySpark `coalesce` function
    (https://spark.apache.org/docs/latest/api/python/...). The
    pandas equivalent for two columns is `s1.combine_first(s2)`, but it
    does not record provenance. The source-tracking layer here is what
    makes the operation auditable.
    """
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return empty_float_series(df.index), empty_string_series(df.index)

    vals = [pd.to_numeric(df[c], errors="coerce").astype("Float64") for c in cols]
    out = vals[0].copy()
    src = pd.Series(cols[0], index=df.index, dtype="string")

    for c, s in zip(cols[1:], vals[1:]):
        take = out.isna() & s.notna()
        out = out.where(~take, s)
        src = src.where(~take, c)

    # Wherever the final value is NA, the source should be NA too.
    src = src.where(out.notna(), pd.NA)
    return out, src


def coalesce_string_series(
    df: pd.DataFrame, cols: list
) -> tuple[pd.Series, pd.Series]:
    """COALESCE across string columns, with per-row source.

    Same logic as `coalesce_numeric_series` but for nullable-string
    columns. Empty strings are treated as NA before coalescing -- a
    common gotcha when reading CSVs where a missing value comes through
    as `""` rather than NaN.
    """
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return empty_string_series(df.index), empty_string_series(df.index)

    vals = [safe_str_series(df[c]).replace("", pd.NA) for c in cols]
    out = vals[0].copy()
    src = pd.Series(cols[0], index=df.index, dtype="string")

    for c, s in zip(cols[1:], vals[1:]):
        take = out.isna() & s.notna()
        out = out.where(~take, s)
        src = src.where(~take, c)

    src = src.where(out.notna(), pd.NA)
    return out.astype("string"), src


# ---------------------------------------------------------------------------
# Frequency table helper (for reports)
# ---------------------------------------------------------------------------

def value_counts_frame(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """value_counts() of `df[col]` as a tidy frame with count + pct.

    Used inside the Stage 1B report to print QC-status and best-source
    distributions. Returning a frame (rather than a Series) means
    `md_table_from_df` will render it cleanly.
    """
    vc = df[col].value_counts(dropna=False)
    out = vc.rename_axis(col).reset_index(name="count")
    total = out["count"].sum()
    out["pct"] = (out["count"] / total * 100.0).round(2) if total else 0.0
    return out


# ---------------------------------------------------------------------------
# Mixed I/O: write a frame to both CSV and Parquet
# ---------------------------------------------------------------------------

def write_csv_and_parquet(
    df: pd.DataFrame, csv_path: Path, parquet_path: Path
) -> tuple[bool, Optional[str]]:
    """Write `df` to both CSV (always) and Parquet (best-effort).

    Parquet write may fail if pyarrow / fastparquet are missing. We do
    not treat that as fatal -- CSV is still produced. Returns a
    `(parquet_ok, error_message_or_None)` tuple so the caller can log it.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    try:
        df.to_parquet(parquet_path, index=False)
        return True, None
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def md_table_from_df(df: pd.DataFrame, max_rows: int = 100) -> str:
    """Render a DataFrame as a Markdown table (falls back to code block).

    `to_markdown` requires the `tabulate` package; if it is not
    installed, we fall back to a monospaced code block so the report
    is still readable.
    """
    head = df.head(max_rows).copy()
    if head.empty:
        return "_(No rows)_"
    try:
        return head.to_markdown(index=False)
    except Exception:
        return "```\n" + head.to_string(index=False) + "\n```"


def build_flag_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Inventory every `flag_*` column in `df`: how many True, how many NA.

    Used in the per-stage markdown reports as a one-glance health check.
    """
    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    rows = []
    for c in flag_cols:
        rows.append(
            {
                "flag": c,
                "n_true": int((df[c] == True).sum()),  # noqa: E712
                "n_na": int(df[c].isna().sum()),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("n_true", ascending=False)


# ---------------------------------------------------------------------------
# Robust statistics for QC
# ---------------------------------------------------------------------------

def robust_outlier_flags(
    x: pd.Series,
    mad_k: float = 3.5,
    max_abs: Optional[float] = None,
) -> pd.Series:
    """Flag values as outliers using a median-absolute-deviation (MAD) rule.

    A point is an outlier if its distance from the median is more than
    `mad_k * 1.4826 * MAD`. The 1.4826 scaling makes this a consistent
    estimator of sigma under normality (Iglewicz & Hoaglin, 1993,
    "How to Detect and Handle Outliers", ASQC, vol. 16). MAD is preferred
    over (mean +/- k*sd) because it is not itself biased by the outliers
    you are trying to find.

    If `max_abs` is given, values whose absolute size exceeds `max_abs`
    are also flagged. Either rule alone (OR'd) flags the row.

    A degenerate MAD (NaN or 0) disables the MAD rule and leaves only the
    `max_abs` rule, so a column of identical values does not get flagged
    en masse.
    """
    xx = pd.to_numeric(x, errors="coerce")
    med = xx.median()
    mad = (xx - med).abs().median()

    if pd.isna(mad) or mad == 0:
        mad_rule = pd.Series(False, index=xx.index)
    else:
        sigma = 1.4826 * mad
        mad_rule = (xx - med).abs() > (mad_k * sigma)

    abs_rule = pd.Series(False, index=xx.index)
    if max_abs is not None:
        abs_rule = xx.abs() > float(max_abs)

    return mad_rule | abs_rule


def build_corrections_table(
    df_qc: pd.DataFrame,
    group_by: Optional[str],
    diff_col: str,
    min_n: int,
) -> pd.DataFrame:
    """Compute per-group (and overall) correction = mean(reference - measured).

    Used by both TA CRM QC and pH-standard QC. Outliers (rows where
    f"{diff_col}_is_outlier" is True) are excluded before averaging --
    that flag must already exist on `df_qc` (set it with
    `robust_outlier_flags` first).

    If `group_by` resolves to a real column, returns per-group N, mean,
    SD plus overall N / mean / SD as extra columns. Otherwise returns a
    one-row frame with just the overall stats. Groups with N < `min_n`
    have their `correction` blanked (kept in the table so the report
    can show why).
    """
    ok = df_qc.loc[~df_qc[f"{diff_col}_is_outlier"]].copy()
    overall_n = int(ok[diff_col].notna().sum())
    overall_mean = float(ok[diff_col].mean()) if overall_n > 0 else float("nan")
    overall_sd = float(ok[diff_col].std(ddof=1)) if overall_n > 1 else float("nan")

    if group_by and group_by in df_qc.columns:
        g = ok[[group_by, diff_col]].copy()
        g[diff_col] = pd.to_numeric(g[diff_col], errors="coerce")

        grp = (
            g.groupby(group_by, dropna=False)[diff_col]
            .agg(["count", "mean", "std"])
            .rename(columns={"count": "n", "mean": "correction", "std": "sd"})
            .reset_index()
        )
        grp["group_has_min_n"] = grp["n"] >= int(min_n)
        grp["correction"] = pd.to_numeric(grp["correction"], errors="coerce").astype("Float64")
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
