"""Failure-isolated batch downloader for public market research data."""
from __future__ import annotations
from collections.abc import Callable, Iterable
from typing import Any

def batches(items: list[dict[str, Any]], size: int = 50) -> Iterable[list[dict[str, Any]]]:
    if size < 1: raise ValueError("批次大小必須大於 0")
    for start in range(0, len(items), size): yield items[start:start + size]

def download_in_batches(items: list[dict[str, Any]], fetch: Callable[[list[dict[str, Any]]], dict[str, Any]], size: int = 50) -> tuple[dict[str, Any], list[str]]:
    data, errors = {}, []
    for group in batches(items, size):
        try: data.update(fetch(group))
        except Exception: errors.extend(f"{item['ticker']} 批次資料暫時無法取得" for item in group)
    return data, errors
