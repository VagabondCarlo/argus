"""Edge analysis — replay every actionable v2 signal against real price history
and segment it to find where the edge actually lives (and where it bleeds).

Answers: BUY vs SELL? which asset class? is confidence calibrated (does 64%
confidence win ~64%)? are we cutting winners short / letting losers run?

Run on agent1:  ./venv/bin/python edge_analysis.py
"""
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

conn = sqlite3.connect("data/argus.db")
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc)
lo = (now - timedelta(days=8)).isoformat()
hi = (now - timedelta(hours=2)).isoformat()  # give each signal time to resolve

rows = conn.execute("""
    SELECT ticker, action, confidence, asset_type, entry_price, stop_loss, price_target, generated_at
    FROM signals
    WHERE action IN ('BUY','SELL')
      AND entry_price IS NOT NULL AND stop_loss IS NOT NULL AND price_target IS NOT NULL
      AND generated_at BETWEEN ? AND ?
""", (lo, hi)).fetchall()
print(f"actionable signals to replay: {len(rows)}", flush=True)

by_ticker = defaultdict(list)
for r in rows:
    by_ticker[r["ticker"]].append(r)

results = []
for tk, sigs in by_ticker.items():
    try:
        df = yf.download(tk, interval="15m", period="8d", progress=False, auto_adjust=False)
        if df is None or not len(df):
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        idx = df.index
        df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    except Exception:
        continue
    for s in sigs:
        entry, stop, target = s["entry_price"], s["stop_loss"], s["price_target"]
        if not entry or not stop or entry == stop or entry == target:
            continue
        is_buy = s["action"] == "BUY"
        ok = (stop < entry < target) if is_buy else (target < entry < stop)
        if not ok:
            continue
        ts = datetime.fromisoformat(s["generated_at"])
        fut = df[df.index > ts]
        if not len(fut):
            continue
        outcome, exit_px = None, None
        for _, b in fut.iterrows():
            hi_, lo_ = float(b["High"]), float(b["Low"])
            if math.isnan(hi_) or math.isnan(lo_):
                continue
            hit_stop = lo_ <= stop if is_buy else hi_ >= stop
            hit_tgt = hi_ >= target if is_buy else lo_ <= target
            if hit_stop:  # ambiguous = loss
                outcome, exit_px = "loss", stop
                break
            if hit_tgt:
                outcome, exit_px = "win", target
                break
        if outcome is None:
            continue  # unresolved
        risk = abs(entry - stop)
        r = (exit_px - entry) / risk if is_buy else (entry - exit_px) / risk
        results.append({
            "action": s["action"], "asset": s["asset_type"],
            "conf": s["confidence"], "outcome": outcome, "r": r,
        })

df = pd.DataFrame(results)
if df.empty:
    print("no resolved signals yet"); raise SystemExit
df["win"] = df.outcome == "win"


def seg(label, g):
    n = len(g)
    wr = g.win.mean()
    return f"{label:<22} n={n:<4} win={wr:5.0%}  avgR={g.r.mean():+.2f}  totalR={g.r.sum():+.1f}"


print(f"\n=== OVERALL ===\n{seg('all', df)}")
print("\n=== BY ACTION ===")
for a, g in df.groupby("action"):
    print(seg(a, g))
print("\n=== BY ASSET ===")
for a, g in df.groupby("asset"):
    print(seg(a, g))
print("\n=== BY CONFIDENCE BAND ===")
df["band"] = pd.cut(df.conf, [0, .64, .66, .68, .70, .72, 1.0],
                    labels=["<.64", ".64-.66", ".66-.68", ".68-.70", ".70-.72", ".72+"])
for b, g in df.groupby("band", observed=True):
    print(seg(str(b), g))
print("\n=== CALIBRATION (does confidence predict win rate?) ===")
for b, g in df.groupby("band", observed=True):
    if len(g):
        mid = g.conf.mean()
        print(f"  conf~{mid:.0%}  actual win={g.win.mean():.0%}  (n={len(g)})")
print("\n=== BUY x ASSET (where the real money is) ===")
for (a, ast), g in df.groupby(["action", "asset"]):
    if len(g) >= 2:
        print(seg(f"{a} {ast}", g))
