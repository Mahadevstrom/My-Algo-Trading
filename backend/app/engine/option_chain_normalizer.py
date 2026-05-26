from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class ChainExtraction:
    spot_price: float | None
    strike_map: dict[str, Any]


class OptionChainNormalizer:
    def normalize(
        self,
        raw_response: Any,
        underlying: str,
        expiry: date | str,
        spot_price: float | None = None,
    ) -> list[dict[str, Any]]:
        extraction = self.extract_chain(raw_response)
        resolved_spot = spot_price if spot_price is not None else extraction.spot_price

        rows = [
            self._base_row(underlying, expiry, strike_key, strike_payload)
            for strike_key, strike_payload in extraction.strike_map.items()
            if isinstance(strike_payload, dict)
        ]
        rows = [row for row in rows if row["strike"] is not None]
        rows.sort(key=lambda row: row["strike"])

        atm_strike = self.find_atm_strike(rows, resolved_spot)
        max_ce_oi = max([_num(row.get("ce_oi")) or 0 for row in rows], default=0)
        max_pe_oi = max([_num(row.get("pe_oi")) or 0 for row in rows], default=0)
        max_ce_volume = max([_num(row.get("ce_volume")) or 0 for row in rows], default=0)
        max_pe_volume = max([_num(row.get("pe_volume")) or 0 for row in rows], default=0)

        for row in rows:
            strike = row["strike"]
            row["atm_marker"] = "ATM" if atm_strike is not None and strike == atm_strike else None
            row["ce_moneyness"] = self._ce_moneyness(strike, resolved_spot, atm_strike)
            row["pe_moneyness"] = self._pe_moneyness(strike, resolved_spot, atm_strike)
            row["ce_spread"] = _spread(row.get("ce_bid"), row.get("ce_ask"))
            row["pe_spread"] = _spread(row.get("pe_bid"), row.get("pe_ask"))
            row["ce_liquidity_score"] = _liquidity_score(
                oi=row.get("ce_oi"),
                volume=row.get("ce_volume"),
                bid=row.get("ce_bid"),
                ask=row.get("ce_ask"),
                max_oi=max_ce_oi,
                max_volume=max_ce_volume,
            )
            row["pe_liquidity_score"] = _liquidity_score(
                oi=row.get("pe_oi"),
                volume=row.get("pe_volume"),
                bid=row.get("pe_bid"),
                ask=row.get("pe_ask"),
                max_oi=max_pe_oi,
                max_volume=max_pe_volume,
            )
            row["ce_activity"] = _activity_label(
                row.get("ce_oi"),
                row.get("ce_volume"),
                row.get("ce_spread"),
                row.get("ce_liquidity_score"),
                max_ce_oi,
                max_ce_volume,
            )
            row["pe_activity"] = _activity_label(
                row.get("pe_oi"),
                row.get("pe_volume"),
                row.get("pe_spread"),
                row.get("pe_liquidity_score"),
                max_pe_oi,
                max_pe_volume,
            )
            row["ce_oi_change"] = _first_number(row.get("_ce_raw"), ["oi_change", "change_oi", "changeinOpenInterest"])
            row["pe_oi_change"] = _first_number(row.get("_pe_raw"), ["oi_change", "change_oi", "changeinOpenInterest"])
            row["ce_buildup"] = "UNKNOWN"
            row["pe_buildup"] = "UNKNOWN"
            row.pop("_ce_raw", None)
            row.pop("_pe_raw", None)

        return rows

    def extract_chain(self, raw_response: Any) -> ChainExtraction:
        payload = raw_response
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("Data", payload))

        spot_price = None
        if isinstance(payload, dict):
            spot_price = _first_number(
                payload,
                ["last_price", "lastPrice", "ltp", "LTP", "spot", "spot_price", "underlyingValue"],
            )
            for key in ("oc", "optionChain", "option_chain", "optionData"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    return ChainExtraction(spot_price=spot_price, strike_map=nested)
                if isinstance(nested, list):
                    return ChainExtraction(spot_price=spot_price, strike_map=_list_to_strike_map(nested))

        if isinstance(payload, list):
            return ChainExtraction(spot_price=spot_price, strike_map=_list_to_strike_map(payload))
        if isinstance(payload, dict):
            return ChainExtraction(spot_price=spot_price, strike_map=payload)
        return ChainExtraction(spot_price=spot_price, strike_map={})

    def find_atm_strike(
        self, rows: list[dict[str, Any]], spot_price: float | None
    ) -> float | None:
        if spot_price is None or not rows:
            return None
        return min(rows, key=lambda row: abs(row["strike"] - spot_price))["strike"]

    def _base_row(
        self,
        underlying: str,
        expiry: date | str,
        strike_key: Any,
        strike_payload: dict[str, Any],
    ) -> dict[str, Any]:
        ce = _leg(strike_payload, "ce")
        pe = _leg(strike_payload, "pe")
        strike = _num(
            _first_present(strike_payload, ["strike", "strike_price", "strikePrice"], fallback=strike_key)
        )
        return {
            "underlying": underlying.upper(),
            "expiry": str(expiry),
            "strike": strike,
            "ce_ltp": _first_number(ce, ["last_price", "lastPrice", "ltp", "LTP"]),
            "pe_ltp": _first_number(pe, ["last_price", "lastPrice", "ltp", "LTP"]),
            "ce_oi": _first_number(ce, ["oi", "open_interest", "openInterest"]),
            "pe_oi": _first_number(pe, ["oi", "open_interest", "openInterest"]),
            "ce_volume": _first_number(ce, ["volume", "volume_traded", "volumeTraded"]),
            "pe_volume": _first_number(pe, ["volume", "volume_traded", "volumeTraded"]),
            "ce_iv": _first_number(ce, ["implied_volatility", "iv", "IV"]),
            "pe_iv": _first_number(pe, ["implied_volatility", "iv", "IV"]),
            "ce_delta": _first_number(ce, ["delta"]),
            "pe_delta": _first_number(pe, ["delta"]),
            "ce_gamma": _first_number(ce, ["gamma"]),
            "pe_gamma": _first_number(pe, ["gamma"]),
            "ce_theta": _first_number(ce, ["theta"]),
            "pe_theta": _first_number(pe, ["theta"]),
            "ce_vega": _first_number(ce, ["vega"]),
            "pe_vega": _first_number(pe, ["vega"]),
            "ce_bid": _best_bid(ce),
            "ce_ask": _best_ask(ce),
            "pe_bid": _best_bid(pe),
            "pe_ask": _best_ask(pe),
            "_ce_raw": ce,
            "_pe_raw": pe,
        }

    def _ce_moneyness(
        self, strike: float, spot_price: float | None, atm_strike: float | None
    ) -> str | None:
        if atm_strike is not None and strike == atm_strike:
            return "ATM"
        if spot_price is None:
            return None
        return "ITM_CE" if strike < spot_price else "OTM_CE"

    def _pe_moneyness(
        self, strike: float, spot_price: float | None, atm_strike: float | None
    ) -> str | None:
        if atm_strike is not None and strike == atm_strike:
            return "ATM"
        if spot_price is None:
            return None
        return "ITM_PE" if strike > spot_price else "OTM_PE"


def _list_to_strike_map(items: list[Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        strike = _first_present(item, ["strike", "strike_price", "strikePrice"])
        if strike is not None:
            mapped[str(strike)] = item
    return mapped


def _leg(payload: dict[str, Any], side: str) -> dict[str, Any]:
    keys = [side, side.upper(), side.capitalize()]
    if side.lower() == "ce":
        keys.extend(["call", "CALL"])
    else:
        keys.extend(["put", "PUT"])
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _first_present(source: dict[str, Any], keys: list[str], fallback: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return fallback


def _first_number(source: dict[str, Any] | None, keys: list[str]) -> float | None:
    if not isinstance(source, dict):
        return None
    return _num(_first_present(source, keys))


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _best_bid(leg: dict[str, Any]) -> float | None:
    direct = _first_number(
        leg,
        ["best_bid_price", "bid_price", "bidPrice", "bid", "buy_price", "buyPrice"],
    )
    if direct is not None:
        return direct
    depth = leg.get("depth") if isinstance(leg.get("depth"), dict) else {}
    buy = depth.get("buy") if isinstance(depth.get("buy"), list) else []
    if buy and isinstance(buy[0], dict):
        return _first_number(buy[0], ["price", "bid_price", "bidPrice"])
    return None


def _best_ask(leg: dict[str, Any]) -> float | None:
    direct = _first_number(
        leg,
        ["best_ask_price", "ask_price", "askPrice", "ask", "sell_price", "sellPrice"],
    )
    if direct is not None:
        return direct
    depth = leg.get("depth") if isinstance(leg.get("depth"), dict) else {}
    sell = depth.get("sell") if isinstance(depth.get("sell"), list) else []
    if sell and isinstance(sell[0], dict):
        return _first_number(sell[0], ["price", "ask_price", "askPrice"])
    return None


def _spread(bid: Any, ask: Any) -> float | None:
    bid_value = _num(bid)
    ask_value = _num(ask)
    if bid_value is None or ask_value is None or bid_value <= 0 or ask_value <= 0:
        return None
    return round(max(ask_value - bid_value, 0), 4)


def _liquidity_score(
    oi: Any,
    volume: Any,
    bid: Any,
    ask: Any,
    max_oi: float,
    max_volume: float,
) -> int:
    oi_value = _num(oi) or 0
    volume_value = _num(volume) or 0
    bid_value = _num(bid)
    ask_value = _num(ask)

    oi_score = 35 * (oi_value / max_oi) if max_oi > 0 else 0
    volume_score = 40 * (volume_value / max_volume) if max_volume > 0 else 0

    if bid_value is None or ask_value is None or bid_value <= 0 or ask_value <= 0:
        spread_score = 5
    else:
        mid = (bid_value + ask_value) / 2
        spread_pct = ((ask_value - bid_value) / mid * 100) if mid > 0 else 100
        spread_score = max(0, 25 - min(spread_pct * 5, 25))

    return int(round(max(0, min(100, oi_score + volume_score + spread_score))))


def _activity_label(
    oi: Any,
    volume: Any,
    spread: Any,
    liquidity_score: Any,
    max_oi: float,
    max_volume: float,
) -> str:
    oi_value = _num(oi) or 0
    volume_value = _num(volume) or 0
    spread_value = _num(spread)
    score = _num(liquidity_score) or 0

    if spread_value is None and score < 25:
        return "LOW_ACTIVITY"
    if spread_value is not None and spread_value > 0 and score < 45:
        return "WIDE_SPREAD"
    if max_oi > 0 and oi_value >= max_oi * 0.70:
        return "HIGH_OI"
    if max_volume > 0 and volume_value >= max_volume * 0.70:
        return "HIGH_VOLUME"
    if score >= 60:
        return "LIQUID"
    return "LOW_ACTIVITY"

