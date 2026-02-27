"""
Volatility Regime Detector for Hyperliquid Trading Bot

Classifies market volatility into three regimes: LOW, MEDIUM, HIGH
Based on ATR, Bollinger Band Width, and historical volatility percentiles.
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone
import numpy as np
from statistics import stdev, mean


class VolatilityRegimeDetector:
    """
    Detects market volatility regimes using multiple volatility metrics.
    
    Metrics:
    - ATR(20): Average True Range over 20 periods
    - Bollinger Band Width: (Upper - Lower) / SMA(20)
    - Historical Volatility: Standard deviation of log returns
    - Percentile: Current vol vs 252-candle history
    
    Regime Classification:
    - LOW: Percentile < 25th
    - HIGH: Percentile > 75th
    - MEDIUM: 25th <= Percentile <= 75th
    """
    
    PERCENTILE_LOW = 25.0
    PERCENTILE_HIGH = 75.0
    HISTORY_LENGTH = 252  # 1 year of candles
    
    def __init__(self, lookback: int = 20):
        """
        Initialize the volatility regime detector.
        
        Args:
            lookback: Period for ATR and Bollinger Bands (default: 20)
        """
        self.lookback = lookback
        self.vol_history = []  # Store historical volatility for percentile calculation
    
    def analyze(self, symbol: str, candles: List[Dict]) -> Dict:
        """
        Analyze volatility regime for a given symbol and candle data.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC', 'ETH')
            candles: List of candle dicts with keys: 'open', 'high', 'low', 'close', 'time'
                    Expected format: [{'open': float, 'high': float, 'low': float, 'close': float, 'time': int/str}, ...]
        
        Returns:
            Dict with keys:
            - regime: "LOW" | "MEDIUM" | "HIGH"
            - atr: ATR(20) value
            - bb_width: Bollinger Band Width
            - hist_vol_percentile: Percentile of current volatility vs history
            - timestamp: ISO timestamp of analysis
        """
        if not candles or len(candles) < self.lookback:
            raise ValueError(f"Insufficient candle data. Need at least {self.lookback} candles, got {len(candles)}")
        
        # Calculate metrics
        atr = self._calculate_atr(candles)
        bb_width = self._calculate_bb_width(candles)
        hist_vol = self._calculate_historical_volatility(candles)
        percentile = self._calculate_percentile(hist_vol)
        
        # Determine regime
        regime = self._classify_regime(percentile)
        
        # Get timestamp from last candle
        timestamp = self._get_timestamp(candles[-1])
        
        return {
            "regime": regime,
            "atr": round(atr, 8),
            "bb_width": round(bb_width, 8),
            "hist_vol_percentile": round(percentile, 2),
            "timestamp": timestamp
        }
    
    def _calculate_atr(self, candles: List[Dict]) -> float:
        """
        Calculate Average True Range (ATR) over lookback period.
        
        ATR = SMA of True Range over lookback periods
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        """
        true_ranges = []
        
        for i in range(len(candles)):
            high = float(candles[i]['high'])
            low = float(candles[i]['low'])
            
            if i == 0:
                tr = high - low
            else:
                prev_close = float(candles[i - 1]['close'])
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
            
            true_ranges.append(tr)
        
        # Use only the last lookback periods for ATR
        atr_periods = true_ranges[-self.lookback:]
        return mean(atr_periods) if atr_periods else 0.0
    
    def _calculate_bb_width(self, candles: List[Dict]) -> float:
        """
        Calculate Bollinger Band Width.
        
        BB_Width = (Upper Band - Lower Band) / SMA(20)
        Where:
        - Upper Band = SMA + (2 * StdDev)
        - Lower Band = SMA - (2 * StdDev)
        """
        closes = [float(c['close']) for c in candles[-self.lookback:]]
        
        if len(closes) < self.lookback:
            closes = [float(c['close']) for c in candles]
        
        sma = mean(closes)
        std_dev = stdev(closes) if len(closes) > 1 else 0.0
        
        upper_band = sma + (2 * std_dev)
        lower_band = sma - (2 * std_dev)
        
        bb_width = upper_band - lower_band
        
        if sma == 0:
            return 0.0
        
        return bb_width / sma
    
    def _calculate_historical_volatility(self, candles: List[Dict]) -> float:
        """
        Calculate historical volatility as standard deviation of log returns.
        
        Historical Volatility = StdDev(ln(close[i] / close[i-1]))
        """
        closes = [float(c['close']) for c in candles]
        
        if len(closes) < 2:
            return 0.0
        
        log_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                log_return = np.log(closes[i] / closes[i - 1])
                log_returns.append(log_return)
        
        if not log_returns or len(log_returns) < 2:
            return 0.0
        
        volatility = stdev(log_returns)
        return volatility
    
    def _calculate_percentile(self, current_vol: float) -> float:
        """
        Calculate percentile rank of current volatility vs historical volatility.
        
        Updates history with current volatility and calculates percentile.
        Maintains history of up to HISTORY_LENGTH values.
        """
        # Add current volatility to history
        self.vol_history.append(current_vol)
        
        # Maintain history length
        if len(self.vol_history) > self.HISTORY_LENGTH:
            self.vol_history.pop(0)
        
        # If not enough history, return 50th percentile
        if len(self.vol_history) < 2:
            return 50.0
        
        # Count how many values are less than current
        lower_count = sum(1 for v in self.vol_history[:-1] if v < current_vol)
        percentile = (lower_count / (len(self.vol_history) - 1)) * 100
        
        return percentile
    
    def _classify_regime(self, percentile: float) -> str:
        """
        Classify volatility regime based on percentile.
        
        LOW: percentile < 25
        HIGH: percentile > 75
        MEDIUM: 25 <= percentile <= 75
        """
        if percentile < self.PERCENTILE_LOW:
            return "LOW"
        elif percentile > self.PERCENTILE_HIGH:
            return "HIGH"
        else:
            return "MEDIUM"
    
    def _get_timestamp(self, candle: Dict) -> str:
        """Extract and format timestamp from candle."""
        time_val = candle.get('time')
        
        if isinstance(time_val, str):
            # Already a string, return as-is
            return time_val
        elif isinstance(time_val, (int, float)):
            # Unix timestamp in milliseconds or seconds
            if time_val > 10000000000:  # Likely milliseconds
                time_val = time_val / 1000
            try:
                return datetime.fromtimestamp(time_val, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except (ValueError, OSError):
                return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    
    def reset_history(self):
        """Reset volatility history. Useful for testing."""
        self.vol_history = []
