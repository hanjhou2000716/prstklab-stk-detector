import json

from src.market_assessment import normalize_headline
from src.market_digest import build_market_digest


def test_storm_headline_removes_byline_publisher_and_normalizes_fact():
    result = normalize_headline({
        "title": "台積電、日月光等30家巨頭共組「矽光子聯盟」！經濟部：供應鏈完全掌握在台灣手上｜張大任 新聞 - Storm.mg",
    })

    assert result["raw_title"].endswith("Storm.mg")
    assert result["normalized_fact"] == "台積電、日月光等業者組成矽光子聯盟，經濟部表示供應鏈涵蓋台灣廠商。"
    assert result["byline_removed"] is True
    assert result["publisher_removed"] is True


def test_official_person_is_role_only_in_public_fact():
    result = normalize_headline({"title": "沃勒表示通膨與勞動市場仍是利率判斷的重要依據"})

    assert result["normalized_fact"].startswith("Fed官員表示")
    assert result["actor_name"] == "沃勒"
    assert result["headline_actor"] == "Fed官員"


def test_unrelated_events_do_not_get_joined_into_market_title():
    result = build_market_digest({
        "generated_at": "2026-09-05T00:00:00+00:00",
        "events": {"items": [
            {
                "source_key": "official",
                "event": "半導體出口管制更新，供應鏈等待後續細節",
                "published_at": "2026-09-04T23:00:00+00:00",
                "observation_id": "semi-1",
            },
            {
                "source_key": "official",
                "event": "原油供應中斷推升能源風險，航運等待核對",
                "published_at": "2026-09-04T22:00:00+00:00",
                "observation_id": "energy-1",
            },
        ]},
        "indices": [
            {"ticker": "SOX", "price": 11735, "change_percent": 3.0, "freshness": "recent_close"},
            {"ticker": "NASDAQ", "price": 26586, "change_percent": -1.0, "freshness": "recent_close"},
            {"ticker": "US10Y", "price": 4.2, "change_percent": 0.2, "freshness": "recent_close"},
        ],
    }, "us_premarket")

    assert "；" in result["public_short_message"]
    assert "半導體出口管制更新" not in result["public_short_message"]
    assert "原油供應中斷" not in result["public_short_message"]
    assert result["market_assessment"]["stance"] == "divergent"


def test_same_event_cluster_keeps_supporting_source_evidence_once():
    common = {
        "event_cluster_key": "cluster-semi-1",
        "event": "半導體出口管制更新，供應鏈等待後續細節",
        "published_at": "2026-09-04T23:00:00+00:00",
    }
    result = build_market_digest({
        "generated_at": "2026-09-05T00:00:00+00:00",
        "events": {"items": [
            {**common, "source_key": "official", "observation_id": "official-1"},
            {**common, "source_key": "financialjuice", "observation_id": "fj-1"},
        ]},
    }, "us_premarket")

    assert len(result["themes"]) == 1
    evidence_ids = {item.get("observation_id") for item in result["primary_theme"]["source_evidence"]}
    assert evidence_ids == {"official-1", "fj-1"}


def test_market_assessment_uses_fixed_three_section_overview_and_weekend_status():
    result = build_market_digest({
        "generated_at": "2026-09-05T00:00:00+00:00",
        "events": {"items": [{
            "source_key": "official",
            "event": "台積電與半導體供應鏈組成聯盟，產業題材等待價格確認",
            "published_at": "2026-09-04T23:00:00+00:00",
        }]},
        "indices": [
            {"ticker": "NASDAQ", "price": 26586, "change_percent": 0.1, "freshness": "recent_close"},
            {"ticker": "SOX", "price": 11735, "change_percent": 2.0, "freshness": "recent_close"},
        ],
    }, "post_close")

    assert result["overview"].startswith("總結｜")
    assert "行情重點｜" in result["overview"]
    assert "風險｜" in result["overview"]
    assert "台股休市" in result["overview"]
    assert len(result["overview"]) <= 140
    assert result["public_short_message"].startswith("📊 台股盤後｜")


def test_quote_only_briefing_is_not_suppressed_but_empty_inputs_are():
    quote_only = build_market_digest({
        "indices": [
            {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "freshness": "recent_close"},
            {"ticker": "SOX", "price": 100, "change_percent": 1.5, "freshness": "recent_close"},
            {"ticker": "US10Y", "price": 4.0, "change_percent": -0.5, "freshness": "recent_close"},
        ],
    }, "us_premarket")
    empty = build_market_digest({}, "us_premarket")

    assert quote_only["notification_eligible"] is True
    assert quote_only["overview"].startswith("總結｜")
    assert empty["notification_eligible"] is False
    assert empty["public_short_message"] == ""


def test_quote_refresh_with_same_assessment_does_not_change_canonical_identity():
    base = {
        "generated_at": "2026-09-05T00:00:00+00:00",
        "events": {"items": [{
            "source_key": "official",
            "event": "半導體出口管制更新，供應鏈等待後續細節",
            "published_at": "2026-09-04T23:00:00+00:00",
        }]},
        "indices": [
            {"ticker": "SOX", "price": 100, "change_percent": 2.0, "freshness": "recent_close"},
            {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "freshness": "recent_close"},
        ],
    }
    changed = json.loads(json.dumps(base))
    changed["indices"][0]["price"] = 120
    changed["indices"][0]["change_percent"] = 3.0

    first = build_market_digest(base, "us_premarket")
    second = build_market_digest(changed, "us_premarket")
    assert first["canonical_hash_version"] == 2
    assert first["briefing_id"] == second["briefing_id"]


def test_public_message_is_bounded_without_ellipsis_or_multiple_event_facts():
    result = build_market_digest({
        "events": {"items": [{
            "source_key": "official",
            "event": "Fed官員表示利率政策將依通膨與就業資料調整",
            "published_at": "2026-09-04T23:00:00+00:00",
        }]},
    }, "morning")

    assert len(result["public_short_message"]) <= 60
    assert "..." not in result["public_short_message"]
    assert "…" not in result["public_short_message"]
    assert result["public_short_message"].count("；") <= 1
