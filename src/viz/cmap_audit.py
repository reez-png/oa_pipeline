# src/viz/cmap_audit.py
from __future__ import annotations
import re, io, sys
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

# Optional: simulate color-vision deficiency (CVD) previews if available
try:
    from colorspacious import cspace_converter
    HAVE_CSP = True
except Exception:
    HAVE_CSP = False

# ---------------------------- policy ----------------------------
# “Approved” defaults: perceptually-uniform, colorblind-aware for scalar fields
APPROVED_SEQUENTIAL = [
    "viridis", "plasma", "magma", "cividis",
    # CMOcean (if installed in your workflows)
    "cmo.thermal", "cmo.haline", "cmo.solar", "cmo.ice", "cmo.gray",
    "cmo.oxy", "cmo.deep", "cmo.dense"
]
APPROVED_DIVERGING = [
    "coolwarm", "PiYG", "PRGn", "BrBG", "PuOr", "RdBu", "RdGy", "RdYlBu", "RdYlGn"
]
APPROVED_QUAL = [
    # qualitative (categorical)—use sparingly
    "tab10", "tab20", "Set2", "Accent", "Dark2"
]
APPROVED = set(APPROVED_SEQUENTIAL + APPROVED_DIVERGING + APPROVED_QUAL)

# “Banned” or discouraged due to non-uniform luminance / hue jumps
BANNED = {
    "jet", "rainbow", "gist_rainbow", "nipy_spectral", "hsv",
    "gist_ncar", "spectral"  # legacy names often equivalent to rainbow-like
}

# Heuristic map → recommended replacement
REPLACEMENTS = {
    "jet": "viridis",
    "rainbow": "viridis",
    "gist_rainbow": "viridis",
    "nipy_spectral": "viridis",
    "hsv": "plasma",
    "spectral": "viridis",
    "gist_ncar": "viridis",
}

# ------------------------- repo code scan ------------------------
_CMAP_PATTERNS = [
    r"cmap\s*=\s*['\"]([\w\.\-]+)['\"]",      # matplotlib/seaborn kwarg
    r"plt\.colormaps\[['\"]([\w\.\-]+)['\"]\]",# Matplotlib 3.6+ registry access
    r"cm\.get_cmap\(\s*['\"]([\w\.\-]+)['\"]", # matplotlib.cm.get_cmap("name")
    r"sns\.\w+map\(\s*['\"]([\w\.\-]+)['\"]",  # seaborn set_palette("...")
]
PALETTE_PATTERNS = [
    r"palette\s*=\s*['\"]([\w\.\-]+)['\"]",
]

def _scan_text(text: str, relpath: str) -> List[Dict]:
    rows = []
    for pat in _CMAP_PATTERNS + PALETTE_PATTERNS:
        for m in re.finditer(pat, text):
            name = m.group(1)
            rows.append({"file": relpath, "match": name, "kind": "palette" if "palette" in pat else "cmap"})
    return rows

def scan_repo_for_colormaps(root: Path, exts=(".py", ".ipynb")) -> pd.DataFrame:
    """Static scan of source for colormap/palette strings."""
    rows = []
    for p in root.rglob("*"):
        if p.suffix.lower() not in exts:
            continue
        try:
            if p.suffix.lower() == ".ipynb":
                # light-weight parse to avoid nbformat dependency
                txt = p.read_text(encoding="utf-8", errors="ignore")
            else:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            rows += _scan_text(txt, str(p.relative_to(root)))
        except Exception:
            continue
    df = pd.DataFrame(rows).drop_duplicates()
    if df.empty:
        return df
    df["risk"] = df["match"].apply(lambda n: "banned" if n in BANNED else ("approved" if n in APPROVED else "check"))
    df["suggested"] = df["match"].map(REPLACEMENTS)
    return df.sort_values(["risk","file","match"]).reset_index(drop=True)

# --------------------- runtime logging (optional) ---------------------
@dataclass
class CmapEvent:
    name: str
    resolved_name: str
    module: str
    callsite: str

class CmapLogger:
    """Monkey-patch matplotlib.cm.get_cmap & plt.get_cmap to record usage at runtime."""
    def __init__(self):
        self.events: List[CmapEvent] = []
        self._orig_cm = matplotlib.cm.get_cmap
        self._orig_plt = getattr(plt, "get_cmap", None)

    def _wrap(self, func, module_name):
        def _inner(name=None, *a, **k):
            res = func(name, *a, **k)
            nm = getattr(res, "name", str(name))
            frame = sys._getframe(2)
            callsite = f"{frame.f_code.co_filename}:{frame.f_lineno}"
            self.events.append(CmapEvent(name=str(name), resolved_name=str(nm),
                                         module=module_name, callsite=callsite))
            return res
        return _inner

    @contextmanager
    def context(self):
        matplotlib.cm.get_cmap = self._wrap(self._orig_cm, "matplotlib.cm")
        if self._orig_plt:
            plt.get_cmap = self._wrap(self._orig_plt, "matplotlib.pyplot")
        try:
            yield self
        finally:
            matplotlib.cm.get_cmap = self._orig_cm
            if self._orig_plt:
                plt.get_cmap = self._orig_plt

def events_to_df(events: List[CmapEvent], root: Path) -> pd.DataFrame:
    rows = []
    for e in events:
        risk = "banned" if e.resolved_name in BANNED else ("approved" if e.resolved_name in APPROVED else "check")
        rows.append({
            "when": "runtime",
            "cmap": e.resolved_name,
            "requested": e.name,
            "module": e.module,
            "callsite": str(Path(e.callsite).resolve()).replace(str(root), "."),
            "risk": risk,
            "suggested": REPLACEMENTS.get(e.resolved_name, "")
        })
    return pd.DataFrame(rows).drop_duplicates()

# --------------------- tiny swatches & CVD previews -------------------
def gradient_swatches(cmap_name: str, width=256, height=18) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Return (normal, deuteranopia, protanopia) gradient row images."""
    cm = plt.get_cmap(cmap_name)
    x = np.linspace(0, 1, width)
    grad = np.tile(x, (height, 1))
    img = cm(grad)[..., :3]  # RGB
    if not HAVE_CSP:
        return (img, None, None)
    # Convert to LMS, apply deficiency matrices, back to sRGB
    def sim(kind):
        # sRGB1 → LMS via colorspacious
        to_lms = cspace_converter("sRGB1", "LMS")
        to_rgb = cspace_converter("LMS", "sRGB1")
        lms = to_lms(img)
        if kind == "deuteranopia":
            M = np.array([[1, 0, 0], [0.494207, 0, 1.24827], [0, 0, 1]])
        else:  # protanopia
            M = np.array([[0, 2.02344, -2.52581], [0, 1, 0], [0, 0, 1]])
        sim_lms = lms @ M.T
        sim_rgb = np.clip(to_rgb(sim_lms), 0, 1)
        return sim_rgb
    return (img, sim("deuteranopia"), sim("protanopia"))

# --------------------- report & fixer utilities -----------------------
def build_report(static_df: pd.DataFrame, runtime_df: pd.DataFrame, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 1) CSVs
    if not static_df.empty: static_df.to_csv(out_dir / "colormap_static_scan.csv", index=False)
    if not runtime_df.empty: runtime_df.to_csv(out_dir / "colormap_runtime_log.csv", index=False)

    # 2) HTML with swatches
    html = io.StringIO()
    html.write("<h2>Colormap Audit</h2>")
    for label, df in [("Static scan", static_df), ("Runtime log", runtime_df)]:
        html.write(f"<h3>{label}</h3>")
        if df.empty:
            html.write("<p><i>No entries.</i></p>")
            continue
        # unique cmaps
        used = sorted(df["match" if "match" in df.columns else "cmap"].unique())
        html.write("<ul>")
        for nm in used:
            normal, deu, pro = gradient_swatches(nm)
            def _to_png(arr):
                if arr is None: return ""
                import base64
                from PIL import Image
                im = Image.fromarray((arr*255).astype(np.uint8))
                buf = io.BytesIO(); im.save(buf, format="PNG"); b64 = base64.b64encode(buf.getvalue()).decode()
                return f'<img src="data:image/png;base64,{b64}" style="border:1px solid #ccc;margin:2px">'
            html.write(f"<li><b>{nm}</b> — ")
            html.write(_to_png(normal))
            if deu is not None: html.write(" deuteranopia: " + _to_png(deu))
            if pro is not None: html.write(" protanopia: " + _to_png(pro))
            # risk label
            risk = "banned" if nm in BANNED else ("approved" if nm in APPROVED else "check")
            sug  = REPLACEMENTS.get(nm, "")
            html.write(f" &nbsp; <span style='background:#eee;padding:2px 5px;border-radius:3px'>{risk}</span>")
            if sug:
                html.write(f" &nbsp; suggest → <code>{sug}</code>")
            html.write("</li>")
        html.write("</ul>")
        # table dump
        html.write(df.to_html(index=False))
    path = out_dir / "colormap_audit.html"
    path.write_text(html.getvalue(), encoding="utf-8")
    return path

def make_rewrite_patch(static_df: pd.DataFrame, repo_root: Path, out_dir: Path, dry_run=True) -> Path:
    """
    Create a patch with substitutions (banned → replacement).
    If dry_run=False, also apply in place for .py files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = static_df.query("risk == 'banned'").copy()
    if targets.empty:
        patch = out_dir / "colormap_rewrite.patch"
        patch.write_text("# No banned colormaps found.\n", encoding="utf-8")
        return patch

    changes = []
    for _, r in targets.iterrows():
        fname = repo_root / r["file"]
        if not fname.exists() or fname.suffix != ".py":
            continue
        txt = fname.read_text(encoding="utf-8", errors="ignore")
        bad = r["match"]
        repl = REPLACEMENTS.get(bad, "viridis")
        new = re.sub(rf"(['\"])({bad})(['\"])", rf"'\g<2>'".replace(bad, repl), txt)
        if new != txt:
            changes.append((fname, txt, new))
            if not dry_run:
                fname.write_text(new, encoding="utf-8")
    # write a simple diff-like patch
    buf = io.StringIO()
    for f, old, new in changes:
        buf.write(f"--- {f}\n+++ {f}\n@@\n")
        buf.write(old)
        buf.write("\n@@\n")
        buf.write(new)
        buf.write("\n\n")
    patch = out_dir / "colormap_rewrite.patch"
    patch.write_text(buf.getvalue(), encoding="utf-8")
    return patch
