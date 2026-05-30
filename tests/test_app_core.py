"""
tests/test_app_core.py
======================
Tests for the GUI-independent launcher logic in oa_pipeline_app_core.

These do not require Tkinter or a display, so they run anywhere pytest does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The app core lives at the project root, not inside the package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

core = pytest.importorskip("oa_pipeline_app_core")


def test_find_project_root_finds_markers(tmp_path: Path) -> None:
    (tmp_path / "run_pipeline.sh").write_text("#!/bin/bash\n")
    (tmp_path / "notebooks").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert core.find_project_root(nested) == tmp_path


def test_find_project_root_returns_none_when_absent(tmp_path: Path) -> None:
    assert core.find_project_root(tmp_path) is None


def test_build_command_minimal() -> None:
    cmd = core.build_command(
        "bash",
        Path("/proj"),
        Path("/proj/in.xlsx"),
        Path("/proj/out"),
        "0",
        no_parquet=False,
        include_viewer=False,
        include_review=False,
        dry_run=False,
    )
    assert cmd[:2] == ["bash", "./run_pipeline.sh"]
    # Compare using str(Path(...)) so the separator matches the host OS
    # (forward slash on POSIX, backslash on Windows). build_command passes the
    # path straight through, which is what run_pipeline.sh expects on each OS.
    assert str(Path("/proj/in.xlsx")) in cmd
    assert str(Path("/proj/out")) in cmd
    assert cmd[-2:] == ["--sheet", "0"]


def test_build_command_all_flags() -> None:
    cmd = core.build_command(
        "bash",
        Path("/proj"),
        Path("/proj/in.xlsx"),
        Path("/proj/out"),
        "2",
        no_parquet=True,
        include_viewer=True,
        include_review=True,
        dry_run=True,
    )
    for flag in ("--no-parquet", "--include-viewer", "--include-review", "--dry-run"):
        assert flag in cmd
    assert "2" in cmd


def test_environment_problems_no_root() -> None:
    problems = core.environment_problems(None, "bash", "python")
    assert len(problems) == 1
    assert "project root" in problems[0].lower()


def test_summarize_verdicts_missing_file(tmp_path: Path) -> None:
    msg = core.summarize_verdicts(tmp_path)
    assert "No final" in msg


def test_summarize_verdicts_counts(tmp_path: Path) -> None:
    data_dir = tmp_path / "oa_stage4_outputs" / "data"
    data_dir.mkdir(parents=True)
    final = data_dir / "analysis_ready.csv"
    final.write_text(
        "record_id,analysis_audit_status\n"
        "R1,PASS\nR2,PASS\nR3,REVIEW\nR4,FAIL\n",
        encoding="utf-8",
    )

    msg = core.summarize_verdicts(tmp_path)
    assert "4 sample rows" in msg
    assert "PASS: 2" in msg
    assert "REVIEW: 1" in msg
    assert "FAIL: 1" in msg
