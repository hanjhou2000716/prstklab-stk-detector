from src.corporate_event_engine import corporate_event_summary, normalize_corporate_event


def test_earnings_normalization_keeps_beat_miss_separate():
    event = normalize_corporate_event({"ticker": "NVDA", "event_type": "earnings", "actual_eps": 1.2, "expected_eps": 1.0, "actual_revenue": 100, "expected_revenue": 110, "published_at": "2026-08-04T02:00:00Z", "source_url": "https://sec.example/8k"})
    assert event["eps_result"] == "beat"
    assert event["revenue_result"] == "miss"
    assert event["directional_claim"] is False
    assert event["point_in_time"] is True


def test_unknown_event_type_falls_back_without_dropping_record():
    event = normalize_corporate_event({"ticker": "AAA", "event_type": "rumor", "title": "Public release"})
    assert event["event_type"] == "other"
    assert event["ticker"] == "AAA"


def test_summary_is_evidence_only():
    event = normalize_corporate_event({"event_type": "guidance", "guidance": "raised", "gross_margin": 0.72, "affected_sectors": ["semiconductor"]})
    summary = corporate_event_summary(event)
    assert "guidance_disclosed" in summary["evidence"]
    assert summary["investment_recommendation"] is None