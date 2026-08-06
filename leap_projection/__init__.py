"""LEAP-Projection: fundamentals-driven bottom -> peak stock projection.

Given a ticker, this package:
  1. Pulls recent price history and current fundamental data.
  2. Assesses whether a price bottom has been established (technical confirmation).
  3. Projects a fundamentals-based peak price target.
  4. Estimates the timeframe to reach that peak.

Intended as a screening aid for long-dated (LEAP) options planning, not
investment advice.
"""

from .report import ProjectionReport, build_report

__all__ = ["ProjectionReport", "build_report"]
