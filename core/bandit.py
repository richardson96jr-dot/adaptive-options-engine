"""Thompson sampling over four arms. Numpy only.

Each arm is a Gaussian posterior on mean pnl. Observation noise variance is 1.
New arms start at mean 0, std 1. State is bandit_state.json in the project root.
"""

import json
from pathlib import Path

import numpy as np

ARMS = ("short_put_spread", "short_call_spread", "iron_condor", "cash")
STATE_PATH = Path(__file__).resolve().parent.parent / "bandit_state.json"
_OBS_VAR = 1.0


def _fresh() -> dict:
    return {
        "arms": {arm: {"mean": 0.0, "std": 1.0} for arm in ARMS},
        "last_arm": None,
    }


class ThompsonBandit:
    def __init__(self, path: Path | None = None, seed: int | None = None):
        self.path = Path(path) if path is not None else STATE_PATH
        self._rng = np.random.default_rng(seed)
        self.state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return _fresh()
        try:
            loaded = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return _fresh()
        fresh = _fresh()
        arms = loaded.get("arms") if isinstance(loaded, dict) else None
        if not isinstance(arms, dict):
            return fresh
        for arm in ARMS:
            saved = arms.get(arm) or {}
            try:
                fresh["arms"][arm]["mean"] = float(saved.get("mean", 0.0))
                fresh["arms"][arm]["std"] = float(saved.get("std", 1.0))
            except (TypeError, ValueError):
                pass
        last = loaded.get("last_arm")
        fresh["last_arm"] = last if last in ARMS else None
        return fresh

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2) + "\n")

    def pick(self) -> str:
        samples = {
            arm: float(self._rng.normal(post["mean"], post["std"]))
            for arm, post in self.state["arms"].items()
        }
        arm = max(samples, key=samples.get)
        self.state["last_arm"] = arm
        self._save()
        return arm

    def update(self, arm: str, pnl: float) -> None:
        if arm not in self.state["arms"]:
            raise KeyError(arm)
        mean = self.state["arms"][arm]["mean"]
        std = self.state["arms"][arm]["std"]
        if std <= 0:
            std = 1.0
        prior_precision = 1.0 / (std * std)
        obs_precision = 1.0 / _OBS_VAR
        new_precision = prior_precision + obs_precision
        new_mean = (prior_precision * mean + obs_precision * float(pnl)) / new_precision
        self.state["arms"][arm]["mean"] = float(new_mean)
        self.state["arms"][arm]["std"] = float(np.sqrt(1.0 / new_precision))
        self.state["last_arm"] = arm
        self._save()
