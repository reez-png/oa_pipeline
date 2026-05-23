"""
stage3.py
=========
Stage 3 logic for the OA pipeline.

Stage 3 performs carbonate system internal consistency diagnostics. The checks
are advisory and non destructive: rows are flagged for review, not removed.

Import as:

    from oa_pipeline.stage3 import ...

Main checks
-----------
1. DIC species sum check:

       DIC = CO2(aq) + HCO3- + CO3(2-)

2. Observed pH versus calculated pH diagnostic.
3. Unit, pH scale, solver provenance, and Stage 2 replicate carry over flags.

Important design rule
---------------------
Stage 3 separates chemistry consistency flags from provenance audit flags.
Unknown carbonate_solver and unknown carbon_input_pair_used are still reported,
but they are not folded into flag_any_carbonate_issue_strict. Stage 4 handles
those provenance issues separately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .common import (
    empty_bool_series,
    empty_float_series,
    empty_string_series,
    robust_outlier_flags,
    safe_str_series,
)
from .schema import DEFAULT_CONFIG, normalize_carbonate_unit, normalize_ph_scale

__all__ = [
    "STAGE3_DEFAULTS",
    "CarbonateIntegrityThresholds",
    "add_canonical_helper_columns",
    "carbonate_integrity_checks",
    "build_qc_summary",
]


# =============================================================================
# Defaults
# =============================================================================

_SCHEMA_ALIASES: Dict[str, List[str]] = {
    key: list(value)
    for key, value in DEFAULT_CONFIG.get("canonical_candidates", {}).items()
}


STAGE3_DEFAULTS: Dict[str, Any] = {
    "canonical_aliases": {
        **_SCHEMA_ALIASES,
        "sample_date": ["sample_date", "sample_date_dt", "date", "datetime"],
        "sample_month": ["sample_month"],
        "sample_day": ["sample_day"],
        "depth_round_m": ["depth_round_m"],
        "depth_bin_m": ["depth_bin_m"],
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
            "pH_best",
            "pH_lab",
            "ph_lab",
            "pH",
            "ph",
        ],
        "ph_co2sys": [
            "ph_co2sys",
            "ph_calculated",
            "pH_co2sys",
            "pH_calc",
            "ph_calc",
        ],
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
        "co2aq_calc_umol_kg": [
            "co2aq_calc_umol_kg",
            "co2aq_umol_kg",
            "co2aq_umolkg",
            "co2_aq_umol_kg",
            "aqueous_co2_umol_kg",
        ],
        "hco3_calc_umol_kg": [
            "hco3_calc_umol_kg",
            "hco3_umol_kg",
            "hco3_umolkg",
            "bicarbonate_umol_kg",
        ],
        "co3_calc_umol_kg": [
            "co3_calc_umol_kg",
            "co3_umol_kg",
            "co3_umolkg",
            "carbonate_umol_kg",
        ],
        "ph_scale_observed_normalized": [
            "ph_scale_observed_normalized",
            "ph_best_scale",
            "ph_scale_observed",
            "pH_scale_observed",
            "ph_scale",
        ],
        "ph_scale_calculated_normalized": [
            "ph_scale_calculated_normalized",
            "ph_co2sys_scale",
            "ph_scale_calculated",
            "ph_scale_calc",
            "pH_scale_calc",
            "ph_calc_scale",
        ],
        "dic_unit_normalized": ["dic_unit_normalized", "dic_unit", "DIC_unit"],
        "co2aq_unit_normalized": [
            "co2aq_unit_normalized",
            "co2aq_unit",
            "CO2aq_unit",
            "co2_unit",
            "CO2_unit",
        ],
        "hco3_unit_normalized": ["hco3_unit_normalized", "hco3_unit", "HCO3_unit"],
        "co3_unit_normalized": ["co3_unit_normalized", "co3_unit", "CO3_unit"],
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
        "flag_replicate_any_conflict": ["flag_replicate_any_conflict"],
        "flag_replicate_provenance_conflict": ["flag_replicate_provenance_conflict"],
        "flag_replicate_qc_conflict": ["flag_replicate_qc_conflict"],
        "flag_replicate_sd_exceeded": [
            "flag_replicate_sd_exceeded",
            "flag_replicate_sd_threshold_exceeded",
        ],
    },
    # Required only for basic grouping and reporting. Chemistry fields are
    # expected, not required, because Stage 3 can still run partial diagnostics.
    "required_stage3_columns": [
        "sample_id",
        "sample_date",
        "station_id",
        "depth_m",
    ],
    # Backward compatible key for older notebook cells.
    "required_stage2_columns": [
        "sample_id",
        "sample_date",
        "station_id",
        "depth_m",
    ],
    "expected_stage3_columns": [
        "record_id",
        "cruise_id",
        "transect_id",
        "salinity",
        "temperature_insitu_c",
        "temperature_measurement_c",
        "pressure_output_dbar",
        "ta_best_umolkg",
        "ph_best",
        "ph_co2sys",
        "dic_best_umol_kg",
        "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg",
        "co3_calc_umol_kg",
        "pco2_best_uatm",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
        "dic_unit_normalized",
        "co2aq_unit_normalized",
        "hco3_unit_normalized",
        "co3_unit_normalized",
        "carbonate_solver",
        "carbon_input_pair_used",
        "ta_best_source",
        "ph_best_source",
        "ph_co2sys_source",
        "pco2_best_source",
        "dic_best_source",
        "flag_replicate_any_conflict",
        "flag_replicate_provenance_conflict",
        "flag_replicate_qc_conflict",
        "flag_replicate_sd_exceeded",
    ],
    # Backward compatible key for older notebook cells.
    "expected_stage2_columns": [
        "record_id",
        "cruise_id",
        "transect_id",
        "salinity",
        "temperature_insitu_c",
        "temperature_measurement_c",
        "pressure_output_dbar",
        "ta_best_umolkg",
        "ph_best",
        "ph_co2sys",
        "dic_best_umol_kg",
        "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg",
        "co3_calc_umol_kg",
        "pco2_best_uatm",
        "ph_scale_observed_normalized",
        "ph_scale_calculated_normalized",
        "dic_unit_normalized",
        "co2aq_unit_normalized",
        "hco3_unit_normalized",
        "co3_unit_normalized",
        "carbonate_solver",
        "carbon_input_pair_used",
        "ta_best_source",
        "ph_best_source",
        "ph_co2sys_source",
        "pco2_best_source",
        "dic_best_source",
        "flag_replicate_any_conflict",
        "flag_replicate_provenance_conflict",
        "flag_replicate_qc_conflict",
        "flag_replicate_sd_exceeded",
    ],
    "qc_group_keys": [
        "cruise_id",
        "transect_id",
        "station_id",
        "depth_round_m",
        "sample_month",
    ],
    "accepted_ph_scales": ["total"],
    "thresholds": {
        "dic_abs_tol": 10.0,
        "dic_rel_tol": 0.010,
        "ph_diag_tol": 0.10,
        "dic_mad_k": 3.5,
        "ph_mad_k": 3.5,
    },
    # Stage 3 does not run a carbonate solver. Production default is therefore
    # to report missing solver and input pair provenance rather than inventing it.
    # Enable this only for controlled synthetic examples or legacy files where
    # the calculated carbonate output provenance is known externally.
    "provenance_backfill": {
        "enabled": False,
        "solver": "synthetic_example_generator",
        "input_pair": "synthetic TA + pH_best",
    },
}


# =============================================================================
# Thresholds
# =============================================================================


@dataclass
class CarbonateIntegrityThresholds:
    """Thresholds for carbonate system integrity checks."""

    dic_abs_tol: float = 10.0
    dic_rel_tol: float = 0.010
    ph_diag_tol: float = 0.10
    dic_mad_k: float = 3.5
    ph_mad_k: float = 3.5

    def __post_init__(self) -> None:
        for name in [
            "dic_abs_tol",
            "dic_rel_tol",
            "ph_diag_tol",
            "dic_mad_k",
            "ph_mad_k",
        ]:
            value = float(getattr(self, name))

            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite, got {value!r}")

            setattr(self, name, value)

        if self.dic_abs_tol < 0:
            raise ValueError("dic_abs_tol must be non negative.")
        if self.dic_rel_tol < 0:
            raise ValueError("dic_rel_tol must be non negative.")
        if self.ph_diag_tol < 0:
            raise ValueError("ph_diag_tol must be non negative.")
        if self.dic_mad_k <= 0:
            raise ValueError("dic_mad_k must be greater than zero.")
        if self.ph_mad_k <= 0:
            raise ValueError("ph_mad_k must be greater than zero.")

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CarbonateIntegrityThresholds":
        """Build thresholds from a config dictionary's thresholds block."""
        return cls(**dict(config.get("thresholds", {})))


# =============================================================================
# Helper columns
# =============================================================================

_NUMERIC_COLS = [
    "latitude_deg",
    "longitude_deg",
    "depth_m",
    "depth_round_m",
    "depth_bin_m",
    "salinity",
    "temperature_measurement_c",
    "temperature_insitu_c",
    "pressure_measurement_dbar",
    "pressure_output_dbar",
    "ta_best_umolkg",
    "ph_best",
    "ph_co2sys",
    "pco2_best_uatm",
    "dic_best_umol_kg",
    "co2aq_calc_umol_kg",
    "hco3_calc_umol_kg",
    "co3_calc_umol_kg",
]

_STRING_COLS = [
    "record_id",
    "sample_id",
    "cruise_id",
    "transect_id",
    "station_id",
    "replicate_id",
    "carbonate_solver",
    "carbon_input_pair_used",
    "ta_best_source",
    "ph_best_source",
    "ph_co2sys_source",
    "pco2_best_source",
    "dic_best_source",
    "ta_qc_status",
    "ph_qc_status",
    "phstd_status",
]

_REPLICATE_FLAG_COLS = [
    "flag_replicate_any_conflict",
    "flag_replicate_provenance_conflict",
    "flag_replicate_qc_conflict",
    "flag_replicate_sd_exceeded",
]

_CALCULATED_CARBONATE_COLS = [
    "ph_co2sys",
    "pco2_best_uatm",
    "dic_best_umol_kg",
    "co2aq_calc_umol_kg",
    "hco3_calc_umol_kg",
    "co3_calc_umol_kg",
]

# Stage 3 does not run a carbonate solver. Backfill defaults are intentionally
# labelled synthetic and are disabled unless config explicitly enables them.
_DEFAULT_BACKFILLED_SOLVER = "synthetic_example_generator"
_DEFAULT_BACKFILLED_INPUT_PAIR = "synthetic TA + pH_best"


def _normalize_scale_series(series: pd.Series) -> pd.Series:
    """Normalise pH scale labels to canonical strings."""
    return series.map(normalize_ph_scale).astype("string")


def _normalize_unit_series(series: pd.Series) -> pd.Series:
    """Normalise carbonate unit labels to canonical strings."""
    return series.map(normalize_carbonate_unit).astype("string")


def _has_value(series: pd.Series) -> pd.Series:
    """Return True where a Series has a non missing and non blank value."""
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        text = series.astype("string").str.strip()
        return series.notna() & text.ne("").fillna(False)
    return series.notna()


def _calculated_carbonate_present(df: pd.DataFrame) -> pd.Series:
    """Return True where any calculated carbonate output exists in a row."""
    present = pd.Series(False, index=df.index, dtype=bool)

    for col in _CALCULATED_CARBONATE_COLS:
        if col in df.columns:
            present = present | pd.to_numeric(df[col], errors="coerce").notna()

    return present.astype("boolean")


def _backfill_calculated_carbonate_provenance(
    out: pd.DataFrame,
    has_calculated: pd.Series,
    notes: List[str],
    enabled: bool = False,
    solver: str = _DEFAULT_BACKFILLED_SOLVER,
    input_pair: str = _DEFAULT_BACKFILLED_INPUT_PAIR,
) -> None:
    """Optionally backfill solver provenance where calculated fields exist.

    Stage 3 does not calculate carbonate chemistry. When backfill is disabled,
    missing provenance remains missing and is flagged by flag_solver_unknown or
    flag_carbon_input_pair_unknown. This is the correct production default.
    """
    if "carbonate_solver" not in out.columns:
        out["carbonate_solver"] = empty_string_series(out.index)

    if "carbon_input_pair_used" not in out.columns:
        out["carbon_input_pair_used"] = empty_string_series(out.index)

    if not enabled:
        return

    calculated_mask = has_calculated.fillna(False).astype(bool)
    solver_missing = ~_has_value(out["carbonate_solver"])
    pair_missing = ~_has_value(out["carbon_input_pair_used"])

    solver_fill_mask = calculated_mask & solver_missing
    pair_fill_mask = calculated_mask & pair_missing

    if solver_fill_mask.any():
        out.loc[solver_fill_mask, "carbonate_solver"] = solver
        notes.append(
            "Backfilled carbonate_solver for rows with calculated carbonate outputs "
            f"using {solver!r}."
        )

    if pair_fill_mask.any():
        out.loc[pair_fill_mask, "carbon_input_pair_used"] = input_pair
        notes.append(
            "Backfilled carbon_input_pair_used for rows with calculated carbonate "
            f"outputs using {input_pair!r}."
        )


def add_canonical_helper_columns(
    df: pd.DataFrame,
    notes: List[str],
    depth_round_decimals: int = 1,
    provenance_backfill: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Add Stage 3 helper columns and normalise existing columns."""
    out = df.copy()

    for col in _NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "sample_date" in out.columns:
        out["sample_date"] = pd.to_datetime(out["sample_date"], errors="coerce", utc=True)
        n_bad = int(out["sample_date"].isna().sum())
        if n_bad:
            notes.append(f"sample_date parsing produced {n_bad} missing values.")
    else:
        out["sample_date"] = pd.NaT
        notes.append("No sample_date column found. sample_date set to missing.")

    sample_dt = out["sample_date"]
    if pd.api.types.is_datetime64_any_dtype(sample_dt):
        if getattr(sample_dt.dt, "tz", None) is not None:
            sample_dt_for_period = sample_dt.dt.tz_convert("UTC").dt.tz_localize(None)
        else:
            sample_dt_for_period = sample_dt

        out["sample_month"] = sample_dt_for_period.dt.to_period("M").astype("string")
        out["sample_day"] = sample_dt_for_period.dt.date.astype("string")
        out.loc[out["sample_date"].isna(), "sample_day"] = pd.NA
    else:
        out["sample_month"] = pd.Series(pd.NA, index=out.index, dtype="string")
        out["sample_day"] = pd.Series(pd.NA, index=out.index, dtype="string")

    if "depth_round_m" in out.columns and out["depth_round_m"].notna().any():
        out["depth_round_m"] = pd.to_numeric(out["depth_round_m"], errors="coerce")
    elif "depth_m" in out.columns:
        out["depth_round_m"] = pd.to_numeric(out["depth_m"], errors="coerce").round(
            depth_round_decimals
        )
    else:
        out["depth_round_m"] = empty_float_series(out.index)
        notes.append("No depth field found. depth_round_m set to missing.")

    out["lat"] = (
        pd.to_numeric(out["latitude_deg"], errors="coerce")
        if "latitude_deg" in out.columns
        else empty_float_series(out.index)
    )
    out["lon"] = (
        pd.to_numeric(out["longitude_deg"], errors="coerce")
        if "longitude_deg" in out.columns
        else empty_float_series(out.index)
    )

    for col in ["ph_scale_observed_normalized", "ph_scale_calculated_normalized"]:
        if col in out.columns:
            out[col] = _normalize_scale_series(out[col])
        else:
            out[col] = empty_string_series(out.index)

    for col in [
        "dic_unit_normalized",
        "co2aq_unit_normalized",
        "hco3_unit_normalized",
        "co3_unit_normalized",
    ]:
        if col in out.columns:
            out[col] = _normalize_unit_series(out[col])
        else:
            out[col] = empty_string_series(out.index)

    for col in _STRING_COLS:
        if col in out.columns:
            out[col] = safe_str_series(out[col]).replace("", pd.NA)
        else:
            out[col] = empty_string_series(out.index)

    for col in _REPLICATE_FLAG_COLS:
        if col in out.columns:
            out[col] = out[col].fillna(False).astype("boolean")
        else:
            out[col] = pd.Series(False, index=out.index, dtype="boolean")

    out["flag_stage2_replicate_conflict_carried"] = (
        out["flag_replicate_any_conflict"].fillna(False)
        | out["flag_replicate_provenance_conflict"].fillna(False)
        | out["flag_replicate_qc_conflict"].fillna(False)
        | out["flag_replicate_sd_exceeded"].fillna(False)
    ).astype("boolean")

    has_calculated = _calculated_carbonate_present(out)
    out["has_calculated_carbonate_output"] = has_calculated.astype("boolean")

    backfill_cfg = provenance_backfill or {}

    _backfill_calculated_carbonate_provenance(
        out,
        has_calculated,
        notes,
        enabled=bool(backfill_cfg.get("enabled", False)),
        solver=str(backfill_cfg.get("solver", _DEFAULT_BACKFILLED_SOLVER)),
        input_pair=str(backfill_cfg.get("input_pair", _DEFAULT_BACKFILLED_INPUT_PAIR)),
    )

    out["flag_solver_unknown"] = (
        has_calculated.fillna(False) & ~_has_value(out["carbonate_solver"])
    ).astype("boolean")

    out["flag_carbon_input_pair_unknown"] = (
        has_calculated.fillna(False) & ~_has_value(out["carbon_input_pair_used"])
    ).astype("boolean")

    return out


# =============================================================================
# DIC block
# =============================================================================


def _dic_block(
    df: pd.DataFrame,
    thr: CarbonateIntegrityThresholds,
    out: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.Series, bool]:
    """Compute DIC species sum diagnostics."""
    dic_cols = [
        "dic_best_umol_kg",
        "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg",
        "co3_calc_umol_kg",
    ]
    have_dic = all(col in df.columns for col in dic_cols)
    out["dic_columns_present"] = pd.Series(have_dic, index=df.index, dtype="boolean")

    if not have_dic:
        for col in [
            "dic_values_present_row",
            "flag_dic_unit_missing",
            "flag_dic_unit_mismatch",
            "flag_dic_nonpositive",
            "flag_co2aq_negative",
            "flag_hco3_negative",
            "flag_co3_negative",
            "flag_any_negative_species",
            "dic_species_check_possible_row",
            "flag_dic_inconsistent",
            "flag_dic_inconsistent_robust",
        ]:
            out[col] = empty_bool_series(df.index)

        for col in [
            "dic_sum_species",
            "dic_minus_species_sum",
            "dic_species_rel_diff",
            "dic_tol_used",
        ]:
            out[col] = empty_float_series(df.index)

        return pd.DataFrame(), pd.Series(False, index=df.index), False

    dic = pd.to_numeric(df["dic_best_umol_kg"], errors="coerce")
    co2aq = pd.to_numeric(df["co2aq_calc_umol_kg"], errors="coerce")
    hco3 = pd.to_numeric(df["hco3_calc_umol_kg"], errors="coerce")
    co3 = pd.to_numeric(df["co3_calc_umol_kg"], errors="coerce")

    vals_ok = dic.notna() & co2aq.notna() & hco3.notna() & co3.notna()
    out["dic_values_present_row"] = vals_ok.astype("boolean")

    unit_cols = [
        "dic_unit_normalized",
        "co2aq_unit_normalized",
        "hco3_unit_normalized",
        "co3_unit_normalized",
    ]

    units_complete = all(col in df.columns for col in unit_cols)

    if units_complete:
        units = df[unit_cols].copy()

        for col in unit_cols:
            units[col] = _normalize_unit_series(units[col])

        unit_present = units.apply(_has_value).all(axis=1)
        unit_same = (
            (units[unit_cols[0]] == units[unit_cols[1]])
            & (units[unit_cols[0]] == units[unit_cols[2]])
            & (units[unit_cols[0]] == units[unit_cols[3]])
        )

        out["flag_dic_unit_missing"] = (vals_ok & ~unit_present).astype("boolean")
        out["flag_dic_unit_mismatch"] = (
            vals_ok & unit_present & ~unit_same.fillna(False)
        ).astype("boolean")
    else:
        out["flag_dic_unit_missing"] = vals_ok.astype("boolean")
        out["flag_dic_unit_mismatch"] = pd.Series(False, index=df.index, dtype="boolean")

    species_sum = co2aq + hco3 + co3
    diff = dic - species_sum
    dic_abs = dic.abs()
    tol = (dic_abs * thr.dic_rel_tol).clip(lower=thr.dic_abs_tol)

    out["flag_dic_nonpositive"] = (dic.notna() & (dic <= 0)).astype("boolean")
    out["flag_co2aq_negative"] = (co2aq.notna() & (co2aq < 0)).astype("boolean")
    out["flag_hco3_negative"] = (hco3.notna() & (hco3 < 0)).astype("boolean")
    out["flag_co3_negative"] = (co3.notna() & (co3 < 0)).astype("boolean")
    out["flag_any_negative_species"] = (
        out["flag_co2aq_negative"].fillna(False)
        | out["flag_hco3_negative"].fillna(False)
        | out["flag_co3_negative"].fillna(False)
    ).astype("boolean")

    checkable = (
        vals_ok
        & ~out["flag_dic_unit_missing"].fillna(False)
        & ~out["flag_dic_unit_mismatch"].fillna(False)
        & ~out["flag_dic_nonpositive"].fillna(False)
    )

    out["dic_species_check_possible_row"] = checkable.astype("boolean")
    out["dic_sum_species"] = species_sum.astype("Float64")
    out["dic_minus_species_sum"] = diff.astype("Float64")
    out["dic_species_rel_diff"] = (diff.abs() / dic_abs.where(dic_abs > 0, pd.NA)).astype("Float64")
    out["dic_tol_used"] = tol.astype("Float64")

    out["flag_dic_inconsistent"] = (checkable & (diff.abs() > tol)).astype("boolean")
    out["flag_dic_inconsistent_robust"] = (
        checkable
        & robust_outlier_flags(
            diff.where(checkable),
            mad_k=thr.dic_mad_k,
            min_n=5,
        ).fillna(False)
    ).astype("boolean")

    flag_mask = (
        out["flag_dic_unit_missing"].fillna(False)
        | out["flag_dic_unit_mismatch"].fillna(False)
        | out["flag_dic_nonpositive"].fillna(False)
        | out["flag_any_negative_species"].fillna(False)
        | out["flag_dic_inconsistent"].fillna(False)
        | out["flag_dic_inconsistent_robust"].fillna(False)
    )

    id_cols = [col for col in ["record_id", "sample_id"] if col in df.columns]
    diagnostic_cols = [
        "flag_dic_unit_missing",
        "flag_dic_unit_mismatch",
        "flag_dic_nonpositive",
        "flag_co2aq_negative",
        "flag_hco3_negative",
        "flag_co3_negative",
        "flag_any_negative_species",
        "flag_dic_inconsistent",
        "flag_dic_inconsistent_robust",
    ]

    dic_mismatches = pd.concat(
        [
            df.loc[flag_mask, id_cols],
            pd.DataFrame(
                {
                    "dic_best_umol_kg": dic,
                    "co2aq_calc_umol_kg": co2aq,
                    "hco3_calc_umol_kg": hco3,
                    "co3_calc_umol_kg": co3,
                    "dic_sum_species": species_sum,
                    "dic_minus_species_sum": diff,
                    "dic_tol_used": tol,
                },
                index=df.index,
            ).loc[flag_mask],
            out.loc[flag_mask, diagnostic_cols],
        ],
        axis=1,
    ).copy()

    return dic_mismatches, flag_mask.astype(bool), True


# =============================================================================
# pH block
# =============================================================================


def _ph_block(
    df: pd.DataFrame,
    thr: CarbonateIntegrityThresholds,
    out: pd.DataFrame,
    accepted_ph_scales: Sequence[str] = ("total",),
) -> Tuple[pd.DataFrame, pd.Series, bool]:
    """Compute observed versus calculated pH diagnostics."""
    have_ph = "ph_best" in df.columns and "ph_co2sys" in df.columns
    out["ph_columns_present"] = pd.Series(have_ph, index=df.index, dtype="boolean")

    if not have_ph:
        for col in [
            "ph_diag_values_present_row",
            "flag_ph_best_missing_scale_context",
            "flag_ph_co2sys_missing_scale_context",
            "flag_ph_best_scale_unexpected",
            "flag_ph_co2sys_scale_unexpected",
            "ph_scale_known_both_row",
            "flag_ph_scale_mismatch",
            "ph_diag_check_possible_row",
            "ph_diag_strict_check_possible_row",
            "flag_ph_diag_mismatch",
            "flag_ph_diag_mismatch_strict",
            "flag_ph_diag_mismatch_robust",
        ]:
            out[col] = empty_bool_series(df.index)

        out["ph_best_scale_norm"] = empty_string_series(df.index)
        out["ph_co2sys_scale_norm"] = empty_string_series(df.index)
        out["ph_best_minus_ph_co2sys"] = empty_float_series(df.index)
        return pd.DataFrame(), pd.Series(False, index=df.index), False

    ph_best = pd.to_numeric(df["ph_best"], errors="coerce")
    ph_calc = pd.to_numeric(df["ph_co2sys"], errors="coerce")
    diff = ph_best - ph_calc
    vals_ok = ph_best.notna() & ph_calc.notna()

    scale_obs = (
        df["ph_scale_observed_normalized"]
        if "ph_scale_observed_normalized" in df.columns
        else empty_string_series(df.index)
    )
    scale_calc = (
        df["ph_scale_calculated_normalized"]
        if "ph_scale_calculated_normalized" in df.columns
        else empty_string_series(df.index)
    )

    scale_obs = _normalize_scale_series(scale_obs)
    scale_calc = _normalize_scale_series(scale_calc)

    scale_obs_present = _has_value(scale_obs)
    scale_calc_present = _has_value(scale_calc)
    scale_known = scale_obs_present & scale_calc_present
    scale_mismatch = scale_known & (scale_obs != scale_calc)
    accepted = {normalize_ph_scale(item) for item in accepted_ph_scales}
    accepted = {
        item
        for item in accepted
        if pd.notna(item) and str(item).strip() != ""
    }
    strict_possible = vals_ok & scale_known & ~scale_mismatch.fillna(False)

    out["ph_diag_values_present_row"] = vals_ok.astype("boolean")
    out["flag_ph_best_missing_scale_context"] = (ph_best.notna() & ~scale_obs_present).astype("boolean")
    out["flag_ph_co2sys_missing_scale_context"] = (ph_calc.notna() & ~scale_calc_present).astype("boolean")
    out["flag_ph_best_scale_unexpected"] = (
        ph_best.notna() & scale_obs_present & ~scale_obs.isin(accepted)
    ).astype("boolean")
    out["flag_ph_co2sys_scale_unexpected"] = (
        ph_calc.notna() & scale_calc_present & ~scale_calc.isin(accepted)
    ).astype("boolean")
    out["ph_scale_known_both_row"] = scale_known.astype("boolean")
    out["flag_ph_scale_mismatch"] = scale_mismatch.astype("boolean")
    out["ph_best_scale_norm"] = scale_obs
    out["ph_co2sys_scale_norm"] = scale_calc
    out["ph_diag_check_possible_row"] = vals_ok.astype("boolean")
    out["ph_diag_strict_check_possible_row"] = strict_possible.astype("boolean")
    out["ph_best_minus_ph_co2sys"] = diff.astype("Float64")
    out["flag_ph_diag_mismatch"] = (vals_ok & (diff.abs() > thr.ph_diag_tol)).astype("boolean")
    out["flag_ph_diag_mismatch_strict"] = (
        strict_possible & (diff.abs() > thr.ph_diag_tol)
    ).astype("boolean")
    out["flag_ph_diag_mismatch_robust"] = (
        vals_ok
        & robust_outlier_flags(
            diff.where(vals_ok),
            mad_k=thr.ph_mad_k,
            min_n=5,
        ).fillna(False)
    ).astype("boolean")

    flag_mask = (
        out["flag_ph_best_missing_scale_context"].fillna(False)
        | out["flag_ph_co2sys_missing_scale_context"].fillna(False)
        | out["flag_ph_best_scale_unexpected"].fillna(False)
        | out["flag_ph_co2sys_scale_unexpected"].fillna(False)
        | out["flag_ph_scale_mismatch"].fillna(False)
        | out["flag_ph_diag_mismatch"].fillna(False)
        | out["flag_ph_diag_mismatch_strict"].fillna(False)
        | out["flag_ph_diag_mismatch_robust"].fillna(False)
    )

    id_cols = [col for col in ["record_id", "sample_id"] if col in df.columns]
    ph_mismatches = pd.concat(
        [
            df.loc[flag_mask, id_cols],
            pd.DataFrame(
                {
                    "ph_best": ph_best,
                    "ph_co2sys": ph_calc,
                    "ph_best_minus_ph_co2sys": diff,
                    "ph_scale_observed_normalized": scale_obs,
                    "ph_scale_calculated_normalized": scale_calc,
                },
                index=df.index,
            ).loc[flag_mask],
            out.loc[
                flag_mask,
                [
                    "flag_ph_best_missing_scale_context",
                    "flag_ph_co2sys_missing_scale_context",
                    "flag_ph_best_scale_unexpected",
                    "flag_ph_co2sys_scale_unexpected",
                    "flag_ph_scale_mismatch",
                    "flag_ph_diag_mismatch",
                    "flag_ph_diag_mismatch_strict",
                    "flag_ph_diag_mismatch_robust",
                ],
            ],
        ],
        axis=1,
    ).copy()

    return ph_mismatches, flag_mask.astype(bool), True


# =============================================================================
# Main carbonate integrity entry point
# =============================================================================


def carbonate_integrity_checks(
    df: pd.DataFrame,
    thr: CarbonateIntegrityThresholds,
    accepted_ph_scales: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Run all row wise carbonate system integrity diagnostics."""
    accepted_ph_scales = accepted_ph_scales or ("total",)
    out = pd.DataFrame(index=df.index)

    dic_mismatches, _, _ = _dic_block(df, thr, out)
    ph_mismatches, _, _ = _ph_block(
        df,
        thr,
        out,
        accepted_ph_scales=accepted_ph_scales,
    )

    for col in [
        "flag_stage2_replicate_conflict_carried",
        "flag_solver_unknown",
        "flag_carbon_input_pair_unknown",
        "has_calculated_carbonate_output",
    ]:
        if col in df.columns:
            out[col] = df[col].fillna(False).astype("boolean")
        else:
            out[col] = pd.Series(False, index=df.index, dtype="boolean")

    flag = lambda col: out[col].fillna(False) if col in out.columns else pd.Series(False, index=out.index)

    out["flag_any_carbonate_issue"] = (
        flag("flag_dic_unit_missing")
        | flag("flag_dic_unit_mismatch")
        | flag("flag_dic_nonpositive")
        | flag("flag_any_negative_species")
        | flag("flag_dic_inconsistent")
        | flag("flag_dic_inconsistent_robust")
        | flag("flag_ph_best_missing_scale_context")
        | flag("flag_ph_co2sys_missing_scale_context")
        | flag("flag_ph_best_scale_unexpected")
        | flag("flag_ph_co2sys_scale_unexpected")
        | flag("flag_ph_scale_mismatch")
        | flag("flag_ph_diag_mismatch")
        | flag("flag_ph_diag_mismatch_robust")
        | flag("flag_stage2_replicate_conflict_carried")
    ).astype("boolean")

    # Strict carbonate chemistry rollup intentionally excludes solver and input
    # pair provenance. Those are audit provenance issues handled by Stage 4.
    out["flag_any_carbonate_issue_strict"] = (
        flag("flag_dic_unit_mismatch")
        | flag("flag_dic_nonpositive")
        | flag("flag_any_negative_species")
        | flag("flag_dic_inconsistent")
        | flag("flag_dic_inconsistent_robust")
        | flag("flag_ph_best_scale_unexpected")
        | flag("flag_ph_co2sys_scale_unexpected")
        | flag("flag_ph_scale_mismatch")
        | flag("flag_ph_diag_mismatch_strict")
        | flag("flag_ph_diag_mismatch_robust")
    ).astype("boolean")

    out["flag_any_stage3_review_issue"] = (
        flag("flag_any_carbonate_issue")
        | flag("flag_stage2_replicate_conflict_carried")
        | flag("flag_solver_unknown")
        | flag("flag_carbon_input_pair_unknown")
    ).astype("boolean")

    count_true = lambda col: int(out[col].fillna(False).sum()) if col in out.columns else 0
    first_bool = lambda col: bool(out[col].fillna(False).iloc[0]) if col in out.columns and len(out) else False

    summary: Dict[str, Any] = {
        "dic_columns_present": first_bool("dic_columns_present"),
        "n_dic_values_present": count_true("dic_values_present_row"),
        "n_dic_checkable": count_true("dic_species_check_possible_row"),
        "n_dic_unit_missing": count_true("flag_dic_unit_missing"),
        "n_dic_unit_mismatch": count_true("flag_dic_unit_mismatch"),
        "n_dic_nonpositive": count_true("flag_dic_nonpositive"),
        "n_any_negative_species": count_true("flag_any_negative_species"),
        "n_dic_inconsistent": count_true("flag_dic_inconsistent"),
        "n_dic_inconsistent_robust": count_true("flag_dic_inconsistent_robust"),
        "ph_columns_present": first_bool("ph_columns_present"),
        "n_ph_values_present": count_true("ph_diag_values_present_row"),
        "n_ph_checkable": count_true("ph_diag_check_possible_row"),
        "n_ph_strict_checkable": count_true("ph_diag_strict_check_possible_row"),
        "n_ph_best_missing_scale_context": count_true("flag_ph_best_missing_scale_context"),
        "n_ph_co2sys_missing_scale_context": count_true("flag_ph_co2sys_missing_scale_context"),
        "n_ph_best_scale_unexpected": count_true("flag_ph_best_scale_unexpected"),
        "n_ph_co2sys_scale_unexpected": count_true("flag_ph_co2sys_scale_unexpected"),
        "n_ph_scale_mismatch": count_true("flag_ph_scale_mismatch"),
        "n_ph_diag_mismatch": count_true("flag_ph_diag_mismatch"),
        "n_ph_diag_mismatch_strict": count_true("flag_ph_diag_mismatch_strict"),
        "n_ph_diag_mismatch_robust": count_true("flag_ph_diag_mismatch_robust"),
        "n_stage2_replicate_conflict_carried": count_true("flag_stage2_replicate_conflict_carried"),
        "n_has_calculated_carbonate_output": count_true("has_calculated_carbonate_output"),
        "n_solver_unknown": count_true("flag_solver_unknown"),
        "n_carbon_input_pair_unknown": count_true("flag_carbon_input_pair_unknown"),
        "n_any_carbonate_issue": count_true("flag_any_carbonate_issue"),
        "n_any_carbonate_issue_strict": count_true("flag_any_carbonate_issue_strict"),
        "n_any_stage3_review_issue": count_true("flag_any_stage3_review_issue"),
        "accepted_ph_scales": list(accepted_ph_scales),
        "dic_abs_tol": thr.dic_abs_tol,
        "dic_rel_tol": thr.dic_rel_tol,
        "ph_diag_tol": thr.ph_diag_tol,
        "dic_mad_k": thr.dic_mad_k,
        "ph_mad_k": thr.ph_mad_k,
    }

    return out, summary, dic_mismatches, ph_mismatches


# =============================================================================
# Per group QC summary
# =============================================================================

_AGG_MAP = {
    "n_rows": ("sample_month", "size"),
    "n_dic_values_present": ("dic_values_present_row", "sum"),
    "n_dic_checkable": ("dic_species_check_possible_row", "sum"),
    "n_dic_unit_missing": ("flag_dic_unit_missing", "sum"),
    "n_dic_unit_mismatch": ("flag_dic_unit_mismatch", "sum"),
    "n_dic_inconsistent": ("flag_dic_inconsistent", "sum"),
    "n_dic_inconsistent_robust": ("flag_dic_inconsistent_robust", "sum"),
    "n_dic_nonpositive": ("flag_dic_nonpositive", "sum"),
    "n_any_negative_species": ("flag_any_negative_species", "sum"),
    "n_ph_values_present": ("ph_diag_values_present_row", "sum"),
    "n_ph_checkable": ("ph_diag_check_possible_row", "sum"),
    "n_ph_strict_checkable": ("ph_diag_strict_check_possible_row", "sum"),
    "n_ph_best_scale_unexpected": ("flag_ph_best_scale_unexpected", "sum"),
    "n_ph_co2sys_scale_unexpected": ("flag_ph_co2sys_scale_unexpected", "sum"),
    "n_ph_scale_mismatch": ("flag_ph_scale_mismatch", "sum"),
    "n_ph_diag_mismatch": ("flag_ph_diag_mismatch", "sum"),
    "n_ph_diag_mismatch_strict": ("flag_ph_diag_mismatch_strict", "sum"),
    "n_ph_diag_mismatch_robust": ("flag_ph_diag_mismatch_robust", "sum"),
    "n_stage2_replicate_conflict_carried": (
        "flag_stage2_replicate_conflict_carried",
        "sum",
    ),
    "n_solver_unknown": ("flag_solver_unknown", "sum"),
    "n_carbon_input_pair_unknown": ("flag_carbon_input_pair_unknown", "sum"),
    "n_any_carbonate_issue": ("flag_any_carbonate_issue", "sum"),
    "n_any_carbonate_issue_strict": ("flag_any_carbonate_issue_strict", "sum"),
    "n_any_stage3_review_issue": ("flag_any_stage3_review_issue", "sum"),
}


def _complete_group_key(df: pd.DataFrame, keys: Sequence[str]) -> pd.Series:
    """Return True where all grouping keys are present and non blank."""
    if not keys:
        return pd.Series(True, index=df.index, dtype=bool)

    complete = pd.Series(True, index=df.index, dtype=bool)
    for key in keys:
        if key not in df.columns:
            complete &= False
        else:
            complete &= _has_value(df[key])
    return complete


def build_qc_summary(
    df: pd.DataFrame,
    requested_keys: Sequence[str],
) -> Tuple[pd.DataFrame, List[str]]:
    """Build per group counts of Stage 3 diagnostics."""
    keys = [key for key in requested_keys if key in df.columns]
    agg = {name: spec for name, spec in _AGG_MAP.items() if spec[0] in df.columns}

    if not agg:
        if keys:
            complete_key = _complete_group_key(df, keys)
            if complete_key.any():
                qc = df.loc[complete_key, keys].drop_duplicates().copy()
                sizes = (
                    df.loc[complete_key]
                    .groupby(keys, dropna=False)
                    .size()
                    .rename("n_rows")
                    .reset_index()
                )
                qc = qc.merge(sizes, on=keys, how="left")
            else:
                qc = pd.DataFrame({"n_rows": [0]})
            qc["n_rows_with_incomplete_group_key"] = int((~complete_key).sum())
        else:
            qc = pd.DataFrame({"n_rows": [len(df)]})
        return qc, keys

    if keys:
        complete_key = _complete_group_key(df, keys)
        n_incomplete = int((~complete_key).sum())

        if complete_key.any():
            qc = df.loc[complete_key].groupby(keys, dropna=False).agg(**agg).reset_index()
            qc["n_rows_with_incomplete_group_key"] = n_incomplete
        else:
            qc = pd.DataFrame({"n_rows_with_incomplete_group_key": [n_incomplete]})
    else:
        qc = pd.DataFrame(
            {
                name: [int(df[source].fillna(False).sum()) if func == "sum" else len(df)]
                for name, (source, func) in agg.items()
            }
        )

    def safe_pct(numerator: str, denominator: str) -> pd.Series:
        return (qc[numerator] / qc[denominator].replace(0, pd.NA) * 100).round(2)

    if "n_dic_checkable" in qc and "n_dic_inconsistent" in qc:
        qc["pct_dic_inconsistent"] = safe_pct("n_dic_inconsistent", "n_dic_checkable")
    if "n_ph_checkable" in qc and "n_ph_diag_mismatch" in qc:
        qc["pct_ph_diag_mismatch"] = safe_pct("n_ph_diag_mismatch", "n_ph_checkable")
    if "n_rows" in qc and "n_any_carbonate_issue" in qc:
        qc["pct_any_carbonate_issue"] = safe_pct("n_any_carbonate_issue", "n_rows")

    return qc, keys
