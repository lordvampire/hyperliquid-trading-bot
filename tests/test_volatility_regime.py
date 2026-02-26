"""
Comprehensive tests for Volatility Regime Detector

Tests cover:
- Basic functionality with synthetic data
- Real Hyperliquid data (mocked)
- Edge cases (gaps, crashes, insufficient data)
- BTC, ETH, SOL scenarios
- Regime classification logic
- Percentile calculation and history tracking
"""

import pytest
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add the parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "v2" / "signals"))

from volatility_regime import VolatilityRegimeDetector


class TestVolatilityRegimeDetectorBasics:
    """Test basic functionality and initialization."""
    
    def test_initialization(self):
        """Test detector initialization with default and custom lookback."""
        detector_default = VolatilityRegimeDetector()
        assert detector_default.lookback == 20
        assert detector_default.vol_history == []
        
        detector_custom = VolatilityRegimeDetector(lookback=30)
        assert detector_custom.lookback == 30
    
    def test_insufficient_data_raises_error(self):
        """Test that insufficient candle data raises ValueError."""
        detector = VolatilityRegimeDetector(lookback=20)
        insufficient_candles = [
            {"open": 100, "high": 105, "low": 95, "close": 102, "time": 1000000}
        ]
        
        with pytest.raises(ValueError, match="Insufficient candle data"):
            detector.analyze("BTC", insufficient_candles)
    
    def test_reset_history(self):
        """Test that reset_history clears volatility history."""
        detector = VolatilityRegimeDetector()
        detector.vol_history = [0.01, 0.02, 0.03]
        detector.reset_history()
        assert detector.vol_history == []


class TestATRCalculation:
    """Test Average True Range calculation."""
    
    def create_simple_candles(self, n: int, start_price: float = 100) -> list:
        """Create simple candles for testing."""
        candles = []
        time = 1000000
        for i in range(n):
            price = start_price + i * 0.5
            candles.append({
                "open": price,
                "high": price + 2,
                "low": price - 1,
                "close": price + 0.5,
                "time": time + (i * 3600)  # 1 hour apart
            })
        return candles
    
    def test_atr_calculation_simple(self):
        """Test ATR calculation with simple ascending prices."""
        detector = VolatilityRegimeDetector(lookback=20)
        candles = self.create_simple_candles(25)
        
        result = detector.analyze("BTC", candles)
        
        assert "atr" in result
        assert result["atr"] > 0
        assert isinstance(result["atr"], float)
    
    def test_atr_with_high_volatility(self):
        """Test ATR is higher with increased volatility."""
        detector = VolatilityRegimeDetector(lookback=20)
        candles = []
        time = 1000000
        
        # Create candles with high volatility (larger H-L spreads)
        for i in range(25):
            price = 100 + i
            candles.append({
                "open": price,
                "high": price + 10,  # Larger spread
                "low": price - 10,
                "close": price,
                "time": time + (i * 3600)
            })
        
        result = detector.analyze("ETH", candles)
        assert result["atr"] > 5  # Should be significantly higher


class TestBollingerBandWidth:
    """Test Bollinger Band Width calculation."""
    
    def create_stable_candles(self, n: int, base_price: float = 100) -> list:
        """Create stable price candles."""
        candles = []
        time = 1000000
        for i in range(n):
            # Price oscillates slightly around base
            price = base_price + (i % 5 - 2) * 0.1
            candles.append({
                "open": price,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price,
                "time": time + (i * 3600)
            })
        return candles
    
    def test_bb_width_low_volatility(self):
        """Test Bollinger Band Width is low with stable prices."""
        detector = VolatilityRegimeDetector(lookback=20)
        candles = self.create_stable_candles(25, base_price=100)
        
        result = detector.analyze("SOL", candles)
        
        assert "bb_width" in result
        assert result["bb_width"] >= 0
        assert result["bb_width"] < 0.01  # Should be very small
    
    def test_bb_width_calculation_present(self):
        """Test BB width is calculated and present in result."""
        detector = VolatilityRegimeDetector()
        candles = [
            {
                "open": 100 + i * 2,
                "high": 110 + i * 2,
                "low": 90 + i * 2,
                "close": 105 + i * 2,
                "time": 1000000 + (i * 3600)
            }
            for i in range(25)
        ]
        
        result = detector.analyze("BTC", candles)
        assert isinstance(result["bb_width"], float)


class TestHistoricalVolatility:
    """Test historical volatility calculation."""
    
    def test_volatility_with_varying_returns(self):
        """Test volatility reflects varying price movements."""
        detector = VolatilityRegimeDetector()
        
        # Create candles with varying returns
        candles = [
            {"open": 100, "high": 102, "low": 98, "close": 101, "time": 1000000},
            {"open": 101, "high": 105, "low": 99, "close": 104, "time": 1003600},
            {"open": 104, "high": 103, "low": 100, "close": 102, "time": 1007200},
            {"open": 102, "high": 106, "low": 101, "close": 105, "time": 1010800},
        ]
        
        # Extend to meet minimum requirement
        while len(candles) < 20:
            candles.append({
                "open": candles[-1]["close"],
                "high": candles[-1]["close"] + 1,
                "low": candles[-1]["close"] - 1,
                "close": candles[-1]["close"] + 0.5,
                "time": candles[-1]["time"] + 3600
            })
        
        result = detector.analyze("ETH", candles)
        assert result["atr"] > 0
        assert isinstance(result["hist_vol_percentile"], float)


class TestRegimeClassification:
    """Test volatility regime classification logic."""
    
    def test_classify_regime_low(self):
        """Test LOW regime classification."""
        detector = VolatilityRegimeDetector()
        detector.vol_history = [v * 0.001 for v in range(1, 252)]  # 251 values
        
        # Current vol very low - should be LOW
        result = detector._classify_regime(0.0001)
        assert result == "LOW"
    
    def test_classify_regime_high(self):
        """Test HIGH regime classification."""
        detector = VolatilityRegimeDetector()
        detector.vol_history = [v * 0.001 for v in range(1, 252)]  # 251 values
        
        # Percentile > 75 - should be HIGH
        result = detector._classify_regime(80.0)
        assert result == "HIGH"
    
    def test_classify_regime_medium(self):
        """Test MEDIUM regime classification."""
        detector = VolatilityRegimeDetector()
        detector.vol_history = [v * 0.001 for v in range(1, 252)]
        
        # Percentile between 25 and 75 - should be MEDIUM
        result = detector._classify_regime(50.0)
        assert result == "MEDIUM"


class TestPercentileCalculation:
    """Test percentile calculation and history tracking."""
    
    def test_percentile_with_small_history(self):
        """Test percentile when history is small."""
        detector = VolatilityRegimeDetector()
        percentile = detector._calculate_percentile(0.01)
        
        # With < 2 values, should return 50
        assert percentile == 50.0
    
    def test_percentile_increases_with_higher_values(self):
        """Test that percentile increases when current vol is higher."""
        detector = VolatilityRegimeDetector()
        
        # Build history
        for i in range(1, 11):
            detector._calculate_percentile(0.001 * i)
        
        # New value higher than most history
        high_percentile = detector._calculate_percentile(0.015)
        
        # New value lower than most history
        detector.reset_history()
        for i in range(1, 11):
            detector._calculate_percentile(0.001 * i)
        low_percentile = detector._calculate_percentile(0.0001)
        
        assert high_percentile > 50
        assert low_percentile < 50
    
    def test_history_maintains_max_length(self):
        """Test that history doesn't exceed HISTORY_LENGTH."""
        detector = VolatilityRegimeDetector()
        
        # Add more than HISTORY_LENGTH values
        for i in range(300):
            detector._calculate_percentile(0.001 * (i % 100 + 1))
        
        assert len(detector.vol_history) <= detector.HISTORY_LENGTH
        assert len(detector.vol_history) == detector.HISTORY_LENGTH


class TestRealWorldScenarios:
    """Test with realistic market data patterns."""
    
    def create_btc_candles(self, volatility_regime: str = "normal") -> list:
        """Create realistic BTC candles."""
        candles = []
        time = 1000000
        price = 45000
        
        if volatility_regime == "low":
            # Consolidating market
            for i in range(25):
                price += (i % 3 - 1) * 10
                candles.append({
                    "open": price,
                    "high": price + 50,
                    "low": price - 50,
                    "close": price + 20,
                    "time": time + (i * 3600)
                })
        elif volatility_regime == "high":
            # High volatility market
            for i in range(25):
                price += (i % 3 - 1) * 500
                candles.append({
                    "open": price,
                    "high": price + 1000,
                    "low": price - 1000,
                    "close": price + 300,
                    "time": time + (i * 3600)
                })
        else:
            # Normal volatility
            for i in range(25):
                price += (i % 3 - 1) * 100
                candles.append({
                    "open": price,
                    "high": price + 200,
                    "low": price - 200,
                    "close": price + 50,
                    "time": time + (i * 3600)
                })
        
        return candles
    
    def test_btc_low_volatility_regime(self):
        """Test BTC in low volatility environment."""
        detector = VolatilityRegimeDetector()
        
        # Simulate historical low volatility
        for i in range(10):
            detector._calculate_percentile(0.001 + i * 0.0001)
        
        candles = self.create_btc_candles(volatility_regime="low")
        result = detector.analyze("BTC", candles)
        
        assert result["regime"] in ["LOW", "MEDIUM"]
        assert "atr" in result
        assert "bb_width" in result
    
    def test_btc_high_volatility_regime(self):
        """Test BTC in high volatility environment."""
        detector = VolatilityRegimeDetector()
        
        # Simulate historical low volatility first
        for i in range(10):
            detector._calculate_percentile(0.001 + i * 0.0001)
        
        candles = self.create_btc_candles(volatility_regime="high")
        result = detector.analyze("BTC", candles)
        
        assert result["regime"] in ["MEDIUM", "HIGH"]
        assert result["atr"] > 0
    
    def test_eth_analysis(self):
        """Test ETH volatility analysis."""
        detector = VolatilityRegimeDetector()
        candles = self.create_btc_candles(volatility_regime="normal")
        
        # Scale prices for ETH
        for candle in candles:
            candle["open"] = candle["open"] / 10
            candle["high"] = candle["high"] / 10
            candle["low"] = candle["low"] / 10
            candle["close"] = candle["close"] / 10
        
        result = detector.analyze("ETH", candles)
        
        assert result["regime"] in ["LOW", "MEDIUM", "HIGH"]
        assert isinstance(result["hist_vol_percentile"], float)
        assert 0 <= result["hist_vol_percentile"] <= 100
    
    def test_sol_analysis(self):
        """Test SOL volatility analysis."""
        detector = VolatilityRegimeDetector()
        candles = self.create_btc_candles(volatility_regime="normal")
        
        # Scale prices for SOL
        for candle in candles:
            candle["open"] = candle["open"] / 1000
            candle["high"] = candle["high"] / 1000
            candle["low"] = candle["low"] / 1000
            candle["close"] = candle["close"] / 1000
        
        result = detector.analyze("SOL", candles)
        
        assert result["regime"] in ["LOW", "MEDIUM", "HIGH"]
        assert result["hist_vol_percentile"] >= 0


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_candle_with_gap(self):
        """Test handling of price gaps."""
        detector = VolatilityRegimeDetector()
        candles = [
            {
                "open": 100,
                "high": 105,
                "low": 95,
                "close": 102,
                "time": 1000000 + (i * 3600)
            }
            for i in range(20)
        ]
        
        # Insert a gap
        candles[10]["close"] = 150
        candles[11]["open"] = 150
        
        result = detector.analyze("BTC", candles)
        
        # Should handle gap in True Range calculation
        assert result["atr"] > 0
    
    def test_crash_scenario(self):
        """Test handling of price crash."""
        detector = VolatilityRegimeDetector()
        candles = [
            {
                "open": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "close": 102 + i,
                "time": 1000000 + (i * 3600)
            }
            for i in range(20)
        ]
        
        # Simulate crash
        candles[15]["high"] = 105
        candles[15]["low"] = 50  # Big drop
        candles[15]["close"] = 55
        
        result = detector.analyze("ETH", candles)
        
        # Should show increased volatility
        assert result["atr"] > 0
        assert "regime" in result
    
    def test_flat_price_action(self):
        """Test with zero price movement (flat market)."""
        detector = VolatilityRegimeDetector()
        price = 100.0
        
        candles = [
            {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "time": 1000000 + (i * 3600)
            }
            for i in range(25)
        ]
        
        result = detector.analyze("BTC", candles)
        
        # Flat market should show LOW volatility
        assert result["atr"] == 0
        assert result["bb_width"] == 0
    
    def test_timestamp_handling_unix_ms(self):
        """Test timestamp handling with Unix milliseconds."""
        detector = VolatilityRegimeDetector()
        candles = [
            {
                "open": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "close": 102 + i,
                "time": 1645000000000 + (i * 3600000)  # Unix ms
            }
            for i in range(25)
        ]
        
        result = detector.analyze("BTC", candles)
        
        assert "timestamp" in result
        assert isinstance(result["timestamp"], str)
    
    def test_timestamp_handling_string(self):
        """Test timestamp handling with string."""
        detector = VolatilityRegimeDetector()
        candles = [
            {
                "open": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "close": 102 + i,
                "time": "2024-01-15T12:00:00Z"
            }
            for i in range(25)
        ]
        
        result = detector.analyze("BTC", candles)
        
        assert result["timestamp"] == "2024-01-15T12:00:00Z"


class TestOutputFormat:
    """Test output format and data types."""
    
    def create_standard_candles(self) -> list:
        """Create standard test candles."""
        return [
            {
                "open": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "close": 102 + i,
                "time": 1000000 + (i * 3600)
            }
            for i in range(25)
        ]
    
    def test_output_contains_all_keys(self):
        """Test that all required keys are in output."""
        detector = VolatilityRegimeDetector()
        candles = self.create_standard_candles()
        result = detector.analyze("BTC", candles)
        
        required_keys = {"regime", "atr", "bb_width", "hist_vol_percentile", "timestamp"}
        assert required_keys.issubset(result.keys())
    
    def test_output_types(self):
        """Test that output values have correct types."""
        detector = VolatilityRegimeDetector()
        candles = self.create_standard_candles()
        result = detector.analyze("BTC", candles)
        
        assert isinstance(result["regime"], str)
        assert isinstance(result["atr"], float)
        assert isinstance(result["bb_width"], float)
        assert isinstance(result["hist_vol_percentile"], float)
        assert isinstance(result["timestamp"], str)
    
    def test_regime_is_valid_value(self):
        """Test that regime is one of the valid values."""
        detector = VolatilityRegimeDetector()
        candles = self.create_standard_candles()
        
        for _ in range(5):
            result = detector.analyze("BTC", candles)
            assert result["regime"] in ["LOW", "MEDIUM", "HIGH"]
    
    def test_percentile_in_valid_range(self):
        """Test that percentile is between 0 and 100."""
        detector = VolatilityRegimeDetector()
        candles = self.create_standard_candles()
        
        for _ in range(5):
            result = detector.analyze("BTC", candles)
            assert 0 <= result["hist_vol_percentile"] <= 100


class TestMultipleAnalyses:
    """Test detector behavior across multiple analyses."""
    
    def test_history_accumulation_across_analyses(self):
        """Test that volatility history accumulates correctly."""
        detector = VolatilityRegimeDetector()
        
        candles_set_1 = [
            {
                "open": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "close": 102 + i,
                "time": 1000000 + (i * 3600)
            }
            for i in range(25)
        ]
        
        candles_set_2 = [
            {
                "open": 150 + i * 2,
                "high": 160 + i * 2,
                "low": 140 + i * 2,
                "close": 155 + i * 2,
                "time": 2000000 + (i * 3600)
            }
            for i in range(25)
        ]
        
        result1 = detector.analyze("BTC", candles_set_1)
        initial_history_len = len(detector.vol_history)
        
        result2 = detector.analyze("BTC", candles_set_2)
        
        # History should have grown
        assert len(detector.vol_history) >= initial_history_len
        assert len(detector.vol_history) > 1
    
    def test_consecutive_analyses_valid_results(self):
        """Test that consecutive analyses produce valid results."""
        detector = VolatilityRegimeDetector()
        
        for run in range(3):
            candles = [
                {
                    "open": 100 + i + (run * 10),
                    "high": 105 + i + (run * 10),
                    "low": 95 + i + (run * 10),
                    "close": 102 + i + (run * 10),
                    "time": 1000000 + (run * 1000000) + (i * 3600)
                }
                for i in range(25)
            ]
            
            result = detector.analyze("BTC", candles)
            
            assert result["regime"] in ["LOW", "MEDIUM", "HIGH"]
            assert result["atr"] >= 0
            assert result["bb_width"] >= 0


if __name__ == "__main__":
    # Run tests with coverage
    pytest.main([__file__, "-v", "--tb=short", "--cov=volatility_regime"])
