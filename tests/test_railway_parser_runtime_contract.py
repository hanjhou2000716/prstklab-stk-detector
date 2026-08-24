from __future__ import annotations

from pathlib import Path


def test_railway_runtime_declares_html_parser_dependency() -> None:
    """The standalone Railway image must be able to import the canonical parser."""
    requirements = (
        Path(__file__).resolve().parents[1] / "railway-monitor" / "requirements.txt"
    ).read_text(encoding="utf-8").casefold()
    assert "beautifulsoup4" in requirements


def test_generated_railway_parser_uses_the_canonical_source_marker() -> None:
    parser = (
        Path(__file__).resolve().parents[1]
        / "railway-monitor"
        / "src"
        / "external_source_parsers.py"
    ).read_text(encoding="utf-8")
    assert "GENERATED FILE: do not edit manually" in parser
    assert "Canonical source: src/external_source_parsers.py" in parser
