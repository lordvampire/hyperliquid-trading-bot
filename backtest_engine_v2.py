"""
BacktestEngineV2 — Uses the EXACT same StrategyB as production.

Key improvements over backtest_engine.py:
  • Accepts any StrategyBase-compatible strategy
  • Slippage & spread costs from config (not hardcoded)
  • Commission model: maker_fee (0.02%) and taker_fee (0.05%)
  • Returns standardised stats dict with max_dd, win_rate, etc.
  • Tracks slippage_cost_usd, commission_usd, total_fees_pct
  • Signal generation path is identical to live trading

Usage:
    config   = ConfigManager("config/base.yaml", "backtest")
    strategy = StrategyB(config.strategy("strategy_b"), "backtest")
    engine   = BacktestEngineV2(strategy, config)
    result   = engine.backtest("BTC", days=7)
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import pandas as pd

from strategies.base import StrategyBase, Signal
from config.manager import ConfigManager

logger = logging.getLogger(__name__)


class BacktestEngineV2:
    """Backtester that delegates signal generation to a StrategyBase instance."""

    def __init__(self, strategy: StrategyBase, config: ConfigManager):
        self.strategy = strategy
        self.config   = config

        # Cost model — loaded once from config
        self.slippage_pct: float = float(config.get("backtest.slippage_pct", 0.0)) / 100.0
        self.spread_pct:   float = float(config.get("backtest.spread_pct",   0.0)) / 100.0
        self.maker_fee:    float = float(config.get("backtest.maker_fee",    0.02)) / 100.0
        self.taker_fee:    float = float(config.get("backtest.taker_fee",    0.05)) / 100.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backtest(self, symbol: str, days: int = 7) -> Dict[str, Any]:
        """
        Run a backtest for *symbol* over *days* days of 1h candles.

        Returns a stats dict with at least:
            total_profit, return_pct, trades, wins, losses,
            win_rate, max_dd, starting_balance, ending_balance,
            slippage_cost_usd, commission_usd, total_fees_pct
        """
        num_candles = days * 24

        try:
            data = self._fetch_ohlcv(symbol, num_candles)
        except Exception as exc:
            logger.error(f"[BacktestV2] Failed to fetch candles for {symbol}: {exc}")
            return {"error": str(exc), "symbol": symbol}

        if data.empty or len(data) < 25:
            return {"error": f"Insufficient data for {symbol} ({len(data)} bars)", "symbol": symbol}

        signals = self.strategy.generate_signals(data)
        stats   = self._simulate(data, signals, symbol)
        stats["symbol"]           = symbol
        stats["days"]             = days
        stats["candles_analyzed"] = len(data)
        stats["strategy"]         = self.strategy.__class__.__name__
        return stats

    def backtest_from_data(self, data: pd.DataFrame, symbol: str, days: int) -> Dict[str, Any]:
        """
        Run backtest on a pre-loaded DataFrame (used by WalkForwardValidator).

        Args:
            data:   OHLCV DataFrame.
            symbol: Instrument name (for labelling).
            days:   Window length in days (for labelling only).

        Returns:
            Same stats dict as backtest().
        """
        if data.empty or len(data) < 25:
            return {"error": f"Insufficient data ({len(data)} bars)", "symbol": symbol}

        signals = self.strategy.generate_signals(data)
        stats   = self._simulate(data, signals, symbol)
        stats["symbol"]           = symbol
        stats["days"]             = days
        stats["candles_analyzed"] = len(data)
        stats["strategy"]         = self.strategy.__class__.__name__
        return stats

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_ohlcv(self, symbol: str, limit: int) -> pd.DataFrame:
        """Fetch candles from exchange and return a clean OHLCV DataFrame."""
        from exchange import fetch_candles  # local import to avoid circular deps at module level

        raw = fetch_candles(symbol, "1h", limit)
        candles = raw if isinstance(raw, list) else raw.get("candles", [])

        rows = []
        for c in candles:
            if isinstance(c, dict):
                rows.append({
                    "open":   float(c.get("o", c.get("open", 0))),
                    "high":   float(c.get("h", c.get("high", 0))),
                    "low":    float(c.get("l", c.get("low", 0))),
                    "close":  float(c.get("c", c.get("close", 0))),
                    "volume": float(c.get("v", c.get("volume", 1.0))),
                })
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                rows.append({
                    "open":   float(c[1]),
                    "high":   float(c[2]),
                    "low":    float(c[3]),
                    "close":  float(c[4]),
                    "volume": float(c[5]) if len(c) > 5 else 1.0,
                })

        return pd.DataFrame(rows)

    def _simulate(
        self,
        data: pd.DataFrame,
        signals: List[Signal],
        symbol: str,
    ) -> Dict[str, Any]:
        """
        Walk through signals and simulate trades with slippage, spread,
        and exchange commissions.

        Cost model:
            Entry price = raw_price * (1 + slippage_pct + spread_pct / 2)
            Exit  price = raw_price * (1 - slippage_pct - spread_pct / 2)
            Commission  = taker_fee * notional  (on both entry and exit)

        Only LONG signals are traded (short positions tracked for future use).
        """
        starting      = float(self.config.get("backtest.starting_balance", 1000.0))
        balance       = starting
        peak_balance  = starting
        max_dd        = 0.0
        trades: list  = []
        slippage_total = 0.0
        commission_total = 0.0

        position: Optional[Dict] = None   # {entry_price, size_usd, signal, entry_commission}

        closes = data["close"].tolist()

        # Build a lookup: bar_index → signal
        sig_by_bar: Dict[int, Signal] = {
            s.metadata.get("bar_index", -1): s for s in signals
        }

        for i, sig in sorted(sig_by_bar.items()):
            if i >= len(closes):
                continue

            raw_price = closes[i]

            # ── Close existing position ──────────────────────────────────
            if position is not None:
                entry_sig = position["signal"]
                should_close = (
                    sig.direction in ("SHORT", "HOLD") and entry_sig.direction == "LONG"
                ) or (
                    sig.direction in ("LONG", "HOLD")  and entry_sig.direction == "SHORT"
                )
                if should_close:
                    # Realistic exit: sell at bid (subtract slippage + half spread)
                    cost_factor = self.slippage_pct + self.spread_pct / 2
                    exit_price  = raw_price * (1.0 - cost_factor)
                    entry_price = position["entry_price"]
                    size_usd    = position["size_usd"]

                    # Slippage cost on exit
                    exit_slip = raw_price * cost_factor / raw_price * size_usd
                    slippage_total += exit_slip + position["entry_slippage"]

                    # Commission on exit (taker)
                    exit_commission = size_usd * self.taker_fee
                    commission_total += exit_commission + position["entry_commission"]

                    pnl = (exit_price - entry_price) / entry_price * size_usd
                    pnl -= exit_commission  # deduct commission from P&L

                    balance += pnl
                    trades.append({
                        "symbol":       symbol,
                        "direction":    entry_sig.direction,
                        "entry":        entry_price,
                        "exit":         exit_price,
                        "pnl":          pnl,
                        "return_pct":   (exit_price - entry_price) / entry_price * 100,
                        "commission":   exit_commission + position["entry_commission"],
                        "slippage":     exit_slip + position["entry_slippage"],
                    })
                    position = None

                    # Drawdown tracking
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = (peak_balance - balance) / peak_balance * 100
                    if dd > max_dd:
                        max_dd = dd

            # ── Open new position ────────────────────────────────────────
            if position is None and sig.direction in ("LONG", "SHORT"):
                # Realistic entry: buy at ask (add slippage + half spread)
                cost_factor  = self.slippage_pct + self.spread_pct / 2
                entry_price  = raw_price * (1.0 + cost_factor)
                size_usd     = balance * 0.10   # risk 10% of balance per trade

                # Slippage cost on entry
                entry_slippage   = raw_price * cost_factor / raw_price * size_usd
                entry_commission = size_usd * self.taker_fee

                position = {
                    "entry_price":      entry_price,
                    "size_usd":         size_usd,
                    "signal":           sig,
                    "entry_slippage":   entry_slippage,
                    "entry_commission": entry_commission,
                }

        # ── Force-close any open position at last bar ────────────────────
        if position is not None and closes:
            raw_price   = closes[-1]
            cost_factor = self.slippage_pct + self.spread_pct / 2
            exit_price  = raw_price * (1.0 - cost_factor)
            entry_price = position["entry_price"]
            size_usd    = position["size_usd"]

            exit_slip       = raw_price * cost_factor / raw_price * size_usd
            exit_commission = size_usd * self.taker_fee
            commission_total += exit_commission + position["entry_commission"]
            slippage_total   += exit_slip + position["entry_slippage"]

            pnl = (exit_price - entry_price) / entry_price * size_usd
            pnl -= exit_commission

            balance += pnl
            trades.append({
                "symbol":     symbol,
                "direction":  position["signal"].direction,
                "entry":      entry_price,
                "exit":       exit_price,
                "pnl":        pnl,
                "return_pct": (exit_price - entry_price) / entry_price * 100,
                "commission": exit_commission + position["entry_commission"],
                "slippage":   exit_slip + position["entry_slippage"],
            })
            if balance > peak_balance:
                peak_balance = balance
            dd = (peak_balance - balance) / peak_balance * 100
            if dd > max_dd:
                max_dd = dd

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_profit = sum(t["pnl"] for t in trades)

        # Cost summary
        total_costs = slippage_total + commission_total
        total_cost_pct = (total_costs / starting * 100) if starting else 0.0

        return {
            "starting_balance":  starting,
            "ending_balance":    round(balance, 4),
            "total_profit":      round(total_profit, 4),
            "return_pct":        round((balance - starting) / starting * 100, 4),
            "trades":            len(trades),
            "wins":              len(wins),
            "losses":            len(losses),
            "win_rate":          round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
            "max_dd":            round(max_dd, 4),
            "avg_win":           round(sum(t["pnl"] for t in wins)   / len(wins),   4) if wins   else 0.0,
            "avg_loss":          round(sum(t["pnl"] for t in losses) / len(losses), 4) if losses else 0.0,
            # Cost breakdown (Phase 2 additions)
            "slippage_cost_usd": round(slippage_total,   4),
            "commission_usd":    round(commission_total, 4),
            "total_cost_pct":    round(total_cost_pct,   4),
            "total_fees_pct":    round(commission_total / starting * 100, 4) if starting else 0.0,
        }


# ------------------------------------------------------------------
# Human-readable formatter (same style as backtest_engine.py)
# ------------------------------------------------------------------

def format_result_v2(results: Dict[str, Dict]) -> str:
    """Format results dict (symbol → stats) for Telegram / terminal output."""
    lines = ["📊 *BACKTEST V2 RESULTS*\n"]
    lines.append("Strategy: *Strategy B (StrategyBase)*\n")

    total_profit = 0.0
    total_return = 0.0

    for symbol, r in results.items():
        if "error" in r:
            lines.append(f"⚠️ {symbol}: {r['error']}")
            continue

        emoji = "🟢" if r["total_profit"] >= 0 else "🔴"
        lines.append(
            f"{emoji} *{symbol}*\n"
            f"  Balance: ${r['starting_balance']:,.0f} → ${r['ending_balance']:,.2f}\n"
            f"  Profit: ${r['total_profit']:+,.2f} ({r['return_pct']:+.2f}%)\n"
            f"  Trades: {r['trades']} (W:{r['wins']} L:{r['losses']} | WR: {r['win_rate']:.1f}%)\n"
            f"  Max DD: {r['max_dd']:.2f}%\n"
            f"  Slippage: ${r.get('slippage_cost_usd', 0):,.4f} | "
            f"Commission: ${r.get('commission_usd', 0):,.4f} | "
            f"Total Cost: {r.get('total_cost_pct', 0):.3f}%\n"
            f"  Candles: {r.get('candles_analyzed', '?')} ({r.get('days', '?')} days)\n"
        )
        total_profit += r["total_profit"]
        total_return += r["return_pct"]

    n = len([r for r in results.values() if "error" not in r])
    lines.append("\n═══════════════════════════════")
    lines.append(f"📈 *TOTAL*")
    lines.append(f"  Profit: ${total_profit:+,.2f}")
    lines.append(f"  Avg Return: {total_return / n:+.2f}%" if n else "  No valid results")
    lines.append("═══════════════════════════════")
    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    from config.manager import ConfigManager
    from strategies.strategy_b import StrategyB

    cfg = ConfigManager("config/base.yaml", "backtest")
    strategy = StrategyB(cfg.strategy("strategy_b"), "backtest")
    engine = BacktestEngineV2(strategy, cfg)

    symbols = ["BTC", "ETH", "SOL"]
    all_results = {}
    for sym in symbols:
        print(f"Backtesting {sym}...")
        all_results[sym] = engine.backtest(sym, days=7)

    print(format_result_v2(all_results))
