from src.config import parse_chat_ids


def test_parse_chat_ids_prefers_multi_recipient_value_and_deduplicates():
    assert parse_chat_ids("100, 200\n100", "300") == ("100", "200", "300")
