import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.dhan_data import DhanDataAdapter
from app.config import settings
from app.engine.data_validator import DataValidator
from app.engine.dhan_instrument_importer import DhanInstrumentImporter
from app.engine.option_chain_analyzer import OptionChainAnalyzer
from app.engine.option_chain_normalizer import OptionChainNormalizer
from app.engine.paper_engine import PaperEngine, PaperTradeBlockedError
from app.engine.risk_manager import RiskManager
from app.models.signal import (
    SignalAnalysisRequest,
    SignalAnalysisResponse,
    SignalRecord,
    SignalStatus,
    SignalType,
)
from app.models.trade import Direction, InstrumentType, OptionType, PaperTradeCreate, PaperTradeRead


class SignalEngineV1:
    def __init__(self) -> None:
        self.data_validator = DataValidator()
        self.instrument_importer = DhanInstrumentImporter()
        self.dhan = DhanDataAdapter()
        self.normalizer = OptionChainNormalizer()
        self.analyzer = OptionChainAnalyzer()
        self.risk_manager = RiskManager()

    async def analyze(self, db: Session, payload: SignalAnalysisRequest) -> SignalAnalysisResponse:
        response = await self._analyze_without_persist(db, payload)
        record = self._store_signal(db, response)
        response.signal_id = record.id
        return response

    async def analyze_and_paper(self, db: Session, payload: SignalAnalysisRequest) -> tuple[SignalAnalysisResponse, Any | None, str]:
        response = await self._analyze_without_persist(db, payload)
        record = self._store_signal(db, response)
        response.signal_id = record.id

        if response.status != SignalStatus.SIGNAL.value:
            return response, None, "Signal is not actionable; no paper trade created."

        if response.entry is None or response.option_type is None or response.selected_strike is None:
            response.status = SignalStatus.NO_TRADE.value
            response.signal_type = SignalType.NO_TRADE.value
            response.warnings.append("Signal is missing option trade fields; no paper trade created.")
            self._update_signal_record(db, record, response)
            return response, None, "Signal missing required trade fields; no paper trade created."

        trade_payload = PaperTradeCreate(
            symbol=response.underlying,
            instrument_type=InstrumentType.INDEX_OPTION,
            exchange="NSE",
            expiry=response.expiry,
            strike=response.selected_strike,
            option_type=OptionType(response.option_type),
            direction=Direction.BUY,
            entry_price=response.entry,
            stop_loss=response.stop_loss,
            target_1=response.target_1,
            target_2=response.target_2,
            quantity=response.quantity,
            signal_confidence=response.final_confidence,
            signal_id=record.id,
            underlying=response.underlying,
            selected_strike=response.selected_strike,
            strategy_score=response.strategy_score,
            data_confidence=response.data_confidence,
            final_confidence=response.final_confidence,
            chain_bias=response.chain_bias,
            signal_type=response.signal_type,
            signal_reason=" | ".join(response.reason),
            data_source="DHAN",
        )

        try:
            trade = PaperEngine().create_trade(db, trade_payload)
        except PaperTradeBlockedError as exc:
            response.status = SignalStatus.NO_TRADE.value
            response.signal_type = SignalType.NO_TRADE.value
            response.warnings.extend(exc.reasons)
            self._update_signal_record(db, record, response)
            return response, None, "Paper trade blocked by risk manager."

        response.paper_trade_id = trade.id
        record.paper_trade_id = trade.id
        db.commit()
        db.refresh(record)
        return response, PaperTradeRead.model_validate(trade).model_dump(mode="json"), "Paper trade created."

    def latest(self, db: Session, limit: int = 20) -> list[SignalRecord]:
        return list(
            db.scalars(
                select(SignalRecord).order_by(SignalRecord.created_at.desc()).limit(limit)
            )
        )

    async def _analyze_without_persist(
        self, db: Session, payload: SignalAnalysisRequest
    ) -> SignalAnalysisResponse:
        reasons: list[str] = []
        warnings: list[str] = []

        if payload.mode != "PAPER" or not settings.is_paper_mode:
            return self._no_trade(payload, reasons, ["Only PAPER mode is allowed."])

        if payload.expiry is None:
            return self._no_trade(
                payload,
                reasons,
                ["Expiry is required. First call /api/market/option-expiries/{underlying} and use one exact expiry from the response."],
            )

        if payload.capital < payload.max_risk_per_trade:
            warnings.append("Capital is lower than max_risk_per_trade.")
            return self._no_trade(payload, reasons, warnings)

        underlying_instrument = self.instrument_importer.lookup_option_underlying(db, payload.underlying)
        if underlying_instrument is None:
            return self._no_trade(payload, reasons, ["Underlying not found in Dhan instrument master."])

        chain_response = await self.dhan.get_option_chain(
            under_security_id=underlying_instrument.security_id,
            under_exchange_segment=underlying_instrument.segment,
            expiry=payload.expiry,
        )
        if not chain_response.get("ok"):
            return self._no_trade(
                payload,
                reasons,
                [chain_response.get("message", "Dhan API failed while fetching option chain.")],
                status=chain_response.get("status"),
            )

        extraction = self.normalizer.extract_chain(chain_response.get("data"))
        spot_price = extraction.spot_price
        if spot_price is None:
            spot_price = await self._spot_price(db, payload.underlying)

        strikes = self.normalizer.normalize(
            chain_response.get("data"),
            underlying=payload.underlying,
            expiry=payload.expiry,
            spot_price=spot_price,
        )
        if not strikes:
            return self._no_trade(payload, reasons, ["No option chain data found for this underlying and expiry."])

        summary = self.analyzer.analyze(
            strikes,
            underlying=payload.underlying,
            expiry=payload.expiry.isoformat(),
            spot_price=spot_price,
        )
        chain_bias = summary.get("chain_bias")
        atm_strike = summary.get("atm_strike")
        signal_type = self._preferred_signal_type(chain_bias)

        if signal_type == SignalType.NO_TRADE:
            reasons.append(f"Option-chain bias is {chain_bias}; no directional edge.")
            return self._decision_response(
                payload=payload,
                signal_type=SignalType.NO_TRADE.value,
                status=SignalStatus.NO_TRADE.value,
                spot_price=spot_price,
                atm_strike=atm_strike,
                selected=None,
                strategy_score=0,
                data_confidence=self.data_validator.confidence_for_source("DHAN").data_confidence,
                risk_reward=None,
                chain_bias=chain_bias,
                reasons=reasons,
                warnings=warnings,
            )

        selected = self._select_option(strikes, signal_type, atm_strike)
        if selected is None:
            warnings.append("No ATM/near-ATM option met liquidity and price requirements.")
            return self._decision_response(
                payload=payload,
                signal_type=SignalType.NO_TRADE.value,
                status=SignalStatus.NO_TRADE.value,
                spot_price=spot_price,
                atm_strike=atm_strike,
                selected=None,
                strategy_score=0,
                data_confidence=self.data_validator.confidence_for_source("DHAN").data_confidence,
                risk_reward=None,
                chain_bias=chain_bias,
                reasons=reasons,
                warnings=warnings,
            )

        trade_levels = self._trade_levels(selected["ltp"])
        risk_reward = trade_levels["risk_reward"]
        score, score_reasons, score_warnings = self._score(
            signal_type=signal_type,
            chain_bias=chain_bias,
            summary=summary,
            selected=selected,
            risk_reward=risk_reward,
        )
        reasons.extend(score_reasons)
        warnings.extend(score_warnings)

        data_confidence = self.data_validator.confidence_for_source("DHAN").data_confidence
        final_confidence = round(score * data_confidence / 100, 2)
        status = self._status_from_confidence(final_confidence)

        if chain_bias == "CHOPPY":
            status = SignalStatus.NO_TRADE.value
            warnings.append("Chain bias is CHOPPY.")
        if selected["liquidity_score"] < 60:
            status = SignalStatus.NO_TRADE.value
            warnings.append("Selected option liquidity score is below 60.")
        if selected["spread"] is None or selected["spread_pct"] > 12:
            status = SignalStatus.NO_TRADE.value
            warnings.append("Selected option spread is too wide or unavailable.")
        if risk_reward is None or risk_reward < 1.5:
            status = SignalStatus.NO_TRADE.value
            warnings.append("Risk/reward is below 1.5.")

        pseudo_trade = self._pseudo_trade(payload, selected, trade_levels, final_confidence, reasons)
        allowed, risk_reasons = self.risk_manager.can_place_paper_trade(db, pseudo_trade)
        if not allowed:
            status = SignalStatus.NO_TRADE.value
            warnings.extend(risk_reasons)

        final_signal_type = signal_type.value if status == SignalStatus.SIGNAL.value else (
            signal_type.value if status == SignalStatus.WATCHLIST.value else SignalType.NO_TRADE.value
        )

        return SignalAnalysisResponse(
            ok=True,
            signal_type=final_signal_type,
            status=status,
            underlying=payload.underlying,
            expiry=payload.expiry.isoformat(),
            spot_price=spot_price,
            atm_strike=atm_strike,
            selected_strike=selected["strike"],
            option_type=selected["option_type"],
            entry=trade_levels["entry"],
            stop_loss=trade_levels["stop_loss"],
            target_1=trade_levels["target_1"],
            target_2=trade_levels["target_2"],
            quantity=payload.lot_size,
            strategy_score=score,
            data_confidence=data_confidence,
            final_confidence=final_confidence,
            risk_reward=risk_reward,
            chain_bias=chain_bias,
            reason=reasons,
            warnings=warnings,
        )

    def _preferred_signal_type(self, chain_bias: str | None) -> SignalType:
        if chain_bias == "BULLISH":
            return SignalType.BUY_CE
        if chain_bias == "BEARISH":
            return SignalType.BUY_PE
        return SignalType.NO_TRADE

    def _select_option(
        self, strikes: list[dict[str, Any]], signal_type: SignalType, atm_strike: float | None
    ) -> dict[str, Any] | None:
        option_type = "CE" if signal_type == SignalType.BUY_CE else "PE"
        prefix = option_type.lower()
        candidates = []
        for row in strikes:
            ltp = row.get(f"{prefix}_ltp")
            liquidity = row.get(f"{prefix}_liquidity_score") or 0
            spread = row.get(f"{prefix}_spread")
            bid = row.get(f"{prefix}_bid")
            ask = row.get(f"{prefix}_ask")
            if ltp is None or ltp <= 0:
                continue
            mid = ((bid or 0) + (ask or 0)) / 2 if bid and ask else None
            spread_pct = (spread / mid * 100) if spread is not None and mid and mid > 0 else 999
            if liquidity < 60 or spread_pct > 12:
                continue
            candidates.append(
                {
                    "strike": row["strike"],
                    "option_type": option_type,
                    "ltp": float(ltp),
                    "liquidity_score": liquidity,
                    "spread": spread,
                    "spread_pct": spread_pct,
                    "volume": row.get(f"{prefix}_volume") or 0,
                    "oi": row.get(f"{prefix}_oi") or 0,
                    "activity": row.get(f"{prefix}_activity"),
                    "distance": abs((row["strike"] or 0) - (atm_strike or row["strike"] or 0)),
                    "otm_preference": self._otm_preference(row["strike"], atm_strike, option_type),
                }
            )
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                item["distance"],
                -item["otm_preference"],
                -item["liquidity_score"],
                item["spread_pct"],
            ),
        )[0]

    def _otm_preference(self, strike: float, atm_strike: float | None, option_type: str) -> int:
        if atm_strike is None:
            return 0
        if option_type == "CE" and strike >= atm_strike:
            return 1
        if option_type == "PE" and strike <= atm_strike:
            return 1
        return 0

    def _trade_levels(self, entry: float) -> dict[str, float]:
        risk = max(entry * 0.20, 1.0)
        return {
            "entry": round(entry, 2),
            "stop_loss": round(max(entry - risk, 0.05), 2),
            "target_1": round(entry + risk * 1.5, 2),
            "target_2": round(entry + risk * 2.0, 2),
            "risk_reward": 1.5,
        }

    def _score(
        self,
        signal_type: SignalType,
        chain_bias: str | None,
        summary: dict[str, Any],
        selected: dict[str, Any],
        risk_reward: float | None,
    ) -> tuple[float, list[str], list[str]]:
        score = 0
        reasons: list[str] = []
        warnings: list[str] = []
        pcr_oi = summary.get("pcr_oi")
        pcr_volume = summary.get("pcr_volume")

        expected_bias = "BULLISH" if signal_type == SignalType.BUY_CE else "BEARISH"
        if chain_bias == expected_bias:
            score += 20
            reasons.append(f"Option-chain bias is {chain_bias.lower()}.")

        if (signal_type == SignalType.BUY_CE and pcr_oi and pcr_oi >= 1.1) or (
            signal_type == SignalType.BUY_PE and pcr_oi and pcr_oi <= 0.9
        ):
            score += 15
            reasons.append("PCR supports the directional view.")
        else:
            warnings.append("PCR confirmation is weak.")

        if self._near_key_zone(signal_type, summary):
            score += 15
            reasons.append("Spot is near a support/resistance decision zone.")
        else:
            warnings.append("Spot is not near a clear support/resistance zone.")

        if selected["liquidity_score"] >= 75:
            score += 20
        elif selected["liquidity_score"] >= 60:
            score += 15
        reasons.append("Selected option has acceptable liquidity.")

        if selected["spread_pct"] <= 6:
            score += 10
            reasons.append("Bid/ask spread is acceptable.")
        elif selected["spread_pct"] <= 12:
            score += 5
            warnings.append("Bid/ask spread is acceptable but not tight.")
        else:
            warnings.append("Bid/ask spread is too wide.")

        if selected["activity"] in {"HIGH_OI", "HIGH_VOLUME", "LIQUID"} or selected["volume"] > 0 or selected["oi"] > 0:
            score += 10
            reasons.append("Volume/OI activity is present.")
        else:
            warnings.append("Volume/OI activity is weak.")

        if risk_reward is not None and risk_reward >= 1.5:
            score += 10
            reasons.append("Risk/reward is acceptable.")
        else:
            warnings.append("Risk/reward is below threshold.")

        if pcr_volume is not None and (signal_type == SignalType.BUY_CE and pcr_volume >= 1.0):
            score += 0
        elif pcr_volume is not None and (signal_type == SignalType.BUY_PE and pcr_volume <= 1.0):
            score += 0

        return float(min(score, 100)), reasons, warnings

    def _near_key_zone(self, signal_type: SignalType, summary: dict[str, Any]) -> bool:
        spot = summary.get("spot_price")
        support = summary.get("support_strike")
        resistance = summary.get("resistance_strike")
        atm = summary.get("atm_strike")
        if spot is None or atm is None:
            return False
        zone = max(abs(atm) * 0.006, 50)
        if signal_type == SignalType.BUY_CE and support is not None:
            return abs(spot - support) <= zone or spot > atm
        if signal_type == SignalType.BUY_PE and resistance is not None:
            return abs(spot - resistance) <= zone or spot < atm
        return False

    def _status_from_confidence(self, final_confidence: float) -> str:
        if final_confidence >= 75:
            return SignalStatus.SIGNAL.value
        if final_confidence >= 60:
            return SignalStatus.WATCHLIST.value
        return SignalStatus.NO_TRADE.value

    async def _spot_price(self, db: Session, underlying: str) -> float | None:
        instrument = self.instrument_importer.lookup_symbol(db, underlying)
        if instrument is None:
            return None
        response = await self.dhan.get_ltp({instrument.segment: [instrument.security_id]})
        normalized = response.get("normalized")
        if isinstance(normalized, list) and normalized:
            try:
                ltp = float(normalized[0].get("ltp"))
            except (TypeError, ValueError):
                return None
            return ltp if ltp > 0 else None
        return None

    def _pseudo_trade(
        self,
        payload: SignalAnalysisRequest,
        selected: dict[str, Any],
        trade_levels: dict[str, float],
        final_confidence: float,
        reasons: list[str],
    ) -> PaperTradeCreate:
        return PaperTradeCreate(
            symbol=payload.underlying,
            instrument_type=InstrumentType.INDEX_OPTION,
            exchange="NSE",
            expiry=payload.expiry.isoformat() if payload.expiry else None,
            strike=selected["strike"],
            option_type=OptionType(selected["option_type"]),
            direction=Direction.BUY,
            entry_price=trade_levels["entry"],
            stop_loss=trade_levels["stop_loss"],
            target_1=trade_levels["target_1"],
            target_2=trade_levels["target_2"],
            quantity=payload.lot_size,
            signal_confidence=final_confidence,
            signal_reason=" | ".join(reasons),
            data_source="DHAN",
        )

    def _decision_response(
        self,
        payload: SignalAnalysisRequest,
        signal_type: str,
        status: str,
        spot_price: float | None,
        atm_strike: float | None,
        selected: dict[str, Any] | None,
        strategy_score: float,
        data_confidence: float,
        risk_reward: float | None,
        chain_bias: str | None,
        reasons: list[str],
        warnings: list[str],
    ) -> SignalAnalysisResponse:
        final_confidence = round(strategy_score * data_confidence / 100, 2)
        return SignalAnalysisResponse(
            ok=True,
            signal_type=signal_type,
            status=status,
            underlying=payload.underlying,
            expiry=payload.expiry.isoformat() if payload.expiry else None,
            spot_price=spot_price,
            atm_strike=atm_strike,
            selected_strike=selected.get("strike") if selected else None,
            option_type=selected.get("option_type") if selected else None,
            entry=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            quantity=payload.lot_size,
            strategy_score=strategy_score,
            data_confidence=data_confidence,
            final_confidence=final_confidence,
            risk_reward=risk_reward,
            chain_bias=chain_bias,
            reason=reasons,
            warnings=warnings,
        )

    def _no_trade(
        self,
        payload: SignalAnalysisRequest,
        reasons: list[str],
        warnings: list[str],
        status: str | None = None,
    ) -> SignalAnalysisResponse:
        if status:
            warnings.append(status)
        return SignalAnalysisResponse(
            ok=True,
            signal_type=SignalType.NO_TRADE.value,
            status=SignalStatus.NO_TRADE.value,
            underlying=payload.underlying,
            expiry=payload.expiry.isoformat() if payload.expiry else None,
            spot_price=None,
            atm_strike=None,
            selected_strike=None,
            option_type=None,
            entry=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            quantity=payload.lot_size,
            strategy_score=0,
            data_confidence=self.data_validator.confidence_for_source("DHAN").data_confidence,
            final_confidence=0,
            risk_reward=None,
            chain_bias=None,
            reason=reasons,
            warnings=warnings,
        )

    def _store_signal(self, db: Session, response: SignalAnalysisResponse) -> SignalRecord:
        record = SignalRecord(
            underlying=response.underlying,
            expiry=date.fromisoformat(response.expiry) if response.expiry else None,
            signal_type=response.signal_type,
            status=response.status,
            spot_price=response.spot_price,
            atm_strike=response.atm_strike,
            selected_strike=response.selected_strike,
            option_type=response.option_type,
            entry=response.entry,
            stop_loss=response.stop_loss,
            target_1=response.target_1,
            target_2=response.target_2,
            quantity=response.quantity,
            strategy_score=response.strategy_score,
            data_confidence=response.data_confidence,
            final_confidence=response.final_confidence,
            risk_reward=response.risk_reward,
            chain_bias=response.chain_bias,
            reason_json=json.dumps(response.reason),
            warnings_json=json.dumps(response.warnings),
            paper_trade_id=response.paper_trade_id,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def _update_signal_record(self, db: Session, record: SignalRecord, response: SignalAnalysisResponse) -> None:
        record.signal_type = response.signal_type
        record.status = response.status
        record.reason_json = json.dumps(response.reason)
        record.warnings_json = json.dumps(response.warnings)
        record.paper_trade_id = response.paper_trade_id
        db.commit()
        db.refresh(record)
