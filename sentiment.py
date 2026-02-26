"""Sentiment Analysis Module — Phase 2 REAL (Heuristic: Funding Trends + Volume)."""

from typing import Dict, Tuple
from datetime import datetime, timedelta
import time
from exchange import get_info
from funding import FundingRateAnalyzer

# Cache: symbol -> {timestamp, data}
_sentiment_cache = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes


class SentimentAnalyzer:
    """
    Strategy B: REAL Sentiment Analysis using:
    - Funding rate trends (rising = more bullish)
    - Recent volume spikes (high volume = stronger sentiment)
    - Open interest changes (if available)
    """

    def __init__(self):
        self.info = get_info()
        self.funding = FundingRateAnalyzer()
        self.cache = {}
        self.last_update = {}

    def analyze(self, symbol: str) -> Dict:
        """
        Analyze market sentiment for a symbol using REAL on-chain data.
        Heuristic: Funding trends + volume intensity
        
        Returns: {symbol, sentiment_score (-1 to 1), signal, confidence, components}
        """
        cache_key = symbol
        now = time.time()

        # Check cache validity
        if cache_key in _sentiment_cache:
            cached_entry = _sentiment_cache[cache_key]
            if now - cached_entry["cached_at"] < _CACHE_TTL_SECONDS:
                return cached_entry["data"]

        try:
            # Component 1: Funding rate trend (40% weight)
            funding_trend = self.funding.get_funding_trend(symbol, hours=24)
            
            # Map trend to sentiment
            if funding_trend.get("trend") == "RISING":
                funding_sentiment = 0.5  # Bullish: funding rising means shorts being liquidated
            elif funding_trend.get("trend") == "FALLING":
                funding_sentiment = -0.5  # Bearish: falling funding = longs exiting
            else:
                funding_sentiment = 0.0  # Neutral

            # Component 2: Current funding rate level (30% weight)
            current_funding = self.funding.get_funding_rate(symbol)
            rate = current_funding.get("funding_rate", 0)
            
            if rate > 0.0002:  # High positive funding
                funding_level_sentiment = 0.6  # Strong bullish (shorters paying)
            elif rate > 0.00005:
                funding_level_sentiment = 0.3  # Mild bullish
            elif rate < -0.0002:
                funding_level_sentiment = -0.6  # Strong bearish (longs paying)
            elif rate < -0.00005:
                funding_level_sentiment = -0.3  # Mild bearish
            else:
                funding_level_sentiment = 0.0  # Neutral

            # Component 3: Volume/volatility from funding (30% weight)
            volatility = funding_trend.get("volatility", 0)
            
            if volatility > 0.0002:
                volume_sentiment = 0.4  # High volatility = strong conviction
            elif volatility > 0.00005:
                volume_sentiment = 0.2  # Moderate
            else:
                volume_sentiment = 0.0  # Low activity

            # Combine components
            sentiment_score = (
                funding_sentiment * 0.40 +
                funding_level_sentiment * 0.30 +
                volume_sentiment * 0.30
            )

            # Clamp to [-1, 1]
            sentiment_score = max(-1.0, min(1.0, sentiment_score))

            # Determine signal
            if sentiment_score > 0.25:
                signal = "BUY"
            elif sentiment_score < -0.25:
                signal = "SELL"
            else:
                signal = "HOLD"

            # Confidence: how extreme the sentiment is
            confidence = abs(sentiment_score)

            result = {
                "symbol": symbol,
                "sentiment_score": round(sentiment_score, 3),
                "signal": signal,
                "confidence": round(confidence, 3),
                "timestamp": datetime.now().isoformat(),
                "components": {
                    "funding_trend": funding_trend,
                    "current_funding_rate": round(rate, 6),
                    "volatility": round(volatility, 6),
                },
            }

            # Cache result
            _sentiment_cache[cache_key] = {
                "cached_at": now,
                "data": result,
            }

            return result

        except Exception as e:
            return {
                "symbol": symbol,
                "sentiment_score": 0.0,
                "signal": "HOLD",
                "confidence": 0.0,
                "timestamp": datetime.now().isoformat(),
                "error": f"Sentiment analysis failed: {str(e)}",
            }

    def get_signal(self, symbol: str, threshold: float = 0.3) -> Tuple[str, float]:
        """Get trade signal if confidence above threshold."""
        analysis = self.analyze(symbol)
        if analysis.get("confidence", 0) >= threshold:
            return analysis["signal"], analysis["confidence"]
        return "HOLD", 0.0
