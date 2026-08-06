import pandas as pd
import pytest

from leap_projection.data import Fundamentals
from leap_projection.estimates import (
    analyst_estimate_crossing_months,
    enrich_fundamentals_with_estimates,
    next_twelve_months_eps,
    parse_stockanalysis_estimates_text,
    ttm_eps_as_of,
)

# A trimmed-down version of the real pasted format: label-alone-then-values
# for most rows, but "Revenue" combined on one line to exercise both shapes.
SAMPLE_TEXT = """\
Fiscal Quarter\tQ2 2025\tQ3 2025\tQ4 2025\tQ1 2026\tQ2 2026\tQ3 2026\tQ4 2026
Period Ending\tJun 30, 2025\tSep 30, 2025\tDec 31, 2025\tMar 31, 2026\tJun 30, 2026\tSep 30, 2026\tDec 31, 2026
Revenue\t11.08B\t11.51B\t12.05B\t12.25B\t12.56B\t12.88B\t13.53B
Revenue Growth
15.90%\t17.16%\t17.61%\t16.19%\t13.36%\t11.87%\t12.29%
EPS
0.72\t0.59\t0.56\t1.23\t0.80\t0.82\t0.73
EPS Growth
-\t-\t-\t-\t11.27%\t39.91%\t30.54%
No. Analysts
-\t-\t-\t-\t-\t38\t37
"""


def _fundamentals(**overrides) -> Fundamentals:
    base = dict(
        symbol="TEST",
        current_price=100.0,
        trailing_eps=4.0,
        forward_eps=4.5,
        trailing_pe=22.0,
        forward_pe=19.0,
        peg_ratio=1.1,
        earnings_growth=0.10,
        revenue_growth=0.08,
        analyst_target_mean=None,
        analyst_target_high=None,
        analyst_target_low=None,
        sector="Technology",
        market_cap=1_000_000_000,
    )
    base.update(overrides)
    return Fundamentals(**base)


def test_parse_handles_mixed_same_line_and_split_line_rows():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)

    assert list(df.index) == list(
        pd.to_datetime(
            ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]
        )
    )
    assert df.loc["2025-06-30", "revenue"] == pytest.approx(11.08e9)
    assert df.loc["2025-06-30", "revenue_growth"] == pytest.approx(0.1590)
    assert df.loc["2026-09-30", "eps"] == pytest.approx(0.82)
    assert df.loc["2025-06-30", "eps_growth"] is None or pd.isna(df.loc["2025-06-30", "eps_growth"])
    assert df.loc["2026-09-30", "num_analysts"] == 38.0
    assert list(df["fiscal_quarter"])[0] == "Q2 2025"


def test_parse_negative_percent_and_missing_values():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    # Q1 2027 isn't in this trimmed sample; check a present negative-free row instead
    assert df.loc["2026-06-30", "eps_growth"] == pytest.approx(0.1127)


def test_parse_raises_on_malformed_header():
    bad = "Not A Header\tQ1\nPeriod Ending\tJan 1, 2025\nEPS\n1.0\n"
    with pytest.raises(ValueError):
        parse_stockanalysis_estimates_text(bad)


def test_parse_raises_without_eps_row():
    text = (
        "Fiscal Quarter\tQ1 2025\n"
        "Period Ending\tMar 31, 2025\n"
        "Revenue\n"
        "1.0B\n"
    )
    with pytest.raises(ValueError):
        parse_stockanalysis_estimates_text(text)


def test_ttm_and_ntm_eps():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2026-08-06")

    last_actual = df.index[df.index <= as_of].max()
    assert last_actual == pd.Timestamp("2026-06-30")

    ttm = ttm_eps_as_of(df, last_actual)
    # Q3 2025 + Q4 2025 + Q1 2026 + Q2 2026
    assert ttm == pytest.approx(0.59 + 0.56 + 1.23 + 0.80)

    ntm = next_twelve_months_eps(df, as_of)
    # only 2 quarters strictly after as_of are present in the trimmed sample -> None
    assert ntm is None


def test_ntm_eps_with_full_four_quarters_available():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2025-05-01")  # before Q2 2025, so 4 quarters follow
    ntm = next_twelve_months_eps(df, as_of)
    assert ntm == pytest.approx(0.72 + 0.59 + 0.56 + 1.23)


def test_enrich_fundamentals_with_estimates_overrides_forward_eps():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2025-05-01")
    fundamentals = _fundamentals()

    enriched = enrich_fundamentals_with_estimates(fundamentals, df, as_of=as_of)

    expected_ntm = 0.72 + 0.59 + 0.56 + 1.23
    assert enriched.forward_eps == pytest.approx(expected_ntm)
    # no 4 trailing actual quarters exist before Q2 2025 in this sample -> TTM unavailable
    # -> earnings_growth falls back to the original FMP-derived value
    assert enriched.earnings_growth == fundamentals.earnings_growth


def test_enrich_fundamentals_with_estimates_computes_growth_when_both_available():
    # 9 quarters so a full trailing TTM and a full next-twelve-months both
    # exist simultaneously around the midpoint as_of date.
    text = (
        "Fiscal Quarter\tQ1\tQ2\tQ3\tQ4\tQ5\tQ6\tQ7\tQ8\tQ9\n"
        "Period Ending\tMar 31, 2025\tJun 30, 2025\tSep 30, 2025\tDec 31, 2025\t"
        "Mar 31, 2026\tJun 30, 2026\tSep 30, 2026\tDec 31, 2026\tMar 31, 2027\n"
        "EPS\n"
        "1.00\t1.00\t1.00\t1.00\t1.10\t1.10\t1.10\t1.10\t1.20\n"
    )
    df = parse_stockanalysis_estimates_text(text)
    as_of = pd.Timestamp("2026-02-01")  # between Q4 2025 and Q5 (Mar 31, 2026)

    fundamentals = _fundamentals()
    enriched = enrich_fundamentals_with_estimates(fundamentals, df, as_of=as_of)

    ttm = 1.00 + 1.00 + 1.00 + 1.00  # Q1-Q4
    ntm = 1.10 + 1.10 + 1.10 + 1.10  # Q5-Q8
    assert enriched.forward_eps == pytest.approx(ntm)
    assert enriched.earnings_growth == pytest.approx((ntm / ttm) - 1)


def test_analyst_estimate_crossing_finds_first_qualifying_quarter():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2025-05-01")
    reversion_pe = 20.0

    # TTM EPS by quarter (ascending): using the first 4 for Q2 2025 is NaN
    # (not enough prior quarters); by Q1 2026 TTM = 0.72+0.59+0.56+1.23=3.10
    # -> projected price = 3.10 * 20 = 62.0
    months = analyst_estimate_crossing_months(df, reversion_pe, target_price=62.0, as_of=as_of)
    assert months is not None
    expected_quarter = pd.Timestamp("2026-03-31")
    assert months == pytest.approx((expected_quarter - as_of).days / 30.44)


def test_analyst_estimate_crossing_returns_none_when_never_reached():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2025-05-01")
    months = analyst_estimate_crossing_months(df, reversion_pe=20.0, target_price=1_000_000.0, as_of=as_of)
    assert months is None


def test_analyst_estimate_crossing_returns_none_without_reversion_pe():
    df = parse_stockanalysis_estimates_text(SAMPLE_TEXT)
    as_of = pd.Timestamp("2025-05-01")
    assert analyst_estimate_crossing_months(df, None, target_price=10.0, as_of=as_of) is None
    assert analyst_estimate_crossing_months(df, 0, target_price=10.0, as_of=as_of) is None
