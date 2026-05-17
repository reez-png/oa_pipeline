"""
oa_qc_ta_ph.py
==============
Quality-control routines for ocean-acidification chemistry data:
  - Total Alkalinity (TA) Certified Reference Material (CRM) QC + correction
  - pH-standard (TRIS / AMP / BIS) QC + optional correction

Used by Notebook 02 (`02_ta_ph_qc.ipynb`). Pulled out of the notebook so the
notebook itself reads as a narrative (load -> QC -> write) rather than a
~400-line wall of functions. This matches Rule 4 (modularize) and Rule 7
(build a pipeline) of "Ten Simple Rules for Reproducible Research in
Jupyter Notebooks" (PLOS Comp. Biol., 2019).

Reference tables (CRM_CERTIFIED_TA, PH_STD_TABLES) live at the top of this
file with a comment indicating their provenance. A chemist adding a new
CRM batch only edits one place.

This module has no notebook-specific code -- it can be imported and tested
independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from oa_common import (
    build_corrections_table,
    die,
    fmt,
    resolve_col,
    robust_outlier_flags,
    safe_str_series,
    utc_stamp,
    write_text,
)

__all__ = [
    # Reference data
    "CRM_CERTIFIED_TA",
    "PH_STD_TABLES",
    # Dataclasses
    "TaSop",
    "PhStdStatusThresholds",
    # TA CRM
    "detect_ta_crm_rows",
    "apply_ta_sop_auto_rule",
    "apply_ta_crm_correction",
    "write_rm_ta_diff_qc_plot",
    "write_ta_markdown_report",
    # pH standard
    "ph_standard_expected",
    "detect_phstd_rows",
    "ph_status_from_mean",
    "apply_ph_standard_qc_and_correction",
    "write_phstd_qc_plot",
    "write_phstd_markdown_report",
]


# ===========================================================================
# Reference tables
# ===========================================================================
# CRM_CERTIFIED_TA: maps CRM batch identifier -> certified Total Alkalinity
# in micromol/kg. Source: Dickson lab certificate of analysis for each batch.
# Add new batches as they arrive.
CRM_CERTIFIED_TA: Dict[str, float] = {
    "213": 2203.56,
}

# PH_STD_TABLES: expected pH of each pH buffer (TRIS, AMP, BIS) at integer
# temperatures from -2 to 29 C. Source: standard buffer tables used in the
# Dickson SOP (Guide to Best Practices for Ocean CO2 Measurements, 2007,
# PICES Spec. Pub. 3, IOCCP Report 8). The functions below linearly
# interpolate between these anchors.
PH_STD_TABLES: Dict[str, Dict[int, float]] = {
    "tris": {
        -2: 9.007, -1: 8.970, 0: 8.934, 1: 8.897, 2: 8.861, 3: 8.825, 4: 8.790, 5: 8.754,
        6: 8.719, 7: 8.685, 8: 8.650, 9: 8.616, 10: 8.582, 11: 8.548, 12: 8.514, 13: 8.480,
        14: 8.447, 15: 8.414, 16: 8.381, 17: 8.349, 18: 8.316, 19: 8.284, 20: 8.252, 21: 8.220,
        22: 8.188, 23: 8.156, 24: 8.125, 25: 8.094, 26: 8.062, 27: 8.031, 28: 8.001, 29: 7.970,
    },
    "amp": {
        -2: 7.477, -1: 7.450, 0: 7.423, 1: 7.396, 2: 7.370, 3: 7.343, 4: 7.317, 5: 7.290,
        6: 7.264, 7: 7.238, 8: 7.212, 9: 7.186, 10: 7.161, 11: 7.135, 12: 7.110, 13: 7.084,
        14: 7.059, 15: 7.034, 16: 7.008, 17: 6.983, 18: 6.958, 19: 6.934, 20: 6.909, 21: 6.884,
        22: 6.860, 23: 6.835, 24: 6.811, 25: 6.787, 26: 6.762, 27: 6.738, 28: 6.714, 29: 6.690,
    },
    "bis": {
        -2: 9.773, -1: 9.736, 0: 9.688, 1: 9.651, 2: 9.624, 3: 9.588, 4: 9.551, 5: 9.515,
        6: 9.478, 7: 9.442, 8: 9.407, 9: 9.371, 10: 9.336, 11: 9.300, 12: 9.265, 13: 9.230,
        14: 9.196, 15: 9.161, 16: 9.127, 17: 9.093, 18: 9.059, 19: 9.025, 20: 8.992, 21: 8.958,
        22: 8.925, 23: 8.892, 24: 8.859, 25: 8.826, 26: 8.793, 27: 8.761, 28: 8.729, 29: 8.697,
    },
}


# ===========================================================================
# TA CRM QC
# ===========================================================================

@dataclass
class TaSop:
    """Standard-operating-procedure thresholds for TA CRM correction.

    no_adjust: if |mean CRM difference| <= this (umol/kg), the correction is
        forced to 0 ("noise floor"). Default 2.0 umol/kg.
    reject: if |mean CRM difference| > this (umol/kg), the correction is
        withheld and the QC status is FAIL. Default 20.0 umol/kg.
    """
    no_adjust: float = 2.0
    reject: float = 20.0


def detect_ta_crm_rows(
    df: pd.DataFrame,
    sample_tag_col: str,
    crm_or_sample_col: Optional[str],
    ta_col: str,
    crm_tag_prefix: str = "RM",
    require_ta_value: bool = True,
    allow_crm_flag_col: bool = False,
) -> pd.Series:
    """Boolean Series marking which rows are TA CRM measurements.

    A row is a CRM if its sample tag begins with `crm_tag_prefix`
    (case-insensitive). If `allow_crm_flag_col` is True and a
    crm-or-sample flag column was supplied, rows where that flag equals
    "crm" are also accepted. If `require_ta_value` is True, rows must also
    have a numeric TA (which is almost always what you want).
    """
    tag = safe_str_series(df[sample_tag_col]).str.upper()
    is_rm = tag.str.startswith(crm_tag_prefix.upper())

    ta = pd.to_numeric(df[ta_col], errors="coerce")
    has_ta = ~ta.isna()

    is_crm = is_rm
    if allow_crm_flag_col and crm_or_sample_col is not None:
        flag = safe_str_series(df[crm_or_sample_col]).str.lower()
        is_crm = is_crm | (flag == "crm")

    if require_ta_value:
        is_crm = is_crm & has_ta

    return is_crm


def apply_ta_sop_auto_rule(
    corr: pd.Series,
    sop: TaSop,
) -> Tuple[pd.Series, pd.Series]:
    """Translate a raw correction into a per-row SOP status + applied value.

    Returns (status_series, correction_applied_series) where:
      INSUFFICIENT_DATA -> applied = NA  (no correction computed)
      NO_ADJUST         -> applied = 0   (within the noise floor)
      ADJUST            -> applied = raw correction
      FAIL              -> applied = NA  (correction exceeds reject threshold)
    """
    c = pd.to_numeric(corr, errors="coerce")

    status = pd.Series("INSUFFICIENT_DATA", index=c.index, dtype="string")
    corr_applied = pd.Series(pd.NA, index=c.index, dtype="Float64")

    ok = c.notna()
    status.loc[ok] = "ADJUST"
    corr_applied.loc[ok] = c.loc[ok].astype("Float64")

    no_adj = ok & (c.abs() <= float(sop.no_adjust))
    status.loc[no_adj] = "NO_ADJUST"
    corr_applied.loc[no_adj] = 0.0

    fail = ok & (c.abs() > float(sop.reject))
    status.loc[fail] = "FAIL"
    corr_applied.loc[fail] = pd.NA

    return status, corr_applied


def apply_ta_crm_correction(
    df: pd.DataFrame,
    ta_col: str,
    sample_tag_col: str,
    crm_or_sample_col: Optional[str],
    crm_batch: str,
    crm_ta_override: Optional[float],
    group_by: Optional[str],
    crm_tag_prefix: str,
    allow_crm_flag_col: bool,
    require_ta_value_for_crm: bool,
    min_crm_n: int,
    mad_k: float,
    max_abs_diff: Optional[float],
    correct_only_samples: bool,
    sop: TaSop,
    sample_flag_value: str = "sample",
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Detect CRM rows, compute mean (certified - measured), and correct samples.

    Returns
    -------
    out : DataFrame
        `df` with extra columns:
          - is_ta_crm_row, crm_batch_used, ta_certified_umolkg
          - ta_correction_raw_umolkg, ta_correction_used_umolkg
          - ta_qc_status, ta_corrected_umolkg
          - ta_has_value, ta_corrected_available
        plus, if `group_by` is set, the per-group correction stats.
    crm_qc : DataFrame
        Per-CRM-row QC: certified value, diff, outlier flags. Save this!
    corr_table : DataFrame
        Per-group (or overall) correction summary.
    summary : dict
        Run-level diagnostics for the report.
    """
    ta_col = resolve_col(df, ta_col)
    sample_tag_col = resolve_col(df, sample_tag_col)
    crm_or_sample_col_res: Optional[str] = None
    if crm_or_sample_col and crm_or_sample_col in df.columns:
        crm_or_sample_col_res = resolve_col(df, crm_or_sample_col)

    if crm_ta_override is not None:
        ta_cert = float(crm_ta_override)
        batch_used = "override"
    else:
        if crm_batch not in CRM_CERTIFIED_TA:
            die(f"Unknown CRM batch '{crm_batch}'. Known: {list(CRM_CERTIFIED_TA.keys())}")
        ta_cert = float(CRM_CERTIFIED_TA[crm_batch])
        batch_used = crm_batch

    out = df.copy()
    out[ta_col] = pd.to_numeric(out[ta_col], errors="coerce")

    is_crm = detect_ta_crm_rows(
        out,
        sample_tag_col=sample_tag_col,
        crm_or_sample_col=crm_or_sample_col_res,
        ta_col=ta_col,
        crm_tag_prefix=crm_tag_prefix,
        require_ta_value=require_ta_value_for_crm,
        allow_crm_flag_col=allow_crm_flag_col,
    )

    if crm_or_sample_col_res is not None:
        flag = safe_str_series(out[crm_or_sample_col_res]).str.lower()
        is_sample = flag.eq(sample_flag_value.lower())
    else:
        is_sample = ~is_crm

    crm = out.loc[is_crm].copy()
    crm["ta_certified_umolkg"] = ta_cert
    crm["ta_diff_umolkg"] = crm["ta_certified_umolkg"] - crm[ta_col]
    crm["ta_exceeds_sop_reject"] = crm["ta_diff_umolkg"].abs() > float(sop.reject)
    crm["ta_diff_umolkg_is_outlier"] = robust_outlier_flags(
        crm["ta_diff_umolkg"], mad_k=mad_k, max_abs=max_abs_diff
    )

    corr_table = build_corrections_table(
        crm, group_by=group_by, diff_col="ta_diff_umolkg", min_n=min_crm_n
    )

    if group_by and group_by in corr_table.columns:
        corr_table = corr_table.rename(
            columns={
                "n": "ta_corr_n",
                "correction": "ta_corr_value",
                "sd": "ta_corr_sd",
                "group_has_min_n": "ta_corr_group_has_min_n",
            }
        )

    out["crm_batch_used"] = batch_used
    out["ta_certified_umolkg"] = ta_cert
    out["is_ta_crm_row"] = is_crm

    overall_n = int(corr_table.get("overall_n", pd.Series([0])).iloc[0])
    overall_corr = float(corr_table.get("overall_correction", pd.Series([float("nan")])).iloc[0])
    overall_sd = float(corr_table.get("overall_sd", pd.Series([float("nan")])).iloc[0])

    out["ta_correction_raw_umolkg"] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    if group_by and group_by in out.columns and group_by in corr_table.columns:
        out = out.merge(
            corr_table[[group_by, "ta_corr_n", "ta_corr_value", "ta_corr_sd", "ta_corr_group_has_min_n"]],
            on=group_by,
            how="left",
        )
        raw = pd.to_numeric(out["ta_corr_value"], errors="coerce").fillna(overall_corr)
        out["ta_correction_raw_umolkg"] = raw.astype("Float64")
    else:
        out["ta_correction_raw_umolkg"] = pd.Series(overall_corr, index=out.index, dtype="Float64")

    if overall_n < int(min_crm_n) or pd.isna(overall_corr):
        out["ta_correction_raw_umolkg"] = pd.NA

    ta_status, ta_corr_applied = apply_ta_sop_auto_rule(out["ta_correction_raw_umolkg"], sop=sop)
    out["ta_qc_status"] = ta_status
    out["ta_correction_used_umolkg"] = ta_corr_applied

    out["ta_corrected_umolkg"] = out[ta_col] + pd.to_numeric(out["ta_correction_used_umolkg"], errors="coerce")

    if correct_only_samples:
        out.loc[~is_sample, "ta_corrected_umolkg"] = out.loc[~is_sample, ta_col]

    out["ta_has_value"] = ~out[ta_col].isna()
    out["ta_corrected_available"] = ~out["ta_corrected_umolkg"].isna()

    crm_valid = int(crm["ta_diff_umolkg"].notna().sum())
    crm_out = int(crm["ta_diff_umolkg_is_outlier"].sum()) if "ta_diff_umolkg_is_outlier" in crm else 0
    crm_kept = int(crm_valid - crm_out)

    overall_status = (
        "INSUFFICIENT_DATA" if (overall_n < int(min_crm_n) or pd.isna(overall_corr))
        else ("NO_ADJUST" if abs(overall_corr) <= float(sop.no_adjust)
              else ("FAIL" if abs(overall_corr) > float(sop.reject) else "ADJUST"))
    )

    diagnostics: list[str] = []
    if int(crm.shape[0]) == 0:
        diagnostics.append("No TA CRM or RM rows detected.")
    if crm_valid == 0 and int(crm.shape[0]) > 0:
        diagnostics.append("CRM rows were detected, but none had numeric TA.")
    if crm_valid > 0 and crm_kept == 0:
        diagnostics.append("All valid CRM differences were rejected as outliers.")
    if overall_n < int(min_crm_n):
        diagnostics.append(f"Not enough non outlier CRMs to compute a correction: kept N = {overall_n}.")
    if overall_status == "FAIL":
        diagnostics.append("Mean TA difference exceeds the SOP reject threshold, so correction is withheld.")
    if overall_status == "NO_ADJUST":
        diagnostics.append("Mean TA difference is within the SOP no adjust threshold, so correction is forced to 0.0.")

    n_samples_flagged = int(is_sample.sum())
    n_samples_ta_missing = int(out.loc[is_sample, ta_col].isna().sum()) if n_samples_flagged > 0 else 0
    n_samples_corrected = int(out.loc[is_sample, "ta_corrected_available"].sum()) if n_samples_flagged > 0 else 0

    summary: Dict[str, Any] = {
        "crm_n_detected": int(crm.shape[0]),
        "crm_n_valid": int(crm_valid),
        "crm_n_outlier": int(crm_out),
        "crm_n_kept": int(crm_kept),
        "overall_n_kept": int(overall_n),
        "overall_corr": overall_corr,
        "overall_sd": overall_sd,
        "sop_no_adjust": float(sop.no_adjust),
        "sop_reject": float(sop.reject),
        "overall_status": overall_status,
        "n_samples_flagged": n_samples_flagged,
        "n_samples_ta_missing": n_samples_ta_missing,
        "n_samples_corrected": n_samples_corrected,
        "diagnostics": diagnostics,
    }

    return out, crm, corr_table, summary


def write_rm_ta_diff_qc_plot(
    crm_qc: pd.DataFrame,
    out_jpeg: Path,
    sample_tag_col: str,
    sop: TaSop,
    annotate_points: bool = True,
    title: str = "RM Alkalinity Difference",
) -> None:
    """Write a JPEG scatter of analysis-number vs. (certified - measured) TA.

    Solid horizontal lines: zero and +/- SOP no-adjust threshold.
    Dotted horizontal lines: +/- SOP reject threshold.

    matplotlib is imported lazily so that headless/CI environments without
    it can still run the rest of the QC.
    """
    try:
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover - import guard
        die(f"matplotlib is required for plotting. Details: {e}")

    if crm_qc.empty:
        die("No RM or CRM TA rows detected for plotting.")

    dfp = crm_qc.copy()
    dfp["ta_diff_umolkg"] = pd.to_numeric(dfp["ta_diff_umolkg"], errors="coerce")
    dfp = dfp[dfp["ta_diff_umolkg"].notna()].copy()
    if dfp.empty:
        die("No numeric TA differences to plot.")

    dfp["analysis_number"] = range(1, len(dfp) + 1)

    exceeds = dfp[dfp.get("ta_exceeds_sop_reject", False)].copy()
    rest = dfp[~dfp.index.isin(exceeds.index)].copy()
    rest_bad = rest[rest.get("ta_diff_umolkg_is_outlier", False)].copy()
    rest_ok = rest[~rest.index.isin(rest_bad.index)].copy()

    fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=170)

    if not rest_ok.empty:
        ax.scatter(rest_ok["analysis_number"], rest_ok["ta_diff_umolkg"], s=56, marker="o", label="RM kept")
    if not rest_bad.empty:
        ax.scatter(rest_bad["analysis_number"], rest_bad["ta_diff_umolkg"], s=72, marker="x", label="RM outlier")
    if not exceeds.empty:
        ax.scatter(exceeds["analysis_number"], exceeds["ta_diff_umolkg"], s=120, marker="x", label="RM exceeds SOP")

    ax.axhline(0.0, linewidth=1.2)
    ax.axhline(+float(sop.no_adjust), linestyle="--", linewidth=1.2)
    ax.axhline(-float(sop.no_adjust), linestyle="--", linewidth=1.2)
    ax.axhline(+float(sop.reject), linestyle=":", linewidth=1.6)
    ax.axhline(-float(sop.reject), linestyle=":", linewidth=1.6)

    ax.set_title(title, fontsize=16, pad=10)
    ax.set_xlabel("Analysis Number", fontsize=12)
    ax.set_ylabel("RM TA Difference (umol/kg)\n(certified - measured)", fontsize=12)
    ax.grid(True, linestyle=":", linewidth=1.0)

    if annotate_points and sample_tag_col in dfp.columns:
        for _, r in dfp.iterrows():
            tag = str(r.get(sample_tag_col, "")).strip()
            if tag:
                ax.annotate(
                    tag,
                    (r["analysis_number"], r["ta_diff_umolkg"]),
                    textcoords="offset points",
                    xytext=(6, 4),
                    fontsize=9,
                )

    ymax = float(dfp["ta_diff_umolkg"].abs().max())
    pad = max(2.0, 0.15 * ymax)
    ax.set_ylim(-(ymax + pad), +(ymax + pad))
    ax.legend(frameon=False, fontsize=10, loc="best")
    fig.tight_layout()

    out_jpeg.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_jpeg, format="jpeg", dpi=240, bbox_inches="tight")
    plt.close(fig)


def write_ta_markdown_report(
    out_md: Path,
    xlsx_path: Path,
    sheet_name: str,
    params: Dict[str, Any],
    ta_summary: Dict[str, Any],
    ta_col_used: str,
    sample_tag_col_used: str,
    group_by: Optional[str],
) -> None:
    """Write a one-page markdown summary of the TA CRM QC for this sheet."""
    diag_lines = "\n".join([f"- {d}" for d in ta_summary.get("diagnostics", [])]) or "- (none)"

    md = f"""# TA CRM QC Report

**Generated:** {utc_stamp()}
**Workbook:** `{xlsx_path}`
**Sheet:** `{sheet_name}`

## Status
- SOP status: **{ta_summary.get("overall_status")}**
- mean_diff_kept: {fmt(ta_summary.get("overall_corr"), nd=3)} umol/kg

## Inputs
- TA column: `{ta_col_used}`
- sample tag column: `{sample_tag_col_used}`
- crm or sample flag column: `{params.get("CRM_OR_SAMPLE_COL")}`
- CRM tag prefix: `{params.get("CRM_TAG_PREFIX")}`
- CRM batch: `{params.get("CRM_BATCH")}`
- group_by: `{group_by if group_by else "None"}`

## Counts
- CRM detected: {ta_summary.get("crm_n_detected")}
- CRM valid: {ta_summary.get("crm_n_valid")}
- CRM kept: {ta_summary.get("crm_n_kept")}
- CRM outliers: {ta_summary.get("crm_n_outlier")}
- sample rows detected: {ta_summary.get("n_samples_flagged")}
- sample rows missing TA: {ta_summary.get("n_samples_ta_missing")}
- sample rows corrected: {ta_summary.get("n_samples_corrected")}

## Diagnostics
{diag_lines}
"""
    write_text(out_md, md)


# ===========================================================================
# pH standard QC
# ===========================================================================

@dataclass
class PhStdStatusThresholds:
    """Status thresholds for the pH-standard QC.

    |mean diff| <= ok   -> OK
    |mean diff| <= warn -> WARN
    otherwise           -> FAIL
    """
    ok: float = 0.02
    warn: float = 0.05


def ph_standard_expected(buffer: str, temp_c: float) -> float:
    """Linear interpolation of the buffer's expected pH at temperature temp_c.

    Outside the table range, the value is clamped to the nearest endpoint.
    `buffer` must be one of the keys of PH_STD_TABLES (tris/amp/bis).
    """
    b = buffer.strip().lower()
    if b not in PH_STD_TABLES:
        die(f"Unknown pH buffer '{buffer}'. Choose from: {list(PH_STD_TABLES.keys())}")

    table = PH_STD_TABLES[b]
    xs = sorted(table.keys())

    if temp_c <= xs[0]:
        return table[xs[0]]
    if temp_c >= xs[-1]:
        return table[xs[-1]]

    for lo, hi in zip(xs[:-1], xs[1:]):
        if lo <= temp_c <= hi:
            ylo = table[lo]
            yhi = table[hi]
            w = (temp_c - lo) / (hi - lo)
            return ylo + w * (yhi - ylo)

    return table[xs[-1]]


def detect_phstd_rows(df: pd.DataFrame, sample_tag_col: str, tag_prefix: str) -> pd.Series:
    """Rows whose sample tag begins with `tag_prefix` (case-insensitive)."""
    tag = safe_str_series(df[sample_tag_col]).str.lower()
    return tag.str.startswith(tag_prefix.strip().lower())


def ph_status_from_mean(mean_diff: Optional[float], thr: PhStdStatusThresholds) -> str:
    """Map a mean (expected - measured) pH residual to OK / WARN / FAIL."""
    if mean_diff is None or pd.isna(mean_diff):
        return "INSUFFICIENT_DATA"
    a = abs(float(mean_diff))
    if a <= float(thr.ok):
        return "OK"
    if a <= float(thr.warn):
        return "WARN"
    return "FAIL"


def apply_ph_standard_qc_and_correction(
    df: pd.DataFrame,
    buffer: str,
    tag_prefix: str,
    ph_col: str,
    temp_col: str,
    sample_tag_col: str,
    crm_or_sample_col: Optional[str],
    group_by: Optional[str],
    mad_k: float,
    max_abs_diff: Optional[float],
    min_std_n: int,
    correct_samples: bool,
    status_thr: PhStdStatusThresholds,
    sample_flag_value: str = "sample",
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Detect pH-standard rows, compute (expected - measured) residual, correct samples.

    Same return shape as `apply_ta_crm_correction`: (out, phstd_qc,
    corr_table, summary).
    """
    out = df.copy()
    ph_col = resolve_col(out, ph_col)
    temp_col = resolve_col(out, temp_col)
    sample_tag_col = resolve_col(out, sample_tag_col)

    crm_or_sample_col_res: Optional[str] = None
    if crm_or_sample_col and crm_or_sample_col in out.columns:
        crm_or_sample_col_res = resolve_col(out, crm_or_sample_col)

    out[ph_col] = pd.to_numeric(out[ph_col], errors="coerce")
    out[temp_col] = pd.to_numeric(out[temp_col], errors="coerce")

    is_std = detect_phstd_rows(out, sample_tag_col=sample_tag_col, tag_prefix=tag_prefix)
    out["is_phstd_row"] = is_std

    if crm_or_sample_col_res is not None:
        flag = safe_str_series(out[crm_or_sample_col_res]).str.lower()
        is_sample = flag.eq(sample_flag_value.lower())
    else:
        is_sample = ~is_std

    std_detected = out.loc[is_std].copy()
    n_detected = int(std_detected.shape[0])

    std = std_detected[std_detected[temp_col].notna() & std_detected[ph_col].notna()].copy()
    n_valid = int(std.shape[0])

    if not std.empty:
        std["phstd_expected"] = std[temp_col].map(lambda t: ph_standard_expected(buffer, float(t)))
        std["phstd_diff"] = std["phstd_expected"] - std[ph_col]
        std["phstd_diff_is_outlier"] = robust_outlier_flags(std["phstd_diff"], mad_k=mad_k, max_abs=max_abs_diff)
    else:
        std["phstd_expected"] = pd.Series(dtype="float64")
        std["phstd_diff"] = pd.Series(dtype="float64")
        std["phstd_diff_is_outlier"] = pd.Series(dtype="bool")

    n_outlier = int(std["phstd_diff_is_outlier"].sum()) if n_valid > 0 else 0
    n_kept = int(n_valid - n_outlier)

    corr_table = build_corrections_table(std, group_by=group_by, diff_col="phstd_diff", min_n=min_std_n)

    if group_by and group_by in corr_table.columns:
        corr_table = corr_table.rename(
            columns={
                "n": "phstd_corr_n",
                "correction": "phstd_corr_value",
                "sd": "phstd_corr_sd",
                "group_has_min_n": "phstd_corr_group_has_min_n",
            }
        )

    overall_n_kept = int(corr_table.get("overall_n", pd.Series([0])).iloc[0])
    overall_corr = float(corr_table.get("overall_correction", pd.Series([float("nan")])).iloc[0])
    overall_sd = float(corr_table.get("overall_sd", pd.Series([float("nan")])).iloc[0])

    out["phstd_buffer"] = buffer.lower()
    out["phstd_expected"] = pd.NA
    out["phstd_diff"] = pd.NA
    out["phstd_diff_is_outlier"] = pd.NA

    out.loc[std.index, "phstd_expected"] = std["phstd_expected"]
    out.loc[std.index, "phstd_diff"] = std["phstd_diff"]
    out.loc[std.index, "phstd_diff_is_outlier"] = std["phstd_diff_is_outlier"]

    out["phstd_correction_raw"] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    if group_by and group_by in out.columns and group_by in corr_table.columns:
        out = out.merge(
            corr_table[[group_by, "phstd_corr_n", "phstd_corr_value", "phstd_corr_sd", "phstd_corr_group_has_min_n"]],
            on=group_by,
            how="left",
        )
        raw = pd.to_numeric(out["phstd_corr_value"], errors="coerce").fillna(overall_corr)
        out["phstd_correction_raw"] = raw.astype("Float64")
    else:
        out["phstd_correction_raw"] = pd.Series(overall_corr, index=out.index, dtype="Float64")

    if overall_n_kept < int(min_std_n) or pd.isna(overall_corr):
        out["phstd_correction_raw"] = pd.NA

    out["phstd_status"] = (
        out["phstd_correction_raw"]
        .map(lambda v: ph_status_from_mean(v, status_thr))
        .astype("string")
    )

    out["phstd_correction_used"] = pd.to_numeric(out["phstd_correction_raw"], errors="coerce").astype("Float64")
    out.loc[out["phstd_status"].eq("FAIL"), "phstd_correction_used"] = pd.NA
    out.loc[out["phstd_status"].eq("INSUFFICIENT_DATA"), "phstd_correction_used"] = pd.NA

    out["ph_corrected_from_phstd"] = pd.NA
    if correct_samples:
        corr_used = pd.to_numeric(out["phstd_correction_used"], errors="coerce")
        out.loc[is_sample, "ph_corrected_from_phstd"] = out.loc[is_sample, ph_col] + corr_used.loc[is_sample]

    overall_status = ph_status_from_mean(
        overall_corr if overall_n_kept >= int(min_std_n) else float("nan"),
        status_thr,
    )

    diagnostics: list[str] = []
    if not correct_samples:
        diagnostics.append("Samples are not corrected because phstd_correct_samples is False.")
    if n_detected == 0:
        diagnostics.append("No pH standard rows were detected.")
    if n_valid == 0 and n_detected > 0:
        diagnostics.append("Standard rows were detected, but none had both numeric temperature and numeric pH.")
    if n_valid > 0 and n_kept == 0:
        diagnostics.append("All valid pH standards were rejected as outliers.")
    if overall_n_kept < int(min_std_n):
        diagnostics.append(f"Not enough non outlier standards to compute a correction: kept N = {overall_n_kept}.")
    if overall_status == "FAIL":
        diagnostics.append("Mean pH offset exceeds the FAIL threshold, so correction is withheld.")

    n_samples_flagged = int(is_sample.sum())
    n_samples_ph_missing = int(out.loc[is_sample, ph_col].isna().sum()) if n_samples_flagged > 0 else 0

    summary: Dict[str, Any] = {
        "buffer": buffer.lower(),
        "tag_prefix": tag_prefix,
        "ph_col_used": ph_col,
        "temp_col_used": temp_col,
        "group_by": group_by,
        "n_detected": n_detected,
        "n_valid": n_valid,
        "n_outlier": n_outlier,
        "n_kept": n_kept,
        "overall_n_kept": overall_n_kept,
        "mean_diff_kept": overall_corr if overall_n_kept >= int(min_std_n) else float("nan"),
        "sd_diff_kept": overall_sd,
        "overall_status": overall_status,
        "status_ok": float(status_thr.ok),
        "status_warn": float(status_thr.warn),
        "n_samples_flagged": n_samples_flagged,
        "n_samples_ph_missing": n_samples_ph_missing,
        "diagnostics": diagnostics,
    }

    return out, std, corr_table, summary


def write_phstd_qc_plot(
    phstd_qc: pd.DataFrame,
    out_jpeg: Path,
    sample_tag_col: str,
    diff_col: str,
    outlier_col: str,
    thr_ok: float,
    thr_warn: float,
    annotate_points: bool,
    title: str,
    summary: Dict[str, Any],
) -> None:
    """JPEG scatter of analysis-number vs. (expected - measured) pH.

    Dashed lines: +/- ok threshold. Dotted lines: +/- warn threshold.
    """
    try:
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        die(f"matplotlib is required for plotting. Details: {e}")

    if phstd_qc.empty:
        die("No pH standard rows detected for plotting.")

    dfp = phstd_qc.copy()
    dfp[diff_col] = pd.to_numeric(dfp[diff_col], errors="coerce")
    dfp = dfp[dfp[diff_col].notna()].copy()
    if dfp.empty:
        die("No numeric pH differences to plot.")

    dfp["analysis_number"] = range(1, len(dfp) + 1)
    ok = dfp[~dfp[outlier_col]].copy()
    bad = dfp[dfp[outlier_col]].copy()

    fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=170)
    if not ok.empty:
        ax.scatter(ok["analysis_number"], ok[diff_col], s=58, marker="o", label="Std kept")
    if not bad.empty:
        ax.scatter(bad["analysis_number"], bad[diff_col], s=92, marker="x", label="Std outlier")

    ax.axhline(0.0, linewidth=1.2)
    ax.axhline(+thr_ok, linestyle="--", linewidth=1.2)
    ax.axhline(-thr_ok, linestyle="--", linewidth=1.2)
    ax.axhline(+thr_warn, linestyle=":", linewidth=1.6)
    ax.axhline(-thr_warn, linestyle=":", linewidth=1.6)

    ax.set_title(title, fontsize=18, pad=10)
    ax.set_xlabel("Analysis Number", fontsize=12)
    ax.set_ylabel("pH Difference\n(expected - measured)", fontsize=12)
    ax.grid(True, linestyle=":", linewidth=1.0)

    if annotate_points and sample_tag_col in dfp.columns:
        for _, r in dfp.iterrows():
            tag = str(r.get(sample_tag_col, "")).strip()
            if tag:
                ax.annotate(
                    tag,
                    (r["analysis_number"], r[diff_col]),
                    textcoords="offset points",
                    xytext=(6, 4),
                    fontsize=10,
                )

    box = (
        f"N_detected={summary.get('n_detected','?')}, N_valid={summary.get('n_valid','?')}\n"
        f"N_kept={summary.get('n_kept','?')}, N_outlier={summary.get('n_outlier','?')}\n"
        f"mean_kept={fmt(summary.get('mean_diff_kept'), nd=4)}, sd_kept={fmt(summary.get('sd_diff_kept'), nd=4)}\n"
        f"status={summary.get('overall_status','?')}"
    )
    ax.text(
        0.99, 0.02, box,
        transform=ax.transAxes,
        ha="right", va="bottom",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="0.6", alpha=0.95),
    )

    ymax = float(dfp[diff_col].abs().max())
    pad = max(0.01, 0.20 * ymax)
    ax.set_ylim(-(ymax + pad), +(ymax + pad))
    ax.legend(frameon=False, fontsize=10, loc="best")
    fig.tight_layout()

    out_jpeg.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_jpeg, format="jpeg", dpi=240, bbox_inches="tight")
    plt.close(fig)


def write_phstd_markdown_report(
    out_md: Path,
    xlsx_path: Path,
    sheet_name: str,
    params: Dict[str, Any],
    ph_summary: Dict[str, Any],
) -> None:
    """One-page markdown summary of the pH-standard QC for this sheet."""
    diag_lines = "\n".join([f"- {d}" for d in ph_summary.get("diagnostics", [])]) or "- (none)"

    md = f"""# pH Standard QC Report

**Generated:** {utc_stamp()}
**Workbook:** `{xlsx_path}`
**Sheet:** `{sheet_name}`
**Buffer:** `{ph_summary.get("buffer")}`
**Tag prefix:** `{ph_summary.get("tag_prefix")}`

## Status
- Overall status: **{ph_summary.get("overall_status")}**
- mean_diff_kept: {fmt(ph_summary.get("mean_diff_kept"), nd=4)}

## Counts
- detected: {ph_summary.get("n_detected")}
- valid: {ph_summary.get("n_valid")}
- kept: {ph_summary.get("n_kept")}
- outliers: {ph_summary.get("n_outlier")}
- sample rows detected: {ph_summary.get("n_samples_flagged")}
- sample rows missing pH: {ph_summary.get("n_samples_ph_missing")}

## Diagnostics
{diag_lines}
"""
    write_text(out_md, md)
