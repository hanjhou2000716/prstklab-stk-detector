from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_the_revised_briefing_structure():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

    assert "D.inv System" in page
    assert "稜量速報系統" in page
    assert 'id="market-focus"' in page
    assert 'id="briefing-report"' in page
    assert "session-grid" not in page
    assert "總經與公開節目" not in page


def test_mini_app_uses_a_light_neutral_palette_and_balanced_logo_rules():
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "color-scheme: light" in styles
    assert "--canvas: #e8e8e4" in styles
    assert "--orange: #c77b43" in styles
    assert ".brand-prstk" in styles
    assert ".brand-dinv" in styles


def test_mini_app_renders_compact_market_risk_cards_without_subscores():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const renderFocus" in app
    assert "risk-metric-card" in app
    assert "sentiment.sub_scores" not in app
    assert "renderFocus(snapshot.events, externalAlert)" in app
    assert "renderBriefing(snapshot.briefing, snapshot.generated_at)" in app


def test_mini_app_uses_strategy_drawers_and_places_source_health_after_sentiment():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert 'class="research-drawer"' in page
    assert "<details" in page
    assert "動能狙擊" in page
    assert ".research-drawer[open] summary" in styles
    assert "#risk > .panel:not(.source-health-panel) { order: 3; }" in styles
    assert ".source-health-panel { order: 4; }" in styles


def test_source_health_is_a_collapsible_card_with_a_warming_state():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert '<details id="source-health"' in page
    assert 'source.status === "warming" ? "建檔中"' in app
    assert ".source-status.warming" in styles
    assert 'aria-labelledby="source-health-title" open' not in page
    assert 'const missing = health.sources.filter((source) => ["partial", "failed", "data_gap"].includes(source.status)).length;' in app
    assert 'summary.textContent = `${missing} 個來源有資料缺口`;' in app
    assert app.count("if (card) card.open = false;") == 2


def test_pending_source_health_shows_domain_and_check_time():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert 'source.status === "pending" && (source.checked_at || source.source_url)' in app
    assert "來源 ${domain}｜核對 ${checkedAt}" in app


def test_dashboard_sections_share_card_chrome_and_news_uses_full_width_switching():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert 'id="alert-card" class="alert-card collapsible-card"' in page
    assert 'id="briefing-report" class="briefing-report collapsible-card"' in page
    assert 'class="panel index-panel collapsible-card"' in page
    assert 'class="panel compact-panel news-panel collapsible-card"' in page
    assert ".section-block > details.collapsible-card > summary" in styles
    assert ".news-grid {\n  display: block;\n}" in styles
    assert ".news-panel[hidden]" in styles


def test_empty_briefing_market_containers_do_not_leave_visual_placeholder_blocks():
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert ".briefing-market-topics:empty" in styles
    assert ".briefing-dynamic-markets:empty" in styles


def test_briefing_report_uses_the_dedicated_observation_list_without_duplicate_market_cards():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="briefing-observations"' in page
    assert 'id="briefing-market-topics"' not in page
    assert 'id="briefing-dynamic-markets"' not in page
    assert 'getElementById("briefing-market-topics")' not in app
    assert 'getElementById("briefing-dynamic-markets")' not in app


def test_briefing_report_renders_fail_closed_intelligence_context():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert 'id="briefing-intelligence"' in page
    assert 'const context = report.intelligence;' in app
    assert 'context.market_regime' in app
    assert 'context.stress_scenarios' in app
    assert 'intelligence.hidden = true;' in app
    assert ".briefing-intelligence" in styles


def test_event_timeline_and_feedback_are_optional_and_non_policy_mutating():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert 'id="event-timeline"' in page
    assert "lifecycle_history" in app
    assert 'data-event-feedback="correct"' in app
    assert "PRSTK_FEEDBACK_ENDPOINT" in app
    assert "不會自動修改政策" in app
    assert ".event-timeline" in styles


def test_source_health_distinguishes_empty_scan_from_failure_and_exposes_slo_metrics():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert 'scanState === "scan_failed"' in app
    assert 'scanState === "no_events"' in app
    assert "health.observability || health.slo" in app
    assert "source.consecutive_failures" in app
    assert "source.crosscheck_rate" in app


def test_research_candidates_have_optional_explainability_without_advice_language():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "const researchExplainability" in app
    assert "passed_conditions" in app
    assert "failed_conditions" in app
    assert "invalidation_condition" in app
    assert "不構成買賣指令" in app
    assert ".research-explainability" in styles


def test_briefing_intelligence_shows_conditional_impact_and_macro_surprise_only():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "context.market_impact_graph?.paths" in app
    assert "等待市場證據" in app
    assert "context.macro_surprise" in app
    assert "不單獨推定市場方向" in app


def test_quote_provenance_uses_the_compact_provider_and_time_format():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const compactQuoteMeta" in app
    assert 'raw.includes("Yahoo") ? "Yahoo"' in app
    assert "const label = !clock" in app
    assert "return `${label} | ${time}${freshness}`" in app
    assert "Yahoo Finance public daily quote" not in app


def test_mini_app_hides_empty_event_trace_and_has_a_legacy_health_fallback():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "container.hidden = container.childElementCount === 0" in app
    assert "此市場快照建立於健康狀態欄位上線前" in app
    assert "renderSourceHealth(snapshot.source_health, snapshot)" in app


def test_value_drawer_hides_observations_when_five_formal_candidates_exist():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const visibleFormal = formal.slice(0, 5);" in app
    assert "const visibleObservation = visibleFormal.length >= 5 ? []" in app


def test_value_drawer_explains_that_mops_history_is_still_being_verified():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert 'const valuePending = valueSource?.scan_state === "building";' in app
    assert "歷史核對中：已完成" in app
    assert "不列入正式璞玉價值候選" in app
