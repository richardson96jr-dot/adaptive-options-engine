"""Environment settings. Missing tokens stay blank and do not crash import."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent


def _raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _bool(name: str, default: bool) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def _float(name: str, default: float) -> float:
    raw = _raw(name)
    return default if raw is None else float(raw)


def _int(name: str, default: int) -> int:
    raw = _raw(name)
    return default if raw is None else int(raw)


class Settings(BaseModel):
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_PAPER: bool = True
    TRADIER_API_TOKEN: str = ""
    TRADIER_SANDBOX: bool = False
    UNDERLYING: str = "SPY"
    TARGET_DELTA: float = 0.16
    MAX_CONTRACTS: int = 1
    MIN_DTE: int = 7
    EXECUTE: bool = False
    FINNHUB_API_KEY: str = ""


def get_settings() -> Settings:
    """Read the environment again. Empty values use the defaults above."""
    load_dotenv(_ROOT / ".env")
    return Settings(
        ALPACA_API_KEY=_raw("ALPACA_API_KEY") or "",
        ALPACA_SECRET_KEY=_raw("ALPACA_SECRET_KEY") or "",
        ALPACA_PAPER=_bool("ALPACA_PAPER", True),
        TRADIER_API_TOKEN=_raw("TRADIER_API_TOKEN") or "",
        TRADIER_SANDBOX=_bool("TRADIER_SANDBOX", False),
        UNDERLYING=_raw("UNDERLYING") or "SPY",
        TARGET_DELTA=_float("TARGET_DELTA", 0.16),
        MAX_CONTRACTS=_int("MAX_CONTRACTS", 1),
        MIN_DTE=_int("MIN_DTE", 7),
        EXECUTE=_bool("EXECUTE", False),
        FINNHUB_API_KEY=_raw("FINNHUB_API_KEY") or "",
    )
