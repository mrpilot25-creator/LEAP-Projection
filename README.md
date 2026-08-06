# LEAP-Projection

Fundamentals-driven bottom → peak stock projection, aimed at helping pick a
sane expiration when planning long-dated (LEAP) call options.

Given a ticker, it:

1. **Fetches** current price history and fundamental data (via `yfinance` /
   Yahoo Finance — free, no API key).
2. **Assesses whether a bottom has been established**, using several
   independent technical signals (not just one).
3. **Projects a peak price target** from current fundamentals, blending
   several independent valuation methods.
4. **Estimates the timeframe** to reach that peak, blending the stock's own
   historical bottom→peak cycle length with a fundamentals-growth-implied
   estimate.

This is a screening aid, not investment advice — see the disclaimer at the
bottom.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python -m leap_projection.cli AAPL
python -m leap_projection.cli AAPL --period 3y --json
```

Or, after `pip install -e .`:

```bash
leap-projection AAPL
```

`--period` accepts any `yfinance` period string (`1y`, `2y`, `5y`, `max`, ...);
it controls how much price history is analyzed for the bottom/cycle
detection. `--json` prints a machine-readable report instead of the text
summary.

## Methodology

### 1. Bottom detection (`leap_projection/bottom.py`)

A max-drawdown/recovery scan over the trailing window (default 252 trading
days) finds the largest peak→trough decline, then checks five independent
signals:

- **meaningful_drawdown** — the decline from the preceding high is at least
  15% (configurable), i.e. this is a real correction, not noise.
- **bounce_off_low** — price is at least 5% above that low.
- **reclaimed_sma20** — price has reclaimed its 20-day simple moving average.
- **rsi_recovery** — RSI(14) was oversold (<35) recently and has since
  recovered above 40.
- **higher_low_pattern** — the most recent swing low is higher than the one
  before it.

A bottom is **confirmed** when the drawdown and bounce signals both hold,
at least one of SMA-reclaim/RSI-recovery holds, and at least 60% of all
signals are true. This deliberately requires multiple signals to agree — no
single indicator is trusted alone.

### 2. Peak valuation (`leap_projection/valuation.py`)

Up to four independent price targets are computed and blended (median):

| Method | Formula |
|---|---|
| `forward_pe_reversion` | forward EPS × the higher of trailing/forward P/E, as a proxy "normal" multiple |
| `peg_one` | forward EPS × growth-implied fair P/E, capped at 60 (PEG = 1 heuristic) |
| `analyst_consensus` | sell-side mean 12-month price target |
| `prior_high_extension` | prior cycle high grown forward by the current revenue/earnings growth rate |

**Known limitation:** `forward_pe_reversion` proxies the stock's "normal"
multiple with its *current* trailing/forward P/E, not a true multi-year
historical average — a clean historical EPS series isn't available from a
free data source. Treat the blended target as a directional anchor with a
visible range (`low_target`/`high_target`), not a precise number.

### 3. Timeframe estimation (`leap_projection/timeframe.py`)

Two independent estimates, blended (median):

- **historical_bottom_to_peak_cycles** — average duration of past swing-low
  → swing-high moves found in the stock's own price history.
- **fundamentals_growth_implied** — years of compounding at the current
  earnings/revenue growth rate needed to close the gap from current price to
  the projected peak target.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests run entirely offline against synthetic, seeded price series (no
network access required) so they're deterministic and CI-friendly.

## Limitations

- Data comes from Yahoo Finance via `yfinance`; fields like `forwardEps`,
  `earningsGrowth`, or analyst targets are sometimes missing or stale for
  smaller/thinly-covered names, which shrinks the number of valuation
  methods used.
- Bottom detection and cycle-length analysis are purely price-based
  (technical), while the peak target is purely fundamentals-based — they are
  intentionally independent lenses, not a single unified model.
- All of this is descriptive/statistical pattern matching, not a guarantee.
  Markets can stay irrational, fundamentals can deteriorate, and "bottoms"
  can be revisited or broken.

**Disclaimer:** informational and educational only. Not investment advice.
Do your own research and size any position — especially leveraged
instruments like options — according to your own risk tolerance.
