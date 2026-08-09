"""Public BTC/ETH spot quotes used by the phase-five cross-check gate."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import requests

from src.provider_health import classify_provider_error, error_token

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_US_TICKER_URL = "https://api.binance.us/api/v3/ticker/24hr"
COINGECKO_SIMPLE_URL = "https://api.coingecko.com/api/v3/simple/price"
ASSETS = {
    "BTC": {"binance": "BTCUSDT", "coingecko": "bitcoin"},
    "ETH": {"binance": "ETHUSDT", "coingecko": "ethereum"},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _health(
    status: str,
    checked_at: str,
    errors: list[str],
    item_count: int,
    *,
    error_details: list[dict[str, Any]] | None = None,
    fallback_used: bool = False,
) -> dict[str, Any]:
    return {
        "key": "crypto_spot",
        "source_key": "crypto_spot",
        "label": "BTC／ETH Binance／CoinGecko 現貨核對",
        "source_tier": "public-market",
        "source_url": COINGECKO_SIMPLE_URL,
        "status": status,
        "checked_at": checked_at,
        "item_count": item_count,
        "data_gap": errors or None,
        "error_details": error_details or None,
        "fallback_used": fallback_used,
    }


def _request_json(
    requester: Callable[..., Any], url: str, *, params: dict[str, Any], timeout: int
) -> Any:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = requester(
                url,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "PRStK-Lab/1.0"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                continue
    raise last_error or RuntimeError("public provider request failed")


def fetch_crypto_spot_snapshot(*, timeout: int = 15, requester: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Fetch Binance as primary and CoinGecko as independent secondary data.

    Each provider is isolated. A missing provider produces an explicit health
    gap and never causes the whole market snapshot to fail.
    """
    requester = requester or requests.get
    checked_at = _now()
    primary: dict[str, dict[str, Any]] = {}
    secondary: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    fallback_used = False

    for ticker, config in ASSETS.items():
        row: Any = None
        selected_url = BINANCE_TICKER_URL
        selected_domain = "api.binance.com"
        try:
            row = _request_json(requester, BINANCE_TICKER_URL, params={"symbol": config["binance"]}, timeout=timeout)
        except Exception as primary_exc:
            # Binance.US is a same-provider-family availability fallback.  It
            # keeps the card observable during regional blocks, but it never
            # counts as the independent CoinGecko cross-check.
            try:
                row = _request_json(
                    requester,
                    BINANCE_US_TICKER_URL,
                    params={"symbol": config["binance"]},
                    timeout=timeout,
                )
                selected_url = BINANCE_US_TICKER_URL
                selected_domain = "api.binance.us"
                fallback_used = True
            except Exception as fallback_exc:
                errors.append(error_token("binance", ticker, primary_exc))
                errors.append(error_token("binance_us", ticker, fallback_exc))
                error_details.extend(
                    [
                        {"provider": "binance", "item": ticker, **classify_provider_error(primary_exc)},
                        {"provider": "binance_us", "item": ticker, **classify_provider_error(fallback_exc)},
                    ]
                )
                continue
        try:
            price = float(row["lastPrice"])
            primary[ticker] = {
                "ticker": ticker,
                "price": price,
                "change_percent": float(row.get("priceChangePercent", 0.0)),
                "quote_time": datetime.fromtimestamp(int(row.get("closeTime", 0)) / 1000, UTC).isoformat()
                if row.get("closeTime") else checked_at,
                "quote_basis": "盤中",
                "quote_source": "Binance.US public spot quote" if selected_domain == "api.binance.us" else "Binance public spot quote",
                "source_url": f"{selected_url}?symbol={config['binance']}",
                "source_domain": selected_domain,
            }
        except Exception as exc:
            errors.append(error_token("binance", ticker, exc))
            error_details.append({"provider": "binance", "item": ticker, **classify_provider_error(exc)})

    try:
        payload = _request_json(
            requester,
            COINGECKO_SIMPLE_URL,
            params={
                "ids": ",".join(config["coingecko"] for config in ASSETS.values()),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            },
            timeout=timeout,
        )
        for ticker, config in ASSETS.items():
            row = payload.get(config["coingecko"]) or {}
            updated = row.get("last_updated_at")
            if row.get("usd") is None:
                raise ValueError(f"missing:{ticker}")
            secondary[ticker] = {
                "ticker": ticker,
                "price": float(row["usd"]),
                "change_percent": float(row.get("usd_24h_change") or 0.0),
                "quote_time": datetime.fromtimestamp(int(updated), UTC).isoformat() if updated else checked_at,
                "quote_basis": "盤中",
                "quote_source": "CoinGecko public spot quote",
                "source_url": f"{COINGECKO_SIMPLE_URL}?ids={config['coingecko']}",
                "source_domain": "api.coingecko.com",
            }
    except Exception as exc:
        errors.append(error_token("coingecko", "spot", exc))
        error_details.append({"provider": "coingecko", "item": "spot", **classify_provider_error(exc)})

    status = "healthy" if primary and secondary and not errors else "partial" if primary or secondary else "failed"
    return {
        "status": status,
        "primary": primary,
        "secondary": secondary,
        "errors": errors,
        "error_details": error_details,
        "fallback_used": fallback_used,
        "fetched_at": checked_at,
        "health": _health(
            status,
            checked_at,
            errors,
            len(primary) + len(secondary),
            error_details=error_details,
            fallback_used=fallback_used,
        ),
    }
