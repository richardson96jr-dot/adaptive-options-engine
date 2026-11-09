"""Black-Scholes price and delta for European calls and puts."""

import math

from scipy.stats import norm


def _d1(spot: float, strike: float, rate: float, vol: float, time_years: float) -> float:
    sqrt_t = math.sqrt(time_years)
    return (math.log(spot / strike) + (rate + 0.5 * vol * vol) * time_years) / (vol * sqrt_t)


def black_scholes_price(
    spot: float,
    strike: float,
    rate: float,
    vol: float,
    time_years: float,
    right: str,
) -> float:
    kind = right.strip().lower()
    if kind not in {"call", "put"}:
        raise ValueError("right must be 'call' or 'put'")
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if time_years <= 0 or vol <= 0:
        intrinsic = max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
        return float(intrinsic)
    d1 = _d1(spot, strike, rate, vol, time_years)
    d2 = d1 - vol * math.sqrt(time_years)
    discount = math.exp(-rate * time_years)
    if kind == "call":
        return float(spot * norm.cdf(d1) - strike * discount * norm.cdf(d2))
    return float(strike * discount * norm.cdf(-d2) - spot * norm.cdf(-d1))


def black_scholes_delta(
    spot: float,
    strike: float,
    rate: float,
    vol: float,
    time_years: float,
    right: str,
) -> float:
    kind = right.strip().lower()
    if kind not in {"call", "put"}:
        raise ValueError("right must be 'call' or 'put'")
    if time_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        if kind == "call":
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    d1 = _d1(spot, strike, rate, vol, time_years)
    if kind == "call":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1.0)
