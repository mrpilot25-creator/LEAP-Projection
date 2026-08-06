"""Fundamentals-based peak price projection.

Several independent valuation methods are computed and then blended
(median) into a single target, with the individual estimates kept around so
the caller can see the spread and judge confidence.

Methods:
  * forward_pe_reversion  - forward EPS x a "normal" multiple for the stock
  * peg_one               - forward EPS x growth-implied fair P/E (PEG = 1)
  * analyst_consensus     - sell-side mean 12-month price target
  * prior_high_extension  - prior cycle high grown forward by the current
                             fundamental growth rate

Limitation: `forward_pe_reversion` proxies the stock's "normal" multiple
with its current trailing/forward P/E rather than a true multi-year
historical average, since a clean historical EPS series isn't available
from the free data source. Treat it as a floor/ceiling anchor, not gospel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .data import Fundamentals

MAX_GROWTH_IMPLIED_PE = 60.0  # sanity cap so hyper-growth quarters don't blow up PEG=1


@dataclass
class ValuationEstimate:
    method: str
    target_price: Optional[float]
    detail: str


@dataclass
class PeakProjection:
    symbol: str
    current_price: float
    estimates: List[ValuationEstimate]
    blended_target: float
    low_target: float
    high_target: float

    @property
    def upside_pct(self) -> float:
        if not self.current_price:
            return 0.0
        return (self.blended_target - self.current_price) / self.current_price


def _reversion_multiple(fundamentals: Fundamentals) -> Optional[float]:
    candidates = [p for p in (fundamentals.trailing_pe, fundamentals.forward_pe) if p and p > 0]
    if not candidates:
        return None
    return float(max(candidates))


def project_peak(fundamentals: Fundamentals, hist: pd.DataFrame) -> PeakProjection:
    close = hist["Close"].dropna()
    current_price = fundamentals.current_price or float(close.iloc[-1])
    estimates: List[ValuationEstimate] = []

    reversion_pe = _reversion_multiple(fundamentals)
    if fundamentals.forward_eps and reversion_pe:
        target = fundamentals.forward_eps * reversion_pe
        estimates.append(
            ValuationEstimate(
                "forward_pe_reversion",
                target,
                f"Forward EPS {fundamentals.forward_eps:.2f} x reversion P/E {reversion_pe:.1f}",
            )
        )

    growth = fundamentals.earnings_growth
    if fundamentals.forward_eps and growth is not None and growth > 0:
        fair_pe = min(growth * 100, MAX_GROWTH_IMPLIED_PE)
        target = fundamentals.forward_eps * fair_pe
        estimates.append(
            ValuationEstimate(
                "peg_one",
                target,
                f"Forward EPS {fundamentals.forward_eps:.2f} x growth-implied P/E "
                f"{fair_pe:.1f} (PEG=1, growth {growth:.1%})",
            )
        )

    if fundamentals.analyst_target_mean:
        estimates.append(
            ValuationEstimate(
                "analyst_consensus",
                float(fundamentals.analyst_target_mean),
                "Sell-side mean 12-month price target",
            )
        )

    prior_high = float(close.max())
    extension_growth = fundamentals.revenue_growth or fundamentals.earnings_growth
    if extension_growth is not None:
        g = max(extension_growth, 0.0)
        target = prior_high * (1 + g)
        estimates.append(
            ValuationEstimate(
                "prior_high_extension",
                target,
                f"Prior cycle high {prior_high:.2f} extended by {g:.1%} fundamental growth",
            )
        )

    valid = [e.target_price for e in estimates if e.target_price and e.target_price > 0]
    if not valid:
        raise ValueError(
            f"Insufficient fundamental data to project a peak target for {fundamentals.symbol}."
        )

    blended = float(np.median(valid))
    return PeakProjection(
        symbol=fundamentals.symbol,
        current_price=current_price,
        estimates=estimates,
        blended_target=blended,
        low_target=float(min(valid)),
        high_target=float(max(valid)),
    )
