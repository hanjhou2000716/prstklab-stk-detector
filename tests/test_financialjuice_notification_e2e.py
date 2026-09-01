from src.financialjuice_notification import deliver_financialjuice_event, financialjuice_caption
from src.financialjuice_notification_e2e import run_financialjuice_notification_e2e
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url


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
    assert len(caption) <= 30


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
