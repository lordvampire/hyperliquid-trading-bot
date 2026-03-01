#!/usr/bin/env python3
"""
strategy_engine.py — Unified VMR Strategy Engine
=================================================
SINGLE SOURCE OF TRUTH for the Volatility Mean Reversion strategy.

Backtest, Paper Trading, and Live Trading ALL import from here.
Changing a parameter here automatically applies to all three modes.

Strategy: Volatility Mean Reversion (VMR)
-----------------------------------------
Logic:
  1. Detect volatility spikes using 1h returns AND Bollinger Band deviation
  2. Enter in the OPPOSITE direction (mean reversion)
  3. Exit on TP (1.5%) or SL (0.5%) — tight risk management
  4. Hold max 24h per position

Configuration: See VMRConfig dataclass below — one place for all params.

Usage:
    from strategy_engine import VMRConfig, VMRStrategy, VMRSignal

    config   = VMRConfig()
    strategy = VMRStrategy(config)
    signal   = strategy.analyze(df, symbol="BTC")

    if signal.direction != "NONE":
        pos = strategy.calculate_position(signal, account_balance=10000.0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION  ← CHANGE PARAMS HERE, APPLIES TO ALL MODES
# ============================================================================

@dataclass
class VMRConfig:
    """
    All VMR strategy parameters in one place.

    Modify these to tune the strategy. All three modes (backtest, paper,
    live) will automatically pick up the changes.
    """

    # ── Signal Detection ─────────────────────────────────────────────────────
    spike_threshold_pct: float = 1.0
    """1h return magnitude that triggers a volatility spike signal (%)."""

    bb_window: int = 20
    """Lookback window (in bars) for Bollinger Band calculation."""

    bb_std_multiplier: float = 2.0
    """Standard-deviation multiplier for Bollinger Band outer bands."""

    require_bb_confirmation: bool = True
    """
    When True, a spike signal is only accepted when the price is also
    outside the Bollinger Band in the same direction (stronger filter).
    When False, spike alone is sufficient (more signals, lower quality).
    """

    # ── Risk Management ──────────────────────────────────────────────────────
    sl_pct: float = 0.005
    """Stop-loss distance from entry as a fraction (0.005 = 0.5%)."""

    tp_pct: float = 0.015
    """Take-profit distance from entry as a fraction (0.015 = 1.5%)."""

    max_hold_hours: int = 24
    """Maximum hours to hold a position before forced exit."""

    # ── Position Sizing ──────────────────────────────────────────────────────
    position_size_pct: float = 0.01
    """Fraction of account balance to risk per trade (0.01 = 1%)."""

    min_leverage: int = 5
    """Minimum leverage applied to position."""

    max_leverage: int = 10
    """Maximum leverage applied to position."""

    # ── Universe ─────────────────────────────────────────────────────────────
    symbols: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    """Symbols traded by this strategy."""

    candle_interval: str = "1h"
    """Candle interval used for signal generation."""

    lookback_days: int = 7
    """Days of historical candle data to fetch for analysis."""

    # ── Risk Limits ──────────────────────────────────────────────────────────
    daily_loss_limit_pct: float = 0.05
    """Maximum daily loss as a fraction of account (0.05 = 5%)."""

    max_open_positions: int = 3
    """Maximum simultaneous open positions."""

    # ── Autonomous Loop ──────────────────────────────────────────────────────
    scan_interval_seconds: int = 900
    """How often (in seconds) the autonomous loop scans for new signals."""


# ============================================================================
# DATA TYPES
# ============================================================================

@dataclass
class VMRSignal:
    """
    Result of strategy.analyze() for one symbol.

    Attributes:
        symbol:       Instrument name (e.g. "BTC").
        direction:    "LONG", "SHORT", or "NONE".
        entry_price:  Suggested entry price.
        stop_loss:    Stop-loss price.
        take_profit:  Take-profit price.
        rr_ratio:     Risk/reward ratio (TP distance / SL distance).
        confidence:   Signal strength 0.0–1.0.
        spike_return: The 1h return that triggered the spike (%).
        volatility:   20-bar rolling std of returns (%).
        bb_upper:     Bollinger Band upper value.
        bb_lower:     Bollinger Band lower value.
        reason:       Human-readable explanation.
        timestamp:    When signal was generated.
    """

    symbol: str
    direction: str            # "LONG" | "SHORT" | "NONE"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rr_ratio: float = 0.0
    confidence: float = 0.0
    spike_return: float = 0.0
    volatility: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VMRPosition:
    """
    Represents an open or closed position.

    Attributes:
        symbol:     Instrument name.
        direction:  "LONG" or "SHORT".
        entry_price, stop_loss, take_profit: Price targets.
        size_usd:   Position notional value in USD.
        size_crypto: Position size in base currency.
        leverage:   Applied leverage.
        entry_time: When the position was opened.
        status:     "OPEN" | "CLOSED".
        exit_price, exit_time, exit_reason, pnl_pct, pnl_usd: Set on close.
    """

    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    size_usd: float
    size_crypto: float
    leverage: int
    entry_time: datetime = field(default_factory=datetime.now)
    status: str = "OPEN"
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0


@dataclass
class VMRTradeResult:
    """Summary returned when a position closes."""

    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl_pct: float
    pnl_usd: float
    hold_hours: float


# ============================================================================
# CORE STRATEGY CLASS
# ============================================================================

class VMRStrategy:
    """
    Volatility Mean Reversion (VMR) Strategy.

    This class provides:
      • analyze(df, symbol)         → VMRSignal
      • calculate_position(signal, account_balance)  → dict
      • check_exit(position, current_price, elapsed_hours) → (should_exit, reason)
      • run_backtest(df, symbol)    → BacktestStats dict

    All three trading modes import this class. Params are controlled
    entirely via VMRConfig.
    """

    def __init__(self, config: Optional[VMRConfig] = None):
        """
        Initialise the VMR strategy.

        Args:
            config: VMRConfig instance. If None, uses default parameters.
        """
        self.config = config or VMRConfig()

    # ── Signal Generation ────────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame, symbol: str) -> VMRSignal:
        """
        Analyse a candle DataFrame and return a VMR trading signal.

        Detection uses TWO conditions:
          1. Spike: |1h return| > spike_threshold_pct
          2. (optional) BB confirmation: price outside Bollinger Band

        Args:
            df:     OHLCV DataFrame with at minimum a 'close' column.
                    Should contain at least (bb_window + 1) rows.
            symbol: Instrument name for labelling.

        Returns:
            VMRSignal with direction "LONG", "SHORT", or "NONE".
        """
        cfg = self.config
        min_bars = cfg.bb_window + 1

        if df is None or len(df) < min_bars:
            return VMRSignal(
                symbol=symbol,
                direction="NONE",
                reason=f"Insufficient data ({len(df) if df is not None else 0} < {min_bars} bars)",
            )

        # ── 1. Compute 1h returns ────────────────────────────────────────────
        df = df.copy()
        df["return_pct"] = df["close"].pct_change() * 100

        latest_return = float(df["return_pct"].iloc[-1])
        current_price = float(df["close"].iloc[-1])

        # Rolling volatility
        vol_20 = float(df["return_pct"].rolling(cfg.bb_window).std().iloc[-1])
        if np.isnan(vol_20):
            vol_20 = float(df["return_pct"].std())

        # ── 2. Bollinger Bands on price ──────────────────────────────────────
        sma = float(df["close"].rolling(cfg.bb_window).mean().iloc[-1])
        price_std = float(df["close"].rolling(cfg.bb_window).std().iloc[-1])
        bb_upper = sma + cfg.bb_std_multiplier * price_std
        bb_lower = sma - cfg.bb_std_multiplier * price_std

        # ── 3. Spike detection ───────────────────────────────────────────────
        is_spike = abs(latest_return) >= cfg.spike_threshold_pct

        if not is_spike:
            return VMRSignal(
                symbol=symbol,
                direction="NONE",
                entry_price=current_price,
                volatility=vol_20,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                spike_return=latest_return,
                reason=(
                    f"No spike: return={latest_return:+.2f}% "
                    f"(threshold ≥ {cfg.spike_threshold_pct:.1f}%)"
                ),
            )

        # Mean-reversion: enter OPPOSITE to spike
        raw_direction = "LONG" if latest_return < -cfg.spike_threshold_pct else "SHORT"

        # ── 4. Bollinger Band confirmation ───────────────────────────────────
        if cfg.require_bb_confirmation:
            below_lower = current_price <= bb_lower
            above_upper = current_price >= bb_upper

            bb_confirmed = (raw_direction == "LONG" and below_lower) or \
                           (raw_direction == "SHORT" and above_upper)

            if not bb_confirmed:
                return VMRSignal(
                    symbol=symbol,
                    direction="NONE",
                    entry_price=current_price,
                    volatility=vol_20,
                    bb_upper=bb_upper,
                    bb_lower=bb_lower,
                    spike_return=latest_return,
                    reason=(
                        f"Spike {latest_return:+.2f}% detected but BB not confirmed "
                        f"(price={current_price:.2f}, BB=[{bb_lower:.2f}, {bb_upper:.2f}])"
                    ),
                )

        # ── 5. Compute targets ───────────────────────────────────────────────
        direction = raw_direction
        if direction == "LONG":
            stop_loss   = current_price * (1 - cfg.sl_pct)
            take_profit = current_price * (1 + cfg.tp_pct)
        else:
            stop_loss   = current_price * (1 + cfg.sl_pct)
            take_profit = current_price * (1 - cfg.tp_pct)

        risk   = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        rr     = reward / risk if risk > 0 else 0.0

        # Confidence: scales with spike magnitude
        confidence = min(abs(latest_return) / cfg.spike_threshold_pct, 2.0) / 2.0

        bb_note = " +BB✓" if cfg.require_bb_confirmation else ""
        return VMRSignal(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr_ratio=rr,
            confidence=confidence,
            spike_return=latest_return,
            volatility=vol_20,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            reason=f"Spike {latest_return:+.2f}%{bb_note} → {direction}",
        )

    # ── Position Sizing ──────────────────────────────────────────────────────

    def calculate_position(self, signal: VMRSignal, account_balance: float) -> Dict:
        """
        Calculate position size from a VMR signal.

        Uses fixed fractional risk: position_size_pct * account_balance.
        Leverage is applied on top of the risk allocation.

        Args:
            signal:          A VMRSignal with direction != "NONE".
            account_balance: Current account value in USD.

        Returns:
            dict with keys: size_usd, size_crypto, leverage, effective_notional,
                            risk_usd, account_risk_pct.
        """
        cfg = self.config
        risk_usd = account_balance * cfg.position_size_pct

        if signal.entry_price <= 0:
            logger.warning("calculate_position: entry_price is 0, skipping")
            return {}

        size_crypto = risk_usd / signal.entry_price
        leverage    = max(cfg.min_leverage, min(cfg.max_leverage, 5))

        return {
            "size_usd":          round(risk_usd, 2),
            "size_crypto":       round(size_crypto, 8),
            "leverage":          leverage,
            "effective_notional": round(size_crypto * leverage * signal.entry_price, 2),
            "risk_usd":          round(risk_usd, 2),
            "account_risk_pct":  cfg.position_size_pct,
        }

    # ── Exit Logic ───────────────────────────────────────────────────────────

    def check_exit(
        self,
        position: VMRPosition,
        current_price: float,
        elapsed_hours: float = 0.0,
    ) -> tuple[bool, str]:
        """
        Check whether an open position should be closed.

        Checks in priority order:
          1. SL hit
          2. TP hit
          3. Max hold time exceeded

        Args:
            position:      The open VMRPosition.
            current_price: Latest market price.
            elapsed_hours: Hours since entry (for max-hold check).

        Returns:
            (should_exit: bool, reason: str)
        """
        cfg = self.config

        if position.direction == "LONG":
            if current_price <= position.stop_loss:
                return True, "SL_HIT"
            if current_price >= position.take_profit:
                return True, "TP_HIT"
        else:  # SHORT
            if current_price >= position.stop_loss:
                return True, "SL_HIT"
            if current_price <= position.take_profit:
                return True, "TP_HIT"

        if elapsed_hours >= cfg.max_hold_hours:
            return True, "MAX_HOLD_EXPIRED"

        return False, ""

    def calculate_pnl(self, position: VMRPosition, exit_price: float) -> tuple[float, float]:
        """
        Calculate P&L for a closing position.

        Args:
            position:   The VMRPosition to close.
            exit_price: Price at exit.

        Returns:
            (pnl_pct, pnl_usd)
        """
        if position.direction == "LONG":
            pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
        else:
            pnl_pct = (position.entry_price - exit_price) / position.entry_price * 100

        pnl_usd = (pnl_pct / 100) * position.size_usd
        return round(pnl_pct, 4), round(pnl_usd, 4)

    # ── Backtest Engine ──────────────────────────────────────────────────────

    def run_backtest(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Run a bar-by-bar backtest on a candle DataFrame.

        This uses THE SAME signal logic as live/paper trading —
        there is no separate backtest strategy code.

        Args:
            df:     OHLCV DataFrame with 'open','high','low','close' columns.
                    Must be sorted ascending (oldest first).
            symbol: Instrument label.

        Returns:
            dict with keys: symbol, trades, wins, losses, win_rate,
                            total_pnl_usd, return_pct, max_dd_pct,
                            starting_balance, ending_balance,
                            profit_factor, avg_win_pct, avg_loss_pct,
                            total_bars, signals_detected.
        """
        cfg = self.config
        starting_balance = 1000.0
        balance          = starting_balance
        peak_balance     = starting_balance
        max_dd           = 0.0

        trades: List[Dict]    = []
        open_position: Optional[VMRPosition] = None
        signals_detected = 0

        min_bars = cfg.bb_window + 1

        for i in range(min_bars, len(df)):
            bar_df = df.iloc[: i + 1]
            current_price = float(df["close"].iloc[i])
            current_high  = float(df.get("high", df["close"]).iloc[i])
            current_low   = float(df.get("low", df["close"]).iloc[i])
            bar_time      = df.index[i] if hasattr(df.index, "dtype") else i

            # ── Check exit on open position ─────────────────────────────────
            if open_position is not None:
                hours_held = (
                    (bar_time - open_position.entry_time).total_seconds() / 3600
                    if hasattr(bar_time, "total_seconds")
                    else float(i)
                )

                # Use intrabar highs/lows for SL/TP check
                check_price = current_price
                if open_position.direction == "LONG":
                    if current_low <= open_position.stop_loss:
                        check_price = open_position.stop_loss
                    elif current_high >= open_position.take_profit:
                        check_price = open_position.take_profit
                else:
                    if current_high >= open_position.stop_loss:
                        check_price = open_position.stop_loss
                    elif current_low <= open_position.take_profit:
                        check_price = open_position.take_profit

                should_exit, exit_reason = self.check_exit(
                    open_position, check_price, hours_held
                )

                if should_exit:
                    pnl_pct, pnl_usd = self.calculate_pnl(open_position, check_price)
                    balance += pnl_usd

                    trades.append({
                        "symbol":      symbol,
                        "direction":   open_position.direction,
                        "entry_price": open_position.entry_price,
                        "exit_price":  check_price,
                        "exit_reason": exit_reason,
                        "pnl_pct":     pnl_pct,
                        "pnl_usd":     pnl_usd,
                        "size_usd":    open_position.size_usd,
                        "bar_index":   i,
                    })
                    open_position = None

                    # Drawdown tracking
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = (peak_balance - balance) / peak_balance * 100
                    max_dd = max(max_dd, dd)

            # ── Check for new signal ────────────────────────────────────────
            if open_position is None:
                signal = self.analyze(bar_df, symbol)

                if signal.direction != "NONE":
                    signals_detected += 1
                    pos_info = self.calculate_position(signal, balance)
                    if not pos_info:
                        continue

                    open_position = VMRPosition(
                        symbol=symbol,
                        direction=signal.direction,
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        size_usd=pos_info["size_usd"],
                        size_crypto=pos_info["size_crypto"],
                        leverage=pos_info["leverage"],
                        entry_time=datetime.now(),  # logical time only
                    )

        # ── Force-close any remaining position ──────────────────────────────
        if open_position is not None:
            last_price = float(df["close"].iloc[-1])
            pnl_pct, pnl_usd = self.calculate_pnl(open_position, last_price)
            balance += pnl_usd
            trades.append({
                "symbol":      symbol,
                "direction":   open_position.direction,
                "entry_price": open_position.entry_price,
                "exit_price":  last_price,
                "exit_reason": "END_OF_DATA",
                "pnl_pct":     pnl_pct,
                "pnl_usd":     pnl_usd,
                "size_usd":    open_position.size_usd,
                "bar_index":   len(df) - 1,
            })
            if balance > peak_balance:
                peak_balance = balance
            dd = (peak_balance - balance) / peak_balance * 100
            max_dd = max(max_dd, dd)

        # ── Stats ────────────────────────────────────────────────────────────
        wins   = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] <= 0]
        total_pnl = sum(t["pnl_usd"] for t in trades)

        avg_win_pct  = (sum(t["pnl_pct"] for t in wins)   / len(wins))   if wins   else 0.0
        avg_loss_pct = (sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0.0

        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss   = abs(sum(t["pnl_usd"] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        return {
            "symbol":           symbol,
            "total_bars":       len(df),
            "signals_detected": signals_detected,
            "trades":           len(trades),
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate":         round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
            "total_pnl_usd":    round(total_pnl, 4),
            "return_pct":       round((balance - starting_balance) / starting_balance * 100, 4),
            "max_dd_pct":       round(max_dd, 4),
            "starting_balance": starting_balance,
            "ending_balance":   round(balance, 4),
            "profit_factor":    round(profit_factor, 4),
            "avg_win_pct":      round(avg_win_pct, 4),
            "avg_loss_pct":     round(avg_loss_pct, 4),
            "trade_log":        trades,
            "config": {
                "spike_threshold_pct":     self.config.spike_threshold_pct,
                "bb_window":               self.config.bb_window,
                "bb_std_multiplier":       self.config.bb_std_multiplier,
                "require_bb_confirmation": self.config.require_bb_confirmation,
                "sl_pct":                  self.config.sl_pct,
                "tp_pct":                  self.config.tp_pct,
                "max_hold_hours":          self.config.max_hold_hours,
                "position_size_pct":       self.config.position_size_pct,
            },
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def format_signal(self, signal: VMRSignal) -> str:
        """Return a human-readable single-line summary of a signal."""
        if signal.direction == "NONE":
            return (
                f"[{signal.symbol}] NO SIGNAL | "
                f"return={signal.spike_return:+.2f}% | "
                f"vol={signal.volatility:.2f}% | "
                f"{signal.reason}"
            )
        return (
            f"[{signal.symbol}] {signal.direction} ✅ | "
            f"entry={signal.entry_price:.2f} "
            f"SL={signal.stop_loss:.2f} "
            f"TP={signal.take_profit:.2f} | "
            f"RR={signal.rr_ratio:.2f}x | "
            f"conf={signal.confidence:.0%} | "
            f"{signal.reason}"
        )
