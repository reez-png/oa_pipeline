"""
oa_pipeline.duplicate_precision — duplicate-based precision assessment.

Implements the GOA-ON Cookbook precision framework for duplicate samples:

  precision = 2.2 * (SD / sqrt(n))     [SOP 22/23; Dickson et al. 2007]

computed from duplicate pairs, and reports it against the operative quality
tolerance. Two duplicate *types* are supported and are scientifically distinct:

  * FIELD duplicates   — two samples collected from the same site/depth on the
                         same trip. They capture TOTAL uncertainty: small-scale
                         spatial/temporal heterogeneity at the site PLUS sample
                         handling PLUS analytical error. This is the default,
                         matching the current sampling design.
  * ANALYTICAL duplicates — one sample split and measured twice. They capture
                         ONLY analytical (instrument + operator) error.

The distinction matters: a field-duplicate spread is expected to be larger than
an analytical-duplicate spread, and the two must not be pooled or compared to
the same target uncritically. The module records which type it computed so the
reported precision is interpreted correctly.

Quality tiers (Cookbook / Newton et al. 2015):
  * WEATHER quality — suitable for mapping current state; looser tolerance.
  * CLIMATE quality — suitable for long-term trend detection; strict (~1 umol/kg
                      for TA). Reported for reference; not enforced when the
                      study targets weather quality.

Pairing: duplicate members share a `sample_id` and are distinguished by
`replicate_id` (e.g. 'a'/'b'). This is the reliable key; the '(R)' tag in
`sample_tag` is cosmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Cookbook precision multiplier (SOP 22/23). precision = K * SD / sqrt(n).
PRECISION_K = 2.2

DUPLICATE_PRECISION_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    # 'field' (default) or 'analytical' — what kind of duplicates these are.
    "duplicate_type": "field",
    # Variables to assess precision on (canonical -> accepted source names).
    "variables": {
        "ta": ["ta_corrected_umolkg", "ta_best_umolkg", "ta"],
        "ph": ["ph_best", "ph_observed", "pH_lab"],
        "dic": ["dic_best_umol_kg", "dic"],
    },
    # Pairing keys.
    "pair_on": "sample_id",       # duplicate members share this
    "member_col": "replicate_id",  # distinguishes a/b within a pair
    # Operative quality tier for this study: 'weather' or 'climate'.
    "quality_tier": "weather",
    # Per-variable tolerances (umol/kg for TA/DIC; pH units for pH).
    # Weather = looser (mapping); climate = strict (trend detection).
    "tolerances": {
        "ta":  {"weather": 10.0, "climate": 1.0},
        "dic": {"weather": 10.0, "climate": 2.0},
        "ph":  {"weather": 0.02, "climate": 0.005},
    },
    # Minimum number of duplicate pairs for a precision estimate to be trusted.
    # The cookbook recommends >= 10 replicate analyses.
    "min_pairs_recommended": 10,
}


@dataclass
class DuplicatePrecisionResult:
    per_pair: pd.DataFrame              # one row per duplicate pair, with diffs
    summary: pd.DataFrame              # one row per variable: precision, SD, n, tier verdict
    duplicate_type: str
    quality_tier: str
    notes: List[str] = field(default_factory=list)


def _first_present(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def compute_precision(df: pd.DataFrame,
                      settings: Optional[Dict[str, Any]] = None
                      ) -> DuplicatePrecisionResult:
    """Compute duplicate-based precision per variable.

    Returns per-pair differences and a per-variable summary containing the
    cookbook precision statistic and a pass/borderline verdict against the
    operative quality tier's tolerance.
    """
    cfg = dict(DUPLICATE_PRECISION_DEFAULTS)
    if settings:
        for k, v in settings.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v

    notes: List[str] = []
    dtype = str(cfg["duplicate_type"]).lower()
    tier = str(cfg["quality_tier"]).lower()

    pair_col = cfg["pair_on"]
    member_col = cfg["member_col"]
    if pair_col not in df.columns:
        raise RuntimeError(
            f"duplicate_precision: pairing column '{pair_col}' not found. "
            f"Cannot identify duplicate pairs."
        )

    # Identify pairs: a sample_id shared by >1 row (with distinct members).
    grp_sizes = df.groupby(pair_col).size()
    dup_ids = grp_sizes[grp_sizes >= 2].index
    dup = df[df[pair_col].isin(dup_ids)].copy()
    n_pairs = len(dup_ids)

    notes.append(
        f"Duplicate type: {dtype.upper()} "
        f"({'total uncertainty: sampling + analytical' if dtype=='field' else 'analytical only'}). "
        f"Quality tier: {tier.upper()}."
    )
    if n_pairs == 0:
        notes.append(f"No duplicate pairs found (no shared '{pair_col}').")
        return DuplicatePrecisionResult(pd.DataFrame(), pd.DataFrame(), dtype, tier, notes)

    if n_pairs < cfg["min_pairs_recommended"]:
        notes.append(
            f"Only {n_pairs} duplicate pairs (cookbook recommends "
            f">= {cfg['min_pairs_recommended']} for a robust precision estimate); "
            f"treat the precision figure as indicative."
        )

    # Build per-pair records and per-variable arrays.
    var_cols = {}
    for canon, cands in cfg["variables"].items():
        col = _first_present(df, cands)
        if col:
            var_cols[canon] = col

    per_pair_rows = []
    var_pair_values: Dict[str, List[float]] = {v: [] for v in var_cols}
    var_pair_means: Dict[str, List[float]] = {v: [] for v in var_cols}

    for sid, g in dup.groupby(pair_col):
        vals = g.sort_values(member_col) if member_col in g.columns else g
        row = {pair_col: sid, "n_members": len(g)}
        # station/date context if present
        for ctx in ("station_id", "sample_date", "depth_round_m", "depth_m"):
            if ctx in g.columns:
                row[ctx] = g[ctx].iloc[0]
        for canon, col in var_cols.items():
            series = pd.to_numeric(vals[col], errors="coerce").dropna()
            if len(series) >= 2:
                # For a duplicate pair the difference is |a - b|; for >2 members
                # use the range as the pair spread. Also record the within-pair SD.
                spread = float(series.max() - series.min())
                pair_sd = float(series.std(ddof=1))
                pair_mean = float(series.mean())
                row[f"{canon}_diff"] = spread
                row[f"{canon}_sd"] = pair_sd
                var_pair_values[canon].append(pair_sd)
                var_pair_means[canon].append(pair_mean)
        per_pair_rows.append(row)

    per_pair = pd.DataFrame(per_pair_rows)

    # Per-variable summary: pooled precision from the pair SDs.
    # For duplicate pairs the standard pooled-SD estimate is
    #   SD_pooled = sqrt( mean( pair_sd^2 ) )   (each pair contributes 1 dof)
    # then precision = K * SD_pooled / sqrt(n_pairs).
    summary_rows = []
    for canon in var_cols:
        sds = np.array(var_pair_values[canon], float)
        sds = sds[np.isfinite(sds)]
        n = len(sds)
        if n == 0:
            continue
        sd_pooled = float(np.sqrt(np.mean(sds ** 2)))
        precision = PRECISION_K * sd_pooled / np.sqrt(n)
        tol = cfg["tolerances"].get(canon, {}).get(tier, np.nan)
        tol_climate = cfg["tolerances"].get(canon, {}).get("climate", np.nan)
        verdict = ("n/a" if not np.isfinite(tol)
                   else ("PASS" if precision <= tol else "EXCEEDS"))
        summary_rows.append({
            "variable": canon,
            "n_pairs": n,
            "SD_pooled": round(sd_pooled, 4),
            "precision_2.2_SD_over_sqrtN": round(precision, 4),
            f"{tier}_tolerance": tol,
            f"{tier}_verdict": verdict,
            "climate_tolerance_ref": tol_climate,
            "mean_signal": round(float(np.mean(var_pair_means[canon])), 2),
        })
    summary = pd.DataFrame(summary_rows)

    # Weather-quality framing note (do not enforce climate tier).
    notes.append(
        "Reported precision is compared against the WEATHER-quality tolerance "
        "(operative tier for mapping current state). The CLIMATE-quality "
        "tolerance is shown for reference only and is not enforced."
    )
    return DuplicatePrecisionResult(per_pair, summary, dtype, tier, notes)


def make_control_chart(per_pair: pd.DataFrame, variable: str = "ta",
                       tolerance: Optional[float] = None,
                       outpath: Optional[str] = None,
                       duplicate_type: str = "field"):
    """Field/analytical duplicate-difference control chart (Cookbook Fig. 1-style).

    Plots the within-pair difference for `variable` across pairs, with the
    quality tolerance drawn as a control line. Returns the matplotlib Figure.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    col = f"{variable}_diff"
    if per_pair.empty or col not in per_pair.columns:
        return None
    d = per_pair.dropna(subset=[col]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(1, len(d) + 1)
    ax.scatter(x, d[col], s=45, color="steelblue", zorder=3,
               label=f"{duplicate_type} duplicate |diff|")
    if tolerance is not None and np.isfinite(tolerance):
        ax.axhline(tolerance, ls="--", color="firebrick", lw=1.2,
                   label=f"weather tolerance ({tolerance:g})")
    ax.axhline(0, color="0.6", lw=0.8)
    ax.set_xlabel("Duplicate pair (analysis order)")
    ax.set_ylabel(f"{variable.upper()} duplicate difference")
    ax.set_title(f"{duplicate_type.capitalize()} Duplicate Samples Difference — {variable.upper()}")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    if outpath:
        fig.savefig(outpath, dpi=150, bbox_inches="tight")
    return fig
