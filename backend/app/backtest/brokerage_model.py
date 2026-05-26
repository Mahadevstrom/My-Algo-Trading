from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerageConfig:
    brokerage_per_order: float = 20.0
    stt_rate_on_sell: float = 0.000625
    exchange_txn_rate: float = 0.0005
    sebi_rate: float = 0.000001
    gst_rate: float = 0.18
    stamp_duty_rate_on_buy: float = 0.00003


class BrokerageModel:
    """Approximate paper/backtest charges. This is not exact broker billing."""

    def __init__(self, config: BrokerageConfig | None = None) -> None:
        self.config = config or BrokerageConfig()

    def charges(self, entry_price: float, exit_price: float, quantity: int) -> dict[str, float]:
        buy_turnover = entry_price * quantity
        sell_turnover = exit_price * quantity
        total_turnover = buy_turnover + sell_turnover
        brokerage = self.config.brokerage_per_order * 2
        stt = sell_turnover * self.config.stt_rate_on_sell
        exchange = total_turnover * self.config.exchange_txn_rate
        sebi = total_turnover * self.config.sebi_rate
        gst = (brokerage + exchange) * self.config.gst_rate
        stamp = buy_turnover * self.config.stamp_duty_rate_on_buy
        total = brokerage + stt + exchange + sebi + gst + stamp
        return {
            "entry_charges": round(self.config.brokerage_per_order + stamp + (exchange / 2), 2),
            "exit_charges": round(self.config.brokerage_per_order + stt + (exchange / 2), 2),
            "total_charges": round(total, 2),
            "brokerage": round(brokerage, 2),
            "stt_ctt": round(stt, 2),
            "exchange_transaction": round(exchange, 2),
            "sebi": round(sebi, 4),
            "gst": round(gst, 2),
            "stamp_duty": round(stamp, 2),
            "note": "Estimated charges for paper/backtest only; not exact broker billing.",
        }
