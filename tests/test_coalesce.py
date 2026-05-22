"""
tests/test_coalesce.py
======================
Tests for oa_pipeline.common coalescing helpers.

The coalescing helpers implement SQL style COALESCE behaviour plus row level
provenance. For each row, they walk candidate columns in priority order, choose
the first usable value, and record the source column that supplied that value.
"""

from __future__ import annotations

import pandas as pd

from oa_pipeline.common import coalesce_numeric_series, coalesce_string_series


# =============================================================================
# coalesce_numeric_series
# =============================================================================


class TestCoalesceNumericSeries:
    def test_first_column_wins_when_present(self) -> None:
        """When the first candidate has a value, later candidates are ignored."""
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [10.0, 20.0]})

        values, sources = coalesce_numeric_series(df, ["a", "b"])

        assert values.tolist() == [1.0, 2.0]
        assert sources.tolist() == ["a", "a"]

    def test_falls_through_to_next_candidate_per_row(self) -> None:
        """Each row independently walks the precedence list."""
        df = pd.DataFrame(
            {
                "a": [1.0, None, 3.0, None],
                "b": [None, 2.0, None, None],
                "c": [None, None, 30.0, 4.0],
            }
        )

        values, sources = coalesce_numeric_series(df, ["a", "b", "c"])

        assert values.tolist() == [1.0, 2.0, 3.0, 4.0]
        assert sources.tolist() == ["a", "b", "a", "c"]

    def test_all_na_row_yields_na_value_and_na_source(self) -> None:
        """A row where every candidate is missing produces missing value and source."""
        df = pd.DataFrame({"a": [None, 1.0], "b": [None, None]})

        values, sources = coalesce_numeric_series(df, ["a", "b"])

        assert pd.isna(values.iloc[0])
        assert pd.isna(sources.iloc[0])
        assert values.iloc[1] == 1.0
        assert sources.iloc[1] == "a"

    def test_missing_candidate_columns_are_skipped_silently(self) -> None:
        """Candidates absent from the dataframe are skipped."""
        df = pd.DataFrame({"b": [1.0, 2.0]})

        values, sources = coalesce_numeric_series(
            df,
            ["a_does_not_exist", "b", "c_neither"],
        )

        assert values.tolist() == [1.0, 2.0]
        assert sources.tolist() == ["b", "b"]

    def test_empty_candidate_list_yields_all_na(self) -> None:
        """If no candidates exist, return all missing values and sources."""
        df = pd.DataFrame({"x": [1.0, 2.0]})

        values, sources = coalesce_numeric_series(df, ["nope", "nada"])

        assert values.isna().all()
        assert sources.isna().all()
        assert len(values) == len(df)
        assert len(sources) == len(df)

    def test_non_numeric_input_is_coerced(self) -> None:
        """Numeric looking strings are parsed and bad strings become missing."""
        df = pd.DataFrame({"a": ["1.5", "not_a_number", "3.0"]})

        values, sources = coalesce_numeric_series(df, ["a"])

        assert values.iloc[0] == 1.5
        assert pd.isna(values.iloc[1])
        assert pd.isna(sources.iloc[1])
        assert values.iloc[2] == 3.0
        assert sources.iloc[2] == "a"

    def test_bad_numeric_value_falls_through_to_next_candidate(self) -> None:
        """A non numeric earlier value should not block a valid fallback value."""
        df = pd.DataFrame(
            {
                "a": ["bad", "1.0", None],
                "b": [2.5, 20.0, 30.0],
            }
        )

        values, sources = coalesce_numeric_series(df, ["a", "b"])

        assert values.tolist() == [2.5, 1.0, 30.0]
        assert sources.tolist() == ["b", "a", "b"]

    def test_numeric_output_dtype_is_nullable_float_and_source_string(self) -> None:
        """Numeric coalescing returns nullable Float64 plus string source."""
        df = pd.DataFrame({"a": [1.0, None]})

        values, sources = coalesce_numeric_series(df, ["a"])

        assert values.dtype.name == "Float64"
        assert sources.dtype.name == "string"

    def test_numeric_coalesce_preserves_index(self) -> None:
        """Output values and sources preserve the input dataframe index."""
        df = pd.DataFrame(
            {"a": [None, 2.0], "b": [1.0, 20.0]},
            index=["row_a", "row_b"],
        )

        values, sources = coalesce_numeric_series(df, ["a", "b"])

        assert values.index.tolist() == ["row_a", "row_b"]
        assert sources.index.tolist() == ["row_a", "row_b"]
        assert values.loc["row_a"] == 1.0
        assert sources.loc["row_a"] == "b"

    def test_duplicate_candidates_do_not_change_result(self) -> None:
        """Repeated candidate names should not affect values or provenance."""
        df = pd.DataFrame({"a": [1.0, None], "b": [10.0, 20.0]})

        values, sources = coalesce_numeric_series(df, ["a", "a", "b"])

        assert values.tolist() == [1.0, 20.0]
        assert sources.tolist() == ["a", "b"]


# =============================================================================
# coalesce_string_series
# =============================================================================


class TestCoalesceStringSeries:
    def test_first_column_wins(self) -> None:
        """When the first candidate has text, later candidates are ignored."""
        df = pd.DataFrame({"a": ["foo", "bar"], "b": ["x", "y"]})

        values, sources = coalesce_string_series(df, ["a", "b"])

        assert values.tolist() == ["foo", "bar"]
        assert sources.tolist() == ["a", "a"]

    def test_empty_string_treated_as_na(self) -> None:
        """Empty strings are treated as missing, not valid values."""
        df = pd.DataFrame(
            {
                "a": ["foo", "", None, "bar"],
                "b": [None, "baz", "qux", None],
            }
        )

        values, sources = coalesce_string_series(df, ["a", "b"])

        assert values.tolist() == ["foo", "baz", "qux", "bar"]
        assert sources.tolist() == ["a", "b", "b", "a"]

    def test_whitespace_string_treated_as_na(self) -> None:
        """Whitespace only strings are treated as missing."""
        df = pd.DataFrame(
            {
                "a": ["   ", "\t", "\n"],
                "b": ["x", "y", None],
            }
        )

        values, sources = coalesce_string_series(df, ["a", "b"])

        assert values.tolist()[:2] == ["x", "y"]
        assert sources.tolist()[:2] == ["b", "b"]
        assert pd.isna(values.iloc[2])
        assert pd.isna(sources.iloc[2])

    def test_returned_dtype_is_nullable_string(self) -> None:
        """The output Series should use pandas nullable string dtype."""
        df = pd.DataFrame({"a": ["x", "y"]})

        values, sources = coalesce_string_series(df, ["a"])

        assert values.dtype.name == "string"
        assert sources.dtype.name == "string"

    def test_string_coalesce_preserves_index(self) -> None:
        """String coalescing preserves the input dataframe index."""
        df = pd.DataFrame(
            {"a": ["", "x"], "b": ["fallback", "y"]},
            index=["row_a", "row_b"],
        )

        values, sources = coalesce_string_series(df, ["a", "b"])

        assert values.index.tolist() == ["row_a", "row_b"]
        assert sources.index.tolist() == ["row_a", "row_b"]
        assert values.loc["row_a"] == "fallback"
        assert sources.loc["row_a"] == "b"

    def test_duplicate_candidates_do_not_change_string_result(self) -> None:
        """Repeated string candidate names should not affect coalescing."""
        df = pd.DataFrame({"a": ["x", ""], "b": ["fallback_1", "fallback_2"]})

        values, sources = coalesce_string_series(df, ["a", "a", "b"])

        assert values.tolist() == ["x", "fallback_2"]
        assert sources.tolist() == ["a", "b"]
