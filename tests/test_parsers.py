import pytest
from perp_tracker.exchanges.binance import parse_binance_funding
from perp_tracker.exchanges.bybit import parse_bybit_ticker
from perp_tracker.exchanges.hyperliquid import parse_hyperliquid_meta


BINANCE_RAW_ITEM = {
    "symbol": "BTCUSDT",
    "markPrice": "64210.50000000",
    "indexPrice": "64195.10000000",
    "lastFundingRate": "0.00010000",
    "nextFundingTime": 1716940800000,
}

BINANCE_RAW_NEGATIVE = {
    "symbol": "SOLUSDT",
    "markPrice": "145.20000000",
    "indexPrice": "145.18000000",
    "lastFundingRate": "-0.00035000",
    "nextFundingTime": 1716940800000,
}

BYBIT_RAW_ITEM = {
    "symbol": "BTCUSDT",
    "lastPrice": "64205.00",
    "indexPrice": "64198.50",
    "markPrice": "64200.00",
    "fundingRate": "0.00015",
    "nextFundingTime": "1716940800000",
}

HYPERLIQUID_META_UNIVERSE = [
    {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
    {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
    {"name": "kPEPE", "szDecimals": 0, "maxLeverage": 20},
]

HYPERLIQUID_ASSET_CTXS = [
    {
        "funding": "0.0000125",
        "openInterest": "1542.21",
        "oraclePx": "64200.0",
        "markPx": "64208.5",
        "midPx": "64208.0",
    },
    {
        "funding": "-0.000025",
        "openInterest": "12800.0",
        "oraclePx": "3450.0",
        "markPx": "3451.2",
        "midPx": "3451.0",
    },
    {
        "funding": "0.00005",
        "openInterest": "999999.0",
        "oraclePx": "0.012",
        "markPx": "0.0121",
        "midPx": "0.0121",
    },
]


def test_binance_parsing():
    parsed = parse_binance_funding(BINANCE_RAW_ITEM)
    assert parsed.symbol == "BTC"
    assert parsed.venue == "binance"
    assert parsed.mark_price == 64210.5
    assert parsed.funding_rate == 0.0001
    # 0.01% per 8h -> 3 * 365 = 10.95% annual
    assert round(parsed.annualized_pct, 2) == 10.95


def test_binance_negative_rate():
    parsed = parse_binance_funding(BINANCE_RAW_NEGATIVE)
    assert parsed.symbol == "SOL"
    assert parsed.funding_rate == -0.00035
    assert round(parsed.annualized_pct, 2) == -38.32


def test_bybit_parsing():
    parsed = parse_bybit_ticker(BYBIT_RAW_ITEM)
    assert parsed.symbol == "BTC"
    assert parsed.venue == "bybit"
    assert parsed.funding_rate == 0.00015
    assert parsed.mark_price == 64200.0
    assert round(parsed.annualized_pct, 2) == 16.43


def test_hyperliquid_parsing():
    rates = parse_hyperliquid_meta(HYPERLIQUID_META_UNIVERSE, HYPERLIQUID_ASSET_CTXS)
    assert len(rates) == 3

    btc = next(r for r in rates if r.symbol == "BTC")
    assert btc.venue == "hyperliquid"
    assert btc.funding_rate == 0.0000125
    # HL is hourly: 0.0000125 * 24 * 365 * 100 = 10.95%
    assert round(btc.annualized_pct, 2) == 10.95

    eth = next(r for r in rates if r.symbol == "ETH")
    assert eth.funding_rate == -0.000025
    assert round(eth.annualized_pct, 2) == -21.90


def test_bybit_missing_rate_defaults():
    broken = {"symbol": "DOGEUSDT", "lastPrice": "0.15", "markPrice": "0.15"}
    res = parse_bybit_ticker(broken)
    assert res.funding_rate == 0.0
    assert res.annualized_pct == 0.0
