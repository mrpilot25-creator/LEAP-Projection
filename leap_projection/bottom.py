"""Technical confirmation of an established price bottom.

No single signal is trusted in isolation. A bottom is only "confirmed" once
several independent signals line up: a real prior drawdown, a bounce off the
low, a reclaimed short-term moving average or oversold RSI recovery, and an
emerging higher-low pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd


@dataclass
class BottomSignal:
    name: str
    confirmed: bool
    detail: str


@dataclass
class BottomAssessment:
    symbol: str
    as_of: pd.Timestamp
    bottom_price: float
    bottom_date: pd.Timestamp
    current_price: float
    fifty_two_wk_high: float
    drawdown_from_high: float
    recovery_from_low: float
    score: float  # fraction of signals confirmed, 0-1
    confirmed: bool
    signals: List[BottomSignal] = field(default_factory=list)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def find_swing_lows(close: pd.Series, order: int = 5) -> pd.Series:
    """Return the subset of `close` that are local minima over a +/-order window."""
    values = close.to_numpy()
    idx = []
    for i in range(order, len(values) - order):
        window = values[i - order : i + order + 1]
        if values[i] == window.min() and np.sum(window == values[i]) == 1:
            idx.append(i)
    return close.iloc[idx]


def assess_bottom(
    hist: pd.DataFrame,
    lookback_days: int = 252,
    min_drawdown: float = 0.15,
    min_recovery: float = 0.05,
) -> BottomAssessment:
    """Assess whether `hist` (a price DataFrame with a 'Close' column) shows a
    confirmed bottom within the trailing `lookback_days` window.
    """
    close = hist["Close"].dropna()
    if len(close) < 30:
        raise ValueError("Need at least 30 price bars to assess a bottom.")

    sma20 = close.rolling(20).mean()
    rsi = _rsi(close, 14)

    window = close.tail(min(lookback_days, len(close)))
    # Standard max-drawdown calc: the peak must chronologically precede the
    # trough, otherwise a steady uptrend's start-of-window low would get
    # misread as a "bottom" relative to today's (unrelated) high.
    running_max = window.cummax()
    drawdown_series = (running_max - window) / running_max
    bottom_date = drawdown_series.idxmax()
    bottom_price = float(window.loc[bottom_date])
    fifty_two_wk_high = float(running_max.loc[bottom_date])
    current_date = close.index[-1]
    current_price = float(close.iloc[-1])

    drawdown = float(drawdown_series.loc[bottom_date])
    recovery = (current_price - bottom_price) / bottom_price if bottom_price else 0.0

    signals: List[BottomSignal] = []

    sig_drawdown = drawdown >= min_drawdown
    signals.append(
        BottomSignal(
            "meaningful_drawdown",
            sig_drawdown,
            f"Drawdown from the {lookback_days}-day high is {drawdown:.1%} "
            f"(threshold {min_drawdown:.0%})",
        )
    )

    sig_recovery = recovery >= min_recovery
    signals.append(
        BottomSignal(
            "bounce_off_low",
            sig_recovery,
            f"Price is {recovery:.1%} above the low of {bottom_price:.2f} "
            f"set on {bottom_date.date()}",
        )
    )

    sma20_now = sma20.iloc[-1]
    sig_sma = bool(not np.isnan(sma20_now) and current_price > sma20_now)
    signals.append(
        BottomSignal(
            "reclaimed_sma20",
            sig_sma,
            f"Price is {'above' if sig_sma else 'below'} the 20-day SMA "
            f"({sma20_now:.2f})" if not np.isnan(sma20_now) else "Not enough data for SMA20",
        )
    )

    recent_rsi = rsi.tail(20)
    was_oversold = bool((recent_rsi < 35).any())
    sig_rsi = was_oversold and rsi.iloc[-1] > 40
    signals.append(
        BottomSignal(
            "rsi_recovery",
            sig_rsi,
            f"RSI(14) is now {rsi.iloc[-1]:.1f}; "
            f"{'was' if was_oversold else 'was not'} oversold (<35) in the last 20 sessions",
        )
    )

    swings = find_swing_lows(close.tail(120), order=5)
    sig_higher_low = len(swings) >= 2 and swings.iloc[-1] > swings.iloc[-2]
    signals.append(
        BottomSignal(
            "higher_low_pattern",
            bool(sig_higher_low),
            "A higher-low pattern is forming"
            if sig_higher_low
            else "No confirmed higher-low pattern yet",
        )
    )

    score = sum(s.confirmed for s in signals) / len(signals)
    confirmed = sig_drawdown and sig_recovery and (sig_sma or sig_rsi) and score >= 0.6

    return BottomAssessment(
        symbol="",
        as_of=current_date,
        bottom_price=bottom_price,
        bottom_date=bottom_date,
        current_price=current_price,
        fifty_two_wk_high=fifty_two_wk_high,
        drawdown_from_high=drawdown,
        recovery_from_low=recovery,
        score=score,
        confirmed=confirmed,
        signals=signals,
    )
