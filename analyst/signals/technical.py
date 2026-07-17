"""
Technical scoring with ATR-based stops and targets.
Shared by the broadcast engine and the signal scanner.
"""


def score_snapshot(snap: dict) -> dict:
    price = snap.get("price", 0)
    if not price or price <= 0:
        return {
            "ticker": snap.get("ticker", ""),
            "display_name": snap.get("display_name", snap.get("ticker", "")),
            "asset_type": snap.get("asset_type", "stock"),
            "action": "WATCH", "confidence": 0.0, "price": 0,
            "price_target": 0, "stop_loss": 0, "risk_reward": 0,
            "setup_type": "invalid", "time_horizon": "—",
            "reasoning": "No valid price data.", "red_flags": "zero price",
            "spy_change": snap.get("spy_change", 0.0),
        }

    rsi   = snap.get("rsi", 50)
    ema   = snap.get("ema_trend", "neutral")
    macd  = snap.get("macd_cross", "neutral")
    bb    = snap.get("bb_pct", 0.5)
    vol   = snap.get("volume_ratio", 1.0)
    chg   = snap.get("price_change_pct", 0.0)
    asset = snap.get("asset_type", "stock")
    atr   = snap.get("atr", price * 0.02)

    buy_score = 0.0
    buy_score += 0.14 if rsi < 30 else 0.09 if rsi < 40 else 0.04 if rsi < 50 else 0.0
    buy_score += 0.12 if macd == "bullish" else 0.0
    buy_score += 0.08 if ema == "up" else 0.0
    buy_score += 0.06 if bb < 0.20 else 0.0
    buy_score += 0.05 if vol > 1.5 else 0.02 if vol > 1.2 else 0.0
    buy_score += 0.04 if chg > 1.5 else 0.02 if chg > 0.5 else 0.0

    sell_score = 0.0
    sell_score += 0.14 if rsi > 70 else 0.09 if rsi > 60 else 0.04 if rsi > 55 else 0.0
    sell_score += 0.12 if macd == "bearish" else 0.0
    sell_score += 0.08 if ema == "down" else 0.0
    sell_score += 0.06 if bb > 0.80 else 0.0
    sell_score += 0.05 if vol > 1.5 else 0.02 if vol > 1.2 else 0.0
    sell_score += 0.04 if chg < -1.5 else 0.02 if chg < -0.5 else 0.0

    # ATR-based stops and targets — scalp mode: tight target, fast exit.
    # Directional cutoff 0.12 (= 0.62 confidence) matches the executor's
    # data-collection floor — the old 0.15 cutoff made every sub-0.65 signal
    # a WATCH by construction, so those setups could never trade at any
    # executor threshold.
    if buy_score >= sell_score and buy_score >= 0.12:
        action = "BUY"
        conf = round(min(0.50 + buy_score, 0.82), 2)
        stop_loss = round(price - (1.0 * atr), 2)
        price_target = round(price + (1.0 * atr), 2)
    elif sell_score > buy_score and sell_score >= 0.12:
        action = "SELL"
        conf = round(min(0.50 + sell_score, 0.82), 2)
        stop_loss = round(price + (1.0 * atr), 2)
        price_target = round(price - (1.0 * atr), 2)
    else:
        action = "WATCH"
        conf = round(min(0.50 + max(buy_score, sell_score), 0.65), 2)
        stop_loss = round(price - (0.75 * atr), 2)
        price_target = round(price + (0.75 * atr), 2)

    risk = abs(price - stop_loss)
    reward = abs(price_target - price)
    rr = round(reward / risk, 1) if risk > 0 else 0.0

    rsi_label = "oversold" if rsi < 35 else "overbought" if rsi > 65 else f"{rsi:.0f}"
    reasoning = (
        f"RSI {rsi:.0f} ({rsi_label}), EMA {ema}, MACD {macd}, "
        f"BB {bb:.2f}, vol {vol:.1f}x avg, session {chg:+.2f}%. "
        f"ATR ${atr:.2f} ({snap.get('atr_pct', 0):.1f}% of price)."
    )

    return {
        "ticker":       snap["ticker"],
        "display_name": snap.get("display_name", snap["ticker"]),
        "asset_type":   asset,
        "action":       action,
        "confidence":   conf,
        "price":        price,
        "price_target": price_target,
        "stop_loss":    stop_loss,
        "risk_reward":  rr,
        "setup_type":   "technical",
        "time_horizon": "1–3 days",
        "reasoning":    reasoning,
        "red_flags":    "none",
        "spy_change":   snap.get("spy_change", 0.0),
    }
