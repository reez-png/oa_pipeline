"""
stage2.py
=========
Stage 2 logic for the OA pipeline.

Stage 2 performs boundary checks, adds time and depth grouping helpers,
checks duplicate records, and harmonises replicate measurements. It is the
first stage that operates across rows rather than only within rows.

Import as:

    from oa_pipeline.stage2 import ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .common import die, first_existing
from .schema import DEFAULT_CONFIG

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


# =============================================================================
# Defaults
# =============================================================================

_SCHEMA_ALIASES: Dict[str, List[str]] = {
    key: list(value)
    for key, value in DEFAULT_CONFIG.get("canonical_candidates", {}).items()
}


STAGE2_DEFAULTS: Dict[str, Any] = {
    # Reuse the schema level aliases, then add Stage 1B best field aliases.
    # This reduces schema drift between Stage 1A, Stage 1B, and Stage 2.
    "canonical_aliases": {
        **_SCHEMA_ALIASES,
        "sample_date": ["sample_date", "sample_date_dt", "date", "datetime"],
        "ta_best_umolkg": [
            "ta_best_umolkg",
            "ta_corrected_umolkg",
            "ta_corrected",
            "ta_umol_kg",
            "ta_umolkg",
            "ta",
            "TA",
        ],
        "ph_best": [
            "ph_best",
            "ph_corrected_from_phstd",
            "pH_corrected_from_std",
            "ph_observed",
            "pH_lab",
            "ph_lab",
            "pH",
            "ph",
        ],
        "ph_co2sys": ["ph_co2sys", "ph_calculated", "pH_calc", "ph_calc"],
        "pco2_best_uatm": [
            "pco2_best_uatm",
            "pco2_calc_uatm",
            "pco2_uatm",
            "pCO2",
            "pco2",
        ],
        "dic_best_umol_kg": [
            "dic_best_umol_kg",
            "dic_calculated_umol_kg",
            "dic_measured_umol_kg",
            "dic_umol_kg",
            "dic_umolkg",
            "dic_calc",
            "DIC",
            "dic",
        ],
        "ta_units_normalized": [
            "ta_units_normalized",
            "ta_units",
            "ta_unit_selected",
            "ta_unit",
        ],
        "ph_scale_observed_normalized": [
            "ph_scale_observed_normalized",
            "ph_scale_observed",
            "pH_scale_observed",
            "ph_scale",
        ],
        "ph_scale_calculated_normalized": [
            "ph_scale_calculated_normalized",
            "ph_scale_calculated",
            "ph_scale_calc",
            "pH_scale_calc",
            "ph_calc_scale",
        ],
        "carbonate_solver": ["carbonate_solver"],
        "carbon_input_pair_used": ["carbon_input_pair_used"],
        "ta_best_source": ["ta_best_source"],
        "ph_best_source": ["ph_best_source"],
        "ph_co2sys_source": ["ph_co2sys_source"],
        "pco2_best_source": ["pco2_best_source"],
        "dic_best_source": ["dic_best_source"],
        "ta_qc_status": ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status": ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status": ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    # Truly required for Stage 2 duplicate and replicate operations.
    "required_stage2_columns": [
        "sample_id",
        "sample_date",
        "station_id",
        "depth_m",
        "ta_best_umolkg",
        "ph_best",
    ],
    # FIX 6-C: required_stage1b_columns was an identical copy of
    # required_stage2_columns with only a note saying "backward compatible".
    # Keeping two identical lists means a future update to one but not the
    # other silently creates inconsistent validation. Removed the duplicate;
    # code that referenced required_stage1b_columns should use
    # required_stage2_columns instead.
    "expected_stage2_columns": [
        "record_id",
        "cruise_id",
        "transect_id",
        "replicate_id",
        "salinity",
        "temperature_insitu_c",
        "temperature_measurement_c",
        "pressure_output_dbar",
        "ph_co2sys",
        "pco2_best_uatm",
        "dic_best_umol_kg",
        "ta_units_normalized",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
        "ta_best_source",
        "ph_best_source",
        "ph_co2sys_source",
        "pco2_best_source",
        "dic_best_source",
        "carbonate_solver",
        "carbon_input_pair_used",
    ],
    # Backward compatible name used in older notebook code.
    "expected_provenance_columns": [
        "record_id",
        "cruise_id",
        "transect_id",
        "replicate_id",
        "salinity",
        "temperature_insitu_c",
        "temperature_measurement_c",
        "pressure_output_dbar",
        "ph_co2sys",
        "pco2_best_uatm",
        "dic_best_umol_kg",
        "ta_units_normalized",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
        "ta_best_source",
        "ph_best_source",
        "ph_co2sys_source",
        "pco2_best_source",
        "dic_best_source",
        "carbonate_solver",
        "carbon_input_pair_used",
    ],
    "duplicate_keys": [
        "sample_id",
        "replicate_id",
        "sample_date",
        "station_id",
        "depth_m",
    ],
    # Group by day and depth bin, not exact timestamp, so near duplicate
    # analyses of the same bottle can harmonise together.
    "replicate_group_keys": [
        "cruise_id",
        "transect_id",
        "station_id",
        "sample_id",
        "depth_bin_m",
        "sample_day",
    ],
    "depth_bin_m": 1.0,
    # Current default uses nearest depth binning. Use "floor" in config if
    # samples should be grouped into lower edge depth bins instead.
    "depth_bin_method": "nearest",
    "replicate_mean_vars": [
        "ph_best",
        "ph_co2sys",
        "ta_best_umolkg",
        "pco2_best_uatm",
        "dic_best_umol_kg",
        "salinity",
        "temperature_measurement_c",
        "temperature_insitu_c",
        "pressure_measurement_dbar",
        "pressure_output_dbar",
        "oxygen_umol_l",
        "nitrate_nitrite_umol_l",
        "phosphate_umol_l",
        "silicate_umol_l",
        "chlorophyll",
    ],
    # Screening thresholds inspired by common ocean acidification data quality
    # objectives. These are replicate consistency flags, not formal measurement
    # uncertainty estimates.
    "replicate_sd_thresholds": {
        "ph_best": 0.02,
        "ph_co2sys": 0.02,
        "ta_best_umolkg": 10.0,
    },
    "replicate_consistency_check_columns": [
        "sample_id",
        "ta_best_source",
        "ph_best_source",
        "ph_co2sys_source",
        "pco2_best_source",
        "dic_best_source",
        "ta_qc_status",
        "ph_qc_status",
        "phstd_status",
        "ta_units_normalized",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
        "carbonate_solver",
        "carbon_input_pair_used",
        "cruise_id",
        "transect_id",
        "station_id",
        "sample_month",
        "sample_day",
        "depth_round_m",
        "depth_bin_m",
    ],
    "replicate_conflict_field_classes": {
        "source": [
            "ta_best_source",
            "ph_best_source",
            "ph_co2sys_source",
            "pco2_best_source",
            "dic_best_source",
        ],
        "qc": ["ta_qc_status", "ph_qc_status", "phstd_status"],
        "provenance": [
            "ta_units_normalized",
            "ph_scale_observed_normalized",
            "ph_scale_calculated_normalized",
            "carbonate_solver",
            "carbon_input_pair_used",
        ],
        "metadata": [
            "sample_id",
            "cruise_id",
            "transect_id",
            "station_id",
            "sample_month",
            "sample_day",
            "depth_round_m",
            "depth_bin_m",
        ],
    },
}


# =============================================================================
# Internal helpers
# =============================================================================


def _has_value(series: pd.Series) -> pd.Series:
    """Return True where values are not missing and not blank strings.

    FIX 1-A (stage2.py copy): Use text.notna() instead of series.notna() in
    the string branch — consistent with the fix applied to common.has_value_series.
    """
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        text = series.astype("string").str.strip()
        return text.notna() & text.ne("")
    return series.notna()


def _coalesce_columns_with_source(
    df: pd.DataFrame,
    candidates: List[str],
) -> tuple[pd.Series, pd.Series]:
    """Coalesce columns row wise and record the source column for each row."""
    if not candidates:
        return (
            pd.Series(pd.NA, index=df.index, dtype="object"),
            pd.Series(pd.NA, index=df.index, dtype="string"),
        )

    out = df[candidates[0]].copy()
    src = pd.Series(candidates[0], index=df.index, dtype="string")

    for col in candidates[1:]:
        take = ~_has_value(out) & _has_value(df[col])
        out = out.where(~take, df[col])
        src = src.where(~take, col)

    src = src.where(_has_value(out), pd.NA)
    return out, src




def _alias_conflict_count(df: pd.DataFrame, candidates: List[str]) -> int:
    """Count rows where candidate aliases contain conflicting non empty values.

    Stage 2 is intentionally permissive: it warns through notes and still uses
    precedence order rather than stopping. This supports reruns and partially
    processed files, while still exposing potential provenance ambiguity.
    """
    if len(candidates) < 2:
        return 0

    existing = [col for col in candidates if col in df.columns]
    if len(existing) < 2:
        return 0

    normalised = pd.DataFrame(index=df.index)

    for col in existing:
        normalised[col] = df[col].astype("string").str.strip()

    present = normalised.notna() & normalised.ne("")
    n_present = present.sum(axis=1)
    n_unique = normalised.where(present).nunique(axis=1, dropna=True)

    conflict = n_present.gt(1) & n_unique.gt(1)
    return int(conflict.sum())


def _normalise_for_conflict(series: pd.Series) -> pd.Series:
    """Normalise string like values before conflict comparisons."""
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        return series.astype("string").str.strip()
    return series


def _complete_key_mask(df: pd.DataFrame, keys: List[str]) -> pd.Series:
    """True where all key fields are present and non blank."""
    if not keys:
        return pd.Series(False, index=df.index)

    complete = pd.Series(True, index=df.index)
    for key in keys:
        if key not in df.columns:
            complete &= False
        else:
            complete &= _has_value(df[key])
    return complete.astype(bool)


# =============================================================================
# Output directory layout
# =============================================================================


def ensure_stage2_dirs(root: Path) -> Dict[str, Path]:
    """Create the canonical Stage 2 output folder structure."""
    root = Path(root)
    dirs = {
        "root": root,
        "data": root / "data",
        "tables": root / "tables",
        "reports": root / "reports",
        "logs": root / "logs",
    }

    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    return dirs


# =============================================================================
# Alias resolution and boundary checks
# =============================================================================


def materialize_canonical_aliases(
    df: pd.DataFrame,
    alias_map: Dict[str, List[str]],
    notes: List[str],
) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """Ensure canonical columns exist, filling empty values from aliases.

    If a canonical column already exists but is partly empty, Stage 2 still
    tries later aliases and fills only the missing cells.

    The resolved source tracks the original input column where possible.
    This prevents a column created earlier in this same function, for example
    pco2_calc_uatm copied from pCO2, from being reported as the true source
    for a later best field.
    """
    out = df.copy()
    resolved: Dict[str, Optional[str]] = {}

    # Track source lineage. Original input columns point to themselves.
    # Canonical columns created during this function point back to the
    # original column that supplied their first non missing value.
    lineage: Dict[str, str] = {col: col for col in out.columns}

    for canonical, aliases in alias_map.items():
        candidates: List[str] = []

        if canonical in out.columns:
            candidates.append(canonical)

        for alias in aliases:
            found = first_existing(out, [alias])
            if found is not None and found not in candidates:
                candidates.append(found)

        if not candidates:
            resolved[canonical] = None
            continue

        n_conflicts = _alias_conflict_count(out, candidates)
        if n_conflicts:
            notes.append(
                f"WARNING: canonical {canonical!r} had {n_conflicts} rows with "
                f"conflicting non empty alias values among {candidates}. "
                "Stage 2 used precedence order to coalesce."
            )

        values, sources = _coalesce_columns_with_source(out, candidates)
        out[canonical] = values

        source_nonmissing = sources.dropna()

        if not source_nonmissing.empty:
            immediate_source = str(source_nonmissing.iloc[0])
            original_source = lineage.get(immediate_source, immediate_source)
        else:
            immediate_source = candidates[0]
            original_source = lineage.get(immediate_source, immediate_source)

        resolved[canonical] = original_source
        lineage[canonical] = original_source

        if len(candidates) > 1:
            notes.append(
                f"Coalesced canonical {canonical!r} from candidates: {candidates}."
            )
        elif candidates[0] != canonical:
            notes.append(f"Copied {candidates[0]!r} to canonical {canonical!r}.")

    return out, resolved


def ensure_required_columns(df: pd.DataFrame, required: Sequence[str]) -> None:
    """Stop with a clear message if any required Stage 2 column is missing."""
    missing = [col for col in required if col not in df.columns]

    if missing:
        die(
            "Missing required Stage 2 columns: "
            + ", ".join(missing)
            + ". Use the Stage 1B analysis ready samples file or update the "
            "Stage 2 config if a column is genuinely not required."
        )


# =============================================================================
# Column and presence inventory
# =============================================================================


def make_column_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Return a one row per column inventory with examples and missingness."""
    n_rows = len(df)
    rows = []

    for col in df.columns:
        series = df[col]
        n_missing = int((~_has_value(series)).sum())
        non_missing = series[_has_value(series)]

        rows.append(
            {
                "column": col,
                "dtype": str(series.dtype),
                "n_missing": n_missing,
                "pct_missing": round(n_missing / n_rows * 100, 2) if n_rows else 0.0,
                "n_unique_nonnull": int(non_missing.nunique(dropna=True)) if len(non_missing) else 0,
                "example_nonnull": non_missing.iloc[0] if len(non_missing) else pd.NA,
            }
        )

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
    """Return presence and missingness for named required and expected columns."""
    rows = []
    seen: set[str] = set()

    for col in list(required) + [item for item in expected if item not in required]:
        if col in seen:
            continue
        seen.add(col)

        present = col in df.columns
        if present:
            non_missing = int(_has_value(df[col]).sum())
            pct_missing = round((1.0 - (non_missing / len(df))) * 100, 2) if len(df) else 100.0
        else:
            non_missing = 0
            pct_missing = 100.0

        rows.append(
            {
                "column": col,
                "required": col in required,
                "present": present,
                "non_missing": non_missing,
                "pct_missing": pct_missing,
            }
        )

    return pd.DataFrame(rows)


# =============================================================================
# Grouping helpers
# =============================================================================


def add_time_and_depth_keys(
    df: pd.DataFrame,
    notes: List[str],
    depth_round_decimals: int = 1,
    depth_bin_m: float = 1.0,
    depth_bin_method: str = "nearest",
) -> pd.DataFrame:
    """Add sample_month, sample_day, depth_round_m, and depth_bin_m.

    depth_bin_method controls how depth bins are assigned:
    "nearest" rounds to the nearest bin center, while "floor" assigns the lower
    bin edge.
    """
    out = df.copy()

    if "sample_date" in out.columns:
        out["sample_date"] = pd.to_datetime(out["sample_date"], errors="coerce", utc=True)
        sample_dt = out["sample_date"]

        if getattr(sample_dt.dt, "tz", None) is not None:
            sample_dt_for_period = sample_dt.dt.tz_convert("UTC").dt.tz_localize(None)
        else:
            sample_dt_for_period = sample_dt

        out["sample_month"] = sample_dt_for_period.dt.to_period("M").astype("string")
        out["sample_day"] = sample_dt_for_period.dt.date.astype("string")
        out.loc[out["sample_date"].isna(), "sample_day"] = pd.NA
    else:
        out["sample_date"] = pd.NaT
        out["sample_month"] = pd.Series(pd.NA, index=out.index, dtype="string")
        out["sample_day"] = pd.Series(pd.NA, index=out.index, dtype="string")
        notes.append("No sample_date column found. sample_date, sample_month, and sample_day set to missing.")

    if "depth_m" in out.columns:
        depth = pd.to_numeric(out["depth_m"], errors="coerce")
        out["depth_round_m"] = depth.round(depth_round_decimals)

        bin_size = float(depth_bin_m)
        if bin_size <= 0:
            die(f"depth_bin_m must be > 0, got {depth_bin_m}")

        method = str(depth_bin_method).strip().lower()

        if method == "nearest":
            out["depth_bin_m"] = (depth / bin_size).round().mul(bin_size)
        elif method == "floor":
            out["depth_bin_m"] = (depth // bin_size).mul(bin_size)
        else:
            die(f"Unknown depth_bin_method: {depth_bin_method!r}. Use 'nearest' or 'floor'.")
    else:
        out["depth_round_m"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
        out["depth_bin_m"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
        notes.append("No depth_m column found. depth_round_m and depth_bin_m set to missing.")

    return out


# =============================================================================
# Duplicate checks
# =============================================================================


def duplicate_check(
    df: pd.DataFrame,
    requested_keys: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Find duplicate key collisions only among rows with complete keys."""
    keys_used = [key for key in requested_keys if key in df.columns]

    if not keys_used:
        return pd.DataFrame(), pd.DataFrame(), []

    complete_key = _complete_key_mask(df, keys_used)
    dup_mask = pd.Series(False, index=df.index)

    if complete_key.any():
        dup_mask.loc[complete_key] = df.loc[complete_key].duplicated(
            subset=keys_used,
            keep=False,
        )

    dups = df.loc[dup_mask].sort_values(keys_used).copy()

    if dups.empty:
        return dups, pd.DataFrame(), keys_used

    metrics = [
        "ph_best",
        "ph_co2sys",
        "ta_best_umolkg",
        "pco2_best_uatm",
        "dic_best_umol_kg",
    ]

    rows = []

    for group_values, group in dups.groupby(keys_used, dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)

        row: dict[str, Any] = {key: value for key, value in zip(keys_used, group_values)}
        row["n_rows"] = len(group)

        for metric in metrics:
            if metric in group.columns:
                values = pd.to_numeric(group[metric], errors="coerce")
                row[f"{metric}_min"] = float(values.min()) if values.notna().any() else pd.NA
                row[f"{metric}_max"] = float(values.max()) if values.notna().any() else pd.NA
                row[f"{metric}_range"] = (
                    float(values.max() - values.min())
                    if values.notna().sum() >= 2
                    else pd.NA
                )

        rows.append(row)

    summary = (
        pd.DataFrame(rows)
        .sort_values(["n_rows"] + keys_used, ascending=[False] + [True] * len(keys_used))
        .reset_index(drop=True)
    )

    return dups, summary, keys_used


def add_duplicate_annotations(df: pd.DataFrame, keys_used: List[str]) -> pd.DataFrame:
    """Add duplicate flags only for rows with complete duplicate keys."""
    out = df.copy()

    out["flag_duplicate"] = pd.Series(False, index=out.index, dtype="boolean")
    out["duplicate_group_size"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["flag_duplicate_key_incomplete"] = pd.Series(False, index=out.index, dtype="boolean")

    if not keys_used:
        return out

    missing = [key for key in keys_used if key not in out.columns]
    if missing:
        die(f"Duplicate key columns are missing: {missing}")

    complete_key = _complete_key_mask(out, keys_used)
    out["flag_duplicate_key_incomplete"] = (~complete_key).astype("boolean")

    if not complete_key.any():
        return out

    group_sizes = (
        out.loc[complete_key]
        .groupby(keys_used, dropna=False)
        .size()
        .rename("duplicate_group_size_new")
        .reset_index()
    )

    out = out.merge(group_sizes, on=keys_used, how="left", sort=False)
    out["duplicate_group_size"] = pd.to_numeric(
        out["duplicate_group_size_new"],
        errors="coerce",
    ).astype("Int64")
    out.drop(columns=["duplicate_group_size_new"], inplace=True)

    complete_after_merge = _complete_key_mask(out, keys_used)
    out["flag_duplicate"] = (
        complete_after_merge & out["duplicate_group_size"].fillna(0).gt(1)
    ).astype("boolean")

    return out


# =============================================================================
# Replicate harmonisation
# =============================================================================


def _classify_field(field: str, class_map: Dict[str, List[str]]) -> str:
    """Bucket a column name into metadata, qc, provenance, source, or other."""
    for class_name, fields in class_map.items():
        if field in fields:
            return class_name
    return "other"


def _consistency_table(
    df: pd.DataFrame,
    group_keys: List[str],
    check_cols: List[str],
    class_map: Dict[str, List[str]],
) -> pd.DataFrame:
    """Return one row per field conflict within replicate groups."""
    cols = [col for col in check_cols if col in df.columns and col not in group_keys]

    if not cols:
        return pd.DataFrame()

    rows = []

    for group_values, group in df.groupby(group_keys, dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)

        key_part = dict(zip(group_keys, group_values))

        for col in cols:
            values = group[col].dropna()
            values_for_compare = _normalise_for_conflict(values)
            values_for_compare = values_for_compare[values_for_compare.notna()]

            if pd.api.types.is_string_dtype(values_for_compare) or values_for_compare.dtype == object:
                values_for_compare = values_for_compare[values_for_compare.astype("string").str.strip().ne("")]

            n_unique = int(values_for_compare.nunique(dropna=True))

            if n_unique > 1:
                row = dict(key_part)
                row["field"] = col
                row["conflict_class"] = _classify_field(col, class_map)
                row["n_rows_in_group"] = len(group)
                row["n_unique_nonnull"] = n_unique
                row["example_values"] = " | ".join(
                    values_for_compare.drop_duplicates().head(5).astype("string").tolist()
                )
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(group_keys + ["conflict_class", "field"])
        .reset_index(drop=True)
    )


def _add_group_conflict_flags(
    group_frame: pd.DataFrame,
    consistency_df: pd.DataFrame,
    disagree_df: pd.DataFrame,
    keys_used: List[str],
) -> pd.DataFrame:
    """Add conflict flags to a group level replicate frame."""
    out = group_frame.copy()
    flags = [
        "flag_replicate_metadata_conflict",
        "flag_replicate_provenance_conflict",
        "flag_replicate_qc_conflict",
        "flag_replicate_source_conflict",
        "flag_replicate_other_conflict",
        "flag_replicate_any_conflict",
        "flag_replicate_sd_exceeded",
    ]

    for flag in flags:
        out[flag] = False

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
            "metadata": "flag_replicate_metadata_conflict",
            "provenance": "flag_replicate_provenance_conflict",
            "qc": "flag_replicate_qc_conflict",
            "source": "flag_replicate_source_conflict",
            "other": "flag_replicate_other_conflict",
        }
        pivot = pivot.rename(columns=rename_map)
        # FIX 6-B: de-duplicate pivot keys before merging to prevent silent
        # row multiplication from unexpected duplicate consistency_df entries.
        pivot = pivot.drop_duplicates(subset=keys_used)
        _pre_merge_len_g = len(out)
        out = out.merge(pivot, on=keys_used, how="left", suffixes=("", "_new"), sort=False)
        if len(out) != _pre_merge_len_g:
            raise RuntimeError(
                f"_add_group_conflict_flags: row count changed from "
                f"{_pre_merge_len_g} to {len(out)} after conflict flag merge."
            )

        for flag in rename_map.values():
            new_col = f"{flag}_new"
            if new_col in out.columns:
                out[flag] = out[new_col].fillna(False).astype(bool)
                out.drop(columns=[new_col], inplace=True)

    if keys_used and not disagree_df.empty:
        bad_keys = disagree_df[keys_used].drop_duplicates().copy()
        bad_keys["flag_replicate_sd_exceeded_new"] = True
        out = out.merge(bad_keys, on=keys_used, how="left", sort=False)
        if "flag_replicate_sd_exceeded_new" in out.columns:
            out["flag_replicate_sd_exceeded"] = out["flag_replicate_sd_exceeded_new"].fillna(False).astype(bool)
            out.drop(columns=["flag_replicate_sd_exceeded_new"], inplace=True)

    out["flag_replicate_any_conflict"] = (
        out["flag_replicate_metadata_conflict"].fillna(False)
        | out["flag_replicate_provenance_conflict"].fillna(False)
        | out["flag_replicate_qc_conflict"].fillna(False)
        | out["flag_replicate_source_conflict"].fillna(False)
        | out["flag_replicate_other_conflict"].fillna(False)
    )

    for flag in flags:
        out[flag] = out[flag].fillna(False).astype("boolean")

    return out


def replicate_harmonise(
    df: pd.DataFrame,
    requested_keys: List[str],
    mean_whitelist: List[str],
    consistency_cols: List[str],
    sd_thresholds: Dict[str, float],
    conflict_class_map: Dict[str, List[str]],
) -> Tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    List[str],
    List[str],
    pd.DataFrame,
]:
    """Group rows into replicates and produce per group statistics."""
    work = df.copy()
    keys_used = [key for key in requested_keys if key in work.columns]

    if not keys_used:
        die(f"No replicate group keys found in columns. Requested: {requested_keys}")

    complete_group_key = _complete_key_mask(work, keys_used)

    if not complete_group_key.any():
        die("No rows have complete replicate group keys. Keys used: " + ", ".join(keys_used))

    work_groupable = work.loc[complete_group_key].copy()

    mean_vars: List[str] = []
    for col in mean_whitelist:
        if col not in work_groupable.columns:
            continue

        numeric = pd.to_numeric(work_groupable[col], errors="coerce")
        if numeric.notna().any():
            work_groupable[col] = numeric.astype("Float64")
            mean_vars.append(col)

    groupby = work_groupable.groupby(keys_used, dropna=False)
    nrep = groupby.size().rename("n_reps").reset_index()

    if mean_vars:
        means = groupby[mean_vars].mean().reset_index()
        sds = groupby[mean_vars].std(ddof=1).add_prefix("sd__").reset_index()
    else:
        means = nrep[keys_used].copy()
        sds = nrep[keys_used].copy()

    non_numeric_cols = [
        col
        for col in work_groupable.columns
        if col not in keys_used and col not in mean_vars
    ]

    # FIX 6-A: For provenance-critical columns (carbonate_solver,
    # carbon_input_pair_used, etc.) groupby.first() silently picks the first
    # non-NA value even when replicates within a group disagree on solver or
    # input pair. Stage 4's provenance audit then sees only one solver label
    # for a replicate group that may have used two different solvers.
    # Fix: store a semicolon-joined string of all unique non-null values for
    # provenance columns so conflicts are visible in the replicate mean output.
    _PROVENANCE_JOIN_COLS = {
        "carbonate_solver",
        "carbon_input_pair_used",
        "ta_units_normalized",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
    }

    provenance_cols = [
        col for col in non_numeric_cols if col in _PROVENANCE_JOIN_COLS
    ]
    plain_first_cols = [
        col for col in non_numeric_cols if col not in _PROVENANCE_JOIN_COLS
    ]

    def _join_unique(x: pd.Series) -> Any:
        unique = x.dropna().unique()
        if len(unique) == 0:
            return pd.NA
        if len(unique) == 1:
            return unique[0]
        return ";".join(str(v) for v in sorted(str(u) for u in unique))

    plain_first_values = (
        groupby[plain_first_cols].first().reset_index()
        if plain_first_cols
        else pd.DataFrame()
    )
    provenance_join_values = (
        groupby[provenance_cols].agg(_join_unique).reset_index()
        if provenance_cols
        else pd.DataFrame()
    )

    first_values_parts = [
        df for df in [plain_first_values, provenance_join_values]
        if not df.empty
    ]
    if first_values_parts:
        first_values = first_values_parts[0]
        for extra in first_values_parts[1:]:
            first_values = first_values.merge(extra, on=keys_used, how="left", sort=False)
    else:
        first_values = pd.DataFrame()

    rep_mean = means.copy()
    if not first_values.empty:
        rep_mean = rep_mean.merge(first_values, on=keys_used, how="left", sort=False)

    rep_mean = rep_mean.merge(nrep, on=keys_used, how="left", sort=False)

    rep_mean_sd = (
        rep_mean.merge(sds, on=keys_used, how="left", sort=False)
        if mean_vars
        else rep_mean.copy()
    )

    consistency_df = _consistency_table(
        work_groupable,
        keys_used,
        consistency_cols,
        conflict_class_map,
    )

    disagree_rows: List[dict] = []

    for metric, threshold in sd_thresholds.items():
        sd_col = f"sd__{metric}"

        if sd_col not in rep_mean_sd.columns or metric not in rep_mean_sd.columns:
            continue

        sd_values = pd.to_numeric(rep_mean_sd[sd_col], errors="coerce")
        bad = rep_mean_sd.loc[
            sd_values > float(threshold),
            keys_used + ["n_reps", metric, sd_col],
        ].copy()

        if bad.empty:
            continue

        bad = bad.rename(columns={metric: "mean_value", sd_col: "sd_value"})
        bad["metric"] = metric
        bad["threshold"] = float(threshold)
        disagree_rows.extend(bad.to_dict(orient="records"))

    disagree_df = pd.DataFrame(disagree_rows)

    if not disagree_df.empty:
        disagree_df = disagree_df.sort_values(
            ["metric", "sd_value"],
            ascending=[True, False],
        ).reset_index(drop=True)

    rep_mean = _add_group_conflict_flags(rep_mean, consistency_df, disagree_df, keys_used)
    rep_mean_sd = _add_group_conflict_flags(rep_mean_sd, consistency_df, disagree_df, keys_used)

    return rep_mean, rep_mean_sd, consistency_df, disagree_df, keys_used, mean_vars, nrep


# =============================================================================
# Replicate and conflict annotations
# =============================================================================


def add_replicate_annotations(
    df: pd.DataFrame,
    nrep: pd.DataFrame,
    keys_used: List[str],
) -> pd.DataFrame:
    """Add replicate group size and incomplete group key flags to row data."""
    out = df.copy()

    out["replicate_group_n"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["flag_has_replicates"] = pd.Series(False, index=out.index, dtype="boolean")
    out["flag_replicate_group_key_incomplete"] = pd.Series(True, index=out.index, dtype="boolean")

    if not keys_used:
        return out

    missing = [key for key in keys_used if key not in out.columns]
    if missing:
        die(f"Replicate group key columns are missing: {missing}")

    complete_key = _complete_key_mask(out, keys_used)
    out["flag_replicate_group_key_incomplete"] = (~complete_key).astype("boolean")

    if nrep.empty:
        return out

    merge_nrep = nrep[keys_used + ["n_reps"]].drop_duplicates().copy()
    out = out.merge(merge_nrep, on=keys_used, how="left", sort=False)

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
    """Add conflict and SD exceedance flags to row level data."""
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

    for col in flag_cols:
        out[col] = False

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
            "metadata": "flag_replicate_metadata_conflict",
            "provenance": "flag_replicate_provenance_conflict",
            "qc": "flag_replicate_qc_conflict",
            "source": "flag_replicate_source_conflict",
            "other": "flag_replicate_other_conflict",
        }
        pivot = pivot.rename(columns=rename_map)
        # FIX 6-B: de-duplicate pivot before merging to prevent silent row
        # multiplication when consistency_df has unexpected duplicate keys.
        pivot = pivot.drop_duplicates(subset=keys_used)
        _pre_merge_len_r = len(out)
        out = out.merge(pivot, on=keys_used, how="left", suffixes=("", "_new"), sort=False)
        if len(out) != _pre_merge_len_r:
            raise RuntimeError(
                f"add_conflict_annotations: row count changed from "
                f"{_pre_merge_len_r} to {len(out)} after conflict flag merge."
            )

        for col in rename_map.values():
            new_col = f"{col}_new"
            if new_col in out.columns:
                out[col] = out[new_col].fillna(False).astype("boolean")
                out.drop(columns=[new_col], inplace=True)
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
        bad_keys["flag_replicate_sd_exceeded_new"] = True
        out = out.merge(bad_keys, on=keys_used, how="left", sort=False)

        if "flag_replicate_sd_exceeded_new" in out.columns:
            out["flag_replicate_sd_exceeded"] = out[
                "flag_replicate_sd_exceeded_new"
            ].fillna(False).astype("boolean")
            out.drop(columns=["flag_replicate_sd_exceeded_new"], inplace=True)

    for col in flag_cols:
        out[col] = out[col].fillna(False).astype("boolean")

    return out
