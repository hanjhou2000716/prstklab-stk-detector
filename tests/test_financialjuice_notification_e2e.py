import importlib.util
from datetime import UTC, datetime

from src.financialjuice_notification import (
    deliver_financialjuice_event,
    financialjuice_caption,
    financialjuice_public_short_message,
    financialjuice_public_summary,
)
from src.financialjuice_notification_e2e import run_financialjuice_notification_e2e
from src.financialjuice_summary_contract import summary_contract_status
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url


def _railway_email_router():
    spec = importlib.util.spec_from_file_location("fj_email_router_e2e", "railway-monitor/email_router.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_financialjuice_notification_e2e_is_offline_and_replay_safe() -> None:
    result = run_financialjuice_notification_e2e()
    assert result["ok"] is True
    assert result["network_used"] is False
    assert result["secrets_used"] is False
    assert result["production_side_effects"] is False
    assert result["checks"]["vendor_score_does_not_change_risk"] is True
    assert result["checks"]["partial_delivery_isolated"] is True
    assert result["checks"]["retry_only_failed_recipient"] is True
    assert result["checks"]["replay_suppressed"] is True


def test_financialjuice_caption_hides_internal_risk_grade() -> None:
    caption = financialjuice_caption({
        "title": "Oil supply disruption",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
    })
    assert "FJ 8/10" in caption
    assert all(level not in caption for level in ("R0", "R1", "R2", "R3", "R4"))


def test_financialjuice_long_english_headline_keeps_discovery_text() -> None:
    caption = financialjuice_caption({
        "title": "Federal Reserve announces emergency liquidity support measures",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
    })
    assert caption.startswith("🟣 FJ 8/10｜")
    assert "Federal" in caption
    assert "資訊待核對" not in caption
    assert len(caption) <= 60


def test_financialjuice_public_message_removes_embedded_risk_icon() -> None:
    caption = financialjuice_caption({
        "event": "🔴 聯準會理事沃勒表示通膨數據將影響利率決策。",
        "vendor_importance": 10,
    })
    assert caption == "🟣 FJ 10/10｜聯準會理事沃勒表示通膨數據將影響利率決策。"
    assert "🔴" not in caption


def test_fj_summary_prefers_complete_policy_fact_over_generic_proposal() -> None:
    result = financialjuice_public_summary({
        "event": "美國政府正考慮一項提議，擬與伊朗安排「石油休戰」，基於為油輪開闢安全通道以通過荷姆茲海峽——引述外交消息人士。",
        "vendor_importance": 9,
    })
    assert result["status"] == "ready"
    assert result["text"] == "🟣 FJ 9/10｜美國考慮與伊朗安排「石油休戰」，為油輪開闢通過荷姆茲海峽的安全通道。"
    assert result["char_count"] == len(result["text"])
    assert result["source_field"] == "event"


def test_fj_summary_keeps_company_comparison_and_market_evidence() -> None:
    company = financialjuice_public_short_message({
        "event": "Meta 將於 2027 年底推出下一代 Astrid 晶片。Meta 將於 2027 上半年部署新款自研 Arke 晶片。Meta：這些晶片將比輝達晶片更省錢、更節能。",
        "vendor_importance": 9,
    })
    market = financialjuice_public_short_message({
        "event": "美國股市下跌，因投資人在聯準會政策決定前避開風險性資產，同時油價上漲加劇通膨疑慮。標普500指數中近350家企業下跌，基準10年期公債殖利率觸及5%。",
        "vendor_importance": 9,
    })
    assert company == "🟣 FJ 9/10｜Meta擬2027上半年部署自研Arke晶片，稱較輝達省錢節能。"
    assert market == "🟣 FJ 9/10｜標普500近350家公司下跌，聯準會決策前避險；10年債殖利率觸5%。"
    assert len(company) <= 60 and len(market) <= 60


def test_fj_summary_suppresses_contextless_fragment() -> None:
    result = financialjuice_public_summary({
        "title": "更節能",
        "vendor_importance": 9,
    })
    assert result["status"] == "incomplete"
    assert result["text"] == ""
    assert financialjuice_public_short_message({"title": "更節能", "vendor_importance": 9}) == ""


def test_fj_summary_compacts_complete_military_event_without_losing_required_facts() -> None:
    result = financialjuice_public_summary({
        "event": "伊朗革命衛隊（IRGC）表示，在荷姆茲海峽附近擊落三架美軍MQ-9無人機，導致該地區緊張局勢進一步升級。",
        "vendor_importance": 9,
    })
    assert result["status"] == "ready"
    assert result["text"] == "🟣 FJ 9/10｜伊朗革命衛隊稱在荷姆茲海峽附近擊落3架美軍MQ-9無人機，區域緊張升級。"
    assert result["char_count"] == len(result["text"]) <= 60
    assert summary_contract_status({
        "event": "伊朗革命衛隊（IRGC）表示，在荷姆茲海峽附近擊落三架美軍MQ-9無人機，導致該地區緊張局勢進一步升級。",
    })["status"] == "ready"


def test_shared_fj_summary_contract_rejects_contextless_military_fragment() -> None:
    result = summary_contract_status({"event": "擊落。"})
    assert result["status"] == "incomplete"
    assert result["reason"] == "summary_semantics_incomplete"


def test_financialjuice_caption_prefers_projected_event_over_generic_title() -> None:
    caption = financialjuice_caption({
        "title": "FinancialJuice 公開快訊",
        "event": "某公司據報正在評估合作",
        "vendor_importance": 10,
        "prstk_risk": {"prstk_risk_level": "R0"},
    })
    assert caption.startswith("🟣 FJ 10/10｜某公司據報")
    assert "FinancialJuice 公開快訊" not in caption
    assert len(caption) <= 60


def test_financialjuice_public_short_message_is_the_release_headline_contract() -> None:
    event = {
        "source_key": "financialjuice",
        "title": "據《The...",
        "event": "Nscale稱Anthropic合約簽約營收逾千億美元。",
        "vendor_importance": 9,
        "prstk_risk_level": "R2",
    }
    message = financialjuice_public_short_message(event)
    assert message == "🟣 FJ 9/10｜Nscale稱Anthropic合約簽約營收逾千億美元。"
    assert financialjuice_caption(event) == message
    assert len(message) <= 60
    assert "據《The" not in message


def test_fj_summary_compacts_company_capacity_plan_with_metric_and_deadline() -> None:
    result = financialjuice_public_summary({
        "event": "Anthropic計劃在年底前擁有5GW的運算能力－紐約時報。",
        "vendor_importance": 9,
    })
    assert result["status"] == "ready"
    assert result["reason"] == "complete_fact_selected"
    assert result["text"] == "🟣 FJ 9/10｜Anthropic計劃年底前具備5GW運算能力，紐時報導。"
    assert result["char_count"] <= 60
    assert summary_contract_status({
        "event": "Anthropic計劃在年底前擁有5GW的運算能力－紐約時報。",
    })["reason"] == "complete_capacity_fact"


def test_financialjuice_incomplete_attribution_is_not_deliverable() -> None:
    assert financialjuice_caption({"title": "據《The...", "vendor_importance": 9}) == ""


def test_financialjuice_rejects_status_only_and_source_envelope_fragments() -> None:
    for title in (
        "🔴，關聯市場：US10Y、NASDAQ（資料待更新）。",
        "聯準會賭注因沃勒而緩解：股市創一個月來最大漲幅 –.",
        "FinancialJuice新聞 (09-02)",
        "📰 FinancialJuice新聞 (09-02.",
        "川普表示油價將下跌。🔴.",
        "Morning Juice - US Session Prep (2nd September)",
    ):
        assert financialjuice_caption({"title": title, "vendor_importance": 10}) == ""


def test_financialjuice_public_summary_keeps_linkage_in_details_not_headline() -> None:
    message = financialjuice_caption({
        "event": "伊朗：美國攻擊電信和通信基礎設施。",
        "possible_linkage": "關聯市場：NASDAQ、US10Y（資料待更新）。",
        "vendor_importance": 10,
    })
    assert message == "🟣 FJ 10/10｜伊朗：美國攻擊電信和通信基礎設施。"
    assert "關聯市場" not in message


def test_financialjuice_compresses_real_nscale_event_to_one_complete_sentence() -> None:
    caption = financialjuice_caption({
        "event": (
            "據《The Information》報導，AI雲端及基礎設施公司 Nscale 在贏得 "
            "Anthropic 的合約後，宣稱其已簽約的合約營收總額已超過1,000億美元。"
        ),
        "vendor_importance": 9,
    })
    assert caption == "🟣 FJ 9/10｜Nscale稱Anthropic合約簽約營收逾千億美元。"
    assert len(caption) <= 60
    assert "據《" not in caption
    assert "…" not in caption and "..." not in caption
    assert caption.count("｜") == 1


def test_financialjuice_waller_relay_keeps_the_event_fact_not_livestream_transport() -> None:
    message = financialjuice_public_short_message({
        "event": (
            "聯準會理事沃勒在溫和對談中發表現場談話。直播影片：Fed Governor Christopher Waller "
            "在 Reuters NEXT Newsmaker 訪談中，討論通膨持續高於聯準會2%目標、勞動市場穩定性，"
            "以及在主席 Kevin Warsh 領導下的貨幣政策考量。"
        ),
        "vendor_importance": 8,
    })
    assert message.startswith("🟣 FJ 8/10｜聯準會理事沃勒談通膨")
    assert "直播影片" not in message
    assert "Fed." not in message
    assert len(message) <= 60


def test_financialjuice_removes_generic_speaker_wrapper_but_keeps_event():
    message = financialjuice_public_short_message({
        "event": "三名消息人士表示：除非通膨降溫，否則聯準會可能維持高利率。",
        "vendor_importance": 10,
    })
    assert message == "🟣 FJ 10/10｜除非通膨降溫，否則聯準會可能維持高利率。"
    assert "消息人士" not in message


def test_financialjuice_prefers_structured_fact_over_attribution_fragment():
    message = financialjuice_public_short_message({
        "title": "三名消息人士表示",
        "structured_fact": {
            "subject": "聯準會",
            "action": "表示",
            "object": "若通膨過熱，可能延後降息",
            "key_numbers": ["2%目標"],
        },
        "vendor_importance": 9,
    })
    assert message.startswith("🟣 FJ 9/10｜聯準會表示")
    assert "延後降息" in message
    assert "2%目標" in message
    assert len(message) <= 60


def test_financialjuice_uses_complete_fallback_when_title_is_truncated() -> None:
    caption = financialjuice_caption({
        "title": "據《The...",
        "vendor_original_headline": "Iran says U.S. strikes telecommunications infrastructure.",
        "vendor_importance": 9,
    })
    assert caption.startswith("🟣 FJ 9/10｜Iran says U.S. strikes")
    assert "據《The" not in caption
    assert "U.…" not in caption
    assert len(caption) <= 60


def test_financialjuice_delivery_suppresses_incomplete_attribution() -> None:
    calls: list[dict[str, object]] = []

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        calls.append(kwargs)
        return ()

    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "incomplete-1",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "notification_status": "eligible",
            "freshness_status": "fresh",
            "title": "據《The...",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )
    assert result["status"] == "blocked"
    assert result["reasons"] == ["content_incomplete"]
    assert calls == []


def test_financialjuice_delivery_reaches_text_sender_with_alert_deep_link() -> None:
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "fj-cluster-1",
        "observation_id": "fj-observation-1",
        "item_id": "fj-item-1",
        "vendor_importance": 9,
        "vendor_priority_notification": True,
        "delivery_policy": "fj_priority",
        "notification_status": "eligible",
        "freshness_status": "fresh",
        # The generic risk classifier may remain blocked for an R2 discovery;
        # FJ >=9 is the deliberate vendor-priority exception.
        "notification": {"allowed": False, "status": "pending"},
        "prstk_risk": {"prstk_risk_level": "R2"},
        "title": "Oil supply update",
    }
    captured: dict[str, object] = {}

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "recipient-hash", "delivered", message_id=1,
            observation_id=kwargs.get("observation_id", ""),
        ),)

    result = deliver_financialjuice_event(
        event,
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )

    assert result["status"] == "delivered"
    assert captured["target_url"] == alert_mini_app_url(
        "https://example.test/app",
        alert_id="fj-cluster-1",
        release_id="release-1",
        snapshot_id="snapshot-1",
        observation_id="fj-observation-1",
    )


def test_versioned_summary_is_authoritative_at_delivery_boundary() -> None:
    captured: dict[str, object] = {}
    expected = "🟣 FJ 9/10｜Meta擬2027上半年部署自研Arke晶片，稱較輝達省錢節能。"

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            "alert", kwargs["release_id"], kwargs["snapshot_id"],
            "recipient-hash", "delivered", message_id=1,
        ),)

    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "fj-versioned",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "delivery_policy": "fj_priority",
            "notification_status": "eligible",
            "freshness_status": "fresh",
            "public_summary_version": "public-summary-v3",
            "public_summary_status": "ready",
            "public_short_message": expected,
            "title": "更節能。",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )
    assert result["status"] == "delivered"
    assert captured["text"] == expected


def test_versioned_incomplete_summary_cannot_reach_sender() -> None:
    calls: list[dict[str, object]] = []

    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "fj-incomplete-v3",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "delivery_policy": "fj_priority",
            "notification_status": "eligible",
            "freshness_status": "fresh",
            "public_summary_version": "public-summary-v3",
            "public_summary_status": "incomplete",
            "public_short_message": "",
            "event": "更節能",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=lambda **kwargs: (calls.append(kwargs) or ()),
    )
    assert result["status"] == "blocked"
    assert "summary_semantics_incomplete" in result["reasons"]
    assert calls == []


def test_financialjuice_eight_score_does_not_enter_priority_sender_lane() -> None:
    calls: list[dict[str, object]] = []

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        calls.append(kwargs)
        return ()

    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "fj-ordinary-8",
            "vendor_importance": 8,
            "vendor_priority_notification": True,
            "delivery_policy": "fj_priority",
            "notification_status": "eligible",
            "freshness_status": "fresh",
            "title": "Ordinary discovery update",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=sender,
    )

    assert result["status"] == "blocked"
    assert "fj_priority_threshold_not_met" in result["reasons"]
    assert calls == []


def test_financialjuice_delivery_returns_safe_failure_classes() -> None:
    result = deliver_financialjuice_event(
        {
            "source_key": "financialjuice",
            "event_cluster_key": "fj-failed-classification",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "notification_status": "eligible",
            "freshness_status": "fresh",
            "title": "Oil supply update",
        },
        release_id="release-1",
        snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("recipient",),
        text_sender=lambda **_kwargs: (TextDeliveryReceipt(
            "alert", "release-1", "snapshot-1", "recipient-hash", "failed",
            error_class="recipient_unavailable",
        ),),
    )
    assert result["status"] == "failed"
    assert result["failure_classes"] == ["recipient_unavailable"]
    assert "recipient-hash" in str(result["receipts"])


def test_financialjuice_delivery_prefers_notification_id_for_alert_deep_link() -> None:
    event = {
        "source_key": "financialjuice", "notification_id": "fj-notification-1",
        "event_cluster_key": "fj-cluster-1", "observation_id": "fj-observation-1",
        "vendor_importance": 9, "vendor_priority_notification": True,
        "delivery_policy": "fj_priority",
        "notification_status": "eligible", "freshness_status": "fresh", "prstk_risk_level": "R0",
        "title": "Oil supply update",
    }
    captured: dict[str, object] = {}

    def sender(**kwargs: object) -> tuple[TextDeliveryReceipt, ...]:
        captured.update(kwargs)
        return (TextDeliveryReceipt(kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"], "h", "delivered", message_id=1),)

    deliver_financialjuice_event(
        event, release_id="release-1", snapshot_id="snapshot-1",
        mini_app_url="https://example.test/app", release_ready=True,
        token="token", chat_ids=("recipient",), text_sender=sender,
    )
    assert captured["alert_id"] == "fj-notification-1"


def test_rich_email_to_priority_to_telegram_preserves_semantics() -> None:
    router = _railway_email_router()
    parsed = router.parse_email({
        "gmail_message_id": "g5-rich-e2e",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice alert",
        "body": (
            "Importance: 10/10\n"
            "Original headline: Reported AI partnership review\n"
            "Translation: 某公司據報正在評估與某 AI 晶片供應商合作\n"
            "AI commentary: 若合作成真，可能代表該公司 AI 基礎建設需求進一步提高，但目前仍未正式確認。\n"
            "Possible impact: 可能影響 AI 伺服器、GPU、相關供應鏈個股情緒。"
        ),
        "source_published_at": datetime.now(UTC).isoformat(),
        "received_at": datetime.now(UTC).isoformat(),
    })
    from src.financialjuice_priority import project_financialjuice_priority

    assert parsed["public_observations"][0]["vendor_original_headline"] == "Reported AI partnership review"
    event = project_financialjuice_priority(parsed["public_observations"])["events"][0]
    telegram_text = financialjuice_caption(event)
    assert event["event"] == "某公司據報正在評估與某 AI 晶片供應商合作"
    assert event["why_important"].endswith("目前仍未正式確認。")
    assert event["possible_linkage"].startswith("可能影響 AI 伺服器")
    assert "某公司據報" in telegram_text
    assert "FinancialJuice 公開快訊" not in telegram_text
    assert event["public_summary_version"] == "public-summary-v3"
    assert event["public_summary_status"] == "ready"
    assert event["public_short_message"] == telegram_text
    assert event["prstk_risk_level"] == "R0"
    assert event["vendor_priority_notification"] is True
