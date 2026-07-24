"""Bounded, retried public daily-bar downloads for research scans."""
from __future__ import annotations

from typing import Any, Callable


DOWNLOAD_TIMEOUT_SECONDS = 8


def download_daily_batch(
    symbols: list[str], *, downloader: Callable[..., Any] | None = None, timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
) -> Any:
    """Download a public batch once, retrying a transient failure exactly once."""
    if not symbols:
        raise ValueError("下載標的不可為空")
    if timeout <= 0:
        raise ValueError("下載逾時必須大於 0")
    if downloader is None:
        import yfinance as yf
        downloader = yf.download
    last_error: Exception | None = None
    for _ in range(2):
        try:
            data = downloader(symbols, period="6mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True, timeout=timeout)
            if data is None or getattr(data, "empty", True):
                raise ValueError("公開資料回傳空白")
            return data
        except Exception as exc:
            last_error = exc
    raise RuntimeError("公開資料批次下載失敗（已重試一次）") from last_error
