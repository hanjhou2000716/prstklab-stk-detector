import asyncio
import os
import subprocess
import sys
import threading
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "app.py"
SPEC = spec_from_file_location("railway_monitor_app", MODULE_PATH)
assert SPEC and SPEC.loader
monitor = module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def test_delivery_shared_secret_accepts_canonical_railway_name(monkeypatch):
    monkeypatch.delenv("DELIVERY_STATUS_SHARED_SECRET", raising=False)
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "canonical")
    assert monitor._delivery_shared_secret() == "canonical"


def test_delivery_shared_secret_prefers_canonical_name(monkeypatch):
    monkeypatch.setenv("DELIVERY_STATUS_SHARED_SECRET", "service")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "legacy")
    assert monitor._delivery_shared_secret() == "legacy"


def test_health_snapshot_exposes_redacted_runtime_configuration(monkeypatch):
    monkeypatch.delenv("DELIVERY_STATUS_SHARED_SECRET", raising=False)
    monkeypatch.delenv("RAILWAY_STATUS_SHARED_SECRET", raising=False)
    snapshot = monitor.health_snapshot()
    assert snapshot["runtime_config"] == {
        "status": "configuration_missing",
        "delivery_secret_configured": False,
        "canonical_name_present": False,
        "legacy_name_present": False,
        "active_name": None,
        "migration_required": False,
        "secret_values_exposed": False,
    }


def test_health_history_survives_store_reopen_without_private_fields(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    sample = {
        "recorded_at": "2026-08-25T00:00:00+00:00",
        "overall_state": "partial",
        "failure_count": 1,
        "no_event_count": 0,
        "component_statuses": {"gdelt": "rate_limited"},
    }
    store.persist_health_sample(sample)
    monitor.restore_health_history([])
    reopened = monitor.SeenStore(tmp_path / "state.sqlite3")
    assert reopened.restore_health_history() == 1
    assert monitor.snapshot_health()["observability"]["history"]["samples"] == [sample]


def test_monitor_imports_shared_classifier_from_railway_root_without_repository_src_package():
    """The root-only Railway image must use the generated canonical bundle."""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    # pytest-cov exports COVERAGE_PROCESS_START so subprocesses can emit
    # parallel data.  This smoke subprocess runs from ``railway-monitor/``
    # (outside the project root), where coverage cannot resolve the same
    # pyproject branch configuration; its empty statement-only file then
    # causes coverage combine to fail.  Keep this import isolation test out
    # of the parent coverage session.
    environment.pop("COVERAGE_PROCESS_START", None)
    environment.pop("COVERAGE_FILE", None)
    # pytest-cov 6 injects the COV_CORE_* variables used by its subprocess
    # tracer.  Remove the full set so the isolation subprocess cannot create
    # a statement-only data file that later conflicts with the parent's
    # branch-enabled report.
    for coverage_key in (
        "COV_CORE_SOURCE",
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COV_CORE_BRANCH",
        "COV_CORE_CONTEXT",
    ):
        environment.pop(coverage_key, None)
    command = [
        sys.executable,
        "-c",
        "import app; assert app._CLASSIFIER_MODE == 'repository-shared'; "
        "assert not app._USING_STANDALONE_CLASSIFIER; "
        "assert app.classifier_delivery_allowed(); "
        "assert app.classify_event_fields({'title': 'WTI oil production update'})['category'] == 'energy'",
    ]
    result = subprocess.run(
        command,
        cwd=MODULE_PATH.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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


def test_historical_war_reference_with_kuwait_oil_production_is_energy():
    flash = monitor.Flash(
        "kuwait-oil-production",
        "Kuwait July oil production reaches its highest level since the Middle East war began",
        "The output increase is an energy-market development, not a new attack.",
        "2026-08-03T10:00:00+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "energy"
    assert reason == "energy_material_keyword"


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


def test_trump_iran_planned_strike_cancellation_alias_is_material_positive():
    flash = monitor.Flash(
        "trump-iran-planned-strike",
        "美國總統川普：我同意取消對伊朗的襲擊計畫。",
        "CNBC reports the planned attacks were called off.",
        "2026-08-03T10:06:55+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "material_positive"
    assert reason == "material_positive_keyword"


def test_chinese_geopolitical_escalation_is_conflict_candidate():
    flash = monitor.Flash(
        "iran-attack-1",
        "美國對伊朗發動攻擊，市場關注原油與航運風險",
        "",
        "2026-08-02T10:06:55+08:00",
    )
    assert monitor.classify_flash(flash) == "conflict"


def test_iran_gulf_context_requires_anchor_and_geopolitical_action():
    flash = monitor.Flash(
        "iran-gulf-context",
        "海灣股市上漲",
        "伊朗相關地緣情勢仍在發展，需觀察原油供給與航運中斷。",
        "2026-08-02T10:06:55+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "conflict"
    assert reason == "iran_gulf_context_market_keyword"


def test_iran_pressure_and_concession_aliases_are_conflict_candidates():
    flash = monitor.Flash(
        "iran-pressure",
        "\u4f0a\u6717\u5982\u4f55\u64f4\u5927\u65bd\u58d3\u4ee5\u8feb\u4f7f\u7f8e\u570b\u8b93\u6b65",
        "",
        "2026-08-03T10:06:55+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "conflict"
    assert reason == "iran_gulf_context_keyword"


def test_bare_gulf_market_move_does_not_trigger_geopolitical_alert():
    flash = monitor.Flash(
        "gulf-market-only",
        "海灣股市上漲",
        "投資人關注企業財報與市場成交量。",
        "2026-08-02T10:06:55+08:00",
    )
    assert monitor.alert_from_flash(flash) is None


def test_trump_iran_negotiation_deadline_is_a_conflict_candidate():
    flash = monitor.Flash(
        "trump-iran-talks",
        "全局｜美國與伊朗局勢｜重要事件",
        "川普稱伊朗談判於週一舉行，但未談妥，這是談判的最後期限。",
        "2026-08-03T10:06:55+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification == "conflict"
    assert reason == "iran_gulf_context_keyword"


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


def test_railway_bundle_catches_trump_policy_aliases_from_companion_headlines():
    flash = monitor.Flash(
        "trump-chevron-oil",
        "Chevron CEO urges Trump to lower Iranian oil prices",
        "Reuters reports the request while shipping risks remain in focus.",
        "2026-08-04T10:00:00+08:00",
    )
    classification, reason = monitor.classify_flash_with_reason(flash)
    assert classification in {"policy", "conflict"}
    assert reason in {"trump_policy_keyword", "iran_gulf_context_keyword", "iran_gulf_context_market_keyword", "conflict_keyword"}


def test_keyword_database_matches_simplified_chinese_and_english_typo():
    simplified = monitor.Flash("cn-trump", "美国总统特朗普宣布新的关税政策", "", "2026-08-02T10:06:55+08:00")
    assert monitor.classify_flash(simplified) == "policy"
    typo = monitor.Flash("typo-fomc", "FOMC statement from the Federal Reserv", "", "2026-08-02T10:06:55+08:00")
    assert monitor.classify_flash(typo) == "fed"


def test_standalone_keyword_bundle_matches_canonical_database():
    """The root-only Railway image must not silently use a reduced policy."""
    import json
    from pathlib import Path

    repository = Path(__file__).parents[1]
    canonical = json.loads(
        (repository / "config" / "event_keywords.json").read_text(encoding="utf-8")
    )
    bundled = json.loads(
        (repository / "railway-monitor" / "event_keywords.json").read_text(encoding="utf-8")
    )
    assert bundled == canonical


def test_shared_classifier_bundle_is_generated_from_canonical_source():
    script = Path(__file__).parents[1] / "scripts" / "sync_railway_shared_classifier.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_self_check_exposes_classifier_provenance():
    monitor.validate_runtime_layout()
    runtime = monitor.health_snapshot()["runtime"]
    assert runtime["classifier_mode"] == "repository-shared"
    assert len(runtime["classifier_source_sha256"]) == 64
    assert len(runtime["keyword_bundle_sha256"]) == 64


def test_fuzzy_matching_does_not_confuse_warning_or_escalation_with_other_terms():
    # ``war`` is a substring of ``warning`` and ``deescalation`` is close to
    # ``escalation``.  Neither should silently change the event category.
    escalation = monitor.Flash("escalation", "Iran military invasion risk escalation", "", "2026-08-02T10:06:55+08:00")
    normalized = monitor.normalized_event_text("routine warning")
    assert not monitor._keyword_in_text("war", normalized, normalized.replace(" ", ""))
    normalized = monitor.normalized_event_text("military escalation")
    assert not monitor._keyword_in_text("deescalation", normalized, normalized.replace(" ", ""))
    assert monitor.classify_flash(escalation) == "black_swan"
    assert monitor.classify_flash_with_reason(escalation)[1] == "black_swan_keyword"


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


def test_gdelt_discovers_kuwait_oil_production_as_energy_candidate():
    articles = [
        monitor.DiscoveryArticle(
            "Kuwait July oil production reaches highest level since Middle East war began",
            "https://www.reuters.com/a",
            "reuters.com",
            "2026-08-03T01:00:00+00:00",
        ),
        monitor.DiscoveryArticle(
            "Kuwaiti crude output hits a post-war high",
            "https://apnews.com/b",
            "apnews.com",
            "2026-08-03T01:01:00+00:00",
        ),
    ]
    category, anchor = monitor._discovery_category_and_anchor(articles[0].title, articles[0].snippet)
    assert category == "energy"
    assert anchor in {"kuwait", "kuwaiti", "oil", "oil production", "production", "crude oil"}
    entities, actions = monitor._discovery_facts(articles[0].title, category, anchor, articles[0].snippet)
    assert "gulf_region" in entities
    assert "energy_supply" in actions


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


def test_gdelt_normalizes_alternate_planned_strike_cancellation_phrases():
    articles = [
        monitor.DiscoveryArticle(
            "Trump agrees to cancel planned attacks on Iran",
            "https://www.cnbc.com/a",
            "cnbc.com",
            "2026-08-03T02:00:00+00:00",
        ),
        monitor.DiscoveryArticle(
            "Trump calls off planned strikes against Iran after talks",
            "https://www.reuters.com/b",
            "reuters.com",
            "2026-08-03T02:01:00+00:00",
        ),
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


def test_gdelt_can_discover_iran_gulf_geopolitical_market_context():
    articles = [
        monitor.DiscoveryArticle("Gulf stocks rise as Iran tensions keep oil supply risk elevated", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Persian Gulf markets react to Iran geopolitical tensions and shipping risk", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "conflict"


def test_gdelt_uses_article_snippet_for_iran_negotiation_context():
    articles = [
        monitor.DiscoveryArticle(
            "全局｜美國與伊朗局勢｜重要事件",
            "https://www.reuters.com/a",
            "reuters.com",
            "2026-07-29T01:00:00+00:00",
            "Trump says Iran talks failed to reach a deal and sets a deadline.",
        ),
        monitor.DiscoveryArticle(
            "全局｜美國與伊朗局勢｜重要事件",
            "https://apnews.com/b",
            "apnews.com",
            "2026-07-29T01:01:00+00:00",
            "Trump says Iran talks failed to reach a deal and the deadline remains.",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "conflict"


def test_gdelt_negotiation_aliases_share_one_canonical_action():
    """talks/dialogue/negotiations must satisfy the same action gate."""
    articles = [
        monitor.DiscoveryArticle(
            "Iran and the US hold talks",
            "https://www.reuters.com/iran-talks",
            "reuters.com",
            "2026-08-03T01:00:00+00:00",
            "Diplomatic dialogue continues over the nuclear issue.",
        ),
        monitor.DiscoveryArticle(
            "Iran US negotiations continue",
            "https://apnews.com/iran-negotiations",
            "apnews.com",
            "2026-08-03T01:01:00+00:00",
            "The two sides remain in dialogue and talks are ongoing.",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "conflict"


def test_gdelt_detects_bessent_yen_intervention_and_fed_support():
    articles = [
        monitor.DiscoveryArticle(
            "US Japan currency policy",
            "https://www.reuters.com/a",
            "reuters.com",
            "2026-08-02T01:00:00+00:00",
            "Bessent says Japan may repeat joint yen intervention and urges Federal Reserve support.",
        ),
        monitor.DiscoveryArticle(
            "Japan intervention risk rises",
            "https://www.cnbc.com/b",
            "cnbc.com",
            "2026-08-02T01:01:00+00:00",
            "Scott Bessent backs coordinated currency intervention and stronger Fed support.",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "fed"


def test_gdelt_pending_candidate_exposes_missing_second_source():
    articles = [
        monitor.DiscoveryArticle(
            "US Japan currency policy",
            "https://www.reuters.com/a",
            "reuters.com",
            "2026-08-02T01:00:00+00:00",
            "Bessent says Japan may repeat joint yen intervention and urges Federal Reserve support.",
        ),
    ]
    assert monitor.cross_checked_gdelt_alerts(articles) == []
    pending = monitor.pending_gdelt_candidates(articles)
    assert pending[0]["reason"] == "waiting_second_trusted_source"
    assert pending[0]["category"] == "fed"


def test_gdelt_merges_pressure_aliases_and_normalizes_reuters_cn():
    articles = [
        monitor.DiscoveryArticle(
            "Iran ramps up pressure to force US concessions",
            "https://reuters.cn/world/iran-pressure",
            "reuters.cn",
            "2026-08-03T01:00:00+00:00",
        ),
        monitor.DiscoveryArticle(
            "Iran increases pressure seeking concessions from Washington",
            "https://apnews.com/iran-pressure",
            "apnews.com",
            "2026-08-03T01:01:00+00:00",
        ),
    ]
    assert monitor._trusted_domain(articles[0].url, articles[0].domain) == "reuters.com"
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "conflict"


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


def test_gdelt_black_swan_with_market_sync_becomes_warning_alert():
    articles = [
        monitor.DiscoveryArticle("Major earthquake hits Japan", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Japan earthquake triggers tsunami warning", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    market_sync = {"indices": [{
        "ticker": "NIKKEI", "change_percent": -2.1,
        "quote_time": "2026-07-29T01:15:00+00:00",
    }]}
    alerts = monitor.cross_checked_gdelt_alerts(articles, market_sync)
    assert len(alerts) == 1
    assert alerts[0].category == "black_swan"
    assert alerts[0].risk_level == "警戒"
    assert alerts[0].official_confirmed is False
    assert alerts[0].market_sync_confirmed is True
    assert alerts[0].market_sync == ("NIKKEI",)


def test_gdelt_black_swan_escalation_variants_merge_with_market_sync():
    # One publisher may say "invasion" while another says "escalation".
    # They still describe one Iran conflict event and must share a cluster.
    articles = [
        monitor.DiscoveryArticle(
            "Iran military invasion risk rises",
            "https://www.reuters.com/iran-invasion",
            "reuters.com",
            "2026-08-03T00:50:00+00:00",
            "Military invasion risk threatens shipping routes.",
        ),
        monitor.DiscoveryArticle(
            "Iran conflict escalation threatens supply routes",
            "https://apnews.com/iran-escalation",
            "apnews.com",
            "2026-08-03T00:52:00+00:00",
            "The attack risk is rising across the region.",
        ),
    ]
    market_sync = {"quotes": [{
        "ticker": "WTI",
        "change_percent": -5.66,
        "quote_time": "2026-08-03T00:53:00+00:00",
        "quote_delayed": False,
    }]}
    alerts = monitor.cross_checked_gdelt_alerts(articles, market_sync)
    assert len(alerts) == 1
    assert alerts[0].category == "black_swan"
    assert alerts[0].risk_level == "警戒"
    assert alerts[0].market_sync == ("WTI",)


def test_gdelt_black_swan_pending_reason_exposes_missing_market_sync():
    articles = [
        monitor.DiscoveryArticle("Major earthquake hits Japan", "https://www.reuters.com/a", "reuters.com", "2026-07-29T01:00:00+00:00"),
        monitor.DiscoveryArticle("Japan earthquake triggers tsunami warning", "https://apnews.com/b", "apnews.com", "2026-07-29T01:01:00+00:00"),
    ]
    pending = monitor.pending_gdelt_candidates(articles, {"indices": []})
    assert pending[0]["reason"] == "waiting_market_sync_for_warning"


def test_gdelt_trump_iran_deescalation_is_not_dropped_as_missing_anchor():
    articles = [
        monitor.DiscoveryArticle(
            "Trump says he agreed to cancel planned attack on Iran",
            "https://www.cnbc.com/example-deescalation",
            "cnbc.com",
            "2026-08-02T02:00:00+00:00",
            "The US president said the planned strike was called off.",
        ),
        monitor.DiscoveryArticle(
            "Trump cancels planned strike on Iran after talks",
            "https://www.reuters.com/example-deescalation",
            "reuters.com",
            "2026-08-02T02:01:00+00:00",
            "The decision was described as a de-escalation.",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles, {})
    assert alerts
    assert alerts[0].category == "material_positive"


def test_gdelt_chinese_trump_iran_deescalation_is_detected():
    articles = [
        monitor.DiscoveryArticle(
            "\u7f8e\u570b\u7e3d\u7d71\u7279\u6717\u666e\uff1a\u6211\u5df2\u540c\u610f\u53d6\u6d88\u5c0d\u4f0a\u6717\u7684\u653b\u64ca",
            "https://www.cnbc.com/example-deescalation-zh",
            "cnbc.com",
            "2026-08-02T02:00:00+00:00",
        ),
        monitor.DiscoveryArticle(
            "\u7279\u6717\u666e\u53d6\u6d88\u5c0d\u4f0a\u6717\u7684\u8972\u64ca\u8a08\u756b",
            "https://www.reuters.com/example-deescalation-zh",
            "reuters.com",
            "2026-08-02T02:01:00+00:00",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles, {})
    assert alerts and alerts[0].category == "material_positive"


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


def test_health_snapshot_declares_preflight_source_states():
    snapshot = monitor.health_snapshot()
    assert snapshot["gdelt"]["event_scan"] in {"not_checked", "no_event", "has_events", "scan_failed"}
    assert "market_sync" in snapshot
    assert snapshot["market_sync"]["status"] in {
        "not_checked", "available", "configuration_missing", "http_error",
        "rate_limited", "invalid_payload", "failed",
    }


def test_gmail_public_health_projects_observability_without_private_cursors():
    diagnostics = {
        "watch": {
            "status": "healthy",
            "observability": {
                "last_received_at": "2026-08-14T00:00:00+00:00",
                "parser_error_count": 0,
                "state": "healthy",
            },
        },
        "store": {"cursor": {"last_history_id": "private", "last_message_id": "private"}},
    }
    fields = monitor._gmail_health_fields(diagnostics)
    assert fields["watch_status"] == "healthy"
    assert fields["observability"]["state"] == "healthy"
    assert "last_history_id" not in str(fields)
    assert "last_message_id" not in str(fields)


def test_gdelt_error_label_preserves_status_without_exposing_response_body():
    response = monitor.httpx.Response(429, request=monitor.httpx.Request("GET", "https://example.test"))
    error = monitor.httpx.HTTPStatusError("rate limited", request=response.request, response=response)
    assert monitor.gdelt_error_label(error) == "HTTP_429"
    assert monitor.gdelt_error_label(monitor.httpx.TimeoutException("slow")) == "timeout"
    assert monitor.gdelt_error_label(ValueError("invalid payload")) == "invalid_payload"


def test_gdelt_failure_health_marks_scan_failed_not_not_checked():
    observed_at = monitor.datetime(2026, 8, 24, 2, 0, tzinfo=monitor.timezone.utc)
    values = monitor.gdelt_failure_health(
        RuntimeError("upstream 429"),
        now=observed_at,
    )
    assert values["status"] == "failed"
    assert values["event_scan"] == "scan_failed"
    assert values["error"] == "RuntimeError"
    assert values["article_count"] == 0
    assert values["alert_count"] == 0
    assert values["last_failure_at"] == observed_at.isoformat()


def test_gdelt_request_uses_identifiable_json_headers(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"articles": []}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(monitor.httpx, "AsyncClient", Client)
    monkeypatch.setattr(monitor, "_GDELT_BACKOFF_UNTIL", 0.0)
    asyncio.run(monitor.fetch_gdelt_articles())
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-Agent"].startswith("PRStK-Stock-Detector/1.0")
    assert "github.com/hanjhou2000716/prstklab-stk-detector" in captured["headers"]["User-Agent"]


def test_gdelt_rate_limit_fallback_is_marked_stale_and_not_live(monkeypatch, tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    payload = [{
        "title": "Iran conflict",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
        "seen_at": "2026-08-09T01:00:00+00:00",
    }]
    store.write_cache("gdelt-success", payload)
    store.connection.execute(
        "UPDATE cache SET refreshed_at=? WHERE cache_key=?",
        ((monitor.datetime.now(monitor.timezone.utc) - monitor.timedelta(minutes=20)).isoformat(), "gdelt-success"),
    )
    store.connection.commit()

    request = monitor.httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc")
    response = monitor.httpx.Response(429, request=request, headers={"Retry-After": "60"})

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: Client())
    monitor._GDELT_BACKOFF_UNTIL = 0.0
    articles = asyncio.run(monitor.fetch_gdelt_articles(store))
    assert len(articles) == 1
    assert monitor._GDELT_LAST_FETCH_STATE == "stale_cache"
    assert monitor._GDELT_LAST_FETCH_ERROR == "HTTP_429"


def test_gdelt_rate_limit_cooldown_survives_process_restart(monkeypatch, tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    payload = [{
        "title": "Iran conflict",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
        "seen_at": "2026-08-09T01:00:00+00:00",
    }]
    store.write_cache("gdelt-success", payload)
    store.connection.execute(
        "UPDATE cache SET refreshed_at=? WHERE cache_key=?",
        ((monitor.datetime.now(monitor.timezone.utc) - monitor.timedelta(minutes=20)).isoformat(), "gdelt-success"),
    )
    store.connection.commit()
    request = monitor.httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc")
    response = monitor.httpx.Response(429, request=request, headers={"Retry-After": "300"})

    class RateLimitedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: RateLimitedClient())
    monitor._GDELT_BACKOFF_UNTIL = 0.0
    assert len(asyncio.run(monitor.fetch_gdelt_articles(store))) == 1
    assert store.read_cache("gdelt-rate-limit", 7200)

    # A restart loses module globals; the durable cache must still suppress
    # the immediate retry and use the bounded stale success.
    monitor._GDELT_BACKOFF_UNTIL = 0.0

    class NoRequestClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            raise AssertionError("rate-limit cooldown should prevent a request")

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: NoRequestClient())
    assert len(asyncio.run(monitor.fetch_gdelt_articles(store))) == 1
    assert monitor._GDELT_LAST_FETCH_STATE == "stale_cache"
    assert monitor._GDELT_LAST_FETCH_ERROR == "HTTP_429"


def test_gdelt_invalid_json_uses_recent_cache_and_stays_failed(monkeypatch, tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    payload = [{
        "title": "Iran talks",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
        "seen_at": "2026-08-09T01:00:00+00:00",
    }]
    store.write_cache("gdelt-success", payload)
    store.connection.execute(
        "UPDATE cache SET refreshed_at=? WHERE cache_key=?",
        ((monitor.datetime.now(monitor.timezone.utc) - monitor.timedelta(minutes=20)).isoformat(), "gdelt-success"),
    )
    store.connection.commit()

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            raise monitor.json.JSONDecodeError("invalid", "<html>", 0)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: Client())
    monitor._GDELT_BACKOFF_UNTIL = 0.0
    articles = asyncio.run(monitor.fetch_gdelt_articles(store))
    assert len(articles) == 1
    assert monitor._GDELT_LAST_FETCH_STATE == "stale_cache"
    assert monitor._GDELT_LAST_FETCH_ERROR == "invalid_json"
    assert store.read_cache("gdelt-rate-limit", 7200)

    # A restart must honor the malformed-response cooldown as well as a 429
    # cooldown, otherwise a non-JSON 200 response can create a retry storm.
    monitor._GDELT_BACKOFF_UNTIL = 0.0

    class NoRequestClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            raise AssertionError("malformed-response cooldown should prevent a request")

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: NoRequestClient())
    assert len(asyncio.run(monitor.fetch_gdelt_articles(store))) == 1
    assert monitor._GDELT_LAST_FETCH_STATE == "stale_cache"
    assert monitor._GDELT_LAST_FETCH_ERROR == "invalid_json"


def test_monitor_health_forbidden_is_degraded_but_nonfatal(monkeypatch):
    class Response:
        status_code = 403
        headers = {}

        def raise_for_status(self):
            raise AssertionError("403 must be handled without raising")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: Client())
    monitor._HEALTH_DISPATCH_BACKOFF_UNTIL = 0.0
    asyncio.run(monitor.dispatch_monitor_health(token="token", repository="owner/repo", gdelt={"status": "failed"}))
    assert monitor.health_snapshot()["gdelt"]["health_dispatch_status"] == "permission_denied"
    assert monitor.health_snapshot()["gdelt"]["health_dispatch_error"] == "HTTP_403"


def test_monitor_health_forbidden_is_bounded_until_permission_changes(monkeypatch):
    calls = 0

    class Response:
        status_code = 403
        headers = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return Response()

    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: Client())
    monitor._HEALTH_DISPATCH_BACKOFF_UNTIL = 0.0
    asyncio.run(monitor.dispatch_monitor_health(token="token", repository="owner/repo", gdelt={"status": "failed"}))
    asyncio.run(monitor.dispatch_monitor_health(token="token", repository="owner/repo", gdelt={"status": "failed"}))
    assert calls == 1
    assert monitor.health_snapshot()["gdelt"]["health_dispatch_status"] == "permission_denied"
    assert monitor.health_snapshot()["gdelt"]["health_dispatch_next_retry_at"]


def test_monitor_health_without_dispatch_configuration_is_explicit(monkeypatch):
    monitor._HEALTH_DISPATCH_BACKOFF_UNTIL = 0.0
    asyncio.run(monitor.dispatch_monitor_health(token="", repository="owner/repo", gdelt={"status": "failed"}))
    diagnostics = monitor.health_snapshot()["gdelt"]
    assert diagnostics["health_dispatch_status"] == "configuration_missing"
    assert diagnostics["health_dispatch_error"] == "missing_github_dispatch_configuration"


def test_monitor_health_429_honors_retry_after_then_accepts(monkeypatch):
    class Response:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected status {self.status_code}")

    class Client:
        def __init__(self):
            self.responses = [Response(429, {"Retry-After": "1"}), Response(204)]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return self.responses.pop(0)

    sleeps = []
    async def fake_sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(monitor.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)
    asyncio.run(monitor.dispatch_monitor_health(token="token", repository="owner/repo", gdelt={"status": "healthy"}))
    assert sleeps == [1]
    assert monitor.health_snapshot()["gdelt"]["health_dispatch_status"] == "healthy"


def test_monitor_heartbeat_marks_a_recent_completed_cycle_healthy():
    now = monitor.datetime(2026, 8, 4, 4, 0, tzinfo=monitor.timezone.utc)
    heartbeat = monitor.monitor_heartbeat({
        "poll_interval_seconds": 120,
        "last_cycle_started_at": "2026-08-04T03:58:00+00:00",
        "last_cycle_completed_at": "2026-08-04T03:59:00+00:00",
    }, now=now)

    assert heartbeat["heartbeat_status"] == "healthy"
    assert heartbeat["heartbeat_timeout_seconds"] == 300
    assert heartbeat["last_cycle_age_seconds"] == 60


def test_monitor_heartbeat_marks_a_blocked_cycle_stale():
    now = monitor.datetime(2026, 8, 4, 4, 0, tzinfo=monitor.timezone.utc)
    heartbeat = monitor.monitor_heartbeat({
        "poll_interval_seconds": 120,
        "last_cycle_started_at": "2026-08-04T03:50:00+00:00",
        "last_cycle_completed_at": "2026-08-04T03:54:59+00:00",
    }, now=now)

    assert heartbeat["heartbeat_status"] == "stale"
    assert heartbeat["last_cycle_age_seconds"] == 301


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


def test_outbox_persists_dispatch_body_and_exposes_due_retry(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("jin10-outbox", "energy", "WTI supply update", "2026-08-02T10:00:00+00:00")
    trace_id = monitor.alert_trace_id(alert)
    dispatch_payload = monitor.sign_dispatch_payload(
        monitor.build_dispatch_payload(alert, trace_id), alert, "test-secret"
    )
    store.record_outbox(alert, {"dispatch_payload": dispatch_payload})
    store.mark_outbox(trace_id, "failed", "TimeoutException")

    # The exponential backoff prevents a tight retry loop.
    assert store.due_outbox() == []
    store.connection.execute(
        "UPDATE delivery_outbox SET next_retry_at=? WHERE trace_id=?",
        ("2000-01-01T00:00:00+00:00", trace_id),
    )
    store.connection.commit()
    due = store.due_outbox()
    assert len(due) == 1
    assert due[0]["trace_id"] == trace_id
    assert due[0]["dispatch_payload"]["client_payload"]["signature"].startswith("sha256=")


def test_outbox_retry_reuses_stable_payload_and_marks_sent(tmp_path, monkeypatch):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("jin10-retry", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = monitor.alert_trace_id(alert)
    payload = monitor.sign_dispatch_payload(
        monitor.build_dispatch_payload(alert, trace_id), alert, "test-secret"
    )
    store.record_outbox(alert, {"dispatch_payload": payload})
    store.mark_outbox(trace_id, "failed", "TimeoutException")
    store.connection.execute(
        "UPDATE delivery_outbox SET next_retry_at=? WHERE trace_id=?",
        ("2000-01-01T00:00:00+00:00", trace_id),
    )
    store.connection.commit()
    calls: list[tuple[str, dict]] = []

    async def fake_dispatch(body, *, token, repository, trace_id):
        calls.append((trace_id, body))

    monkeypatch.setattr(monitor, "dispatch_repository_payload", fake_dispatch)
    delivered = asyncio.run(
        monitor.retry_due_outbox(
            store, token="token", repository="owner/repo", shared_secret="test-secret"
        )
    )
    assert delivered == 1
    assert calls == [(trace_id, payload)]
    assert store.connection.execute(
        "SELECT status, next_retry_at FROM delivery_outbox WHERE trace_id=?", (trace_id,)
    ).fetchone() == ("sent", None)


def test_outbox_state_distinguishes_replayable_legacy_rows(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    legacy = monitor.Alert("legacy-outbox", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = store.record_outbox(legacy, {"summary": legacy.summary})
    assert store.outbox_state(trace_id) == ("pending", False)
    current = monitor.Alert("current-outbox", "macro", "PCE release", "2026-08-02T10:00:00+00:00")
    current_trace = monitor.alert_trace_id(current)
    payload = monitor.sign_dispatch_payload(
        monitor.build_dispatch_payload(current, current_trace), current, "test-secret"
    )
    store.record_outbox(current, {"dispatch_payload": payload})
    assert store.outbox_state(current_trace) == ("pending", True)


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
    assert snapshot["delivery"]["last_receipt_trace_id"] == trace_id
    assert snapshot["delivery"]["receipt_matches_last_outbox"] is True
    assert snapshot["delivery"]["stale_receipt_status"] is None
    assert snapshot["delivery"]["counts"]["partial"] == 1
    assert snapshot["delivery"]["last_delivered_count"] == 3
    assert snapshot["delivery"]["last_failed_count"] == 1
    assert snapshot["delivery"]["last_recipient_count"] == 4
    assert snapshot["delivery"]["last_reported_at"] == "2026-08-02T10:01:00+00:00"
    assert snapshot["delivery"]["last_receipt_age_seconds"] >= 0
    assert snapshot["delivery"]["last_failed_recipient_hash_count"] == 1
    assert snapshot["delivery"]["recent"][0]["trace_id"] == trace_id
    assert snapshot["delivery"]["recent"][0]["source"] == "jin10"
    assert snapshot["delivery"]["recent"][0]["event_id"] == "jin10-receipt"
    assert snapshot["delivery"]["recent"][0]["category"] == "macro"
    assert snapshot["delivery"]["recent"][0]["receipt_status"] == "partial"
    assert snapshot["delivery"]["recent"][0]["recipient_count"] == 4


def test_seen_store_rejects_invalid_delivery_counters(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("delivery-counts", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = store.record_outbox(alert, {"summary": alert.summary})
    with pytest.raises(ValueError, match="invalid delivery counts"):
        store.record_delivery_status({
            "trace_id": trace_id,
            "delivery_status": "delivered",
            "delivered_count": -1,
            "failed_count": 0,
        })
    with pytest.raises(ValueError, match="invalid delivery counts"):
        store.record_delivery_status({
            "trace_id": trace_id,
            "delivery_status": "delivered",
            "delivered_count": True,
            "failed_count": 0,
        })


def test_seen_store_accepts_scoped_photo_smoke_receipt_without_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    trace_id = "photo-smoke-test-1234"
    assert store.record_delivery_status({
        "trace_id": trace_id,
        "receipt_kind": "photo_smoke",
        "release_id": "photo-smoke-test",
        "snapshot_id": "photo-smoke-test",
        "alert_id": "photo-smoke-test",
        "delivery_mode": "photo",
        "delivery_status": "delivered",
        "delivered_count": 1,
        "failed_count": 0,
        "failed_recipient_hashes": [],
    })
    row = store.connection.execute(
        "SELECT source,event_id,category,status FROM delivery_outbox WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()
    assert row == ("github_actions", "photo-smoke-test", "photo_smoke", "delivered")
    assert store.connection.execute(
        "SELECT status,delivered_count,failed_count FROM delivery_receipts WHERE trace_id=? AND recipient_hash='__aggregate__'",
        (trace_id,),
    ).fetchone() == ("delivered", 1, 0)


def test_seen_store_accepts_release_bound_photo_smoke_receipt_without_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    trace_id = "release-photo-smoke-1234"
    assert store.record_delivery_status({
        "trace_id": trace_id,
        "receipt_kind": "photo_smoke",
        "receipt_origin": "github_actions",
        "release_id": "release-abc",
        "snapshot_id": "snapshot-abc",
        "alert_id": "production-photo-smoke-release-abc",
        "delivery_mode": "photo",
        "delivery_status": "delivered",
        "delivered_count": 1,
        "failed_count": 0,
        "failed_recipient_hashes": [],
    })
    assert store.connection.execute(
        "SELECT status,delivered_count,failed_count FROM delivery_receipts WHERE trace_id=? AND recipient_hash='__aggregate__'",
        (trace_id,),
    ).fetchone() == ("delivered", 1, 0)


def test_seen_store_registers_signed_production_receipt_without_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    trace_id = "brief-production-test-1234"
    assert store.record_delivery_status({
        "trace_id": trace_id,
        "receipt_kind": "production",
        "receipt_origin": "github_actions",
        "release_id": "release-abc",
        "snapshot_id": "snapshot-abc",
        "alert_id": "brief-abc",
        "delivery_mode": "photo",
        "delivery_status": "partial",
        "delivered_count": 4,
        "failed_count": 3,
        "failed_recipient_hashes": ["deadbeef"],
    })
    row = store.connection.execute(
        "SELECT source,event_id,category,status FROM delivery_outbox WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()
    assert row == ("github_actions", "brief-abc", "production_receipt", "partial")
    assert store.connection.execute(
        "SELECT delivered_count,failed_count FROM delivery_receipts WHERE trace_id=? AND recipient_hash='__aggregate__'",
        (trace_id,),
    ).fetchone() == (4, 3)


def test_seen_store_registers_creator_receipt_without_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    trace_id = "creator-release-test-1234"
    assert store.record_delivery_status({
        "trace_id": trace_id,
        "receipt_kind": "creator",
        "receipt_origin": "github_actions",
        "release_id": "release-creator",
        "snapshot_id": "snapshot-creator",
        "alert_id": "creator-release-creator",
        "delivery_mode": "text",
        "delivery_status": "delivered",
        "delivered_count": 1,
        "failed_count": 0,
        "failed_recipient_hashes": [],
        "notification_keys": ["creator-episode-1", "creator-episode-2"],
    })
    row = store.connection.execute(
        "SELECT source,event_id,category,status FROM delivery_outbox WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()
    assert row == ("github_actions", "creator-release-creator", "creator_receipt", "delivered")
    history = store.delivery_history(limit=5)
    assert history[0]["notification_keys"] == ["creator-episode-1", "creator-episode-2"]
    assert store.connection.execute(
        "SELECT delivered_count,failed_count FROM delivery_receipts WHERE trace_id=? AND recipient_hash='__aggregate__'",
        (trace_id,),
    ).fetchone() == (1, 0)


def test_seen_store_rejects_unknown_production_receipt(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    assert store.record_delivery_status({
        "trace_id": "unknown-production-trace",
        "receipt_kind": "production",
        "delivery_status": "delivered",
        "delivered_count": 1,
        "failed_count": 0,
        "failed_recipient_hashes": [],
    }) is False


def test_delivery_diagnostics_does_not_apply_older_receipt_to_newer_outbox(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    first = monitor.Alert("older-delivery", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    first_trace = store.record_outbox(first, {"summary": first.summary})
    assert store.record_delivery_status({
        "trace_id": first_trace,
        "delivery_status": "partial",
        "delivered_count": 1,
        "failed_count": 1,
        "failed_recipient_hashes": ["old-failure"],
    })
    second = monitor.Alert("newer-delivery", "energy", "Oil update", "2026-08-02T10:02:00+00:00")
    second_trace = store.record_outbox(second, {"summary": second.summary})
    store.mark_outbox(second_trace, "sent")

    diagnostics = store.delivery_diagnostics()
    assert diagnostics["status"] == "sent"
    assert diagnostics["last_receipt_status"] is None
    assert diagnostics["last_receipt_trace_id"] is None
    assert diagnostics["receipt_matches_last_outbox"] is False
    assert diagnostics["stale_receipt_status"] == "partial"


def test_delivery_retention_prunes_only_old_terminal_rows_and_receipts(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    sent = monitor.Alert("old-sent", "macro", "CPI release", "2026-07-01T10:00:00+00:00")
    partial = monitor.Alert("old-partial", "energy", "Oil update", "2026-07-01T10:01:00+00:00")
    pending = monitor.Alert("old-pending", "policy", "Tariff update", "2026-07-01T10:02:00+00:00")
    sent_trace = store.record_outbox(sent, {"summary": sent.summary})
    partial_trace = store.record_outbox(partial, {"summary": partial.summary})
    pending_trace = store.record_outbox(pending, {"summary": pending.summary})
    store.mark_outbox(sent_trace, "sent")
    store.mark_outbox(partial_trace, "partial")
    old = "2026-01-01T00:00:00+00:00"
    store.connection.execute(
        "UPDATE delivery_outbox SET updated_at=? WHERE trace_id IN (?,?,?)",
        (old, sent_trace, partial_trace, pending_trace),
    )
    store.connection.execute(
        "INSERT INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
        (sent_trace, "recipient-a", "delivered", None, old),
    )
    store.connection.commit()

    assert store.prune_delivery_history(retention_days=30, limit=10) == 2
    remaining = {
        row[0]: row[1]
        for row in store.connection.execute(
            "SELECT trace_id,status FROM delivery_outbox ORDER BY trace_id"
        ).fetchall()
    }
    assert remaining == {pending_trace: "pending"}
    assert store.connection.execute(
        "SELECT COUNT(*) FROM delivery_receipts WHERE trace_id=?", (sent_trace,)
    ).fetchone()[0] == 0


def test_delivery_retention_cleanup_is_bounded(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    traces = []
    for index in range(3):
        alert = monitor.Alert(f"old-{index}", "macro", f"CPI release {index}", "2026-07-01T10:00:00+00:00")
        trace_id = store.record_outbox(alert, {"summary": alert.summary})
        store.mark_outbox(trace_id, "sent")
        traces.append(trace_id)
    old = "2026-01-01T00:00:00+00:00"
    store.connection.execute("UPDATE delivery_outbox SET updated_at=?", (old,))
    store.connection.commit()

    assert store.prune_delivery_history(limit=2) == 2
    assert store.connection.execute("SELECT COUNT(*) FROM delivery_outbox").fetchone()[0] == 1


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


def test_delivery_history_can_be_read_from_health_server_thread(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("history-thread", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    trace_id = store.record_outbox(alert, {"summary": alert.summary})
    result: list[list[dict[str, object]]] = []

    def health_thread() -> None:
        result.append(store.delivery_history(limit=5))

    thread = threading.Thread(target=health_thread)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result and result[0][0]["trace_id"] == trace_id


def test_delivery_diagnostics_can_be_read_from_health_server_thread(tmp_path):
    store = monitor.SeenStore(tmp_path / "state.sqlite3")
    alert = monitor.Alert("diagnostics-thread", "macro", "CPI release", "2026-08-02T10:00:00+00:00")
    store.record_outbox(alert, {"summary": alert.summary})
    result: list[dict[str, object]] = []

    def health_thread() -> None:
        result.append(store.delivery_diagnostics())

    thread = threading.Thread(target=health_thread)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result and result[0]["counts"]["pending"] == 1


def test_health_endpoint_accepts_cache_busting_query_string():
    assert monitor._health_request_path("/health?ts=31353476129") == "/health"
    assert monitor._health_request_path("/") == "/"


def test_trade_war_easing_market_commentary_is_material_positive():
    flash = monitor.Flash(
        "cncb-daily-open-relief",
        "CNBC Daily Open: trade war easing lifts hopes for peace",
        "Global relief rally as geopolitical tensions ease.",
        "2026-08-03T09:19:00+08:00",
    )
    assert monitor.classify_flash(flash) == "material_positive"


def test_gdelt_deescalation_aliases_share_one_positive_action():
    articles = [
        monitor.DiscoveryArticle(
            "Trade war easing lifts hopes for peace",
            "https://www.reuters.com/a",
            "reuters.com",
            "2026-08-03T01:00:00+00:00",
        ),
        monitor.DiscoveryArticle(
            "Global relief rally as geopolitical tensions ease",
            "https://www.cnbc.com/b",
            "cnbc.com",
            "2026-08-03T01:01:00+00:00",
        ),
    ]
    alerts = monitor.cross_checked_gdelt_alerts(articles)
    assert len(alerts) == 1
    assert alerts[0].category == "material_positive"
