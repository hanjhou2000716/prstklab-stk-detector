from pathlib import Path


def test_duplicate_brief_still_deploys_the_latest_dashboard_files():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")

    assert "The lock deduplicates the Telegram notification" in workflow
    deploy_section = workflow.split("- name: 設定 GitHub Pages", 1)[1]
    assert "steps.idempotency.outputs.cache-hit" not in deploy_section


def test_automatic_scheduled_dispatch_enables_notification_but_manual_stays_opt_in():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    assert "github.event_name == 'repository_dispatch' && 'true'" in workflow
    assert "inputs.notify && 'true'" in workflow


def test_release_policy_writes_outputs_without_corrupting_github_output():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    policy = workflow.split("- name: Resolve release publication policy", 1)[1].split(
        "- name: Publish snapshot and manifest", 1
    )[0]

    assert 'Path(os.environ["GITHUB_OUTPUT"]).open("a"' in policy
    assert 'publish = manifest.get("status") == "ready"' in policy
    assert 'print("::warning::Release manifest is not ready; preserving the previous immutable release.")' in policy
    assert "Publication and research delivery are separate gates" in policy
    assert 'run: |\n          python - <<\'PY\' >> "$GITHUB_OUTPUT"' not in policy


def test_research_policy_marks_stale_content_without_blocking_market_delivery():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    policy = workflow.split("- name: Resolve research delivery policy", 1)[1].split(
        "- name: Verify deployed release before delivery", 1
    )[0]

    assert 'Path(os.environ["GITHUB_OUTPUT"]).open("a"' in policy
    assert 'print("::warning::Research is stale or unverified; market delivery continues without research claims.")' in policy
    assert 'output.write("allow_telegram=true\\n")' in policy
    assert 'run: |\n          python - <<\'PY\' >> "$GITHUB_OUTPUT"' not in policy


def test_stale_research_fallback_does_not_block_market_pages_publication():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    publication = workflow.split("- name: Resolve release publication policy", 1)[1].split(
        "- name: Publish snapshot and manifest", 1
    )[0]
    research = workflow.split("- name: Resolve research delivery policy", 1)[1].split(
        "- name: Verify deployed release before delivery", 1
    )[0]

    # A stale fallback remains visible and auditable in Pages, while the
    # market delivery path remains eligible without research claims.
    assert 'publish = manifest.get("status") == "ready"' in publication
    assert 'include_research = freshness == "fresh"' in research
    assert 'allow_telegram=true' in research
