"""
Test: close_position() handles None response from market_close()

Root cause: Hyperliquid SDK's market_close() returns None (implicitly)
when no matching open position exists for the given coin.
This happens when a position was already closed by TP/SL trigger before
the vmr bot's close logic fires.

Regression test: should NOT raise AttributeError ('NoneType' has no attribute 'get')
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure repo root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestClosePositionNoneResponse(unittest.TestCase):
    """Verify close_position() is safe when market_close() returns None."""

    def _make_trader(self):
        """Create a LiveTrader with mocked SDK clients (no real credentials needed)."""
        with patch("live_trader.LiveTrader._setup_clients"):
            from live_trader import LiveTrader
            lt = LiveTrader(dry_run=False)
            lt._wallet = "0xTestWallet"

        # Mock exchange client
        lt._exchange = MagicMock()
        # Mock info client for get_mark_price
        lt._info = MagicMock()
        lt._info.all_mids.return_value = {"BTC": "65000.0"}
        return lt

    def test_none_response_does_not_raise(self):
        """market_close() returning None should NOT raise AttributeError."""
        lt = self._make_trader()
        # Simulate SDK returning None (no position found on exchange)
        lt._exchange.market_close.return_value = None

        result = lt.close_position("BTC")

        # Must not crash — should return a graceful result
        self.assertIsNotNone(result)

    def test_none_response_returns_success_true(self):
        """None response = position already closed → treat as success."""
        lt = self._make_trader()
        lt._exchange.market_close.return_value = None

        result = lt.close_position("BTC")

        self.assertTrue(result.success,
            "close_position should return success=True when no position exists (already closed)")

    def test_none_response_has_informative_error_message(self):
        """Result should include a helpful note about why it was None."""
        lt = self._make_trader()
        lt._exchange.market_close.return_value = None

        result = lt.close_position("BTC")

        self.assertIsNotNone(result.error)
        self.assertIn("already closed", result.error.lower())

    def test_valid_response_still_parses_correctly(self):
        """Normal (non-None) response must still work after the fix."""
        lt = self._make_trader()
        lt._exchange.market_close.return_value = {
            "response": {
                "type": "order",
                "data": {
                    "statuses": [
                        {"filled": {"avgPx": "65100.0", "oid": 99999, "totalSz": "0.001"}}
                    ]
                }
            }
        }

        result = lt.close_position("BTC")

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.price, 65100.0, places=1)
        self.assertEqual(result.order_id, "99999")

    def test_error_in_response_returns_failure(self):
        """Exchange returns an error status → success=False."""
        lt = self._make_trader()
        lt._exchange.market_close.return_value = {
            "response": {
                "type": "order",
                "data": {
                    "statuses": [
                        {"error": "Insufficient margin"}
                    ]
                }
            }
        }

        result = lt.close_position("BTC")

        self.assertFalse(result.success)
        self.assertIn("Insufficient margin", result.error)

    def test_with_explicit_size(self):
        """Partial close (explicit size) with None response also handled."""
        lt = self._make_trader()
        lt._exchange.market_close.return_value = None

        result = lt.close_position("BTC", size=0.005)

        self.assertTrue(result.success)
        self.assertEqual(result.size, 0.005)


if __name__ == "__main__":
    unittest.main(verbosity=2)
