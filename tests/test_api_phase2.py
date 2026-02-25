"""Tests for Phase 2 API endpoints."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def test_next_signal_endpoint():
    """Test /next_signal endpoint."""
    response = client.get("/next_signal?symbol=BTC")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTC"
    assert data["signal"] in ["BUY", "SELL", "HOLD"]
    assert "confidence" in data
    print("✓ /next_signal endpoint works")


def test_next_signal_multiple_symbols():
    """Test /next_signal with multiple symbols."""
    for symbol in ["BTC", "ETH", "SOL"]:
        response = client.get(f"/next_signal?symbol={symbol}")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == symbol
    print("✓ /next_signal works with multiple symbols")


def test_execute_trade_endpoint():
    """Test /execute_trade endpoint."""
    response = client.post("/execute_trade", json={"symbol": "BTC"})
    # Should be 202 (accepted) or 400 (low confidence) or 403 (risk check)
    assert response.status_code in [202, 400, 403]
    if response.status_code == 202:
        data = response.json()
        assert "trade" in data
        print("✓ /execute_trade endpoint works (202 Accepted)")
    else:
        print(f"✓ /execute_trade endpoint works ({response.status_code})")


def test_backtest_endpoint():
    """Test /backtest endpoint."""
    response = client.post("/backtest", json={
        "symbol": "BTC",
        "days": 7,
        "interval": "1h"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTC"
    assert data["trades_executed"] >= 0
    assert "win_rate" in data
    assert "total_return" in data
    print("✓ /backtest endpoint works")


def test_backtest_validation():
    """Test /backtest input validation."""
    # Invalid days (too high)
    response = client.post("/backtest", json={
        "symbol": "BTC",
        "days": 400,
        "interval": "1h"
    })
    assert response.status_code == 400
    print("✓ /backtest validates days")
    
    # Invalid days (too low)
    response = client.post("/backtest", json={
        "symbol": "BTC",
        "days": 0,
        "interval": "1h"
    })
    assert response.status_code == 400
    print("✓ /backtest validates minimum days")


def test_health_check():
    """Ensure health endpoint still works."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    print("✓ /health endpoint still works")


def test_all_endpoints_exist():
    """Verify all Phase 2 endpoints exist."""
    endpoints = [
        ("GET", "/next_signal"),
        ("POST", "/execute_trade"),
        ("POST", "/backtest"),
    ]
    
    for method, path in endpoints:
        if method == "GET":
            response = client.get(f"{path}?symbol=BTC")
        else:
            response = client.post(path, json={"symbol": "BTC"})
        
        # Should not be 404
        assert response.status_code != 404, f"{method} {path} not found"
    
    print("✓ All Phase 2 endpoints exist")


if __name__ == "__main__":
    test_next_signal_endpoint()
    test_next_signal_multiple_symbols()
    test_execute_trade_endpoint()
    test_backtest_endpoint()
    test_backtest_validation()
    test_health_check()
    test_all_endpoints_exist()
    print("\n✅ All Phase 2 API tests passed!")
