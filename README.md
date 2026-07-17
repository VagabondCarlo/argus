# Argus — Autonomous AI Trading System

> *Named for the all-seeing giant of Greek mythology. Argus never sleeps.*

Argus is a fully autonomous, multi-agent AI trading system built on consumer hardware. It watches equities, forex, precious metals, and crypto around the clock — scores opportunities using pure technical analysis reinforced by social intelligence — and executes only when signals clear a calibrated confidence threshold with capital protection rules in place.

Built as a functional portfolio piece demonstrating applied AI, distributed systems, and real-world financial engineering.

---

## Version 2 — Current

**`main` is Argus v2.** Version 1 ran a 22-day live trial (June 16 – July 7, 2026), analyzed 2,559 signals, and was retired to build a sharper system on what the data proved. The v1 codebase is frozen at [`v1-archive`](../../tree/v1-archive) / tag [`v1.0-final`](../../releases/tag/v1.0-final) — see the [full diff](../../compare/v1.0-final...main).

What changed, and why:

| | v1 | v2 |
|---|---|---|
| Confidence threshold | 0.66–0.75 (drifted between code and config) | **0.72** — set by replaying all 733 archived signals against price history: ≥0.72 won 56% at ~2:1 R/R, the 0.66–0.72 zone was net negative |
| Signal selection | First signal over threshold | **Ranked batch** — fills open slots best-first |
| Crypto | Signals only, never executed | **Executes 24/7 via Alpaca** (8 pairs) |
| Exits | Broker bracket orders (silently absent on crypto and fractional positions) | **Software stop/target enforcement** — the monitor closes every position at its signal's levels |
| Entry quality | Executed at any price, any age | **15-min signal expiry + drift guard** (no chasing past half the risk distance) |
| Cadence | 15-min scans, 60s executor | **5-min scans, 30s executor/monitor loops** |
| Testing | Manual | **15 integration tests** on the signal→execution path |

v1's fatal flaw, found post-mortem: resting stop orders held the shares, so the risk monitor's position closes were silently rejected — stuck positions jammed the 3-slot limit and blocked every trade for 19 days. v2 cancels resting orders before any close, and a test now guards that path.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       ANALYST AGENT                             │
│                                                                 │
│  500+ equity tickers + 9 forex pairs + 5 metals + 9 crypto     │
│                          ↓                                      │
│  Pre-screen: volume spike, price action, regime filter          │
│                          ↓                                      │
│  Parallel snapshot fetch (ThreadPoolExecutor)                   │
│                          ↓                                      │
│  Pure Technical Scoring (RSI, MACD, EMA, Bollinger, Volume)    │
│  + Social Modifier (Reddit · Bluesky · Truth Social)           │
│                          ↓                                      │
│  Signal ≥ 66%  ──────────────────────────────────► Executor    │
│  Signal 62–66% ──────────────────────────────────► DB (track)  │
│  Signal < 62%  → filtered                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                    REST API (local network)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EXECUTOR AGENT                             │
│                                                                 │
│  Market hours check → stock signals only                        │
│  Open position check → no double-entry                          │
│                          ↓                                      │
│  Risk controls:                                                 │
│    • 2% stop-loss per trade                                    │
│    • Max 40% position size                                     │
│    • Max 25 trades/week                                        │
│    • 6% weekly loss kill switch                                │
│                          ↓                                      │
│  Alpaca Paper Trading API → fractional market order + GTC stop │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
      Dev Machine        Telegram Bot         Broadcast Channels
      (SSH remote)    @ArgusVagabondBot      Tier 1 — Free Public
                      Owner + Guest UI       Tier 2 — Paid Private
                      System control         3× daily, 7 days/week
```

---

## Scan Schedule — Always On

Argus watches the market 24 hours a day, 7 days a week. Scan frequency adjusts by session; execution only fires during NYSE market hours.

| Session (ET) | Assets Scanned | Frequency |
|---|---|---|
| Pre-market 07:00–09:30 | Stocks (full universe) + crypto + forex + metals | Every 30 min |
| Market 09:30–16:00 | Stocks (core universe) + crypto + forex + metals | Every 15 min |
| After-hours 16:00–20:00 | Stocks + crypto + forex + metals | Every 30 min |
| Overnight 20:00–07:00 | Crypto + forex + metals only | Every 60 min |

Deduplication: stocks skip if scored within the last 4 hours. Extended assets skip if scored within 2 hours.

---

## Scoring Engine

Every signal is scored in two passes.

### Pass 1 — Pure Technical (instant, no LLM)

Weighted scoring across 6 indicators:

| Indicator | Max BUY contribution | Max SELL contribution |
|---|---|---|
| RSI | +0.14 (oversold < 30) | +0.14 (overbought > 70) |
| MACD cross | +0.12 (bullish) | +0.12 (bearish) |
| EMA 9 vs 21 | +0.08 (trending up) | +0.08 (trending down) |
| Bollinger position | +0.06 (near lower band) | +0.06 (near upper band) |
| Volume ratio | +0.05 (> 1.5× average) | +0.05 (> 1.5× average) |
| Session change | +0.04 (> +1.5%) | +0.04 (< −1.5%) |

- Score ≥ 0.15, buy > sell → **BUY**, confidence = `min(0.50 + score, 0.82)`
- Score ≥ 0.15, sell > buy → **SELL**, confidence = `min(0.50 + score, 0.82)`
- Otherwise → **WATCH**, confidence = `min(0.50 + max(score), 0.65)`

R/R is fixed at 2:1 for all stock signals (4% target / 2% stop).

### Pass 2 — Social Modifier (±0.02 to ±0.04)

Reddit, Bluesky, and Truth Social conviction data is applied as a lightweight modifier:

| Condition | Adjustment |
|---|---|
| Cross-platform buzz (2+ platforms) + sentiment aligns with signal | +0.04 |
| Single platform + sentiment aligns | +0.02 |
| Sentiment opposes signal direction | −0.02 |

Social data refines confidence — it does not gate signals. Fetched once per scan cycle and cached for the day.

---

## Signal Thresholds

| Confidence | What Happens |
|---|---|
| ≥ 66% BUY/SELL | Saved to DB + executor places trade during market hours |
| 62–66% BUY/SELL | Saved to DB for tracking, not executed |
| ≥ 62% WATCH | Saved to DB, tracked only — never executed |
| < 62% | Filtered out |

---

## Multi-Asset Broadcast

Three times daily, Argus sends market intelligence to both Telegram channels.

### Schedule (ET, 7 days/week)

| Time | Session |
|---|---|
| **8:15 AM** | Pre-market — setups to watch at the open |
| **12:00 PM** | Midday — live intraday setups |
| **4:30 PM** | After-market — next day preview |

### Channel Tiers

**Tier 1 — Free Public**
- 1 signal per asset class (4 total) — second-best confidence pick
- Confidence score and plain-language reasoning
- One-line conservative execution hint
- Upgrade CTA to Tier 2 on every broadcast

**Tier 2 — Paid Private**
- Top 3 signals per asset class (up to 12 total)
- Full entry price, stop-loss, price target, R/R ratio
- Full reasoning per signal
- Execution playbook: conservative / moderate / aggressive approach per asset class

---

## Social Intelligence

Argus aggregates retail sentiment from multiple free platforms — no paid API required for core functionality:

| Platform | Weight | Notes |
|---|---|---|
| Twitter/X | ×3.0 | Optional — requires Bearer token |
| Reddit WSB | ×2.0 | r/wallstreetbets — free, no auth needed |
| Reddit General | ×1.0–1.5 | 25 subreddits: US, UK, Asia, Australia |
| Bluesky | ×0.8 | Free public AT Protocol API |
| Truth Social | ×0.5 | Mastodon-compatible, useful for energy/defense names |

Conviction scores are used as confidence modifiers on top of technical scoring. Cross-platform signals (trending on 2+ platforms simultaneously) carry the strongest weight.

---

## Risk Management

| Rule | Value | Enforced By |
|---|---|---|
| Minimum confidence to execute | 66% | Executor |
| Asset type restriction | Stocks only via Alpaca | Executor filter |
| No double-entry | One position per ticker | Open position check |
| Max trades per week | 25 (configurable via `.env`) | Executor hard block |
| Max position size | 40% of account | Risk manager |
| Stop-loss per trade | 2% | GTC stop order |
| Weekly loss kill switch | −6% of account | Auto-halt |
| Minimum R/R ratio | 2:1 | Scoring engine |
| Market hours gate | NYSE hours only | Executor pre-check |

---

## Telegram Interface

### Owner Commands

| Command | Action |
|---|---|
| `/status` | Live system health — both agents, trade count, signals today |
| `/account` | Paper trading balance, buying power, P&L |
| `/signals` | All signals generated today with confidence scores |
| `/report` | Full summary |
| `/history` | Last 10 executed trades |
| `/pause` | Pause all trading (positions held) |
| `/resume` | Resume trading |
| `/stop` | Emergency stop |
| `/threshold` | Adjust confidence threshold live |
| `/testbroadcast` | Fire an on-demand broadcast immediately |

Destructive commands require the master authorization key passed as an argument.

### Guest Commands

| Command | Action |
|---|---|
| `/predictions` | Today's highest-confidence trade reads |
| `/suggestions` | Setups with entry, stop-loss, and target |
| `/setups` | Signals at threshold confidence |
| `/news` | Top market-moving headlines |
| `/research TICKER` | Live social sentiment and options flow lookup |

Guests can talk to Argus in plain text — ask about a ticker, a forex pair, or anything markets-related. Rate-limited to 2 questions per 4-hour window per user.

### Owner Daily Reports (ET, weekdays)

| Time | Report |
|---|---|
| 8:30 AM | Pre-market — signals ready, what to watch at open |
| 12:30 PM | Mid-day — trades executed, open positions, P&L |
| 4:30 PM | After-market — full day recap, tomorrow's outlook |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Signal Scoring | Pure technical scoring engine (custom, no API cost) |
| LLM Engine | Llama 3.1 8B via Ollama — local only, no data leaves machine |
| Broker API | Alpaca Markets paper trading |
| Market Data | yfinance (equities, forex, metals, crypto) |
| Social Intelligence | Reddit, Bluesky, Truth Social — no paid API required |
| News | Multi-source RSS (Yahoo Finance, CNBC, MarketWatch) |
| Web Scraping | requests + BeautifulSoup (Finviz — analyst ratings, short interest) |
| Browser Automation | Playwright + headless Chromium (JS-rendered pages) |
| Research Agent | OpenClaw (self-hosted AI browser agent) |
| Notifications | Telegram Bot + 2 broadcast channels |
| Agent API | FastAPI + Uvicorn (Analyst :8001, Executor :8002) |
| Database | SQLite (signals, trades, daily_stats) |
| Session Management | tmux |
| Remote Access | Tailscale (WireGuard VPN) |
| Language | Python 3.11 |
| Hardware | Apple Mac Mini M2 (16GB RAM) |

---

## Market Coverage

**Equities**
- Full universe: S&P 500 + ~300 liquid growth/momentum names (pre-market)
- Core universe: ~300 highest-liquidity names (intraday)
- Pre-screen filters: min $5 price · 500K avg volume · 1.5× volume spike · 1.5% move · regime filter

**Extended (24/7)**
- Forex: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD, EUR/JPY, GBP/JPY
- Metals: Gold, Silver, Platinum, Palladium, Copper (futures)
- Crypto: BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOGE, LINK

---

## Results

**v1 trial (June 16 – July 7, 2026):** 2,559 signals analyzed across four asset classes. The replay of its archive against actual price history is what set v2's execution threshold — the trial's product was evidence, not P&L.

**v2 (live since July 16, 2026):** Paper trading with the rebuilt execution engine. 30-day minimum track record before any live capital consideration. Results will be posted here weekly.

---

## Project Structure

```
argus/
├── analyst/
│   ├── data/
│   │   ├── universe.py             # Equity universe definitions
│   │   ├── universe_extended.py    # Forex, metals, crypto universe
│   │   ├── screener.py             # Pre-screen filters
│   │   ├── market.py               # Technical indicator calculation
│   │   ├── multi_asset.py          # Snapshots for non-equity assets
│   │   ├── news.py                 # RSS news aggregation
│   │   ├── market_news.py          # Headline fetcher
│   │   ├── web_scraper.py          # Finviz + extended fundamental data
│   │   ├── browser_scraper.py      # Playwright headless browser
│   │   └── social_aggregator.py    # Reddit, Bluesky, Truth Social scoring
│   ├── sentiment/
│   │   ├── analyzer.py             # LLM framework (equities — research path)
│   │   └── analyzer_extended.py    # LLM framework (forex/metals/crypto)
│   ├── signals/
│   │   ├── technical.py            # Shared pure technical scorer
│   │   ├── scorer.py               # 24/7 scan pipeline + signal routing
│   │   ├── broadcaster.py          # Multi-asset broadcast engine
│   │   └── execution.py            # Execution suggestion engine
│   └── main.py                     # FastAPI service (port 8001)
├── executor/
│   ├── audit/
│   │   └── auditor.py              # Independent Risk Desk audit
│   ├── gateway/
│   │   └── alpaca.py               # Alpaca paper trading API
│   ├── risk/
│   │   └── manager.py              # Position sizing, kill switch, limits
│   └── main.py                     # FastAPI service (port 8002)
├── notifications/
│   ├── bot.py                      # Telegram bot
│   └── reports.py                  # Report builders
├── shared/
│   ├── config.py                   # Environment config (no secrets stored here)
│   ├── database.py                 # SQLite ORM
│   └── models.py                   # Shared dataclasses
├── docs/
│   ├── changelog/                  # Version history
│   │   ├── v0.1.md through v0.5.md
│   └── setup-log.md
├── display.py                      # Terminal mission control UI
├── demo.py                         # Demo mode
└── start_argus.sh                  # Service launcher
```

---

## Setup

```bash
git clone git@github.com:VagabondCarlo/argus.git
cd argus
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b
cp .env.example .env   # fill in your credentials — never commit this file
./start_argus.sh       # launches all services in tmux
```

**Required environment variables (`.env` only — never commit):**
```
ALPACA_API_KEY
ALPACA_SECRET_KEY
ALPACA_BASE_URL

TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TIER1_CHANNEL_ID
TIER2_CHANNEL_ID

MASTER_KEY
CONFIDENCE_THRESHOLD
MAX_TRADES_PER_WEEK
ACCOUNT_CAPITAL

# Optional — activates Twitter/X social intelligence when available
TWITTER_BEARER_TOKEN
```

---

## Mission

Institutional-quality market intelligence has always been locked behind expensive terminals, private data feeds, and hedge fund infrastructure. Argus exists to change that — broadcasting the same level of multi-asset analysis to anyone, regardless of account size.

The free channel levels the playing field. The paid channel funds the infrastructure. The goal is fair play.

---

*Built by Michael Carlo — CySA+ candidate, AI systems builder*  
*Vibe coded with Claude*  
*Paper trading minimum 30 days before live capital deployment*  
*Version history: [docs/changelog/](docs/changelog/)*
