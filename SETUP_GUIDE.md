# Hyperliquid Trading Bot — Complete Setup Guide

Schritt-für-Schritt Anleitung zum Einrichten und Starten des VMR-Bots.

## 📋 Voraussetzungen

- **Python 3.10+** (prüfen: `python3 --version`)
- **Git** (prüfen: `git --version`)
- **Ein Telegram-Konto**
- **Ca. 30 Minuten Zeit**

---

## 🔧 Schritt 1: Hyperliquid Testnet Account erstellen

Der Bot läuft **zuerst auf Testnet** (keine echten Kosten, nur Play-Money).

### 1.1 Wallet vorbereiten

Du brauchst eine **Ethereum-kompatible Wallet** (MetaMask, Ledger, etc.).

**Empfohlen: MetaMask** (kostenlos, einfach)
- Download: https://metamask.io/
- Extension installieren
- Neue Wallet erstellen oder existierende importieren
- Notiz: Deine **Wallet-Adresse** (beginnt mit `0x...`)

### 1.2 Hyperliquid Testnet Account

1. Gehe zu: https://app.hyperliquid-testnet.xyz
2. Klick auf **"Connect Wallet"** → wähle MetaMask
3. Genehmige die Verbindung in MetaMask
4. ✅ Du bist jetzt auf dem **Hyperliquid Testnet**
5. Notiz: Deine **Wallet-Adresse** aus der App (oben rechts)

### 1.3 Testnet USD bekommen (kostenlos)

1. In der Hyperliquid App:
   - Gehe zu **"Portfolio"** oder **"Funding"**
   - Suche **"Faucet"** oder **"Claim Testnet USD"**
   - Klick auf **"Claim"** → erhalte kostenlos ~100 USD in Testnet-Tokens
2. ✅ Jetzt hast du Testnet-Kapital

---

## 🔑 Schritt 2: Hyperliquid API Keys generieren

### 2.1 Private Key aus MetaMask exportieren

⚠️ **WARNUNG: NIEMALS deinen Private Key mit anderen teilen!**

**Auf Desktop (MetaMask):**
1. Klick auf dein Profil (oben rechts in MetaMask)
2. **Settings** → **Security & Privacy**
3. **"Reveal private key"** → Gib dein Passwort ein
4. Kopiere die lange Hex-String (beginnt mit `0x...`)
5. **Speichere das SICHER ab** (z.B. in deinem Password Manager)

### 2.2 Notiere deine Credentials

```
HL_SECRET_KEY   = 0x...  (Private Key aus MetaMask)
HL_WALLET_ADDRESS = 0x...  (Deine Wallet-Adresse)
HL_TESTNET      = true   (Testnet-Modus)
```

---

## 💬 Schritt 3: Telegram Bot erstellen

### 3.1 Bot Token bekommen

1. Öffne Telegram
2. Suche nach **@BotFather**
3. Schreib `/newbot`
4. Folge den Instruktionen (Name + Username vergeben)
5. ✅ Du erhältst einen **Token** (z.B. `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 3.2 Deine Telegram Chat-ID finden

1. Starte eine Unterhaltung mit deinem neuen Bot (klick auf den Link in BotFather)
2. Gehe zu: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Suche in der JSON-Response nach:
   ```json
   "chat": { "id": 123456789 }
   ```
4. **Notiere die `id`** — das ist deine Chat-ID

---

## 💾 Schritt 4: Repository klonen & konfigurieren

### 4.1 Code downloaden

```bash
git clone https://github.com/lordvampire/hyperliquid-trading-bot.git
cd hyperliquid-trading-bot
```

### 4.2 Python Environment erstellen

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4.3 Umgebungsvariablen konfigurieren

```bash
cp example.env .env
nano .env
```

Fülle diese Werte aus:

```env
# Hyperliquid
HL_SECRET_KEY=0x...                 # Dein Private Key (Schritt 2.2)
HL_WALLET_ADDRESS=0x...             # Deine Wallet-Adresse
HL_TESTNET=true                     # true = Testnet, false = Mainnet
HL_DRY_RUN=false                    # true = Pre-flight only, keine echten Orders

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...  # Token (Schritt 3.1)
TELEGRAM_CHAT_ID=123456789            # Chat ID (Schritt 3.2)

# Paper Trading (wenn HL_SECRET_KEY fehlt → Paper-Modus)
PAPER_BALANCE=10000.0
```

> **Modus-Erkennung automatisch:**
> - `HL_SECRET_KEY` gesetzt → **LIVE-Modus** (echte Testnet-Orders)
> - `HL_SECRET_KEY` fehlt → **Paper-Modus** (Simulation, kein echtes Geld)
> - `HL_DRY_RUN=true` → **Dry Run** (validiert Orders, sendet nichts)

---

## 🚀 Schritt 5: Bot starten & testen

### 5.1 Bot starten

```bash
python3 vmr_trading_bot.py
```

Erwarteter Output:
```
2026-03-01 12:29:10 - [INFO] - LiveTrader initialising — TESTNET
2026-03-01 12:29:10 - [INFO] - ✅ Info client ready
2026-03-01 12:29:12 - [INFO] - ✅ Bot ready. Polling for Telegram messages...
```

✅ Der Bot hört jetzt auf deine Telegram Commands!

### 5.2 Testen: Telegram Commands

In Telegram bei deinem Bot:

```
/start          → Willkommensnachricht + Schnellstatus
/status         → Balance, Positionen, Loop-Info
/balance        → Kontostand + Risk-Limits
/mode           → Aktueller Modus (LIVE/PAPER/DRY-RUN)
```

✅ Du erhältst Live-Responses!

---

## 📊 Schritt 6: Erste Analysen

### 6.1 Signal analysieren

```
/analyze BTC
```

Output:
```
🔍 VMR Analysis — BTC
1h Return: -1.2% (spike detected!)
BB Lower: $64,500 | Current: $64,400 (below band)
→ Signal: LONG @ $64,400 | SL: $64,080 | TP: $65,360
Confidence: 0.85
```

### 6.2 Alle Signale anzeigen

```
/signals
```

Output für alle 3 Symbole (BTC, ETH, SOL).

### 6.3 Backtest laufen lassen

```
/backtest BTC 30
```

Testet die VMR-Strategie auf den letzten 30 Tagen echter Daten.

---

## 🔧 Schritt 7: Parameter optimieren (empfohlen)

Bevor du live handelst, optimiere die Parameter:

```
/optimize BTC ETH SOL
```

Dauert 5–15 Minuten. Testet ~10.000 Parameterkombinationen.

Danach:
```
/show_best_params
```

Zeigt die Top-3 Parametersätze. Wähle einen aus und setze ihn:

```
/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
```

---

## 🤖 Schritt 8: Autonomes Trading starten

```
/start_auto
```

Der Bot scannt jetzt alle 15 Minuten BTC, ETH, SOL auf Signale und öffnet/schließt Positionen automatisch.

Stoppen:
```
/stop_auto       → Stoppt den Loop (Positionen bleiben offen)
/stop_all        → Stoppt Loop + schließt alle Positionen
```

---

## 🛡️ Troubleshooting

### Problem: Bot startet nicht

```bash
# Python-Version prüfen
python3 --version  # Muss 3.10+ sein

# Dependencies nochmal installieren
pip install -r requirements.txt
```

### Problem: "ModuleNotFoundError: No module named 'hyperliquid'"

```bash
pip install hyperliquid-python-sdk
```

### Problem: "invalid private key"

- Prüfe ob `HL_SECRET_KEY` in `.env` mit `0x` beginnt
- Keine Leerzeichen oder Anführungszeichen

### Problem: Telegram Bot antwortet nicht

1. Prüfe ob Bot-Terminal noch läuft (`python3 vmr_trading_bot.py`)
2. Prüfe ob `TELEGRAM_BOT_TOKEN` korrekt in `.env`
3. Prüfe ob `TELEGRAM_CHAT_ID` korrekt (nur Ziffern)

### Problem: "No signals" — keine Trades

Der Markt ist ruhig, keine Spikes gefunden. Optionen:
- Threshold senken: `/set_params spike=0.7 bb_mult=1.5`
- Oder warten auf volatile Marktphasen

---

## 📈 Nächste Schritte

1. **Paper Trading:** Lass Bot 24–48h im Paper-Modus laufen
2. **Optimierung:** `/optimize BTC ETH SOL` → beste Parameter finden
3. **Backtest:** `/backtest BTC 30` → out-of-sample prüfen
4. **Live Testnet:** `HL_SECRET_KEY` setzen, klein starten (`size=0.005`)
5. **Live Mainnet:** Wenn zuversichtlich → `HL_TESTNET=false`, **mit kleinem Kapital starten**

---

## 🔐 Security Best Practices

### NIEMALS:
- ❌ Private Keys in Git committen
- ❌ `.env` auf GitHub pushen
- ❌ Tokens in Telegram-Nachrichten posten
- ❌ Screenshots von Private Keys teilen

### IMMER:
- ✅ `.env` in `.gitignore` halten
- ✅ Keys im Password Manager speichern
- ✅ Erst auf Testnet testen, dann Mainnet
- ✅ Klein starten (`position_size_pct=0.005`)

---

## 📚 Weitere Ressourcen

- **[README.md](./README.md)** — Übersicht VMR-Strategie
- **[README_VMR.md](./README_VMR.md)** — Detaillierter VMR-Guide (EN)
- **[USER_MANUAL.md](./USER_MANUAL.md)** — Vollständiges Benutzerhandbuch (EN)
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — Live-Deployment-Guide
- **Hyperliquid Testnet:** https://app.hyperliquid-testnet.xyz
- **Telegram Bot API:** https://core.telegram.org/bots/api

---

**Viel Erfolg beim Trading! 🚀**
