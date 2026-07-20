"""Setup analysis — which signal CONDITIONS actually win?

Replays stock+crypto signals for outcome, parses the indicator state out of each
signal's reasoning text, and reports win rate per condition. Where a condition
clearly wins or loses, that's a scorer adjustment worth making.
"""
import math
import re
import sqlite3
from collections import defaultdict

import pandas as pd
import yfinance as yf

sigs = []
for path in ("/Users/agent/argus_backup_20260707/data/argus.db", "data/argus.db"):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True); c.row_factory = sqlite3.Row
        for r in c.execute("""SELECT ticker,action,confidence,entry_price,stop_loss,price_target,
                              reasoning,generated_at,asset_type FROM signals
                              WHERE action IN ('BUY','SELL') AND entry_price IS NOT NULL
                              AND stop_loss IS NOT NULL AND asset_type IN ('stock','crypto')"""):
            sigs.append(dict(r))
        c.close()
    except Exception as e:
        print(path, e)

by_ticker = defaultdict(list)
for s in sigs:
    by_ticker[s["ticker"]].append(s)

recs = []
for tk, group in by_ticker.items():
    try:
        df = yf.download(tk, interval="15m", period="60d", progress=False, auto_adjust=False)
        if df is None or not len(df): continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        idx = df.index; df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    except Exception:
        continue
    for s in group:
        e, st, tg = s["entry_price"], s["stop_loss"], s["price_target"]
        if not e or not st or e == st or e == tg: continue
        is_buy = s["action"] == "BUY"
        if not ((st < e < tg) if is_buy else (tg < e < st)): continue
        ts = pd.Timestamp(s["generated_at"])
        ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        fut = df[df.index > ts]
        if not len(fut): continue
        outcome = None
        for _, b in fut.iterrows():
            hi, lo = float(b["High"]), float(b["Low"])
            if math.isnan(hi) or math.isnan(lo): continue
            hs = lo <= st if is_buy else hi >= st
            ht = hi >= tg if is_buy else lo <= tg
            if hs: outcome = 0; break
            if ht: outcome = 1; break
        if outcome is None: continue
        txt = s["reasoning"] or ""
        rsi = re.search(r"RSI (\d+)", txt)
        vol = re.search(r"vol ([\d.]+)x", txt)
        recs.append({
            "action": s["action"], "asset": s["asset_type"], "win": outcome,
            "rsi": int(rsi.group(1)) if rsi else None,
            "ema": "up" if "EMA up" in txt else "down" if "EMA down" in txt else "neutral",
            "macd": "bull" if "MACD bullish" in txt else "bear" if "MACD bearish" in txt else "neutral",
            "vol": float(vol.group(1)) if vol else None,
        })

df = pd.DataFrame(recs)
print(f"resolved w/ parsed conditions: {len(df)}\n")
if df.empty: raise SystemExit


def show(name, mask):
    g = df[mask]
    if len(g) >= 4:
        print(f"  {name:<28} n={len(g):<3} win={g.win.mean():5.0%}")


print("=== DIRECTION ===")
for a in ["BUY", "SELL"]:
    show(a, df.action == a)
print("=== TREND ALIGNMENT ===")
show("BUY + EMA up (with-trend)", (df.action == "BUY") & (df.ema == "up"))
show("BUY + EMA down (counter)", (df.action == "BUY") & (df.ema == "down"))
show("SELL + EMA down (with-trend)", (df.action == "SELL") & (df.ema == "down"))
show("SELL + EMA up (counter)", (df.action == "SELL") & (df.ema == "up"))
print("=== MACD CONFIRMATION ===")
show("BUY + MACD bull", (df.action == "BUY") & (df.macd == "bull"))
show("BUY + MACD bear (fighting)", (df.action == "BUY") & (df.macd == "bear"))
show("SELL + MACD bear", (df.action == "SELL") & (df.macd == "bear"))
print("=== VOLUME ===")
show("vol >= 1.5x", df.vol >= 1.5)
show("vol < 1.2x (thin)", df.vol < 1.2)
print("=== RSI EXTREMES ===")
show("BUY + RSI<35 (oversold)", (df.action == "BUY") & (df.rsi < 35))
show("BUY + RSI>55", (df.action == "BUY") & (df.rsi > 55))
show("baseline (all)", df.index >= 0)
