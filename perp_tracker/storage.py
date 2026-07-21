import sqlite3
from pathlib import Path
from perp_tracker.exchanges.base import FundingSnapshot

CURRENT_SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS funding_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    base_asset TEXT NOT NULL,
    rate_1h REAL NOT NULL,
    rate_8h REAL NOT NULL,
    mark_price REAL NOT NULL,
    open_interest_usd REAL NOT NULL,
    timestamp INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rates_asset_ts ON funding_rates(base_asset, timestamp);

CREATE TABLE IF NOT EXISTS sim_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    long_exchange TEXT NOT NULL,
    short_exchange TEXT NOT NULL,
    base_asset TEXT NOT NULL,
    notional REAL NOT NULL,
    entry_ts INTEGER NOT NULL,
    exit_ts INTEGER,
    long_entry_price REAL NOT NULL,
    short_entry_price REAL NOT NULL,
    long_exit_price REAL,
    short_exit_price REAL,
    accumulated_funding REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'OPEN'
);
"""


class Storage:
    def __init__(self, db_path: str | Path = "rates.db"):
        self.db_path = str(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        # FIXME: handle sqlite busy timeout when poller runs alongside sim backfill
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            version = conn.execute("PRAGMA user_version;").fetchone()[0]
            if version == 0:
                conn.executescript(SCHEMA_V1)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rates_ex_asset_ts ON funding_rates(exchange, base_asset, timestamp);")
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};")
            elif version < 2:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rates_ex_asset_ts ON funding_rates(exchange, base_asset, timestamp);")
                conn.execute("PRAGMA user_version = 2;")

    def insert_rates(self, rates: list[FundingSnapshot]) -> int:
        if not rates:
            return 0
        rows = [
            (
                r.exchange,
                r.symbol,
                r.base_asset,
                r.rate_1h,
                r.rate_8h,
                r.mark_price,
                r.open_interest_usd,
                r.timestamp,
            )
            for r in rates
        ]
        sql = """
        INSERT INTO funding_rates (
            exchange, symbol, base_asset, rate_1h, rate_8h, mark_price, open_interest_usd, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_conn() as conn:
            conn.executemany(sql, rows)
        return len(rows)

    def get_latest_rates(self, max_age_seconds: int = 3600) -> list[dict]:
        sql = """
        SELECT f1.*
        FROM funding_rates f1
        JOIN (
            SELECT exchange, base_asset, MAX(timestamp) as max_ts
            FROM funding_rates
            GROUP BY exchange, base_asset
        ) f2 ON f1.exchange = f2.exchange AND f1.base_asset = f2.base_asset AND f1.timestamp = f2.max_ts
        WHERE f1.timestamp >= strftime('%s', 'now') - ?
        ORDER BY f1.base_asset, f1.exchange
        """
        with self._get_conn() as conn:
            cur = conn.execute(sql, (max_age_seconds,))
            return [dict(row) for row in cur.fetchall()]

    def get_rate_history(self, base_asset: str, exchange: str, start_ts: int, end_ts: int) -> list[dict]:
        sql = """
        SELECT rate_8h, rate_1h, mark_price, timestamp
        FROM funding_rates
        WHERE base_asset = ? AND exchange = ? AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
        """
        with self._get_conn() as conn:
            cur = conn.execute(sql, (base_asset.upper(), exchange, start_ts, end_ts))
            return [dict(row) for row in cur.fetchall()]

    def save_position(self, pos: dict) -> int:
        if "id" in pos and pos["id"]:
            sql = """
            UPDATE sim_positions
            SET exit_ts = :exit_ts,
                long_exit_price = :long_exit_price,
                short_exit_price = :short_exit_price,
                accumulated_funding = :accumulated_funding,
                status = :status
            WHERE id = :id
            """
            with self._get_conn() as conn:
                conn.execute(sql, pos)
            return pos["id"]
        else:
            sql = """
            INSERT INTO sim_positions (
                strategy_id, long_exchange, short_exchange, base_asset, notional,
                entry_ts, long_entry_price, short_entry_price, accumulated_funding, status
            ) VALUES (
                :strategy_id, :long_exchange, :short_exchange, :base_asset, :notional,
                :entry_ts, :long_entry_price, :short_entry_price, :accumulated_funding, :status
            )
            """
            with self._get_conn() as conn:
                cur = conn.execute(sql, pos)
                return cur.lastrowid

    def get_open_positions(self, strategy_id: str | None = None) -> list[dict]:
        if strategy_id:
            sql = "SELECT * FROM sim_positions WHERE status = 'OPEN' AND strategy_id = ?"
            params = (strategy_id,)
        else:
            sql = "SELECT * FROM sim_positions WHERE status = 'OPEN'"
            params = ()
        with self._get_conn() as conn:
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
