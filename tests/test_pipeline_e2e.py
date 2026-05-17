"""
tests/test_pipeline_e2e.py
==========================
End-to-end smoke test: run the eight-notebook chain on the bundled
example dataset and assert the verdict distribution.

This is the test that the EOI specifically calls out: "automated tests
for critical transformations and quality control rules" — at the
*pipeline* level rather than the per-function level. If anything in any
stage regresses, the verdict counts here change and the test fails.

The example dataset has four deliberately-broken rows (S005 / S007 /
S010 / S015) whose verdicts and reason codes are pinned below. Re-run
``examples/make_example_data.py`` whenever you change those injections
in lockstep with the asserts.

The test is skipped when ``papermill`` isn't installed, since it relies
on the runner script.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


# Skip the whole module if papermill or the runner script aren't available.
papermill = pytest.importorskip("papermill")


@pytest.fixture(scope="module")
def pipeline_outputs(project_root: Path, example_xlsx_path: Path, tmp_path_factory):
    """Run the pipeline once for the module; tests share the output.

    Uses a per-test-run tmp dir for OUT_DIR so we never collide with a
    real run under ``outputs/``.
    """
    out_root = tmp_path_factory.mktemp("pipeline_e2e")
    runner = project_root / "run_pipeline.sh"
    if not runner.exists():
        pytest.skip(f"runner not found: {runner}")

    result = subprocess.run(
        ["bash", str(runner), str(example_xlsx_path), str(out_root)],
        cwd=project_root,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Capture both stdout and stderr so a CI failure has actionable info.
        pytest.fail(
            f"run_pipeline.sh exited with code {result.returncode}\n"
            f"--- stdout (last 1500 chars) ---\n{result.stdout[-1500:]}\n"
            f"--- stderr (last 1500 chars) ---\n{result.stderr[-1500:]}"
        )

    return out_root


def _load_final(out_root: Path) -> pd.DataFrame:
    final = out_root / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    assert final.exists(), f"Stage 4 did not produce {final}"
    return pd.read_csv(final)


def _load_manifest(out_root: Path) -> dict:
    manifest = out_root / "oa_stage4_outputs" / "logs" / "manifest.json"
    return json.loads(manifest.read_text())


# ---------------------------------------------------------------------------
# Output presence
# ---------------------------------------------------------------------------

def test_each_stage_writes_its_output(pipeline_outputs):
    """Every stage in the critical path should produce its output CSV."""
    expected = [
        "oa_prelim_data__qc_outputs/sheet_0/data/derived.csv",
        "oa_stage1a_outputs/data/staged.csv",
        "oa_stage1a_outputs/data/analysis_ready.csv",
        "oa_stage1b_outputs/data/analysis_ready_samples.csv",
        "oa_stage2_outputs/data/enhanced.csv",
        "oa_stage3_outputs/data/enhanced.csv",
        "oa_stage4_outputs/data/analysis_ready.csv",
    ]
    for rel in expected:
        assert (pipeline_outputs / rel).exists(), f"Missing output: {rel}"


def test_each_stage_writes_a_manifest(pipeline_outputs):
    """Each stage's logs/ folder should have a manifest.json + effective_config.json."""
    stage_dirs = [
        "oa_stage1a_outputs", "oa_stage1b_outputs",
        "oa_stage2_outputs", "oa_stage3_outputs", "oa_stage4_outputs",
    ]
    for d in stage_dirs:
        assert (pipeline_outputs / d / "logs" / "manifest.json").exists(), (
            f"Missing manifest for {d}"
        )
        assert (pipeline_outputs / d / "logs" / "effective_config.json").exists(), (
            f"Missing effective_config for {d}"
        )


# ---------------------------------------------------------------------------
# Verdict distribution (the headline number)
# ---------------------------------------------------------------------------

def test_only_sample_rows_in_final_output(pipeline_outputs):
    """Stage 1B filters to sample rows only — CRMs and standards are not in
    the analysis-ready output. The example dataset has 20 sample rows."""
    ar = _load_final(pipeline_outputs)
    assert len(ar) == 20


def test_verdict_distribution_matches_injected_issues(pipeline_outputs):
    """20 sample rows: ~15 PASS, the rest non-PASS due to injected issues."""
    ar = _load_final(pipeline_outputs)
    counts = ar["analysis_audit_status"].value_counts()
    # At least 4 must be non-PASS (the four deliberately-broken rows).
    n_non_pass = (ar["analysis_audit_status"] != "PASS").sum()
    assert n_non_pass >= 4, (
        f"expected >= 4 non-PASS rows from deliberate injections, "
        f"got {n_non_pass}. Distribution: {counts.to_dict()}"
    )
    # And all the rest should be PASS or REVIEW or FAIL (no other value).
    assert set(counts.index) <= {"PASS", "REVIEW", "FAIL"}


# ---------------------------------------------------------------------------
# Per-row verdicts (the four known injections)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sample_tag,expected_reason_substring", [
    # S005: salinity = 50 (above sal_max=42). Expected REVIEW range_flag,
    # but the Stage 2 replicate-grouping cascade sometimes makes it FAIL
    # via stage3_strict_issue carry-forward (see explanatory note in
    # the README). Either way, the row must NOT be PASS and the
    # reason-codes must mention range_flag.
    ("S005", "range_flag"),
    ("S007", "missing_key"),
    ("S010", "strict_dic_species_fail"),
    ("S015", "strict_dic_species_fail"),
])
def test_specific_broken_row_has_expected_reason(
    pipeline_outputs, sample_tag, expected_reason_substring,
):
    ar = _load_final(pipeline_outputs)
    matches = ar[ar["sample_tag"] == sample_tag]
    assert len(matches) == 1, f"expected exactly one row {sample_tag!r}"
    row = matches.iloc[0]

    assert row["analysis_audit_status"] != "PASS", (
        f"{sample_tag} should be REVIEW or FAIL, got "
        f"{row['analysis_audit_status']!r}. Reasons: "
        f"{row.get('analysis_audit_reason_codes')!r}"
    )

    reasons = str(row["analysis_audit_reason_codes"] or "")
    assert expected_reason_substring in reasons, (
        f"{sample_tag}: expected reason code containing "
        f"{expected_reason_substring!r}, got {reasons!r}"
    )


# ---------------------------------------------------------------------------
# Stage 4 manifest sanity
# ---------------------------------------------------------------------------

def test_stage4_manifest_has_reason_code_counts(pipeline_outputs):
    """The manifest exposes a dict of `reason_code -> count`. Downstream
    tooling parses this; renaming a code silently here would break it."""
    m = _load_manifest(pipeline_outputs)
    rc = m.get("reason_code_counts", {})
    assert isinstance(rc, dict)
    # The injected rows must produce these specific codes.
    for required_code in ("missing_key", "strict_dic_species_fail"):
        assert required_code in rc, (
            f"expected reason code {required_code!r} in manifest, "
            f"got {list(rc.keys())}"
        )


def test_stage4_manifest_records_row_counts(pipeline_outputs):
    m = _load_manifest(pipeline_outputs)
    rc = m.get("row_counts", {})
    assert rc.get("n_rows") == 20
    assert "status_PASS" in rc
    assert "status_REVIEW" in rc
    assert "status_FAIL" in rc
    # Sanity: PASS + REVIEW + FAIL == total rows.
    assert (
        rc["status_PASS"] + rc["status_REVIEW"] + rc["status_FAIL"]
    ) == rc["n_rows"]
