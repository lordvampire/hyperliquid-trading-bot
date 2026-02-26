#!/usr/bin/env python3
"""
Testnet Runner — Phase 2 Validation
Runs the trading bot on testnet for N hours, logs all trades to SQLite.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict
import aiosqlite
from config import cfg
from strategy_b import StrategyB
from funding import FundingRateAnalyzer
from sentiment import SentimentAnalyzer
from exchange import get_info, fetch_candles


# Test trades table schema
TEST_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal TEXT NOT NULL,
    sentiment_score REAL,
    funding_rate REAL,
    sentiment_confidence REAL,
    funding_strength REAL,
    combined_confidence REAL,
    action TEXT NOT NULL,
    reason TEXT,
    side TEXT,
    entry_price REAL,
    exit_price REAL,
    size REAL,
    pnl REAL,
    pnl_pct REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_run_summary (
    test_run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_minutes INTEGER,
    total_signals INTEGER DEFAULT 0,
    trades_executed INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    win_rate REAL,
    notes TEXT
);
"""


class TestnetRunner:
    """Run Phase 2 strategy on testnet with detailed logging."""

    def __init__(self, symbols: List[str] = None, duration_minutes: int = 720):
        """
        Initialize testnet runner.
        
        Args:
            symbols: List of symbols to trade (default: ['BTC', 'ETH'])
            duration_minutes: How long to run (default: 720 = 12 hours)
        """
        self.symbols = symbols or ["BTC", "ETH"]
        self.duration_minutes = duration_minutes
        self.test_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(minutes=duration_minutes)
        
        self.strategy = StrategyB()
        self.sentiment = SentimentAnalyzer()
        self.funding = FundingRateAnalyzer()
        self.info = get_info()
        
        self.signal_count = 0
        self.trade_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        
        print(f"\n🚀 Testnet Runner Started")
        print(f"   Test ID: {self.test_run_id}")
        print(f"   Duration: {duration_minutes} minutes (~{duration_minutes/60:.1f} hours)")
        print(f"   Symbols: {', '.join(self.symbols)}")
        print(f"   Start: {self.start_time.isoformat()}")
        print(f"   End: {self.end_time.isoformat()}")

    async def init_db(self):
        """Initialize test database tables."""
        db = await aiosqlite.connect(cfg.DB_PATH)
        await db.executescript(TEST_TRADES_SCHEMA)
        
        # Create test run record
        await db.execute(
            """INSERT INTO test_run_summary (test_run_id, start_time, total_signals)
               VALUES (?, ?, 0)""",
            (self.test_run_id, self.start_time.isoformat())
        )
        await db.commit()
        await db.close()
        print(f"✓ Database initialized for test run {self.test_run_id}")

    async def log_signal(self, symbol: str, signal_data: Dict, action: str, reason: str = ""):
        """Log a signal to the test_trades table."""
        db = await aiosqlite.connect(cfg.DB_PATH)
        
        sentiment = signal_data.get("sentiment", {})
        funding = signal_data.get("funding", {})
        
        await db.execute(
            """INSERT INTO test_trades 
               (test_run_id, timestamp, symbol, signal, sentiment_score, funding_rate,
                sentiment_confidence, funding_strength, combined_confidence, action, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.test_run_id,
                datetime.now().isoformat(),
                symbol,
                signal_data.get("signal", "HOLD"),
                sentiment.get("sentiment_score", 0),
                funding.get("funding_rate", 0),
                sentiment.get("confidence", 0),
                funding.get("strength", 0),
                signal_data.get("confidence", 0),
                action,
                reason,
            )
        )
        await db.commit()
        await db.close()

    async def run_signal_check(self):
        """Check signals for all symbols once."""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking signals...")
        
        for symbol in self.symbols:
            try:
                # Get strategy signal
                signal = self.strategy.get_next_signal(symbol)
                signal_type = signal.get("signal", "HOLD")
                confidence = signal.get("confidence", 0)
                
                self.signal_count += 1
                
                # Decide action
                action = "SKIPPED"
                reason = "Confidence too low"
                
                if signal_type != "HOLD" and confidence >= 0.3:
                    action = "TRADE"
                    reason = f"Confidence {confidence:.2%}, sentiment aligns with funding"
                    self.trade_count += 1
                    
                    # Log execution
                    trade_data = self.strategy.execute_trade(symbol, signal)
                    print(f"  📊 {symbol}: {signal_type} ({confidence:.1%})")
                    print(f"     → {action}: {reason}")
                    print(f"     → Side: {trade_data.get('side')}, Size: {trade_data.get('size'):.6f}")
                    
                else:
                    print(f"  📊 {symbol}: {signal_type} ({confidence:.1%}) - {reason}")
                
                # Log to database
                await self.log_signal(symbol, signal, action, reason)
                
            except Exception as e:
                print(f"  ✗ {symbol}: Error checking signal: {str(e)}")
                await self.log_signal(
                    symbol, 
                    {"signal": "ERROR", "confidence": 0}, 
                    "ERROR",
                    str(e)
                )

    async def generate_report(self):
        """Generate test run report."""
        db = await aiosqlite.connect(cfg.DB_PATH)
        
        # Update test run summary
        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        
        if self.trade_count > 0:
            win_rate = (self.winning_trades / self.trade_count) * 100
        else:
            win_rate = 0
        
        await db.execute(
            """UPDATE test_run_summary SET
               end_time = ?, duration_minutes = ?, 
               total_signals = ?, trades_executed = ?,
               winning_trades = ?, losing_trades = ?,
               total_pnl = ?, win_rate = ?
               WHERE test_run_id = ?""",
            (
                datetime.now().isoformat(),
                int(elapsed),
                self.signal_count,
                self.trade_count,
                self.winning_trades,
                self.losing_trades,
                self.total_pnl,
                win_rate,
                self.test_run_id,
            )
        )
        await db.commit()
        
        # Get all test trades
        cursor = await db.execute(
            "SELECT * FROM test_trades WHERE test_run_id = ? ORDER BY timestamp",
            (self.test_run_id,)
        )
        trades = await cursor.fetchall()
        await db.close()
        
        # Print report
        print("\n" + "="*70)
        print("TESTNET RUN SUMMARY")
        print("="*70)
        print(f"Test Run ID: {self.test_run_id}")
        print(f"Duration: {int(elapsed)} minutes ({elapsed/60:.1f} hours)")
        print(f"Symbols: {', '.join(self.symbols)}")
        print(f"\nSignal Statistics:")
        print(f"  Total signals checked: {self.signal_count}")
        print(f"  Trades executed: {self.trade_count}")
        print(f"  Winning trades: {self.winning_trades}")
        print(f"  Losing trades: {self.losing_trades}")
        print(f"  Win rate: {win_rate:.1f}%")
        print(f"  Total P&L: ${self.total_pnl:.2f}")
        
        print(f"\nSignal Details (all {len(trades)} entries):")
        for i, trade in enumerate(trades):
            timestamp = trade[2]  # timestamp column
            symbol = trade[3]  # symbol column
            signal = trade[4]  # signal column
            action = trade[10]  # action column
            confidence = trade[9]  # combined_confidence
            
            print(f"\n  {i+1}. [{timestamp}] {symbol}")
            print(f"     Signal: {signal} ({confidence:.1%})")
            print(f"     Action: {action}")
        
        print("\n" + "="*70)
        print("✓ Report complete")
        print("="*70)

    async def run(self):
        """Run the testnet validation."""
        await self.init_db()
        
        print(f"\n⏱️  Running for {self.duration_minutes} minutes...")
        print(f"Testnet mode: {cfg.HL_TESTNET}")
        
        # Run signal checks every 30 minutes (or every 1 hour in production)
        check_interval_seconds = 1800  # 30 minutes
        
        iteration = 0
        while datetime.now() < self.end_time:
            iteration += 1
            await self.run_signal_check()
            
            # Wait before next check, but allow early exit
            elapsed = (datetime.now() - self.start_time).total_seconds() / 60
            remaining = self.duration_minutes - elapsed
            
            if remaining <= 0:
                break
            
            wait_seconds = min(check_interval_seconds, remaining * 60)
            print(f"\n⏳ Waiting {int(wait_seconds/60)} min before next check...")
            print(f"   Elapsed: {elapsed:.1f}/{self.duration_minutes} min")
            
            await asyncio.sleep(wait_seconds)
        
        # Generate final report
        await self.generate_report()


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 2 Testnet Validation Runner")
    parser.add_argument("--duration", type=int, default=720, 
                        help="Duration in minutes (default: 720 = 12 hours)")
    parser.add_argument("--symbols", type=str, default="BTC,ETH",
                        help="Comma-separated symbols (default: BTC,ETH)")
    parser.add_argument("--check-interval", type=int, default=30,
                        help="Minutes between signal checks (default: 30)")
    
    args = parser.parse_args()
    symbols = args.symbols.split(",")
    
    runner = TestnetRunner(
        symbols=symbols,
        duration_minutes=args.duration
    )
    
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
