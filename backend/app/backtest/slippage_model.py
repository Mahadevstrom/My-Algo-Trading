from dataclasses import dataclass


@dataclass(frozen=True)
class SlippageConfig:
    fixed_slippage_points: float | None = None
    percentage_slippage: float = 0.0025
    min_option_slippage_points: float = 0.5


class SlippageModel:
    def __init__(self, config: SlippageConfig | None = None) -> None:
        self.config = config or SlippageConfig()

    def option_slippage(self, premium: float, bid: float | None = None, ask: float | None = None) -> float:
        if self.config.fixed_slippage_points is not None:
            return round(max(self.config.fixed_slippage_points, 0.0), 2)
        spread_slippage = 0.0
        if bid is not None and ask is not None and ask > bid:
            spread_slippage = (ask - bid) / 2
        percent_slippage = premium * self.config.percentage_slippage
        return round(max(self.config.min_option_slippage_points, percent_slippage, spread_slippage), 2)
