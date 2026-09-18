"""Release-gated FinancialJuice notification delivery.

FinancialJuice is a discovery/relay source.  A vendor score of 9/10 or more
authorizes a vendor-priority notification, but it never changes the PRStK
risk level.  This module keeps that boundary explicit and provides a
recipient-scoped, replay-safe delivery plan for the production sender.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.financialjuice_priority import (
    FJ_PRIORITY_MIN_IMPORTANCE,
    financialjuice_vendor_importance,
)
from src.financialjuice_summary_contract import (
    SUMMARY_CONTRACT_VERSION,
    compact_capacity_fact,
    compact_military_fact,
)
from src.telegram_client import (
    PUBLIC_SUMMARY_VERSION,
    PUBLIC_TEXT_MAX_CHARS,
    TextDeliveryReceipt,
    alert_mini_app_url,
    canonical_prstk_risk_level,
    is_valid_public_summary,
    send_text_briefs_audited,
    structured_public_fact,
)

MAX_FINANCIALJUICE_CAPTION = PUBLIC_TEXT_MAX_CHARS


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _recipient_hash(chat_id: str) -> str:
    return hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:12]


def _bounded(value: str, limit: int) -> str:
    from src.telegram_client import summarize_public_message

    return summarize_public_message(value, limit=limit, message_kind="financialjuice")


def _compress_fj_sentence(value: str) -> str:
    """Apply only factual, deterministic shortening to an FJ event sentence."""
    from src.telegram_client import _clean_public_fragment

    text = _clean_public_fragment(value)
    if not text or "…" in text or "..." in text:
        return ""
    if re.search(r"\bundefined\b", text, flags=re.IGNORECASE) or re.search(r"https?://|www\.", text, flags=re.IGNORECASE):
        return ""
    if re.match(r"^(?:[📰🟢🟡🟠🔴⚪⚫🟣]\s*)?(?:financialjuice|morning\s+juice)(?:\s+公開)?(?:新聞|快訊)?(?:\s|[（(]|[-–—]|$)", text, flags=re.IGNORECASE):
        return ""
    if re.search(r"關聯市場|資料待更新|報價待取得|資訊待核對", text, flags=re.IGNORECASE):
        return ""
    if re.search(r"[-–—]\s*\.?$", text):
        return ""
    if re.search(r"[🟢🟡🟠🔴⚪⚫🟣]\s*[。！？!?，,、:：；;.\s]*$", text):
        return ""
    if re.fullmatch(r"[🟢🟡🟠🔴⚪⚫🟣\s。！？!?，,、:：|｜()（）\[\]{}]*", text):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    # Relay records often append an embedded livestream or the parser's
    # attribution footer after the actual event.  Keep a substantive topic
    # from that suffix when it is explicitly present; otherwise drop the
    # transport wrapper instead of publishing "直播影片：Fed.".
    text = re.sub(r"\s*(?:📈\s*)?StockRocket[^。！？]*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*\[(?:Embed|LIVE)\].*$", "", text, flags=re.IGNORECASE).strip()
    live_match = re.search(r"(?:直播影片|直播|影片)\s*[:：]\s*", text, flags=re.IGNORECASE)
    if live_match:
        prefix = text[:live_match.start()].strip(" ，,。；;:")
        details = text[live_match.end():].strip()
        topic_match = re.search(
            r"(?:討論|談及|談到|addresses?|discuss(?:es)?)\s*(?P<topic>.+)",
            details,
            flags=re.IGNORECASE,
        )
        if prefix and topic_match:
            subject_match = re.match(
                r"(?P<subject>[^，,。；;]+?)(?:在[^，,。；;]+中)?"
                r"(?:發表|表示|稱|指出|說|談)",
                prefix,
            )
            subject = subject_match.group("subject").strip() if subject_match else prefix
            topic = topic_match.group("topic").strip()
            text = f"{subject}談{topic}"
        else:
            text = prefix
    text = re.sub(r"\s+-\s+The Information\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?P<entity>[A-Za-z][\w-]*)\s+boasts over \$100 billion in contracted revenue"
        r" after [A-Za-z][\w-]* win\.?$",
        r"\g<entity> claims $100B revenue.",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace("1,000億", "千億").replace("1,000 億", "千億")
    # Preserve the reported claim while dropping nonessential industry
    # framing and repeated Chinese function words.
    text = re.sub(r"^AI雲端及基礎設施公司\s*", "", text)
    text = re.sub(
        r"^(?P<entity>\S+)\s+在贏得\s+(?P<partner>[^，,]+?)\s+的合約後，\s*"
        r"宣稱其已簽約的合約營收總額已超過(?P<amount>[\d,]+億美元|千億美元)",
        r"\g<entity>稱\g<partner>合約簽約營收逾\g<amount>",
        text,
    )
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", text)
    # Preserve the event while removing only non-material English relay
    # modifiers when a complete headline otherwise exceeds the public limit.
    text = re.sub(r"\bemergency\s+(?=liquidity\s+support)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+liquidity\s+support\s+measures(?=\.?$)", " liquidity support", text, flags=re.IGNORECASE)
    text = re.sub(r"\btelecommunications\s+infrastructure\b", "infrastructure", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?P<entity>[A-Za-z0-9][\w.-]*)\s*將與\s*(?P<partner>[A-Za-z][\w.-]*)\s*"
        r"簽署超過\s*(?P<amount>[\d,]+)\s*億美元合約。?$",
        r"\g<entity>與\g<partner>簽約逾\g<amount>億美元。",
        text,
    )
    text = text.replace("其已", "").replace("已超過", "逾")
    text = text.replace("合約營收總額", "合約營收")
    # Keep source uncertainty.  ``據《…》報導`` has already been reduced by
    # the public-fragment cleaner, but a direct ``據報導`` qualifier carries
    # meaning and must not be silently deleted.
    text = text.replace("據報導", "據報")
    if text and not text.endswith(("。", "！", "？", ".", "!", "?")):
        text += "。"
    return text


def _complete_factual_clauses(headline: str) -> list[str]:
    """Return only complete clauses that can safely be shown publicly.

    Conditional headlines are atomic facts: emitting the clause before the
    comma would reverse or erase the source's actual qualification.  Such a
    headline therefore remains whole, or is suppressed until a shorter
    structured fact is available.
    """
    from src.telegram_client import _is_usable_financialjuice_fact

    candidates = [headline]
    if not re.search(r"(?:如果|若|除非|\bif\b|\bunless\b)", headline, re.IGNORECASE):
        candidates.extend(
            part.strip(" ，,、；;。")
            for part in re.split(r"(?<=[，,、；;])", headline)
        )
    return list(dict.fromkeys(
        candidate for candidate in candidates
        if candidate and _is_usable_financialjuice_fact(candidate)
    ))


def _financialjuice_headline(event: dict[str, Any]) -> str:
    """Select the best parsed event fact, excluding metadata-only labels."""
    from src.telegram_client import _clean_public_fragment

    generic = {"financialjuice 公開快訊", "fj 公開快訊", "公開快訊", "資訊待核對"}
    structured = structured_public_fact(event)
    if structured.get("complete") is True:
        value = _compress_fj_sentence(str(structured.get("text") or ""))
        if value and value.casefold() not in generic:
            return value
    for field in (
        "event", "chinese_translation", "title", "brief_title",
        "vendor_original_headline", "original_headline",
    ):
        value = _clean_public_fragment(event.get(field))
        # A malformed Morning Juice envelope is metadata plus a raw URL/body,
        # not a usable event headline.  Let a richer parsed field win, or
        # suppress the item when no such field exists.
        if re.match(r"^undefined\s*[|｜]", value, flags=re.IGNORECASE):
            continue
        if field in {"brief_title", "title"}:
            value = re.sub(r"^[🟣🟡🟠🔴⚪⚫]\s*FJ\s*\d+(?:\.\d+)?\s*/\s*10\s*[｜|]\s*", "", value, flags=re.IGNORECASE)
        value = _compress_fj_sentence(value)
        if value and value.casefold() not in generic:
            return value
    return ""


def _legacy_financialjuice_notification_key(event: dict[str, Any]) -> str:
    """Return the pre-convergence key so old delivered rows remain idempotent."""
    material = "|".join(
        _text(event.get(name)).casefold()
        for name in ("event_cluster_key", "item_id", "observation_id", "source_url")
    )
    if not material:
        return ""
    return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def financialjuice_notification_key(event: dict[str, Any]) -> str:
    """Return a stable key based on factual event identity only.

    New records carry ``canonical_fact_key``.  The fallback intentionally
    preserves the previous headline+impact identity for historical records;
    callers can still match it through the alias set during migration.
    """
    canonical = _text(event.get("canonical_fact_key"))
    if canonical:
        version = _text(event.get("material_fact_version") or event.get("fact_version"))
        material = "|".join(value.casefold() for value in (canonical, version) if value)
        return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"
    return _legacy_semantic_notification_key(event)


def _legacy_semantic_notification_key(event: dict[str, Any]) -> str:
    """Return the pre-fact-key semantic identity for compatibility lookup."""
    headline = _financialjuice_headline(event)
    impact = _text(event.get("possible_impact") or event.get("possible_linkage"))
    material = "|".join((headline, impact)).casefold().strip("|")
    if not material:
        material = _text(event.get("content_hash")).casefold()
    if not material:
        return ""
    return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def financialjuice_notification_aliases(event: dict[str, Any]) -> tuple[str, ...]:
    """Return current and legacy identities for replay-safe migration."""
    current = financialjuice_notification_key(event)
    semantic = _legacy_semantic_notification_key(event)
    legacy = _legacy_financialjuice_notification_key(event)
    return tuple(dict.fromkeys(item for item in (current, semantic, legacy) if item))


def _summary_source_text(value: Any) -> str:
    """Return source text suitable for semantic selection, without guessing."""
    from src.telegram_client import _clean_public_fragment, _strip_public_icons

    text = _clean_public_fragment(value)
    if not text:
        return ""
    # A trailing alert icon after punctuation is a malformed relay fragment,
    # not part of the fact.  Leading/interior decorations are safe to remove
    # after this check so the final message has exactly one public icon.
    if re.search(r"[🟢🟡🟠🔴⚪⚫🟣]\s*[。！？!?，,、:：；;.\s]*$", text):
        return ""
    text = _strip_public_icons(text).strip()
    # Tickers and relay decorations are metadata around the fact.  Removing
    # them prevents an orphan ``$META $NVDA`` from becoming the whole alert;
    # the company names in the source sentence remain intact.
    text = re.sub(r"\s*\$[A-Z][A-Z0-9._-]*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _summary_source_candidates(event: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Collect all complete-source views before choosing a public sentence."""
    from src.telegram_client import _fact_text_quality, structured_public_fact

    candidates: list[tuple[str, str, int]] = []
    structured = structured_public_fact(event)
    if structured.get("complete") is True:
        text = _summary_source_text(structured.get("text"))
        if text:
            evidence = structured.get("evidence_fields")
            source_field = (
                str(evidence[0])
                if isinstance(evidence, list) and evidence and str(evidence[0]).strip()
                else "structured_fact"
            )
            candidates.append((source_field, text, 6))
    # Translations normally provide the readable public form.  ``event`` is
    # still preferred over title/brief_title because those may already be a
    # clipped notification from an older release.
    fields = (
        ("event", 5),
        ("what_happened", 5),
        ("chinese_translation", 4),
        ("vendor_translation", 4),
        ("headline", 3),
        ("original_headline", 2),
        ("vendor_original_headline", 2),
        ("title", 1),
    )
    seen: set[str] = set()
    for field, rank in fields:
        text = _summary_source_text(event.get(field))
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        # Keep low-information fields available for a valid legacy headline,
        # but make a richer source view win when both fit the same budget.
        candidates.append((field, text, rank + _fact_text_quality(text) // 5))
    return candidates


def _sentence_parts(text: str) -> list[str]:
    return [
        part.strip(" ，,、；;")
        for part in re.split(r"(?<=[。！？!?；;])", text)
        if part.strip(" ，,、；;")
    ]


def _compact_policy_fact(text: str) -> list[str]:
    """Compress a proposal without dropping the proposal's concrete object."""
    compact = _summary_source_text(text)
    match = re.search(
        r"(?P<actor>[\u4e00-\u9fffA-Za-z][^，。]{0,18}?)(?:正)?考慮(?:一項|一项)?"
        r"(?:提議|提议|提案|proposal)[，,]\s*(?:擬|拟)與"
        r"(?P<party>[^，。]+?)安排(?P<deal>「[^」]+」|\"[^\"]+\")[，,]"
        r"(?:基於|基于)(?P<detail>[^——。]+)", compact, re.IGNORECASE,
    )
    if not match:
        return []
    actor = re.sub(r"政府$", "", match.group("actor")).strip()
    detail = match.group("detail").strip()
    detail = re.sub(r"^為", "", detail)
    detail = re.sub(
        r"^(?P<who>[^，,]+?)開闢安全通道以通過(?P<place>.+)$",
        r"\g<who>開闢通過\g<place>的安全通道",
        detail,
    )
    # Keep the source's uncertainty (the administration is considering it),
    # while retaining the concrete proposal rather than the vague phrase
    # "一項提議".
    result = f"{actor}考慮與{match.group('party').strip()}安排{match.group('deal')}，為{detail}。"
    return [result]


def _compact_company_fact(text: str) -> list[str]:
    """Keep one company's action and its directly related comparison claim."""
    compact = _summary_source_text(text)
    parts = _sentence_parts(compact)
    timeline_matches: list[tuple[int, re.Match[str]]] = []
    comparison: re.Match[str] | None = None
    for index, part in enumerate(parts):
        match = re.search(
            r"(?P<actor>Meta)\s*(?:將於|将在)\s*"
            r"(?P<when>\d{4}\s*年?\s*(?:上半年|下半年|年底|年末))\s*"
            r"(?P<action>推出|部署|發布|发布)\s*(?P<product>[^。；;]+?晶片)",
            part, re.IGNORECASE,
        )
        if match:
            timeline_matches.append((index, match))
        comparison_match = re.search(
            r"Meta\s*[：:]?\s*(?:這些晶片|这些芯片)?\s*將?比"
            r"(?P<peer>輝達|英偉達|Nvidia)(?:晶片|芯片)?"
            r"更?(?P<claim>省錢|省钱)[、,，與和]?(?:更)?(?P<energy>節能|节能)",
            part, re.IGNORECASE,
        )
        if comparison_match:
            comparison = comparison_match
    if not timeline_matches:
        return []
    # Prefer the earlier deployment window when a relay reports several
    # products.  It gives the reader an immediately actionable timeline.
    _, timeline = sorted(
        timeline_matches,
        key=lambda item: (0 if "上半年" in item[1].group("when") else 1, item[0]),
    )[0]
    when = re.sub(r"\s+", "", timeline.group("when"))
    product = re.sub(r"^(?:新款|下一代)", "", timeline.group("product").strip())
    result = f"Meta擬{when}{timeline.group('action')}{product}。"
    if comparison is not None:
        result = result[:-1] + f"，稱較{comparison.group('peer')}省錢節能。"
    return [result]


def _compact_market_fact(text: str) -> list[str]:
    """Prefer concrete breadth/yield evidence over a generic market direction."""
    compact = _summary_source_text(text)
    breadth = re.search(
        r"標普500(?:指數中)?近?(?P<count>\d+)家(?:企業|公司)下跌", compact,
    )
    treasury = re.search(
        r"(?:基準)?10年期(?:公債)?殖利率觸(?:及)?(?P<yield>\d+(?:\.\d+)?%)", compact,
    )
    if not breadth and not treasury:
        return []
    facts: list[str] = []
    if breadth:
        facts.append(f"標普500近{breadth.group('count')}家公司下跌")
    if treasury:
        facts.append(f"10年債殖利率觸{treasury.group('yield')}")
    cause = ""
    if re.search(r"聯準會政策決定前避開風險性資產", compact):
        cause = "聯準會決策前避險"
    elif re.search(r"聯準會.*?避開風險性資產", compact):
        cause = "聯準會決策前避險"
    if cause and facts:
        if len(facts) == 2:
            return [f"{facts[0]}，{cause}；{facts[1]}。"]
        facts.insert(1, cause)
    return ["；".join(facts) + "。"]


def _compact_livestream_fact(text: str) -> list[str]:
    """Replace a relay's live-video wrapper with its stated discussion topic."""
    compact = _summary_source_text(text)
    match = re.search(
        r"(?P<prefix>[^。！？!?]+)[。！？!?]\s*"
        r"(?:直播影片|直播|影片)\s*[:：]\s*(?P<details>.+)$",
        compact,
        re.IGNORECASE,
    )
    if not match:
        return []
    subject_match = re.match(
        r"(?P<subject>.+?)(?:在[^，,。；;]+中)?(?:發表|发表|表示|稱|称|談|谈)",
        match.group("prefix"),
    )
    topic_match = re.search(
        r"(?:討論|讨论|談及|谈及|談到|谈到)\s*(?P<topic>[^，,。；;]+)",
        match.group("details"),
        re.IGNORECASE,
    )
    if not subject_match or not topic_match:
        return []
    return [f"{subject_match.group('subject').strip()}談{topic_match.group('topic').strip()}。"]


def _summary_variants(text: str) -> list[str]:
    """Build complete-sentence variants; never return a character slice."""
    from src.telegram_client import _fact_text_is_complete

    values: list[str] = []
    for value in (
        compact_military_fact(text),
        compact_capacity_fact(text),
        _compress_fj_sentence(text),
        *_compact_policy_fact(text),
        *_compact_company_fact(text),
        *_compact_market_fact(text),
        *_compact_livestream_fact(text),
        *_sentence_parts(_summary_source_text(text)),
    ):
        cleaned = _compress_fj_sentence(value)
        if cleaned and cleaned not in values and _fact_text_is_complete(cleaned):
            values.append(cleaned)
    return values


def _importance_for_summary(event: dict[str, Any]) -> Any:
    importance = event.get("vendor_importance")
    if importance not in (None, ""):
        return importance
    match = re.search(
        r"FJ[^0-9]{0,40}(\d+(?:\.\d+)?)\s*/\s*10",
        _text(event.get("brief_title")), re.IGNORECASE,
    )
    return match.group(1) if match else None


def financialjuice_public_summary(
    event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION,
) -> dict[str, Any]:
    """Create the single versioned, auditable FJ summary used by all views."""
    from src.telegram_client import _fact_text_quality, is_valid_public_summary

    importance = _importance_for_summary(event)
    suffix = f"FJ {importance}/10" if importance is not None else "FJ 待核對"
    prefix = f"🟣 {suffix}｜"
    body_limit = limit - len(prefix)
    ranked: list[tuple[int, int, int, str, str]] = []
    for field, source_text, source_rank in _summary_source_candidates(event):
        for variant in _summary_variants(source_text):
            if len(variant) > body_limit:
                continue
            message = prefix + variant
            if not is_valid_public_summary(message, source="financialjuice"):
                continue
            # Specificity is more important than compactness.  Source rank
            # breaks ties in favor of the translated/structured fact from the
            # same event, never a stored clipped title.
            compactness_bonus = 1 if "；" in variant else 0
            domain_fact_bonus = 2 if re.search(
                r"(?:石油休戰|荷姆茲|省錢節能|近\d+家|殖利率觸)", variant,
            ) else 0
            ranked.append((
                _fact_text_quality(variant) + compactness_bonus + domain_fact_bonus,
                source_rank, -len(variant), field, message,
            ))
    if ranked:
        _, _, _, field, message = max(ranked)
        return {
            "version": PUBLIC_SUMMARY_VERSION,
            "summary_contract_version": SUMMARY_CONTRACT_VERSION,
            "status": "ready",
            "text": message,
            "char_count": len(message),
            "source_field": field,
            "evidence_fields": [field],
            "reason": "complete_fact_selected",
        }
    return {
        "version": PUBLIC_SUMMARY_VERSION,
        "summary_contract_version": SUMMARY_CONTRACT_VERSION,
        "status": "incomplete",
        "text": "",
        "char_count": 0,
        "source_field": "",
        "evidence_fields": [],
        "reason": "summary_semantics_incomplete",
    }


def financialjuice_public_short_message(
    event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION,
) -> str:
    """Return the canonical summary text without performing transport work."""
    return str(financialjuice_public_summary(event, limit=limit).get("text") or "")


def financialjuice_caption(event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION) -> str:
    """Backward-compatible alias for the canonical public FJ message."""
    return financialjuice_public_short_message(event, limit=limit)


def _history_delivered(
    history: list[dict[str, Any]], notification_keys: tuple[str, ...], recipient_hash: str,
) -> bool:
    for row in history:
        if not isinstance(row, dict):
            continue
        if _text(row.get("notification_key")) not in set(notification_keys):
            continue
        if _text(row.get("recipient_hash") or row.get("chat_id_hash")) != recipient_hash:
            continue
        if _text(row.get("delivery_status") or row.get("status")) == "delivered":
            return True
    return False


def deliver_financialjuice_event(
    event: dict[str, Any],
    *,
    release_id: str,
    snapshot_id: str,
    mini_app_url: str,
    release_ready: bool,
    token: str,
    chat_ids: tuple[str, ...],
    photo_path: str | Path | None = None,
    delivery_history: list[dict[str, Any]] | None = None,
    photo_sender: Callable[..., tuple[Any, ...]] | None = None,
    text_sender: Callable[..., tuple[TextDeliveryReceipt, ...]] | None = None,
    ledger: Any | None = None,
    slot_key: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Deliver one eligible FJ event with recipient-level idempotency.

    The returned object is safe to persist: recipient identifiers and Telegram
    file IDs are represented only by short hashes.  A partial first attempt
    retries only recipients that did not already succeed.
    """
    notification_key = financialjuice_notification_key(event)
    notification_keys = financialjuice_notification_aliases(event)
    from src.telegram_client import PUBLIC_SUMMARY_VERSION

    stored_version = _text(event.get("public_summary_version"))
    stored_caption = _text(event.get("public_short_message"))
    if stored_version == PUBLIC_SUMMARY_VERSION:
        # The producer's v3 result is authoritative.  Delivery must not
        # choose a different clause or create a second summary identity.
        caption = stored_caption
    else:
        caption = financialjuice_caption(event, limit=MAX_FINANCIALJUICE_CAPTION)
    reasons: list[str] = []
    if stored_version == PUBLIC_SUMMARY_VERSION and event.get("public_summary_status") != "ready":
        reasons.append("summary_semantics_incomplete")
    if _text(event.get("source_key") or event.get("source")).casefold() != "financialjuice":
        reasons.append("source_not_financialjuice")
    if _text(event.get("source_key") or event.get("source")).casefold() == "financialjuice":
        freshness_status = _text(event.get("freshness_status"))
        if freshness_status != "fresh":
            reasons.append(freshness_status or "missing_source_timestamp")
    status = _text(event.get("notification_status")).casefold()
    policy = _text(event.get("delivery_policy")).casefold()
    importance = financialjuice_vendor_importance(event.get("vendor_importance"))
    explicit_priority = policy == "fj_priority"
    legacy_priority = (
        not policy
        and event.get("vendor_priority_notification") is True
        and importance is not None
        and importance >= FJ_PRIORITY_MIN_IMPORTANCE
    )
    if status != "eligible":
        reasons.append("notification_status_not_eligible")
    elif explicit_priority or legacy_priority:
        if event.get("vendor_priority_notification") is not True or importance is None or importance < FJ_PRIORITY_MIN_IMPORTANCE:
            reasons.append("fj_priority_threshold_not_met")
    elif policy == "material_event":
        # The official monitor marks this only after the normal event policy
        # and budget gates pass.  It prevents a low-score discovery row from
        # accidentally entering the vendor-priority sender directly.
        if event.get("event_policy_allowed") is not True:
            reasons.append("material_event_policy_not_verified")
    else:
        reasons.append("financialjuice_delivery_policy_missing")
    if not release_ready:
        reasons.append("release_gate_not_ready")
    if not token or not chat_ids:
        reasons.append("telegram_configuration_missing")
    if reasons:
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": reasons,
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    if not is_valid_public_summary(caption, source="financialjuice"):
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": ["content_incomplete"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }
    if not notification_key:
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": ["notification_key_missing"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    history = delivery_history or []
    pending_ids = tuple(
        chat_id for chat_id in chat_ids
        if not _history_delivered(history, notification_keys, _recipient_hash(chat_id))
    )
    claim: dict[str, Any] | None = None
    if ledger is not None and hasattr(ledger, "claim_notification"):
        claim = ledger.claim_notification(
            notification_key,
            slot_key=slot_key,
            recipient_hashes=tuple(_recipient_hash(chat_id) for chat_id in chat_ids),
            aliases=tuple(notification_keys[1:]),
            run_id=run_id,
        )
        claim_status = str(claim.get("status") or "")
        if claim_status in {"already_delivered", "in_flight", "uncertain"}:
            return {
                "status": "already_delivered" if claim_status == "already_delivered" else "blocked",
                "notification_key": notification_key,
                "reasons": [claim_status],
                "receipts": [],
                "release_id": release_id,
                "snapshot_id": snapshot_id,
            }
        allowed_hashes = set(str(item) for item in claim.get("pending_recipient_hashes") or [])
        pending_ids = tuple(chat_id for chat_id in pending_ids if _recipient_hash(chat_id) in allowed_hashes)
    if not pending_ids:
        return {
            "status": "already_delivered",
            "notification_key": notification_key,
            "reasons": ["already_delivered"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    # notification_id is the primary immutable alert identity.  Cluster/item
    # aliases remain only for legacy rows that predate the identity contract.
    alert_id = _text(event.get("notification_id") or event.get("event_cluster_key") or event.get("item_id") or event.get("observation_id"))
    observation_id = _text(event.get("observation_id"))
    target_url = alert_mini_app_url(
        mini_app_url,
        alert_id=alert_id,
        release_id=_text(release_id),
        snapshot_id=_text(snapshot_id),
        observation_id=observation_id,
    )
    # FinancialJuice is a vendor/news lane, never the Creator attachment
    # exception.  Ignore any legacy photo callback so production FJ delivery
    # can only emit one canonical text message per recipient.
    sender = text_sender or send_text_briefs_audited
    try:
        delivered = sender(
            token=token,
            chat_ids=pending_ids,
            text=caption,
            dashboard_url=mini_app_url,
            alert_id=alert_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            target_url=target_url,
            prstk_risk_level=canonical_prstk_risk_level(event),
            message_kind="financialjuice",
        )
    except Exception as exc:  # transport adapters must fail closed
        if ledger is not None and hasattr(ledger, "complete_notification_claim"):
            ledger.complete_notification_claim(notification_key, uncertain=True)
        return {
            "status": "failed",
            "notification_key": notification_key,
            "reasons": [f"delivery_exception:{type(exc).__name__}"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
            "mini_app_url": target_url,
        }

    receipts: list[dict[str, Any]] = []
    for receipt in delivered:
        receipts.append({
            "notification_key": notification_key,
            "recipient_hash": receipt.chat_id_hash,
            "delivery_status": receipt.status,
            "message_id": receipt.message_id,
            "error_class": receipt.error_class,
            "release_id": receipt.release_id,
            "snapshot_id": receipt.snapshot_id,
            "observation_id": receipt.observation_id,
            "telegram_file_id_hash": getattr(receipt, "telegram_file_id_hash", None),
        })
    delivered_count = sum(row["delivery_status"] == "delivered" for row in receipts)
    failed_count = len(receipts) - delivered_count
    failure_classes = sorted({
        _text(row.get("error_class"))
        for row in receipts
        if row.get("delivery_status") != "delivered" and _text(row.get("error_class"))
    })
    status = "delivered" if failed_count == 0 and delivered_count else "partial" if delivered_count else "failed"
    if ledger is not None and hasattr(ledger, "complete_notification_claim"):
        ledger.complete_notification_claim(
            notification_key,
            delivered_recipient_hashes=tuple(
                str(row.get("recipient_hash") or "") for row in receipts
                if row.get("delivery_status") == "delivered"
            ),
            failed_recipient_hashes=tuple(
                str(row.get("recipient_hash") or "") for row in receipts
                if row.get("delivery_status") != "delivered"
            ),
        )
    return {
        "status": status,
        "notification_key": notification_key,
        "reasons": [] if status == "delivered" else ["recipient_delivery_partial" if delivered_count else "recipient_delivery_failed"],
        "failure_classes": failure_classes,
        "receipts": receipts,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "mini_app_url": target_url,
        "vendor_importance": event.get("vendor_importance"),
        "vendor_importance_is_not_risk": event.get("source_trace", {}).get("vendor_importance_is_not_risk") is True,
        "prstk_risk": event.get("prstk_risk"),
    }


__all__ = [
    "MAX_FINANCIALJUICE_CAPTION",
    "deliver_financialjuice_event",
    "financialjuice_caption",
    "financialjuice_public_summary",
    "financialjuice_public_short_message",
    "financialjuice_notification_key",
    "financialjuice_notification_aliases",
]
