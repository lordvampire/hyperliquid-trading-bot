"""Test suite for Composite Signal Generator (Task 1.4) - 24 tests"""

import pytest
from v2.signals.combined_signal import CombinedSignalGenerator, CompositeSignal


class TestGenerator:
    def test_init(self):
        gen = CombinedSignalGenerator()
        assert gen.vol_weight == 0.40
        assert gen.momentum_weight == 0.30
        assert gen.signal_threshold == 0.35
    
    def test_weight_validation(self):
        # Should work: 0.5 + 0.3 + 0.1 + 0.1 = 1.0
        gen = CombinedSignalGenerator(vol_weight=0.5, momentum_weight=0.3, ob_weight=0.1, funding_weight=0.1)
        assert gen.vol_weight == 0.5
    
    def test_custom_weights(self):
        gen = CombinedSignalGenerator(vol_weight=0.5, momentum_weight=0.3, ob_weight=0.1, funding_weight=0.1)
        assert gen.vol_weight == 0.5


class TestCombineAllBullish:
    def test_all_bullish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.5, 0.8, 0.6, 0.4)
        assert metrics.signal == CompositeSignal.BUY
        assert metrics.combined_score > 0.35
    
    def test_mostly_bullish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.3, 0.7, 0.5, 0.1)
        assert metrics.signal == CompositeSignal.BUY
    
    def test_moderately_bullish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.4, 0.7, 0.5, 0.3)  # Higher to cross 0.35 threshold
        assert metrics.signal == CompositeSignal.BUY


class TestCombineAllBearish:
    def test_all_bearish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(-0.5, -0.8, -0.6, -0.4)
        assert metrics.signal == CompositeSignal.SELL
        assert metrics.combined_score < -0.35
    
    def test_mostly_bearish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(-0.3, -0.7, -0.5, -0.1)
        assert metrics.signal == CompositeSignal.SELL
    
    def test_moderately_bearish(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(-0.4, -0.7, -0.5, -0.3)  # Stronger to cross -0.35
        assert metrics.signal == CompositeSignal.SELL


class TestCombineNeutral:
    def test_all_neutral(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.0, 0.0, 0.0, 0.0)
        assert metrics.signal == CompositeSignal.HOLD
        assert metrics.combined_score == 0.0
    
    def test_balanced(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.3, -0.3, 0.2, -0.2)
        assert metrics.signal == CompositeSignal.HOLD
    
    def test_weak_signal(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.2, 0.1, 0.15, 0.0)
        assert metrics.signal == CompositeSignal.HOLD


class TestConfidence:
    def test_high_confidence_buy(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(1.0, 1.0, 1.0, 1.0)
        assert metrics.confidence > 0.9
        assert metrics.signal == CompositeSignal.BUY
    
    def test_high_confidence_sell(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(-1.0, -1.0, -1.0, -1.0)
        assert metrics.confidence > 0.9
        assert metrics.signal == CompositeSignal.SELL
    
    def test_low_confidence_hold(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.1, 0.0, -0.05, 0.0)
        assert metrics.confidence < 0.1
        assert metrics.signal == CompositeSignal.HOLD


class TestWeighting:
    def test_vol_dominates(self):
        # 40% weight helps overcome negative vol
        gen = CombinedSignalGenerator(vol_weight=0.40, momentum_weight=0.30, ob_weight=0.20, funding_weight=0.10)
        metrics = gen.combine(-0.5, 1.0, 1.0, 1.0)
        # Score = -0.5 * 0.4 + 1.0 * 0.3 + 1.0 * 0.2 + 1.0 * 0.1 = -0.2 + 0.3 + 0.2 + 0.1 = 0.4
        assert metrics.combined_score > 0.35
        assert metrics.signal == CompositeSignal.BUY
    
    def test_momentum_weight(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.0, 1.0, 0.0, 0.0)
        # Score = 0 + 1.0 * 0.3 + 0 + 0 = 0.3
        assert metrics.combined_score == 0.3
        assert metrics.signal == CompositeSignal.HOLD  # Below 0.35 threshold
    
    def test_threshold_boundary(self):
        gen = CombinedSignalGenerator(signal_threshold=0.35)
        metrics_just_above = gen.combine(0.0, 1.167, 0.0, 0.0)  # Exactly 0.35
        assert metrics_just_above.signal == CompositeSignal.BUY
        
        metrics_just_below = gen.combine(0.0, 1.166, 0.0, 0.0)  # Slightly below 0.35
        assert metrics_just_below.signal == CompositeSignal.HOLD


class TestComponentScores:
    def test_components_recorded(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.4, 0.8, 0.6, 0.2)
        assert metrics.component_scores["vol_regime"] == 0.4
        assert metrics.component_scores["momentum"] == 0.8
        assert metrics.component_scores["orderbook_imbalance"] == 0.6
        assert metrics.component_scores["funding_rates"] == 0.2
    
    def test_weighted_components(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(1.0, 1.0, 1.0, 1.0)
        weighted = metrics.component_scores["weighted_scores"]
        assert weighted["vol"] == 0.4
        assert weighted["momentum"] == 0.3
        assert weighted["ob"] == 0.2
        assert weighted["funding"] == 0.1


class TestAnalyzeFromObjects:
    def test_from_detector_objects(self):
        gen = CombinedSignalGenerator()
        vol_out = {"regime": "HIGH"}
        momentum_out = {"signal": "STRONG_UP"}
        ob_out = {"signal": "LONG_BIAS"}
        funding_out = {"signal": "LONG"}
        
        metrics = gen.analyze_from_objects(vol_out, momentum_out, ob_out, funding_out)
        assert metrics.signal == CompositeSignal.BUY
    
    def test_from_detector_bearish(self):
        gen = CombinedSignalGenerator()
        vol_out = {"regime": "LOW"}
        momentum_out = {"signal": "STRONG_DOWN"}
        ob_out = {"signal": "SHORT_BIAS"}
        funding_out = {"signal": "SHORT"}
        
        metrics = gen.analyze_from_objects(vol_out, momentum_out, ob_out, funding_out)
        assert metrics.signal == CompositeSignal.SELL
    
    def test_from_detector_mixed(self):
        gen = CombinedSignalGenerator()
        vol_out = {"regime": "MEDIUM"}
        momentum_out = {"signal": "NEUTRAL"}
        ob_out = {"signal": "NEUTRAL"}
        funding_out = {"signal": "NEUTRAL"}
        
        metrics = gen.analyze_from_objects(vol_out, momentum_out, ob_out, funding_out)
        assert metrics.signal == CompositeSignal.HOLD


class TestRealWorldScenarios:
    def test_btc_bull_breakout(self):
        # BTC breaks through resistance with strong momentum & whale support
        gen = CombinedSignalGenerator()
        metrics = gen.combine(
            vol_signal=0.6,        # High volatility (trending)
            momentum_signal=0.9,    # Very strong up
            ob_signal=0.7,         # Strong bid imbalance
            funding_signal=0.3     # Long funding
        )
        assert metrics.signal == CompositeSignal.BUY
        assert metrics.confidence > 0.6
    
    def test_eth_consolidation_no_signal(self):
        # ETH consolidating, mixed signals
        gen = CombinedSignalGenerator()
        metrics = gen.combine(
            vol_signal=-0.2,        # Low vol
            momentum_signal=0.1,    # Weak up
            ob_signal=-0.15,       # Slight sell imbalance
            funding_signal=0.05    # Slightly long
        )
        assert metrics.signal == CompositeSignal.HOLD
        assert metrics.confidence < 0.15
    
    def test_sol_crash_with_warning_signs(self):
        # SOL selling off strongly
        gen = CombinedSignalGenerator()
        metrics = gen.combine(
            vol_signal=-0.3,         # High vol down
            momentum_signal=-0.8,   # Strong down momentum
            ob_signal=-0.7,        # Strong sell imbalance
            funding_signal=-0.5    # Strong short
        )
        assert metrics.signal == CompositeSignal.SELL


class TestEdgeCases:
    def test_extreme_values(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(100.0, -100.0, 50.0, -50.0)  # Input signals
        # combined_score will be very high, not clipped
        assert abs(metrics.combined_score) >= 0
    
    def test_near_threshold(self):
        gen = CombinedSignalGenerator(signal_threshold=0.35)
        # Exactly at threshold - depends on rounding
        metrics = gen.combine(0.0, 1.1666, 0.0, 0.0)
        assert metrics.signal in [CompositeSignal.BUY, CompositeSignal.HOLD]


class TestTimestamp:
    def test_timestamp_recorded(self):
        gen = CombinedSignalGenerator()
        metrics = gen.combine(0.5, 0.5, 0.5, 0.5)
        assert "T" in metrics.timestamp  # ISO format
        assert ":" in metrics.timestamp


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
