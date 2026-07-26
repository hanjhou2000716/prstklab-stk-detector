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

import httpx


JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
GITHUB_API_VERSION = "2022-11-28"
ALLOWED_CATEGORIES = {"fed", "macro", "policy", "conflict", "semiconductor", "market"}
CATEGORY_LABELS = {
    "fed": "Fed",
    "macro": "宏觀",
    "policy": "政策",
    "conflict": "衝突",
    "semiconductor": "半導體",
    "market": "市場",
}

# These are deliberately conservative.  A flash must contain one of these
# expressions before it can create a public alert; everything else is merely
# marked as seen and never forwarded.
CATEGORY_KEYWORDS = {
    "fed": ("fomc", "federal reserve", "powell", "聯準會", "美联储", "鮑威爾", "鲍威尔"),
    "macro": ("cpi", "pce", "非農", "非农", "失業率", "失业率", "gdp", "通膨", "通胀"),
    "policy": ("關稅", "关税", "制裁", "出口管制", "政策", "tariff", "sanction"),
    "conflict": ("戰爭", "战争", "軍事", "军事", "導彈", "导弹", "停火", "中東", "中东", "invasion"),
    "semiconductor": ("nvidia", "輝達", "英伟达", "台積電", "台积电", "tsmc", "半導體", "半导体"),
    "market": ("熔斷", "熔断", "閃崩", "闪崩", "crash", "circuit breaker"),
}


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

    @property
    def canonical(self) -> str:
        return "\n".join(("jin10", self.event_id, self.category, self.summary, self.occurred_at))


def configured(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required Railway variable: {name}")
    return value


def classify_flash(flash: Flash) -> str | None:
    haystack = flash.text.casefold()
    for category, keywords in CATEGORY_KEYWORDS.items():
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
        self.connection.commit()

    def add_if_new(self, event_id: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO seen(event_id, first_seen_at) VALUES (?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()
        return cursor.rowcount == 1


def sign(alert: Alert, shared_secret: str) -> str:
    digest = hmac.new(shared_secret.encode("utf-8"), alert.canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def dispatch_alert(alert: Alert, *, token: str, repository: str, shared_secret: str) -> None:
    payload = {
        "event_type": "external-market-alert",
        "client_payload": {
            "source": "jin10",
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
    bootstrap = os.environ.get("JIN10_INITIAL_BACKFILL", "false").lower() == "true"
    store = SeenStore(Path(os.environ.get("MONITOR_STATE_PATH", "/data/jin10-monitor.sqlite3")))
    first_cycle = True

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
                await dispatch_alert(alert, token=github_token, repository=repository, shared_secret=shared_secret)
                dispatched += 1
            logging.info("Jin10 poll completed: %s flash(es), %s alert(s) dispatched", len(flashes), dispatched)
            first_cycle = False
        except Exception:
            logging.exception("Jin10 poll failed; will retry")
        await asyncio.sleep(interval)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    start_health_server()
    asyncio.run(monitor_forever())


if __name__ == "__main__":
    main()
