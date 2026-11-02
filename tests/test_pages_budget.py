from pathlib import Path

import pytest

from src.pages_budget import PagesBudgetError, measure_pages_tree


def test_pages_budget_counts_regular_files_and_nested_content(tmp_path: Path):
    (tmp_path / "index.html").write_bytes(b"index")
    nested = tmp_path / "assets"
    nested.mkdir()
    (nested / "app.js").write_bytes(b"bundle")

    assert measure_pages_tree(tmp_path) == (11, 2)


def test_pages_budget_stops_at_configured_size(tmp_path: Path):
    (tmp_path / "large.bin").write_bytes(b"0123456789")

    with pytest.raises(PagesBudgetError, match="byte budget"):
        measure_pages_tree(tmp_path, max_bytes=9)


def test_pages_budget_rejects_non_positive_limit(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")

    with pytest.raises(PagesBudgetError):
        measure_pages_tree(tmp_path, max_bytes=0)
