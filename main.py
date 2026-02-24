"""FastAPI server — the API layer for the trading bot."""

import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import cfg
from db import init_db
from exchange import fetch_balance, fetch_candles
from manager import RiskManager


risk_manager = RiskManager(
    max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
    max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
    default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Initialize risk manager with current balance
    bal_data = fetch_balance()
    if "error" not in bal_data:
        balance = float(bal_data.get("account_value", 0))
        risk_manager.reset_day(balance)
    yield


app = FastAPI(title="Hyperliquid Trading Bot", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    config_issues = cfg.validate()
    return {
        "status": "ok" if not config_issues else "degraded",
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


@app.post("/order")
async def place_order(req: OrderRequest):
    allowed, reason = risk_manager.can_trade()
    if not allowed:
        raise HTTPException(status_code=403, detail=f"Trading blocked: {reason}")

    # Phase 1: order placement is stubbed — wiring to SDK comes in Phase 2
    return {
        "status": "received",
        "note": "Order execution not yet wired (Phase 2)",
        "order": req.model_dump(),
        "suggested_size": risk_manager.get_position_size(),
    }


@app.get("/candles")
async def candles(symbol: str = "BTC", interval: str = "1h", limit: int = 100):
    data = fetch_candles(symbol, interval, limit)
    return {"symbol": symbol, "interval": interval, "count": len(data), "candles": data}


@app.get("/risk")
async def risk_status():
    return risk_manager.status()


if __name__ == "__main__":
    uvicorn.run("main:app", host=cfg.HOST, port=cfg.PORT, reload=True)
