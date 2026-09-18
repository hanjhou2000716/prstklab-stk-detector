# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/financialjuice_summary_contract.py
# Canonical source SHA256: 1ad18594eac1c9193c654ea49219ad346933f4b98ff6feb555028fa410555179

"""Shared, privacy-safe FinancialJuice summary readiness helpers.

This module is intentionally small so the same contract can be bundled into
the standalone Gmail ingress runtime and imported by the public summary
producer.  It never stores or emits transport identifiers or raw mail.
"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_CONTRACT_VERSION = "fj-summary-contract-v2"
PUBLIC_SUMMARY_MAX_CHARS = 60

_ACTION_RE = re.compile(
    r"(?:表示|指出|宣稱|宣称|宣布|公布|發布|发布|更新|完成|組成|组成|影響|上漲|上升|下跌|下降|升息|降息|"
    r"中斷|中断|供應|供给|簽署|簽約|簽|簽訂|達|高於|低於|發射|否認|否认|可能|擬|拟|"
    r"考慮|考虑|評估|评估|計劃|计划|擁有|拥有|具備|具备|達到|达到|容量|攻擊|攻击|擊落|击落|攔截|拦截|摧毀|摧毁|扣押|封鎖|封锁|撤離|撤离|部署|"
    r"會面|会面|討論|讨论|發表|发表|推出|said|says|announc|report|rise|fall|jump|drop|"
    r"increase|decrease|disrupt|supply|rate|outlook|earnings|guidance|forecast|profit|revenue|policy)",
    re.IGNORECASE,
)
_INVALID_RE = (
    re.compile(r"(?:關聯市場|資料待更新|報價待取得|資訊待核對)", re.IGNORECASE),
    re.compile(r"[-–—]\s*\.?$"),
)


def _text(value: Any) -> str:
    if value in (None, "") or isinstance(value, (dict, list, tuple, set, bool)):
        return ""
    return " ".join(str(value).replace("\n", " ").split()).strip()


def _clean(value: Any) -> str:
    text = _text(value)
    text = re.sub(r"[📰🟢🟡🟠🔴⚪⚫🟣]\s*", "", text)
    text = re.sub(r"\s*\$[A-Z][A-Z0-9._-]*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _condition_complete(text: str) -> bool:
    for match in re.finditer(r"(如果|若|除非|if|unless)", text, re.IGNORECASE):
        tail = re.split(r"[。！？.!?;；]", text[match.end():], maxsplit=1)[0]
        if match.group(1).casefold() in {"除非", "unless"}:
            if not re.search(r"(?:，|,).*(?:否則|否则|不然|才會|才会|otherwise)", tail, re.IGNORECASE):
                return False
        elif not re.search(r"(?:，|,).*(?:則|则|就|將|将|會|会|可能|因此|then|would|will)", tail, re.IGNORECASE):
            return False
    return True


def is_complete_fact(value: Any) -> bool:
    """Check whether a source fact can stand alone without guessing."""
    text = _clean(value).strip()
    if not text or len(text.rstrip("。！？.!?")) < 8:
        return False
    if not _ACTION_RE.search(text) or not _condition_complete(text):
        return False
    if any(pattern.search(text) for pattern in _INVALID_RE):
        return False
    if re.search(r"(?:考慮|考虑|評估|评估)\s*(?:一項|一项)?\s*(?:提議|提议|提案|proposal)\s*[。.!！]?$", text, re.IGNORECASE):
        return False
    if re.fullmatch(r"(?:更|較為|更加)?(?:省錢|省钱|節能|节能|有效率|efficient)\s*[。.!！]?", text, re.IGNORECASE):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text))


def _compact_number(value: str) -> str:
    return (
        value.replace("三架", "3架")
        .replace("兩架", "2架")
        .replace("兩艘", "2艘")
        .replace("一架", "1架")
    )


def compact_military_fact(value: Any) -> str:
    """Compress a complete military fact while retaining attribution and object."""
    text = _clean(value).rstrip("。！？.!?")
    if not text or not re.search(r"(?:擊落|击落|攔截|拦截|摧毀|摧毁|發射|发射|扣押|封鎖|封锁|撤離|撤离)", text):
        return ""

    action = re.search(r"(?P<verb>擊落|击落|攔截|拦截|摧毀|摧毁|發射|发射|扣押|封鎖|封锁|撤離|撤离)", text)
    if not action:
        return ""
    actor_match = re.match(r"(?P<actor>.+?)(?:表示|稱|称|指出|宣稱|宣称|報導稱|报道称|：|:)", text)
    actor = actor_match.group("actor").strip() if actor_match else text[:action.start()].strip(" ，,")
    if not actor:
        return ""
    if "革命衛隊" in actor or "革命卫队" in actor or "IRGC" in actor.upper():
        actor = "伊朗革命衛隊"
    else:
        actor = re.sub(r"\s+", "", actor)

    location = ""
    location_match = re.search(r"(?:在|於|于)(?P<location>[^，,。；;]+?)(?:附近|上空|境內|境内)", text)
    if location_match:
        location = location_match.group("location").strip() + "附近"
    object_match = re.search(
        r"(?:附近|上空|境內|境内)?(?:擊落|击落|攔截|拦截|摧毀|摧毁|發射|发射|扣押|封鎖|封锁|撤離|撤离)"
        r"(?P<object>[^，,。；;]+)", text,
    )
    if not object_match:
        return ""
    target = _compact_number(object_match.group("object").strip())
    if not target:
        return ""

    verb = action.group("verb")
    attribution = "稱" if actor_match else ""
    prefix = f"{actor}{attribution}"
    place = f"在{location}" if location else ""
    result = f"{prefix}{place}{verb}{target}"
    if re.search(r"(?:緊張局勢|緊張情勢|局勢).*(?:升級|升高|惡化)", text):
        result += "，區域緊張升級"
    elif re.search(r"(?:局勢|衝突|冲突).*(?:升級|升高|惡化)", text):
        result += "，局勢升級"
    return result + "。" if is_complete_fact(result + "。") else ""


def compact_capacity_fact(value: Any) -> str:
    """Compress a company capacity or infrastructure plan without guessing.

    The output keeps the actor, the commitment/target modality, the deadline
    when present, and the numeric capacity with its subject.  It deliberately
    does not infer cost, demand, market impact, or whether the plan will be
    achieved.
    """
    text = _clean(value).rstrip("。！？.!?")
    if not text:
        return ""
    match = re.search(
        r"(?P<actor>[A-Za-z][A-Za-z0-9 ._-]{1,40}|[\u4e00-\u9fff][^，,。；;]{0,24}?)"
        r"(?:計劃|計畫|计划|拟|擬|預計|预計|目標|目标)"
        r"(?:在)?(?P<when>年底前|年末前|年內|年内|\d{4}\s*年(?:底|末)?前?)?"
        r"(?:擁有|拥有|具備|具备|部署|上線|上线|達到|达到|取得)"
        r"(?P<amount>\d+(?:\.\d+)?\s*(?:GW|MW|TW|億|万億|萬億|%))"
        r"(?:的)?(?P<object>運算能力|運算容量|算力|資料中心容量|数据中心容量|產能|产能|能源容量|容量)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    actor = re.sub(r"\s+", "", match.group("actor")).strip(" ：:")
    when = re.sub(r"\s+", "", match.group("when") or "")
    amount = re.sub(r"\s+", "", match.group("amount"))
    object_name = match.group("object")
    if not actor or not amount or not object_name:
        return ""
    result = f"{actor}計劃{when}具備{amount}{object_name}"
    if "紐約時報" in text or "紐時" in text:
        result += "，紐時報導"
    result += "。"
    return result if is_complete_fact(result) else ""


def summary_contract_status(event: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded readiness result for ingress and monitor alignment."""
    fields = (
        ("structured_fact", event.get("structured_fact")),
        ("event", event.get("event")),
        ("what_happened", event.get("what_happened")),
        ("chinese_translation", event.get("chinese_translation")),
        ("vendor_translation", event.get("vendor_translation")),
        ("headline", event.get("headline")),
        ("original_headline", event.get("original_headline")),
        ("vendor_original_headline", event.get("vendor_original_headline")),
        ("title", event.get("title")),
    )
    for field, raw in fields:
        value = raw
        if field == "structured_fact" and isinstance(raw, dict):
            value = raw.get("text") or raw.get("fact_text") or raw.get("what_happened")
        military = compact_military_fact(value)
        capacity = compact_capacity_fact(value)
        compact = military or capacity
        if compact:
            return {
                "status": "ready",
                "reason": "complete_military_fact" if military else "complete_capacity_fact",
                "source_field": field, "text": compact,
                "version": SUMMARY_CONTRACT_VERSION,
            }
        if is_complete_fact(value):
            return {
                "status": "ready", "reason": "complete_fact_detected",
                "source_field": field, "text": _clean(value),
                "version": SUMMARY_CONTRACT_VERSION,
            }
    return {
        "status": "incomplete", "reason": "summary_semantics_incomplete",
        "source_field": "", "text": "", "version": SUMMARY_CONTRACT_VERSION,
    }


__all__ = [
    "PUBLIC_SUMMARY_MAX_CHARS", "SUMMARY_CONTRACT_VERSION", "compact_capacity_fact",
    "compact_military_fact",
    "is_complete_fact", "summary_contract_status",
]
