"""
tests/conftest.py
=================
Shared pytest fixtures.

Most tests build small synthetic frames inline; the fixtures here are for
the things that take several lines to construct repeatably.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Project root, the directory containing the pipeline notebooks."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def example_xlsx_path() -> Path:
    """Path to the bundled example_data.xlsx.

    Built by examples/make_example_data.py with a fixed seed, so the
    output is deterministic. Re-run that script if the file is missing.
    """
    p = PROJECT_ROOT / "examples" / "example_data.xlsx"
    if not p.exists():
        pytest.skip(
            f"{p} not present. Run `python examples/make_example_data.py` to "
            "regenerate it, then re-run the tests."
        )
    return p


# ---------------------------------------------------------------------------
# Synthetic Stage 1B-style frames for unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_sample_frame() -> pd.DataFrame:
    """Five-row frame that looks like what Stage 1B would have produced.

    Row meanings:
    row 0: clean PASS
    row 1: clean PASS
    row 2: salinity 50, out of range, expected REVIEW range_flag
    row 3: missing sample_id, expected FAIL missing_key
    row 4: stage3 strict issue, expected FAIL stage3_strict_issue
    """
    return pd.DataFrame({
        "record_id": ["R1", "R2", "R3", "R4", "R5"],
        "sample_id": ["S1", "S2", "S3", pd.NA, "S5"],
        "cruise_id": ["C1"] * 5,
        "transect_id": ["T1"] * 5,
        "station_id": ["ST1", "ST2", "ST3", "ST4", "ST5"],
        "replicate_id": ["a", "a", "a", "a", "a"],
        "sample_date": pd.to_datetime([
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
            "2024-01-18",
            "2024-01-19",
        ]),

        "depth_m": [10.0, 10.0, 10.0, 10.0, 10.0],
        "depth_round_m": [10.0, 10.0, 10.0, 10.0, 10.0],
        "salinity": [35.0, 35.0, 50.0, 35.0, 35.0],
        "temperature_insitu_c": [25.0] * 5,

        "ta_best_umolkg": [2300.0, 2300.0, 2300.0, 2300.0, 2300.0],
        "ph_best": [8.05, 8.06, 8.08, 8.05, 8.05],
        "ph_co2sys": [8.04, 8.05, 8.07, 8.04, 8.04],

        "flag_any_carbonate_issue": [False, False, False, False, True],
        "flag_any_carbonate_issue_strict": [False, False, False, False, True],
        "flag_solver_unknown": [False] * 5,
        "flag_carbon_input_pair_unknown": [False] * 5,
        "flag_stage2_replicate_conflict_carried": [False] * 5,
        "flag_dic_inconsistent": [False] * 5,
        "flag_dic_inconsistent_robust": [False] * 5,
        "flag_ph_scale_mismatch": [False] * 5,
        "flag_ph_diag_mismatch": [False] * 5,
        "flag_ph_diag_mismatch_strict": [False] * 5,
        "flag_ph_diag_mismatch_robust": [False] * 5,

        "sample_month": pd.Series(
            ["2024-01", "2024-01", "2024-01", "2024-01", "2024-01"],
            dtype="string",
        ),
    })
