from src.financialjuice_contract import build_financialjuice_envelope


def test_compound_envelope_keeps_items_independent_and_public_safe():
    envelope = build_financialjuice_envelope(
        [{"item_id": "fj-item-1", "original_headline": "one"}, {"item_id": "fj-item-2", "original_headline": "two"}],
        message_id="message-1",
    )
    payload = envelope.to_dict()
    assert payload["parse_status"] == "parsed"
    assert payload["item_count"] == 2
    assert [item["item_id"] for item in payload["items"]] == ["fj-item-1", "fj-item-2"]
    assert payload["public_safe"] is True


def test_unresolved_compound_is_explicit():
    result = build_financialjuice_envelope([], message_id="message-2", compound_unresolved=True).to_dict()
    assert result["parse_status"] == "compound_unresolved"
    assert result["compound_unresolved"] is True
