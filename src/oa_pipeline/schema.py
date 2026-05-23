"""
schema.py
=========
Canonical carbonate chemistry schema, alias resolution, value normalisers,
and duplicate key selection for the OA pipeline.

Import as:

    from oa_pipeline.schema import ...

This module defines the canonical data model used by Stage 1A onward. Its main
job is to map variable names from messy Excel or CSV inputs into stable,
auditable canonical column names.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .common import die, first_existing, load_config as load_generic_config

__all__ = [
    "DEFAULT_CONFIG",
    "load_schema_config",
    "load_config",
    "normalize_ta_units",
    "normalize_ph_scale",
    "normalize_carbonate_unit",
    "coalesce_aliases_for_canonical",
    "build_canonical_action_map",
    "apply_canonical_schema",
    "add_canonical_presence_flags",
    "build_canonical_inventory",
    "build_canonical_export",
    "build_numeric_candidates_for_canonical",
    "choose_duplicate_keys",
    "add_duplicate_flags",
]


# =============================================================================
# DEFAULT_CONFIG
# =============================================================================

DEFAULT_CONFIG: Dict[str, Any] = {
    "range_policy": {
        "sal_min": 0.0,
        "sal_max": 42.0,
        "ta_min": 1000.0,
        "ta_max": 3000.0,
        "ph_min": 7.0,
        "ph_max": 9.0,
        "depth_min": 0.0,
        "depth_max": 12000.0,
        "lat_min": -90.0,
        "lat_max": 90.0,
        "lon_min": -180.0,
        "lon_max": 180.0,
    },
    "accepted_ph_scales": ["total"],
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
            "temperature_measurement_c",
            "temp_measurement_c",
            "temp_lab",
            "temperature_lab_c",
        ],
        "temperature_insitu_c": [
            "temperature_insitu_c",
            "temperature_output_c",
            "temp_output_c",
            "temp_insitu",
            "temperature_insitu",
        ],
        "salinity": ["salinity", "Salinity", "sal"],
        "oxygen_umol_l": [
            "oxygen_umol_l",
            "o2_umol/L",
            "o2_umol_l",
            "oxygen",
        ],
        "nitrate_nitrite_umol_l": [
            "nitrate_nitrite_umol_l",
            "no3_no2 uM/L",
            "no3_no2_umol_l",
            "nitrate_nitrite",
        ],
        "phosphate_umol_l": [
            "phosphate_umol_l",
            "po4 uM/L",
            "po4_umol_l",
            "phosphate",
        ],
        "silicate_umol_l": [
            "silicate_umol_l",
            "sio3 uM/L",
            "sio3_umol_l",
            "silicate",
        ],
        "nitrate_nitrite_umol_kg": [
            "nitrate_nitrite_umol_kg",
            "no3_no2_umol_kg",
            "nitrate_nitrite_umolkg",
        ],
        "phosphate_umol_kg": [
            "phosphate_umol_kg",
            "po4_umol_kg",
            "phosphate_umolkg",
        ],
        "silicate_umol_kg": [
            "silicate_umol_kg",
            "sio3_umol_kg",
            "silicate_umolkg",
        ],
        "chlorophyll": ["chlorophyll", "chl", "chla", "chlor_a"],
        "latitude_deg": ["latitude_deg", "latitude", "lattitude", "lat"],
        "longitude_deg": ["longitude_deg", "longitude", "lon", "long"],
        "ta_umol_kg": [
            "ta_umol_kg",
            "ta_umolkg",
            "ta_corrected_umolkg",
            "ta_corrected",
            "ta",
            "TA",
        ],
        "ph_observed": [
            "ph_observed",
            "ph_corrected_from_phstd",
            "pH_corrected_from_std",
            "pH_lab",
            "ph_lab",
            "pH",
            "ph",
        ],
        "ph_calculated": ["ph_calculated", "pH_calc", "ph_calc"],
        "dic_calculated_umol_kg": [
            "dic_calculated_umol_kg",
            "dic_measured_umol_kg",
            "dic_umol_kg",
            "dic_umolkg",
            "dic_calc",
            "DIC",
            "dic",
        ],
        "pco2_calc_uatm": [
            "pco2_calc_uatm",
            "pco2_uatm",
            "pCO2",
            "pco2",
        ],
        "co2aq_calc_umol_kg": [
            "co2aq_calc_umol_kg",
            "co2aq_umol_kg",
            "co2aq_umolkg",
            "co2_aq_umol_kg",
            "aqueous_co2_umol_kg",
        ],
        "hco3_calc_umol_kg": [
            "hco3_calc_umol_kg",
            "hco3_umol_kg",
            "hco3_umolkg",
            "bicarbonate_umol_kg",
        ],
        "co3_calc_umol_kg": [
            "co3_calc_umol_kg",
            "co3_umol_kg",
            "co3_umolkg",
            "carbonate_umol_kg",
        ],
        "omega_calcite_calc": ["omega_calcite_calc", "omega_ca"],
        "omega_aragonite_calc": ["omega_aragonite_calc", "omega_ar"],
        "revelle_factor_calc": ["revelle_factor_calc", "revelle_factor"],
        "comment_ph": ["comment_ph", "comments_ph"],
        "ph_scale_observed": [
            "ph_scale_observed",
            "pH_scale_observed",
            "ph_scale",
            "pH_scale",
        ],
        "ph_scale_calculated": [
            "ph_scale_calculated",
            "pH_scale_calc",
            "ph_calc_scale",
            "pH_calc_scale",
        ],
        "pressure_measurement_dbar": [
            "pressure_measurement_dbar",
            "pressure_lab_dbar",
            "sample_pressure_dbar",
        ],
        "pressure_output_dbar": [
            "pressure_output_dbar",
            "pressure_insitu_dbar",
            "pressure_calc_dbar",
        ],
        "ta_units": [
            "ta_units",
            "ta_unit",
            "TA_unit",
            "TA_units",
            "ta_corrected_unit",
            "ta_corrected_units",
        ],
        "ta_qc_status": ["ta_qc_status", "TA_qc_status", "ta_status"],
        "ph_qc_status": ["ph_qc_status", "pH_qc_status", "ph_status"],
        "phstd_status": ["phstd_status", "pHstd_status", "ph_std_status"],
    },
    # Alias conflict checks are intentionally limited to groups of aliases that
    # should be true synonyms. Corrected values such as ph_corrected_from_phstd
    # and ta_corrected_umolkg are not placed in these groups because they can
    # legitimately differ from raw measured values.
    "conflict_check_alias_groups": {
        "ph_observed": [
            ["ph_observed", "pH_lab", "ph_lab", "pH", "ph"],
        ],
        "ph_calculated": [
            ["ph_calculated", "pH_calc", "ph_calc"],
        ],
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
    "required_columns": {
        "identity": [
            "record_id",
            "sample_id",
            "sample_date",
        ],
        "station": [
            "cruise_id",
            "transect_id",
            "station_id",
            "depth_m",
            "latitude_deg",
            "longitude_deg",
        ],
        "hydrography": [
            "temperature_insitu_c",
            "salinity",
        ],
        "carbonate_minimum_for_ta_ph": [
            "ta_umol_kg",
            "ph_observed",
        ],
    },
    "canonical_export_order": [
        "record_id",
        "sample_id",
        "cruise_id",
        "transect_id",
        "station_id",
        "depth_m",
        "sample_type",
        "collection_mode",
        "replicate_id",
        "sample_date",
        "latitude_deg",
        "longitude_deg",
        "temperature_measurement_c",
        "temperature_insitu_c",
        "pressure_measurement_dbar",
        "pressure_output_dbar",
        "salinity",
        "oxygen_umol_l",
        "nitrate_nitrite_umol_l",
        "phosphate_umol_l",
        "silicate_umol_l",
        "nitrate_nitrite_umol_kg",
        "phosphate_umol_kg",
        "silicate_umol_kg",
        "chlorophyll",
        "ta_umol_kg",
        "ta_units",
        "ta_qc_status",
        "ph_observed",
        "ph_scale_observed",
        "ph_qc_status",
        "phstd_status",
        "ph_calculated",
        "ph_scale_calculated",
        "dic_calculated_umol_kg",
        "pco2_calc_uatm",
        "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg",
        "co3_calc_umol_kg",
        "omega_calcite_calc",
        "omega_aragonite_calc",
        "revelle_factor_calc",
        "comment_ph",
        "carbonate_solver",
        "carbon_input_pair_used",
        "preferred_ta_for_analysis",
        "preferred_ph_for_analysis",
        "preferred_pco2_for_analysis",
        "preferred_dic_for_analysis",
        "ta_umol_kg_role",
        "ph_observed_role",
        "ph_calculated_role",
        "dic_calculated_umol_kg_role",
        "pco2_calc_uatm_role",
        "oxygen_umol_l_role",
        "nitrate_nitrite_umol_l_role",
        "phosphate_umol_l_role",
        "silicate_umol_l_role",
        "nitrate_nitrite_umol_kg_role",
        "phosphate_umol_kg_role",
        "silicate_umol_kg_role",
        "chlorophyll_role",
        "source_file",
        "stage1a_processed_utc",
        "flag_possible_duplicate",
        "flag_duplicate_key_incomplete",
        "flag_lat_out_of_range",
        "flag_lon_out_of_range",
        "flag_sal_out_of_range",
        "flag_depth_out_of_range",
        "flag_ta_out_of_range",
        "flag_ph_observed_out_of_range",
        "flag_ph_calculated_out_of_range",
        "flag_identity_missing",
        "flag_station_metadata_missing",
        "flag_hydrography_missing",
        "flag_ta_ph_pair_missing",
        "flag_required_core_missing",
        "flag_ta_units_missing",
        "flag_ta_units_unexpected",
        "flag_ph_scale_observed_missing",
        "flag_ph_scale_observed_unexpected",
        "flag_pressure_output_dbar_missing",
    ],
    "provenance_defaults": {
        "carbonate_solver": pd.NA,
        "carbon_input_pair_used": pd.NA,
        "preferred_ta_for_analysis": "ta_umol_kg",
        "preferred_ph_for_analysis": "ph_observed",
        "preferred_pco2_for_analysis": "pco2_calc_uatm",
        "preferred_dic_for_analysis": "dic_calculated_umol_kg",
    },
}


# =============================================================================
# Config loading
# =============================================================================


def load_schema_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Load schema config override and deep merge it onto DEFAULT_CONFIG.

    Returns:
        (merged_config, resolved_path_or_None)
    """
    if config_path is None or str(config_path).strip().lower() in {"", "none", "null"}:
        return deepcopy(DEFAULT_CONFIG), None

    path = Path(str(config_path)).expanduser().resolve()
    merged = load_generic_config(path, default=DEFAULT_CONFIG)
    return merged, str(path)


# Backward compatibility for existing notebooks that import load_config.
load_config = load_schema_config


# =============================================================================
# Value normalisers
# =============================================================================


def normalize_ta_units(value: Any) -> Any:
    """Canonicalise a TA unit string to 'umol kg-1' where possible."""
    if pd.isna(value):
        return pd.NA

    original = str(value).strip()

    text = (
        original
        .replace("\u00b5", "U")
        .replace("\u03bc", "U")
        .replace("\u039c", "U")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("⁻", "-")
        .replace("¹", "1")
    )

    key = (
        text.upper()
        .replace("MICROMOL", "UMOL")
        .replace("MICRO MOL", "UMOL")
        .replace(" ", "")
        .replace("_", "")
        .replace(".", "")
    )

    key = key.replace("KGSW", "KG")
    key = key.replace("KG-SW", "KG")
    key = key.replace("KG-SEAWATER", "KG")
    key = key.replace("/KGSEAWATER", "/KG")

    accepted = {
        "UMOL/KG",
        "UMOLKG",
        "UMOLKG-1",
        "UMOLKG^-1",
        "UMOL/KG-1",
        "UMOL/KGSEAWATER",
        "UMOLKGSEAWATER",
    }

    if key in accepted:
        return "umol kg-1"

    return original


def normalize_ph_scale(value: Any) -> Any:
    """Canonicalise a pH scale label.

    Single letter labels such as "t" and "f" are intentionally not mapped
    because they can be ambiguous in laboratory spreadsheets.
    """
    if pd.isna(value):
        return pd.NA

    original = str(value).strip()
    text = original.lower().replace(" ", "")

    mapping = {
        "total": "total",
        "tot": "total",
        "totalscale": "total",
        "ph_total": "total",
        "phtotal": "total",
        "free": "free",
        "freescale": "free",
        "ph_free": "free",
        "phfree": "free",
        "seawater": "seawater",
        "seawaterscale": "seawater",
        "sws": "seawater",
        "ph_sws": "seawater",
        "phsws": "seawater",
        "nbs": "nbs",
        "ph_nbs": "nbs",
        "phnbs": "nbs",
    }

    return mapping.get(text, original)


def normalize_carbonate_unit(value: Any) -> Any:
    """Canonicalise carbonate species concentration units.

    Equivalent micromol per kg spellings are normalised to "umol kg-1" so
    DIC/species unit comparisons do not falsely fail because of micro symbols,
    spacing, slash notation, or minus sign variants.
    """
    if pd.isna(value):
        return pd.NA

    original = str(value).strip()

    text = (
        original
        .replace("\u00b5", "U")
        .replace("\u03bc", "U")
        .replace("\u039c", "U")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("⁻", "-")
        .replace("¹", "1")
    )

    key = (
        text.upper()
        .replace("MICROMOL", "UMOL")
        .replace("MICRO MOL", "UMOL")
        .replace(" ", "")
        .replace("_", "")
        .replace(".", "")
    )

    key = key.replace("KGSW", "KG")
    key = key.replace("KG-SW", "KG")
    key = key.replace("KG-SEAWATER", "KG")
    key = key.replace("/KGSEAWATER", "/KG")

    accepted = {
        "UMOL/KG",
        "UMOLKG",
        "UMOLKG-1",
        "UMOLKG^-1",
        "UMOL/KG-1",
        "UMOL/KGSEAWATER",
        "UMOLKGSEAWATER",
    }

    if key in accepted:
        return "umol kg-1"

    return original if original else pd.NA


# =============================================================================
# Schema application
# =============================================================================


def _series_has_value(s: pd.Series) -> pd.Series:
    """Return True where a Series has a non missing, non blank value."""
    if pd.api.types.is_string_dtype(s) or s.dtype == object:
        as_text = s.astype("string")
        return s.notna() & as_text.str.strip().ne("").fillna(False)
    return s.notna()


def _values_conflict(a: pd.Series, b: pd.Series) -> pd.Series:
    """Return True where two non missing alias values disagree.

    Numeric looking values are compared numerically so that 8.0 and 8.00 are
    treated as equivalent. Non numeric values are compared after stripping
    surrounding whitespace.
    """
    a_str = a.astype("string").str.strip()
    b_str = b.astype("string").str.strip()

    both_present = (
        a_str.notna()
        & b_str.notna()
        & a_str.ne("")
        & b_str.ne("")
    )

    a_num = pd.to_numeric(a_str, errors="coerce")
    b_num = pd.to_numeric(b_str, errors="coerce")
    both_numeric = a_num.notna() & b_num.notna()

    numeric_diff = (a_num - b_num).abs() > 1e-12
    text_diff = a_str.ne(b_str)

    return both_present & ((both_numeric & numeric_diff) | (~both_numeric & text_diff))


def _aliases_need_conflict_check(
    canonical: str,
    left: str,
    right: str,
    conflict_alias_groups: Optional[Dict[str, List[List[str]]]],
) -> bool:
    """Return True when two aliases belong to the same conflict check group."""
    if not conflict_alias_groups:
        return False

    groups = conflict_alias_groups.get(canonical, [])

    for group in groups:
        members = set(group)
        if left in members and right in members:
            return True

    return False


def _check_conflicting_aliases(
    df: pd.DataFrame,
    canonical: str,
    resolved: List[str],
    conflict_alias_groups: Optional[Dict[str, List[List[str]]]],
) -> None:
    """Fail if configured true synonym aliases contain conflicting values."""
    if len(resolved) <= 1:
        return

    for i, left in enumerate(resolved):
        for right in resolved[i + 1:]:
            if not _aliases_need_conflict_check(
                canonical=canonical,
                left=left,
                right=right,
                conflict_alias_groups=conflict_alias_groups,
            ):
                continue

            conflict = _values_conflict(df[left], df[right])

            if conflict.any():
                example_rows = conflict[conflict].index[:5].tolist()
                die(
                    f"Conflicting aliases for canonical column {canonical!r}: "
                    f"{left!r} and {right!r} both contain different values. "
                    f"Example row indexes: {example_rows}"
                )


def coalesce_aliases_for_canonical(
    df: pd.DataFrame,
    canonical: str,
    candidates: List[str],
    conflict_alias_groups: Optional[Dict[str, List[List[str]]]] = None,
) -> Tuple[pd.Series, pd.Series]:
    """Return best available value and source column for one canonical field.

    Values are coalesced row by row across all aliases in priority order. Empty
    canonical columns therefore do not block later aliases that contain data.
    Configured alias groups are checked before coalescing so true synonym
    columns with conflicting values cannot be silently resolved.
    """
    resolved: List[str] = []

    for candidate in candidates:
        found = first_existing(df, [candidate])
        if found is not None and found not in resolved:
            resolved.append(found)

    if canonical in df.columns and canonical not in resolved:
        resolved.insert(0, canonical)

    _check_conflicting_aliases(
        df=df,
        canonical=canonical,
        resolved=resolved,
        conflict_alias_groups=conflict_alias_groups,
    )

    if not resolved:
        return (
            pd.Series(pd.NA, index=df.index, dtype="object"),
            pd.Series(pd.NA, index=df.index, dtype="string"),
        )

    out = df[resolved[0]].copy()
    src = pd.Series(resolved[0], index=df.index, dtype="string")

    for col in resolved[1:]:
        take = ~_series_has_value(out) & _series_has_value(df[col])
        out = out.where(~take, df[col])
        src = src.where(~take, col)

    src = src.where(_series_has_value(out), pd.NA)
    return out, src


def build_canonical_action_map(
    df: pd.DataFrame,
    config: Dict[str, Any],
    preserve_original_columns: bool = True,
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    """Build an audit map describing how canonical columns will be sourced.

    Original columns are currently always preserved. The preserve_original_columns
    argument is retained for backward compatible call signatures.
    """
    del preserve_original_columns

    actions: List[Dict[str, str]] = []
    source_lookup: Dict[str, str] = {}
    conflict_alias_groups = config.get("conflict_check_alias_groups", {})

    for canonical, candidates in config.get("canonical_candidates", {}).items():
        _, best_source = coalesce_aliases_for_canonical(
            df,
            canonical=canonical,
            candidates=list(candidates),
            conflict_alias_groups=conflict_alias_groups,
        )

        non_missing_sources = best_source.dropna()
        unique_sources = sorted(set(str(x) for x in non_missing_sources))

        source_text = ";".join(unique_sources)
        action = (
            "created_missing"
            if len(unique_sources) == 0
            else "coalesced"
            if len(unique_sources) > 1
            else "copied"
        )

        source_lookup[canonical] = source_text
        actions.append(
            {
                "canonical_column": canonical,
                "source_column": source_text,
                "action": action,
            }
        )

    return actions, source_lookup


def apply_canonical_schema(
    df: pd.DataFrame,
    config: Dict[str, Any],
    preserve_original_columns: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    """Resolve aliases, normalise units and scales, and add provenance columns.

    Original columns are currently always preserved. The preserve_original_columns
    argument is retained for backward compatible call signatures.

    Returns:
        (new_df, audit_df, source_lookup)
    """
    del preserve_original_columns

    out = df.copy()
    actions: List[Dict[str, str]] = []
    source_lookup: Dict[str, str] = {}
    conflict_alias_groups = config.get("conflict_check_alias_groups", {})

    for canonical, candidates in config.get("canonical_candidates", {}).items():
        best_value, best_source = coalesce_aliases_for_canonical(
            out,
            canonical=canonical,
            candidates=list(candidates),
            conflict_alias_groups=conflict_alias_groups,
        )

        out[canonical] = best_value

        non_missing_sources = best_source.dropna()
        unique_sources = sorted(set(str(x) for x in non_missing_sources))
        source_text = ";".join(unique_sources)

        action = (
            "created_missing"
            if len(unique_sources) == 0
            else "coalesced"
            if len(unique_sources) > 1
            else "copied"
        )

        source_lookup[canonical] = source_text
        actions.append(
            {
                "canonical_column": canonical,
                "source_column": source_text,
                "action": action,
                "n_source_columns": str(len(unique_sources)),
            }
        )

    for canonical in config.get("canonical_candidates", {}).keys():
        if canonical not in out.columns:
            out[canonical] = pd.NA

    if "ta_units" in out.columns:
        out["ta_units"] = out["ta_units"].map(normalize_ta_units)

    if "ph_scale_observed" in out.columns:
        out["ph_scale_observed"] = out["ph_scale_observed"].map(normalize_ph_scale)

    if "ph_scale_calculated" in out.columns:
        out["ph_scale_calculated"] = out["ph_scale_calculated"].map(normalize_ph_scale)

    for col, default_value in config.get("provenance_defaults", {}).items():
        if col not in out.columns:
            out[col] = default_value
        else:
            out[col] = out[col].where(out[col].notna(), default_value)

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
        "nitrate_nitrite_umol_kg_role": ("nitrate_nitrite_umol_kg", "measured_or_converted"),
        "phosphate_umol_kg_role": ("phosphate_umol_kg", "measured_or_converted"),
        "silicate_umol_kg_role": ("silicate_umol_kg", "measured_or_converted"),
        "chlorophyll_role": ("chlorophyll", "measured"),
    }

    for role_col, (value_col, role_value) in role_defaults.items():
        out[role_col] = pd.Series(pd.NA, index=out.index, dtype="string")
        if value_col in out.columns:
            out.loc[_series_has_value(out[value_col]), role_col] = role_value

    audit_df = pd.DataFrame(actions)
    return out, audit_df, source_lookup


# =============================================================================
# Presence, inventory, and export helpers
# =============================================================================


def build_numeric_candidates_for_canonical() -> List[str]:
    """Return canonical columns that should usually be numeric."""
    return [
        "depth_m",
        "temperature_measurement_c",
        "temperature_insitu_c",
        "pressure_measurement_dbar",
        "pressure_output_dbar",
        "salinity",
        "oxygen_umol_l",
        "nitrate_nitrite_umol_l",
        "phosphate_umol_l",
        "silicate_umol_l",
        "nitrate_nitrite_umol_kg",
        "phosphate_umol_kg",
        "silicate_umol_kg",
        "chlorophyll",
        "latitude_deg",
        "longitude_deg",
        "ta_umol_kg",
        "ph_observed",
        "ph_calculated",
        "dic_calculated_umol_kg",
        "pco2_calc_uatm",
        "co2aq_calc_umol_kg",
        "hco3_calc_umol_kg",
        "co3_calc_umol_kg",
        "omega_calcite_calc",
        "omega_aragonite_calc",
        "revelle_factor_calc",
    ]


def _missing_any(df: pd.DataFrame, columns: List[str]) -> pd.Series:
    """Return True where any listed column is missing or absent."""
    missing = pd.Series(False, index=df.index)

    for col in columns:
        if col in df.columns:
            missing = missing | ~_series_has_value(df[col])
        else:
            missing = missing | pd.Series(True, index=df.index)

    return missing.astype("boolean")


def add_canonical_presence_flags(df: pd.DataFrame, config: Dict[str, Any]) -> None:
    """In place addition of canonical completeness and unit flags."""
    required = config.get("required_columns", {})

    if isinstance(required, dict):
        flag_map = {
            "identity": "flag_identity_missing",
            "station": "flag_station_metadata_missing",
            "hydrography": "flag_hydrography_missing",
            "carbonate_minimum_for_ta_ph": "flag_ta_ph_pair_missing",
        }

        aggregate = pd.Series(False, index=df.index)
        for group_name, flag_name in flag_map.items():
            cols = list(required.get(group_name, []))
            df[flag_name] = _missing_any(df, cols)
            aggregate = aggregate | df[flag_name].fillna(False)

        df["flag_required_core_missing"] = aggregate.astype("boolean")
    else:
        df["flag_required_core_missing"] = _missing_any(df, list(required))

    if "ta_units" in df.columns:
        df["flag_ta_units_missing"] = (~_series_has_value(df["ta_units"])).astype("boolean")
        df["flag_ta_units_unexpected"] = (
            _series_has_value(df["ta_units"]) & (df["ta_units"] != "umol kg-1")
        ).astype("boolean")
    else:
        df["flag_ta_units_missing"] = pd.Series(True, index=df.index, dtype="boolean")
        df["flag_ta_units_unexpected"] = pd.Series(pd.NA, index=df.index, dtype="boolean")

    accepted_ph_scales = {
        normalize_ph_scale(x)
        for x in config.get("accepted_ph_scales", ["total"])
    }
    accepted_ph_scales = {
        x
        for x in accepted_ph_scales
        if pd.notna(x) and str(x).strip() != ""
    }

    if "ph_scale_observed" in df.columns:
        df["flag_ph_scale_observed_missing"] = (
            ~_series_has_value(df["ph_scale_observed"])
        ).astype("boolean")
        df["flag_ph_scale_observed_unexpected"] = (
            _series_has_value(df["ph_scale_observed"])
            & ~df["ph_scale_observed"].isin(accepted_ph_scales)
        ).astype("boolean")
    else:
        df["flag_ph_scale_observed_missing"] = pd.Series(True, index=df.index, dtype="boolean")
        df["flag_ph_scale_observed_unexpected"] = pd.Series(pd.NA, index=df.index, dtype="boolean")

    if "pressure_output_dbar" in df.columns:
        df["flag_pressure_output_dbar_missing"] = (
            ~_series_has_value(df["pressure_output_dbar"])
        ).astype("boolean")
    else:
        df["flag_pressure_output_dbar_missing"] = pd.Series(True, index=df.index, dtype="boolean")


def build_canonical_inventory(
    df: pd.DataFrame,
    config: Dict[str, Any],
    source_lookup: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Build canonical column inventory with missingness, dtype, and source."""
    source_lookup = source_lookup or {}
    rows = []

    for col in config.get("canonical_export_order", []):
        if col in df.columns:
            n_total = len(df)
            n_present = int(_series_has_value(df[col]).sum())
            pct_missing = (
                round((n_total - n_present) / n_total * 100.0, 2)
                if n_total
                else 100.0
            )

            rows.append(
                {
                    "column": col,
                    "present": True,
                    "source_column": source_lookup.get(col, ""),
                    "dtype": str(df[col].dtype),
                    "non_missing": n_present,
                    "n_unique": int(df[col].nunique(dropna=True)),
                    "pct_missing": pct_missing,
                }
            )
        else:
            rows.append(
                {
                    "column": col,
                    "present": False,
                    "source_column": source_lookup.get(col, ""),
                    "dtype": "",
                    "non_missing": 0,
                    "n_unique": 0,
                    "pct_missing": 100.0,
                }
            )

    return pd.DataFrame(rows)


def build_canonical_export(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Return a copy ordered by canonical_export_order plus remaining columns."""
    ordered = [c for c in config.get("canonical_export_order", []) if c in df.columns]
    remaining = [c for c in df.columns if c not in ordered]
    return df[ordered + remaining].copy()


# =============================================================================
# Duplicate key helpers
# =============================================================================


def choose_duplicate_keys(
    df: pd.DataFrame,
    config: Dict[str, Any],
    override_keys: Optional[List[str]] = None,
) -> List[str]:
    """Pick a duplicate key tuple from config or override_keys.

    A candidate key set is usable only if all columns exist and at least one row
    has a complete non blank key across the full tuple. This prevents selecting
    weak key sets where each column has some data somewhere but no row has all
    key values together.
    """
    if override_keys:
        keys = [k for k in override_keys if k in df.columns]
        if not keys:
            return []

        complete = pd.Series(True, index=df.index)
        for key in keys:
            complete &= _series_has_value(df[key])

        return keys if complete.any() else []

    for candidate_set in config.get("duplicate_key_candidates", []):
        if not all(c in df.columns for c in candidate_set):
            continue

        complete = pd.Series(True, index=df.index)
        for col in candidate_set:
            complete &= _series_has_value(df[col])

        if complete.any():
            return list(candidate_set)

    return []


def add_duplicate_flags(df: pd.DataFrame, dup_keys: List[str]) -> int:
    """Flag possible duplicates only among rows with complete duplicate keys."""
    if not dup_keys:
        df["flag_possible_duplicate"] = pd.Series(False, index=df.index, dtype="boolean")
        df["flag_duplicate_key_incomplete"] = pd.Series(True, index=df.index, dtype="boolean")
        return 0

    missing = [col for col in dup_keys if col not in df.columns]
    if missing:
        die(f"Duplicate key columns are missing: {missing}")

    complete_key = pd.Series(True, index=df.index)

    for key in dup_keys:
        complete_key &= _series_has_value(df[key])

    dup_mask = pd.Series(False, index=df.index)

    if complete_key.any():
        dup_mask.loc[complete_key] = df.loc[complete_key].duplicated(
            subset=dup_keys,
            keep=False,
        )

    df["flag_possible_duplicate"] = dup_mask.astype("boolean")
    df["flag_duplicate_key_incomplete"] = (~complete_key).astype("boolean")

    return int(dup_mask.sum())
