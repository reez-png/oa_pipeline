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