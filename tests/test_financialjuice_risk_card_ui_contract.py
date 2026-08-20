from pathlib import Path

APP = Path("site/app.js").read_text(encoding="utf-8")


def test_financialjuice_risk_card_keeps_vendor_priority_separate_from_prstk_risk() -> None:
    assert "來源重要度：" in APP
    assert "PRStK Risk：" in APP
    assert "等待第二來源" in APP
    assert "isFinancialJuice" in APP


def test_financialjuice_card_does_not_render_vendor_score_as_risk_level() -> None:
    marker = "const isFinancialJuice"
    block = APP[APP.index(marker):APP.index("const domains", APP.index(marker))]
    assert "vendor_importance" in block
    assert "prstk_risk" in block
    assert "來源重要度" in block
