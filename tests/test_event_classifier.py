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


def test_policy_aliases_cover_trump_steel_and_oil_wording():
    steel = classify_event_fields({
        "title": "Trump tariff policy drives a surge in steel imports",
        "summary": "Markets assess the trade-policy impact.",
    })
    assert steel["category"] == "policy"

    oil = classify_event_fields({
        "title": "Chevron CEO urges Trump to lower Iranian oil prices",
        "summary": "Iranian oil and shipping risks remain in focus.",
    })
    assert oil["category"] == "energy"


def test_social_crime_story_does_not_become_currency_macro_event():
    result = classify_event_fields({
        "title": "29歲台男赴日當詐騙車手 詐老翁2千萬日圓",
        "metadata": "Fed rate decision NVDA oil",
        "interest_graph": {"topics": ["日圓", "Fed"]},
    })
    assert result["category"] is None
    assert result["decision_value_eligible"] is False
    assert "fed" not in result["text"]
    assert "oil" not in result["text"]


def test_bessent_hormuz_opinion_is_not_fed_without_energy_fact():
    result = classify_event_fields({
        "title": "貝森特：荷姆茲2年內將被繞過、對石油業毫無價值",
    })
    assert result["category"] is None


def test_structured_market_fact_requires_subject_and_action():
    result = classify_event_fields({"title": "US jobs data beats expectations as Nasdaq falls"})
    assert result["category"] == "macro"
    assert result["matched_subject"] == "jobs"
    assert result["matched_action"] == "data"
