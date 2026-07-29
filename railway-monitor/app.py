"""Railway bridge: Jin10 MCP Flash -> signed GitHub repository_dispatch.

The service intentionally performs no scraping.  It calls Jin10's official MCP
``list_flash`` tool, records seen IDs locally, and only forwards in-scope events.
GitHub independently verifies the HMAC signature and de-duplicates the event.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx


JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '(war OR invasion OR ceasefire OR sanctions OR Hormuz OR tariff OR "export controls" OR semiconductor OR earthquake OR tsunami OR cyberattack OR ransomware OR pandemic OR Bitcoin OR Ethereum)'
GITHUB_API_VERSION = "2022-11-28"
ALLOWED_CATEGORIES = {"fed", "macro", "policy", "conflict", "energy", "semiconductor", "market", "black_swan", "material_positive"}
CATEGORY_LABELS = {
    "black_swan": "黑天鵝",
    "material_positive": "重大正向",
    "fed": "Fed",
    "macro": "宏觀",
    "policy": "政策",
    "conflict": "地緣",
    "energy": "能源",
    "semiconductor": "半導體",
    "market": "市場",
}

# These are deliberately conservative.  A flash must contain one of these
# expressions before it can create a public alert; everything else is merely
# marked as seen and never forwarded.
CATEGORY_KEYWORDS = {
    "fed": ("fomc", "federal reserve", "powell", "聯準會", "美联储", "鮑威爾", "鲍威尔"),
    "macro": ("cpi", "pce", "非農", "非农", "失業率", "失业率", "gdp", "通膨", "通胀"),
    "policy": ("關稅", "关税", "制裁", "出口管制", "政策", "tariff", "sanction", "duties", "duty", "trade war"),
    "conflict": ("戰爭", "战争", "軍事", "军事", "導彈", "导弹", "停火", "中東", "中东", "invasion", "iran", "israel", "ukraine", "russia", "truce", "ceasefire", "airstrike"),
    "energy": ("wti", "brent", "原油", "油價", "油价", "opec", "crude oil", "oil supply"),
    "semiconductor": ("nvidia", "輝達", "英伟达", "台積電", "台积电", "tsmc", "半導體", "半导体"),
    "market": ("熔斷", "熔断", "閃崩", "闪崩", "crash", "circuit breaker"),
}
ESCALATION_TERMS = (
    "擴大", "升级", "升級", "加徵", "加征", "大幅", "急升", "急跌", "供應中斷", "供应中断",
    "additional", "increase", "airstrike", "missile", "attack", "supply disruption", "supply cut",
)

# A discovery item is never sufficient on its own. GDELT candidates must have
# two independent domains from this conservative set and share a concrete
# event anchor before they can reach the signed GitHub dispatch bridge.
TRUSTED_NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "nytimes.com", "bbc.com", "cnbc.com", "nikkei.com",
}
DISCOVERY_ANCHORS = {
    "conflict": ("iran", "israel", "ukraine", "russia", "hormuz", "taiwan"),
    "policy": ("tariff", "sanction", "export control", "duties"),
    "energy": ("wti", "brent", "oil", "opec", "crude"),
    "semiconductor": ("nvidia", "tsmc", "asml", "semiconductor"),
    "black_swan": ("earthquake", "tsunami", "ransomware", "cyberattack", "pandemic"),
    "material_positive": ("ceasefire", "truce", "peace deal", "tariff exemption", "rate cut"),
}


# These require a confirmed, broadly material event. They deliberately are not
# a catch-all for ordinary geopolitical headlines or routine market moves.
BLACK_SWAN_TERMS = (
    "major earthquake", "magnitude 7", "magnitude 8", "tsunami", "nuclear accident",
    "重大地震", "強震", "規模7", "規模8", "海嘯", "核事故", "大規模停電",
    "金融危機", "銀行擠兌", "交易所遭駭", "重大駭客", "circuit breaker",
)
MATERIAL_POSITIVE_TERMS = (
    "ceasefire agreement", "ceasefire", "truce agreement", "peace deal",
    "tariff exemption", "tariff removal", "rate cut", "停火協議", "停火", "休戰協議",
    "和平協議", "關稅豁免", "取消關稅", "降息",
)


@dataclass(frozen=True)
class Flash:
    event_id: str
    title: str
    content: str
    occurred_at: str

    @property
    def text(self) -> str:
        return " ".join(part for part in (self.title, self.content) if part).strip()


@dataclass(frozen=True)
class Alert:
    event_id: str
    category: str
    summary: str
    occurred_at: str
    source: str = "jin10"

    @property
    def canonical(self) -> str:
        return "\n".join((self.source, self.event_id, self.category, self.summary, self.occurred_at))


@dataclass(frozen=True)
class DiscoveryArticle:
    title: str
    url: str
    domain: str
    seen_at: str


def configured(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required Railway variable: {name}")
    return value


def classify_flash(flash: Flash) -> str | None:
    haystack = flash.text.casefold()
    if any(keyword.casefold() in haystack for keyword in BLACK_SWAN_TERMS):
        return "black_swan"
    if any(keyword.casefold() in haystack for keyword in MATERIAL_POSITIVE_TERMS):
        return "material_positive"
    # Oil headlines are material only when supply, a large move, or a
    # geopolitical catalyst is also present. This avoids routine daily oil
    # commentary becoming a Telegram emergency alert.
    if any(keyword.casefold() in haystack for keyword in CATEGORY_KEYWORDS["energy"]):
        material_energy_terms = ("iran", "israel", "中東", "中东", "supply", "供應", "供给", "opec", "attack", "戰爭", "战争", "停火", "ceasefire", "truce", "%")
        if any(term.casefold() in haystack for term in material_energy_terms):
            return "energy"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "energy":
            continue
        if any(keyword.casefold() in haystack for keyword in keywords):
            return category
    return None


def compact_summary(flash: Flash, category: str) -> str:
    """Keep the eventual Telegram body below 30 characters.

    GitHub forms ``緊急｜分類｜摘要``.  A 20-character summary leaves room for
    every currently allowed Chinese category label and avoids watch truncation.
    """
    text = re.sub(r"\s+", " ", flash.text).strip()
    label = CATEGORY_LABELS[category]
    prefix = f"{label}："
    available = 20 - len(prefix)
    return f"{prefix}{text[:max(1, available)]}".rstrip("，。；： ")


def alert_from_flash(flash: Flash) -> Alert | None:
    category = classify_flash(flash)
    if category is None or category not in ALLOWED_CATEGORIES:
        return None
    return Alert(
        event_id=f"jin10-{flash.event_id}",
        category=category,
        summary=compact_summary(flash, category),
        occurred_at=flash.occurred_at,
    )


def extract_flashes(value: Any) -> list[Flash]:
    """Extract the documented Flash item fields from an MCP tool response."""
    found: list[Flash] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            event_id = item.get("id")
            content = item.get("content")
            occurred_at = item.get("time")
            if event_id is not None and content is not None and occurred_at is not None:
                found.append(
                    Flash(
                        event_id=str(event_id),
                        title=str(item.get("title") or ""),
                        content=str(content),
                        occurred_at=str(occurred_at),
                    )
                )
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    deduped: dict[str, Flash] = {flash.event_id: flash for flash in found}
    return list(deduped.values())


def result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    texts: list[Any] = []
    for block in getattr(result, "content", []) or []:
        raw = getattr(block, "text", None)
        if raw is None:
            continue
        try:
            texts.append(json.loads(raw))
        except json.JSONDecodeError:
            texts.append(raw)
    return texts


class SeenStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS seen (event_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS dispatched (category TEXT NOT NULL, summary TEXT NOT NULL, dispatched_at TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS cache (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, refreshed_at TEXT NOT NULL)"
        )
        self.connection.commit()

    def add_if_new(self, event_id: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO seen(event_id, first_seen_at) VALUES (?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def may_dispatch(self, alert: Alert, cooldown_seconds: int) -> bool:
        """Allow a category update after cooldown, or immediately on escalation."""
        row = self.connection.execute(
            "SELECT summary, dispatched_at FROM dispatched WHERE category = ? ORDER BY rowid DESC LIMIT 1",
            (alert.category,),
        ).fetchone()
        if row is None:
            return True
        previous_summary, previous_time = row
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(previous_time)).total_seconds()
        except ValueError:
            return True
        if elapsed >= cooldown_seconds:
            return True
        current = alert.summary.casefold()
        previous = str(previous_summary).casefold()
        return any(term.casefold() in current and term.casefold() not in previous for term in ESCALATION_TERMS)

    def record_dispatch(self, alert: Alert) -> None:
        self.connection.execute(
            "INSERT INTO dispatched(category, summary, dispatched_at) VALUES (?, ?, ?)",
            (alert.category, alert.summary, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def read_cache(self, cache_key: str, max_age_seconds: int) -> list[dict[str, str]] | None:
        row = self.connection.execute(
            "SELECT payload, refreshed_at FROM cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        payload, refreshed_at = row
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(refreshed_at)).total_seconds()
            cached = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return cached if age <= max_age_seconds and isinstance(cached, list) else None

    def write_cache(self, cache_key: str, payload: list[dict[str, str]]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO cache(cache_key, payload, refreshed_at) VALUES (?, ?, ?)",
            (cache_key, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()


def sign(alert: Alert, shared_secret: str) -> str:
    digest = hmac.new(shared_secret.encode("utf-8"), alert.canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def dispatch_alert(alert: Alert, *, token: str, repository: str, shared_secret: str) -> None:
    payload = {
        "event_type": "external-market-alert",
        "client_payload": {
            "source": alert.source,
            "event_id": alert.event_id,
            "category": alert.category,
            "summary": alert.summary,
            "occurred_at": alert.occurred_at,
            "signature": sign(alert, shared_secret),
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"https://api.github.com/repos/{repository}/dispatches", headers=headers, json=payload)
    response.raise_for_status()


def default_flash_arguments(schema: dict[str, Any], requested_limit: int) -> dict[str, Any]:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {"limit": requested_limit} if "limit" in properties else {}


async def fetch_jin10_flashes(token: str, requested_limit: int) -> list[Flash]:
    """Call only the official MCP endpoint; no HTML or feed scraping occurs."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        async with streamable_http_client(JIN10_MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool = next((item for item in tools.tools if item.name == "list_flash"), None)
                if tool is None:
                    raise RuntimeError("Jin10 MCP did not expose the list_flash tool")
                arguments = default_flash_arguments(getattr(tool, "inputSchema", {}), requested_limit)
                try:
                    result = await session.call_tool("list_flash", arguments=arguments)
                except Exception:
                    if not arguments:
                        raise
                    logging.warning("list_flash rejected the optional limit; retrying without arguments")
                    result = await session.call_tool("list_flash", arguments={})
    return extract_flashes(result_payload(result))


def _gdelt_seen_at(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _trusted_domain(url: str, supplied_domain: str) -> str:
    host = (supplied_domain or urlparse(url).hostname or "").lower().removeprefix("www.")
    return next((domain for domain in TRUSTED_NEWS_DOMAINS if host == domain or host.endswith(f".{domain}")), "")


def _discovery_category_and_anchor(title: str) -> tuple[str, str] | None:
    normalized = title.casefold()
    category = classify_flash(Flash("discovery", title, "", ""))
    if category is None:
        return None
    anchor = next((term for term in DISCOVERY_ANCHORS.get(category, ()) if term in normalized), "")
    return (category, anchor) if anchor else None


def _decode_discovery_articles(rows: list[dict[str, str]]) -> list[DiscoveryArticle]:
    return [DiscoveryArticle(**row) for row in rows]


async def fetch_gdelt_articles(store: SeenStore | None = None) -> list[DiscoveryArticle]:
    """Fetch discovery headlines with a 15-minute cache and 120-minute fallback."""
    if store:
        cached = store.read_cache("gdelt-success", 15 * 60)
        if cached is not None:
            return _decode_discovery_articles(cached)
    params = {"query": GDELT_QUERY, "mode": "artlist", "format": "json", "sort": "datedesc", "maxrecords": 75}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(GDELT_DOC_URL, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429 and store:
            stale = store.read_cache("gdelt-success", 120 * 60)
            if stale is not None:
                logging.warning("GDELT rate-limited; using the most recent cached success")
                return _decode_discovery_articles(stale)
        raise
    cutoff = datetime.now(timezone.utc).timestamp() - 45 * 60
    articles: list[DiscoveryArticle] = []
    for row in response.json().get("articles", []):
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        seen_at = str(row.get("seendate") or "").strip()
        observed = _gdelt_seen_at(seen_at)
        domain = _trusted_domain(url, str(row.get("domain") or ""))
        if not title or not url or not observed or observed.timestamp() < cutoff or not domain:
            continue
        articles.append(DiscoveryArticle(title=title, url=url, domain=domain, seen_at=observed.isoformat()))
    if store:
        store.write_cache("gdelt-success", [article.__dict__ for article in articles])
    return articles


def cross_checked_gdelt_alerts(articles: Iterable[DiscoveryArticle]) -> list[Alert]:
    """Require two trusted publishers and a shared, concrete event anchor."""
    clusters: dict[tuple[str, str], list[DiscoveryArticle]] = {}
    for article in articles:
        classified = _discovery_category_and_anchor(article.title)
        if classified:
            clusters.setdefault(classified, []).append(article)
    alerts: list[Alert] = []
    for (category, anchor), cluster in clusters.items():
        domains = {article.domain for article in cluster}
        if len(domains) < 2:
            continue
        representative = min(cluster, key=lambda article: article.seen_at)
        stable_id = hashlib.sha256("|".join(sorted(article.url for article in cluster)).encode("utf-8")).hexdigest()[:20]
        alerts.append(Alert(
            event_id=f"gdelt-{category}-{stable_id}",
            category=category,
            summary=f"{CATEGORY_LABELS[category]}：{anchor}多源核對",
            occurred_at=representative.seen_at,
            source="gdelt",
        ))
    return alerts


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/health"}:
            self.send_error(404)
            return
        body = b'{"status":"ok","service":"prstk-jin10-monitor"}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Health endpoint listening on port %s", port)


async def monitor_forever() -> None:
    jin10_token = configured("JIN10_MCP_TOKEN")
    github_token = configured("GITHUB_DISPATCH_TOKEN")
    repository = configured("GITHUB_REPOSITORY")
    shared_secret = configured("EXTERNAL_ALERT_SHARED_SECRET")
    interval = max(60, int(os.environ.get("JIN10_POLL_SECONDS", "120")))
    limit = min(100, max(1, int(os.environ.get("JIN10_FLASH_LIMIT", "30"))))
    cooldown = max(1800, int(os.environ.get("JIN10_CATEGORY_COOLDOWN_SECONDS", "1800")))
    bootstrap = os.environ.get("JIN10_INITIAL_BACKFILL", "false").lower() == "true"
    gdelt_interval = max(900, int(os.environ.get("GDELT_POLL_SECONDS", "900")))
    store = SeenStore(Path(os.environ.get("MONITOR_STATE_PATH", "/data/jin10-monitor.sqlite3")))
    first_cycle = True
    gdelt_baseline = True
    last_gdelt_poll = 0.0

    while True:
        try:
            flashes = await fetch_jin10_flashes(jin10_token, limit)
            flashes.sort(key=lambda item: item.occurred_at)
            dispatched = 0
            for flash in flashes:
                if not store.add_if_new(flash.event_id):
                    continue
                alert = alert_from_flash(flash)
                if alert is None or (first_cycle and not bootstrap):
                    continue
                if not store.may_dispatch(alert, cooldown):
                    logging.info("Jin10 alert suppressed by category cooldown: %s", alert.category)
                    continue
                await dispatch_alert(alert, token=github_token, repository=repository, shared_secret=shared_secret)
                store.record_dispatch(alert)
                dispatched += 1
            logging.info("Jin10 poll completed: %s flash(es), %s alert(s) dispatched", len(flashes), dispatched)
            first_cycle = False
        except Exception:
            logging.exception("Jin10 poll failed; will retry")
        if time.monotonic() - last_gdelt_poll >= gdelt_interval:
            last_gdelt_poll = time.monotonic()
            try:
                articles = await fetch_gdelt_articles(store)
                alerts = cross_checked_gdelt_alerts(articles)
                dispatched = 0
                for alert in alerts:
                    if not store.add_if_new(alert.event_id) or (gdelt_baseline and not bootstrap):
                        continue
                    if not store.may_dispatch(alert, gdelt_interval if gdelt_interval >= 1800 else 7200):
                        continue
                    await dispatch_alert(alert, token=github_token, repository=repository, shared_secret=shared_secret)
                    store.record_dispatch(alert)
                    dispatched += 1
                logging.info("GDELT cross-check completed: %s article(s), %s alert(s) dispatched", len(articles), dispatched)
                gdelt_baseline = False
            except Exception:
                logging.exception("GDELT discovery failed; will wait for the next interval")
        await asyncio.sleep(interval)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    start_health_server()
    asyncio.run(monitor_forever())


if __name__ == "__main__":
    main()
