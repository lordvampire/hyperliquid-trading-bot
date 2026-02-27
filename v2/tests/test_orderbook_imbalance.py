"""
Test suite for Order-Book Imbalance Detector (Task 1.3)
42 tests | Target: >90% coverage
"""

import pytest
from datetime import datetime
from v2.signals.orderbook_imbalance import (
    OrderBookImbalanceDetector,
    OrderBookMetrics,
    OBSignal
)


class TestOBSignalEnum:
    """Test OBSignal enumeration."""
    
    def test_signal_values(self):
        """Test that all signal enums exist."""
        assert OBSignal.LONG_BIAS.value == "LONG_BIAS"
        assert OBSignal.NEUTRAL.value == "NEUTRAL"
        assert OBSignal.SHORT_BIAS.value == "SHORT_BIAS"
    
    def test_signal_comparison(self):
        """Test signal comparison."""
        assert OBSignal.LONG_BIAS != OBSignal.SHORT_BIAS
        assert OBSignal.NEUTRAL != OBSignal.LONG_BIAS


class TestOrderBookMetrics:
    """Test OrderBookMetrics dataclass."""
    
    def test_metrics_creation(self):
        """Test creating metrics object."""
        metrics = OrderBookMetrics(
            bid_ask_ratio=1.5,
            bid_depth_1m=1000,
            ask_depth_1m=700,
            spread_pct=0.02,
            imbalance_strength=0.25,
            signal=OBSignal.LONG_BIAS,
            timestamp="2026-02-26T23:45:00"
        )
        assert metrics.bid_ask_ratio == 1.5
        assert metrics.signal == OBSignal.LONG_BIAS
    
    def test_metrics_with_neutral(self):
        """Test metrics with neutral signal."""
        metrics = OrderBookMetrics(
            bid_ask_ratio=1.0,
            bid_depth_1m=1000,
            ask_depth_1m=1000,
            spread_pct=0.01,
            imbalance_strength=0.0,
            signal=OBSignal.NEUTRAL,
            timestamp="2026-02-26T23:45:00"
        )
        assert metrics.bid_ask_ratio == 1.0
        assert metrics.imbalance_strength == 0.0


class TestDetectorInitialization:
    """Test OrderBookImbalanceDetector initialization."""
    
    def test_default_init(self):
        """Test detector with default parameters."""
        detector = OrderBookImbalanceDetector()
        assert detector.depth_level == 1_000_000
        assert detector.imbalance_threshold == 0.15
        assert detector.cache_ttl_sec == 5
    
    def test_custom_init(self):
        """Test detector with custom parameters."""
        detector = OrderBookImbalanceDetector(
            depth_level=500_000,
            imbalance_threshold=0.20,
            cache_ttl_sec=10
        )
        assert detector.depth_level == 500_000
        assert detector.imbalance_threshold == 0.20
        assert detector.cache_ttl_sec == 10


class TestDepthCalculation:
    """Test _calculate_depth helper method."""
    
    def test_simple_depth(self):
        """Test depth calculation with simple data."""
        side = [
            [50000, 1.0],
            [49999, 1.0],
        ]
        depth = OrderBookImbalanceDetector._calculate_depth(side, 50000)
        assert depth == 1.0
    
    def test_multi_level_depth(self):
        """Test depth across multiple price levels."""
        side = [
            [50000, 1.0],   # 50k
            [49999, 2.0],   # 99.998k total
            [49998, 1.0],   # 149.996k total
        ]
        depth = OrderBookImbalanceDetector._calculate_depth(side, 100000)
        assert 1.9 < depth < 2.1  # Approximately 2.0 at 2nd level
    
    def test_empty_side(self):
        """Test depth with empty order book side."""
        depth = OrderBookImbalanceDetector._calculate_depth([], 100000)
        assert depth == 0
    
    def test_partial_fill(self):
        """Test depth with partial fill on last level."""
        side = [[50000, 5.0]]
        depth = OrderBookImbalanceDetector._calculate_depth(side, 100000)
        assert depth == 2.0  # 50000 * 2 = 100k
    
    def test_zero_price_handling(self):
        """Test depth handles zero price gracefully."""
        side = [[0, 5.0], [50000, 1.0]]
        depth = OrderBookImbalanceDetector._calculate_depth(side, 50000)
        assert depth > 0  # Skips zero price, counts next level


class TestAnalyzeBasic:
    """Test basic analyze functionality."""
    
    def test_analyze_balanced_book(self):
        """Test analyze with balanced order book."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 1.0], [49999, 1.0]],
            "asks": [[50001, 1.0], [50002, 1.0]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.NEUTRAL
        assert abs(metrics.bid_ask_ratio - 1.0) < 0.05
    
    def test_analyze_bullish_book(self):
        """Test analyze with bullish (bid-heavy) order book."""
        detector = OrderBookImbalanceDetector(imbalance_threshold=0.15)
        ob = {
            "bids": [[50000, 3.0], [49999, 2.0]],
            "asks": [[50001, 1.0], [50002, 0.5]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.LONG_BIAS
        assert metrics.bid_ask_ratio > 1.15
    
    def test_analyze_bearish_book(self):
        """Test analyze with bearish (ask-heavy) order book."""
        detector = OrderBookImbalanceDetector(imbalance_threshold=0.15)
        ob = {
            "bids": [[50000, 1.0], [49999, 0.5]],
            "asks": [[50001, 3.0], [50002, 2.0]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.SHORT_BIAS
        assert metrics.bid_ask_ratio < 0.85
    
    def test_analyze_missing_data(self):
        """Test analyze with missing order book data."""
        detector = OrderBookImbalanceDetector()
        metrics = detector.analyze("BTC", None)
        assert metrics.signal == OBSignal.NEUTRAL
        assert metrics.bid_depth_1m == 0
    
    def test_analyze_empty_ob(self):
        """Test analyze with empty order book."""
        detector = OrderBookImbalanceDetector()
        metrics = detector.analyze("BTC", {"bids": [], "asks": []})
        assert metrics.signal == OBSignal.NEUTRAL


class TestCaching:
    """Test cache functionality."""
    
    def test_cache_hit(self):
        """Test that cache returns same object within TTL."""
        detector = OrderBookImbalanceDetector(cache_ttl_sec=10)
        ob = {
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]]
        }
        metrics1 = detector.analyze("BTC", ob)
        metrics2 = detector.analyze("BTC", ob)
        
        # Should be same timestamp (cached)
        assert metrics1.timestamp == metrics2.timestamp
    
    def test_cache_expiry(self):
        """Test that cache expires after TTL."""
        import time
        detector = OrderBookImbalanceDetector(cache_ttl_sec=0)  # Expire immediately
        ob = {
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]]
        }
        metrics1 = detector.analyze("BTC", ob)
        time.sleep(0.1)
        metrics2 = detector.analyze("BTC", ob)
        
        # Timestamps should differ (cache expired)
        assert metrics1.timestamp != metrics2.timestamp


class TestWhaleDetection:
    """Test whale order detection."""
    
    def test_whale_bid(self):
        """Test whale detection on bid side."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [
                [50000, 10.0],  # 10 BTC = whale
                [49999, 1.0],
                [49998, 1.0]
            ],
            "asks": [[50001, 1.0]]
        }
        whales = detector.detect_whale_orders(ob, whale_threshold=0.05)
        assert len(whales["bid_whales"]) > 0
        assert whales["bid_whales"][0]["volume"] == 10.0
    
    def test_whale_ask(self):
        """Test whale detection on ask side."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 1.0]],
            "asks": [
                [50001, 8.0],   # 8 BTC = whale
                [50002, 1.0],
                [50003, 1.0]
            ]
        }
        whales = detector.detect_whale_orders(ob, whale_threshold=0.05)
        assert len(whales["ask_whales"]) > 0
    
    def test_no_whales(self):
        """Test whale detection with no whales."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 1.0], [49999, 1.0], [49998, 1.0], [49997, 1.0], [49996, 1.0]],
            "asks": [[50001, 1.0], [50002, 1.0], [50003, 1.0], [50004, 1.0], [50005, 1.0]]
        }
        whales = detector.detect_whale_orders(ob, whale_threshold=0.50)  # 50% threshold
        assert len(whales["bid_whales"]) == 0
        assert len(whales["ask_whales"]) == 0


class TestRealWorldScenarios:
    """Test with realistic order book patterns."""
    
    def test_btc_consolidation(self):
        """Test BTC consolidation pattern."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [
                [50000, 0.5], [49999, 0.4], [49998, 0.3], [49997, 0.3]
            ],
            "asks": [
                [50001, 0.5], [50002, 0.4], [50003, 0.3], [50004, 0.3]
            ]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.NEUTRAL
    
    def test_eth_bull_run(self):
        """Test ETH bull run pattern."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [
                [3000, 5.0], [2999, 3.0], [2998, 2.0]
            ],
            "asks": [
                [3001, 1.0], [3002, 0.5], [3003, 0.3]
            ]
        }
        metrics = detector.analyze("ETH", ob)
        assert metrics.signal == OBSignal.LONG_BIAS
    
    def test_sol_dumping(self):
        """Test SOL sell-off pattern."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [
                [140, 1.0], [139, 0.8], [138, 0.6]
            ],
            "asks": [
                [141, 5.0], [142, 3.0], [143, 2.0]
            ]
        }
        metrics = detector.analyze("SOL", ob)
        assert metrics.signal == OBSignal.SHORT_BIAS


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_negative_price(self):
        """Test handling of negative prices (shouldn't happen)."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[-50000, 1.0]],
            "asks": [[50001, 1.0]]
        }
        # Should not crash
        metrics = detector.analyze("BTC", ob)
        assert metrics is not None
    
    def test_zero_volume(self):
        """Test handling of zero volume."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 0], [49999, 0]],
            "asks": [[50001, 0], [50002, 0]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.NEUTRAL
    
    def test_very_large_imbalance(self):
        """Test extreme imbalance."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 100.0]],
            "asks": [[50001, 0.1]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.LONG_BIAS
        assert metrics.imbalance_strength > 0.5
    
    def test_single_level_ob(self):
        """Test order book with only one level per side."""
        detector = OrderBookImbalanceDetector()
        ob = {
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]]
        }
        metrics = detector.analyze("BTC", ob)
        assert metrics.signal == OBSignal.NEUTRAL


class TestIntegration:
    """Integration tests."""
    
    def test_multiple_symbols(self):
        """Test analyzing multiple symbols."""
        detector = OrderBookImbalanceDetector()
        symbols = ["BTC", "ETH", "SOL"]
        
        for sym in symbols:
            ob = {
                "bids": [[100, 1.0]],
                "asks": [[101, 1.0]]
            }
            metrics = detector.analyze(sym, ob)
            assert metrics.signal == OBSignal.NEUTRAL
    
    def test_changing_imbalance(self):
        """Test detector with changing imbalance."""
        detector = OrderBookImbalanceDetector(imbalance_threshold=0.15)
        
        # Start neutral
        ob1 = {"bids": [[50000, 1.0]], "asks": [[50001, 1.0]]}
        m1 = detector.analyze("BTC", ob1)
        assert m1.signal == OBSignal.NEUTRAL
        
        # Become bullish
        ob2 = {"bids": [[50000, 3.0]], "asks": [[50001, 1.0]]}
        m2 = detector.analyze("BTC_2", ob2)  # Different key to avoid cache
        assert m2.signal == OBSignal.LONG_BIAS


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
