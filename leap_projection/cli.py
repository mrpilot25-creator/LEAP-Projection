"""Command-line entry point.

Usage:
    python -m leap_projection.cli AAPL
    python -m leap_projection.cli AAPL --years 5 --json
    python -m leap_projection.cli AAPL --eps-growth-threshold 0.15

Requires the FMP_API_KEY environment variable (see README).
"""

from __future__ import annotations

import argparse
import json
import sys

from .data import FMPError
from .report import run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="leap-projection",
        description=(
            "Fundamentals-driven bottom -> peak stock projection, for LEAP "
            "option planning. Not investment advice."
        ),
    )
    parser.add_argument("symbol", help="Ticker symbol, e.g. AAPL")
    parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years of price history to analyze (default 3)",
    )
    parser.add_argument(
        "--eps-growth-threshold",
        type=float,
        default=None,
        help=(
            "Optional fundamental gate: only confirm a bottom if trailing YoY "
            "EPS growth is also >= this fraction (e.g. 0.15 for 15%%). Off by default."
        ),
    )
    parser.add_argument(
        "--stockanalysis-xlsx",
        default=None,
        help=(
            "Optional path to a stockanalysis.com financials export (.xlsx) to enrich "
            "the peak valuation with a multi-year historical P/E multiple and longer-run "
            "growth rates."
        ),
    )
    parser.add_argument(
        "--estimates-file",
        default=None,
        help=(
            "Optional path to a text file containing a copy-pasted stockanalysis.com "
            "quarterly analyst-estimates table, used for a real consensus forward EPS "
            "and an analyst-grounded timeframe estimate."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        report = run(
            args.symbol,
            years=args.years,
            eps_growth_threshold=args.eps_growth_threshold,
            stockanalysis_xlsx=args.stockanalysis_xlsx,
            estimates_file=args.estimates_file,
        )
    except (ValueError, FMPError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
