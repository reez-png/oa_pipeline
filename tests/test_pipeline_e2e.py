"""
tests/test_pipeline_e2e.py
==========================
End to end smoke tests for the OA pipeline.

The test runs run_pipeline.sh on the bundled example dataset and checks that
critical outputs, manifests, reports, final audit columns, verdicts, and reason
codes are produced as expected.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pytest


# Skip this module when the optional notebook runner is unavailable.
pytest.importorskip("papermill")


# =============================================================================
# Helpers
# =============================================================================


def _find_git_bash() -> str | None:
    """Prefer Git Bash over WSL bash on Windows."""
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Git" / "usr" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Git" / "usr" / "bin" / "bash.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return shutil.which("bash")


def _path_arg(path: Path, project_root: Path) -> str:
    """Use project relative POSIX path when possible, otherwise absolute POSIX path."""
    path = path.resolve()

    try:
        return path.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _make_test_output_root(
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Return an output root for the E2E run.

    By default this uses pytest's temporary directory so the repository is not
    polluted. Set OA_KEEP_PYTEST_RUNS=1 to write under .pytest_runs for manual
    inspection after a local debugging run.
    """
    if os.environ.get("OA_KEEP_PYTEST_RUNS") == "1":
        out_root = project_root / ".pytest_runs" / "pipeline_e2e"
        if out_root.exists():
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        return out_root

    return tmp_path_factory.mktemp("pipeline_e2e")


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object and fail clearly if it is invalid."""
    assert path.exists(), f"Missing JSON file: {path}"

    with path.open("r", encoding="utf-8") as handle:
        obj = json.load(handle)

    assert isinstance(obj, dict), f"Expected JSON object in {path}"
    return obj


def _find_qc_derived_csv(out_root: Path) -> Path:
    """Find the single derived.csv written by Notebook 02."""
    qc_root = out_root / "oa_prelim_data__qc_outputs"
    matches = sorted(qc_root.glob("sheet_*/data/derived.csv"))

    assert matches, f"No Notebook 02 derived.csv found under {qc_root}"
    assert len(matches) == 1, (
        f"Expected exactly one Notebook 02 derived.csv, found {len(matches)}: "
        f"{matches}"
    )

    return matches[0]


def _load_final(out_root: Path) -> pd.DataFrame:
    """Load the final Stage 4 analysis ready CSV."""
    final = out_root / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    assert final.exists(), f"Stage 4 did not produce {final}"
    return pd.read_csv(final)


def _load_manifest(out_root: Path) -> dict[str, Any]:
    """Load the Stage 4 manifest."""
    manifest = out_root / "oa_stage4_outputs" / "logs" / "manifest.json"
    return _load_json(manifest)


def _id_column(df: pd.DataFrame) -> str:
    """Return the canonical ID column, with sample_tag as backward fallback."""
    if "record_id" in df.columns:
        return "record_id"
    if "sample_tag" in df.columns:
        return "sample_tag"
    pytest.fail("Final output has neither record_id nor sample_tag.")
    return "record_id"


# =============================================================================
# Pipeline execution fixture
# =============================================================================


@pytest.fixture(scope="module")
def pipeline_outputs(
    project_root: Path,
    example_xlsx_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Run the notebook pipeline once; tests in this module share the output."""
    runner = project_root / "run_pipeline.sh"
    if not runner.exists():
        pytest.skip(f"runner not found: {runner}")

    if not example_xlsx_path.exists():
        pytest.skip(
            f"{example_xlsx_path} not present. Run "
            "`python examples/make_example_data.py` to regenerate it."
        )

    package_dir = project_root / "src" / "oa_pipeline"
    if not package_dir.exists():
        pytest.fail(f"oa_pipeline package directory not found: {package_dir}")

    if importlib.util.find_spec("oa_pipeline") is None:
        pytest.fail(
            "oa_pipeline is not importable in the pytest process. Run "
            "`python -m pip install -e \".[all]\"` before running the E2E test."
        )

    bash_exe = _find_git_bash()
    if bash_exe is None:
        pytest.skip("bash not found on PATH")

    out_root = _make_test_output_root(project_root, tmp_path_factory)

    input_arg = _path_arg(example_xlsx_path, project_root)
    output_arg = _path_arg(out_root, project_root)

    env = os.environ.copy()

    venv_scripts = project_root / ".venv" / "Scripts"
    if venv_scripts.exists():
        env["PATH"] = str(venv_scripts) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(project_root / ".venv")

    src_path = project_root / "src"
    env["PYTHONPATH"] = (
        str(src_path)
        + os.pathsep
        + str(project_root)
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )

    result = subprocess.run(
        [
            bash_exe,
            "./run_pipeline.sh",
            input_arg,
            output_arg,
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(
            f"run_pipeline.sh exited with code {result.returncode}\n"
            f"--- stdout last 2000 chars ---\n{result.stdout[-2000:]}\n"
            f"--- stderr last 2000 chars ---\n{result.stderr[-2000:]}"
        )

    return out_root


# =============================================================================
# Runner refactor checks
# =============================================================================


def test_runner_references_notebooks_dir(project_root: Path) -> None:
    """The runner should define NOTEBOOK_DIR and reference required notebooks."""
    runner = project_root / "run_pipeline.sh"
    assert runner.exists(), f"Missing runner: {runner}"

    text = runner.read_text(encoding="utf-8")

    assert "NOTEBOOK_DIR" in text
    assert 'NOTEBOOK_DIR="$SCRIPT_DIR/notebooks"' in text

    expected_notebook_names = [
        "02_ta_ph_qc.ipynb",
        "04_stage1a.ipynb",
        "05_stage1b.ipynb",
        "06_stage2.ipynb",
        "07_stage3.ipynb",
        "08_stage4.ipynb",
    ]

    missing = [name for name in expected_notebook_names if name not in text]
    assert not missing, f"run_pipeline.sh does not reference notebooks: {missing}"


# =============================================================================
# Output presence and auditability
# =============================================================================


def test_each_stage_writes_its_output(pipeline_outputs: Path) -> None:
    """Every stage in the critical path should produce its main output CSV."""
    qc_derived = _find_qc_derived_csv(pipeline_outputs)
    assert qc_derived.exists(), f"Missing Notebook 02 derived.csv: {qc_derived}"

    expected = [
        "oa_stage1a_outputs/data/staged.csv",
        "oa_stage1a_outputs/data/analysis_ready.csv",
        "oa_stage1b_outputs/data/analysis_ready_samples.csv",
        "oa_stage2_outputs/data/enhanced.csv",
        "oa_stage3_outputs/data/enhanced.csv",
        "oa_stage4_outputs/data/analysis_ready.csv",
    ]

    for rel in expected:
        assert (pipeline_outputs / rel).exists(), f"Missing output: {rel}"


def test_each_stage_writes_a_manifest_and_effective_config(
    pipeline_outputs: Path,
) -> None:
    """Stage logs should contain manifest and effective config JSON files."""
    stage_dirs = [
        "oa_stage1a_outputs",
        "oa_stage1b_outputs",
        "oa_stage2_outputs",
        "oa_stage3_outputs",
        "oa_stage4_outputs",
    ]

    for stage_dir in stage_dirs:
        manifest = pipeline_outputs / stage_dir / "logs" / "manifest.json"
        effective_config = pipeline_outputs / stage_dir / "logs" / "effective_config.json"

        assert manifest.exists(), f"Missing manifest for {stage_dir}"
        assert effective_config.exists(), f"Missing effective_config for {stage_dir}"


def test_each_effective_config_is_valid_json(pipeline_outputs: Path) -> None:
    """Every effective_config.json should parse as a JSON object."""
    stage_dirs = [
        "oa_stage1a_outputs",
        "oa_stage1b_outputs",
        "oa_stage2_outputs",
        "oa_stage3_outputs",
        "oa_stage4_outputs",
    ]

    for stage_dir in stage_dirs:
        path = pipeline_outputs / stage_dir / "logs" / "effective_config.json"
        obj = _load_json(path)
        assert isinstance(obj, dict), f"{path} did not contain a JSON object"


def test_each_stage_writes_report(pipeline_outputs: Path) -> None:
    """Each major stage should write a non empty analyst readable report."""
    stage_dirs = [
        "oa_stage1a_outputs",
        "oa_stage1b_outputs",
        "oa_stage2_outputs",
        "oa_stage3_outputs",
        "oa_stage4_outputs",
    ]

    for stage_dir in stage_dirs:
        report = pipeline_outputs / stage_dir / "reports" / "report.md"
        assert report.exists(), f"Missing report for {stage_dir}"
        assert report.stat().st_size > 0, f"Empty report for {stage_dir}"


def test_data_folders_do_not_contain_notebooks(pipeline_outputs: Path) -> None:
    """Papermill output notebooks should not be written inside data folders."""
    bad_paths = list(pipeline_outputs.rglob("data/*.ipynb"))
    assert not bad_paths, f"Notebook unexpectedly written to data folder: {bad_paths}"


# =============================================================================
# Final output schema
# =============================================================================


def test_final_output_has_audit_columns(pipeline_outputs: Path) -> None:
    """The final CSV should expose the analyst facing audit columns."""
    analysis_ready = _load_final(pipeline_outputs)

    required_cols = [
        "analysis_audit_status",
        "analysis_audit_reason_codes",
        "analysis_audit_reason_fail",
        "analysis_audit_reason_review",
    ]

    missing = [col for col in required_cols if col not in analysis_ready.columns]
    assert not missing, f"Missing final audit columns: {missing}"


def test_final_output_has_core_chemistry_columns(pipeline_outputs: Path) -> None:
    """The final CSV should preserve core sample and chemistry fields."""
    analysis_ready = _load_final(pipeline_outputs)

    required_cols = [
        "record_id",
        "sample_id",
        "station_id",
        "sample_date",
        "depth_m",
        "salinity",
        "temperature_insitu_c",
        "ta_best_umolkg",
        "ph_best",
    ]

    missing = [col for col in required_cols if col not in analysis_ready.columns]
    assert not missing, f"Missing final output columns: {missing}"


# =============================================================================
# Verdict distribution
# =============================================================================


def test_only_sample_rows_in_final_output(pipeline_outputs: Path) -> None:
    """CRMs and standards are not in the final sample analysis output."""
    analysis_ready = _load_final(pipeline_outputs)
    manifest = _load_manifest(pipeline_outputs)
    row_counts = manifest.get("row_counts", {})

    assert len(analysis_ready) == row_counts.get("n_rows")
    assert len(analysis_ready) == 20


def test_verdict_distribution_matches_injected_issues(pipeline_outputs: Path) -> None:
    """20 sample rows should contain a bounded number of non PASS injected issues."""
    analysis_ready = _load_final(pipeline_outputs)
    counts = analysis_ready["analysis_audit_status"].value_counts()

    n_non_pass = int((analysis_ready["analysis_audit_status"] != "PASS").sum())

    assert 4 <= n_non_pass <= 8, (
        f"Expected 4 to 8 non PASS rows from deliberate injections, got "
        f"{n_non_pass}. Distribution: {counts.to_dict()}"
    )
    assert set(counts.index) <= {"PASS", "REVIEW", "FAIL"}


# =============================================================================
# Per row verdicts
# =============================================================================


@pytest.mark.parametrize(
    "sample_tag, expected_status, expected_reason_substring",
    [
        ("S005", "REVIEW", "range_flag"),
        ("S007", "FAIL", "missing_key"),
        ("S010", "FAIL", "strict_dic_species_fail"),
        ("S015", "FAIL", "strict_dic_species_fail"),
    ],
)
def test_specific_broken_row_has_expected_status_and_reason(
    pipeline_outputs: Path,
    sample_tag: str,
    expected_status: str,
    expected_reason_substring: str,
) -> None:
    """Deliberately injected broken rows should have expected verdicts and reasons."""
    analysis_ready = _load_final(pipeline_outputs)
    id_col = _id_column(analysis_ready)
    matches = analysis_ready[analysis_ready[id_col] == sample_tag]

    assert len(matches) == 1, f"expected exactly one row {sample_tag!r} by {id_col}"

    row = matches.iloc[0]

    assert row["analysis_audit_status"] == expected_status, (
        f"{sample_tag} should be {expected_status}, got "
        f"{row['analysis_audit_status']!r}. Reasons: "
        f"{row.get('analysis_audit_reason_codes')!r}"
    )

    reasons = str(row["analysis_audit_reason_codes"] or "")
    assert expected_reason_substring in reasons, (
        f"{sample_tag}: expected reason code containing "
        f"{expected_reason_substring!r}, got {reasons!r}"
    )


# =============================================================================
# Stage 4 manifest sanity
# =============================================================================


def test_stage4_manifest_has_reason_code_counts(pipeline_outputs: Path) -> None:
    """The Stage 4 manifest should expose reason_code to count mapping."""
    manifest = _load_manifest(pipeline_outputs)
    reason_code_counts = manifest.get("reason_code_counts", {})

    assert isinstance(reason_code_counts, dict)

    for required_code in ("missing_key", "strict_dic_species_fail"):
        assert required_code in reason_code_counts, (
            f"expected reason code {required_code!r} in manifest, "
            f"got {list(reason_code_counts.keys())}"
        )


def test_stage4_manifest_records_row_counts(pipeline_outputs: Path) -> None:
    """Manifest row counts should agree internally and match final row count."""
    manifest = _load_manifest(pipeline_outputs)
    analysis_ready = _load_final(pipeline_outputs)
    row_counts = manifest.get("row_counts", {})

    assert row_counts.get("n_rows") == len(analysis_ready)
    assert row_counts.get("n_rows") == 20
    assert "status_PASS" in row_counts
    assert "status_REVIEW" in row_counts
    assert "status_FAIL" in row_counts

    assert (
        row_counts["status_PASS"]
        + row_counts["status_REVIEW"]
        + row_counts["status_FAIL"]
    ) == row_counts["n_rows"]
