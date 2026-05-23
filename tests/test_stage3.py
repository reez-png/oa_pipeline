"""
tests/test_stage3.py
====================
Focused unit tests for Stage 3 carbonate integrity diagnostics.

These tests protect Stage 3 behaviours that are important for scientific
traceability and downstream Stage 4 verdicts:

1. Stage 3 does not invent carbonate solver provenance by default.
2. Optional provenance backfill only happens when explicitly enabled.
3. Accepted pH scales are normalised before comparison.
4. Non finite carbonate integrity thresholds are rejected.
5. DIC unit mismatch is detected after unit normalisation.
6. DIC species aliases are intentionally strict and do not accept ambiguous
   plain CO2, HCO3, and CO3 names by default.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_pipeline.stage3 import (
    STAGE3_DEFAULTS,
    CarbonateIntegrityThresholds,
    add_canonical_helper_columns,
    carbonate_integrity_checks,
)


# =============================================================================
# Small helpers
# =============================================================================


def _missing_like(value: object) -> bool:
    """Return True for pd.NA, None, nan, or blank strings."""
    if pd.isna(value):
        return True
    return str(value).strip() == ""


# =============================================================================
# Provenance backfill
# =============================================================================


def test_stage3_does_not_backfill_solver_by_default() -> None:
    """Stage 3 should flag missing solver provenance rather than inventing it."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "sample_date": ["2024-01-01"],
            "station_id": ["ST01"],
            "depth_m": [10.0],
            "ph_co2sys": [8.04],
            "pco2_best_uatm": [420.0],
        }
    )
    notes: list[str] = []

    out = add_canonical_helper_columns(df, notes)

    assert bool(out.loc[0, "has_calculated_carbonate_output"])
    assert _missing_like(out.loc[0, "carbonate_solver"])
    assert _missing_like(out.loc[0, "carbon_input_pair_used"])
    assert bool(out.loc[0, "flag_solver_unknown"])
    assert bool(out.loc[0, "flag_carbon_input_pair_unknown"])
    assert not any("Backfilled carbonate_solver" in note for note in notes)


def test_stage3_backfills_solver_only_when_explicitly_enabled() -> None:
    """Optional provenance backfill should be opt in and configurable."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "sample_date": ["2024-01-01"],
            "station_id": ["ST01"],
            "depth_m": [10.0],
            "ph_co2sys": [8.04],
            "pco2_best_uatm": [420.0],
        }
    )
    notes: list[str] = []

    out = add_canonical_helper_columns(
        df,
        notes,
        provenance_backfill={
            "enabled": True,
            "solver": "synthetic_example_generator",
            "input_pair": "synthetic TA + pH_best",
        },
    )

    assert out.loc[0, "carbonate_solver"] == "synthetic_example_generator"
    assert out.loc[0, "carbon_input_pair_used"] == "synthetic TA + pH_best"
    assert not bool(out.loc[0, "flag_solver_unknown"])
    assert not bool(out.loc[0, "flag_carbon_input_pair_unknown"])
    assert any("Backfilled carbonate_solver" in note for note in notes)


# =============================================================================
# pH scale handling
# =============================================================================


def test_accepted_ph_scales_are_normalized_in_stage3() -> None:
    """Configured accepted pH scales should pass through normalize_ph_scale."""
    df = pd.DataFrame(
        {
            "ph_best": [8.05],
            "ph_co2sys": [8.04],
            "ph_scale_observed_normalized": ["total"],
            "ph_scale_calculated_normalized": ["total"],
        }
    )

    thr = CarbonateIntegrityThresholds()
    flags, summary, _, _ = carbonate_integrity_checks(
        df,
        thr,
        accepted_ph_scales=["TOTAL"],
    )

    assert not bool(flags.loc[0, "flag_ph_best_scale_unexpected"])
    assert not bool(flags.loc[0, "flag_ph_co2sys_scale_unexpected"])
    assert summary["n_ph_best_scale_unexpected"] == 0
    assert summary["n_ph_co2sys_scale_unexpected"] == 0


# =============================================================================
# Threshold validation
# =============================================================================


def test_stage3_rejects_nonfinite_thresholds() -> None:
    """Carbonate integrity thresholds must be finite numeric values."""
    with pytest.raises(ValueError):
        CarbonateIntegrityThresholds(dic_abs_tol=float("nan"))

    with pytest.raises(ValueError):
        CarbonateIntegrityThresholds(ph_diag_tol=float("inf"))

    with pytest.raises(ValueError):
        CarbonateIntegrityThresholds(dic_mad_k=float("-inf"))


# =============================================================================
# DIC unit handling
# =============================================================================


def test_dic_unit_mismatch_detected_after_normalization() -> None:
    """Compatible spellings should normalize, but incompatible units should mismatch."""
    df = pd.DataFrame(
        {
            "dic_best_umol_kg": [2000.0],
            "co2aq_calc_umol_kg": [10.0],
            "hco3_calc_umol_kg": [1800.0],
            "co3_calc_umol_kg": [190.0],
            "dic_unit_normalized": ["umol/kg"],
            "co2aq_unit_normalized": ["umol kg-1"],
            "hco3_unit_normalized": ["umol/kg"],
            "co3_unit_normalized": ["umol/L"],
        }
    )

    flags, summary, dic_mismatches, _ = carbonate_integrity_checks(
        df,
        CarbonateIntegrityThresholds(),
    )

    assert bool(flags.loc[0, "flag_dic_unit_mismatch"])
    assert not bool(flags.loc[0, "flag_dic_unit_missing"])
    assert summary["n_dic_unit_mismatch"] == 1
    assert len(dic_mismatches) == 1


def test_blank_dic_unit_is_missing_not_mismatch() -> None:
    """Blank species unit fields should be classified as missing unit context."""
    df = pd.DataFrame(
        {
            "dic_best_umol_kg": [2000.0],
            "co2aq_calc_umol_kg": [10.0],
            "hco3_calc_umol_kg": [1800.0],
            "co3_calc_umol_kg": [190.0],
            "dic_unit_normalized": ["umol/kg"],
            "co2aq_unit_normalized": ["umol/kg"],
            "hco3_unit_normalized": [""],
            "co3_unit_normalized": ["umol/kg"],
        }
    )

    flags, summary, _, _ = carbonate_integrity_checks(
        df,
        CarbonateIntegrityThresholds(),
    )

    assert bool(flags.loc[0, "flag_dic_unit_missing"])
    assert not bool(flags.loc[0, "flag_dic_unit_mismatch"])
    assert summary["n_dic_unit_missing"] == 1
    assert summary["n_dic_unit_mismatch"] == 0


# =============================================================================
# Strict carbonate species aliases
# =============================================================================


def test_stage3_species_aliases_do_not_accept_ambiguous_plain_names() -> None:
    """Plain CO2, HCO3, and CO3 should not materialise species columns by default."""
    aliases = STAGE3_DEFAULTS["canonical_aliases"]

    assert "CO2" not in aliases["co2aq_calc_umol_kg"]
    assert "co2" not in aliases["co2aq_calc_umol_kg"]
    assert "HCO3" not in aliases["hco3_calc_umol_kg"]
    assert "hco3" not in aliases["hco3_calc_umol_kg"]
    assert "CO3" not in aliases["co3_calc_umol_kg"]
    assert "co3" not in aliases["co3_calc_umol_kg"]


# =============================================================================
# Stage 3 review rollup
# =============================================================================


def test_stage3_review_rollup_includes_provenance_issues_without_strict_chemistry_fail() -> None:
    """Unknown solver should count as review issue but not strict chemistry issue."""
    df = pd.DataFrame(
        {
            "has_calculated_carbonate_output": [True],
            "flag_solver_unknown": [True],
            "flag_carbon_input_pair_unknown": [True],
        }
    )

    flags, summary, _, _ = carbonate_integrity_checks(
        df,
        CarbonateIntegrityThresholds(),
    )

    assert bool(flags.loc[0, "flag_any_stage3_review_issue"])
    assert not bool(flags.loc[0, "flag_any_carbonate_issue_strict"])
    assert summary["n_any_stage3_review_issue"] == 1
    assert summary["n_any_carbonate_issue_strict"] == 0
