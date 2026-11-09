"""Open iron condors and the 50% / 200% exit check.

One condor per expiration. A later slice can split several condors that share a date.
Marks come from the position objects the caller already has. This module does not
fetch a price history.
"""

import time
from dataclasses import dataclass
from typing import Dict, List

from alpaca.trading.client import TradingClient


@dataclass
class CondorStructure:
    underlying: str
    expiration: str
    long_put: str
    short_put: str
    short_call: str
    long_call: str
    qty: int
    initial_net_credit: float
    current_liquidation_cost: float
    unrealized_pnl: float
    profit_capture_pct: float


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _is_short(position) -> bool:
    side = getattr(position, "side", None)
    text = str(getattr(side, "value", side)).lower()
    if "short" in text:
        return True
    if "long" in text:
        return False
    qty = _f(getattr(position, "qty", None)) or 0.0
    return qty < 0


class AlpacaMultiLegMonitor:
    def __init__(self, trading_client: TradingClient):
        self.client = trading_client

    def parse_occ_symbol(self, symbol: str) -> Dict[str, float | str]:
        """OCC root + YYMMDD + C/P + 8-digit strike. Example shape only, not an order."""
        raw = symbol.strip().upper()
        if len(raw) < 16:
            raise ValueError(f"not an OCC option symbol: {symbol}")
        tail = raw[-15:]
        root = raw[:-15]
        right = tail[6]
        if right not in {"C", "P"} or not root:
            raise ValueError(f"not an OCC option symbol: {symbol}")
        try:
            strike = int(tail[7:]) / 1000.0
            expiration = f"20{tail[0:2]}-{tail[2:4]}-{tail[4:6]}"
        except ValueError as exc:
            raise ValueError(f"not an OCC option symbol: {symbol}") from exc
        return {
            "underlying": root,
            "expiration": expiration,
            "right": "call" if right == "C" else "put",
            "strike": strike,
            "symbol": raw,
        }

    def get_open_condors(self, underlying: str = "SPY") -> List[CondorStructure]:
        positions = self.client.get_all_positions()
        legs = []
        wanted = underlying.upper()
        for position in positions:
            symbol = str(getattr(position, "symbol", "") or "")
            try:
                parsed = self.parse_occ_symbol(symbol)
            except ValueError:
                continue
            if parsed["underlying"] != wanted:
                continue
            qty = _f(getattr(position, "qty", None))
            if qty is None:
                continue
            legs.append(
                {
                    **parsed,
                    "short": _is_short(position),
                    "qty": abs(qty),
                    "entry": _f(getattr(position, "avg_entry_price", None)),
                    "mark": _f(getattr(position, "current_price", None)),
                }
            )
        return condors_from_legs(legs, wanted)

    def display_portfolio_status(self, underlying: str = "SPY") -> None:
        condors = self.get_open_condors(underlying)
        if not condors:
            print(f"no open condors for {underlying}")
            return
        for condor in condors:
            print(
                f"{condor.expiration} credit {condor.initial_net_credit:.2f} "
                f"to_close {condor.current_liquidation_cost:.2f} "
                f"pnl {condor.unrealized_pnl:.2f} "
                f"capture {condor.profit_capture_pct:.1f}%"
            )


def _tightest_pair(shorts: list[dict], longs: list[dict], long_is_above: bool):
    """Closest long wing outside the short strike. One pair; easy to replace later."""
    best = None
    best_gap = None
    for short in shorts:
        for long in longs:
            if long_is_above and long["strike"] <= short["strike"]:
                continue
            if not long_is_above and long["strike"] >= short["strike"]:
                continue
            gap = abs(long["strike"] - short["strike"])
            if best is None or gap < best_gap:
                best = (long, short)
                best_gap = gap
    return best


def _pnl(credit: float, cost: float | None) -> tuple[float, float, float]:
    """Missing marks stay flat so a blank quote cannot trip the exit."""
    if cost is None or credit <= 0:
        return 0.0, 0.0, credit
    pnl = credit - cost
    return pnl, 100.0 * pnl / credit, cost


def condors_from_legs(legs: list[dict], underlying: str) -> List[CondorStructure]:
    by_exp: dict[str, list[dict]] = {}
    for leg in legs:
        if leg.get("underlying") != underlying:
            continue
        by_exp.setdefault(str(leg["expiration"]), []).append(leg)
    found: List[CondorStructure] = []
    for expiration, group in sorted(by_exp.items()):
        put_shorts = [leg for leg in group if leg["right"] == "put" and leg["short"]]
        put_longs = [leg for leg in group if leg["right"] == "put" and not leg["short"]]
        call_shorts = [leg for leg in group if leg["right"] == "call" and leg["short"]]
        call_longs = [leg for leg in group if leg["right"] == "call" and not leg["short"]]
        puts = _tightest_pair(put_shorts, put_longs, long_is_above=False)
        calls = _tightest_pair(call_shorts, call_longs, long_is_above=True)
        if puts is None or calls is None:
            continue
        long_put, short_put = puts
        long_call, short_call = calls
        four = (long_put, short_put, short_call, long_call)
        if any(leg.get("entry") is None for leg in four):
            continue
        qty = int(min(leg["qty"] for leg in four))
        if qty < 1:
            continue
        credit = (
            short_put["entry"] + short_call["entry"] - long_put["entry"] - long_call["entry"]
        )
        marks = [leg.get("mark") for leg in four]
        if any(mark is None for mark in marks):
            cost = None
        else:
            cost = short_put["mark"] + short_call["mark"] - long_put["mark"] - long_call["mark"]
        pnl, pct, shown_cost = _pnl(credit, cost)
        found.append(
            CondorStructure(
                underlying=underlying,
                expiration=expiration,
                long_put=long_put["symbol"],
                short_put=short_put["symbol"],
                short_call=short_call["symbol"],
                long_call=long_call["symbol"],
                qty=qty,
                initial_net_credit=float(credit),
                current_liquidation_cost=float(shown_cost),
                unrealized_pnl=float(pnl),
                profit_capture_pct=float(pct),
            )
        )
    return found


def close_condor_order(condor_order, condor: CondorStructure, execute: bool):
    """Submit the closing debit only when execute is true."""
    if not execute:
        return None
    if condor_order is None:
        raise RuntimeError("close requested but no AlpacaIronCondorOrder was provided")
    debit = float(condor.current_liquidation_cost)
    if debit <= 0:
        debit = 0.01
    return condor_order.close_condor(
        long_put_symbol=condor.long_put,
        short_put_symbol=condor.short_put,
        short_call_symbol=condor.short_call,
        long_call_symbol=condor.long_call,
        debit_limit=debit,
        qty=condor.qty,
    )


def run_intraday_exit_manager(
    monitor: AlpacaMultiLegMonitor | None = None,
    underlying: str = "SPY",
    execute: bool = False,
    loop: bool = False,
    condor_order=None,
):
    """50% profit or 200% credit loss. Dry-run is one pass and does not sleep."""
    if monitor is None:
        print("dry-run: exit check one pass, no network")
        print("close if profit reaches 50% of max credit, or credit loss reaches 200%")
        return
    while True:
        condors = monitor.get_open_condors(underlying)
        for condor in condors:
            if condor.profit_capture_pct >= 50.0:
                print(f"Triggering automated exit for {condor.expiration}: 50% profit reached.")
                close_condor_order(condor_order, condor, execute)
            elif (
                condor.initial_net_credit > 0
                and condor.unrealized_pnl <= -(2.0 * condor.initial_net_credit)
            ):
                print(f"Triggering stop-loss exit for {condor.expiration}: 200% loss hit.")
                close_condor_order(condor_order, condor, execute)
        if not loop:
            return
        time.sleep(60)
