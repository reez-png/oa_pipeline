"""
tests/test_common.py
====================
Focused unit tests for oa_pipeline.common.

These tests protect shared behaviours used across the notebook runner and the
stage modules:

1. Config merges should not share nested default objects.
2. Papermill style no config values should return defaults.
3. Blank Excel strings should count as missing values.
4. Numeric looking sheet names should be treated as exact names first.
5. Robust outlier settings should reject invalid thresholds.
6. Optional strict column normalisation should catch canonical duplicates.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from oa_pipeline.common import (
    deep_update,
    has_value_series,
    load_config,
    make_missingness_table,
    normalize_columns,
    percent_missing,
    read_excel_sheets,
    robust_outlier_flags,
)


# =============================================================================
# Config merging and loading
# =============================================================================


def test_deep_update_does_not_share_nested_defaults() -> None:
    """deep_update should deep copy nested dictionaries and lists."""
    default = {"a": {"b": [1, 2]}}
    cfg = deep_update(default, {})

    cfg["a"]["b"].append(3)

    assert default["a"]["b"] == [1, 2]
    assert cfg["a"]["b"] == [1, 2, 3]


def test_deep_update_does_not_share_nested_override_values() -> None:
    """Override values should also be copied rather than shared."""
    override = {"a": {"b": [3, 4]}}
    cfg = deep_update({"a": {"b": [1, 2]}}, override)

    cfg["a"]["b"].append(5)

    assert override["a"]["b"] == [3, 4]
    assert cfg["a"]["b"] == [3, 4, 5]


def test_load_config_string_null_returns_default() -> None:
    """String null should behave like no config path."""
    cfg = load_config("null", default={"x": {"y": 1}})

    assert cfg == {"x": {"y": 1}}


def test_load_config_none_like_strings_return_default() -> None:
    """Common no config strings should all return the supplied defaults."""
    default = {"x": {"y": 1}}

    for value in [None, "", "None", "none", "NULL", "null"]:
        cfg = load_config(value, default=default)
        assert cfg == default
        assert cfg is not default
        assert cfg["x"] is not default["x"]


def test_load_config_json_null_file_returns_default(tmp_path) -> None:
    """A JSON null config file should merge as an empty config."""
    path = tmp_path / "config.json"
    path.write_text("null", encoding="utf-8")

    cfg = load_config(path, default={"x": {"y": 1}})

    assert cfg == {"x": {"y": 1}}


def test_load_config_merges_nested_json_without_mutating_default(tmp_path) -> None:
    """Nested config overrides should merge without mutating defaults."""
    default = {
        "outer": {
            "a": 1,
            "b": [1, 2],
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"outer": {"a": 99}}), encoding="utf-8")

    cfg = load_config(path, default=default)

    assert cfg == {"outer": {"a": 99, "b": [1, 2]}}
    assert default == {"outer": {"a": 1, "b": [1, 2]}}


# =============================================================================
# Missingness and value presence
# =============================================================================


def test_has_value_series_treats_blank_strings_as_missing() -> None:
    """Blank and whitespace strings should be missing for value presence."""
    s = pd.Series(["", " ", pd.NA, "x", 0])

    assert has_value_series(s).tolist() == [False, False, False, True, True]


def test_make_missingness_table_counts_blank_strings() -> None:
    """Missingness table should count blank Excel strings as missing."""
    df = pd.DataFrame({"a": ["", " ", pd.NA, "x"]})

    table = make_missingness_table(df)
    row = table.loc[table["column"].eq("a")].iloc[0]

    assert row["n_missing"] == 3
    assert row["pct_missing"] == 75.0


def test_percent_missing_counts_blank_strings() -> None:
    """percent_missing should use the same blank aware logic."""
    s = pd.Series(["", " ", pd.NA, "x"])

    assert percent_missing(s) == pytest.approx(75.0)


# =============================================================================
# Excel sheet selection
# =============================================================================


def test_read_excel_sheets_prefers_numeric_sheet_name(tmp_path) -> None:
    """A sheet named 01 should not be mistaken for sheet index 1."""
    path = tmp_path / "book.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="00", index=False)
        pd.DataFrame({"x": [2]}).to_excel(writer, sheet_name="01", index=False)

    sheets = read_excel_sheets(path, "01")

    assert list(sheets.keys()) == ["01"]
    assert sheets["01"].loc[0, "x"] == 2


def test_read_excel_sheets_numeric_string_uses_index_only_if_no_exact_name(tmp_path) -> None:
    """Numeric strings can still select by index when no exact sheet name exists."""
    path = tmp_path / "book.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="first", index=False)
        pd.DataFrame({"x": [2]}).to_excel(writer, sheet_name="second", index=False)

    sheets = read_excel_sheets(path, "1")

    assert list(sheets.keys()) == ["second"]
    assert sheets["second"].loc[0, "x"] == 2


# =============================================================================
# Robust outlier threshold validation
# =============================================================================


def test_robust_outlier_flags_rejects_bad_thresholds() -> None:
    """Invalid MAD threshold settings should fail clearly."""
    with pytest.raises(SystemExit):
        robust_outlier_flags(pd.Series([1, 2, 3]), mad_k=-1)

    with pytest.raises(SystemExit):
        robust_outlier_flags(pd.Series([1, 2, 3]), mad_k=float("nan"))

    with pytest.raises(SystemExit):
        robust_outlier_flags(pd.Series([1, 2, 3]), min_n=0)

    with pytest.raises(SystemExit):
        robust_outlier_flags(pd.Series([1, 2, 3]), max_abs=-10)


def test_robust_outlier_flags_accepts_valid_thresholds() -> None:
    """Valid thresholds should return a boolean mask aligned to input index."""
    s = pd.Series([1, 1, 1, 1, 100])

    flags = robust_outlier_flags(s, mad_k=3.5, max_abs=50, min_n=1)

    assert flags.index.equals(s.index)
    assert flags.dtype == bool
    assert flags.tolist() == [False, False, False, False, True]


# =============================================================================
# Column normalisation
# =============================================================================


def test_normalize_columns_rejects_exact_duplicates_after_strip() -> None:
    """Whitespace cleanup can create exact duplicate headers and should fail."""
    df = pd.DataFrame([[1, 2]], columns=["TA", "TA "])

    with pytest.raises(SystemExit):
        normalize_columns(df)


def test_normalize_columns_can_reject_canonical_duplicates() -> None:
    """Strict mode should catch TA, ta, and T A style ambiguous headers."""
    df = pd.DataFrame([[1, 2, 3]], columns=["TA", "ta", "T A"])

    with pytest.raises(SystemExit):
        normalize_columns(df, fail_on_canonical_duplicates=True)


def test_normalize_columns_preserves_default_permissive_canonical_behavior() -> None:
    """Canonical duplicate rejection is opt in to avoid breaking existing files."""
    df = pd.DataFrame([[1, 2]], columns=["TA", "ta"])

    out = normalize_columns(df)

    assert out.columns.tolist() == ["TA", "ta"]
