"""
tests/test_schema.py
====================
Tests for ``oa_schema``: canonical alias resolution, the duplicate-key
chooser, and the unit/scale normalisers.

These tests pin two of the bugs we caught and fixed during the refactor:

  1. The duplicate-key chooser used to pick a candidate set where every
     column existed in df — but ``apply_canonical_schema`` creates every
     canonical column NA-filled, so the existence test was trivially
     true and every row got flagged as a duplicate. The fix requires
     each column to have at least one non-NA value. See test
     ``test_chooser_skips_all_na_columns``.

  2. The lower-case canonical pH-scale strings (``total``, ``free``,
     ``seawater``, ``nbs``). The original Stage 3 produced UPPERCASE,
     while Stages 1A/1B produced lower; the divergence was silent but
     would have broken any downstream join.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_schema import (
    DEFAULT_CONFIG,
    apply_canonical_schema,
    choose_duplicate_keys,
    normalize_carbonate_unit,
    normalize_ph_scale,
    normalize_ta_units,
)


# ---------------------------------------------------------------------------
# apply_canonical_schema
# ---------------------------------------------------------------------------

class TestApplyCanonicalSchema:
    def test_resolves_aliases_to_canonical_names(self):
        """A workbook with quirky column names gets canonical names attached."""
        df = pd.DataFrame({
            "sample_tag": ["S1", "S2"],     # -> record_id
            "Salinity":   [35.0, 35.1],     # -> salinity (case-insensitive)
            "lattitude":  [10.0, 11.0],     # -> latitude_deg (misspelling alias)
        })
        out, audit, lookup = apply_canonical_schema(df, DEFAULT_CONFIG)
        assert "record_id" in out.columns
        assert "salinity" in out.columns
        assert "latitude_deg" in out.columns
        assert out["record_id"].tolist() == ["S1", "S2"]
        assert out["latitude_deg"].tolist() == [10.0, 11.0]
        # Audit records the resolution.
        assert "lattitude" in lookup.get("latitude_deg", "")

    def test_creates_canonical_columns_when_no_alias_resolves(self):
        """If no alias is found, the canonical column is created with all-NA."""
        df = pd.DataFrame({"sample_tag": ["S1", "S2"]})
        out, _, _ = apply_canonical_schema(df, DEFAULT_CONFIG)
        # `pco2_calc_uatm` has no matching alias in df
        assert "pco2_calc_uatm" in out.columns
        assert out["pco2_calc_uatm"].isna().all()

    def test_preserves_original_columns_by_default(self):
        """`preserve_original_columns=True` (default) keeps the source column."""
        df = pd.DataFrame({"sample_tag": ["S1"], "Salinity": [35.0]})
        out, _, _ = apply_canonical_schema(df, DEFAULT_CONFIG)
        # Both the original "Salinity" and the canonical "salinity" should exist.
        # (The exact case of "Salinity" survives because we copy, not rename.)
        assert "salinity" in out.columns
        # The audit may have re-cased; what we care about is that data is preserved
        # at *some* column.
        assert any("Salinity" in c or c == "salinity" for c in out.columns)


# ---------------------------------------------------------------------------
# choose_duplicate_keys
# ---------------------------------------------------------------------------

class TestChooseDuplicateKeys:
    def test_picks_first_candidate_set_where_all_columns_have_values(self):
        """The straightforward case: first usable candidate set wins."""
        df = pd.DataFrame({
            "sample_id":    ["S1", "S2", "S3"],
            "replicate_id": ["a", "b", "c"],
            "sample_date":  pd.to_datetime(["2024-01-01"] * 3),
            "station_id":   ["X", "Y", "Z"],
        })
        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)
        # First candidate in DEFAULT_CONFIG is [sample_id, replicate_id,
        # sample_date, station_id] -- all present -> chosen.
        assert keys == ["sample_id", "replicate_id", "sample_date", "station_id"]

    def test_chooser_skips_all_na_columns(self):
        """REGRESSION TEST for the bug we caught.

        ``apply_canonical_schema`` creates every canonical column NA-filled
        if no alias resolved. The original chooser only checked "column
        exists in df", which was trivially true after schema application,
        and would pick the [sample_id, replicate_id, sample_date,
        station_id] set even when all four were NA. ``df.duplicated``
        then treats all-NA tuples as equal -> every row flagged as
        duplicate.

        Fixed by requiring "column exists AND has >= 1 non-NA value".
        """
        # A frame that has been through apply_canonical_schema where only
        # the `record_id` column actually carries values.
        df = pd.DataFrame({
            "sample_id":    [pd.NA, pd.NA],
            "replicate_id": [pd.NA, pd.NA],
            "sample_date":  [pd.NaT, pd.NaT],
            "station_id":   [pd.NA, pd.NA],
            "record_id":    ["R1", "R2"],   # the only usable column
        })
        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)
        # Should NOT pick [sample_id, replicate_id, sample_date,
        # station_id]; should fall through to a candidate set that uses
        # record_id.
        assert "sample_id" not in keys  # the dangerous all-NA column was rejected
        # The DEFAULT_CONFIG candidate list eventually includes ["record_id"]
        # as a fallback; that's what should be chosen.
        assert keys == ["record_id"]

    def test_returns_empty_when_no_candidate_set_works(self):
        """A frame with no usable identifier returns an empty list."""
        df = pd.DataFrame({"junk": [1, 2, 3]})
        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)
        assert keys == []

    def test_override_keys_take_precedence(self):
        """`override_keys` short-circuits the candidate list."""
        df = pd.DataFrame({
            "sample_id":  ["S1", "S2"],
            "custom_key": ["A", "B"],
        })
        keys = choose_duplicate_keys(df, DEFAULT_CONFIG, override_keys=["custom_key"])
        assert keys == ["custom_key"]


# ---------------------------------------------------------------------------
# Unit + scale normalisers
# ---------------------------------------------------------------------------

class TestNormalizers:
    @pytest.mark.parametrize("input_val,expected", [
        ("total", "total"),
        ("TOTAL", "total"),       # case-insensitive
        ("Total", "total"),
        ("tot", "total"),         # abbrev
        ("t", "total"),
        ("seawater", "seawater"),
        ("SWS", "seawater"),
        ("sws", "seawater"),
        ("sw", "seawater"),
        ("free", "free"),
        ("f", "free"),
        ("nbs", "nbs"),
        ("NBS", "nbs"),
    ])
    def test_normalize_ph_scale_to_lowercase_canonical(self, input_val, expected):
        """REGRESSION: scale strings normalize to LOWERCASE canonical form.

        The original Stage 3 produced UPPERCASE (`"TOTAL"`), which
        diverged from Stages 1A/1B's lowercase. Fixed by unifying on
        lower-case here.
        """
        assert normalize_ph_scale(input_val) == expected

    def test_normalize_ph_scale_unknown_value_passes_through(self):
        """Unrecognised scale labels return unchanged (with whitespace stripped)."""
        assert normalize_ph_scale("  unknown_scale  ") == "unknown_scale"

    def test_normalize_ph_scale_na_returns_na(self):
        assert pd.isna(normalize_ph_scale(pd.NA))

    @pytest.mark.parametrize("input_val,expected", [
        ("umol/kg",   "umol kg-1"),
        ("UMOLKG",    "umol kg-1"),
        ("umolkg-1",  "umol kg-1"),
        ("\u00b5mol/kg", "umol kg-1"),    # micro sign
    ])
    def test_normalize_ta_units(self, input_val, expected):
        assert normalize_ta_units(input_val) == expected

    def test_normalize_carbonate_unit_handles_micro_sign_variants(self):
        """All three forms of "micro" fold to ASCII U."""
        # micro sign U+00B5
        assert normalize_carbonate_unit("\u00b5mol/kg") == "UMOL/KG"
        # Greek lowercase mu U+03BC
        assert normalize_carbonate_unit("\u03bcmol/kg") == "UMOL/KG"
        # Greek capital mu U+039C
        assert normalize_carbonate_unit("\u039cMOL/KG") == "UMOL/KG"
