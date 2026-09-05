import pytest
import requests

from src import telegram_client
from src.telegram_client import (
    alert_mini_app_url,
    canonical_short_message,
    classify_telegram_error,
    format_text_brief,
    is_valid_public_summary,
    mini_app_button,
    mini_app_menu_button,
    send_brief,
    send_briefs,
    summarize_deliveries,
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
        "text": "開啟稜量速報系統",
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


def test_public_summary_rejects_missing_fj_score_and_scheduled_body():
    assert canonical_short_message("FJ 待核對｜資料待核對", message_kind="financialjuice") == ""
    assert canonical_short_message("📊 晨報｜", message_kind="scheduled_brief") == ""
    assert canonical_short_message("聯準會公布決策。", message_kind="scheduled_brief", label="晨報") == "📊 晨報｜聯準會公布決策。"


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
        "text": "稜量系統",
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
