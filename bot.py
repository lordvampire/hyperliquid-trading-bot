"""Telegram bot — alerts and commands for the trading bot."""

import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import cfg
from exchange import fetch_balance
from manager import RiskManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bug #3 fix: Use DB-backed RiskManager so state is shared with API process
risk_manager = RiskManager(
    max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
    max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
    default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
    db_path=cfg.DB_PATH,
)


def format_status(bal: dict, risk: dict) -> str:
    """Format a nice status message for Telegram."""
    if "error" in bal:
        return f"⚠️ Error: {bal['error']}"

    net = "🟢 TESTNET" if cfg.HL_TESTNET else "🔴 MAINNET"
    positions = bal.get("positions", [])
    pos_text = "No open positions"
    if positions:
        lines = []
        for p in positions:
            pnl = float(p["unrealized_pnl"])
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {p['symbol']}: {p['size']} @ {p['entry_price']} (PnL: ${pnl:.2f})")
        pos_text = "\n".join(lines)

    can_trade = "✅ Yes" if risk.get("can_trade") else f"❌ No — {risk.get('reason')}"

    return (
        f"📊 *Trading Bot Status* {net}\n\n"
        f"💰 Account Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"📈 Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n\n"
        f"*Positions:*\n{pos_text}\n\n"
        f"*Risk:*\n"
        f"  Daily P&L: ${risk.get('daily_pnl', 0):,.2f} ({risk.get('daily_dd_pct', 0):.2f}%)\n"
        f"  Consecutive Losses: {risk.get('consecutive_losses', 0)}\n"
        f"  Can Trade: {can_trade}"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Hyperliquid Trading Bot active. Use /status to check.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await risk_manager.load_state()  # Bug #3: reload shared state from DB
    bal = fetch_balance()
    risk = risk_manager.status()
    msg = format_status(bal, risk)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = fetch_balance()
    if "error" in bal:
        await update.message.reply_text(f"⚠️ {bal['error']}")
        return
    await update.message.reply_text(
        f"💰 Account Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"📈 Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n"
        f"🌐 {'Testnet' if cfg.HL_TESTNET else 'Mainnet'}"
    )


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await risk_manager.load_state()  # Bug #3: reload shared state from DB
    risk = risk_manager.status()
    can = "✅" if risk["can_trade"] else "❌"
    await update.message.reply_text(
        f"🛡️ *Risk Status*\n\n"
        f"Daily P&L: ${risk['daily_pnl']:,.2f} ({risk['daily_dd_pct']:.2f}%)\n"
        f"DD Cap: -{risk_manager.max_daily_dd_pct}%\n"
        f"Consecutive Losses: {risk['consecutive_losses']}/{risk_manager.max_consecutive_losses}\n"
        f"Circuit Breaker: {'🔴 ACTIVE' if risk['circuit_breaker_active'] else '🟢 OFF'}\n"
        f"Can Trade: {can}",
        parse_mode="Markdown"
    )


def run_bot():
    if not cfg.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set, bot not starting")
        return

    app = Application.builder().token(cfg.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("risk", cmd_risk))

    logger.info("Telegram bot starting...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
