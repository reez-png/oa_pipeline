"""
oa_stage4.py
============
Stage 4-specific logic: the **analyst-facing decision layer**.

Stage 4 is the only stage that assigns a per-row verdict
(`analysis_audit_status`) and attaches explicit reason codes
(`analysis_audit_reason_codes`). Earlier stages flag, count, and
summarise; Stage 4 says "this row is PASS, this is REVIEW, this is FAIL,
and here is the reason."

The taxonomy is the standard PASS / WARN / FAIL "quality gate" pattern
documented across software-quality and statistical-process literature:

- NDepend, *Quality Gates*: "PASS / WARN / FAIL approach... a
  synthesized way to know if the team can release to production."
- testRigor, *Software Quality Gates*: "Pass: all gate metrics are met...
  Warning: may not be met... Fail: must be resolved before
  production can proceed."
- UN/ABS *Data Quality Manual Part B -- Quality Gates in the
  Statistical Process*: "Actions associated with quality measures need
  to take into account the severity of the result on the end product."

We use REVIEW (not WARN) for the middle tier because that is what an
analyst actually does -- review the row, decide whether to include or
exclude. The vocabulary is identical to the NDepend/SonarQube one in
substance.

What lives here
---------------
- `STAGE4_DEFAULTS`                  : aliases, range_policy, dic_audit, etc.
- `_ID_COLS`                         : columns attached to long-format outputs
- `coerce_and_standardize`           : numeric/string/date coercion
- `missing_key_rows` / `detect_duplicates` : key integrity
- `run_range_checks`                 : long-format range_flags + summary
- `DicSpeciesAudit` / `dic_species_audit` : the strict species audit
- `add_readiness_status`             : the PASS/REVIEW/FAIL classifier
- `reason_count_table`               : per-reason-code histogram for the manifest

What stays elsewhere
--------------------
- `RangePolicy`                      -> `oa_policy.py` (unified across stages)
- Alias resolution / normalisers     -> `oa_schema.py`
- Helper inventory / presence tables -> `oa_stage2.py`
- Generic helpers                    -> `oa_common.py`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from oa_common import (
    empty_bool_series,
    empty_float_series,
    empty_string_series,
    first_existing,
    safe_str_series,
)
from oa_schema import normalize_carbonate_unit, normalize_ph_scale

__all__ = [
    "STAGE4_DEFAULTS",
    "DicSpeciesAudit",
    "coerce_and_standardize",
    "missing_key_rows",
    "detect_duplicates",
    "run_range_checks",
    "dic_species_audit",
    "add_readiness_status",
    "reason_count_table",
]


# ===========================================================================
# STAGE4_DEFAULTS
# ===========================================================================

STAGE4_DEFAULTS: Dict[str, Any] = {
    "canonical_aliases": {
        "record_id":    ["record_id", "sample_tag"],
        "sample_id":    ["sample_id"],
        "cruise_id":    ["cruise_id", "Cruise", "cruise"],
        "transect_id":  ["transect_id", "Transect", "transect"],
        "station_id":   ["station_id", "Station", "station"],
        "replicate_id": ["replicate_id", "replicate"],
        "sample_date":  ["sample_date", "sample_date_dt", "date", "Date", "datetime"],
        "sample_month": ["sample_month", "month"],
        "depth_m":      ["depth_m", "Depth", "depth"],
        "depth_round_m": ["depth_round_m"],
        "latitude_deg":  ["latitude_deg", "latitude", "Latitude", "lattitude", "lat"],
        "longitude_deg": ["longitude_deg", "longitude", "Longitude", "longtitude", "long", "lon"],
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
        "ta_best_umolkg": ["ta_best_umolkg", "ta_umol_kg", "ta_best"],
        "ph_best": [
            "ph_best", "ph_observed", "pH_best",
            "pH_lab", "ph_lab", "pH", "ph",
        ],
        "ph_co2sys": [
            "ph_co2sys", "ph_calculated", "pH_co2sys",
            "pH_calc", "ph_calc",
        ],
        "pco2_best_uatm": ["pco2_best_uatm", "pco2_calc_uatm", "pco2", "pCO2"],
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
        "omega_aragonite_calc": [
            "omega_aragonite_calc", "omega_ar", "omega_arag", "OmegaArag",
        ],
        "omega_calcite_calc": [
            "omega_calcite_calc", "omega_ca", "omega_calc", "OmegaCalc",
        ],
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
        "carbonate_solver":      ["carbonate_solver"],
        "carbon_input_pair_used": ["carbon_input_pair_used"],
        "ta_best_source":   ["ta_best_source"],
        "ph_best_source":   ["ph_best_source"],
        "ph_co2sys_source": ["ph_co2sys_source"],
        "pco2_best_source": ["pco2_best_source"],
        "dic_best_source":  ["dic_best_source"],
        "flag_dic_inconsistent":          ["flag_dic_inconsistent"],
        "flag_dic_inconsistent_robust":   ["flag_dic_inconsistent_robust"],
        "flag_ph_scale_mismatch":         ["flag_ph_scale_mismatch"],
        "flag_ph_diag_mismatch":          ["flag_ph_diag_mismatch"],
        "flag_ph_diag_mismatch_strict":   ["flag_ph_diag_mismatch_strict"],
        "flag_ph_diag_mismatch_robust":   ["flag_ph_diag_mismatch_robust"],
        "flag_any_carbonate_issue":        ["flag_any_carbonate_issue"],
        "flag_any_carbonate_issue_strict": ["flag_any_carbonate_issue_strict"],
        "flag_stage2_replicate_conflict_carried": ["flag_stage2_replicate_conflict_carried"],
        "flag_solver_unknown":            ["flag_solver_unknown"],
        "flag_carbon_input_pair_unknown": ["flag_carbon_input_pair_unknown"],
    },
    "required_stage3_columns": [
        "record_id", "sample_id", "sample_date", "sample_month",
        "station_id", "depth_m", "depth_round_m", "salinity",
        "temperature_insitu_c", "ta_best_umolkg", "ph_best", "ph_co2sys",
        "flag_any_carbonate_issue", "flag_any_carbonate_issue_strict",
    ],
    "expected_stage3_columns": [
        "cruise_id", "transect_id", "replicate_id", "pressure_output_dbar",
        "pco2_best_uatm", "dic_best_umol_kg", "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg", "co3_calc_umol_kg",
        "omega_aragonite_calc", "omega_calcite_calc",
        "ph_scale_observed_normalized", "ph_scale_calculated_normalized",
        "carbonate_solver", "carbon_input_pair_used",
        "ta_best_source", "ph_best_source", "ph_co2sys_source",
        "pco2_best_source", "dic_best_source",
        "flag_stage2_replicate_conflict_carried", "flag_solver_unknown",
        "flag_carbon_input_pair_unknown", "flag_dic_inconsistent",
        "flag_dic_inconsistent_robust", "flag_ph_scale_mismatch",
        "flag_ph_diag_mismatch", "flag_ph_diag_mismatch_strict",
        "flag_ph_diag_mismatch_robust",
    ],
    "duplicate_keys": [
        "sample_id", "sample_date", "station_id", "depth_round_m", "replicate_id",
    ],
    # Stage 4's range_policy is *wider* than Stage 1A/1B's: this is the
    # "could this physically be seawater chemistry?" check, not the
    # "is this typical open-ocean chemistry?" check. See oa_policy
    # docstring for the two-tier rationale.
    "range_policy": {
        "sal_min":   0.0,   "sal_max":   42.0,
        "temp_min": -2.0,   "temp_max":  40.0,
        "ph_min":    6.0,   "ph_max":     9.5,
        "ta_min":    0.0,   "ta_max":  3500.0,
        "dic_min":   0.0,   "dic_max": 3500.0,
        "pco2_min":  0.0,   "pco2_max": 10000.0,
        "omega_min": 0.0,   "omega_max":  20.0,
    },
    # Strict DIC species audit -- tighter than Stage 3's diagnostic version.
    # Stage 3 catches "values don't add up"; Stage 4 also requires the
    # units to be matching AND in an allow-list of equivalent strings.
    "dic_species_audit": {
        "enabled": True,
        "abs_tol_umolkg": 5.0,
        "rel_tol": 0.01,
        "require_matching_units": True,
    },
    "strict_dic_candidates": {
        "dic":   ["dic_best_umol_kg", "dic_calculated_umol_kg", "dic_calc", "dic", "DIC"],
        "co2aq": ["co2aq_calc_umol_kg", "co2aq", "CO2aq", "co2_aq", "aqueous_co2", "co2", "CO2"],
        "hco3":  ["hco3_calc_umol_kg", "hco3", "HCO3", "hco3-", "HCO3-"],
        "co3":   ["co3_calc_umol_kg", "co3", "CO3", "co3-", "CO3-"],
        "dic_unit":   ["dic_unit_normalized", "dic_unit", "DIC_unit"],
        "co2aq_unit": ["co2aq_unit_normalized", "co2aq_unit", "CO2aq_unit", "co2_unit", "CO2_unit"],
        "hco3_unit":  ["hco3_unit_normalized", "hco3_unit", "HCO3_unit"],
        "co3_unit":   ["co3_unit_normalized", "co3_unit", "CO3_unit"],
    },
    # All these strings get treated as equivalent to umol/kg for the
    # strict audit. Allows downstream rows to differ in typography
    # (umol/kg vs UMOLKG vs micromol/kg) without firing a mismatch.
    "unit_equivalents": [
        "UMOL/KG", "UMOLKG", "UMOLKG-1", "UMOLKG^-1",
        "UMOL/KG-1", "MICROMOL/KG", "MICROMOLKG", "UMOLKG1",
    ],
}


# Module-level constant: which columns are "identifiers" worth attaching
# to a long-format output row. The long-format range_flags table and the
# missing_key_rows table both use this.
_ID_COLS: List[str] = [
    "record_id", "sample_id", "cruise_id", "transect_id",
    "station_id", "replicate_id",
    "depth_round_m", "sample_date", "sample_month",
]


# ===========================================================================
# Coerce and standardise
# ===========================================================================

_NUMERIC_COLS = [
    "depth_m", "depth_round_m", "latitude_deg", "longitude_deg",
    "salinity", "temperature_measurement_c", "temperature_insitu_c",
    "pressure_measurement_dbar", "pressure_output_dbar",
    "ta_best_umolkg", "ph_best", "ph_co2sys", "pco2_best_uatm",
    "dic_best_umol_kg", "co2aq_calc_umol_kg", "hco3_calc_umol_kg",
    "co3_calc_umol_kg", "omega_aragonite_calc", "omega_calcite_calc",
]

_STRING_COLS = [
    "record_id", "sample_id", "cruise_id", "transect_id",
    "station_id", "replicate_id",
    "carbonate_solver", "carbon_input_pair_used",
    "ta_best_source", "ph_best_source", "ph_co2sys_source",
    "pco2_best_source", "dic_best_source",
]

# Boolean flags inherited from Stage 3 that we need to coerce to a
# non-null `boolean` dtype so downstream `.fillna(False)` is reliable.
_INHERITED_BOOL_COLS = [
    "flag_dic_inconsistent", "flag_dic_inconsistent_robust",
    "flag_ph_scale_mismatch", "flag_ph_diag_mismatch",
    "flag_ph_diag_mismatch_strict", "flag_ph_diag_mismatch_robust",
    "flag_any_carbonate_issue", "flag_any_carbonate_issue_strict",
    "flag_stage2_replicate_conflict_carried",
    "flag_solver_unknown", "flag_carbon_input_pair_unknown",
]


def coerce_and_standardize(df: pd.DataFrame, notes: List[str]) -> pd.DataFrame:
    """In a copy of `df`: coerce numerics, parse dates, normalise units/scales.

    Adds `year` and (re)derives `sample_month` from `sample_date`. Adds
    `lat` / `lon` as plain aliases of `latitude_deg` / `longitude_deg`.
    Re-runs `normalize_ph_scale` and `normalize_carbonate_unit` on the
    relevant columns (defensive: Stage 1B/3 should have done this
    already, but Stage 4 should also work on a non-Stage-3 input).
    Forces all `_INHERITED_BOOL_COLS` to be `boolean` dtype with no NAs
    so `.fillna(False) | ...` chains behave consistently.
    """
    out = df.copy()

    if "sample_date" in out.columns:
        out["sample_date"] = pd.to_datetime(out["sample_date"], errors="coerce")
        out["year"] = out["sample_date"].dt.year.astype("Int64")
        out["sample_month"] = out["sample_date"].dt.to_period("M").astype("string")
    else:
        out["sample_date"] = pd.NaT
        out["year"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        out["sample_month"] = empty_string_series(out.index)
        notes.append("No sample_date found. year and sample_month set to missing.")

    for c in _NUMERIC_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    # If Stage 2/3 didn't carry depth_round_m, derive it from depth_m.
    if "depth_round_m" not in out.columns or out["depth_round_m"].isna().all():
        if "depth_m" in out.columns:
            out["depth_round_m"] = pd.to_numeric(out["depth_m"], errors="coerce")
        else:
            out["depth_round_m"] = empty_float_series(out.index)

    out["lat"] = (
        out["latitude_deg"] if "latitude_deg" in out.columns
        else empty_float_series(out.index)
    )
    out["lon"] = (
        out["longitude_deg"] if "longitude_deg" in out.columns
        else empty_float_series(out.index)
    )

    for c in _STRING_COLS:
        if c in out.columns:
            out[c] = safe_str_series(out[c]).replace("", pd.NA)

    for c in ["ph_scale_observed_normalized", "ph_scale_calculated_normalized"]:
        if c in out.columns:
            out[c] = out[c].map(normalize_ph_scale).astype("string")
        else:
            out[c] = empty_string_series(out.index)

    for c in ["dic_unit_normalized", "co2aq_unit_normalized",
              "hco3_unit_normalized", "co3_unit_normalized"]:
        if c in out.columns:
            out[c] = out[c].map(normalize_carbonate_unit).astype("string")
        else:
            out[c] = empty_string_series(out.index)

    for c in _INHERITED_BOOL_COLS:
        if c in out.columns:
            out[c] = out[c].fillna(False).astype("boolean")
        else:
            out[c] = pd.Series(False, index=out.index, dtype="boolean")

    return out


# ===========================================================================
# Key completeness and duplicate checks
# ===========================================================================

def missing_key_rows(df: pd.DataFrame, keys: List[str]) -> pd.DataFrame:
    """Rows where any of the named key columns is missing.

    Returns a frame with `_ID_COLS` (the ones that exist) plus one
    `flag_missing_key__<keyname>` column per key. Empty string is
    treated as missing for non-datetime columns.
    """
    present = [k for k in keys if k in df.columns]
    if not present:
        return pd.DataFrame()

    flags = pd.DataFrame(index=df.index)
    for k in present:
        if pd.api.types.is_datetime64_any_dtype(df[k]):
            flags[f"flag_missing_key__{k}"] = df[k].isna()
        else:
            flags[f"flag_missing_key__{k}"] = (
                safe_str_series(df[k]).eq("") | df[k].isna()
            )

    any_missing = flags.any(axis=1)
    id_cols = [c for c in _ID_COLS if c in df.columns]
    return pd.concat(
        [df.loc[any_missing, id_cols], flags.loc[any_missing]],
        axis=1,
    ).copy()


def detect_duplicates(
    df: pd.DataFrame, keys: List[str]
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """Stage-4 duplicate detection: requires all keys to be NON-NULL.

    This is stricter than Stage 2's duplicate check by design. Stage 2's
    flag is advisory and works on partial-key collisions (so it catches
    rows that *look* like duplicates even when some IDs are missing).
    Stage 4's check is the FAIL gate: we only consider two rows duplicate
    if every key column for both rows is non-null AND the values match.
    Rows with any null in the key tuple fall through to the missing-key
    check instead.

    Returns `(duplicate_rows_df, messages, keys_used)`.
    """
    present = [k for k in keys if k in df.columns]
    missing = [k for k in keys if k not in df.columns]

    if not present:
        return pd.DataFrame(), [f"No key columns found among: {keys}"], present

    valid = pd.Series(True, index=df.index)
    for k in present:
        if pd.api.types.is_datetime64_any_dtype(df[k]):
            valid &= df[k].notna()
        else:
            valid &= ~(safe_str_series(df[k]).eq("") | df[k].isna())

    dup_mask = df.duplicated(subset=present, keep=False) & valid
    msgs: List[str] = []
    if missing:
        msgs.append(f"Keys not found (ignored): {missing}")
    msgs.append(f"Keys used: {present}")
    return df.loc[dup_mask].copy(), msgs, present


# ===========================================================================
# Range checks (long-format output)
# ===========================================================================

def run_range_checks(
    df: pd.DataFrame, policy: "RangePolicyType",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Long-format range-check output.

    Unlike Stages 1A/1B (which add `flag_*_out_of_range` *columns* to
    the row-level frame), Stage 4 produces:

    1. A summary: one row per logical variable, with min/max bounds,
       count of valid values, count of flagged.
    2. A long table: one row per (row_index, variable, direction)
       violation, with the offending value and the ID columns
       attached.

    Long format is the right shape for the analyst-facing tooling:
    "show me every salinity below 30" is one filter; the row-level
    flag columns would require unpivoting first.

    `policy` is `oa_policy.RangePolicy`; we type-hint it as a string
    forward reference to avoid a hard import at module-load time
    (callers always pass a real one).
    """
    checks = [
        (["salinity"],                                            policy.sal_min,   policy.sal_max,   "salinity"),
        (["temperature_insitu_c", "temperature_measurement_c"],    policy.temp_min,  policy.temp_max,  "temperature"),
        (["ph_best"],                                              policy.ph_min,    policy.ph_max,    "observed_ph"),
        (["ph_co2sys"],                                            policy.ph_min,    policy.ph_max,    "co2sys_ph"),
        (["ta_best_umolkg"],                                       policy.ta_min,    policy.ta_max,    "alkalinity"),
        (["dic_best_umol_kg"],                                     policy.dic_min,   policy.dic_max,   "dic"),
        (["pco2_best_uatm"],                                       policy.pco2_min,  policy.pco2_max,  "pco2"),
        (["omega_aragonite_calc"],                                 policy.omega_min, policy.omega_max, "omega_aragonite"),
        (["omega_calcite_calc"],                                   policy.omega_min, policy.omega_max, "omega_calcite"),
    ]

    id_cols = [c for c in _ID_COLS if c in df.columns]
    summary_rows: List[dict] = []
    flag_rows: List[dict] = []

    for candidates, lo, hi, name in checks:
        col = first_existing(df, candidates)
        if col is None:
            continue

        x = pd.to_numeric(df[col], errors="coerce")
        n_lo = int((x < lo).sum())
        n_hi = int((x > hi).sum())

        summary_rows.append({
            "logical_variable": name,
            "column_used": col,
            "min_allowed": lo,
            "max_allowed": hi,
            "n": len(df),
            "n_valid": int(x.notna().sum()),
            "n_flagged": n_lo + n_hi,
        })

        for direction, mask in [("below_min", x < lo), ("above_max", x > hi)]:
            for idx in df.index[mask]:
                row = {
                    "row_index": int(idx),
                    "logical_variable": name,
                    "column_used": col,
                    "value": float(x.loc[idx]),
                    "flag": direction,
                }
                for c in id_cols:
                    row[c] = df.loc[idx, c]
                flag_rows.append(row)

    return pd.DataFrame(summary_rows), pd.DataFrame(flag_rows)


# ===========================================================================
# Strict DIC vs species audit
# ===========================================================================

@dataclass
class DicSpeciesAudit:
    """Thresholds for the *strict* DIC vs species check.

    Stricter than Stage 3's diagnostic version because:

    1. `abs_tol_umolkg` defaults to 5 (vs Stage 3's 10) -- this is a
       cross-validation gate, not a screening diagnostic.
    2. `require_matching_units` defaults to True -- if the four species
       columns disagree on units OR fall outside `unit_equivalents`,
       we don't even attempt the species-sum check; we flag the unit
       situation instead.

    A "unit equivalents" allow-list lets the same physical unit be
    written several typographical ways (UMOL/KG, UMOLKG, MICROMOL/KG,
    etc.) without firing a mismatch.
    """
    abs_tol_umolkg: float = 5.0
    rel_tol:        float = 0.01
    require_matching_units: bool = True


def dic_species_audit(
    df: pd.DataFrame,
    check: DicSpeciesAudit,
    candidates: Dict[str, List[str]],
    unit_equivalents: set,
) -> Tuple[pd.DataFrame, str, Dict[str, Optional[str]]]:
    """Run the strict DIC vs species audit.

    Returns `(result_df, note_string, column_metadata)`:

    * `result_df` has one row per input row, with the resolved values
      `dic_best_umol_kg`, `co2aq_calc_umol_kg`, `hco3_calc_umol_kg`,
      `co3_calc_umol_kg`, the computed `dic_species_sum`, `dic_minus_sum`,
      `dic_sum_tol`, and three boolean flags:
        - `flag_dic_species_audit_strict`        -- species sum check failed
        - `flag_dic_species_unit_mismatch_audit` -- units disagree or off-list
        - `flag_dic_species_unit_missing_audit`  -- units missing
    * `note_string` for the report ("Ran strict DIC vs species audit:
      abs_tol=..., rel_tol=...").
    * `column_metadata` records which source columns the audit actually
      used, for the manifest.

    If any of the four species value columns is missing, the audit is
    skipped and an empty-result frame is returned.
    """
    dic_c  = first_existing(df, candidates.get("dic", []))
    co2_c  = first_existing(df, candidates.get("co2aq", []))
    hco3_c = first_existing(df, candidates.get("hco3", []))
    co3_c  = first_existing(df, candidates.get("co3", []))
    du_c   = first_existing(df, candidates.get("dic_unit", []))
    co2u_c = first_existing(df, candidates.get("co2aq_unit", []))
    hco3u_c = first_existing(df, candidates.get("hco3_unit", []))
    co3u_c  = first_existing(df, candidates.get("co3_unit", []))

    colmeta = {
        "dic_col": dic_c,    "co2aq_col": co2_c,
        "hco3_col": hco3_c,  "co3_col": co3_c,
        "dic_unit_col": du_c,    "co2aq_unit_col": co2u_c,
        "hco3_unit_col": hco3u_c, "co3_unit_col": co3u_c,
    }

    if not all([dic_c, co2_c, hco3_c, co3_c]):
        empty = pd.DataFrame({
            "flag_dic_species_audit_strict":        empty_bool_series(df.index),
            "flag_dic_species_unit_mismatch_audit": empty_bool_series(df.index),
            "flag_dic_species_unit_missing_audit":  empty_bool_series(df.index),
        })
        # All-false (not all-NA), so the readiness classifier sees them cleanly.
        for c in empty.columns:
            empty[c] = pd.Series(False, index=df.index, dtype="boolean")
        return empty, "Skipped: one or more required species columns missing.", colmeta

    dic  = pd.to_numeric(df[dic_c],  errors="coerce")
    co2  = pd.to_numeric(df[co2_c],  errors="coerce")
    hco3 = pd.to_numeric(df[hco3_c], errors="coerce")
    co3  = pd.to_numeric(df[co3_c],  errors="coerce")
    vals_ok = dic.notna() & co2.notna() & hco3.notna() & co3.notna()

    unit_missing  = pd.Series(False, index=df.index, dtype="boolean")
    unit_mismatch = pd.Series(False, index=df.index, dtype="boolean")

    if check.require_matching_units and all([du_c, co2u_c, hco3u_c, co3u_c]):
        du   = df[du_c].map(normalize_carbonate_unit).astype("string")
        co2u = df[co2u_c].map(normalize_carbonate_unit).astype("string")
        hco3u = df[hco3u_c].map(normalize_carbonate_unit).astype("string")
        co3u  = df[co3u_c].map(normalize_carbonate_unit).astype("string")

        known = du.notna() & co2u.notna() & hco3u.notna() & co3u.notna()
        allowed = (
            du.isin(unit_equivalents)
            & co2u.isin(unit_equivalents)
            & hco3u.isin(unit_equivalents)
            & co3u.isin(unit_equivalents)
        )
        same = (du == co2u) & (du == hco3u) & (du == co3u)

        unit_missing  = (vals_ok & ~known).astype("boolean")
        unit_mismatch = (known & (~same | ~allowed)).astype("boolean")
    elif check.require_matching_units:
        # require_matching_units was requested but the unit columns are
        # missing -- treat every row as "unit unknown" rather than
        # silently letting the check proceed.
        unit_missing = vals_ok.astype("boolean")

    checkable = vals_ok & ~unit_missing.fillna(False) & ~unit_mismatch.fillna(False)
    species_sum = co2 + hco3 + co3
    diff = dic - species_sum
    # tol = max(|DIC|*rel_tol, abs_tol_umolkg) row-wise.
    tol = (dic.abs() * check.rel_tol).combine(
        pd.Series(check.abs_tol_umolkg, index=df.index), max
    )
    strict_fail = (checkable & (diff.abs() > tol)).astype("boolean")

    result = pd.DataFrame(
        {
            "dic_best_umol_kg": dic,
            "co2aq_calc_umol_kg": co2,
            "hco3_calc_umol_kg": hco3,
            "co3_calc_umol_kg": co3,
            "dic_species_sum": species_sum,
            "dic_minus_sum": diff,
            "dic_sum_tol": tol,
            "flag_dic_species_audit_strict": strict_fail,
            "flag_dic_species_unit_mismatch_audit": unit_mismatch,
            "flag_dic_species_unit_missing_audit": unit_missing,
        },
        index=df.index,
    )

    note = (
        f"Ran strict DIC vs species audit: abs_tol={check.abs_tol_umolkg} umol/kg, "
        f"rel_tol={check.rel_tol * 100:.1f}%."
    )
    return result, note, colmeta


# ===========================================================================
# Readiness classification (the PASS/REVIEW/FAIL gate)
# ===========================================================================

def _bcol(df: pd.DataFrame, name: str) -> pd.Series:
    """Get a boolean column safely: missing -> all-False; NaN -> False."""
    if name in df.columns:
        return df[name].fillna(False).astype("boolean")
    return pd.Series(False, index=df.index, dtype="boolean")


def add_readiness_status(
    df: pd.DataFrame,
    dup_table: pd.DataFrame,
    missing_key_idx: pd.Index,
) -> pd.DataFrame:
    """Assign `analysis_audit_status` (PASS / REVIEW / FAIL) per row.

    Severity ladder:
      * **FAIL** -- any of: missing required key, Stage 3 strict carbonate
        issue, strict DIC species-sum fail, DIC unit mismatch, unknown
        solver, unknown carbon input pair.
      * **REVIEW** -- any of: duplicate complete-key row, range flag,
        Stage 3 (non-strict) carbonate issue, Stage 2 replicate conflict
        carried, DIC unit *missing* (vs mismatched), Stage 3 robust DIC
        outlier, Stage 3 pH diagnostic mismatch (threshold or robust).
      * **PASS** otherwise.

    Each row also gets:
      - `analysis_audit_reason_fail`   -- semicolon-joined reason codes
      - `analysis_audit_reason_review` -- semicolon-joined reason codes
      - `analysis_audit_reason_codes`  -- the union of the above

    Reason codes are short strings (`missing_key`, `range_flag`,
    `stage3_strict_issue`, etc.); the union is the column an analyst
    filters on. The split fail-vs-review columns let you see *why* a
    row got each tier of verdict.

    The taxonomy follows the PASS/WARN/FAIL "quality gate" pattern
    (NDepend; testRigor; UN/ABS Data Quality Manual Part B). We use
    REVIEW for the middle tier because that is what an analyst
    actually does -- review, then decide.
    """
    out = df.copy()

    # Initialise the eleven audit-side flags.
    out["flag_audit_missing_key"]            = pd.Series(False, index=out.index, dtype="boolean")
    out["flag_audit_duplicate_complete_key"] = pd.Series(False, index=out.index, dtype="boolean")
    # range_flag_count might be absent (range checks disabled or
    # produced zero violations). Treat missing as zero.
    if "range_flag_count" in out.columns:
        rfc = pd.to_numeric(out["range_flag_count"], errors="coerce").fillna(0)
    else:
        rfc = pd.Series(0, index=out.index)
    out["flag_audit_range_issue"] = (rfc > 0).astype("boolean")
    out["flag_audit_stage3_issue"]         = _bcol(out, "flag_any_carbonate_issue")
    out["flag_audit_stage3_issue_strict"]  = _bcol(out, "flag_any_carbonate_issue_strict")
    out["flag_audit_replicate_conflict"]   = _bcol(out, "flag_stage2_replicate_conflict_carried")
    out["flag_audit_unknown_solver"]       = _bcol(out, "flag_solver_unknown")
    out["flag_audit_unknown_input_pair"]   = _bcol(out, "flag_carbon_input_pair_unknown")
    out["flag_audit_strict_dic_fail"]      = _bcol(out, "flag_dic_species_audit_strict")
    out["flag_audit_dic_unit_mismatch"]    = _bcol(out, "flag_dic_species_unit_mismatch_audit")
    out["flag_audit_dic_unit_missing"]     = _bcol(out, "flag_dic_species_unit_missing_audit")

    if len(missing_key_idx):
        out.loc[missing_key_idx, "flag_audit_missing_key"] = True
    if not dup_table.empty:
        out.loc[dup_table.index, "flag_audit_duplicate_complete_key"] = True

    severe = (
        out["flag_audit_missing_key"]
        | out["flag_audit_stage3_issue_strict"]
        | out["flag_audit_strict_dic_fail"]
        | out["flag_audit_dic_unit_mismatch"]
        | out["flag_audit_unknown_solver"]
        | out["flag_audit_unknown_input_pair"]
    ).fillna(False)

    review = (
        out["flag_audit_duplicate_complete_key"]
        | out["flag_audit_range_issue"]
        | out["flag_audit_stage3_issue"]
        | out["flag_audit_replicate_conflict"]
        | out["flag_audit_dic_unit_missing"]
        | _bcol(out, "flag_dic_inconsistent_robust")
        | _bcol(out, "flag_ph_diag_mismatch")
        | _bcol(out, "flag_ph_diag_mismatch_robust")
    ).fillna(False)

    # Reason-code mappings. Order matters only for human readability;
    # the codes are sorted alphabetically in the output.
    fail_def = [
        ("flag_audit_missing_key",           "missing_key"),
        ("flag_audit_stage3_issue_strict",   "stage3_strict_issue"),
        ("flag_audit_strict_dic_fail",       "strict_dic_species_fail"),
        ("flag_audit_dic_unit_mismatch",     "strict_dic_unit_mismatch"),
        ("flag_audit_unknown_solver",        "unknown_solver"),
        ("flag_audit_unknown_input_pair",    "unknown_input_pair"),
    ]
    review_def = [
        ("flag_audit_duplicate_complete_key", "duplicate_complete_key"),
        ("flag_audit_range_issue",            "range_flag"),
        ("flag_audit_stage3_issue",           "stage3_issue"),
        ("flag_audit_replicate_conflict",     "replicate_conflict_carried"),
        ("flag_audit_dic_unit_missing",       "strict_dic_unit_missing"),
        ("flag_dic_inconsistent_robust",      "dic_robust_issue"),
        ("flag_ph_diag_mismatch",             "ph_diag_issue"),
        ("flag_ph_diag_mismatch_robust",      "ph_diag_robust_issue"),
    ]

    n = len(out)
    fail_codes: List[List[str]] = [[] for _ in range(n)]
    review_codes: List[List[str]] = [[] for _ in range(n)]
    # Index -> positional offset, for safe in-place updates regardless
    # of the original index type.
    pos = {idx: i for i, idx in enumerate(out.index)}

    for flag_col, code in fail_def:
        for idx in out.index[_bcol(out, flag_col)]:
            fail_codes[pos[idx]].append(code)

    for flag_col, code in review_def:
        for idx in out.index[_bcol(out, flag_col)]:
            review_codes[pos[idx]].append(code)

    out["analysis_audit_reason_fail"] = pd.Series(
        [";".join(sorted(set(x))) or pd.NA for x in fail_codes],
        index=out.index, dtype="string",
    )
    out["analysis_audit_reason_review"] = pd.Series(
        [";".join(sorted(set(x))) or pd.NA for x in review_codes],
        index=out.index, dtype="string",
    )
    out["analysis_audit_reason_codes"] = pd.Series(
        [";".join(sorted(set(f + r))) or pd.NA for f, r in zip(fail_codes, review_codes)],
        index=out.index, dtype="string",
    )

    status = pd.Series("PASS", index=out.index, dtype="string")
    status[review] = "REVIEW"
    status[severe] = "FAIL"  # severe wins over review where both fire
    out["analysis_audit_status"] = status

    return out


def reason_count_table(
    df: pd.DataFrame, col: str = "analysis_audit_reason_codes",
) -> pd.DataFrame:
    """Histogram of the semicolon-joined reason codes in `col`.

    Returns a two-column frame: `reason_code`, `count`, sorted by count
    descending. Useful for the manifest's `reason_code_counts` field and
    the markdown report's reason-summary section.

    An empty `col` (or an all-NA column) yields an empty frame, not an
    error -- a "perfect" dataset with zero flagged rows should produce
    an empty histogram, not crash.
    """
    if col not in df.columns:
        return pd.DataFrame(columns=["reason_code", "count"])

    s = (
        df[col].dropna().astype("string")
        .str.split(";").explode()
        .dropna().str.strip()
    )
    s = s[s.ne("")]
    if s.empty:
        return pd.DataFrame(columns=["reason_code", "count"])

    return s.value_counts().rename_axis("reason_code").reset_index(name="count")
