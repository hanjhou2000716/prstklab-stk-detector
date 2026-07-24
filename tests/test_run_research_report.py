import json

from src.run_research_report import default_sources, write_report


def test_default_sources_cover_two_markets_and_two_strategies(tmp_path):
    sources = default_sources(tmp_path)
    assert {(source["market"], source["strategy"]) for source in sources} == {
        ("taiwan", "momentum"), ("us", "momentum"), ("taiwan", "price_action"), ("us", "price_action"),
    }


def test_write_report_creates_dashboard_json(tmp_path):
    output = tmp_path / "site" / "data" / "research-report.json"
    write_report({"status": "測試"}, output)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "測試"
