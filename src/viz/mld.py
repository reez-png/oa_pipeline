# ───────────────────────── src/viz/mld.py ─────────────────────────
from __future__ import annotations
import numpy as np
import pandas as pd

def overlay_mld_on_section(ax, *,
                           df_all: pd.DataFrame,
                           cast_tbl: pd.DataFrame,
                           lat_col: str = "lat",
                           season: str,
                           lat_bins: np.ndarray) -> None:
    """
    Plot a single white MLD line (median by lat-bin) on an existing lat–depth section.
    Uses density-based MLD when available, else temperature-based.
    """
    if df_all.empty or cast_tbl.empty or lat_col not in df_all.columns:
        return

    # representative latitude per cast
    rep_lat = df_all.groupby("cast_id")[lat_col].median().rename("lat_rep")
    cc = cast_tbl.merge(rep_lat, left_on="cast_id", right_index=True, how="left")
    cc = cc.loc[cc["season"] == season]

    if cc.empty:
        return

    crit = "mld_sigma_m" if np.isfinite(cc["mld_sigma_m"]).any() else ("mld_temp_m" if np.isfinite(cc["mld_temp_m"]).any() else None)
    if crit is None:
        return

    # bin by latitude
    X = 0.5*(lat_bins[1:] + lat_bins[:-1])
    cc = cc.dropna(subset=["lat_rep"])
    cc["ilat"] = np.clip(np.digitize(cc["lat_rep"], lat_bins)-1, 0, len(lat_bins)-2)
    mld_line = cc.groupby("ilat")[crit].median().dropna()
    if not mld_line.empty:
        ax.plot(X[mld_line.index], mld_line.values, color="w", lw=1.8, label="MLD")
        # avoid duplicate legends if caller handles them
