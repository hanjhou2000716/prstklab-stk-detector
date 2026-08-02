from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import threading


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


def test_chinese_deescalation_headline_is_material_positive():
    flash = monitor.Flash(
        "trump-iran-1",
        "美國總統特朗普：我已同意取消對伊朗的攻擊。",
        "",
        "2026-08-02T10:06:55+08:00",
    )
    alert = monitor.alert_from_flash(flash)
    assert alert is not None
    assert alert.category == "material_positive"


def test_chinese_geopolitical_escalation_is_conflict_candidate():
    flash = monitor.Flash(
        "iran-attack-1",
        "美國對伊朗發動攻擊，市場關注原油與航運風險",
        "",
        "2026-08-02T10:06:55+08:00",
    )
    assert monitor.classify_flash(flash) == "conflict"


def test_keyword_matching_normalizes_full_width_text_and_case():
    flash = monitor.Flash(
        "full-width-fomc",
        "ＦＯＭＣ／聯準會聲明",
        "Powell indicated a policy decision.",
        "2026-08-02T10:06:55+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "fed"
    assert reason == "fed_keyword"


def test_keyword_database_matches_simplified_chinese_and_english_typo():
    simplified = monitor.Flash("cn-trump", "美国总统特朗普宣布新的关税政策", "", "2026-08-02T10:06:55+08:00")
    assert monitor.classify_flash(simplified) == "policy"
    typo = monitor.Flash("typo-fomc", "FOMC statement from the Federal Reserv", "", "2026-08-02T10:06:55+08:00")
    assert monitor.classify_flash(typo) == "fed"


def test_trump_taco_phrase_is_a_policy_alert():
    flash = monitor.Flash(
        "taco-1",
        "TACO trade: Trump backs down on tariff threats",
        "Markets assess another tariff pause.",
        "2026-08-02T10:06:55+08:00",
    )
    alert = monitor.alert_from_flash(flash)
    assert alert is not None
    assert alert.category == "policy"


def test_trump_tariff_deescalation_is_material_positive():
    flash = monitor.Flash(
        "trump-tariff-pause",
        "美國總統特朗普宣布暫緩關稅",
        "White House says the tariff deadline is extended.",
        "2026-08-02T10:06:55+08:00",
    )
    assert monitor.classify_flash(flash) == "material_positive"


def test_bare_trump_mention_does_not_trigger_an_alert():
    flash = monitor.Flash(
        "trump-speech",
        "Trump speaks at a campaign rally",
        "The speech contains no policy or market action.",
        "2026-08-02T10:06:55+08:00",
    )
    assert monitor.alert_from_flash(flash) is None


def test_geopolitical_war_is_black_swan_candidate_but_not_directly_sent():
    flash = monitor.Flash("war-1", "War escalates after missile attack", "Markets monitor supply disruption", "2026-08-02T10:06:55+08:00")
    assert monitor.classify_flash(flash) == "black_swan"
    assert monitor.alert_from_flash(flash) is None


def test_unclassified_reason_distinguishes_energy_context_from_no_keyword():
    routine_oil = monitor.Flash("oil-audit", "WTI 原油日報", "市場等待例行庫存資料。", "2026-08-02T10:00:00+00:00")
    unrelated = monitor.Flash("unrelated-audit", "一般市場消息", "公司發布新品。", "2026-08-02T10:00:00+00:00")
    assert monitor.classify_flash_with_reason(routine_oil) == (None, "energy_requires_material_context")
    assert monitor.classify_flash_with_reason(unrelated) == (None, "keyword_no_match")


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


def test_legacy_unclassified_event_can_be_reclassified_after_keyword_update(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    assert store.add_if_new("legacy-1")
    assert store.classification_for("legacy-1") == "unclassified"
    assert store.claim_classification("legacy-1", "in_scope")
    assert store.classification_for("legacy-1") == "in_scope"
    assert not store.claim_classification("legacy-1", "in_scope")


def test_new_event_is_not_claimed_twice_during_baseline(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    assert store.claim_classification("new-1", "in_scope")
    store.set_classification("new-1", "baseline")
    assert not store.claim_classification("new-1", "in_scope")


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


def test_gdelt_can_discover_a_trump_iran_deescalation_event():
    articles = [
        monitor.DiscoveryArticle("Trump agrees to cancel attack on Iran", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Trump cancels attack on Iran after talks", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "material_positive"


def test_gdelt_single_trusted_story_never_becomes_an_alert():
    article = monitor.DiscoveryArticle("Iran conflict raises oil risk", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00")
    assert monitor.cross_checked_gdelt_alerts([article]) == []


def test_gdelt_requires_shared_entity_and_action_not_only_a_topic_anchor():
    articles = [
        monitor.DiscoveryArticle("Iran conflict raises oil risk", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Iran war raises oil risk", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    assert monitor._matching_discovery_evidence(articles, "conflict", "iran") == ()


def test_gdelt_supports_chinese_entity_and_action_aliases():
    articles = [
        monitor.DiscoveryArticle("特朗普宣布對伊朗停火", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("川普與伊朗達成停火協議", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "material_positive"


def test_gdelt_can_discover_a_trump_taco_policy_reversal():
    articles = [
        monitor.DiscoveryArticle("TACO trade: Trump backs down on tariffs", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("TACO tariff reversal: Trump changes tariff threat after talks", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "policy"


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


def test_seen_store_persists_incoming_event_and_retryable_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    flash = monitor.Flash("f-1", "FOMC", "rate decision", "2026-08-02T10:00:00+00:00")
    store.record_incoming_flash(flash)
    assert store.claim_classification(flash.event_id, "in_scope")
    alert = monitor.Alert("jin10-f-1", "fed", "快訊｜Fed｜利率決策", flash.occurred_at)
    trace_id = store.record_outbox(alert, {"trace_id": "pending"})
    store.mark_outbox(trace_id, "failed", "TimeoutException")
    store.release_classification(flash.event_id, "TimeoutException")

    row = store.connection.execute(
        "SELECT status, attempts, last_error FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    incoming = store.connection.execute(
        "SELECT classification, last_error FROM incoming_events WHERE event_id = ?", (flash.event_id,)
    ).fetchone()
    assert row == ("failed", 1, "TimeoutException")
    assert incoming == ("unclassified", "TimeoutException")
    assert store.classification_for(flash.event_id) == "unclassified"


def test_seen_store_persists_classification_reason_and_health_counts(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    flash = monitor.Flash("audit-1", "一般市場消息", "公司發布新品。", "2026-08-02T10:00:00+00:00")
    store.record_incoming_flash(flash, "keyword_no_match")
    assert store.classification_diagnostics() == {
        "classification_counts": {"unclassified": 1},
        "reason_counts": {"keyword_no_match": 1},
        "unclassified_count": 1,
    }


def test_alert_trace_id_is_stable_and_non_secret():
    alert = monitor.Alert("jin10-1", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    assert monitor.alert_trace_id(alert) == monitor.alert_trace_id(alert)
    assert "jin10" in monitor.alert_trace_id(alert)


def test_seen_store_persists_authenticated_delivery_receipt(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("jin10-receipt", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = store.record_outbox(alert, {"summary": alert.summary})
    assert store.record_delivery_status({
        "trace_id": trace_id,
        "delivery_status": "partial",
        "delivered_count": 3,
        "failed_count": 1,
        "failed_recipient_hashes": ["deadbeef"],
        "reported_at": "2026-08-02T10:01:00+00:00",
    })
    row = store.connection.execute(
        "SELECT status, last_error FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    receipt = store.connection.execute(
        "SELECT status FROM delivery_receipts WHERE trace_id = ? AND recipient_hash = 'deadbeef'", (trace_id,)
    ).fetchone()
    assert row == ("partial", "recipient delivery incomplete")
    assert receipt == ("failed",)
    snapshot = monitor.health_snapshot()
    assert snapshot["delivery"]["status"] == "partial"
    assert snapshot["delivery"]["last_receipt_status"] == "partial"
    assert snapshot["delivery"]["counts"]["partial"] == 1


def test_delivery_receipt_can_be_saved_from_health_server_thread(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("jin10-thread-receipt", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = store.record_outbox(alert, {"summary": alert.summary})
    result: list[bool] = []

    def callback_thread() -> None:
        result.append(store.record_delivery_status({
            "trace_id": trace_id,
            "delivery_status": "delivered",
            "delivered_count": 1,
            "failed_count": 0,
            "failed_recipient_hashes": [],
        }))

    thread = threading.Thread(target=callback_thread)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result == [True]
