from dataclasses import dataclass


@dataclass(frozen=True)
class DataValidationResult:
    data_confidence: float
    status: str
    reason: str
    block_signal: bool = False


class DataValidator:
    def confidence_for_source(self, source: str) -> DataValidationResult:
        normalized_source = source.strip().upper()
        if normalized_source == "DHAN":
            return DataValidationResult(85, "DHAN_ONLY", "Using Dhan market data.")
        if normalized_source == "MOCK":
            return DataValidationResult(50, "MOCK_DATA", "Using mock market data.")
        if normalized_source == "MANUAL":
            return DataValidationResult(60, "MANUAL_DATA", "Using manually supplied market data.")
        if normalized_source == "INDSTOCKS":
            return DataValidationResult(65, "INDSTOCKS_ONLY", "Using INDstocks market data.")
        if normalized_source == "HYBRID":
            return DataValidationResult(
                0,
                "HYBRID_PENDING",
                "Hybrid confidence is pending until both feeds are matched.",
                block_signal=True,
            )
        return DataValidationResult(
            0,
            "UNKNOWN_SOURCE",
            f"Unknown market data source: {source}.",
            block_signal=True,
        )

    def validate_ltp(
        self,
        dhan_ltp: float | None,
        indstocks_ltp: float | None,
        dhan_connected: bool,
        indstocks_connected: bool,
    ) -> DataValidationResult:
        if dhan_ltp is not None and dhan_ltp <= 0:
            dhan_ltp = None
        if indstocks_ltp is not None and indstocks_ltp <= 0:
            indstocks_ltp = None
        dhan_has_ltp = dhan_connected and dhan_ltp is not None
        indstocks_has_ltp = indstocks_connected and indstocks_ltp is not None
        if dhan_has_ltp and indstocks_has_ltp:
            difference_pct = abs(dhan_ltp - indstocks_ltp) / max(dhan_ltp, indstocks_ltp) * 100
            if difference_pct == 0:
                return DataValidationResult(100, "MATCH", "Dhan and Indstocks LTP match.")
            if difference_pct <= 0.10:
                return DataValidationResult(85, "SMALL_DIFFERENCE", "Small LTP difference detected.")
            if difference_pct <= 0.50:
                return DataValidationResult(60, "MEDIUM_DIFFERENCE", "Medium LTP difference detected.")
            return DataValidationResult(
                0,
                "DATA_MISMATCH",
                "Large LTP mismatch detected. Signal is blocked.",
                block_signal=True,
            )

        if dhan_has_ltp:
            return DataValidationResult(85, "DHAN_ONLY", "Only Dhan market data is connected.")

        if indstocks_has_ltp:
            return DataValidationResult(65, "INDSTOCKS_ONLY", "Only Indstocks market data is connected.")

        return DataValidationResult(
            0,
            "NO_DATA",
            "Both Dhan and Indstocks market data are disconnected. No signal generated.",
            block_signal=True,
        )
