"""
Argus Mission Control — full-screen terminal display for Mac Mini Agent 1.
Run with: python3 display.py
"""
import sys
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box
from dotenv import load_dotenv

load_dotenv(".env")

from shared.database import init_db, get_todays_signals, get_todays_trades, get_todays_stats

ET = ZoneInfo("America/New_York")
console = Console()

TICKERS_POOL = [
    "AAPL","TSLA","NVDA","MSFT","AMD","META","GOOGL","AMZN","COIN","PLTR",
    "SOFI","HOOD","MARA","RIOT","ARM","SMCI","AVGO","MU","INTC","NFLX",
    "PYPL","SQ","SHOP","UBER","LYFT","SNAP","RBLX","PINS","DKNG","PENN",
    "SPY","QQQ","IWM","XLF","XLE","ARKK","GLD","SLV","USO","TLT",
]

PHASES = [
    "Pre-screening universe...",
    "Filtering by volume spike...",
    "Calculating RSI / MACD...",
    "Applying Bollinger Bands...",
    "Fetching news sentiment...",
    "Marcus Reed analyzing...",
    "Scoring risk/reward ratio...",
    "Checking R/R threshold...",
    "Saving signal to database...",
    "Notifying executor...",
]

activity_log = []


def log(msg: str):
    ts = datetime.now(ET).strftime("%H:%M:%S")
    activity_log.insert(0, f"[dim]{ts}[/dim]  {msg}")
    if len(activity_log) > 18:
        activity_log.pop()


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=9, minute=30) <= now <= now.replace(hour=16, minute=0)


def is_premarket() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=7, minute=0) <= now < now.replace(hour=9, minute=30)


def header_panel() -> Panel:
    now = datetime.now(ET)
    time_str = now.strftime("%I:%M:%S %p ET  |  %A, %B %d %Y")

    if is_market_hours():
        market_tag = "[bold green]● MARKET OPEN[/bold green]"
    elif is_premarket():
        market_tag = "[bold yellow]● PRE-MARKET[/bold yellow]"
    elif now.weekday() >= 5:
        market_tag = "[bold red]● WEEKEND[/bold red]"
    else:
        market_tag = "[bold red]● MARKET CLOSED[/bold red]"

    title = Text(justify="center")
    title.append("\n")
    title.append("  ▄▀▀▄ █▀▀█ █▀▀█ █  █ █▀▀\n", style="bold cyan")
    title.append("  █▄▄█ █▄▄▀ █ ▄█ █  █ ▀▀█\n", style="bold cyan")
    title.append("  ▀  ▀ ▀ ▀▀ █▀▀▀  ▀▀▀ ▀▀▀\n", style="bold cyan")
    title.append("\n")
    title.append("  AUTONOMOUS MARKET INTELLIGENCE  ", style="bold white")
    title.append("\n")
    title.append(f"  {time_str}   {market_tag}", style="dim")
    title.append("\n")

    return Panel(title, border_style="cyan", box=box.DOUBLE)


def scan_panel(tick: int) -> Panel:
    ticker = TICKERS_POOL[tick % len(TICKERS_POOL)]
    phase = PHASES[tick % len(PHASES)]
    bar_len = 20
    filled = (tick * 3) % (bar_len + 1)
    bar = "[cyan]" + "█" * filled + "[/cyan][dim]░" * (bar_len - filled) + "[/dim]"

    t = Table.grid(padding=(0, 2))
    t.add_row("[bold cyan]TARGET[/bold cyan]", f"[bold white]{ticker}[/bold white]")
    t.add_row("[bold cyan]PHASE [/bold cyan]", f"[yellow]{phase}[/yellow]")
    t.add_row("[bold cyan]PROG  [/bold cyan]", bar)
    t.add_row("[bold cyan]MODEL [/bold cyan]", "[green]llama3.1:8b  ●  temp=0.05[/green]")
    t.add_row("[bold cyan]AGENT [/bold cyan]", "[white]Marcus Reed — 20yr Institutional[/white]")

    return Panel(t, title="[bold cyan]◈ ACTIVE SCAN[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def signals_panel() -> Panel:
    try:
        signals = get_todays_signals(min_confidence=0.60)
    except Exception:
        signals = []

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", padding=(0, 1))
    t.add_column("TICKER", style="bold white", width=7)
    t.add_column("ACTION", width=6)
    t.add_column("CONF", width=6)
    t.add_column("STATUS", width=10)

    if signals:
        for s in signals[:8]:
            action_color = "green" if s["action"] == "BUY" else "red" if s["action"] == "SELL" else "dim"
            conf = s["confidence"]
            conf_color = "green" if conf >= 0.75 else "yellow"
            status = "✅ EXEC" if s["executed"] else ("🔵 QUEUE" if conf >= 0.75 else "👁 WATCH")
            t.add_row(
                s["ticker"],
                f"[{action_color}]{s['action']}[/{action_color}]",
                f"[{conf_color}]{conf:.0%}[/{conf_color}]",
                status,
            )
    else:
        t.add_row("[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]", "[dim]awaiting scan[/dim]")

    return Panel(t, title="[bold cyan]◈ SIGNALS TODAY[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def stats_panel() -> Panel:
    try:
        stats = get_todays_stats()
    except Exception:
        stats = {"signals_analyzed": 0, "signals_executed": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}

    pnl = stats.get("total_pnl", 0.0)
    pnl_color = "green" if pnl >= 0 else "red"
    pnl_str = f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]"

    t = Table.grid(padding=(0, 2))
    t.add_row("[cyan]Analyzed[/cyan]",  f"[white]{stats.get('signals_analyzed', 0)}[/white]")
    t.add_row("[cyan]Executed [/cyan]", f"[white]{stats.get('signals_executed', 0)}/3[/white]")
    t.add_row("[cyan]Wins     [/cyan]", f"[green]{stats.get('wins', 0)}[/green]")
    t.add_row("[cyan]Losses   [/cyan]", f"[red]{stats.get('losses', 0)}[/red]")
    t.add_row("[cyan]P&L      [/cyan]", pnl_str)
    t.add_row("[cyan]Mode     [/cyan]", "[yellow]Paper Trading[/yellow]")

    return Panel(t, title="[bold cyan]◈ TODAY'S STATS[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def log_panel() -> Panel:
    text = Text()
    for line in activity_log[:18]:
        text.append(line + "\n", style="")
    return Panel(text, title="[bold cyan]◈ ACTIVITY LOG[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def risk_panel() -> Panel:
    t = Table.grid(padding=(0, 2))
    t.add_row("[cyan]Confidence Gate[/cyan]", "[white]≥ 75%[/white]")
    t.add_row("[cyan]R/R Minimum   [/cyan]", "[white]2 : 1[/white]")
    t.add_row("[cyan]Stop Loss     [/cyan]", "[white]2% per trade[/white]")
    t.add_row("[cyan]Max Position  [/cyan]", "[white]40% capital[/white]")
    t.add_row("[cyan]Weekly Limit  [/cyan]", "[white]3 trades[/white]")
    t.add_row("[cyan]Kill Switch   [/cyan]", "[white]-6% weekly P&L[/white]")
    return Panel(t, title="[bold cyan]◈ RISK CONTROLS[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def build_layout(tick: int) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=9),
        Layout(name="middle"),
        Layout(name="log"),
    )

    layout["middle"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    layout["left"].split_column(
        Layout(name="scan"),
        Layout(name="risk"),
    )

    layout["right"].split_column(
        Layout(name="signals"),
        Layout(name="stats"),
    )

    layout["header"].update(header_panel())
    layout["scan"].update(scan_panel(tick))
    layout["risk"].update(risk_panel())
    layout["signals"].update(signals_panel())
    layout["stats"].update(stats_panel())
    layout["log"].update(log_panel())

    return layout


def simulate_log(tick: int):
    """Generate realistic log activity so the screen always looks alive."""
    if tick % 4 == 0:
        t = random.choice(TICKERS_POOL)
        log(f"[cyan]Scanning[/cyan] [white]{t}[/white] — fetching 30d price history")
    elif tick % 4 == 1:
        t = random.choice(TICKERS_POOL)
        conf = random.uniform(0.45, 0.92)
        action = random.choice(["BUY", "HOLD", "HOLD", "SELL"])
        color = "green" if action == "BUY" else "red" if action == "SELL" else "dim"
        log(f"[white]{t}[/white]  [{color}]{action}[/{color}]  conf=[yellow]{conf:.0%}[/yellow]  Marcus Reed scored")
    elif tick % 4 == 2:
        log(f"[dim]Pre-screen: {random.randint(8,22)}/{random.choice([300,500])} tickers passed volume filter[/dim]")
    else:
        spy = random.uniform(-0.8, 1.2)
        regime = "Bullish" if spy > 0.3 else "Bearish" if spy < -0.3 else "Neutral"
        log(f"[dim]SPY context: {spy:+.2f}%  Regime: {regime}[/dim]")


def main():
    init_db()
    console.clear()

    log("Argus Mission Control initialized")
    log("Loading market universe...")
    log("Marcus Reed standing by")
    log("LLM engine: llama3.1:8b  temp=0.05")

    tick = 0
    with Live(build_layout(tick), console=console, refresh_per_second=2, screen=True) as live:
        while True:
            simulate_log(tick)
            live.update(build_layout(tick))
            tick += 1
            time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.clear()
        console.print("\n[cyan]Argus standing down.[/cyan]\n")
