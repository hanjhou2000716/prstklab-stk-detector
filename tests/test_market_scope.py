from src.market_scope import event_belongs_to_scope, market_scope_for_slot, scope_snapshot


def test_routine_slot_scope_is_defined_by_slot_not_summary_text():
    assert market_scope_for_slot("pre_open") == "taiwan"
    assert market_scope_for_slot("post_close") == "taiwan"
    assert market_scope_for_slot("us_premarket") == "us"
    assert market_scope_for_slot("morning") is None


def test_explicit_aliases_scope_events_without_using_headline_text():
    event = {"market_evidence": [{"ticker": "費半"}]}
    assert event_belongs_to_scope(event, "us") is True
    assert event_belongs_to_scope(event, "taiwan") is False
    assert event_belongs_to_scope({"event": "台灣與美國市場波動"}, "us") is False


def test_cross_market_event_is_excluded_from_both_scoped_projections():
    event = {
        "market_scope": "us",
        "market_evidence": [{"ticker": "費半"}, {"ticker": "台指期"}],
    }
    snapshot = {"events": {"items": [event]}}
    assert scope_snapshot(snapshot, "us_premarket")["events"]["items"] == []
    assert scope_snapshot(snapshot, "post_close")["events"]["items"] == []
