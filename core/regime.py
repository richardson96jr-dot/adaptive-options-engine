"""Realized vol and a three-way label.

Fixed annualized close-to-close thresholds:
- calm: realized vol below 0.15
- elevated: 0.15 up to 0.25
- stress: 0.25 and above

Simple stand-in for an HMM. The label is these cutoffs, not a hidden-state model.
"""

import math

import numpy as np

CALM_BELOW = 0.15
STRESS_AT = 0.25


def realized_vol(closes) -> float:
    """Close-to-close realized vol, annualized with 252 sessions."""
    series = np.asarray(list(closes), dtype=float)
    if series.size < 2:
        raise ValueError("need at least two closes")
    if np.any(series <= 0):
        raise ValueError("closes must be positive")
    log_returns = np.diff(np.log(series))
    if log_returns.size == 1:
        sigma = abs(float(log_returns[0]))
    else:
        sigma = float(np.std(log_returns, ddof=1))
    return sigma * math.sqrt(252)


def variance_risk_premium(implied_vol: float, realized: float) -> float:
    """Implied vol minus realized vol. Call this only when IV is known."""
    return float(implied_vol - realized)


def regime_label(realized: float) -> str:
    if realized < CALM_BELOW:
        return "calm"
    if realized < STRESS_AT:
        return "elevated"
    return "stress"
