"""News safety gate: high-impact days (CPI, FOMC) and Finnhub earnings."""

import os
from datetime import date, datetime
from typing import Tuple
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")

# Edit this list. Trading is blocked on these same-day CPI and FOMC dates.
# Announcement days only. FOMC is the decision day, not the first meeting day.
# BLS lists 2026 CPI releases for Nov 10 and Dec 10. Earlier 2026 CPI dates are not on that page.
CPI_FOMC_DATES = [
    ("2026-01-28", "FOMC"),
    ("2026-03-18", "FOMC"),
    ("2026-04-29", "FOMC"),
    ("2026-06-17", "FOMC"),
    ("2026-07-29", "FOMC"),
    ("2026-09-16", "FOMC"),
    ("2026-10-28", "FOMC"),
    ("2026-11-10", "CPI"),
    ("2026-12-09", "FOMC"),
    ("2026-12-10", "CPI"),
]


def _session_day(now: datetime | date | None) -> date:
    if now is None:
        return datetime.now(NY).date()
    if isinstance(now, datetime):
        clock = now if now.tzinfo is not None else now.replace(tzinfo=NY)
        return clock.astimezone(NY).date()
    return now


class NewsRiskFilter:
    def __init__(self, finnhub_key: str | None = None):
        key = finnhub_key if finnhub_key is not None else os.getenv("FINNHUB_API_KEY")
        self.api_key = (key or "").strip()
        self.base_url = "https://finnhub.io/api/v1"

    def _macro_reason(self, day: date, window_days: int = 0) -> str | None:
        for raw, name in CPI_FOMC_DATES:
            event = date.fromisoformat(raw)
            if abs((event - day).days) <= window_days:
                return f"{name} on {raw}."
        return None

    def is_safe_to_enter(
        self,
        symbol: str,
        now: datetime | date | None = None,
        check_earnings: bool = True,
        window_days: int = 0,
    ) -> Tuple[bool, str]:
        """
        Returns (False, reason) if a listed macro day or earnings event hits today.
        Otherwise returns (True, reason). A news outage does not raise.
        """
        blocked = self._macro_reason(_session_day(now), window_days=window_days)
        if blocked:
            return False, blocked
        if not self.api_key:
            return True, "No Finnhub API Key provided; risk filter bypassed."
        if not check_earnings:
            return True, "Market Clear"
        today = _session_day(now).strftime("%Y-%m-%d")
        url = f"{self.base_url}/calendar/earnings"
        params = {"from": today, "to": today, "symbol": symbol, "token": self.api_key}
        try:
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json().get("earningsCalendar", [])
            if data:
                return False, f"Earnings release scheduled today for {symbol}."
        except Exception as exc:
            text = str(exc)
            if self.api_key and self.api_key in text:
                text = "news unavailable"
            return True, f"Filter check failed: {text}"
        return True, "Market Clear"
