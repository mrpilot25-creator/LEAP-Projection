import pandas as pd
import pytest

from leap_projection.bottom import assess_bottom
from leap_projection.data import Fundamentals
from leap_projection.timeframe import (
    growth_implied_months,
    historical_cycle_months,
    project_timeframe,
)
from leap_projection.valuation import project_peak


def _fundamentals(**overrides) -> Fundamentals:
    base = dict(
        symbol="TEST",
        current_price=100.0,
        trailing_eps=4.0,
        forward_eps=5.0,
        trailing_pe=25.0,
        forward_pe=20.0,
        peg_ratio=1.2,
        earnings_growth=0.20,
        revenue_growth=0.15,
        analyst_target_mean=130.0,
        analyst_target_high=160.0,
        analyst_target_low=110.0,
        sector="Technology",
        market_cap=5_000_000_000,
    )
    base.update(overrides)
    return Fundamentals(**base)


def test_growth_implied_months_basic():
    # 100 -> 200 at 20%/yr should take ~3.8 years => ~46 months
    months = growth_implied_months(100.0, 200.0, 0.20)
    assert months == pytest.approx(45.6, abs=1.0)


def test_growth_implied_months_zero_when_target_at_or_below_current():
    assert growth_implied_months(150.0, 150.0, 0.20) == 0.0
    assert growth_implied_months(150.0, 100.0, 0.20) == 0.0


def test_growth_implied_months_none_without_growth_rate():
    assert growth_implied_months(100.0, 200.0, None) is None


def test_historical_cycle_months_finds_cycles(cyclical_hist):
    months = historical_cycle_months(cyclical_hist)
    assert months is not None
    assert months > 0


def test_project_timeframe_end_to_end(declining_then_basing_hist):
    fundamentals = _fundamentals()
    bottom = assess_bottom(declining_then_basing_hist)
    bottom.symbol = fundamentals.symbol
    peak = project_peak(fundamentals, declining_then_basing_hist)

    projection = project_timeframe(declining_then_basing_hist, fundamentals, peak, bottom)

    assert projection.blended_months > 0
    assert isinstance(projection.target_date, pd.Timestamp)
    assert projection.target_date > bottom.as_of
