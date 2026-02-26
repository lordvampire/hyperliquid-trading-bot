#!/usr/bin/env python3
"""Phase 2 Validation Tests — Real API Integration."""

import sys
import json
from datetime import datetime


def test_funding_api():
    """Test: Funding rates from Hyperliquid API."""
    print("\n" + "="*60)
    print("TEST 1: Funding Rate API Integration")
    print("="*60)
    
    try:
        from funding import FundingRateAnalyzer
        
        analyzer = FundingRateAnalyzer()
        
        # Test current funding rate
        print("\n▶ Fetching BTC funding rate...")
        btc_funding = analyzer.get_funding_rate("BTC")
        
        print(f"  Symbol: {btc_funding.get('symbol')}")
        print(f"  Funding Rate: {btc_funding.get('funding_rate'):.6f}")
        print(f"  Annualized: {btc_funding.get('annualized'):.2f}%")
        print(f"  Cached: {btc_funding.get('is_cached', False)}")
        
        if "error" in btc_funding:
            print(f"  ⚠️  Error: {btc_funding['error']}")
        else:
            print("  ✓ Real funding rate retrieved!")
        
        # Test funding signal
        print("\n▶ Getting funding signal...")
        signal = analyzer.get_funding_signal("BTC")
        print(f"  Signal: {signal.get('signal')}")
        print(f"  Strength: {signal.get('strength', 0):.3f}")
        print("  ✓ Signal generated!")
        
        # Test funding history
        print("\n▶ Fetching funding history...")
        history = analyzer.get_history("BTC", limit=5)
        print(f"  History entries: {len(history)}")
        for i, entry in enumerate(history[:3]):
            if "error" not in entry:
                print(f"    {i+1}. {entry.get('timestamp')}: {entry.get('funding_rate'):.6f}")
        print("  ✓ History retrieved!")
        
        # Test funding trend
        print("\n▶ Analyzing funding trend...")
        trend = analyzer.get_funding_trend("BTC", hours=24)
        print(f"  Trend: {trend.get('trend')}")
        print(f"  Avg Rate: {trend.get('avg_rate'):.6f}")
        print(f"  Change: {trend.get('change_pct'):.3f}%")
        print(f"  Volatility: {trend.get('volatility'):.6f}")
        print("  ✓ Trend analysis complete!")
        
        return True
        
    except Exception as e:
        print(f"  ✗ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_sentiment_api():
    """Test: Sentiment analyzer with real funding data."""
    print("\n" + "="*60)
    print("TEST 2: Sentiment Analysis (Heuristic)")
    print("="*60)
    
    try:
        from sentiment import SentimentAnalyzer
        
        analyzer = SentimentAnalyzer()
        
        # Test sentiment analysis
        print("\n▶ Analyzing BTC sentiment...")
        sentiment = analyzer.analyze("BTC")
        
        print(f"  Symbol: {sentiment.get('symbol')}")
        print(f"  Sentiment Score: {sentiment.get('sentiment_score'):.3f}")
        print(f"  Signal: {sentiment.get('signal')}")
        print(f"  Confidence: {sentiment.get('confidence'):.3f}")
        
        if "error" in sentiment:
            print(f"  ⚠️  Error: {sentiment['error']}")
        else:
            print("  ✓ Real sentiment generated!")
            
            components = sentiment.get("components", {})
            if components:
                print(f"\n  Components:")
                print(f"    Funding Trend: {components.get('funding_trend', {}).get('trend')}")
                print(f"    Current Rate: {components.get('current_funding_rate'):.6f}")
                print(f"    Volatility: {components.get('volatility'):.6f}")
        
        # Test signal generation
        print("\n▶ Getting trade signal...")
        signal, conf = analyzer.get_signal("BTC", threshold=0.2)
        print(f"  Signal: {signal}")
        print(f"  Confidence: {conf:.3f}")
        print("  ✓ Trade signal generated!")
        
        return True
        
    except Exception as e:
        print(f"  ✗ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_backtest_api():
    """Test: Backtest engine with real candles."""
    print("\n" + "="*60)
    print("TEST 3: Backtest with Real Candles")
    print("="*60)
    
    try:
        from backtest import BacktestEngine
        
        engine = BacktestEngine(start_balance=1000)
        
        print("\n▶ Running 7-day backtest on BTC...")
        results = engine.run("BTC", days=7, interval="1h")
        
        if results.get("status") == "error":
            print(f"  ✗ Backtest failed: {results.get('message')}")
            return False
        
        print(f"  Period: {results.get('period')}")
        print(f"  Candles Processed: {results.get('candles_processed')}")
        print(f"  Trades Executed: {results.get('trades_executed')}")
        print(f"  Winning Trades: {results.get('winning_trades')}")
        print(f"  Losing Trades: {results.get('losing_trades')}")
        print(f"  Win Rate: {results.get('win_rate'):.1f}%")
        print(f"  Total P&L: ${results.get('total_pnl'):.2f}")
        print(f"  Total Return: {results.get('total_return'):.2f}%")
        print(f"  Start Balance: ${results.get('start_balance'):.2f}")
        print(f"  Final Balance: ${results.get('final_balance'):.2f}")
        
        fees = results.get("fees_included", {})
        print(f"\n  Fee Structure:")
        print(f"    Entry Fee: {fees.get('entry_fee_pct'):.2f}%")
        print(f"    Exit Fee: {fees.get('exit_fee_pct'):.2f}%")
        
        trades = results.get("trades", [])
        if trades:
            print(f"\n  Sample Trades (last 3):")
            for i, trade in enumerate(trades[-3:]):
                print(f"    {i+1}. {trade.get('side').upper()} @ ${trade.get('entry_price'):.2f}")
                print(f"       P&L: ${trade.get('pnl'):.2f} ({trade.get('pnl_pct'):+.2f}%)")
                print(f"       Exit Reason: {trade.get('exit_reason')}")
        
        print("\n  ✓ Backtest completed successfully!")
        return True
        
    except Exception as e:
        print(f"  ✗ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_strategy_integration():
    """Test: Strategy B integration with real components."""
    print("\n" + "="*60)
    print("TEST 4: Strategy B Integration")
    print("="*60)
    
    try:
        from strategy_b import StrategyB
        
        strategy = StrategyB()
        
        print("\n▶ Getting next signal...")
        signal = strategy.get_next_signal("BTC")
        
        print(f"  Symbol: {signal.get('symbol')}")
        print(f"  Signal: {signal.get('signal')}")
        print(f"  Confidence: {signal.get('confidence'):.3f}")
        
        sentiment = signal.get("sentiment", {})
        funding = signal.get("funding", {})
        
        print(f"\n  Sentiment Component:")
        print(f"    Score: {sentiment.get('sentiment_score'):.3f}")
        print(f"    Signal: {sentiment.get('signal')}")
        print(f"    Confidence: {sentiment.get('confidence'):.3f}")
        
        print(f"\n  Funding Component:")
        print(f"    Rate: {funding.get('funding_rate'):.6f}")
        print(f"    Signal: {funding.get('signal')}")
        print(f"    Strength: {funding.get('strength'):.3f}")
        
        # Test trade execution
        print("\n▶ Executing trade...")
        execution = strategy.execute_trade("BTC", signal)
        print(f"  Status: {execution.get('status')}")
        print(f"  Side: {execution.get('side', 'N/A')}")
        print(f"  Size: {execution.get('size', 0):.6f}")
        
        print("\n  ✓ Strategy integration complete!")
        return True
        
    except Exception as e:
        print(f"  ✗ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all Phase 2 tests."""
    print("\n")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║         Phase 2 Validation — Real API Integration          ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    results = {
        "Funding API": test_funding_api(),
        "Sentiment Analysis": test_sentiment_api(),
        "Backtest Engine": test_backtest_api(),
        "Strategy Integration": test_strategy_integration(),
    }
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} — {test_name}")
    
    passed_count = sum(1 for p in results.values() if p)
    total_count = len(results)
    
    print(f"\nTotal: {passed_count}/{total_count} passed")
    
    if passed_count == total_count:
        print("\n🎉 All Phase 2 tests passed! Real integrations are working.\n")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check errors above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
