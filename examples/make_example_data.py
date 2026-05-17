"""
make_example_data.py
====================
Generate `example_data.xlsx`, a small synthetic ocean-acidification
dataset used by the quickstart tutorial and the pytest end-to-end
smoke test.

The dataset is **synthetic but realistic**: 30 rows of carbonate-system
measurements at a fictitious coastal-Ghana sampling site (Volta estuary
shelf, 5.6 N / 0.6 E). Values are drawn from defensible ranges:

- Salinity 33-36 (coastal/shelf)
- Temperature 24-29 C (tropical)
- TA 2200-2350 umol/kg (typical surface)
- pH (total scale) 7.95-8.15
- DIC 1900-2100 umol/kg with species (CO2aq, HCO3, CO3) that satisfy
  DIC = CO2aq + HCO3 + CO3 to within ~1 umol/kg, except for two rows
  intentionally broken to exercise Stage 3's integrity check.

We also include:

- 4 CRM (certified reference material) rows tagged ``RM213_*`` so
  Notebook 02's TA correction has something to compute against the
  ``213`` batch certified value (2203.56 umol/kg in
  ``oa_qc_ta_ph.CRM_CERTIFIED_TA``).
- 3 pH-standard rows tagged ``TRIS_*`` so the pH-standard correction
  path runs.
- 1 row with salinity = 50 (above the Stage 4 `sal_max` of 42)
  -> demonstrates a REVIEW verdict from `range_flag`.
- 1 row with missing `sample_id` -> demonstrates a FAIL verdict from
  `missing_key`.
- 2 rows with intentionally inconsistent DIC species
  -> demonstrates the Stage 3 DIC species-sum check firing.
- The remainder produces clean PASS rows.

Running this script:

    python make_example_data.py             # writes example_data.xlsx here
    python make_example_data.py --out PATH  # writes to a different path

The output is deterministic (fixed seed) so two runs produce identical
files. Re-run after editing this script to regenerate the bundled xlsx.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 20260516       # the EOI submission date, for sentimentality
N_SAMPLES = 20
N_CRMS = 4
N_PH_STANDARDS = 3


def _build_clean_samples(rng: np.random.Generator) -> pd.DataFrame:
    """20 clean sample rows that should mostly come out PASS.

    Carbonate-system values are drawn together so that they are mutually
    consistent: DIC = CO2aq + HCO3 + CO3 within 1 umol/kg, and
    pH_observed agrees with a synthetic ph_calculated within 0.02 (well
    inside the default Stage 3 tolerance of 0.10).
    """
    n = N_SAMPLES
    base_date = pd.Timestamp("2024-03-01", tz="UTC").tz_convert(None)
    dates = base_date + pd.to_timedelta(rng.integers(0, 60, n), unit="D")

    # Coastal Ghana ~5.6 N, 0.6 E. Add small jitter per station.
    station_ids = [f"V{1 + i % 4:02d}" for i in range(n)]
    station_lat = {"V01": 5.55, "V02": 5.60, "V03": 5.65, "V04": 5.70}
    station_lon = {"V01": 0.55, "V02": 0.60, "V03": 0.65, "V04": 0.70}
    latitude = [station_lat[s] + rng.normal(0, 0.002) for s in station_ids]
    longitude = [station_lon[s] + rng.normal(0, 0.002) for s in station_ids]

    salinity = rng.uniform(33.0, 36.0, n).round(2)
    temp_insitu = rng.uniform(24.0, 29.0, n).round(2)
    temp_lab = (temp_insitu + rng.normal(0, 0.3, n)).round(2)

    # TA + pH drawn together so they are physically consistent.
    ta = rng.uniform(2200.0, 2350.0, n).round(2)
    ph_observed = rng.uniform(7.95, 8.15, n).round(3)

    # Approximate DIC from TA + pH using simple coastal-shelf ratios.
    # We are NOT calling PyCO2SYS here -- this is synthetic data, not a
    # validated calculation. The point is internal consistency: the
    # four species sum to DIC.
    dic = (ta * rng.uniform(0.88, 0.92, n)).round(2)
    co2aq = (dic * rng.uniform(0.005, 0.012, n)).round(2)
    co3 = (dic * rng.uniform(0.04, 0.08, n)).round(2)
    hco3 = (dic - co2aq - co3).round(2)

    # Synthetic calculated pH agrees with observed within +/- 0.02.
    ph_calculated = (ph_observed + rng.normal(0, 0.008, n)).round(3)

    df = pd.DataFrame({
        "sample_tag": [f"S{i + 1:03d}" for i in range(n)],
        "crm_or_sample": ["sample"] * n,
        "sample_id": [f"OA-2024-{i + 1:03d}" for i in range(n)],
        "cruise_id": ["VISS-EX-2024"] * n,
        "transect_id": ["T1"] * n,
        "station_id": station_ids,
        "replicate_id": [f"r{1 + (i % 2)}" for i in range(n)],
        "sample_date": dates,
        "depth_m": rng.choice([2.0, 5.0, 10.0, 20.0], n),
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "salinity": salinity,
        "temp_lab": temp_lab,
        "temperature_insitu_c": temp_insitu,
        "pressure_output_dbar": rng.uniform(2.0, 25.0, n).round(2),
        "ta": ta,
        "pH_lab": ph_observed,
        "ph_calculated": ph_calculated,
        "ph_scale_observed": ["total"] * n,
        "ph_scale_calculated": ["total"] * n,
        "dic_calculated_umol_kg": dic,
        "co2aq_calc_umol_kg": co2aq,
        "hco3_calc_umol_kg": hco3,
        "co3_calc_umol_kg": co3,
        "dic_unit": ["umol/kg"] * n,
        "co2aq_unit": ["umol/kg"] * n,
        "hco3_unit": ["umol/kg"] * n,
        "co3_unit": ["umol/kg"] * n,
        "pco2_calc_uatm": rng.uniform(380.0, 500.0, n).round(1),
        "ta_units": ["umol/kg"] * n,
        "oxygen_umol_l": rng.uniform(190.0, 240.0, n).round(1),
        "nitrate_nitrite_umol_l": rng.uniform(0.5, 8.0, n).round(2),
        "phosphate_umol_l": rng.uniform(0.05, 1.2, n).round(3),
        "silicate_umol_l": rng.uniform(2.0, 15.0, n).round(2),
        "chlorophyll": rng.uniform(0.2, 5.0, n).round(2),
        "carbonate_solver": ["PyCO2SYS"] * n,
        "carbon_input_pair_used": ["TA + pH_observed"] * n,
    })
    return df


def _build_crm_rows(rng: np.random.Generator) -> pd.DataFrame:
    """4 CRM rows tagged RM213_* with TA values near the certified
    value of 2203.56 umol/kg (CRM batch 213).

    The Notebook 02 TA QC step will compute the per-batch correction
    from these rows. One row is intentionally a bit off (~2208) so the
    correction is non-trivial.
    """
    n = N_CRMS
    base_date = pd.Timestamp("2024-03-15", tz="UTC").tz_convert(None)
    return pd.DataFrame({
        "sample_tag": [f"RM213_{i + 1}" for i in range(n)],
        "crm_or_sample": ["crm"] * n,
        "sample_id": [pd.NA] * n,           # CRMs lack sample IDs (correct)
        "cruise_id": ["VISS-EX-2024"] * n,
        "transect_id": [pd.NA] * n,
        "station_id": [pd.NA] * n,
        "replicate_id": [f"r{1 + i}" for i in range(n)],
        "sample_date": [base_date] * n,
        "depth_m": [pd.NA] * n,
        "latitude_deg": [pd.NA] * n,
        "longitude_deg": [pd.NA] * n,
        "salinity": [35.0] * n,             # nominal CRM salinity
        "temp_lab": rng.uniform(25.0, 25.5, n).round(2),
        "temperature_insitu_c": [pd.NA] * n,
        "pressure_output_dbar": [pd.NA] * n,
        # TA values cluster near 2203.56 (the certified value for batch 213)
        # except RM213_3 which is high; the QC will compute a small correction.
        "ta": [2204.10, 2202.80, 2208.20, 2203.60][:n],
        "pH_lab": rng.uniform(8.05, 8.10, n).round(3),
        "ph_calculated": [pd.NA] * n,
        "ph_scale_observed": ["total"] * n,
        "ph_scale_calculated": [pd.NA] * n,
        "dic_calculated_umol_kg": [pd.NA] * n,
        "co2aq_calc_umol_kg": [pd.NA] * n,
        "hco3_calc_umol_kg": [pd.NA] * n,
        "co3_calc_umol_kg": [pd.NA] * n,
        "dic_unit": [pd.NA] * n,
        "co2aq_unit": [pd.NA] * n,
        "hco3_unit": [pd.NA] * n,
        "co3_unit": [pd.NA] * n,
        "pco2_calc_uatm": [pd.NA] * n,
        "ta_units": ["umol/kg"] * n,
        "oxygen_umol_l": [pd.NA] * n,
        "nitrate_nitrite_umol_l": [pd.NA] * n,
        "phosphate_umol_l": [pd.NA] * n,
        "silicate_umol_l": [pd.NA] * n,
        "chlorophyll": [pd.NA] * n,
        "carbonate_solver": [pd.NA] * n,
        "carbon_input_pair_used": [pd.NA] * n,
    })


def _build_ph_standard_rows() -> pd.DataFrame:
    """3 pH-standard buffer rows tagged TRIS_* so Notebook 02's
    pH-standard correction path exercises.

    Values are close to the Dickson SOP TRIS expected value (~8.09 at
    25 C, S = 35), with small lab-noise deviations.
    """
    n = N_PH_STANDARDS
    base_date = pd.Timestamp("2024-03-15", tz="UTC").tz_convert(None)
    return pd.DataFrame({
        "sample_tag": [f"TRIS_{i + 1}" for i in range(n)],
        "crm_or_sample": ["std"] * n,
        "sample_id": [pd.NA] * n,
        "cruise_id": ["VISS-EX-2024"] * n,
        "transect_id": [pd.NA] * n,
        "station_id": [pd.NA] * n,
        "replicate_id": [f"r{1 + i}" for i in range(n)],
        "sample_date": [base_date] * n,
        "depth_m": [pd.NA] * n,
        "latitude_deg": [pd.NA] * n,
        "longitude_deg": [pd.NA] * n,
        "salinity": [35.0] * n,
        "temp_lab": [25.0] * n,
        "temperature_insitu_c": [pd.NA] * n,
        "pressure_output_dbar": [pd.NA] * n,
        "ta": [pd.NA] * n,
        # TRIS expected ~8.09 at 25 C, salinity 35; we have small lab-noise dev.
        "pH_lab": [8.08, 8.09, 8.07][:n],
        "ph_calculated": [pd.NA] * n,
        "ph_scale_observed": ["total"] * n,
        "ph_scale_calculated": [pd.NA] * n,
        "dic_calculated_umol_kg": [pd.NA] * n,
        "co2aq_calc_umol_kg": [pd.NA] * n,
        "hco3_calc_umol_kg": [pd.NA] * n,
        "co3_calc_umol_kg": [pd.NA] * n,
        "dic_unit": [pd.NA] * n,
        "co2aq_unit": [pd.NA] * n,
        "hco3_unit": [pd.NA] * n,
        "co3_unit": [pd.NA] * n,
        "pco2_calc_uatm": [pd.NA] * n,
        "ta_units": [pd.NA] * n,
        "oxygen_umol_l": [pd.NA] * n,
        "nitrate_nitrite_umol_l": [pd.NA] * n,
        "phosphate_umol_l": [pd.NA] * n,
        "silicate_umol_l": [pd.NA] * n,
        "chlorophyll": [pd.NA] * n,
        "carbonate_solver": [pd.NA] * n,
        "carbon_input_pair_used": [pd.NA] * n,
    })


def _inject_known_issues(df: pd.DataFrame) -> pd.DataFrame:
    """Mutate `df` to inject a small number of intentional issues that
    every stage's flag machinery should catch. Returns the mutated df.

    Each mutation is paired with a comment naming the verdict it should
    produce at Stage 4, so anyone reading the quickstart can trace
    cause-and-effect.
    """
    out = df.copy()

    # Sample S005 -> salinity 50 (above sal_max=42)
    # -> Stage 4 REVIEW with reason `range_flag`.
    mask = out["sample_tag"].eq("S005")
    out.loc[mask, "salinity"] = 50.0

    # Sample S007 -> drop sample_id
    # -> Stage 4 FAIL with reason `missing_key`.
    out.loc[out["sample_tag"].eq("S007"), "sample_id"] = pd.NA

    # Sample S010 -> break the DIC species sum by 200 umol/kg
    # -> Stage 3 `flag_dic_inconsistent` -> Stage 4 REVIEW with reason
    # `stage3_issue`.
    mask = out["sample_tag"].eq("S010")
    out.loc[mask, "co2aq_calc_umol_kg"] = (
        out.loc[mask, "co2aq_calc_umol_kg"].astype(float) + 200.0
    )

    # Sample S015 -> negative HCO3 (physically impossible)
    # -> Stage 3 `flag_any_negative_species` (in `flag_any_carbonate_issue`)
    # -> Stage 4 REVIEW with `stage3_issue`.
    out.loc[out["sample_tag"].eq("S015"), "hco3_calc_umol_kg"] = -50.0

    return out


def build_example_dataset() -> pd.DataFrame:
    """Build the full 27-row example dataset.

    Layout: 20 clean samples + 4 CRMs + 3 pH standards, with 4 of the
    sample rows mutated to demonstrate Stages 3 and 4 flagging.
    """
    rng = np.random.default_rng(SEED)
    samples = _build_clean_samples(rng)
    samples = _inject_known_issues(samples)
    crms = _build_crm_rows(rng)
    stds = _build_ph_standard_rows()
    return pd.concat([samples, crms, stds], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="example_data.xlsx",
        help="Output xlsx path (default: example_data.xlsx in cwd)",
    )
    args = parser.parse_args()

    df = build_example_dataset()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Single-sheet workbook. Notebook 02 picks the sheet via the SHEET
    # parameter; the first sheet ("Sheet1") is the default.
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="oa_data", index=False)

    print(f"Wrote {len(df)} rows to {out_path}")
    print(f"  Samples:      {(df['crm_or_sample'] == 'sample').sum()}")
    print(f"  CRMs:         {(df['crm_or_sample'] == 'crm').sum()}")
    print(f"  pH standards: {(df['crm_or_sample'] == 'std').sum()}")


if __name__ == "__main__":
    main()
