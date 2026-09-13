from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "production-acceptance-photo.yml").read_text(
    encoding="utf-8"
)


def test_acceptance_recipient_is_server_side_fixed_and_not_user_supplied() -> None:
    checkout_step = WORKFLOW.index("actions/checkout@")
    text_step = WORKFLOW.index("Verify release and send one text")
    assert checkout_step < text_step
    assert 'TELEGRAM_EDITOR_CHAT_ID: "8869592162"' in WORKFLOW
    assert "test_chat_id" not in WORKFLOW
    assert "TELEGRAM_CHAT_IDS: ${{ env.TELEGRAM_EDITOR_CHAT_ID }}" in WORKFLOW


def test_photo_acceptance_uses_the_same_valid_release_selector_as_pages() -> None:
    assert "python -m src.pages_release" in WORKFLOW
    assert "--require-production-research" in WORKFLOW
    assert "--preserve-public-url \"$DASHBOARD_URL\"" in WORKFLOW
    assert "python -m src.data_release --restore" not in WORKFLOW
    assert "sendPhoto" not in WORKFLOW
    assert "playwright install" not in WORKFLOW
    assert "production_text_acceptance" in WORKFLOW


def test_text_acceptance_uses_existing_production_receipt_contract() -> None:
    assert "DELIVERY_RECEIPT_KIND: production" in WORKFLOW
    assert "DELIVERY_RECEIPT_KIND: text_acceptance" not in WORKFLOW
