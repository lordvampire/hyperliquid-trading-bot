"""Funding Rates Module — Phase 2 REAL (Hyperliquid API)."""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time
from exchange import get_info

# Cache: symbol -> {timestamp, data}
_funding_cache = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


class FundingRateAnalyzer:
    """Analyze funding rates for perpetual futures strategy using REAL Hyperliquid API."""

    def __init__(self):
        self.info = get_info()  # Hyperliquid Info client

    def get_funding_rate(self, symbol: str) -> Dict:
        """
        Fetch REAL current funding rate from Hyperliquid /info/fundingHistory.
        Caches for 1 hour to avoid hammering API.
        
        Returns: {symbol, funding_rate, annualized, timestamp, is_cached}
        """
        cache_key = symbol
        now = time.time()

        # Check cache validity
        if cache_key in _funding_cache:
            cached_entry = _funding_cache[cache_key]
            if now - cached_entry["cached_at"] < _CACHE_TTL_SECONDS:
                result = cached_entry["data"].copy()
                result["is_cached"] = True
                return result

        # Fetch from Hyperliquid API
        try:
            # Get most recent funding rate: fetch last 1 hour of data
            end_time = int(time.time() * 1000)  # Current time in milliseconds
            start_time = end_time - 3600000  # 1 hour ago
            
            funding_history = self.info.funding_history(symbol, startTime=start_time, endTime=end_time)
            
            if not funding_history or len(funding_history) == 0:
                # Fallback: return 0 if no data
                result = {
                    "symbol": symbol,
                    "funding_rate": 0.0,
                    "annualized": 0.0,
                    "timestamp": datetime.now().isoformat(),
                    "is_cached": False,
                    "error": "No funding history available",
                }
                return result

            # Most recent funding rate (last entry in the list)
            latest = funding_history[-1]
            funding_rate = float(latest.get("fundingRate", 0))

            result = {
                "symbol": symbol,
                "funding_rate": funding_rate,
                "annualized": funding_rate * 365 * 100,  # Annual %
                "timestamp": datetime.now().isoformat(),
                "is_cached": False,
            }

            # Cache result
            _funding_cache[cache_key] = {
                "cached_at": now,
                "data": result,
            }

            return result

        except Exception as e:
            return {
                "symbol": symbol,
                "funding_rate": 0.0,
                "annualized": 0.0,
                "timestamp": datetime.now().isoformat(),
                "is_cached": False,
                "error": f"Failed to fetch funding rate: {str(e)}",
            }

    def get_funding_signal(self, symbol: str, threshold: float = 0.0001) -> Dict:
        """
        Determine trade signal based on REAL funding rates.
        High positive funding: go short (collect funding)
        High negative funding: go long (pay less funding)
        """
        rate_data = self.get_funding_rate(symbol)
        funding_rate = rate_data.get("funding_rate", 0.0)

        if "error" in rate_data:
            return {
                "symbol": symbol,
                "funding_rate": funding_rate,
                "signal": "NEUTRAL",
                "strength": 0.0,
                "timestamp": datetime.now().isoformat(),
                "error": rate_data["error"],
            }

        if funding_rate > threshold:
            signal = "SHORT"  # Collect positive funding
            strength = min(funding_rate / threshold, 1.0)
        elif funding_rate < -threshold:
            signal = "LONG"  # Avoid paying negative funding
            strength = min(abs(funding_rate) / threshold, 1.0)
        else:
            signal = "NEUTRAL"
            strength = 0.0

        return {
            "symbol": symbol,
            "funding_rate": funding_rate,
            "signal": signal,
            "strength": strength,
            "timestamp": datetime.now().isoformat(),
        }

    def get_history(self, symbol: str, limit: int = 24) -> List[Dict]:
        """Get historical funding rates from Hyperliquid API (REAL data)."""
        try:
            # Calculate time range: last N hours
            end_time = int(time.time() * 1000)
            # Assume each funding period is ~8 hours, so for 24 periods we need ~7 days
            start_time = end_time - (limit * 3600000)  # N hours in milliseconds
            
            funding_history = self.info.funding_history(symbol, startTime=start_time, endTime=end_time)
            history = []
            for entry in funding_history:
                history.append({
                    "timestamp": datetime.fromtimestamp(entry.get("time", 0) / 1000).isoformat(),
                    "funding_rate": float(entry.get("fundingRate", 0)),
                })
            return history
        except Exception as e:
            return [{"error": f"Failed to fetch history: {str(e)}"}]

    def get_funding_trend(self, symbol: str, hours: int = 24) -> Dict:
        """
        Analyze funding rate trend over N hours.
        Returns: {trend_direction, avg_rate, change_pct, volatility}
        Used by sentiment analyzer for heuristic-based sentiment.
        """
        try:
            history = self.get_history(symbol, limit=hours)
            if not history or "error" in history[0]:
                return {
                    "trend": "UNKNOWN",
                    "avg_rate": 0.0,
                    "change_pct": 0.0,
                    "volatility": 0.0,
                }

            rates = [h["funding_rate"] for h in history if "funding_rate" in h]
            if not rates:
                return {
                    "trend": "UNKNOWN",
                    "avg_rate": 0.0,
                    "change_pct": 0.0,
                    "volatility": 0.0,
                }

            avg_rate = sum(rates) / len(rates)
            oldest_rate = rates[-1] if len(rates) > 1 else rates[0]
            newest_rate = rates[0]
            change_pct = ((newest_rate - oldest_rate) / abs(oldest_rate) * 100) if oldest_rate != 0 else 0

            # Volatility: std dev of rates
            variance = sum((r - avg_rate) ** 2 for r in rates) / len(rates)
            volatility = variance ** 0.5

            # Trend direction
            if change_pct > 0.5:
                trend = "RISING"
            elif change_pct < -0.5:
                trend = "FALLING"
            else:
                trend = "STABLE"

            return {
                "trend": trend,
                "avg_rate": avg_rate,
                "change_pct": round(change_pct, 3),
                "volatility": round(volatility, 6),
            }

        except Exception as e:
            return {
                "trend": "ERROR",
                "avg_rate": 0.0,
                "change_pct": 0.0,
                "volatility": 0.0,
                "error": str(e),
            }
