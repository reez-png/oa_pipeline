# src/viz/style.py
from __future__ import annotations
from pathlib import Path
import re
import warnings
import matplotlib as mpl
import matplotlib.pyplot as plt

def set_pub_defaults():
    """Journal-ready defaults; supports subscripts (CO2, Ωarag) without warnings."""
    mpl.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "font.family": "DejaVu Sans",        # robust glyph coverage
        "mathtext.fontset": "dejavusans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,                   # no gridlines
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.titleweight": "bold",
        "legend.frameon": False,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,                  # TrueType embed (publisher-friendly)
        "ps.fonttype": 42,
    })

def chem(label: str) -> str:
    """Pretty labels for common variables (auto-fallback to raw)."""
    repl = {
        # carbonate
        "pCO2": r"$p$CO$_2$ (µatm)",
        "delta_pCO2": r"$\Delta p$CO$_2$ (µatm)",
        "Omega_ar": r"$\Omega_{\mathrm{arag}}$",
        "Omega_ca": r"$\Omega_{\mathrm{calc}}$",
        "HCO3": r"HCO$_3^-$ (µmol kg$^{-1}$)",
        "CO3": r"CO$_3^{2-}$ (µmol kg$^{-1}$)",
        "ta": r"Total Alkalinity (µmol kg$^{-1}$)",
        "ph": r"pH (total)",
        "FCO2": r"$F_{\mathrm{CO_2}}$ (mmol m$^{-2}$ d$^{-1}$)",
        # hydro
        "temp_wat": r"Temperature (°C)",
        "sal_wat": "Salinity (PSU)",
        "sigma_theta": r"$\sigma_\theta$ (kg m$^{-3}$)",
        # oxygen
        "O2_sat_pct": r"O$_2$ sat. (%)",
        "AOU": r"AOU (µmol kg$^{-1}$)",
        # nutrients (if present)
        "NOx_uM": r"NO$_3$+NO$_2$ (µM)",
        "PO4_uM": r"PO$_4^{3-}$ (µM)",
        "Si_uM": r"Si(OH)$_4$ (µM)",
        # forcing
        "wind10": r"10 m wind (m s$^{-1}$)",
    }
    return repl.get(label, label)

def add_panel_label(ax, label="a", loc="upper left", dx=0.02, dy=0.02, **textkw):
    """
    Draw a small panel label like '(a)' on an axes.

    Parameters
    ----------
    ax : matplotlib Axes
    label : str
        Panel letter/marker, e.g. 'a'.
    loc : {'upper left','upper right','lower left','lower right'}
        Corner of the axes to place the label.
    dx, dy : float
        Offsets from the chosen corner in axes-fraction units.
    **textkw : dict
        Forwarded to ax.text (e.g., fontsize=12, fontweight='bold', color='k').
    """
    label_text = f"({label})"
    x = dx if "right" not in loc else 1 - dx
    y = 1 - dy if "upper" in loc else dy
    ha = "left" if "left" in loc else "right"
    va = "top"  if "upper" in loc else "bottom"

    default_kw = dict(fontweight="bold", fontsize=10, transform=ax.transAxes)
    default_kw.update(textkw or {})
    ax.text(x, y, label_text, ha=ha, va=va, **default_kw)

def _sanitize(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)  # Windows-safe
    return re.sub(r"\s+", " ", name).strip()

def savefig_multi(fig, out_base: Path, *, dpi: int = 300, pad_inches: float = 0.08):
    """
    Save to PNG and PDF. If the figure already uses the 'constrained' layout
    engine (e.g., created with constrained_layout=True and colorbars added),
    skip fig.tight_layout() to avoid engine conflicts.
    """
    out_base = Path(out_base)

    # Detect current layout engine (Matplotlib ≥3.6 returns an engine object)
    try:
        eng = fig.get_layout_engine()
        eng_name = getattr(eng, "name", None) if eng is not None else None
    except Exception:
        eng_name = None  # older Matplotlib – be conservative

    # Only run tight_layout when not using 'constrained'
    if eng_name in (None, "tight"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                fig.tight_layout()
            except Exception:
                # Don't fail saving just because tight_layout choked
                pass

    fig.savefig(out_base.with_suffix(".png"), dpi=dpi,
                bbox_inches="tight", pad_inches=pad_inches)
    fig.savefig(out_base.with_suffix(".pdf"),
                bbox_inches="tight", pad_inches=pad_inches)
