import argparse
import sys
from datetime import datetime
from rich.console import Console
from rich.table import Table

from perp_tracker.exchanges.binance import BinanceClient
from perp_tracker.exchanges.bybit import BybitClient
from perp_tracker.exchanges.hyperliquid import HyperliquidClient
from perp_tracker.storage import Storage
from perp_tracker.sim import Simulator

console = Console()


def build_rates_table(rates: list[dict]) -> Table:
    tbl = Table(title="Current Funding Rates", header_style="bold cyan")
    tbl.add_column("Exchange", style="bold")
    tbl.add_column("Rate (Interval)", justify="right")
    tbl.add_column("APR (Annualized)", justify="right")
    tbl.add_column("Interval", justify="center")
    tbl.add_column("Next Settlement")

    for r in rates:
        if r.get("error"):
            tbl.add_row(r["exchange"], "[red]ERR[/red]", "-", "-", f"[dim]{r['error']}[/dim]")
            continue

        apr = r["apr"]
        apr_str = f"{apr:+.2f}%"
        if apr > 20.0:
            apr_style = "green"
        elif apr < -5.0:
            apr_style = "red"
        else:
            apr_style = "white"

        next_t = r["next_funding"]
        if isinstance(next_t, (int, float)):
            # some endpoints return ms, some seconds
            ts = next_t / 1000 if next_t > 1e11 else next_t
            settle_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
        else:
            settle_str = str(next_t)

        tbl.add_row(
            r["exchange"],
            f"{r['rate_pct']:+.4f}%",
            f"[{apr_style}]{apr_str}[/{apr_style}]",
            f"{r['interval_hours']}h",
            settle_str,
        )
    return tbl


def handle_rates(args):
    sym = args.symbol.upper()
    # HL uses USDC collateral, binance/bybit standard is USDT for perps
    clients = [
        ("binance", BinanceClient()),
        ("bybit", BybitClient()),
        ("hyperliquid", HyperliquidClient()),
    ]
    rows = []
    with console.status(f"Fetching funding rates for {sym}..."):
        for name, client in clients:
            try:
                res = client.get_funding_rate(sym)
                annual_factor = (24 / res.interval_hours) * 365
                rows.append({
                    "exchange": name,
                    "rate_pct": res.rate * 100,
                    "apr": res.rate * annual_factor * 100,
                    "interval_hours": res.interval_hours,
                    "next_funding": res.next_funding_time,
                })
            except Exception as exc:
                rows.append({
                    "exchange": name,
                    "error": str(exc),
                })

    table = build_rates_table(rows)
    console.print(table)

    # save snapshot to db if requested
    if args.save:
        db = Storage()
        for r in rows:
            if not r.get("error"):
                db.save_rate(sym, r["exchange"], r["rate_pct"] / 100, r["apr"])
        console.print("[dim]Snapshot saved to local db.[/dim]")


def handle_sim_open(args):
    sim = Simulator()
    pos_id = sim.open_position(
        symbol=args.symbol.upper(),
        long_ex=args.long_ex.lower(),
        short_ex=args.short_ex.lower(),
        size_usd=args.size,
    )
    console.print(f"[green]Opened carry position #{pos_id}[/green]: Long {args.symbol} on {args.long_ex}, Short on {args.short_ex} (${args.size:,.2f})")


def handle_sim_status(args):
    sim = Simulator()
    positions = sim.get_active_positions()
    if not positions:
        console.print("No active carry positions found.")
        return

    tbl = Table(title="Paper Trading Positions", header_style="bold magenta")
    tbl.add_column("ID", justify="right")
    tbl.add_column("Symbol")
    tbl.add_column("Long Ex")
    tbl.add_column("Short Ex")
    tbl.add_column("Size (USD)", justify="right")
    tbl.add_column("Accrued PnL", justify="right")
    tbl.add_column("Opened At")

    # TODO: update unrealized funding ticks before rendering
    for p in positions:
        pnl = p["funding_collected_usd"]
        pnl_color = "green" if pnl >= 0 else "red"
        tbl.add_row(
            str(p["id"]),
            p["symbol"],
            p["long_exchange"],
            p["short_exchange"],
            f"${p['size_usd']:,.2f}",
            f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]",
            p["created_at"],
        )
    console.print(tbl)


def handle_sim_close(args):
    sim = Simulator()
    res = sim.close_position(args.position_id)
    if not res:
        console.print(f"[red]Position #{args.position_id} not found or already closed.[/red]")
        return
    console.print(f"Closed position #{args.position_id}. Total net carry: [bold]${res['final_pnl']:+,.2f}[/bold]")


def main():
    parser = argparse.ArgumentParser(prog="perp-tracker", description="Perp funding monitor & carry sim")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # rates command (default if no subcommand given)
    rates_p = subparsers.add_parser("rates", help="Show current rates across venues")
    rates_p.add_argument("symbol", nargs="?", default="BTC", help="Underlying coin (default: BTC)")
    rates_p.add_argument("--save", action="store_true", help="Record rates to sqlite")
    rates_p.set_defaults(func=handle_rates)

    # sim command
    sim_p = subparsers.add_parser("sim", help="Carry trade simulator")
    sim_subs = sim_p.add_subparsers(dest="sim_action", help="Sim actions")

    open_p = sim_subs.add_parser("open", help="Open a delta-neutral funding position")
    open_p.add_argument("--symbol", "-s", default="BTC", help="Asset symbol")
    open_p.add_argument("--long-ex", "-l", required=True, help="Long leg exchange")
    open_p.add_argument("--short-ex", "-r", required=True, help="Short leg exchange")
    open_p.add_argument("--size", type=float, default=10000.0, help="Position size in USD")
    open_p.set_defaults(func=handle_sim_open)

    status_p = sim_subs.add_parser("status", help="Show active paper positions")
    status_p.set_defaults(func=handle_sim_status)

    close_p = sim_subs.add_parser("close", help="Close an existing position")
    close_p.add_argument("position_id", type=int, help="Position ID to close")
    close_p.set_defaults(func=handle_sim_close)

    args = parser.parse_args()

    if not args.command:
        # fallback to rates BTC
        args.symbol = "BTC"
        args.save = False
        handle_rates(args)
        return 0

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

    return 0
