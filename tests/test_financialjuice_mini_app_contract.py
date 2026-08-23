from pathlib import Path

APP = Path("site/app.js").read_text(encoding="utf-8")


def test_financialjuice_external_panel_exposes_vendor_risk_separation() -> None:
    """The investor UI must show FJ priority without treating it as PRStK risk."""
    assert "來源重要度：" in APP
    assert "不等同 PRStK 風險" in APP
    assert "PRStK Risk：" in APP
    assert "class=\"external-evidence\"" in APP


def test_financialjuice_external_panel_exposes_release_lineage_and_time() -> None:
    """Every public FJ row should make its release evidence traceable."""
    assert "發布鏈：" in APP
    assert "release_id" in APP
    assert "snapshot_id" in APP
    assert "observation_id" in APP
    assert "資料時間：" in APP
    assert "class=\"external-lineage\"" in APP


def test_financialjuice_external_panel_keeps_waiting_evidence_states() -> None:
    """Missing evidence remains explicit instead of being rendered as confirmed."""
    assert "等待官方核對／市場同步" in APP
    assert "等待市場同步" in APP
    assert "等待官方核對" in APP
