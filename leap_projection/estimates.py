"""Parser for stockanalysis.com's quarterly analyst-estimates table.

stockanalysis.com's forward-estimates page isn't downloadable, but its
table can be copy-pasted as plain text. A paste typically looks like:

    Fiscal Quarter	Q2 2025	Q3 2025	...
    Period Ending	Jun 30, 2025	Sep 30, 2025	...
    Revenue
    11.08B	11.51B	...
    Revenue Growth
    15.90%	17.16%	...
    ...
    EPS
    0.72	0.59	...

Each metric's row label sometimes lands on its own line with the
tab-separated values on the next line (an artifact of copying a table
whose row-label cell doesn't align with its data cells in plain text) --
the parser accepts that shape, or "label\\tv1\\tv2..." on a single line.

Quarters with no analyst count ("No. Analysts" == "-") are already-reported
actuals; the rest are forward consensus estimates. This is genuinely
forward-looking, unlike the CAGR-derived proxies used when only FMP/xlsx
history is available -- it's used both to set a real consensus forward EPS
and to find which future quarter first justifies the projected peak price.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pandas as pd

from .data import Fundamentals, _cagr, _clip_growth

_SUFFIX_MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

_METRIC_COLUMN_MAP = {
    "Revenue": "revenue",
    "Revenue Growth": "revenue_growth",
    "Gross Profit": "gross_profit",
    "Gross Margin": "gross_margin",
    "Operating Income": "operating_income",
    "Net Income": "net_income",
    "EPS": "eps",
    "EPS Growth": "eps_growth",
    "Free Cash Flow": "free_cash_flow",
    "No. Analysts": "num_analysts",
}

AVG_DAYS_PER_MONTH = 30.44


def _parse_value(raw: str) -> Optional[float]:
    raw = raw.strip()
    if raw in ("", "-", "—", "N/A", "NM"):
        return None
    is_pct = raw.endswith("%")
    if is_pct:
        raw = raw[:-1]
    suffix = raw[-1].upper() if raw and raw[-1].upper() in _SUFFIX_MULTIPLIERS else None
    if suffix:
        raw = raw[:-1]
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        value *= _SUFFIX_MULTIPLIERS[suffix]
    if is_pct:
        value /= 100.0
    return value


def parse_stockanalysis_estimates_text(text: str) -> pd.DataFrame:
    """Parse a copy-pasted stockanalysis.com quarterly-estimates table into
    a DataFrame indexed by period-ending date (ascending)."""
    lines = [ln for ln in text.strip("\n").split("\n") if ln.strip() != ""]
    if len(lines) < 3:
        raise ValueError("Not enough lines to parse a quarterly-estimates table.")

    header_fields = lines[0].split("\t")
    if header_fields[0].strip() != "Fiscal Quarter":
        raise ValueError("Expected the first line to start with 'Fiscal Quarter'.")
    quarters = [f.strip() for f in header_fields[1:]]

    period_fields = lines[1].split("\t")
    if period_fields[0].strip() != "Period Ending":
        raise ValueError("Expected the second line to start with 'Period Ending'.")
    period_ends = [pd.Timestamp(f.strip()) for f in period_fields[1:]]

    n = len(period_ends)
    if len(quarters) != n:
        raise ValueError("'Fiscal Quarter' and 'Period Ending' rows have different lengths.")

    data = {}
    i = 2
    while i < len(lines):
        fields = lines[i].split("\t")
        label = fields[0].strip()
        column = _METRIC_COLUMN_MAP.get(label)
        if column is None:
            i += 1
            continue

        if len(fields) - 1 == n:
            values = fields[1:]
            i += 1
        elif i + 1 < len(lines) and len(lines[i + 1].split("\t")) == n:
            values = lines[i + 1].split("\t")
            i += 2
        else:
            i += 1
            continue

        data[column] = [_parse_value(v) for v in values]

    if "eps" not in data:
        raise ValueError("Couldn't find a parseable 'EPS' row in the pasted table.")

    df = pd.DataFrame(data, index=pd.DatetimeIndex(period_ends, name="period_ending"))
    df.insert(0, "fiscal_quarter", quarters)
    return df.sort_index()


def load_stockanalysis_estimates(path: str) -> pd.DataFrame:
    """Load a quarterly-estimates paste that was saved to a text file."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_stockanalysis_estimates_text(text)


def ttm_eps_as_of(estimates: pd.DataFrame, quarter_end: pd.Timestamp) -> Optional[float]:
    """Trailing-twelve-months EPS: sum of the 4 quarters ending at or
    before `quarter_end`. None if fewer than 4 are available or any is
    missing."""
    window = estimates.loc[:quarter_end].tail(4)
    if len(window) < 4 or window["eps"].isna().any():
        return None
    return float(window["eps"].sum())


def next_twelve_months_eps(estimates: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
    """Consensus next-twelve-months EPS: sum of the next 4 quarters
    (period-ending strictly after `as_of`). None if fewer than 4 are
    available or any is missing."""
    upcoming = estimates[estimates.index > as_of].head(4)
    if len(upcoming) < 4 or upcoming["eps"].isna().any():
        return None
    return float(upcoming["eps"].sum())


def enrich_fundamentals_with_estimates(
    fundamentals: Fundamentals,
    estimates: pd.DataFrame,
    as_of: Optional[pd.Timestamp] = None,
) -> Fundamentals:
    """Return a copy of `fundamentals` with `forward_eps`/`earnings_growth`
    (and the `peg_ratio` derived from them) replaced by real consensus
    next-twelve-months figures, when the estimates table has enough
    coverage -- falling back to the original values otherwise."""
    as_of = as_of or pd.Timestamp.today().normalize()

    ntm_eps = next_twelve_months_eps(estimates, as_of)
    last_actual = estimates.index[estimates.index <= as_of]
    ttm_eps = ttm_eps_as_of(estimates, last_actual.max()) if len(last_actual) else None

    forward_eps = ntm_eps if ntm_eps is not None else fundamentals.forward_eps
    earnings_growth = (
        _clip_growth(_cagr(ttm_eps, ntm_eps, 1))
        if ntm_eps is not None and ttm_eps is not None
        else fundamentals.earnings_growth
    )
    peg_ratio = (
        fundamentals.trailing_pe / (earnings_growth * 100)
        if fundamentals.trailing_pe and earnings_growth and earnings_growth > 0
        else fundamentals.peg_ratio
    )

    return replace(
        fundamentals,
        forward_eps=forward_eps,
        earnings_growth=earnings_growth,
        peg_ratio=peg_ratio,
    )


def analyst_estimate_crossing_months(
    estimates: pd.DataFrame,
    reversion_pe: Optional[float],
    target_price: float,
    as_of: pd.Timestamp,
) -> Optional[float]:
    """Months from `as_of` to the first future quarter whose trailing-twelve-
    month consensus EPS, at `reversion_pe`, projects a price >= `target_price`.

    None if there's no usable reversion multiple, or no future quarter in
    the estimates table ever crosses the target.
    """
    if not reversion_pe or reversion_pe <= 0:
        return None

    for quarter_end in estimates.index[estimates.index > as_of]:
        ttm = ttm_eps_as_of(estimates, quarter_end)
        if ttm is None:
            continue
        projected_price = ttm * reversion_pe
        if projected_price >= target_price:
            return (quarter_end - as_of).days / AVG_DAYS_PER_MONTH
    return None
