from __future__ import annotations

from time import monotonic
from typing import Any
from urllib.parse import urlencode

import httpx

from app.market.schemas import clean_response, utc_timestamp


NSE_BASE_URL = "https://www.nseindia.com"
NSE_INDEX_ALIASES = {
    "NIFTY": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "NIFTY 50": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "NIFTYBANK": "NIFTY BANK",
    "NIFTY BANK": "NIFTY BANK",
}
NSE_NIFTY50_PAGE = f"{NSE_BASE_URL}/market-data/live-equity-market?symbol=NIFTY%2050"
NSE_NIFTY50_API = f"{NSE_BASE_URL}/api/equity-stock-indices?index=NIFTY%2050"
NSE_OPTION_CHAIN_PAGE = f"{NSE_BASE_URL}/option-chain"

DEFAULT_CACHE_TTL_SECONDS = 45.0
STATIC_CACHE_TTL_SECONDS = 6 * 60 * 60.0


class NseDataAdapter:
    """Read-only NSE public market-data adapter.

    The public NSE site expects a browser-style warmup request before JSON API calls.
    This adapter keeps that behavior in one place and uses short in-memory caching so
    dashboard polling does not repeatedly hit NSE for the same payload.
    """

    _cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, float, dict[str, Any]]] = {}

    def __init__(self) -> None:
        self.timeout = httpx.Timeout(20.0)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json,text/plain,*/*",
        }

    async def get_nifty50_quotes(self) -> dict[str, Any]:
        response = await self.get_index_quotes("NIFTY 50")
        if not response.get("ok"):
            return response
        response["normalized"] = self.normalize_nifty50_response(response.get("data") or {})
        return response

    async def get_index_quotes(self, index: str = "NIFTY 50") -> dict[str, Any]:
        nse_index = normalize_nse_index_name(index)
        response = await self.get_equity_stock_indices(nse_index)
        if not response.get("ok"):
            return response
        response["index"] = nse_index
        response["normalized"] = self.normalize_equity_index_response(response.get("data") or {}, nse_index)
        return response

    async def get_all_indices(self) -> dict[str, Any]:
        return await self._get_json(
            "/api/allIndices",
            referer=f"{NSE_BASE_URL}/market-data/live-market-indices",
        )

    async def get_index_names(self) -> dict[str, Any]:
        return await self._get_json(
            "/api/index-names",
            referer=NSE_NIFTY50_PAGE,
            cache_ttl=STATIC_CACHE_TTL_SECONDS,
        )

    async def get_equity_master(self) -> dict[str, Any]:
        return await self._get_json(
            "/api/equity-master",
            referer=NSE_NIFTY50_PAGE,
            cache_ttl=STATIC_CACHE_TTL_SECONDS,
        )

    async def get_equity_stock_indices(self, index: str = "NIFTY 50") -> dict[str, Any]:
        return await self._get_json(
            "/api/equity-stock-indices",
            params={"index": index},
            referer=f"{NSE_BASE_URL}/market-data/live-equity-market?symbol={index.replace(' ', '%20')}",
        )

    async def get_pre_open_market(self, key: str = "NIFTY") -> dict[str, Any]:
        return await self._get_json(
            "/api/market-data-pre-open",
            params={"key": key.upper()},
            referer=f"{NSE_BASE_URL}/market-data/pre-open-market-cm-and-emerge-market",
        )

    async def get_live_analysis_variations(self, side: str = "gainers") -> dict[str, Any]:
        nse_side = "loosers" if side.lower() in {"loser", "losers", "looser", "loosers"} else "gainers"
        response = await self._get_json(
            "/api/live-analysis-variations",
            params={"index": nse_side},
            referer=f"{NSE_BASE_URL}/market-data/top-gainers-losers",
        )
        response["side"] = "losers" if nse_side == "loosers" else "gainers"
        return response

    async def get_most_active_equities(self, by: str = "value") -> dict[str, Any]:
        metric = "volume" if by.lower() == "volume" else "value"
        response = await self._get_json(
            "/api/live-analysis-most-active-securities",
            params={"index": metric},
            referer=f"{NSE_BASE_URL}/market-data/most-active-equities",
        )
        response["metric"] = metric
        return response

    async def get_option_contract_info(self, symbol: str) -> dict[str, Any]:
        return await self._get_json(
            "/api/option-chain-contract-info",
            params={"symbol": symbol.upper()},
            referer=NSE_OPTION_CHAIN_PAGE,
            cache_ttl=10 * 60.0,
        )

    async def get_option_chain(
        self,
        symbol: str,
        *,
        segment: str = "indices",
        expiry: str | None = None,
    ) -> dict[str, Any]:
        resolved_symbol = symbol.upper()
        resolved_segment = "Equity" if segment.lower() in {"equity", "stock", "stocks"} else "Indices"
        resolved_expiry = expiry
        contract_info: dict[str, Any] | None = None

        if not resolved_expiry:
            contract_response = await self.get_option_contract_info(resolved_symbol)
            if not contract_response.get("ok"):
                return contract_response
            contract_info = contract_response.get("data") if isinstance(contract_response.get("data"), dict) else {}
            expiries = contract_info.get("expiryDates") if isinstance(contract_info, dict) else None
            if not isinstance(expiries, list) or not expiries:
                return clean_response(
                    ok=False,
                    connected=True,
                    status="EXPIRY_NOT_FOUND",
                    message="NSE did not return any option expiries for this symbol.",
                    symbol=resolved_symbol,
                    segment=resolved_segment,
                    data=contract_info,
                )
            resolved_expiry = str(expiries[0])

        response = await self._get_json(
            "/api/option-chain-v3",
            params={"type": resolved_segment, "symbol": resolved_symbol, "expiry": resolved_expiry},
            referer=NSE_OPTION_CHAIN_PAGE,
        )
        response["symbol"] = resolved_symbol
        response["segment"] = resolved_segment
        response["expiry"] = resolved_expiry
        if contract_info is not None:
            response["contract_info"] = contract_info
        if response.get("ok"):
            response["normalized"] = self.normalize_option_chain_response(response.get("data") or {})
        return response

    async def get_historical_security(
        self,
        symbol: str,
        *,
        from_date: str,
        to_date: str,
        series: str = "EQ",
        data_type: str = "priceVolumeDeliverable",
    ) -> dict[str, Any]:
        response = await self._get_json(
            "/api/historicalOR/generateSecurityWiseHistoricalData",
            params={
                "symbol": symbol.upper(),
                "series": series.upper(),
                "from": from_date,
                "to": to_date,
                "type": data_type,
            },
            referer=f"{NSE_BASE_URL}/report-detail/eq_security",
            cache_ttl=10 * 60.0,
        )
        if response.get("ok"):
            response["normalized"] = self.normalize_security_history_response(response.get("data") or {})
        return response

    async def get_historical_price_volume(
        self,
        symbol: str,
        *,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        return await self._get_json(
            "/api/historicalOR/priceAndVolumeDataPerSecurity",
            params={"symbol": symbol.upper(), "from": from_date, "to": to_date},
            referer=f"{NSE_BASE_URL}/reports-indices-historical-index-data",
            cache_ttl=10 * 60.0,
        )

    async def get_historical_index(
        self,
        index_type: str,
        *,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        response = await self._get_json(
            "/api/historicalOR/indicesHistory",
            params={"indexType": index_type.upper(), "from": from_date, "to": to_date},
            referer=f"{NSE_BASE_URL}/reports-indices-historical-index-data",
            cache_ttl=10 * 60.0,
        )
        if response.get("ok"):
            response["normalized"] = self.normalize_index_history_response(response.get("data") or {})
        return response

    async def get_historical_vix(self, *, from_date: str, to_date: str) -> dict[str, Any]:
        response = await self._get_json(
            "/api/historicalOR/vixhistory",
            params={"from": from_date, "to": to_date},
            referer=f"{NSE_BASE_URL}/reports-indices-historical-index-data",
            cache_ttl=10 * 60.0,
        )
        if response.get("ok"):
            response["normalized"] = self.normalize_index_history_response(response.get("data") or {})
        return response

    async def get_daily_reports(self, key: str = "CM") -> dict[str, Any]:
        response = await self._get_json(
            "/api/daily-reports",
            params={"key": key.upper()},
            referer=f"{NSE_BASE_URL}/all-reports",
            cache_ttl=10 * 60.0,
        )
        if response.get("ok"):
            response["files"] = self.normalize_report_files(response.get("data"))
        return response

    async def get_monthly_reports(self, key: str = "CM") -> dict[str, Any]:
        response = await self._get_json(
            "/api/monthly-reports",
            params={"key": key.upper()},
            referer=f"{NSE_BASE_URL}/all-reports",
            cache_ttl=30 * 60.0,
        )
        if response.get("ok"):
            response["files"] = self.normalize_report_files(response.get("data"))
        return response

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        referer: str = NSE_BASE_URL,
        cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> dict[str, Any]:
        request_params = {key: str(value) for key, value in (params or {}).items() if value is not None}
        cache_key = (path, tuple(sorted(request_params.items())))
        cached = self._cache.get(cache_key)
        now = monotonic()
        if cached and now - cached[0] <= cached[1]:
            cached_response = dict(cached[2])
            cached_response["cache"] = "HIT"
            return cached_response

        source_url = _build_url(path, request_params)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
            ) as client:
                await client.get(
                    referer,
                    headers={**self.headers, "Accept": "text/html,*/*"},
                )
                response = await client.get(
                    source_url,
                    headers={
                        **self.headers,
                        "Referer": referer,
                    },
                )
        except httpx.TimeoutException:
            return clean_response(
                ok=False,
                connected=False,
                status="TIMEOUT",
                message="NSE request timed out.",
                source="NSE",
                source_url=source_url,
            )
        except httpx.HTTPError as exc:
            return clean_response(
                ok=False,
                connected=False,
                status="API_ERROR",
                message=f"NSE request failed: {type(exc).__name__}.",
                source="NSE",
                source_url=source_url,
            )

        if response.status_code >= 400:
            return clean_response(
                ok=False,
                connected=False,
                status="API_ERROR",
                message=f"NSE request returned HTTP {response.status_code}.",
                source="NSE",
                http_status=response.status_code,
                source_url=source_url,
            )

        payload = _safe_json(response)
        if not isinstance(payload, (dict, list)):
            return clean_response(
                ok=False,
                connected=False,
                status="INVALID_RESPONSE",
                message="NSE response was not JSON.",
                source="NSE",
                source_url=source_url,
            )

        result = clean_response(
            ok=True,
            connected=True,
            status="CONNECTED",
            message="NSE read-only request completed.",
            source="NSE",
            data=payload,
            source_url=source_url,
            cache="MISS",
        )
        self._cache[cache_key] = (now, cache_ttl, result)
        return result

    def normalize_nifty50_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return self.normalize_equity_index_response(payload, "NIFTY 50")

    def normalize_equity_index_response(self, payload: dict[str, Any], index_name: str) -> list[dict[str, Any]]:
        items = []
        timestamp = payload.get("timestamp") or utc_timestamp()
        normalized_index = normalize_nse_index_name(index_name)
        for row in payload.get("data", []):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or symbol == normalized_index:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "ltp": _to_float(row.get("lastPrice")),
                    "open": _to_float(row.get("open")),
                    "high": _to_float(row.get("dayHigh")),
                    "low": _to_float(row.get("dayLow")),
                    "close": _to_float(row.get("previousClose")),
                    "change": _to_float(row.get("change")),
                    "change_percent": _to_float(row.get("pChange")),
                    "volume": _to_float(row.get("totalTradedVolume")),
                    "value": _to_float(row.get("totalTradedValue")),
                    "source": "NSE",
                    "timestamp": timestamp,
                    "data_status": "OK",
                }
            )
        return items

    def normalize_option_chain_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        records = payload.get("records") if isinstance(payload, dict) else None
        rows = records.get("data") if isinstance(records, dict) else None
        if not isinstance(rows, list):
            return []

        items: list[dict[str, Any]] = []
        timestamp = records.get("timestamp") or utc_timestamp()
        underlying_value = _to_float(records.get("underlyingValue"))
        for row in rows:
            if not isinstance(row, dict):
                continue
            strike = _to_float(row.get("strikePrice"))
            expiry = row.get("expiryDate") or row.get("expiryDates")
            for option_type in ("CE", "PE"):
                leg = row.get(option_type)
                if not isinstance(leg, dict):
                    continue
                items.append(
                    {
                        "strike": strike,
                        "option_type": option_type,
                        "expiry": leg.get("expiryDate") or expiry,
                        "ltp": _to_float(leg.get("lastPrice")),
                        "change": _to_float(leg.get("change")),
                        "change_percent": _to_float(leg.get("pChange") or leg.get("PChange")),
                        "oi": _to_float(leg.get("openInterest")),
                        "oi_change": _to_float(leg.get("changeinOpenInterest")),
                        "volume": _to_float(leg.get("totalTradedVolume")),
                        "iv": _to_float(leg.get("impliedVolatility")),
                        "bid": _to_float(leg.get("buyPrice1")),
                        "ask": _to_float(leg.get("sellPrice1")),
                        "underlying_value": underlying_value,
                        "source": "NSE",
                        "timestamp": timestamp,
                    }
                )
        return items

    def normalize_security_history_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            items.append(
                {
                    "symbol": row.get("CH_SYMBOL"),
                    "series": row.get("CH_SERIES"),
                    "date": row.get("mTIMESTAMP") or row.get("CH_TIMESTAMP"),
                    "open": _to_float(row.get("CH_OPENING_PRICE")),
                    "high": _to_float(row.get("CH_TRADE_HIGH_PRICE")),
                    "low": _to_float(row.get("CH_TRADE_LOW_PRICE")),
                    "close": _to_float(row.get("CH_CLOSING_PRICE")),
                    "last": _to_float(row.get("CH_LAST_TRADED_PRICE")),
                    "previous_close": _to_float(row.get("CH_PREVIOUS_CLS_PRICE")),
                    "vwap": _to_float(row.get("VWAP")),
                    "volume": _to_float(row.get("CH_TOT_TRADED_QTY")),
                    "value": _to_float(row.get("CH_TOT_TRADED_VAL")),
                    "trades": _to_float(row.get("CH_TOTAL_TRADES")),
                    "deliverable_quantity": _to_float(row.get("COP_DELIV_QTY")),
                    "deliverable_percent": _to_float(row.get("COP_DELIV_PERC")),
                    "source": "NSE",
                }
            )
        return items

    def normalize_index_history_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            items.append(
                {
                    "index": row.get("EOD_INDEX_NAME"),
                    "date": row.get("EOD_TIMESTAMP") or row.get("TIMESTAMP"),
                    "open": _to_float(row.get("EOD_OPEN_INDEX_VAL")),
                    "high": _to_float(row.get("EOD_HIGH_INDEX_VAL")),
                    "low": _to_float(row.get("EOD_LOW_INDEX_VAL")),
                    "close": _to_float(row.get("EOD_CLOSE_INDEX_VAL")),
                    "previous_close": _to_float(row.get("EOD_PREV_CLOSE")),
                    "change": _to_float(row.get("EOD_PTS_CHG") or row.get("VIX_PTS_CHG")),
                    "change_percent": _to_float(row.get("EOD_PERC_CHG") or row.get("VIX_PERC_CHG")),
                    "volume": _to_float(row.get("HIT_TRADED_QTY")),
                    "turnover": _to_float(row.get("HIT_TURN_OVER")),
                    "source": "NSE",
                }
            )
        return items

    def normalize_report_files(self, payload: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(payload, list):
            rows.extend(row for row in payload if isinstance(row, dict))
        elif isinstance(payload, dict):
            for bucket in ("CurrentDay", "PreviousDay", "FutureDay"):
                value = payload.get(bucket)
                if isinstance(value, list):
                    for row in value:
                        if isinstance(row, dict):
                            rows.append({**row, "bucket": bucket})

        files: list[dict[str, Any]] = []
        for row in rows:
            file_path = str(row.get("filePath") or "")
            file_name = str(row.get("fileActlName") or "")
            files.append(
                {
                    "bucket": row.get("bucket"),
                    "segment": row.get("fileSegment"),
                    "name": _strip_html(str(row.get("displayName") or row.get("fileKey") or "")),
                    "file_name": file_name or None,
                    "trading_date": row.get("tradingDate") or row.get("tradeDate"),
                    "download_url": f"{file_path}{file_name}" if file_path and file_name else None,
                    "source": "NSE",
                }
            )
        return files


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _build_url(path: str, params: dict[str, str]) -> str:
    url = f"{NSE_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def normalize_nse_index_name(value: str) -> str:
    key = value.strip().upper().replace("-", " ").replace("_", " ")
    compact = key.replace(" ", "")
    return NSE_INDEX_ALIASES.get(key) or NSE_INDEX_ALIASES.get(compact) or value.strip().upper()


def _to_float(value: Any) -> float | None:
    try:
        if value in {None, "-", ""}:
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _strip_html(value: str) -> str:
    return " ".join(value.replace("<sup>&reg;</sup>", "").replace("&amp;", "&").split())
