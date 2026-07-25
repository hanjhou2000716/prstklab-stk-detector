from pathlib import Path


def test_readme_documents_the_official_event_backup_dispatch():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "official-event-check" in readme
    assert "Official macro event monitor" in readme
    assert "cron-job.org" in readme
