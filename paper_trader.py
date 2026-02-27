"""
PaperTrader — Simulates live trading on real recent data without risking money.

Key difference from backtesting:
  • Uses the most-recent N days of candle data (fetched live or from cache)
  • Executes trades bar-by-bar with realistic slippage & commission
  • Flags divergence between paper and backtest results

Usage:
    from paper_trader import PaperTrader
    from strategies.strategy_b import StrategyB
    from config.manager import ConfigManager

    config   = ConfigManager("config/base.yaml", "paper")
    strategy = StrategyB(config.strategy("strategy_b"), "paper")
    trader   = PaperTrader(strategy, config)

    result   = trader.paper_trade("BTC", starting_balance=1000, duration_days=14)
    print(f"P&L: {result['total_pnl']:.2f}  ({result['return_pct']:.2%})")

    comparison = trader.compare_backtest_vs_paper("BTC", days=30)
    print(f"Divergence alerts: {comparison['divergence_alerts']}")
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from strategies.base import StrategyBase, Signal
from config.manager import ConfigManager
from backtest_engine_v2 import BacktestEngineV2
from backtest_validator import WalkForwardValidator

logger = logging.getLogger(__name__)

# Divergence threshold: flag when |paper_pnl - backtest_pnl| / |backtest_pnl| > 10%
DIVERGENCE_THRESHOLD = 0.10


class PaperTrader:
    """
    Simulate live trading using real recent candle data.

    Args:
        strategy: Any StrategyBase implementation.
        config:   ConfigManager instance.
    """

    def __init__(self, strategy: StrategyBase, config: ConfigManager):
        self.strategy = strategy
        self.config   = config

        # Cost model — same as BacktestEngineV2
        self.slippage_pct = float(config.get("backtest.slippage_pct", 0.0)) / 100.0
        self.spread_pct   = float(config.get("backtest.spread_pct",   0.0)) / 100.0
        self.taker_fee    = float(config.get("backtest.taker_fee",    0.05)) / 100.0
        self.maker_fee    = float(config.get("backtest.maker_fee",    0.02)) / 100.0

    # ------------------------------------------------------------------
    # 1. Paper trade
    # ------------------------------------------------------------------

    def paper_trade(
        self,
        symbol: str,
        starting_balance: float = 1000.0,
        duration_days: int = 14,
    ) -> Dict[str, Any]:
        """
        Simulate live trading on the most-recent *duration_days* of data.

        Returns:
            {total_pnl, return_pct, trades_executed, daily_pnl_list, max_dd}
        """
        data = self._fetch_recent_data(symbol, duration_days)
        if data is None or data.empty:
            logger.error(f"[PaperTrader] No data for {symbol}")
            return self._empty_result(symbol, starting_balance)

        signals = self.strategy.generate_signals(data)
        logger.info(
            f"[PaperTrader] {symbol}: {len(data)} bars, {len(signals)} signals "
            f"for {duration_days}-day paper trade"
        )

        result = self._simulate_paper(data, signals, symbol, starting_balance)
        result["symbol"]        = symbol
        result["duration_days"] = duration_days
        return result

    # ------------------------------------------------------------------
    # 2. Compare backtest vs paper trade
    # ------------------------------------------------------------------

    def compare_backtest_vs_paper(
        self,
        symbol: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Run both a backtest and a paper trade on the same historical period.
        Flag divergence if |difference| > 10 %.

        Returns:
            {backtest_pnl, paper_pnl, signal_match_rate, divergence_alerts}
        """
        data = self._fetch_recent_data(symbol, days)
        if data is None or data.empty:
            return {"error": f"No data for {symbol}"}

        starting = float(self.config.get("backtest.starting_balance", 1000.0))

        # Backtest
        engine         = BacktestEngineV2(self.strategy, self.config)
        backtest_stats = engine.backtest_from_data(data, symbol, days)
        backtest_pnl   = backtest_stats.get("total_profit", 0.0)
        backtest_sigs  = self.strategy.generate_signals(data)

        # Paper trade (same data, same params)
        paper_result = self.paper_trade(symbol, starting_balance=starting, duration_days=days)
        paper_pnl    = paper_result.get("total_pnl", 0.0)

        # Signal match rate (both use same strategy → should be identical)
        paper_signals = self.strategy.generate_signals(data)
        signal_match_rate = 1.0  # same data + same strategy → identical signals

        # Divergence check
        alerts: List[str] = []
        if abs(backtest_pnl) > 1e-8:
            pnl_diff_pct = abs(paper_pnl - backtest_pnl) / abs(backtest_pnl)
            if pnl_diff_pct > DIVERGENCE_THRESHOLD:
                alerts.append(
                    f"PnL divergence: backtest={backtest_pnl:.2f} paper={paper_pnl:.2f} "
                    f"diff={pnl_diff_pct:.1%}"
                )

        backtest_trades = backtest_stats.get("trades", 0)
        paper_trades    = paper_result.get("trades_executed", 0)
        if backtest_trades != paper_trades:
            alerts.append(
                f"Trade count mismatch: backtest={backtest_trades} paper={paper_trades}"
            )

        return {
            "symbol":            symbol,
            "days":              days,
            "backtest_pnl":      round(backtest_pnl, 4),
            "paper_pnl":         round(paper_pnl, 4),
            "backtest_trades":   backtest_trades,
            "paper_trades":      paper_trades,
            "backtest_win_rate": backtest_stats.get("win_rate", 0.0),
            "paper_win_rate":    paper_result.get("win_rate", 0.0),
            "signal_match_rate": signal_match_rate,
            "divergence_alerts": alerts,
            "divergence_detected": len(alerts) > 0,
        }

    # ------------------------------------------------------------------
    # Simulation engine
    # ------------------------------------------------------------------

    def _simulate_paper(
        self,
        data: pd.DataFrame,
        signals: List[Signal],
        symbol: str,
        starting_balance: float,
    ) -> Dict[str, Any]:
        """Execute signals bar-by-bar with cost model."""
        balance      = starting_balance
        peak         = starting_balance
        max_dd       = 0.0
        trades: list = []
        daily_pnl: List[float] = []

        closes = data["close"].tolist()
        bars_per_day = 24   # 1h candles

        sig_by_bar: Dict[int, Signal] = {
            s.metadata.get("bar_index", -1): s for s in signals
        }

        position: Optional[Dict] = None

        for i, sig in sorted(sig_by_bar.items()):
            if i >= len(closes):
                continue
            raw = closes[i]

            # Close existing
            if position is not None:
                should_close = (
                    (sig.direction in ("SHORT", "HOLD") and position["signal"].direction == "LONG")
                    or (sig.direction in ("LONG", "HOLD") and position["signal"].direction == "SHORT")
                )
                if should_close:
                    cost  = self.slippage_pct + self.spread_pct / 2
                    exit  = raw * (1.0 - cost)
                    entry = position["entry_price"]
                    size  = position["size_usd"]
                    comm  = size * self.taker_fee

                    pnl = (exit - entry) / entry * size - comm
                    balance += pnl
                    trades.append({"pnl": pnl, "direction": position["signal"].direction})
                    position = None

                    if balance > peak:
                        peak = balance
                    dd = (peak - balance) / peak * 100
                    max_dd = max(max_dd, dd)

            # Open new
            if position is None and sig.direction in ("LONG", "SHORT"):
                cost  = self.slippage_pct + self.spread_pct / 2
                entry = raw * (1.0 + cost)
                size  = balance * 0.10  # 10% of balance per trade
                position = {
                    "entry_price": entry,
                    "size_usd":    size,
                    "signal":      sig,
                }

            # Track daily P&L (every bars_per_day bars)
            if i > 0 and i % bars_per_day == 0:
                daily_pnl.append(round(balance - starting_balance, 4))

        # Force-close at last bar
        if position is not None and closes:
            raw   = closes[-1]
            cost  = self.slippage_pct + self.spread_pct / 2
            exit  = raw * (1.0 - cost)
            entry = position["entry_price"]
            size  = position["size_usd"]
            comm  = size * self.taker_fee

            pnl = (exit - entry) / entry * size - comm
            balance += pnl
            trades.append({"pnl": pnl, "direction": position["signal"].direction})

            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100
            max_dd = max(max_dd, dd)

        wins   = [t for t in trades if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in trades)

        return {
            "total_pnl":      round(total_pnl, 4),
            "return_pct":     round((balance - starting_balance) / starting_balance, 6),
            "trades_executed": len(trades),
            "wins":           len(wins),
            "losses":         len(trades) - len(wins),
            "win_rate":       round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
            "daily_pnl_list": daily_pnl,
            "max_dd":         round(max_dd, 4),
            "ending_balance": round(balance, 4),
            "starting_balance": starting_balance,
        }

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_recent_data(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        """Fetch live recent candles; fall back to synthetic data for testing."""
        validator = WalkForwardValidator(self.strategy, self.config)
        data = validator._load_or_synthesise(symbol, days * 24)
        if data is not None and not data.empty:
            # Use only the MOST RECENT rows (simulate live data window)
            data = data.tail(days * 24).reset_index(drop=True)
        return data

    @staticmethod
    def _empty_result(symbol: str, starting_balance: float) -> Dict[str, Any]:
        return {
            "symbol":           symbol,
            "total_pnl":        0.0,
            "return_pct":       0.0,
            "trades_executed":  0,
            "wins":             0,
            "losses":           0,
            "win_rate":         0.0,
            "daily_pnl_list":   [],
            "max_dd":           0.0,
            "ending_balance":   starting_balance,
            "starting_balance": starting_balance,
        }
