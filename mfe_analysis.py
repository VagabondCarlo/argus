"""Max-favorable-excursion (MFE) analysis — is there a bigger-move edge to catch?

For every historical signal, walk price forward and measure how far it ran in the
signal's direction (in R = multiples of the stop distance) BEFORE the stop was hit.
If most signals top out near 1R, it's a scalp grinder (wins are structurally small).
If a identifiable subset runs 3R+, that's a trend strategy worth building.

Reports the run distribution overall and by signal condition, then the expectancy
of a 3R-target strategy on the best subset.
"""
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yfinance as yf

HOME = Path.home()
sigs = []
for path in (HOME / "argus_backup_20260707" / "data" / "argus.db", "data/argus.db"):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True); c.row_factory = sqlite3.Row
        for r in c.execute("""SELECT ticker,action,confidence,entry_price,stop_loss,
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
        e, st = s["entry_price"], s["stop_loss"]
        if not e or not st or e == st: continue
        is_buy = s["action"] == "BUY"
        if not ((st < e) if is_buy else (st > e)): continue
        risk = abs(e - st)
        ts = pd.Timestamp(s["generated_at"])
        ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        fut = df[df.index > ts]
        if not len(fut): continue
        mfe = 0.0  # max favorable excursion in R, before stop hit
        for _, b in fut.iterrows():
            hi, lo = float(b["High"]), float(b["Low"])
            if math.isnan(hi) or math.isnan(lo): continue
            fav = (hi - e) if is_buy else (e - lo)      # best move in our favor this bar
            mfe = max(mfe, fav / risk)
            hit_stop = lo <= st if is_buy else hi >= st
            if hit_stop:
                break
        txt = s["reasoning"] or ""
        vol = re.search(r"vol ([\d.]+)x", txt)
        recs.append({
            "asset": s["asset_type"], "mfe": mfe,
            "ema": "up" if "EMA up" in txt else "down" if "EMA down" in txt else "neu",
            "macd": "bull" if "MACD bullish" in txt else "bear" if "MACD bearish" in txt else "neu",
            "vol": float(vol.group(1)) if vol else 1.0,
            "action": s["action"],
        })

df = pd.DataFrame(recs)
print(f"signals replayed: {len(df)}\n")
if df.empty: raise SystemExit

n = len(df)
print("=== HOW FAR DID PRICE RUN (before stop)? — the key question ===")
for thr in [1, 2, 3, 4]:
    pct = (df.mfe >= thr).mean()
    print(f"  reached >= {thr}R favorable: {pct:5.0%}  ({int(pct*n)} of {n})")
print(f"\n  median MFE: {df.mfe.median():.2f}R   mean MFE: {df.mfe.mean():.2f}R")

print("\n=== which conditions RUN farthest (mean MFE)? ===")
def seg(label, mask):
    g = df[mask]
    if len(g) >= 5:
        print(f"  {label:<28} n={len(g):<4} meanMFE={g.mfe.mean():.2f}R  reached3R={ (g.mfe>=3).mean():.0%}")
seg("with-trend (BUY+EMAup)", (df.action=="BUY") & (df.ema=="up"))
seg("with-trend (SELL+EMAdn)", (df.action=="SELL") & (df.ema=="down"))
seg("counter-trend", ((df.action=="BUY")&(df.ema=="down"))|((df.action=="SELL")&(df.ema=="up")))
seg("high volume (>=1.5x)", df.vol>=1.5)
seg("MACD-confirmed BUY", (df.action=="BUY")&(df.macd=="bull"))
seg("MACD-confirmed SELL", (df.action=="SELL")&(df.macd=="bear"))
seg("crypto", df.asset=="crypto")
seg("stock", df.asset=="stock")

print("\n=== would a 3R-target strategy beat the 1R scalp? ===")
# Approx: a trade 'wins 3R' if MFE >= 3 (target hit before stop); else -1R (stopped).
for tgt in [1, 2, 3]:
    wins = (df.mfe >= tgt)
    exp = wins.mean() * tgt - (~wins).mean() * 1.0
    print(f"  target {tgt}R: hit {wins.mean():4.0%}  expectancy {exp:+.2f}R/trade")

best = df[(df.vol >= 1.5)]  # best-MFE subset guess; adjust after seeing segments
if len(best) >= 8:
    print(f"\n=== high-vol subset (n={len(best)}) at 3R target ===")
    for tgt in [1, 2, 3]:
        w = (best.mfe >= tgt)
        print(f"  target {tgt}R: hit {w.mean():4.0%}  expectancy {w.mean()*tgt-(~w).mean():+.2f}R")
