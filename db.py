"""SQLite database — schema, migrations, and query helpers."""

import aiosqlite
import json
from datetime import datetime, timezone
from config import cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    size REAL NOT NULL,
    price REAL NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'market',
    status TEXT NOT NULL DEFAULT 'filled',
    pnl REAL,
    fee REAL,
    hl_order_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    entry_price REAL NOT NULL,
    unrealized_pnl REAL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    starting_balance REAL,
    ending_balance REAL,
    realized_pnl REAL DEFAULT 0,
    trade_count INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    circuit_breaker_hit INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candle_cache (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, interval, open_time)
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(cfg.DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.commit()
    await db.close()


async def log_trade(symbol: str, side: str, size: float, price: float,
                    order_type: str = "market", pnl: float = None,
                    fee: float = None, hl_order_id: str = None):
    db = await get_db()
    await db.execute(
        "INSERT INTO trades (symbol, side, size, price, order_type, pnl, fee, hl_order_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol, side, size, price, order_type, pnl, fee, hl_order_id)
    )
    await db.commit()
    await db.close()


async def get_today_stats() -> dict:
    db = await get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = await db.execute_fetchall(
        "SELECT * FROM daily_stats WHERE date = ?", (today,)
    )
    await db.close()
    if row:
        return dict(row[0])
    return {"date": today, "realized_pnl": 0, "trade_count": 0, "consecutive_losses": 0}


async def update_daily_stats(realized_pnl: float, consecutive_losses: int):
    db = await get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await db.execute(
        """INSERT INTO daily_stats (date, realized_pnl, trade_count, consecutive_losses)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(date) DO UPDATE SET
             realized_pnl = realized_pnl + ?,
             trade_count = trade_count + 1,
             consecutive_losses = ?""",
        (today, realized_pnl, consecutive_losses, realized_pnl, consecutive_losses)
    )
    await db.commit()
    await db.close()
