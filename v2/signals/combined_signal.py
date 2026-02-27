"""
Composite Signal Combiner — Phase 1, Task 1.4
Combines all 4 signals: Vol (40%) + Momentum (30%) + OB (20%) + Funding (10%)
Final signal: BUY / SELL / HOLD
"""

import logging
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CompositeSignal(Enum):
    """Final composite signal classification."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class CompositeMetrics:
    """Container for composite signal analysis."""
    signal: CompositeSignal
    combined_score: float  # -1.0 to +1.0
    confidence: float  # 0 to 1.0
    component_scores: Dict  # Individual component scores
    timestamp: str


class CombinedSignalGenerator:
    """
    Combines 4 signals with weighted scoring.
    
    Weights:
    - 40%: Volatility-Regime (when to trade)
    - 30%: Price-Momentum (price direction)
    - 20%: Order-Book Imbalance (market structure)
    - 10%: Funding-Rate (supporting evidence)
    
    Signal Generation:
    - BUY if combined_score > +0.35
    - SELL if combined_score < -0.35
    - HOLD otherwise
    """
    
    def __init__(self,
                 vol_weight: float = 0.40,
                 momentum_weight: float = 0.30,
                 ob_weight: float = 0.20,
                 funding_weight: float = 0.10,
                 signal_threshold: float = 0.35):
        """
        Initialize combined signal generator.
        
        Args:
            vol_weight: Weight for volatility regime (default 40%)
            momentum_weight: Weight for price momentum (default 30%)
            ob_weight: Weight for order-book imbalance (default 20%)
            funding_weight: Weight for funding rates (default 10%)
            signal_threshold: Threshold for BUY/SELL signals (default 0.35)
        """
        # Validate weights sum to 1.0
        total_weight = vol_weight + momentum_weight + ob_weight + funding_weight
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
        
        self.vol_weight = vol_weight
        self.momentum_weight = momentum_weight
        self.ob_weight = ob_weight
        self.funding_weight = funding_weight
        self.signal_threshold = signal_threshold
    
    def combine(self,
                vol_signal: float,
                momentum_signal: float,
                ob_signal: float,
                funding_signal: float) -> CompositeMetrics:
        """
        Combine all 4 signals into final signal.
        
        Args:
            vol_signal: Volatility regime signal (-1.0 to +1.0)
            momentum_signal: Price momentum signal (-1.0 to +1.0)
            ob_signal: Order-book imbalance signal (-1.0 to +1.0)
            funding_signal: Funding rates signal (-1.0 to +1.0)
        
        Returns:
            CompositeMetrics with combined signal and scores
        
        Example:
            >>> gen = CombinedSignalGenerator()
            >>> metrics = gen.combine(
            ...     vol_signal=0.5,      # Medium volatility
            ...     momentum_signal=0.8,  # Strong up momentum
            ...     ob_signal=0.6,       # Bullish order book
            ...     funding_signal=0.2   # Slight long bias
            ... )
            >>> print(metrics.signal)  # BUY
        """
        
        # Weighted combination
        combined_score = (
            self.vol_weight * vol_signal +
            self.momentum_weight * momentum_signal +
            self.ob_weight * ob_signal +
            self.funding_weight * funding_signal
        )
        
        # Confidence = absolute value of combined score
        confidence = min(abs(combined_score), 1.0)
        
        # Final signal
        if combined_score > self.signal_threshold:
            signal = CompositeSignal.BUY
        elif combined_score < -self.signal_threshold:
            signal = CompositeSignal.SELL
        else:
            signal = CompositeSignal.HOLD
        
        # Component breakdown
        component_scores = {
            "vol_regime": vol_signal,
            "momentum": momentum_signal,
            "orderbook_imbalance": ob_signal,
            "funding_rates": funding_signal,
            "weighted_scores": {
                "vol": self.vol_weight * vol_signal,
                "momentum": self.momentum_weight * momentum_signal,
                "ob": self.ob_weight * ob_signal,
                "funding": self.funding_weight * funding_signal
            }
        }
        
        metrics = CompositeMetrics(
            signal=signal,
            combined_score=round(combined_score, 4),
            confidence=round(confidence, 4),
            component_scores=component_scores,
            timestamp=datetime.now().isoformat()
        )
        
        logger.info(f"Composite: {signal.value}, score={metrics.combined_score}, "
                   f"confidence={metrics.confidence}")
        
        return metrics
    
    def analyze_from_objects(self,
                            vol_detector_output: Dict,
                            momentum_detector_output: Dict,
                            ob_detector_output: Dict,
                            funding_detector_output: Dict) -> CompositeMetrics:
        """
        Combine signals from detector objects.
        
        Args:
            vol_detector_output: VolatilityRegimeDetector output
            momentum_detector_output: PriceMomentumDetector output
            ob_detector_output: OrderBookImbalanceDetector output
            funding_detector_output: FundingRateDetector output
        
        Returns:
            CompositeMetrics with combined signal
        """
        
        # Extract signals from detector outputs
        vol_signal = self._signal_to_numeric(
            vol_detector_output.get("regime"),
            mapping={"LOW": -0.5, "MEDIUM": 0.0, "HIGH": 0.5}
        )
        
        momentum_signal = self._signal_to_numeric(
            momentum_detector_output.get("signal"),
            mapping={"STRONG_DOWN": -1.0, "NEUTRAL": 0.0, "STRONG_UP": 1.0}
        )
        
        ob_signal = self._signal_to_numeric(
            ob_detector_output.get("signal"),
            mapping={"SHORT_BIAS": -1.0, "NEUTRAL": 0.0, "LONG_BIAS": 1.0}
        )
        
        funding_signal = self._signal_to_numeric(
            funding_detector_output.get("signal"),
            mapping={"SHORT": -0.5, "NEUTRAL": 0.0, "LONG": 0.5}
        )
        
        return self.combine(vol_signal, momentum_signal, ob_signal, funding_signal)
    
    @staticmethod
    def _signal_to_numeric(signal: Optional[str], mapping: Dict) -> float:
        """Convert signal string to numeric value."""
        if signal is None:
            return 0.0
        return mapping.get(signal, 0.0)


# Example usage
if __name__ == "__main__":
    gen = CombinedSignalGenerator()
    
    # Scenario: Bullish alignment
    metrics = gen.combine(
        vol_signal=0.3,       # Medium volatility
        momentum_signal=0.8,   # Strong up
        ob_signal=0.6,        # Bullish OB
        funding_signal=0.2    # Slight long
    )
    print(f"Signal: {metrics.signal.value}")
    print(f"Score: {metrics.combined_score}")
    print(f"Confidence: {metrics.confidence}")
