"""Strategy B: Trading Assistant + Sentiment — Phase 2."""

from typing import Dict, List, Tuple
from datetime import datetime
from sentiment import SentimentAnalyzer
from funding import FundingRateAnalyzer


class StrategyB:
    """
    Strategy B: Combines sentiment analysis + funding rates.
    - Sentiment gives directional bias
    - Funding rates give market inefficiency signal
    - Entry: when both align
    - Exit: when sentiment reverses or target profit hit
    """

    def __init__(self):
        self.sentiment = SentimentAnalyzer()
        self.funding = FundingRateAnalyzer()
        self.open_positions = {}  # symbol -> {entry_price, size, entry_time}

    def get_next_signal(self, symbol: str) -> Dict:
        """
        Generate trading signal for a symbol.
        Combines sentiment + funding rates.
        """
        sentiment = self.sentiment.analyze(symbol)
        funding = self.funding.get_funding_signal(symbol)

        # Scoring logic
        sentiment_score = 1.0 if sentiment["signal"] == "BUY" else (-1.0 if sentiment["signal"] == "SELL" else 0)
        funding_score = 1.0 if funding["signal"] == "LONG" else (-1.0 if funding["signal"] == "SHORT" else 0)

        # Combined signal
        combined_score = (sentiment_score * sentiment["confidence"] + funding_score * funding["strength"]) / 2

        # Determine trade signal (confidence threshold: 0.05 for aggressive trading)
        if combined_score > 0.05:
            trade_signal = "BUY"
            confidence = combined_score
        elif combined_score < -0.05:
            trade_signal = "SELL"
            confidence = abs(combined_score)
        else:
            trade_signal = "HOLD"
            confidence = 0.0

        return {
            "symbol": symbol,
            "signal": trade_signal,
            "confidence": round(confidence, 3),
            "sentiment": sentiment,
            "funding": funding,
            "timestamp": datetime.now().isoformat(),
        }

    def execute_trade(self, symbol: str, signal: Dict) -> Dict:
        """
        Execute trade based on signal.
        Returns: {status, order_id, entry_price, size, ...}
        """
        trade_signal = signal.get("signal", "HOLD")
        confidence = signal.get("confidence", 0)

        if trade_signal == "HOLD" or confidence < 0.05:
            return {
                "status": "skipped",
                "reason": f"low confidence ({confidence:.2%})",
                "timestamp": datetime.now().isoformat(),
            }

        # Phase 2: Position sizing
        position_size = max(0.001, confidence * 0.1)  # Risk 10% per trade max

        # In production: would call exchange.place_order()
        # For Phase 2: return mock execution
        return {
            "status": "queued",
            "symbol": symbol,
            "side": "long" if trade_signal == "BUY" else "short",
            "size": position_size,
            "entry_price": None,  # Filled by exchange
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
        }

    def check_exit(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if an open position should be exited.
        Triggers: sentiment reversal or target profit hit.
        """
        if symbol not in self.open_positions:
            return False, "no open position"

        # Get latest sentiment
        sentiment = self.sentiment.analyze(symbol)
        current_signal = sentiment["signal"]

        # Exit if sentiment reverses (simplistic check)
        if current_signal == "SELL":
            return True, "sentiment reversed to SELL"
        elif current_signal == "BUY":
            return True, "sentiment reversed to BUY"

        return False, "position held"
