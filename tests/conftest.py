import numpy as np
import pandas as pd
import pytest


def _make_price_series(
    n_days: int,
    start_price: float,
    pattern: list,
    noise_std: float = 0.003,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a list of (days, daily_drift)
    segments, e.g. [(120, -0.01), (60, 0.015)] for a decline then a rally.
    """
    dates = pd.bdate_range("2021-01-04", periods=n_days)
    prices = [start_price]
    rng = np.random.default_rng(seed)
    seg_idx = 0
    seg_days_left, seg_drift = pattern[0]
    for _ in range(n_days - 1):
        if seg_days_left <= 0 and seg_idx < len(pattern) - 1:
            seg_idx += 1
            seg_days_left, seg_drift = pattern[seg_idx]
        noise = rng.normal(0, noise_std)
        next_price = max(prices[-1] * (1 + seg_drift + noise), 0.5)
        prices.append(next_price)
        seg_days_left -= 1

    close = pd.Series(prices, index=dates[: len(prices)], name="Close")
    volume = pd.Series(rng.integers(800_000, 1_200_000, size=len(close)), index=close.index)
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.012,
            "Low": close * 0.988,
            "Close": close,
            "Volume": volume,
        }
    )
    return df


@pytest.fixture
def declining_then_basing_hist() -> pd.DataFrame:
    """A stock that fell ~30% then bottomed and has bounced modestly."""
    return _make_price_series(
        n_days=260,
        start_price=100.0,
        pattern=[(160, -0.0025), (40, 0.0005), (60, 0.006)],
    )


@pytest.fixture
def cyclical_hist() -> pd.DataFrame:
    """Several full bottom -> peak -> bottom cycles, for timeframe-estimation tests."""
    pattern = [
        (60, -0.01),
        (60, 0.012),
        (60, -0.01),
        (60, 0.012),
        (60, -0.01),
        (60, 0.012),
    ]
    return _make_price_series(n_days=sum(d for d, _ in pattern) + 1, start_price=80.0, pattern=pattern)


@pytest.fixture
def sample_hist() -> pd.DataFrame:
    """A generic, long-enough-for-the-checklist price series with no
    engineered pattern -- used for tests that mock out `compute_signals`
    and only care about assess_bottom's aggregation/decision logic.
    """
    return _make_price_series(n_days=160, start_price=75.0, pattern=[(160, 0.0003)])


@pytest.fixture
def checklist_fire_hist() -> pd.DataFrame:
    """A sharp decline followed by a V-shaped recovery, deterministic (fixed
    seed) and empirically verified to trigger the real (unmocked) checklist
    -- used for one end-to-end sanity test against the actual indicators.
    """
    return _make_price_series(
        n_days=220,
        start_price=100.0,
        pattern=[(140, -0.008), (30, 0.0), (20, 0.02), (30, 0.003)],
        noise_std=0.006,
    )
