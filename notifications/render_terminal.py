"""Render the public terminal HTML from a public_feed payload.

Pure presentation: it only ever reads fields build_public_payload() chose to
emit, so it cannot leak anything the feed didn't already clear. Self-contained
HTML — no external assets, safe to serve as a static file anywhere.

    python -m notifications.render_terminal   # writes public/index.html
"""
import html
import os
from datetime import datetime, timezone

from notifications.public_feed import build_public_payload


def _bar(conf: float, thr_pct: int) -> str:
    pct = int(round(conf * 100))
    return (f'<div class="bar"><i style="width:{pct}%"></i>'
            f'<span class="thresh" style="left:{thr_pct}%"></span></div>')


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _signal_card(s: dict, thr_pct: int) -> str:
    side = "buy" if s["action"] == "BUY" else "sell"
    conv = ' <span class="hc">◉ trade line</span>' if s["high_conviction"] else ""
    return f"""      <div class="card">
        <div class="top"><span class="tk">{_e(s['ticker'])}</span><span class="side {side}">{_e(s['action'])}</span></div>
        <div class="conf">Confidence {int(round(s['confidence']*100))}%{conv}</div>
        {_bar(s['confidence'], thr_pct)}
        <div class="cbar-l"><span>50%</span><span>{thr_pct}% trade line</span></div>
        <div class="levels">
          <div class="lv"><span>Sugg. stop</span><b>{_e(s['stop'])}</b></div>
          <div class="lv lock"><span>Entry</span><b>PRO →</b></div>
          <div class="lv lock"><span>Target</span><b>PRO →</b></div>
        </div>
      </div>"""


def _closed_row(t: dict) -> str:
    cls = "pos" if t["won"] else "neg"
    sign = "+" if t["pnl"] >= 0 else "−"
    side = "buy" if t["action"] == "BUY" else "sell"
    return f"""      <div class="row">
        <div class="lead"><span class="tk">{_e(t['ticker'])}</span><span class="side {side}">{_e(t['action'].title())}</span><span class="meta">{int(round(t['confidence']*100))}% · {_e(t['when'])}</span></div>
        <div class="pnl {cls}">{sign}${abs(t['pnl']):.2f}<span class="px">${_e(t['entry'])} → ${_e(t['exit'])} · {_e(t['held'])}</span></div>
      </div>"""


def _open_row(p: dict) -> str:
    side = "sell" if p["action"] == "SHORT" else "buy"
    if p["pnl"] is None:
        pnl_html = '<span class="meta">live…</span>'
    else:
        cls = "pos" if p["up"] else "neg"
        sign = "+" if p["pnl"] >= 0 else "−"
        pnl_html = f'<span class="pnl {cls}" style="font-size:15px">{sign}${abs(p["pnl"]):.2f}</span>'
    return f"""      <div class="row">
        <div class="lead"><span class="tk">{_e(p['ticker'])}</span><span class="side {side}">{_e(p['action'])}</span><span class="meta">{int(round(p['confidence']*100))}% · held {_e(p['held'])}</span></div>
        <div class="pnl"><div>{pnl_html}</div><span class="px">${_e(p['entry'])} → ${_e(p['current'])} <span class="livedot">●</span> live</span></div>
      </div>"""


def _calib_row(c: dict) -> str:
    status = ('<span class="traded">◉ traded live</span>' if c["status"] == "traded"
              else '<span class="meta">shadow only</span>')
    if not c["n"]:
        return (f'      <tr><td class="band">{_e(c["band"])}</td><td>—</td><td>—</td>'
                f'<td>—</td><td>{status}</td></tr>')
    r = c["total_r"] or 0
    rcls = "pos" if r >= 0 else "neg"
    rsign = "+" if r >= 0 else "−"
    return (f'      <tr><td class="band">{_e(c["band"])}</td><td>{c["n"]}</td><td>{c["wins"]}</td>'
            f'<td class="{rcls}">{rsign}{abs(r):.1f}R</td><td>{status}</td></tr>')


def _news_block(news: list[dict]) -> str:
    if not news:
        return ""
    items = []
    for n in news:
        heads = "".join(
            f'<a class="hl" href="{_e(h["url"])}" target="_blank" rel="noopener noreferrer nofollow">'
            f'{_e(h["title"])} <span class="src">{_e(h.get("source","") )}</span></a>'
            for h in n["headlines"]
        ) or '<span class="nonews">No fresh headlines — tap to search →</span>'
        srcline = ""
        if n.get("sources"):
            srcline = f'<div class="srcs">{len(n["sources"])} sources · {_e(" · ".join(n["sources"][:4]))}</div>'
        items.append(f"""        <div class="news-row">
          <div class="news-tk">{_e(n['ticker'])}</div>
          <div class="news-links">{heads}
            {srcline}
            <a class="more" href="{_e(n['more'])}" target="_blank" rel="noopener noreferrer nofollow">more coverage →</a>
          </div>
        </div>""")
    return f"""
  <section>
    <div class="eyebrow"><span class="n">06</span>The tape</div>
    <h2>Read the story yourself</h2>
    <p class="sub">Recent headlines for what's on the board right now. We show you the setup and the probability — the news is so you can form your own view before you act. Links open at the source; we don't editorialize them.</p>
    <div class="news">
{"".join(items)}
    </div>
  </section>"""


def render(payload: dict) -> str:
    rec = payload["record"]
    total = rec["total_trades"]
    pnl = rec["total_pnl"]
    pnl_cls = "pos" if pnl >= 0 else "neg"
    pnl_str = f'{"+" if pnl >= 0 else "−"}${abs(pnl):,.2f}'
    rec_line = (f'{rec["wins"]}W · {rec["losses"]}L' if total else "building")
    gen = datetime.fromisoformat(payload["generated_at"]).astimezone(timezone.utc)
    gen_str = gen.strftime("%b %d · %H:%M UTC")
    thr_pct = int(round(payload.get("threshold", 0.66) * 100))

    hc = payload["high_conviction_count"]
    if payload["signals"]:
        cards = "\n".join(_signal_card(s, thr_pct) for s in payload["signals"])
        patient = "" if hc else f"""      <div class="patient"><span class="big">0</span>
        <span>signals above the <b>≥{thr_pct}%</b> trade line right now. Argus only <i>trades</i> its strongest setups and will sit in cash rather than force one. Below is the current watchlist — weaker probabilities, shown honestly.</span>
      </div>"""
    else:
        cards, patient = "", '      <div class="patient"><span class="big">·</span><span>Quiet board — no setups worth showing this moment. That\'s information too.</span></div>'

    closed = "\n".join(_closed_row(t) for t in payload["closed_trades"]) \
        or '      <div class="row"><div class="lead"><span class="meta">No closed trades yet.</span></div><div></div></div>'
    open_pos = payload.get("open_positions", [])
    open_section = ""
    if open_pos:
        open_rows = "\n".join(_open_row(p) for p in open_pos)
        open_section = f"""
  <section>
    <div class="eyebrow"><span class="n">02</span>Open now</div>
    <h2>Live positions</h2>
    <p class="sub">What Argus is holding this moment, marked to the market. Skin in the game, updated every 5 minutes.</p>
    <div class="rows">
{open_rows}
    </div>
  </section>"""
    calib = "\n".join(_calib_row(c) for c in payload["calibration"])
    news = _news_block(payload.get("news", []))

    return f"""<title>Argus — Signal Terminal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{{
    --ground:#0b0e14; --panel:#121620; --panel-2:#161b27;
    --ink:#e9e6dd; --muted:#8a90a0; --faint:#5b6373;
    --accent:#d9a441; --accent-dim:#8a6d2f; --accent-glow:rgba(217,164,65,.14);
    --up:#43b98d; --down:#e5645f;
    --line:rgba(255,255,255,.07);
    --mono:ui-monospace,"SF Mono","SFMono-Regular",Menlo,"Cascadia Mono","Roboto Mono",monospace;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html{{-webkit-text-size-adjust:100%}}
  body{{background:var(--ground); color:var(--ink); font-family:var(--mono);
    font-size:15px; line-height:1.5; letter-spacing:.01em; -webkit-font-smoothing:antialiased;
    padding:0 0 64px; background-image:radial-gradient(1200px 600px at 80% -10%,rgba(217,164,65,.05),transparent 60%);}}
  .wrap{{max-width:860px; margin:0 auto; padding:0 20px}}
  .rule{{height:1px; background:var(--line); border:0}}
  header{{padding:30px 0 22px; display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap}}
  .brand{{display:flex; align-items:center; gap:12px}}
  .eye{{width:30px;height:30px;flex:none}} .eye svg{{display:block;width:100%;height:100%}}
  .wordmark{{font-size:23px; font-weight:700; letter-spacing:.42em; padding-left:.42em}}
  .tagline{{color:var(--muted); font-size:12px; letter-spacing:.16em; text-transform:uppercase; margin-top:5px}}
  .status{{display:flex; align-items:center; gap:8px; font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); padding-top:6px}}
  .pulse{{width:8px;height:8px;border-radius:50%;background:var(--up);box-shadow:0 0 0 0 rgba(67,185,141,.6);animation:pulse 2.6s infinite}}
  @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(67,185,141,.5)}}70%{{box-shadow:0 0 0 7px rgba(67,185,141,0)}}100%{{box-shadow:0 0 0 0 rgba(67,185,141,0)}}}}
  @media (prefers-reduced-motion:reduce){{.pulse{{animation:none}}}}
  section{{padding:26px 0}}
  .eyebrow{{font-size:11px; letter-spacing:.24em; text-transform:uppercase; color:var(--accent); margin-bottom:3px}}
  .eyebrow .n{{color:var(--faint); margin-right:10px}}
  h2{{font-size:16px; font-weight:600; letter-spacing:.04em; margin-bottom:2px}}
  .sub{{color:var(--muted); font-size:13px; margin-bottom:18px; max-width:60ch}}
  .ledger{{display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--line); border:1px solid var(--line); border-radius:10px; overflow:hidden}}
  .ledger .cell{{background:var(--panel); padding:18px 16px}}
  .cell .k{{font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted)}}
  .cell .v{{font-size:26px; font-weight:600; margin-top:8px; font-variant-numeric:tabular-nums}}
  .cell .v small{{font-size:13px; color:var(--muted); font-weight:400}}
  .pos{{color:var(--up)}} .neg{{color:var(--down)}}
  .honest{{margin-top:16px; padding:13px 16px; border:1px dashed var(--accent-dim); border-radius:8px; background:var(--accent-glow); font-size:13px}}
  .honest b{{color:var(--accent); font-weight:600}}
  .rows{{border:1px solid var(--line); border-radius:10px; overflow:hidden}}
  .row{{display:grid; grid-template-columns:1fr auto; gap:8px 14px; padding:13px 16px; align-items:center; background:var(--panel)}}
  .row + .row{{border-top:1px solid var(--line)}}
  .row .lead{{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap}}
  .tk{{font-weight:600; letter-spacing:.03em}}
  .side{{font-size:11px; letter-spacing:.12em; padding:2px 7px; border-radius:4px; text-transform:uppercase}}
  .buy{{color:#8fe3c1; background:rgba(67,185,141,.12); border:1px solid rgba(67,185,141,.28)}}
  .sell{{color:#f0a9a5; background:rgba(229,100,95,.1); border:1px solid rgba(229,100,95,.26)}}
  .meta{{color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums}}
  .pnl{{font-size:16px; font-weight:600; font-variant-numeric:tabular-nums; text-align:right}}
  .pnl .px{{display:block; font-size:11px; color:var(--faint); font-weight:400}}
  .livedot{{color:var(--up); font-size:9px; vertical-align:middle}}
  .patient{{display:flex; gap:12px; align-items:center; padding:14px 16px; border:1px solid var(--line); border-left:2px solid var(--accent); border-radius:8px; background:var(--panel); margin-bottom:16px; font-size:13px}}
  .patient .big{{font-size:20px; font-weight:700; color:var(--accent)}}
  .cards{{display:grid; grid-template-columns:1fr 1fr; gap:12px}}
  .card{{background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:15px 16px}}
  .card .top{{display:flex; justify-content:space-between; align-items:baseline; gap:8px}}
  .card .conf{{font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em}}
  .card .hc{{color:var(--accent); letter-spacing:.04em}}
  .bar{{position:relative; height:6px; border-radius:3px; background:var(--panel-2); margin:12px 0 4px; overflow:hidden}}
  .bar i{{position:absolute; inset:0 auto 0 0; background:linear-gradient(90deg,var(--accent-dim),var(--accent)); border-radius:3px}}
  .bar .thresh{{position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--ink); opacity:.55}}
  .cbar-l{{display:flex; justify-content:space-between; font-size:10px; color:var(--faint); letter-spacing:.08em}}
  .levels{{display:flex; gap:18px; margin-top:13px; font-size:13px; font-variant-numeric:tabular-nums}}
  .levels .lv{{display:flex; flex-direction:column; gap:2px}}
  .levels .lv span{{font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--faint)}}
  .levels .lock b{{color:var(--accent); letter-spacing:.06em}}
  .calib{{width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums}}
  .calib th{{text-align:left; font-size:10px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); font-weight:500; padding:0 14px 10px 0; border-bottom:1px solid var(--line)}}
  .calib td{{padding:12px 14px 12px 0; border-bottom:1px solid var(--line)}}
  .calib tr:last-child td{{border-bottom:0}}
  .calib .band{{color:var(--accent)}} .calib .traded{{color:var(--up); font-size:11px}}
  .tblwrap{{overflow-x:auto}}
  .news{{display:flex; flex-direction:column; border:1px solid var(--line); border-radius:10px; overflow:hidden}}
  .news-row{{display:grid; grid-template-columns:96px 1fr; gap:14px; padding:14px 16px; background:var(--panel)}}
  .news-row + .news-row{{border-top:1px solid var(--line)}}
  .news-tk{{font-weight:600; color:var(--accent); font-size:13px}}
  .news-links{{display:flex; flex-direction:column; gap:8px; min-width:0}}
  .hl{{color:var(--ink); text-decoration:none; font-size:13px; line-height:1.45; display:block}}
  .hl:hover{{color:var(--accent)}}
  .hl .src{{color:var(--faint); font-size:10px; letter-spacing:.06em; text-transform:uppercase; white-space:nowrap}}
  .srcs{{font-size:10px; color:var(--faint); letter-spacing:.05em; padding-top:2px}}
  .more, .nonews{{font-size:11px; letter-spacing:.06em; color:var(--faint); text-decoration:none}}
  .more:hover{{color:var(--accent)}}
  footer{{padding-top:26px; color:var(--faint); font-size:12px; line-height:1.7}}
  footer b{{color:var(--muted); font-weight:600}}
  .pro{{margin-top:16px; display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap; padding:16px; border:1px solid var(--accent-dim); border-radius:10px; background:var(--accent-glow)}}
  .pro .lead{{font-size:13px}} .pro .lead b{{color:var(--accent)}}
  .pro .cta{{font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--ground); background:var(--accent); padding:9px 15px; border-radius:6px; font-weight:700; white-space:nowrap}}
  a:focus-visible, .cta:focus-visible{{outline:2px solid var(--accent); outline-offset:2px}}
  @media (max-width:560px){{.ledger{{grid-template-columns:1fr}} .cards{{grid-template-columns:1fr}}
    .wordmark{{font-size:20px;letter-spacing:.34em}} .news-row{{grid-template-columns:1fr; gap:8px}}}}
</style>
<div class="wrap">
  <header>
    <div>
      <div class="brand">
        <div class="eye" aria-hidden="true"><svg viewBox="0 0 40 40" fill="none">
          <ellipse cx="20" cy="20" rx="18" ry="11" stroke="#d9a441" stroke-width="1.4"/>
          <circle cx="20" cy="20" r="6.4" fill="#d9a441" fill-opacity="0.14" stroke="#d9a441" stroke-width="1.4"/>
          <circle cx="20" cy="20" r="2.4" fill="#d9a441"/></svg></div>
        <div class="wordmark">ARGUS</div>
      </div>
      <div class="tagline">Autonomous signal intelligence · never sleeps</div>
    </div>
    <div class="status"><span class="pulse"></span> Live · updates every 5 min · {_e(gen_str)}</div>
  </header>
  <hr class="rule">

  <section>
    <div class="eyebrow"><span class="n">01</span>Track record</div>
    <h2>The whole book. Reds included.</h2>
    <p class="sub">Every trade the system takes is posted here — win or lose, at the fill price. No screenshots, no cherry-picking, no deleting the losers.</p>
    <div class="ledger">
      <div class="cell"><div class="k">Net P&amp;L</div><div class="v {pnl_cls}">{pnl_str}</div></div>
      <div class="cell"><div class="k">Record</div><div class="v">{_e(rec_line)}</div></div>
      <div class="cell"><div class="k">Open now</div><div class="v">{payload['open_count']} <small>positions</small></div></div>
    </div>
    <div class="honest">Most signal services advertise <b>75–96% win rates</b> independent tracking can't reproduce. We'd rather show a real record than a fake one. Paper account, live execution — the record is the pitch.</div>
  </section>
{open_section}
  <section>
    <div class="eyebrow"><span class="n">03</span>Closed trades</div>
    <h2>Settled positions</h2>
    <p class="sub">Most recent first. Confidence is the score the system held at entry.</p>
    <div class="rows">
{closed}
    </div>
  </section>

  <section>
    <div class="eyebrow"><span class="n">04</span>Live signals</div>
    <h2>What Argus sees right now</h2>
    <p class="sub">Direction and probability for every active setup, plus a suggested stop — the risk is never hidden. Exact entries and targets are the Pro layer. You judge whether a setup deserves your money.</p>
{patient}
    <div class="cards">
{cards}
    </div>
  </section>

  <section>
    <div class="eyebrow"><span class="n">05</span>Calibration</div>
    <h2>Does the probability mean anything?</h2>
    <p class="sub">The number nobody else publishes: how each confidence band actually resolves against real prices — including the signals we chose <b>not</b> to trade. This is how we set the {thr_pct}% trade line.</p>
    <div class="tblwrap"><table class="calib">
      <thead><tr><th>Confidence band</th><th>Signals</th><th>Won</th><th>Net R</th><th>Status</th></tr></thead>
      <tbody>
{calib}
      </tbody>
    </table></div>
  </section>
{news}
  <footer>
    <div class="pro">
      <div class="lead"><b>Argus Pro</b> — exact entries, profit targets, and an instant push the moment a setup fires, so you act without watching the board. Same signals as here, no delay — Pro just hands you the full trade and the alert.</div>
      <div class="cta">Join the waitlist</div>
    </div>
    <p style="margin-top:18px"><b>Educational only — not financial advice.</b> Argus is an autonomous algorithmic system, not a licensed advisor. Signals are probabilities, not recommendations; every entry carries risk of total loss. Suggested stops are shown so you can manage your own risk — the decision to enter is entirely yours. News links are third-party sources shown for context, not endorsements. The board updates about every 5 minutes. Past performance does not guarantee future results.</p>
    <p style="margin-top:12px;color:#454b58">◉ ARGUS · paper-trading track record · generated {_e(gen_str)}</p>
  </footer>
</div>"""


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
    os.makedirs(out_dir, exist_ok=True)
    payload = build_public_payload(include_news=True)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(render(payload))
    print(f"wrote {out_dir}/index.html — {len(payload['signals'])} signals, "
          f"{len(payload['closed_trades'])} closed, news for {len(payload.get('news', []))}")
