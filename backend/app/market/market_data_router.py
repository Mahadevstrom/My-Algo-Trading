from typing import Any

from app.brokers.dhan_data import DhanDataAdapter
from app.config import settings


class MarketDataRouter:
    def status(self) -> dict[str, Any]:
        mode = settings.market_data_mode.upper()

        if mode == "DHAN":
            return {
                "market_data_mode": mode,
                "provider": DhanDataAdapter().status(),
            }

        if mode == "MOCK":
            return {
                "market_data_mode": mode,
                "provider": {
                    "enabled": True,
                    "connected": True,
                    "mode": "MOCK",
                    "message": "Mock market-data mode is active.",
                },
            }

        if mode == "INDSTOCKS":
            return {
                "market_data_mode": mode,
                "provider": {
                    "enabled": settings.indstocks_enabled,
                    "connected": False,
                    "mode": "INDSTOCKS",
                    "message": "INDstocks market-data routing is not configured for primary mode yet.",
                },
            }

        if mode == "HYBRID":
            return {
                "market_data_mode": mode,
                "provider": {
                    "enabled": False,
                    "connected": False,
                    "mode": "HYBRID",
                    "message": "Hybrid market-data mode is pending.",
                },
            }

        return {
            "market_data_mode": mode,
            "provider": {
                "enabled": False,
                "connected": False,
                "mode": mode,
                "message": "Unsupported MARKET_DATA_MODE. Use DHAN, MOCK, INDSTOCKS, or HYBRID.",
            },
        }

