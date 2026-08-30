from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "production-acceptance-photo.yml").read_text(
    encoding="utf-8"
)


def test_single_recipient_is_masked_before_checkout_and_not_job_level_env() -> None:
    mask_step = WORKFLOW.index("Mask the single recipient before any job output")
    checkout_step = WORKFLOW.index("actions/checkout@")
    text_step = WORKFLOW.index("Verify release and send one text")
    assert mask_step < checkout_step < text_step
    assert "TELEGRAM_CHAT_IDS: ${{ inputs.test_chat_id }}" not in WORKFLOW.split("steps:", 1)[0]
    assert "env:\n          TELEGRAM_CHAT_IDS: ${{ inputs.test_chat_id }}" in WORKFLOW


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
