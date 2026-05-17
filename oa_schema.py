"""
oa_schema.py
============
Canonical carbonate-chemistry schema, alias resolution, value normalisers,
and duplicate-key selection.

Why this is its own module
--------------------------
Stages 1A, 1B, 2, 3, 4 all touch the same canonical columns and the same
"how do we find `salinity` when the workbook calls it `sal`?" problem.
Putting the schema and the alias resolver in one importable file means:

1. A new alias for `nitrate_nitrite_umol_l` is a one-line edit in one
   place, not a hunt through five notebooks.
2. The same canonical names are used downstream by definition. (In the
   original monolithic notebook, the schema was redefined per stage with
   different orderings -- exactly the divergence the audit picked up.)

This is the **canonical data model** pattern from enterprise integration:
one schema, many sources, mappings recorded explicitly. The Avro
specification calls these mappings "aliases" and treats them as the
correct way to handle renames without breaking history (`Schema
Resolution and Aliases`, Avro spec).

What lives here
---------------
- `DEFAULT_CONFIG`               : default schema + ranges + duplicate keys
- `load_config(path)`            : load + merge a JSON/YAML override
- Normalisers: `normalize_ta_units`, `normalize_ph_scale`
- Schema application:
    `build_canonical_action_map`, `apply_canonical_schema`,
    `add_canonical_presence_flags`,
    `build_canonical_inventory`, `build_canonical_export`,
    `build_numeric_candidates_for_canonical`
- Duplicate-key helpers: `choose_duplicate_keys`, `add_duplicate_flags`

What does NOT live here
-----------------------
- Range bounds (`RangePolicy`) -> `oa_policy.py`
- TA/pH QC math               -> `oa_qc_ta_ph.py`
- Output-folder inspection    -> `oa_inspect.py`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dep
    yaml = None  # type: ignore

from oa_common import deep_update, die, first_existing

__all__ = [
    "DEFAULT_CONFIG",
    "load_config",
    "normalize_ta_units",
    "normalize_ph_scale",
    "normalize_carbonate_unit",
    "build_canonical_action_map",
    "apply_canonical_schema",
    "add_canonical_presence_flags",
    "build_canonical_inventory",
    "build_canonical_export",
    "build_numeric_candidates_for_canonical",
    "choose_duplicate_keys",
    "add_duplicate_flags",
]


# ===========================================================================
# DEFAULT_CONFIG
# ===========================================================================
# This is the canonical schema for the OA pipeline. Three concerns are
# nested under it:
#   * range_policy             -> consumed by oa_policy.RangePolicy
#   * canonical_candidates     -> canonical_name -> [aliases in priority order]
#   * required_columns         -> trigger flag_required_core_missing
#   * canonical_export_order   -> output column order for analysis_ready.csv
#   * provenance_defaults      -> values filled in if absent
#   * duplicate_key_candidates -> tried in order; first set with all
#                                 columns present wins
#
# A user supplies a YAML/JSON that overrides any of these via deep_update.
DEFAULT_CONFIG: Dict[str, Any] = {
    "range_policy": {
        "sal_min": 0.0,   "sal_max": 42.0,
        "ta_min": 1000.0, "ta_max": 3000.0,
        "ph_min": 7.0,    "ph_max": 9.0,
        "depth_min": 0.0, "depth_max": 12000.0,
        "lat_min": -90.0, "lat_max": 90.0,
        "lon_min": -180.0, "lon_max": 180.0,
    },
    "canonical_candidates": {
        "record_id": ["record_id", "sample_tag"],
        "sample_id": ["sample_id"],
        "cruise_id": ["cruise_id", "Cruise", "cruise"],
        "transect_id": ["transect_id", "Transect", "transect"],
        "station_id": ["station_id", "Station", "station"],
        "depth_m": ["depth_m", "Depth", "depth"],
        "sample_type": ["sample_type", "crm_or_sample"],
        "collection_mode": ["collection_mode", "mode_of_collection"],
        "replicate_id": ["replicate_id", "replicate"],
        "sample_date": ["sample_date"],
        "temperature_measurement_c": [
            "temperature_measurement_c", "temp_measurement_c",
            "temp_lab", "temperature_lab_c",
        ],
        "temperature_insitu_c": [
            "temperature_insitu_c", "temperature_output_c", "temp_output_c",
            "temp_insitu", "temperature_insitu",
        ],
        "salinity": ["salinity", "sal"],
        "oxygen_umol_l": ["oxygen_umol_l", "o2_umol/L", "o2_umol_l", "oxygen"],
        "nitrate_nitrite_umol_l": [
            "nitrate_nitrite_umol_l", "no3_no2 uM/L",
            "no3_no2_umol_l", "nitrate_nitrite",
        ],
        "phosphate_umol_l": [
            "phosphate_umol_l", "po4 uM/L", "po4_umol_l", "phosphate",
        ],
        "silicate_umol_l": [
            "silicate_umol_l", "sio3 uM/L", "sio3_umol_l", "silicate",
        ],
        "chlorophyll": ["chlorophyll", "chl", "chla", "chlor_a"],
        # NB: 'lattitude' (misspelling) listed here so the alias resolver
        # catches it -- no separate fix_lattitude flag needed.
        "latitude_deg": ["latitude_deg", "latitude", "lattitude", "lat"],
        "longitude_deg": ["longitude_deg", "longitude", "lon", "long"],
        "ta_umol_kg": [
            "ta_umol_kg", "ta_corrected_umolkg", "ta_corrected", "ta", "TA",
        ],
        "ph_observed": [
            "ph_observed", "ph_corrected_from_phstd", "pH_corrected_from_std",
            "pH_lab", "ph_lab", "pH", "ph",
        ],
        "ph_calculated": ["ph_calculated", "pH_calc", "ph_calc"],
        "dic_calculated_umol_kg": ["dic_calculated_umol_kg", "dic_calc"],
        "pco2_calc_uatm": ["pco2_calc_uatm", "pco2"],
        "co2aq_calc_umol_kg": ["co2aq_calc_umol_kg", "co2"],
        "hco3_calc_umol_kg": ["hco3_calc_umol_kg", "hco3-"],
        "co3_calc_umol_kg": ["co3_calc_umol_kg", "co3-"],
        "omega_calcite_calc": ["omega_calcite_calc", "omega_ca"],
        "omega_aragonite_calc": ["omega_aragonite_calc", "omega_ar"],
        "revelle_factor_calc": ["revelle_factor_calc", "revelle_factor"],
        "comment_ph": ["comment_ph", "comments_ph"],
        "ph_scale_observed": [
            "ph_scale_observed", "pH_scale_observed", "ph_scale", "pH_scale",
        ],
        "ph_scale_calculated": [
            "ph_scale_calculated", "pH_scale_calc",
            "ph_calc_scale", "pH_calc_scale",
        ],
        "pressure_measurement_dbar": [
            "pressure_measurement_dbar", "pressure_lab_dbar",
            "sample_pressure_dbar",
        ],
        "pressure_output_dbar": [
            "pressure_output_dbar", "pressure_insitu_dbar",
            "pressure_calc_dbar",
        ],
        "ta_units": [
            "ta_units", "ta_unit", "TA_unit", "TA_units",
            "ta_corrected_unit", "ta_corrected_units",
        ],
        "ta_qc_status": ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status": ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status": ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    "duplicate_key_candidates": [
        ["sample_id", "replicate_id", "sample_date", "station_id"],
        ["record_id", "replicate_id", "sample_date", "station_id"],
        ["sample_id", "sample_date", "station_id", "depth_m"],
        ["record_id", "sample_date", "station_id", "depth_m"],
        ["sample_id", "sample_date"],
        ["record_id", "sample_date"],
        ["sample_id"],
        ["record_id"],
    ],
    "required_columns": [
        "record_id", "sample_id", "sample_date",
        "cruise_id", "transect_id", "station_id",
        "depth_m", "latitude_deg", "longitude_deg",
        "temperature_insitu_c", "salinity",
        "ta_umol_kg", "ph_observed",
    ],
    "canonical_export_order": [
        "record_id", "sample_id", "cruise_id", "transect_id", "station_id",
        "depth_m", "sample_type", "collection_mode", "replicate_id", "sample_date",
        "latitude_deg", "longitude_deg",
        "temperature_measurement_c", "temperature_insitu_c",
        "pressure_measurement_dbar", "pressure_output_dbar",
        "salinity",
        "oxygen_umol_l", "nitrate_nitrite_umol_l", "phosphate_umol_l",
        "silicate_umol_l", "chlorophyll",
        "ta_umol_kg", "ta_units", "ta_qc_status",
        "ph_observed", "ph_scale_observed", "ph_qc_status", "phstd_status",
        "ph_calculated", "ph_scale_calculated",
        "dic_calculated_umol_kg", "pco2_calc_uatm",
        "co2aq_calc_umol_kg", "hco3_calc_umol_kg", "co3_calc_umol_kg",
        "omega_calcite_calc", "omega_aragonite_calc", "revelle_factor_calc",
        "comment_ph",
        "carbonate_solver", "carbon_input_pair_used",
        "preferred_ta_for_analysis", "preferred_ph_for_analysis",
        "preferred_pco2_for_analysis", "preferred_dic_for_analysis",
        "ta_umol_kg_role", "ph_observed_role", "ph_calculated_role",
        "dic_calculated_umol_kg_role", "pco2_calc_uatm_role",
        "oxygen_umol_l_role", "nitrate_nitrite_umol_l_role",
        "phosphate_umol_l_role", "silicate_umol_l_role", "chlorophyll_role",
        "source_file", "stage1a_processed_utc",
        "flag_possible_duplicate",
        "flag_lat_out_of_range", "flag_lon_out_of_range",
        "flag_sal_out_of_range", "flag_depth_out_of_range",
        "flag_ta_out_of_range",
        "flag_ph_observed_out_of_range", "flag_ph_calculated_out_of_range",
        "flag_required_core_missing",
        "flag_ta_units_missing", "flag_ta_units_unexpected",
        "flag_ph_scale_observed_missing",
        "flag_pressure_output_dbar_missing",
    ],
    "provenance_defaults": {
        "carbonate_solver": "PyCO2SYS",
        "carbon_input_pair_used": "TA + pH_observed",
        "preferred_ta_for_analysis": "ta_umol_kg",
        "preferred_ph_for_analysis": "ph_observed",
        "preferred_pco2_for_analysis": "pco2_calc_uatm",
        "preferred_dic_for_analysis": "dic_calculated_umol_kg",
    },
}


# ===========================================================================
# Config loading (JSON / YAML, deep-merged onto DEFAULT_CONFIG)
# ===========================================================================

def load_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Load a config override file and deep-merge onto DEFAULT_CONFIG.

    Returns `(merged_config, resolved_path_or_None)`. Passing None returns
    DEFAULT_CONFIG unchanged. YAML is supported only if `pyyaml` is
    installed; otherwise we fail clearly via `die(...)`.
    """
    if not config_path:
        return DEFAULT_CONFIG, None

    p = Path(config_path).expanduser().resolve()
    if not p.exists():
        die(f"Config file not found: {p}")

    suffix = p.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        if yaml is None:
            die("YAML config requested but PyYAML is not installed. "
                "Install with: pip install pyyaml")
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    elif suffix == ".json":
        loaded = json.loads(p.read_text(encoding="utf-8"))
    else:
        die("Config file must be .json, .yml, or .yaml")
        return DEFAULT_CONFIG, None  # unreachable, satisfies type-checker

    if not isinstance(loaded, dict):
        die("Config file must parse to a dictionary")
        return DEFAULT_CONFIG, None  # unreachable

    return deep_update(DEFAULT_CONFIG, loaded), str(p)


# ===========================================================================
# Value normalisers
# ===========================================================================
# Aliases for *unit strings* and *pH scale labels*. Lab spreadsheets vary
# wildly in how they write these ("umol/kg", "umolkg-1", "uMol Kg^-1");
# we map all known surface forms to a single canonical string so downstream
# range / completeness flags can compare deterministically.

def normalize_ta_units(value: Any) -> Any:
    """Canonicalise a TA unit string to ``"umol kg-1"`` (or pass through).

    Folds the three Unicode "micro" variants to ASCII "U" *before*
    uppercasing, because Python's ``str.upper()`` turns the micro sign
    (U+00B5) into Greek capital mu (U+039C), not back to a Latin letter
    — which used to silently bypass the mapping table for inputs like
    ``"µmol/kg"``. See tests/test_schema.py:test_normalize_ta_units.
    """
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    # Fold every "micro" variant to ASCII U before any case folding.
    text = (
        text
        .replace("\u00b5", "U")   # micro sign U+00B5
        .replace("\u03bc", "U")   # Greek lowercase mu U+03BC
        .replace("\u039c", "U")   # Greek capital mu U+039C
    )
    text = text.upper().replace("MICROMOL", "UMOL").replace(" ", "")
    mapping = {
        "UMOL/KG":   "umol kg-1",
        "UMOLKG":    "umol kg-1",
        "UMOLKG-1":  "umol kg-1",
        "UMOLKG^-1": "umol kg-1",
    }
    return mapping.get(text, str(value).strip())


def normalize_ph_scale(value: Any) -> Any:
    """Canonicalise a pH-scale label to total/free/seawater/nbs."""
    if pd.isna(value):
        return pd.NA
    text = str(value).strip().lower()
    mapping = {
        "total": "total", "tot": "total", "t": "total",
        "free": "free", "f": "free",
        "seawater": "seawater", "sws": "seawater", "sw": "seawater",
        "nbs": "nbs",
    }
    return mapping.get(text, str(value).strip())


def normalize_carbonate_unit(value: Any) -> Any:
    """Whitespace-stripped, uppercased view of a carbonate species unit.

    Returns NA for NA / empty inputs; otherwise an uppercase string with
    spaces removed and the micro sign (U+00B5) / Greek mu (U+03BC) /
    Greek capital mu (U+039C) all folded to ASCII "U" (so "umol/kg",
    "µmol/kg", and "μmol/kg" all become "UMOL/KG").

    Used by Stage 3 to compare the units of DIC, CO2aq, HCO3, and CO3
    species and surface mismatches. Unlike `normalize_ta_units`, this
    function does NOT map to a fixed canonical form like "umol kg-1";
    it just normalises typographical variation so equality comparisons
    are reliable. The caller decides whether to insist on a specific
    string.
    """
    if pd.isna(value):
        return pd.NA
    text = (
        str(value).strip().upper()
        .replace(" ", "")
        .replace("\u00b5", "U")   # micro sign
        .replace("\u03bc", "U")   # Greek lowercase mu
        .replace("\u039c", "U")   # Greek capital mu
    )
    return text if text else pd.NA


# ===========================================================================
# Schema application
# ===========================================================================

def build_canonical_action_map(
    df: pd.DataFrame,
    config: Dict[str, Any],
    preserve_original_columns: bool = True,
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    """Decide, per canonical column, whether to keep / copy / rename.

    Returns `(actions, source_lookup)` where:
      - `actions` is one row per canonical column resolved -- each row is
        `{canonical_column, source_column, action}` and `action` is one of
        `"already_present"`, `"copied"`, `"renamed"`.
      - `source_lookup` maps canonical_name -> source_name.

    This separation (decide first, mutate later) makes the rename audit
    log trivially generatable and lets callers see what *would* happen
    before applying it.
    """
    actions: List[Dict[str, str]] = []
    source_lookup: Dict[str, str] = {}

    for canonical, candidates in config.get("canonical_candidates", {}).items():
        found = first_existing(df, candidates)
        if found is None:
            continue

        if canonical in df.columns:
            source_lookup[canonical] = canonical
            actions.append({
                "canonical_column": canonical,
                "source_column": canonical,
                "action": "already_present",
            })
            continue

        source_lookup[canonical] = found
        actions.append({
            "canonical_column": canonical,
            "source_column": found,
            "action": "copied" if preserve_original_columns else "renamed",
        })

    return actions, source_lookup


def apply_canonical_schema(
    df: pd.DataFrame,
    config: Dict[str, Any],
    preserve_original_columns: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    """Resolve aliases, normalise units/scales, fill provenance defaults.

    Returns `(new_df, audit_df, source_lookup)` where `audit_df` is the
    DataFrame form of the `actions` list (use it to write the rename
    audit CSV).

    `preserve_original_columns=True` (the default) copies values into
    canonical columns and keeps the original names around -- useful while
    you are still iterating and want to compare. `False` renames in place,
    deleting the originals.

    Side effects on the returned frame:
      - canonical columns are created (NA if no alias resolved)
      - `ta_units`, `ph_scale_observed`, `ph_scale_calculated` are normalised
      - provenance default columns are added/filled
      - per-variable `<name>_role` columns are added ("measured" or
        "derived", or NA if the value column is empty)
    """
    out = df.copy()
    actions, source_lookup = build_canonical_action_map(
        out, config=config, preserve_original_columns=preserve_original_columns
    )

    rename_map: Dict[str, str] = {}
    for row in actions:
        canonical = row["canonical_column"]
        source = row["source_column"]
        action = row["action"]

        if action == "already_present":
            continue

        if preserve_original_columns:
            out[canonical] = out[source]
        else:
            rename_map[source] = canonical

    if rename_map:
        out = out.rename(columns=rename_map)

    # Ensure every canonical column exists (NA where unresolved).
    for canonical in config.get("canonical_candidates", {}).keys():
        if canonical not in out.columns:
            out[canonical] = pd.NA

    # Value-level normalisation.
    if "ta_units" in out.columns:
        out["ta_units"] = out["ta_units"].map(normalize_ta_units)
    if "ph_scale_observed" in out.columns:
        out["ph_scale_observed"] = out["ph_scale_observed"].map(normalize_ph_scale)
    if "ph_scale_calculated" in out.columns:
        out["ph_scale_calculated"] = out["ph_scale_calculated"].map(normalize_ph_scale)

    # Provenance defaults: only fill if missing/null.
    for col, default_value in config.get("provenance_defaults", {}).items():
        if col not in out.columns:
            out[col] = default_value
        else:
            out[col] = out[col].fillna(default_value)

    # Per-variable role flags ("measured" vs "derived").
    role_defaults = {
        "ta_umol_kg_role": ("ta_umol_kg", "measured"),
        "ph_observed_role": ("ph_observed", "measured"),
        "ph_calculated_role": ("ph_calculated", "derived"),
        "dic_calculated_umol_kg_role": ("dic_calculated_umol_kg", "derived"),
        "pco2_calc_uatm_role": ("pco2_calc_uatm", "derived"),
        "oxygen_umol_l_role": ("oxygen_umol_l", "measured"),
        "nitrate_nitrite_umol_l_role": ("nitrate_nitrite_umol_l", "measured"),
        "phosphate_umol_l_role": ("phosphate_umol_l", "measured"),
        "silicate_umol_l_role": ("silicate_umol_l", "measured"),
        "chlorophyll_role": ("chlorophyll", "measured"),
    }
    for role_col, (value_col, role_value) in role_defaults.items():
        if value_col in out.columns and out[value_col].notna().any():
            out[role_col] = role_value
        else:
            out[role_col] = pd.NA

    audit_df = pd.DataFrame(actions)
    return out, audit_df, source_lookup


# ===========================================================================
# Presence / inventory / export helpers
# ===========================================================================

def build_numeric_candidates_for_canonical() -> List[str]:
    """Canonical column names that should be coerced to numeric.

    Kept as a function rather than a constant so tests can override it,
    and so the list reads top-to-bottom alongside the schema.
    """
    return [
        "depth_m",
        "temperature_measurement_c", "temperature_insitu_c",
        "pressure_measurement_dbar", "pressure_output_dbar",
        "salinity",
        "oxygen_umol_l",
        "nitrate_nitrite_umol_l", "phosphate_umol_l", "silicate_umol_l",
        "chlorophyll",
        "latitude_deg", "longitude_deg",
        "ta_umol_kg",
        "ph_observed", "ph_calculated",
        "dic_calculated_umol_kg", "pco2_calc_uatm",
        "co2aq_calc_umol_kg", "hco3_calc_umol_kg", "co3_calc_umol_kg",
        "omega_calcite_calc", "omega_aragonite_calc",
        "revelle_factor_calc",
    ]


def add_canonical_presence_flags(df: pd.DataFrame, config: Dict[str, Any]) -> None:
    """In-place: add `flag_required_core_missing`, `flag_ta_units_*`, etc.

    A row triggers `flag_required_core_missing` if *any* of the
    `required_columns` is NA for that row. This is intentionally strict:
    a downstream consumer can always loosen it; reconstructing it after
    the fact requires re-reading the original frame.
    """
    required_cols = config.get("required_columns", [])
    missing_any = pd.Series(False, index=df.index)

    for col in required_cols:
        if col in df.columns:
            missing_any = missing_any | df[col].isna()
        else:
            missing_any = missing_any | pd.Series(True, index=df.index)

    df["flag_required_core_missing"] = missing_any.astype("boolean")

    if "ta_units" in df.columns:
        df["flag_ta_units_missing"] = df["ta_units"].isna().astype("boolean")
        df["flag_ta_units_unexpected"] = (
            df["ta_units"].notna() & (df["ta_units"] != "umol kg-1")
        ).astype("boolean")
    else:
        df["flag_ta_units_missing"] = pd.Series(True, index=df.index, dtype="boolean")
        df["flag_ta_units_unexpected"] = pd.Series(pd.NA, index=df.index, dtype="boolean")

    if "ph_scale_observed" in df.columns:
        df["flag_ph_scale_observed_missing"] = df["ph_scale_observed"].isna().astype("boolean")
    else:
        df["flag_ph_scale_observed_missing"] = pd.Series(True, index=df.index, dtype="boolean")

    if "pressure_output_dbar" in df.columns:
        df["flag_pressure_output_dbar_missing"] = df["pressure_output_dbar"].isna().astype("boolean")
    else:
        df["flag_pressure_output_dbar_missing"] = pd.Series(True, index=df.index, dtype="boolean")


def build_canonical_inventory(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """One row per canonical column: present / non_missing / pct_missing.

    Useful as a quick "did the schema get resolved?" view.
    """
    rows = []
    for col in config.get("canonical_export_order", []):
        if col in df.columns:
            n_present = int(df[col].notna().sum())
            n_total = len(df)
            pct_missing = round((n_total - n_present) / n_total * 100.0, 2) if n_total else 100.0
            rows.append({
                "column": col, "present": True,
                "non_missing": n_present, "pct_missing": pct_missing,
            })
        else:
            rows.append({
                "column": col, "present": False,
                "non_missing": 0, "pct_missing": 100.0,
            })
    return pd.DataFrame(rows)


def build_canonical_export(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Return a copy with columns ordered per `canonical_export_order`.

    Columns not in the list go to the right end, in original order, so
    nothing is lost.
    """
    ordered = [c for c in config.get("canonical_export_order", []) if c in df.columns]
    remaining = [c for c in df.columns if c not in ordered]
    return df[ordered + remaining].copy()


# ===========================================================================
# Duplicate-key chooser
# ===========================================================================

def choose_duplicate_keys(
    df: pd.DataFrame,
    config: Dict[str, Any],
    override_keys: Optional[List[str]] = None,
) -> List[str]:
    """Pick a duplicate-key tuple from `config['duplicate_key_candidates']`.

    Tries candidate sets in order; returns the first one where every
    column exists *and* has at least one non-NA value in `df`. If
    `override_keys` is supplied, those win (filtered to columns that
    exist). Empty list = no usable key.

    The "has at least one non-NA value" check is important: `apply_canonical_schema`
    creates every canonical column with NA fills if no alias resolved.
    Without this check, a frame that only has `sample_tag` would still
    "pass" the `[sample_id, replicate_id, ...]` candidate (because every
    column technically exists, all NA) -- and `df.duplicated` then flags
    every row, because all-NA tuples compare equal.
    """
    if override_keys:
        return [k for k in override_keys if k in df.columns]
    for candidate_set in config.get("duplicate_key_candidates", []):
        usable = all(
            (c in df.columns) and df[c].notna().any()
            for c in candidate_set
        )
        if usable:
            return candidate_set
    return []


def add_duplicate_flags(df: pd.DataFrame, dup_keys: List[str]) -> int:
    """In-place: add `flag_possible_duplicate` (True for any row in a group).

    Returns the number of rows flagged. `keep=False` in `df.duplicated`
    means *all* members of a duplicate group are flagged, not just the
    "extras" -- which is what we want for an audit (the analyst should
    look at all of them before deciding which to keep).
    """
    if not dup_keys:
        df["flag_possible_duplicate"] = pd.Series(False, index=df.index, dtype="boolean")
        return 0
    dup_mask = df.duplicated(subset=dup_keys, keep=False)
    df["flag_possible_duplicate"] = dup_mask.astype("boolean")
    return int(dup_mask.sum())
