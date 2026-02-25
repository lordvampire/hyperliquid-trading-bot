"""FastAPI server — the API layer for the trading bot."""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from config import cfg
from db import init_db, get_risk_state, save_risk_state
from exchange import fetch_balance, fetch_candles
from manager import RiskManager
from strategy_b import StrategyB
from backtest import BacktestEngine


risk_manager = RiskManager(
    max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
    max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
    default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
    db_path=cfg.DB_PATH,
)

strategy_b = StrategyB()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Load persisted risk state or initialize from balance
    await risk_manager.load_state()
    bal_data = fetch_balance()
    if "error" not in bal_data:
        balance = float(bal_data.get("account_value", 0))
        if risk_manager.starting_balance == 0:
            risk_manager.reset_day(balance)
            await risk_manager.save_state()
    yield


app = FastAPI(title="Hyperliquid Trading Bot", version="0.1.0", lifespan=lifespan)

# Bug #8: Add CORS middleware restricted to localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1", "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Bug #4: Return {"status": "healthy"} per spec
@app.get("/health")
async def health():
    config_issues = cfg.validate()
    return {
        "status": "healthy" if not config_issues else "degraded",
        "testnet": cfg.HL_TESTNET,
        "config_issues": config_issues,
    }


@app.get("/status")
async def status():
    bal = fetch_balance()
    risk = risk_manager.status()
    return {"balance": bal, "risk": risk}


class OrderRequest(BaseModel):
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    price: Optional[float] = None  # None = market order
    order_type: str = "market"


# Bug #5: Return 202 Accepted for queued orders
@app.post("/order", status_code=202)
async def place_order(req: OrderRequest):
    allowed, reason = risk_manager.can_trade()
    if not allowed:
        raise HTTPException(status_code=403, detail=f"Trading blocked: {reason}")

    # Phase 1: order placement is stubbed — wiring to SDK comes in Phase 2
    return JSONResponse(
        status_code=202,
        content={
            "message": "order queued",
            "order": req.model_dump(),
            "suggested_size": risk_manager.get_position_size(),
        },
    )


# Bug #6: Proper error handling — SDK errors → 500, bad input → 400
@app.get("/candles")
async def candles(symbol: str = "BTC", interval: str = "1h", limit: int = 100):
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 5000")
    valid_intervals = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"interval must be one of {valid_intervals}")
    try:
        data = fetch_candles(symbol, interval, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"symbol": symbol, "interval": interval, "count": len(data), "candles": data}


@app.get("/risk")
async def risk_status():
    return risk_manager.status()


# Phase 2: Strategy B Endpoints

@app.get("/next_signal")
async def next_signal(symbol: str = "BTC"):
    """Get next trading signal using Strategy B (sentiment + funding rates)."""
    signal = strategy_b.get_next_signal(symbol)
    return signal


class ExecuteTradeRequest(BaseModel):
    symbol: str
    allow_low_confidence: bool = False


@app.post("/execute_trade", status_code=202)
async def execute_trade(req: ExecuteTradeRequest):
    """Execute trade based on Strategy B signal."""
    signal = strategy_b.get_next_signal(req.symbol)
    
    if signal["confidence"] < 0.3 and not req.allow_low_confidence:
        raise HTTPException(
            status_code=400,
            detail=f"signal confidence too low: {signal['confidence']:.2%}"
        )
    
    # Check risk
    allowed, reason = risk_manager.can_trade()
    if not allowed:
        raise HTTPException(status_code=403, detail=f"Trading blocked: {reason}")
    
    # Execute
    trade = strategy_b.execute_trade(req.symbol, signal)
    return JSONResponse(
        status_code=202,
        content={
            "message": "trade queued",
            "trade": trade,
            "risk_status": risk_manager.status(),
        },
    )


class BacktestRequest(BaseModel):
    symbol: str
    days: int = 30
    interval: str = "1h"


@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    """Run backtest of Strategy B."""
    if req.days < 1 or req.days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    
    engine = BacktestEngine(start_balance=1000)
    results = engine.run(req.symbol, days=req.days, interval=req.interval)
    return results


if __name__ == "__main__":
    uvicorn.run("main:app", host=cfg.HOST, port=cfg.PORT, reload=True)
