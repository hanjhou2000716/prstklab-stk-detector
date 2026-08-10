from src.research_fallback import mark_stale_research_fallback


def test_stale_fallback_is_explicit_and_blocks_candidates():
    report = {
        "generated_at": "2026-08-04T00:00:00+08:00",
        "candidates": [{"ticker": "2330"}],
        "sources": [{"strategy": "momentum", "scan_state": "complete", "candidate_state": "available"}],
        "production_eligible": True,
        "publish_eligible": True,
    }
    fallback = mark_stale_research_fallback(report, "Taiwan universe source unavailable")
    assert fallback["availability"] == "expired"
    assert fallback["research_freshness"] == "stale_fallback"
    assert fallback["production_eligible"] is False
    assert fallback["publish_eligible"] is False
    assert fallback["sources"][0]["scan_state"] == "failed"
    assert fallback["sources"][0]["candidate_state"] == "data_gap"
    assert fallback["candidates"] == report["candidates"]
