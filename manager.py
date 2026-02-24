"""Risk Manager — daily drawdown cap, circuit breaker, position sizing."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RiskManager:
    max_daily_dd_pct: float = 5.0       # max daily drawdown as % of starting balance
    max_consecutive_losses: int = 3      # circuit breaker trigger
    default_size_pct: float = 2.0        # default position size as % of balance

    # State (reset daily)
    starting_balance: float = 0.0
    current_balance: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    circuit_breaker_active: bool = False
    _trade_date: str = field(default="", repr=False)

    def reset_day(self, balance: float):
        """Call at start of each trading day."""
        self.starting_balance = balance
        self.current_balance = balance
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self._trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def record_trade(self, pnl: float):
        """Record a completed trade's P&L. Updates DD tracking + circuit breaker."""
        self.daily_pnl += pnl
        self.current_balance += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check circuit breaker
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.circuit_breaker_active = True

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed. Returns (allowed, reason)."""
        if self.circuit_breaker_active:
            return False, f"Circuit breaker: {self.consecutive_losses} consecutive losses"

        if self.starting_balance > 0:
            dd_pct = (self.daily_pnl / self.starting_balance) * 100
            if dd_pct <= -self.max_daily_dd_pct:
                return False, f"Daily DD cap hit: {dd_pct:.2f}% (max: -{self.max_daily_dd_pct}%)"

        return True, "OK"

    def get_position_size(self, balance: float = None) -> float:
        """Calculate position size in USD based on % of balance."""
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
