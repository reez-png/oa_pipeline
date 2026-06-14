#!/usr/bin/env python3
"""
stamp_carbonate_provenance.py
=============================
Add carbonate-system provenance columns to oa_data_apr.xlsx so the Stage 4
audit can document (and pass) the externally computed chemistry.

Why this is needed
------------------
The carbonate parameters in this workbook (ph_calculated, pco2_calc_uatm,
omega_ar/omega_ca, dic, ...) were computed externally with the CO2Sys v25b06
Excel workbook from the TA + pH input pair. The OA pipeline does NOT run its
own solver; it ingests precomputed chemistry and AUDITS its provenance. With
no solver/input-pair recorded, Stage 4 flags every sample row
unknown_solver + unknown_input_pair, both of which are FAIL-severity, so all
rows fail. Recording the provenance that actually produced the numbers clears
those flags truthfully and documents the method for the manuscript.

What it stamps (sample rows only; std/crm rows left blank)
----------------------------------------------------------
  carbonate_solver        = "CO2Sys_v25b06"
  carbon_input_pair_used  = "TA_pH"
  dic_unit_normalized     = "umol_kg"
  carbonate_constants     = "Lueker2000;KSO4_Dickson;KF_PerezFraga1987;B_Lee2010"
  carbonate_ph_scale      = "total"

The audit only checks that solver/input-pair are non-empty (it does not
validate against a fixed vocabulary), so these human-readable strings satisfy
it while remaining accurate. dic_unit_normalized additionally clears the
DIC-unit-missing REVIEW flag and lets the strict DIC species audit run.

Usage
-----
    .venv\\Scripts\\python.exe stamp_carbonate_provenance.py \\
        "C:/Users/OA_2023-03/Projects/oa_pipeline/data/raw/oa_data_apr.xlsx"

Writes a NEW file alongside the original (……_provenance.xlsx) by default so
the source workbook is never mutated in place; pass --in-place to overwrite.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


# --- provenance values, transcribed from the CO2Sys settings panel ----------
PROVENANCE = {
    "carbonate_solver": "CO2Sys_v25b06",
    "carbon_input_pair_used": "TA_pH",
    "dic_unit_normalized": "umol_kg",
    # Unit metadata for the DIC species columns, so Stage 4's strict DIC
    # species-closure audit can run its unit check and the
    # strict_dic_values_missing / dic_unit_missing flags clear. The species
    # values (co2aq/hco3/co3_calc_umol_kg) are already in umol/kg per the
    # CO2Sys output; these columns just record that unit explicitly.
    "co2aq_unit_normalized": "umol_kg",
    "hco3_unit_normalized": "umol_kg",
    "co3_unit_normalized": "umol_kg",
    "carbonate_constants": "Lueker2000;KSO4_Dickson;KF_PerezFraga1987;B_Lee2010",
    "carbonate_ph_scale": "total",
    # CO2Sys output temperature for the calculated parameters (omega, etc.)
    # was set to in-situ temperature, so saturation states reflect the
    # conditions organisms experience. Recorded for provenance.
    "carbonate_output_temperature": "in_situ",
}

# Rows are "samples" (vs std/crm reference rows) when this column holds this
# value. Reference rows are intentionally left blank: they carry no computed
# carbonate chemistry and are not analysis samples.
SAMPLE_TYPE_COL = "sample_type"
SAMPLE_TYPE_VALUE = "sample"


def stamp(xlsx_in: Path, xlsx_out: Path, sheet_index: int = 0) -> None:
    """Append provenance columns without disturbing existing data.

    IMPORTANT: we read the sheet with pandas (which returns the *computed*
    cell values for the active sheet, the same values openpyxl would only
    expose with data_only=True after Excel had cached them). Reading with a
    plain openpyxl load_workbook()+save() round-trip is unsafe here: any
    column defined by an Excel FORMULA (this workbook's `dic` column was
    formula-driven) is loaded as the formula text, not its value, and
    re-saving writes a blank because openpyxl does not evaluate formulas.
    Round-tripping through a pandas DataFrame captures the values and writes
    a clean static-value workbook, so no column is silently emptied.
    """
    import pandas as pd

    df = pd.read_excel(xlsx_in, sheet_name=sheet_index)

    if SAMPLE_TYPE_COL not in df.columns:
        raise SystemExit(
            f"Column '{SAMPLE_TYPE_COL}' not found. Found: {list(df.columns)}"
        )

    is_sample = (
        df[SAMPLE_TYPE_COL].astype("string").str.strip().str.lower()
        == SAMPLE_TYPE_VALUE
    )
    n_sample = int(is_sample.sum())
    n_other = int((~is_sample).sum())

    # Add/overwrite provenance columns: value on sample rows, blank elsewhere.
    for name, value in PROVENANCE.items():
        df[name] = pd.Series(pd.NA, index=df.index, dtype="object")
        df.loc[is_sample, name] = value

    # Sanity guard: confirm we did not lose any pre-existing chemistry values
    # during the read (catches the formula-blanking failure mode explicitly).
    for guard_col in ("dic", "ta", "ph_observed"):
        if guard_col in df.columns:
            n = int(df[guard_col].notna().sum())
            print(f"  carried {guard_col:14}: {n}/{len(df)} non-null")

    df.to_excel(xlsx_out, index=False)
    print(f"Stamped provenance into: {xlsx_out}")
    print(f"  sample rows stamped : {n_sample}")
    print(f"  other rows skipped  : {n_other}  (std/crm/etc. left blank)")
    print(f"  columns written     : {', '.join(PROVENANCE)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", type=Path, help="Path to the input .xlsx workbook")
    ap.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file instead of writing *_provenance.xlsx",
    )
    ap.add_argument(
        "--sheet-index", type=int, default=0, help="0-based sheet index"
    )
    args = ap.parse_args()

    xlsx_in: Path = args.xlsx.expanduser()
    if not xlsx_in.exists():
        raise SystemExit(f"File not found: {xlsx_in}")

    if args.in_place:
        xlsx_out = xlsx_in
        # Safety backup before mutating in place.
        backup = xlsx_in.with_suffix(xlsx_in.suffix + ".bak")
        shutil.copy2(xlsx_in, backup)
        print(f"Backup written: {backup}")
    else:
        xlsx_out = xlsx_in.with_name(xlsx_in.stem + "_provenance" + xlsx_in.suffix)

    stamp(xlsx_in, xlsx_out, sheet_index=args.sheet_index)


if __name__ == "__main__":
    main()