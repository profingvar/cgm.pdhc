"""Glucose simulator — generates slowly fluctuating glucose readings.

Produces realistic-looking CGM values using a random walk with mean-reversion
around a configurable baseline (default 5.5 mmol/L). Values stay within
physiological bounds (2.0–20.0 mmol/L).
"""
import random
import math


class GlucoseSimulator:
    """Stateful simulator that remembers its last value for smooth continuity."""

    def __init__(self, baseline=5.5, volatility=0.15, mean_reversion=0.05,
                 floor=2.0, ceiling=20.0):
        self.baseline = baseline
        self.volatility = volatility
        self.mean_reversion = mean_reversion
        self.floor = floor
        self.ceiling = ceiling
        self._current = baseline + random.gauss(0, 0.3)

    def next_value(self):
        """Generate the next glucose reading (mmol/L).

        Uses a mean-reverting random walk:
        - Drift toward baseline (mean reversion)
        - Small random noise (volatility)
        - Clamped to physiological bounds
        """
        drift = self.mean_reversion * (self.baseline - self._current)
        noise = random.gauss(0, self.volatility)
        self._current += drift + noise
        self._current = max(self.floor, min(self.ceiling, self._current))
        return round(self._current, 1)
