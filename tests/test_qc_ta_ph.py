"""
tests/test_qc_ta_ph.py
======================
Focused unit tests for TA CRM and pH standard QC helpers.

These tests protect the scientific behaviour of oa_pipeline.qc_ta_ph:

1. TA SOP status mapping.
2. pH standard table interpolation and out of range handling.
3. Exclusion of TA CRM outliers from correction means.
4. Exclusion of pH standard outliers from correction means.
5. Enforcement of require_ta_value_for_crm.
6. Protection against correcting CRM rows themselves.
7. Preservation of original pH when pH correction is disabled or withheld.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from oa_pipeline.qc_ta_ph import (
    CRM_CERTIFIED_TA,
    PhStdStatusThresholds,
    TaSop,
    apply_ph_standard_qc_and_correction,
    apply_ta_crm_correction,
    apply_ta_sop_auto_rule,
    ph_standard_expected,
)


# =============================================================================
# Basic threshold helpers
# =============================================================================


def test_ta_sop_auto_rule_statuses() -> None:
    """TA SOP rule should map correction size to status and used correction."""
    sop = TaSop(no_adjust=2.0, reject=20.0)
    corr = pd.Series([pd.NA, 1.5, 5.0, 25.0], dtype="Float64")

    status, used = apply_ta_sop_auto_rule(corr, sop)

    assert status.tolist() == ["INSUFFICIENT_DATA", "NO_ADJUST", "ADJUST", "FAIL"]
    assert pd.isna(used.iloc[0])
    assert used.iloc[1] == 0.0
    assert used.iloc[2] == 5.0
    assert pd.isna(used.iloc[3])


def test_ph_standard_expected_interpolates_and_flags_out_of_range() -> None:
    """pH standard expected values should interpolate and flag out of range."""
    value, outside = ph_standard_expected("tris", 25.5)

    assert 8.062 < value < 8.094
    assert outside is False

    value, outside = ph_standard_expected("tris", 35.0, allow_clamp=False)

    assert pd.isna(value)
    assert outside is True


def test_ph_standard_expected_clamps_when_allowed() -> None:
    """Out of range pH standard temperatures can be clamped if configured."""
    value, outside = ph_standard_expected("tris", 35.0, allow_clamp=True)

    assert value == pytest.approx(7.970)
    assert outside is True


# =============================================================================
# TA CRM correction behaviour
# =============================================================================


def _ta_crm_outlier_frame() -> pd.DataFrame:
    """Six CRM rows: five near zero diff and one extreme outlier, plus one sample."""
    cert = CRM_CERTIFIED_TA["213"]
    crm_diffs = [0.05, -0.05, 0.02, -0.02, 0.00, 100.0]
    crm_ta = [cert - diff for diff in crm_diffs]

    crm_rows = pd.DataFrame(
        {
            "sample_tag": [f"RM213_{i + 1}" for i in range(6)],
            "crm_or_sample": ["crm"] * 6,
            "ta": crm_ta,
            "batch": ["A"] * 6,
        }
    )

    sample_row = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "crm_or_sample": ["sample"],
            "ta": [2300.0],
            "batch": ["A"],
        }
    )

    return pd.concat([crm_rows, sample_row], ignore_index=True)


def test_ta_crm_outlier_is_excluded_from_correction() -> None:
    """A flagged CRM outlier should not pull the TA correction mean."""
    df = _ta_crm_outlier_frame()

    out, crm_qc, corr_table, summary = apply_ta_crm_correction(
        df,
        ta_col="ta",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        crm_batch="213",
        crm_ta_override=None,
        group_by=None,
        crm_tag_prefix="RM",
        allow_crm_flag_col=True,
        require_ta_value_for_crm=True,
        min_crm_n=5,
        mad_k=3.5,
        max_abs_diff=10.0,
        correct_only_samples=True,
        sop=TaSop(no_adjust=2.0, reject=20.0),
    )

    assert summary["crm_n_valid"] == 6
    assert summary["crm_n_outlier"] == 1
    assert summary["crm_n_kept"] == 5
    assert summary["overall_n_kept"] == 5

    # Without outlier exclusion, the mean correction would be about 16.67.
    # With outlier exclusion, it should stay near zero and trigger NO_ADJUST.
    assert abs(summary["overall_corr"]) < 0.1
    assert summary["overall_status"] == "NO_ADJUST"

    assert int(crm_qc["ta_diff_umolkg_is_outlier"].fillna(False).sum()) == 1
    assert float(corr_table["overall_correction"].iloc[0]) == pytest.approx(0.0, abs=0.1)

    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert sample["ta_qc_status"] == "NO_ADJUST"
    assert sample["ta_correction_used_umolkg"] == pytest.approx(0.0)
    assert sample["ta_corrected_umolkg"] == pytest.approx(2300.0)


def test_require_ta_value_for_crm_rejects_detected_crm_with_missing_ta() -> None:
    """require_ta_value_for_crm=True should fail on detected CRM rows without TA."""
    df = pd.DataFrame(
        {
            "sample_tag": ["RM213_1", "RM213_2", "S001"],
            "crm_or_sample": ["crm", "crm", "sample"],
            "ta": [CRM_CERTIFIED_TA["213"], pd.NA, 2300.0],
        }
    )

    with pytest.raises(SystemExit):
        apply_ta_crm_correction(
            df,
            ta_col="ta",
            sample_tag_col="sample_tag",
            crm_or_sample_col="crm_or_sample",
            crm_batch="213",
            crm_ta_override=None,
            group_by=None,
            crm_tag_prefix="RM",
            allow_crm_flag_col=True,
            require_ta_value_for_crm=True,
            min_crm_n=1,
            mad_k=3.5,
            max_abs_diff=10.0,
            correct_only_samples=True,
            sop=TaSop(no_adjust=2.0, reject=20.0),
        )


def test_ta_correction_does_not_apply_to_crm_when_correct_only_samples_false() -> None:
    """Even broad correction mode should not correct CRM rows themselves."""
    df = _ta_crm_outlier_frame()

    out, _, _, _ = apply_ta_crm_correction(
        df,
        ta_col="ta",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        crm_batch="213",
        crm_ta_override=None,
        group_by=None,
        crm_tag_prefix="RM",
        allow_crm_flag_col=True,
        require_ta_value_for_crm=True,
        min_crm_n=5,
        mad_k=3.5,
        max_abs_diff=10.0,
        correct_only_samples=False,
        sop=TaSop(no_adjust=2.0, reject=20.0),
    )

    crm_rows = out[out["is_ta_crm_row"].fillna(False)]
    assert not crm_rows["ta_correction_applied"].fillna(False).any()


def test_ta_correction_level_is_reported() -> None:
    """TA correction level should identify overall fallback correction provenance."""
    df = _ta_crm_outlier_frame()

    out, _, _, _ = apply_ta_crm_correction(
        df,
        ta_col="ta",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        crm_batch="213",
        crm_ta_override=None,
        group_by=None,
        crm_tag_prefix="RM",
        allow_crm_flag_col=True,
        require_ta_value_for_crm=True,
        min_crm_n=5,
        mad_k=3.5,
        max_abs_diff=10.0,
        correct_only_samples=True,
        sop=TaSop(no_adjust=2.0, reject=20.0),
    )

    assert "ta_correction_level" in out.columns
    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert sample["ta_correction_level"] == "overall"


# =============================================================================
# pH standard correction behaviour
# =============================================================================


def _phstd_outlier_frame() -> pd.DataFrame:
    """Six TRIS rows: five near zero diff and one extreme outlier, plus one sample."""
    expected, outside = ph_standard_expected("tris", 25.0)
    assert outside is False

    std_diffs = [0.001, -0.001, 0.000, 0.002, -0.002, 0.200]
    measured = [expected - diff for diff in std_diffs]

    std_rows = pd.DataFrame(
        {
            "sample_tag": [f"TRIS_{i + 1}" for i in range(6)],
            "crm_or_sample": ["std"] * 6,
            "pH_lab": measured,
            "temp_lab": [25.0] * 6,
            "batch": ["A"] * 6,
        }
    )

    sample_row = pd.DataFrame(
        {
            "sample_tag": ["S001"],
            "crm_or_sample": ["sample"],
            "pH_lab": [8.050],
            "temp_lab": [25.0],
            "batch": ["A"],
        }
    )

    return pd.concat([std_rows, sample_row], ignore_index=True)


def test_phstd_outlier_is_excluded_from_correction() -> None:
    """A flagged pH standard outlier should not pull the pH correction mean."""
    df = _phstd_outlier_frame()

    out, phstd_qc, corr_table, summary = apply_ph_standard_qc_and_correction(
        df,
        buffer="tris",
        tag_prefix="TRIS",
        ph_col="pH_lab",
        temp_col="temp_lab",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        group_by=None,
        mad_k=3.5,
        max_abs_diff=0.05,
        min_std_n=5,
        correct_samples=True,
        status_thr=PhStdStatusThresholds(ok=0.02, warn=0.05),
        sample_flag_value="sample",
        apply_warn_correction=True,
        allow_temp_clamp=False,
    )

    assert summary["n_valid"] == 6
    assert summary["n_outlier"] == 1
    assert summary["n_kept"] == 5
    assert summary["overall_n_kept"] == 5

    # Without outlier exclusion, the mean correction would be about 0.033.
    # With outlier exclusion, it should stay near zero and remain OK.
    assert abs(summary["mean_diff_kept"]) < 0.005
    assert summary["overall_status"] == "OK"

    assert int(phstd_qc["phstd_diff_is_outlier"].fillna(False).sum()) == 1
    assert float(corr_table["overall_correction"].iloc[0]) == pytest.approx(0.0, abs=0.005)

    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert sample["phstd_status"] == "OK"
    assert bool(sample["phstd_correction_applied"])
    assert bool(sample["ph_corrected_available"])
    assert sample["ph_corrected_from_phstd"] == pytest.approx(8.050, abs=0.005)


def test_ph_correction_level_is_reported() -> None:
    """pH correction level should identify overall fallback correction provenance."""
    df = _phstd_outlier_frame()

    out, _, _, _ = apply_ph_standard_qc_and_correction(
        df,
        buffer="tris",
        tag_prefix="TRIS",
        ph_col="pH_lab",
        temp_col="temp_lab",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        group_by=None,
        mad_k=3.5,
        max_abs_diff=0.05,
        min_std_n=5,
        correct_samples=True,
        status_thr=PhStdStatusThresholds(ok=0.02, warn=0.05),
        sample_flag_value="sample",
        apply_warn_correction=True,
        allow_temp_clamp=False,
    )

    assert "phstd_correction_level" in out.columns
    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert sample["phstd_correction_level"] == "overall"


def test_ph_corrected_column_preserves_original_when_correction_withheld() -> None:
    """When pH correction is withheld, corrected pH should fall back to original pH."""
    df = pd.DataFrame(
        {
            "sample_tag": ["TRIS_1", "TRIS_2", "S001"],
            "crm_or_sample": ["std", "std", "sample"],
            "pH_lab": [7.500, 7.510, 8.050],
            "temp_lab": [25.0, 25.0, 25.0],
        }
    )

    out, _, _, summary = apply_ph_standard_qc_and_correction(
        df,
        buffer="tris",
        tag_prefix="TRIS",
        ph_col="pH_lab",
        temp_col="temp_lab",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        group_by=None,
        mad_k=3.5,
        max_abs_diff=None,
        min_std_n=2,
        correct_samples=True,
        status_thr=PhStdStatusThresholds(ok=0.02, warn=0.05),
        sample_flag_value="sample",
        apply_warn_correction=True,
        allow_temp_clamp=False,
    )

    assert summary["overall_status"] == "FAIL"

    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert bool(sample["phstd_correction_withheld"])
    assert bool(sample["ph_corrected_available"])
    assert sample["ph_corrected_from_phstd"] == pytest.approx(8.050)


def test_ph_corrected_column_preserves_original_when_correction_disabled() -> None:
    """When correction is disabled, corrected pH should still contain original pH."""
    df = _phstd_outlier_frame()

    out, _, _, _ = apply_ph_standard_qc_and_correction(
        df,
        buffer="tris",
        tag_prefix="TRIS",
        ph_col="pH_lab",
        temp_col="temp_lab",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        group_by=None,
        mad_k=3.5,
        max_abs_diff=0.05,
        min_std_n=5,
        correct_samples=False,
        status_thr=PhStdStatusThresholds(ok=0.02, warn=0.05),
        sample_flag_value="sample",
        apply_warn_correction=True,
        allow_temp_clamp=False,
    )

    sample = out.loc[out["sample_tag"].eq("S001")].iloc[0]
    assert not bool(sample["phstd_correction_applied"])
    assert bool(sample["ph_corrected_available"])
    assert sample["ph_corrected_from_phstd"] == pytest.approx(8.050)


# =============================================================================
# Dataclass validation
# =============================================================================


def test_ta_sop_validation() -> None:
    """TaSop should reject invalid threshold ordering."""
    with pytest.raises(ValueError):
        TaSop(no_adjust=-1.0, reject=20.0)

    with pytest.raises(ValueError):
        TaSop(no_adjust=2.0, reject=2.0)


def test_phstd_status_threshold_validation() -> None:
    """PhStdStatusThresholds should reject invalid threshold ordering."""
    with pytest.raises(ValueError):
        PhStdStatusThresholds(ok=-0.01, warn=0.05)

    with pytest.raises(ValueError):
        PhStdStatusThresholds(ok=0.05, warn=0.02)


def test_no_unexpected_nan_in_outlier_summaries() -> None:
    """Smoke check that outlier exclusion summaries are finite when data are valid."""
    df = _ta_crm_outlier_frame()

    _, _, _, summary = apply_ta_crm_correction(
        df,
        ta_col="ta",
        sample_tag_col="sample_tag",
        crm_or_sample_col="crm_or_sample",
        crm_batch="213",
        crm_ta_override=None,
        group_by=None,
        crm_tag_prefix="RM",
        allow_crm_flag_col=True,
        require_ta_value_for_crm=True,
        min_crm_n=5,
        mad_k=3.5,
        max_abs_diff=10.0,
        correct_only_samples=True,
        sop=TaSop(no_adjust=2.0, reject=20.0),
    )

    assert math.isfinite(float(summary["overall_corr"]))
    assert math.isfinite(float(summary["overall_sd"]))
    assert math.isfinite(float(summary["overall_se"]))
