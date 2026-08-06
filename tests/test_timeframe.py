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
    assert {e.method for e in projection.estimates} <= {
        "historical_bottom_to_peak_cycles",
        "fundamentals_growth_implied",
    }


def test_project_timeframe_includes_analyst_estimate_crossing_when_supplied(declining_then_basing_hist):
    fundamentals = _fundamentals()  # trailing_pe=25.0, forward_pe=20.0 -> reversion P/E 25.0
    bottom = assess_bottom(declining_then_basing_hist)
    bottom.symbol = fundamentals.symbol
    peak = project_peak(fundamentals, declining_then_basing_hist)
    as_of = bottom.as_of
    reversion_pe = 25.0

    # 4 trailing quarters (low EPS) + 4 upcoming quarters sized so the
    # trailing-twelve-month run rate eventually clears the peak target.
    needed_ttm_eps = (peak.blended_target / reversion_pe) * 1.5
    per_quarter = needed_ttm_eps / 4
    before_dates = [as_of - pd.DateOffset(months=3 * i) for i in range(4, 0, -1)]
    after_dates = [as_of + pd.DateOffset(months=3 * i) for i in range(1, 5)]
    eps_values = [per_quarter * 0.5] * 4 + [per_quarter] * 4
    quarterly_estimates = pd.DataFrame(
        {"eps": eps_values},
        index=pd.DatetimeIndex(before_dates + after_dates, name="period_ending"),
    ).sort_index()

    projection = project_timeframe(
        declining_then_basing_hist, fundamentals, peak, bottom, quarterly_estimates=quarterly_estimates
    )

    crossing = next((e for e in projection.estimates if e.method == "analyst_estimate_crossing"), None)
    assert crossing is not None
    assert crossing.months > 0
