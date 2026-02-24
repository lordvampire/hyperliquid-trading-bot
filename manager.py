"""Risk Manager — daily drawdown cap, circuit breaker, position sizing.

Bug #3 fix: State is persisted to SQLite so API and bot processes share
the same circuit breaker / risk state via the daily_stats table.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RiskManager:
    max_daily_dd_pct: float = 5.0
    max_consecutive_losses: int = 3
    default_size_pct: float = 2.0
    db_path: str = "trading_bot.db"

    # State (reset daily)
    starting_balance: float = 0.0
    current_balance: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    circuit_breaker_active: bool = False
    _trade_date: str = field(default="", repr=False)

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def reset_day(self, balance: float):
        """Call at start of each trading day."""
        self.starting_balance = balance
        self.current_balance = balance
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self._trade_date = self._today()

    def record_trade(self, pnl: float):
        """Record a completed trade's P&L."""
        self.daily_pnl += pnl
        self.current_balance += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.circuit_breaker_active = True

    def can_trade(self) -> tuple[bool, str]:
        if self.circuit_breaker_active:
            return False, f"Circuit breaker: {self.consecutive_losses} consecutive losses"

        if self.starting_balance > 0:
            dd_pct = (self.daily_pnl / self.starting_balance) * 100
            if dd_pct <= -self.max_daily_dd_pct:
                return False, f"Daily DD cap hit: {dd_pct:.2f}% (max: -{self.max_daily_dd_pct}%)"

        return True, "OK"

    def get_position_size(self, balance: float = None) -> float:
        bal = balance or self.current_balance
        return bal * (self.default_size_pct / 100)

    def status(self) -> dict:
        can, reason = self.can_trade()
        return {
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "daily_pnl": self.daily_pnl,
            "daily_dd_pct": (self.daily_pnl / self.starting_balance * 100) if self.starting_balance else 0,
            "consecutive_losses": self.consecutive_losses,
            "circuit_breaker_active": self.circuit_breaker_active,
            "can_trade": can,
            "reason": reason,
        }

    # --- SQLite persistence (Bug #3) ---

    async def load_state(self):
        """Load today's risk state from DB. If date changed, start fresh."""
        import aiosqlite
        today = self._today()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchall(
                "SELECT * FROM daily_stats WHERE date = ?", (today,)
            )
        if row:
            r = dict(row[0])
            self.starting_balance = r.get("starting_balance") or 0.0
            self.current_balance = (r.get("ending_balance") or self.starting_balance)
            self.daily_pnl = r.get("realized_pnl") or 0.0
            self.consecutive_losses = r.get("consecutive_losses") or 0
            self.circuit_breaker_active = bool(r.get("circuit_breaker_hit"))
            self._trade_date = today

    async def save_state(self):
        """Persist current risk state to DB atomically."""
        import aiosqlite
        today = self._today()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO daily_stats
                   (date, starting_balance, ending_balance, realized_pnl,
                    trade_count, consecutive_losses, circuit_breaker_hit)
                   VALUES (?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     ending_balance = excluded.ending_balance,
                     realized_pnl = excluded.realized_pnl,
                     consecutive_losses = excluded.consecutive_losses,
                     circuit_breaker_hit = excluded.circuit_breaker_hit""",
                (today, self.starting_balance, self.current_balance,
                 self.daily_pnl, self.consecutive_losses,
                 1 if self.circuit_breaker_active else 0),
            )
            await db.commit()
