from pathlib import Path


def test_pages_is_the_single_release_publisher():
    workflow = Path(".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "data_release --restore" in workflow
    assert "src.release_gate" in workflow
    assert "upload-pages-artifact" in workflow
    assert "concurrency:" in workflow


def test_research_publisher_restores_before_writing():
    workflow = Path(".github/workflows/unified-research-report.yml").read_text(encoding="utf-8")
    assert "data_release --restore" in workflow
    assert "data_release --publish" in workflow
