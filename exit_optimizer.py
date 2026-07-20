"""Exit optimizer — find the profit-target that maximizes expectancy.

Trades currently use a 1:1 reward:risk (target = 1x the stop distance). This
replays every historical signal (v1 archive + v2) with a range of target
multiples, stop fixed at 1x risk, to find the R:R that makes the most money
per trade. Data-driven adjustment, not a guess.
"""
import math
from collections import defaultdict

import pandas as pd
import yfinance as yf
import sqlite3

MULTIPLES = [0.5, 0.75, 1.0, 1.25]

sigs = []
for path, tag in [("/Users/agent/argus_backup_20260707/data/argus.db", "v1"),
                  ("data/argus.db", "v2")]:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        for r in c.execute("""
            SELECT ticker, action, confidence, entry_price, stop_loss, generated_at, asset_type
            FROM signals
            WHERE action IN ('BUY','SELL') AND entry_price IS NOT NULL
              AND stop_loss IS NOT NULL AND asset_type IN ('stock','crypto')
        """):
            sigs.append(dict(r))
        c.close()
    except Exception as e:
        print(f"{tag}: {e}")

# keep signals with a real risk distance
sigs = [s for s in sigs if s["entry_price"] and s["stop_loss"]
        and s["entry_price"] != s["stop_loss"]]
print(f"signals with valid entry/stop (stock+crypto): {len(sigs)}", flush=True)

by_ticker = defaultdict(list)
for s in sigs:
    by_ticker[s["ticker"]].append(s)

# results[m] = list of R outcomes
results = {m: [] for m in MULTIPLES}
resolved_count = 0
for tk, group in by_ticker.items():
    try:
        df = yf.download(tk, interval="15m", period="60d", progress=False, auto_adjust=False)
        if df is None or not len(df):
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        idx = df.index
        df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    except Exception:
        continue
    for s in group:
        entry, stop = s["entry_price"], s["stop_loss"]
        is_buy = s["action"] == "BUY"
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        if not ((stop < entry) if is_buy else (stop > entry)):
            continue
        ts = pd.Timestamp(s["generated_at"]).tz_localize("UTC") if pd.Timestamp(s["generated_at"]).tz is None else pd.Timestamp(s["generated_at"]).tz_convert("UTC")
        fut = df[df.index > ts]
        if not len(fut):
            continue
        bars = [(float(b["High"]), float(b["Low"])) for _, b in fut.iterrows()
                if not (math.isnan(b["High"]) or math.isnan(b["Low"]))]
        if not bars:
            continue
        resolved_this = False
        for m in MULTIPLES:
            target = entry + m * risk if is_buy else entry - m * risk
            outcome = None
            for hi, lo in bars:
                hit_stop = lo <= stop if is_buy else hi >= stop
                hit_tgt = hi >= target if is_buy else lo <= target
                if hit_stop:  # ambiguous = loss (conservative)
                    outcome = -1.0
                    break
                if hit_tgt:
                    outcome = m  # win = m times the risk
                    break
            if outcome is not None:
                results[m].append(outcome)
                resolved_this = True
        if resolved_this:
            resolved_count += 1

print(f"resolved signals: {resolved_count}\n", flush=True)
print(f"{'target':>7} {'n':>5} {'win%':>6} {'avgR':>7} {'totalR':>9} {'expectancy/trade':>18}")
best = None
for m in MULTIPLES:
    rs = results[m]
    if not rs:
        continue
    n = len(rs)
    wins = sum(1 for r in rs if r > 0)
    wr = wins / n
    avg = sum(rs) / n
    total = sum(rs)
    print(f"{m:>6.1f}x {n:>5} {wr:>5.0%} {avg:>+7.2f} {total:>+9.1f} {avg:>+17.2f}R")
    if best is None or avg > best[1]:
        best = (m, avg)
if best:
    print(f"\n>>> OPTIMAL TARGET: {best[0]:.1f}x risk  (expectancy {best[1]:+.2f}R/trade)")
