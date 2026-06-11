# Argus — Autonomous AI Trading Agent

> *Named for the all-seeing giant of Greek mythology. Argus never sleeps.*

Argus is a fully autonomous, multi-agent trading system built on consumer hardware. It watches markets continuously, scores trade opportunities using a local large language model, and executes only when confidence exceeds 75% — protecting capital first, growing it second.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Analyst Agent                          │
│                  (Mac Mini 1)                            │
│                                                         │
│  Historical Data + Real-Time Feed + News/Events         │
│                       ↓                                 │
│            LLM Confidence Scoring Engine                │
│         (Llama 3.1 8B via Ollama — runs locally)        │
│                       ↓                                 │
│         Signal: BUY $TICKER | 82% confidence            │
└─────────────────────┬───────────────────────────────────┘
                      │ REST API (local network)
                      ↓
┌─────────────────────────────────────────────────────────┐
│                   Executor Agent                         │
│                  (Mac Mini 2)                            │
│                                                         │
│   Confidence ≥ 75%? → Execute via Alpaca API           │
│   Confidence < 75%? → Log and discard                  │
│   Weekly loss > 6%? → Kill switch engaged              │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────┴────────────┐
          ↓                        ↓
   MacBook Pro                  iPhone
  (Dashboard)          (Telegram daily reports)
```

## Design Principles

- **Capital protection over profit** — hard stop-losses and weekly kill switch
- **Low frequency, high confidence** — max 3 trades/week, min 75% confidence
- **Fully local AI** — LLM runs on-device, no API costs, no data leakage
- **Transparent decisions** — every signal logged with full reasoning chain

## Tech Stack

| Layer | Technology |
|---|---|
| LLM Engine | Llama 3.1 8B via Ollama |
| Broker API | Alpaca Markets |
| Market Data | yfinance + Alpaca data feed |
| News/Sentiment | NewsAPI + LLM analysis |
| Notifications | Telegram Bot API |
| Agent Communication | FastAPI REST |
| Language | Python 3.11 |

## Risk Management

| Rule | Value |
|---|---|
| Minimum confidence to trade | 75% |
| Max trades per week | 3 |
| Max position size | 40% of account |
| Stop-loss per trade | 2% |
| Weekly loss kill switch | 6% of account |

## Results

*Paper trading in progress. Results will be logged here.*

| Week | Trades | Win Rate | P&L |
|---|---|---|---|
| — | — | — | — |

## Setup

See [docs/setup.md](docs/setup.md) for full installation and configuration guide.

## Methodology

See [docs/methodology.md](docs/methodology.md) for signal scoring and LLM prompt design.

---

*Built by VagabondCarlo | Paper trading: 30 days minimum before live capital*
