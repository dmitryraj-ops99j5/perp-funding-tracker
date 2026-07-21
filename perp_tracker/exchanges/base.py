from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class FundingRecord:
    """Normalized funding snapshot for a single perpetual contract."""
    exchange: str
    symbol: str
    mark_price: float
    index_price: float
    funding_rate: float
    next_funding_time: Optional[datetime]
    funding_interval_hours: int = 8

    @property
    def annualized_rate(self) -> float:
        if self.funding_interval_hours <= 0:
            return 0.0
        periods_per_year = (24 / self.funding_interval_hours) * 365
        return self.funding_rate * periods_per_year

class ExchangeAdapter(ABC):
    name: str

    @abstractmethod
    async def fetch_funding_rates(self) -> list[FundingRecord]:
        ...

    @abstractmethod
    async def close(self):
        ...
