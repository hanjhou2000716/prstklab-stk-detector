import importlib.util

from src.financialjuice_notification import (
    deliver_financialjuice_event,
    financialjuice_caption,
    financialjuice_public_short_message,
)
from src.financialjuice_notification_e2e import run_financialjuice_notification_e2e
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url


def _railway_email_router():
    spec = importlib.util.spec_from_file_location("fj_email_router_e2e", "railway-monitor/email_router.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_financialjuice_notification_e2e_is_offline_and_replay_safe() -> None:
    result = run_financialjuice_notification_e2e()
    assert result["ok"] is True
    assert result["network_used"] is False
    assert result["secrets_used"] is False
    assert result["production_side_effects"] is False
    assert result["checks"]["vendor_score_does_not_change_risk"] is True
    assert result["checks"]["partial_delivery_isolated"] is True
    assert result["checks"]["retry_only_failed_recipient"] is True
    assert result["checks"]["replay_suppressed"] is True


def test_financialjuice_caption_hides_internal_risk_grade() -> None:
    caption = financialjuice_caption({
        "title": "Oil supply disruption",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
    })
    assert "FJ 8/10" in caption
    assert all(level not in caption for level in ("R0", "R1", "R2", "R3", "R4"))


def test_financialjuice_long_english_headline_keeps_discovery_text() -> None:
    caption = financialjuice_caption({
        "title": "Federal Reserve announces emergency liquidity support measures",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
    })
    assert caption.startswith("🟣 FJ 8/10｜")
    assert "Federal" in caption
    assert "資訊待核對" not in caption
    assert len(caption) <= 40


def test_financialjuice_caption_prefers_projected_event_over_generic_title() -> None:
    caption = financialjuice_caption({
        "title": "FinancialJuice 公開快訊",
        "event": "某公司據報正在評估合作",
        "vendor_importance": 10,
        "prstk_risk": {"prstk_risk_level": "R0"},
    })
    assert caption.startswith("🟣 FJ 10/10｜某公司據報")
    assert "FinancialJuice 公開快訊" not in caption
    assert len(caption) <= 40


def test_financialjuice_public_short_message_is_the_release_headline_contract() -> None:
    event = {
        "source_key": "financialjuice",
        "title": "據《The...",
        "event": "Nscale稱Anthropic合約簽約營收逾千億美元。",
        "vendor_importance": 9,
        "prstk_risk_level": "R2",
    }
    message = financialjuice_public_short_message(event)
    assert message == "🟣 FJ 9/10｜Nscale稱Anthropic合約簽約營收逾千億美元。"
    assert financialjuice_caption(event) == message
    assert len(message) <= 40
    assert "據《The" not in message


def test_financialjuice_incomplete_attribution_is_not_deliverable() -> None:
    assert financialjuice_caption({"title": "據《The...", "vendor_importance": 9}) == ""


def test_financialjuice_compresses_real_nscale_event_to_one_complete_sentence() -> None:
    caption = financialjuice_caption({
        "event": (
            "據《The Information》報導，AI雲端及基礎設施公司 Nscale 在贏得 "
            "Anthropic 的合約後，宣稱其已簽約的合約營收總額已超過1,000億美元。"
        ),
        "vendor_importance": 9,
    })
    assert caption == "🟣 FJ 9/10｜Nscale稱Anthropic合約簽約營收逾千億美元。"
    assert len(caption) <= 40
    assert "據《" not in caption
    assert "…" not in caption and "..." not in caption
    assert caption.count("｜") == 1


def test_financialjuice_uses_complete_fallback_when_title_is_truncated() -> None:
    caption = financialjuice_caption({
        "title": "據《The...",
        "vendor_original_headline": "Iran says U.S. strikes telecommunications infrastructure.",
        "vendor_importance": 9,
    })
    assert caption.startswith("🟣 FJ 9/10｜Iran says U.S. strikes")
    assert "據《The" not in caption
    assert "U.…" not in caption
    assert len(caption) <= 40


def test_financialjuice_delivery_suppresses_incomplete_attribution() -> None:
    calls: list[dict[str, object]] = []

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        calls.append(kwargs)
        return ()

    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "incomplete-1",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "notification_status": "eligible",
            "title": "據《The...",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )
    assert result["status"] == "blocked"
    assert result["reasons"] == ["content_incomplete"]
    assert calls == []


def test_financialjuice_delivery_reaches_text_sender_with_alert_deep_link() -> None:
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "fj-cluster-1",
        "observation_id": "fj-observation-1",
        "item_id": "fj-item-1",
        "vendor_importance": 8,
        "vendor_priority_notification": True,
        "notification_status": "eligible",
        # The generic risk classifier may remain blocked for an R2 discovery;
        # FJ >=8 is the deliberate vendor-priority exception.
        "notification": {"allowed": False, "status": "pending"},
        "prstk_risk": {"prstk_risk_level": "R2"},
        "title": "Oil supply update",
    }
    captured: dict[str, object] = {}

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "recipient-hash", "delivered", message_id=1,
            observation_id=kwargs.get("observation_id", ""),
        ),)

    result = deliver_financialjuice_event(
        event,
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )

    assert result["status"] == "delivered"
    assert captured["target_url"] == alert_mini_app_url(
        "https://example.test/app",
        alert_id="fj-cluster-1",
        release_id="release-1",
        snapshot_id="snapshot-1",
        observation_id="fj-observation-1",
    )


def test_financialjuice_delivery_returns_safe_failure_classes() -> None:
    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "fj-failed-classification",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "notification_status": "eligible",
            "title": "Oil supply update",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=lambda **_kwargs: (TextDeliveryReceipt(
            "alert", "release-1", "snapshot-1", "recipient-hash", "failed",
            error_class="recipient_unavailable",
        ),),
    )
    assert result["status"] == "failed"
    assert result["failure_classes"] == ["recipient_unavailable"]
    assert "recipient-hash" in str(result["receipts"])


def test_financialjuice_delivery_prefers_notification_id_for_alert_deep_link() -> None:
    event = {
        "source_key": "financialjuice", "notification_id": "fj-notification-1",
        "event_cluster_key": "fj-cluster-1", "observation_id": "fj-observation-1",
        "vendor_importance": 8, "vendor_priority_notification": True,
        "notification_status": "eligible", "prstk_risk_level": "R0",
        "title": "Oil supply update",
    }
    captured: dict[str, object] = {}

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        captured.update(kwargs)
        return (TextDeliveryReceipt(kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"], "h", "delivered", message_id=1),)

    deliver_financialjuice_event(
        event, release_id="release-1", snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app", release_ready=True,
        token="token", chat_ids=("recipient",), text_sender=sender,
    )
    assert captured["alert_id"] == "fj-notification-1"


def test_rich_email_to_priority_to_telegram_preserves_semantics() -> None:
    router = _railway_email_router()
    parsed = router.parse_email({
        "gmail_message_id": "g5-rich-e2e",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice alert",
        "body": (
            "Importance: 10/10\n"
            "Original headline: Reported AI partnership review\n"
            "Translation: 某公司據報正在評估與某 AI 晶片供應商合作\n"
            "AI commentary: 若合作成真，可能代表該公司 AI 基礎建設需求進一步提高，但目前仍未正式確認。\n"
            "Possible impact: 可能影響 AI 伺服器、GPU、相關供應鏈個股情緒。"
        ),
    })
    from src.financialjuice_priority import project_financialjuice_priority

    assert parsed["public_observations"][0]["vendor_original_headline"] == "Reported AI partnership review"
    event = project_financialjuice_priority(parsed["public_observations"])["events"][0]
    telegram_text = financialjuice_caption(event)
    assert event["event"] == "某公司據報正在評估與某 AI 晶片供應商合作"
    assert event["why_important"].endswith("目前仍未正式確認。")
    assert event["possible_linkage"].startswith("可能影響 AI 伺服器")
    assert "某公司據報" in telegram_text
    assert "FinancialJuice 公開快訊" not in telegram_text
    assert event["prstk_risk_level"] == "R0"
    assert event["vendor_priority_notification"] is True
