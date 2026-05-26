from abc import ABC, abstractmethod
from typing import Any


class BrokerClient(ABC):
    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError


class ReadOnlyBrokerClient(BrokerClient):
    @abstractmethod
    async def funds(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def positions(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def orderbook(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def tradebook(self) -> dict[str, Any]:
        raise NotImplementedError

