"""Tests for oa_pipeline.carbonate_calc — internal carbonate-system calculation.

These lock in the validated behaviour: PyCO2SYS with the pinned settings must
reproduce the reference CO2SYS-Excel output on raw TA, applying the RM
correction must lower Omega slightly, provenance must be stamped, and rows
lacking the core parameters must be skipped cleanly.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PyCO2SYS")

from oa_pipeline import carbonate_calc as cc


def _one_row(ta):
    """A single validated sample (J1-C1-N6) with the given TA."""
    return pd.DataFrame({
        "sample_tag": ["J1-C1-N6"],
        "ta": [ta],
        "ph_observed": [8.020047626852753],
        "sal": [35.1783],
        "temp_lab": [23.6],
        "temp_insitu": [29.2012],
        "pressure_insitu_dbar": [4.022],
    })


def _corrected_row(ta_corrected):
    """A validated sample whose TA is provided as ta_corrected_umolkg."""
    df = _one_row(ta_corrected)
    df["ta_corrected_umolkg"] = ta_corrected
    return df


def test_reproduces_excel_on_raw_ta():
    """Raw TA 2173.60 must give Omega_ar ~3.0218 (the Excel reference).

    Disable require_corrected_ta so the calc runs on the raw 'ta' column for
    this solver-reproduction check.
    """
    res = cc.compute(_one_row(2173.602653), {"require_corrected_ta": False})
    om = res.df["omega_aragonite_calc"].iloc[0]
    assert abs(om - 3.0218) < 0.005, f"got {om}, expected ~3.0218"
    dic = res.df["dic"].iloc[0]
    assert abs(dic - 1906.67) < 1.0, f"got {dic}, expected ~1906.67"


def test_reproduces_excel_on_raw_ta_default_skips():
    """With the default (require_corrected_ta=True), a row lacking
    ta_corrected_umolkg must SKIP and leave chemistry untouched — this protects
    synthetic/example data whose injected chemistry the E2E tests depend on."""
    res = cc.compute(_one_row(2173.602653))  # no ta_corrected_umolkg column
    assert res.n_computed == 0
    assert "omega_aragonite_calc" not in res.df.columns
    assert any("Skipped internal calculation" in n for n in res.notes)


def test_correction_lowers_omega():
    """Corrected TA (lower) must give a lower Omega_ar than raw TA."""
    raw = cc.compute(_corrected_row(2173.602653)).df["omega_aragonite_calc"].iloc[0]
    corr = cc.compute(_corrected_row(2163.8285)).df["omega_aragonite_calc"].iloc[0]
    assert corr < raw


def test_provenance_stamped():
    res = cc.compute(_corrected_row(2163.8285))
    row = res.df.iloc[0]
    assert str(row["carbonate_solver"]).startswith("PyCO2SYS")
    assert row["carbon_input_pair_used"] == "TA_pH"
    assert row["carbonate_ph_scale"] == "total"
    assert row["carbonate_output_temperature"] == "in_situ"
    assert bool(row["carbonate_calc_internal"]) is True


def test_settings_pinned():
    res = cc.compute(_corrected_row(2163.8285))
    s = res.settings
    assert s["opt_k_carbonic"] == 10      # Lueker 2000
    assert s["opt_k_bisulfate"] == 1      # Dickson 1990
    assert s["opt_total_borate"] == 2     # Lee 2010
    assert s["opt_k_fluoride"] == 2       # Perez & Fraga 1987
    assert s["opt_pH_scale"] == 1         # total


def test_skips_rows_without_core_params():
    df = _corrected_row(2163.8285)
    df.loc[1] = df.loc[0]
    df.loc[1, "ph_observed"] = np.nan   # second row missing pH -> skip
    res = cc.compute(df)
    assert res.n_computed == 1
    assert res.n_skipped == 1
    assert pd.isna(res.df.loc[1, "omega_aragonite_calc"])


def test_prefers_corrected_ta_column():
    """When ta_corrected_umolkg is present it must be used over raw ta."""
    df = _one_row(2173.602653)
    df["ta_corrected_umolkg"] = 2163.8285
    res = cc.compute(df)
    # result should match the corrected-TA number, not the raw one
    om = res.df["omega_aragonite_calc"].iloc[0]
    om_corr = cc.compute(_corrected_row(2163.8285)).df["omega_aragonite_calc"].iloc[0]
    assert abs(om - om_corr) < 1e-6


def test_disabled_returns_untouched():
    res = cc.compute(_corrected_row(2163.8285), {"enabled": False})
    assert res.n_computed == 0
    assert "omega_aragonite_calc" not in res.df.columns or \
           res.df["omega_aragonite_calc"].isna().all()
