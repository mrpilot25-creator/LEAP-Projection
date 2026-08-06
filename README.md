# LEAP-Projection

Fundamentals-driven bottom → peak stock projection, aimed at helping pick a
sane expiration when planning long-dated (LEAP) call options.

Given a ticker, it:

1. **Fetches** current price history and fundamental data from
   [Financial Modeling Prep](https://financialmodelingprep.com/) (FMP).
2. **Assesses whether a bottom has been established**, using a validated
   6-signal technical checklist (ported from backtested research — see
   below).
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

### API key

Requires a [Financial Modeling Prep](https://financialmodelingprep.com/)
API key, exported as an environment variable:

```bash
export FMP_API_KEY=your_key_here
```

Or drop it in a `.env` file in the project root (auto-loaded via
`python-dotenv`):

```
FMP_API_KEY=your_key_here
```

Built against **Free/Starter**-tier endpoints (`quote`, `profile`,
`income-statement`, `historical-price-full`). Analyst-estimates and
price-target endpoints require a higher FMP plan and aren't used — forward
EPS and growth rates are instead derived from historical income-statement
trends (see Methodology).

## Usage

```bash
python -m leap_projection.cli AAPL
python -m leap_projection.cli AAPL --years 5 --json
python -m leap_projection.cli AAPL --eps-growth-threshold 0.15
```

Or, after `pip install -e .`:

```bash
leap-projection AAPL
```

`--years` controls how much price history is pulled for the bottom
checklist and cycle-length analysis (default 3; needs at least ~150 daily
bars). `--json` prints a machine-readable report instead of the text
summary. `--eps-growth-threshold` optionally layers a fundamental gate on
top of the technical checklist (see below).

## Methodology

### 1. Bottom detection (`leap_projection/bottom.py`)

Ported from validated research in the companion
[`bottom-backtest`](https://github.com/mrpilot25-creator/bottom-backtest)
repo: a 21-ticker parameter sweep plus an 8-ticker leave-one-out
cross-validation on momentum/growth names (NFLX, AAPL, MSFT, AMZN, TSLA,
GOOGL, META, NVDA). Six independent technical signals are computed on each
bar:

| Signal | What it catches |
|---|---|
| `macd_cross` | MACD(12,26,9) histogram crosses up through zero |
| `bb_squeeze_release` | Price breaks above the upper Bollinger Band after a prior low-volatility squeeze |
| `trend_break` | Price closes above a downward-sloping linear trend line fit over the trailing 40 days |
| `cmf_cross` | Chaikin Money Flow crosses up through zero |
| `stoch_rsi_recover` | Stochastic RSI recovers up through an oversold threshold |
| `hvn_hold` | Price is holding near a high-volume node (a volume-profile support level) |

A bottom is **confirmed** when at least `MIN_SIGNALS` (2 of 6) fire within
a recent window (15 trading days). The fixed parameters
(`trend_lookback=40, bb_pctile=0.10, stoch_threshold=20, hvn_tolerance=0.02,
min_signals=2`) are the QuantConnect-validated values from the backtest —
not re-tuned per stock. At that "Score >= 2" rule, the out-of-sample
backtest measured **~64.3% precision / ~78.4% recall** against a 40-day
forward window, 10%-rally, ≤1%-drawdown "true bottom" label.

**Optional fundamental gate:** the backtest also found that layering a
trailing YoY EPS growth filter (≥15%) on top of the technical checklist
improved precision further. This is available via `--eps-growth-threshold`
(off by default) — it only confirms a bottom if the latest reported
quarter's YoY EPS growth also clears the threshold.

No single signal, technical or fundamental, is trusted alone.

### 2. Peak valuation (`leap_projection/valuation.py`)

Up to four independent price targets are computed and blended (median):

| Method | Formula |
|---|---|
| `forward_pe_reversion` | forward EPS × the higher of trailing/forward P/E, as a proxy "normal" multiple |
| `peg_one` | forward EPS × growth-implied fair P/E, capped at 60 (PEG = 1 heuristic) |
| `analyst_consensus` | sell-side mean 12-month price target (unavailable on FMP Free/Starter — skipped) |
| `prior_high_extension` | prior cycle high grown forward by the current revenue/earnings growth rate |

**On the Free/Starter FMP plan**, `forward_eps` and `earnings_growth` are
derived from the historical annual EPS/revenue CAGR (up to 5 years, via
`income-statement`) rather than analyst consensus — a self-contained proxy,
not a market-implied one. Growth rates are clipped to [-50%, +150%]/yr to
keep noisy small-base periods from producing absurd projections.

**Known limitation:** `forward_pe_reversion` proxies the stock's "normal"
multiple with its *current* trailing/forward P/E, not a true multi-year
historical average. Treat the blended target as a directional anchor with a
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

Tests run entirely offline against synthetic, seeded price series and mocked
FMP HTTP responses (no network access or real API key required), so they're
deterministic and CI-friendly.

## Limitations

- FMP's `Free`/`Starter`-tier income-statement history is typically limited
  to a handful of years, and quarterly report timing/field availability
  varies by ticker — coverage is thinner for smaller/less-covered names.
- Bottom detection and cycle-length analysis are purely price/volume-based
  (technical), while the peak target is purely fundamentals-based — they are
  intentionally independent lenses, not a single unified model.
- The checklist's validated precision (~64%) and recall (~78%) numbers come
  from a momentum/growth-style backtest universe; performance on other
  sectors/styles (see `bottom-backtest/segment_analysis.py`) degrades
  somewhat, so treat confirmations on non-momentum names with more caution.
- All of this is descriptive/statistical pattern matching, not a guarantee.
  Markets can stay irrational, fundamentals can deteriorate, and "bottoms"
  can be revisited or broken.

**Disclaimer:** informational and educational only. Not investment advice.
Do your own research and size any position — especially leveraged
instruments like options — according to your own risk tolerance.
