#!/usr/bin/env python3
"""
oa_plots.py — reusable plotting for ocean-acidification / carbonate data
========================================================================

Works on BOTH:
  * the preliminary workbook (columns like pH_lab, omega_ar, Station, Depth), and
  * the pipeline's analysis_ready.csv (ph_best, omega_aragonite_calc, station_id...)

It auto-detects which column names are present via an alias map, drops CRM/std
reference rows, and offers a menu of plot types. Quick PNGs by default; pass
--polished for figure-quality styling.

Usage
-----
    python oa_plots.py INPUT [--plots LIST] [--outdir DIR] [--polished] [--show]

    INPUT            path to .xlsx or .csv
    --sheet NAME     sheet name/index for xlsx (default: first sheet)
    --plots LIST     comma-separated subset of:
                     timeseries, profiles, transects, crossplots, map, all
                     (default: all)
    --outdir DIR     where PNGs go (default: ./oa_figures)
    --polished       higher-DPI, cleaner styling for sharing
    --show           also display interactively

Examples
--------
    python oa_plots.py data/raw/oa_prelim_data.xlsx
    python oa_plots.py data/processed/oa_stage4_outputs/data/analysis_ready.csv --plots timeseries,crossplots
    python oa_plots.py oa_prelim_data.xlsx --polished --outdir figs_for_supervisor
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # safe default; --show switches to interactive
import matplotlib.pyplot as plt  # noqa: E402


# ---------------------------------------------------------------------------
# Column alias map: canonical name -> list of accepted source names.
# First match present in the data wins. Add aliases here as schemas evolve.
# ---------------------------------------------------------------------------
ALIASES: dict[str, list[str]] = {
    "ph": ["ph_best", "pH_lab", "ph_lab", "ph_observed"],
    "ph_calc": ["ph_co2sys", "pH_calc", "ph_calc", "ph_calculated"],
    "omega_ar": ["omega_aragonite_calc", "omega_ar"],
    "omega_ca": ["omega_calcite_calc", "omega_ca"],
    "pco2": ["pco2_best_uatm", "pco2_calc_uatm", "pco2"],
    "ta": ["ta_best_umolkg", "ta_corrected_umolkg", "ta"],
    "dic": ["dic_best_umol_kg", "dic_calc", "dic"],
    "revelle": ["revelle_factor_calc", "revelle_factor"],
    "temp_insitu": ["temperature_insitu_c", "temp_insitu"],
    "temp_lab": ["temperature_measurement_c", "temp_lab"],
    "sal": ["salinity", "sal"],
    "oxygen": ["oxygen_umol_l", "o2_umol/L", "o2_umol_l"],
    "chl": ["chlorophyll", "chl"],
    "depth": ["depth_round_m", "Depth", "depth_m", "depth"],
    "date": ["sample_date"],
    "station": ["station_id", "Station"],
    "transect": ["transect_id", "Transect"],
    "cruise": ["Cruise", "cruise_id"],
    "lat": ["latitude_deg", "latitude", "lat"],
    "lon": ["longitude_deg", "longitude", "long", "lon"],
    "kind": ["crm_or_sample", "sample_type"],
}

# Pretty labels (with units) for axes.
LABELS = {
    "ph": "pH",
    "ph_calc": "pH (calculated)",
    "omega_ar": "$\\Omega_{aragonite}$",
    "omega_ca": "$\\Omega_{calcite}$",
    "pco2": "pCO$_2$ ($\\mu$atm)",
    "ta": "Total alkalinity ($\\mu$mol kg$^{-1}$)",
    "dic": "DIC ($\\mu$mol kg$^{-1}$)",
    "revelle": "Revelle factor",
    "temp_insitu": "In situ temperature ($\\degree$C)",
    "temp_lab": "Lab temperature ($\\degree$C)",
    "sal": "Salinity",
    "oxygen": "Oxygen ($\\mu$mol L$^{-1}$)",
    "chl": "Chlorophyll",
    "depth": "Depth (m)",
}


def resolve(df: pd.DataFrame) -> dict[str, str]:
    """Map canonical names to the actual column present in df."""
    found = {}
    for canon, candidates in ALIASES.items():
        for c in candidates:
            if c in df.columns:
                found[canon] = c
                break
    return found


def load(path: Path, sheet) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        sheet_arg = 0 if sheet is None else sheet
        try:
            sheet_arg = int(sheet_arg)
        except (TypeError, ValueError):
            pass
        return pd.read_excel(path, sheet_name=sheet_arg)
    return pd.read_csv(path)


def prep(df: pd.DataFrame, col: dict[str, str]) -> pd.DataFrame:
    """Drop CRM/std reference rows, coerce numerics and dates."""
    out = df.copy()
    if "kind" in col:
        k = out[col["kind"]].astype("string").str.strip().str.lower()
        out = out[k.eq("sample")].copy()
    # numeric coercion for everything plottable
    for canon in [
        "ph", "ph_calc", "omega_ar", "omega_ca", "pco2", "ta", "dic",
        "revelle", "temp_insitu", "temp_lab", "sal", "oxygen", "chl",
        "depth", "lat", "lon",
    ]:
        if canon in col:
            out[col[canon]] = pd.to_numeric(out[col[canon]], errors="coerce")
    if "date" in col:
        out[col["date"]] = pd.to_datetime(out[col["date"]], errors="coerce")
    return out


def _style(polished: bool) -> dict:
    if polished:
        plt.rcParams.update({
            "figure.dpi": 200, "savefig.dpi": 300,
            "font.size": 11, "axes.grid": True,
            "grid.alpha": 0.3, "axes.spines.top": False,
            "axes.spines.right": False,
        })
        return {"s": 45, "alpha": 0.85, "edgecolor": "white", "linewidth": 0.5}
    plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 140, "axes.grid": True, "grid.alpha": 0.25})
    return {"s": 35, "alpha": 0.8}


def _save(fig, outdir: Path, name: str, show: bool):
    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / f"{name}.png"
    fig.savefig(p, bbox_inches="tight")
    print(f"  wrote {p}")
    if show:
        plt.show()
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot types
# ---------------------------------------------------------------------------
def plot_timeseries(df, col, outdir, sc, show):
    """Key carbonate vars over time, one point per sample, colored by cruise."""
    if "date" not in col:
        print("  [timeseries] no date column; skipping")
        return
    vars_ = [v for v in ["ph", "omega_ar", "pco2", "ta", "dic", "temp_insitu"] if v in col]
    if not vars_:
        print("  [timeseries] no plottable variables; skipping")
        return
    group = "cruise" if "cruise" in col else ("transect" if "transect" in col else None)
    n = len(vars_)
    ncol = 2
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(12, 3.2 * nrow), squeeze=False)
    for i, v in enumerate(vars_):
        ax = axes[i // ncol][i % ncol]
        if group:
            for gname, gdf in df.groupby(col[group]):
                ax.scatter(gdf[col["date"]], gdf[col[v]], label=str(gname), **sc)
        else:
            ax.scatter(df[col["date"]], df[col[v]], **sc)
        ax.set_ylabel(LABELS.get(v, v))
        ax.set_xlabel("Date")
        ax.tick_params(axis="x", rotation=30)
        if v == "omega_ar":
            ax.axhline(1.0, ls="--", c="firebrick", lw=1, label="$\\Omega$=1 (saturation)")
    for j in range(n, nrow * ncol):
        axes[j // ncol][j % ncol].axis("off")
    if group:
        h, l = axes[0][0].get_legend_handles_labels()
        fig.legend(h, l, loc="upper center", ncol=min(6, len(l)), bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Carbonate system over sampling period", y=1.04, fontsize=13)
    fig.tight_layout()
    _save(fig, outdir, "timeseries_by_cruise", show)


def plot_profiles(df, col, outdir, sc, show):
    """Depth profiles of key variables, colored by cruise."""
    if "depth" not in col:
        print("  [profiles] no depth column; skipping")
        return
    vars_ = [v for v in ["ph", "omega_ar", "temp_insitu", "oxygen", "sal"] if v in col]
    if not vars_:
        print("  [profiles] no plottable variables; skipping")
        return
    group = "cruise" if "cruise" in col else ("transect" if "transect" in col else None)
    n = len(vars_)
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 5), squeeze=False)
    for i, v in enumerate(vars_):
        ax = axes[0][i]
        if group:
            for gname, gdf in df.groupby(col[group]):
                ax.scatter(gdf[col[v]], gdf[col["depth"]], label=str(gname), **sc)
        else:
            ax.scatter(df[col[v]], df[col["depth"]], **sc)
        ax.set_xlabel(LABELS.get(v, v))
        if i == 0:
            ax.set_ylabel(LABELS["depth"])
        ax.invert_yaxis()  # depth increases downward
        if v == "omega_ar":
            ax.axvline(1.0, ls="--", c="firebrick", lw=1)
    if group:
        h, l = axes[0][0].get_legend_handles_labels()
        fig.legend(h, l, loc="upper center", ncol=min(6, len(l)), bbox_to_anchor=(0.5, 1.05))
    fig.suptitle("Depth profiles", y=1.06, fontsize=13)
    fig.tight_layout()
    _save(fig, outdir, "depth_profiles", show)


def plot_transects(df, col, outdir, sc, show):
    """Distribution of key vars by transect (box + jittered points)."""
    if "transect" not in col:
        print("  [transects] no transect column; skipping")
        return
    vars_ = [v for v in ["ph", "omega_ar", "pco2", "sal"] if v in col]
    if not vars_:
        print("  [transects] no plottable variables; skipping")
        return
    cats = list(df[col["transect"]].dropna().unique())
    n = len(vars_)
    ncol = 2
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(11, 3.4 * nrow), squeeze=False)
    for i, v in enumerate(vars_):
        ax = axes[i // ncol][i % ncol]
        data = [df.loc[df[col["transect"]] == c, col[v]].dropna().values for c in cats]
        labels = [str(c) for c in cats]
        try:
            ax.boxplot(data, tick_labels=labels, showmeans=True)
        except TypeError:  # matplotlib < 3.9
            ax.boxplot(data, labels=labels, showmeans=True)
        for xi, arr in enumerate(data, start=1):
            x = np.random.normal(xi, 0.05, size=len(arr))
            ax.scatter(x, arr, s=14, alpha=0.5, color="steelblue")
        ax.set_ylabel(LABELS.get(v, v))
        ax.tick_params(axis="x", rotation=20)
        if v == "omega_ar":
            ax.axhline(1.0, ls="--", c="firebrick", lw=1)
    for j in range(n, nrow * ncol):
        axes[j // ncol][j % ncol].axis("off")
    fig.suptitle("Variation by transect", y=1.02, fontsize=13)
    fig.tight_layout()
    _save(fig, outdir, "by_transect", show)


def plot_crossplots(df, col, outdir, sc, show):
    """Relationship plots: Omega_ar vs pH, TA vs salinity, pCO2 vs temp, Omega_ar vs depth."""
    pairs = [
        ("ph", "omega_ar"),
        ("sal", "ta"),
        ("temp_insitu", "pco2"),
        ("depth", "omega_ar"),
    ]
    pairs = [(x, y) for x, y in pairs if x in col and y in col]
    if not pairs:
        print("  [crossplots] no plottable pairs; skipping")
        return
    group = "cruise" if "cruise" in col else ("transect" if "transect" in col else None)
    n = len(pairs)
    ncol = 2
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(11, 4.2 * nrow), squeeze=False)
    for i, (xv, yv) in enumerate(pairs):
        ax = axes[i // ncol][i % ncol]
        if group:
            for gname, gdf in df.groupby(col[group]):
                ax.scatter(gdf[col[xv]], gdf[col[yv]], label=str(gname), **sc)
        else:
            ax.scatter(df[col[xv]], df[col[yv]], **sc)
        ax.set_xlabel(LABELS.get(xv, xv))
        ax.set_ylabel(LABELS.get(yv, yv))
        if yv == "omega_ar":
            ax.axhline(1.0, ls="--", c="firebrick", lw=1)
    for j in range(n, nrow * ncol):
        axes[j // ncol][j % ncol].axis("off")
    if group:
        h, l = axes[0][0].get_legend_handles_labels()
        fig.legend(h, l, loc="upper center", ncol=min(6, len(l)), bbox_to_anchor=(0.5, 1.03))
    fig.suptitle("Relationships between variables", y=1.04, fontsize=13)
    fig.tight_layout()
    _save(fig, outdir, "crossplots", show)


def plot_map(df, col, outdir, sc, show):
    """Station map colored by Omega_ar (or pH) if lat/lon present."""
    if "lat" not in col or "lon" not in col:
        print("  [map] no lat/lon columns; skipping")
        return
    cvar = "omega_ar" if "omega_ar" in col else ("ph" if "ph" in col else None)
    fig, ax = plt.subplots(figsize=(7, 6))
    if cvar:
        sca = ax.scatter(df[col["lon"]], df[col["lat"]], c=df[col[cvar]],
                         cmap="viridis", s=55, edgecolor="k", linewidth=0.3)
        fig.colorbar(sca, ax=ax, label=LABELS.get(cvar, cvar))
    else:
        ax.scatter(df[col["lon"]], df[col["lat"]], **sc)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Sampling stations")
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    _save(fig, outdir, "station_map", show)


PLOTS = {
    "timeseries": plot_timeseries,
    "profiles": plot_profiles,
    "transects": plot_transects,
    "crossplots": plot_crossplots,
    "map": plot_map,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--plots", default="all")
    ap.add_argument("--outdir", type=Path, default=Path("oa_figures"))
    ap.add_argument("--polished", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    if args.show:
        matplotlib.use("TkAgg", force=True)

    df0 = load(args.input, args.sheet)
    col = resolve(df0)
    df = prep(df0, col)
    print(f"Loaded {args.input.name}: {len(df)} sample rows (CRM/std dropped).")
    print(f"Detected columns: {', '.join(sorted(col))}")

    which = list(PLOTS) if args.plots.strip().lower() == "all" else [
        p.strip() for p in args.plots.split(",") if p.strip()
    ]
    sc = _style(args.polished)
    for name in which:
        fn = PLOTS.get(name)
        if fn is None:
            print(f"  [{name}] unknown plot type; choices: {', '.join(PLOTS)}")
            continue
        fn(df, col, args.outdir, sc, args.show)
    print(f"Done. Figures in: {args.outdir.resolve()}")


if __name__ == "__main__":
    main()
