"""Command-line entry point.

Usage:
    python -m leap_projection.cli AAPL
    python -m leap_projection.cli AAPL --period 3y --json
"""

from __future__ import annotations

import argparse
import json
import sys

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
        "--period",
        default="5y",
        help="Price history window to analyze (yfinance period string, default 5y)",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        report = run(args.symbol, period=args.period)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
