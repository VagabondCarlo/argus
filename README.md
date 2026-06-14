# Argus — Autonomous AI Trading System

> *Named for the all-seeing giant of Greek mythology. Argus never sleeps.*

Argus is a fully autonomous, multi-agent AI trading system built on consumer hardware. It continuously scans equities, forex, precious metals, and crypto — scores opportunities using a locally-hosted large language model — and executes only when two independent agents agree the trade meets a high confidence threshold. Capital protection first, growth second.

Built as a functional portfolio piece demonstrating applied AI, distributed systems, and real-world financial engineering.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     ANALYST AGENT (Mac Mini 1)                  │
│                                                                 │
│  500+ equity tickers + forex + metals + crypto universe         │
│           ↓                                                     │
│  Pre-screen: volume spike, price action, regime filter          │
│           ↓                                                     │
│  Technical Analysis (RSI, MACD, Bollinger Bands, EMA)           │
│           ↓                                                     │
│  Three-Committee LLM Scoring (Llama 3.1 8B — fully local)      │
│    ├─ Fundamental Quality  → moat, margin of safety, entry      │
│    ├─ Macro Regime         → economic cycle, dollar, SPY        │
│    └─ Technical Execution  → R/R ≥ 2:1, volume, clean entry    │
│           ↓                                                     │
│  Signal ≥ 75%  ───────────────────────────────────────► Execute │
│  Signal 70–75% ─────────────────► POST to Executor /audit      │
│  Signal < 70%  → HOLD                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                    REST API (local network)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXECUTOR AGENT (Mac Mini 1)                  │
│                                                                 │
│  Independent Risk Desk Audit (second LLM pass)                  │
│    ├─ Timing verdict   → Is right now the ideal entry?         │
│    ├─ Worst case       → Realistic downside if wrong?          │
│    ├─ Counter-thesis   → What makes this trade fail?           │
│    └─ Execution quality → Clean entry or chasing?              │
│           ↓                                                     │
│  Audit ≥ 75%  → Execute via Alpaca Paper Trading API           │
│  Audit < 75%  → Veto with full explanation logged              │
│                                                                 │
│  Hard risk controls:                                            │
│    • 2% stop-loss per trade                                    │
│    • Max 40% position size                                     │
│    • Max 3 trades/week (PDT compliance)                        │
│    • 6% weekly loss kill switch                                │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   MacBook Pro          iPhone (owner)     Telegram Channels
 (Dev / SSH)      @ArgusVagabondBot      Tier 1 — Free Public
                  Private commands       Tier 2 — Paid Private
                  System control         3× daily broadcasts
                  Conversational AI
```

---

## The Three-Committee Framework

Every signal passes through three independent analytical filters before scoring above 75%. All three must agree — a single veto caps confidence at 65% and blocks execution.

| Committee | Role | What It Asks |
|---|---|---|
| **Fundamental Quality** | Is the underlying asset fundamentally sound? | Is there a real thesis — moat, margin of safety, macro divergence, genuine adoption? Or just momentum on a weak foundation? |
| **Macro Regime** | Does the economic environment support this direction? | Is the Fed tightening or easing? Dollar strengthening or weakening? Is SPY confirming the move? |
| **Technical Execution** | Is the setup precise enough to act on? | Is R/R ≥ 2:1? Does volume confirm? Is this a real breakout or a trap? |

When all three align in a strong regime, confidence can reach 90%. This mirrors how Autopilot attaches to known-good conditions — Argus attaches to setups where every filter agrees.

> All analysis is AI-generated using institutionally-inspired frameworks. Argus does not quote, represent, or affiliate with any real investor or financial institution.

---

## Two-Stage Audit Pipeline

Argus uses a challenger model architecture: the Analyst and Executor run **separate LLM instances with different directives** — optimist vs. skeptic.

```
Analyst scores 72%  →  "Possible setup — needs a second opinion"
                              ↓
                    Executor Risk Desk audits independently
                              ↓
              Audit scores 78%  →  TRADE EXECUTES
              Audit scores 61%  →  VETOED (reason logged)
```

The Analyst finds opportunities. The Executor stress-tests them. Capital only moves when both agree.

---

## Multi-Asset Broadcast System

Beyond trading equities, Argus runs a daily intelligence broadcast across **4 asset classes** sent to two Telegram channel tiers.

### Asset Classes Covered

| Class | Universe | Data Source |
|---|---|---|
| Stocks | 15 highest-liquidity U.S. equities (AAPL, NVDA, TSLA, etc.) | yfinance |
| Forex | 9 major pairs (EUR/USD, GBP/JPY, AUD/USD, etc.) | yfinance |
| Precious Metals | Gold, Silver, Platinum, Palladium, Copper futures | yfinance |
| Crypto | BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOGE, LINK | yfinance |

### Broadcast Schedule (ET, 7 days/week)

| Time | Label | Content |
|---|---|---|
| **8:15 AM** | 🌅 Pre-Market Picks | Setups to watch at the 9:30 open |
| **12:00 PM** | ☀️ Midday Update | Live setups with fresh intraday data |
| **4:30 PM** | 🌙 Next Day Preview | What to watch for tomorrow's open |

Forex and crypto markets never close — broadcasts run all 7 days.

### Two-Tier Channel Structure

**Tier 1 — Free Public Channel**
- 1 signal per asset class (4 total) — the second-best confidence pick
- The top pick per class is reserved for Tier 2
- Confidence score with plain-language explanation of what it means
- One-line execution hint (conservative approach)
- Clear upgrade path to Tier 2 on every broadcast

**Tier 2 — Paid Private Channel**
- Top 3 signals per asset class (12 total)
- Full entry price, stop-loss, price target, and R/R ratio
- Three-committee reasoning for every pick
- Full execution playbook per signal (see below)

---

## Execution Suggestion Engine

Every signal in Tier 2 includes a "how some traders approach this setup" breakdown — not directives, but the instruments and methods traders commonly use in similar situations, ranked by risk level.

| Risk Level | Stocks | Forex | Metals | Crypto |
|---|---|---|---|---|
| 🟢 Conservative | Shares with a stop order | Spot forex via broker | GLD/SLV/PPLT ETF | Spot on Coinbase/Kraken |
| 🟡 Moderate | Weekly call/put options | Currency ETF (FXE, FXB…) | Options on ETF, mining stocks (GDX) | IBIT/ETHA ETF or options |
| 🔴 Aggressive | 0DTE call/put (intraday scalp) | — | /GC /SI futures | — |

Tier 1 shows one conservative suggestion per pick. Tier 2 shows all three risk tiers with specific context and risk notes.

Every suggestion includes a DYOR reminder. Argus is not a financial advisor — these are educational suggestions only.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM Engine | Llama 3.1 8B via Ollama (fully local — no API cost, no data sent out) |
| Broker API | Alpaca Markets paper trading |
| Market Data | yfinance (equities, forex, metals, crypto) |
| News/Sentiment | Multi-source RSS (Yahoo Finance, CNBC, MarketWatch) |
| Notifications | Telegram Bot (`@ArgusVagabondBot`) + 2 broadcast channels |
| Agent API | FastAPI + Uvicorn (Analyst :8001, Executor :8002) |
| Session Management | tmux (persistent, survives SSH disconnect) |
| Remote Access | Tailscale (WireGuard VPN — SSH from anywhere) |
| Database | SQLite (signals, trades, daily stats) |
| Language | Python 3.11 |
| Hardware | Apple Mac Mini M2 (16GB RAM) + MacBook Pro |

---

## Market Coverage

Argus does not watch a fixed watchlist for equities. It scans the whole market.

- **Full universe:** S&P 500 + 300 liquid growth/momentum names (pre-market scan)
- **Core universe:** ~300 highest-liquidity names (intraday scans every 30 min)
- **Pre-screen filters:** min $5 price, 500K avg volume, 1.5x volume spike, 1.5% price move
- **Regime filter:** SPY direction adjusts candidate ranking before LLM scoring
- **Broadcast universe:** 9 forex pairs, 5 metals, 9 crypto assets scanned 3× daily

---

## Telegram Interface — `@ArgusVagabondBot`

### Owner Commands (private — authorized user only)

| Command | Action |
|---|---|
| `/status` | Live system health — both agents online/offline, trade count |
| `/account` | Paper trading balance, buying power, P&L |
| `/signals` | All signals generated today with confidence scores |
| `/report` | Full mid-day summary |
| `/history` | Last 10 executed trades |
| `/pause [key]` | Pause all trading (positions held) |
| `/resume [key]` | Resume trading |
| `/stop [key]` | Emergency stop — halt all activity |
| `/threshold [value] [key]` | Adjust confidence threshold live |
| `/config` | View current risk parameters |

Destructive commands require the master authorization key.

### Guest Commands (open to all)

| Command | Action |
|---|---|
| `/predictions` | Today's highest-confidence trade reads |
| `/suggestions` | Setups with entry, stop-loss, and target |
| `/setups` | Signals at 65%+ confidence |
| `/news` | Top 3 market-moving headlines with links |

Guests can also talk to Argus in plain text. It responds with market analysis and trading education — always framed as suggestions, never directives. Ask it about a stock, a forex pair, what's moving, or anything markets-related.

### Owner Daily Reports (ET, weekdays)

- 🌅 **8:30 AM** — Pre-market: signals ready, what to watch at open
- ☀️ **12:30 PM** — Mid-day: trades executed, open positions, P&L
- 🌙 **4:30 PM** — After-market: full day recap, tomorrow's outlook

---

## Risk Management

| Rule | Value | Enforced By |
|---|---|---|
| Minimum confidence to trade | 75% | Both agents |
| Two-agent consensus required | Analyst + Executor | Architecture |
| Max trades per week | 3 (PDT compliance) | Executor hard block |
| Max position size | 40% of account | Risk manager |
| Stop-loss per trade | 2% | Alpaca stop order |
| Weekly loss kill switch | −6% of account | Auto-halt |
| Minimum R/R ratio | 2:1 | Hard cap on confidence |
| RSI overbought block | RSI > 75 = no BUY | LLM + hard rule |

---

## Results

*Paper trading in progress. Live results will be logged here as trades execute.*

| Week | Trades | Win Rate | P&L |
|---|---|---|---|
| — | — | — | — |

---

## Project Structure

```
argus/
├── analyst/
│   ├── data/
│   │   ├── universe.py           # S&P 500 + 500-ticker equity universe
│   │   ├── universe_extended.py  # Forex, metals, crypto universe definitions
│   │   ├── screener.py           # Concurrent pre-screen (volume, price)
│   │   ├── market.py             # Technical indicators (RSI, MACD, BB, EMA)
│   │   ├── multi_asset.py        # Snapshots for forex, metals, crypto
│   │   ├── news.py               # NewsAPI integration
│   │   └── market_news.py        # RSS headlines (/news command)
│   ├── sentiment/
│   │   ├── analyzer.py           # Three-committee LLM framework (equities)
│   │   └── analyzer_extended.py  # Adapted framework for forex/metals/crypto
│   ├── signals/
│   │   ├── scorer.py             # Full equity scan pipeline + signal routing
│   │   ├── broadcaster.py        # Multi-asset broadcast engine (3× daily)
│   │   └── execution.py          # Execution suggestion engine (how to play it)
│   └── main.py                   # FastAPI service (port 8001)
├── executor/
│   ├── audit/
│   │   └── auditor.py            # Independent Risk Desk LLM audit
│   ├── gateway/
│   │   └── alpaca.py             # Alpaca paper trading API (lazy init)
│   ├── risk/
│   │   └── manager.py            # Position sizing, kill switch, weekly limits
│   └── main.py                   # FastAPI service (port 8002) + /audit endpoint
├── notifications/
│   ├── bot.py                    # Telegram bot (owner + guest, conversational AI)
│   └── reports.py                # Pre-market, mid-day, after-market report builders
├── shared/
│   ├── config.py                 # Environment config (inc. Tier 1/2 channel IDs)
│   ├── database.py               # SQLite: signals, trades, daily_stats
│   └── models.py                 # TradeSignal, TradeResult dataclasses
├── display.py                    # Full-screen mission control terminal UI
├── demo.py                       # Live demo — works outside market hours
└── docs/
    └── setup-log.md              # Full build log with blockers and resolutions
```

---

## Setup

See [docs/setup-log.md](docs/setup-log.md) for the complete installation log.

**Quick start:**
```bash
git clone git@github.com:VagabondCarlo/argus.git
cd argus
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b
cp .env.example .env  # fill in credentials
./start_argus.sh      # launches all services in tmux
```

**Remote access via Tailscale:**
```bash
ssh agent1  # resolves to Mac Mini via WireGuard — works from anywhere
tmux attach -t argus
# Ctrl+B then 0/1/2/3 to switch windows (analyst / bot / executor / display)
```

**Environment variables required:**
```
ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
TIER1_CHANNEL_ID   # free public broadcast channel
TIER2_CHANNEL_ID   # paid private broadcast channel
MASTER_KEY         # required for destructive Telegram commands
CONFIDENCE_THRESHOLD, MAX_TRADES_PER_WEEK, ACCOUNT_CAPITAL
```

---

## Mission

Institutional-quality market intelligence has always been locked behind expensive terminals, private data feeds, and hedge fund resources. Argus exists to change that — broadcasting the same level of multi-asset analysis to anyone, regardless of account size.

The free channel levels the playing field. The paid channel funds the infrastructure. The goal is fair play.

---

*Built by VagabondCarlo — CySA+ candidate, AI systems builder*
*Paper trading minimum 30 days before live capital deployment*
