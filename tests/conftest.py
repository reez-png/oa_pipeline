"""
tests/conftest.py
=================
Shared pytest fixtures for the OA pipeline test suite.

The fixtures here provide stable project paths, temporary output roots, and
small synthetic dataframes used by unit and integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# Path fixtures
# =============================================================================


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Project root, the directory containing pyproject.toml."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def notebooks_dir(project_root: Path) -> Path:
    """Directory containing the pipeline notebooks."""
    return project_root / "notebooks"


@pytest.fixture(scope="session")
def configs_dir(project_root: Path) -> Path:
    """Directory containing YAML or JSON configuration files."""
    return project_root / "configs"


@pytest.fixture(scope="session")
def src_dir(project_root: Path) -> Path:
    """Directory containing the src layout package root."""
    return project_root / "src"


@pytest.fixture(scope="session")
def package_dir(src_dir: Path) -> Path:
    """Directory containing the oa_pipeline package."""
    return src_dir / "oa_pipeline"


@pytest.fixture(scope="session")
def example_xlsx_path(project_root: Path) -> Path:
    """Path to bundled example_data.xlsx for integration tests."""
    path = project_root / "examples" / "example_data.xlsx"

    if not path.exists():
        pytest.skip(
            f"{path} not present. Run `python examples/make_example_data.py` "
            "to regenerate it, then re run the integration tests."
        )

    return path


@pytest.fixture
def tmp_output_root(tmp_path: Path) -> Path:
    """Temporary output root for tests that write pipeline products."""
    root = tmp_path / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root


# =============================================================================
# Small fixture helpers
# =============================================================================


def _bool_series(values: list[bool]) -> pd.Series:
    """Return a nullable boolean Series for dataframe fixtures."""
    return pd.Series(values, dtype="boolean")


# =============================================================================
# Synthetic Stage 4 style frame
# =============================================================================


@pytest.fixture
def tiny_stage4_audit_frame() -> pd.DataFrame:
    """Five row frame for Stage 4 readiness status tests.

    Row meanings:
    row 0: clean PASS
    row 1: clean PASS
    row 2: salinity 50, range issue, expected REVIEW range_flag
    row 3: missing sample_id, expected FAIL missing_key
    row 4: Stage 3 strict issue, expected FAIL stage3_strict_issue
    """
    return pd.DataFrame(
        {
            "record_id": ["R1", "R2", "R3", "R4", "R5"],
            "sample_id": ["S1", "S2", "S3", pd.NA, "S5"],
            "cruise_id": ["C1"] * 5,
            "transect_id": ["T1"] * 5,
            "station_id": ["ST1", "ST2", "ST3", "ST4", "ST5"],
            "replicate_id": ["a", "a", "a", "a", "a"],
            "sample_date": pd.to_datetime(
                [
                    "2024-01-15",
                    "2024-01-16",
                    "2024-01-17",
                    "2024-01-18",
                    "2024-01-19",
                ],
                utc=True,
            ),
            "sample_month": pd.Series(["2024-01"] * 5, dtype="string"),
            "sample_day": pd.Series(
                [
                    "2024-01-15",
                    "2024-01-16",
                    "2024-01-17",
                    "2024-01-18",
                    "2024-01-19",
                ],
                dtype="string",
            ),
            "depth_m": [10.0] * 5,
            "depth_round_m": [10.0] * 5,
            "depth_bin_m": [10.0] * 5,
            "latitude_deg": [5.0] * 5,
            "longitude_deg": [-1.0] * 5,
            "salinity": [35.0, 35.0, 50.0, 35.0, 35.0],
            "temperature_insitu_c": [25.0] * 5,
            "pressure_output_dbar": [10.0] * 5,
            "ta_best_umolkg": [2300.0] * 5,
            "ph_best": [8.05, 8.06, 8.08, 8.05, 8.05],
            "ph_co2sys": [8.04, 8.05, 8.07, 8.04, 8.04],
            "pco2_best_uatm": [410.0] * 5,
            "dic_best_umol_kg": [2000.0] * 5,
            "co2aq_calc_umol_kg": [10.0] * 5,
            "hco3_calc_umol_kg": [1800.0] * 5,
            "co3_calc_umol_kg": [190.0] * 5,
            "omega_aragonite_calc": [2.5] * 5,
            "omega_calcite_calc": [3.8] * 5,
            "ph_scale_observed_normalized": ["total"] * 5,
            "ph_scale_calculated_normalized": ["total"] * 5,
            "dic_unit_normalized": ["UMOL/KG"] * 5,
            "co2aq_unit_normalized": ["UMOL/KG"] * 5,
            "hco3_unit_normalized": ["UMOL/KG"] * 5,
            "co3_unit_normalized": ["UMOL/KG"] * 5,
            "carbonate_solver": ["PyCO2SYS"] * 5,
            "carbon_input_pair_used": ["TA + pH_observed"] * 5,
            "ta_best_source": ["ta_corrected_umolkg"] * 5,
            "ph_best_source": ["ph_corrected_from_phstd"] * 5,
            "ph_co2sys_source": ["ph_calculated"] * 5,
            "pco2_best_source": ["pco2_calc_uatm"] * 5,
            "dic_best_source": ["dic_calculated_umol_kg"] * 5,
            # Explicitly include this because Stage 4 readiness uses this
            # row level count rather than inspecting salinity directly.
            "range_flag_count": pd.Series([0, 0, 1, 0, 0], dtype="Int64"),
            "flag_any_carbonate_issue": _bool_series(
                [False, False, False, False, True]
            ),
            "flag_any_carbonate_issue_strict": _bool_series(
                [False, False, False, False, True]
            ),
            "flag_solver_unknown": _bool_series([False] * 5),
            "flag_carbon_input_pair_unknown": _bool_series([False] * 5),
            "flag_stage2_replicate_conflict_carried": _bool_series([False] * 5),
            "flag_dic_unit_missing": _bool_series([False] * 5),
            "flag_dic_inconsistent": _bool_series([False] * 5),
            "flag_dic_inconsistent_robust": _bool_series([False] * 5),
            "flag_ph_scale_mismatch": _bool_series([False] * 5),
            "flag_ph_best_scale_unexpected": _bool_series([False] * 5),
            "flag_ph_co2sys_scale_unexpected": _bool_series([False] * 5),
            "flag_ph_diag_mismatch": _bool_series([False] * 5),
            "flag_ph_diag_mismatch_strict": _bool_series([False] * 5),
            "flag_ph_diag_mismatch_robust": _bool_series([False] * 5),
            "flag_dic_species_audit_not_run": _bool_series([False] * 5),
            "flag_dic_species_values_missing_audit": _bool_series([False] * 5),
            "flag_dic_species_audit_strict": _bool_series([False] * 5),
            "flag_dic_species_unit_mismatch_audit": _bool_series([False] * 5),
            "flag_dic_species_unit_missing_audit": _bool_series([False] * 5),
        }
    )


@pytest.fixture
def tiny_sample_frame(tiny_stage4_audit_frame: pd.DataFrame) -> pd.DataFrame:
    """Backward compatible alias for older tests."""
    return tiny_stage4_audit_frame.copy()
