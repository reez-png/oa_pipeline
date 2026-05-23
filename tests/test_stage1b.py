"""
tests/test_stage1b.py
=====================
Focused unit tests for Stage 1B helper logic.

These tests protect Stage 1B behaviours that are important for downstream
Stage 3 and Stage 4 audit logic:

1. Existing carbonate solver provenance is preserved.
2. Missing pH QC status does not block all rows by default.
3. Accepted pH scale labels are normalised before comparison.
4. pH standard fallback values are not misclassified as corrected pH.
5. Absent optional range columns are treated as not assessed, not missing.
6. Common DIC and pCO2 aliases are accepted by best field coalescing.
"""

from __future__ import annotations

import copy

import pandas as pd

from oa_pipeline.policy import RangePolicy
from oa_pipeline.stage1b import (
    STAGE1B_DEFAULTS,
    add_analysis_range_flags,
    add_best_analysis_fields,
    add_presence_flags,
    add_provenance_fields,
    add_scale_flags,
    add_status_normalizations,
    analysis_ready_subset,
)


# =============================================================================
# Small helpers
# =============================================================================


def _config() -> dict:
    """Return a deep copy so tests cannot mutate shared defaults."""
    return copy.deepcopy(STAGE1B_DEFAULTS)


# =============================================================================
# Provenance preservation
# =============================================================================


def test_stage1b_preserves_existing_carbonate_solver_metadata() -> None:
    """Stage 1B must not erase existing solver and input pair provenance."""
    df = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "ta": [2300.0],
            "pH_lab": [8.05],
            "salinity": [35.0],
            "temperature_insitu_c": [25.0],
            "ta_units": ["umol/kg"],
            "ph_scale_observed": ["total"],
            "carbonate_solver": ["synthetic_example_generator"],
            "carbon_input_pair_used": ["TA + pH_observed"],
        }
    )

    config = _config()

    add_best_analysis_fields(df, config)
    add_status_normalizations(df, config)
    add_provenance_fields(df, config)

    assert df.loc[0, "carbonate_solver"] == "synthetic_example_generator"
    assert df.loc[0, "carbon_input_pair_used"] == "TA + pH_observed"


def test_stage1b_does_not_invent_solver_metadata_by_default() -> None:
    """Missing solver provenance should remain missing unless explicitly configured."""
    df = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "ta": [2300.0],
            "pH_lab": [8.05],
            "salinity": [35.0],
            "temperature_insitu_c": [25.0],
            "ta_units": ["umol/kg"],
            "ph_scale_observed": ["total"],
        }
    )

    config = _config()

    add_best_analysis_fields(df, config)
    add_status_normalizations(df, config)
    add_provenance_fields(df, config)

    assert "carbonate_solver" in df.columns
    assert "carbon_input_pair_used" in df.columns
    assert pd.isna(df.loc[0, "carbonate_solver"])
    assert pd.isna(df.loc[0, "carbon_input_pair_used"])


# =============================================================================
# QC gate behaviour
# =============================================================================


def test_missing_ph_qc_status_does_not_block_all_rows_by_default() -> None:
    """The default QC gate should require TA status but not absent pH status."""
    df = pd.DataFrame(
        {
            "is_sample_row": [True],
            "ta_qc_status_norm": ["NO_ADJUST"],
            "ta_best_umolkg": [2300.0],
            "ph_best": [8.05],
            "salinity": [35.0],
            "calc_temperature_c": [25.0],
            "ta_units_normalized": ["umol kg-1"],
            "ph_scale_observed_normalized": ["total"],
            "flag_core_chemistry_missing": [False],
        }
    )

    out = analysis_ready_subset(df, _config())

    assert bool(out.loc[0, "safe_for_analysis_qc"])


def test_required_ph_qc_status_can_be_enabled_by_config() -> None:
    """Users can still make pH QC status mandatory through analysis_policy."""
    config = _config()
    config["analysis_policy"]["required_qc_status_norm_columns"] = [
        "ta_qc_status_norm",
        "ph_qc_status_norm",
    ]

    df = pd.DataFrame(
        {
            "is_sample_row": [True],
            "ta_qc_status_norm": ["NO_ADJUST"],
            "ta_best_umolkg": [2300.0],
            "ph_best": [8.05],
            "salinity": [35.0],
            "calc_temperature_c": [25.0],
            "ta_units_normalized": ["umol kg-1"],
            "ph_scale_observed_normalized": ["total"],
            "flag_core_chemistry_missing": [False],
        }
    )

    out = analysis_ready_subset(df, config)

    assert not bool(out.loc[0, "safe_for_analysis_qc"])


# =============================================================================
# pH scale handling
# =============================================================================


def test_accepted_ph_scales_are_normalized() -> None:
    """Configured pH scale labels should be normalised before comparison."""
    df = pd.DataFrame(
        {
            "ph_best": [8.05],
            "ph_scale_observed_normalized": ["total"],
            "ph_co2sys": [8.04],
            "ph_scale_calculated_normalized": ["total"],
        }
    )

    add_scale_flags(df, accepted_observed_scales=["TOTAL"])

    assert not bool(df.loc[0, "flag_ph_scale_observed_unexpected"])


# =============================================================================
# pH standard correction source tracking
# =============================================================================


def test_phstd_original_fallback_is_not_treated_as_corrected_ph() -> None:
    """A copied original pH fallback should not count as corrected pH."""
    df = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "ta": [2300.0],
            "ph_corrected_from_phstd": [8.05],
            "phstd_correction_applied": [False],
            "phstd_status_norm": ["FAIL"],
            "salinity": [35.0],
            "temperature_insitu_c": [25.0],
            "ta_units": ["umol/kg"],
            "ph_scale_observed": ["total"],
            "ta_qc_status_norm": ["NO_ADJUST"],
        }
    )

    config = _config()
    config["analysis_policy"]["phstd_fail_blocks_corrected_ph"] = True

    add_best_analysis_fields(df, config)
    add_status_normalizations(df, config)
    add_provenance_fields(df, config)
    add_presence_flags(df)

    out = analysis_ready_subset(df, config)

    assert df.loc[0, "ph_best_source"] == "ph_after_phstd_qc"
    assert df.loc[0, "ph_best_correction_status_source"] == "phstd_original_fallback"
    assert not bool(out.loc[0, "ph_best_from_corrected"])
    assert bool(out.loc[0, "safe_for_analysis_qc"])


def test_phstd_corrected_value_is_tracked_as_corrected_ph() -> None:
    """A true pH standard corrected value should be identifiable downstream."""
    df = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "ta": [2300.0],
            "ph_corrected_from_phstd": [8.06],
            "phstd_correction_applied": [True],
            "phstd_status_norm": ["OK"],
            "salinity": [35.0],
            "temperature_insitu_c": [25.0],
            "ta_units": ["umol/kg"],
            "ph_scale_observed": ["total"],
            "ta_qc_status_norm": ["NO_ADJUST"],
        }
    )

    config = _config()

    add_best_analysis_fields(df, config)
    add_status_normalizations(df, config)
    add_provenance_fields(df, config)
    add_presence_flags(df)

    out = analysis_ready_subset(df, config)

    assert df.loc[0, "ph_best_source"] == "ph_after_phstd_qc"
    assert df.loc[0, "ph_best_correction_status_source"] == "phstd_corrected"
    assert bool(out.loc[0, "ph_best_from_corrected"])


# =============================================================================
# Range flags
# =============================================================================


def test_absent_optional_range_columns_are_not_marked_missing() -> None:
    """Absent optional range fields should be not assessed, not row level missing."""
    df = pd.DataFrame(
        {
            "ta_best_umolkg": [2300.0],
            "ph_best": [8.05],
            "salinity": [35.0],
            "calc_temperature_c": [25.0],
        }
    )

    add_analysis_range_flags(df, RangePolicy())

    assert not bool(df.loc[0, "flag_ph_co2sys_missing"])
    assert not bool(df.loc[0, "flag_ph_co2sys_non_numeric"])
    assert not bool(df.loc[0, "flag_ph_co2sys_out_of_range"])


# =============================================================================
# Alias expansion
# =============================================================================


def test_stage1b_accepts_common_dic_and_pco2_aliases() -> None:
    """Common DIC and pCO2 names should populate Stage 1B best fields."""
    df = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "ta": [2300.0],
            "pH_lab": [8.05],
            "DIC": [2050.0],
            "pCO2": [420.0],
        }
    )

    add_best_analysis_fields(df, _config())

    assert df.loc[0, "dic_best_umol_kg"] == 2050.0
    assert df.loc[0, "dic_best_source"] == "DIC"
    assert df.loc[0, "pco2_best_uatm"] == 420.0
    assert df.loc[0, "pco2_best_source"] == "pCO2"
