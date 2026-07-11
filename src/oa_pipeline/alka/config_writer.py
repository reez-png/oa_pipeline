"""
alka.config_writer — translate GUI choices into pipeline config files.

This module is deliberately GUI-free: it takes plain values (booleans, strings)
and writes/updates the per-stage YAML files the pipeline reads. Keeping it
separate means it can be unit-tested without launching any window — call the
function, inspect the file it produced.

The main job today: when the user ticks "compute carbonate chemistry
internally", write `configs/08_stage4.yaml` with `carbonate_calc.enabled: true`
so the pipeline's Stage 4 runs the internal PyCO2SYS calculation from
RM-corrected TA (instead of requiring the user to hand-edit YAML).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# We write YAML by hand (small, fixed structure) to avoid adding a PyYAML
# dependency to the GUI layer. If PyYAML is already available it is used for
# safety; otherwise the hand-written form below is valid YAML.
def _dump_stage4_yaml(enabled: bool,
                      require_corrected_ta: bool = True,
                      rm_reject_fraction_warn: float = 0.34) -> str:
    """Produce the text of configs/08_stage4.yaml."""
    return (
        "# configs/08_stage4.yaml\n"
        "# Written by Alka (do not hand-edit unless you know why).\n"
        "# Enables the internal PyCO2SYS carbonate calculation in Stage 4:\n"
        "# DIC / Omega / pCO2 computed from RM-corrected TA + measured pH, at the\n"
        "# lab-temperature input / in-situ-temperature output convention.\n"
        "# Settings are pinned/validated (Lueker 2000; Dickson KSO4; Lee 2010\n"
        "# borate; Perez & Fraga KF; total pH scale). See carbonate_calc_design.md.\n"
        "carbonate_calc:\n"
        f"  enabled: {str(bool(enabled)).lower()}\n"
        f"  require_corrected_ta: {str(bool(require_corrected_ta)).lower()}\n"
        f"  rm_reject_fraction_warn: {float(rm_reject_fraction_warn)}\n"
    )


@dataclass
class ConfigResult:
    """What the writer did, so the GUI can report it and the runner can use it."""
    config_dir: Optional[Path]   # dir to pass to --config-dir, or None
    written: list[Path]          # files written this call
    notes: list[str]             # human-readable summary lines


def write_stage_configs(
    project_root: Path,
    compute_carbonate_internally: bool,
    require_corrected_ta: bool = True,
    rm_reject_fraction_warn: float = 0.34,
    config_dir_name: str = "configs",
) -> ConfigResult:
    """Create/update the config files implied by the GUI options.

    Returns a ConfigResult whose `config_dir` should be passed to
    build_command(config_dir=...) when it is not None. When no options require
    a config, `config_dir` is None and the pipeline runs with built-in defaults.

    Only the files this call is responsible for are (re)written; other config
    files in the folder are left untouched.
    """
    config_dir = project_root / config_dir_name
    written: list[Path] = []
    notes: list[str] = []

    # Stage 4 carbonate calc toggle.
    stage4_path = config_dir / "08_stage4.yaml"
    if compute_carbonate_internally:
        config_dir.mkdir(parents=True, exist_ok=True)
        text = _dump_stage4_yaml(
            enabled=True,
            require_corrected_ta=require_corrected_ta,
            rm_reject_fraction_warn=rm_reject_fraction_warn,
        )
        # Only rewrite if content differs, to keep git diffs quiet.
        if not stage4_path.exists() or stage4_path.read_text(encoding="utf-8") != text:
            stage4_path.write_text(text, encoding="utf-8")
            written.append(stage4_path)
            notes.append("Carbonate calculation ENABLED (wrote configs/08_stage4.yaml).")
        else:
            notes.append("Carbonate calculation already enabled (config unchanged).")
    else:
        # If the user turned it OFF and a previously-written config exists, we
        # rewrite it to enabled: false rather than delete it (so the user can
        # see the state explicitly and we never remove a file we didn't own).
        if stage4_path.exists():
            text = _dump_stage4_yaml(enabled=False)
            if stage4_path.read_text(encoding="utf-8") != text:
                stage4_path.write_text(text, encoding="utf-8")
                written.append(stage4_path)
                notes.append("Carbonate calculation DISABLED (updated configs/08_stage4.yaml).")
            else:
                notes.append("Carbonate calculation off (config already disabled).")
        else:
            notes.append("Carbonate calculation off (using pipeline defaults).")

    # Decide whether a config dir needs to be passed at all: pass it if the
    # folder exists and contains any per-stage config the pipeline should read.
    has_configs = config_dir.exists() and any(config_dir.glob("*.yaml")) or \
        (config_dir.exists() and any(config_dir.glob("*.yml")))
    return ConfigResult(
        config_dir=config_dir if has_configs else None,
        written=written,
        notes=notes,
    )