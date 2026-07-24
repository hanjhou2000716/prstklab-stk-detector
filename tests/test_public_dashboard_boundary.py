from pathlib import Path


def test_public_mini_app_does_not_render_actionable_price_or_allocation_fields():
    root = Path(__file__).resolve().parents[1]
    app = (root / "site" / "app.js").read_text(encoding="utf-8")
    page = (root / "site" / "index.html").read_text(encoding="utf-8")

    for forbidden in ("reference_stop", "reference_risk", "risk_percent", "weight_percent", "renderAllocation"):
        assert forbidden not in app
    assert "研究配置" not in page
