from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_tests_and_non_network_smoke_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt pytest" in workflow
    assert "pytest -q" in workflow
    assert "python -m compileall -q src railway-monitor" in workflow
    assert "python -m src.delivery_smoke_test" in workflow
    assert "TELEGRAM_BOT_TOKEN: \"\"" in workflow
    assert "--send" not in workflow


def test_notify_workflow_supports_an_explicit_single_recipient_smoke_test():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "notify.yml").read_text(encoding="utf-8")
    assert "test_chat_id:" in workflow
    assert "inputs.test_chat_id || secrets.TELEGRAM_CHAT_IDS" in workflow
    assert "photo_test:" in workflow
    assert "python -m src.photo_smoke_test" in workflow
    assert "playwright install --with-deps chromium" in workflow


def test_scheduled_brief_installs_the_alert_card_renderer():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "python -m playwright install --with-deps chromium" in workflow
