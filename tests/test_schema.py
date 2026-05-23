"""
tests/test_schema.py
====================
Tests for oa_pipeline.schema.

These tests cover canonical alias resolution, row wise alias coalescing,
duplicate key selection, duplicate flags, schema config loading, and unit or
scale normalisation.

The carbonate unit tests intentionally expect all equivalent concentration unit
spellings to normalise to one canonical value: "umol kg-1". This protects Stage
3 and Stage 4 from false DIC unit mismatch flags when equivalent units are
written with different symbols or spacing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oa_pipeline.schema import (
    DEFAULT_CONFIG,
    add_duplicate_flags,
    apply_canonical_schema,
    choose_duplicate_keys,
    load_schema_config,
    normalize_carbonate_unit,
    normalize_ph_scale,
    normalize_ta_units,
)


# =============================================================================
# apply_canonical_schema
# =============================================================================


class TestApplyCanonicalSchema:
    def test_resolves_aliases_to_canonical_names(self) -> None:
        """A workbook with quirky column names gets canonical names attached."""
        df = pd.DataFrame(
            {
                "sample_tag": ["S1", "S2"],
                "Salinity": [35.0, 35.1],
                "lattitude": [10.0, 11.0],
            }
        )

        out, audit, lookup = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert "record_id" in out.columns
        assert "salinity" in out.columns
        assert "latitude_deg" in out.columns
        assert out["record_id"].tolist() == ["S1", "S2"]
        assert out["salinity"].tolist() == [35.0, 35.1]
        assert out["latitude_deg"].tolist() == [10.0, 11.0]
        assert not audit.empty
        assert "lattitude" in lookup.get("latitude_deg", "")

    def test_creates_canonical_columns_when_no_alias_resolves(self) -> None:
        """If no alias is found, the canonical column is created as all missing."""
        df = pd.DataFrame({"sample_tag": ["S1", "S2"]})

        out, _, _ = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert "pco2_calc_uatm" in out.columns
        assert out["pco2_calc_uatm"].isna().all()

    def test_preserves_original_columns_by_default(self) -> None:
        """Original source columns are preserved while canonical columns are added."""
        df = pd.DataFrame({"sample_tag": ["S1"], "Salinity": [35.0]})

        out, _, _ = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert "Salinity" in out.columns
        assert "salinity" in out.columns
        assert out.loc[0, "Salinity"] == 35.0
        assert out.loc[0, "salinity"] == 35.0

    def test_apply_canonical_schema_does_not_mutate_input(self) -> None:
        """Schema application should not modify the caller's original dataframe."""
        df = pd.DataFrame({"sample_tag": ["S1"], "Salinity": [35.0]})
        original_cols = list(df.columns)

        out, _, _ = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert list(df.columns) == original_cols
        assert "salinity" not in df.columns
        assert "salinity" in out.columns

    def test_empty_canonical_column_is_filled_from_better_alias(self) -> None:
        """Regression: empty canonical columns must not block useful aliases."""
        df = pd.DataFrame(
            {
                "ta_umol_kg": [pd.NA, pd.NA],
                "ta_corrected_umolkg": [2201.5, 2202.0],
                "ph_observed": [pd.NA, pd.NA],
                "ph_corrected_from_phstd": [8.01, 8.02],
            }
        )

        out, _, lookup = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert out["ta_umol_kg"].tolist() == [2201.5, 2202.0]
        assert out["ph_observed"].tolist() == [8.01, 8.02]
        assert "ta_corrected_umolkg" in lookup.get("ta_umol_kg", "")
        assert "ph_corrected_from_phstd" in lookup.get("ph_observed", "")

    def test_apply_canonical_schema_coalesces_aliases_row_wise(self) -> None:
        """Different rows may take values from different aliases."""
        df = pd.DataFrame(
            {
                "ta_umol_kg": [2300.0, pd.NA],
                "ta_corrected_umolkg": [pd.NA, 2310.0],
            }
        )

        out, _, lookup = apply_canonical_schema(df, DEFAULT_CONFIG)

        assert out["ta_umol_kg"].tolist() == [2300.0, 2310.0]
        assert "ta_umol_kg" in lookup.get("ta_umol_kg", "")
        assert "ta_corrected_umolkg" in lookup.get("ta_umol_kg", "")

    def test_apply_canonical_schema_rejects_ambiguous_aliases(self) -> None:
        """Ambiguous aliases should fail rather than silently picking one pH field."""
        df = pd.DataFrame(
            {
                "pH": [8.01, 8.02],
                "ph": [7.91, 7.92],
            }
        )

        with pytest.raises(SystemExit):
            apply_canonical_schema(df, DEFAULT_CONFIG)


# =============================================================================
# choose_duplicate_keys and add_duplicate_flags
# =============================================================================


class TestDuplicateKeys:
    def test_picks_first_candidate_set_where_all_columns_have_values(self) -> None:
        """The straightforward case: first usable candidate set wins."""
        df = pd.DataFrame(
            {
                "sample_id": ["S1", "S2", "S3"],
                "replicate_id": ["a", "b", "c"],
                "sample_date": pd.to_datetime(["2024-01-01"] * 3, utc=True),
                "station_id": ["X", "Y", "Z"],
            }
        )

        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)

        assert keys == ["sample_id", "replicate_id", "sample_date", "station_id"]

    def test_chooser_skips_all_na_columns(self) -> None:
        """All missing canonical columns should not be selected as duplicate keys."""
        df = pd.DataFrame(
            {
                "sample_id": [pd.NA, pd.NA],
                "replicate_id": [pd.NA, pd.NA],
                "sample_date": [pd.NaT, pd.NaT],
                "station_id": [pd.NA, pd.NA],
                "record_id": ["R1", "R2"],
            }
        )

        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)

        assert "sample_id" not in keys
        assert keys == ["record_id"]

    def test_returns_empty_when_no_candidate_set_works(self) -> None:
        """A frame with no usable identifier returns an empty key list."""
        df = pd.DataFrame({"junk": [1, 2, 3]})

        keys = choose_duplicate_keys(df, DEFAULT_CONFIG)

        assert keys == []

    def test_override_keys_take_precedence(self) -> None:
        """override_keys short circuits the configured candidate list."""
        df = pd.DataFrame(
            {
                "sample_id": ["S1", "S2"],
                "custom_key": ["A", "B"],
            }
        )

        keys = choose_duplicate_keys(
            df,
            DEFAULT_CONFIG,
            override_keys=["custom_key"],
        )

        assert keys == ["custom_key"]

    def test_add_duplicate_flags_ignores_incomplete_key_rows(self) -> None:
        """Rows with incomplete duplicate keys should not be flagged as duplicates."""
        df = pd.DataFrame(
            {
                "sample_id": [pd.NA, pd.NA, "S3"],
                "sample_date": [pd.NaT, pd.NaT, pd.Timestamp("2024-01-01")],
            }
        )

        n_flagged = add_duplicate_flags(df, ["sample_id", "sample_date"])

        assert n_flagged == 0
        assert "flag_possible_duplicate" in df.columns
        assert "flag_duplicate_key_incomplete" in df.columns
        assert not df["flag_possible_duplicate"].fillna(False).any()
        assert df["flag_duplicate_key_incomplete"].fillna(False).tolist() == [
            True,
            True,
            False,
        ]

    def test_add_duplicate_flags_treats_blank_strings_as_incomplete_keys(self) -> None:
        """Blank strings in duplicate keys should be incomplete, not duplicates."""
        df = pd.DataFrame(
            {
                "sample_id": ["", " ", "S3"],
                "sample_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
            }
        )

        n_flagged = add_duplicate_flags(df, ["sample_id", "sample_date"])

        assert n_flagged == 0
        assert not df["flag_possible_duplicate"].fillna(False).any()
        assert df["flag_duplicate_key_incomplete"].fillna(False).tolist() == [
            True,
            True,
            False,
        ]


# =============================================================================
# Config loading
# =============================================================================


class TestSchemaConfigLoading:
    def test_load_schema_config_none_returns_defaults(self) -> None:
        """None config returns defaults and no resolved path."""
        cfg, resolved = load_schema_config(None)

        assert resolved is None
        assert "canonical_candidates" in cfg
        assert cfg["canonical_candidates"]

    def test_load_schema_config_string_none_returns_defaults(self) -> None:
        """String None from Papermill should behave like no config path."""
        cfg, resolved = load_schema_config("None")

        assert resolved is None
        assert "canonical_candidates" in cfg
        assert cfg["canonical_candidates"]

    @pytest.mark.parametrize("value", ["", "none", "None", "NONE", "null", "NULL"])
    def test_load_schema_config_empty_like_strings_return_defaults(self, value) -> None:
        """Papermill style empty config strings should not be treated as paths."""
        cfg, resolved = load_schema_config(value)

        assert resolved is None
        assert "canonical_candidates" in cfg
        assert cfg["canonical_candidates"]

    def test_load_schema_config_empty_yaml_returns_defaults(self, tmp_path) -> None:
        """Empty YAML should not turn the config into None."""
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")

        cfg, resolved = load_schema_config(str(path))

        assert resolved == str(path.resolve())
        assert "canonical_candidates" in cfg
        assert cfg["canonical_candidates"]

    def test_load_schema_config_override_merges_defaults(self, tmp_path) -> None:
        """A partial override should deep merge with schema defaults."""
        path = tmp_path / "schema.yaml"
        path.write_text(
            """
canonical_candidates:
  salinity:
    - salinity
    - sal
    - practical_salinity
""",
            encoding="utf-8",
        )

        cfg, _ = load_schema_config(str(path))

        assert "canonical_candidates" in cfg
        assert "practical_salinity" in cfg["canonical_candidates"]["salinity"]
        assert "ta_umol_kg" in cfg["canonical_candidates"]


# =============================================================================
# Unit and scale normalisers
# =============================================================================


class TestNormalizers:
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("total", "total"),
            ("TOTAL", "total"),
            ("Total", "total"),
            ("tot", "total"),
            ("total scale", "total"),
            ("ph_total", "total"),
            ("seawater", "seawater"),
            ("SWS", "seawater"),
            ("sws", "seawater"),
            ("ph_sws", "seawater"),
            ("free", "free"),
            ("free scale", "free"),
            ("ph_free", "free"),
            ("nbs", "nbs"),
            ("NBS", "nbs"),
        ],
    )
    def test_normalize_ph_scale_to_lowercase_canonical(
        self,
        input_val,
        expected,
    ) -> None:
        """Scale strings normalise to lowercase canonical forms."""
        assert normalize_ph_scale(input_val) == expected

    @pytest.mark.parametrize("input_val", ["t", "T", "f", "F"])
    def test_normalize_ph_scale_ambiguous_one_letter_values_pass_through(
        self,
        input_val,
    ) -> None:
        """Single letter labels are ambiguous and should not be silently mapped."""
        assert normalize_ph_scale(input_val) == input_val.strip()

    def test_normalize_ph_scale_unknown_value_passes_through(self) -> None:
        """Unrecognised scale labels return unchanged, with whitespace stripped."""
        assert normalize_ph_scale("  unknown_scale  ") == "unknown_scale"

    def test_normalize_ph_scale_na_returns_na(self) -> None:
        """Missing pH scale values remain missing."""
        assert pd.isna(normalize_ph_scale(pd.NA))

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("umol/kg", "umol kg-1"),
            ("UMOLKG", "umol kg-1"),
            ("umolkg-1", "umol kg-1"),
            ("\u00b5mol/kg", "umol kg-1"),
            ("\u00b5mol kg\u22121", "umol kg-1"),
            ("umol kg\u207b\u00b9", "umol kg-1"),
            ("umol/kgSW", "umol kg-1"),
        ],
    )
    def test_normalize_ta_units_common_variants(
        self,
        input_val,
        expected,
    ) -> None:
        """Common TA unit variants normalise to umol kg-1."""
        assert normalize_ta_units(input_val) == expected

    def test_normalize_ta_units_unknown_value_passes_through(self) -> None:
        """Unknown TA units are preserved for downstream review flags."""
        assert normalize_ta_units("mg/L") == "mg/L"

    def test_normalize_ta_units_na_returns_na(self) -> None:
        """Missing TA units remain missing."""
        assert pd.isna(normalize_ta_units(pd.NA))

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("umol/kg", "umol kg-1"),
            ("UMOL/KG", "umol kg-1"),
            ("UMOLKG", "umol kg-1"),
            ("UMOLKG-1", "umol kg-1"),
            ("UMOLKG^-1", "umol kg-1"),
            ("UMOL/KG-1", "umol kg-1"),
            ("MICROMOL/KG", "umol kg-1"),
            ("MICROMOLKG", "umol kg-1"),
            ("\u00b5mol/kg", "umol kg-1"),
            ("\u03bcmol/kg", "umol kg-1"),
            ("\u039cMOL/KG", "umol kg-1"),
            ("umol kg-1", "umol kg-1"),
            ("umol kg\u22121", "umol kg-1"),
            ("umol kg\u207b\u00b9", "umol kg-1"),
            (" \u00b5mol / kg ", "umol kg-1"),
        ],
    )
    def test_normalize_carbonate_unit_variants(
        self,
        input_val,
        expected,
    ) -> None:
        """Equivalent carbonate species units normalise to one canonical form."""
        assert normalize_carbonate_unit(input_val) == expected

    def test_normalize_carbonate_unit_unknown_value_passes_through(self) -> None:
        """Unknown carbonate species units are preserved for review."""
        assert normalize_carbonate_unit("mmol/m3") == "mmol/m3"

    def test_normalize_carbonate_unit_na_returns_na(self) -> None:
        """Missing carbonate species unit values remain missing."""
        assert pd.isna(normalize_carbonate_unit(pd.NA))
