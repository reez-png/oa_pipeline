"""
alka.results — read pipeline outputs into structured data for the UI.

The existing core.summarize_verdicts returns a human-readable string, which is
fine for the log but not for a panel that wants to render counts as coloured
rows. This module reads the same analysis_ready.csv and returns structured
data, so the results panel can format it however it likes. Kept in Alka (not
the shared core) so the core module stays untouched.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# Canonical verdict order and display colours (foreground) for the panel.
VERDICT_ORDER = ["PASS", "REVIEW", "FAIL"]
VERDICT_COLOR = {
    "PASS": "#1a7f37",     # green
    "REVIEW": "#9a6700",   # amber
    "FAIL": "#b3261e",     # red
}


@dataclass
class VerdictSummary:
    found: bool                       # was analysis_ready.csv present?
    total: int = 0
    counts: Dict[str, int] = field(default_factory=dict)  # verdict -> n
    final_path: Optional[Path] = None
    carbonate_internal: Optional[bool] = None  # did the internal calc run?
    message: str = ""                 # human-readable note (errors etc.)


@dataclass
class PrecisionRow:
    variable: str
    n_pairs: int
    precision: float
    tolerance: float
    within_tolerance: bool
    sd_pooled: float = float("nan")
    mean_signal: float = float("nan")


@dataclass
class PrecisionPair:
    """One duplicate pair's difference for a variable (for the detail view)."""
    sample_id: str
    station: str
    diff: float


@dataclass
class PrecisionSummary:
    available: bool                   # could precision be computed?
    duplicate_type: str = "field"
    quality_tier: str = "weather"
    rows: list = field(default_factory=list)   # list[PrecisionRow]
    n_pairs: int = 0
    message: str = ""                 # note (e.g. "no duplicate pairs found")
    # per-variable list of PrecisionPair, for the "show pairs" detail view
    pairs_by_var: dict = field(default_factory=dict)


def read_verdicts(out_dir: Path) -> VerdictSummary:
    """Read verdict counts (and a couple of provenance facts) from the run."""
    final = Path(out_dir) / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    if not final.exists():
        return VerdictSummary(found=False,
                              message="No final analysis_ready.csv was produced.")
    try:
        counts: Dict[str, int] = {}
        carb_internal: Optional[bool] = None
        with final.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            status_col = "analysis_audit_status" if "analysis_audit_status" in fields else None
            has_carb = "carbonate_calc_internal" in fields
            if status_col is None:
                return VerdictSummary(found=True, final_path=final,
                                      message="Final file written (no verdict column found).")
            for row in reader:
                v = (row.get(status_col) or "").strip() or "(blank)"
                counts[v] = counts.get(v, 0) + 1
                if has_carb and carb_internal is not True:
                    val = (row.get("carbonate_calc_internal") or "").strip().lower()
                    if val in ("true", "1", "yes"):
                        carb_internal = True
            if has_carb and carb_internal is None:
                carb_internal = False
        total = sum(counts.values())
        return VerdictSummary(
            found=True, total=total, counts=counts, final_path=final,
            carbonate_internal=carb_internal,
        )
    except Exception as exc:  # noqa: BLE001
        return VerdictSummary(found=True, final_path=final,
                              message=f"Could not summarise: {exc}")


def ordered_counts(summary: VerdictSummary):
    """Yield (verdict, count, color) in canonical order, unknown verdicts last."""
    seen = set()
    for v in VERDICT_ORDER:
        if v in summary.counts:
            seen.add(v)
            yield v, summary.counts[v], VERDICT_COLOR.get(v, "#333333")
    for v, n in sorted(summary.counts.items()):
        if v not in seen:
            yield v, n, "#333333"


def read_precision(out_dir: Path,
                   duplicate_type: str = "field",
                   quality_tier: str = "weather") -> PrecisionSummary:
    """Compute duplicate-based precision on the run's analysis_ready.csv.

    Reuses oa_pipeline.duplicate_precision. Returns a PrecisionSummary the panel
    can render. Degrades gracefully: if the module isn't importable, pandas is
    missing, or there are no duplicate pairs, `available` is False with a note.
    """
    final = Path(out_dir) / "oa_stage4_outputs" / "data" / "analysis_ready.csv"
    if not final.exists():
        return PrecisionSummary(available=False, message="No final file to assess.")
    try:
        import pandas as pd
        from oa_pipeline import duplicate_precision as dp
    except Exception as exc:  # noqa: BLE001
        return PrecisionSummary(available=False,
                                message=f"Precision unavailable ({type(exc).__name__}).")
    try:
        df = pd.read_csv(final)
        res = dp.compute_precision(df, {"duplicate_type": duplicate_type,
                                        "quality_tier": quality_tier})
        if res.summary.empty:
            return PrecisionSummary(available=False, duplicate_type=duplicate_type,
                                    quality_tier=quality_tier,
                                    message="No duplicate pairs found in this dataset.")
        rows = []
        tier_verdict_col = f"{quality_tier}_verdict"
        tol_col = f"{quality_tier}_tolerance"
        for _, r in res.summary.iterrows():
            rows.append(PrecisionRow(
                variable=str(r["variable"]).upper(),
                n_pairs=int(r["n_pairs"]),
                precision=float(r["precision_2.2_SD_over_sqrtN"]),
                tolerance=float(r[tol_col]) if tol_col in r else float("nan"),
                within_tolerance=(str(r.get(tier_verdict_col, "")).upper() == "PASS"),
                sd_pooled=float(r["SD_pooled"]) if "SD_pooled" in r else float("nan"),
                mean_signal=float(r["mean_signal"]) if "mean_signal" in r else float("nan"),
            ))
        # per-pair differences for the detail view, sorted worst-first
        pairs_by_var: dict = {}
        pp = res.per_pair
        for canon in ("ta", "ph", "dic"):
            dcol = f"{canon}_diff"
            if dcol in pp.columns:
                sub = pp.dropna(subset=[dcol]).sort_values(dcol, ascending=False)
                pairs_by_var[canon.upper()] = [
                    PrecisionPair(
                        sample_id=str(row.get("sample_id", "")),
                        station=str(row.get("station_id", "")),
                        diff=float(row[dcol]),
                    )
                    for _, row in sub.iterrows()
                ]
        n_pairs = int(res.summary["n_pairs"].max())
        return PrecisionSummary(available=True, duplicate_type=duplicate_type,
                                quality_tier=quality_tier, rows=rows, n_pairs=n_pairs,
                                pairs_by_var=pairs_by_var)
    except Exception as exc:  # noqa: BLE001
        return PrecisionSummary(available=False,
                                message=f"Could not compute precision: {exc}")