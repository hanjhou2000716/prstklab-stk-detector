import json

from src.market_assessment import build_joint_market_signal, normalize_headline
from src.market_digest import build_market_digest


def test_historical_backup_fgi_does_not_modify_current_risk_adjustments():
    from src.market_assessment import _joint_risk_adjustments

    assert _joint_risk_adjustments({
        "台股": {
            "sentiment": {"label": "極度恐慌", "calculation_state": "backup_history"},
            "vix": None,
        }
    }) == []


def test_storm_headline_removes_byline_publisher_and_normalizes_fact():
    result = normalize_headline({
        "title": "台積電、日月光等30家巨頭共組「矽光子聯盟」！經濟部：供應鏈完全掌握在台灣手上｜張大任 新聞 - Storm.mg",
    })

    assert result["raw_title"].endswith("Storm.mg")
    assert result["normalized_fact"] == "台積電、日月光等業者組成矽光子聯盟，經濟部表示供應鏈涵蓋台灣廠商。"
    assert result["byline_removed"] is True
    assert result["publisher_removed"] is True


def test_news_publisher_suffix_is_removed_from_public_event_fact():
    result = normalize_headline({
        "event": "台指期夜盤大漲473點站上4萬7，台股周一迎戰8月營收 AI供應鏈續受關注 - Yahoo股市。",
    })

    assert result["normalized_fact"].endswith("AI供應鏈續受關注。")
    assert "Yahoo股市" not in result["normalized_fact"]
    assert result["publisher_removed"] is True


def test_chained_news_publisher_suffixes_are_removed_from_public_event_fact():
    result = normalize_headline({
        "title": "全球半導體產值上看2兆美元，亞洲AI供應鏈成焦點，台積電曝量產優勢-財經焦點情報站 - CMoney投資網誌。",
    })

    assert result["normalized_fact"] == "全球半導體產值上看2兆美元，亞洲AI供應鏈成焦點，台積電曝量產優勢。"
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

    assert result["public_short_message"].startswith("🟡 美股盤前")
    assert "半導體出口管制更新" not in result["public_short_message"]
    assert "原油供應中斷" not in result["public_short_message"]
    assert result["market_scope_key"] == "us"
    assert "半導體出口管制更新" not in json.dumps(result, ensure_ascii=False)
    assert "原油供應中斷" not in json.dumps(result, ensure_ascii=False)


def test_same_event_cluster_keeps_supporting_source_evidence_once():
    common = {
        "market_scope": "us",
        "event_cluster_key": "cluster-semi-1",
        "event": "半導體出口管制更新，供應鏈等待後續細節",
        "published_at": "2026-09-04T23:00:00+00:00",
    }
    result = build_market_digest({
        "generated_at": "2026-09-05T00:00:00+00:00",
        "events": {"items": [
            {**common, "source_key": "official", "observation_id": "official-1"},
            {
                **common,
                "source_key": "financialjuice",
                "observation_id": "fj-1",
                "freshness_status": "fresh",
            },
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
            {"ticker": "TAIEX", "price": 26586, "change_percent": 0.1, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "TXF", "price": 11735, "change_percent": 2.0, "freshness": "recent_close", "quote_date": "2026-09-04", "contract_month": "202609"},
        ],
    }, "post_close")

    assert result["overview"].startswith("總結｜")
    assert "行情重點｜" in result["overview"]
    assert "風險｜" in result["overview"]
    assert "台股休市" in result["overview"]
    assert len(result["overview"]) <= 140
    assert result["public_short_message"].startswith("🟡 台股盤後")


def test_taiwan_stance_does_not_call_nasdaq_softness_a_generic_conflict():
    result = build_market_digest({
        "indices": [
            {"ticker": "TAIEX", "price": 100, "change_percent": 1.2, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "TPEx", "price": 100, "change_percent": 1.0, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "TXF", "price": 101, "change_percent": 0.9, "freshness": "recent_close", "quote_date": "2026-09-04", "contract_month": "202609"},
            {"ticker": "SOX", "price": 100, "change_percent": 1.1, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "NASDAQ", "price": 100, "change_percent": -0.4, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "US10Y", "price": 4.0, "change_percent": 0.1, "freshness": "recent_close", "quote_date": "2026-09-04"},
        ],
    }, "post_close")

    assert result["market_assessment"]["stance"] != "divergent"
    assert result["market_assessment"]["factor_count"] == 2
    assert "directional_quote_conflict" not in result["market_assessment"]["conflict_flags"]


def test_quote_only_briefing_is_not_suppressed_but_empty_inputs_are():
    quote_only = build_market_digest({
        "indices": [
            {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "SOX", "price": 100, "change_percent": 1.5, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "ES", "price": 6000, "change_percent": 0.5, "freshness": "live", "quote_time": "2026-09-05T12:00:00Z", "contract_month": "202609"},
            {"ticker": "US10Y", "price": 4.0, "change_percent": -0.5, "freshness": "recent_close", "quote_date": "2026-09-04"},
        ],
    }, "us_premarket")
    empty = build_market_digest({}, "us_premarket")

    assert quote_only["notification_eligible"] is True
    assert quote_only["overview"].startswith("總結｜")
    assert empty["notification_eligible"] is True
    assert "行情資料不足" in empty["public_short_message"]


def test_tpex_does_not_replace_weighted_index_and_txf_in_taiwan_core_projection():
    result = build_market_digest({
        "indices": [
            {"ticker": "TAIEX", "price": 100, "change_percent": 1.0, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "TPEx", "price": 100, "change_percent": 0.8, "freshness": "recent_close", "quote_date": "2026-09-04"},
            {"ticker": "TXF", "price": 101, "change_percent": 0.7, "freshness": "recent_close", "quote_date": "2026-09-04", "contract_month": "202609"},
            {"ticker": "SOX", "price": 100, "change_percent": 1.0, "freshness": "recent_close", "quote_date": "2026-09-04"},
        ],
    }, "post_close")

    assert result["market_assessment"]["factor_count"] == 2
    taiwan_evidence = result["market_assessment"]["joint_market_signal"]["evidence"]["taiwan"]
    assert {row["ticker"] for row in taiwan_evidence} >= {"TAIEX", "TXF"}
    assert all(row["ticker"] != "TPEx" for row in taiwan_evidence)
    assert all(row["ticker"] != "SOX" for row in taiwan_evidence)


def test_market_assessment_is_json_serializable_for_snapshot_publication():
    result = build_market_digest({
        "indices": [
            {"ticker": "TAIEX", "price": 100, "change_percent": 1.0, "freshness": "recent_close"},
            {"ticker": "NASDAQ", "price": 100, "change_percent": 0.8, "freshness": "recent_close"},
            {"ticker": "US10Y", "price": 4.0, "change_percent": -0.2, "freshness": "recent_close"},
        ],
    }, "post_close")

    json.dumps(result, ensure_ascii=False)


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


def test_joint_market_signal_requires_three_factors_and_both_markets():
    signal = build_joint_market_signal([
        {"ticker": "TAIEX", "price": 100, "change_percent": 0.8, "freshness": "recent_close"},
        {"ticker": "TXF", "price": 100, "change_percent": 0.4, "freshness": "recent_close"},
        {"ticker": "NASDAQ", "price": 100, "change_percent": 0.6, "freshness": "recent_close"},
    ])

    assert signal["status"] == "complete"
    assert signal["label"] == "偏多"
    assert signal["valid_factor_count"] == 3


def test_joint_market_signal_marks_taiwan_us_divergence_and_panic_downgrade():
    signal = build_joint_market_signal([
        {"ticker": "TAIEX", "price": 100, "change_percent": -0.6, "freshness": "recent_close"},
        {"ticker": "TXF", "price": 100, "change_percent": -0.4, "freshness": "recent_close"},
        {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "freshness": "recent_close"},
        {"ticker": "SOX", "price": 100, "change_percent": 1.2, "freshness": "recent_close"},
    ], {
        "us": {"sentiment": {"label": "恐慌"}},
    })

    assert signal["status"] == "complete"
    assert signal["divergent"] is True
    assert signal["label"].startswith("台美分歧，整體")
    assert signal["risk_adjustments"] == ["us情緒：恐慌"]


def test_joint_market_signal_accepts_valid_recent_close_marked_delayed():
    signal = build_joint_market_signal([
        {
            "ticker": "TAIEX",
            "price": 100,
            "change_percent": -0.4,
            "freshness": "recent_close",
            "data_status": "最近收盤",
            "quote_date": "2026-09-11",
            "quote_delayed": True,
            "stale_used": True,
        },
        {
            "ticker": "NASDAQ",
            "price": 100,
            "change_percent": 0.6,
            "freshness": "recent_close",
            "data_status": "最近收盤",
            "quote_date": "2026-09-11",
            "quote_delayed": True,
            "stale_used": True,
        },
        {
            "ticker": "SOX",
            "price": 100,
            "change_percent": 0.8,
            "freshness": "recent_close",
            "data_status": "最近收盤",
            "quote_date": "2026-09-11",
            "quote_delayed": True,
            "stale_used": True,
        },
    ])

    assert signal["status"] == "complete"
    assert signal["valid_factor_count"] == 3
    assert signal["divergent"] is True


def test_joint_market_signal_fails_closed_for_missing_or_invalid_prices():
    signal = build_joint_market_signal([
        {"ticker": "TAIEX", "price": 100, "change_percent": None},
        {"ticker": "TPEx", "price": 100, "change_percent": float("nan")},
        {"ticker": "NASDAQ", "price": 100, "change_percent": 0.5, "freshness": "recent_close"},
    ])

    assert signal["status"] == "insufficient_evidence"
    assert signal["label"] == "資料不足，台美狀態待確認"
    assert signal["valid_factor_count"] == 1
