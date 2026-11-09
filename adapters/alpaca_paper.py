"""Alpaca paper trading. paper=True is hardcoded; this module cannot go live."""

import os
from typing import Dict

from alpaca.trading.client import TradingClient

from .alpaca_iron_condor import AlpacaIronCondorOrder


class AlpacaPaperExecutor:
    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if not self.api_key or not self.secret_key:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for a paper call")
        # paper=True routes orders to the paper sandbox. There is no live switch.
        self.client = TradingClient(self.api_key, self.secret_key, paper=True)

    def get_account_summary(self) -> Dict[str, float]:
        account = self.client.get_account()
        return {
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
        }

    def close_all_positions(self):
        """Emergency circuit breaker: liquidates open positions."""
        return self.client.close_all_positions(cancel_orders=True)

    def submit_iron_condor_credit(
        self,
        long_put_symbol: str,
        short_put_symbol: str,
        short_call_symbol: str,
        long_call_symbol: str,
        net_credit_limit: float,
        qty: int = 1,
    ):
        """One 4-leg credit limit. Limit orders only; no market orders, no stock shorts."""
        return AlpacaIronCondorOrder(self.client).submit_condor(
            long_put_symbol=long_put_symbol,
            short_put_symbol=short_put_symbol,
            short_call_symbol=short_call_symbol,
            long_call_symbol=long_call_symbol,
            net_credit_limit=net_credit_limit,
            qty=qty,
        )

    def close_iron_condor(
        self,
        long_put_symbol: str,
        short_put_symbol: str,
        short_call_symbol: str,
        long_call_symbol: str,
        debit_limit: float,
        qty: int = 1,
    ):
        """Close helper. Debit limit, opening flag off."""
        return AlpacaIronCondorOrder(self.client).close_condor(
            long_put_symbol=long_put_symbol,
            short_put_symbol=short_put_symbol,
            short_call_symbol=short_call_symbol,
            long_call_symbol=long_call_symbol,
            debit_limit=debit_limit,
            qty=qty,
        )
