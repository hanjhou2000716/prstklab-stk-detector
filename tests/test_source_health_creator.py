from datetime import datetime
from zoneinfo import ZoneInfo

from src.source_health import build_source_health


def test_creator_health_is_optional_and_distinguishes_no_content_from_failure() -> None:
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={}, checked_at=datetime(2026, 8, 12, tzinfo=ZoneInfo("Asia/Taipei")),
        creator_sources=[
            {"provider": "haojiao", "status": "no_event", "last_success_at": "2026-08-12T00:00:00Z"},
            {"provider": "gooaye", "status": "failed", "issues": ["parse_failed"]},
        ],
    )
    rows = {row["key"]: row for row in health["sources"]}
    assert rows["creator_haojiao"]["semantic_state"] == "no_event"
    assert rows["creator_gooaye"]["semantic_state"] == "failed"
    assert health["runtime_failure_count"] >= 1
