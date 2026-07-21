from datetime import datetime, timezone
import httpx
from perp_tracker.config import DEFAULT_HTTP_TIMEOUT, USER_AGENT
from perp_tracker.exchanges.base import ExchangeAdapter, FundingRecord

BINANCE_FAPI_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

class BinanceAdapter(ExchangeAdapter):
    name = "binance"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            timeout=DEFAULT_HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None

    async def fetch_funding_rates(self) -> list[FundingRecord]:
        resp = await self._client.get(BINANCE_FAPI_URL)
        resp.raise_for_status()
        data = resp.json()
        # print(f"binance raw count: {len(data)}")

        records: list[FundingRecord] = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym or not sym.endswith("USDT"):
                continue

            # skip delivery futures like BTCUSDT_240628
            if "_" in sym:
                continue

            try:
                mark = float(item.get("markPrice") or 0)
                index = float(item.get("indexPrice") or mark)
                rate_str = item.get("lastFundingRate")
                if rate_str is None or rate_str == "":
                    continue
                rate = float(rate_str)
            except (ValueError, TypeError):
                continue

            nxt_raw = item.get("nextFundingTime")
            nxt = None
            # FIXME: binance occasionally returns 0 for nextFundingTime on delisted pairs
            if nxt_raw and int(nxt_raw) > 0:
                try:
                    nxt = datetime.fromtimestamp(int(nxt_raw) / 1000, tz=timezone.utc)
                except (ValueError, OSError):
                    nxt = None

            records.append(FundingRecord(
                exchange=self.name,
                symbol=sym,
                mark_price=mark,
                index_price=index,
                funding_rate=rate,
                next_funding_time=nxt,
                funding_interval_hours=8,
            ))
        return records

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
