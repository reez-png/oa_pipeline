"""
tests/test_coalesce.py
======================
Tests for ``oa_common.coalesce_numeric_series`` and
``coalesce_string_series`` — Stage 1B's best-source picker.

These functions implement SQL ``COALESCE(...)`` plus row-level
provenance: per row, walk a list of candidate columns and pick the first
non-NA value, recording which column it came from. Stage 1B uses them
seven times for the different chemistry-variable families, so a
regression in either function would corrupt the analysis_ready output
silently. These tests pin the behaviour.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_common import coalesce_numeric_series, coalesce_string_series


# ---------------------------------------------------------------------------
# coalesce_numeric_series
# ---------------------------------------------------------------------------

class TestCoalesceNumericSeries:
    def test_first_column_wins_when_present(self):
        """When the first candidate has a value, downstream candidates are ignored."""
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [10.0, 20.0]})
        values, sources = coalesce_numeric_series(df, ["a", "b"])
        assert values.tolist() == [1.0, 2.0]
        assert sources.tolist() == ["a", "a"]

    def test_falls_through_to_next_candidate_per_row(self):
        """Each row independently walks the precedence list."""
        df = pd.DataFrame({
            "a": [1.0, None, 3.0, None],
            "b": [None, 2.0, None, None],
            "c": [None, None, 30.0, 4.0],
        })
        values, sources = coalesce_numeric_series(df, ["a", "b", "c"])
        # Row 0: a=1, taken. Row 1: a=NA -> b=2, taken.
        # Row 2: a=3, taken (NOT c=30, even though c has a value).
        # Row 3: a=NA, b=NA, c=4 -> c is taken.
        assert values.tolist() == [1.0, 2.0, 3.0, 4.0]
        assert sources.tolist() == ["a", "b", "a", "c"]

    def test_all_na_row_yields_na_value_and_na_source(self):
        """A row where every candidate is NA produces (NA, NA) — including the source."""
        df = pd.DataFrame({"a": [None, 1.0], "b": [None, None]})
        values, sources = coalesce_numeric_series(df, ["a", "b"])
        # Row 0: all NA -> value NA, source must also be NA (not "a")
        assert pd.isna(values.iloc[0])
        assert pd.isna(sources.iloc[0])
        # Row 1: a=1 wins
        assert values.iloc[1] == 1.0
        assert sources.iloc[1] == "a"

    def test_missing_candidate_columns_are_skipped_silently(self):
        """Candidates that don't exist in df are not errors."""
        df = pd.DataFrame({"b": [1.0, 2.0]})
        values, sources = coalesce_numeric_series(df, ["a_does_not_exist", "b", "c_neither"])
        assert values.tolist() == [1.0, 2.0]
        assert sources.tolist() == ["b", "b"]

    def test_empty_candidate_list_yields_all_na(self):
        """If no candidates exist, return all-NA values and all-NA sources."""
        df = pd.DataFrame({"x": [1.0, 2.0]})
        values, sources = coalesce_numeric_series(df, ["nope", "nada"])
        assert values.isna().all()
        assert sources.isna().all()
        assert len(values) == len(df)

    def test_non_numeric_input_is_coerced(self):
        """Strings that look like numbers get parsed; bad strings become NA.

        This matters because Stage 1B sometimes receives a column that
        was read from CSV as object dtype.
        """
        df = pd.DataFrame({"a": ["1.5", "not_a_number", "3.0"]})
        values, sources = coalesce_numeric_series(df, ["a"])
        assert values.iloc[0] == 1.5
        assert pd.isna(values.iloc[1])      # "not_a_number" -> NA
        assert pd.isna(sources.iloc[1])     # therefore no source either
        assert values.iloc[2] == 3.0


# ---------------------------------------------------------------------------
# coalesce_string_series
# ---------------------------------------------------------------------------

class TestCoalesceStringSeries:
    def test_first_column_wins(self):
        df = pd.DataFrame({"a": ["foo", "bar"], "b": ["x", "y"]})
        values, sources = coalesce_string_series(df, ["a", "b"])
        assert values.tolist() == ["foo", "bar"]
        assert sources.tolist() == ["a", "a"]

    def test_empty_string_treated_as_na(self):
        """An empty string is treated as missing, not as a valid value.

        This is the canonical pandas-CSV-reads-empty-cells-as-empty-string
        gotcha; the helper guards against it explicitly.
        """
        df = pd.DataFrame({
            "a": ["foo", "", None, "bar"],
            "b": [None, "baz", "qux", None],
        })
        values, sources = coalesce_string_series(df, ["a", "b"])
        # Row 0: "foo" from a
        # Row 1: a="" -> fall through to b="baz"
        # Row 2: a=None -> b="qux"
        # Row 3: "bar" from a
        assert values.tolist() == ["foo", "baz", "qux", "bar"]
        assert sources.tolist() == ["a", "b", "b", "a"]

    def test_returned_dtype_is_nullable_string(self):
        """The output Series should be `pd.StringDtype()`, not object."""
        df = pd.DataFrame({"a": ["x", "y"]})
        values, sources = coalesce_string_series(df, ["a"])
        # pandas uses "string" pretty-name for StringDtype.
        assert values.dtype.name == "string"
        assert sources.dtype.name == "string"
