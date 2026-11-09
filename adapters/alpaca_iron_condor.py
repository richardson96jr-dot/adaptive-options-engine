"""
Multi-leg iron condor constructor for Alpaca paper trading.

Symbols are arguments. Sample OCC strings in the spec are examples only and
are not used here. Callers pass strikes chosen from the option chain.
"""

from decimal import Decimal
from typing import List

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    PositionIntent,
    TimeInForce,
)
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest


class AlpacaIronCondorOrder:
    def __init__(self, trading_client: TradingClient):
        self.client = trading_client

    def build_legs(
        self,
        long_put_symbol: str,
        short_put_symbol: str,
        short_call_symbol: str,
        long_call_symbol: str,
        qty: int = 1,
        is_opening: bool = True,
    ) -> List[OptionLegRequest]:
        intent = PositionIntent.BUY_TO_OPEN if is_opening else PositionIntent.SELL_TO_CLOSE
        short_intent = PositionIntent.SELL_TO_OPEN if is_opening else PositionIntent.BUY_TO_CLOSE
        legs = [
            OptionLegRequest(
                symbol=long_put_symbol,
                ratio_qty=Decimal(qty),
                side=OrderSide.BUY if is_opening else OrderSide.SELL,
                position_intent=intent,
            ),
            OptionLegRequest(
                symbol=short_put_symbol,
                ratio_qty=Decimal(qty),
                side=OrderSide.SELL if is_opening else OrderSide.BUY,
                position_intent=short_intent,
            ),
            OptionLegRequest(
                symbol=short_call_symbol,
                ratio_qty=Decimal(qty),
                side=OrderSide.SELL if is_opening else OrderSide.BUY,
                position_intent=short_intent,
            ),
            OptionLegRequest(
                symbol=long_call_symbol,
                ratio_qty=Decimal(qty),
                side=OrderSide.BUY if is_opening else OrderSide.SELL,
                position_intent=intent,
            ),
        ]
        return legs

    def _submit(self, legs: List[OptionLegRequest], limit_price: float, qty: int, time_in_force: TimeInForce):
        # LimitOrderRequest is the alpaca-py type that keeps limit_price.
        # The base OrderRequest cannot. Negative mleg price is a credit; positive is a debit.
        mleg_order = LimitOrderRequest(
            qty=Decimal(qty),
            order_class=OrderClass.MLEG,
            time_in_force=time_in_force,
            limit_price=Decimal(str(round(limit_price, 2))),
            legs=legs,
        )
        if mleg_order.type.value != "limit":
            raise RuntimeError("market orders are not allowed")
        return self.client.submit_order(order_data=mleg_order)

    def submit_condor(
        self,
        long_put_symbol: str,
        short_put_symbol: str,
        short_call_symbol: str,
        long_call_symbol: str,
        net_credit_limit: float,
        qty: int = 1,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        if net_credit_limit <= 0:
            raise ValueError("net_credit_limit must be a positive credit")
        legs = self.build_legs(
            long_put_symbol=long_put_symbol,
            short_put_symbol=short_put_symbol,
            short_call_symbol=short_call_symbol,
            long_call_symbol=long_call_symbol,
            qty=qty,
            is_opening=True,
        )
        return self._submit(legs, -abs(float(net_credit_limit)), qty, time_in_force)

    def close_condor(
        self,
        long_put_symbol: str,
        short_put_symbol: str,
        short_call_symbol: str,
        long_call_symbol: str,
        debit_limit: float,
        qty: int = 1,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        """Close path. build_legs(..., is_opening=False) and a debit limit, not a credit."""
        if debit_limit <= 0:
            raise ValueError("debit_limit must be a positive debit")
        legs = self.build_legs(
            long_put_symbol=long_put_symbol,
            short_put_symbol=short_put_symbol,
            short_call_symbol=short_call_symbol,
            long_call_symbol=long_call_symbol,
            qty=qty,
            is_opening=False,
        )
        return self._submit(legs, abs(float(debit_limit)), qty, time_in_force)
