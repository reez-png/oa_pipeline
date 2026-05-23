"""
tests/test_stage4.py
====================
Focused unit tests for Stage 4 audit and readiness helpers.

These tests protect Stage 4 behaviours that directly affect final
PASS / REVIEW / FAIL decisions:

1. Missing DIC species values are only flagged when there is partial DIC species
   evidence, not when optional species fields are entirely absent.
2. DIC species audit thresholds must be finite.
3. Boolean config parsing must reject unknown strings.
4. Ambiguous carbonate species aliases are not accepted by default.
5. Negative or nonpositive carbonate species trigger strict DIC failure.
6. Strict DIC failure propagates to Stage 4 FAIL readiness status.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_pipeline.stage4 import (
    STAGE4_DEFAULTS,
    DicSpeciesAudit,
    add_readiness_status,
    dic_species_audit,
    reason_count_table,
)


# =============================================================================
# DIC species missingness
# =============================================================================


def test_dic_values_missing_only_flags_partial_species_evidence() -> None:
    """Rows with no species evidence should not be reviewed as partial species rows."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001", "S002"],
            "dic_best_umol_kg": [pd.NA, 2050.0],
            "co2aq_calc_umol_kg": [pd.NA, 10.0],
            "hco3_calc_umol_kg": [pd.NA, pd.NA],
            "co3_calc_umol_kg": [pd.NA, 100.0],
        }
    )

    check = DicSpeciesAudit()
    result, note, colmeta = dic_species_audit(
        df,
        check,
        candidates=STAGE4_DEFAULTS["strict_dic_candidates"],
        unit_equivalents=set(STAGE4_DEFAULTS["unit_equivalents"]),
    )

    assert "Ran strict DIC" in note
    assert colmeta["dic_col"] == "dic_best_umol_kg"
    assert not bool(result.loc[0, "flag_dic_species_values_missing_audit"])
    assert bool(result.loc[1, "flag_dic_species_values_missing_audit"])


def test_dic_species_audit_with_no_species_evidence_has_no_missing_values_flag() -> None:
    """Completely absent optional species values should not create review flags."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "dic_best_umol_kg": [pd.NA],
            "co2aq_calc_umol_kg": [pd.NA],
            "hco3_calc_umol_kg": [pd.NA],
            "co3_calc_umol_kg": [pd.NA],
        }
    )

    result, _, _ = dic_species_audit(
        df,
        DicSpeciesAudit(),
        candidates=STAGE4_DEFAULTS["strict_dic_candidates"],
        unit_equivalents=set(STAGE4_DEFAULTS["unit_equivalents"]),
    )

    assert not bool(result.loc[0, "flag_dic_species_values_missing_audit"])
    assert not bool(result.loc[0, "flag_dic_species_audit_strict"])


# =============================================================================
# Config validation
# =============================================================================


def test_dic_species_audit_rejects_nonfinite_thresholds() -> None:
    """Strict DIC audit thresholds must be finite numeric values."""
    with pytest.raises(ValueError):
        DicSpeciesAudit(abs_tol_umolkg=float("nan"))

    with pytest.raises(ValueError):
        DicSpeciesAudit(rel_tol=float("inf"))

    with pytest.raises(ValueError):
        DicSpeciesAudit(abs_tol_umolkg=float("-inf"))


def test_as_bool_rejects_unknown_string() -> None:
    """Unknown boolean config strings should fail instead of becoming True."""
    with pytest.raises(ValueError):
        DicSpeciesAudit(enabled="maybe")

    with pytest.raises(ValueError):
        DicSpeciesAudit(require_matching_units="sometimes")


# =============================================================================
# Alias safety
# =============================================================================


def test_stage4_species_aliases_do_not_accept_ambiguous_plain_names() -> None:
    """Plain CO2, HCO3, and CO3 should not be default species aliases."""
    aliases = STAGE4_DEFAULTS["canonical_aliases"]
    strict = STAGE4_DEFAULTS["strict_dic_candidates"]

    assert "CO2" not in aliases["co2aq_calc_umol_kg"]
    assert "co2" not in aliases["co2aq_calc_umol_kg"]
    assert "HCO3" not in aliases["hco3_calc_umol_kg"]
    assert "hco3" not in aliases["hco3_calc_umol_kg"]
    assert "CO3" not in aliases["co3_calc_umol_kg"]
    assert "co3" not in aliases["co3_calc_umol_kg"]

    assert "CO2" not in strict["co2aq"]
    assert "co2" not in strict["co2aq"]
    assert "HCO3" not in strict["hco3"]
    assert "hco3" not in strict["hco3"]
    assert "CO3" not in strict["co3"]
    assert "co3" not in strict["co3"]


def test_stage4_accepts_expanded_ta_dic_and_pco2_aliases() -> None:
    """Stage 4 aliases should stay aligned with Stage 1B, Stage 2, and Stage 3."""
    aliases = STAGE4_DEFAULTS["canonical_aliases"]

    assert "ta_corrected" in aliases["ta_best_umolkg"]
    assert "ta_umolkg" in aliases["ta_best_umolkg"]
    assert "dic_measured_umol_kg" in aliases["dic_best_umol_kg"]
    assert "dic_umol_kg" in aliases["dic_best_umol_kg"]
    assert "dic_umolkg" in aliases["dic_best_umol_kg"]
    assert "pco2_uatm" in aliases["pco2_best_uatm"]


# =============================================================================
# Negative species and strict DIC audit failure
# =============================================================================


def test_negative_species_triggers_strict_dic_audit_failure() -> None:
    """A species sum can be numerically consistent but physically impossible."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "dic_best_umol_kg": [1900.0],
            "co2aq_calc_umol_kg": [10.0],
            "hco3_calc_umol_kg": [-100.0],
            "co3_calc_umol_kg": [1990.0],
        }
    )

    result, _, _ = dic_species_audit(
        df,
        DicSpeciesAudit(require_matching_units=False),
        candidates=STAGE4_DEFAULTS["strict_dic_candidates"],
        unit_equivalents=set(STAGE4_DEFAULTS["unit_equivalents"]),
    )

    assert bool(result.loc[0, "flag_dic_species_negative_hco3_audit"])
    assert bool(result.loc[0, "flag_dic_species_audit_strict"])
    assert result.loc[0, "dic_minus_sum"] == pytest.approx(0.0)


def test_nonpositive_dic_triggers_strict_dic_audit_failure() -> None:
    """DIC must be positive when present in a complete DIC species block."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "dic_best_umol_kg": [0.0],
            "co2aq_calc_umol_kg": [0.0],
            "hco3_calc_umol_kg": [0.0],
            "co3_calc_umol_kg": [0.0],
        }
    )

    result, _, _ = dic_species_audit(
        df,
        DicSpeciesAudit(require_matching_units=False),
        candidates=STAGE4_DEFAULTS["strict_dic_candidates"],
        unit_equivalents=set(STAGE4_DEFAULTS["unit_equivalents"]),
    )

    assert bool(result.loc[0, "flag_dic_species_nonpositive_dic_audit"])
    assert bool(result.loc[0, "flag_dic_species_audit_strict"])


# =============================================================================
# Readiness integration
# =============================================================================


def test_strict_dic_species_failure_becomes_fail_status() -> None:
    """Strict DIC audit failure should produce FAIL with strict_dic_species_fail."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "sample_date": ["2024-01-01"],
            "station_id": ["ST01"],
            "depth_round_m": [10.0],
            "flag_dic_species_audit_strict": [True],
            "range_flag_count": [0],
        }
    )

    out = add_readiness_status(
        df,
        dup_table=pd.DataFrame(),
        missing_key_idx=pd.Index([]),
        required_analysis_missing_idx=pd.Index([]),
    )

    assert out.loc[0, "analysis_audit_status"] == "FAIL"
    assert "strict_dic_species_fail" in out.loc[0, "analysis_audit_reason_codes"]

    counts = reason_count_table(out)
    assert counts.loc[counts["reason_code"].eq("strict_dic_species_fail"), "count"].iloc[0] == 1
