#!/usr/bin/env python3
"""
Enhanced Telegram Bot with Live Signal Monitoring
Shows real-time analysis and periodic updates
Features: /stop, /shutdown, /live, /analyze, /status, /risk
"""

import asyncio
import logging
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

from config import cfg
from exchange import fetch_balance, fetch_candles
from manager import RiskManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Risk manager
risk_manager = RiskManager(
    max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
    max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
    default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
    db_path=cfg.DB_PATH,
)

# Bot state
class BotState:
    def __init__(self):
        self.last_signals = {}
        self.analysis_running = False
        self.monitoring_tasks = {}  # {chat_id: task}

bot_state = BotState()

def format_status(bal: dict, risk: dict) -> str:
    """Format status message"""
    if "error" in bal:
        return f"⚠️ Error: {bal['error']}"

    net = "🟢 TESTNET" if cfg.HL_TESTNET else "🔴 MAINNET"
    positions = bal.get("positions", [])
    pos_text = "No open positions"
    if positions:
        lines = []
        for p in positions[:3]:
            pnl = float(p.get("unrealized_pnl", 0))
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {p.get('symbol')}: {p.get('size')} (PnL: ${pnl:.2f})")
        pos_text = "\n".join(lines)
        if len(positions) > 3:
            pos_text += f"\n  ... +{len(positions)-3} more"

    can_trade = "✅ Yes" if risk.get("can_trade") else f"❌ No"

    return (
        f"📊 *Trading Bot Status* {net}\n"
        f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"💰 Account Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"📈 Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n\n"
        f"*Positions:*\n{pos_text}\n\n"
        f"*Risk Status:*\n"
        f"  Daily P&L: ${risk.get('daily_pnl', 0):,.2f} ({risk.get('daily_dd_pct', 0):.2f}%)\n"
        f"  Losses: {risk.get('consecutive_losses', 0)}/{risk_manager.max_consecutive_losses}\n"
        f"  Can Trade: {can_trade}\n\n"
        f"📋 Use /help for all commands"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    msg = (
        "🤖 *Hyperliquid Trading Bot v2*\n\n"
        "Available commands:\n"
        "  /help — Show this menu + detailed explanations\n"
        "  /status — Account + risk overview\n"
        "  /balance — Quick balance check\n"
        "  /risk — Detailed risk metrics\n"
        "  /signals — Last generated signals\n"
        "  /analyze [BTC|ETH|SOL] — Analyze symbol now\n"
        "  /live — Start 30sec live monitoring ⚡\n"
        "  /stop — Stop live monitoring\n"
        "  /shutdown — Stop entire bot\n\n"
        "🎮 Testnet Mode Active\n"
        "Type /help for detailed guide!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command with detailed explanations"""
    msg = (
        "📚 *Hyperliquid Trading Bot - Command Guide*\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*📊 STATUS & MONITORING COMMANDS*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/status**\n"
        "Shows complete bot status:\n"
        "  • Account value (balance)\n"
        "  • Margin used\n"
        "  • Open positions\n"
        "  • Daily P&L\n"
        "  • Can trade? (yes/no)\n"
        "Usage: `/status`\n\n"
        
        "**/balance**\n"
        "Quick balance check without all the details\n"
        "Usage: `/balance`\n\n"
        
        "**/risk**\n"
        "See detailed risk management status:\n"
        "  • Daily P&L (profit/loss)\n"
        "  • Daily loss limit (-5%)\n"
        "  • Consecutive losses\n"
        "  • Circuit breaker status\n"
        "Usage: `/risk`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*📈 SIGNAL & ANALYSIS COMMANDS*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/signals**\n"
        "Shows the last signals generated:\n"
        "  • BUY 📈 = Price going up\n"
        "  • SELL 📉 = Price going down\n"
        "  • HOLD ⏸️ = No clear direction\n"
        "Usage: `/signals`\n\n"
        
        "**/analyze [SYMBOL]**\n"
        "Analyze a specific symbol RIGHT NOW\n"
        "Choose: BTC, ETH, or SOL\n"
        "Shows: current price, 5h/1h change, signal\n"
        "Usage: `/analyze BTC` or `/analyze ETH`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*🎮 LIVE MONITORING & CONTROL*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/live**\n"
        "Start continuous monitoring! ⚡\n"
        "Bot will send updates every 30 seconds showing:\n"
        "  • Current price for BTC, ETH, SOL\n"
        "  • Price change (5h and 1h)\n"
        "  • Trading signal for each\n"
        "  • Current balance\n"
        "  • Daily P&L\n"
        "Usage: `/live`\n\n"
        
        "**/stop**\n"
        "Stop live monitoring immediately\n"
        "Use this to pause updates and go back to manual mode\n"
        "Usage: `/stop`\n\n"
        
        "**/shutdown**\n"
        "STOP THE ENTIRE BOT\n"
        "⚠️ This terminates all processes!\n"
        "You'll need to restart it manually.\n"
        "Usage: `/shutdown`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*💡 QUICK START GUIDE*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "1️⃣ Check status: `/status`\n"
        "2️⃣ Analyze a coin: `/analyze BTC`\n"
        "3️⃣ Watch live: `/live`\n"
        "4️⃣ Stop watching: `/stop`\n\n"
        
        "📚 For more info, ask `/help` again!\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot status"""
    await risk_manager.load_state()
    bal = fetch_balance()
    risk = risk_manager.status()
    msg = format_status(bal, risk)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick balance check"""
    bal = fetch_balance()
    if "error" in bal:
        await update.message.reply_text(f"⚠️ {bal['error']}")
        return
    
    msg = (
        f"💰 *Account Balance*\n\n"
        f"Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n"
        f"Mode: {'🟢 Testnet' if cfg.HL_TESTNET else '🔴 Mainnet'}\n"
        f"Positions: {len(bal.get('positions', []))}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Risk details"""
    await risk_manager.load_state()
    risk = risk_manager.status()
    can = "✅ Trading enabled" if risk["can_trade"] else "❌ Trading blocked"
    
    msg = (
        f"🛡️ *Risk Status*\n\n"
        f"Daily P&L: ${risk['daily_pnl']:,.2f}\n"
        f"Daily Loss %: {risk['daily_dd_pct']:.2f}%\n"
        f"DD Limit: -{risk_manager.max_daily_dd_pct}%\n\n"
        f"Consecutive Losses: {risk['consecutive_losses']}/{risk_manager.max_consecutive_losses}\n"
        f"Circuit Breaker: {'🔴 ACTIVE!' if risk['circuit_breaker_active'] else '🟢 Off'}\n\n"
        f"Status: {can}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last signals"""
    if not bot_state.last_signals:
        await update.message.reply_text("📭 No signals generated yet. Run /live or /analyze to generate signals.")
        return
    
    lines = ["📊 *Last Signals*\n"]
    for symbol, data in bot_state.last_signals.items():
        signal = data.get("signal", "?")
        price = data.get("price", 0)
        lines.append(f"{signal} {symbol}: ${price:,.2f}")
    
    msg = "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze specific symbol"""
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Usage: `/analyze BTC` (or ETH, SOL)")
        return
    
    symbol = context.args[0].upper()
    valid_symbols = ["BTC", "ETH", "SOL"]
    if symbol not in valid_symbols:
        await update.message.reply_text(f"Invalid symbol. Use: {', '.join(valid_symbols)}")
        return
    
    await update.message.reply_text(f"🔄 Analyzing {symbol}...")
    
    try:
        candles_data = fetch_candles(symbol, "1h", 100)
        candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
        
        if not candles or len(candles) < 20:
            await update.message.reply_text(f"⚠️ Insufficient data for {symbol}")
            return
        
        closes = []
        for c in candles:
            if isinstance(c, dict):
                closes.append(float(c.get("c", c.get("close", 0))))
            else:
                closes.append(float(c[4]))
        
        current_price = closes[-1]
        recent_change = (closes[-1] - closes[-5]) / closes[-5] * 100
        signal = "📈 BUY" if recent_change > 1 else "📉 SELL" if recent_change < -1 else "⏸️ HOLD"
        
        msg = (
            f"*{symbol} Analysis*\n\n"
            f"Price: ${current_price:,.2f}\n"
            f"5h Change: {recent_change:+.2f}%\n"
            f"Candles: {len(closes)}\n\n"
            f"Signal: {signal}\n"
            f"Status: Ready for trading"
        )
        
        bot_state.last_signals[symbol] = {
            "signal": signal,
            "price": current_price,
            "timestamp": datetime.now().isoformat()
        }
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await update.message.reply_text(f"❌ Analysis failed: {str(e)}")

async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start live monitoring"""
    chat_id = update.message.chat_id
    
    if chat_id in bot_state.monitoring_tasks:
        await update.message.reply_text(
            "⚠️ *Already Monitoring*\n\n"
            "Live monitoring is already running.\n"
            "Use /stop to stop it first."
        )
        return
    
    await update.message.reply_text(
        "🟢 *Live Monitoring Started*\n\n"
        "Analyzing BTC, ETH, SOL every 30 seconds...\n"
        "You'll receive updates automatically.\n\n"
        "📋 Commands:\n"
        "  /stop  — Stop live monitoring\n"
        "  /analyze [BTC|ETH|SOL] — Single analysis\n"
        "  /status — Quick status check"
    )
    
    task = asyncio.create_task(monitor_signals(chat_id, context.application))
    bot_state.monitoring_tasks[chat_id] = task

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop live monitoring"""
    chat_id = update.message.chat_id
    
    if chat_id not in bot_state.monitoring_tasks:
        await update.message.reply_text(
            "ℹ️ *No Monitoring Active*\n\n"
            "Live monitoring is not running.\n"
            "Use /live to start it."
        )
        return
    
    task = bot_state.monitoring_tasks[chat_id]
    task.cancel()
    del bot_state.monitoring_tasks[chat_id]
    
    await update.message.reply_text(
        "🛑 *Live Monitoring Stopped*\n\n"
        "Updates have been stopped.\n\n"
        "Use /live to restart or /help for other commands."
    )

async def cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shutdown entire bot"""
    if update.message.chat_id != int(cfg.TELEGRAM_CHAT_ID):
        await update.message.reply_text("❌ Unauthorized")
        return
    
    # Cancel all tasks
    for task in bot_state.monitoring_tasks.values():
        task.cancel()
    bot_state.monitoring_tasks.clear()
    
    await update.message.reply_text(
        "🛑 *Bot Shutting Down*\n\n"
        "All processes stopping...\n"
        "Bot will exit in 2 seconds."
    )
    
    logger.info("🛑 Shutdown initiated")
    await asyncio.sleep(2)
    os._exit(0)

async def monitor_signals(chat_id: int, app: Application):
    """Monitor and send signal updates"""
    symbols = ["BTC", "ETH", "SOL"]
    iteration = 0
    
    try:
        while True:
            try:
                iteration += 1
                timestamp = datetime.now().strftime("%H:%M:%S")
                update_lines = [f"📊 *Update #{iteration}* ({timestamp})\n"]
                
                for symbol in symbols:
                    try:
                        candles_data = fetch_candles(symbol, "1h", 50)
                        candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
                        
                        if candles and len(candles) >= 10:
                            closes = [float(c.get("c", 0) if isinstance(c, dict) else c[4]) for c in candles]
                            price = closes[-1]
                            change = (closes[-1] - closes[-3]) / closes[-3] * 100 if closes[-3] > 0 else 0
                            signal = "📈" if change > 0.5 else "📉" if change < -0.5 else "⏸️"
                            update_lines.append(f"{signal} {symbol}: ${price:,.2f} ({change:+.2f}%)")
                            
                            bot_state.last_signals[symbol] = {
                                "signal": signal,
                                "price": price,
                                "change": change,
                                "timestamp": timestamp
                            }
                    except Exception as e:
                        logger.error(f"Analysis {symbol} failed: {e}")
                        update_lines.append(f"⚠️ {symbol}: Error")
                
                await app.bot.send_message(chat_id=chat_id, text="\n".join(update_lines), parse_mode="Markdown")
                await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                logger.info(f"Monitor cancelled for {chat_id}")
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass

def run_bot():
    """Start Telegram bot"""
    if not cfg.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(cfg.TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("live", cmd_live))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    
    logger.info("🤖 Telegram Bot v2 Enhanced starting...")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
