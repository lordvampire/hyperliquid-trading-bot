"""Backtesting Module — Phase 2."""

from typing import List, Dict
from datetime import datetime, timedelta
from strategy_b import StrategyB
from exchange import fetch_candles


class BacktestEngine:
    """Run backtest of Strategy B on historical candles."""

    def __init__(self, start_balance: float = 1000):
        self.strategy = StrategyB()
        self.start_balance = start_balance
        self.current_balance = start_balance
        self.trades = []
        self.results = {}

    def run(self, symbol: str, days: int = 30, interval: str = "1h") -> Dict:
        """
        Run backtest over historical period.
        """
        # Fetch candles (returns list[dict], not dict)
        try:
            candle_data = fetch_candles(symbol, interval, limit=days * 24)
            if not isinstance(candle_data, list) or not candle_data:
                return {
                    "status": "error",
                    "message": f"failed to fetch candles for {symbol}",
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"fetch failed: {str(e)}",
            }

        # Simulate trades
        trades_executed = 0
        winning_trades = 0
        losing_trades = 0
        total_pnl = 0

        for i, candle in enumerate(candle_data):
            # Get signal
            signal = self.strategy.get_next_signal(symbol)

            if signal["signal"] != "HOLD":
                # Execute
                trade = self.strategy.execute_trade(symbol, signal)

                if trade.get("status") == "queued":
                    trades_executed += 1

                    # Simulate P&L (simplistic: random walk)
                    pnl = (hash(f"{symbol}{i}") % 100 - 50) / 100  # -0.5 to +0.5
                    total_pnl += pnl

                    if pnl > 0:
                        winning_trades += 1
                    else:
                        losing_trades += 1

                    self.trades.append({
                        "timestamp": candle.get("time", ""),
                        "signal": signal["signal"],
                        "pnl": pnl,
                        "confidence": signal.get("confidence", 0),
                    })

        # Calculate results
        win_rate = (winning_trades / trades_executed * 100) if trades_executed > 0 else 0
        final_balance = self.start_balance + total_pnl
        total_return = ((final_balance - self.start_balance) / self.start_balance) * 100

        self.results = {
            "symbol": symbol,
            "period": f"{days}d",
            "interval": interval,
            "trades_executed": trades_executed,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 6),
            "start_balance": self.start_balance,
            "final_balance": round(final_balance, 6),
            "total_return": round(total_return, 2),
            "trades": self.trades[:10],  # Last 10 trades
            "timestamp": datetime.now().isoformat(),
        }

        return self.results

    def get_results(self) -> Dict:
        """Get backtest results."""
        return self.results
