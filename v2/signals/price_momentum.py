"""
Price Momentum Detector

Uses RSI(14), MACD + signal line, and Rate of Change (ROC) to generate
momentum signals: STRONG_UP, NEUTRAL, or STRONG_DOWN.
"""

from enum import Enum
from typing import Optional, List
import numpy as np
import pandas as pd


class MomentumSignal(str, Enum):
    """Momentum signal states"""
    STRONG_UP = "STRONG_UP"
    NEUTRAL = "NEUTRAL"
    STRONG_DOWN = "STRONG_DOWN"


class PriceMomentumDetector:
    """
    Detects price momentum using technical indicators:
    - RSI(14): Overbought/oversold detection
    - MACD + Signal line: Trend confirmation
    - Rate of Change (ROC): Momentum strength
    
    Generates signals: STRONG_UP, NEUTRAL, STRONG_DOWN
    """
    
    def __init__(
        self,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        roc_period: int = 12,
        roc_threshold: float = 0.005,  # 0.5%
    ):
        """
        Initialize PriceMomentumDetector.
        
        Args:
            rsi_period: Period for RSI calculation (default 14)
            rsi_overbought: RSI overbought threshold (default 70)
            rsi_oversold: RSI oversold threshold (default 30)
            macd_fast: Fast EMA period for MACD (default 12)
            macd_slow: Slow EMA period for MACD (default 26)
            macd_signal: Signal line EMA period (default 9)
            roc_period: Period for Rate of Change calculation (default 12)
            roc_threshold: Minimum ROC threshold for strong signals (default 0.005)
        """
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        
        self.roc_period = roc_period
        self.roc_threshold = roc_threshold
        
        # Store last calculated values for analysis
        self.last_rsi: Optional[float] = None
        self.last_macd: Optional[float] = None
        self.last_macd_signal: Optional[float] = None
        self.last_roc: Optional[float] = None
    
    def _calculate_rsi(self, prices: List[float]) -> Optional[float]:
        """
        Calculate RSI(period) for the given prices.
        
        Args:
            prices: List of closing prices
            
        Returns:
            RSI value or None if insufficient data
        """
        if len(prices) < self.rsi_period + 1:
            return None
        
        prices_arr = np.array(prices, dtype=np.float64)
        deltas = np.diff(prices_arr)
        seed = deltas[:self.rsi_period + 1]
        
        up = seed[seed >= 0].sum() / self.rsi_period
        down = -seed[seed < 0].sum() / self.rsi_period
        
        rs = np.zeros_like(prices_arr)
        rs[:self.rsi_period] = 100. - 100. / (1. + (up / down)) if down != 0 else 100.
        
        for i in range(self.rsi_period, len(prices_arr)):
            delta = deltas[i - 1]
            
            if delta >= 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta
            
            up = (up * (self.rsi_period - 1) + upval) / self.rsi_period
            down = (down * (self.rsi_period - 1) + downval) / self.rsi_period
            
            rs[i] = 100. - 100. / (1. + (up / down)) if down != 0 else 100.
        
        return float(rs[-1])
    
    def _calculate_macd(self, prices: List[float]) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate MACD and signal line.
        
        Args:
            prices: List of closing prices
            
        Returns:
            Tuple of (MACD value, Signal line value) or (None, None) if insufficient data
        """
        if len(prices) < self.macd_slow + self.macd_signal:
            return None, None
        
        prices_arr = np.array(prices, dtype=np.float64)
        
        # Calculate EMAs
        ema_fast = self._calculate_ema(prices_arr, self.macd_fast)
        ema_slow = self._calculate_ema(prices_arr, self.macd_slow)
        
        if ema_fast is None or ema_slow is None:
            return None, None
        
        # MACD line
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD)
        # We need enough MACD values to calculate the signal line
        if len(prices) < self.macd_slow + self.macd_signal:
            return None, None
        
        # Build MACD line for all values
        macd_values = []
        for i in range(self.macd_slow - 1, len(prices_arr)):
            ema_f = self._calculate_ema(prices_arr[:i + 1], self.macd_fast)
            ema_s = self._calculate_ema(prices_arr[:i + 1], self.macd_slow)
            if ema_f is not None and ema_s is not None:
                macd_values.append(ema_f - ema_s)
        
        if len(macd_values) < self.macd_signal:
            return None, None
        
        # Signal line is EMA of MACD values
        macd_arr = np.array(macd_values, dtype=np.float64)
        signal_line = self._calculate_ema(macd_arr, self.macd_signal)
        
        if signal_line is None:
            return None, None
        
        return float(macd_values[-1]), float(signal_line)
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> Optional[float]:
        """
        Calculate Exponential Moving Average (EMA).
        
        Args:
            data: Array of values
            period: EMA period
            
        Returns:
            EMA value or None if insufficient data
        """
        if len(data) < period:
            return None
        
        alpha = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        
        for i in range(period, len(data)):
            ema = data[i] * alpha + ema * (1 - alpha)
        
        return float(ema)
    
    def _calculate_roc(self, prices: List[float]) -> Optional[float]:
        """
        Calculate Rate of Change (ROC).
        
        Args:
            prices: List of closing prices
            
        Returns:
            ROC value or None if insufficient data
        """
        if len(prices) < self.roc_period + 1:
            return None
        
        current_price = prices[-1]
        previous_price = prices[-(self.roc_period + 1)]
        
        if previous_price == 0:
            return None
        
        roc = (current_price - previous_price) / previous_price
        return float(roc)
    
    def detect(self, prices: List[float]) -> MomentumSignal:
        """
        Detect momentum signal based on RSI, MACD, and ROC.
        
        Args:
            prices: List of closing prices (at least 27 prices needed)
            
        Returns:
            MomentumSignal: STRONG_UP, NEUTRAL, or STRONG_DOWN
        """
        if not prices or len(prices) < max(self.macd_slow + self.macd_signal, self.rsi_period + 1):
            return MomentumSignal.NEUTRAL
        
        # Calculate indicators
        rsi = self._calculate_rsi(prices)
        macd, macd_signal = self._calculate_macd(prices)
        roc = self._calculate_roc(prices)
        
        # Store last values
        self.last_rsi = rsi
        self.last_macd = macd
        self.last_macd_signal = macd_signal
        self.last_roc = roc
        
        # Handle insufficient data
        if rsi is None or macd is None or macd_signal is None or roc is None:
            return MomentumSignal.NEUTRAL
        
        # Signal logic
        # STRONG_UP: RSI > 50 AND MACD > signal AND ROC > threshold
        if rsi > 50 and macd > macd_signal and roc > self.roc_threshold:
            return MomentumSignal.STRONG_UP
        
        # STRONG_DOWN: RSI < 50 AND MACD < signal AND ROC < -threshold
        if rsi < 50 and macd < macd_signal and roc < -self.roc_threshold:
            return MomentumSignal.STRONG_DOWN
        
        # Everything else is NEUTRAL
        return MomentumSignal.NEUTRAL
    
    def get_indicators(self, prices: List[float]) -> dict:
        """
        Get current indicator values.
        
        Args:
            prices: List of closing prices
            
        Returns:
            Dictionary with RSI, MACD, Signal, and ROC values
        """
        self.detect(prices)  # Update cached values
        
        return {
            "rsi": self.last_rsi,
            "macd": self.last_macd,
            "macd_signal": self.last_macd_signal,
            "roc": self.last_roc,
        }
