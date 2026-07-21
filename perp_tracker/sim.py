from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3


@dataclass
class Position:
    id: int | None
    symbol: str
    long_venue: str
    short_venue: str
    notional_usd: float
    entry_price_long: float
    entry_price_short: float
    opened_at: str
    closed_at: str | None = None
    realized_funding: float = 0.0
    fees_paid: float = 0.0
    status: str = "OPEN"


class CarrySimulator:
    """Simulates delta-neutral funding carry trades across exchanges."""

    def __init__(self, db_path: str = "perp_tracker.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sim_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    long_venue TEXT NOT NULL,
                    short_venue TEXT NOT NULL,
                    notional_usd REAL NOT NULL,
                    entry_price_long REAL NOT NULL,
                    entry_price_short REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    realized_funding REAL DEFAULT 0.0,
                    fees_paid REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'OPEN'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sim_funding_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    venue TEXT NOT NULL,
                    side TEXT NOT NULL,
                    funding_rate REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(position_id) REFERENCES sim_positions(id)
                )
            """)
            conn.commit()

    def open_position(
        self,
        symbol: str,
        long_venue: str,
        short_venue: str,
        notional_usd: float,
        price_long: float,
        price_short: float,
        taker_fee_bps: float = 5.0,
    ) -> int:
        # taker fee applied on both legs on entry
        entry_fee = notional_usd * (taker_fee_bps / 10000.0) * 2
        now = datetime.now(timezone.utc).isoformat()

        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO sim_positions (
                    symbol, long_venue, short_venue, notional_usd,
                    entry_price_long, entry_price_short, opened_at, fees_paid, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (symbol, long_venue, short_venue, notional_usd, price_long, price_short, now, entry_fee),
            )
            conn.commit()
            return cur.lastrowid

    def apply_funding(
        self,
        pos_id: int,
        venue: str,
        side: str,
        funding_rate: float,
        timestamp: str | None = None,
    ) -> float:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        # Hyperliquid rates are 1h, Binance/Bybit are 8h standard snapshots.
        # The stored rate should be the per-interval payment rate.
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sim_positions WHERE id = ?", (pos_id,)).fetchone()
            if not row or row["status"] != "OPEN":
                return 0.0

            notional = row["notional_usd"]
            # if short, positive funding means we collect; if long, we pay
            if side.upper() == "SHORT":
                payment = notional * funding_rate
            else:
                payment = -1.0 * notional * funding_rate

            # print(f"[DEBUG] funding pos={pos_id} venue={venue} rate={funding_rate} payout={payment}")

            conn.execute(
                """
                INSERT INTO sim_funding_events (position_id, venue, side, funding_rate, amount_usd, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pos_id, venue, side.upper(), funding_rate, payment, timestamp),
            )

            new_funding = row["realized_funding"] + payment
            conn.execute(
                "UPDATE sim_positions SET realized_funding = ? WHERE id = ?",
                (new_funding, pos_id),
            )
            conn.commit()
            return payment

    def close_position(self, pos_id: int, taker_fee_bps: float = 5.0) -> dict:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sim_positions WHERE id = ?", (pos_id,)).fetchone()
            if not row:
                raise ValueError(f"Position {pos_id} not found")
            if row["status"] == "CLOSED":
                raise ValueError(f"Position {pos_id} is already closed")

            exit_fee = row["notional_usd"] * (taker_fee_bps / 10000.0) * 2
            total_fees = row["fees_paid"] + exit_fee
            closed_at = datetime.now(timezone.utc).isoformat()
            net_pnl = row["realized_funding"] - total_fees

            conn.execute(
                """
                UPDATE sim_positions
                SET status = 'CLOSED', closed_at = ?, fees_paid = ?
                WHERE id = ?
                """,
                (closed_at, total_fees, pos_id),
            )
            conn.commit()

            return {
                "id": pos_id,
                "symbol": row["symbol"],
                "notional_usd": row["notional_usd"],
                "realized_funding": round(row["realized_funding"], 4),
                "fees_paid": round(total_fees, 4),
                "net_pnl": round(net_pnl, 4),
                "roi_pct": round((net_pnl / row["notional_usd"]) * 100, 4),
            }

    def list_open_positions(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM sim_positions WHERE status = 'OPEN' ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def get_summary(self) -> dict:
        # quick rollup for cli dashboard
        with self._get_conn() as conn:
            open_count = conn.execute("SELECT COUNT(*) FROM sim_positions WHERE status = 'OPEN'").fetchone()[0]
            closed_count = conn.execute("SELECT COUNT(*) FROM sim_positions WHERE status = 'CLOSED'").fetchone()[0]
            totals = conn.execute("""
                SELECT
                    COALESCE(SUM(realized_funding), 0.0) as total_funding,
                    COALESCE(SUM(fees_paid), 0.0) as total_fees
                FROM sim_positions
            """).fetchone()

            funding = totals["total_funding"]
            fees = totals["total_fees"]
            return {
                "open_positions": open_count,
                "closed_positions": closed_count,
                "total_funding_collected": round(funding, 4),
                "total_fees_paid": round(fees, 4),
                "net_sim_pnl": round(funding - fees, 4),
            }
