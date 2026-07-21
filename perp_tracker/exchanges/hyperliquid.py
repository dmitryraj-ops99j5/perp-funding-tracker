import time
import httpx
from perp_tracker.exchanges.base import BaseExchange, FundingSnapshot


class HyperliquidExchange(BaseExchange):
    name = "hyperliquid"
    API_URL = "https://api.hyperliquid.xyz/info"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def fetch_rates(self) -> list[FundingSnapshot]:
        """Pulls current funding and mark prices from metaAndAssetCtxs."""
        payload = {"type": "metaAndAssetCtxs"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.API_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        universe = data[0]["universe"]
        ctxs = data[1]
        now = int(time.time())
        snapshots = []

        for i, meta in enumerate(universe):
            name = meta.get("name", "")
            if not name or meta.get("isDelisted", False):
                continue

            ctx = ctxs[i]

            # oraclePx is fallback if markPx is zero or None during auction
            mark_raw = ctx.get("markPx") or ctx.get("oraclePx") or "0"
            mark_px = float(mark_raw)
            if mark_px <= 0:
                continue

            # HL reports 1-hour funding rate as string fraction
            funding_1h = float(ctx.get("funding") or 0.0)
            oi_coins = float(ctx.get("openInterest") or 0.0)
            oi_usd = oi_coins * mark_px

            # print(f"HL {name}: 1h={funding_1h} oi_usd={oi_usd}")

            snapshots.append(
                FundingSnapshot(
                    exchange=self.name,
                    symbol=f"{name}-PERP",
                    base_asset=name.upper(),
                    rate_1h=funding_1h,
                    rate_8h=funding_1h * 8.0,
                    mark_price=mark_px,
                    open_interest_usd=oi_usd,
                    timestamp=now,
                )
            )

        return snapshots
