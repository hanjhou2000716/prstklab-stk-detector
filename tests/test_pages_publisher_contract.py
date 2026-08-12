from pathlib import Path


WORKFLOW_DIR = Path(__file__).parents[1] / ".github" / "workflows"
PUBLISHERS = (
    "refresh-dashboard.yml",
    "monitor-health.yml",
    "scheduled-brief.yml",
    "official-event-monitor.yml",
    "emergency-alert.yml",
    "unified-research-report.yml",
)


def test_pages_publishers_rebuild_and_validate_static_assets():
    for name in PUBLISHERS:
        text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
        assert "python -m src.build_assets --root site" in text, name
        assert "python -m src.asset_contract --root site" in text, name
