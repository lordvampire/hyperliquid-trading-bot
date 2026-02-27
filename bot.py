#!/usr/bin/env python3
"""
Enhanced Telegram Bot with Live Signal Monitoring
Shows real-time analysis and periodic updates
Features: /stop, /shutdown, /live, /analyze, /status, /risk,
          /optimize, /paper_trade, /go_live  (Phase 4)
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
from backtest_engine import BacktestEngine, format_backtest_result

# Phase 4 imports
try:
    from config.manager import ConfigManager
    from safety_manager import SafetyManager
    from live_deployment import LiveDeployment
    from optimization_runner import OptimizationRunner
    from paper_trader import PaperTrader
    from strategies.strategy_b import StrategyB
    _PHASE4_AVAILABLE = True
except ImportError as _p4_err:
    _PHASE4_AVAILABLE = False
    logging.getLogger(__name__).warning(f"Phase 4 modules not fully available: {_p4_err}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Phase 4: global config + safety manager ----------------------------
_p4_config: "ConfigManager | None" = None
_p4_safety: "SafetyManager | None" = None
_live_deployment: "LiveDeployment | None" = None

def _get_p4_config() -> "ConfigManager | None":
    global _p4_config
    if _p4_config is None and _PHASE4_AVAILABLE:
        try:
            _p4_config = ConfigManager("config/base.yaml", "backtest")
        except Exception as exc:
            logger.warning(f"Could not load Phase 4 config: {exc}")
    return _p4_config

def _get_p4_safety() -> "SafetyManager | None":
    global _p4_safety
    if _p4_safety is None and _PHASE4_AVAILABLE:
        cfg_obj = _get_p4_config()
        if cfg_obj:
            _p4_safety = SafetyManager(cfg_obj)
    return _p4_safety

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
        "  /backtest [days] — Test on past data 🔬\n"
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
        "*🔬 BACKTESTING & ANALYSIS*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/backtest [strategy] [days] [symbols]**\n"
        "Test strategy on past N days of data\n"
        "Strategies: `simple` | `improved` | `mean_reversion`\n"
        "Default: improved strategy, 7 days, BTC ETH SOL\n\n"
        
        "*Strategies:*\n"
        "  `simple` — Old momentum (not recommended)\n"
        "  `improved` — Multi-filter + RSI (⭐ BEST)\n"
        "  `mean_reversion` — Buy dips, sell rallies\n\n"
        
        "Usage:\n"
        "  `/backtest` — Improved, 7d, BTC/ETH/SOL\n"
        "  `/backtest improved 14` — Improved, 14 days\n"
        "  `/backtest mean_reversion 7 BTC` — MeanRev, 7d, BTC\n"
        "  `/backtest simple 30` — Old strat, 30 days\n\n"
        "Max: 60 days, 5 symbols per test\n\n"
        
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
    """Bot status — includes Phase 4 safety checks if available"""
    await risk_manager.load_state()
    bal = fetch_balance()
    risk = risk_manager.status()
    msg = format_status(bal, risk)

    # Phase 4: append safety check summary
    safety = _get_p4_safety()
    if safety:
        can_trade = safety.check_daily_limit()
        ct_icon = "✅" if can_trade else "🔴"
        msg += f"\n\n🛡️ *Safety (Phase 4):*\n  Circuit Breaker: {ct_icon} {'OFF' if can_trade else 'ACTIVE'}"
        if _live_deployment:
            status = _live_deployment.get_status()
            msg += f"\n  Live trading: {'🟢 Running' if status['running'] else '⚪ Stopped'}"
            msg += f"\n  Open positions: {len(status['open_positions'])}"

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
    """Risk details — includes Phase 4 safety circuit breaker"""
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

    # Phase 4 safety additions
    safety = _get_p4_safety()
    if safety:
        p4_cb = not safety.check_daily_limit()
        msg += (
            f"\n\n*Phase 4 Safety Manager:*\n"
            f"  Max Daily DD: {safety.max_daily_dd_pct}%\n"
            f"  Max Leverage: {safety.max_leverage}x\n"
            f"  Max Slippage: {safety.max_slippage_pct}%\n"
            f"  Circuit Breaker: {'🔴 ACTIVE' if p4_cb else '🟢 Off'}"
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

async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run backtest on historical data"""
    # Parse arguments: /backtest [strategy] [days] [symbols]
    # Strategies: simple, improved, mean_reversion
    # Default: improved strategy, 7 days, BTC ETH SOL
    
    strategy = "improved"
    days = 7
    symbols = ["BTC", "ETH", "SOL"]
    
    if context.args:
        arg_idx = 0
        
        # Check if first arg is a strategy
        if context.args[arg_idx] in ["simple", "improved", "mean_reversion"]:
            strategy = context.args[arg_idx]
            arg_idx += 1
        
        # Parse days
        if arg_idx < len(context.args):
            try:
                days = int(context.args[arg_idx])
                if days < 1 or days > 60:
                    await update.message.reply_text("⚠️ Days must be between 1 and 60")
                    return
                arg_idx += 1
            except ValueError:
                pass
        
        # Parse symbols
        if arg_idx < len(context.args):
            symbols = [s.upper() for s in context.args[arg_idx:]]
            if len(symbols) > 5:
                await update.message.reply_text("⚠️ Max 5 symbols allowed")
                return
    
    strategy_names = {
        "simple": "Simple Momentum",
        "improved": "Multi-Filter",
        "mean_reversion": "Mean Reversion"
    }
    
    await update.message.reply_text(
        f"📊 Backtesting {', '.join(symbols)}\n"
        f"Strategy: {strategy_names[strategy]} | Days: {days}\n"
        f"Please wait (this may take a moment)..."
    )
    
    try:
        engine = BacktestEngine(starting_balance=1000.0)
        results = {}
        
        for symbol in symbols:
            result = engine.backtest_symbol(symbol, days, strategy)
            results[symbol] = result
        
        formatted = format_backtest_result(results)
        await update.message.reply_text(formatted, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        await update.message.reply_text(f"❌ Backtest failed: {str(e)}")

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

# ============================================================
# PHASE 4 COMMANDS
# ============================================================

async def cmd_optimize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /optimize [symbol] [days]
    Trigger OptimizationRunner: sensitivity + grid search → best params.
    """
    if not _PHASE4_AVAILABLE:
        await update.message.reply_text("❌ Phase 4 modules not available.")
        return

    symbol = context.args[0].upper() if context.args else "BTC"
    try:
        days = int(context.args[1]) if len(context.args) > 1 else 30
    except (ValueError, IndexError):
        days = 30

    await update.message.reply_text(
        f"⚙️ *Running optimization for {symbol} ({days}d)…*\n"
        f"Sensitivity + Grid Search — this may take 30–120 seconds.",
        parse_mode="Markdown",
    )

    try:
        runner = OptimizationRunner(symbol, days, config_path="config/base.yaml")
        results = runner.quick_optimization("optimization_results")
        best = results.get("best_params", {})
        sharpe = results.get("sharpe_final", 0.0)
        msg = (
            f"✅ *Optimization complete for {symbol}*\n\n"
            f"Best Sharpe: `{sharpe:.3f}`\n"
            f"Best Params:\n"
        )
        for k, v in best.items():
            msg += f"  `{k}`: {v}\n"
        msg += "\nParams saved to `param_history.json`"
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as exc:
        logger.error(f"Optimize error: {exc}")
        await update.message.reply_text(f"❌ Optimization failed: {exc}")


async def cmd_paper_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /paper_trade [symbol] [days]
    Run PaperTrader on recent data, compare vs backtest, report divergence.
    """
    if not _PHASE4_AVAILABLE:
        await update.message.reply_text("❌ Phase 4 modules not available.")
        return

    symbol = context.args[0].upper() if context.args else "BTC"
    try:
        days = int(context.args[1]) if len(context.args) > 1 else 14
    except (ValueError, IndexError):
        days = 14

    await update.message.reply_text(
        f"📄 *Running paper trade for {symbol} ({days}d)…*",
        parse_mode="Markdown",
    )

    try:
        config   = _get_p4_config()
        strategy = StrategyB(config.strategy("strategy_b"), "paper")
        trader   = PaperTrader(strategy, config)

        result = trader.paper_trade(symbol, starting_balance=1000.0, duration_days=days)
        comparison = trader.compare_backtest_vs_paper(symbol, days=days)

        pnl      = result.get("total_pnl", 0.0)
        ret_pct  = result.get("return_pct", 0.0) * 100
        n_trades = result.get("num_trades", 0)
        alerts   = comparison.get("divergence_alerts", [])

        msg = (
            f"📄 *Paper Trade Result — {symbol} ({days}d)*\n\n"
            f"P&L: `${pnl:+.2f}` ({ret_pct:+.2f}%)\n"
            f"Trades: {n_trades}\n"
        )
        if alerts:
            msg += f"\n⚠️ *Divergence Alerts ({len(alerts)}):*\n"
            for a in alerts[:3]:
                msg += f"  • {a}\n"
        else:
            msg += "\n✅ No model drift detected."

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as exc:
        logger.error(f"Paper trade error: {exc}")
        await update.message.reply_text(f"❌ Paper trade failed: {exc}")


async def cmd_go_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /go_live [symbol] [amount]
    ADMIN ONLY — Start LiveDeployment with the given starting capital.
    """
    global _live_deployment

    if not _PHASE4_AVAILABLE:
        await update.message.reply_text("❌ Phase 4 modules not available.")
        return

    # Admin check — use config admin_user_ids
    config = _get_p4_config()
    admin_ids = config.get("telegram.admin_user_ids", []) if config else []
    user_id = update.effective_user.id

    if admin_ids and user_id not in admin_ids:
        logger.warning(f"Unauthorized /go_live attempt from user_id={user_id}")
        await update.message.reply_text("❌ Unauthorized. Admin only.")
        return

    symbol = context.args[0].upper() if context.args else "BTC"
    try:
        amount = float(context.args[1]) if len(context.args) > 1 else 100.0
    except (ValueError, IndexError):
        amount = 100.0

    await update.message.reply_text(
        f"🚀 *Starting live trading…*\n\nSymbol: {symbol}\nCapital: ${amount:,.2f}\n\n"
        "⚠️ Safety checks will run before every trade.",
        parse_mode="Markdown",
    )

    try:
        strategy = StrategyB(config.strategy("strategy_b"), "live")
        safety   = _get_p4_safety()
        # Override starting capital
        config._data.setdefault("deployment", {})["starting_capital"] = amount

        deployer = LiveDeployment(
            strategy=strategy,
            config=config,
            exchange=None,          # None = dry-run until mainnet is configured
            safety_manager=safety,
        )
        deployer.start_trading()
        _live_deployment = deployer

        # Audit the go-live event
        safety.log_trade(
            trade_id=f"GO_LIVE-{user_id}",
            symbol=symbol,
            signal=__import__("strategies.base", fromlist=["Signal"]).Signal(
                symbol, "HOLD", 0.0, 0.0, 0.0,
                {"event": "go_live", "admin_id": user_id, "amount": amount}
            ),
            entry_price=0.0,
            size=0.0,
            status="go_live",
        )

        status = deployer.get_status()
        msg = (
            f"✅ *Live trading started on {symbol}*\n\n"
            f"Capital: `${amount:,.2f}`\n"
            f"Can trade: {'✅' if status['can_trade'] else '❌'}\n"
            f"Circuit breaker: {'🔴 ACTIVE' if status['circuit_breaker'] else '🟢 Off'}\n\n"
            f"Use /status to monitor."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as exc:
        logger.error(f"Go-live error: {exc}")
        await update.message.reply_text(f"❌ Go-live failed: {exc}")


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
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    # Phase 4 commands
    app.add_handler(CommandHandler("optimize", cmd_optimize))
    app.add_handler(CommandHandler("paper_trade", cmd_paper_trade))
    app.add_handler(CommandHandler("go_live", cmd_go_live))
    
    logger.info("🤖 Telegram Bot v2 Enhanced starting...")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
