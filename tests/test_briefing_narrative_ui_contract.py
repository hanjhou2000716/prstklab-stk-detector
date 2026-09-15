from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_renders_narrative_preview_and_collapsed_details() -> None:
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "morning-analysis-highlights" in app
    assert "morning-analysis-details" in app
    assert "展開詳解" in app
    assert "narrative.evidence_refs" in app


def test_narrative_css_wraps_long_evidence_for_narrow_cards() -> None:
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert ".morning-analysis-highlights" in styles
    assert ".morning-analysis-details" in styles
    assert "overflow-wrap: anywhere" in styles
