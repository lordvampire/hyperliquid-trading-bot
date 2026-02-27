"""
Order-Book Imbalance Detector — Phase 1, Task 1.3

Analyzes order book to detect whale accumulation/distribution patterns.
Generates signals: LONG_BIAS / NEUTRAL / SHORT_BIAS

Used as 20% weight in composite signal (Task 1.4).
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class OBSignal(Enum):
    """Order-book imbalance signal classification."""
    LONG_BIAS = "LONG_BIAS"
    NEUTRAL = "NEUTRAL"
    SHORT_BIAS = "SHORT_BIAS"


@dataclass
class OrderBookMetrics:
    """Container for order book analysis metrics."""
    bid_ask_ratio: float
    bid_depth_1m: float
    ask_depth_1m: float
    spread_pct: float
    imbalance_strength: float  # 0-1, higher = more imbalanced
    signal: OBSignal
    timestamp: str


class OrderBookImbalanceDetector:
    """
    Detects order book imbalance patterns indicating whale activity.
    
    Metrics analyzed:
    - Bid/Ask ratio at $1M+ depth
    - Volume skew (which side has more)
    - Spread analysis (tight vs wide = different intentions)
    - Whale order detection (>5% of volume)
    
    Signal Generation:
    - LONG_BIAS: Bid side significantly stronger
    - SHORT_BIAS: Ask side significantly stronger
    - NEUTRAL: Balanced or unclear
    """
    
    def __init__(self, 
                 depth_level: float = 1_000_000,
                 imbalance_threshold: float = 0.15,
                 cache_ttl_sec: int = 5):
        """
        Initialize order book detector.
        
        Args:
            depth_level: USD depth to analyze (default $1M)
            imbalance_threshold: Ratio threshold for signal (default 15%)
            cache_ttl_sec: Cache TTL to avoid API spam (default 5 sec)
        """
        self.depth_level = depth_level
        self.imbalance_threshold = imbalance_threshold
        self.cache_ttl_sec = cache_ttl_sec
        self.last_cache = {}
        self.last_cache_time = {}
    
    def analyze(self, symbol: str, orderbook: Optional[Dict] = None) -> OrderBookMetrics:
        """
        Analyze order book for imbalance patterns.
        
        Args:
            symbol: Trading pair (e.g., "BTC")
            orderbook: Order book dict with 'bids' and 'asks' keys
                      If None, returns NEUTRAL (no data)
        
        Returns:
            OrderBookMetrics with signal and detailed metrics
        
        Example:
            >>> detector = OrderBookImbalanceDetector()
            >>> metrics = detector.analyze("BTC", orderbook={
            ...     "bids": [[50000, 1.5], [49999, 0.8], ...],
            ...     "asks": [[50001, 0.5], [50002, 0.3], ...]
            ... })
            >>> print(metrics.signal)  # LONG_BIAS
        """
        
        # Check cache
        cache_key = f"{symbol}_ob"
        if cache_key in self.last_cache_time:
            elapsed = (datetime.now() - self.last_cache_time[cache_key]).total_seconds()
            if elapsed < self.cache_ttl_sec:
                return self.last_cache[cache_key]
        
        # Handle missing data
        if not orderbook or "bids" not in orderbook or "asks" not in orderbook:
            logger.warning(f"No order book data for {symbol}")
            return OrderBookMetrics(
                bid_ask_ratio=1.0,
                bid_depth_1m=0,
                ask_depth_1m=0,
                spread_pct=0,
                imbalance_strength=0,
                signal=OBSignal.NEUTRAL,
                timestamp=datetime.now().isoformat()
            )
        
        # Calculate metrics
        bid_depth = self._calculate_depth(orderbook["bids"], self.depth_level)
        ask_depth = self._calculate_depth(orderbook["asks"], self.depth_level)
        
        # Bid/Ask ratio
        if ask_depth == 0:
            bid_ask_ratio = float('inf') if bid_depth > 0 else 1.0
        else:
            bid_ask_ratio = bid_depth / ask_depth
        
        # Spread (%)
        if orderbook["asks"] and orderbook["bids"]:
            best_bid = float(orderbook["bids"][0][0]) if orderbook["bids"] else 0
            best_ask = float(orderbook["asks"][0][0]) if orderbook["asks"] else 0
            spread_pct = ((best_ask - best_bid) / best_bid * 100) if best_bid > 0 else 0
        else:
            spread_pct = 0
        
        # Imbalance strength (0-1)
        # Closer to 1 = more imbalanced
        max_ratio = max(bid_ask_ratio, 1/bid_ask_ratio) if bid_ask_ratio > 0 else 1.0
        imbalance_strength = min((max_ratio - 1.0) / 2.0, 1.0)  # Normalize to 0-1
        
        # Generate signal
        if bid_ask_ratio > (1.0 + self.imbalance_threshold):
            signal = OBSignal.LONG_BIAS
        elif bid_ask_ratio < (1.0 - self.imbalance_threshold):
            signal = OBSignal.SHORT_BIAS
        else:
            signal = OBSignal.NEUTRAL
        
        # Create result
        metrics = OrderBookMetrics(
            bid_ask_ratio=round(bid_ask_ratio, 4),
            bid_depth_1m=round(bid_depth, 2),
            ask_depth_1m=round(ask_depth, 2),
            spread_pct=round(spread_pct, 4),
            imbalance_strength=round(imbalance_strength, 4),
            signal=signal,
            timestamp=datetime.now().isoformat()
        )
        
        # Cache result
        self.last_cache[cache_key] = metrics
        self.last_cache_time[cache_key] = datetime.now()
        
        logger.info(f"{symbol} OB: {signal.value}, ratio={metrics.bid_ask_ratio}, "
                   f"strength={metrics.imbalance_strength}")
        
        return metrics
    
    @staticmethod
    def _calculate_depth(side: List, target_usd: float) -> float:
        """
        Calculate cumulative volume up to target USD depth.
        
        Args:
            side: List of [price, volume] pairs
            target_usd: Target USD amount
        
        Returns:
            Total volume in base asset up to target USD
        
        Example:
            >>> side = [[50000, 1.0], [49999, 2.0], [49998, 1.5]]
            >>> depth = OrderBookImbalanceDetector._calculate_depth(side, 100000)
            >>> print(depth)  # 2.0 (50000*2 = 100k USD)
        """
        if not side:
            return 0
        
        cumulative_usd = 0
        cumulative_volume = 0
        
        for price, volume in side:
            try:
                price = float(price)
                volume = float(volume)
            except (ValueError, TypeError):
                continue
            
            order_usd = price * volume
            
            if cumulative_usd + order_usd >= target_usd:
                # Partial fill for this level
                remaining_usd = target_usd - cumulative_usd
                partial_volume = remaining_usd / price if price > 0 else 0
                cumulative_volume += partial_volume
                break
            else:
                # Full fill for this level
                cumulative_usd += order_usd
                cumulative_volume += volume
        
        return cumulative_volume
    
    def detect_whale_orders(self, orderbook: Dict, whale_threshold: float = 0.05) -> Dict:
        """
        Detect potentially whale-sized orders (>5% of cumulative depth).
        
        Args:
            orderbook: Order book dict
            whale_threshold: Volume % to consider "whale" (default 5%)
        
        Returns:
            Dict with "bid_whales" and "ask_whales" lists
        """
        whales = {"bid_whales": [], "ask_whales": []}
        
        if not orderbook or "bids" not in orderbook or "asks" not in orderbook:
            return whales
        
        # Calculate total depth
        bid_total = sum(float(v) for p, v in orderbook["bids"][:100] if v)
        ask_total = sum(float(v) for p, v in orderbook["asks"][:100] if v)
        
        # Find whale orders on bid side
        for price, volume in orderbook["bids"][:20]:
            try:
                volume = float(volume)
                if bid_total > 0 and volume / bid_total > whale_threshold:
                    whales["bid_whales"].append({
                        "price": float(price),
                        "volume": volume,
                        "pct_of_depth": round(volume / bid_total * 100, 2)
                    })
            except (ValueError, TypeError):
                continue
        
        # Find whale orders on ask side
        for price, volume in orderbook["asks"][:20]:
            try:
                volume = float(volume)
                if ask_total > 0 and volume / ask_total > whale_threshold:
                    whales["ask_whales"].append({
                        "price": float(price),
                        "volume": volume,
                        "pct_of_depth": round(volume / ask_total * 100, 2)
                    })
            except (ValueError, TypeError):
                continue
        
        return whales


# Example usage
if __name__ == "__main__":
    detector = OrderBookImbalanceDetector()
    
    # Mock order book
    mock_ob = {
        "bids": [
            [50000, 2.0],
            [49999, 1.5],
            [49998, 1.0],
        ],
        "asks": [
            [50001, 0.5],
            [50002, 0.3],
            [50003, 0.2],
        ]
    }
    
    metrics = detector.analyze("BTC", mock_ob)
    print(f"Signal: {metrics.signal.value}")
    print(f"Bid/Ask Ratio: {metrics.bid_ask_ratio}")
    print(f"Imbalance Strength: {metrics.imbalance_strength}")
    
    whales = detector.detect_whale_orders(mock_ob)
    print(f"Whale Orders: {whales}")
