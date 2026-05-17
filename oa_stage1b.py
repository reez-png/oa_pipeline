"""
oa_stage1b.py
=============
Stage 1B-specific logic: build "best" analysis fields for each chemistry
variable, classify rows as samples / standards / CRMs, attach chemistry
provenance, and produce the analysis-ready subset.

What is "best-source coalescing"?
---------------------------------
A typical OA dataset has the same physical quantity (say, TA) recorded
under several historical column names: `ta_corrected_umolkg` from the QC
stage, `ta_umol_kg` from Stage 1A, raw `ta`/`TA` from the original
workbook, possibly a `ta_best_umolkg` written by some earlier batch. The
"best" value for a given row is the first non-NA we find walking that
list in precedence order. We also record *which column* the value came
from, so the lineage is auditable per row.

The pattern is SQL's `COALESCE(...)` (and PySpark's `coalesce(...)`)
plus a source-tracking layer. See
`oa_common.coalesce_numeric_series` / `coalesce_string_series` for the
mechanics; this module just composes them with the OA-specific
precedence lists from `oa_schema.DEFAULT_CONFIG` / a user config.

Why this is its own module
--------------------------
The "is_sample_row" classifier, the "safe_for_analysis_qc" vs
"safe_for_analysis_strict" split, and the chemistry-provenance defaults
are all Stage-1B-shaped and would clutter `oa_common.py`. They land
here, near each other, with a single import surface for the notebook.
The generic SQL-like building blocks (`coalesce_*`, `existing_columns`,
`safe_upper`) live in `oa_common.py` and may be used by other stages.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from oa_common import (
    coalesce_numeric_series,
    coalesce_string_series,
    coerce_datetime,
    empty_bool_series,
    empty_float_series,
    empty_string_series,
    existing_columns,
    first_existing,
    safe_str_series,
    safe_upper,
)
from oa_policy import RangePolicy
from oa_schema import normalize_ph_scale, normalize_ta_units

__all__ = [
    "STAGE1B_DEFAULTS",
    "build_numeric_candidates_for_stage1b",
    "add_status_normalizations",
    "add_best_analysis_fields",
    "classify_rows_sample",
    "add_provenance_fields",
    "validate_ta_units",
    "add_scale_flags",
    "add_presence_flags",
    "add_analysis_range_flags",
    "analysis_ready_subset",
    "provenance_counts_table",
]


# ===========================================================================
# Stage 1B config defaults
# ===========================================================================
# These are the keys Stage 1B uses on top of the schema-level config in
# `oa_schema.DEFAULT_CONFIG`. A user-supplied YAML/JSON config can
# override any of them. They live here (not in oa_schema.py) because
# they are precedence orders specific to the "build a best field"
# operation, not part of the canonical schema itself.
STAGE1B_DEFAULTS: Dict[str, Any] = {
    "ta_precedence": [
        "ta_umol_kg",          # canonical from Stage 1A
        "ta_best_umolkg",      # previous Stage 1B run, if rerunning
        "ta_corrected_umolkg", # from Notebook 02 QC
        "ta_corrected",
        "ta", "TA",
    ],
    "ph_precedence": [
        "ph_observed",                # canonical from Stage 1A
        "ph_best",                    # previous Stage 1B run
        "ph_corrected_from_phstd",    # from Notebook 02 QC
        "pH_corrected_from_std",
        "pH_lab", "ph_lab",
        "pH", "ph",
    ],
    # ph_calculated stays SEPARATE from ph_best on purpose: ph_best is
    # the observed measurement chain; ph_calculated is what comes out of
    # CO2SYS. We keep both visible so downstream code can compare them.
    "ph_co2sys_candidates": [
        "ph_calculated", "ph_co2sys", "pH_calc", "ph_calc",
    ],
    "pco2_precedence": [
        "pco2_calc_uatm", "pco2_best_uatm", "pco2",
    ],
    "dic_precedence": [
        "dic_calculated_umol_kg", "dic_best_umol_kg", "dic_calc",
    ],
    "status_candidates": {
        "ta_qc_status": ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status": ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status": ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    "ta_unit_candidates": [
        "ta_units_normalized", "ta_units", "ta_units_raw",
        "ta_unit", "TA_unit", "ta_corrected_unit", "ta_corrected_units",
    ],
    "ph_scale_observed_candidates": [
        "ph_scale_observed_normalized", "ph_scale_observed",
        "ph_scale_observed_raw", "pH_scale_observed", "ph_scale", "pH_scale",
    ],
    "ph_scale_calculated_candidates": [
        "ph_scale_calculated_normalized", "ph_scale_calculated",
        "ph_scale_calculated_raw", "ph_scale_calc", "pH_scale_calc",
        "ph_calc_scale", "pH_calc_scale",
    ],
    "analysis_policy": {
        # If True, a row whose ph_best came from the pH-std-corrected
        # source AND whose phstd_status was FAIL is *excluded* from
        # safe_for_analysis_qc. Default False -- the row is kept and
        # the FAIL diagnostic is exposed via `phstd_fail_diagnostic`.
        "phstd_fail_blocks_corrected_ph": False,
        # Source-column names that count as "the pH was corrected via
        # the pH standard". Used by the policy above.
        "corrected_ph_source_names": [
            "ph_corrected_from_phstd", "pH_corrected_from_std",
        ],
        # If True, `flag_pressure_output_dbar_missing` also blocks
        # safe_for_analysis_strict. Default False so pressure is just a
        # warning.
        "require_pressure_for_strict": False,
    },
    "provenance_defaults": {
        # NOTE: Stage 1B OVERWRITES Stage 1A's provenance_defaults for
        # the same column names -- by the time Stage 1B is done, the
        # preferred fields are the `_best` ones (which Stage 1A doesn't
        # produce). Downstream stages should follow these pointers.
        "carbonate_solver": "PyCO2SYS",
        "carbon_input_pair_used": "TA + pH_observed",
        "preferred_ta_for_analysis": "ta_best_umolkg",
        "preferred_ph_for_analysis": "ph_best",
        "preferred_pco2_for_analysis": "pco2_best_uatm",
        "preferred_dic_for_analysis": "dic_best_umol_kg",
    },
    "variable_roles": {
        "ta_role": "measured",
        "ph_observed_role": "measured",
        "ph_calculated_role": "derived",
        "pco2_role": "derived",
        "dic_role": "derived",
        "oxygen_role": "measured",
        "nitrate_nitrite_role": "measured",
        "phosphate_role": "measured",
        "silicate_role": "measured",
        "chlorophyll_role": "measured",
    },
}


# ===========================================================================
# Numeric coercion candidates (everything Stage 1B should treat as numeric)
# ===========================================================================

def build_numeric_candidates_for_stage1b(config: Dict[str, Any]) -> List[str]:
    """All column names Stage 1B should pre-cast to numeric.

    Pulls every precedence list out of `config` plus the standard
    environmental fields (depth, lat/lon, temperature, salinity,
    nutrients). Order doesn't matter, but duplicates are removed.
    """
    out: List[str] = []
    for key in [
        "ta_precedence", "ph_precedence", "ph_co2sys_candidates",
        "pco2_precedence", "dic_precedence",
    ]:
        out.extend(config.get(key, []))

    out.extend([
        "depth_m",
        "latitude_deg", "longitude_deg",
        "temperature_measurement_c", "temperature_insitu_c",
        "pressure_measurement_dbar", "pressure_output_dbar",
        "salinity",
        "oxygen_umol_l", "nitrate_nitrite_umol_l",
        "phosphate_umol_l", "silicate_umol_l",
        "chlorophyll",
    ])

    seen = set()
    unique = []
    for c in out:
        if c not in seen:
            unique.append(c)
            seen.add(c)
    return unique


# ===========================================================================
# QC status normalisation
# ===========================================================================

def add_status_normalizations(
    df: pd.DataFrame, config: Dict[str, Any]
) -> Dict[str, Optional[str]]:
    """In-place: for each `status_candidates` entry, add a normalised pair.

    For `ta_qc_status` (the canonical name), creates two columns:
      - `ta_qc_status`       : trimmed string of the source value (preserves case)
      - `ta_qc_status_norm`  : uppercase (for equality comparisons against
                                "FAIL", "PASS", etc.)

    Returns the per-status dict of which source column actually got used,
    for the manifest.
    """
    used: Dict[str, Optional[str]] = {}
    for out_col, candidates in config.get("status_candidates", {}).items():
        src_col = first_existing(df, candidates)
        used[out_col] = src_col
        if src_col:
            df[out_col] = safe_str_series(df[src_col]).replace("", pd.NA)
            df[f"{out_col}_norm"] = safe_upper(df[src_col]).replace("", pd.NA)
        else:
            df[out_col] = empty_string_series(df.index)
            df[f"{out_col}_norm"] = empty_string_series(df.index)
    return used


# ===========================================================================
# Best-source analysis fields
# ===========================================================================

def add_best_analysis_fields(
    df: pd.DataFrame, config: Dict[str, Any]
) -> Dict[str, Any]:
    """In-place: build `ta_best_umolkg`, `ph_best`, `ph_co2sys`, etc.

    For each variable family, resolves the precedence list against
    columns actually present in `df`, then coalesces. A companion
    `_source` column records which name each row's value came from.

    Returns a metadata dict (lists of columns actually used per
    precedence) for the manifest.
    """
    meta: Dict[str, Any] = {}

    # Normalise identifier columns to trimmed strings (NA-friendly).
    for c in [
        "record_id", "sample_id", "cruise_id", "transect_id",
        "station_id", "sample_type", "collection_mode", "replicate_id",
    ]:
        if c in df.columns:
            df[c] = safe_str_series(df[c]).replace("", pd.NA)

    # Sample date -> datetime, plus a sample_month convenience field.
    if "sample_date" in df.columns:
        coerce_datetime(df, "sample_date")
        if pd.api.types.is_datetime64_any_dtype(df["sample_date"]):
            df["sample_month"] = df["sample_date"].dt.to_period("M").astype("string")

    # TA
    ta_candidates = existing_columns(df, config.get("ta_precedence", []))
    df["ta_best_umolkg"], df["ta_best_source"] = coalesce_numeric_series(df, ta_candidates)
    meta["ta_precedence_used"] = ta_candidates

    # Observed pH
    ph_candidates = existing_columns(df, config.get("ph_precedence", []))
    df["ph_best"], df["ph_best_source"] = coalesce_numeric_series(df, ph_candidates)
    meta["ph_precedence_used"] = ph_candidates

    # Calculated pH (kept separate from ph_best on purpose).
    ph_co2sys_col = first_existing(df, config.get("ph_co2sys_candidates", []))
    meta["ph_co2sys_source"] = ph_co2sys_col
    if ph_co2sys_col:
        df["ph_co2sys"] = pd.to_numeric(df[ph_co2sys_col], errors="coerce").astype("Float64")
    else:
        df["ph_co2sys"] = empty_float_series(df.index)

    # pCO2 and DIC -- coalesce just like TA and pH.
    pco2_candidates = existing_columns(df, config.get("pco2_precedence", []))
    df["pco2_best_uatm"], df["pco2_best_source"] = coalesce_numeric_series(df, pco2_candidates)
    meta["pco2_precedence_used"] = pco2_candidates

    dic_candidates = existing_columns(df, config.get("dic_precedence", []))
    df["dic_best_umol_kg"], df["dic_best_source"] = coalesce_numeric_series(df, dic_candidates)
    meta["dic_precedence_used"] = dic_candidates

    return meta


# ===========================================================================
# Row classification (sample vs CRM vs standard)
# ===========================================================================

def classify_rows_sample(df: pd.DataFrame) -> pd.Series:
    """True for rows that should participate in environmental analysis.

    Three sources, in priority order:
      1. `sample_type` == "sample" (case-insensitive). The cleanest,
         comes from Stage 1A's alias resolution of `crm_or_sample`.
      2. Failing that, derive from the boolean QC flags
         `is_ta_crm_row` and `is_phstd_row` written by Notebook 02:
         a row is a sample iff it is *neither* a CRM nor a standard.

    Returns a non-null boolean Series; never raises.
    """
    if "sample_type" in df.columns:
        sample_type = safe_str_series(df["sample_type"]).str.lower()
        return sample_type.eq("sample")

    is_crm = (
        df["is_ta_crm_row"].fillna(False)
        if "is_ta_crm_row" in df.columns
        else pd.Series(False, index=df.index)
    )
    is_std = (
        df["is_phstd_row"].fillna(False)
        if "is_phstd_row" in df.columns
        else pd.Series(False, index=df.index)
    )
    return ~(is_crm | is_std)


# ===========================================================================
# Chemistry provenance + per-variable role flags
# ===========================================================================

def add_provenance_fields(
    df: pd.DataFrame, config: Dict[str, Any]
) -> Dict[str, Any]:
    """In-place: add unit/scale provenance and per-variable role columns."""
    meta: Dict[str, Any] = {}

    df["is_sample_row"] = classify_rows_sample(df)

    # TA units -- coalesce candidates, then normalise to "umol kg-1" form.
    ta_units_cols = existing_columns(df, config.get("ta_unit_candidates", []))
    ta_units_raw, ta_units_source = coalesce_string_series(df, ta_units_cols)
    df["ta_units_normalized"] = ta_units_raw.map(normalize_ta_units)
    df["ta_units_source"] = ta_units_source

    # Observed pH scale -- coalesce, then map to total/free/seawater/nbs.
    ph_scale_obs_cols = existing_columns(df, config.get("ph_scale_observed_candidates", []))
    ph_scale_obs_raw, ph_scale_obs_source = coalesce_string_series(df, ph_scale_obs_cols)
    df["ph_scale_observed_normalized"] = ph_scale_obs_raw.map(normalize_ph_scale)
    df["ph_scale_observed_source"] = ph_scale_obs_source

    # Calculated pH scale -- same.
    ph_scale_calc_cols = existing_columns(df, config.get("ph_scale_calculated_candidates", []))
    ph_scale_calc_raw, ph_scale_calc_source = coalesce_string_series(df, ph_scale_calc_cols)
    df["ph_scale_calculated_normalized"] = ph_scale_calc_raw.map(normalize_ph_scale)
    df["ph_scale_calculated_source"] = ph_scale_calc_source

    # Provenance defaults overwrite Stage 1A's. Intentional: by Stage 1B
    # the preferred fields are the `_best` ones.
    defaults = config.get("provenance_defaults", {})
    for col, value in defaults.items():
        df[col] = value

    # Carbonate-system input columns: T, S, P (output pressure).
    df["calc_temperature_c"] = empty_float_series(df.index)
    if "temperature_insitu_c" in df.columns:
        df["calc_temperature_c"] = pd.to_numeric(
            df["temperature_insitu_c"], errors="coerce"
        ).astype("Float64")
    if "temperature_measurement_c" in df.columns:
        take = df["calc_temperature_c"].isna() & df["temperature_measurement_c"].notna()
        df.loc[take, "calc_temperature_c"] = pd.to_numeric(
            df.loc[take, "temperature_measurement_c"], errors="coerce"
        )

    df["calc_salinity"] = (
        pd.to_numeric(df["salinity"], errors="coerce").astype("Float64")
        if "salinity" in df.columns
        else empty_float_series(df.index)
    )
    df["calc_pressure_dbar"] = (
        pd.to_numeric(df["pressure_output_dbar"], errors="coerce").astype("Float64")
        if "pressure_output_dbar" in df.columns
        else empty_float_series(df.index)
    )

    # Per-variable role flag: "measured" if data exists, else NA. This
    # is what lets downstream stages tell at a glance whether they have
    # an observed pH (measured) or only a CO2SYS-derived pH (derived).
    roles = config.get("variable_roles", {})
    role_specs = [
        ("ta_role", "ta_best_umolkg", "measured"),
        ("ph_observed_role", "ph_best", "measured"),
        ("ph_calculated_role", "ph_co2sys", "derived"),
        ("pco2_role", "pco2_best_uatm", "derived"),
        ("dic_role", "dic_best_umol_kg", "derived"),
        ("oxygen_role", "oxygen_umol_l", "measured"),
        ("nitrate_nitrite_role", "nitrate_nitrite_umol_l", "measured"),
        ("phosphate_role", "phosphate_umol_l", "measured"),
        ("silicate_role", "silicate_umol_l", "measured"),
        ("chlorophyll_role", "chlorophyll", "measured"),
    ]
    for role_col, value_col, default_role in role_specs:
        chosen_role = roles.get(role_col, default_role)
        if value_col in df.columns and df[value_col].notna().any():
            df[role_col] = chosen_role
        else:
            df[role_col] = pd.NA

    meta["carbonate_solver"] = defaults.get("carbonate_solver")
    meta["carbon_input_pair_used"] = defaults.get("carbon_input_pair_used")
    return meta


# ===========================================================================
# TA / pH-scale / presence / range flags
# ===========================================================================

def validate_ta_units(df: pd.DataFrame) -> Dict[str, Any]:
    """In-place: add TA-units presence and unexpected-value flags.

    Returns a dict summarising unexpected unit values for the manifest.
    """
    df["flag_ta_units_missing"] = (
        df["ta_best_umolkg"].notna() & df["ta_units_normalized"].isna()
    )
    df["flag_ta_units_unexpected"] = (
        df["ta_best_umolkg"].notna()
        & df["ta_units_normalized"].notna()
        & ~df["ta_units_normalized"].eq("umol kg-1")
    )
    return {
        "unexpected_ta_units": (
            df.loc[df["flag_ta_units_unexpected"], "ta_units_normalized"]
            .value_counts(dropna=False)
            .to_dict()
        ),
    }


def add_scale_flags(df: pd.DataFrame) -> None:
    """In-place: pH-scale presence flags for both observed and calculated pH."""
    df["flag_ph_scale_observed_missing"] = (
        df["ph_best"].notna() & df["ph_scale_observed_normalized"].isna()
    )
    df["flag_ph_scale_calculated_missing"] = (
        df["ph_co2sys"].notna() & df["ph_scale_calculated_normalized"].isna()
    )


def add_presence_flags(df: pd.DataFrame) -> None:
    """In-place: presence flags scoped to *sample rows only*.

    `flag_core_chemistry_missing` is True for a sample row that lacks
    any of the four CO2SYS-input ingredients (TA, observed pH, salinity,
    in-situ temperature). CRMs and standards are not penalised here
    because they are not meant to have full environmental context.

    `flag_pressure_output_dbar_missing` is True for a sample row that
    has both TA and pH but no pressure -- flagging not blocking
    (see `analysis_policy.require_pressure_for_strict`).
    """
    is_sample = df["is_sample_row"].fillna(False)

    sal_missing = (
        df["salinity"].isna()
        if "salinity" in df.columns
        else pd.Series(True, index=df.index)
    )
    temp_missing = (
        df["temperature_insitu_c"].isna()
        if "temperature_insitu_c" in df.columns
        else pd.Series(True, index=df.index)
    )

    df["flag_core_chemistry_missing"] = (
        is_sample
        & (
            df["ta_best_umolkg"].isna()
            | df["ph_best"].isna()
            | sal_missing
            | temp_missing
        )
    )

    pressure_missing = (
        df["pressure_output_dbar"].isna()
        if "pressure_output_dbar" in df.columns
        else pd.Series(True, index=df.index)
    )
    df["flag_pressure_output_dbar_missing"] = (
        is_sample
        & df["ta_best_umolkg"].notna()
        & df["ph_best"].notna()
        & pressure_missing
    )


def add_analysis_range_flags(df: pd.DataFrame, policy: RangePolicy) -> None:
    """In-place: range flags for the BEST analysis fields, plus geographics.

    Stage 1B's flags are computed on `ta_best_umolkg` and `ph_best`,
    not on the original `ta_umol_kg` / `ph_observed` Stage 1A used.
    The Stage 1A flags survive on the staged frame; these supersede
    them for downstream consumers.
    """
    def _range_flag(series: pd.Series, low: float, high: float) -> pd.Series:
        num = pd.to_numeric(series, errors="coerce")
        return (~num.between(low, high) & num.notna()).astype("boolean")

    range_specs = [
        ("flag_lat_out_of_range",       "latitude_deg",    policy.lat_min,   policy.lat_max),
        ("flag_lon_out_of_range",       "longitude_deg",   policy.lon_min,   policy.lon_max),
        ("flag_sal_out_of_range",       "salinity",        policy.sal_min,   policy.sal_max),
        ("flag_depth_out_of_range",     "depth_m",         policy.depth_min, policy.depth_max),
        ("flag_ta_out_of_range",        "ta_best_umolkg",  policy.ta_min,    policy.ta_max),
        ("flag_ph_out_of_range",        "ph_best",         policy.ph_min,    policy.ph_max),
        ("flag_ph_co2sys_out_of_range", "ph_co2sys",       policy.ph_min,    policy.ph_max),
    ]
    for flag_col, val_col, lo, hi in range_specs:
        if val_col in df.columns:
            df[flag_col] = _range_flag(df[val_col], lo, hi)
        else:
            df[flag_col] = empty_bool_series(df.index)


# ===========================================================================
# Analysis-ready subset (sample rows + two QC gates)
# ===========================================================================

def analysis_ready_subset(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Return the sample-only subset with two analysis gates.

    Output frame is `df.loc[is_sample_row]` with two new boolean
    columns:

    - `safe_for_analysis_qc`: True unless the row has a FAIL in
      `ta_qc_status_norm` or `ph_qc_status_norm`. Optionally also
      excludes rows whose `ph_best` was sourced from a pH-std-corrected
      column AND whose `phstd_status` was FAIL (controlled by the
      `phstd_fail_blocks_corrected_ph` policy).

    - `safe_for_analysis_strict`: stricter version. Requires
      `safe_for_analysis_qc` AND no range / units / scale / core-missing
      flags. Optionally also requires pressure
      (`require_pressure_for_strict`).

    Two diagnostic columns are added regardless: `phstd_fail_diagnostic`
    and `ph_best_from_corrected`. These let an analyst inspect the
    rationale even when the policy chose not to block.
    """
    out = df.loc[df["is_sample_row"] == True].copy()  # noqa: E712

    # Start permissive, then tighten.
    safe_qc = pd.Series(True, index=out.index)

    if "ta_qc_status_norm" in out.columns:
        safe_qc &= ~safe_upper(out["ta_qc_status_norm"]).eq("FAIL")
    if "ph_qc_status_norm" in out.columns:
        safe_qc &= ~safe_upper(out["ph_qc_status_norm"]).eq("FAIL")

    phstd_fail = pd.Series(False, index=out.index)
    if "phstd_status_norm" in out.columns:
        phstd_fail = safe_upper(out["phstd_status_norm"]).eq("FAIL")

    corrected_sources = set(
        config.get("analysis_policy", {}).get("corrected_ph_source_names", [])
    )
    ph_best_from_corrected = (
        out["ph_best_source"].isin(corrected_sources)
        if "ph_best_source" in out.columns
        else pd.Series(False, index=out.index)
    )

    # Diagnostics always exposed.
    out["phstd_fail_diagnostic"] = phstd_fail
    out["ph_best_from_corrected"] = ph_best_from_corrected

    # Optional: phstd_fail blocks corrected pH rows.
    if bool(config.get("analysis_policy", {}).get("phstd_fail_blocks_corrected_ph", False)):
        safe_qc &= ~(phstd_fail & ph_best_from_corrected)

    out["safe_for_analysis_qc"] = safe_qc

    # safe_for_analysis_strict layers on the per-row flags.
    strict = safe_qc.copy()
    for c in [
        "flag_lat_out_of_range",
        "flag_lon_out_of_range",
        "flag_sal_out_of_range",
        "flag_depth_out_of_range",
        "flag_ta_out_of_range",
        "flag_ph_out_of_range",
        "flag_ta_units_missing",
        "flag_ta_units_unexpected",
        "flag_ph_scale_observed_missing",
        "flag_core_chemistry_missing",
    ]:
        if c in out.columns:
            strict &= ~(out[c] == True)  # noqa: E712

    if bool(config.get("analysis_policy", {}).get("require_pressure_for_strict", False)):
        if "flag_pressure_output_dbar_missing" in out.columns:
            strict &= ~(out["flag_pressure_output_dbar_missing"] == True)  # noqa: E712

    out["safe_for_analysis_strict"] = strict
    return out


# ===========================================================================
# Report helper (used by the notebook)
# ===========================================================================

def provenance_counts_table(df: pd.DataFrame) -> pd.DataFrame:
    """Tidy "did each provenance field get populated?" summary for the report."""
    from oa_common import percent_missing

    specs = [
        ("ta_best_umolkg", "Best TA"),
        ("ph_best", "Best observed pH"),
        ("ph_co2sys", "Calculated pH"),
        ("pco2_best_uatm", "Best pCO2"),
        ("dic_best_umol_kg", "Best DIC"),
        ("ta_units_normalized", "TA units"),
        ("ph_scale_observed_normalized", "Observed pH scale"),
        ("ph_scale_calculated_normalized", "Calculated pH scale"),
        ("pressure_output_dbar", "Output pressure"),
    ]
    rows = []
    for col, label in specs:
        if col in df.columns:
            rows.append({
                "field": label,
                "non_missing": int(df[col].notna().sum()),
                "pct_missing": round(percent_missing(df[col]), 2),
            })
    return pd.DataFrame(rows)
