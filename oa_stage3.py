"""
oa_stage3.py
============
Stage 3-specific logic: carbonate-system internal-consistency checks,
canonical helper columns, and a per-group QC summary roll-up.

The new operation in this stage is the **carbonate-system integrity
check**. Three families of test:

1. **DIC species-sum check.** The defining relation of dissolved
   inorganic carbon (Wikipedia "Dissolved inorganic carbon"; Murray,
   *Ocean Carbonate Chemistry*) is:

       DIC = [CO2(aq)] + [HCO3-] + [CO3(2-)]

   If all four are reported, they must balance. We flag a row when the
   residual `DIC - sum(species)` exceeds
   `max(dic_abs_tol, |DIC| * dic_rel_tol)` -- an absolute floor plus a
   relative ceiling, mirroring the OCADS internal-consistency approach
   (NDP-090). Defaults: 10 µmol/kg absolute, 1 % relative, matching the
   GOA-ON "weather" precision objective.

2. **pH diagnostic.** Compares `ph_best` (observed) with `ph_co2sys`
   (calculated from TA + DIC or TA + pCO2). Disagreement above
   `ph_diag_tol` (default 0.10) is flagged. There is also a "strict"
   version that requires matching pH scales -- comparing a total-scale
   pH with a free-scale pH would produce a spurious mismatch
   (OCADS CO2SYS reference: "Four different pH scales [total, seawater,
   free, NBS] are in current usage").

3. **Scale / unit mismatch.** Per-row flags for missing scale context,
   mismatched scales between observed/calculated pH, and mismatched
   units across the four DIC species.

All flags are **advisory**, never destructive -- consistent with how
Stages 1A/1B/2 handle out-of-range and replicate-disagreement rows.

What lives here
---------------
- `CarbonateIntegrityThresholds`     : the dataclass
- `STAGE3_DEFAULTS`                  : aliases, required/expected lists,
                                       qc group keys, thresholds
- `add_canonical_helper_columns`     : sample_month, depth_round_m, lat,
                                       lon, normalised scale/unit cols
- `carbonate_integrity_checks`       : the main row-wise check
- `build_qc_summary`                 : per-group flag counts

What does NOT live here
-----------------------
- `RangePolicy`                       -> `oa_policy.py`
- Alias resolution / unit normalisers -> `oa_schema.py`
- Generic helpers (`first_existing`, `robust_outlier_flags`, ...) ->
  `oa_common.py`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd

from oa_common import (
    empty_bool_series,
    empty_float_series,
    empty_string_series,
    robust_outlier_flags,
    safe_str_series,
)
from oa_schema import normalize_carbonate_unit, normalize_ph_scale

__all__ = [
    "STAGE3_DEFAULTS",
    "CarbonateIntegrityThresholds",
    "add_canonical_helper_columns",
    "carbonate_integrity_checks",
    "build_qc_summary",
]


# ===========================================================================
# STAGE3_DEFAULTS
# ===========================================================================

STAGE3_DEFAULTS: Dict[str, Any] = {
    "canonical_aliases": {
        "record_id":   ["record_id", "sample_tag"],
        "sample_id":   ["sample_id"],
        "cruise_id":   ["cruise_id", "Cruise", "cruise"],
        "transect_id": ["transect_id", "Transect", "transect"],
        "station_id":  ["station_id", "Station", "station"],
        "replicate_id": ["replicate_id", "replicate"],
        "sample_date": ["sample_date", "sample_date_dt", "date", "datetime"],
        "sample_month": ["sample_month"],
        "depth_m":      ["depth_m", "Depth", "depth"],
        "depth_round_m": ["depth_round_m"],
        "latitude_deg":  ["latitude_deg", "lat", "latitude", "Latitude", "lattitude"],
        "longitude_deg": ["longitude_deg", "lon", "longitude", "Longitude", "long"],
        "salinity":      ["salinity", "sal"],
        "temperature_measurement_c": [
            "temperature_measurement_c", "temp_measurement_c",
            "temp_lab", "temperature_lab_c",
        ],
        "temperature_insitu_c": [
            "temperature_insitu_c", "temperature_output_c",
            "temp_output_c", "temp_insitu",
        ],
        "pressure_measurement_dbar": [
            "pressure_measurement_dbar", "pressure_lab_dbar",
            "sample_pressure_dbar",
        ],
        "pressure_output_dbar": [
            "pressure_output_dbar", "pressure_insitu_dbar",
            "pressure_calc_dbar",
        ],
        "ta_best_umolkg": [
            "ta_best_umolkg", "ta_umol_kg", "ta_corrected_umolkg",
            "ta_corrected", "ta", "TA",
        ],
        "ph_best": [
            "ph_best", "ph_observed", "pH_best",
            "pH_lab", "ph_lab", "pH", "ph",
        ],
        "ph_co2sys": [
            "ph_co2sys", "ph_calculated", "pH_co2sys",
            "pH_calc", "ph_calc",
        ],
        "pco2_best_uatm":   ["pco2_best_uatm", "pco2_calc_uatm", "pco2"],
        "dic_best_umol_kg": [
            "dic_best_umol_kg", "dic_calculated_umol_kg",
            "dic_calc", "dic", "DIC",
        ],
        "co2aq_calc_umol_kg": [
            "co2aq_calc_umol_kg", "co2aq", "CO2aq",
            "co2_aq", "aqueous_co2", "co2", "CO2",
        ],
        "hco3_calc_umol_kg": ["hco3_calc_umol_kg", "hco3", "HCO3", "hco3-", "HCO3-"],
        "co3_calc_umol_kg":  ["co3_calc_umol_kg", "co3", "CO3", "co3-", "CO3-"],
        "ph_scale_observed_normalized": [
            "ph_scale_observed_normalized", "ph_best_scale",
            "ph_scale_observed", "pH_scale_observed", "ph_scale",
        ],
        "ph_scale_calculated_normalized": [
            "ph_scale_calculated_normalized", "ph_co2sys_scale",
            "ph_scale_calc", "pH_scale_calc", "ph_calc_scale",
        ],
        "dic_unit_normalized":   ["dic_unit_normalized", "dic_unit", "DIC_unit"],
        "co2aq_unit_normalized": [
            "co2aq_unit_normalized", "co2aq_unit", "CO2aq_unit",
            "co2_unit", "CO2_unit",
        ],
        "hco3_unit_normalized": ["hco3_unit_normalized", "hco3_unit", "HCO3_unit"],
        "co3_unit_normalized":  ["co3_unit_normalized", "co3_unit", "CO3_unit"],
        "carbonate_solver":     ["carbonate_solver"],
        "carbon_input_pair_used": ["carbon_input_pair_used"],
        "ta_best_source":      ["ta_best_source"],
        "ph_best_source":      ["ph_best_source"],
        "ph_co2sys_source":    ["ph_co2sys_source"],
        "pco2_best_source":    ["pco2_best_source"],
        "dic_best_source":     ["dic_best_source"],
        "ta_qc_status":        ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status":        ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status":        ["phstd_status", "pHstd_status", "ph_std_status"],
        "flag_replicate_any_conflict":        ["flag_replicate_any_conflict"],
        "flag_replicate_provenance_conflict": ["flag_replicate_provenance_conflict"],
        "flag_replicate_qc_conflict":         ["flag_replicate_qc_conflict"],
        "flag_replicate_sd_exceeded": [
            "flag_replicate_sd_exceeded",
            "flag_replicate_sd_threshold_exceeded",
        ],
    },
    "required_stage2_columns": [
        "record_id", "sample_id", "sample_date", "station_id", "depth_m",
        "salinity", "temperature_insitu_c", "ta_best_umolkg",
        "ph_best", "ph_co2sys",
    ],
    "expected_stage2_columns": [
        "cruise_id", "transect_id", "replicate_id", "pressure_output_dbar",
        "pco2_best_uatm", "dic_best_umol_kg", "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg", "co3_calc_umol_kg",
        "ph_scale_observed_normalized", "ph_scale_calculated_normalized",
        "carbonate_solver", "carbon_input_pair_used",
        "ta_best_source", "ph_best_source", "ph_co2sys_source",
        "pco2_best_source", "dic_best_source",
        "flag_replicate_any_conflict", "flag_replicate_provenance_conflict",
        "flag_replicate_qc_conflict", "flag_replicate_sd_exceeded",
    ],
    "qc_group_keys": [
        "cruise_id", "transect_id", "station_id",
        "depth_round_m", "sample_month",
    ],
    # Defaults for the integrity-check thresholds. See the dataclass below
    # for the explanation of each.
    "thresholds": {
        "dic_abs_tol": 10.0,
        "dic_rel_tol": 0.010,
        "ph_diag_tol": 0.10,
        "dic_mad_k":   3.5,
        "ph_mad_k":    3.5,
    },
}


# ===========================================================================
# Thresholds dataclass
# ===========================================================================

@dataclass
class CarbonateIntegrityThresholds:
    """Thresholds for the row-wise carbonate-system integrity checks.

    Attributes
    ----------
    dic_abs_tol : float
        Absolute tolerance, in µmol/kg, for the DIC species-sum check.
        A row is flagged when `|DIC - sum(species)|` exceeds the larger
        of this value and the relative tolerance. Default 10 µmol/kg,
        matching the GOA-ON "weather" precision objective for TA
        (Newton et al. 2015).
    dic_rel_tol : float
        Relative tolerance (fraction of DIC) for the same check.
        Default 0.010 = 1 %, matching the OCADS internal-consistency
        approach for high-DIC samples where 10 µmol/kg becomes
        a loose bound.
    ph_diag_tol : float
        Maximum acceptable |ph_best - ph_co2sys|. Default 0.10. This
        is intentionally loose; tighten to 0.02 (matching the GOA-ON
        weather pH objective) when the dataset comes from cruise-grade
        instruments.
    dic_mad_k : float
        MAD multiplier for the robust-outlier version of the DIC check.
        See `oa_common.robust_outlier_flags` for the rule.
    ph_mad_k : float
        MAD multiplier for the robust-outlier version of the pH
        diagnostic.
    """
    dic_abs_tol: float = 10.0
    dic_rel_tol: float = 0.010
    ph_diag_tol: float = 0.10
    dic_mad_k:   float = 3.5
    ph_mad_k:    float = 3.5


# ===========================================================================
# Helper columns
# ===========================================================================

# Numeric / string column buckets used by `add_canonical_helper_columns`.
_NUMERIC_COLS = [
    "latitude_deg", "longitude_deg", "depth_m", "depth_round_m",
    "salinity", "temperature_measurement_c", "temperature_insitu_c",
    "pressure_measurement_dbar", "pressure_output_dbar",
    "ta_best_umolkg", "ph_best", "ph_co2sys", "pco2_best_uatm",
    "dic_best_umol_kg", "co2aq_calc_umol_kg",
    "hco3_calc_umol_kg", "co3_calc_umol_kg",
]
_STRING_COLS = [
    "carbonate_solver", "carbon_input_pair_used",
    "ta_best_source", "ph_best_source", "ph_co2sys_source",
    "pco2_best_source", "dic_best_source",
    "ta_qc_status", "ph_qc_status", "phstd_status",
]
_REPLICATE_FLAG_COLS = [
    "flag_replicate_any_conflict",
    "flag_replicate_provenance_conflict",
    "flag_replicate_qc_conflict",
    "flag_replicate_sd_exceeded",
]


def _normalize_scale_series(s: pd.Series) -> pd.Series:
    """Apply normalize_ph_scale to every element, preserving dtype."""
    return s.map(normalize_ph_scale).astype("string")


def _normalize_unit_series(s: pd.Series) -> pd.Series:
    """Apply normalize_carbonate_unit to every element, preserving dtype."""
    return s.map(normalize_carbonate_unit).astype("string")


def add_canonical_helper_columns(
    df: pd.DataFrame,
    notes: List[str],
    depth_round_decimals: int = 1,
) -> pd.DataFrame:
    """Add the helper columns Stage 3 needs and tidy existing ones.

    Side effects (all on a copy of `df`):
      * Every column in `_NUMERIC_COLS` is `pd.to_numeric(..., 'coerce')`-cast.
      * `sample_date` is parsed to datetime; `sample_month` is derived.
      * `depth_round_m` is created from `depth_m` if missing.
      * `lat` / `lon` are created from `latitude_deg` / `longitude_deg`.
      * pH-scale columns are re-normalised via `normalize_ph_scale`
        (lower-cased). Carbonate-species unit columns are re-normalised
        via `normalize_carbonate_unit` (upper-cased, ASCII-folded).
      * String identifier / source / QC columns are whitespace-stripped.
      * Stage 2 replicate-conflict flags are forced to non-null boolean.
      * Roll-up flags are added: `flag_stage2_replicate_conflict_carried`,
        `flag_solver_unknown`, `flag_carbon_input_pair_unknown`.

    Notes are appended to the mutable `notes` list when a missing
    source column forces an all-NA helper column.
    """
    out = df.copy()

    for c in _NUMERIC_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    if "sample_date" in out.columns:
        out["sample_date"] = pd.to_datetime(out["sample_date"], errors="coerce")
        n_bad = int(out["sample_date"].isna().sum())
        if n_bad:
            notes.append(f"sample_date parsing produced {n_bad} missing values.")
    else:
        out["sample_date"] = pd.NaT
        notes.append("No sample_date column found. sample_date set to missing.")

    out["sample_month"] = out["sample_date"].dt.to_period("M").astype("string")

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
        out["latitude_deg"]
        if "latitude_deg" in out.columns
        else empty_float_series(out.index)
    )
    out["lon"] = (
        out["longitude_deg"]
        if "longitude_deg" in out.columns
        else empty_float_series(out.index)
    )

    # Normalise scale and unit columns (defensive: Stage 1B should have
    # done this, but Stage 3 should also work on a non-Stage-1B input).
    scale_cols = ["ph_scale_observed_normalized", "ph_scale_calculated_normalized"]
    for col in scale_cols:
        if col in out.columns:
            out[col] = _normalize_scale_series(out[col])
        else:
            out[col] = empty_string_series(out.index)

    unit_cols = [
        "dic_unit_normalized", "co2aq_unit_normalized",
        "hco3_unit_normalized", "co3_unit_normalized",
    ]
    for col in unit_cols:
        if col in out.columns:
            out[col] = _normalize_unit_series(out[col])
        else:
            out[col] = empty_string_series(out.index)

    # String identifier hygiene.
    for c in _STRING_COLS:
        if c in out.columns:
            out[c] = safe_str_series(out[c]).replace("", pd.NA)
        else:
            out[c] = empty_string_series(out.index)

    # Stage 2 carry-over flags.
    for c in _REPLICATE_FLAG_COLS:
        if c in out.columns:
            out[c] = out[c].fillna(False).astype("boolean")
        else:
            out[c] = pd.Series(False, index=out.index, dtype="boolean")

    out["flag_stage2_replicate_conflict_carried"] = (
        out["flag_replicate_any_conflict"].fillna(False)
        | out["flag_replicate_provenance_conflict"].fillna(False)
        | out["flag_replicate_qc_conflict"].fillna(False)
        | out["flag_replicate_sd_exceeded"].fillna(False)
    ).astype("boolean")

    out["flag_solver_unknown"] = out["carbonate_solver"].isna().astype("boolean")
    out["flag_carbon_input_pair_unknown"] = (
        out["carbon_input_pair_used"].isna().astype("boolean")
    )

    return out


# ===========================================================================
# Carbonate-system integrity checks
# ===========================================================================

def _dic_block(
    df: pd.DataFrame, thr: CarbonateIntegrityThresholds, out: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.Series, bool]:
    """Compute the DIC-side flags. Returns (mismatches_df, flag_mask, have_dic).

    Implementation factored out of `carbonate_integrity_checks` to keep
    the main entry point readable. `out` is mutated in place to receive
    the per-row flag columns.
    """
    dic_cols = ["dic_best_umol_kg", "co2aq_calc_umol_kg",
                "hco3_calc_umol_kg", "co3_calc_umol_kg"]
    have_dic = all(c in df.columns for c in dic_cols)
    out["dic_columns_present"] = have_dic

    if not have_dic:
        for c in [
            "dic_values_present_row", "flag_dic_unit_mismatch",
            "flag_dic_nonpositive", "flag_co2aq_negative",
            "flag_hco3_negative", "flag_co3_negative",
            "flag_any_negative_species",
            "dic_species_check_possible_row",
            "flag_dic_inconsistent", "flag_dic_inconsistent_robust",
        ]:
            out[c] = empty_bool_series(df.index)
        for c in [
            "dic_sum_species", "dic_minus_species_sum",
            "dic_species_rel_diff", "dic_tol_used",
        ]:
            out[c] = empty_float_series(df.index)
        return pd.DataFrame(), pd.Series(False, index=df.index), False

    dic   = pd.to_numeric(df["dic_best_umol_kg"], errors="coerce")
    co2aq = pd.to_numeric(df["co2aq_calc_umol_kg"], errors="coerce")
    hco3  = pd.to_numeric(df["hco3_calc_umol_kg"], errors="coerce")
    co3   = pd.to_numeric(df["co3_calc_umol_kg"], errors="coerce")

    vals_ok = dic.notna() & co2aq.notna() & hco3.notna() & co3.notna()
    out["dic_values_present_row"] = vals_ok.astype("boolean")

    # Unit mismatch: only firing if every unit column is non-null AND
    # they disagree. A null unit column is "unknown", not "wrong".
    unit_cols = ["dic_unit_normalized", "co2aq_unit_normalized",
                 "hco3_unit_normalized", "co3_unit_normalized"]
    units_complete = all(c in df.columns for c in unit_cols)
    if units_complete:
        u_complete = (
            df[unit_cols[0]].notna() & df[unit_cols[1]].notna()
            & df[unit_cols[2]].notna() & df[unit_cols[3]].notna()
        )
        u_same = (
            (df[unit_cols[0]] == df[unit_cols[1]])
            & (df[unit_cols[0]] == df[unit_cols[2]])
            & (df[unit_cols[0]] == df[unit_cols[3]])
        )
        out["flag_dic_unit_mismatch"] = (u_complete & ~u_same).astype("boolean")
    else:
        out["flag_dic_unit_mismatch"] = pd.Series(False, index=df.index, dtype="boolean")

    # Sum check.
    species_sum = co2aq + hco3 + co3
    diff = dic - species_sum
    tol = (dic.abs() * thr.dic_rel_tol).clip(lower=thr.dic_abs_tol)
    checkable = vals_ok & (~out["flag_dic_unit_mismatch"].fillna(False))

    # Sign sanity.
    out["flag_dic_nonpositive"] = (dic.notna() & (dic <= 0)).astype("boolean")
    out["flag_co2aq_negative"] = (co2aq.notna() & (co2aq < 0)).astype("boolean")
    out["flag_hco3_negative"]  = (hco3.notna()  & (hco3  < 0)).astype("boolean")
    out["flag_co3_negative"]   = (co3.notna()   & (co3   < 0)).astype("boolean")
    out["flag_any_negative_species"] = (
        out["flag_co2aq_negative"] | out["flag_hco3_negative"] | out["flag_co3_negative"]
    ).astype("boolean")

    out["dic_species_check_possible_row"] = checkable.astype("boolean")
    out["dic_sum_species"] = species_sum
    out["dic_minus_species_sum"] = diff
    out["dic_species_rel_diff"] = diff.abs() / dic.abs().replace(0, pd.NA)
    out["dic_tol_used"] = tol

    out["flag_dic_inconsistent"] = (checkable & (diff.abs() > tol)).astype("boolean")
    out["flag_dic_inconsistent_robust"] = (
        checkable & robust_outlier_flags(diff.where(vals_ok), mad_k=thr.dic_mad_k).fillna(False)
    ).astype("boolean")

    flag_mask = (
        out["flag_dic_unit_mismatch"]
        | out["flag_dic_nonpositive"]
        | out["flag_any_negative_species"]
        | out["flag_dic_inconsistent"]
        | out["flag_dic_inconsistent_robust"]
    ).fillna(False)

    id_cols = [c for c in ["record_id", "sample_id"] if c in df.columns]
    dic_mismatches = pd.concat(
        [
            df.loc[flag_mask, id_cols],
            pd.DataFrame({
                "dic_best_umol_kg": dic,
                "co2aq_calc_umol_kg": co2aq,
                "hco3_calc_umol_kg": hco3,
                "co3_calc_umol_kg": co3,
                "dic_sum_species": species_sum,
                "dic_minus_species_sum": diff,
                "dic_tol_used": tol,
            }, index=df.index),
            out[[c for c in out.columns if c.startswith(("flag_dic", "flag_co", "flag_hco"))
                 or c == "flag_any_negative_species"]],
        ],
        axis=1,
    ).loc[flag_mask].copy()

    return dic_mismatches, flag_mask, True


def _ph_block(
    df: pd.DataFrame, thr: CarbonateIntegrityThresholds, out: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.Series, bool]:
    """Compute the pH-diagnostic flags. Mutates `out` in place.

    Tests observed-vs-calculated pH agreement, scale-context presence,
    and scale-mismatch. The strict check requires matching scales.
    """
    have_ph = "ph_best" in df.columns and "ph_co2sys" in df.columns
    out["ph_columns_present"] = have_ph

    if not have_ph:
        for c in [
            "ph_diag_values_present_row",
            "flag_ph_best_missing_scale_context",
            "flag_ph_co2sys_missing_scale_context",
            "ph_scale_known_both_row", "flag_ph_scale_mismatch",
            "ph_diag_check_possible_row", "ph_diag_strict_check_possible_row",
            "flag_ph_diag_mismatch", "flag_ph_diag_mismatch_strict",
            "flag_ph_diag_mismatch_robust",
        ]:
            out[c] = empty_bool_series(df.index)
        out["ph_best_scale_norm"] = empty_string_series(df.index)
        out["ph_co2sys_scale_norm"] = empty_string_series(df.index)
        out["ph_best_minus_ph_co2sys"] = empty_float_series(df.index)
        return pd.DataFrame(), pd.Series(False, index=df.index), False

    ph_b = pd.to_numeric(df["ph_best"], errors="coerce")
    ph_c = pd.to_numeric(df["ph_co2sys"], errors="coerce")
    diff = ph_b - ph_c
    vals_ok = ph_b.notna() & ph_c.notna()

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
    scale_known = scale_obs.notna() & scale_calc.notna()
    scale_mismatch = scale_known & (scale_obs != scale_calc)

    out["ph_diag_values_present_row"] = vals_ok.astype("boolean")
    out["flag_ph_best_missing_scale_context"] = (ph_b.notna() & scale_obs.isna()).astype("boolean")
    out["flag_ph_co2sys_missing_scale_context"] = (ph_c.notna() & scale_calc.isna()).astype("boolean")
    out["ph_scale_known_both_row"] = scale_known.astype("boolean")
    out["flag_ph_scale_mismatch"] = scale_mismatch.astype("boolean")
    out["ph_best_scale_norm"] = scale_obs
    out["ph_co2sys_scale_norm"] = scale_calc
    out["ph_diag_check_possible_row"] = vals_ok.astype("boolean")
    out["ph_diag_strict_check_possible_row"] = (vals_ok & ~scale_mismatch.fillna(False)).astype("boolean")
    out["ph_best_minus_ph_co2sys"] = diff
    out["flag_ph_diag_mismatch"] = (vals_ok & (diff.abs() > thr.ph_diag_tol)).astype("boolean")
    out["flag_ph_diag_mismatch_strict"] = (
        out["ph_diag_strict_check_possible_row"] & (diff.abs() > thr.ph_diag_tol)
    ).astype("boolean")
    out["flag_ph_diag_mismatch_robust"] = (
        vals_ok & robust_outlier_flags(diff.where(vals_ok), mad_k=thr.ph_mad_k).fillna(False)
    ).astype("boolean")

    flag_mask = (
        out["flag_ph_best_missing_scale_context"]
        | out["flag_ph_co2sys_missing_scale_context"]
        | out["flag_ph_scale_mismatch"]
        | out["flag_ph_diag_mismatch"]
        | out["flag_ph_diag_mismatch_strict"]
        | out["flag_ph_diag_mismatch_robust"]
    ).fillna(False)

    ph_mismatches = pd.DataFrame(
        {
            "ph_best": ph_b,
            "ph_co2sys": ph_c,
            "ph_best_minus_ph_co2sys": diff,
            "ph_scale_observed_normalized": scale_obs,
            "ph_scale_calculated_normalized": scale_calc,
            "flag_ph_best_missing_scale_context": out["flag_ph_best_missing_scale_context"],
            "flag_ph_co2sys_missing_scale_context": out["flag_ph_co2sys_missing_scale_context"],
            "flag_ph_scale_mismatch": out["flag_ph_scale_mismatch"],
            "flag_ph_diag_mismatch": out["flag_ph_diag_mismatch"],
            "flag_ph_diag_mismatch_strict": out["flag_ph_diag_mismatch_strict"],
            "flag_ph_diag_mismatch_robust": out["flag_ph_diag_mismatch_robust"],
        },
        index=df.index,
    ).loc[flag_mask].copy()

    return ph_mismatches, flag_mask, True


def carbonate_integrity_checks(
    df: pd.DataFrame,
    thr: CarbonateIntegrityThresholds,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Run all row-wise carbonate-system integrity checks.

    Returns
    -------
    flags_df : DataFrame
        Same index as `df`, with all the new flag and diagnostic columns.
        Stage 3 then assigns these into the main frame.
    summary : dict
        Aggregate counts (one entry per flag) used by the manifest and
        the markdown report.
    dic_mismatches : DataFrame
        Rows that failed any DIC-side check, with the relevant diagnostic
        columns attached.
    ph_mismatches : DataFrame
        Rows that failed any pH-diagnostic check, with the relevant
        diagnostic columns attached.

    The function never modifies `df`.
    """
    out = pd.DataFrame(index=df.index)

    dic_mismatches, _, _ = _dic_block(df, thr, out)
    ph_mismatches, _, _ = _ph_block(df, thr, out)

    # Carry forward Stage 2's replicate-conflict roll-up and solver-unknown
    # flags so the combined `flag_any_carbonate_issue` includes them.
    for c in [
        "flag_stage2_replicate_conflict_carried",
        "flag_solver_unknown",
        "flag_carbon_input_pair_unknown",
    ]:
        if c in df.columns:
            out[c] = df[c].fillna(False).astype("boolean")
        else:
            out[c] = pd.Series(False, index=df.index, dtype="boolean")

    # The two combined flags. _strict adds the scale-mismatch-blocked
    # pH check plus the solver/input-pair-unknown flags.
    f = lambda c: out[c].fillna(False)
    out["flag_any_carbonate_issue"] = (
        f("flag_dic_unit_mismatch")
        | f("flag_dic_nonpositive")
        | f("flag_any_negative_species")
        | f("flag_dic_inconsistent")
        | f("flag_dic_inconsistent_robust")
        | f("flag_ph_best_missing_scale_context")
        | f("flag_ph_co2sys_missing_scale_context")
        | f("flag_ph_scale_mismatch")
        | f("flag_ph_diag_mismatch")
        | f("flag_ph_diag_mismatch_robust")
        | f("flag_stage2_replicate_conflict_carried")
    ).astype("boolean")
    out["flag_any_carbonate_issue_strict"] = (
        out["flag_any_carbonate_issue"]
        | f("flag_ph_diag_mismatch_strict")
        | f("flag_solver_unknown")
        | f("flag_carbon_input_pair_unknown")
    ).astype("boolean")

    # Aggregate counts for the manifest / report.
    n = lambda c: int(out[c].fillna(False).sum()) if c in out.columns else 0
    summary: Dict[str, Any] = {
        "dic_columns_present": bool(out["dic_columns_present"].iloc[0]) if "dic_columns_present" in out.columns else False,
        "n_dic_values_present": n("dic_values_present_row"),
        "n_dic_checkable": n("dic_species_check_possible_row"),
        "n_dic_unit_mismatch": n("flag_dic_unit_mismatch"),
        "n_dic_nonpositive": n("flag_dic_nonpositive"),
        "n_any_negative_species": n("flag_any_negative_species"),
        "n_dic_inconsistent": n("flag_dic_inconsistent"),
        "n_dic_inconsistent_robust": n("flag_dic_inconsistent_robust"),
        "ph_columns_present": bool(out["ph_columns_present"].iloc[0]) if "ph_columns_present" in out.columns else False,
        "n_ph_values_present": n("ph_diag_values_present_row"),
        "n_ph_checkable": n("ph_diag_check_possible_row"),
        "n_ph_strict_checkable": n("ph_diag_strict_check_possible_row"),
        "n_ph_best_missing_scale_context": n("flag_ph_best_missing_scale_context"),
        "n_ph_co2sys_missing_scale_context": n("flag_ph_co2sys_missing_scale_context"),
        "n_ph_scale_mismatch": n("flag_ph_scale_mismatch"),
        "n_ph_diag_mismatch": n("flag_ph_diag_mismatch"),
        "n_ph_diag_mismatch_strict": n("flag_ph_diag_mismatch_strict"),
        "n_ph_diag_mismatch_robust": n("flag_ph_diag_mismatch_robust"),
        "n_stage2_replicate_conflict_carried": n("flag_stage2_replicate_conflict_carried"),
        "n_solver_unknown": n("flag_solver_unknown"),
        "n_carbon_input_pair_unknown": n("flag_carbon_input_pair_unknown"),
        "n_any_carbonate_issue": n("flag_any_carbonate_issue"),
        "n_any_carbonate_issue_strict": n("flag_any_carbonate_issue_strict"),
        "dic_abs_tol": thr.dic_abs_tol,
        "dic_rel_tol": thr.dic_rel_tol,
        "ph_diag_tol": thr.ph_diag_tol,
        "dic_mad_k": thr.dic_mad_k,
        "ph_mad_k": thr.ph_mad_k,
    }

    return out, summary, dic_mismatches, ph_mismatches


# ===========================================================================
# Per-group QC summary
# ===========================================================================

_AGG_MAP = {
    "n_rows":                            ("sample_month", "size"),
    "n_dic_values_present":              ("dic_values_present_row", "sum"),
    "n_dic_checkable":                   ("dic_species_check_possible_row", "sum"),
    "n_dic_inconsistent":                ("flag_dic_inconsistent", "sum"),
    "n_dic_inconsistent_robust":         ("flag_dic_inconsistent_robust", "sum"),
    "n_dic_nonpositive":                 ("flag_dic_nonpositive", "sum"),
    "n_any_negative_species":            ("flag_any_negative_species", "sum"),
    "n_ph_values_present":               ("ph_diag_values_present_row", "sum"),
    "n_ph_checkable":                    ("ph_diag_check_possible_row", "sum"),
    "n_ph_strict_checkable":             ("ph_diag_strict_check_possible_row", "sum"),
    "n_ph_scale_mismatch":               ("flag_ph_scale_mismatch", "sum"),
    "n_ph_diag_mismatch":                ("flag_ph_diag_mismatch", "sum"),
    "n_ph_diag_mismatch_strict":         ("flag_ph_diag_mismatch_strict", "sum"),
    "n_ph_diag_mismatch_robust":         ("flag_ph_diag_mismatch_robust", "sum"),
    "n_stage2_replicate_conflict_carried": ("flag_stage2_replicate_conflict_carried", "sum"),
    "n_any_carbonate_issue":             ("flag_any_carbonate_issue", "sum"),
    "n_any_carbonate_issue_strict":      ("flag_any_carbonate_issue_strict", "sum"),
}


def build_qc_summary(
    df: pd.DataFrame, requested_keys: Sequence[str]
) -> Tuple[pd.DataFrame, List[str]]:
    """Per-group counts of every Stage 3 flag.

    Groups by the subset of `requested_keys` that exists in `df` (which
    is normally `[cruise_id, transect_id, station_id, depth_round_m,
    sample_month]`). Falls back to a single-row frame if no keys are
    available. Adds three percentage columns where the denominator is
    well-defined (`pct_dic_inconsistent`, `pct_ph_diag_mismatch`,
    `pct_any_carbonate_issue`).
    """
    keys = [k for k in requested_keys if k in df.columns]
    agg = {k: v for k, v in _AGG_MAP.items() if v[0] in df.columns}

    if keys:
        qc = df.groupby(keys, dropna=False).agg(**agg).reset_index()
    else:
        qc = pd.DataFrame({
            k: [int(df[v[0]].sum()) if v[1] == "sum" else len(df)]
            for k, v in agg.items()
        })

    safe_div = lambda n, d: (qc[n] / qc[d].replace(0, pd.NA) * 100).round(2)

    if "n_dic_checkable" in qc and "n_dic_inconsistent" in qc:
        qc["pct_dic_inconsistent"] = safe_div("n_dic_inconsistent", "n_dic_checkable")
    if "n_ph_checkable" in qc and "n_ph_diag_mismatch" in qc:
        qc["pct_ph_diag_mismatch"] = safe_div("n_ph_diag_mismatch", "n_ph_checkable")
    if "n_rows" in qc and "n_any_carbonate_issue" in qc:
        qc["pct_any_carbonate_issue"] = safe_div("n_any_carbonate_issue", "n_rows")

    return qc, keys
