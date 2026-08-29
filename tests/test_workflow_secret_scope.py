from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "scheduled-brief.yml"


def test_scheduled_collection_and_publication_do_not_receive_delivery_secrets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job_body = workflow.split("jobs:", 1)[1]
    notification_start = job_body.index("- name: Send Telegram brief")
    pre_notification = job_body[:notification_start]
    for secret in (
        "secrets.TELEGRAM_BOT_TOKEN",
        "secrets.TELEGRAM_CHAT_IDS",
        "secrets.DELIVERY_RECEIPT_SHARED_SECRET",
        "secrets.RAILWAY_STATUS_SHARED_SECRET",
    ):
        assert secret not in pre_notification


def test_scheduled_delivery_credentials_are_step_scoped() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    send_block = workflow.split("- name: Send Telegram brief", 1)[1].split("- name: Persist scheduled-brief delivery receipt", 1)[0]
    assert "secrets.TELEGRAM_BOT_TOKEN" in send_block
    assert "secrets.TELEGRAM_CHAT_IDS" in send_block
    creator_block = workflow.split("- name: Send release-gated Creator notifications", 1)[1].split("- name: Summarize Creator notification decision", 1)[0]
    assert "secrets.TELEGRAM_BOT_TOKEN" in creator_block
    assert "secrets.DELIVERY_RECEIPT_SHARED_SECRET" in creator_block
