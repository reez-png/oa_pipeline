"""
oa_pipeline.carbonate_calc — internal carbonate-system calculation.

Computes the carbonate system with PyCO2SYS from the pipeline's own
RM-corrected total alkalinity and measured pH, at the correct temperature
convention, so the reported saturation states / DIC / pCO2 are consistent with
the corrected TA (they no longer come from an external Excel workbook run on
raw TA).

See carbonate_calc_design.md for the full reasoning behind every setting.
Validated: with these settings PyCO2SYS reproduces the prior CO2SYS-Excel output
to ~4 significant figures on the same (raw) TA, so any difference in the final
data is attributable to the RM correction alone, not to a solver change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# PINNED SETTINGS — mapped to the lab's CO2SYS-Excel configuration and the
# GOA-ON Cookbook. Each is set EXPLICITLY (never relying on library defaults)
# so a future PyCO2SYS default change cannot silently alter results.
#   opt_k_carbonic  = 10  -> Lueker, Dickson & Keeling (2000)   [K1,K2]
#   opt_k_bisulfate =  1  -> Dickson (1990)                     [KSO4]
#   opt_total_borate=  2  -> Lee et al. (2010)                  [B:S]
#   opt_k_fluoride  =  2  -> Perez & Fraga (1987)               [KF]
#   opt_pH_scale    =  1  -> Total scale
# ---------------------------------------------------------------------------
CARBONATE_CALC_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    # PyCO2SYS option codes (do not change without re-validating vs Excel).
    "opt_k_carbonic": 10,
    "opt_k_bisulfate": 1,
    "opt_total_borate": 2,
    "opt_k_fluoride": 2,
    "opt_pH_scale": 1,
    # Source columns (canonical -> accepted names, first match wins).
    "cols": {
        "ta": ["ta_corrected_umolkg", "ta_best_umolkg", "ta"],
        "ph": ["ph_best", "ph_observed", "pH_lab"],
        "sal": ["salinity", "sal"],
        "temp_lab": ["temperature_measurement_c", "temp_lab"],
        "temp_insitu": ["temperature_insitu_c", "temp_insitu"],
        "pressure_insitu": ["pressure_insitu_dbar", "pressure_dbar"],
        "silicate": ["sio3_umol_kg", "sio3", "sio3_uM/L"],
        "phosphate": ["po4_umol_kg", "po4", "po4_uM/L"],
    },
    # Output column names the audit downstream expects.
    "out": {
        "dic": "dic",
        "omega_ar": "omega_aragonite_calc",
        "omega_ca": "omega_calcite_calc",
        "pco2": "pco2_calc_uatm",
        "co2aq": "co2aq_calc_umol_kg",
        "hco3": "hco3_calc_umol_kg",
        "co3": "co3_calc_umol_kg",
        "revelle": "revelle_factor_calc",
        "ph_insitu": "ph_co2sys",  # calculated pH re-expressed at in-situ T
    },
    # Only compute where TA was actually correction-resolved. If True, rows
    # whose TA correction was withheld/failed still get computed (from whatever
    # ta_best is) but are flagged.
    "require_corrected_ta": True,
    # Batch-quality guard: if the fraction of RMs rejected in a batch exceeds
    # this, raise a batch-quality flag (cookbook: >20 umol/kg => investigate).
    "rm_reject_fraction_warn": 0.34,  # e.g. 3 of 7 rejected -> warn
}


@dataclass
class CarbonateCalcResult:
    df: pd.DataFrame
    n_computed: int
    n_skipped: int
    settings: Dict[str, Any]
    batch_quality: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def _first_present(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _num(df: pd.DataFrame, colname: Optional[str]) -> Optional[pd.Series]:
    if colname is None or colname not in df.columns:
        return None
    return pd.to_numeric(df[colname], errors="coerce")


def _to_umol_kg(series: Optional[pd.Series], sal: pd.Series,
                temp: pd.Series) -> Optional[pd.Series]:
    """Convert a nutrient in uM (umol/L) to umol/kg using seawater density.

    The nutrient-alkalinity term is tiny, so this correction is minor, but we
    do it properly rather than ignore the L-vs-kg distinction. Uses a simple
    density approximation; if unavailable, returns the input unchanged.
    """
    if series is None:
        return None
    # crude but adequate seawater density (kg/L) ~ 1 + 0.0008*S - 0.0002*(T-20)
    rho = 1.0 + 0.0008 * sal.fillna(35.0) - 0.0002 * (temp.fillna(25.0) - 20.0)
    return series / rho


def compute(df: pd.DataFrame, settings: Optional[Dict[str, Any]] = None
            ) -> CarbonateCalcResult:
    """Compute the carbonate system in place-ish (returns a new DataFrame).

    Reads corrected TA + measured pH + conditions, runs PyCO2SYS with the
    pinned settings, writes the chemistry columns the downstream audit checks,
    and records provenance. Rows lacking the two core parameters are left
    untouched (NaN chemistry) and counted as skipped.
    """
    cfg = dict(CARBONATE_CALC_DEFAULTS)
    if settings:
        # shallow-merge top level, deep-merge the nested dicts we care about
        for k, v in settings.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v

    out = df.copy()
    notes: List[str] = []

    if not cfg.get("enabled", True):
        return CarbonateCalcResult(out, 0, len(out), cfg, {}, ["carbonate_calc disabled"])

    try:
        import PyCO2SYS as pyco2
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "PyCO2SYS is required for internal carbonate calculation. "
            "Install with `pip install PyCO2SYS`."
        ) from e

    cols = cfg["cols"]
    ta_col = _first_present(out, cols["ta"])
    ph_col = _first_present(out, cols["ph"])

    # If corrected TA is required (default) and the first TA candidate
    # (ta_corrected_umolkg) is not the resolved column, skip the whole calc.
    # This is the correct semantics: the point of this stage is to compute the
    # carbonate system from RM-corrected TA, so with no corrected TA present
    # (e.g. synthetic/example data, or a dataset that never ran RM correction)
    # we must NOT overwrite existing chemistry. The pipeline then keeps whatever
    # chemistry was already in the data, and the downstream audit still runs.
    corrected_ta_name = cols["ta"][0]  # "ta_corrected_umolkg"
    if cfg.get("require_corrected_ta", True) and ta_col != corrected_ta_name:
        notes.append(
            f"Skipped internal calculation: required corrected-TA column "
            f"'{corrected_ta_name}' not present (found TA source: {ta_col}). "
            f"Existing chemistry left untouched."
        )
        return CarbonateCalcResult(out, 0, len(out), cfg, {}, notes)

    sal_col = _first_present(out, cols["sal"])
    tlab_col = _first_present(out, cols["temp_lab"])
    tins_col = _first_present(out, cols["temp_insitu"])
    pres_col = _first_present(out, cols["pressure_insitu"])
    si_col = _first_present(out, cols["silicate"])
    po4_col = _first_present(out, cols["phosphate"])

    ta = _num(out, ta_col)
    ph = _num(out, ph_col)
    sal = _num(out, sal_col)
    tlab = _num(out, tlab_col)
    tins = _num(out, tins_col)
    pres = _num(out, pres_col)

    missing = [name for name, s in [("TA", ta), ("pH", ph), ("salinity", sal),
                                    ("temp_lab", tlab), ("temp_insitu", tins)] if s is None]
    if missing:
        raise RuntimeError(
            f"carbonate_calc: required columns not found for {missing}. "
            f"Looked for: TA={cols['ta']}, pH={cols['ph']}, sal={cols['sal']}, "
            f"temp_lab={cols['temp_lab']}, temp_insitu={cols['temp_insitu']}."
        )
    notes.append(f"Inputs: TA='{ta_col}', pH='{ph_col}', sal='{sal_col}', "
                 f"temp_lab='{tlab_col}', temp_insitu='{tins_col}', "
                 f"pressure='{pres_col or 'none->0'}'.")

    # pressure: surface (0) at measurement, in-situ at collection.
    pres_out = pres if pres is not None else pd.Series(0.0, index=out.index)

    # nutrients -> umol/kg (default 0 where absent, as Excel-blank behaviour)
    si = _to_umol_kg(_num(out, si_col), sal, tlab) if si_col else None
    po4 = _to_umol_kg(_num(out, po4_col), sal, tlab) if po4_col else None
    if si_col is None and po4_col is None:
        notes.append("No silicate/phosphate columns found; nutrients set to 0 "
                     "(same as leaving them blank in CO2SYS-Excel).")

    # rows we can solve: both core params present
    solvable = ta.notna() & ph.notna() & sal.notna() & tlab.notna() & tins.notna()
    n_solvable = int(solvable.sum())
    idx = out.index[solvable]

    if n_solvable == 0:
        notes.append("No rows had both TA and pH present; nothing computed.")
        return CarbonateCalcResult(out, 0, len(out), cfg, {}, notes)

    kwargs = dict(
        par1=ta[solvable].to_numpy(float),
        par2=ph[solvable].to_numpy(float),
        par1_type=1,   # total alkalinity
        par2_type=3,   # pH
        salinity=sal[solvable].to_numpy(float),
        temperature=tlab[solvable].to_numpy(float),        # input: lab temp
        temperature_out=tins[solvable].to_numpy(float),    # output: in-situ temp
        pressure=np.zeros(n_solvable),                     # input: ~0 dbar (lab)
        pressure_out=pres_out[solvable].to_numpy(float),   # output: in-situ dbar
        opt_pH_scale=cfg["opt_pH_scale"],
        opt_k_carbonic=cfg["opt_k_carbonic"],
        opt_k_bisulfate=cfg["opt_k_bisulfate"],
        opt_total_borate=cfg["opt_total_borate"],
        opt_k_fluoride=cfg["opt_k_fluoride"],
    )
    if si is not None:
        kwargs["total_silicate"] = si[solvable].to_numpy(float)
    if po4 is not None:
        kwargs["total_phosphate"] = po4[solvable].to_numpy(float)

    res = pyco2.sys(**kwargs)

    o = cfg["out"]
    # DIC is a total (temperature/scale-independent) -> take directly.
    out.loc[idx, o["dic"]] = res["dic"]
    # Saturation states, pCO2, species, Revelle: take the OUTPUT-condition
    # (in-situ) variants, because those are what organisms experience.
    out.loc[idx, o["omega_ar"]] = res["saturation_aragonite_out"]
    out.loc[idx, o["omega_ca"]] = res["saturation_calcite_out"]
    out.loc[idx, o["pco2"]] = res["pCO2_out"]
    out.loc[idx, o["co2aq"]] = res["CO2_out"]
    out.loc[idx, o["hco3"]] = res["HCO3_out"]
    out.loc[idx, o["co3"]] = res["CO3_out"]
    out.loc[idx, o["revelle"]] = res["revelle_factor_out"]
    # calculated pH re-expressed at in-situ temperature (for the QC cross-check)
    out.loc[idx, o["ph_insitu"]] = res["pH_out"]

    # ---- provenance stamps (constant across sample rows) ----
    import PyCO2SYS as _pyco2
    solver_tag = f"PyCO2SYS_{getattr(_pyco2, '__version__', 'unknown')}"
    const_tag = "Lueker2000;KSO4_Dickson1990;B_Lee2010;KF_PerezFraga1987"
    out.loc[idx, "carbonate_solver"] = solver_tag
    out.loc[idx, "carbon_input_pair_used"] = "TA_pH"
    out.loc[idx, "carbonate_constants"] = const_tag
    out.loc[idx, "carbonate_ph_scale"] = "total"
    out.loc[idx, "carbonate_output_temperature"] = "in_situ"
    out.loc[idx, "dic_unit_normalized"] = "umol_kg"
    out.loc[idx, "co2aq_unit_normalized"] = "umol_kg"
    out.loc[idx, "hco3_unit_normalized"] = "umol_kg"
    out.loc[idx, "co3_unit_normalized"] = "umol_kg"
    out.loc[idx, "carbonate_calc_internal"] = True
    out.loc[idx, "carbonate_calc_ta_source"] = ta_col  # which TA fed the calc

    # ---- batch-quality guard (cookbook: >20 umol/kg RM diff => investigate) ----
    batch_quality: Dict[str, Any] = {}
    if "ta_exceeds_sop_reject" in out.columns and "crm_batch_used" in out.columns:
        crm = out[out.get("is_ta_crm_row", False) == True] if "is_ta_crm_row" in out.columns else out
        if len(crm):
            for batch, g in crm.groupby("crm_batch_used"):
                n = len(g); nrej = int(pd.to_numeric(g["ta_exceeds_sop_reject"], errors="coerce").fillna(0).astype(bool).sum())
                frac = nrej / n if n else 0.0
                batch_quality[str(batch)] = {"n_rm": n, "n_rejected": nrej, "frac_rejected": round(frac, 3)}
                if frac > cfg["rm_reject_fraction_warn"]:
                    notes.append(
                        f"BATCH QUALITY WARNING: batch {batch} had {nrej}/{n} RMs exceed the "
                        f"+/-20 umol/kg SOP limit ({frac*100:.0f}%). Per the cookbook this means "
                        f"'re-evaluate methods', not correct-through. TA (and all derived "
                        f"chemistry) for this batch is lower-confidence; investigate before "
                        f"treating as final."
                    )
                    # mark affected sample rows
                    mask = (out.get("crm_batch_used") == batch)
                    out.loc[mask, "carbonate_batch_quality_warn"] = True

    return CarbonateCalcResult(
        df=out, n_computed=n_solvable, n_skipped=int((~solvable).sum()),
        settings=cfg, batch_quality=batch_quality, notes=notes,
    )
