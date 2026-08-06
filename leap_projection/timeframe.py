"""Timeframe estimation: how long until the projected peak, once a bottom holds.

Up to three independent methods are blended:
  * historical_bottom_to_peak_cycles - average duration of past bottom->peak
    swings in the stock's own price history.
  * fundamentals_growth_implied - years of compounding at the fundamental
    growth rate needed to close the gap between current price and the
    projected peak target.
  * analyst_estimate_crossing - (only when a stockanalysis.com quarterly
    estimates paste is supplied) the first future quarter whose consensus
    trailing-twelve-month EPS, at the reversion P/E, projects a price that
    reaches the peak target -- a real analyst-grounded date rather than a
    constant-growth-rate assumption.

This is directly aimed at LEAP option planning: the blended horizon is a
starting point for picking an expiration with enough runway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .bottom import BottomAssessment, find_swing_lows
from .data import Fundamentals
from .estimates import analyst_estimate_crossing_months
from .valuation import PeakProjection, _reversion_multiple

AVG_DAYS_PER_MONTH = 30.44
DEFAULT_FALLBACK_MONTHS = 18.0  # a neutral LEAP-horizon default when no signal is available
MIN_ANNUAL_GROWTH_FLOOR = 0.02  # avoid divide-by-zero / absurd horizons on ~0% growth


@dataclass
class TimeframeEstimate:
    method: str
    months: Optional[float]
    detail: str


@dataclass
class TimeframeProjection:
    symbol: str
    estimates: List[TimeframeEstimate]
    blended_months: float
    target_date: pd.Timestamp


def _find_swing_highs(close: pd.Series, order: int = 15) -> pd.Series:
    values = close.to_numpy()
    idx = []
    for i in range(order, len(values) - order):
        window = values[i - order : i + order + 1]
        if values[i] == window.max() and np.sum(window == values[i]) == 1:
            idx.append(i)
    return close.iloc[idx]


def historical_cycle_months(hist: pd.DataFrame, order: int = 15) -> Optional[float]:
    """Average number of months from a swing low to the next swing high,
    across the full price history available.
    """
    close = hist["Close"].dropna()
    lows = find_swing_lows(close, order=order)
    highs = _find_swing_highs(close, order=order)
    if lows.empty or highs.empty:
        return None

    swings = sorted(
        [(idx, "L") for idx in lows.index] + [(idx, "H") for idx in highs.index]
    )
    # Collapse consecutive swings of the same type, keeping the most extreme.
    collapsed: List[tuple] = []
    for idx, kind in swings:
        if collapsed and collapsed[-1][1] == kind:
            prev_idx, _ = collapsed[-1]
            if kind == "L":
                if close.loc[idx] < close.loc[prev_idx]:
                    collapsed[-1] = (idx, kind)
            else:
                if close.loc[idx] > close.loc[prev_idx]:
                    collapsed[-1] = (idx, kind)
        else:
            collapsed.append((idx, kind))

    durations = []
    for (idx1, kind1), (idx2, kind2) in zip(collapsed, collapsed[1:]):
        if kind1 == "L" and kind2 == "H":
            days = (idx2 - idx1).days
            if days > 20:
                durations.append(days)

    if not durations:
        return None
    return float(np.mean(durations)) / AVG_DAYS_PER_MONTH


def growth_implied_months(
    current_price: float, target_price: float, annual_growth_rate: Optional[float]
) -> Optional[float]:
    """Months of compounding at `annual_growth_rate` to go from current_price
    to target_price. Returns 0 if the target is already at/below current price.
    """
    if target_price <= current_price:
        return 0.0
    if annual_growth_rate is None:
        return None
    g = max(annual_growth_rate, MIN_ANNUAL_GROWTH_FLOOR)
    years = np.log(target_price / current_price) / np.log(1 + g)
    return max(years, 0.0) * 12


def project_timeframe(
    hist: pd.DataFrame,
    fundamentals: Fundamentals,
    peak: PeakProjection,
    bottom: BottomAssessment,
    quarterly_estimates: Optional[pd.DataFrame] = None,
) -> TimeframeProjection:
    estimates: List[TimeframeEstimate] = []

    hist_months = historical_cycle_months(hist)
    if hist_months is not None:
        estimates.append(
            TimeframeEstimate(
                "historical_bottom_to_peak_cycles",
                hist_months,
                f"Average duration of past bottom -> peak swings in "
                f"{fundamentals.symbol}'s own price history",
            )
        )

    growth = fundamentals.earnings_growth or fundamentals.revenue_growth
    growth_months = growth_implied_months(peak.current_price, peak.blended_target, growth)
    if growth_months is not None:
        g_display = growth if growth is not None else MIN_ANNUAL_GROWTH_FLOOR
        estimates.append(
            TimeframeEstimate(
                "fundamentals_growth_implied",
                growth_months,
                f"Time to compound at ~{g_display:.1%}/yr fundamental growth from "
                f"{peak.current_price:.2f} to {peak.blended_target:.2f}",
            )
        )

    if quarterly_estimates is not None:
        reversion_pe = _reversion_multiple(fundamentals)
        crossing_months = analyst_estimate_crossing_months(
            quarterly_estimates, reversion_pe, peak.blended_target, bottom.as_of
        )
        if crossing_months is not None:
            estimates.append(
                TimeframeEstimate(
                    "analyst_estimate_crossing",
                    crossing_months,
                    f"First future quarter whose consensus TTM EPS x {reversion_pe:.1f} "
                    f"reversion P/E reaches {peak.blended_target:.2f}",
                )
            )

    valid = [e.months for e in estimates if e.months is not None]
    blended = float(np.median(valid)) if valid else DEFAULT_FALLBACK_MONTHS
    target_date = bottom.as_of + pd.DateOffset(months=int(round(blended)))

    return TimeframeProjection(
        symbol=fundamentals.symbol,
        estimates=estimates,
        blended_months=blended,
        target_date=target_date,
    )
