"""
Argus Demo — runs a live market scan right now, market hours or not.
Shows every step: screening, analysis, LLM scoring.
Run with: python3 demo.py
"""
import sys
import time
sys.path.insert(0, ".")

from analyst.data.universe import get_core_universe
from analyst.data.screener import run_prescreen
from analyst.data.market import get_market_snapshot
from analyst.data.news import fetch_news, format_news_for_prompt
from analyst.sentiment.analyzer import analyze_ticker, get_spy_context
from shared.database import init_db, save_signal

DEMO_TICKERS = [
    "AAPL","TSLA","NVDA","MSFT","AMD","META","GOOGL","AMZN","COIN","PLTR",
    "SPY","QQQ","SOFI","HOOD","MARA","RIOT","ARM","SMCI","AVGO","MU"
]

def divider(label=""):
    width = 60
    if label:
        pad = (width - len(label) - 2) // 2
        print("\n" + "─" * pad + f" {label} " + "─" * pad)
    else:
        print("─" * width)

def main():
    init_db()

    print("""
╔══════════════════════════════════════════╗
║        ARGUS TRADING INTELLIGENCE        ║
║     Autonomous Market Analysis System    ║
╚══════════════════════════════════════════╝
    """)

    divider("MARKET CONTEXT")
    spy_change, market_regime = get_spy_context()
    print(f"  SPY Today:      {spy_change:+.2f}%")
    print(f"  Market Regime:  {market_regime}")

    divider("PRE-SCREENING")
    print(f"  Scanning {len(DEMO_TICKERS)} tickers for unusual activity...\n")
    candidates = run_prescreen(DEMO_TICKERS, max_workers=10)

    if candidates:
        print(f"  {len(candidates)} tickers passed live screening:\n")
        for c in candidates:
            vol = f"{c['volume_ratio']:.1f}x vol"
            move = f"{c['price_change_pct']:+.1f}%"
            print(f"  ✓ {c['ticker']:<6} ${c['price']:<8.2f} {move:<8} {vol}  score={c['score']:.0f}")
    else:
        print("  Market is closed / low activity — running full analysis on all tickers.")
        print("  (During market hours the screener filters to high-activity candidates only)\n")
        candidates = [{"ticker": t} for t in DEMO_TICKERS]

    divider("DEEP ANALYSIS")
    print(f"  Marcus Reed analyzing {min(len(candidates),8)} tickers...\n")

    signals_found = []

    for i, candidate in enumerate(candidates[:8], 1):
        ticker = candidate["ticker"]
        print(f"  [{i}/{min(len(candidates),8)}] Analyzing {ticker}...", end=" ", flush=True)

        snapshot = get_market_snapshot(ticker)
        if not snapshot:
            print("no data")
            continue

        news = fetch_news(ticker)
        news_text = format_news_for_prompt(news)
        signal = analyze_ticker(snapshot, news_text, spy_change=spy_change, market_regime=market_regime)

        if not signal:
            print("LLM error")
            continue

        action = signal.get("action","HOLD")
        conf = signal.get("confidence", 0.0)
        rr = signal.get("risk_reward", 0.0)

        icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⬜"
        bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
        print(f"{icon} {action}  [{bar}] {conf:.0%}  R/R:{rr:.1f}x")

        if action != "HOLD" and conf >= 0.60:
            signals_found.append(signal)
            save_signal(
                ticker=ticker,
                action=action,
                confidence=conf,
                price_target=signal.get("price_target", snapshot["price"]),
                stop_loss=signal.get("stop_loss", snapshot["price"] * 0.98),
                reasoning=signal.get("reasoning",""),
            )

    divider("SIGNALS REPORT")

    if not signals_found:
        print("\n  Marcus Reed found no actionable setups today.")
        print("  Capital preserved. Waiting for the right trade.\n")
        return

    above_threshold = [s for s in signals_found if s["confidence"] >= 0.75]
    watching = [s for s in signals_found if s["confidence"] < 0.75]

    if above_threshold:
        print(f"\n  ✅ EXECUTE ({len(above_threshold)} trade{'s' if len(above_threshold)>1 else ''} above 75% threshold):\n")
        for s in above_threshold:
            print(f"  {s['ticker']} {s['action']}")
            print(f"  Confidence:  {s['confidence']:.0%}")
            print(f"  Entry:       ~${s.get('price_target',0):.2f}")
            print(f"  Stop Loss:   ${s.get('stop_loss',0):.2f}")
            print(f"  R/R Ratio:   {s.get('risk_reward',0):.1f}x")
            print(f"  Setup:       {s.get('setup_type','')}")
            print(f"  Reasoning:   {s.get('reasoning','')[:200]}")
            if s.get('red_flags') and s['red_flags'] != 'none':
                print(f"  ⚠ Flags:    {s['red_flags']}")
            print()

    if watching:
        print(f"  👁  WATCHING ({len(watching)} below threshold — not executing):\n")
        for s in watching:
            print(f"  {s['ticker']} {s['action']}  {s['confidence']:.0%}  — {s.get('reasoning','')[:100]}")

    divider()
    print(f"\n  Signals saved to database. Executor will act on anything ≥75%.")
    print(f"  Daily report will include all signals including non-executed ones.\n")

if __name__ == "__main__":
    main()
