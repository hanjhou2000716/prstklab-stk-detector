"""Canonical instrument identity and alias resolution.

The master is deliberately a local registry. Fetchers may refresh constituent
records later, but every downstream quote/event must resolve to one canonical
instrument before it is compared or published.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


class InstrumentError(ValueError):
    """Base error for invalid or ambiguous instrument identity."""


class AmbiguousInstrument(InstrumentError):
    """Raised when an alias resolves to more than one instrument."""


def _alias(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().casefold())


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    date.fromisoformat(raw)
    return raw


def _cik(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = re.sub(r"\D", "", str(value))
    if not raw:
        return None
    return raw.zfill(10)


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    ticker: str
    symbol: str
    name: str
    market: str
    exchange: str
    asset_type: str
    currency: str
    timezone: str
    calendar: str
    aliases: tuple[str, ...] = ()
    isin: str | None = None
    sec_cik: str | None = None
    listed_from: str | None = None
    listed_to: str | None = None
    source_url: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Instrument:
        ticker = str(value.get("ticker") or "").strip().upper()
        symbol = str(value.get("symbol") or ticker).strip()
        market = str(value.get("market") or "").strip().lower()
        exchange = str(value.get("exchange") or market).strip().upper()
        if not ticker or not market or not exchange:
            raise InstrumentError("ticker, market and exchange are required")
        instrument_id = str(value.get("instrument_id") or f"{market}:{exchange}:{ticker}").strip()
        aliases = tuple(dict.fromkeys(str(item).strip() for item in (value.get("aliases") or ()) if str(item).strip()))
        return cls(
            instrument_id=instrument_id,
            ticker=ticker,
            symbol=symbol,
            name=str(value.get("name") or ticker).strip(),
            market=market,
            exchange=exchange,
            asset_type=str(value.get("asset_type") or "equity").strip().lower(),
            currency=str(value.get("currency") or ("TWD" if market == "taiwan" else "USD")).strip().upper(),
            timezone=str(value.get("timezone") or ("Asia/Taipei" if market == "taiwan" else "America/New_York")).strip(),
            calendar=str(value.get("calendar") or exchange).strip().upper(),
            aliases=aliases,
            isin=str(value.get("isin")).strip() if value.get("isin") else None,
            sec_cik=_cik(value.get("sec_cik") or value.get("cik")),
            listed_from=_date(value.get("listed_from")),
            listed_to=_date(value.get("listed_to")),
            source_url=str(value.get("source_url")).strip() if value.get("source_url") else None,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.instrument_id:
            errors.append("instrument_id is required")
        if not self.ticker or not self.symbol:
            errors.append("ticker and symbol are required")
        if not self.name:
            errors.append("name is required")
        if not self.currency or not self.timezone or not self.calendar:
            errors.append("currency, timezone and calendar are required")
        if self.listed_from and self.listed_to and self.listed_from > self.listed_to:
            errors.append("listed_from must not be after listed_to")
        if self.sec_cik and (not self.sec_cik.isdigit() or len(self.sec_cik) != 10):
            errors.append("sec_cik must be a zero-padded ten-digit string")
        return errors

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"aliases": list(self.aliases)}


class InstrumentMaster:
    """In-memory master with deterministic, collision-safe alias lookup."""

    def __init__(self, instruments: Iterable[Instrument] = ()) -> None:
        self._instruments: dict[str, Instrument] = {}
        self._aliases: dict[str, set[str]] = {}
        for item in instruments:
            self.add(item)

    def add(self, instrument: Instrument) -> None:
        errors = instrument.validate()
        if errors:
            raise InstrumentError(f"{instrument.instrument_id}: {'; '.join(errors)}")
        existing = self._instruments.get(instrument.instrument_id)
        if existing and existing != instrument:
            raise InstrumentError(f"conflicting instrument_id: {instrument.instrument_id}")
        keys = [instrument.instrument_id, instrument.ticker, instrument.symbol, instrument.name, *instrument.aliases]
        normalized = {_alias(key) for key in keys if _alias(key)}
        for key in normalized:
            owners = self._aliases.get(key, set()) - {instrument.instrument_id}
            if owners:
                raise AmbiguousInstrument(f"alias collision for {key}: {sorted(owners)}")
        self._instruments[instrument.instrument_id] = instrument
        for key in normalized:
            self._aliases.setdefault(key, set()).add(instrument.instrument_id)

    def resolve(self, value: str, *, market: str | None = None) -> Instrument:
        key = _alias(value)
        candidates = [self._instruments[item] for item in sorted(self._aliases.get(key, set()))]
        if market:
            candidates = [item for item in candidates if item.market == market.lower()]
        if not candidates:
            raise InstrumentError(f"instrument not found: {value}")
        if len(candidates) > 1:
            raise AmbiguousInstrument(f"instrument alias is ambiguous: {value}")
        return candidates[0]

    def validate(self) -> dict[str, list[str]]:
        return {key: errors for key, item in self._instruments.items() if (errors := item.validate())}

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "instruments": [item.as_dict() for item in self._instruments.values()]}

    def save(self, path: Path | str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, path: Path | str) -> InstrumentMaster:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("instruments", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise InstrumentError("instrument master must contain an instruments list")
        return cls(Instrument.from_mapping(row) for row in rows if isinstance(row, dict))

    def __len__(self) -> int:
        return len(self._instruments)


DEFAULT_INSTRUMENTS = (
    Instrument.from_mapping({"ticker": "2330", "symbol": "2330.TW", "name": "台積電", "market": "taiwan", "exchange": "TWSE", "currency": "TWD", "timezone": "Asia/Taipei", "calendar": "XTAI", "aliases": ["TSM", "台積電"]}),
    Instrument.from_mapping({"ticker": "NVDA", "symbol": "NVDA", "name": "NVIDIA", "market": "us", "exchange": "NASDAQ", "currency": "USD", "timezone": "America/New_York", "calendar": "XNYS", "aliases": ["Nvidia"]}),
    Instrument.from_mapping({"ticker": "TAIEX", "symbol": "^TWII", "name": "臺灣加權指數", "market": "taiwan", "exchange": "TWSE", "asset_type": "index", "currency": "TWD", "timezone": "Asia/Taipei", "calendar": "XTAI", "aliases": ["加權指數", "台指"]}),
    Instrument.from_mapping({"ticker": "NASDAQ", "symbol": "^IXIC", "name": "Nasdaq Composite", "market": "us", "exchange": "NASDAQ", "asset_type": "index", "currency": "USD", "timezone": "America/New_York", "calendar": "XNYS", "aliases": ["納斯達克", "那斯達克"]}),
)