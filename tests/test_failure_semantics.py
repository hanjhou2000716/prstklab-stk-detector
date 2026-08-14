from src.failure_semantics import classify_failure, is_alert_eligible


def test_no_event_is_not_provider_failure() -> None:
    assert classify_failure({"status": "no_event"}) == "no_new_content"
    assert not is_alert_eligible("no_new_content")


def test_parse_and_provider_errors_are_distinct() -> None:
    assert classify_failure({"status": "parse_failed"}) == "parse_failed"
    assert classify_failure({"status": "failed"}) == "provider_failed"


def test_missing_configuration_and_release_block_are_fail_closed() -> None:
    assert classify_failure({"status": "not_configured"}) == "configuration_missing"
    assert classify_failure({"release_blocked": True}) == "release_blocked"
    assert not is_alert_eligible("release_blocked")


def test_unknown_status_fails_closed() -> None:
    assert classify_failure({"status": "future_provider_state"}) == "provider_failed"
