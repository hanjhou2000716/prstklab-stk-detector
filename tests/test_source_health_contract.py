from src.artifact_contract import validate_source_health


def _health(**overrides):
    value = {
        "status": "healthy",
        "sources": [{
            "key": "market_quotes",
            "status": "no_event",
            "semantic_state": "no_event",
            "no_event": True,
        }],
        "event_scan": {"status": "no_event", "detail": "scan completed"},
        "observability": {
            "observations": 1,
            "success_rate": 100,
            "failure_count": 0,
            "no_event_count": 1,
            "stale_count": 0,
            "degraded_count": 0,
            "state": "healthy",
        },
    }
    value.update(overrides)
    return value


def test_source_health_accepts_successful_empty_scan():
    assert validate_source_health(_health()) == []


def test_source_health_rejects_failed_source_hidden_as_no_event():
    value = _health(
        sources=[{
            "key": "market_quotes",
            "status": "failed",
            "semantic_state": "no_event",
        }]
    )
    errors = validate_source_health(value)
    assert any("semantic_state=no_event" in error for error in errors)
    assert any("event_scan=no_event" in error for error in errors)


def test_source_health_rejects_healthy_status_with_stale_semantics():
    value = _health(sources=[{
        "key": "market_quotes",
        "status": "healthy",
        "semantic_state": "stale",
    }])
    assert any("semantic_state=stale" in error for error in validate_source_health(value))


def test_source_health_schema_rejects_negative_observability_counter():
    value = _health(observability={"failure_count": -1})
    errors = validate_source_health(value)
    assert any("schema" in error and "failure_count" in error for error in errors)


def test_source_health_rejects_stale_aggregate_gap_count():
    value = _health(
        missing_source_count=1,
        sources=[{"key": "market_quotes", "status": "healthy", "semantic_state": "healthy"}],
    )
    assert any("missing_source_count" in error for error in validate_source_health(value))
