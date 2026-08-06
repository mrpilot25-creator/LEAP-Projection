import pytest

from leap_projection.data import Fundamentals
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


def test_blends_multiple_methods(declining_then_basing_hist):
    fundamentals = _fundamentals()
    projection = project_peak(fundamentals, declining_then_basing_hist)

    methods = {e.method for e in projection.estimates}
    assert "forward_pe_reversion" in methods
    assert "peg_one" in methods
    assert "analyst_consensus" in methods
    assert "prior_high_extension" in methods

    assert projection.low_target <= projection.blended_target <= projection.high_target
    assert projection.blended_target > 0


def test_raises_without_any_usable_fundamentals(declining_then_basing_hist):
    fundamentals = _fundamentals(
        forward_eps=None,
        trailing_pe=None,
        forward_pe=None,
        earnings_growth=None,
        revenue_growth=None,
        analyst_target_mean=None,
    )
    with pytest.raises(ValueError):
        project_peak(fundamentals, declining_then_basing_hist)


def test_growth_implied_pe_is_capped(declining_then_basing_hist):
    fundamentals = _fundamentals(earnings_growth=3.0, forward_eps=5.0)  # 300% growth, absurd
    projection = project_peak(fundamentals, declining_then_basing_hist)
    peg_estimate = next(e for e in projection.estimates if e.method == "peg_one")
    assert peg_estimate.target_price == pytest.approx(5.0 * 60.0)
