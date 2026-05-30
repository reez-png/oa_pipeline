"""
make_example_data.py
====================
Generate example_data.xlsx, a small synthetic ocean acidification dataset used
by the quickstart tutorial and the pytest end to end smoke test.

The dataset is synthetic but realistic: 27 rows of carbonate system data at a
fictitious coastal Ghana sampling site on the Volta estuary shelf near
5.6 N, 0.6 E.

Workbook layout
---------------
20 sample rows
4 CRM rows for TA correction
3 TRIS pH standard rows for pH correction

Controlled Stage 4 outcomes
---------------------------
The example intentionally injects a small number of known problems so the end
to end test can verify that the full pipeline is working.

EXPECTED_STAGE4_OUTCOMES records the intended final audit outcomes:

S005 -> REVIEW, range_flag
S007 -> FAIL, missing_key
S010 -> FAIL, strict_dic_species_fail
S015 -> FAIL, strict_dic_species_fail

No replicate conflict is intentionally injected. Sample dates, stations, and
depths are constructed to avoid accidental replicate group conflicts during
Stage 2 harmonisation.

Important scientific note
-------------------------
The carbonate fields are internally consistent synthetic values. This script
does not call PyCO2SYS or any other carbonate solver. The provenance columns
therefore use synthetic_example_generator rather than PyCO2SYS.

Running this script
-------------------
python make_example_data.py
python make_example_data.py --out PATH

The output is deterministic because a fixed random seed is used.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd


SEED: Final[int] = 20260516
N_SAMPLES: Final[int] = 20
N_CRMS: Final[int] = 4
N_PH_STANDARDS: Final[int] = 3
TOTAL_ROWS: Final[int] = N_SAMPLES + N_CRMS + N_PH_STANDARDS
SHEET_NAME: Final[str] = "oa_data"

SYNTHETIC_SOLVER: Final[str] = "synthetic_example_generator"
SYNTHETIC_INPUT_PAIR: Final[str] = "synthetic TA + pH_observed"

EXPECTED_STAGE4_OUTCOMES: Final[dict[str, tuple[str, str]]] = {
    "S005": ("REVIEW", "range_flag"),
    "S007": ("FAIL", "missing_key"),
    "S010": ("FAIL", "strict_dic_species_fail"),
    "S015": ("FAIL", "strict_dic_species_fail"),
}


def _build_clean_samples(rng: np.random.Generator) -> pd.DataFrame:
    """Build 20 sample rows that should pass unless later mutated.

    Carbonate system values are drawn together so that:

        DIC = CO2aq + HCO3 + CO3

    to within rounding precision. Observed pH and synthetic calculated pH agree
    within about 0.02, which is inside the default Stage 3 tolerance of 0.10.
    """
    n = N_SAMPLES
    base_date = pd.Timestamp("2024-03-01")

    # Use one unique day per sample. This prevents accidental replicate conflict
    # groups when Stage 2 uses day, station, and depth style grouping keys.
    dates = [base_date + pd.Timedelta(days=i) for i in range(n)]

    station_ids = [f"V{1 + i % 4:02d}" for i in range(n)]
    station_lat = {"V01": 5.55, "V02": 5.60, "V03": 5.65, "V04": 5.70}
    station_lon = {"V01": 0.55, "V02": 0.60, "V03": 0.65, "V04": 0.70}

    latitude = [station_lat[s] + rng.normal(0, 0.002) for s in station_ids]
    longitude = [station_lon[s] + rng.normal(0, 0.002) for s in station_ids]

    depth_sequence = np.array([2.0, 5.0, 10.0, 20.0] * 5, dtype=float)

    salinity = rng.uniform(33.0, 36.0, n).round(2)
    temp_insitu = rng.uniform(24.0, 29.0, n).round(2)
    temp_lab = (temp_insitu + rng.normal(0, 0.3, n)).round(2)

    ta = rng.uniform(2200.0, 2350.0, n).round(2)
    ph_observed = rng.uniform(7.95, 8.15, n).round(3)

    # Synthetic carbonate values. These are not solver outputs. They are only
    # constructed to satisfy an internal DIC species sum for testing.
    dic = (ta * rng.uniform(0.88, 0.92, n)).round(2)
    co2aq = (dic * rng.uniform(0.005, 0.012, n)).round(2)
    co3 = (dic * rng.uniform(0.04, 0.08, n)).round(2)
    hco3 = (dic - co2aq - co3).round(2)

    ph_calculated = (ph_observed + rng.normal(0, 0.008, n)).round(3)

    return pd.DataFrame(
        {
            "sample_tag": [f"S{i + 1:03d}" for i in range(n)],
            "crm_or_sample": ["sample"] * n,
            "sample_id": [f"OA-2024-{i + 1:03d}" for i in range(n)],
            "cruise_id": ["VISS-EX-2024"] * n,
            "transect_id": ["T1"] * n,
            "station_id": station_ids,
            "replicate_id": [f"r{1 + (i % 2)}" for i in range(n)],
            "sample_date": dates,
            "depth_m": depth_sequence,
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
            "carbonate_solver": [SYNTHETIC_SOLVER] * n,
            "carbon_input_pair_used": [SYNTHETIC_INPUT_PAIR] * n,
        }
    )


def _build_crm_rows(rng: np.random.Generator) -> pd.DataFrame:
    """Build 4 CRM rows tagged RM213_* for Notebook 02 TA correction."""
    n = N_CRMS
    base_date = pd.Timestamp("2024-03-15")

    return pd.DataFrame(
        {
            "sample_tag": [f"RM213_{i + 1}" for i in range(n)],
            "crm_or_sample": ["crm"] * n,
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
            "temp_lab": rng.uniform(25.0, 25.5, n).round(2),
            "temperature_insitu_c": [pd.NA] * n,
            "pressure_output_dbar": [pd.NA] * n,
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
        }
    )


def _build_ph_standard_rows() -> pd.DataFrame:
    """Build 3 TRIS pH standard rows for Notebook 02 pH correction."""
    n = N_PH_STANDARDS
    base_date = pd.Timestamp("2024-03-15")

    return pd.DataFrame(
        {
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
        }
    )


def _inject_known_issues(df: pd.DataFrame) -> pd.DataFrame:
    """Inject intentional issues used by the end to end smoke test."""
    out = df.copy()

    # Sample S005 -> salinity 50, above the Stage 4 sal_max of 42.
    # Expected Stage 4 outcome: REVIEW with reason range_flag.
    out.loc[out["sample_tag"].eq("S005"), "salinity"] = 50.0

    # Sample S007 -> missing sample_id.
    # Expected Stage 4 outcome: FAIL with reason missing_key.
    out.loc[out["sample_tag"].eq("S007"), "sample_id"] = pd.NA

    # Sample S010 -> break the DIC species sum by 200 umol/kg.
    # Expected Stage 4 outcome: FAIL with reason strict_dic_species_fail.
    mask_s010 = out["sample_tag"].eq("S010")
    out.loc[mask_s010, "co2aq_calc_umol_kg"] = (
        out.loc[mask_s010, "co2aq_calc_umol_kg"].astype(float) + 200.0
    )

    # Sample S015 -> negative HCO3, physically impossible.
    # Expected Stage 4 outcome: FAIL with reason strict_dic_species_fail.
    out.loc[out["sample_tag"].eq("S015"), "hco3_calc_umol_kg"] = -50.0

    return out


def _validate_example_dataset(df: pd.DataFrame) -> None:
    """Fail fast if the generated workbook no longer matches its contract."""
    if len(df) != TOTAL_ROWS:
        raise RuntimeError(f"Expected {TOTAL_ROWS} rows, got {len(df)}.")

    counts = df["crm_or_sample"].value_counts(dropna=False).to_dict()
    expected_counts = {
        "sample": N_SAMPLES,
        "crm": N_CRMS,
        "std": N_PH_STANDARDS,
    }

    for label, expected in expected_counts.items():
        actual = int(counts.get(label, 0))
        if actual != expected:
            raise RuntimeError(
                f"Expected {expected} {label!r} rows, got {actual}."
            )

    sample_tags = set(df.loc[df["crm_or_sample"].eq("sample"), "sample_tag"])
    missing_expected = sorted(set(EXPECTED_STAGE4_OUTCOMES) - sample_tags)

    if missing_expected:
        raise RuntimeError(
            "Expected outcome rows are missing from the sample table: "
            + ", ".join(missing_expected)
        )

    if df.loc[df["sample_tag"].eq("S005"), "salinity"].iloc[0] != 50.0:
        raise RuntimeError("S005 salinity issue was not injected correctly.")

    if not df.loc[df["sample_tag"].eq("S007"), "sample_id"].isna().iloc[0]:
        raise RuntimeError("S007 missing sample_id issue was not injected correctly.")

    sample_solver = df.loc[df["crm_or_sample"].eq("sample"), "carbonate_solver"]
    if not sample_solver.eq(SYNTHETIC_SOLVER).all():
        raise RuntimeError("Sample carbonate_solver provenance is inconsistent.")


def build_example_dataset() -> pd.DataFrame:
    """Build the full 27 row example dataset."""
    rng = np.random.default_rng(SEED)
    samples = _build_clean_samples(rng)
    samples = _inject_known_issues(samples)
    crms = _build_crm_rows(rng)
    standards = _build_ph_standard_rows()

    # The CRM and standard frames legitimately carry all-NA values in some
    # chemistry columns (a CRM has no DIC species, etc.). pandas emits a
    # FutureWarning about all-NA columns changing concat dtype behaviour; the
    # current behaviour is what we want and the generated workbook is verified
    # bit-identical, so we silence just this one warning to keep output clean.
    columns = list(samples.columns)
    frames = [
        frame.reindex(columns=columns) for frame in (samples, crms, standards)
    ]
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated",
            category=FutureWarning,
        )
        df = pd.concat(frames, ignore_index=True)
    _validate_example_dataset(df)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="example_data.xlsx",
        help="Output xlsx path. Default: example_data.xlsx in the current folder.",
    )
    args = parser.parse_args()

    df = build_example_dataset()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)

    print(f"Wrote {len(df)} rows to {out_path}")
    print(f"  Sheet:        {SHEET_NAME}")
    print(f"  Samples:      {(df['crm_or_sample'] == 'sample').sum()}")
    print(f"  CRMs:         {(df['crm_or_sample'] == 'crm').sum()}")
    print(f"  pH standards: {(df['crm_or_sample'] == 'std').sum()}")
    print("  Expected Stage 4 outcomes:")
    for sample_tag, (status, reason) in EXPECTED_STAGE4_OUTCOMES.items():
        print(f"    {sample_tag}: {status}, {reason}")


if __name__ == "__main__":
    main()
