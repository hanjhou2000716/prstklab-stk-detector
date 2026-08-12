from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_tests_and_non_network_smoke_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt pytest" in workflow
    assert "pytest -q" in workflow
    assert "python -m compileall -q src railway-monitor" in workflow
    assert "python -m src.delivery_smoke_test" in workflow
    assert "python -m src.production_e2e" in workflow
    assert "TELEGRAM_BOT_TOKEN: \"\"" in workflow
    assert "--send" not in workflow


def test_notify_workflow_supports_an_explicit_single_recipient_smoke_test():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "notify.yml").read_text(encoding="utf-8")
    assert "test_chat_id:" in workflow
    assert "inputs.test_chat_id || secrets.TELEGRAM_CHAT_IDS" in workflow
    assert "photo_test:" in workflow
    assert "photo_test requires an explicit single test_chat_id" in workflow


def test_scheduled_production_workflow_installs_renderer_browser():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "send-only" in workflow
    assert "requirements-production.txt" in workflow
    assert "playwright install --with-deps chromium" in workflow


def test_scheduled_workflow_only_passes_explicit_external_creator_records():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "CREATOR_RECORDS_PATH" in workflow
    assert "-f \"$CREATOR_RECORDS_PATH\"" in workflow
    assert "--creator-records \"$CREATOR_RECORDS_PATH\"" in workflow


def test_event_production_workflows_install_renderer_browser():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in ("official-event-monitor.yml", "emergency-alert.yml"):
        workflow = (root / name).read_text(encoding="utf-8")
        assert "requirements-production.txt" in workflow
        assert "playwright install --with-deps chromium" in workflow


def test_public_release_smoke_workflow_is_read_only_and_non_delivery():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "public-release-smoke.yml").read_text(encoding="utf-8")
    assert "contents: read" in workflow
    assert "src.public_release_smoke" in workflow
    assert "TELEGRAM" not in workflow


def test_security_workflow_uses_current_pinned_sbom_action():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    assert "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610" in workflow
    assert "fallback_sbom.py" in workflow
    assert "steps.syft.outcome == 'failure'" in workflow
