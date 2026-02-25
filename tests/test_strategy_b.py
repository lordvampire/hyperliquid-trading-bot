"""Tests for Strategy B (Phase 2)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_b import StrategyB
from sentiment import SentimentAnalyzer
from funding import FundingRateAnalyzer


def test_sentiment_analyzer():
    """Test sentiment analyzer."""
    analyzer = SentimentAnalyzer()
    
    # Test analyze
    sentiment = analyzer.analyze("BTC")
    assert "symbol" in sentiment
    assert "sentiment_score" in sentiment
    assert "signal" in sentiment
    assert sentiment["signal"] in ["BUY", "SELL", "HOLD"]
    assert -1 <= sentiment["sentiment_score"] <= 1
    assert 0 <= sentiment["confidence"] <= 1
    print("✓ Sentiment analyzer works")


def test_funding_rate_analyzer():
    """Test funding rate analyzer."""
    analyzer = FundingRateAnalyzer()
    
    # Test get_funding_rate
    rate = analyzer.get_funding_rate("BTC")
    assert "funding_rate" in rate
    assert "symbol" in rate
    assert isinstance(rate["funding_rate"], float)
    print("✓ Funding rate analyzer works")
    
    # Test signal generation
    signal = analyzer.get_funding_signal("BTC")
    assert signal["signal"] in ["LONG", "SHORT", "NEUTRAL"]
    assert 0 <= signal["strength"] <= 1
    print("✓ Funding signal generation works")
    
    # Test history
    history = analyzer.get_history("BTC", limit=10)
    assert len(history) == 10
    print("✓ Funding history works")


def test_strategy_b():
    """Test Strategy B."""
    strategy = StrategyB()
    
    # Test get_next_signal
    signal = strategy.get_next_signal("BTC")
    assert "symbol" in signal
    assert signal["signal"] in ["BUY", "SELL", "HOLD"]
    assert "confidence" in signal
    assert 0 <= signal["confidence"] <= 1
    print("✓ Strategy B signal generation works")
    
    # Test execute_trade
    trade = strategy.execute_trade("BTC", signal)
    assert "status" in trade
    assert trade["status"] in ["queued", "skipped"]
    print("✓ Strategy B trade execution works")
    
    # Test check_exit
    should_exit, reason = strategy.check_exit("BTC")
    assert isinstance(should_exit, bool)
    assert isinstance(reason, str)
    print("✓ Strategy B exit check works")


def test_strategy_b_integration():
    """Integration test: signal -> execute -> exit."""
    strategy = StrategyB()
    symbol = "ETH"
    
    # Get signal
    signal = strategy.get_next_signal(symbol)
    assert signal["signal"] in ["BUY", "SELL", "HOLD"]
    
    # Execute if confident
    if signal["confidence"] > 0.3:
        trade = strategy.execute_trade(symbol, signal)
        assert trade["status"] == "queued"
        print(f"✓ Executed {trade['side']} trade with confidence {signal['confidence']:.2%}")
    
    # Check exit
    should_exit, reason = strategy.check_exit(symbol)
    assert isinstance(should_exit, bool)
    print("✓ Exit check works")


if __name__ == "__main__":
    test_sentiment_analyzer()
    test_funding_rate_analyzer()
    test_strategy_b()
    test_strategy_b_integration()
    print("\n✅ All Phase 2 tests passed!")
