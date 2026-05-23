"""
stage1b.py
==========
Stage 1B logic for the OA pipeline.

This module builds best available analysis fields, classifies rows as samples
or non samples, attaches provenance needed by downstream stages, and creates
sample level analysis gates.

Import as:

    from oa_pipeline.stage1b import ...

Stage 1B prepares analysis inputs. It does not run PyCO2SYS and therefore does
not invent carbonate solver provenance. Existing solver metadata is preserved
when present, and missing solver metadata remains missing unless the user
explicitly supplies a real default in configuration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .common import (
    coalesce_numeric_series,
    coalesce_string_series,
    coerce_datetime,
    empty_float_series,
    empty_string_series,
    existing_columns,
    first_existing,
    percent_missing,
    safe_str_series,
    safe_upper,
)
from .policy import RangePolicy
from .schema import normalize_ph_scale, normalize_ta_units

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


# =============================================================================
# Stage 1B config defaults
# =============================================================================

STAGE1B_DEFAULTS: Dict[str, Any] = {
    # Fresh QC corrected values are intentionally preferred over previous
    # Stage 1B best fields. Previous best fields are kept last only to support
    # deliberate reruns from an already processed file.
    "ta_precedence": [
        "ta_corrected_umolkg",
        "ta_corrected",
        "ta_umol_kg",
        "ta_umolkg",
        "ta",
        "TA",
        "ta_best_umolkg",
    ],
    # ph_after_phstd_qc is created inside add_best_analysis_fields. It carries
    # either true pH standard corrected pH or the original pH fallback from the
    # QC module, with row level source status preserved separately.
    "ph_precedence": [
        "ph_after_phstd_qc",
        "ph_corrected_from_phstd",
        "pH_corrected_from_std",
        "ph_observed",
        "pH_lab",
        "ph_lab",
        "pH",
        "ph",
        "ph_best",
    ],
    # Calculated pH remains separate from observed pH.
    "ph_co2sys_candidates": [
        "ph_calculated",
        "ph_co2sys",
        "pH_calc",
        "ph_calc",
    ],
    "pco2_precedence": [
        "pco2_calc_uatm",
        "pco2_uatm",
        "pCO2",
        "pco2",
        "pco2_best_uatm",
    ],
    "dic_precedence": [
        "dic_calculated_umol_kg",
        "dic_measured_umol_kg",
        "dic_umol_kg",
        "dic_umolkg",
        "dic_calc",
        "DIC",
        "dic",
        "dic_best_umol_kg",
    ],
    "status_candidates": {
        "ta_qc_status": ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status": ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status": ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    "ta_unit_candidates": [
        "ta_units_normalized",
        "ta_units",
        "ta_units_raw",
        "ta_unit",
        "TA_unit",
        "ta_corrected_unit",
        "ta_corrected_units",
    ],
    "ph_scale_observed_candidates": [
        "ph_scale_observed_normalized",
        "ph_scale_observed",
        "ph_scale_observed_raw",
        "pH_scale_observed",
        "ph_scale",
        "pH_scale",
    ],
    "ph_scale_calculated_candidates": [
        "ph_scale_calculated_normalized",
        "ph_scale_calculated",
        "ph_scale_calculated_raw",
        "ph_scale_calc",
        "pH_scale_calc",
        "ph_calc_scale",
        "pH_calc_scale",
    ],
    "analysis_policy": {
        # Conservative default: TA QC status is required. pH QC status is not
        # required by default because pH QC may be represented by phstd_status
        # and row level pH fallback provenance.
        "missing_qc_status_blocks_analysis": True,
        "required_qc_status_norm_columns": [
            "ta_qc_status_norm",
        ],
        # Status values allowed to pass the QC gate. Blank or missing values
        # are handled separately by missing_qc_status_blocks_analysis.
        "allowed_qc_status_for_analysis": [
            "PASS",
            "OK",
            "NO_ADJUST",
            "ADJUST",
        ],
        # If True, rows whose pH best value was truly pH standard corrected are
        # blocked when phstd_status is FAIL. Original pH fallback rows are not
        # treated as corrected pH.
        "phstd_fail_blocks_corrected_ph": False,
        "corrected_ph_status_source_names": [
            "phstd_corrected",
        ],
        # Kept for backward compatibility with older configs and reports.
        "corrected_ph_source_names": [
            "ph_corrected_from_phstd",
            "pH_corrected_from_std",
        ],
        # If True, require pressure_output_dbar for strict gate.
        "require_pressure_for_strict": False,
        # If True, using temperature_measurement_c as calc temperature blocks
        # strict analysis. Default False because some datasets may intentionally
        # use measurement temperature before later carbonate processing.
        "measurement_temperature_blocks_strict": False,
        "accepted_ph_scale_observed": ["total"],
    },
    "provenance_defaults": {
        # Stage 1B preserves existing carbonate solver and input pair provenance.
        # It does not invent solver metadata when those columns are absent.
        "carbonate_solver": pd.NA,
        "carbon_input_pair_used": pd.NA,
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


# =============================================================================
# Internal helpers
# =============================================================================


def _has_value(s: pd.Series) -> pd.Series:
    """Return True where a Series has a non missing and non blank value."""
    if pd.api.types.is_string_dtype(s) or s.dtype == object:
        text = s.astype("string").str.strip()
        return s.notna() & text.ne("").fillna(False)
    return s.notna()


def _scalar_default_has_value(value: Any) -> bool:
    """Return True when a scalar config default is usable for filling blanks."""
    if value is None or value is pd.NA:
        return False

    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


def _bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    """Return a clean bool Series from a possibly absent or nullable column."""
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)

    s = df[col]
    if str(s.dtype) == "boolean":
        return s.fillna(default).astype(bool)
    if s.dtype == bool:
        return s.fillna(default)

    text = s.astype("string").str.strip().str.upper()
    true_values = {"TRUE", "T", "YES", "Y", "1"}
    false_values = {"FALSE", "F", "NO", "N", "0", "", "NONE", "NULL", "<NA>", "NAN"}
    parsed = text.map(
        lambda value: (
            True
            if value in true_values
            else False
            if value in false_values
            else default
        )
    )
    return parsed.astype(bool)


def _range_flags(
    series: pd.Series,
    low: float,
    high: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return missing, non numeric, and out of range flags."""
    text = series.astype("string").str.strip()
    missing = (series.isna() | text.isna() | text.eq("")).astype("boolean")

    num = pd.to_numeric(series, errors="coerce")
    non_numeric = (~missing.fillna(False) & num.isna()).astype("boolean")
    out_of_range = (
        num.notna() & ~num.between(low, high, inclusive="both")
    ).astype("boolean")

    return missing, non_numeric, out_of_range


def _add_range_triplet(
    df: pd.DataFrame,
    value_col: str,
    missing_flag: str,
    non_numeric_flag: str,
    out_of_range_flag: str,
    low: float,
    high: float,
) -> None:
    """Add missing, non numeric, and out of range flags for one value column.

    A column absent from the dataframe is treated as not assessed, not as a
    missing value for every row. Core chemistry missingness is handled by
    flag_core_chemistry_missing.
    """
    if value_col in df.columns:
        missing, non_numeric, out_of_range = _range_flags(df[value_col], low, high)
        df[missing_flag] = missing
        df[non_numeric_flag] = non_numeric
        df[out_of_range_flag] = out_of_range
    else:
        df[missing_flag] = pd.Series(False, index=df.index, dtype="boolean")
        df[non_numeric_flag] = pd.Series(False, index=df.index, dtype="boolean")
        df[out_of_range_flag] = pd.Series(False, index=df.index, dtype="boolean")


def _status_is_allowed(
    status: pd.Series,
    allowed: set[str],
    missing_blocks: bool,
) -> pd.Series:
    """Return True where a status value is acceptable for analysis."""
    norm = safe_upper(status).replace("", pd.NA)

    if missing_blocks:
        return norm.notna() & norm.isin(allowed)

    return norm.isna() | norm.isin(allowed)


# =============================================================================
# Numeric coercion candidates
# =============================================================================


def build_numeric_candidates_for_stage1b(config: Dict[str, Any]) -> List[str]:
    """Return column names Stage 1B should pre cast to numeric."""
    out: List[str] = []

    for key in [
        "ta_precedence",
        "ph_precedence",
        "ph_co2sys_candidates",
        "pco2_precedence",
        "dic_precedence",
    ]:
        out.extend(config.get(key, []))

    out.extend(
        [
            "depth_m",
            "latitude_deg",
            "longitude_deg",
            "temperature_measurement_c",
            "temperature_insitu_c",
            "pressure_measurement_dbar",
            "pressure_output_dbar",
            "salinity",
            "oxygen_umol_l",
            "nitrate_nitrite_umol_l",
            "phosphate_umol_l",
            "silicate_umol_l",
            "chlorophyll",
            "co2aq_calc_umol_kg",
            "hco3_calc_umol_kg",
            "co3_calc_umol_kg",
            "omega_calcite_calc",
            "omega_aragonite_calc",
        ]
    )

    seen = set()
    unique: List[str] = []
    for col in out:
        if col not in seen:
            unique.append(col)
            seen.add(col)

    return unique


# =============================================================================
# QC status normalisation
# =============================================================================


def add_status_normalizations(
    df: pd.DataFrame,
    config: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    """Add normalised QC status columns in place.

    If a raw status column exists, it is used to rebuild the canonical status
    and normalised status columns.

    If no raw status column exists but an existing normalised column is already
    present, preserve it instead of overwriting it with blanks. This supports
    reruns or partially processed files that already contain columns such as
    ta_qc_status_norm.
    """
    used: Dict[str, Optional[str]] = {}

    for out_col, candidates in config.get("status_candidates", {}).items():
        norm_col = f"{out_col}_norm"
        src_col = first_existing(df, candidates)
        used[out_col] = src_col

        if src_col:
            df[out_col] = safe_str_series(df[src_col]).replace("", pd.NA)
            df[norm_col] = safe_upper(df[src_col]).replace("", pd.NA)
            continue

        if norm_col in df.columns:
            df[norm_col] = safe_upper(df[norm_col]).replace("", pd.NA)

            if out_col not in df.columns:
                df[out_col] = safe_str_series(df[norm_col]).replace("", pd.NA)
            else:
                df[out_col] = safe_str_series(df[out_col]).replace("", pd.NA)

            used[out_col] = norm_col
            continue

        if out_col in df.columns:
            df[out_col] = safe_str_series(df[out_col]).replace("", pd.NA)
            df[norm_col] = safe_upper(df[out_col]).replace("", pd.NA)
            used[out_col] = out_col
            continue

        df[out_col] = empty_string_series(df.index)
        df[norm_col] = empty_string_series(df.index)

    return used


# =============================================================================
# Best source analysis fields
# =============================================================================


def add_best_analysis_fields(
    df: pd.DataFrame,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Build best analysis fields and row level source columns in place."""
    meta: Dict[str, Any] = {}

    for col in [
        "record_id",
        "sample_id",
        "cruise_id",
        "transect_id",
        "station_id",
        "sample_type",
        "collection_mode",
        "replicate_id",
    ]:
        if col in df.columns:
            df[col] = safe_str_series(df[col]).replace("", pd.NA)

    if "sample_date" in df.columns:
        coerce_datetime(df, "sample_date", utc=True)

        if pd.api.types.is_datetime64_any_dtype(df["sample_date"]):
            sample_dt = df["sample_date"]
            if getattr(sample_dt.dt, "tz", None) is not None:
                sample_dt = sample_dt.dt.tz_convert("UTC").dt.tz_localize(None)
            df["sample_month"] = sample_dt.dt.to_period("M").astype("string")

    ta_candidates = existing_columns(df, config.get("ta_precedence", []))
    df["ta_best_umolkg"], df["ta_best_source"] = coalesce_numeric_series(df, ta_candidates)
    meta["ta_precedence_used"] = ta_candidates

    corrected_ph_col = first_existing(
        df,
        ["ph_corrected_from_phstd", "pH_corrected_from_std"],
    )

    df["ph_after_phstd_qc"] = empty_float_series(df.index)
    df["ph_after_phstd_qc_source"] = empty_string_series(df.index)

    if corrected_ph_col:
        ph_after = pd.to_numeric(df[corrected_ph_col], errors="coerce").astype("Float64")
        df["ph_after_phstd_qc"] = ph_after

        if "phstd_correction_applied" in df.columns:
            applied = _bool_series(df, "phstd_correction_applied", default=False)
        else:
            # Older files may have a corrected pH column but no correction flag.
            # Treat non missing corrected values as unknown corrected provenance,
            # not as a confirmed applied correction.
            applied = pd.Series(False, index=df.index, dtype=bool)

        has_ph_after = df["ph_after_phstd_qc"].notna()
        df.loc[applied & has_ph_after, "ph_after_phstd_qc_source"] = "phstd_corrected"
        df.loc[
            ~applied & has_ph_after,
            "ph_after_phstd_qc_source",
        ] = "phstd_original_fallback"

    ph_candidates = existing_columns(df, config.get("ph_precedence", []))
    df["ph_best"], df["ph_best_source"] = coalesce_numeric_series(df, ph_candidates)
    meta["ph_precedence_used"] = ph_candidates

    df["ph_best_correction_status_source"] = empty_string_series(df.index)
    if "ph_after_phstd_qc_source" in df.columns:
        from_ph_after = df["ph_best_source"].eq("ph_after_phstd_qc")
        df.loc[
            from_ph_after,
            "ph_best_correction_status_source",
        ] = df.loc[from_ph_after, "ph_after_phstd_qc_source"]

    ph_co2sys_col = first_existing(df, config.get("ph_co2sys_candidates", []))
    meta["ph_co2sys_source"] = ph_co2sys_col
    if ph_co2sys_col:
        df["ph_co2sys"] = pd.to_numeric(df[ph_co2sys_col], errors="coerce").astype("Float64")
    else:
        df["ph_co2sys"] = empty_float_series(df.index)

    pco2_candidates = existing_columns(df, config.get("pco2_precedence", []))
    df["pco2_best_uatm"], df["pco2_best_source"] = coalesce_numeric_series(df, pco2_candidates)
    meta["pco2_precedence_used"] = pco2_candidates

    dic_candidates = existing_columns(df, config.get("dic_precedence", []))
    df["dic_best_umol_kg"], df["dic_best_source"] = coalesce_numeric_series(df, dic_candidates)
    meta["dic_precedence_used"] = dic_candidates

    return meta


# =============================================================================
# Row classification
# =============================================================================


def classify_rows_sample(df: pd.DataFrame) -> pd.Series:
    """Classify rows that should participate in environmental analysis.

    Explicit sample_type labels are used when available. Blank sample_type values
    fall back to the QC flags: a row is treated as a sample if it is neither a
    TA CRM nor a pH standard.
    """
    is_crm = _bool_series(df, "is_ta_crm_row", default=False)
    is_std = _bool_series(df, "is_phstd_row", default=False)
    fallback_sample = ~(is_crm | is_std)

    if "sample_type" not in df.columns:
        return fallback_sample.astype("boolean")

    sample_type = safe_str_series(df["sample_type"]).str.lower()

    explicit_sample = sample_type.isin(
        ["sample", "s", "environmental", "water_sample", "water sample"]
    )
    explicit_non_sample = sample_type.isin(
        ["crm", "rm", "standard", "std", "phstd", "ph_standard", "ph standard", "blank"]
    )

    out = pd.Series(fallback_sample, index=df.index, dtype=bool)
    out.loc[explicit_sample] = True
    out.loc[explicit_non_sample] = False

    return out.astype("boolean")


# =============================================================================
# Chemistry provenance and role flags
# =============================================================================


def add_provenance_fields(
    df: pd.DataFrame,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Add unit, scale, calculation input, and role provenance in place."""
    meta: Dict[str, Any] = {}

    df["is_sample_row"] = classify_rows_sample(df)

    ta_units_cols = existing_columns(df, config.get("ta_unit_candidates", []))
    ta_units_raw, ta_units_source = coalesce_string_series(df, ta_units_cols)
    df["ta_units_normalized"] = ta_units_raw.map(normalize_ta_units)
    df["ta_units_source"] = ta_units_source

    ph_scale_obs_cols = existing_columns(df, config.get("ph_scale_observed_candidates", []))
    ph_scale_obs_raw, ph_scale_obs_source = coalesce_string_series(df, ph_scale_obs_cols)
    df["ph_scale_observed_normalized"] = ph_scale_obs_raw.map(normalize_ph_scale)
    df["ph_scale_observed_source"] = ph_scale_obs_source

    ph_scale_calc_cols = existing_columns(df, config.get("ph_scale_calculated_candidates", []))
    ph_scale_calc_raw, ph_scale_calc_source = coalesce_string_series(df, ph_scale_calc_cols)
    df["ph_scale_calculated_normalized"] = ph_scale_calc_raw.map(normalize_ph_scale)
    df["ph_scale_calculated_source"] = ph_scale_calc_source

    defaults = config.get("provenance_defaults", {})

    for col, value in defaults.items():
        if col in {"carbonate_solver", "carbon_input_pair_used"}:
            if col not in df.columns:
                df[col] = pd.Series(pd.NA, index=df.index, dtype="string")
            else:
                df[col] = safe_str_series(df[col]).replace("", pd.NA)

            if _scalar_default_has_value(value):
                missing = df[col].isna()
                df.loc[missing, col] = str(value)
        else:
            df[col] = value

    df["calc_temperature_c"] = empty_float_series(df.index)
    df["calc_temperature_source"] = empty_string_series(df.index)

    if "temperature_insitu_c" in df.columns:
        insitu = pd.to_numeric(df["temperature_insitu_c"], errors="coerce").astype("Float64")
        take = insitu.notna()
        df.loc[take, "calc_temperature_c"] = insitu.loc[take]
        df.loc[take, "calc_temperature_source"] = "temperature_insitu_c"

    if "temperature_measurement_c" in df.columns:
        measured = pd.to_numeric(df["temperature_measurement_c"], errors="coerce").astype("Float64")
        take = df["calc_temperature_c"].isna() & measured.notna()
        df.loc[take, "calc_temperature_c"] = measured.loc[take]
        df.loc[take, "calc_temperature_source"] = "temperature_measurement_c"

    df["flag_calc_temperature_from_measurement"] = (
        df["calc_temperature_source"].eq("temperature_measurement_c")
    ).astype("boolean")

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
        df[role_col] = pd.Series(pd.NA, index=df.index, dtype="string")

        if value_col in df.columns:
            df.loc[_has_value(df[value_col]), role_col] = chosen_role

    meta["carbonate_solver"] = defaults.get("carbonate_solver")
    meta["carbon_input_pair_used"] = defaults.get("carbon_input_pair_used")
    meta["carbonate_solver_existing_non_missing"] = (
        int(_has_value(df["carbonate_solver"]).sum())
        if "carbonate_solver" in df.columns
        else 0
    )
    meta["carbon_input_pair_existing_non_missing"] = (
        int(_has_value(df["carbon_input_pair_used"]).sum())
        if "carbon_input_pair_used" in df.columns
        else 0
    )
    meta["calc_temperature_sources"] = (
        df["calc_temperature_source"].value_counts(dropna=False).to_dict()
        if "calc_temperature_source" in df.columns
        else {}
    )

    return meta


# =============================================================================
# Unit, scale, presence, and range flags
# =============================================================================


def validate_ta_units(df: pd.DataFrame) -> Dict[str, Any]:
    """Add TA units presence and unexpected value flags in place."""
    df["flag_ta_units_missing"] = (
        df["ta_best_umolkg"].notna() & df["ta_units_normalized"].isna()
    ).astype("boolean")

    df["flag_ta_units_unexpected"] = (
        df["ta_best_umolkg"].notna()
        & df["ta_units_normalized"].notna()
        & ~df["ta_units_normalized"].eq("umol kg-1")
    ).astype("boolean")

    return {
        "unexpected_ta_units": (
            df.loc[df["flag_ta_units_unexpected"].fillna(False), "ta_units_normalized"]
            .value_counts(dropna=False)
            .to_dict()
        ),
    }


def add_scale_flags(
    df: pd.DataFrame,
    accepted_observed_scales: Optional[List[str]] = None,
) -> None:
    """Add pH scale missing and unexpected flags in place."""
    accepted = {
        normalize_ph_scale(x)
        for x in (accepted_observed_scales or ["total"])
    }
    accepted = {x for x in accepted if pd.notna(x)}

    df["flag_ph_scale_observed_missing"] = (
        df["ph_best"].notna() & df["ph_scale_observed_normalized"].isna()
    ).astype("boolean")

    df["flag_ph_scale_observed_unexpected"] = (
        df["ph_best"].notna()
        & df["ph_scale_observed_normalized"].notna()
        & ~df["ph_scale_observed_normalized"].isin(accepted)
    ).astype("boolean")

    df["flag_ph_scale_calculated_missing"] = (
        df["ph_co2sys"].notna() & df["ph_scale_calculated_normalized"].isna()
    ).astype("boolean")



def add_presence_flags(df: pd.DataFrame) -> None:
    """Add sample scoped core chemistry and pressure presence flags in place."""
    is_sample = df["is_sample_row"].fillna(False).astype(bool)

    sal_missing = (
        df["calc_salinity"].isna()
        if "calc_salinity" in df.columns
        else pd.Series(True, index=df.index)
    )

    temp_missing = (
        df["calc_temperature_c"].isna()
        if "calc_temperature_c" in df.columns
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
    ).astype("boolean")

    pressure_missing = (
        df["calc_pressure_dbar"].isna()
        if "calc_pressure_dbar" in df.columns
        else pd.Series(True, index=df.index)
    )

    df["flag_pressure_output_dbar_missing"] = (
        is_sample
        & df["ta_best_umolkg"].notna()
        & df["ph_best"].notna()
        & pressure_missing
    ).astype("boolean")


def add_analysis_range_flags(df: pd.DataFrame, policy: RangePolicy) -> None:
    """Add Stage 1B range diagnostics for best analysis fields in place."""
    specs = [
        (
            "latitude_deg",
            "flag_lat_missing",
            "flag_lat_non_numeric",
            "flag_lat_out_of_range",
            policy.lat_min,
            policy.lat_max,
        ),
        (
            "longitude_deg",
            "flag_lon_missing",
            "flag_lon_non_numeric",
            "flag_lon_out_of_range",
            policy.lon_min,
            policy.lon_max,
        ),
        (
            "salinity",
            "flag_sal_missing",
            "flag_sal_non_numeric",
            "flag_sal_out_of_range",
            policy.sal_min,
            policy.sal_max,
        ),
        (
            "depth_m",
            "flag_depth_missing",
            "flag_depth_non_numeric",
            "flag_depth_out_of_range",
            policy.depth_min,
            policy.depth_max,
        ),
        (
            "calc_temperature_c",
            "flag_calc_temperature_missing",
            "flag_calc_temperature_non_numeric",
            "flag_calc_temperature_out_of_range",
            policy.temp_min,
            policy.temp_max,
        ),
        (
            "ta_best_umolkg",
            "flag_ta_missing",
            "flag_ta_non_numeric",
            "flag_ta_out_of_range",
            policy.ta_min,
            policy.ta_max,
        ),
        (
            "ph_best",
            "flag_ph_missing",
            "flag_ph_non_numeric",
            "flag_ph_out_of_range",
            policy.ph_min,
            policy.ph_max,
        ),
        (
            "ph_co2sys",
            "flag_ph_co2sys_missing",
            "flag_ph_co2sys_non_numeric",
            "flag_ph_co2sys_out_of_range",
            policy.ph_min,
            policy.ph_max,
        ),
    ]

    for value_col, missing_flag, non_numeric_flag, out_flag, low, high in specs:
        _add_range_triplet(
            df,
            value_col=value_col,
            missing_flag=missing_flag,
            non_numeric_flag=non_numeric_flag,
            out_of_range_flag=out_flag,
            low=low,
            high=high,
        )


# =============================================================================
# Analysis ready subset
# =============================================================================


def analysis_ready_subset(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Return sample only rows with QC and strict analysis gates."""
    out = df.loc[df["is_sample_row"].fillna(False).astype(bool)].copy()

    policy = config.get("analysis_policy", {})
    allowed_qc_status = set(
        str(x).upper()
        for x in policy.get(
            "allowed_qc_status_for_analysis",
            ["PASS", "OK", "NO_ADJUST", "ADJUST"],
        )
    )
    missing_blocks = bool(policy.get("missing_qc_status_blocks_analysis", True))

    safe_qc = pd.Series(True, index=out.index, dtype=bool)

    required_status_cols = policy.get(
        "required_qc_status_norm_columns",
        ["ta_qc_status_norm"],
    )

    for status_col in required_status_cols:
        if status_col in out.columns:
            safe_qc &= _status_is_allowed(
                out[status_col],
                allowed=allowed_qc_status,
                missing_blocks=missing_blocks,
            ).fillna(False)
        else:
            safe_qc &= not missing_blocks

    phstd_fail = pd.Series(False, index=out.index, dtype=bool)
    if "phstd_status_norm" in out.columns:
        phstd_fail = safe_upper(out["phstd_status_norm"]).eq("FAIL").fillna(False)

    corrected_status_sources = set(
        str(x)
        for x in policy.get(
            "corrected_ph_status_source_names",
            ["phstd_corrected"],
        )
    )

    if "ph_best_correction_status_source" in out.columns:
        ph_best_from_corrected = out["ph_best_correction_status_source"].isin(
            corrected_status_sources
        )
    else:
        # Backward compatible fallback for outputs created before the row level
        # correction status column existed. This is less precise than the new
        # ph_best_correction_status_source column.
        corrected_sources = set(policy.get("corrected_ph_source_names", []))
        ph_best_from_corrected = (
            out["ph_best_source"].isin(corrected_sources)
            if "ph_best_source" in out.columns
            else pd.Series(False, index=out.index)
        )

    out["phstd_fail_diagnostic"] = phstd_fail.astype("boolean")
    out["ph_best_from_corrected"] = ph_best_from_corrected.astype("boolean")

    if bool(policy.get("phstd_fail_blocks_corrected_ph", False)):
        safe_qc &= ~(phstd_fail & ph_best_from_corrected)

    out["safe_for_analysis_qc"] = safe_qc.astype("boolean")

    strict = safe_qc.copy()

    strict_block_flags = [
        "flag_lat_out_of_range",
        "flag_lon_out_of_range",
        "flag_sal_out_of_range",
        "flag_depth_out_of_range",
        "flag_calc_temperature_out_of_range",
        "flag_ta_out_of_range",
        "flag_ph_out_of_range",
        "flag_ta_non_numeric",
        "flag_ph_non_numeric",
        "flag_sal_non_numeric",
        "flag_calc_temperature_non_numeric",
        "flag_ta_units_missing",
        "flag_ta_units_unexpected",
        "flag_ph_scale_observed_missing",
        "flag_ph_scale_observed_unexpected",
        "flag_core_chemistry_missing",
    ]

    for flag_col in strict_block_flags:
        if flag_col in out.columns:
            strict &= ~_bool_series(out, flag_col, default=False)

    if bool(policy.get("require_pressure_for_strict", False)):
        strict &= ~_bool_series(out, "flag_pressure_output_dbar_missing", default=False)

    if bool(policy.get("measurement_temperature_blocks_strict", False)):
        strict &= ~_bool_series(out, "flag_calc_temperature_from_measurement", default=False)

    out["safe_for_analysis_strict"] = strict.astype("boolean")

    return out


# =============================================================================
# Report helper
# =============================================================================


def provenance_counts_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy population summary for key Stage 1B provenance fields."""
    specs = [
        ("ta_best_umolkg", "Best TA"),
        ("ta_best_source", "Best TA source"),
        ("ph_best", "Best observed pH"),
        ("ph_best_source", "Best observed pH source"),
        ("ph_best_correction_status_source", "Best pH correction status source"),
        ("ph_co2sys", "Calculated pH"),
        ("pco2_best_uatm", "Best pCO2"),
        ("dic_best_umol_kg", "Best DIC"),
        ("ta_units_normalized", "TA units"),
        ("ph_scale_observed_normalized", "Observed pH scale"),
        ("ph_scale_calculated_normalized", "Calculated pH scale"),
        ("calc_temperature_c", "Calculation temperature"),
        ("calc_temperature_source", "Calculation temperature source"),
        ("calc_salinity", "Calculation salinity"),
        ("calc_pressure_dbar", "Calculation pressure"),
        ("carbonate_solver", "Carbonate solver"),
        ("carbon_input_pair_used", "Carbonate input pair"),
    ]

    rows = []

    for col, label in specs:
        if col in df.columns:
            rows.append(
                {
                    "field": label,
                    "column": col,
                    "non_missing": int(_has_value(df[col]).sum()),
                    "pct_missing": round(percent_missing(df[col]), 2),
                    "n_unique": int(df[col].nunique(dropna=True)),
                }
            )

    return pd.DataFrame(rows)
