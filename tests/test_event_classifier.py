from src.event_classifier import classify_event_fields, notification_gate


def test_classifier_reads_body_and_market_context_not_only_title():
    result = classify_event_fields({
        "title": "全球｜美國與伊朗局勢｜重要事件",
        "summary": "川普表示取消對伊朗的攻擊計畫，後續仍待核對。",
        "market_impact": "WTI 原油單日 -5.63%，航運風險受到關注。",
    })
    assert result["category"] == "material_positive"
    assert result["matched_terms"]


def test_iran_war_candidate_is_pending_without_official_and_sync():
    result = classify_event_fields({"title": "Iran war escalation", "what_happened": "shipping supply disruption"})
    assert result["category"] == "black_swan"
    gate = notification_gate(result["category"], official_confirmed=False, market_sync_confirmed=False)
    assert gate == {"status": "pending", "reasons": ["等待官方核對", "等待市場同步"]}


def test_non_strict_market_event_is_eligible():
    assert notification_gate("macro", official_confirmed=False, market_sync_confirmed=False) == {
        "status": "eligible", "reasons": []
    }
