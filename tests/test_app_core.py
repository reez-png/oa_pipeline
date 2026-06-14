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
    # build_command now converts paths to a POSIX mount form bash will not
    # mangle (see to_bash_path). A path with no Windows drive letter is
    # already POSIX, so it passes through with forward slashes on every host
    # OS — that's what we assert, rather than str(Path(...)) which would be
    # backslash-separated on Windows and never reach bash intact.
    assert "/proj/in.xlsx" in cmd
    assert "/proj/out" in cmd
    assert cmd[-2:] == ["--sheet", "0"]


def test_build_command_converts_windows_path_to_forward_slashes() -> None:
    """A Windows drive path must reach bash with forward slashes only.

    This is the regression that caused the launcher's
    'file not found: C:UsersOA_2023-03...' error: backslashes were stripped
    by bash during tokenization. Using forward slashes (keeping the drive
    letter) prevents that AND stays parseable by the Windows Python that
    papermill invokes downstream.
    """
    cmd = core.build_command(
        "C:/Program Files/Git/bin/bash.exe",
        Path("/proj"),
        Path(r"C:\Users\OA_2023-03\data\in.xlsx"),
        Path(r"C:\Users\OA_2023-03\out"),
        "0",
        no_parquet=False,
        include_viewer=False,
        include_review=False,
        dry_run=False,
    )
    # The path arguments (after the script name) carry no backslashes; cmd[0]
    # is the bash executable path, which we do not convert.
    assert all("\\" not in arg for arg in cmd[2:])
    assert "C:/Users/OA_2023-03/data/in.xlsx" in cmd
    assert "C:/Users/OA_2023-03/out" in cmd


def test_build_command_forward_slash_form_is_bash_flavor_independent() -> None:
    """The conversion is identical regardless of which bash is used."""
    args = (
        Path("/proj"),
        Path(r"C:\Users\OA_2023-03\data\in.xlsx"),
        Path(r"C:\Users\OA_2023-03\out"),
        "0",
    )
    kw = dict(
        no_parquet=False,
        include_viewer=False,
        include_review=False,
        dry_run=False,
    )
    git = core.build_command("C:/Program Files/Git/bin/bash.exe", *args, **kw)
    wsl = core.build_command(r"C:\WINDOWS\system32\bash.EXE", *args, **kw)
    assert git[2:] == wsl[2:]
    assert "C:/Users/OA_2023-03/data/in.xlsx" in git


def test_build_command_config_dir_omitted_by_default() -> None:
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
    assert "--config-dir" not in cmd


def test_build_command_config_dir_included_when_given() -> None:
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
        config_dir=Path("/proj/configs"),
    )
    assert "--config-dir" in cmd
    assert cmd[cmd.index("--config-dir") + 1] == "/proj/configs"


def test_build_command_config_dir_windows_path_forward_slashed() -> None:
    cmd = core.build_command(
        "C:/Program Files/Git/bin/bash.exe",
        Path("/proj"),
        Path(r"C:\Users\x\in.xlsx"),
        Path(r"C:\Users\x\out"),
        "0",
        no_parquet=False,
        include_viewer=False,
        include_review=False,
        dry_run=False,
        config_dir=Path(r"C:\Users\x\configs"),
    )
    assert cmd[cmd.index("--config-dir") + 1] == "C:/Users/x/configs"


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


def test_to_bash_path_posix_unchanged() -> None:
    assert core.to_bash_path(Path("/proj/in.xlsx")) == "/proj/in.xlsx"


def test_to_bash_path_windows_forward_slash() -> None:
    # Drive letter kept, separators flipped to forward slashes — parseable
    # by both bash and Windows Python.
    out = core.to_bash_path(Path(r"C:\Users\x\in.xlsx"))
    assert out == "C:/Users/x/in.xlsx"


def test_to_bash_path_no_backslashes_remain() -> None:
    out = core.to_bash_path(Path(r"C:\Users\x\sub dir\in.xlsx"))
    assert "\\" not in out


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