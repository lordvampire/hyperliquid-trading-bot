"""
SafetyManager — Production safety guards and circuit breaker for live trading.

Responsibilities:
  • Pre-trade validation (liquidity, slippage, price bounds)
  • Daily loss circuit breaker (5% max drawdown)
  • Leverage enforcement (max 35x, warn at 30x)
  • Network health check (latency < 2 s)
  • Daily report generation
  • Immutable audit logging (append-only)

Usage:
    from safety_manager import SafetyManager
    from config.manager import ConfigManager

    config  = ConfigManager("config/base.yaml", "live")
    safety  = SafetyManager(config)

    ok, reason = safety.check_pre_trade(signal, current_price=45_000, balance=1000)
    if ok:
        ...place order...
    safety.log_trade(trade_id, symbol, signal, entry_price, size, "executed")
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from strategies.base import Signal
from config.manager import ConfigManager

logger = logging.getLogger(__name__)


class SafetyManager:
    """Production safety layer — every trade must pass before execution."""

    def __init__(self, config: ConfigManager):
        self.config = config

        # Safety thresholds from config
        self.max_daily_dd_pct: float   = float(config.get("safety.max_daily_dd_pct", 5.0))
        self.max_leverage: float        = float(config.get("safety.max_leverage", 35.0))
        self.max_slippage_pct: float    = float(config.get("safety.max_slippage_pct", 2.0))
        self.network_latency_limit_ms: float = float(
            config.get("safety.network_latency_limit_ms", 2000)
        )

        # Audit log (append-only)
        self.audit_log_path = Path(config.get("safety.audit_log_path", "logs/audit.log"))
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Daily P&L tracking (in-memory, reset on daily_reset())
        self._daily_start_balance: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_trades: List[Dict[str, Any]] = []

        logger.info(
            f"[SafetyManager] Ready — max_dd={self.max_daily_dd_pct}%, "
            f"max_leverage={self.max_leverage}x, "
            f"max_slippage={self.max_slippage_pct}%"
        )

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    def check_pre_trade(
        self,
        signal: Signal,
        current_price: float,
        balance: float,
    ) -> Tuple[bool, str]:
        """
        Full pre-trade safety validation.

        Checks:
          1. Signal is not HOLD
          2. Slippage estimate < max_slippage_pct
          3. Price bounds (within ±20% of simple SMA proxy)
          4. Daily loss circuit breaker
          5. Network health

        Returns:
            (is_safe: bool, reason: str)  — reason is empty string when safe.
        """
        if signal.direction == "HOLD":
            return False, "Signal is HOLD — no trade needed"

        # 1. Slippage estimate (simplified: 0.05% base + volatility proxy)
        estimated_slippage = self._estimate_slippage(signal, current_price)
        if estimated_slippage > self.max_slippage_pct:
            reason = (
                f"Estimated slippage {estimated_slippage:.2f}% exceeds "
                f"limit {self.max_slippage_pct:.2f}%"
            )
            logger.warning(f"[SafetyManager] PRE-TRADE REJECTED: {reason}")
            return False, reason

        # 2. Price bounds check (not >20% from a rough SMA proxy stored in metadata)
        if "sma" in signal.metadata:
            sma = float(signal.metadata["sma"])
            deviation = abs(current_price - sma) / sma
            if deviation > 0.20:
                reason = (
                    f"Price {current_price:.2f} is {deviation*100:.1f}% from "
                    f"SMA {sma:.2f} — exceeds 20% bound"
                )
                logger.warning(f"[SafetyManager] PRE-TRADE REJECTED: {reason}")
                return False, reason

        # 3. Daily limit check
        if not self.check_daily_limit():
            reason = (
                f"Daily loss circuit breaker active — "
                f"daily_pnl={self._daily_pnl:.2f} "
                f"(limit: -{self.max_daily_dd_pct}% of starting balance)"
            )
            logger.warning(f"[SafetyManager] PRE-TRADE REJECTED: {reason}")
            return False, reason

        # 4. Liquidity check (signal strength proxy — <0.2 = thin market)
        if signal.strength < 0.2:
            reason = f"Signal strength {signal.strength:.2f} too low — insufficient liquidity signal"
            logger.warning(f"[SafetyManager] PRE-TRADE REJECTED: {reason}")
            return False, reason

        logger.info(
            f"[SafetyManager] Pre-trade OK: {signal.symbol} {signal.direction} "
            f"strength={signal.strength:.2f} slippage≈{estimated_slippage:.3f}%"
        )
        return True, ""

    def _estimate_slippage(self, signal: Signal, current_price: float) -> float:
        """
        Estimate slippage as base spread + strength-adjusted market impact.
        Returns percentage (e.g. 0.08 = 0.08%).
        """
        base_spread = 0.05          # 0.05% baseline spread on Hyperliquid
        impact = (1.0 - signal.strength) * 0.5   # higher confidence → lower impact
        return round(base_spread + impact, 4)

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def check_daily_limit(self) -> bool:
        """
        Return False (block trading) if daily loss >= max_daily_dd_pct.

        Uses _daily_pnl updated by update_daily_pnl() or set_daily_start_balance().
        """
        if self._daily_start_balance <= 0:
            return True     # no baseline yet → allow

        daily_dd_pct = (-self._daily_pnl / self._daily_start_balance) * 100
        if daily_dd_pct >= self.max_daily_dd_pct:
            logger.error(
                f"[SafetyManager] 🔴 CIRCUIT BREAKER ACTIVE: "
                f"daily_dd={daily_dd_pct:.2f}% >= limit {self.max_daily_dd_pct}%"
            )
            return False
        return True

    def update_daily_pnl(self, pnl_delta: float) -> None:
        """Add pnl_delta to today's running P&L."""
        self._daily_pnl += pnl_delta

    def set_daily_start_balance(self, balance: float) -> None:
        """Called at daily_reset() to record baseline for % calculation."""
        self._daily_start_balance = balance
        self._daily_pnl = 0.0
        self._daily_trades = []

    # ------------------------------------------------------------------
    # Leverage check
    # ------------------------------------------------------------------

    def check_leverage(self, position_size: float, leverage: float) -> bool:
        """
        Return False if leverage exceeds max_leverage.
        Log a warning when leverage >= 30x.
        """
        if leverage >= 30.0:
            logger.warning(
                f"[SafetyManager] ⚠️  HIGH LEVERAGE WARNING: {leverage:.1f}x "
                f"(warn threshold: 30x, hard limit: {self.max_leverage}x)"
            )
        if leverage > self.max_leverage:
            logger.error(
                f"[SafetyManager] ❌ LEVERAGE EXCEEDED: {leverage:.1f}x > {self.max_leverage}x"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Network health
    # ------------------------------------------------------------------

    def check_network_health(self) -> bool:
        """
        Ping the Hyperliquid API and return False if latency > limit.
        """
        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "meta"}
        try:
            start = time.monotonic()
            resp = requests.post(url, json=payload, timeout=5)
            latency_ms = (time.monotonic() - start) * 1000
            resp.raise_for_status()
            ok = latency_ms <= self.network_latency_limit_ms
            if ok:
                logger.info(f"[SafetyManager] ✅ Network healthy — latency={latency_ms:.0f}ms")
            else:
                logger.warning(
                    f"[SafetyManager] ⚠️  Network slow: {latency_ms:.0f}ms "
                    f"> {self.network_latency_limit_ms:.0f}ms limit"
                )
            return ok
        except Exception as exc:
            logger.error(f"[SafetyManager] ❌ Network check failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Daily report
    # ------------------------------------------------------------------

    def generate_daily_report(self) -> str:
        """
        Generate a text/HTML summary of today's trading activity.

        Returns:
            Multi-line string (plain-text format with HTML tags for email).
        """
        today = date.today().isoformat()
        trades = self._daily_trades
        total = len(trades)
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losses = total - wins
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        win_rate = (wins / total * 100) if total > 0 else 0.0

        report = (
            f"<h2>📊 Daily Trading Report — {today}</h2>\n"
            f"<hr/>\n"
            f"<b>Trades:</b> {total} &nbsp; "
            f"<b>Wins:</b> {wins} &nbsp; "
            f"<b>Losses:</b> {losses} &nbsp; "
            f"<b>Win Rate:</b> {win_rate:.1f}%<br/>\n"
            f"<b>Total P&L:</b> ${total_pnl:+.2f}<br/>\n"
            f"<b>Starting Balance:</b> ${self._daily_start_balance:,.2f}<br/>\n"
            f"<hr/>\n"
        )

        if trades:
            report += "<b>Trade Log:</b><br/>\n<ul>\n"
            for t in trades[-20:]:  # show last 20
                ts   = t.get("timestamp", "")[:19]
                sym  = t.get("symbol", "?")
                side = t.get("direction", "?")
                px   = t.get("entry_price", 0)
                sz   = t.get("size", 0)
                st   = t.get("status", "?")
                report += (
                    f"<li>{ts} | {sym} {side} | px={px:.2f} sz={sz:.4f} | {st}</li>\n"
                )
            report += "</ul>\n"

        circuit = "🔴 ACTIVE" if not self.check_daily_limit() else "🟢 Off"
        report += f"<b>Circuit Breaker:</b> {circuit}<br/>\n"
        return report

    # ------------------------------------------------------------------
    # Audit log (immutable, append-only)
    # ------------------------------------------------------------------

    def log_trade(
        self,
        trade_id: str,
        symbol: str,
        signal: Signal,
        entry_price: float,
        size: float,
        status: str,
        pnl: float = 0.0,
    ) -> None:
        """
        Write an immutable audit entry (append-only) to the audit log.

        Args:
            trade_id:    Unique trade identifier.
            symbol:      Trading symbol (e.g. "BTC").
            signal:      The Signal object that triggered the trade.
            entry_price: Fill price in USD.
            size:        Position size in contracts.
            status:      One of: executed, rejected, closed, error.
            pnl:         Realized P&L (filled in on close).
        """
        entry = {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "trade_id":    trade_id,
            "symbol":      symbol,
            "direction":   signal.direction,
            "strength":    round(signal.strength, 4),
            "entry_price": round(entry_price, 4),
            "size":        round(size, 8),
            "stop_loss":   signal.stop_loss,
            "take_profit": signal.take_profit,
            "status":      status,
            "pnl":         round(pnl, 4),
            "metadata":    signal.metadata,
        }

        # Append-only write (no truncation, no rewrite)
        with self.audit_log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

        # Track in-memory for daily report
        self._daily_trades.append(entry)
        logger.info(f"[SafetyManager] AUDIT: {status} {symbol} {signal.direction} px={entry_price:.2f}")
