"""
oa_policy.py
============
Range-policy dataclass and per-record range flags.

This module exists so that the same `RangePolicy` is used everywhere it
appears in the pipeline. In the original monolithic notebook the dataclass
was redefined in three sections (Stage 1A, Stage 1B, Stage 4) with
*different fields each time* -- a textbook example of the "redefine in
every cell" anti-pattern documented by Pimentel et al. (2019). The fix
is structural: one definition, imported.

What lives here
---------------
- `RangePolicy`         : the dataclass (sal/ta/ph/depth/lat/lon ranges)
- `policy_from_config`  : build a `RangePolicy` from a config dict
- `add_stage_range_flags` : add `flag_*_out_of_range` columns to a frame

What does NOT live here
-----------------------
- Anything about *canonical aliases* (column-name resolution) -> oa_schema.py
- Anything about pH-buffer or CRM thresholds                   -> oa_qc_ta_ph.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

__all__ = [
    "RangePolicy",
    "policy_from_config",
    "add_stage_range_flags",
]


@dataclass
class RangePolicy:
    """Plausible-value ranges for the carbonate chemistry core fields.

    Values outside these intervals get a `flag_*_out_of_range` set to True
    by `add_stage_range_flags`. They are *not* removed -- flagging is
    advisory, not destructive (Rule 4 of the data-harmonization pattern:
    validate at the boundary, do not silently drop).

    This single dataclass holds the union of every stage's needs. Each
    stage's config file populates only the fields it cares about; the
    others fall back to defaults. The audit identified that the original
    notebook redefined this class three times across Stages 1A, 1B, and 4
    with *different fields each time* -- a silent-overwrite bug.
    The unified class fixes it by construction.

    Defaults are intentionally split into two tiers:
      * `sal`, `ta`, `ph`, `depth`, `lat`, `lon`: Stage 1A/1B "typical
        seawater" bounds. Tight enough that an obvious outlier flags.
      * `temp`, `dic`, `pco2`, `omega`: Stage 4 "physically plausible"
        bounds. Looser; meant to catch only nonsense values.

    Stage 4 in particular uses a *wider* pH range (6.0-9.5 vs the Stage
    1A 7.0-9.0 default) and a wider TA range (0-3500 vs 1000-3000) because
    its purpose is "could this physically be seawater chemistry?" not
    "is this typical open-ocean chemistry?" The configs encode which
    bounds each stage wants.
    """
    # Salinity (Stages 1A/1B/4)
    sal_min: float = 0.0
    sal_max: float = 42.0
    # Total alkalinity (Stages 1A/1B/4)
    ta_min: float = 1000.0
    ta_max: float = 3000.0
    # pH (Stages 1A/1B/4)
    ph_min: float = 7.0
    ph_max: float = 9.0
    # Depth (Stages 1A/1B)
    depth_min: float = 0.0
    depth_max: float = 12000.0
    # Geographics (Stages 1A/1B)
    lat_min: float = -90.0
    lat_max: float = 90.0
    lon_min: float = -180.0
    lon_max: float = 180.0
    # Temperature (Stage 4)
    temp_min: float = -2.0
    temp_max: float = 40.0
    # DIC (Stage 4)
    dic_min: float = 0.0
    dic_max: float = 3500.0
    # pCO2 (Stage 4)
    pco2_min: float = 0.0
    pco2_max: float = 10000.0
    # Saturation states (Stage 4)
    omega_min: float = 0.0
    omega_max: float = 20.0


def policy_from_config(config: Dict[str, Any]) -> RangePolicy:
    """Build a `RangePolicy` from a config dict's `range_policy` sub-block.

    Missing keys fall back to the dataclass defaults. This is what lets
    a user override just the bounds they care about in a YAML config
    without restating the full set, and what lets each stage use its
    own subset of fields without collision.
    """
    rp = config.get("range_policy", {}) if config else {}
    # Keep only keys that map to dataclass fields, so a stray key in
    # the config doesn't crash with a TypeError.
    valid_fields = set(RangePolicy.__dataclass_fields__.keys())
    filtered = {k: float(v) for k, v in rp.items() if k in valid_fields}
    return RangePolicy(**filtered)


# ---------------------------------------------------------------------------
# Per-record flagging
# ---------------------------------------------------------------------------

def _range_flag(series: pd.Series, low: float, high: float) -> pd.Series:
    """True where the numeric value falls *outside* [low, high]; NA stays NA.

    Coerces non-numeric to NaN first, so a column of strings does not
    crash the whole pipeline -- it just yields all-NA flags, which the
    report then surfaces.
    """
    num = pd.to_numeric(series, errors="coerce")
    return (~num.between(low, high) & num.notna()).astype("boolean")


# Mapping from canonical column name to (low_attr, high_attr) on RangePolicy.
# Keeping it as data means a new flagged field is one line, not a new branch.
_RANGE_MAP: Dict[str, tuple[str, str]] = {
    "latitude_deg":   ("lat_min", "lat_max"),
    "longitude_deg":  ("lon_min", "lon_max"),
    "salinity":       ("sal_min", "sal_max"),
    "depth_m":        ("depth_min", "depth_max"),
    "ta_umol_kg":     ("ta_min", "ta_max"),
    "ph_observed":    ("ph_min", "ph_max"),
    "ph_calculated":  ("ph_min", "ph_max"),
}

# Mapping from canonical column name to the *output* flag column name.
# Only difference from a name suffix is the `latitude_deg` -> `flag_lat...`
# shortening (matches the original notebook's choice).
_FLAG_NAME: Dict[str, str] = {
    "latitude_deg":  "flag_lat_out_of_range",
    "longitude_deg": "flag_lon_out_of_range",
    "salinity":      "flag_sal_out_of_range",
    "depth_m":       "flag_depth_out_of_range",
    "ta_umol_kg":    "flag_ta_out_of_range",
    "ph_observed":   "flag_ph_observed_out_of_range",
    "ph_calculated": "flag_ph_calculated_out_of_range",
}


def add_stage_range_flags(df: pd.DataFrame, policy: RangePolicy) -> None:
    """In-place: add a `flag_*_out_of_range` column for each known field.

    If the canonical column is absent, the flag column is created with
    all-NA values rather than being skipped, so downstream code can
    rely on every flag column existing.
    """
    for canonical, (low_attr, high_attr) in _RANGE_MAP.items():
        flag_col = _FLAG_NAME[canonical]
        if canonical in df.columns:
            df[flag_col] = _range_flag(
                df[canonical], getattr(policy, low_attr), getattr(policy, high_attr)
            )
        else:
            df[flag_col] = pd.Series(pd.NA, index=df.index, dtype="boolean")
