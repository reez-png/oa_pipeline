"""
tests/test_readiness.py
=======================
Tests for ``oa_stage4.add_readiness_status`` — the PASS/REVIEW/FAIL
classifier and its reason-code assignment.

This is the most consequential function in the pipeline because its
output is the column an analyst will filter on. Edits to ``fail_def`` /
``review_def`` lists silently promote or demote rows between tiers, so
these tests pin the current behaviour: FAIL beats REVIEW beats PASS,
and each reason code maps to a specific input flag.

The ``reason_count_table`` is also tested because the Stage 4 manifest
exposes it as ``reason_code_counts`` — downstream tooling that filters
on a specific reason code can break silently if a code is renamed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_stage4 import add_readiness_status, reason_count_table


def _base_frame() -> pd.DataFrame:
    """A two-row frame where everything passes by default.

    Tests below mutate one column at a time to assert each verdict tier.
    """
    return pd.DataFrame({
        "record_id":   ["A", "B"],
        "sample_id":   ["S1", "S2"],
        "sample_date": pd.to_datetime(["2024-01-15", "2024-01-16"]),
        "station_id":  ["ST1", "ST2"],
        "depth_round_m": [10.0, 10.0],
        "salinity":    [35.0, 35.0],
        "ph_best":     [8.05, 8.05],
        "ph_co2sys":   [8.04, 8.04],
        "ta_best_umolkg": [2300.0, 2300.0],
        "flag_any_carbonate_issue":          [False, False],
        "flag_any_carbonate_issue_strict":   [False, False],
        "flag_solver_unknown":               [False, False],
        "flag_carbon_input_pair_unknown":    [False, False],
        "flag_stage2_replicate_conflict_carried": [False, False],
        "flag_dic_inconsistent":             [False, False],
        "flag_dic_inconsistent_robust":      [False, False],
        "flag_ph_diag_mismatch":             [False, False],
        "flag_ph_diag_mismatch_robust":      [False, False],
        "flag_dic_species_audit_strict":     [False, False],
        "flag_dic_species_unit_mismatch_audit": [False, False],
        "flag_dic_species_unit_missing_audit":  [False, False],
    })


# ---------------------------------------------------------------------------
# Verdict tiers
# ---------------------------------------------------------------------------

class TestAddReadinessStatus:
    def test_clean_rows_get_pass(self):
        df = _base_frame()
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out["analysis_audit_status"].tolist() == ["PASS", "PASS"]
        assert out["analysis_audit_reason_codes"].isna().all()

    def test_missing_key_index_promotes_to_fail(self):
        """A row whose index is in `missing_key_idx` -> FAIL `missing_key`."""
        df = _base_frame()
        # Row 0 has a missing key, row 1 does not.
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([0])
        )
        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert out.loc[1, "analysis_audit_status"] == "PASS"
        assert "missing_key" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_duplicate_table_promotes_to_review(self):
        """A row whose index is in `dup_table` -> REVIEW `duplicate_complete_key`."""
        df = _base_frame()
        # Pretend Stage 4's `detect_duplicates` flagged row 1 as duplicate.
        dup_table = df.loc[[1]].copy()
        out = add_readiness_status(
            df, dup_table=dup_table, missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "PASS"
        assert out.loc[1, "analysis_audit_status"] == "REVIEW"
        assert "duplicate_complete_key" in (out.loc[1, "analysis_audit_reason_codes"] or "")

    def test_stage3_strict_flag_promotes_to_fail(self):
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue_strict"] = True
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "stage3_strict_issue" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_stage3_non_strict_flag_promotes_to_review(self):
        """A non-strict carbonate issue -> REVIEW (not FAIL)."""
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue"] = True
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "REVIEW"
        assert "stage3_issue" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_range_flag_count_drives_range_issue(self):
        """`range_flag_count > 0` -> REVIEW `range_flag`."""
        df = _base_frame()
        df["range_flag_count"] = [0, 2]
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "PASS"
        assert out.loc[1, "analysis_audit_status"] == "REVIEW"
        assert "range_flag" in (out.loc[1, "analysis_audit_reason_codes"] or "")

    def test_strict_dic_fail_promotes_to_fail(self):
        df = _base_frame()
        df.loc[0, "flag_dic_species_audit_strict"] = True
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "strict_dic_species_fail" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_severe_beats_review(self):
        """When both severe and review-tier flags fire, FAIL wins."""
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue"] = True          # review tier
        df.loc[0, "flag_any_carbonate_issue_strict"] = True   # severe tier
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        # Both reason codes survive in `analysis_audit_reason_codes`
        # so the analyst sees the full picture.
        codes = out.loc[0, "analysis_audit_reason_codes"]
        assert "stage3_issue" in codes
        assert "stage3_strict_issue" in codes

    def test_missing_range_flag_count_does_not_crash(self):
        """REGRESSION: when no range checks ran, `range_flag_count` is absent.

        The original Stage 4 code used `pd.to_numeric(df.get(...))`,
        which returned a scalar `np.float64(nan)` when the column was
        missing; the next `.fillna(0)` then crashed with AttributeError.
        Fixed with a guarded conditional.
        """
        df = _base_frame()
        # Note: NO range_flag_count column.
        out = add_readiness_status(
            df, dup_table=pd.DataFrame(), missing_key_idx=pd.Index([])
        )
        # Should not raise; rows should be PASS since no flags fired.
        assert out["analysis_audit_status"].tolist() == ["PASS", "PASS"]


# ---------------------------------------------------------------------------
# reason_count_table
# ---------------------------------------------------------------------------

class TestReasonCountTable:
    def test_counts_each_reason_separately(self):
        df = pd.DataFrame({
            "analysis_audit_reason_codes": pd.Series([
                "range_flag",
                "range_flag;stage3_issue",
                "missing_key",
                None,
                "range_flag",
            ], dtype="string"),
        })
        tbl = reason_count_table(df)
        counts = dict(zip(tbl["reason_code"], tbl["count"]))
        assert counts["range_flag"] == 3
        assert counts["stage3_issue"] == 1
        assert counts["missing_key"] == 1

    def test_empty_or_missing_column_returns_empty_frame(self):
        empty = reason_count_table(pd.DataFrame())
        assert empty.empty
        assert list(empty.columns) == ["reason_code", "count"]
