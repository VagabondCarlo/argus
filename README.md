# Argus — Autonomous AI Trading System

> *Named for the all-seeing giant of Greek mythology. Argus never sleeps.*

Argus is a fully autonomous, multi-agent AI trading system built on consumer hardware. It continuously scans the entire U.S. equity market, scores trade opportunities using a locally-hosted large language model, and executes only when two independent agents agree the trade meets a high confidence threshold — protecting capital first, growing it second.

Built as a functional portfolio piece demonstrating applied AI, distributed systems, and real-world financial engineering.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ANALYST AGENT (Mac Mini 1)              │
│                                                             │
│  500+ ticker universe → Pre-screen (volume, price action)   │
│           ↓                                                 │
│  Technical Analysis (RSI, MACD, Bollinger, EMA)             │
│           ↓                                                 │
│  Three-Committee LLM Scoring (Llama 3.1 8B — local)        │
│    ├─ Warren Buffett  → Fundamental quality & margin of safety│
│    ├─ Ray Dalio       → Macro regime & economic cycle        │
│    └─ Marcus Reed     → Technical execution & R/R discipline │
│           ↓                                                 │
│  Signal ≥ 75%  ──────────────────────────────────────────► Execute
│  Signal 70–75% ──────────────► POST to Executor /audit      │
│  Signal < 70%  → HOLD                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                    REST API (local network)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    EXECUTOR AGENT (Mac Mini 2)              │
│                                                             │
│  Independent Risk Desk Audit (second LLM pass)              │
│    ├─ Timing verdict   → Is right now the ideal entry?      │
│    ├─ Worst case       → Realistic downside if wrong?       │
│    ├─ Counter-thesis   → What makes this trade fail?        │
│    └─ Execution quality → Clean entry or guessing?          │
│           ↓                                                 │
│  Audit ≥ 75%  → Execute via Alpaca Paper Trading API        │
│  Audit < 75%  → Veto with full explanation                  │
│                                                             │
│  Hard risk controls enforced at execution:                  │
│    • 2% stop-loss per trade                                 │
│    • Max 40% position size                                  │
│    • Max 3 trades per week (PDT compliance)                 │
│    • 6% weekly loss kill switch                             │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       MacBook Pro                         iPhone
   (Development / SSH)            (Telegram — @ArgusVagabondBot)
                                    • 3 daily automated reports
                                    • Real-time trade alerts
                                    • Full system control
                                    • Conversational AI interface
                                    • Guest mode with live signals
```

---

## The Three-Committee Framework

Every trade signal passes through three independent investment philosophies before scoring above 75%. All three must agree — a single veto caps confidence at 65% and blocks execution.

| Committee Member | Philosophy | What They Ask |
|---|---|---|
| **Warren Buffett** | Fundamental Quality | Is this a quality business? Are we buying at fear, not greed? Is there a margin of safety? |
| **Ray Dalio** | Macro Regime | Does the economic cycle and SPY direction support this trade? Don't fight the machine. |
| **Marcus Reed** | Technical Execution | Is the R/R ≥ 2:1? Does volume confirm? Is the entry precise or are we chasing? |

When all three align in a strong market regime, confidence can reach 90%. This mirrors how Tesla Autopilot attaches to successful driving patterns — Argus attaches to setups where every filter agrees.

---

## Two-Stage Audit Pipeline

Argus uses a challenger model architecture: the Analyst and Executor are **independent agents running separate LLM instances** with different perspectives.

```
Analyst scores 70%  →  "Possible setup — needs a second opinion"
                              ↓
                    Executor Risk Desk audits
                              ↓
              Audit scores 78%  →  TRADE EXECUTES
              Audit scores 61%  →  VETOED (with reason)
```

The Analyst is the optimist — finding opportunities. The Executor is the skeptic — stress-testing them. Capital only moves when both agree.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM Engine | Llama 3.1 8B via Ollama (runs fully local — no API cost) |
| Broker API | Alpaca Markets paper trading |
| Market Data | yfinance + Alpaca data feed |
| News/Sentiment | Multi-source RSS (Yahoo Finance, CNBC, MarketWatch) |
| Notifications | Telegram Bot (`@ArgusVagabondBot`) |
| Agent API | FastAPI + Uvicorn (Analyst :8001, Executor :8002) |
| Session Management | tmux (persistent, survives SSH disconnect) |
| Database | SQLite (signals, trades, daily stats) |
| Language | Python 3.11 |
| Hardware | 2× Apple Mac Mini M2 (16GB RAM), MacBook Pro |

---

## Market Coverage

Argus does not watch a fixed watchlist. It scans the whole market.

- **Full universe:** S&P 500 + 300 liquid growth/momentum names (pre-market scan)
- **Core universe:** ~300 highest-liquidity names (intraday scans every 30 min)
- **Pre-screen filters:** minimum $5 price, 500K avg volume, 1.5x volume spike, 1.5% price move
- **Regime filter:** SPY direction adjusts candidate ranking before LLM scoring

---

## Telegram Interface — `@ArgusVagabondBot`

**Owner commands (private — Mike only):**

| Command | Action |
|---|---|
| `/status` | Live system health — both agents online/offline |
| `/account` | Paper trading balance, buying power, P&L |
| `/signals` | All signals generated today with confidence scores |
| `/report` | Full mid-day summary |
| `/history` | Last 10 executed trades |
| `/pause` | Pause all trading (positions held) |
| `/resume` | Resume trading |
| `/stop` | Emergency stop — close all positions immediately |
| `/threshold` | Adjust confidence threshold live (e.g. `/threshold 0.80`) |
| `/config` | View current risk parameters |

**Guest commands (public):**

| Command | Action |
|---|---|
| `/predictions` | Today's highest-confidence trade reads |
| `/suggestions` | Full setups with entry, stop-loss, and target |
| `/setups` | Signals at 65%+ confidence |
| `/news` | Top 3 market-moving headlines with links |

**Automated daily reports:**
- 🌅 **8:30 AM ET** — Pre-market: signals ready, what to watch
- ☀️ **12:30 PM ET** — Mid-day: trades executed, open positions, P&L
- 🌙 **4:30 PM ET** — After-market: full day recap, missed signals, tomorrow's outlook

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
│   │   ├── universe.py      # S&P 500 + 500-ticker market coverage
│   │   ├── screener.py      # Concurrent pre-screen (volume, price)
│   │   ├── market.py        # Technical indicators (RSI, MACD, BB, EMA)
│   │   ├── news.py          # NewsAPI integration
│   │   └── market_news.py   # RSS market headlines (/news command)
│   ├── sentiment/
│   │   └── analyzer.py      # Three-committee LLM framework
│   ├── signals/
│   │   └── scorer.py        # Full scan pipeline + signal routing
│   └── main.py              # FastAPI service (port 8001)
├── executor/
│   ├── audit/
│   │   └── auditor.py       # Independent Risk Desk LLM audit
│   ├── gateway/
│   │   └── alpaca.py        # Alpaca paper trading API (lazy init)
│   ├── risk/
│   │   └── manager.py       # Position sizing, kill switch, weekly limits
│   └── main.py              # FastAPI service (port 8002) + /audit endpoint
├── notifications/
│   ├── bot.py               # Telegram bot (owner + guest, conversational AI)
│   └── reports.py           # Pre-market, mid-day, after-market report builders
├── shared/
│   ├── config.py            # Environment config
│   ├── database.py          # SQLite: signals, trades, daily_stats
│   └── models.py            # TradeSignal, TradeResult dataclasses
├── display.py               # Full-screen mission control terminal UI
├── demo.py                  # Live demo — works outside market hours
└── docs/
    └── setup-log.md         # Full build log with blockers and resolutions
```

---

## Setup

See [docs/setup-log.md](docs/setup-log.md) for the complete installation log across all machines.

**Quick start (on each Mac Mini):**
```bash
git clone git@github.com:VagabondCarlo/argus.git
cd argus
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b
cp .env.example .env  # fill in Alpaca + Telegram credentials
./start_argus.sh      # launches all services in tmux
```

**To view the mission control display:**
```bash
ssh agent@<mac-mini-ip> -t "tmux attach -t argus"
# Ctrl+B then 0/1/2/3 to switch windows
```

---

*Built by VagabondCarlo — CySA+ candidate, AI systems builder*
*Paper trading minimum 30 days before live capital*
