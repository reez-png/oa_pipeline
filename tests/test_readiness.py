"""
tests/test_readiness.py
=======================
Tests for oa_pipeline.stage4 readiness classification.

These tests pin the Stage 4 PASS, REVIEW, and FAIL verdict logic, the reason
code mapping, missing key detection, duplicate detection, and reason code
histogram behaviour.
"""

from __future__ import annotations

import pandas as pd

from oa_pipeline.stage4 import (
    add_readiness_status,
    detect_duplicates,
    missing_key_rows,
    reason_count_table,
)


def _base_frame() -> pd.DataFrame:
    """A two row Stage 4 input frame where everything passes by default."""
    return pd.DataFrame(
        {
            "record_id": ["A", "B"],
            "sample_id": ["S1", "S2"],
            "sample_date": pd.to_datetime(
                ["2024-01-15", "2024-01-16"],
                utc=True,
            ),
            "sample_month": pd.Series(["2024-01", "2024-01"], dtype="string"),
            "station_id": ["ST1", "ST2"],
            "replicate_id": ["a", "a"],
            "depth_m": [10.0, 10.0],
            "depth_round_m": [10.0, 10.0],
            "salinity": [35.0, 35.0],
            "temperature_insitu_c": [25.0, 25.0],
            "ph_best": [8.05, 8.05],
            "ph_co2sys": [8.04, 8.04],
            "ta_best_umolkg": [2300.0, 2300.0],
            "dic_best_umol_kg": [2000.0, 2000.0],
            "pco2_best_uatm": [410.0, 410.0],
            "ph_scale_observed_normalized": ["total", "total"],
            "ph_scale_calculated_normalized": ["total", "total"],
            "carbonate_solver": ["PyCO2SYS", "PyCO2SYS"],
            "carbon_input_pair_used": ["TA + pH_observed", "TA + pH_observed"],
            "flag_any_carbonate_issue": [False, False],
            "flag_any_carbonate_issue_strict": [False, False],
            "flag_solver_unknown": [False, False],
            "flag_carbon_input_pair_unknown": [False, False],
            "flag_stage2_replicate_conflict_carried": [False, False],
            "flag_dic_inconsistent": [False, False],
            "flag_dic_inconsistent_robust": [False, False],
            "flag_ph_diag_mismatch": [False, False],
            "flag_ph_diag_mismatch_robust": [False, False],
            "flag_dic_species_audit_strict": [False, False],
            "flag_dic_species_unit_mismatch_audit": [False, False],
            "flag_dic_species_unit_missing_audit": [False, False],
            "flag_dic_species_audit_not_run": [False, False],
            "flag_dic_species_values_missing_audit": [False, False],
        }
    )


# =============================================================================
# Verdict tiers
# =============================================================================


class TestAddReadinessStatus:
    def test_clean_rows_get_pass(self) -> None:
        """Rows with no audit flags get PASS and no reason codes."""
        df = _base_frame()

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out["analysis_audit_status"].tolist() == ["PASS", "PASS"]
        assert out["analysis_audit_reason_codes"].isna().all()

    def test_missing_key_index_promotes_to_fail(self) -> None:
        """A row whose index is in missing_key_idx gets FAIL missing_key."""
        df = _base_frame()

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([0]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert out.loc[1, "analysis_audit_status"] == "PASS"
        assert "missing_key" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_required_analysis_missing_promotes_to_fail(self) -> None:
        """Missing required analysis fields get FAIL missing_required_analysis."""
        df = _base_frame()

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
            required_analysis_missing_idx=pd.Index([1]),
        )

        assert out.loc[0, "analysis_audit_status"] == "PASS"
        assert out.loc[1, "analysis_audit_status"] == "FAIL"
        assert "missing_required_analysis" in (
            out.loc[1, "analysis_audit_reason_codes"] or ""
        )

    def test_duplicate_table_promotes_to_review(self) -> None:
        """A row whose index is in dup_table gets REVIEW duplicate_complete_key."""
        df = _base_frame()
        dup_table = df.loc[[1]].copy()

        out = add_readiness_status(
            df,
            dup_table=dup_table,
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "PASS"
        assert out.loc[1, "analysis_audit_status"] == "REVIEW"
        assert "duplicate_complete_key" in (
            out.loc[1, "analysis_audit_reason_codes"] or ""
        )

    def test_stage3_strict_flag_promotes_to_fail(self) -> None:
        """Stage 3 strict carbonate issue gets FAIL."""
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue_strict"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "stage3_strict_issue" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_stage3_non_strict_flag_promotes_to_review(self) -> None:
        """Stage 3 non strict carbonate issue gets REVIEW, not FAIL."""
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "REVIEW"
        assert "stage3_issue" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_range_flag_count_drives_range_issue(self) -> None:
        """range_flag_count greater than zero gets REVIEW range_flag."""
        df = _base_frame()
        df["range_flag_count"] = pd.Series([0, 2], dtype="Int64")

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "PASS"
        assert out.loc[1, "analysis_audit_status"] == "REVIEW"
        assert "range_flag" in (out.loc[1, "analysis_audit_reason_codes"] or "")

    def test_strict_dic_fail_promotes_to_fail(self) -> None:
        """Strict DIC species sum failure gets FAIL."""
        df = _base_frame()
        df.loc[0, "flag_dic_species_audit_strict"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "strict_dic_species_fail" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_dic_unit_mismatch_promotes_to_fail(self) -> None:
        """Strict DIC unit mismatch gets FAIL."""
        df = _base_frame()
        df.loc[0, "flag_dic_species_unit_mismatch_audit"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "strict_dic_unit_mismatch" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_dic_unit_missing_promotes_to_review(self) -> None:
        """Strict DIC unit missing gets REVIEW rather than FAIL."""
        df = _base_frame()
        df.loc[0, "flag_dic_species_unit_missing_audit"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "REVIEW"
        assert "strict_dic_unit_missing" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_dic_species_audit_not_run_promotes_to_review(self) -> None:
        """If strict DIC audit cannot run, the row gets REVIEW."""
        df = _base_frame()
        df.loc[0, "flag_dic_species_audit_not_run"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "REVIEW"
        assert "strict_dic_audit_not_run" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_dic_species_values_missing_promotes_to_review(self) -> None:
        """Rows with missing DIC species values get REVIEW."""
        df = _base_frame()
        df.loc[0, "flag_dic_species_values_missing_audit"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "REVIEW"
        assert "strict_dic_values_missing" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_unknown_solver_promotes_to_fail_when_calculated_outputs_exist(self) -> None:
        """Unknown solver gets FAIL when calculated carbonate outputs exist."""
        df = _base_frame()
        df.loc[0, "flag_solver_unknown"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "unknown_solver" in (out.loc[0, "analysis_audit_reason_codes"] or "")

    def test_unknown_input_pair_promotes_to_fail_when_calculated_outputs_exist(self) -> None:
        """Unknown carbonate input pair gets FAIL when calculated outputs exist."""
        df = _base_frame()
        df.loc[0, "flag_carbon_input_pair_unknown"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert "unknown_input_pair" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_string_boolean_flags_are_parsed(self) -> None:
        """CSV style string booleans are parsed safely by readiness logic."""
        df = _base_frame()
        df["flag_any_carbonate_issue_strict"] = ["TRUE", "FALSE"]

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        assert out.loc[1, "analysis_audit_status"] == "PASS"
        assert "stage3_strict_issue" in (
            out.loc[0, "analysis_audit_reason_codes"] or ""
        )

    def test_severe_beats_review(self) -> None:
        """When severe and review tier flags both fire, FAIL wins."""
        df = _base_frame()
        df.loc[0, "flag_any_carbonate_issue"] = True
        df.loc[0, "flag_any_carbonate_issue_strict"] = True

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out.loc[0, "analysis_audit_status"] == "FAIL"
        codes = out.loc[0, "analysis_audit_reason_codes"] or ""
        assert "stage3_issue" in codes
        assert "stage3_strict_issue" in codes

    def test_missing_range_flag_count_does_not_crash(self) -> None:
        """Missing range_flag_count is treated as zero range issues."""
        df = _base_frame()

        out = add_readiness_status(
            df,
            dup_table=pd.DataFrame(),
            missing_key_idx=pd.Index([]),
        )

        assert out["analysis_audit_status"].tolist() == ["PASS", "PASS"]


# =============================================================================
# Missing key and duplicate helpers
# =============================================================================


class TestMissingKeysAndDuplicates:
    def test_missing_key_rows_flags_missing_values(self) -> None:
        """Missing values inside existing key columns are flagged."""
        df = _base_frame()
        df.loc[0, "sample_id"] = pd.NA

        missing = missing_key_rows(
            df,
            keys=["sample_id", "sample_date", "station_id", "depth_round_m"],
        )

        assert 0 in missing.index
        assert "flag_missing_key__sample_id" in missing.columns
        assert bool(missing.loc[0, "flag_missing_key__sample_id"])

    def test_missing_key_rows_flags_absent_key_columns_for_all_rows(self) -> None:
        """A completely absent required key column is flagged for every row."""
        df = _base_frame().drop(columns=["sample_id"])

        missing = missing_key_rows(
            df,
            keys=["sample_id", "sample_date", "station_id", "depth_round_m"],
        )

        assert len(missing) == len(df)
        assert "flag_missing_key__sample_id" in missing.columns
        assert missing["flag_missing_key__sample_id"].all()

    def test_detect_duplicates_requires_complete_keys(self) -> None:
        """Duplicate detection uses complete matching key tuples."""
        df = _base_frame()
        df.loc[1, "sample_id"] = "S1"
        df.loc[1, "sample_date"] = df.loc[0, "sample_date"]
        df.loc[1, "station_id"] = "ST1"
        df.loc[1, "depth_round_m"] = 10.0

        dups, messages, keys_used = detect_duplicates(
            df,
            keys=["sample_id", "sample_date", "station_id", "depth_round_m"],
        )

        assert set(dups.index) == {0, 1}
        assert keys_used == ["sample_id", "sample_date", "station_id", "depth_round_m"]
        assert any("Keys used" in message for message in messages)

    def test_detect_duplicates_does_not_flag_incomplete_key_rows(self) -> None:
        """Rows with incomplete keys are not treated as confirmed duplicates."""
        df = _base_frame()
        df.loc[0, "sample_id"] = pd.NA
        df.loc[1, "sample_id"] = pd.NA
        df.loc[1, "sample_date"] = df.loc[0, "sample_date"]
        df.loc[1, "station_id"] = df.loc[0, "station_id"]
        df.loc[1, "depth_round_m"] = df.loc[0, "depth_round_m"]

        dups, _, _ = detect_duplicates(
            df,
            keys=["sample_id", "sample_date", "station_id", "depth_round_m"],
        )

        assert dups.empty

    def test_detect_duplicates_requires_all_requested_key_columns_to_exist(self) -> None:
        """If a requested duplicate key column is absent, duplicate checking stops."""
        df = _base_frame().drop(columns=["sample_id"])

        dups, messages, keys_used = detect_duplicates(
            df,
            keys=["sample_id", "sample_date", "station_id", "depth_round_m"],
        )

        assert dups.empty
        assert "sample_id" not in keys_used
        assert any("Required duplicate key columns missing" in message for message in messages)


# =============================================================================
# reason_count_table
# =============================================================================


class TestReasonCountTable:
    def test_counts_each_reason_separately(self) -> None:
        """Semicolon joined reason codes are split into individual counts."""
        df = pd.DataFrame(
            {
                "analysis_audit_reason_codes": pd.Series(
                    [
                        "range_flag",
                        "range_flag;stage3_issue",
                        "missing_key",
                        None,
                        "range_flag",
                    ],
                    dtype="string",
                ),
            }
        )

        table = reason_count_table(df)
        counts = dict(zip(table["reason_code"], table["count"]))

        assert counts["range_flag"] == 3
        assert counts["stage3_issue"] == 1
        assert counts["missing_key"] == 1

    def test_reason_count_table_strips_and_counts_repeated_codes(self) -> None:
        """Whitespace is stripped and repeated codes are counted per appearance."""
        df = pd.DataFrame(
            {
                "analysis_audit_reason_codes": pd.Series(
                    [
                        " range_flag ; stage3_issue ",
                        "range_flag;range_flag",
                        pd.NA,
                    ],
                    dtype="string",
                ),
            }
        )

        table = reason_count_table(df)
        counts = dict(zip(table["reason_code"], table["count"]))

        assert counts["range_flag"] == 3
        assert counts["stage3_issue"] == 1

    def test_empty_or_missing_column_returns_empty_frame(self) -> None:
        """Missing reason code column returns an empty count table."""
        empty = reason_count_table(pd.DataFrame())

        assert empty.empty
        assert list(empty.columns) == ["reason_code", "count"]
