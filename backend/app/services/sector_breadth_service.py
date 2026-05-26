from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from app.audit.audit_logger import AuditLogger
from app.brokers.dhan_data import DhanDataAdapter
from app.brokers.nse_data import NseDataAdapter
from app.config import settings
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.market_breadth.heavyweight_analyzer import analyze_heavyweights
from app.market_breadth.sector_rotation_score import calculate_sector_stats, market_breadth_from_sectors
from app.market_breadth.sector_universe import (
    INDEX_CONSTITUENTS,
    SECTOR_UNIVERSE,
    all_symbols,
    index_constituents,
    index_display_name,
    normalize_index as normalize_index_key,
    normalize_sector,
)


class SectorBreadthService:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_at: dict[str, float] = {}
        self._last_updated_at: datetime | None = None
        self._last_audit_at: dict[str, float] = {}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.enable_sector_breadth_engine,
            "default_index": settings.sector_breadth_default_index,
            "symbol_count": len(all_symbols()),
            "sector_count": len(SECTOR_UNIVERSE),
            "cache_seconds": settings.sector_breadth_cache_seconds,
            "data_sources": {
                "dhan": settings.sector_breadth_use_dhan,
                "indstocks_cross_check": settings.sector_breadth_use_indstocks_cross_check,
                "indstocks_required": settings.sector_breadth_require_indstocks,
            },
            "last_updated_at": self._last_updated_at.isoformat() if self._last_updated_at else None,
            "live_order_status": settings.safety_status["live_order_status"],
            "supported_indices": sorted(INDEX_CONSTITUENTS),
            "supported_sectors": sorted(SECTOR_UNIVERSE),
        }

    async def summary(self, db: Session, index: str = "NIFTY", force_refresh: bool = False) -> dict[str, Any]:
        normalized_index = _normalize_index(index)
        if normalized_index not in INDEX_CONSTITUENTS:
            return _error("INVALID_INDEX", "This index is not configured for sector breadth.", index=normalized_index)
        if not settings.enable_sector_breadth_engine:
            return _error("ENGINE_DISABLED", "Sector breadth engine is disabled by config.", index=normalized_index)
        if normalized_index != "NIFTY":
            return await self._constituent_index_summary(db, normalized_index, force_refresh)

        cached = self._get_cache(normalized_index, force_refresh)
        if cached is not None:
            return cached

        resolved = self._resolve_symbols(db)
        quote_result = await self._fetch_quotes(resolved, normalized_index)
        quotes_by_symbol = quote_result["quotes_by_symbol"]
        sectors = []
        for sector, definition in SECTOR_UNIVERSE.items():
            sector_quotes = [quotes_by_symbol[symbol] for symbol in definition.symbols if symbol in quotes_by_symbol]
            missing = [
                symbol
                for symbol in definition.symbols
                if symbol not in resolved["resolved_symbols"] or quotes_by_symbol.get(symbol, {}).get("data_status") != "OK"
            ]
            sectors.append(calculate_sector_stats(sector, sector_quotes, missing))

        sectors = sorted(sectors, key=lambda item: item.get("sector_score", 0), reverse=True)
        breadth = market_breadth_from_sectors(sectors, settings.sector_breadth_min_sectors_for_market_bias)
        heavyweights = analyze_heavyweights(quotes_by_symbol)
        nifty_confirmation = self._nifty_confirmation(sectors, breadth, heavyweights)
        rotation = self._rotation(sectors)
        now = datetime.now(timezone.utc)
        status = self._summary_status(breadth, quote_result)
        result = {
            "ok": True,
            "index": normalized_index,
            "status": status,
            "source": quote_result.get("source", "DHAN"),
            "secondary_data_status": self._secondary_data_status(),
            "data_status": breadth.get("data_status"),
            "breadth_bias": breadth.get("breadth_bias"),
            "market_breadth": breadth,
            "risk_on_score": breadth.get("risk_on_score", 0),
            "risk_off_score": breadth.get("risk_off_score", 0),
            "sector_count": len(SECTOR_UNIVERSE),
            "resolved_symbol_count": len(resolved["resolved_symbols"]),
            "missing_symbol_count": len(resolved["missing_symbols"]),
            "missing_symbols": resolved["missing_symbols"],
            "quote_status": quote_result["status"],
            "quote_message": quote_result["message"],
            "sectors": sectors,
            "rotation": rotation,
            "leading_sectors": rotation["leading_sectors"],
            "lagging_sectors": rotation["lagging_sectors"],
            "heavyweight_contribution": heavyweights,
            "nifty_confirmation": nifty_confirmation,
            "warnings": self._warnings(status, resolved, quote_result, nifty_confirmation),
            "generated_at": now.isoformat(),
            "live_order_status": settings.safety_status["live_order_status"],
        }
        self._set_cache(normalized_index, result)
        self._last_updated_at = now
        self._audit(db, self._audit_event(status, nifty_confirmation), "Sector breadth summary generated.", "INFO")
        return result

    async def sectors(self, db: Session, index: str = "NIFTY") -> dict[str, Any]:
        summary = await self.summary(db, index)
        return {
            "ok": summary.get("ok", False),
            "index": summary.get("index", index),
            "status": summary.get("status"),
            "items": summary.get("sectors", []),
            "leading_sectors": summary.get("leading_sectors", []),
            "lagging_sectors": summary.get("lagging_sectors", []),
            "generated_at": summary.get("generated_at"),
        }

    async def sector_detail(self, db: Session, sector: str) -> dict[str, Any]:
        normalized = normalize_sector(sector)
        if normalized not in SECTOR_UNIVERSE:
            return _error("INVALID_SECTOR", "Sector is not configured in the Phase 1.18 sector universe.", sector=normalized)
        summary = await self.summary(db, settings.sector_breadth_default_index)
        for item in summary.get("sectors", []):
            if item.get("sector") == normalized:
                return {"ok": True, "status": item.get("data_status"), "sector": normalized, "item": item}
        return _error("NO_DATA", "Sector breadth data is not available for this sector.", sector=normalized)

    async def nifty_confirmation(self, db: Session) -> dict[str, Any]:
        summary = await self.summary(db, settings.sector_breadth_default_index)
        return {"ok": summary.get("ok", False), "index": summary.get("index"), **summary.get("nifty_confirmation", {})}

    async def heavyweights(self, db: Session) -> dict[str, Any]:
        summary = await self.summary(db, settings.sector_breadth_default_index)
        return {"ok": summary.get("ok", False), "index": summary.get("index"), **summary.get("heavyweight_contribution", {})}

    async def heatmap(self, db: Session) -> dict[str, Any]:
        summary = await self.summary(db, settings.sector_breadth_default_index)
        items = []
        for sector in summary.get("sectors", []):
            for symbol in sector.get("strongest_symbols", []) + sector.get("weakest_symbols", []):
                items.append(
                    {
                        "sector": sector.get("sector"),
                        "symbol": symbol.get("symbol"),
                        "change_percent": symbol.get("change_percent"),
                        "ltp": symbol.get("ltp"),
                        "sector_score": sector.get("sector_score"),
                        "sector_bias": sector.get("sector_bias"),
                        "data_status": symbol.get("data_status"),
                    }
                )
        return {
            "ok": True,
            "index": summary.get("index"),
            "status": summary.get("status"),
            "items": items,
            "generated_at": summary.get("generated_at"),
        }

    async def constituents(self, db: Session, index: str = "NIFTY") -> dict[str, Any]:
        normalized_index = _normalize_index(index)
        constituents = index_constituents(normalized_index)
        if constituents is None:
            return _error("INVALID_INDEX", "This index is not configured for constituents.", index=normalized_index)
        if not settings.enable_sector_breadth_engine:
            return _error("ENGINE_DISABLED", "Sector breadth engine is disabled by config.", index=normalized_index)

        resolved = self._resolve_constituents(db, constituents)
        quote_result = await self._fetch_quotes(resolved, normalized_index)
        quotes_by_symbol = quote_result["quotes_by_symbol"]
        items = []
        for constituent in constituents:
            quote = quotes_by_symbol.get(constituent.symbol, {})
            change_percent = _to_float(quote.get("change_percent"))
            ltp = _to_float(quote.get("ltp"))
            previous_close = _to_float(quote.get("previous_close"))
            data_status = quote.get("data_status") or (
                "NO_INSTRUMENT" if constituent.symbol in resolved["missing_symbols"] else "NO_QUOTE"
            )
            items.append(
                {
                    "company_name": constituent.company_name,
                    "industry": constituent.industry,
                    "symbol": constituent.symbol,
                    "resolved_symbol": resolved["resolved_symbols"].get(constituent.symbol, {}).get("resolved_symbol"),
                    "security_id": quote.get("security_id") or resolved["resolved_symbols"].get(constituent.symbol, {}).get("security_id"),
                    "ltp": ltp,
                    "previous_close": previous_close,
                    "change_percent": change_percent,
                    "change_value": round(ltp - previous_close, 2) if ltp is not None and previous_close is not None else None,
                    "volume": _to_float(quote.get("volume")),
                    "data_status": data_status,
                    "source": quote.get("source", "DHAN"),
                    "last_updated_at": quote.get("last_updated_at"),
                }
            )

        sorted_items = sorted(
            items,
            key=lambda item: (
                item.get("change_percent") is not None,
                item.get("change_percent") or -9999,
            ),
            reverse=True,
        )
        for index_number, item in enumerate(sorted_items, start=1):
            item["rank"] = index_number

        available = [item for item in sorted_items if item.get("data_status") == "OK"]
        gainers = [item for item in available if (item.get("change_percent") or 0) > 0]
        losers = [item for item in available if (item.get("change_percent") or 0) < 0]
        return {
            "ok": True,
            "index": normalized_index,
            "index_name": index_display_name(normalized_index),
            "constituent_count": len(constituents),
            "available_count": len(available),
            "gainer_count": len(gainers),
            "loser_count": len(losers),
            "unchanged_count": max(0, len(available) - len(gainers) - len(losers)),
            "missing_symbols": resolved["missing_symbols"],
            "quote_status": quote_result["status"],
            "quote_message": quote_result["message"],
            "items": sorted_items,
            "sort": "change_percent_desc",
            "source": f"NSE_{index_display_name(normalized_index).replace(' ', '_')}_LIST_WITH_{quote_result.get('source', 'DHAN')}_QUOTES",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def explain(self, db: Session) -> dict[str, Any]:
        summary = await self.summary(db, settings.sector_breadth_default_index)
        explanation = []
        if summary.get("status") == "NO_DATA":
            explanation.append("Sector breadth has no usable quote data yet. Check Dhan credentials, market data access, and symbol resolution.")
        else:
            explanation.append(
                f"Market breadth is {summary.get('breadth_bias')} with risk-on score {summary.get('risk_on_score')} and risk-off score {summary.get('risk_off_score')}."
            )
            leaders = ", ".join(summary.get("leading_sectors", [])[:3]) or "none"
            laggards = ", ".join(summary.get("lagging_sectors", [])[:3]) or "none"
            explanation.append(f"Leading sectors: {leaders}. Lagging sectors: {laggards}.")
            confirmation = summary.get("nifty_confirmation", {})
            explanation.append(
                f"NIFTY confirmation is {confirmation.get('nifty_confirmation')} because {', '.join(confirmation.get('reasons', [])[:2]) or 'sector data is mixed'}."
            )
        if summary.get("warnings"):
            explanation.extend(summary["warnings"][:3])
        explanation.append("Sector breadth is analysis support only and is not trade approval.")
        return {"ok": True, "index": summary.get("index"), "explanation": explanation, "summary": summary}

    async def _constituent_index_summary(self, db: Session, normalized_index: str, force_refresh: bool) -> dict[str, Any]:
        cached = self._get_cache(normalized_index, force_refresh)
        if cached is not None:
            return cached

        constituents = index_constituents(normalized_index) or ()
        resolved = self._resolve_constituents(db, constituents)
        quote_result = await self._fetch_quotes(resolved, normalized_index)
        quotes_by_symbol = quote_result["quotes_by_symbol"]
        sector_name = "BANKING" if normalized_index == "BANKNIFTY" else index_display_name(normalized_index).replace(" ", "_")
        sector_quotes = [
            quotes_by_symbol[constituent.symbol]
            for constituent in constituents
            if constituent.symbol in quotes_by_symbol
        ]
        missing = [
            constituent.symbol
            for constituent in constituents
            if constituent.symbol not in resolved["resolved_symbols"]
            or quotes_by_symbol.get(constituent.symbol, {}).get("data_status") != "OK"
        ]
        sectors = [calculate_sector_stats(sector_name, sector_quotes, missing)]
        breadth = market_breadth_from_sectors(sectors, 1)
        heavyweights = analyze_heavyweights(quotes_by_symbol)
        confirmation = self._nifty_confirmation(sectors, breadth, heavyweights)
        rotation = self._rotation(sectors)
        now = datetime.now(timezone.utc)
        status = self._summary_status(breadth, quote_result)
        result = {
            "ok": True,
            "index": normalized_index,
            "index_name": index_display_name(normalized_index),
            "status": status,
            "source": quote_result.get("source", "DHAN"),
            "secondary_data_status": self._secondary_data_status(),
            "data_status": breadth.get("data_status"),
            "breadth_bias": breadth.get("breadth_bias"),
            "market_breadth": breadth,
            "risk_on_score": breadth.get("risk_on_score", 0),
            "risk_off_score": breadth.get("risk_off_score", 0),
            "sector_count": len(sectors),
            "resolved_symbol_count": len(resolved["resolved_symbols"]),
            "missing_symbol_count": len(resolved["missing_symbols"]),
            "missing_symbols": resolved["missing_symbols"],
            "quote_status": quote_result["status"],
            "quote_message": quote_result["message"],
            "sectors": sectors,
            "rotation": rotation,
            "leading_sectors": rotation["leading_sectors"],
            "lagging_sectors": rotation["lagging_sectors"],
            "heavyweight_contribution": heavyweights,
            "nifty_confirmation": confirmation,
            "warnings": self._warnings(status, resolved, quote_result, confirmation),
            "generated_at": now.isoformat(),
            "live_order_status": settings.safety_status["live_order_status"],
        }
        self._set_cache(normalized_index, result)
        self._last_updated_at = now
        self._audit(db, self._audit_event(status, confirmation), f"{index_display_name(normalized_index)} breadth summary generated.", "INFO")
        return result

    def _resolve_constituents(self, db: Session, constituents: tuple[Any, ...]) -> dict[str, Any]:
        importer = DhanInstrumentImporter()
        resolved: dict[str, Any] = {}
        missing = []
        for constituent in constituents:
            instrument = None
            resolved_symbol = None
            for candidate in (constituent.symbol, *constituent.aliases):
                instrument = importer.lookup_symbol(db, candidate)
                if instrument is not None:
                    resolved_symbol = candidate
                    break
            if instrument is None:
                missing.append(constituent.symbol)
                continue
            resolved[constituent.symbol] = {
                "symbol": constituent.symbol,
                "resolved_symbol": resolved_symbol,
                "security_id": instrument.security_id,
                "exchange_segment": instrument.segment,
                "trading_symbol": instrument.trading_symbol,
                "display_name": instrument.display_name,
            }
        return {"resolved_symbols": resolved, "missing_symbols": missing}

    def _resolve_symbols(self, db: Session) -> dict[str, Any]:
        importer = DhanInstrumentImporter()
        resolved: dict[str, Any] = {}
        missing = []
        for symbol in all_symbols()[: settings.sector_breadth_max_symbols_per_run]:
            instrument = importer.lookup_symbol(db, symbol)
            if instrument is None:
                missing.append(symbol)
                continue
            resolved[symbol] = {
                "symbol": symbol,
                "security_id": instrument.security_id,
                "exchange_segment": instrument.segment,
                "trading_symbol": instrument.trading_symbol,
                "display_name": instrument.display_name,
            }
        return {"resolved_symbols": resolved, "missing_symbols": missing}

    async def _fetch_quotes(self, resolved: dict[str, Any], index: str = "NIFTY") -> dict[str, Any]:
        if not settings.sector_breadth_use_dhan:
            return await self._fetch_nse_quotes(resolved, fallback_status="DHAN_DISABLED", index=index)
        instruments: dict[str, list[str]] = {}
        security_to_symbol: dict[str, str] = {}
        for symbol, item in resolved["resolved_symbols"].items():
            instruments.setdefault(item["exchange_segment"], []).append(item["security_id"])
            security_to_symbol[str(item["security_id"])] = symbol
        if not instruments:
            return await self._fetch_nse_quotes(resolved, fallback_status="NO_DHAN_SYMBOLS", index=index)

        response = await DhanDataAdapter().get_quote(instruments)
        quotes: dict[str, dict[str, Any]] = {}
        if not response.get("ok"):
            nse_result = await self._fetch_nse_quotes(
                resolved,
                fallback_status=response.get("status", "QUOTE_FAILED"),
                index=index,
            )
            if nse_result["quotes_by_symbol"]:
                return nse_result
            return {
                "status": response.get("status", "QUOTE_FAILED"),
                "message": response.get("message", "Quote request failed."),
                "quotes_by_symbol": self._missing_quote_shells(resolved, response.get("status", "QUOTE_FAILED")),
            }
        for quote in response.get("normalized", []):
            symbol = security_to_symbol.get(str(quote.get("security_id")))
            if not symbol:
                continue
            ltp = _to_float(quote.get("ltp"))
            previous_close = _to_float(quote.get("close"))
            change_percent = None
            if ltp is not None and previous_close and previous_close > 0:
                change_percent = round(((ltp - previous_close) / previous_close) * 100, 4)
            quotes[symbol] = {
                "symbol": symbol,
                "security_id": str(quote.get("security_id")),
                "exchange_segment": quote.get("exchange_segment"),
                "ltp": ltp,
                "previous_close": previous_close,
                "change_percent": change_percent,
                "volume": _to_float(quote.get("volume")),
                "data_status": "OK" if ltp is not None and change_percent is not None else "PARTIAL_DATA",
                "source": "DHAN",
                "last_updated_at": quote.get("timestamp"),
            }
        for symbol, item in resolved["resolved_symbols"].items():
            if symbol not in quotes:
                quotes[symbol] = {
                    "symbol": symbol,
                    "security_id": item["security_id"],
                    "exchange_segment": item["exchange_segment"],
                    "data_status": "NO_QUOTE",
                    "source": "DHAN",
                    "warning": "No quote returned for resolved symbol.",
                }
        return {"status": "OK", "source": "DHAN", "message": "Dhan read-only quote request completed.", "quotes_by_symbol": quotes}

    async def _fetch_nse_quotes(self, resolved: dict[str, Any], fallback_status: str, index: str = "NIFTY") -> dict[str, Any]:
        display_name = index_display_name(index)
        response = await NseDataAdapter().get_index_quotes(display_name)
        if not response.get("ok"):
            return {
                "status": response.get("status", "NSE_QUOTE_FAILED"),
                "message": response.get("message", "NSE quote request failed."),
                "quotes_by_symbol": {},
            }

        requested_symbols = set(resolved["resolved_symbols"]) | set(resolved.get("missing_symbols", []))
        quotes: dict[str, dict[str, Any]] = {}
        for quote in response.get("normalized", []):
            symbol = str(quote.get("symbol") or "").upper()
            if symbol not in requested_symbols:
                continue
            ltp = _to_float(quote.get("ltp"))
            previous_close = _to_float(quote.get("close"))
            change_percent = _to_float(quote.get("change_percent"))
            if change_percent is None and ltp is not None and previous_close and previous_close > 0:
                change_percent = round(((ltp - previous_close) / previous_close) * 100, 4)
            quotes[symbol] = {
                "symbol": symbol,
                "security_id": resolved["resolved_symbols"].get(symbol, {}).get("security_id"),
                "exchange_segment": resolved["resolved_symbols"].get(symbol, {}).get("exchange_segment", "NSE_EQ"),
                "ltp": ltp,
                "previous_close": previous_close,
                "change_percent": change_percent,
                "volume": _to_float(quote.get("volume")),
                "data_status": "OK" if ltp is not None and change_percent is not None else "PARTIAL_DATA",
                "source": "NSE",
                "last_updated_at": quote.get("timestamp"),
            }

        for symbol in requested_symbols:
            item = resolved["resolved_symbols"].get(symbol, {})
            if symbol not in quotes:
                quotes[symbol] = {
                    "symbol": symbol,
                    "security_id": item.get("security_id"),
                    "exchange_segment": item.get("exchange_segment", "NSE_EQ"),
                    "data_status": "NO_NSE_QUOTE",
                    "source": "NSE",
                    "warning": f"Symbol was not present in NSE {display_name} live market response.",
                }

        return {
            "status": "NSE_FALLBACK",
            "source": "NSE",
            "message": f"NSE {display_name} quote fallback used after Dhan status {fallback_status}.",
            "quotes_by_symbol": quotes,
        }

    def _missing_quote_shells(self, resolved: dict[str, Any], status: str) -> dict[str, dict[str, Any]]:
        return {
            symbol: {
                "symbol": symbol,
                "security_id": item["security_id"],
                "exchange_segment": item["exchange_segment"],
                "data_status": status,
                "source": "DHAN",
                "warning": "Quote data unavailable.",
            }
            for symbol, item in resolved["resolved_symbols"].items()
        }

    def _nifty_confirmation(
        self,
        sectors: list[dict[str, Any]],
        breadth: dict[str, Any],
        heavyweights: dict[str, Any],
    ) -> dict[str, Any]:
        by_sector = {item.get("sector"): item for item in sectors}
        banking = by_sector.get("BANKING", {})
        financial = by_sector.get("FINANCIAL_SERVICES", {})
        it = by_sector.get("IT", {})
        reasons = []
        warnings = []
        breadth_bias = breadth.get("breadth_bias", "NO_DATA")
        heavyweight_confirmation = heavyweights.get("heavyweight_confirmation", "NO_DATA")
        if breadth_bias == "NO_DATA":
            label = "NO_DATA"
            reasons.append("No usable sector breadth quote data is available.")
        elif breadth_bias in {"BROAD_BULLISH", "SELECTIVE_BULLISH"} and heavyweight_confirmation in {
            "CONFIRMING_BULLISH",
            "WEAK_BULLISH_CONFIRMATION",
        }:
            label = "CONFIRMED_BULLISH" if breadth_bias == "BROAD_BULLISH" else "WEAK_CONFIRMATION"
            reasons.append("Breadth and heavyweight context lean bullish.")
        elif breadth_bias in {"BROAD_BEARISH", "SELECTIVE_BEARISH"} and heavyweight_confirmation in {
            "CONFIRMING_BEARISH",
            "WEAK_BEARISH_CONFIRMATION",
        }:
            label = "CONFIRMED_BEARISH" if breadth_bias == "BROAD_BEARISH" else "WEAK_CONFIRMATION"
            reasons.append("Breadth and heavyweight context lean bearish.")
        elif breadth_bias in {"BROAD_BULLISH", "BROAD_BEARISH"} and heavyweight_confirmation == "MIXED":
            label = "DIVERGENCE"
            reasons.append("Broad sector breadth and heavyweight leadership are not aligned.")
        else:
            label = "MIXED"
            reasons.append("Sector breadth is mixed or selective.")
        if heavyweights.get("narrow_leadership_warning"):
            warnings.append("Heavyweight leadership is narrow; NIFTY move may be concentrated in only a few stocks.")
        return {
            "nifty_confirmation": label,
            "breadth_bias": breadth_bias,
            "banking_confirmation": banking.get("sector_bias", "NO_DATA"),
            "financial_confirmation": financial.get("sector_bias", "NO_DATA"),
            "it_confirmation": it.get("sector_bias", "NO_DATA"),
            "heavyweight_confirmation": heavyweight_confirmation,
            "divergence": label == "DIVERGENCE",
            "warnings": warnings,
            "reasons": reasons,
        }

    def _rotation(self, sectors: list[dict[str, Any]]) -> dict[str, Any]:
        leading = [item["sector"] for item in sectors if item.get("rotation_label") == "LEADERS"]
        lagging = [item["sector"] for item in sectors if item.get("rotation_label") == "LAGGARDS"]
        improving = [item["sector"] for item in sectors if item.get("rotation_label") == "IMPROVING"]
        weakening = [item["sector"] for item in sectors if item.get("rotation_label") == "WEAKENING"]
        if leading and len(leading) > len(lagging):
            bias = "RISK_ON_ROTATION"
        elif lagging and len(lagging) > len(leading):
            bias = "RISK_OFF_ROTATION"
        elif improving or weakening:
            bias = "MIXED_ROTATION"
        else:
            bias = "NO_DATA"
        return {
            "leading_sectors": leading,
            "lagging_sectors": lagging,
            "improving_sectors": improving,
            "weakening_sectors": weakening,
            "rotation_bias": bias,
        }

    def _summary_status(self, breadth: dict[str, Any], quote_result: dict[str, Any]) -> str:
        if quote_result.get("status") not in {"OK"}:
            return "PARTIAL_DATA" if settings.sector_breadth_allow_partial_data else "NO_DATA"
        return breadth.get("data_status", "UNKNOWN")

    def _secondary_data_status(self) -> str:
        if not settings.sector_breadth_use_indstocks_cross_check:
            return "DISABLED"
        if not settings.indstocks_enabled:
            return "DISABLED"
        if not settings.has_indstocks_credentials:
            return "TOKEN_MISSING"
        return "CONFIGURED_READ_ONLY"

    def _warnings(self, status: str, resolved: dict[str, Any], quote_result: dict[str, Any], confirmation: dict[str, Any]) -> list[str]:
        warnings = []
        if status != "OK":
            warnings.append(f"Sector breadth is {status}; quote status is {quote_result.get('status')}.")
        if resolved["missing_symbols"]:
            warnings.append(f"{len(resolved['missing_symbols'])} configured symbols were not found in the Dhan instrument master.")
        warnings.extend(confirmation.get("warnings", []))
        if settings.sector_breadth_use_indstocks_cross_check and not settings.sector_breadth_require_indstocks:
            warnings.append("INDstocks is optional for Phase 1.18 and is not required for sector breadth calculation.")
        return warnings

    def _audit_event(self, status: str, confirmation: dict[str, Any]) -> str:
        if confirmation.get("divergence"):
            return "SECTOR_BREADTH_DIVERGENCE_DETECTED"
        if status == "NO_DATA":
            return "SECTOR_BREADTH_NO_DATA"
        if status == "PARTIAL_DATA":
            return "SECTOR_BREADTH_PARTIAL_DATA"
        return "SECTOR_BREADTH_REFRESHED"

    def _get_cache(self, key: str, force_refresh: bool) -> dict[str, Any] | None:
        if force_refresh:
            return None
        cached = self._cache.get(key)
        cached_at = self._cache_at.get(key)
        if cached and cached_at and monotonic() - cached_at <= settings.sector_breadth_cache_seconds:
            return {**cached, "cache_hit": True}
        return None

    def _set_cache(self, key: str, value: dict[str, Any]) -> None:
        self._cache[key] = {**value, "cache_hit": False}
        self._cache_at[key] = monotonic()

    def _audit(self, db: Session, event_type: str, message: str, severity: str) -> None:
        if not settings.sector_breadth_enable_audit:
            return
        now = monotonic()
        last = self._last_audit_at.get(event_type, 0.0)
        if now - last < settings.sector_breadth_audit_throttle_seconds:
            return
        self._last_audit_at[event_type] = now
        AuditLogger().log(db, event_type, message, severity=severity, source="SECTOR_BREADTH")


def _normalize_index(index: str) -> str:
    return normalize_index_key(index)


def _error(status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "status": status, "message": message, "live_order_status": settings.safety_status["live_order_status"], **extra}


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


sector_breadth_service = SectorBreadthService()


def get_sector_breadth_service() -> SectorBreadthService:
    return sector_breadth_service
