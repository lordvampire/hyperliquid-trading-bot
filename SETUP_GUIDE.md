# Hyperliquid Trading Bot — Complete Setup Guide

Schritt-für-Schritt Anleitung zum Testen und Starten des Bots.

## 📋 Voraussetzungen

- **Python 3.10+** (prüfen: `python3 --version`)
- **Git** (prüfen: `git --version`)
- **Ein Telegram-Konto**
- **Ca. 30 Minuten Zeit**

---

## 🔧 Schritt 1: Hyperliquid Testnet Account erstellen

Der Bot läuft **zuerst auf Testnet** (keine echten Pesos, nur Play-Money).

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

Der Bot braucht **private Keys** um automatisch zu traden.

### 2.1 Private Key aus MetaMask exportieren

⚠️ **WARNUNG: NIEMALS deinen Private Key mit anderen teilen!**

**Auf Desktop (MetaMask):**
1. Klick auf dein Profil (oben rechts in MetaMask)
2. **Settings** → **Security & Privacy**
3. **"Reveal private key"** → Gib dein Passwort ein
4. Kopiere die lange Hex-String (beginnt mit `0x...`)
5. **Speichere das SICHER ab** (z.B. in deinem Password Manager)

**Auf Mobile (MetaMask):**
1. Tap das Menü (≡) oben rechts
2. **Settings** → **Security**
3. **"Reveal Private Key"** → Gib Passwort ein
4. Kopiere den Key

### 2.2 Notiere deine Credentials

Speichere diese 3 Dinge **SICHER** ab:

```
HYPERLIQUID_PRIVATE_KEY = 0x... (Private Key aus MetaMask)
HYPERLIQUID_WALLET_ADDRESS = 0x... (Deine Wallet-Adresse)
HYPERLIQUID_TESTNET = true (ist Testnet, kein Mainnet)
```

---

## 💬 Schritt 3: Telegram Bot erstellen

Der Bot sendet dir Live-Alerts über Telegram (z.B. "BTC Long @ $95,000 | SL @ $94,500").

### 3.1 Bot Token bekommen

1. Öffne Telegram (Web oder App)
2. Suche nach **@BotFather**
3. Schreib `/newbot`
4. Folge den Instruktionen:
   - **Name:** z.B. "Mein Hyperliquid Bot"
   - **Username:** z.B. `my_hl_bot_123` (muss unique sein)
5. ✅ Du erhältst einen **Token** (lange Nummer)
   - Beispiel: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
6. **Speichere den Token!**

### 3.2 Deine Telegram Chat-ID finden

1. Starte eine Unterhaltung mit deinem Bot: `@my_hl_bot_123` / **Start**
2. Gehe zu: https://api.telegram.org/bot<TOKEN>/getUpdates
   - Ersetze `<TOKEN>` mit deinem Token von oben
   - Beispiel: `https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/getUpdates`
3. Du siehst eine JSON-Response. Suche nach:
   ```json
   "chat": {
     "id": 123456789,
     ...
   }
   ```
4. **Notiere die `id`** (deine Chat-ID)

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

Kopiere die Example-Datei:
```bash
cp example.env .env
```

Öffne `.env` mit deinem Editor (z.B. VS Code, nano):
```bash
nano .env
```

Fülle diese Werte aus (von Schritt 1-3):

```env
# Hyperliquid Testnet
HL_SECRET_KEY=0x...                    # Dein Private Key (Schritt 2.2)
HL_WALLET_ADDRESS=0x...                # Deine Wallet-Adresse (Schritt 2.2)
HL_TESTNET=true                        # true = Testnet, false = Mainnet

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...   # Token (Schritt 3.1)
TELEGRAM_CHAT_ID=123456789             # Chat ID (Schritt 3.2)

# Risk Management (optional, Defaults OK)
DAILY_DRAWDOWN_LIMIT=0.05              # 5% max Tagesverlust
CIRCUIT_BREAKER_LOSSES=3               # Stop nach 3 Verlusten
POSITION_SIZE_PERCENT=0.02             # 2% der Balance pro Trade
```

Speichern (CTRL+S, dann CTRL+X im nano).

---

## 🚀 Schritt 5: Bot starten & testen

### 5.1 API Server starten

```bash
python3 main.py
```

Erwarteter Output:
```
INFO: Uvicorn running on http://127.0.0.1:8000
...
```

✅ Der API-Server läuft jetzt auf `http://localhost:8000`

### 5.2 In anderem Terminal: Telegram Bot starten

```bash
python3 bot.py
```

Erwarteter Output:
```
INFO: Telegram bot started. Listening for commands...
```

✅ Der Bot hört jetzt auf deine Telegram Commands

### 5.3 Testen: API Health Check

In **neuem Terminal** (während beide oben laufen):

```bash
curl http://localhost:8000/health
```

Erwarteter Output:
```json
{
  "status": "healthy",
  "config": {
    "testnet": true,
    "leverage": 35,
    ...
  }
}
```

✅ API funktioniert!

### 5.4 Testen: Account Status

```bash
curl http://localhost:8000/status
```

Erwarteter Output:
```json
{
  "balance": 100.5,
  "positions": [],
  "risk_status": "healthy",
  ...
}
```

✅ Du siehst deine Testnet Balance!

### 5.5 Testen: Telegram Commands

In Telegram bei deinem Bot:

```
/start         → Bot wird aktiviert
/status        → Zeigt Balance + Positions + Risk
/balance       → Zeigt nur Balance
/risk          → Risk Manager Status
```

✅ Du erhältst Live-Responses!

---

## 📊 Schritt 6: Erste Test-Trades

### 6.1 Next Signal abrufen

```bash
curl "http://localhost:8000/next_signal?symbol=BTC"
```

Erwarteter Output:
```json
{
  "symbol": "BTC",
  "signal": "HOLD",
  "sentiment_score": 0.15,
  "funding_trend": "RISING",
  "confidence": 0.20
}
```

### 6.2 Trade manuell ausführen (optional)

Über Telegram:
```
/execute_trade BTC LONG 0.01 47500 46500
```

Bedeutung:
- `BTC` = Symbol
- `LONG` = Long-Position (Preis steigt)
- `0.01` = Größe in BTC
- `47500` = Take-Profit (Gewinn-Level)
- `46500` = Stop-Loss (Verlust-Level)

✅ Du erhältst Telegram-Alerts wenn Trade aktiviert!

### 6.3 Backtest laufen lassen

```bash
curl -X POST http://localhost:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTC", "days": 7}'
```

Erwarteter Output:
```json
{
  "symbol": "BTC",
  "period_days": 7,
  "trades": 3,
  "win_rate": 0.67,
  "total_pnl": 125.50,
  ...
}
```

✅ Du siehst wie gut die Strategie funktioniert!

---

## 🛡️ Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'hyperliquid'"

**Lösung:**
```bash
pip install hyperliquid
```

### Problem: "invalid private key"

**Lösung:**
- Prüfe ob `HL_SECRET_KEY` in `.env` mit `0x` anfängt
- Keine Spaces/Anführungszeichen

### Problem: Telegram Bot antwortet nicht

**Lösung:**
1. Prüfe ob Bot-Terminal noch läuft (`python3 bot.py`)
2. Prüfe ob `TELEGRAM_BOT_TOKEN` korrekt in `.env`
3. Prüfe ob `TELEGRAM_CHAT_ID` korrekt (sollte Ziffer sein)

### Problem: "HL_TESTNET is not true"

**Lösung:**
- In `.env` muss sein: `HL_TESTNET=true` (kein Anführungszeichen!)

### Problem: API gibt "401 Unauthorized"

**Lösung:**
- Hyperliquid API Key ist ungültig
- Prüfe Private Key in `.env`
- Regeneriere neuen Key

---

## 📈 Nächste Schritte (nach erfolgreichem Test)

1. **Testnet Extended Run:** Lass Bot 24h+ auf Testnet laufen
2. **Monitoring:** Prüf Telegram-Alerts & Trade-Logs
3. **Backtesting:** Teste verschiedene Symbole (BTC, ETH, SOL, etc.)
4. **Live Mainnet:** Wenn zuversichtlich, auf Mainnet starten
   - ⚠️ Aber: Mit **kleinem Capital starten** (~$100 zum Testen)
   - Mit 35x Leverage = $3,500 Notional (Risk-Management ist wichtig!)

---

## 🔐 Security Best Practices

### NIEMALS:

- ❌ Private Keys in Git committen
- ❌ .env datei pushen auf GitHub
- ❌ Tokens in Telegram nachrichten posten
- ❌ Screenshots von Private Keys teilen

### IMMER:

- ✅ .env in `.gitignore` halten
- ✅ Keys in securerem Password Manager speichern
- ✅ Regelmäßig Test-Keys rotieren (neue Key generieren, alte löschen)
- ✅ Nur kleine Beträge auf Live-Mainnet starten

---

## 📞 Support & Feedback

Probleme? Fragen?

1. Prüf **Troubleshooting** Sektion oben
2. Check GitHub Issues: https://github.com/lordvampire/hyperliquid-trading-bot/issues
3. Kontakt: faruk.tuefekli@gmail.com

---

## 📚 Weitere Ressourcen

- **Hyperliquid Docs:** https://hyperliquid.xyz/docs
- **Hyperliquid Testnet:** https://app.hyperliquid-testnet.xyz
- **Telegram Bot API:** https://core.telegram.org/bots/api
- **FastAPI Docs:** http://localhost:8000/docs (wenn Bot läuft)

---

**Viel Erfolg beim Testen! 🚀**