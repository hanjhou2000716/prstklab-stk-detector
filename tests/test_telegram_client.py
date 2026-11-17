from pathlib import Path

import pytest
import requests

from src import telegram_client
from src.telegram_client import (
    alert_mini_app_url,
    canonical_prstk_risk_level,
    canonical_short_message,
    classify_telegram_error,
    format_text_brief,
    is_valid_public_summary,
    mini_app_button,
    mini_app_menu_button,
    send_brief,
    send_briefs,
    send_photo_brief,
    send_text_briefs_audited,
    summarize_deliveries,
    summarize_photo_deliveries,
    summarize_public_message,
    validate_brief,
    versioned_mini_app_url,
)


def test_accepts_60_character_brief():
    validate_brief("測" * 60)


def test_shared_summary_handles_unicode_boundary_without_ellipsis():
    text = canonical_short_message("🟣 FJ 9/10｜" + "事件" * 23)
    assert text
    assert len(text) <= 60
    assert "…" not in text and "..." not in text


def test_classifies_telegram_failures_without_exposing_provider_details():
    assert classify_telegram_error(telegram_client.TelegramError("Bad Request: chat not found")) == "recipient_unavailable"
    assert classify_telegram_error(telegram_client.TelegramTransientError("HTTP 503")) == "temporary_transport"
    assert classify_telegram_error(telegram_client.TelegramError("HTTP 429: too many requests")) == "rate_limited"
    assert classify_telegram_error(telegram_client.TelegramError("Bad Request: malformed payload")) == "telegram_api"


def test_text_brief_hides_internal_risk_grade_and_stays_bounded():
    text = format_text_brief("台指波動觀察｜+2.9%｜等待官方核對", prstk_risk_level="R1")
    assert text.startswith("🟢 ")
    assert all(level not in text for level in ("R0", "R1", "R2", "R3", "R4"))
    assert len(text) <= 60


def test_canonical_short_message_preserves_colour_and_fj_vendor_score_without_risk_token():
    text = canonical_short_message("快訊｜台指波動觀察｜+2.9%｜R2", prstk_risk_level="R2")
    assert text.startswith("🟡 ")
    assert "R2" not in text
    assert len(text) <= 60

    fj = canonical_short_message("🟣 FJ 8/10｜R2｜北韓發射飛行物", prstk_risk_level="R2")
    assert fj.startswith("🟣 FJ 8/10｜")
    assert "R2" not in fj


def test_canonical_short_message_keeps_colour_cue_without_internal_grade():
    for level, icon in (("R0", "🟢"), ("R1", "🟢"), ("R2", "🟡"), ("R3", "🟠"), ("R4", "🔴")):
        text = canonical_short_message(f"{icon} {level}｜市場觀察｜資料待核對", prstk_risk_level=level)
        assert text.startswith(f"{icon} ")
        assert all(code not in text for code in ("R0", "R1", "R2", "R3", "R4"))


def test_public_photo_caption_removes_risk_grade_and_collapses_separators():
    from src.telegram_client import sanitize_public_photo_caption

    assert sanitize_public_photo_caption("🟡 R2｜市場觀察｜資料待核對") == "🟡 市場觀察｜資料待核對"
    assert sanitize_public_photo_caption("R4｜") == "市場資訊待核對"


def test_rejects_over_60_character_brief():
    with pytest.raises(ValueError, match="超過 60 字"):
        validate_brief("測" * 61)


def test_shared_summary_drops_incomplete_source_attribution_without_raw_cut():
    text = canonical_short_message("🟣 FJ 9/10｜據《The...", prstk_risk_level="R2")
    assert text == ""
    assert "據《The" not in text


def test_shared_summary_keeps_complete_event_fact_and_uses_word_boundary():
    text = canonical_short_message(
        "🟣 FJ 8/10｜Federal Reserve announces emergency liquidity support measures",
    )
    assert text.startswith("🟣 FJ 8/10｜Federal Reserve")
    assert len(text) <= 60
    assert "..." not in text
    assert "…" not in text


def test_shared_summary_never_uses_ellipsis_or_second_public_field_separator():
    text = canonical_short_message(
        "🟣 FJ 9/10｜Nscale稱Anthropic合約簽約營收逾千億美元。｜可能影響美股科技股。",
    )
    assert len(text) <= 60
    assert "…" not in text and "..." not in text
    assert text.count("｜") == 1
    assert text.endswith("。")


def test_shared_summary_drops_impact_fragment_when_no_complete_clause_fits():
    text = canonical_short_message(
        "🟣 FJ 10/10｜伊朗：美國攻擊電信和通信基礎設施。｜可能影響油價與美股能源股",
    )
    assert text == "🟣 FJ 10/10｜伊朗：美國攻擊電信和通信基礎設施，可能影響油價與美股能源股"


def test_rejects_blank_brief():
    with pytest.raises(ValueError, match="不可空白"):
        validate_brief("   ")


def test_mini_app_button_uses_telegram_web_app_field():
    assert mini_app_button("https://example.github.io/app/") == {
        "text": "📡 D.iNV Detector",
        "web_app": {"url": "https://example.github.io/app/"},
    }


def test_public_summary_keeps_only_the_structured_scheduled_icon():
    text = canonical_short_message(
        "🟡 📊晨報｜🔴 聯準會公布利率決策。",
        message_kind="scheduled_brief",
    )
    assert text == "📊 晨報｜聯準會公布利率決策。"
    assert text.count("📊") == 1
    assert all(icon not in text[1:] for icon in ("🟡", "🔴"))


def test_public_summary_removes_flags_skin_tones_and_keycap_decorations():
    text = canonical_short_message(
        "🇺🇸 👍🏽 🟡 📊晨報｜🔴 聯準會公布決策。",
        message_kind="scheduled_brief",
    )
    assert text == "📊 晨報｜聯準會公布決策。"
    assert len(text) <= 60


def test_public_summary_rejects_missing_fj_score_and_scheduled_body():
    assert canonical_short_message("FJ 待核對｜資料待核對", message_kind="financialjuice") == ""
    assert canonical_short_message("📊 晨報｜", message_kind="scheduled_brief") == ""
    assert canonical_short_message("聯準會公布決策。", message_kind="scheduled_brief", label="晨報") == "📊 晨報｜聯準會公布決策。"


def test_public_summary_rejects_standalone_fj_transport_fragment():
    assert canonical_short_message(
        "🟣 FJ 8/10｜直播影片", message_kind="financialjuice",
    ) == ""


def test_public_summary_validates_scheduled_shape_and_unknown_kind():
    assert is_valid_public_summary("📊 晨報｜聯準會公布決策。", source="scheduled_brief") is True
    assert is_valid_public_summary("📊 晨報｜🟡 聯準會公布決策。", source="scheduled_brief") is False
    assert is_valid_public_summary("📊 晨報｜聯準會|公布決策。", source="scheduled_brief") is False
    assert canonical_short_message("事件。", message_kind="unknown") == "🟡 事件。"


def test_public_summary_rejects_incomplete_conditional_fj_fact():
    assert canonical_short_message(
        "🟣 FJ 10/10｜聯準會表示如果通膨過熱。", message_kind="financialjuice",
    ) == ""
    accepted = canonical_short_message(
        "🟣 FJ 10/10｜聯準會表示如果通膨過熱，可能延後降息。",
        message_kind="financialjuice",
    )
    assert accepted.startswith("🟣 FJ 10/10｜")


def test_public_summary_keeps_unless_condition_and_consequence_together():
    accepted = canonical_short_message(
        "🟣 FJ 10/10｜除非通膨降溫，否則聯準會可能維持高利率。",
        message_kind="financialjuice",
    )
    assert accepted == "🟣 FJ 10/10｜除非通膨降溫，否則聯準會可能維持高利率。"
    assert canonical_short_message(
        "🟣 FJ 10/10｜除非通膨降溫。",
        message_kind="financialjuice",
    ) == ""


def test_structured_public_fact_preserves_subject_action_object_and_number():
    event = {
        "structured_fact": {
            "subject": "聯準會",
            "action": "表示",
            "object": "將維持高利率",
            "key_numbers": ["4.5%"],
        }
    }
    projection = telegram_client.structured_public_fact(event)
    assert projection["complete"] is True
    assert projection["text"] == "聯準會表示將維持高利率4.5%"


def test_mini_app_button_rejects_non_https_url():
    with pytest.raises(ValueError, match="HTTPS"):
        mini_app_button("http://example.test/app")


def test_versioned_mini_app_url_busts_webview_cache(monkeypatch):
    monkeypatch.setattr("src.telegram_client.time", lambda: 1.234)
    assert versioned_mini_app_url("https://example.github.io/app/") == "https://example.github.io/app/?v=1234"
    assert versioned_mini_app_url("https://example.github.io/app/?menu=1") == "https://example.github.io/app/?menu=1&v=1234"


def test_alert_mini_app_url_targets_published_alert_release_and_snapshot():
    assert alert_mini_app_url(
        "https://example.github.io/app/",
        alert_id="evt-1",
        release_id="rel-2",
        snapshot_id="snap-3",
    ) == "https://example.github.io/app/?alert=evt-1&release=rel-2&snapshot=snap-3&view=event"


def test_alert_mini_app_url_can_target_source_observation():
    target = alert_mini_app_url(
        "https://example.github.io/app/",
        alert_id="evt-1",
        release_id="rel-2",
        snapshot_id="snap-3",
        observation_id="obs-4",
    )
    assert target.endswith("&observation=obs-4")


def test_mini_app_menu_button_uses_persistent_web_app_shape():
    assert mini_app_menu_button("https://example.github.io/app/") == {
        "type": "web_app",
        "text": "📡D.iNV",
        "web_app": {"url": "https://example.github.io/app/"},
    }


def test_configure_mini_app_menus_isolates_unstarted_chat(monkeypatch):
    calls = []
    class Response:
        ok = True
        def __init__(self, chat_id): self.chat_id = chat_id
        def json(self):
            if self.chat_id == "blocked":
                return {"ok": False, "description": "bot was blocked by the user"}
            return {"ok": True}
    def post(url, json, timeout):
        calls.append(json)
        return Response(json.get("chat_id"))
    monkeypatch.setattr("src.telegram_client.requests.post", post)
    results = telegram_client.configure_mini_app_menus(token="t", chat_ids=("ok", "blocked"), mini_app_url="https://example.test")
    assert [item.delivered for item in results] == [True, False]
    assert len(calls) == 3


def test_send_briefs_rejects_empty_recipients():
    with pytest.raises(ValueError):
        send_briefs(token="t", chat_ids=(), text="ok", dashboard_url="https://example.test")


def test_send_brief_rejects_invalid_json_response(monkeypatch):
    class Response:
        ok = True
        status_code = 200
        def json(self): raise ValueError("bad json")
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(telegram_client.TelegramError):
        send_brief(token="t", chat_id="1", text="ok", dashboard_url="https://example.test")


def test_send_brief_uses_alert_deep_link_when_provided(monkeypatch):
    captured = {}

    class Response:
        ok = True
        status_code = 200
        def json(self): return {"ok": True, "result": {"message_id": 1}}

    def post(url, json, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", post)
    send_brief(
        token="t", chat_id="1", text="ok", dashboard_url="https://example.test",
        target_url="https://example.test/?alert=evt&release=rel&snapshot=snap&view=event",
    )
    assert captured["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"].startswith(
        "https://example.test/?alert=evt&release=rel&snapshot=snap&view=event&v="
    )


def test_send_briefs_delivers_to_each_configured_recipient(monkeypatch):
    calls = []

    class Response:
        ok = True

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, json, timeout):
        calls.append((url, json["chat_id"]))
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    results = send_briefs(
        token="token",
        chat_ids=("100", "200"),
        text="測試快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert len(results) == 2
    assert all(result.delivered for result in results)
    assert [chat_id for _, chat_id in calls] == ["100", "200"]


def test_send_briefs_keeps_other_recipients_running_when_one_has_not_started_bot(monkeypatch):
    class Response:
        def __init__(self, chat_id):
            self.ok = chat_id != "missing"

        def json(self):
            if self.ok:
                return {"ok": True, "result": {"message_id": 1}}
            return {"ok": False, "description": "Bad Request: chat not found"}

    monkeypatch.setattr(
        "src.telegram_client.requests.post",
        lambda url, json, timeout: Response(json["chat_id"]),
    )

    results = send_briefs(
        token="token",
        chat_ids=("available", "missing", "also-available"),
        text="市場快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert [result.delivered for result in results] == [True, False, True]
    assert results[1].error == "Bad Request: chat not found"


def test_send_brief_retries_temporary_connection_reset(monkeypatch):
    calls = 0

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 7}}

    def fake_post(url, json, timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.ConnectionError("connection reset")
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)

    result = send_brief(
        token="token",
        chat_id="100",
        text="測試快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert result.message_id == 7
    assert calls == 3


def test_send_briefs_records_temporary_failure_without_stopping_other_recipients(monkeypatch):
    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, json, timeout):
        if json["chat_id"] == "offline":
            raise requests.ConnectionError("connection reset")
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)

    results = send_briefs(
        token="token",
        chat_ids=("online", "offline", "also-online"),
        text="測試快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert [result.delivered for result in results] == [True, False, True]
    assert "temporary delivery failure" in (results[1].error or "")


def test_send_briefs_retries_only_failed_recipient(monkeypatch):
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 8}}

    def fake_post(url, json, timeout):
        calls.append(json["chat_id"])
        if json["chat_id"] == "offline" and calls.count("offline") <= 3:
            raise requests.ConnectionError("connection reset")
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)
    results = send_briefs(token="token", chat_ids=("online", "offline"), text="測試訊息", dashboard_url="https://example.test/app")

    assert [item.delivered for item in results] == [True, True]
    assert calls.count("online") == 1
    assert calls.count("offline") == 4
    summary = summarize_deliveries(results)
    assert (summary.delivered_count, summary.failed_count) == (2, 0)


def test_send_briefs_supports_multiple_bounded_recipient_retry_rounds(monkeypatch):
    calls = 0

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 10}}

    def fake_post(url, json, timeout):
        nonlocal calls
        calls += 1
        # The initial send_brief cycle uses three attempts.  The first
        # recipient-scoped retry also fails; the second one succeeds.
        if calls <= 4:
            raise requests.ConnectionError("connection reset")
        return Response()

    monkeypatch.setenv("TELEGRAM_FAILED_RECIPIENT_RETRIES", "2")
    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)

    results = send_briefs(
        token="token",
        chat_ids=("offline-then-online",),
        text="測試訊息",
        dashboard_url="https://example.test/app",
    )

    assert results[0].delivered
    assert calls == 5


def test_send_briefs_can_disable_recipient_scoped_retry(monkeypatch):
    calls = 0

    def fake_post(url, json, timeout):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("connection reset")

    monkeypatch.setenv("TELEGRAM_FAILED_RECIPIENT_RETRIES", "0")
    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)

    results = send_briefs(
        token="token",
        chat_ids=("offline",),
        text="測試訊息",
        dashboard_url="https://example.test/app",
    )

    assert not results[0].delivered
    assert calls == 3


def test_send_brief_honors_telegram_retry_after(monkeypatch):
    sleeps = []
    calls = 0

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code
            self.ok = status_code == 200

        def json(self):
            if self.status_code == 429:
                return {"ok": False, "parameters": {"retry_after": 7}}
            return {"ok": True, "result": {"message_id": 9}}

    def fake_post(url, json, timeout):
        nonlocal calls
        calls += 1
        return Response(429 if calls == 1 else 200)

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", sleeps.append)
    result = send_brief(token="token", chat_id="100", text="測試訊息", dashboard_url="https://example.test/app")
    assert result.message_id == 9
    assert sleeps == [7]


def test_public_summary_handles_zero_limit_and_invalid_risk_level():
    assert summarize_public_message("事件。", limit=0) == ""
    assert canonical_short_message("事件。", prstk_risk_level="not-a-risk") == "🟡 事件。"


def test_canonical_risk_level_reads_nested_legacy_and_safe_defaults():
    assert canonical_prstk_risk_level(None) == "R2"
    assert canonical_prstk_risk_level({"prstk_risk": {"prstk_risk_level": "R4"}}) == "R4"
    assert canonical_prstk_risk_level({"prstk_risk_level": "R1"}) == "R1"
    assert canonical_prstk_risk_level({"risk_level": "warning"}) == "R3"
    assert canonical_prstk_risk_level({"risk_level": "unknown"}) == "R2"


@pytest.mark.parametrize(
    "fact",
    ["", "…", "https://example.test/story", "直播影片", "🟣", "事件—."],
)
def test_financialjuice_fact_gate_rejects_transport_and_incomplete_fragments(fact):
    assert telegram_client._is_usable_financialjuice_fact(fact) is False


def test_public_summary_validator_rejects_transport_noise_and_bad_fj_shapes():
    assert is_valid_public_summary("這是一段……", source="") is False
    assert is_valid_public_summary("資訊 https://example.test", source="") is False
    assert is_valid_public_summary("市場觀察", source="") is False
    assert is_valid_public_summary("🟣 FJ 9/10｜事件｜另一段", source="financialjuice") is False
    assert is_valid_public_summary("🟣 FJ 9/10｜市場觀察", source="financialjuice") is False
    assert is_valid_public_summary("🟣 FJ 9/10｜🟣", source="financialjuice") is False
    assert is_valid_public_summary("🟣 FJ 9/10｜事件：", source="financialjuice") is False


def test_audited_text_delivery_records_success_and_failure_without_fail_fast(monkeypatch):
    def fake_send_brief(**kwargs):
        if kwargs["chat_id"] == "offline":
            raise requests.ConnectionError("connection reset")
        return telegram_client.TelegramResult(message_id=42)

    monkeypatch.setattr("src.telegram_client.send_brief", fake_send_brief)
    receipts = send_text_briefs_audited(
        token="token",
        chat_ids=("online", "offline"),
        text="市場事件。",
        dashboard_url="https://example.test/app",
        alert_id="alert",
        release_id="release",
        snapshot_id="snapshot",
    )
    assert [item.status for item in receipts] == ["delivered", "failed"]
    assert receipts[0].message_id == 42
    assert receipts[1].error_class == "temporary_transport"


def test_audited_fj_sender_preserves_producer_selected_summary(monkeypatch):
    captured = {}

    def fake_send_brief(**kwargs):
        captured.update(kwargs)
        return telegram_client.TelegramResult(message_id=7)

    monkeypatch.setattr("src.telegram_client.send_brief", fake_send_brief)
    text = "🟣 FJ 9/10｜標普500近350家公司下跌；聯準會決策前避險；10年債殖利率觸5%。"
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("online",), text=text,
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", message_kind="financialjuice",
    )
    assert receipts[0].status == "delivered"
    assert captured["text"] == text


def test_guarded_delivery_reserves_once_then_persists_telegram_message(monkeypatch):
    transitions = []
    monkeypatch.setattr(
        "src.telegram_delivery_guard.reserve_and_start",
        lambda **kwargs: telegram_client_guard_reservation(True, "sending", "attempt-1"),
    )
    monkeypatch.setattr(
        "src.telegram_delivery_guard.record_result",
        lambda **kwargs: transitions.append(kwargs) or kwargs["status"],
    )

    class Response:
        status_code = 200
        ok = True

        def json(self):
            return {"ok": True, "result": {"message_id": 42}}

    calls = []
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: calls.append(kwargs) or Response())
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="event-key",
    )

    assert len(calls) == 1
    assert [item["status"] for item in transitions] == ["delivered"]
    assert transitions[0]["attempt_id"] == "attempt-1"
    assert receipts[0].status == "delivered"
    assert receipts[0].message_id == 42


def test_guarded_delivery_fails_closed_when_guard_is_not_configured(monkeypatch):
    monkeypatch.delenv("RECEIPT_CALLBACK_URL", raising=False)
    telegram_calls = []
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: telegram_calls.append(args))
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="event-key",
    )
    assert telegram_calls == []
    assert receipts[0].status == "failed"
    assert receipts[0].error_class == "delivery_guard_not_configured"


def test_send_briefs_cannot_bypass_required_guard_with_missing_key(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DELIVERY_GUARD_REQUIRED", "true")
    telegram_calls = []
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: telegram_calls.append(args))

    deliveries = send_briefs(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app",
    )

    assert telegram_calls == []
    assert len(deliveries) == 1
    assert deliveries[0].delivered is False
    assert "notification key is missing" in (deliveries[0].error or "")


def test_production_guard_rejects_missing_notification_key_before_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DELIVERY_GUARD_REQUIRED", "true")
    telegram_calls = []
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: telegram_calls.append(args))
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot",
    )
    assert telegram_calls == []
    assert receipts[0].status == "failed"
    assert receipts[0].error_class == "delivery_guard_notification_key_missing"


def test_guarded_ambiguous_telegram_timeout_is_unknown_and_never_retried(monkeypatch):
    from src.telegram_delivery_guard import GuardReservation

    recorded = []
    monkeypatch.setattr(
        "src.telegram_delivery_guard.reserve_and_start",
        lambda **kwargs: GuardReservation(True, "sending", "attempt-1"),
    )
    monkeypatch.setattr(
        "src.telegram_delivery_guard.record_result",
        lambda **kwargs: recorded.append(kwargs) or kwargs["status"],
    )
    calls = []

    def timeout(*_args, **_kwargs):
        calls.append(1)
        raise requests.Timeout("response lost")

    monkeypatch.setattr("src.telegram_client.requests.post", timeout)
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="event-key",
    )
    assert len(calls) == 1
    assert recorded[0]["status"] == "delivery_unknown"
    assert receipts[0].status == "delivery_unknown"


def test_guarded_telegram_429_retries_once_after_explicit_retry_after(monkeypatch):
    from datetime import datetime

    from src.telegram_delivery_guard import GuardReservation

    recorded = []
    attempt_number = [0]

    def reserve(**_kwargs):
        attempt_number[0] += 1
        return GuardReservation(True, "sending", f"attempt-{attempt_number[0]}")

    monkeypatch.setattr(
        "src.telegram_delivery_guard.reserve_and_start",
        reserve,
    )
    monkeypatch.setattr(
        "src.telegram_delivery_guard.record_result",
        lambda **kwargs: recorded.append(kwargs) or kwargs["status"],
    )

    class RateLimited:
        ok = False
        status_code = 429

        @staticmethod
        def json():
            return {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}

    class Accepted:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 77}}

    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return RateLimited() if len(calls) == 1 else Accepted()

    monkeypatch.setattr("src.telegram_client.requests.post", post)
    delays = []
    monkeypatch.setattr("src.telegram_client.sleep", delays.append)
    receipts = send_text_briefs_audited(
        token="token", chat_ids=("1001",), text="市場事件已確認。",
        dashboard_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="event-key",
    )

    assert len(calls) == 2
    assert delays and 6 <= delays[0] <= 7
    assert [item["status"] for item in recorded] == ["retryable_failed", "delivered"]
    assert recorded[0]["status"] == "retryable_failed"
    assert isinstance(recorded[0]["retry_after_at"], datetime)
    assert receipts[0].status == "delivered"
    assert receipts[0].message_id == 77


def test_guarded_photo_429_retries_once_after_explicit_retry_after(monkeypatch, tmp_path):
    from src.telegram_delivery_guard import GuardReservation

    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    attempt_number = [0]
    recorded = []

    def reserve(**_kwargs):
        attempt_number[0] += 1
        return GuardReservation(True, "sending", f"photo-attempt-{attempt_number[0]}")

    monkeypatch.setattr("src.telegram_delivery_guard.reserve_and_start", reserve)
    monkeypatch.setattr(
        "src.telegram_delivery_guard.record_result",
        lambda **kwargs: recorded.append(kwargs) or kwargs["status"],
    )

    class RateLimited:
        ok = False
        status_code = 429

        @staticmethod
        def json():
            return {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}

    class Accepted:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 78}}

    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return RateLimited() if len(calls) == 1 else Accepted()

    monkeypatch.setattr("src.telegram_client.requests.post", post)
    delays = []
    monkeypatch.setattr("src.telegram_client.sleep", delays.append)
    receipt = send_photo_brief(
        token="token", chat_id="1001", caption="事件已確認", photo_path=image,
        mini_app_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="photo-event",
        telegram_file_id="cached-photo",
    )

    assert len(calls) == 2
    assert delays and 6 <= delays[0] <= 7
    assert [item["status"] for item in recorded] == ["retryable_failed", "delivered"]
    assert receipt.status == "delivered"
    assert receipt.message_id == 78
    assert receipt.telegram_file_id == "cached-photo"


def test_guarded_photo_ambiguous_timeout_is_not_retried(monkeypatch, tmp_path):
    from src.telegram_delivery_guard import GuardReservation

    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    recorded = []
    monkeypatch.setattr(
        "src.telegram_delivery_guard.reserve_and_start",
        lambda **kwargs: GuardReservation(True, "sending", "photo-attempt"),
    )
    monkeypatch.setattr(
        "src.telegram_delivery_guard.record_result",
        lambda **kwargs: recorded.append(kwargs) or kwargs["status"],
    )
    calls = []

    def timeout(*args, **kwargs):
        calls.append(args)
        raise requests.Timeout("response lost")

    monkeypatch.setattr("src.telegram_client.requests.post", timeout)
    receipt = send_photo_brief(
        token="token", chat_id="1001", caption="事件已確認", photo_path=image,
        mini_app_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot", notification_key="photo-event",
    )

    assert len(calls) == 1
    assert recorded[0]["status"] == "delivery_unknown"
    assert receipt.status == "delivery_unknown"


def test_production_photo_guard_rejects_missing_key_before_telegram(monkeypatch, tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    monkeypatch.setenv("TELEGRAM_DELIVERY_GUARD_REQUIRED", "true")
    calls = []
    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: calls.append(args))
    receipt = send_photo_brief(
        token="token", chat_id="1001", caption="事件已確認", photo_path=image,
        mini_app_url="https://example.test/app", alert_id="alert",
        release_id="release", snapshot_id="snapshot",
    )
    assert calls == []
    assert receipt.status == "failed"
    assert receipt.error_class == "delivery_guard_notification_key_missing"


def telegram_client_guard_reservation(allowed, status, attempt_id):
    from src.telegram_delivery_guard import GuardReservation

    return GuardReservation(allowed, status, attempt_id)


def test_audited_text_delivery_rejects_empty_recipients_invalid_risk_and_bad_summary():
    with pytest.raises(ValueError, match="recipient list"):
        send_text_briefs_audited(
            token="token", chat_ids=(), text="事件。", dashboard_url="https://example.test",
            alert_id="a", release_id="r", snapshot_id="s",
        )
    with pytest.raises(ValueError, match="R0-R4"):
        send_text_briefs_audited(
            token="token", chat_ids=("1",), text="事件。", dashboard_url="https://example.test",
            alert_id="a", release_id="r", snapshot_id="s", prstk_risk_level="bad",
        )
    with pytest.raises(ValueError, match="不完整"):
        send_text_briefs_audited(
            token="token", chat_ids=("1",), text="📊 晨報｜", dashboard_url="https://example.test",
            alert_id="a", release_id="r", snapshot_id="s", message_kind="scheduled_brief",
        )


def test_photo_delivery_handles_caption_request_and_json_failures(monkeypatch):
    photo = Path("site/assets/hero-prism-cover.png")
    with pytest.raises(ValueError, match="1-40"):
        send_photo_brief(
            token="token", chat_id="1", caption="x" * 41, photo_path=photo,
            mini_app_url="https://example.test/app", alert_id="a", release_id="r", snapshot_id="s",
        )

    def request_error(*args, **kwargs):
        raise requests.ConnectionError("connection reset")

    monkeypatch.setattr("src.telegram_client.requests.post", request_error)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)
    failed_transport = send_photo_brief(
        token="token", chat_id="1", caption="事件", photo_path=photo,
        mini_app_url="https://example.test/app", alert_id="a", release_id="r", snapshot_id="s",
    )
    assert failed_transport.status == "failed"
    assert failed_transport.error_class == "temporary_transport"

    class BadJsonResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            raise ValueError("bad json")

    monkeypatch.setattr("src.telegram_client.requests.post", lambda *args, **kwargs: BadJsonResponse())
    failed_json = send_photo_brief(
        token="token", chat_id="1", caption="事件", photo_path=photo,
        mini_app_url="https://example.test/app", alert_id="a", release_id="r", snapshot_id="s",
    )
    assert failed_json.status == "failed"
    assert failed_json.error_class == "telegram_api"


def test_photo_delivery_handles_retry_after_json_failure_and_summary(monkeypatch):
    calls = 0

    class Response:
        ok = True

        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            if self.status_code == 429:
                raise ValueError("bad retry metadata")
            return {"ok": True, "result": {"message_id": 8}}

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response(429 if calls == 1 else 200)

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    monkeypatch.setattr("src.telegram_client.sleep", lambda _: None)
    delivered = send_photo_brief(
        token="token", chat_id="1", caption="事件", photo_path=Path("site/assets/hero-prism-cover.png"),
        mini_app_url="https://example.test/app", alert_id="a", release_id="r", snapshot_id="s",
    )
    assert delivered.status == "delivered"
    assert calls == 2
    summary = summarize_photo_deliveries([
        delivered,
        telegram_client.PhotoDeliveryReceipt("a", "r", "s", "failed-hash", "failed"),
    ])
    assert (summary.delivered_count, summary.failed_count) == (1, 1)
    assert summary.any_delivered
