from pathlib import Path


def test_creator_release_rows_are_marked_production_after_pipeline_binding():
    document = (Path(__file__).parents[1] / "docs" / "integration-status.md").read_text(encoding="utf-8")
    assert "Creator release lineage" in document
    assert "Creator scheduled input" in document
    assert "| production |" in document
