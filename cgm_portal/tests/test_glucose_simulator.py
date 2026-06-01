"""Tests for the glucose simulator."""
from app.services.glucose_simulator import GlucoseSimulator


def test_values_in_range():
    sim = GlucoseSimulator(baseline=5.5, floor=2.0, ceiling=20.0)
    for _ in range(500):
        v = sim.next_value()
        assert 2.0 <= v <= 20.0


def test_values_fluctuate():
    sim = GlucoseSimulator()
    values = [sim.next_value() for _ in range(100)]
    # Not all the same
    assert len(set(values)) > 1


def test_mean_reversion():
    """Over many steps, the mean should be near the baseline."""
    sim = GlucoseSimulator(baseline=5.5, volatility=0.1, mean_reversion=0.1)
    values = [sim.next_value() for _ in range(1000)]
    mean = sum(values) / len(values)
    assert abs(mean - 5.5) < 1.0


def test_single_decimal():
    sim = GlucoseSimulator()
    for _ in range(100):
        v = sim.next_value()
        assert v == round(v, 1)
