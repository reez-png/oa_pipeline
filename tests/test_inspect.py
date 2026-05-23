"""
tests/test_inspect.py
=====================
Focused unit tests for oa_pipeline.inspect.

These tests protect Notebook 03 helper behaviour:

1. Empty output folders still produce a stable inventory schema.
2. Single string suffix filters such as "csv" work correctly.
3. Inventory filtering matches both file names and relative paths.
4. CSV and image file helpers return the expected paths.
5. Table preview reads only the requested number of rows.
6. TSV preview support works after the optional inspect.py patch.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from oa_pipeline.inspect import (
    INVENTORY_COLUMNS,
    filter_inventory,
    get_csv_files,
    get_image_files,
    list_output_files,
    preview_csv_table,
)


# =============================================================================
# Inventory creation
# =============================================================================


def test_list_output_files_empty_folder_has_stable_columns(tmp_path: Path) -> None:
    """An empty output directory should still return the stable inventory schema."""
    out = list_output_files(tmp_path)

    assert list(out.columns) == INVENTORY_COLUMNS
    assert out.empty


def test_list_output_files_accepts_single_suffix_string(tmp_path: Path) -> None:
    """suffixes="csv" should mean one suffix, not characters c, s, and v."""
    csv_path = tmp_path / "table.csv"
    png_path = tmp_path / "plot.png"

    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    png_path.write_bytes(b"not really an image")

    out = list_output_files(tmp_path, suffixes="csv")

    assert out["name"].tolist() == ["table.csv"]
    assert out["suffix"].tolist() == [".csv"]


def test_list_output_files_accepts_dot_prefixed_suffix_list(tmp_path: Path) -> None:
    """Suffix lists should work with dot prefixed and non dot prefixed values."""
    (tmp_path / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "report.md").write_text("# Report\n", encoding="utf-8")
    (tmp_path / "plot.png").write_bytes(b"fake")

    out = list_output_files(tmp_path, suffixes=[".csv", "md"])

    assert out["name"].tolist() == ["report.md", "table.csv"]


# =============================================================================
# Inventory filtering and path helpers
# =============================================================================


def test_filter_inventory_matches_name_and_relative_path(tmp_path: Path) -> None:
    """Filtering should match nested relative paths, not only basenames."""
    nested = tmp_path / "sheet_oa_data" / "data"
    nested.mkdir(parents=True)
    path = nested / "derived.csv"
    path.write_text("a\n1\n", encoding="utf-8")

    inventory = list_output_files(tmp_path)
    filtered = filter_inventory(inventory, "sheet_oa_data")

    assert filtered["name"].tolist() == ["derived.csv"]


def test_filter_inventory_blank_keyword_returns_copy(tmp_path: Path) -> None:
    """A blank keyword should return an unchanged copy of the inventory."""
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")

    inventory = list_output_files(tmp_path)
    filtered = filter_inventory(inventory, "  ")

    assert filtered.equals(inventory)
    assert filtered is not inventory


def test_get_csv_and_image_files(tmp_path: Path) -> None:
    """CSV and image helpers should select only their supported file types."""
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "b.png").write_bytes(b"fake")
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")

    inventory = list_output_files(tmp_path)

    assert [p.name for p in get_csv_files(inventory)] == ["a.csv"]
    assert [p.name for p in get_image_files(inventory)] == ["b.png"]


# =============================================================================
# Table preview
# =============================================================================


def test_preview_csv_table_reads_head_only(tmp_path: Path) -> None:
    """CSV preview should return only the requested number of rows."""
    path = tmp_path / "table.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    out = preview_csv_table(path, nrows=1)

    assert out.shape == (1, 2)
    assert out.loc[0, "a"] == 1


def test_preview_csv_table_supports_tsv(tmp_path: Path) -> None:
    """TSV preview should use tab separation."""
    path = tmp_path / "table.tsv"
    path.write_text("a\tb\n1\t2\n3\t4\n", encoding="utf-8")

    out = preview_csv_table(path, nrows=2)

    assert out.shape == (2, 2)
    assert out.loc[0, "a"] == 1
    assert out.loc[1, "b"] == 4


def test_preview_csv_table_rejects_bad_nrows(tmp_path: Path) -> None:
    """nrows must be a positive integer."""
    path = tmp_path / "table.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        preview_csv_table(path, nrows=0)

    with pytest.raises(SystemExit):
        preview_csv_table(path, nrows="not-an-int")


def test_preview_csv_table_rejects_unsupported_suffix(tmp_path: Path) -> None:
    """Only .csv, .tsv, and .txt previews are supported."""
    path = tmp_path / "table.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit):
        preview_csv_table(path)
