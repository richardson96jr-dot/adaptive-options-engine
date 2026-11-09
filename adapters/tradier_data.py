"""Tradier option expirations and chains. A live call needs TRADIER_API_TOKEN."""

import os

import pandas as pd
import requests


class TradierOptionsClient:
    def __init__(self, api_token: str | None = None, sandbox: bool = False):
        token = api_token if api_token is not None else os.getenv("TRADIER_API_TOKEN")
        self.api_token = (token or "").strip()
        host = "https://sandbox.tradier.com/v1" if sandbox else "https://api.tradier.com/v1"
        self.base_url = host
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    def _require_token(self) -> None:
        if not self.api_token:
            raise RuntimeError("TRADIER_API_TOKEN is missing")

    def _get(self, path: str, params: dict) -> dict:
        self._require_token()
        response = requests.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_expirations(self, symbol: str) -> list[str]:
        payload = self._get(
            "/markets/options/expirations",
            {"symbol": symbol, "includeAllRoots": "true"},
        )
        expirations = (payload or {}).get("expirations") or {}
        dates = expirations.get("date") if isinstance(expirations, dict) else None
        if dates is None:
            return []
        if isinstance(dates, str):
            return [dates]
        return [str(item) for item in dates]

    def get_option_chain(self, symbol: str, expiration: str) -> pd.DataFrame:
        payload = self._get(
            "/markets/options/chains",
            {"symbol": symbol, "expiration": expiration, "greeks": "true"},
        )
        options = (payload or {}).get("options") or {}
        rows = options.get("option") if isinstance(options, dict) else None
        if not rows:
            return pd.DataFrame()
        if isinstance(rows, dict):
            rows = [rows]
        frame = pd.DataFrame(rows)
        if "greeks" not in frame.columns:
            return frame
        records = [item if isinstance(item, dict) else {} for item in frame["greeks"].tolist()]
        greeks = pd.json_normalize(records)
        frame = frame.drop(columns=["greeks"]).reset_index(drop=True)
        greeks = greeks.reset_index(drop=True)
        shared = [column for column in greeks.columns if column in frame.columns]
        if shared:
            frame = frame.drop(columns=shared)
        return frame.join(greeks)
