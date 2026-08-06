"""Technical bottom-detection checklist.

Ported from the validated research in the companion `bottom-backtest`
repo (QuantConnect-validated parameters, confirmed via a 21-ticker sweep
and an 8-ticker leave-one-out cross-validation on momentum/growth names).
Six independent signals are computed on each bar; a bottom is confirmed
when at least `MIN_SIGNALS` of them have fired within a recent window.

At the validated "Score >= 2" fixed rule (trend_lookback=40, bb_pctile=0.10,
stoch_threshold=20, hvn_tolerance=0.02, min_signals=2), the out-of-sample
backtest across NFLX/AAPL/MSFT/AMZN/TSLA/GOOGL/META/NVDA measured
~64.28% precision / ~78.36% recall against a 40-day-forward, 10%-rally,
<=1%-drawdown "true bottom" label. No single signal is trusted alone.

Signals:
  1. macd_cross         - MACD(12,26,9) histogram crosses up through zero
  2. bb_squeeze_release  - price breaks above the upper Bollinger Band
                           after a prior low-volatility squeeze
  3. trend_break         - price closes above a downward-sloping linear
                           trend line fit over the trailing window
                           (catches a downtrend reversing)
  4. cmf_cross           - Chaikin Money Flow crosses up through zero
  5. stoch_rsi_recover   - Stochastic RSI recovers up through an
                           oversold threshold
  6. hvn_hold            - price is holding near a high-volume node
                           (a volume-profile support/resistance level)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .data import Fundamentals

# Fixed, validated parameters (see bottom-backtest/leave_one_out.py:
# FIXED_RULE_COMBO). Not re-tuned per stock.
TREND_LOOKBACK = 40
BB_SQUEEZE_PERCENTILE = 0.10
BB_SQUEEZE_LOOKBACK = 120
STOCH_RSI_THRESHOLD = 20
HVN_TOLERANCE = 0.02
HVN_LOOKBACK = 60
HVN_BINS = 20
CMF_WINDOW = 20
MIN_SIGNALS = 2

# How many recent trading days to scan for a checklist "fire". This is a
# live-use analogue of the backtest's +/-10-day matching tolerance window.
RECENT_FIRE_WINDOW = 15

MIN_BARS = BB_SQUEEZE_LOOKBACK + 30

SIGNAL_NAMES = [
    "macd_cross",
    "bb_squeeze_release",
    "trend_break",
    "cmf_cross",
    "stoch_rsi_recover",
    "hvn_hold",
]

_SIGNAL_LABELS = {
    "macd_cross": "MACD(12,26,9) histogram crossed up through zero",
    "bb_squeeze_release": "Price broke above the upper Bollinger Band after a volatility squeeze",
    "trend_break": f"Price closed above its {TREND_LOOKBACK}-day downtrend line",
    "cmf_cross": f"Chaikin Money Flow({CMF_WINDOW}) crossed up through zero",
    "stoch_rsi_recover": f"Stochastic RSI recovered above {STOCH_RSI_THRESHOLD}",
    "hvn_hold": "Price is holding near a high-volume support node",
}


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
    score: float  # fraction of the 6 checklist signals fired on bottom_date
    confirmed: bool
    signals: List[BottomSignal] = field(default_factory=list)
    fundamental_gate: Optional[BottomSignal] = None


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def _macd_cross(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = fast - slow
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd_line - macd_signal
    return (macd_hist.shift(1) <= 0) & (macd_hist > 0)


def _bollinger(close: pd.Series) -> tuple:
    mid = close.rolling(20, min_periods=20).mean()
    std = close.rolling(20, min_periods=20).std(ddof=0)
    upper = mid + 2 * std
    bandwidth = (upper - (mid - 2 * std)) / mid
    return upper, bandwidth


def _bb_squeeze_release(close: pd.Series, upper: pd.Series, bandwidth: pd.Series) -> pd.Series:
    was_squeezed = (
        bandwidth.rolling(BB_SQUEEZE_LOOKBACK)
        .apply(lambda w: w[-1] <= np.quantile(w, BB_SQUEEZE_PERCENTILE), raw=True)
        .shift(1)
        .fillna(0)
        .astype(bool)
    )
    return was_squeezed & (close > upper)


def _trend_break(close: pd.Series, lookback: int = TREND_LOOKBACK) -> pd.Series:
    def slope_and_break(window: np.ndarray) -> float:
        x = np.arange(len(window))
        slope, intercept = np.polyfit(x, window, 1)
        projected = slope * (len(window) - 1) + intercept
        return 1.0 if (window[-1] > projected and slope < 0) else 0.0

    result = close.rolling(lookback).apply(slope_and_break, raw=True)
    return result.fillna(0).astype(bool)


def _chaikin_money_flow(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    price_range = (high - low).replace(0, np.nan)
    mf_multiplier = (((2 * close) - high - low) / price_range).fillna(0)
    return (
        (mf_multiplier * volume).rolling(CMF_WINDOW).sum()
        / volume.rolling(CMF_WINDOW).sum()
    )


def _cmf_cross(cmf: pd.Series) -> pd.Series:
    return (cmf.shift(1) < 0) & (cmf >= 0)


def _stoch_rsi(rsi: pd.Series) -> pd.Series:
    rsi_low = rsi.rolling(14).min()
    rsi_high = rsi.rolling(14).max()
    return 100 * (rsi - rsi_low) / (rsi_high - rsi_low)


def _stoch_rsi_recover(stoch_rsi: pd.Series, threshold: int = STOCH_RSI_THRESHOLD) -> pd.Series:
    return (stoch_rsi.shift(1) < threshold) & (stoch_rsi >= threshold)


def _hvn_distance(close: pd.Series, volume: pd.Series) -> pd.Series:
    close_vals = close.to_numpy()
    vol_vals = volume.to_numpy()
    distance = np.full(len(close), np.nan)
    for i in range(HVN_LOOKBACK - 1, len(close)):
        wc = close_vals[i - HVN_LOOKBACK + 1 : i + 1]
        wv = vol_vals[i - HVN_LOOKBACK + 1 : i + 1]
        hi, lo = wc.max(), wc.min()
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, HVN_BINS + 1)
        bin_vols = np.zeros(HVN_BINS)
        for price, vol in zip(wc, wv):
            b = min(max(np.searchsorted(edges, price, side="right") - 1, 0), HVN_BINS - 1)
            bin_vols[b] += vol
        best_bin = int(np.argmax(bin_vols))
        hvn_price = (edges[best_bin] + edges[best_bin + 1]) / 2
        distance[i] = abs(wc[-1] - hvn_price) / wc[-1]
    return pd.Series(distance, index=close.index)


def _hvn_hold(hvn_distance: pd.Series, tolerance: float = HVN_TOLERANCE) -> pd.Series:
    return hvn_distance <= tolerance


def find_swing_lows(close: pd.Series, order: int = 5) -> pd.Series:
    """Return the subset of `close` that are local minima over a +/-order window."""
    values = close.to_numpy()
    idx = []
    for i in range(order, len(values) - order):
        window = values[i - order : i + order + 1]
        if values[i] == window.min() and np.sum(window == values[i]) == 1:
            idx.append(i)
    return close.iloc[idx]


def compute_signals(hist: pd.DataFrame) -> pd.DataFrame:
    """Compute all 6 checklist signals as boolean columns aligned to `hist`'s index."""
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    rsi = _rsi(close)
    upper, bandwidth = _bollinger(close)
    cmf = _chaikin_money_flow(high, low, close, volume)
    stoch_rsi = _stoch_rsi(rsi)
    hvn_distance = _hvn_distance(close, volume)

    return pd.DataFrame(
        {
            "macd_cross": _macd_cross(close),
            "bb_squeeze_release": _bb_squeeze_release(close, upper, bandwidth),
            "trend_break": _trend_break(close),
            "cmf_cross": _cmf_cross(cmf),
            "stoch_rsi_recover": _stoch_rsi_recover(stoch_rsi),
            "hvn_hold": _hvn_hold(hvn_distance),
        }
    ).fillna(False)


def assess_bottom(
    hist: pd.DataFrame,
    min_signals: int = MIN_SIGNALS,
    recent_fire_window: int = RECENT_FIRE_WINDOW,
    fundamentals: Optional[Fundamentals] = None,
    eps_growth_threshold: Optional[float] = None,
) -> BottomAssessment:
    """Assess whether the checklist has fired a confirmed bottom recently.

    `fundamentals` + `eps_growth_threshold` optionally layer on the
    backtest's fundamental pre-filter: a checklist fire only counts as
    confirmed if trailing YoY EPS growth is also >= threshold (the
    combined screen tested best around 15%). Off by default.
    """
    close = hist["Close"].dropna()
    if len(close) < MIN_BARS:
        raise ValueError(
            f"Need at least {MIN_BARS} price bars to run the bottom checklist "
            f"(got {len(close)})."
        )

    signals_df = compute_signals(hist).reindex(close.index).fillna(False)
    score = signals_df.sum(axis=1)
    fired = score >= min_signals

    current_price = float(close.iloc[-1])
    current_date = close.index[-1]

    recent = fired.tail(recent_fire_window)
    technical_confirmed = bool(recent.any())
    if technical_confirmed:
        bottom_date = recent[recent].index[-1]
    else:
        bottom_date = current_date

    bottom_price = float(close.loc[bottom_date])
    fired_score = int(score.loc[bottom_date])
    signal_row = signals_df.loc[bottom_date]
    signals = [
        BottomSignal(name, bool(signal_row[name]), _SIGNAL_LABELS[name])
        for name in SIGNAL_NAMES
    ]

    confirmed = technical_confirmed
    fundamental_gate = None
    if eps_growth_threshold is not None:
        eps_growth = fundamentals.eps_growth_yoy if fundamentals else None
        passed = eps_growth is not None and eps_growth >= eps_growth_threshold
        fundamental_gate = BottomSignal(
            "eps_growth_gate",
            passed,
            f"Trailing YoY EPS growth "
            f"{f'{eps_growth:.1%}' if eps_growth is not None else 'unavailable'} "
            f">= {eps_growth_threshold:.0%} threshold",
        )
        confirmed = confirmed and passed

    pre_bottom = close.loc[:bottom_date]
    running_max = pre_bottom.cummax()
    fifty_two_wk_high = float(running_max.iloc[-1])
    drawdown_from_high = (
        (fifty_two_wk_high - bottom_price) / fifty_two_wk_high if fifty_two_wk_high else 0.0
    )
    recovery_from_low = (current_price - bottom_price) / bottom_price if bottom_price else 0.0

    return BottomAssessment(
        symbol="",
        as_of=current_date,
        bottom_price=bottom_price,
        bottom_date=bottom_date,
        current_price=current_price,
        fifty_two_wk_high=fifty_two_wk_high,
        drawdown_from_high=drawdown_from_high,
        recovery_from_low=recovery_from_low,
        score=fired_score / len(SIGNAL_NAMES),
        confirmed=confirmed,
        signals=signals,
        fundamental_gate=fundamental_gate,
    )
