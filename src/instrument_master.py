"""Point-in-time instrument identity and cross-market symbol mapping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    ticker: str
    name: str
    market: str
    asset_type: str
    currency: str
    timezone: str
    symbols: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    isin: str | None = None
    sec_cik: str | None = None
    listed_from: date | None = None
    listed_until: date | None = None

    def matches(self, query: str) -> bool:
        normalized = "".join(str(query).casefold().split())
        values = (self.instrument_id, self.ticker, self.name, *self.symbols, *self.aliases)
        return any(normalized == "".join(str(value).casefold().split()) for value in values)

    def active_on(self, as_of: date) -> bool:
        return (self.listed_from is None or as_of >= self.listed_from) and (
            self.listed_until is None or as_of <= self.listed_until
        )

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["symbols"] = list(self.symbols)
        record["aliases"] = list(self.aliases)
        record["listed_from"] = self.listed_from.isoformat() if self.listed_from else None
        record["listed_until"] = self.listed_until.isoformat() if self.listed_until else None
        return record


DEFAULT_INSTRUMENTS = (
    Instrument("twse:taiex", "TAIEX", "TAIEX", "taiwan", "index", "TWD", "Asia/Taipei", ("^TWII",), ("台股加權",)),
    Instrument("tpex:index", "TPEx", "TPEx", "taiwan", "index", "TWD", "Asia/Taipei", ("^TWOII",), ("臺灣櫃買指數",)),
    Instrument("twse:2330", "2330", "台積電", "taiwan", "equity", "TWD", "Asia/Taipei", ("2330.TW",), ("TSMC", "台積")),
    Instrument("us:tsm", "TSM", "Taiwan Semiconductor ADR", "us", "equity", "USD", "America/New_York", ("TSM",), ("台積電ADR",)),
    Instrument("us:nvda", "NVDA", "NVIDIA", "us", "equity", "USD", "America/New_York", ("NVDA",)),
    Instrument("us:nasdaq", "NASDAQ", "NASDAQ Composite", "us", "index", "USD", "America/New_York", ("^IXIC",), ("Nasdaq",)),
    Instrument("global:btc", "BTC", "Bitcoin", "global", "crypto", "USD", "UTC", ("BTC-USD", "BTCUSDT"), ("比特幣",)),
    Instrument("global:eth", "ETH", "Ethereum", "global", "crypto", "USD", "UTC", ("ETH-USD", "ETHUSDT"), ("以太坊",)),
)


class InstrumentMaster:
    """Lookup registry that rejects ambiguous aliases instead of guessing."""

    def __init__(self, instruments: list[Instrument] | tuple[Instrument, ...] = DEFAULT_INSTRUMENTS) -> None:
        self._instruments = tuple(instruments)
        self._index: dict[str, list[Instrument]] = {}
        for instrument in self._instruments:
            for value in (instrument.instrument_id, instrument.ticker, instrument.name, *instrument.symbols, *instrument.aliases):
                key = self._key(value)
                if key:
                    self._index.setdefault(key, []).append(instrument)

    @staticmethod
    def _key(value: Any) -> str:
        return "".join(str(value or "").casefold().split())

    def validate(self) -> list[str]:
        issues: list[str] = []
        for key, matches in self._index.items():
            unique_ids = {item.instrument_id for item in matches}
            if len(unique_ids) > 1:
                issues.append(f"ambiguous alias: {key}")
        return issues

    def resolve(self, query: str, *, market: str | None = None, as_of: date | None = None) -> Instrument:
        matches = list(self._index.get(self._key(query), ()))
        if market:
            matches = [item for item in matches if item.market == market]
        if as_of:
            matches = [item for item in matches if item.active_on(as_of)]
        if not matches:
            raise KeyError(f"instrument not found: {query}")
        unique = {item.instrument_id: item for item in matches}
        if len(unique) != 1:
            raise ValueError(f"ambiguous instrument: {query}")
        return next(iter(unique.values()))

    def all(self, *, market: str | None = None, asset_type: str | None = None) -> list[Instrument]:
        return [
            item for item in self._instruments
            if (market is None or item.market == market) and (asset_type is None or item.asset_type == asset_type)
        ]

    def save(self, path: Path | str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps({"schema_version": 1, "instruments": [item.to_dict() for item in self._instruments]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> InstrumentMaster:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("instruments", []) if isinstance(payload, dict) else []
        instruments = []
        for row in rows:
            instruments.append(
                Instrument(
                    **{**row,
                       "symbols": tuple(row.get("symbols") or ()),
                       "aliases": tuple(row.get("aliases") or ()),
                       "listed_from": date.fromisoformat(row["listed_from"]) if row.get("listed_from") else None,
                       "listed_until": date.fromisoformat(row["listed_until"]) if row.get("listed_until") else None}
                )
            )
        return cls(tuple(instruments))
