from src.integration_release import validate_pre_delivery


def test_pre_delivery_blocks_failed_event_health():
    result = validate_pre_delivery(market={}, research={}, manifest={}, event_health={"state": "failed"})
    assert result["allowed"] is False
    assert "event source health is not publishable" in result["errors"]

