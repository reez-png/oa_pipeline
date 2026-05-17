"""
oa_stage2.py
============
Stage 2-specific logic: re-resolve aliases (in case the input is not a
clean Stage 1B output), add grouping helpers (`sample_month`,
`depth_round_m`), detect duplicates, and harmonise replicates.

The new operation here is **replicate harmonisation** -- grouping rows
that represent the same physical sample (same station, depth bin,
sampling date) and computing per-group means + standard deviations for
a whitelisted set of numeric variables. The SD thresholds used to flag
"replicates disagree more than they should" match the GOA-ON "weather"
precision objectives:
  - pH:  +/- 0.02 (matches `replicate_sd_thresholds.ph_best`)
  - TA:  +/- 10 umol/kg (matches `replicate_sd_thresholds.ta_best_umolkg`)
See Newton et al. (2015), "Global Ocean Acidification Observing Network
Requirements and Governance Plan", §3.1.

Why this is its own module
--------------------------
Stage 2 is the first stage that operates *across rows* (rather than
within a single row). The grouping / aggregation / conflict-detection
logic is meaningfully different from the Stage 1A canonical schema and
the Stage 1B per-row coalescing, so it earns its own module.

What stays in oa_common.py
--------------------------
The generic helpers (`die`, `utc_stamp`, `write_json`, `write_text`,
`deep_update`, `coerce_numeric`, `coerce_datetime`, `ensure_dir`,
`make_missingness_table`, `first_existing`, etc.) were factored out in
earlier stages and just get imported here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from oa_common import die, ensure_dir, first_existing

__all__ = [
    "STAGE2_DEFAULTS",
    "ensure_stage2_dirs",
    "materialize_canonical_aliases",
    "ensure_required_columns",
    "make_column_inventory",
    "make_presence_table",
    "add_time_and_depth_keys",
    "duplicate_check",
    "add_duplicate_annotations",
    "replicate_harmonise",
    "add_replicate_annotations",
    "add_conflict_annotations",
]


# ===========================================================================
# STAGE2_DEFAULTS
# ===========================================================================
# Stage 2's config keys layered on top of the schema-wide DEFAULT_CONFIG.
# Aliases are re-listed here because Stage 2 is supposed to also work if
# a user feeds in a CSV that came from somewhere else (not Stage 1B);
# the alias resolution step gives it the chance to recover canonical
# names. If you DO feed it Stage 1B's output, alias resolution is a
# no-op (every canonical name is already there).
STAGE2_DEFAULTS: Dict[str, Any] = {
    "canonical_aliases": {
        "record_id":                    ["record_id", "sample_tag"],
        "sample_id":                    ["sample_id"],
        "cruise_id":                    ["cruise_id", "Cruise", "cruise"],
        "transect_id":                  ["transect_id", "Transect", "transect"],
        "station_id":                   ["station_id", "Station", "station"],
        "replicate_id":                 ["replicate_id", "replicate"],
        "sample_date":                  ["sample_date", "sample_date_dt", "date", "datetime"],
        "depth_m":                      ["depth_m", "Depth", "depth"],
        "salinity":                     ["salinity", "sal"],
        "temperature_measurement_c":    [
            "temperature_measurement_c", "temp_measurement_c",
            "temp_lab", "temperature_lab_c",
        ],
        "temperature_insitu_c":         [
            "temperature_insitu_c", "temperature_output_c",
            "temp_output_c", "temp_insitu",
        ],
        "pressure_measurement_dbar":    [
            "pressure_measurement_dbar", "pressure_lab_dbar",
            "sample_pressure_dbar",
        ],
        "pressure_output_dbar":         [
            "pressure_output_dbar", "pressure_insitu_dbar",
            "pressure_calc_dbar",
        ],
        "oxygen_umol_l":                ["oxygen_umol_l", "o2_umol/L", "o2_umol_l", "oxygen"],
        "nitrate_nitrite_umol_l":       [
            "nitrate_nitrite_umol_l", "no3_no2 uM/L",
            "no3_no2_umol_l", "nitrate_nitrite",
        ],
        "phosphate_umol_l":             ["phosphate_umol_l", "po4 uM/L", "po4_umol_l", "phosphate"],
        "silicate_umol_l":              ["silicate_umol_l", "sio3 uM/L", "sio3_umol_l", "silicate"],
        "chlorophyll":                  ["chlorophyll", "chl", "chla", "chlor_a"],
        "ta_best_umolkg":               [
            "ta_best_umolkg", "ta_umol_kg", "ta_corrected_umolkg",
            "ta_corrected", "ta", "TA",
        ],
        "ph_best":                      [
            "ph_best", "ph_observed", "ph_corrected_from_phstd",
            "pH_corrected_from_std", "pH_lab", "ph_lab", "pH", "ph",
        ],
        "ph_co2sys":                    ["ph_co2sys", "ph_calculated", "pH_calc", "ph_calc"],
        "pco2_best_uatm":               ["pco2_best_uatm", "pco2_calc_uatm", "pco2"],
        "dic_best_umol_kg":             ["dic_best_umol_kg", "dic_calculated_umol_kg", "dic_calc"],
        "sample_type":                  ["sample_type", "crm_or_sample"],
        "collection_mode":              ["collection_mode", "mode_of_collection"],
        "ta_units_normalized":          ["ta_units_normalized", "ta_units", "ta_unit_selected"],
        "ph_scale_observed_normalized": [
            "ph_scale_observed_normalized", "ph_scale_observed",
            "pH_scale_observed", "ph_scale",
        ],
        "ph_scale_calculated_normalized": [
            "ph_scale_calculated_normalized", "ph_scale_calculated",
            "ph_scale_calc", "pH_scale_calc", "ph_calc_scale",
        ],
        "carbonate_solver":             ["carbonate_solver"],
        "carbon_input_pair_used":       ["carbon_input_pair_used"],
        "ta_best_source":               ["ta_best_source"],
        "ph_best_source":               ["ph_best_source"],
        "ph_co2sys_source":             ["ph_co2sys_source"],
        "pco2_best_source":             ["pco2_best_source"],
        "dic_best_source":              ["dic_best_source"],
        "ta_qc_status":                 ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status":                 ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status":                 ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    "required_stage1b_columns": [
        "record_id", "sample_id", "sample_date", "station_id", "depth_m",
        "salinity", "temperature_insitu_c", "ta_best_umolkg", "ph_best",
        "ph_co2sys", "ta_units_normalized", "ph_scale_observed_normalized",
    ],
    "expected_provenance_columns": [
        "cruise_id", "transect_id", "replicate_id", "pressure_output_dbar",
        "pco2_best_uatm", "dic_best_umol_kg",
        "ta_best_source", "ph_best_source", "ph_co2sys_source",
        "pco2_best_source", "dic_best_source",
        "ph_scale_calculated_normalized", "carbonate_solver",
        "carbon_input_pair_used",
    ],
    "duplicate_keys": [
        "sample_id", "replicate_id", "sample_date", "station_id", "depth_m",
    ],
    "replicate_group_keys": [
        "cruise_id", "transect_id", "station_id", "depth_round_m", "sample_date",
    ],
    "replicate_mean_vars": [
        "ph_best", "ph_co2sys", "ta_best_umolkg",
        "pco2_best_uatm", "dic_best_umol_kg",
        "salinity",
        "temperature_measurement_c", "temperature_insitu_c",
        "pressure_measurement_dbar", "pressure_output_dbar",
        "oxygen_umol_l", "nitrate_nitrite_umol_l",
        "phosphate_umol_l", "silicate_umol_l", "chlorophyll",
    ],
    # Per-metric standard-deviation thresholds for replicate disagreement.
    # If the SD across a replicate group exceeds the threshold, the
    # group is flagged via `flag_replicate_sd_exceeded`.
    #
    # Defaults come from GOA-ON "weather" precision objectives:
    #   pH:  +/- 0.02 (matches both ph_best and ph_co2sys)
    #   TA:  +/- 10 umol/kg
    # See Newton et al. (2015), GOA-ON Requirements and Governance Plan
    # (https://www.goa-on.org/documents/general/GOA-ON_plan_print.pdf).
    "replicate_sd_thresholds": {
        "ph_best":         0.02,
        "ph_co2sys":       0.02,
        "ta_best_umolkg":  10.0,
    },
    "replicate_consistency_check_columns": [
        "record_id", "sample_id",
        "ta_best_source", "ph_best_source", "ph_co2sys_source",
        "pco2_best_source", "dic_best_source",
        "ta_qc_status", "ph_qc_status", "phstd_status",
        "ta_units_normalized",
        "ph_scale_observed_normalized", "ph_scale_calculated_normalized",
        "carbonate_solver", "carbon_input_pair_used",
        "cruise_id", "transect_id", "station_id", "sample_month",
        "depth_round_m",
    ],
    "replicate_conflict_field_classes": {
        "source": [
            "ta_best_source", "ph_best_source", "ph_co2sys_source",
            "pco2_best_source", "dic_best_source",
        ],
        "qc": [
            "ta_qc_status", "ph_qc_status", "phstd_status",
        ],
        "provenance": [
            "ta_units_normalized",
            "ph_scale_observed_normalized", "ph_scale_calculated_normalized",
            "carbonate_solver", "carbon_input_pair_used",
        ],
        "metadata": [
            "record_id", "sample_id", "cruise_id", "transect_id",
            "station_id", "sample_month", "depth_round_m",
        ],
    },
}


# ===========================================================================
# Output directory layout
# ===========================================================================

def ensure_stage2_dirs(root: Path) -> Dict[str, Path]:
    """Create the canonical Stage 2 output folder structure.

    Returns a dict mapping logical name ('data', 'tables', 'reports',
    'logs') to absolute Path. All directories are created up front, so
    every file-writing step can assume its directory exists.
    """
    dirs = {
        "root":    root,
        "data":    root / "data",
        "tables":  root / "tables",
        "reports": root / "reports",
        "logs":    root / "logs",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


# ===========================================================================
# Alias resolution / column hygiene (Stage 2 boundary check)
# ===========================================================================

def materialize_canonical_aliases(
    df: pd.DataFrame,
    alias_map: Dict[str, List[str]],
    notes: List[str],
) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """For each canonical name, ensure a column with that name exists.

    If the canonical name already exists, leave it alone. Otherwise, find
    the first matching alias from `alias_map[canonical]` and copy its
    values into a new column with the canonical name. Records every copy
    action in `notes` (a mutable list).

    Returns `(out_df, resolved_lookup)` where `resolved_lookup` maps
    canonical_name -> the source column actually used, or None if no
    alias matched.

    Why "copy" not "rename": Stage 2 may be fed by Stage 1B (in which case
    canonical names already exist) or by some external CSV (where they
    don't). Copying preserves the original columns so downstream code can
    still inspect them; renaming would lose that audit trail.
    """
    out = df.copy()
    resolved: Dict[str, Optional[str]] = {}

    for canonical, aliases in alias_map.items():
        found = first_existing(out, aliases)
        resolved[canonical] = found

        if canonical in out.columns:
            continue
        if found is not None:
            out[canonical] = out[found]
            if found != canonical:
                notes.append(f"Copied {found!r} to canonical {canonical!r}.")

    return out, resolved


def ensure_required_columns(df: pd.DataFrame, required: Sequence[str]) -> None:
    """Hard-stop with a clear message if any required column is missing.

    Stage 2 cannot do replicate grouping without `sample_date`,
    `station_id`, `depth_m`, etc. Failing fast here is preferable to
    silently producing groups of one.
    """
    missing = [c for c in required if c not in df.columns]
    if missing:
        die(
            "Missing required Stage 1B canonical columns: "
            + ", ".join(missing)
            + ". Use the Stage 1B analysis-ready-samples file or update the "
            "`required_stage1b_columns` config to remove them if they are "
            "genuinely not needed."
        )


# ===========================================================================
# Column / presence inventory
# ===========================================================================

def make_column_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-column inventory richer than `make_missingness_table`.

    Adds `n_unique_nonnull` and `example_nonnull` columns, which help
    spot-check what a column actually contains (the simpler
    `oa_common.make_missingness_table` only reports dtype and
    missingness counts).

    Sorted with the worst columns first so `.head()` shows you the
    problems immediately.
    """
    n = len(df)
    rows = []
    for c in df.columns:
        s = df[c]
        n_miss = int(s.isna().sum())
        nonnull = s.dropna()
        rows.append({
            "column": c,
            "dtype": str(s.dtype),
            "n_missing": n_miss,
            "pct_missing": round(n_miss / n * 100, 2) if n else 0.0,
            "n_unique_nonnull": int(nonnull.nunique(dropna=True)) if len(nonnull) else 0,
            "example_nonnull": nonnull.iloc[0] if len(nonnull) else pd.NA,
        })
    return (
        pd.DataFrame(rows)
        .sort_values(["pct_missing", "column"], ascending=[False, True])
        .reset_index(drop=True)
    )


def make_presence_table(
    df: pd.DataFrame,
    required: Sequence[str],
    expected: Sequence[str],
) -> pd.DataFrame:
    """Presence inventory for the *named* required + expected columns.

    Different from `make_column_inventory` (which lists every column);
    this one targets the schema-promise columns and tells you which of
    them are present, non-missing-count, and which are required vs
    merely expected. Useful as the "did Stage 1B give me what I need?"
    one-glance check.
    """
    rows = []
    seen: set = set()

    for col in list(required) + [c for c in expected if c not in required]:
        if col in seen:
            continue
        seen.add(col)
        present = col in df.columns
        rows.append({
            "column": col,
            "required": col in required,
            "present": present,
            "non_missing": int(df[col].notna().sum()) if present else 0,
            "pct_missing": round(float(df[col].isna().mean()) * 100, 2)
                           if present and len(df) else 100.0,
        })
    return pd.DataFrame(rows)


# ===========================================================================
# Grouping helpers
# ===========================================================================

def add_time_and_depth_keys(
    df: pd.DataFrame,
    notes: List[str],
    depth_round_decimals: int = 1,
) -> pd.DataFrame:
    """Add `sample_month` and `depth_round_m` (returned in a new frame).

    - `sample_month`: monthly period string ('2023-04') derived from
      `sample_date`. NA if no date.
    - `depth_round_m`: `depth_m` rounded to `depth_round_decimals`
      decimal places. NA if no depth.

    Both are used as Stage 2's replicate-grouping keys -- two profiles
    taken minutes apart at the same depth bin should aggregate together.

    Missing columns are tolerated (the new columns are created as
    all-NA) and a note is appended so the report explains it.
    """
    out = df.copy()

    if "sample_date" in out.columns:
        out["sample_date"] = pd.to_datetime(out["sample_date"], errors="coerce")
        out["sample_month"] = out["sample_date"].dt.to_period("M").astype("string")
    else:
        out["sample_date"] = pd.NaT
        out["sample_month"] = pd.Series(pd.NA, index=out.index, dtype="string")
        notes.append(
            "No sample_date column found. sample_date and sample_month set to missing."
        )

    if "depth_m" in out.columns:
        out["depth_round_m"] = pd.to_numeric(out["depth_m"], errors="coerce").round(
            depth_round_decimals
        )
    else:
        out["depth_round_m"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
        notes.append("No depth_m column found. depth_round_m set to missing.")

    return out


# ===========================================================================
# Duplicate checks
# ===========================================================================

def duplicate_check(
    df: pd.DataFrame,
    requested_keys: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Find duplicate-key collisions and summarise the spread in metrics.

    A "duplicate" here is any row whose `requested_keys` tuple matches at
    least one other row. The function returns three things:

    1. `dups`: every row in a duplicate group (sorted by keys for
       readability).
    2. `summary`: one row per duplicate *group*, with n_rows and
       min/max/range for each carbonate-chemistry metric. This is
       what an analyst actually looks at -- "OK so these two records
       agree to 0.01 in pH but differ by 30 umol/kg in TA, that's
       suspicious".
    3. `keys_used`: the subset of `requested_keys` that actually
       existed in `df`. Missing keys are silently dropped (the audit
       trail is in the manifest).
    """
    keys_used = [k for k in requested_keys if k in df.columns]
    if not keys_used:
        return pd.DataFrame(), pd.DataFrame(), []

    dup_mask = df.duplicated(subset=keys_used, keep=False)
    dups = df.loc[dup_mask].sort_values(keys_used).copy()
    if dups.empty:
        return dups, pd.DataFrame(), keys_used

    metrics = ["ph_best", "ph_co2sys", "ta_best_umolkg", "pco2_best_uatm", "dic_best_umol_kg"]
    rows = []
    for gvals, g in dups.groupby(keys_used, dropna=False):
        if not isinstance(gvals, tuple):
            gvals = (gvals,)
        row: dict = {k: v for k, v in zip(keys_used, gvals)}
        row["n_rows"] = len(g)

        for m in metrics:
            if m in g.columns:
                vals = pd.to_numeric(g[m], errors="coerce")
                row[f"{m}_min"] = float(vals.min()) if vals.notna().any() else pd.NA
                row[f"{m}_max"] = float(vals.max()) if vals.notna().any() else pd.NA
                row[f"{m}_range"] = (
                    float(vals.max() - vals.min()) if vals.notna().sum() >= 2 else pd.NA
                )
        rows.append(row)

    summary = (
        pd.DataFrame(rows)
        .sort_values(["n_rows"] + keys_used, ascending=[False] + [True] * len(keys_used))
    )
    return dups, summary, keys_used


def add_duplicate_annotations(df: pd.DataFrame, keys_used: List[str]) -> pd.DataFrame:
    """Add `flag_duplicate` and `duplicate_group_size` columns to `df`.

    `flag_duplicate` is True for any row whose key tuple appears more
    than once; `duplicate_group_size` is the count for that tuple.
    Returns a copy.
    """
    out = df.copy()
    if not keys_used:
        out["flag_duplicate"] = pd.Series(False, index=out.index, dtype="boolean")
        out["duplicate_group_size"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        return out

    grp = (
        out.groupby(keys_used, dropna=False)
        .size()
        .rename("duplicate_group_size")
        .reset_index()
    )
    out = out.merge(grp, on=keys_used, how="left")
    out["duplicate_group_size"] = pd.to_numeric(
        out["duplicate_group_size"], errors="coerce"
    ).astype("Int64")
    out["flag_duplicate"] = out["duplicate_group_size"].fillna(0).gt(1).astype("boolean")
    return out


# ===========================================================================
# Replicate harmonisation (the big one)
# ===========================================================================

def _classify_field(field: str, class_map: Dict[str, List[str]]) -> str:
    """Bucket a column name into the 'metadata' / 'qc' / 'provenance' / etc class."""
    for cls, fields in class_map.items():
        if field in fields:
            return cls
    return "other"


def _consistency_table(
    df: pd.DataFrame,
    group_keys: List[str],
    check_cols: List[str],
    class_map: Dict[str, List[str]],
) -> pd.DataFrame:
    """For each (group, check_col), record if values disagree across the group.

    A "conflict" is more than one non-null distinct value in the group
    for that column. Returns one row per conflict, with the keys, the
    conflicting field, the classification ("source" / "qc" /
    "provenance" / "metadata" / "other"), and a few example values.
    Empty frame if no conflicts.
    """
    cols = [c for c in check_cols if c in df.columns and c not in group_keys]
    if not cols:
        return pd.DataFrame()

    rows = []
    for gvals, g in df.groupby(group_keys, dropna=False):
        if not isinstance(gvals, tuple):
            gvals = (gvals,)
        key_part = dict(zip(group_keys, gvals))

        for c in cols:
            vals = g[c].dropna()
            n_unique = int(vals.nunique(dropna=True))
            if n_unique > 1:
                row = dict(key_part)
                row["field"] = c
                row["conflict_class"] = _classify_field(c, class_map)
                row["n_rows_in_group"] = len(g)
                row["n_unique_nonnull"] = n_unique
                row["example_values"] = " | ".join(
                    vals.astype("string").drop_duplicates().head(5).tolist()
                )
                rows.append(row)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(group_keys + ["conflict_class", "field"])
        .reset_index(drop=True)
    )


def replicate_harmonise(
    df: pd.DataFrame,
    requested_keys: List[str],
    mean_whitelist: List[str],
    consistency_cols: List[str],
    sd_thresholds: Dict[str, float],
    conflict_class_map: Dict[str, List[str]],
) -> Tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame,
    List[str], List[str], pd.DataFrame,
]:
    """Group rows into replicates and produce per-group statistics.

    Returns a 7-tuple:
      * `rep_mean`        : one row per replicate group, with the mean of
                            each whitelisted numeric variable + the
                            first non-null value of every other column.
      * `rep_mean_sd`     : `rep_mean` augmented with `sd__<var>`
                            columns (sample standard deviation, ddof=1).
      * `consistency_df`  : table of fields whose value varies across
                            rows in the same replicate group (from
                            `_consistency_table`).
      * `disagree_df`     : table of (group, metric) pairs where the SD
                            exceeds the threshold from `sd_thresholds`.
      * `keys_used`       : the subset of `requested_keys` that existed
                            in `df`.
      * `mean_vars`       : the subset of `mean_whitelist` that existed
                            in `df` AND was numeric.
      * `nrep`            : one row per group with the `n_reps` count
                            (used by `add_replicate_annotations`).

    Implementation notes:
      * Only whitelisted numerics are averaged. Other columns are taken
        as the *first* value in the group -- a common convention when
        aggregating environmental data with metadata columns. Conflicts
        in those columns are surfaced via `consistency_df`, not silently
        dropped.
      * Sample standard deviation uses ddof=1 (Bessel's correction);
        groups of size 1 produce NaN, which means the SD-threshold rule
        never flags solo rows.
      * SD thresholds default to GOA-ON "weather" precision objectives
        (Newton et al. 2015): pH +/- 0.02, TA +/- 10 umol/kg.
    """
    keys_used = [k for k in requested_keys if k in df.columns]
    if not keys_used:
        die(f"No replicate group keys found in columns. Requested: {requested_keys}")

    mean_vars = [
        c for c in mean_whitelist
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
    ]

    gb = df.groupby(keys_used, dropna=False)
    nrep = gb.size().rename("n_reps").reset_index()

    means = (
        gb[mean_vars].mean().reset_index()
        if mean_vars else nrep.copy()
    )
    sds = (
        gb[mean_vars].std(ddof=1).add_prefix("sd__").reset_index()
        if mean_vars else nrep[keys_used].copy()
    )

    nonnum = [c for c in df.columns if c not in keys_used and c not in mean_vars]
    first_vals = gb[nonnum].first().reset_index() if nonnum else pd.DataFrame()

    rep_mean = means.copy()
    if not first_vals.empty:
        rep_mean = rep_mean.merge(first_vals, on=keys_used, how="left")
    rep_mean = rep_mean.merge(nrep, on=keys_used, how="left")
    rep_mean_sd = rep_mean.merge(sds, on=keys_used, how="left") if mean_vars else rep_mean.copy()

    consistency_df = _consistency_table(df, keys_used, consistency_cols, conflict_class_map)

    # SD threshold check
    disagree_rows: List[dict] = []
    for metric, threshold in sd_thresholds.items():
        sd_col = f"sd__{metric}"
        if sd_col not in rep_mean_sd.columns:
            continue
        sd_vals = pd.to_numeric(rep_mean_sd[sd_col], errors="coerce")
        bad = rep_mean_sd.loc[sd_vals > threshold, keys_used + ["n_reps", metric, sd_col]].copy()
        if bad.empty:
            continue
        bad = bad.rename(columns={metric: "mean_value", sd_col: "sd_value"})
        bad["metric"] = metric
        bad["threshold"] = threshold
        disagree_rows.extend(bad.to_dict(orient="records"))

    disagree_df = pd.DataFrame(disagree_rows)
    if not disagree_df.empty:
        disagree_df = disagree_df.sort_values(
            ["metric", "sd_value"], ascending=[True, False]
        ).reset_index(drop=True)

    return rep_mean, rep_mean_sd, consistency_df, disagree_df, keys_used, mean_vars, nrep


def add_replicate_annotations(
    df: pd.DataFrame, nrep: pd.DataFrame, keys_used: List[str]
) -> pd.DataFrame:
    """In-place: add `replicate_group_n` and `flag_has_replicates`.

    Joins the per-group `n_reps` count back to the row-level frame so
    every row knows the size of its replicate group.
    """
    out = df.copy()
    if not keys_used:
        out["replicate_group_n"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        out["flag_has_replicates"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        return out

    out = out.merge(nrep, on=keys_used, how="left")
    out["n_reps"] = pd.to_numeric(out["n_reps"], errors="coerce").astype("Int64")
    out["replicate_group_n"] = out["n_reps"]
    out["flag_has_replicates"] = out["replicate_group_n"].fillna(0).gt(1).astype("boolean")
    return out


def add_conflict_annotations(
    df: pd.DataFrame,
    consistency_df: pd.DataFrame,
    disagree_df: pd.DataFrame,
    keys_used: List[str],
) -> pd.DataFrame:
    """In-place: add per-conflict-class boolean flags plus a roll-up.

    For each row, the flags indicate whether *its replicate group*
    contains a metadata / provenance / QC / source / other conflict
    (per `_consistency_table`), plus a `flag_replicate_sd_exceeded`
    that fires if any SD threshold was exceeded for that group.
    A summary `flag_replicate_any_conflict` is the OR of the five
    class flags.

    Note: these flags fire at the *group* level. If row A is in the
    same group as row B and only B has a conflicting metadata value,
    both A and B get `flag_replicate_metadata_conflict=True`. This is
    intentional -- the analyst should look at all members of a
    conflicting group, not just the one with the odd value.
    """
    out = df.copy()
    flag_cols = [
        "flag_replicate_metadata_conflict",
        "flag_replicate_provenance_conflict",
        "flag_replicate_qc_conflict",
        "flag_replicate_source_conflict",
        "flag_replicate_other_conflict",
        "flag_replicate_any_conflict",
        "flag_replicate_sd_exceeded",
    ]
    for c in flag_cols:
        out[c] = False

    if keys_used and not consistency_df.empty:
        pivot = (
            consistency_df.pivot_table(
                index=keys_used,
                columns="conflict_class",
                values="n_rows_in_group",
                aggfunc="count",
                fill_value=0,
            )
            .gt(0)
            .reset_index()
        )
        rename_map = {
            "metadata":   "flag_replicate_metadata_conflict",
            "provenance": "flag_replicate_provenance_conflict",
            "qc":         "flag_replicate_qc_conflict",
            "source":     "flag_replicate_source_conflict",
            "other":      "flag_replicate_other_conflict",
        }
        pivot = pivot.rename(columns=rename_map)
        out = out.merge(pivot, on=keys_used, how="left", suffixes=("", "_new"))

        for col in rename_map.values():
            new = f"{col}_new"
            if new in out.columns:
                out[col] = out[new].fillna(False).astype("boolean")
                out.drop(columns=[new], inplace=True)
            else:
                out[col] = out[col].fillna(False).astype("boolean")

        out["flag_replicate_any_conflict"] = (
            out["flag_replicate_metadata_conflict"].fillna(False)
            | out["flag_replicate_provenance_conflict"].fillna(False)
            | out["flag_replicate_qc_conflict"].fillna(False)
            | out["flag_replicate_source_conflict"].fillna(False)
            | out["flag_replicate_other_conflict"].fillna(False)
        ).astype("boolean")

    if keys_used and not disagree_df.empty:
        bad_keys = disagree_df[keys_used].drop_duplicates().copy()
        bad_keys["flag_replicate_sd_exceeded"] = True
        out = out.merge(bad_keys, on=keys_used, how="left", suffixes=("", "_new"))
        new = "flag_replicate_sd_exceeded_new"
        if new in out.columns:
            out["flag_replicate_sd_exceeded"] = out[new].fillna(False).astype("boolean")
            out.drop(columns=[new], inplace=True)

    # Final hygiene: all five flag columns should be boolean dtype with no NAs.
    for c in flag_cols:
        out[c] = out[c].fillna(False).astype("boolean")

    return out
