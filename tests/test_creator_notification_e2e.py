from src.creator_notification_e2e import run_creator_notification_e2e


def test_creator_notification_e2e_is_offline_and_privacy_safe() -> None:
    report = run_creator_notification_e2e()

    assert report["ok"] is True
    assert report["network_used"] is False
    assert report["secrets_used"] is False
    assert report["production_side_effects"] is False
    assert report["recipient_count"] == 2
    assert report["receipt_statuses"] == ["delivered", "failed"]
    assert report["replay_status"] == "already_delivered"
    assert report["late_delta_status"] == "delivered"
