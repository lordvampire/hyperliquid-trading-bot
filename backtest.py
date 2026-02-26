"""Backtesting Module — Phase 2 REAL (Historical Candles + Realistic P&L)."""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from strategy_b import StrategyB
from exchange import fetch_candles

# Trading fees
ENTRY_FEE = 0.0002  # 0.02% taker fee
EXIT_FEE = 0.0006   # 0.06% taker fee
FUNDING_MULTIPLIER = 8  # Assume 8 funding periods per day (3h each)


class BacktestEngine:
    """
    Run backtest of Strategy B on REAL historical candles.
    Realistic P&L: entry fee, exit fee, funding costs.
    """

    def __init__(self, start_balance: float = 1000):
        self.strategy = StrategyB()
        self.start_balance = start_balance
        self.current_balance = start_balance
        self.trades = []
        self.results = {}

    def _calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        side: str,  # "long" or "short"
        size: float,
        funding_paid: float = 0.0,
    ) -> Tuple[float, float]:
        """
        Calculate realistic P&L for a trade.
        
        Returns: (pnl_dollars, pnl_pct)
        """
        # Entry cost (always negative)
        entry_cost = entry_price * size * ENTRY_FEE
        
        # Exit cost (always negative)
        exit_cost = exit_price * size * EXIT_FEE
        
        # Price movement P&L
        if side == "long":
            price_pnl = size * (exit_price - entry_price)
        else:  # short
            price_pnl = size * (entry_price - exit_price)
        
        # Total P&L (in notional dollars, assuming 1x leverage for simplicity)
        total_pnl = price_pnl - entry_cost - exit_cost - funding_paid
        
        # P&L percentage
        position_notional = entry_price * size
        pnl_pct = (total_pnl / position_notional * 100) if position_notional > 0 else 0
        
        return total_pnl, pnl_pct

    def run(self, symbol: str, days: int = 30, interval: str = "1h") -> Dict:
        """
        Run backtest over historical period using REAL candles.
        
        Args:
            symbol: Trading pair (e.g., "BTC")
            days: Number of days to backtest
            interval: Candle interval (e.g., "1h")
        
        Returns: backtest results
        """
        # Fetch REAL historical candles
        try:
            candle_data = fetch_candles(symbol, interval, limit=days * 24)
            if not isinstance(candle_data, list) or not candle_data:
                return {
                    "status": "error",
                    "message": f"failed to fetch candles for {symbol}",
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"fetch failed: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            }

        # Sort candles by time (oldest first)
        candle_data.sort(key=lambda x: x.get("time", 0))

        # Simulate trading
        trades_executed = 0
        winning_trades = 0
        losing_trades = 0
        total_pnl = 0.0
        open_position: Optional[Dict] = None

        for i, candle in enumerate(candle_data):
            candle_time = candle.get("time", 0)
            open_price = float(candle.get("open", 0))
            close_price = float(candle.get("close", 0))
            high_price = float(candle.get("high", 0))
            low_price = float(candle.get("low", 0))

            # Skip invalid candles
            if not all([open_price, close_price, high_price, low_price]):
                continue

            # Get trade signal
            signal = self.strategy.get_next_signal(symbol)

            # Exit logic: check if open position should be closed
            if open_position:
                exit_triggered = False
                exit_price = close_price
                exit_reason = "signal_reversal"

                # Exit if sentiment reverses
                if signal["signal"] != open_position["signal"]:
                    exit_triggered = True

                # Exit if stop loss hit
                if open_position["side"] == "long" and low_price < open_position["stop_loss"]:
                    exit_triggered = True
                    exit_price = open_position["stop_loss"]
                    exit_reason = "stop_loss"

                # Exit if take profit hit
                if open_position["side"] == "long" and high_price > open_position["take_profit"]:
                    exit_triggered = True
                    exit_price = open_position["take_profit"]
                    exit_reason = "take_profit"

                # Exit if short stop loss
                if open_position["side"] == "short" and high_price > open_position["stop_loss"]:
                    exit_triggered = True
                    exit_price = open_position["stop_loss"]
                    exit_reason = "stop_loss"

                # Exit if short take profit
                if open_position["side"] == "short" and low_price < open_position["take_profit"]:
                    exit_triggered = True
                    exit_price = open_position["take_profit"]
                    exit_reason = "take_profit"

                if exit_triggered:
                    # Calculate P&L with fees
                    pnl, pnl_pct = self._calculate_pnl(
                        entry_price=open_position["entry_price"],
                        exit_price=exit_price,
                        side=open_position["side"],
                        size=open_position["size"],
                        funding_paid=open_position.get("funding_paid", 0),
                    )

                    total_pnl += pnl
                    self.current_balance += pnl

                    self.trades.append({
                        "timestamp": datetime.fromtimestamp(candle_time / 1000).isoformat() if candle_time > 0 else "unknown",
                        "symbol": symbol,
                        "side": open_position["side"],
                        "entry_price": open_position["entry_price"],
                        "exit_price": exit_price,
                        "size": open_position["size"],
                        "pnl": round(pnl, 6),
                        "pnl_pct": round(pnl_pct, 2),
                        "signal": open_position["signal"],
                        "confidence": open_position["confidence"],
                        "exit_reason": exit_reason,
                    })

                    if pnl > 0:
                        winning_trades += 1
                    else:
                        losing_trades += 1

                    trades_executed += 1
                    open_position = None

            # Entry logic: open new position if signal is strong
            if not open_position and signal["signal"] != "HOLD":
                confidence = signal.get("confidence", 0)
                if confidence > 0.3:  # Only enter if confidence high enough
                    # Position sizing: risk 2% of balance per trade
                    position_size = (self.current_balance * 0.02) / open_price
                    
                    # Set stop loss and take profit (5% each way)
                    sl_distance = open_price * 0.05
                    tp_distance = open_price * 0.05

                    if signal["signal"] == "BUY":
                        stop_loss = open_price - sl_distance
                        take_profit = open_price + tp_distance
                    else:  # SELL
                        stop_loss = open_price + sl_distance
                        take_profit = open_price - tp_distance

                    # Estimate funding paid (8 periods of funding * current rate)
                    funding_rate = signal.get("funding", {}).get("funding_rate", 0)
                    funding_paid = position_size * open_price * funding_rate * FUNDING_MULTIPLIER

                    open_position = {
                        "entry_price": open_price,
                        "side": "long" if signal["signal"] == "BUY" else "short",
                        "size": position_size,
                        "signal": signal["signal"],
                        "confidence": confidence,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "funding_paid": funding_paid,
                    }

        # Close any remaining open position at last close price
        if open_position and candle_data:
            last_close = float(candle_data[-1].get("close", open_position["entry_price"]))
            pnl, pnl_pct = self._calculate_pnl(
                entry_price=open_position["entry_price"],
                exit_price=last_close,
                side=open_position["side"],
                size=open_position["size"],
                funding_paid=open_position.get("funding_paid", 0),
            )

            total_pnl += pnl
            self.current_balance += pnl

            self.trades.append({
                "timestamp": datetime.fromtimestamp(candle_data[-1].get("time", 0) / 1000).isoformat(),
                "symbol": symbol,
                "side": open_position["side"],
                "entry_price": open_position["entry_price"],
                "exit_price": last_close,
                "size": open_position["size"],
                "pnl": round(pnl, 6),
                "pnl_pct": round(pnl_pct, 2),
                "signal": open_position["signal"],
                "confidence": open_position["confidence"],
                "exit_reason": "backtest_end",
            })

            if pnl > 0:
                winning_trades += 1
            else:
                losing_trades += 1

            trades_executed += 1

        # Calculate final results
        win_rate = (winning_trades / trades_executed * 100) if trades_executed > 0 else 0
        total_return = ((self.current_balance - self.start_balance) / self.start_balance) * 100

        self.results = {
            "status": "success",
            "symbol": symbol,
            "period": f"{days}d",
            "interval": interval,
            "trades_executed": trades_executed,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 6),
            "start_balance": self.start_balance,
            "final_balance": round(self.current_balance, 6),
            "total_return": round(total_return, 2),
            "candles_processed": len(candle_data),
            "trades": self.trades[-20:],  # Last 20 trades for detail
            "fees_included": {
                "entry_fee_pct": ENTRY_FEE * 100,
                "exit_fee_pct": EXIT_FEE * 100,
                "funding_periods_per_day": FUNDING_MULTIPLIER,
            },
            "timestamp": datetime.now().isoformat(),
        }

        return self.results

    def get_results(self) -> Dict:
        """Get backtest results."""
        return self.results
