"""
tests/test_stage2.py
====================
Focused unit tests for Stage 2 duplicate, alias, and replicate logic.

These tests protect Stage 2 behaviours that strongly affect downstream
replicate conflict flags and Stage 4 review reasons:

1. Replicate grouping should not merge different sample_id values.
2. record_id differences should not create replicate metadata conflicts.
3. Stage 2 should accept common DIC and pCO2 aliases.
4. Conflicting alias values should be reported in notes.
5. depth_bin_method should support both nearest and floor binning.
"""

from __future__ import annotations

import copy

import pandas as pd

from oa_pipeline.stage2 import (
    STAGE2_DEFAULTS,
    add_conflict_annotations,
    add_replicate_annotations,
    add_time_and_depth_keys,
    materialize_canonical_aliases,
    replicate_harmonise,
)


# =============================================================================
# Small helpers
# =============================================================================


def _config() -> dict:
    """Return a deep copy so tests cannot mutate shared defaults."""
    return copy.deepcopy(STAGE2_DEFAULTS)


def _run_replicate_harmonise(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the standard Stage 2 replicate path and return row annotated data."""
    config = _config()
    notes: list[str] = []

    keyed = add_time_and_depth_keys(
        df,
        notes=notes,
        depth_round_decimals=1,
        depth_bin_m=config.get("depth_bin_m", 1.0),
        depth_bin_method=config.get("depth_bin_method", "nearest"),
    )

    (
        _rep_mean,
        _rep_mean_sd,
        consistency_df,
        disagree_df,
        keys_used,
        _mean_vars,
        nrep,
    ) = replicate_harmonise(
        keyed,
        requested_keys=config["replicate_group_keys"],
        mean_whitelist=config["replicate_mean_vars"],
        consistency_cols=config["replicate_consistency_check_columns"],
        sd_thresholds=config["replicate_sd_thresholds"],
        conflict_class_map=config["replicate_conflict_field_classes"],
    )

    annotated = add_replicate_annotations(keyed, nrep, keys_used)
    annotated = add_conflict_annotations(
        annotated,
        consistency_df=consistency_df,
        disagree_df=disagree_df,
        keys_used=keys_used,
    )

    return annotated, consistency_df, nrep


# =============================================================================
# Replicate grouping
# =============================================================================


def test_replicate_grouping_does_not_merge_different_sample_ids() -> None:
    """Same station, depth, and day should not merge distinct sample IDs."""
    df = pd.DataFrame(
        {
            "record_id": ["R001", "R002"],
            "sample_id": ["S001", "S002"],
            "sample_date": ["2024-03-01T10:00:00", "2024-03-01T10:05:00"],
            "cruise_id": ["C1", "C1"],
            "transect_id": ["T1", "T1"],
            "station_id": ["ST01", "ST01"],
            "depth_m": [10.1, 10.2],
            "ph_best": [8.05, 8.06],
            "ta_best_umolkg": [2300.0, 2301.0],
        }
    )

    annotated, consistency_df, nrep = _run_replicate_harmonise(df)

    assert nrep["n_reps"].max() == 1
    assert not annotated["flag_has_replicates"].fillna(False).any()
    assert not annotated["flag_replicate_any_conflict"].fillna(False).any()
    assert consistency_df.empty


def test_record_id_does_not_create_replicate_metadata_conflict() -> None:
    """Valid replicate rows may have different record_id values."""
    df = pd.DataFrame(
        {
            "record_id": ["R001", "R002"],
            "sample_id": ["S001", "S001"],
            "sample_date": ["2024-03-01T10:00:00", "2024-03-01T10:02:00"],
            "cruise_id": ["C1", "C1"],
            "transect_id": ["T1", "T1"],
            "station_id": ["ST01", "ST01"],
            "depth_m": [10.0, 10.0],
            "ph_best": [8.050, 8.051],
            "ta_best_umolkg": [2300.0, 2301.0],
            "ta_best_source": ["ta_corrected_umolkg", "ta_corrected_umolkg"],
            "ph_best_source": ["ph_after_phstd_qc", "ph_after_phstd_qc"],
            "ta_qc_status": ["NO_ADJUST", "NO_ADJUST"],
            "ph_qc_status": [pd.NA, pd.NA],
            "phstd_status": ["OK", "OK"],
            "ta_units_normalized": ["umol kg-1", "umol kg-1"],
            "ph_scale_observed_normalized": ["total", "total"],
            "carbonate_solver": ["synthetic_example_generator", "synthetic_example_generator"],
            "carbon_input_pair_used": ["TA + pH_observed", "TA + pH_observed"],
        }
    )

    annotated, consistency_df, nrep = _run_replicate_harmonise(df)

    assert nrep["n_reps"].max() == 2
    assert annotated["flag_has_replicates"].fillna(False).all()
    assert "record_id" not in set(consistency_df.get("field", pd.Series(dtype="string")))
    assert not annotated["flag_replicate_metadata_conflict"].fillna(False).any()
    assert not annotated["flag_replicate_any_conflict"].fillna(False).any()


# =============================================================================
# Alias handling
# =============================================================================


def test_stage2_accepts_common_dic_and_pco2_aliases() -> None:
    """Common DIC and pCO2 aliases should populate canonical best fields."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "sample_date": ["2024-03-01"],
            "station_id": ["ST01"],
            "depth_m": [10.0],
            "ta": [2300.0],
            "pH_lab": [8.05],
            "DIC": [2050.0],
            "pCO2": [420.0],
        }
    )

    notes: list[str] = []
    out, resolved = materialize_canonical_aliases(
        df,
        alias_map=_config()["canonical_aliases"],
        notes=notes,
    )

    assert out.loc[0, "dic_best_umol_kg"] == 2050.0
    assert out.loc[0, "pco2_best_uatm"] == 420.0
    assert resolved["dic_best_umol_kg"] == "DIC"
    assert resolved["pco2_best_uatm"] == "pCO2"


def test_materialize_canonical_aliases_warns_on_conflicting_aliases() -> None:
    """Conflicting non empty aliases should be surfaced in notes."""
    df = pd.DataFrame(
        {
            "sample_id": ["S001"],
            "sample_date": ["2024-03-01"],
            "station_id": ["ST01"],
            "depth_m": [10.0],
            "ta_best_umolkg": [2300.0],
            "ph_best": [8.05],
            "pH_lab": [8.10],
        }
    )

    notes: list[str] = []
    out, resolved = materialize_canonical_aliases(
        df,
        alias_map=_config()["canonical_aliases"],
        notes=notes,
    )

    assert out.loc[0, "ph_best"] == 8.05
    assert resolved["ph_best"] == "ph_best"
    assert any(
        "WARNING: canonical 'ph_best'" in note
        and "conflicting non empty alias values" in note
        for note in notes
    )


# =============================================================================
# Depth binning
# =============================================================================


def test_depth_bin_method_nearest_and_floor_are_distinct() -> None:
    """Depth binning should support explicit nearest and floor semantics."""
    df = pd.DataFrame(
        {
            "sample_date": ["2024-03-01", "2024-03-01"],
            "depth_m": [10.49, 10.51],
        }
    )

    nearest = add_time_and_depth_keys(
        df,
        notes=[],
        depth_bin_m=1.0,
        depth_bin_method="nearest",
    )
    floored = add_time_and_depth_keys(
        df,
        notes=[],
        depth_bin_m=1.0,
        depth_bin_method="floor",
    )

    assert nearest["depth_bin_m"].tolist() == [10.0, 11.0]
    assert floored["depth_bin_m"].tolist() == [10.0, 10.0]
