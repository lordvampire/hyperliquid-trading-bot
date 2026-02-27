#!/usr/bin/env python3
"""
Backtesting Engine - Test trading strategies on historical data
Simulates trades over past N days with real candle data
"""

import asyncio
import logging
from datetime import datetime, timedelta
from exchange import fetch_candles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BacktestResult:
    def __init__(self):
        self.trades = []
        self.starting_balance = 1000.0
        self.ending_balance = 1000.0
        self.total_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.win_rate = 0.0
        self.total_return_pct = 0.0
        self.max_drawdown_pct = 0.0
        self.largest_win = 0.0
        self.largest_loss = 0.0

class BacktestEngine:
    """Simple backtesting engine using historical candle data"""
    
    def __init__(self, starting_balance: float = 1000.0):
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.trades = []
        self.max_balance = starting_balance
        self.max_drawdown_pct = 0.0
    
    def simple_signal(self, closes: list) -> str:
        """Generate simple trading signal (BUY/SELL/HOLD)"""
        if len(closes) < 5:
            return "HOLD"
        
        # Simple momentum: if price went up 1%+ in last 5 candles = BUY
        change_5 = (closes[-1] - closes[-5]) / closes[-5] * 100
        change_1 = (closes[-1] - closes[-2]) / closes[-2] * 100
        
        if change_5 > 1 and change_1 > 0:
            return "BUY"
        elif change_5 < -1 and change_1 < 0:
            return "SELL"
        else:
            return "HOLD"
    
    def backtest_symbol(self, symbol: str, days: int = 7) -> dict:
        """Backtest a symbol over N days"""
        try:
            # Fetch historical candles (1h, last 7 days = 168 candles)
            num_candles = days * 24
            candles_data = fetch_candles(symbol, "1h", num_candles)
            candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
            
            if not candles or len(candles) < 24:
                return {"error": f"Insufficient data for {symbol}"}
            
            # Extract OHLCV
            prices = []
            opens = []
            closes = []
            highs = []
            lows = []
            
            for c in candles:
                if isinstance(c, dict):
                    opens.append(float(c.get("o", c.get("open", 0))))
                    closes.append(float(c.get("c", c.get("close", 0))))
                    highs.append(float(c.get("h", c.get("high", 0))))
                    lows.append(float(c.get("l", c.get("low", 0))))
                else:  # list format
                    opens.append(float(c[1]))
                    closes.append(float(c[4]))
                    highs.append(float(c[2]))
                    lows.append(float(c[3]))
            
            # Run backtest
            position = None  # None, "LONG", "SHORT"
            position_price = 0
            balance = self.starting_balance
            balance_history = [balance]
            
            for i in range(20, len(closes)):  # Start after enough history
                recent_closes = closes[max(0, i-20):i+1]
                signal = self.simple_signal(recent_closes)
                current_price = closes[i]
                
                # Open position
                if signal == "BUY" and position is None:
                    # Buy 10% of balance
                    position = "LONG"
                    position_price = current_price
                    balance_used = balance * 0.1
                
                # Close position
                elif signal == "SELL" and position == "LONG":
                    pnl = (current_price - position_price) / position_price * (balance * 0.1)
                    balance += pnl
                    
                    self.trades.append({
                        "symbol": symbol,
                        "entry": position_price,
                        "exit": current_price,
                        "pnl": pnl,
                        "return_pct": (current_price - position_price) / position_price * 100,
                        "signal": signal
                    })
                    
                    position = None
                
                balance_history.append(balance)
                
                # Track max drawdown
                if balance > self.max_balance:
                    self.max_balance = balance
                drawdown = (self.max_balance - balance) / self.max_balance * 100
                if drawdown > self.max_drawdown_pct:
                    self.max_drawdown_pct = drawdown
            
            # Close any open position
            if position == "LONG":
                final_price = closes[-1]
                pnl = (final_price - position_price) / position_price * (balance * 0.1)
                balance += pnl
                self.trades.append({
                    "symbol": symbol,
                    "entry": position_price,
                    "exit": final_price,
                    "pnl": pnl,
                    "return_pct": (final_price - position_price) / position_price * 100,
                    "signal": "CLOSE"
                })
            
            # Calculate stats
            win_count = sum(1 for t in self.trades if t["pnl"] > 0)
            loss_count = sum(1 for t in self.trades if t["pnl"] < 0)
            total_profit = sum(t["pnl"] for t in self.trades)
            
            return {
                "symbol": symbol,
                "days": days,
                "candles_analyzed": len(closes),
                "starting_balance": self.starting_balance,
                "ending_balance": balance,
                "total_profit": total_profit,
                "total_return_pct": (balance - self.starting_balance) / self.starting_balance * 100,
                "trades": len(self.trades),
                "wins": win_count,
                "losses": loss_count,
                "win_rate_pct": (win_count / len(self.trades) * 100) if self.trades else 0,
                "max_drawdown_pct": self.max_drawdown_pct,
                "avg_win": sum(t["pnl"] for t in self.trades if t["pnl"] > 0) / win_count if win_count > 0 else 0,
                "avg_loss": sum(t["pnl"] for t in self.trades if t["pnl"] < 0) / loss_count if loss_count > 0 else 0,
            }
            
        except Exception as e:
            logger.error(f"Backtest failed for {symbol}: {e}")
            return {"error": str(e)}

async def run_backtest_multi(symbols: list, days: int = 7) -> dict:
    """Run backtest on multiple symbols"""
    engine = BacktestEngine()
    results = {}
    
    for symbol in symbols:
        logger.info(f"Backtesting {symbol} over {days} days...")
        result = engine.backtest_symbol(symbol, days)
        results[symbol] = result
    
    return results

def format_backtest_result(results: dict) -> str:
    """Format backtest results for display"""
    lines = ["📊 *BACKTEST RESULTS*\n"]
    
    total_profit = 0
    total_return = 0
    total_trades = 0
    
    for symbol, result in results.items():
        if "error" in result:
            lines.append(f"⚠️ {symbol}: {result['error']}")
            continue
        
        emoji = "🟢" if result["total_profit"] >= 0 else "🔴"
        lines.append(
            f"{emoji} *{symbol}*\n"
            f"  Balance: ${result['starting_balance']:,.0f} → ${result['ending_balance']:,.2f}\n"
            f"  Profit: ${result['total_profit']:+,.2f} ({result['total_return_pct']:+.2f}%)\n"
            f"  Trades: {result['trades']} (W:{result['wins']} L:{result['losses']} | WR: {result['win_rate_pct']:.1f}%)\n"
            f"  Max DD: {result['max_drawdown_pct']:.2f}%\n"
            f"  Analyzed: {result['candles_analyzed']} candles ({result['days']} days)\n"
        )
        
        total_profit += result["total_profit"]
        total_return += result["total_return_pct"]
        total_trades += result["trades"]
    
    # Summary
    lines.append("\n═══════════════════════════════")
    lines.append(f"📈 *TOTAL*")
    lines.append(f"  Profit: ${total_profit:+,.2f}")
    lines.append(f"  Avg Return: {total_return / len(results):+.2f}%")
    lines.append(f"  Total Trades: {total_trades}")
    lines.append("═══════════════════════════════")
    
    return "\n".join(lines)

if __name__ == "__main__":
    # Test
    results = asyncio.run(run_backtest_multi(["BTC", "ETH", "SOL"], days=7))
    print(format_backtest_result(results))
