import hashlib

from src.external_source_parsers import parse_financialjuice_email
from src.financialjuice_priority import (
    bind_financialjuice_semantic_views,
    project_financialjuice_priority,
    public_financialjuice_observations,
)


def _row(importance=8):
    return {
        "observation_id": "fj-observation-1",
        "item_id": "fj-item-1",
        "source": "financialjuice",
        "original_headline": "Oil supply risk",
        "event_type": "energy",
        "importance": importance,
        "source_url": "https://financialjuice.com/item/1",
        "published_at": "2026-08-21T01:00:00Z",
        "received_at": "2026-08-21T01:01:00Z",
        "parser_version": "financialjuice-compound-v1",
        "public_safe": True,
    }


def test_qualifying_fj_item_becomes_release_bound_vendor_priority_event():
    projection = project_financialjuice_priority([_row(8)])
    assert projection["decisions"][0]["notification_status"] == "eligible"
    event = projection["events"][0]
    assert event["vendor_priority_notification"] is True
    assert event["risk_level"] == "R2"
    assert event["prstk_risk_level"] == "R2"
    assert event["market_direction"] is None
    assert event["source_trace"]["vendor_importance_is_not_risk"] is True
    assert event["received_at"] == "2026-08-21T01:01:00Z"
    assert event["parser_version"] == "financialjuice-compound-v1"
    assert event["observation_id_hash"] == hashlib.sha256(b"fj-observation-1").hexdigest()
    assert event["source_trace"]["observation_id_hash"] == event["observation_id_hash"]
    assert "fj-observation-1" not in event["source_trace"]["observation_id_hash"]


def test_fj_missing_article_url_uses_vendor_homepage_source_trace():
    row = _row(8)
    row.pop("source_url")

    event = project_financialjuice_priority([row])["events"][0]

    assert event["source_url"] == "https://www.financialjuice.com/"
    assert event["source_trace"]["source_url"] == "https://www.financialjuice.com/"
    assert event["source_trace"]["source_domain"] == "financialjuice.com"


def test_fj_below_threshold_is_visible_but_not_eligible():
    projection = project_financialjuice_priority([_row(7)])
    assert projection["decisions"][0]["notification_status"] == "not_eligible"
    assert projection["events"][0]["alert_eligible"] is False


def test_fj_same_cluster_is_not_sent_twice():
    projection = project_financialjuice_priority([_row(8)], existing_events=[{"event_cluster_key": ""}])
    # Without a cluster key, this is a new auditable item; the absence of a
    # key must not silently suppress a qualifying notification.
    assert projection["decisions"][0]["notification_status"] == "eligible"

    row = _row(8)
    row["event_cluster_key"] = "cluster-1"
    projection = project_financialjuice_priority([row], existing_events=[{"event_cluster_key": "cluster-1"}])
    assert projection["decisions"][0]["notification_status"] == "already_cluster_notified"
    assert "already_cluster_notified" in projection["decisions"][0]["notification_reason"]


def test_rich_fj_fields_project_to_canonical_semantics_without_risk_mutation():
    row = _row(10)
    row.update({
        "chinese_translation": "某公司據報正在評估與某 AI 晶片供應商合作",
        "ai_commentary": "若合作成真，可能代表該公司 AI 基礎建設需求進一步提高，但目前仍未正式確認。",
        "possible_impact": "可能影響 AI 伺服器、GPU、相關供應鏈個股情緒。",
    })

    event = project_financialjuice_priority([row])["events"][0]

    assert event["event"] == row["chinese_translation"]
    assert event["why_important"] == row["ai_commentary"]
    assert event["possible_linkage"] == row["possible_impact"]
    assert event["stock_observation"] == "等待官方後續確認，並觀察相關市場是否同步反應。"
    assert "據報" in event["event"]
    assert "正式確認" in event["why_important"]
    assert event["risk_level"] == "R2"
    assert event["source_evidence"]
    assert event["source_evidence"][0]["chinese_translation"] == row["chinese_translation"]


def test_rich_source_fields_win_over_legacy_generic_canonical_values():
    row = _row(10)
    row.update({
        "event": "FinancialJuice 公開快訊",
        "why_important": "舊版摘要",
        "possible_linkage": "舊版影響",
        "chinese_translation": "某公司據報正在評估合作",
        "ai_commentary": "目前仍未正式確認，但可能提高 AI 基礎建設需求。",
        "possible_impact": "可能影響 AI 伺服器供應鏈。",
    })

    event = project_financialjuice_priority([row])["events"][0]

    assert event["event"] == row["chinese_translation"]
    assert event["why_important"] == row["ai_commentary"]
    assert event["possible_linkage"] == row["possible_impact"]


def test_legacy_fj_label_contamination_is_split_at_projection_boundary():
    row = _row(8)
    row.update({
        "vendor_translation": "美伊衝突升級。 💡 AI 評論: 市場風險偏好受壓，但仍需核對。",
        "vendor_analysis": "重要性評分: 8/10 📝 繁體中文翻譯:",
        "vendor_possible_impact": "油價波動可能升高。 📄 原文內容 Iran says no nuclear activity.",
    })

    event = project_financialjuice_priority([row])["events"][0]

    assert event["event"] == "美伊衝突升級。"
    assert event["title"] == "Oil supply risk"
    assert event["why_important"] == "市場風險偏好受壓，但仍需核對。"
    assert event["possible_linkage"] == "油價波動可能升高。"
    assert event["prstk_risk_level"] == "R2"


def test_projection_binds_clean_semantics_to_public_observation_view():
    row = {
        "observation_id": "fj-public-1",
        "source": "financialjuice",
        "vendor_translation": "舊標題 💡 AI 評論: 舊評論",
        "vendor_analysis": "重要性評分: 8/10 📝 繁體中文翻譯:",
        "vendor_possible_impact": "油價可能上升。 📄 原文內容 Iran: ...",
        "vendor_importance": 8,
        "public_safe": True,
    }
    projection = project_financialjuice_priority([row])
    view = bind_financialjuice_semantic_views([row], projection["events"])[0]
    assert view["event"] == "舊標題"
    assert view["vendor_translation"] == "舊標題"
    assert view["ai_commentary"] == "舊評論"
    assert view["vendor_possible_impact"] == "油價可能上升。"
    assert "原文內容" not in view["vendor_possible_impact"]


def test_compound_rich_semantics_stay_bound_to_each_item():
    parsed = parse_financialjuice_email(
        sender="alerts@financialjuice.com",
        subject="compound alert",
        body=(
            "Item 1\nImportance: 10/10\nOriginal headline: First headline\n"
            "Translation: 第一個據報事件\nAI commentary: 第一個仍待確認。\n"
            "Possible impact: 第一個可能影響供應鏈。\n"
            "Item 2\nImportance: 9/10\nOriginal headline: Second headline\n"
            "Translation: 第二個傳聞事件\nAI commentary: 第二個尚未證實。\n"
            "Possible impact: 第二個可能影響科技股。"
        ),
        message_id="rich-compound-1",
    )
    items = [dict(item, source="financialjuice") for item in parsed["items"]]

    events = project_financialjuice_priority(items)["events"]
    by_item = {event["item_id"]: event for event in events}

    assert len(by_item) == 2
    assert {event["event"] for event in events} == {"第一個據報事件", "第二個傳聞事件"}
    assert by_item[items[0]["item_id"]]["why_important"] == "第一個仍待確認。"
    assert by_item[items[1]["item_id"]]["why_important"] == "第二個尚未證實。"
    assert by_item[items[0]["item_id"]]["possible_linkage"] == "第一個可能影響供應鏈。"
    assert by_item[items[1]["item_id"]]["possible_linkage"] == "第二個可能影響科技股。"


def test_legacy_and_malformed_optional_fields_degrade_without_raw_json():
    row = _row(8)
    row.update({"ai_commentary": {"private": "no"}, "possible_impact": []})

    event = project_financialjuice_priority([row])["events"][0]

    assert event["event"] == "Oil supply risk"
    assert event["why_important"].startswith("來源快訊標示重要度 8/10")
    assert "Oil supply risk" in event["why_important"]
    assert "仍待官方或第二來源核對" in event["why_important"]
    assert event["possible_linkage"] == "尚無足夠公開資料判定連動。"
    assert event["stock_observation"] == "等待官方後續確認，並觀察相關市場是否同步反應。"
    assert "private" not in str(event)
    assert "[]" not in event["possible_linkage"]


def test_score_only_fj_item_uses_event_and_impact_as_evidence_template():
    row = _row(10)
    row.update({
        "chinese_translation": "伊朗：美國攻擊電信和通信基礎設施。",
        "possible_impact": "可能推升能源與全球風險溢酬。",
    })

    event = project_financialjuice_priority([row])['events'][0]

    assert event['why_important'].startswith('來源快訊標示重要度 10/10')
    assert '可能推升能源與全球風險溢酬' in event['why_important']
    assert '仍待官方或第二來源核對' in event['why_important']


def test_neutral_legacy_importance_is_replaced_by_fj_evidence_template():
    row = _row(10)
    row.update({
        "chinese_translation": "伊朗：美國攻擊電信和通信基礎設施。",
        "why_important": "目前尚無額外重要性說明，等待後續公開資料核對。",
        "possible_impact": "可能推升全球風險溢酬。",
    })

    event = project_financialjuice_priority([row])['events'][0]

    assert event['why_important'].startswith('來源快訊標示重要度 10/10')
    assert '目前尚無額外重要性說明' not in event['why_important']


def test_importance_alone_is_audited_but_blocked_from_public_and_telegram():
    row = {
        "observation_id": "fj-incomplete-1",
        "source": "financialjuice",
        "vendor_importance": 10,
        "public_safe": True,
    }
    projection = project_financialjuice_priority([row], market_snapshot={"indices": []})
    event = projection["events"][0]
    decision = projection["decisions"][0]
    assert decision["notification_status"] == "content_incomplete"
    assert "missing_material_event" in decision["notification_reason"]
    assert decision["vendor_priority_notification"] is False
    assert event["alert_eligible"] is False
    assert event["public_signal_eligible"] is False
    assert public_financialjuice_observations([row], projection["events"]) == []


def test_legacy_fj_row_without_verified_source_identity_is_audit_only():
    row = _row(10)
    row["source_identity_verified"] = False
    projection = project_financialjuice_priority([row], market_snapshot={"indices": []})
    event = projection["events"][0]
    assert projection["decisions"][0]["notification_status"] == "content_incomplete"
    assert "source_identity_unverified" in projection["decisions"][0]["notification_reason"]
    assert event["public_signal_eligible"] is False
    assert public_financialjuice_observations([row], projection["events"]) == []


def test_fj_market_linkage_is_deterministic_and_separates_sync_from_linked():
    snapshot = {
        "instrument_master": {"instruments": [
            {"ticker": "WTI", "name": "WTI", "aliases": ["原油"]},
            {"ticker": "BRENT", "name": "Brent", "aliases": ["油價"]},
            {"ticker": "NASDAQ", "name": "NASDAQ", "aliases": ["科技股"]},
        ]},
        "indices": [
            {"ticker": "WTI", "name": "WTI", "price": 90, "change_percent": 2.2, "freshness": "recent_close", "quality_freshness": "fresh", "stale_used": False},
            {"ticker": "BRENT", "name": "Brent", "price": 94, "change_percent": 1.5, "freshness": "recent_close", "quality_freshness": "fresh", "stale_used": False},
            {"ticker": "NASDAQ", "name": "NASDAQ", "price": 18000, "change_percent": -0.1, "freshness": "recent_close", "quality_freshness": "fresh", "stale_used": False},
        ],
    }
    row = _row(8)
    row.update({
        "chinese_translation": "油品供應中斷",
        "ai_commentary": "供應風險升高。",
        "possible_impact": "可能推升油價。",
    })
    event = project_financialjuice_priority([row], market_snapshot=snapshot)["events"][0]
    assert event["linked_markets"] == ["BRENT", "WTI"]
    assert event["market_sync_confirmed"] is True
    assert event["linkage_state"] == "synchronized_evidence"
    assert "BRENT +1.50%" in event["stock_observation"]
    assert "WTI +2.20%" in event["stock_observation"]


def test_stale_linked_market_never_confirms_sync_or_direction():
    snapshot = {"indices": [
        {"ticker": "BRENT", "name": "Brent", "price": 94, "change_percent": 4.0, "freshness": "stale", "quality_freshness": "stale", "stale_used": True},
        {"ticker": "WTI", "name": "WTI", "price": 90, "change_percent": 3.0, "freshness": "recent_close", "quality_freshness": "fresh", "stale_used": False},
    ]}
    row = _row(8)
    row.update({"chinese_translation": "油品供應中斷", "possible_impact": "可能推升油價。"})
    event = project_financialjuice_priority([row], market_snapshot=snapshot)["events"][0]
    assert event["linked_markets"] == ["BRENT", "WTI"]
    assert event["market_sync_confirmed"] is False
    assert event["linkage_state"] == "linked_data_stale"
    assert "不做方向判定" in event["stock_observation"]


def test_fj_market_evidence_recovers_us10y_freshness_from_date_and_price():
    row = _row(10)
    row.update({
        "chinese_translation": "伊朗：美國攻擊電信和通信基礎設施。",
        "possible_impact": "可能影響美國利率預期。",
    })
    snapshot = {
        "macro_quotes": [{
            "ticker": "US10Y",
            "name": "美國10年債殖利率",
            "market": "global",
            "price": 4.79,
            "change_percent": -0.21,
            "quote_date": "2026-09-02",
        }],
    }

    event = project_financialjuice_priority([row], market_snapshot=snapshot)['events'][0]

    evidence = next(item for item in event['market_evidence'] if item['ticker'] == 'US10Y')
    assert evidence['freshness'] == 'recent_close'
    assert evidence['data_status'] == '最近收盤'
