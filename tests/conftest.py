import numpy as np
import pandas as pd
import pytest


def _make_price_series(
    n_days: int,
    start_price: float,
    pattern: list,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a list of (days, daily_drift)
    segments, e.g. [(120, -0.01), (60, 0.015)] for a decline then a rally.
    """
    dates = pd.bdate_range("2021-01-04", periods=n_days)
    prices = [start_price]
    rng = np.random.default_rng(42)
    seg_idx = 0
    seg_days_left, seg_drift = pattern[0]
    for _ in range(n_days - 1):
        if seg_days_left <= 0 and seg_idx < len(pattern) - 1:
            seg_idx += 1
            seg_days_left, seg_drift = pattern[seg_idx]
        noise = rng.normal(0, 0.003)
        next_price = max(prices[-1] * (1 + seg_drift + noise), 0.5)
        prices.append(next_price)
        seg_days_left -= 1

    close = pd.Series(prices, index=dates[: len(prices)], name="Close")
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        }
    )
    return df


@pytest.fixture
def declining_then_basing_hist() -> pd.DataFrame:
    """A stock that fell ~30% then bottomed and has bounced modestly,
    reclaiming its short-term moving average.
    """
    return _make_price_series(
        n_days=260,
        start_price=100.0,
        pattern=[(160, -0.0025), (40, 0.0005), (60, 0.006)],
    )


@pytest.fixture
def uptrend_hist() -> pd.DataFrame:
    """A stock in a steady uptrend with no meaningful drawdown - no bottom to confirm."""
    return _make_price_series(n_days=260, start_price=50.0, pattern=[(260, 0.0025)])


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
