"""Monday paper iron condor. Dry-run unless EXECUTE=true.

The coming Friday weekly is the chain. MIN_DTE stays in config for a later slice
and does not skip that Friday. No price history is scraped; pass closes in.
"""

import argparse
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from adapters.alpaca_iron_condor import AlpacaIronCondorOrder
from adapters.alpaca_monitor import AlpacaMultiLegMonitor, run_intraday_exit_manager
from adapters.alpaca_paper import AlpacaPaperExecutor
from adapters.macro_news import NewsRiskFilter
from adapters.tradier_data import TradierOptionsClient
from config import get_settings
from core.bandit import ThompsonBandit
from core.greeks import black_scholes_delta
from core.regime import realized_vol, regime_label

NY = ZoneInfo("America/New_York")
# Further-OTM long wing. Short strikes use TARGET_DELTA (the 0.15 condor is the example).
WING_DELTA = 0.05
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
LOG_PATH = Path(__file__).resolve().parent / "logs" / "engine.log"
ENTRY_STAMP = LOG_PATH.parent / "last_weekly_entry.txt"


def _as_ny(now: datetime | date | None) -> datetime:
    if now is None:
        return datetime.now(NY)
    if isinstance(now, datetime):
        clock = now if now.tzinfo is not None else now.replace(tzinfo=NY)
        return clock.astimezone(NY)
    return datetime(now.year, now.month, now.day, 9, 30, tzinfo=NY)


def coming_friday(day: date) -> date:
    return day + timedelta(days=(4 - day.weekday()) % 7)


def match_friday(expirations, friday: date) -> str | None:
    wanted = friday.isoformat()
    clean = sorted({str(item)[:10] for item in expirations})
    if wanted in clean:
        return wanted
    later = [
        item
        for item in clean
        if item > wanted and date.fromisoformat(item).weekday() == 4
    ]
    return later[0] if later else None


def _frame(chain: pd.DataFrame) -> pd.DataFrame:
    frame = chain.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def _mid(row) -> float | None:
    bid = row.get("bid")
    ask = row.get("ask")
    if bid is None or ask is None or pd.isna(bid) or pd.isna(ask):
        return None
    bid_f = float(bid)
    ask_f = float(ask)
    if ask_f <= 0 or bid_f < 0 or ask_f < bid_f:
        return None
    return (bid_f + ask_f) / 2.0


def _right(row) -> str:
    raw = row.get("option_type", row.get("type", ""))
    if raw is None or pd.isna(raw):
        return ""
    return str(raw).strip().lower()


def _delta(row, right: str, expiration: str, spot, rate, vol):
    delta = row.get("delta")
    if delta is not None and not pd.isna(delta):
        return float(delta)
    if spot is None or rate is None or vol is None:
        return None
    strike = float(row["strike"])
    exp_raw = row.get("expiration_date") or expiration
    exp = date.fromisoformat(str(exp_raw)[:10])
    years = max((exp - date.today()).days, 0) / 365.0
    return black_scholes_delta(spot, strike, rate, vol, years, right)


def _closest(frame, right, target, expiration, spot, rate, vol, strike_lt=None, strike_gt=None):
    best = None
    best_dist = None
    for _, row in frame.iterrows():
        if _right(row) != right:
            continue
        symbol = row.get("symbol")
        if symbol is None or pd.isna(symbol) or not str(symbol):
            continue
        strike = float(row["strike"])
        if strike_lt is not None and strike >= strike_lt:
            continue
        if strike_gt is not None and strike <= strike_gt:
            continue
        delta = _delta(row, right, expiration, spot, rate, vol)
        if delta is None:
            continue
        dist = abs(abs(delta) - target)
        if best is None or dist < best_dist:
            best = (row, delta)
            best_dist = dist
    return best


def _pack(picked) -> dict:
    row, delta = picked
    return {
        "symbol": str(row["symbol"]),
        "strike": float(row["strike"]),
        "delta": float(delta),
        "mid": _mid(row),
    }


def iron_condor_from_chain(
    chain: pd.DataFrame,
    target_delta: float,
    expiration: str,
    spot=None,
    rate=None,
    vol=None,
    wing_delta: float = WING_DELTA,
):
    """Map target deltas to chain symbols. Returns None when a wing is missing."""
    if chain is None or len(chain) == 0:
        return None
    frame = _frame(chain)
    short_put = _closest(frame, "put", target_delta, expiration, spot, rate, vol)
    short_call = _closest(frame, "call", target_delta, expiration, spot, rate, vol)
    if short_put is None or short_call is None:
        return None
    long_put = _closest(
        frame,
        "put",
        wing_delta,
        expiration,
        spot,
        rate,
        vol,
        strike_lt=float(short_put[0]["strike"]),
    )
    long_call = _closest(
        frame,
        "call",
        wing_delta,
        expiration,
        spot,
        rate,
        vol,
        strike_gt=float(short_call[0]["strike"]),
    )
    if long_put is None or long_call is None:
        return None
    legs = {
        "long_put": _pack(long_put),
        "short_put": _pack(short_put),
        "short_call": _pack(short_call),
        "long_call": _pack(long_call),
    }
    if any(legs[name]["mid"] is None for name in legs):
        legs["credit"] = None
        return legs
    legs["credit"] = (
        legs["short_put"]["mid"]
        + legs["short_call"]["mid"]
        - legs["long_put"]["mid"]
        - legs["long_call"]["mid"]
    )
    return legs


def _print_legs(legs: dict, qty: int) -> None:
    for name in ("long_put", "short_put", "short_call", "long_call"):
        leg = legs[name]
        mid = "na" if leg["mid"] is None else f"{leg['mid']:.2f}"
        print(
            f"{name} {leg['symbol']} strike {leg['strike']:.2f} "
            f"delta {leg['delta']:.3f} mid {mid}"
        )
    if legs["credit"] is None:
        print("4-leg credit: unpriced (missing bid/ask); order not sent")
    else:
        print(f"4-leg credit {legs['credit']:.2f} qty {qty}")


def _regime(closes) -> str:
    if closes is None:
        return "unknown"
    series = list(closes)
    if len(series) < 2:
        return "unknown"
    return regime_label(realized_vol(series))


def run_week(
    closes=None,
    now=None,
    dry_run: bool | None = None,
    chain: pd.DataFrame | None = None,
    expiration: str | None = None,
    spot=None,
    rate=None,
    vol=None,
    loop_monitor: bool = False,
    realized_pnl: float | None = None,
) -> int:
    settings = get_settings()
    if dry_run is None:
        dry_run = not settings.EXECUTE

    ny = _as_ny(now)
    if ny.weekday() != 0:
        print("not Monday in New York; no weekly entry")
        return 0

    gate = NewsRiskFilter()
    for symbol in ("SPY", "QQQ"):
        ok, reason = gate.is_safe_to_enter(symbol, now=ny, check_earnings=not dry_run)
        print(f"{symbol}: {reason}")
        if not ok:
            return 0

    label = _regime(closes)
    print(f"regime: {label}")
    if label == "stress":
        print("no trade")
        return 0

    bandit = ThompsonBandit()
    arm = bandit.pick()
    print(f"bandit: {arm}")
    if realized_pnl is not None:
        bandit.update(arm, realized_pnl)
    if arm == "cash":
        print("no trade")
        return 0
    if arm != "iron_condor":
        print(f"no iron condor this run ({arm})")
        return 0

    target = settings.TARGET_DELTA
    qty = settings.MAX_CONTRACTS
    friday = coming_friday(ny.date())
    if chain is None:
        if dry_run:
            print(f"dry-run: Friday weekly {friday.isoformat()} not pulled")
            print(
                f"4-leg iron condor target delta {target:.2f}; "
                "credit not priced without a chain"
            )
            print("dry-run: order not sent")
            run_intraday_exit_manager(execute=False, loop=False)
            return 0
        data = TradierOptionsClient(
            api_token=settings.TRADIER_API_TOKEN,
            sandbox=settings.TRADIER_SANDBOX,
        )
        expiration = match_friday(data.get_expirations(settings.UNDERLYING), friday)
        if expiration is None:
            print(f"no Friday expiration on or after {friday.isoformat()}")
            return 0
        chain = data.get_option_chain(settings.UNDERLYING, expiration)
    else:
        expiration = expiration or friday.isoformat()

    legs = iron_condor_from_chain(
        chain, target, expiration, spot=spot, rate=rate, vol=vol
    )
    if legs is None:
        print("no contract near target delta")
        return 0
    print(f"expiration {expiration} target delta {target:.2f}")
    _print_legs(legs, qty)
    if legs["credit"] is None or legs["credit"] <= 0:
        if legs["credit"] is not None:
            print("no credit at these wings; order not sent")
        return 0
    if dry_run or not settings.EXECUTE:
        print("dry-run: order not sent")
        run_intraday_exit_manager(execute=False, loop=False)
        return 0

    broker = AlpacaPaperExecutor()
    order_api = AlpacaIronCondorOrder(broker.client)
    response = order_api.submit_condor(
        long_put_symbol=legs["long_put"]["symbol"],
        short_put_symbol=legs["short_put"]["symbol"],
        short_call_symbol=legs["short_call"]["symbol"],
        long_call_symbol=legs["long_call"]["symbol"],
        net_credit_limit=round(float(legs["credit"]), 2),
        qty=qty,
    )
    print(getattr(response, "id", response))
    try:
        run_intraday_exit_manager(
            monitor=AlpacaMultiLegMonitor(broker.client),
            underlying=settings.UNDERLYING,
            execute=True,
            loop=loop_monitor,
            condor_order=order_api,
        )
    except Exception as exc:
        print(f"monitor unavailable: {exc}")
    return 0


def in_market_hours(now: datetime | date | None = None) -> bool:
    """Weekdays 9:30–16:00 America/New_York. No holiday calendar."""
    ny = _as_ny(now)
    if ny.weekday() >= 5:
        return False
    current = ny.time().replace(second=0, microsecond=0)
    return MARKET_OPEN <= current < MARKET_CLOSE


def is_weekly_entry(now: datetime | date | None = None) -> bool:
    """Monday 9:30 is the one weekly entry. Later Monday checks are exits."""
    ny = _as_ny(now)
    current = ny.time().replace(second=0, microsecond=0)
    return ny.weekday() == 0 and current == MARKET_OPEN


def next_open(now: datetime | date | None = None) -> datetime:
    ny = _as_ny(now)
    day = ny.date()
    open_today = datetime.combine(day, MARKET_OPEN, tzinfo=NY)
    if ny.weekday() < 5 and ny < open_today:
        return open_today
    day = day + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, MARKET_OPEN, tzinfo=NY)


def seconds_until_next_check(now: datetime | date | None = None) -> float:
    """60 seconds while the market is open. Otherwise sleep until the next 9:30."""
    ny = _as_ny(now)
    if in_market_hours(ny):
        return 60.0
    return max((next_open(ny) - ny).total_seconds(), 1.0)


class _LogFile:
    """Line log for a process with no terminal. isatty() is always false."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")
        self._buf = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                stamp = datetime.now(NY).strftime("%Y-%m-%d %H:%M:%S")
                self._fh.write(f"{stamp} {line}\n")
        self._fh.flush()
        return len(data)

    def flush(self) -> None:
        if self._buf.strip():
            stamp = datetime.now(NY).strftime("%Y-%m-%d %H:%M:%S")
            self._fh.write(f"{stamp} {self._buf.strip()}\n")
            self._buf = ""
        self._fh.flush()

    def isatty(self) -> bool:
        return False


def _attach_log() -> None:
    stream = _LogFile(LOG_PATH)
    sys.stdout = stream
    sys.stderr = stream


def _exit_pass(execute: bool) -> None:
    """One 50% / 200% check. Dry-run does not open a broker client."""
    if not execute:
        run_intraday_exit_manager(execute=False, loop=False)
        return
    settings = get_settings()
    broker = AlpacaPaperExecutor()
    orders = AlpacaIronCondorOrder(broker.client)
    run_intraday_exit_manager(
        monitor=AlpacaMultiLegMonitor(broker.client),
        underlying=settings.UNDERLYING,
        execute=True,
        loop=False,
        condor_order=orders,
    )


def _already_entered(day: date) -> bool:
    if not ENTRY_STAMP.exists():
        return False
    return ENTRY_STAMP.read_text().strip() == day.isoformat()


def _mark_entered(day: date) -> None:
    ENTRY_STAMP.parent.mkdir(parents=True, exist_ok=True)
    ENTRY_STAMP.write_text(day.isoformat() + "\n")


def _headless_pass(clock: datetime, execute: bool) -> None:
    if is_weekly_entry(clock):
        # A restart during the 9:30 minute must not send a second paper order.
        if execute and _already_entered(clock.date()):
            print("weekly entry already ran today")
        else:
            print("Monday 9:30 weekly entry")
            if execute:
                _mark_entered(clock.date())
            run_week(now=clock, dry_run=not execute)
            return
    print("exit check")
    _exit_pass(execute)


def run_headless(once: bool = False, now=None, sleep=None) -> int:
    """No prompts and no TTY. --once is a single dry pass and does not sleep."""
    _attach_log()
    # --once stays dry even if EXECUTE=true, so a smoke check cannot send.
    execute = False if once else bool(get_settings().EXECUTE)
    print(f"headless paper runner once={once} execute={execute}")
    sleeper = time.sleep if sleep is None else sleep
    while True:
        clock = _as_ny(now) if now is not None else _as_ny(None)
        try:
            _headless_pass(clock, execute)
        except Exception as exc:
            print(f"pass failed: {exc}")
            if once:
                sys.stdout.flush()
                return 1
        if once:
            sys.stdout.flush()
            return 0
        delay = seconds_until_next_check(clock)
        print(f"sleep {int(delay)} seconds")
        sys.stdout.flush()
        sleeper(delay)
        now = None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Paper-only Monday iron condor")
    parser.add_argument("--dry-run", action="store_true", help="No network and no orders")
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="With EXECUTE=true, poll the exit rule every 60 seconds",
    )
    parser.add_argument(
        "--realized-pnl",
        type=float,
        default=None,
        help="Record a realized pnl for the arm just chosen",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run on the New York clock with no terminal",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --headless, one dry pass and exit",
    )
    parser.add_argument("--backtest", action="store_true", help="Not available yet")
    parser.add_argument("--data-dir", default=None, help="Not available yet")
    args = parser.parse_args(argv)
    if args.backtest or args.data_dir is not None:
        print("data directory not available yet", file=sys.stderr)
        raise SystemExit(1)
    if args.headless:
        raise SystemExit(run_headless(once=args.once))
    settings = get_settings()
    dry = True if args.dry_run or not settings.EXECUTE else False
    if args.monitor and dry:
        print("dry-run: --monitor does not sleep-loop the network")
    code = run_week(
        dry_run=dry,
        loop_monitor=bool(args.monitor and not dry),
        realized_pnl=args.realized_pnl,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
