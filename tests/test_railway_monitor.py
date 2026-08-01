from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "app.py"
SPEC = spec_from_file_location("railway_monitor_app", MODULE_PATH)
assert SPEC and SPEC.loader
monitor = module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def test_macro_flash_is_classified_and_compacted_for_watch_delivery():
    flash = monitor.Flash("1", "美國 CPI 公布", "年增率高於市場預期，美元走強。", "2026-07-26T20:30:00+08:00")
    alert = monitor.alert_from_flash(flash)

    assert alert is not None
    assert alert.category == "macro"
    assert alert.summary.startswith("宏觀：")
    assert len(f"緊急｜宏觀｜{alert.summary}") <= 30


def test_unrelated_flash_is_not_forwarded():
    flash = monitor.Flash("2", "一般市場消息", "公司發布新品。", "2026-07-26T20:30:00+08:00")
    assert monitor.alert_from_flash(flash) is None


def test_material_oil_and_geopolitical_flash_is_sent_as_energy_alert():
    flash = monitor.Flash("oil-1", "Iran tensions lift WTI", "原油供應疑慮擴大，WTI 上漲 5%。", "2026-07-26T20:30:00+08:00")
    alert = monitor.alert_from_flash(flash)
    assert alert is not None
    assert alert.category == "energy"


def test_routine_oil_commentary_is_not_an_emergency_alert():
    flash = monitor.Flash("oil-2", "WTI 原油日報", "市場等待例行庫存資料。", "2026-07-26T20:30:00+08:00")
    assert monitor.alert_from_flash(flash) is None


def test_black_swan_flash_requires_official_monitor_confirmation():
    flash = monitor.Flash("quake-1", "Major earthquake hits Japan", "A major earthquake triggers tsunami warnings", "2026-07-28T17:00:00+08:00")
    assert monitor.classify_flash(flash) == "black_swan"
    assert monitor.alert_from_flash(flash) is None


def test_confirmed_ceasefire_is_classified_as_material_positive_event():
    flash = monitor.Flash("truce-1", "Ceasefire agreement announced", "Officials confirm a ceasefire agreement", "2026-07-28T17:00:00+08:00")
    alert = monitor.alert_from_flash(flash)
    assert alert is not None
    assert alert.category == "material_positive"


def test_category_cooldown_allows_only_escalation_before_window_expires(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    first = monitor.Alert("a1", "policy", "政策：關稅消息", "2026-07-26T20:30:00+08:00")
    repeat = monitor.Alert("a2", "policy", "政策：關稅消息更新", "2026-07-26T20:31:00+08:00")
    escalation = monitor.Alert("a3", "policy", "政策：加徵關稅範圍擴大", "2026-07-26T20:32:00+08:00")
    assert store.may_dispatch(first, 1800)
    store.record_dispatch(first)
    assert not store.may_dispatch(repeat, 1800)
    assert store.may_dispatch(escalation, 1800)


def test_extract_flashes_reads_documented_jin10_item_shape():
    result = {"data": {"items": [{"id": "a1", "title": "", "content": "FOMC", "time": "2026-07-26T20:30:00+08:00"}]}}
    flashes = monitor.extract_flashes(result)
    assert [(flash.event_id, flash.content) for flash in flashes] == [("a1", "FOMC")]


def test_signature_covers_exact_github_payload_fields():
    alert = monitor.Alert("jin10-1", "macro", "宏觀：CPI", "2026-07-26T20:30:00+08:00")
    signature = monitor.sign(alert, "shared")
    assert signature.startswith("sha256=")
    assert len(signature) == len("sha256=") + 64


def test_gdelt_requires_two_trusted_publishers_with_the_same_concrete_anchor():
    articles = [
        monitor.DiscoveryArticle("Iran conflict raises oil risk", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Iran conflict puts markets on alert", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
        monitor.DiscoveryArticle("Routine market update", "https://bbc.com/c", "bbc.com", "2026-07-29T01:02:00+00:00"),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "conflict"
    assert alerts[0].source == "gdelt"
    assert {item["domain"] for item in alerts[0].evidence_payload} == {"reuters.com", "apnews.com"}


def test_gdelt_single_trusted_story_never_becomes_an_alert():
    article = monitor.DiscoveryArticle("Iran conflict raises oil risk", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00")
    assert monitor.cross_checked_gdelt_alerts([article]) == []


def test_gdelt_requires_shared_entity_and_action_not_only_a_topic_anchor():
    articles = [
        monitor.DiscoveryArticle("Iran conflict raises oil risk", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Iran war raises oil risk", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    assert monitor._matching_discovery_evidence(articles, "conflict", "iran") == ()


def test_gdelt_black_swan_headlines_wait_for_a_first_party_confirmation():
    articles = [
        monitor.DiscoveryArticle("Major earthquake hits Japan", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Japan earthquake triggers tsunami warning", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    assert monitor.cross_checked_gdelt_alerts(articles) == []


def test_discovery_cache_keeps_a_recent_success_for_rate_limit_fallback(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    payload = [{"title": "Iran conflict", "url": "https://www.reuters.com/a", "domain": "reuters.com", "seen_at": "2026-07-29T01:00:00+00:00"}]
    store.write_cache("gdelt-success", payload)
    assert store.read_cache("gdelt-success", 15 * 60) == payload


def test_list_flash_argument_uses_limit_only_when_schema_supports_it():
    assert monitor.default_flash_arguments({"properties": {"limit": {}}}, 30) == {"limit": 30}
    assert monitor.default_flash_arguments({"properties": {}}, 30) == {}


def test_health_snapshot_exposes_source_diagnostics_without_secrets():
    monitor.update_health("gdelt", enabled=True, status="failed", error="HTTPStatusError")
    snapshot = monitor.health_snapshot()
    assert snapshot["status"] == "ok"
    assert snapshot["service"] == "prstk-jin10-monitor"
    assert snapshot["gdelt"]["status"] == "failed"
    assert snapshot["gdelt"]["error"] == "HTTPStatusError"
    assert "JIN10_MCP_TOKEN" not in str(snapshot)
    assert "GITHUB_DISPATCH_TOKEN" not in str(snapshot)
