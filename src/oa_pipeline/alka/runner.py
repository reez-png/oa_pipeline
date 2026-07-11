"""
alka.runner — build and run the pipeline, reusing the existing core module.

This is a thin adapter. It does NOT reimplement command-building, bash
discovery, or verdict summarising — those already live in
`oa_pipeline_app_core.py` and are tested and working. Alka imports them and
adds exactly one new step: writing the config files implied by the GUI options
(via config_writer) before assembling the command.

Keeping this as an adapter means:
  * the existing launcher (oa_pipeline_app.py) keeps working unchanged;
  * there is one source of truth for how the pipeline is invoked;
  * when a run misbehaves, you look here for the Alka-specific wiring and in
    the core module for the invocation itself — not one tangled file.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from .state import AppState
from . import config_writer

# Import the existing, tested core. We try the package path first (installed
# as oa_pipeline), then fall back to a top-level module if Alka is run from the
# project root where oa_pipeline_app_core.py sits beside run_pipeline.sh.
try:  # pragma: no cover - import resolution differs by launch context
    from oa_pipeline import oa_pipeline_app_core as core  # type: ignore
except Exception:  # noqa: BLE001
    import importlib
    core = importlib.import_module("oa_pipeline_app_core")


def resolve_environment(state: AppState) -> list[str]:
    """Fill in bash/python/project_root on the state; return any problems."""
    start = Path(__file__).resolve()
    state.project_root = core.find_project_root(start) or core.find_project_root(Path.cwd())
    state.bash_exe = core.find_bash()
    state.python_exe = core.find_python()
    return core.environment_problems(state.project_root, state.bash_exe, state.python_exe)


def build_run_command(state: AppState) -> tuple[list[str], list[str]]:
    """Write configs from the GUI options, then assemble the pipeline command.

    Returns (command, notes). `notes` are human-readable lines about what the
    config step did, for the log.
    """
    # 1) translate GUI options into config files (the new Alka step)
    cfg_res = config_writer.write_stage_configs(
        project_root=state.project_root,
        compute_carbonate_internally=state.compute_carbonate_internally,
    )
    state.last_config_dir = cfg_res.config_dir

    # 2) hand off to the existing, tested command builder
    cmd = core.build_command(
        bash_exe=state.bash_exe,
        project_root=state.project_root,
        xlsx=Path(state.input_xlsx),
        out_dir=Path(state.output_dir),
        sheet=state.sheet,
        no_parquet=state.no_parquet,
        include_viewer=state.include_viewer,
        include_review=state.include_review,
        dry_run=state.dry_run,
        config_dir=cfg_res.config_dir,
    )
    return cmd, cfg_res.notes


def run_pipeline(
    state: AppState,
    on_output: Callable[[str], None],
    on_finish: Callable[[int, str], None],
    cancel_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Run the pipeline in a background thread, streaming output.

    on_output(line)   — called for each line of stdout/stderr.
    on_finish(rc, summary) — called once when done, with return code and a
                             verdict summary string.
    Returns the started Thread so the caller can join/track it.
    """
    def _work():
        try:
            cmd, notes = build_run_command(state)
        except Exception as exc:  # noqa: BLE001
            on_finish(-1, f"Could not build command: {exc}")
            return

        for n in notes:
            on_output(f"[config] {n}")
        on_output("[run] " + " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(state.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:  # noqa: BLE001
            on_finish(-1, f"Failed to start pipeline: {exc}")
            return

        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                on_output("[run] cancelled by user")
                break
            on_output(line.rstrip("\n"))
        rc = proc.wait()

        summary = ""
        if rc == 0 and not state.dry_run:
            try:
                summary = core.summarize_verdicts(Path(state.output_dir))
            except Exception as exc:  # noqa: BLE001
                summary = f"(could not summarise verdicts: {exc})"
        on_finish(rc, summary)

    state.is_running = True
    t = threading.Thread(target=_work, daemon=True)
    t.start()
    return t