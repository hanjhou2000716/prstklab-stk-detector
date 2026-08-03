from importlib.util import module_from_spec, spec_from_file_location
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading


MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "app.py"
SPEC = spec_from_file_location("railway_monitor_app", MODULE_PATH)
assert SPEC and SPEC.loader
monitor = module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def test_monitor_imports_from_railway_root_without_repository_src_package():
    """Railway's configured root directory must not crash on ``import app``."""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    command = [
        sys.executable,
        "-c",
        "import app; assert app._USING_STANDALONE_CLASSIFIER; "
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
