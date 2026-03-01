#!/usr/bin/env python3
"""
vmr_trading_bot.py — Volatility Mean Reversion Trading Bot
===========================================================
Hyperliquid Testnet (Live) or Paper Trading — auto-detected

MODE DETECTION:
  HL_SECRET_KEY set in .env → LIVE mode  (real orders on testnet/mainnet)
  HL_SECRET_KEY missing     → PAPER mode (simulation with fake balance)
  HL_DRY_RUN=true           → DRY RUN   (validates but sends zero orders)

ARCHITECTURE (Single Source of Truth):
  All strategy logic lives in strategy_engine.py → VMRStrategy.
  This file handles:
    • Telegram bot interface (commands + notifications)
    • Autonomous trading loop (auto-scan every N minutes)
    • Paper OR Live trading state management
    • Real candle data from Hyperliquid API

LIVE MODE:
  • Uses LiveTrader (live_trader.py) to place REAL orders on Hyperliquid
  • Reads REAL balance from your margin account
  • Places market orders with optional SL/TP trigger orders
  • Closes positions via market_close()

PAPER TRADING MODE:
  • Simulates trades with a configurable fake balance
  • No real orders sent, no real money at risk

COMMANDS:
  /start              — Show help and current status
  /help               — Full command reference
  /start_auto         — Start autonomous trading loop
  /stop_auto          — Stop the loop (keep positions open)
  /status             — Current positions, P&L, scan interval
  /analyze [BTC|ETH|SOL] — On-demand signal analysis
  /signals            — Show latest signal for all symbols
  /backtest [BTC] [days] — Run in-process backtest on real data
  /stats              — Completed trade statistics
  /balance            — Account balance and risk settings
  /stop_all           — Stop loop and close all positions at market
  /mode               — Show current trading mode (live/paper/dry-run)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from hyperliquid.info import Info
from hyperliquid.utils import constants

# ── Strategy: import from single source of truth ─────────────────────────────
from strategy_engine import VMRConfig, VMRPosition, VMRStrategy, VMRSignal

# ── Live trading ──────────────────────────────────────────────────────────────
from live_trader import LiveTrader, OrderResult


# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("vmr_bot.log"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8568129217:AAEj8EUljihDtMYC_ILXgz9QwF0RsK4oJgk",
)
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "5890731372"))

# Strategy config (single source of truth — change VMRConfig in strategy_engine.py)
CFG = VMRConfig(
    spike_threshold_pct=1.0,      # 1% hourly return spike
    require_bb_confirmation=True, # Also require price outside Bollinger Band
    sl_pct=0.005,                 # 0.5% stop loss
    tp_pct=0.015,                 # 1.5% take profit
    position_size_pct=0.01,       # 1% account per trade
    max_hold_hours=24,
    scan_interval_seconds=900,    # Scan every 15 minutes
    symbols=["BTC", "ETH", "SOL"],
    lookback_days=7,
)

# ── Trading mode detection ────────────────────────────────────────────────────
# LIVE mode  → HL_SECRET_KEY is set in .env
# PAPER mode → HL_SECRET_KEY missing or empty
# DRY RUN    → HL_DRY_RUN=true  (or --dry-run CLI flag)

_HL_SECRET_KEY  = os.getenv("HL_SECRET_KEY", "").strip()
_HL_DRY_RUN     = os.getenv("HL_DRY_RUN", "false").lower() == "true"
LIVE_MODE       = bool(_HL_SECRET_KEY)
DRY_RUN         = _HL_DRY_RUN

PAPER_ACCOUNT_BALANCE = float(os.getenv("PAPER_BALANCE", "10000.0"))

# Initialise LiveTrader (shared instance — not None even in paper mode, for balance reads)
live_trader: Optional[LiveTrader] = None
if LIVE_MODE:
    live_trader = LiveTrader(dry_run=DRY_RUN)


# ============================================================================
# DATA FETCHER
# ============================================================================

class DataFetcher:
    """
    Fetches real 1h candles from the Hyperliquid API (mainnet).

    Uses mainnet read-only API — no keys required.
    """

    def __init__(self):
        """Initialise with mainnet read-only Info client."""
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.cache_dir = Path.home() / "hyperliquid-trading-bot" / ".cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_candles(self, symbol: str, days: int = 7) -> Optional[pd.DataFrame]:
        """
        Fetch 1h OHLCV candles from Hyperliquid for the given symbol.

        Args:
            symbol: Instrument name (e.g. "BTC").
            days:   Number of past days to fetch.

        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume]
            sorted ascending, or None on failure.
        """
        try:
            end_ms   = int(datetime.now().timestamp() * 1000)
            start_ms = end_ms - (days * 24 * 3_600_000)

            logger.info(f"Fetching {symbol} candles ({days}d, 1h) ...")
            raw = self.info.candles_snapshot(
                name=symbol,
                interval="1h",
                startTime=start_ms,
                endTime=end_ms,
            )

            if not raw:
                logger.warning(f"No candles returned for {symbol}")
                return None

            rows = []
            for c in raw:
                rows.append(
                    {
                        "timestamp": int(c["t"]),
                        "open":  float(c["o"]),
                        "high":  float(c["h"]),
                        "low":   float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c["v"]),
                    }
                )

            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.sort_values("timestamp").reset_index(drop=True)

            logger.info(f"✅ {symbol}: {len(df)} candles fetched")
            return df

        except Exception as exc:
            logger.error(f"DataFetcher error ({symbol}): {exc}")
            return None


# ============================================================================
# PAPER TRADING STATE
# ============================================================================

class PaperTrader:
    """
    Manages the paper trading lifecycle.

    Attributes:
        is_running:       Whether the autonomous scan loop is active.
        account_balance:  Current (simulated) account value in USD.
        positions:        Dict[symbol → VMRPosition] of OPEN positions.
        trade_log:        All completed trades (VMRPosition objects).
        daily_pnl:        P&L since last midnight reset.
        scan_count:       Number of autonomous scans performed.
        last_scan_time:   When signals were last checked.
    """

    def __init__(self, balance: float):
        """
        Args:
            balance: Starting paper account balance in USD.
        """
        self.is_running: bool = False
        self.account_balance: float = balance
        self.starting_balance: float = balance
        self.positions: Dict[str, VMRPosition] = {}
        self.trade_log: List[VMRPosition] = []
        self.daily_pnl: float = 0.0
        self.scan_count: int = 0
        self.last_scan_time: Optional[datetime] = None
        self._daily_reset: datetime = datetime.now()

    # ── P&L helpers ─────────────────────────────────────────────────────────

    def unrealised_pnl(self, symbol: str, current_price: float) -> float:
        """
        Calculate unrealised P&L in USD for an open position.

        Args:
            symbol:        Instrument name.
            current_price: Current market price.

        Returns:
            Unrealised P&L in USD (positive = profit, negative = loss).
        """
        if symbol not in self.positions:
            return 0.0
        pos = self.positions[symbol]
        if pos.direction == "LONG":
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price
        else:
            pnl_pct = (pos.entry_price - current_price) / pos.entry_price
        return pnl_pct * pos.size_usd

    def total_unrealised(self, prices: Dict[str, float]) -> float:
        """
        Total unrealised P&L across all open positions.

        Args:
            prices: Dict[symbol → current_price].

        Returns:
            Total unrealised P&L in USD.
        """
        return sum(
            self.unrealised_pnl(sym, prices.get(sym, pos.entry_price))
            for sym, pos in self.positions.items()
        )

    def equity(self, prices: Dict[str, float]) -> float:
        """
        Current account equity = balance + unrealised P&L.

        Args:
            prices: Dict[symbol → current_price].
        """
        return self.account_balance + self.total_unrealised(prices)

    # ── Daily reset ──────────────────────────────────────────────────────────

    def maybe_reset_daily_pnl(self):
        """Reset daily P&L counter at midnight (Berlin time)."""
        now = datetime.now()
        if now.date() > self._daily_reset.date():
            logger.info("🌅 Daily P&L counter reset")
            self.daily_pnl = 0.0
            self._daily_reset = now

    # ── Trade management ─────────────────────────────────────────────────────

    def open_position(self, signal: VMRSignal, pos_info: dict) -> VMRPosition:
        """
        Record a new open paper position.

        Args:
            signal:   The triggering VMRSignal.
            pos_info: dict from VMRStrategy.calculate_position().

        Returns:
            The newly created VMRPosition.
        """
        pos = VMRPosition(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size_usd=pos_info["size_usd"],
            size_crypto=pos_info["size_crypto"],
            leverage=pos_info["leverage"],
            entry_time=datetime.now(),
            status="OPEN",
        )
        self.positions[signal.symbol] = pos
        logger.info(
            f"📍 OPENED {pos.direction} {pos.symbol} @ ${pos.entry_price:,.2f} "
            f"| SL=${pos.stop_loss:,.2f} TP=${pos.take_profit:,.2f} "
            f"| size=${pos.size_usd:.2f}"
        )
        return pos

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        strategy: VMRStrategy,
    ) -> Optional[VMRPosition]:
        """
        Close an open position and record results.

        Args:
            symbol:      Instrument name.
            exit_price:  Price at which position is closed.
            exit_reason: "SL_HIT" | "TP_HIT" | "MAX_HOLD_EXPIRED" | "MANUAL".
            strategy:    VMRStrategy instance for P&L calculation.

        Returns:
            Closed VMRPosition, or None if symbol not in open positions.
        """
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        pnl_pct, pnl_usd = strategy.calculate_pnl(pos, exit_price)

        pos.exit_price  = exit_price
        pos.exit_time   = datetime.now()
        pos.exit_reason = exit_reason
        pos.pnl_pct     = pnl_pct
        pos.pnl_usd     = pnl_usd
        pos.status      = "CLOSED"

        self.account_balance += pnl_usd
        self.daily_pnl       += pnl_usd
        self.trade_log.append(pos)

        del self.positions[symbol]

        result_emoji = "✅" if pnl_usd >= 0 else "❌"
        logger.info(
            f"{result_emoji} CLOSED {pos.direction} {pos.symbol} @ ${exit_price:,.2f} "
            f"| {exit_reason} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})"
        )
        return pos

    # ── Statistics ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """
        Compute aggregate statistics over all completed trades.

        Returns:
            dict with total_trades, wins, losses, win_rate, total_pnl,
                  roi_pct, avg_win_pct, avg_loss_pct, profit_factor.
        """
        if not self.trade_log:
            return {}

        wins   = [t for t in self.trade_log if t.pnl_usd > 0]
        losses = [t for t in self.trade_log if t.pnl_usd <= 0]
        total_pnl = sum(t.pnl_usd for t in self.trade_log)
        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss   = abs(sum(t.pnl_usd for t in losses))

        return {
            "total_trades":  len(self.trade_log),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      len(wins) / len(self.trade_log) * 100,
            "total_pnl":     total_pnl,
            "roi_pct":       total_pnl / self.starting_balance * 100,
            "avg_win_pct":   sum(t.pnl_pct for t in wins)   / len(wins)   if wins   else 0.0,
            "avg_loss_pct":  sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0,
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        }


# ============================================================================
# GLOBAL STATE
# ============================================================================

data_fetcher = DataFetcher()
strategy     = VMRStrategy(CFG)

# Determine starting balance:
#   LIVE mode  → fetch real balance from Hyperliquid margin account
#   PAPER mode → use PAPER_ACCOUNT_BALANCE env var (default $10,000)
def _resolve_starting_balance() -> float:
    if LIVE_MODE and live_trader is not None:
        bal = live_trader.get_balance()
        if bal > 0:
            logger.info(f"💰 Real testnet balance: ${bal:,.2f}")
            return bal
        logger.warning("⚠️  Could not fetch real balance — falling back to paper balance")
    return PAPER_ACCOUNT_BALANCE

paper = PaperTrader(_resolve_starting_balance())

# asyncio task handle for the autonomous loop
_scan_task: Optional[asyncio.Task] = None


# ============================================================================
# AUTONOMOUS TRADING LOOP
# ============================================================================

async def trading_loop(app: Application):
    """
    Autonomous paper-trading scan loop.

    Runs every CFG.scan_interval_seconds.
    On each scan:
      1. Fetch latest candles for each symbol.
      2. Check open positions for SL/TP/max-hold exits.
      3. Scan for new entry signals.
      4. Send Telegram notifications for any trade events.

    Args:
        app: The running Telegram Application (for sending messages).
    """
    global paper

    mode_label = "🔴 LIVE" if LIVE_MODE else "📄 PAPER"
    if LIVE_MODE and DRY_RUN:
        mode_label = "🔵 DRY RUN"

    logger.info(
        f"🤖 Autonomous trading loop started [{mode_label}] — "
        f"scan every {CFG.scan_interval_seconds}s"
    )
    await _send_message(
        app,
        f"🤖 *Autonomous Trading Loop STARTED*\n"
        f"Mode: {mode_label}\n"
        f"Scan interval: {CFG.scan_interval_seconds // 60} min\n"
        f"Symbols: {', '.join(CFG.symbols)}\n"
        f"Balance: ${paper.account_balance:,.2f}\n"
        f"Spike threshold: {CFG.spike_threshold_pct}%\n"
        f"BB confirmation: {'ON' if CFG.require_bb_confirmation else 'OFF'}\n"
        f"SL/TP: {CFG.sl_pct*100:.1f}% / {CFG.tp_pct*100:.1f}%",
    )

    while paper.is_running:
        try:
            paper.maybe_reset_daily_pnl()
            paper.scan_count += 1
            paper.last_scan_time = datetime.now()

            logger.info(f"🔍 Scan #{paper.scan_count} — {paper.last_scan_time.strftime('%H:%M:%S')}")

            for symbol in CFG.symbols:
                df = data_fetcher.get_candles(symbol, days=CFG.lookback_days)
                if df is None or df.empty:
                    logger.warning(f"⚠️  No data for {symbol}, skipping")
                    continue

                current_price = float(df["close"].iloc[-1])

                # ── 1. Exit check for open position ─────────────────────────
                if symbol in paper.positions:
                    pos = paper.positions[symbol]
                    elapsed = (datetime.now() - pos.entry_time).total_seconds() / 3600

                    # Check SL/TP using candle high/low for realism
                    check_price = current_price
                    high = float(df["high"].iloc[-1]) if "high" in df.columns else current_price
                    low  = float(df["low"].iloc[-1])  if "low"  in df.columns else current_price

                    if pos.direction == "LONG":
                        if low <= pos.stop_loss:
                            check_price = pos.stop_loss
                        elif high >= pos.take_profit:
                            check_price = pos.take_profit
                    else:
                        if high >= pos.stop_loss:
                            check_price = pos.stop_loss
                        elif low <= pos.take_profit:
                            check_price = pos.take_profit

                    should_exit, reason = strategy.check_exit(pos, check_price, elapsed)

                    if should_exit:
                        closed = paper.close_position(symbol, check_price, reason, strategy)
                        if closed:
                            # ── LIVE: close real position ────────────────────
                            if LIVE_MODE and live_trader is not None:
                                close_result = live_trader.close_position(symbol)
                                if close_result.success:
                                    logger.info(
                                        f"✅ LIVE CLOSE {symbol} — OID={close_result.order_id} "
                                        f"fill=${close_result.price:,.2f}"
                                    )
                                else:
                                    logger.error(
                                        f"❌ LIVE CLOSE FAILED {symbol}: {close_result.error}"
                                    )
                            await _send_position_closed(app, closed)

                # ── 2. Entry signal check ────────────────────────────────────
                if symbol not in paper.positions:
                    open_count = len(paper.positions)
                    if open_count >= CFG.max_open_positions:
                        continue

                    signal = strategy.analyze(df, symbol)
                    logger.info(strategy.format_signal(signal))

                    if signal.direction != "NONE":
                        # Check daily loss limit
                        if paper.daily_pnl < -(paper.account_balance * CFG.daily_loss_limit_pct):
                            logger.warning(f"🛑 Daily loss limit hit — skipping {symbol}")
                            continue

                        pos_info = strategy.calculate_position(signal, paper.account_balance)
                        if pos_info:
                            # ── LIVE: place real order ───────────────────────
                            live_order_ok = True
                            if LIVE_MODE and live_trader is not None:
                                order_result = live_trader.place_order(
                                    symbol=signal.symbol,
                                    direction=signal.direction,
                                    size_usd=pos_info["size_usd"],
                                    entry_price=signal.entry_price,
                                    stop_loss=signal.stop_loss,
                                    take_profit=signal.take_profit,
                                    order_type="MARKET",
                                )
                                if order_result.success:
                                    logger.info(
                                        f"✅ LIVE ORDER {signal.symbol} — "
                                        f"OID={order_result.order_id} "
                                        f"fill=${order_result.price:,.2f}"
                                    )
                                    # Use actual fill price for paper tracking
                                    signal = signal._replace(entry_price=order_result.price) \
                                             if hasattr(signal, '_replace') else signal
                                else:
                                    logger.error(
                                        f"❌ LIVE ORDER FAILED {signal.symbol}: "
                                        f"{order_result.error}"
                                    )
                                    live_order_ok = False

                            if live_order_ok:
                                pos = paper.open_position(signal, pos_info)
                                await _send_position_opened(app, pos, signal)

        except asyncio.CancelledError:
            logger.info("Trading loop cancelled — shutting down")
            break
        except Exception as exc:
            logger.exception(f"Trading loop error: {exc}")

        await asyncio.sleep(CFG.scan_interval_seconds)

    logger.info("🛑 Trading loop stopped")


# ============================================================================
# TELEGRAM HELPERS
# ============================================================================

async def _send_message(app: Application, text: str):
    """
    Send a Telegram message to the configured CHAT_ID.

    Args:
        app:  Running Telegram Application.
        text: Message text (Markdown supported).
    """
    try:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error(f"Telegram send error: {exc}")


async def _send_position_opened(app: Application, pos: VMRPosition, signal: VMRSignal):
    """
    Notify Telegram that a position was opened.

    Args:
        app:    Running Telegram Application.
        pos:    The opened VMRPosition.
        signal: The VMRSignal that triggered the entry.
    """
    emoji = "📈" if pos.direction == "LONG" else "📉"
    if LIVE_MODE and DRY_RUN:
        mode_tag = "🔵 DRY-RUN TRADE OPENED"
    elif LIVE_MODE:
        mode_tag = "🔴 LIVE TRADE OPENED"
    else:
        mode_tag = "📄 PAPER TRADE OPENED"

    msg = (
        f"{emoji} *{mode_tag}*\n\n"
        f"Symbol:  {pos.symbol}\n"
        f"Side:    {pos.direction}\n"
        f"Entry:   ${pos.entry_price:,.2f}\n"
        f"SL:      ${pos.stop_loss:,.2f} (-{CFG.sl_pct*100:.1f}%)\n"
        f"TP:      ${pos.take_profit:,.2f} (+{CFG.tp_pct*100:.1f}%)\n"
        f"Size:    ${pos.size_usd:.2f}\n"
        f"Trigger: {signal.reason}\n"
        f"Conf:    {signal.confidence:.0%}"
    )
    await _send_message(app, msg)


async def _send_position_closed(app: Application, pos: VMRPosition):
    """
    Notify Telegram that a position was closed.

    Args:
        app: Running Telegram Application.
        pos: The closed VMRPosition (with pnl_pct, pnl_usd filled in).
    """
    result_emoji = "✅ WIN" if pos.pnl_usd >= 0 else "❌ LOSS"
    if LIVE_MODE and DRY_RUN:
        mode_tag = "DRY-RUN TRADE CLOSED"
    elif LIVE_MODE:
        mode_tag = "🔴 LIVE TRADE CLOSED"
    else:
        mode_tag = "PAPER TRADE CLOSED"

    msg = (
        f"{result_emoji} *{mode_tag}*\n\n"
        f"Symbol:  {pos.symbol}\n"
        f"Side:    {pos.direction}\n"
        f"Entry:   ${pos.entry_price:,.2f}\n"
        f"Exit:    ${pos.exit_price:,.2f}\n"
        f"Reason:  {pos.exit_reason}\n"
        f"P&L:     {pos.pnl_pct:+.2f}% (${pos.pnl_usd:+.2f})\n"
        f"Balance: ${paper.account_balance:,.2f}"
    )
    await _send_message(app, msg)


# ============================================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — Display welcome message and command reference.
    """
    loop_status = "🟢 RUNNING" if paper.is_running else "🔴 STOPPED"
    positions   = len(paper.positions)

    msg = f"""
🤖 *Volatility Mean Reversion Bot*
Strategy: VMR (spike detection + BB filter)
Loop: {loop_status} | Open positions: {positions}

*AUTONOMOUS TRADING*
/start\\_auto  — Start scanning every {CFG.scan_interval_seconds//60} min
/stop\\_auto   — Pause scanning (keep positions)
/stop\\_all    — Stop + close all positions at market

*MONITORING*
/status       — Positions, P&L, scan info
/signals      — Latest signal for all symbols
/analyze BTC  — On-demand analysis
/stats        — Completed trade history
/balance      — Account and risk settings

*BACKTESTING*
/backtest BTC 30  — Run real-data backtest (30 days)
/backtest BTC 30 \\-\\-use\\-optimized\\-params

*OPTIMIZATION*
/optimize BTC         — Grid search (15–60 min)
/show\\_best\\_params    — Top 3 combos from last run
/set\\_params spike=1.0 bb\\_mult=2.0 sl=0.005 tp=0.015

*STRATEGY CONFIG*
Symbols:       {', '.join(CFG.symbols)}
Spike trigger: {CFG.spike_threshold_pct}% hourly return
BB filter:     {'ON' if CFG.require_bb_confirmation else 'OFF'}
SL / TP:       {CFG.sl_pct*100:.1f}% / {CFG.tp_pct*100:.1f}%
Max hold:      {CFG.max_hold_hours}h
Scan every:    {CFG.scan_interval_seconds//60} min
    """
    await update.message.reply_text(msg.strip(), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help — Full command reference.
    """
    msg = """
📖 *Command Reference*

*AUTONOMOUS TRADING*
/start\\_auto          Start autonomous paper trading loop
/stop\\_auto           Pause scan loop (positions stay open)
/stop\\_all            Stop loop, close all positions at market

*MONITORING*
/status               Open positions with live P&L
/signals              Latest signal check for BTC, ETH, SOL
/analyze [SYMBOL]     Detailed signal analysis for one symbol
/stats                Completed trade statistics
/balance              Account balance and risk config

*BACKTESTING*
/backtest [SYM] [D]               Run backtest on real data
/backtest BTC 30 \\-\\-use\\-optimized\\-params  Backtest with best params

*OPTIMIZATION*
/optimize [BTC|ETH|SOL]            Run grid search (15–60 min)
/show\\_best\\_params                  Top 3 combos from last run
/set\\_params spike=1.0 bb\\_mult=2.0  Apply params live

/start                Welcome message + quick status
/help                 This message
    """
    await update.message.reply_text(msg.strip(), parse_mode="Markdown")


async def cmd_start_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start_auto — Launch the autonomous paper trading scan loop.

    Safe to call multiple times — only one loop runs at a time.
    """
    global _scan_task

    if paper.is_running:
        await update.message.reply_text("⚠️ Auto-loop already running. Use /status to check.")
        return

    paper.is_running = True
    paper.scan_count = 0

    _scan_task = asyncio.create_task(trading_loop(context.application))

    await update.message.reply_text(
        f"✅ *Autonomous trading loop started!*\n"
        f"Scanning every {CFG.scan_interval_seconds // 60} min\n"
        f"Balance: ${paper.account_balance:,.2f}\n"
        f"Use /status to monitor, /stop\\_auto to pause.",
        parse_mode="Markdown",
    )


async def cmd_stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stop_auto — Pause the autonomous scan loop.

    Positions remain open — use /stop_all to also close them.
    """
    global _scan_task

    if not paper.is_running:
        await update.message.reply_text("⚠️ Auto-loop is not running.")
        return

    paper.is_running = False
    if _scan_task and not _scan_task.done():
        _scan_task.cancel()

    open_pos = len(paper.positions)
    await update.message.reply_text(
        f"⏸ *Auto-loop paused.*\n"
        f"Open positions: {open_pos} (still active)\n"
        f"Use /start\\_auto to resume or /stop\\_all to close everything.",
        parse_mode="Markdown",
    )


async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stop_all — Stop the loop AND close all open positions at current market price.
    """
    global _scan_task

    paper.is_running = False
    if _scan_task and not _scan_task.done():
        _scan_task.cancel()

    msg = await update.message.reply_text("⏳ Closing all positions...")

    closed_text = ""
    for symbol in list(paper.positions.keys()):
        df = data_fetcher.get_candles(symbol, days=1)
        price = float(df["close"].iloc[-1]) if df is not None else paper.positions[symbol].entry_price

        # ── LIVE: close real position ──────────────────────────────────────
        if LIVE_MODE and live_trader is not None:
            close_result = live_trader.close_position(symbol)
            if close_result.success:
                price = close_result.price or price
                logger.info(f"✅ LIVE CLOSE {symbol} @ ${price:,.2f}")
            else:
                logger.error(f"❌ LIVE CLOSE FAILED {symbol}: {close_result.error}")

        closed = paper.close_position(symbol, price, "MANUAL", strategy)
        if closed:
            closed_text += (
                f"\n• {closed.symbol} {closed.direction}: "
                f"{closed.pnl_pct:+.2f}% (${closed.pnl_usd:+.2f})"
            )

    s = paper.stats()
    response = (
        f"🛑 *All positions closed.*\n"
        f"{closed_text or ' None were open.'}\n\n"
        f"Balance: ${paper.account_balance:,.2f}\n"
        f"Total ROI: {s.get('roi_pct', 0):+.2f}%\n"
        f"Trades done: {s.get('total_trades', 0)}"
    )
    await msg.edit_text(response, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status — Show current open positions with live P&L, loop info.
    """
    loop_status = "🟢 RUNNING" if paper.is_running else "🔴 STOPPED"
    last_scan   = (
        paper.last_scan_time.strftime("%H:%M:%S")
        if paper.last_scan_time
        else "never"
    )
    next_scan_secs = (
        CFG.scan_interval_seconds
        - int((datetime.now() - paper.last_scan_time).total_seconds())
        if paper.last_scan_time
        else 0
    )
    next_scan_secs = max(next_scan_secs, 0)

    response = (
        f"📊 *Bot Status*\n\n"
        f"Loop:      {loop_status}\n"
        f"Last scan: {last_scan}\n"
        f"Next scan: {next_scan_secs}s\n"
        f"Scans:     #{paper.scan_count}\n"
        f"Balance:   ${paper.account_balance:,.2f}\n"
        f"Daily P&L: ${paper.daily_pnl:+.2f}\n\n"
    )

    if not paper.positions:
        response += "_No open positions._\n"
    else:
        prices = {}
        for symbol in paper.positions:
            df = data_fetcher.get_candles(symbol, days=1)
            if df is not None:
                prices[symbol] = float(df["close"].iloc[-1])

        for symbol, pos in paper.positions.items():
            price  = prices.get(symbol, pos.entry_price)
            unreal = paper.unrealised_pnl(symbol, price)
            elapsed = (datetime.now() - pos.entry_time).total_seconds() / 3600
            emoji = "📈" if pos.direction == "LONG" else "📉"

            response += (
                f"{emoji} *{symbol}* {pos.direction}\n"
                f"  Entry:   ${pos.entry_price:,.2f}\n"
                f"  Current: ${price:,.2f}\n"
                f"  Unreal:  ${unreal:+.2f}\n"
                f"  SL/TP:   ${pos.stop_loss:,.2f} / ${pos.take_profit:,.2f}\n"
                f"  Held:    {elapsed:.1f}h / {CFG.max_hold_hours}h max\n\n"
            )

    await update.message.reply_text(response, parse_mode="Markdown")


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /signals — Fetch latest candles and show signal analysis for all symbols.
    """
    msg = await update.message.reply_text("⏳ Analysing all symbols ...")

    response = "📡 *Signal Scan*\n\n"
    for symbol in CFG.symbols:
        df = data_fetcher.get_candles(symbol, days=CFG.lookback_days)
        if df is None:
            response += f"⚠️ {symbol}: no data\n"
            continue

        sig = strategy.analyze(df, symbol)
        current = float(df["close"].iloc[-1])

        if sig.direction == "NONE":
            response += (
                f"🟡 *{symbol}* — NO SIGNAL\n"
                f"  Price:   ${current:,.2f}\n"
                f"  Return:  {sig.spike_return:+.2f}%\n"
                f"  Reason:  {sig.reason}\n\n"
            )
        else:
            emoji = "📈" if sig.direction == "LONG" else "📉"
            response += (
                f"{emoji} *{symbol}* — *{sig.direction}* ✅\n"
                f"  Entry:  ${sig.entry_price:,.2f}\n"
                f"  SL:     ${sig.stop_loss:,.2f}\n"
                f"  TP:     ${sig.take_profit:,.2f}\n"
                f"  RR:     {sig.rr_ratio:.1f}x\n"
                f"  Conf:   {sig.confidence:.0%}\n"
                f"  Reason: {sig.reason}\n\n"
            )

    await msg.edit_text(response, parse_mode="Markdown")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /analyze [BTC|ETH|SOL] — Detailed analysis for a single symbol.
    """
    if not context.args:
        await update.message.reply_text("Usage: /analyze BTC (or ETH, SOL)")
        return

    symbol = context.args[0].upper()
    if symbol not in CFG.symbols:
        await update.message.reply_text(
            f"❌ Unknown symbol. Choose from: {', '.join(CFG.symbols)}"
        )
        return

    msg = await update.message.reply_text(f"⏳ Analysing {symbol} ...")

    df = data_fetcher.get_candles(symbol, days=CFG.lookback_days)
    if df is None or df.empty:
        await msg.edit_text(f"❌ No data for {symbol}")
        return

    sig = strategy.analyze(df, symbol)
    current = float(df["close"].iloc[-1])

    if sig.direction == "NONE":
        response = (
            f"📊 *{symbol} Analysis*\n\n"
            f"Signal:  NO SIGNAL 🟡\n"
            f"Price:   ${current:,.2f}\n"
            f"Return:  {sig.spike_return:+.2f}%\n"
            f"Volatility: {sig.volatility:.2f}%\n"
            f"BB Upper: ${sig.bb_upper:,.2f}\n"
            f"BB Lower: ${sig.bb_lower:,.2f}\n"
            f"Reason:  {sig.reason}\n\n"
            f"_Threshold: ≥{CFG.spike_threshold_pct}% spike_"
        )
    else:
        emoji = "📈" if sig.direction == "LONG" else "📉"
        pos_info = strategy.calculate_position(sig, paper.account_balance)
        response = (
            f"{emoji} *{symbol} — {sig.direction} SIGNAL*\n\n"
            f"Entry:  ${sig.entry_price:,.2f}\n"
            f"SL:     ${sig.stop_loss:,.2f} (-{CFG.sl_pct*100:.1f}%)\n"
            f"TP:     ${sig.take_profit:,.2f} (+{CFG.tp_pct*100:.1f}%)\n"
            f"RR:     {sig.rr_ratio:.2f}x\n"
            f"Conf:   {sig.confidence:.0%}\n"
            f"Spike:  {sig.spike_return:+.2f}%\n"
            f"Vol:    {sig.volatility:.2f}%\n"
            f"Reason: {sig.reason}\n\n"
            f"Position size: ${pos_info.get('size_usd', 0):.2f}\n"
            f"Leverage: {pos_info.get('leverage', 5)}x"
        )

    await msg.edit_text(response, parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats — Show completed paper trade statistics.
    """
    s = paper.stats()

    if not s:
        await update.message.reply_text(
            "📊 No completed trades yet.\n"
            "Use /start\\_auto to begin autonomous trading.",
            parse_mode="Markdown",
        )
        return

    pf = s["profit_factor"]
    pf_str = f"{pf:.2f}x" if pf != float("inf") else "∞"

    response = (
        f"📈 *Paper Trading Statistics*\n\n"
        f"Trades:    {s['total_trades']}\n"
        f"Wins:      {s['wins']}\n"
        f"Losses:    {s['losses']}\n"
        f"Win Rate:  {s['win_rate']:.1f}%\n\n"
        f"Total P&L: ${s['total_pnl']:+.2f}\n"
        f"ROI:       {s['roi_pct']:+.2f}%\n"
        f"Avg Win:   {s['avg_win_pct']:+.2f}%\n"
        f"Avg Loss:  {s['avg_loss_pct']:+.2f}%\n"
        f"P Factor:  {pf_str}\n\n"
        f"Balance:   ${paper.account_balance:,.2f}\n"
        f"Daily P&L: ${paper.daily_pnl:+.2f}"
    )

    await update.message.reply_text(response, parse_mode="Markdown")


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mode — Show current trading mode (live / dry-run / paper).
    """
    if LIVE_MODE and DRY_RUN:
        label   = "🔵 DRY RUN"
        details = "Live credentials loaded, but HL\\_DRY\\_RUN=true — zero real orders."
    elif LIVE_MODE:
        label   = "🔴 LIVE TESTNET" if os.getenv("HL_TESTNET", "true").lower() == "true" else "🔴 LIVE MAINNET"
        details = "Real orders are being placed on Hyperliquid."
    else:
        label   = "📄 PAPER"
        details = "Simulation only — no HL\\_SECRET\\_KEY set."

    wallet = os.getenv("HL_WALLET_ADDRESS", "(not set)")
    wallet_display = wallet[:10] + "..." + wallet[-6:] if len(wallet) > 20 else wallet

    response = (
        f"⚙️ *Trading Mode: {label}*\n\n"
        f"{details}\n\n"
        f"Wallet: `{wallet_display}`\n"
        f"Order log: {len(live_trader.get_order_log()) if live_trader else 0} orders this session"
    )
    await update.message.reply_text(response, parse_mode="Markdown")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /balance — Show account balance and risk configuration.
    In LIVE mode, fetches real balance from Hyperliquid.
    """
    prices = {}
    for symbol in CFG.symbols:
        df = data_fetcher.get_candles(symbol, days=1)
        if df is not None:
            prices[symbol] = float(df["close"].iloc[-1])

    equity = paper.equity(prices)

    # In live mode, also fetch real balance from Hyperliquid
    real_balance_line = ""
    if LIVE_MODE and live_trader is not None:
        real_bal = live_trader.get_balance()
        network  = live_trader.network_label()
        real_balance_line = f"HL Account ({network}): ${real_bal:,.2f}\n"

    response = (
        f"💰 *Account Balance*\n\n"
        f"{real_balance_line}"
        f"Starting:    ${paper.starting_balance:,.2f}\n"
        f"Current:     ${paper.account_balance:,.2f}\n"
        f"Equity:      ${equity:,.2f}\n"
        f"Daily P&L:   ${paper.daily_pnl:+.2f}\n\n"
        f"*Risk Settings*\n"
        f"Per trade:   {CFG.position_size_pct*100:.1f}% (${paper.account_balance * CFG.position_size_pct:,.2f})\n"
        f"Daily limit: {CFG.daily_loss_limit_pct*100:.1f}% (${paper.account_balance * CFG.daily_loss_limit_pct:,.2f})\n"
        f"Max positions: {CFG.max_open_positions}\n"
        f"Leverage:    {CFG.min_leverage}–{CFG.max_leverage}x"
    )

    await update.message.reply_text(response, parse_mode="Markdown")


# ============================================================================
# OPTIMIZATION COMMANDS
# ============================================================================

import asyncio as _asyncio
import json as _json
import subprocess as _subprocess
from pathlib import Path as _Path

_REPO_ROOT       = _Path(__file__).parent
_BEST_PARAMS_FILE = _REPO_ROOT / "best_params.json"
_OPTIMIZER_SCRIPT = _REPO_ROOT / "optimizer.py"

# Track running optimizer subprocess
_optimizer_proc: Optional[_subprocess.Popen] = None
_optimizer_symbol: str = ""


async def cmd_optimize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /optimize [BTC|ETH|SOL] — Run parameter grid search for a symbol.

    Spawns optimizer.py as a background subprocess and reports when done.
    Only one optimization can run at a time.
    """
    global _optimizer_proc, _optimizer_symbol

    # Check if one is already running
    if _optimizer_proc is not None and _optimizer_proc.poll() is None:
        await update.message.reply_text(
            f"⏳ Optimizer already running for *{_optimizer_symbol}*.\n"
            f"Wait for it to finish or restart the bot to cancel.",
            parse_mode="Markdown",
        )
        return

    args = context.args or []
    symbol = args[0].upper() if args else "BTC"
    valid_symbols = ["BTC", "ETH", "SOL"]
    if symbol not in valid_symbols:
        await update.message.reply_text(
            f"❌ Unknown symbol. Choose from: {', '.join(valid_symbols)}"
        )
        return

    msg = await update.message.reply_text(
        f"🔬 *Launching optimizer for {symbol}*\n\n"
        f"Running grid search across {5*5*5*5*4*4:,} parameter combinations.\n"
        f"This may take 15–60 minutes depending on hardware.\n\n"
        f"Progress is logged to `optimizer.log`.\n"
        f"I'll notify you when complete!",
        parse_mode="Markdown",
    )

    _optimizer_symbol = symbol

    try:
        import sys
        python = sys.executable
        _optimizer_proc = _subprocess.Popen(
            [python, str(_OPTIMIZER_SCRIPT), "--symbol", symbol],
            stdout=open(_REPO_ROOT / "optimizer.log", "a"),
            stderr=_subprocess.STDOUT,
            cwd=str(_REPO_ROOT),
        )
        logger.info(f"Optimizer subprocess started PID={_optimizer_proc.pid} symbol={symbol}")
    except Exception as exc:
        await msg.edit_text(
            f"❌ Failed to start optimizer: {exc}",
            parse_mode="Markdown",
        )
        return

    # Monitor in background and notify when done
    async def _monitor():
        while _optimizer_proc.poll() is None:
            await asyncio.sleep(30)
        rc = _optimizer_proc.returncode
        if rc == 0:
            summary_file = _REPO_ROOT / "optimization_summary.md"
            exists = "✅ `optimization_summary.md` updated." if summary_file.exists() else ""
            await _send_message(
                context.application,
                f"🎉 *Optimizer done for {symbol}!*\n\n"
                f"Return code: {rc} (success)\n"
                f"{exists}\n\n"
                f"Use /show\\_best\\_params to see top combos.\n"
                f"Use /set\\_params to apply the best params live.",
            )
        else:
            await _send_message(
                context.application,
                f"❌ *Optimizer failed for {symbol}*\n\n"
                f"Return code: {rc}\n"
                f"Check `optimizer.log` for details.",
            )

    asyncio.create_task(_monitor())


async def cmd_show_best_params(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /show_best_params — Display top 3 parameter combos from last optimization.

    Reads best_params.json written by optimizer.py.
    """
    if not _BEST_PARAMS_FILE.exists():
        await update.message.reply_text(
            "❌ No optimization results found.\n"
            "Run /optimize BTC (or ETH, SOL) first.",
        )
        return

    try:
        with open(_BEST_PARAMS_FILE) as f:
            data = _json.load(f)
    except Exception as exc:
        await update.message.reply_text(f"❌ Could not read best_params.json: {exc}")
        return

    generated = data.get("generated", "unknown")
    combos    = data.get("top_combos", [])

    if not combos:
        await update.message.reply_text("❌ No combos found in best_params.json.")
        return

    lines = [f"🏆 *Best Parameter Combos* (from {generated})\n"]

    for combo in combos[:3]:
        rank   = combo.get("rank", "?")
        p      = combo.get("params", {})
        sharpe = combo.get("avg_sharpe", 0.0)

        # Per-symbol Sharpes if available
        sym_sharpes = {
            k.replace("sharpe_", ""): v
            for k, v in combo.items()
            if k.startswith("sharpe_") and v is not None
        }
        sym_line = "  ".join(
            f"{s}:{v:.3f}" for s, v in sym_sharpes.items()
        )

        lines.append(
            f"*#{rank}* — Avg Sharpe: `{sharpe:.4f}`\n"
            f"  {sym_line}\n"
            f"  • spike:  `{p.get('spike_threshold_pct', '?')}`\n"
            f"  • bb\\_mult: `{p.get('bb_std_multiplier', '?')}`\n"
            f"  • sl:     `{p.get('sl_pct', '?')}`\n"
            f"  • tp:     `{p.get('tp_pct', '?')}`\n"
            f"  • size:   `{p.get('position_size_pct', '?')}`\n"
            f"  • hold:   `{int(p.get('max_hold_hours', 24))}h`\n"
        )

    lines.append(
        "\n_Apply with:_\n"
        "`/set_params spike=X bb_mult=Y sl=0.005 tp=0.015 size=0.01 hold=24`"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_set_params(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_params spike=X bb_mult=Y sl=Z tp=W size=V hold=H

    Updates VMRConfig live without restarting the bot.
    Only the provided keys are changed; others remain at current values.

    Supported keys:
      spike    → spike_threshold_pct
      bb_mult  → bb_std_multiplier
      sl       → sl_pct
      tp       → tp_pct
      size     → position_size_pct
      hold     → max_hold_hours
      bb_on    → require_bb_confirmation (0/1)
    """
    global strategy

    ALIAS_MAP = {
        "spike":    "spike_threshold_pct",
        "bb_mult":  "bb_std_multiplier",
        "sl":       "sl_pct",
        "tp":       "tp_pct",
        "size":     "position_size_pct",
        "hold":     "max_hold_hours",
        "bb_on":    "require_bb_confirmation",
    }

    if not context.args:
        alias_list = "\n".join(f"  {k} → {v}" for k, v in ALIAS_MAP.items())
        await update.message.reply_text(
            f"❌ No params given.\n\nUsage:\n"
            f"`/set_params spike=1.0 bb_mult=2.0 sl=0.005 tp=0.015 size=0.01 hold=24`\n\n"
            f"Supported keys:\n{alias_list}",
            parse_mode="Markdown",
        )
        return

    changes: Dict[str, Any] = {}
    errors:  List[str]      = []

    for arg in context.args:
        if "=" not in arg:
            errors.append(f"Invalid format `{arg}` (expected key=value)")
            continue
        key_raw, val_str = arg.split("=", 1)
        key_raw = key_raw.lower().strip()

        # Resolve alias
        cfg_key = ALIAS_MAP.get(key_raw, key_raw)

        if not hasattr(CFG, cfg_key):
            errors.append(f"Unknown param `{key_raw}`")
            continue

        try:
            if cfg_key == "require_bb_confirmation":
                val = bool(int(val_str))
            elif cfg_key == "max_hold_hours":
                val = int(val_str)
            else:
                val = float(val_str)
        except ValueError:
            errors.append(f"Invalid value `{val_str}` for `{key_raw}`")
            continue

        setattr(CFG, cfg_key, val)
        changes[cfg_key] = val

    # Rebuild strategy with updated config (VMRStrategy wraps the config reference)
    # Since strategy holds a reference to CFG, changes above are already live.
    # Rebuild explicitly to be safe:
    strategy = VMRStrategy(CFG)

    if errors:
        err_text = "\n".join(f"  ⚠️ {e}" for e in errors)
        await update.message.reply_text(
            f"⚠️ Some params had errors:\n{err_text}",
            parse_mode="Markdown",
        )

    if not changes:
        await update.message.reply_text("❌ No valid params were applied.")
        return

    change_lines = "\n".join(
        f"  • `{k}` = `{v}`" for k, v in changes.items()
    )
    await update.message.reply_text(
        f"✅ *Strategy params updated live:*\n\n"
        f"{change_lines}\n\n"
        f"*Current config:*\n"
        f"  spike = `{CFG.spike_threshold_pct}`\n"
        f"  bb\\_mult = `{CFG.bb_std_multiplier}`\n"
        f"  sl = `{CFG.sl_pct}`\n"
        f"  tp = `{CFG.tp_pct}`\n"
        f"  size = `{CFG.position_size_pct}`\n"
        f"  hold = `{CFG.max_hold_hours}h`\n"
        f"  bb\\_on = `{CFG.require_bb_confirmation}`",
        parse_mode="Markdown",
    )


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /backtest [BTC] [days] [--use-optimized-params]

    Run real-data bar-by-bar backtest.
    With --use-optimized-params, loads top-1 combo from best_params.json.
    """
    args = context.args or []

    use_opt  = "--use-optimized-params" in args
    clean_args = [a for a in args if a != "--use-optimized-params"]

    symbol = clean_args[0].upper() if clean_args else "BTC"
    days   = int(clean_args[1]) if len(clean_args) > 1 else 30

    if symbol not in CFG.symbols:
        await update.message.reply_text(f"❌ Unknown symbol. Use: {', '.join(CFG.symbols)}")
        return

    # Choose config: optimized or current
    bt_cfg = VMRConfig(
        spike_threshold_pct  = CFG.spike_threshold_pct,
        bb_std_multiplier    = CFG.bb_std_multiplier,
        sl_pct               = CFG.sl_pct,
        tp_pct               = CFG.tp_pct,
        position_size_pct    = CFG.position_size_pct,
        max_hold_hours       = CFG.max_hold_hours,
        require_bb_confirmation = CFG.require_bb_confirmation,
    )

    opt_label = ""
    if use_opt:
        if not _BEST_PARAMS_FILE.exists():
            await update.message.reply_text(
                "❌ No optimization results found. Run /optimize first."
            )
            return
        try:
            with open(_BEST_PARAMS_FILE) as f:
                best_data = _json.load(f)
            top = best_data.get("top_combos", [])
            if not top:
                raise ValueError("Empty top_combos list")
            p = top[0]["params"]
            bt_cfg.spike_threshold_pct = float(p.get("spike_threshold_pct", bt_cfg.spike_threshold_pct))
            bt_cfg.bb_std_multiplier   = float(p.get("bb_std_multiplier",   bt_cfg.bb_std_multiplier))
            bt_cfg.sl_pct              = float(p.get("sl_pct",              bt_cfg.sl_pct))
            bt_cfg.tp_pct              = float(p.get("tp_pct",              bt_cfg.tp_pct))
            bt_cfg.position_size_pct   = float(p.get("position_size_pct",   bt_cfg.position_size_pct))
            bt_cfg.max_hold_hours      = int(p.get("max_hold_hours",        bt_cfg.max_hold_hours))
            opt_label = " \\[optimized params\\]"
        except Exception as exc:
            await update.message.reply_text(f"❌ Could not load optimized params: {exc}")
            return

    msg = await update.message.reply_text(
        f"⏳ Running {days}\\-day backtest on {symbol}{opt_label} "
        f"\\(real Hyperliquid data\\)\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    df = data_fetcher.get_candles(symbol, days=days)
    if df is None or df.empty:
        await msg.edit_text(f"❌ No data for {symbol}")
        return

    bt_strategy = VMRStrategy(bt_cfg)
    result = bt_strategy.run_backtest(df, symbol)

    pf_str = (
        f"{result['profit_factor']:.2f}x"
        if result["profit_factor"] != float("inf")
        else "∞"
    )

    opt_note = "\n_Using optimized params from last optimization run._" if use_opt else ""

    response = (
        f"📊 *Backtest: {symbol} ({days}d)*{opt_note}\n\n"
        f"Data: {result['total_bars']} bars (1h candles)\n"
        f"Signals detected: {result['signals_detected']}\n\n"
        f"*Results*\n"
        f"Trades:   {result['trades']}\n"
        f"Wins:     {result['wins']}\n"
        f"Losses:   {result['losses']}\n"
        f"Win Rate: {result['win_rate']:.1f}%\n"
        f"P&L:      ${result['total_pnl_usd']:+.2f}\n"
        f"Return:   {result['return_pct']:+.2f}%\n"
        f"Max DD:   {result['max_dd_pct']:.2f}%\n"
        f"P Factor: {pf_str}\n"
        f"Avg Win:  {result['avg_win_pct']:+.2f}%\n"
        f"Avg Loss: {result['avg_loss_pct']:+.2f}%\n\n"
        f"_Config: spike≥{bt_cfg.spike_threshold_pct}%, "
        f"BB={'ON' if bt_cfg.require_bb_confirmation else 'OFF'}, "
        f"SL={bt_cfg.sl_pct*100:.1f}%, TP={bt_cfg.tp_pct*100:.1f}%, "
        f"hold={bt_cfg.max_hold_hours}h_"
    )

    await msg.edit_text(response, parse_mode="Markdown")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """
    Entry point — start Telegram bot.

    Registers all command handlers and begins polling.
    The autonomous trading loop is started via /start_auto command.
    """
    logger.info("=" * 70)
    logger.info("VMR TRADING BOT — Starting up")
    logger.info("=" * 70)

    if LIVE_MODE and DRY_RUN:
        logger.info("Mode:          🔵 DRY RUN (live credentials loaded, no orders sent)")
    elif LIVE_MODE:
        network = live_trader.network_label() if live_trader else "TESTNET"
        logger.info(f"Mode:          🔴 LIVE TRADING ({network})")
    else:
        logger.info("Mode:          📄 PAPER TRADING (no real money)")

    logger.info(f"Balance:       ${paper.starting_balance:,.2f}")
    logger.info(f"Symbols:       {', '.join(CFG.symbols)}")
    logger.info(f"Spike thresh:  {CFG.spike_threshold_pct}%")
    logger.info(f"BB filter:     {'ON' if CFG.require_bb_confirmation else 'OFF'}")
    logger.info(f"SL / TP:       {CFG.sl_pct*100:.1f}% / {CFG.tp_pct*100:.1f}%")
    logger.info(f"Scan interval: {CFG.scan_interval_seconds}s ({CFG.scan_interval_seconds//60} min)")
    logger.info("=" * 70)
    logger.info("Send /start to Telegram bot to begin")
    logger.info("=" * 70)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Register all commands
    handlers = [
        ("start",            cmd_start),
        ("help",             cmd_help),
        ("start_auto",       cmd_start_auto),
        ("stop_auto",        cmd_stop_auto),
        ("stop_all",         cmd_stop_all),
        ("status",           cmd_status),
        ("signals",          cmd_signals),
        ("analyze",          cmd_analyze),
        ("backtest",         cmd_backtest),
        ("stats",            cmd_stats),
        ("balance",          cmd_balance),
        ("mode",             cmd_mode),
        # Optimization commands
        ("optimize",         cmd_optimize),
        ("set_params",       cmd_set_params),
        ("show_best_params", cmd_show_best_params),
    ]

    for cmd, handler in handlers:
        app.add_handler(CommandHandler(cmd, handler))

    logger.info("✅ Bot ready — polling Telegram ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
