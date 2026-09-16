"""Regression tests for the evidence-first four-report narrative contract."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.briefing_cards import build_briefing_snapshot
from src.briefing_narrative import NARRATIVE_VERSION, SLOT_FOCUS, build_narrative


def test_narrative_contract_is_schema_valid_and_keeps_event_context() -> None:
    narrative = build_narrative(
        slot="post_close",
        section="semiconductor",
        as_of="2026-09-14T14:20:00+08:00",
        facts=["台積電 2,380.00 TWD（-1.24%）", "費半 11,824.00（+1.81%）"],
        quote_evidence=[{"ticker": "2330", "quote_date": "2026-09-14", "source_label": "TWSE"}],
        themes=[{
            "title": "半導體與 AI",
            "market_topic": "semiconductor_ai",
            "what_happened": "台積電公告資本支出展望維持，市場等待後續指引。",
            "why_important": "資本支出展望可用來核對 AI 供應鏈需求預期。",
            "market_implication": "台積電下跌、費半上漲，價格呈現分歧，尚不能推論因果。",
            "stock_observation": "後續核對公司指引與下一交易時段價格是否延續。",
            "source_evidence": [{"source": "issuer", "published_at": "2026-09-14T06:00:00Z"}],
        }],
    )

    schema = json.loads((Path("schemas") / "briefing-narrative.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(narrative))
    assert narrative["version"] == NARRATIVE_VERSION
    assert narrative["focus"] == SLOT_FOCUS["post_close"]
    assert [item["label"] for item in narrative["details"]] == [
        "發生什麼", "為何重要", "可能傳導", "下一項催化劑",
    ]
    assert "資本支出展望" in narrative["highlights"][0]
    assert "買進" not in json.dumps(narrative, ensure_ascii=False)
    assert "賣出" not in json.dumps(narrative, ensure_ascii=False)


def test_taiwan_narrative_uses_available_statistics_without_filling_missing_values() -> None:
    narrative = build_narrative(
        slot="post_close",
        section="taiwan",
        as_of="2026-09-14",
        facts=["加權指數 45,862.52 點（-0.70%）"],
        quote_evidence=[{"ticker": "TAIEX", "quote_date": "2026-09-14", "source_label": "TWSE"}],
        themes=[],
        statistics={
            "turnover": {"trade_value": 3210.5, "unit": "億元"},
            "breadth": {"scope_verified": True, "advancing": 410, "declining": 720, "unchanged": 85},
            "institutional_flows": {"total_net": -45.2, "unit": "億元"},
        },
        limitations=["櫃買指數"],
    )

    joined = json.dumps(narrative, ensure_ascii=False)
    assert "成交值 3,210.50億元" in joined
    assert "上漲 410 家、下跌 720 家、平盤 85 家" in joined
    assert "三大法人合計淨額 -45.20億元" in joined
    assert "櫃買指數" in narrative["limitations"]
    assert "資料暫時無法取得" not in joined


def test_narrative_focus_is_metadata_and_not_repeated_in_public_text() -> None:
    narrative = build_narrative(
        slot="pre_open",
        section="risk",
        as_of="2026-09-15",
        facts=["台指 +0.40%"],
        quote_evidence=[],
        themes=[],
    )

    assert narrative["focus"] == SLOT_FOCUS["pre_open"]
    assert all("本報聚焦" not in value for value in narrative["highlights"])
    assert all("本報聚焦" not in item["text"] for item in narrative["details"])


def test_briefing_snapshot_exposes_narrative_for_each_report_slot() -> None:
    snapshot = {
        "generated_at": "2026-09-14T14:20:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 45862.52, "change_percent": -0.70, "quote_date": "2026-09-14"},
            {"ticker": "TPEx", "price": 394.41, "change_percent": -0.28, "quote_date": "2026-09-14"},
            {"ticker": "NASDAQ", "price": 26333.04, "change_percent": 0.96, "quote_date": "2026-09-14"},
            {"ticker": "SOX", "price": 11824.00, "change_percent": 1.81, "quote_date": "2026-09-14"},
        ],
        "quotes": [{"ticker": "2330", "price": 2380.0, "change_percent": -1.24, "quote_date": "2026-09-14"}],
        "events": {"items": []},
    }

    focuses = set()
    confirmations = set()
    for slot in ("morning", "pre_open", "post_close", "us_premarket"):
        briefing = build_briefing_snapshot(snapshot, slot)
        analysis = briefing["morning_analysis"]
        assert analysis["narrative_version"] == NARRATIVE_VERSION
        focuses.add(analysis["sections"][0]["narrative"]["focus"])
        confirmations.add(analysis["sections"][0]["narrative"]["highlights"][2])
        for section in analysis["sections"]:
            narrative = section["narrative"]
            assert 1 <= len(narrative["highlights"]) <= 3
            assert len(narrative["details"]) == 4
            assert narrative["evidence_refs"] is not None
    assert len(focuses) == 4
    assert len(confirmations) == 4
