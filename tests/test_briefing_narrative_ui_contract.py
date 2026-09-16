from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_direct_card_fields_without_duplicate_narrative_blocks() -> None:
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "renderLabeledValue" in app
    assert "morning-analysis-highlights" not in app
    assert "morning-analysis-details" not in app
    assert "展開詳解" not in app
    assert "narrative.evidence_refs" not in app


def test_narrative_css_wraps_long_evidence_for_narrow_cards() -> None:
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert ".briefing-evidence" in styles
    assert ".morning-analysis-highlights" not in styles
    assert ".morning-analysis-details" not in styles
    assert "overflow-wrap: anywhere" in styles
