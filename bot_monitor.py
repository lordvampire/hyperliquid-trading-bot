#!/usr/bin/env python3
"""
Live Bot Monitor - Shows real-time analysis in terminal
Runs alongside the bot to display what's happening
"""

import asyncio
import logging
from datetime import datetime
from exchange import fetch_balance, fetch_candles
from manager import RiskManager
from config import cfg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LiveMonitor:
    def __init__(self):
        self.risk_manager = RiskManager(
            max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
            max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
            default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
            db_path=cfg.DB_PATH,
        )
        self.last_signals = {}
    
    async def analyze_symbol(self, symbol: str):
        """Analyze and display signal for symbol"""
        try:
            candles_data = fetch_candles(symbol, "1h", 100)
            candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
            
            if not candles or len(candles) < 20:
                logger.warning(f"⚠️ Insufficient data for {symbol}")
                return None
            
            # Extract closes
            closes = []
            for c in candles:
                if isinstance(c, dict):
                    closes.append(float(c.get("c", c.get("close", 0))))
                else:
                    closes.append(float(c[4]))
            
            price = closes[-1]
            
            # Simple momentum signal
            change_5h = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0
            change_1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0
            
            # Volatility (std dev of last 10 closes)
            import statistics
            recent_closes = closes[-10:]
            volatility = statistics.stdev(recent_closes) / statistics.mean(recent_closes) * 100
            
            # Decision
            if change_5h > 2:
                signal = "🚀 BUY"
                confidence = "HIGH" if change_1h > 0 else "MEDIUM"
            elif change_5h < -2:
                signal = "🔻 SELL"
                confidence = "HIGH" if change_1h < 0 else "MEDIUM"
            else:
                signal = "⏸️ HOLD"
                confidence = "NEUTRAL"
            
            result = {
                "symbol": symbol,
                "price": price,
                "change_5h": change_5h,
                "change_1h": change_1h,
                "volatility": volatility,
                "signal": signal,
                "confidence": confidence
            }
            
            self.last_signals[symbol] = result
            return result
            
        except Exception as e:
            logger.error(f"❌ Analysis failed for {symbol}: {e}")
            return None
    
    async def run_monitor(self, interval: int = 60):
        """Run continuous monitoring"""
        symbols = ["BTC", "ETH", "SOL"]
        iteration = 0
        
        logger.info("=" * 70)
        logger.info("🤖 LIVE BOT MONITOR - Real-time Signal Analysis")
        logger.info("=" * 70)
        logger.info("Monitoring symbols: " + ", ".join(symbols))
        logger.info(f"Update interval: every {interval} seconds")
        logger.info("=" * 70 + "\n")
        
        while True:
            try:
                iteration += 1
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                logger.info(f"\n[Update #{iteration}] {timestamp}")
                logger.info("-" * 70)
                
                # Get balance
                await self.risk_manager.load_state()
                bal = fetch_balance()
                balance = float(bal.get("account_value", 0)) if "error" not in bal else 0
                
                # Analyze all symbols
                for symbol in symbols:
                    result = await self.analyze_symbol(symbol)
                    if result:
                        msg = (
                            f"  {result['symbol']:<6} "
                            f"${result['price']:>10,.0f} │ "
                            f"5h: {result['change_5h']:>+6.2f}% │ "
                            f"1h: {result['change_1h']:>+6.2f}% │ "
                            f"Vol: {result['volatility']:>5.2f}% │ "
                            f"{result['signal']:<12} [{result['confidence']}]"
                        )
                        logger.info(msg)
                
                # Account status
                logger.info("-" * 70)
                logger.info(f"💰 Balance: ${balance:,.2f}")
                
                risk = self.risk_manager.status()
                logger.info(f"📊 Daily P&L: ${risk['daily_pnl']:,.2f} ({risk['daily_dd_pct']:.2f}%)")
                logger.info(f"🛡️ Can Trade: {'✅ Yes' if risk['can_trade'] else '❌ No'}")
                
                # Wait for next update
                logger.info(f"\n⏳ Next update in {interval}s (Ctrl+C to stop)")
                await asyncio.sleep(interval)
                
            except KeyboardInterrupt:
                logger.info("\n🛑 Monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)

async def main():
    monitor = LiveMonitor()
    await monitor.run_monitor(interval=60)  # Update every 60 seconds

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nGoodbye!")
