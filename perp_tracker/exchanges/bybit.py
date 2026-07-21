from datetime import datetime, timezone
import httpx
from perp_tracker.config import DEFAULT_HTTP_TIMEOUT, USER_AGENT
from perp_tracker.exchanges.base import ExchangeAdapter, FundingRecord

BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"

class BybitAdapter(ExchangeAdapter):
    name = "bybit"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            timeout=DEFAULT_HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None

    async def fetch_funding_rates(self) -> list[FundingRecord]:
        # bybit returns all linear tickers in a single page if limit is high enough (up to 1000)
        params = {"category": "linear", "limit": "1000"}
        resp = await self._client.get(BYBIT_TICKERS_URL, params=params)
        resp.raise_for_status()
        body = resp.json()

        ret_code = body.get("retCode")
        if ret_code != 0:
            return []

        items = body.get("result", {}).get("list", [])
        records: list[FundingRecord] = []

        for item in items:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue

            # Bybit linear tickers without active funding rate are either pre-market or suspended
            raw_rate = item.get("fundingRate")
            if not raw_rate:
                continue

            try:
                mark = float(item.get("markPrice") or 0)
                index = float(item.get("indexPrice") or mark)
                rate = float(raw_rate)
            except (ValueError, TypeError):
                continue

            if mark <= 0:
                continue

            # bybit nextFundingTime is epoch ms as string
            nxt_raw = item.get("nextFundingTime")
            nxt = None
            if nxt_raw and str(nxt_raw).isdigit() and int(nxt_raw) > 0:
                nxt = datetime.fromtimestamp(int(nxt_raw) / 1000, tz=timezone.utc)

            # fundingIntervalHour is not always returned on tickers endpoint, defaults to 8
            interval_hours = 8
            raw_interval = item.get("fundingIntervalHour")
            if raw_interval and str(raw_interval).isdigit():
                interval_hours = int(raw_interval)

            records.append(FundingRecord(
                exchange=self.name,
                symbol=sym,
                mark_price=mark,
                index_price=index,
                funding_rate=rate,
                next_funding_time=nxt,
                funding_interval_hours=interval_hours,
            ))
        return records

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
