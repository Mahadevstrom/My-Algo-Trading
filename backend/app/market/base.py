from abc import ABC, abstractmethod
from typing import Any


class MarketDataProvider(ABC):
    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

