"""
qc_ta_ph.py
===========
Quality control routines for ocean acidification chemistry data:

- Total Alkalinity Certified Reference Material QC and correction.
- pH standard QC and optional correction.

Import as:

    from oa_pipeline.qc_ta_ph import ...

This module contains reusable QC logic only. Notebook 02 should call these
functions, write outputs, and present the workflow narrative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from .common import (
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
    "CRM_REFERENCE_METADATA",
    "CRM_CERTIFIED_VALUES_CONFIG",
    "load_crm_certified_values",
    "PH_STD_TABLES",
    "PH_STD_REFERENCE_METADATA",
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


# =============================================================================
# Reference data
# =============================================================================

# CRM_CERTIFIED_TA maps CRM batch identifier to certified Total Alkalinity in
# micromol kg-1.
#
# AUDIT FIX N-1 (CRITICAL — scientific data integrity)
# ---------------------------------------------------------------------------
# The previous version of this table contained FABRICATED values that the
# code itself described as "illustrative starting points". Cross-checking
# against the authoritative NOAA OCADS Dickson CRM batch table revealed that
# SEVEN of the eight hardcoded values were wrong — by up to ~50 umol/kg
# (batch 220 read 2198.33 here vs. the certified 2148.41). Because the
# certified value is subtracted from the measured CRM to derive the
# correction applied to EVERY sample's TA, a wrong certified value injects a
# systematic bias of the same magnitude into the whole dataset. The QC
# tolerance is ~1-2 umol/kg, so a 50 umol/kg error is catastrophic and
# silent.
#
# What changed:
#   1. The preferred source of certified values is now the versioned data
#      file configs/crm_certified_values.yaml, loaded via
#      load_crm_certified_values(). Values there are transcribed from the
#      NOAA OCADS table (https://www.ncei.noaa.gov/access/
#      ocean-carbon-acidification-data-system/oceans/Dickson_CRM/batches.html).
#   2. The in-code dictionary below is retained ONLY as a fallback for code
#      that imports CRM_CERTIFIED_TA directly, and every value in it has been
#      corrected against the same authoritative table. It is NOT a complete
#      list — prefer the YAML file, or pass crm_ta_override with the exact
#      value from your certificate.
#   3. The batch lookup now raises a clear, instructive error (see
#      apply_ta_crm_correction) listing both the YAML path and the override
#      option, rather than silently offering a fabricated default.
#
# Reproducibility of Dickson certification is < 1 umol/kg, accuracy within
# 2 umol/kg (Dickson, Afghan & Anderson 2003, Marine Chemistry 80:185-197).
# GOA-ON / WMO TA data-quality objectives: 2 / 1 umol/kg.
CRM_CERTIFIED_TA: Dict[str, float] = {
    # Batch: certified TA (umol kg-1) — transcribed from NOAA OCADS, 2026-05-29.
    # Verify against the per-batch certificate PDF for your bottle lot.
    "180": 2224.47,
    "195": 2213.51,
    "200": 2186.43,
    "205": 2202.05,
    "210": 2220.62,
    "211": 2218.40,
    "212": 2193.54,
    "213": 2203.56,
    "214": 2200.67,
    "215": 2191.30,
    "216": 2188.02,
    "217": 2212.31,
    "218": 2197.08,
    "219": 2183.64,
    "220": 2148.41,
    "221": 2183.42,
    "222": 2215.63,
    "223": 2225.91,
    "224": 2235.50,
    "225": 2215.80,
}

CRM_REFERENCE_METADATA: Dict[str, str] = {
    "source": "NOAA OCADS — Dickson CO2 CRM batch table",
    "url": (
        "https://www.ncei.noaa.gov/access/ocean-carbon-acidification-data-system/"
        "oceans/Dickson_CRM/batches.html"
    ),
    "unit": "umol kg-1",
    "retrieved_utc": "2026-05-29",
    "notes": (
        "Certified TA transcribed from the NOAA OCADS batch table. Prefer the "
        "versioned file configs/crm_certified_values.yaml. Always confirm "
        "against the per-batch certificate PDF for the specific bottle lot."
    ),
}

# Default location of the versioned CRM values file, relative to the repo root.
CRM_CERTIFIED_VALUES_CONFIG = "configs/crm_certified_values.yaml"


def load_crm_certified_values(
    config_path: Optional[str | Path] = None,
) -> Dict[str, float]:
    """Load certified CRM Total Alkalinity values from a versioned YAML file.

    AUDIT FIX N-1: This is the preferred source of certified values, replacing
    the previously fabricated hardcoded table. The YAML file
    (configs/crm_certified_values.yaml) stores values transcribed from the
    authoritative NOAA OCADS Dickson CRM batch table together with provenance
    metadata (source URL, retrieval date, salinity, bottling date).

    Parameters
    ----------
    config_path:
        Path to the YAML file. When None, falls back to the corrected in-code
        CRM_CERTIFIED_TA dictionary so the function never silently returns an
        empty mapping.

    Returns
    -------
    dict[str, float]
        Mapping of batch identifier (string) to certified TA in umol kg-1.
    """
    if config_path is None:
        # No file supplied: return a copy of the corrected in-code fallback.
        return dict(CRM_CERTIFIED_TA)

    path = Path(config_path)
    if not path.exists():
        die(
            f"CRM certified-values file not found: {path}. "
            "Create it from configs/crm_certified_values.yaml (values "
            "transcribed from the NOAA OCADS Dickson CRM batch table), or "
            "pass crm_ta_override with the exact value from your certificate."
        )

    try:
        import yaml
    except ImportError:
        die(
            "Reading the CRM certified-values YAML requires PyYAML. "
            "Install with: python -m pip install pyyaml"
        )

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"Could not parse CRM certified-values file {path}: {exc}")

    if not isinstance(loaded, dict) or "batches" not in loaded:
        die(
            f"CRM certified-values file {path} must contain a top-level "
            "'batches' mapping."
        )

    result: Dict[str, float] = {}
    for batch, entry in (loaded.get("batches") or {}).items():
        key = str(batch)
        if isinstance(entry, dict):
            if "total_alkalinity_umol_kg" not in entry:
                die(
                    f"CRM batch '{key}' in {path} is missing "
                    "'total_alkalinity_umol_kg'."
                )
            value = entry["total_alkalinity_umol_kg"]
        else:
            # Allow a simple "batch: value" shorthand as well.
            value = entry
        try:
            result[key] = float(value)
        except Exception:
            die(
                f"CRM batch '{key}' in {path} has a non-numeric certified TA: "
                f"{value!r}"
            )

    if not result:
        die(f"CRM certified-values file {path} defined no usable batches.")

    return result

# PH_STD_TABLES gives expected pH of TRIS, AMP, and BIS buffers at integer
# temperatures from -2 to 29 deg C. Longer term, move this table to
# configs/ph_standard_tables.yaml with full source metadata.
PH_STD_TABLES: Dict[str, Dict[int, float]] = {
    "tris": {
        -2: 9.007,
        -1: 8.970,
        0: 8.934,
        1: 8.897,
        2: 8.861,
        3: 8.825,
        4: 8.790,
        5: 8.754,
        6: 8.719,
        7: 8.685,
        8: 8.650,
        9: 8.616,
        10: 8.582,
        11: 8.548,
        12: 8.514,
        13: 8.480,
        14: 8.447,
        15: 8.414,
        16: 8.381,
        17: 8.349,
        18: 8.316,
        19: 8.284,
        20: 8.252,
        21: 8.220,
        22: 8.188,
        23: 8.156,
        24: 8.125,
        25: 8.094,
        26: 8.062,
        27: 8.031,
        28: 8.001,
        29: 7.970,
    },
    "amp": {
        -2: 7.477,
        -1: 7.450,
        0: 7.423,
        1: 7.396,
        2: 7.370,
        3: 7.343,
        4: 7.317,
        5: 7.290,
        6: 7.264,
        7: 7.238,
        8: 7.212,
        9: 7.186,
        10: 7.161,
        11: 7.135,
        12: 7.110,
        13: 7.084,
        14: 7.059,
        15: 7.034,
        16: 7.008,
        17: 6.983,
        18: 6.958,
        19: 6.934,
        20: 6.909,
        21: 6.884,
        22: 6.860,
        23: 6.835,
        24: 6.811,
        25: 6.787,
        26: 6.762,
        27: 6.738,
        28: 6.714,
        29: 6.690,
    },
    "bis": {
        -2: 9.773,
        -1: 9.736,
        0: 9.688,
        1: 9.651,
        2: 9.624,
        3: 9.588,
        4: 9.551,
        5: 9.515,
        6: 9.478,
        7: 9.442,
        8: 9.407,
        9: 9.371,
        10: 9.336,
        11: 9.300,
        12: 9.265,
        13: 9.230,
        14: 9.196,
        15: 9.161,
        16: 9.127,
        17: 9.093,
        18: 9.059,
        19: 9.025,
        20: 8.992,
        21: 8.958,
        22: 8.925,
        23: 8.892,
        24: 8.859,
        25: 8.826,
        26: 8.793,
        27: 8.761,
        28: 8.729,
        29: 8.697,
    },
}

PH_STD_REFERENCE_METADATA: Dict[str, str] = {
    "source": "Dickson SOP buffer tables for ocean CO2 measurements",
    "temperature_range_c": "-2 to 29",
    "notes": "Values are linearly interpolated between integer temperature anchors.",
}


# =============================================================================
# Small internal helpers
# =============================================================================


def _bool_col(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    """Return a clean boolean Series even if the column is missing or has NA."""
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)

    s = df[col]

    if str(s.dtype) == "boolean":
        return s.fillna(default).astype(bool)

    if s.dtype == bool:
        return s.fillna(default)

    text = s.astype("string").str.strip().str.upper()
    true_values = {"TRUE", "T", "YES", "Y", "1"}
    false_values = {"FALSE", "F", "NO", "N", "0"}

    parsed = text.map(
        lambda value: (
            True
            if value in true_values
            else False
            if value in false_values
            else default
        )
    )

    return parsed.astype(bool)


def _safe_float(value: Any) -> float:
    """Return float(value), or nan if conversion fails."""
    try:
        return float(value)
    except Exception:
        return float("nan")


def _first_value(frame: pd.DataFrame, col: str, default: Any = pd.NA) -> Any:
    """Return the first value from frame[col], or default if unavailable."""
    if col not in frame.columns or frame.empty:
        return default
    return frame[col].iloc[0]


def _add_standard_error(
    frame: pd.DataFrame,
    sd_col: str,
    n_col: str,
    se_col: str,
) -> pd.DataFrame:
    """Add a standard error column when SD and N columns are available."""
    out = frame.copy()

    if sd_col in out.columns and n_col in out.columns:
        sd = pd.to_numeric(out[sd_col], errors="coerce")
        n = pd.to_numeric(out[n_col], errors="coerce")
        out[se_col] = sd / n.pow(0.5)

    return out


# =============================================================================
# TA CRM QC
# =============================================================================


@dataclass
class TaSop:
    """TA CRM correction thresholds in micromol kg-1."""

    no_adjust: float = 2.0
    reject: float = 20.0

    def __post_init__(self) -> None:
        self.no_adjust = float(self.no_adjust)
        self.reject = float(self.reject)

        if self.no_adjust < 0:
            raise ValueError("TaSop.no_adjust must be >= 0.")

        if self.reject <= self.no_adjust:
            raise ValueError("TaSop.reject must be greater than TaSop.no_adjust.")


def detect_ta_crm_rows(
    df: pd.DataFrame,
    sample_tag_col: str,
    crm_or_sample_col: Optional[str],
    ta_col: str,
    crm_tag_prefix: str = "RM",
    allow_crm_flag_col: bool = False,
) -> tuple[pd.Series, pd.Series]:
    """Return detected CRM rows and usable CRM rows separately.

    Detected CRM rows are identified by tag prefix or, optionally, a CRM flag
    column. Usable CRM rows are detected CRM rows with numeric TA values.
    """
    tag = safe_str_series(df[sample_tag_col]).str.upper()
    is_crm = tag.str.startswith(crm_tag_prefix.upper())

    if allow_crm_flag_col and crm_or_sample_col is not None:
        flag = safe_str_series(df[crm_or_sample_col]).str.lower()
        is_crm = is_crm | flag.eq("crm")

    ta = pd.to_numeric(df[ta_col], errors="coerce")
    is_usable_crm = is_crm & ta.notna()

    return is_crm.astype("boolean"), is_usable_crm.astype("boolean")


def apply_ta_sop_auto_rule(
    corr: pd.Series,
    sop: TaSop,
) -> Tuple[pd.Series, pd.Series]:
    """Translate raw correction values into SOP status and applied correction.

    Returns:
        (status_series, correction_applied_series)
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
    crm_values: Optional[Dict[str, float]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Detect CRM rows, compute CRM correction, and apply it to eligible rows.

    Returns:
        (out, crm_qc, corr_table, summary)

    CRM detection and CRM usability are recorded separately. A CRM row with
    missing or non numeric TA is still counted as a detected CRM row. If
    require_ta_value_for_crm is True, such rows cause a clear failure; if False,
    they are recorded but excluded from the correction calculation.

    AUDIT FIX N-1: ``crm_values`` lets the caller pass certified values loaded
    from configs/crm_certified_values.yaml (via load_crm_certified_values).
    When None, the corrected in-code CRM_CERTIFIED_TA fallback is used. The
    batch lookup raises a clear, instructive error if the batch is unknown,
    instead of silently substituting a fabricated default.
    """
    require_ta_value_for_crm = bool(require_ta_value_for_crm)
    certified_values = dict(crm_values) if crm_values else dict(CRM_CERTIFIED_TA)

    ta_col = resolve_col(df, ta_col)
    sample_tag_col = resolve_col(df, sample_tag_col)

    crm_or_sample_col_res: Optional[str] = None
    if crm_or_sample_col and crm_or_sample_col in df.columns:
        crm_or_sample_col_res = resolve_col(df, crm_or_sample_col)

    group_by_res: Optional[str] = None
    if group_by and group_by in df.columns:
        group_by_res = resolve_col(df, group_by)

    if crm_ta_override is not None:
        ta_cert = float(crm_ta_override)
        batch_used = "override"
    else:
        if crm_batch not in certified_values:
            die(
                f"Unknown CRM batch '{crm_batch}'. "
                f"Known batches: {sorted(certified_values.keys())}. "
                "Certified values must be transcribed from the per-batch "
                "Dickson certificate (see configs/crm_certified_values.yaml, "
                "sourced from the NOAA OCADS table). If your batch is not "
                "listed, add it there with its certified value, or pass "
                "crm_ta_override with the exact value from your certificate. "
                "The pipeline refuses to guess a certified value because a "
                "wrong value biases every corrected TA measurement."
            )
        ta_cert = float(certified_values[crm_batch])
        batch_used = str(crm_batch)

    out = df.copy()
    out[ta_col] = pd.to_numeric(out[ta_col], errors="coerce")

    is_crm, is_usable_crm = detect_ta_crm_rows(
        out,
        sample_tag_col=sample_tag_col,
        crm_or_sample_col=crm_or_sample_col_res,
        ta_col=ta_col,
        crm_tag_prefix=crm_tag_prefix,
        allow_crm_flag_col=allow_crm_flag_col,
    )

    if crm_or_sample_col_res is not None:
        flag = safe_str_series(out[crm_or_sample_col_res]).str.lower()
        is_sample = flag.eq(sample_flag_value.lower())
    else:
        is_sample = ~is_crm.fillna(False)

    out["crm_batch_used"] = batch_used
    out["ta_certified_umolkg"] = ta_cert
    out["is_ta_crm_row"] = is_crm.astype("boolean")
    out["is_ta_crm_usable"] = is_usable_crm.astype("boolean")
    out["is_ta_sample_row"] = is_sample.astype("boolean")

    crm_detected = out.loc[out["is_ta_crm_row"].fillna(False)].copy()
    crm = out.loc[out["is_ta_crm_usable"].fillna(False)].copy()

    n_crm_missing_ta = int(
        out.loc[out["is_ta_crm_row"].fillna(False), ta_col].isna().sum()
    )

    if require_ta_value_for_crm and n_crm_missing_ta > 0:
        die(
            f"{n_crm_missing_ta} TA CRM rows were detected but have missing "
            f"or non numeric TA values. Set require_ta_value_for_crm=False "
            f"to record these rows but exclude them from correction."
        )

    # FIX 4-A: Guard the CRM computation block *before* the computations so
    # the empty path never reaches the arithmetic. The previous code placed
    # the guard *after* assigning into crm[], making it a dead block that
    # silently re-assigned empty typed Series over already-existing columns.
    if crm.empty:
        crm = crm.copy()  # avoid SettingWithCopyWarning on empty slice
        crm["ta_certified_umolkg"] = pd.Series(dtype="float64")
        crm["ta_diff_umolkg"] = pd.Series(dtype="float64")
        crm["ta_exceeds_sop_reject"] = pd.Series(dtype="boolean")
        crm["ta_diff_umolkg_is_outlier"] = pd.Series(dtype="boolean")
    else:
        crm["ta_certified_umolkg"] = ta_cert
        crm["ta_diff_umolkg"] = crm["ta_certified_umolkg"] - crm[ta_col]
        crm["ta_exceeds_sop_reject"] = (
            crm["ta_diff_umolkg"].abs() > float(sop.reject)
        ).astype("boolean")
        crm["ta_diff_umolkg_is_outlier"] = robust_outlier_flags(
            crm["ta_diff_umolkg"],
            mad_k=mad_k,
            max_abs=max_abs_diff,
            min_n=max(5, int(min_crm_n)),
        ).astype("boolean")

    crm_for_correction = crm.loc[
        crm["ta_diff_umolkg"].notna()
        & ~crm["ta_diff_umolkg_is_outlier"].fillna(False)
    ].copy()

    corr_table = build_corrections_table(
        crm_for_correction,
        group_by=group_by_res,
        diff_col="ta_diff_umolkg",
        min_n=min_crm_n,
    )

    if group_by_res and group_by_res in corr_table.columns:
        corr_table = corr_table.rename(
            columns={
                "n": "ta_corr_n",
                "correction": "ta_corr_value",
                "sd": "ta_corr_sd",
                "group_has_min_n": "ta_corr_group_has_min_n",
            }
        )
        corr_table = _add_standard_error(
            corr_table,
            sd_col="ta_corr_sd",
            n_col="ta_corr_n",
            se_col="ta_corr_se",
        )

    overall_n = int(_first_value(corr_table, "overall_n", 0) or 0)
    overall_corr = _safe_float(_first_value(corr_table, "overall_correction", float("nan")))
    overall_sd = _safe_float(_first_value(corr_table, "overall_sd", float("nan")))
    overall_se = overall_sd / (overall_n ** 0.5) if overall_n > 0 and pd.notna(overall_sd) else float("nan")

    out["ta_correction_raw_umolkg"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    out["ta_correction_level"] = pd.Series(pd.NA, index=out.index, dtype="string")

    if group_by_res and group_by_res in out.columns and group_by_res in corr_table.columns:
        merge_cols = [
            group_by_res,
            "ta_corr_n",
            "ta_corr_value",
            "ta_corr_sd",
            "ta_corr_group_has_min_n",
        ]
        if "ta_corr_se" in corr_table.columns:
            merge_cols.append("ta_corr_se")

        out = out.merge(corr_table[merge_cols], on=group_by_res, how="left")
        group_raw = pd.to_numeric(out["ta_corr_value"], errors="coerce")
        has_group_corr = group_raw.notna()
        raw = group_raw.fillna(overall_corr)
        out["ta_correction_raw_umolkg"] = raw.astype("Float64")
        out["ta_correction_level"] = pd.Series("overall", index=out.index, dtype="string")
        out.loc[has_group_corr, "ta_correction_level"] = "group"
    else:
        out["ta_corr_n"] = overall_n
        out["ta_corr_value"] = overall_corr
        out["ta_corr_sd"] = overall_sd
        out["ta_corr_se"] = overall_se
        out["ta_corr_group_has_min_n"] = overall_n >= int(min_crm_n)
        out["ta_correction_raw_umolkg"] = pd.Series(overall_corr, index=out.index, dtype="Float64")
        out["ta_correction_level"] = pd.Series("overall", index=out.index, dtype="string")

    if overall_n < int(min_crm_n) or pd.isna(overall_corr):
        out["ta_correction_raw_umolkg"] = pd.NA
        out["ta_correction_level"] = pd.NA

    out.loc[out["ta_correction_raw_umolkg"].isna(), "ta_correction_level"] = pd.NA

    ta_status, ta_corr_applied = apply_ta_sop_auto_rule(
        out["ta_correction_raw_umolkg"],
        sop=sop,
    )

    out["ta_qc_status"] = ta_status
    out["ta_correction_used_umolkg"] = ta_corr_applied

    sample_mask = out["is_ta_sample_row"].fillna(False).astype(bool)
    has_ta = out[ta_col].notna()
    non_crm_with_ta = (~out["is_ta_crm_row"].fillna(False).astype(bool)) & has_ta
    eligible_mask = sample_mask if correct_only_samples else non_crm_with_ta
    corr_used = pd.to_numeric(out["ta_correction_used_umolkg"], errors="coerce")

    out["ta_correction_applied"] = (eligible_mask & has_ta & corr_used.notna()).astype("boolean")
    out["ta_correction_withheld"] = (
        eligible_mask
        & has_ta
        & out["ta_qc_status"].isin(["FAIL", "INSUFFICIENT_DATA"])
    ).astype("boolean")

    out["ta_corrected_umolkg"] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    apply_mask = out["ta_correction_applied"].fillna(False).astype(bool)
    out.loc[apply_mask, "ta_corrected_umolkg"] = (
        out.loc[apply_mask, ta_col] + corr_used.loc[apply_mask]
    )

    not_eligible = ~eligible_mask
    out.loc[not_eligible, "ta_corrected_umolkg"] = out.loc[not_eligible, ta_col]

    out["ta_has_value"] = has_ta.astype("boolean")
    out["ta_corrected_available"] = out["ta_corrected_umolkg"].notna().astype("boolean")

    crm_valid = int(crm["ta_diff_umolkg"].notna().sum()) if "ta_diff_umolkg" in crm.columns else 0
    crm_out = (
        int((crm["ta_diff_umolkg"].notna() & crm["ta_diff_umolkg_is_outlier"].fillna(False)).sum())
        if "ta_diff_umolkg_is_outlier" in crm.columns and "ta_diff_umolkg" in crm.columns
        else 0
    )
    crm_kept = int(crm_for_correction.shape[0])

    overall_status = (
        "INSUFFICIENT_DATA"
        if overall_n < int(min_crm_n) or pd.isna(overall_corr)
        else (
            "NO_ADJUST"
            if abs(overall_corr) <= float(sop.no_adjust)
            else "FAIL"
            if abs(overall_corr) > float(sop.reject)
            else "ADJUST"
        )
    )

    diagnostics: list[str] = []
    if int(crm_detected.shape[0]) == 0:
        diagnostics.append("No TA CRM or RM rows were detected.")
    if int(crm_detected.shape[0]) > 0 and int(crm.shape[0]) == 0:
        diagnostics.append("CRM rows were detected, but none had numeric TA.")
    if n_crm_missing_ta > 0:
        diagnostics.append(
            f"{n_crm_missing_ta} detected CRM rows had missing or non numeric TA "
            "and were excluded from correction."
        )
    if crm_valid > 0 and crm_kept == 0:
        diagnostics.append("All valid CRM differences were rejected as outliers.")
    if overall_n < int(min_crm_n):
        diagnostics.append(f"Not enough non outlier CRMs to compute a correction: kept N = {overall_n}.")
    if overall_status == "FAIL":
        diagnostics.append("Mean TA difference exceeds the SOP reject threshold, so correction is withheld.")
    if overall_status == "NO_ADJUST":
        diagnostics.append("Mean TA difference is within the SOP no adjust threshold, so correction is forced to 0.0.")
    if not correct_only_samples:
        diagnostics.append(
            "TA correction was allowed for non CRM rows with TA. CRM rows are "
            "still never corrected because they are the basis for the correction."
        )

    n_samples_flagged = int(sample_mask.sum())
    n_samples_ta_missing = int(out.loc[sample_mask, ta_col].isna().sum()) if n_samples_flagged else 0
    n_samples_corrected = int(out.loc[sample_mask, "ta_corrected_available"].sum()) if n_samples_flagged else 0
    n_correction_applied = int(out["ta_correction_applied"].fillna(False).sum())
    n_correction_withheld = int(out["ta_correction_withheld"].fillna(False).sum())

    summary: Dict[str, Any] = {
        "crm_n_detected": int(crm_detected.shape[0]),
        "crm_n_usable": int(crm.shape[0]),
        "crm_n_missing_ta": int(n_crm_missing_ta),
        "crm_n_valid": int(crm_valid),
        "crm_n_outlier": int(crm_out),
        "crm_n_kept": int(crm_kept),
        "overall_n_kept": int(overall_n),
        "overall_corr": overall_corr,
        "overall_sd": overall_sd,
        "overall_se": overall_se,
        "sop_no_adjust": float(sop.no_adjust),
        "sop_reject": float(sop.reject),
        "overall_status": overall_status,
        "n_samples_flagged": n_samples_flagged,
        "n_samples_ta_missing": n_samples_ta_missing,
        "n_samples_corrected": n_samples_corrected,
        "n_ta_correction_applied": n_correction_applied,
        "n_ta_correction_withheld": n_correction_withheld,
        "correct_only_samples": bool(correct_only_samples),
        "require_ta_value_for_crm": bool(require_ta_value_for_crm),
        "group_by": group_by_res,
        "min_crm_n": int(min_crm_n),
        "mad_k": float(mad_k),
        "max_abs_diff": max_abs_diff,
        "crm_batch_used": batch_used,
        "crm_certified_ta_umolkg": ta_cert,
        "crm_reference_source": CRM_REFERENCE_METADATA["source"],
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
) -> bool:
    """Write a JPEG scatter of analysis number against certified minus measured TA.

    Returns True if a plot was written, False if skipped (no plottable data).
    """
    try:
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        die(f"matplotlib is required for plotting. Details: {e}")

    if crm_qc.empty:
        print("INFO: no CRM/RM TA rows to plot; skipping TA plot.")
        return False

    dfp = crm_qc.copy()
    dfp["ta_diff_umolkg"] = pd.to_numeric(dfp["ta_diff_umolkg"], errors="coerce")
    dfp = dfp[dfp["ta_diff_umolkg"].notna()].copy()

    if dfp.empty:
        print("INFO: no numeric TA differences to plot; skipping TA plot.")
        return False

    dfp["analysis_number"] = range(1, len(dfp) + 1)

    exceeds_mask = _bool_col(dfp, "ta_exceeds_sop_reject")
    outlier_mask = _bool_col(dfp, "ta_diff_umolkg_is_outlier")

    exceeds = dfp[exceeds_mask].copy()
    rest = dfp[~exceeds_mask].copy()
    rest_outlier_mask = _bool_col(rest, "ta_diff_umolkg_is_outlier")
    rest_bad = rest[rest_outlier_mask].copy()
    rest_ok = rest[~rest_outlier_mask].copy()

    fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=170)

    if not rest_ok.empty:
        ax.scatter(rest_ok["analysis_number"], rest_ok["ta_diff_umolkg"], s=56, marker="o",
                   label="RM kept (within SOP)")
    if not rest_bad.empty:
        ax.scatter(rest_bad["analysis_number"], rest_bad["ta_diff_umolkg"], s=72, marker="x",
                   label="RM statistical outlier")
    if not exceeds.empty:
        ax.scatter(exceeds["analysis_number"], exceeds["ta_diff_umolkg"], s=120, marker="x",
                   label=f"RM exceeds SOP (±{float(sop.reject):g})")

    ax.axhline(0.0, linewidth=1.2)
    ax.axhline(+float(sop.no_adjust), linestyle="--", linewidth=1.2,
               label=f"no-adjust ±{float(sop.no_adjust):g} (GOA-ON/Dickson SOP)")
    ax.axhline(-float(sop.no_adjust), linestyle="--", linewidth=1.2)
    ax.axhline(+float(sop.reject), linestyle=":", linewidth=1.6,
               label=f"reject ±{float(sop.reject):g}")
    ax.axhline(-float(sop.reject), linestyle=":", linewidth=1.6)

    ax.set_title(title, fontsize=16, pad=10)
    ax.set_xlabel("Analysis Number", fontsize=12)
    ax.set_ylabel("RM TA Difference (umol/kg)\n(certified - measured)", fontsize=12)
    # light horizontal-only grid: aids reading the difference value without
    # competing with the data or the dotted SOP threshold lines.
    ax.grid(True, axis="y", linestyle="-", linewidth=0.5, color="0.85", alpha=0.8)
    ax.set_axisbelow(True)

    if annotate_points and sample_tag_col in dfp.columns:
        # AUDIT FIX N-4: iterate with zip over the three needed columns instead
        # of DataFrame.iterrows(), which builds a per-row Series. This is a
        # small per-analysis subset so the impact is minor, but zip avoids the
        # Series-construction overhead and the dtype coercion iterrows performs.
        for tag_val, x_val, y_val in zip(
            dfp[sample_tag_col], dfp["analysis_number"], dfp["ta_diff_umolkg"]
        ):
            tag = str(tag_val).strip() if tag_val is not None else ""
            if tag and tag.lower() not in {"nan", "<na>", "none"}:
                ax.annotate(
                    tag,
                    (x_val, y_val),
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
    return True


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
    """Write a markdown summary of TA CRM QC."""
    diag_lines = "\n".join([f"- {d}" for d in ta_summary.get("diagnostics", [])]) or "- (none)"

    md = f"""# TA CRM QC Report

**Generated:** {utc_stamp()}
**Workbook:** `{xlsx_path}`
**Sheet:** `{sheet_name}`

## Status
- SOP status: **{ta_summary.get("overall_status")}**
- mean_diff_kept: {fmt(ta_summary.get("overall_corr"), nd=3)} umol/kg
- sd_diff_kept: {fmt(ta_summary.get("overall_sd"), nd=3)} umol/kg
- se_diff_kept: {fmt(ta_summary.get("overall_se"), nd=3)} umol/kg

## Reference material
- CRM batch used: `{ta_summary.get("crm_batch_used")}`
- certified TA used: {fmt(ta_summary.get("crm_certified_ta_umolkg"), nd=3)} umol/kg
- CRM reference source: {ta_summary.get("crm_reference_source")}

## Inputs and policy
- TA column: `{ta_col_used}`
- sample tag column: `{sample_tag_col_used}`
- crm or sample flag column: `{params.get("CRM_OR_SAMPLE_COL")}`
- CRM tag prefix: `{params.get("CRM_TAG_PREFIX")}`
- group_by: `{group_by if group_by else "None"}`
- grouped correction: `{bool(group_by)}`
- correct only samples: `{ta_summary.get("correct_only_samples")}`
- require TA value for detected CRM rows: `{ta_summary.get("require_ta_value_for_crm")}`
- minimum CRM N: `{ta_summary.get("min_crm_n")}`
- MAD k: `{ta_summary.get("mad_k")}`
- max absolute difference threshold: `{ta_summary.get("max_abs_diff")}`
- SOP no adjust threshold: `{ta_summary.get("sop_no_adjust")}` umol/kg
- SOP reject threshold: `{ta_summary.get("sop_reject")}` umol/kg

## Counts
- CRM detected: {ta_summary.get("crm_n_detected")}
- CRM usable: {ta_summary.get("crm_n_usable")}
- CRM missing or non numeric TA: {ta_summary.get("crm_n_missing_ta")}
- CRM valid: {ta_summary.get("crm_n_valid")}
- CRM kept: {ta_summary.get("crm_n_kept")}
- CRM outliers: {ta_summary.get("crm_n_outlier")}
- sample rows detected: {ta_summary.get("n_samples_flagged")}
- sample rows missing TA: {ta_summary.get("n_samples_ta_missing")}
- sample rows with corrected TA available: {ta_summary.get("n_samples_corrected")}
- rows where TA correction was applied: {ta_summary.get("n_ta_correction_applied")}
- rows where TA correction was withheld: {ta_summary.get("n_ta_correction_withheld")}

## Diagnostics
{diag_lines}
"""
    write_text(out_md, md)


# =============================================================================
# pH standard QC
# =============================================================================


@dataclass
class PhStdStatusThresholds:
    """pH standard status thresholds."""

    ok: float = 0.02
    warn: float = 0.05

    def __post_init__(self) -> None:
        self.ok = float(self.ok)
        self.warn = float(self.warn)

        if self.ok < 0:
            raise ValueError("PhStdStatusThresholds.ok must be >= 0.")

        if self.warn <= self.ok:
            raise ValueError("PhStdStatusThresholds.warn must be greater than ok.")


def ph_standard_expected(
    buffer: str,
    temp_c: float,
    allow_clamp: bool = False,
) -> tuple[float, bool]:
    """Return expected pH and whether temperature was outside the table range.

    If `allow_clamp` is False, out of range temperatures return nan and True.
    If `allow_clamp` is True, out of range temperatures are clamped to the
    nearest endpoint and still return True.
    """
    b = str(buffer).strip().lower()

    if b not in PH_STD_TABLES:
        die(f"Unknown pH buffer '{buffer}'. Choose from: {list(PH_STD_TABLES.keys())}")

    table = PH_STD_TABLES[b]
    xs = sorted(table.keys())
    temp = float(temp_c)
    out_of_range = temp < xs[0] or temp > xs[-1]

    if out_of_range and not allow_clamp:
        return float("nan"), True

    if temp <= xs[0]:
        return float(table[xs[0]]), True

    if temp >= xs[-1]:
        return float(table[xs[-1]]), True

    for lo, hi in zip(xs[:-1], xs[1:]):
        if lo <= temp <= hi:
            ylo = float(table[lo])
            yhi = float(table[hi])
            w = (temp - lo) / (hi - lo)
            return ylo + w * (yhi - ylo), False

    return float("nan"), True


def detect_phstd_rows(df: pd.DataFrame, sample_tag_col: str, tag_prefix: str) -> pd.Series:
    """Return rows whose sample tag begins with the pH standard prefix."""
    tag = safe_str_series(df[sample_tag_col]).str.lower()
    return tag.str.startswith(tag_prefix.strip().lower()).astype("boolean")


def ph_status_from_mean(mean_diff: Optional[float], thr: PhStdStatusThresholds) -> str:
    """Map a mean expected minus measured pH residual to status."""
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
    apply_warn_correction: bool = True,
    allow_temp_clamp: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Detect pH standard rows, compute pH offset, and optionally correct samples.

    Returns:
        (out, phstd_qc, corr_table, summary)
    """
    out = df.copy()

    ph_col = resolve_col(out, ph_col)
    temp_col = resolve_col(out, temp_col)
    sample_tag_col = resolve_col(out, sample_tag_col)

    crm_or_sample_col_res: Optional[str] = None
    if crm_or_sample_col and crm_or_sample_col in out.columns:
        crm_or_sample_col_res = resolve_col(out, crm_or_sample_col)

    group_by_res: Optional[str] = None
    if group_by and group_by in out.columns:
        group_by_res = resolve_col(out, group_by)

    out[ph_col] = pd.to_numeric(out[ph_col], errors="coerce")
    out[temp_col] = pd.to_numeric(out[temp_col], errors="coerce")

    is_std = detect_phstd_rows(out, sample_tag_col=sample_tag_col, tag_prefix=tag_prefix)

    if crm_or_sample_col_res is not None:
        flag = safe_str_series(out[crm_or_sample_col_res]).str.lower()
        is_sample = flag.eq(sample_flag_value.lower())
    else:
        is_sample = ~is_std.fillna(False)

    out["is_phstd_row"] = is_std.astype("boolean")
    out["is_ph_sample_row"] = is_sample.astype("boolean")

    std_detected = out.loc[out["is_phstd_row"].fillna(False)].copy()
    n_detected = int(std_detected.shape[0])

    std = std_detected[
        std_detected[temp_col].notna() & std_detected[ph_col].notna()
    ].copy()
    n_numeric_temp_and_ph = int(std.shape[0])

    if not std.empty:
        expected_pairs = std[temp_col].map(
            lambda t: ph_standard_expected(
                buffer=buffer,
                temp_c=float(t),
                allow_clamp=allow_temp_clamp,
            )
        )
        std["phstd_expected"] = expected_pairs.map(lambda pair: pair[0])
        std["flag_phstd_temp_outside_table"] = expected_pairs.map(
            lambda pair: pair[1]
        ).astype("boolean")
        std["phstd_diff"] = pd.to_numeric(std["phstd_expected"], errors="coerce") - std[ph_col]
        std["phstd_diff_is_outlier"] = robust_outlier_flags(
            std["phstd_diff"],
            mad_k=mad_k,
            max_abs=max_abs_diff,
            min_n=max(5, int(min_std_n)),
        ).astype("boolean")
    else:
        std["phstd_expected"] = pd.Series(dtype="float64")
        std["flag_phstd_temp_outside_table"] = pd.Series(dtype="boolean")
        std["phstd_diff"] = pd.Series(dtype="float64")
        std["phstd_diff_is_outlier"] = pd.Series(dtype="boolean")

    n_valid = int(std["phstd_diff"].notna().sum()) if "phstd_diff" in std.columns else 0
    n_temp_outside = int(std["flag_phstd_temp_outside_table"].fillna(False).sum()) if "flag_phstd_temp_outside_table" in std.columns else 0
    n_outlier = (
        int((std["phstd_diff"].notna() & std["phstd_diff_is_outlier"].fillna(False)).sum())
        if "phstd_diff" in std.columns and "phstd_diff_is_outlier" in std.columns
        else 0
    )
    std_for_correction = std.loc[
        std["phstd_diff"].notna()
        & ~std["phstd_diff_is_outlier"].fillna(False)
    ].copy()
    n_kept = int(std_for_correction.shape[0])

    corr_table = build_corrections_table(
        std_for_correction,
        group_by=group_by_res,
        diff_col="phstd_diff",
        min_n=min_std_n,
    )

    if group_by_res and group_by_res in corr_table.columns:
        corr_table = corr_table.rename(
            columns={
                "n": "phstd_corr_n",
                "correction": "phstd_corr_value",
                "std": "phstd_corr_sd",
                "sd": "phstd_corr_sd",
                "group_has_min_n": "phstd_corr_group_has_min_n",
            }
        )
        corr_table = _add_standard_error(
            corr_table,
            sd_col="phstd_corr_sd",
            n_col="phstd_corr_n",
            se_col="phstd_corr_se",
        )

    overall_n_kept = int(_first_value(corr_table, "overall_n", 0) or 0)
    overall_corr = _safe_float(_first_value(corr_table, "overall_correction", float("nan")))
    overall_sd = _safe_float(_first_value(corr_table, "overall_sd", float("nan")))
    overall_se = overall_sd / (overall_n_kept ** 0.5) if overall_n_kept > 0 and pd.notna(overall_sd) else float("nan")

    out["phstd_buffer"] = buffer.lower()
    out["phstd_expected"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    out["phstd_diff"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    out["phstd_diff_is_outlier"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
    out["flag_phstd_temp_outside_table"] = pd.Series(pd.NA, index=out.index, dtype="boolean")

    if not std.empty:
        out.loc[std.index, "phstd_expected"] = pd.to_numeric(std["phstd_expected"], errors="coerce")
        out.loc[std.index, "phstd_diff"] = pd.to_numeric(std["phstd_diff"], errors="coerce")
        out.loc[std.index, "phstd_diff_is_outlier"] = std["phstd_diff_is_outlier"].astype("boolean")
        out.loc[std.index, "flag_phstd_temp_outside_table"] = std["flag_phstd_temp_outside_table"].astype("boolean")

    out["phstd_correction_raw"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    out["phstd_correction_level"] = pd.Series(pd.NA, index=out.index, dtype="string")

    if group_by_res and group_by_res in out.columns and group_by_res in corr_table.columns:
        merge_cols = [
            group_by_res,
            "phstd_corr_n",
            "phstd_corr_value",
            "phstd_corr_sd",
            "phstd_corr_group_has_min_n",
        ]
        if "phstd_corr_se" in corr_table.columns:
            merge_cols.append("phstd_corr_se")

        out = out.merge(corr_table[merge_cols], on=group_by_res, how="left")
        group_raw = pd.to_numeric(out["phstd_corr_value"], errors="coerce")
        has_group_corr = group_raw.notna()
        raw = group_raw.fillna(overall_corr)
        out["phstd_correction_raw"] = raw.astype("Float64")
        out["phstd_correction_level"] = pd.Series("overall", index=out.index, dtype="string")
        out.loc[has_group_corr, "phstd_correction_level"] = "group"
    else:
        out["phstd_corr_n"] = overall_n_kept
        out["phstd_corr_value"] = overall_corr
        out["phstd_corr_sd"] = overall_sd
        out["phstd_corr_se"] = overall_se
        out["phstd_corr_group_has_min_n"] = overall_n_kept >= int(min_std_n)
        out["phstd_correction_raw"] = pd.Series(overall_corr, index=out.index, dtype="Float64")
        out["phstd_correction_level"] = pd.Series("overall", index=out.index, dtype="string")

    if overall_n_kept < int(min_std_n) or pd.isna(overall_corr):
        out["phstd_correction_raw"] = pd.NA
        out["phstd_correction_level"] = pd.NA

    out.loc[out["phstd_correction_raw"].isna(), "phstd_correction_level"] = pd.NA

    out["phstd_status"] = (
        out["phstd_correction_raw"]
        .map(lambda v: ph_status_from_mean(v, status_thr))
        .astype("string")
    )

    out["phstd_correction_used"] = pd.to_numeric(
        out["phstd_correction_raw"],
        errors="coerce",
    ).astype("Float64")

    withhold = out["phstd_status"].isin(["FAIL", "INSUFFICIENT_DATA"])
    if not apply_warn_correction:
        withhold = withhold | out["phstd_status"].eq("WARN")

    out.loc[withhold, "phstd_correction_used"] = pd.NA

    sample_mask = out["is_ph_sample_row"].fillna(False).astype(bool)
    corr_used = pd.to_numeric(out["phstd_correction_used"], errors="coerce")
    has_ph = out[ph_col].notna()
    sample_with_ph = sample_mask & has_ph

    out["phstd_correction_applied"] = (
        bool(correct_samples)
        & sample_with_ph
        & corr_used.notna()
    ).astype("boolean")

    out["phstd_correction_withheld"] = (
        sample_with_ph
        & out["phstd_status"].isin(["FAIL", "INSUFFICIENT_DATA", "WARN"])
        & corr_used.isna()
    ).astype("boolean")

    out["ph_corrected_from_phstd"] = pd.Series(
        pd.NA,
        index=out.index,
        dtype="Float64",
    )

    if correct_samples:
        valid = sample_with_ph & corr_used.notna()

        out.loc[valid, "ph_corrected_from_phstd"] = (
            out.loc[valid, ph_col] + corr_used.loc[valid]
        )

        fallback = sample_with_ph & ~valid
        out.loc[fallback, "ph_corrected_from_phstd"] = out.loc[fallback, ph_col]
    else:
        out.loc[sample_with_ph, "ph_corrected_from_phstd"] = out.loc[
            sample_with_ph,
            ph_col,
        ]

    out["ph_corrected_available"] = (
        out["ph_corrected_from_phstd"].notna().astype("boolean")
    )

    overall_status = ph_status_from_mean(
        overall_corr if overall_n_kept >= int(min_std_n) else float("nan"),
        status_thr,
    )

    diagnostics: list[str] = []
    if not correct_samples:
        diagnostics.append("Samples are not corrected because phstd_correct_samples is False.")
    if not apply_warn_correction:
        diagnostics.append("WARN status pH standard corrections are withheld by configuration.")
    if n_detected == 0:
        diagnostics.append("No pH standard rows were detected.")
    if n_numeric_temp_and_ph == 0 and n_detected > 0:
        diagnostics.append("Standard rows were detected, but none had both numeric temperature and numeric pH.")
    if n_temp_outside > 0 and not allow_temp_clamp:
        diagnostics.append("Some pH standard temperatures were outside the buffer table range and were not clamped.")
    if n_temp_outside > 0 and allow_temp_clamp:
        diagnostics.append("Some pH standard temperatures were outside the buffer table range and were clamped to endpoints.")
    if n_valid > 0 and n_kept == 0:
        diagnostics.append("All valid pH standards were rejected as outliers.")
    if overall_n_kept < int(min_std_n):
        diagnostics.append(f"Not enough non outlier standards to compute a correction: kept N = {overall_n_kept}.")
    if overall_status == "FAIL":
        diagnostics.append("Mean pH offset exceeds the FAIL threshold, so correction is withheld.")

    n_samples_flagged = int(sample_mask.sum())
    n_samples_ph_missing = int(out.loc[sample_mask, ph_col].isna().sum()) if n_samples_flagged else 0
    n_samples_ph_corrected_available = int(out.loc[sample_mask, "ph_corrected_available"].sum()) if n_samples_flagged else 0
    n_correction_applied = int(out["phstd_correction_applied"].fillna(False).sum())
    n_correction_withheld = int(out["phstd_correction_withheld"].fillna(False).sum())

    temp_min = _safe_float(std[temp_col].min()) if temp_col in std.columns and not std.empty else float("nan")
    temp_max = _safe_float(std[temp_col].max()) if temp_col in std.columns and not std.empty else float("nan")

    # FIX 4-B: Include the actual out-of-range temperature values in the
    # summary so operators can assess severity (lab at 30°C vs polar sample at
    # -3°C have very different scientific implications). Previously only the
    # count was reported, hiding the magnitude of the range violation.
    _table_temp_min = min(PH_STD_TABLES.get(buffer.lower(), {}).keys(), default=-2)
    _table_temp_max = max(PH_STD_TABLES.get(buffer.lower(), {}).keys(), default=29)
    if temp_col in std.columns and not std.empty:
        _temp_vals = pd.to_numeric(std[temp_col], errors="coerce")
        _outside_mask = _temp_vals.notna() & (
            (_temp_vals < _table_temp_min) | (_temp_vals > _table_temp_max)
        )
        temperature_outside_table_values = sorted(
            _temp_vals[_outside_mask].dropna().tolist()
        )
    else:
        temperature_outside_table_values = []

    summary: Dict[str, Any] = {
        "buffer": buffer.lower(),
        "tag_prefix": tag_prefix,
        "ph_col_used": ph_col,
        "temp_col_used": temp_col,
        "group_by": group_by_res,
        "n_detected": n_detected,
        "n_numeric_temp_and_ph": n_numeric_temp_and_ph,
        "n_valid": n_valid,
        "n_temp_outside_table": n_temp_outside,
        # FIX 4-B: actual out-of-range temperature values for operator review
        "temperature_outside_table_values": temperature_outside_table_values,
        "n_outlier": n_outlier,
        "n_kept": n_kept,
        "overall_n_kept": overall_n_kept,
        "mean_diff_kept": overall_corr if overall_n_kept >= int(min_std_n) else float("nan"),
        "sd_diff_kept": overall_sd,
        "se_diff_kept": overall_se,
        "overall_status": overall_status,
        "status_ok": float(status_thr.ok),
        "status_warn": float(status_thr.warn),
        "n_samples_flagged": n_samples_flagged,
        "n_samples_ph_missing": n_samples_ph_missing,
        "n_samples_ph_corrected_available": n_samples_ph_corrected_available,
        "n_phstd_correction_applied": n_correction_applied,
        "n_phstd_correction_withheld": n_correction_withheld,
        "apply_warn_correction": bool(apply_warn_correction),
        "allow_temp_clamp": bool(allow_temp_clamp),
        "correct_samples": bool(correct_samples),
        "min_std_n": int(min_std_n),
        "mad_k": float(mad_k),
        "max_abs_diff": max_abs_diff,
        "temperature_min_c": temp_min,
        "temperature_max_c": temp_max,
        "ph_buffer_table_source": PH_STD_REFERENCE_METADATA["source"],
        "ph_buffer_table_temperature_range_c": PH_STD_REFERENCE_METADATA["temperature_range_c"],
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
) -> bool:
    """Write a JPEG scatter of analysis number against expected minus measured pH.

    Returns True if a plot was written, False if skipped (no plottable data).
    """
    try:
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        die(f"matplotlib is required for plotting. Details: {e}")

    if phstd_qc.empty:
        # No standard rows to plot is a normal QC outcome (e.g. standards
        # were logged but carry no measured pH/temperature). Skip the plot
        # and signal that nothing was written rather than aborting the run.
        print("INFO: no pH standard rows to plot; skipping pH-standard plot.")
        return False

    dfp = phstd_qc.copy()
    dfp[diff_col] = pd.to_numeric(dfp[diff_col], errors="coerce")
    dfp = dfp[dfp[diff_col].notna()].copy()

    if dfp.empty:
        print(
            "INFO: no numeric pH differences to plot "
            "(standards present but missing pH/temp); skipping plot."
        )
        return False

    dfp["analysis_number"] = range(1, len(dfp) + 1)
    outlier_mask = _bool_col(dfp, outlier_col)

    # AUDIT FIX: mark points by whether they EXCEED the drawn acceptance
    # threshold (|diff| > thr_ok), not only by the MAD statistical flag. The
    # previous version flagged the statistically most-distant point as the
    # "outlier" while ignoring the +/- thr_ok lines it draws — so a point that
    # actually breached the tolerance could be shown as "kept" and a point
    # comfortably within tolerance shown as the "outlier". This mirrors the TA
    # plot, which already separates a threshold-exceeds category.
    diff_abs = dfp[diff_col].abs()
    exceeds_mask = diff_abs > float(thr_ok)

    exceeds = dfp[exceeds_mask].copy()
    rest = dfp[~exceeds_mask].copy()
    rest_outlier_mask = _bool_col(rest, outlier_col)
    rest_bad = rest[rest_outlier_mask].copy()
    rest_ok = rest[~rest_outlier_mask].copy()

    fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=170)

    if not rest_ok.empty:
        ax.scatter(rest_ok["analysis_number"], rest_ok[diff_col], s=58, marker="o",
                   label="Std kept (within tolerance)")
    if not rest_bad.empty:
        ax.scatter(rest_bad["analysis_number"], rest_bad[diff_col], s=92, marker="x",
                   label="Std statistical outlier")
    if not exceeds.empty:
        ax.scatter(exceeds["analysis_number"], exceeds[diff_col], s=120, marker="x",
                   label=f"Std exceeds tolerance (±{thr_ok:g})")

    ax.axhline(0.0, linewidth=1.2)
    ax.axhline(+thr_ok, linestyle="--", linewidth=1.2,
               label=f"acceptance ±{thr_ok:g} (GOA-ON/Dickson SOP)")
    ax.axhline(-thr_ok, linestyle="--", linewidth=1.2)
    ax.axhline(+thr_warn, linestyle=":", linewidth=1.6,
               label=f"warning ±{thr_warn:g}")
    ax.axhline(-thr_warn, linestyle=":", linewidth=1.6)

    ax.set_title(title, fontsize=18, pad=10)
    ax.set_xlabel("Analysis Number", fontsize=12)
    ax.set_ylabel("pH Difference\n(expected - measured)", fontsize=12)
    ax.grid(True, axis="y", linestyle="-", linewidth=0.5, color="0.85", alpha=0.8)
    ax.set_axisbelow(True)

    if annotate_points and sample_tag_col in dfp.columns:
        # AUDIT FIX N-4: see the TA plot above — iterate with zip over the
        # needed columns instead of DataFrame.iterrows().
        for tag_val, x_val, y_val in zip(
            dfp[sample_tag_col], dfp["analysis_number"], dfp[diff_col]
        ):
            tag = str(tag_val).strip() if tag_val is not None else ""
            if tag and tag.lower() not in {"nan", "<na>", "none"}:
                ax.annotate(
                    tag,
                    (x_val, y_val),
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
        0.99,
        0.02,
        box,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
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
    return True


def write_phstd_markdown_report(
    out_md: Path,
    xlsx_path: Path,
    sheet_name: str,
    params: Dict[str, Any],
    ph_summary: Dict[str, Any],
) -> None:
    """Write a markdown summary of pH standard QC."""
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
- sd_diff_kept: {fmt(ph_summary.get("sd_diff_kept"), nd=4)}
- se_diff_kept: {fmt(ph_summary.get("se_diff_kept"), nd=4)}

## Reference table
- pH buffer table source: {ph_summary.get("ph_buffer_table_source")}
- table temperature range: {ph_summary.get("ph_buffer_table_temperature_range_c")} deg C
- expected pH method: table lookup with linear temperature interpolation, not a full buffer composition model
- temperature clamping allowed: `{ph_summary.get("allow_temp_clamp")}`
- standard temperature range observed: {fmt(ph_summary.get("temperature_min_c"), nd=2)} to {fmt(ph_summary.get("temperature_max_c"), nd=2)} deg C

## Inputs and policy
- pH column: `{ph_summary.get("ph_col_used")}`
- temperature column: `{ph_summary.get("temp_col_used")}`
- crm or sample flag column: `{params.get("CRM_OR_SAMPLE_COL")}`
- group_by: `{ph_summary.get("group_by") if ph_summary.get("group_by") else "None"}`
- minimum standard N: `{ph_summary.get("min_std_n")}`
- MAD k: `{ph_summary.get("mad_k")}`
- max absolute difference threshold: `{ph_summary.get("max_abs_diff")}`
- OK threshold: `{ph_summary.get("status_ok")}`
- WARN threshold: `{ph_summary.get("status_warn")}`
- correct samples: `{ph_summary.get("correct_samples")}`
- apply WARN correction: `{ph_summary.get("apply_warn_correction")}`

## Counts
- detected: {ph_summary.get("n_detected")}
- numeric temperature and pH: {ph_summary.get("n_numeric_temp_and_ph")}
- valid: {ph_summary.get("n_valid")}
- temperature outside table: {ph_summary.get("n_temp_outside_table")}
- kept: {ph_summary.get("n_kept")}
- outliers: {ph_summary.get("n_outlier")}
- sample rows detected: {ph_summary.get("n_samples_flagged")}
- sample rows missing pH: {ph_summary.get("n_samples_ph_missing")}
- sample rows with corrected or original pH available: {ph_summary.get("n_samples_ph_corrected_available")}
- rows where pH correction was applied: {ph_summary.get("n_phstd_correction_applied")}
- rows where pH correction was withheld: {ph_summary.get("n_phstd_correction_withheld")}

## Diagnostics
{diag_lines}
"""
    write_text(out_md, md)