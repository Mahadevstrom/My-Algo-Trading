from hashlib import sha256

from app.config import settings
from app.engine.data_validator import DataValidator
from app.models.signal import SignalGenerateRequest, SignalResponse, SignalType


class SignalEngine:
    def __init__(self) -> None:
        self.data_validator = DataValidator()

    def generate(self, request: SignalGenerateRequest) -> SignalResponse:
        mock_ltp = self._mock_ltp(request.symbol)
        trend_score = self._mock_strategy_score(request.symbol)

        if request.data_source.upper() == "MOCK":
            data_result = self.data_validator.confidence_for_source("MOCK")
        else:
            data_result = self.data_validator.validate_ltp(
                dhan_ltp=mock_ltp,
                indstocks_ltp=None,
                dhan_connected=settings.dhan_data_enabled,
                indstocks_connected=settings.indstocks_enabled,
            )

        if data_result.block_signal:
            return SignalResponse(
                symbol=request.symbol,
                signal_type=SignalType.NO_TRADE,
                confidence=0,
                entry=None,
                stop_loss=None,
                target_1=None,
                target_2=None,
                reason=data_result.reason,
                strategy_score=trend_score,
                data_confidence=data_result.data_confidence,
                final_confidence=0,
            )

        final_confidence = round(trend_score * data_result.data_confidence / 100, 2)
        signal_type = self._signal_type_from_score(trend_score, final_confidence)

        if signal_type == SignalType.NO_TRADE:
            return SignalResponse(
                symbol=request.symbol,
                signal_type=signal_type,
                confidence=final_confidence,
                entry=None,
                stop_loss=None,
                target_1=None,
                target_2=None,
                reason=f"Mock strategy score is neutral. {data_result.reason}",
                strategy_score=trend_score,
                data_confidence=data_result.data_confidence,
                final_confidence=final_confidence,
            )

        entry = round(mock_ltp, 2)
        return SignalResponse(
            symbol=request.symbol,
            signal_type=signal_type,
            confidence=final_confidence,
            entry=entry,
            stop_loss=round(entry * 0.90, 2),
            target_1=round(entry * 1.15, 2),
            target_2=round(entry * 1.30, 2),
            reason=f"Mock {signal_type.value} setup generated. {data_result.reason}",
            strategy_score=trend_score,
            data_confidence=data_result.data_confidence,
            final_confidence=final_confidence,
        )

    def _mock_ltp(self, symbol: str) -> float:
        digest = sha256(symbol.encode("utf-8")).hexdigest()
        return 100 + (int(digest[:4], 16) % 900)

    def _mock_strategy_score(self, symbol: str) -> float:
        digest = sha256(f"{symbol}:strategy".encode("utf-8")).hexdigest()
        return float(45 + (int(digest[:2], 16) % 51))

    def _signal_type_from_score(self, strategy_score: float, final_confidence: float) -> SignalType:
        if final_confidence < 55:
            return SignalType.NO_TRADE
        return SignalType.BUY_CE if int(strategy_score) % 2 == 0 else SignalType.BUY_PE
