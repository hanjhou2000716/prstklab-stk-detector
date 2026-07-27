from pathlib import Path


def test_duplicate_brief_still_deploys_the_latest_dashboard_files():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")

    assert "The lock deduplicates the Telegram notification" in workflow
    deploy_section = workflow.split("- name: 設定 GitHub Pages", 1)[1]
    assert "steps.idempotency.outputs.cache-hit" not in deploy_section
