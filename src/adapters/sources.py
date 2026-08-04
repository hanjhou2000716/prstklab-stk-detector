"""Concrete endpoint declarations for the first-party/public adapters."""

from __future__ import annotations

from .base import HttpSourceAdapter


class TwseAdapter(HttpSourceAdapter):
    provider = "twse"
    source_tier = "official"
    endpoint = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    source_url = endpoint
    response_format = "json"


class TaifexAdapter(HttpSourceAdapter):
    provider = "taifex"
    source_tier = "official"
    endpoint = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
    source_url = endpoint
    response_format = "text"


class TpexAdapter(HttpSourceAdapter):
    provider = "tpex"
    source_tier = "official"
    endpoint = "https://www.tpex.org.tw/www/zh-tw/afterTrading/marketHighlights"
    source_url = endpoint
    response_format = "json"


class YahooAdapter(HttpSourceAdapter):
    provider = "yahoo"
    source_tier = "public-market"
    endpoint = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
    source_url = endpoint
    response_format = "json"


class SecAdapter(HttpSourceAdapter):
    provider = "sec"
    source_tier = "official"
    endpoint = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-k&count=100&output=atom"
    source_url = endpoint
    response_format = "text"
    default_headers = {"Accept": "application/atom+xml, application/xml", "User-Agent": "PRStK-Lab/1.0 (+https://github.com/hanjhou2000716/prstklab-stk-detector)"}


class FredAdapter(HttpSourceAdapter):
    provider = "fred"
    source_tier = "official"
    endpoint = "https://api.stlouisfed.org/fred/series/observations"
    source_url = endpoint
    response_format = "json"
    required_env = "FRED_API_KEY"
    credential_param = "api_key"


class EiaAdapter(HttpSourceAdapter):
    provider = "eia"
    source_tier = "official"
    endpoint = "https://api.eia.gov/v2/"
    source_url = endpoint
    response_format = "json"
    required_env = "EIA_API_KEY"
    credential_param = "api_key"


class BinanceAdapter(HttpSourceAdapter):
    provider = "binance"
    source_tier = "public-market"
    endpoint = "https://api.binance.com/api/v3/ticker/24hr"
    source_url = endpoint
    response_format = "json"


class GdeltAdapter(HttpSourceAdapter):
    provider = "gdelt"
    source_tier = "discovery"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    source_url = endpoint
    response_format = "json"