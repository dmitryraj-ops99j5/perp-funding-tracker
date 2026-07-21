import pytest
from perp_tracker.sim import PaperAccount, CarryTrade


def test_account_initial_balance():
    acc = PaperAccount(initial_balance=10_000.0, taker_fee_bps=5.0)
    assert acc.balance == 10_000.0
    assert acc.realized_pnl == 0.0
    assert len(acc.positions) == 0


def test_open_position_deducts_fee():
    # 5 bps = 0.05% = 0.0005
    acc = PaperAccount(initial_balance=10_000.0, taker_fee_bps=5.0)
    trade = acc.open_trade(
        symbol="BTC",
        long_exchange="binance_spot",
        short_exchange="binance_perp",
        notional=2_000.0,
        spot_price=60_000.0,
        perp_price=60_050.0,
    )
    # 2000 notional on spot + 2000 on perp = 4000 total turnover
    # fee = 4000 * 0.0005 = 2.0
    assert trade.entry_fees == pytest.approx(2.0)
    assert acc.balance == pytest.approx(10_000.0 - 2.0)
    assert len(acc.positions) == 1


def test_positive_funding_accrual():
    acc = PaperAccount(initial_balance=5_000.0, taker_fee_bps=0.0)
    trade = acc.open_trade(
        symbol="ETH",
        long_exchange="spot",
        short_exchange="bybit",
        notional=1_000.0,
        spot_price=3_000.0,
        perp_price=3_000.0,
    )
    
    # 0.01% funding rate (0.0001) paid every 8h
    # short position earns funding when rate is positive
    payment = acc.apply_funding(trade.trade_id, rate=0.0001, perp_price=3_000.0)
    assert payment == pytest.approx(0.10)  # 1000 * 0.0001
    assert trade.funding_collected == pytest.approx(0.10)
    assert acc.balance == pytest.approx(5_000.0 + 0.10)


def test_negative_funding_pays_out():
    acc = PaperAccount(initial_balance=5_000.0, taker_fee_bps=0.0)
    trade = acc.open_trade(
        symbol="ETH",
        long_exchange="spot",
        short_exchange="hyperliquid",
        notional=2_000.0,
        spot_price=3_000.0,
        perp_price=3_000.0,
    )
    
    # negative funding: longs get paid, shorts pay
    payment = acc.apply_funding(trade.trade_id, rate=-0.0002, perp_price=3_000.0)
    assert payment == pytest.approx(-0.40)
    assert trade.funding_collected == pytest.approx(-0.40)
    assert acc.balance == pytest.approx(5_000.0 - 0.40)


def test_perp_perp_differential_funding():
    # Long on Binance (pays/receives rate_a), Short on Hyperliquid (receives/pays rate_b)
    acc = PaperAccount(initial_balance=10_000.0, taker_fee_bps=0.0)
    trade = acc.open_trade(
        symbol="BTC",
        long_exchange="binance",
        short_exchange="hyperliquid",
        notional=10_000.0,
        spot_price=50_000.0,
        perp_price=50_000.0,
        is_perp_perp=True,
    )
    
    # binance funding is 0.0001 (long pays 1.0)
    # hl funding is 0.0004 (short receives 4.0)
    # net funding income should be +3.0
    payment = acc.apply_perp_perp_funding(
        trade.trade_id,
        long_rate=0.0001,
        short_rate=0.0004,
        long_price=50_000.0,
        short_price=50_000.0,
    )
    assert payment == pytest.approx(3.0)
    assert acc.balance == pytest.approx(10_003.0)


def test_close_with_basis_drift():
    # entered when perp was at a premium, closed when premium converged
    acc = PaperAccount(initial_balance=10_000.0, taker_fee_bps=0.0)
    trade = acc.open_trade(
        symbol="SOL",
        long_exchange="spot",
        short_exchange="bybit",
        notional=1_000.0,
        spot_price=100.0,  # bought 10 SOL for 1000
        perp_price=102.0,  # shorted 9.8039 SOL for 1000 notional
    )
    
    # spot moves to 110 (+100 pnl on spot: 10 * 110 - 1000 = +100)
    # perp moves to 110 (converged with spot)
    # short pnl: 9.8039 * (102 - 110) = -78.4313
    # basis gain net: 100 - 78.4313 = 21.5686
    pnl = acc.close_trade(
        trade.trade_id,
        spot_price=110.0,
        perp_price=110.0,
    )
    assert pnl == pytest.approx(21.5686, abs=0.01)


def test_close_position_pnl_calc():
    acc = PaperAccount(initial_balance=10_000.0, taker_fee_bps=5.0)
    trade = acc.open_trade(
        symbol="SOL",
        long_exchange="spot",
        short_exchange="binance",
        notional=1_000.0,
        spot_price=100.0,
        perp_price=100.0,
    )
    # entry fee: 2000 * 0.0005 = 1.0
    
    # collect 3 funding intervals at 0.03% each
    for _ in range(3):
        acc.apply_funding(trade.trade_id, rate=0.0003, perp_price=100.0)
    
    # funding should be 1000 * 0.0003 * 3 = 0.90
    assert trade.funding_collected == pytest.approx(0.90)
    
    # close with spot and perp price unchanged
    # exit fee: 2000 * 0.0005 = 1.0
    pnl = acc.close_trade(
        trade.trade_id,
        spot_price=100.0,
        perp_price=100.0,
    )
    
    # net pnl = 0.90 (funding) - 1.0 (entry fee) - 1.0 (exit fee) = -1.10
    assert pnl == pytest.approx(-1.10)
    assert acc.balance == pytest.approx(10_000.0 - 1.10)
    assert len(acc.positions) == 0
