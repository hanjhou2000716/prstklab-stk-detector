from src.event_classifier import build_haystack, classify_event_fields


def test_classifier_matches_traditional_and_simplified_policy_aliases():
    traditional = classify_event_fields("川普宣布加征關稅")
    simplified = classify_event_fields("特朗普宣布加征关税")
    assert traditional["category"] == "policy"
    assert simplified["category"] == "policy"


def test_classifier_matches_english_entities_and_actions_case_insensitively():
    result = classify_event_fields({"title": "TRUMP tariff policy", "summary": "Iran talks resume"})
    assert result["category"] == "policy"
    assert "tariff" in result["matched_terms"]


def test_classifier_uses_all_report_fields_for_geopolitical_context():
    result = classify_event_fields(
        {
            "title": "Global market watch",
            "what_happened": "Iran talks and shipping security",
            "market_impact": {"WTI": "-5.2%"},
        }
    )
    assert result["category"] == "conflict"
    assert result["matched_terms"]


def test_haystack_normalizes_spacing_and_unicode_width():
    assert "trump tariff" in build_haystack("ＴＲＵＭＰ\tTARIFF")


def test_unmatched_text_remains_explicitly_unclassified():
    result = classify_event_fields("ordinary company profile update")
    assert result["category"] is None
    assert result["reason"] == "keyword_no_match"
