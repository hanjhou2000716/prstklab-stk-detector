"""Official Jin10 MCP source adapter for the Railway monitor."""

from __future__ import annotations

from typing import Any

import httpx


def default_flash_arguments(schema: dict[str, Any], requested_limit: int) -> dict[str, Any]:
    """Only send arguments advertised by the official MCP schema."""
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {"limit": requested_limit} if "limit" in properties else {}


async def fetch_jin10_flashes(
    token: str,
    requested_limit: int,
    *,
    endpoint: str,
) -> list[Any]:
    """Call the official ``list_flash`` tool without scraping or guessing."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        async with streamable_http_client(endpoint, http_client=client) as (read, write, _):
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
                    result = await session.call_tool("list_flash", arguments={})
                return result.content
