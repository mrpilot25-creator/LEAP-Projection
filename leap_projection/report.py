"""Ties data, bottom detection, valuation, and timeframe estimation together
into a single report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from .bottom import BottomAssessment, assess_bottom
from .data import Fundamentals, fetch_fundamentals, fetch_price_history
from .stockanalysis_xlsx import enrich_fundamentals
from .timeframe import TimeframeProjection, project_timeframe
from .valuation import PeakProjection, project_peak


@dataclass
class ProjectionReport:
    symbol: str
    as_of: pd.Timestamp
    fundamentals: Fundamentals
    bottom: BottomAssessment
    peak: PeakProjection
    timeframe: TimeframeProjection

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": str(self.as_of.date()),
            "bottom": {
                "confirmed": self.bottom.confirmed,
                "confidence_score": round(self.bottom.score, 2),
                "bottom_price": round(self.bottom.bottom_price, 2),
                "bottom_date": str(self.bottom.bottom_date.date()),
                "current_price": round(self.bottom.current_price, 2),
                "drawdown_from_high": round(self.bottom.drawdown_from_high, 4),
                "recovery_from_low": round(self.bottom.recovery_from_low, 4),
                "signals": [
                    {"name": s.name, "confirmed": s.confirmed, "detail": s.detail}
                    for s in self.bottom.signals
                ],
                "fundamental_gate": (
                    {
                        "name": self.bottom.fundamental_gate.name,
                        "confirmed": self.bottom.fundamental_gate.confirmed,
                        "detail": self.bottom.fundamental_gate.detail,
                    }
                    if self.bottom.fundamental_gate
                    else None
                ),
            },
            "peak": {
                "blended_target": round(self.peak.blended_target, 2),
                "low_target": round(self.peak.low_target, 2),
                "high_target": round(self.peak.high_target, 2),
                "upside_pct": round(self.peak.upside_pct, 4),
                "estimates": [
                    {
                        "method": e.method,
                        "target_price": round(e.target_price, 2) if e.target_price else None,
                        "detail": e.detail,
                    }
                    for e in self.peak.estimates
                ],
            },
            "timeframe": {
                "blended_months": round(self.timeframe.blended_months, 1),
                "target_date": str(self.timeframe.target_date.date()),
                "estimates": [
                    {
                        "method": e.method,
                        "months": round(e.months, 1) if e.months is not None else None,
                        "detail": e.detail,
                    }
                    for e in self.timeframe.estimates
                ],
            },
        }

    def summary(self) -> str:
        lines = []
        lines.append(f"=== LEAP Projection: {self.symbol} (as of {self.as_of.date()}) ===")
        lines.append("")

        b = self.bottom
        status = "CONFIRMED" if b.confirmed else "NOT YET CONFIRMED"
        lines.append(f"Bottom status: {status}  (confidence {b.score:.0%})")
        lines.append(
            f"  Low: {b.bottom_price:.2f} on {b.bottom_date.date()}  |  "
            f"Current: {b.current_price:.2f}  |  "
            f"Drawdown from high: {b.drawdown_from_high:.1%}  |  "
            f"Off the low: {b.recovery_from_low:.1%}"
        )
        for s in b.signals:
            mark = "x" if s.confirmed else " "
            lines.append(f"    [{mark}] {s.detail}")
        if b.fundamental_gate:
            mark = "x" if b.fundamental_gate.confirmed else " "
            lines.append(f"    [{mark}] {b.fundamental_gate.detail}  (fundamental gate)")
        lines.append("")

        if not b.confirmed:
            lines.append(
                "NOTE: a bottom has not been fully confirmed yet. The peak/timeframe "
                "projections below are still computed for reference, but treat them as "
                "provisional until more signals line up."
            )
            lines.append("")

        p = self.peak
        lines.append(
            f"Projected peak target: {p.blended_target:.2f} "
            f"(range {p.low_target:.2f} - {p.high_target:.2f}, "
            f"{p.upside_pct:+.1%} from {p.current_price:.2f})"
        )
        for e in p.estimates:
            tp = f"{e.target_price:.2f}" if e.target_price else "n/a"
            lines.append(f"    - {e.method}: {tp}  ({e.detail})")
        lines.append("")

        t = self.timeframe
        lines.append(
            f"Projected timeframe to peak: ~{t.blended_months:.1f} months "
            f"(target date ~{t.target_date.date()})"
        )
        for e in t.estimates:
            m = f"{e.months:.1f} mo" if e.months is not None else "n/a"
            lines.append(f"    - {e.method}: {m}  ({e.detail})")
        lines.append("")
        lines.append(
            "Disclaimer: informational/educational only, not investment advice. "
            "Fundamental and technical signals can fail; size positions accordingly."
        )
        return "\n".join(lines)


def build_report(
    symbol: str,
    hist: pd.DataFrame,
    fundamentals: Fundamentals,
    eps_growth_threshold: Optional[float] = None,
) -> ProjectionReport:
    bottom = assess_bottom(hist, fundamentals=fundamentals, eps_growth_threshold=eps_growth_threshold)
    bottom.symbol = fundamentals.symbol
    peak = project_peak(fundamentals, hist)
    timeframe = project_timeframe(hist, fundamentals, peak, bottom)
    return ProjectionReport(
        symbol=fundamentals.symbol,
        as_of=bottom.as_of,
        fundamentals=fundamentals,
        bottom=bottom,
        peak=peak,
        timeframe=timeframe,
    )


def run(
    symbol: str,
    years: int = 3,
    eps_growth_threshold: Optional[float] = None,
    stockanalysis_xlsx: Optional[str] = None,
) -> ProjectionReport:
    """Convenience end-to-end entry point: fetch data and build the report.

    `stockanalysis_xlsx`, if given, is the path to a stockanalysis.com
    financials export used to enrich the FMP fundamentals with a
    multi-year historical P/E reversion multiple and longer-run growth
    rates (see leap_projection/stockanalysis_xlsx.py).
    """
    hist = fetch_price_history(symbol, years=years)
    fundamentals = fetch_fundamentals(symbol)
    if stockanalysis_xlsx:
        fundamentals = enrich_fundamentals(fundamentals, stockanalysis_xlsx)
    return build_report(symbol, hist, fundamentals, eps_growth_threshold=eps_growth_threshold)
