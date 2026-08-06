# LEAP-Projection

Fundamentals-driven bottom → peak stock projection, aimed at helping pick a
sane expiration when planning long-dated (LEAP) call options.

Given a ticker, it:

1. **Fetches** current price history and fundamental data from
   [Financial Modeling Prep](https://financialmodelingprep.com/) (FMP),
   optionally enriched with a manually-downloaded
   [stockanalysis.com](https://stockanalysis.com/) financials export and/or
   a copy-pasted stockanalysis.com quarterly analyst-estimates table.
2. **Assesses whether a bottom has been established**, using a validated
   6-signal technical checklist (ported from backtested research — see
   below).
3. **Projects a peak price target** from current fundamentals, blending
   several independent valuation methods.
4. **Estimates the timeframe** to reach that peak, blending the stock's own
   historical bottom→peak cycle length with a fundamentals-growth-implied
   estimate (and, when analyst estimates are supplied, the first future
   quarter the consensus trajectory actually reaches the target).

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

### Optional: stockanalysis.com financials export

[stockanalysis.com](https://stockanalysis.com/) doesn't offer a live API on
a standard subscription, but its "Export to Excel" financials download can
be passed in manually to improve the peak valuation. On a stock's page,
download the financials workbook (Income/Balance-Sheet/Cash-Flow/Ratios ×
Annual/Quarterly/TTM, 12 sheets) and pass its path via
`--stockanalysis-xlsx`. Note this export has **no analyst estimates or
price targets** — its value here is a genuine multi-year historical P/E
series and longer earnings/revenue history (see Methodology).

### Optional: stockanalysis.com quarterly analyst estimates (copy-paste)

stockanalysis.com's *forward* quarterly-estimates table (Revenue/EPS/etc.
projected out ~3 years, with analyst counts) isn't downloadable either, but
it can be **copy-pasted**. Select the table on the page, copy it, paste it
into a plain text file, and pass that file's path via `--estimates-file`.
This is the one source that actually has forward-looking consensus data —
see `leap_projection/estimates.py` for the expected paste shape. It's used
to set a real consensus forward EPS/growth rate (replacing the CAGR-derived
proxy) and to find which future quarter the consensus EPS trajectory first
justifies the projected peak price.

## Usage

```bash
python -m leap_projection.cli AAPL
python -m leap_projection.cli AAPL --years 5 --json
python -m leap_projection.cli AAPL --eps-growth-threshold 0.15
python -m leap_projection.cli NFLX --stockanalysis-xlsx ~/Downloads/NFLX-financials.xlsx
python -m leap_projection.cli NFLX --estimates-file ~/Downloads/NFLX-estimates.txt
```

Or, after `pip install -e .`:

```bash
leap-projection AAPL
```

`--years` controls how much price history is pulled for the bottom
checklist and cycle-length analysis (default 3; needs at least ~150 daily
bars). `--json` prints a machine-readable report instead of the text
summary. `--eps-growth-threshold` optionally layers a fundamental gate on
top of the technical checklist (see below). `--stockanalysis-xlsx` optionally
enriches the peak valuation with a downloaded stockanalysis.com financials
export. `--estimates-file` optionally enriches both the peak valuation and
the timeframe estimate with a copy-pasted quarterly analyst-estimates table.

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
| `forward_pe_reversion` | forward EPS × a "normal" P/E multiple |
| `peg_one` | forward EPS × growth-implied fair P/E, capped at 60 (PEG = 1 heuristic) |
| `analyst_consensus` | sell-side mean 12-month price target (unavailable on FMP Free/Starter — skipped) |
| `prior_high_extension` | prior cycle high grown forward by the current revenue/earnings growth rate |

**On the Free/Starter FMP plan**, `forward_eps` and `earnings_growth` are
derived from the historical annual EPS/revenue CAGR (up to 5 years, via
`income-statement`) rather than analyst consensus — a self-contained proxy,
not a market-implied one. Growth rates are clipped to [-50%, +150%]/yr to
keep noisy small-base periods from producing absurd projections.

**With `--estimates-file` supplied** (`leap_projection/estimates.py`),
`forward_eps` is instead the real **consensus next-twelve-months EPS**
(sum of the next 4 quarters' estimates), and `earnings_growth` is that NTM
EPS versus the trailing-twelve-months actual — both fall back to the
FMP/xlsx-derived values when the pasted table doesn't have 4 full quarters
on either side of today.

**`forward_pe_reversion`'s "normal" multiple:** without a stockanalysis.com
export, this proxies the stock's normal multiple with its *current*
trailing/forward P/E — a single point in time, not a true historical
average. With a `--stockanalysis-xlsx` export supplied
(`leap_projection/stockanalysis_xlsx.py`), it instead uses the **median of
the trailing 5 fiscal years' actual P/E ratios** (positive years only,
needs at least 3 usable years) — a materially better reversion target — and
`earnings_growth`/`revenue_growth` are recomputed from the export's longer
EPS/revenue history too, falling back to the FMP-derived CAGR wherever the
export doesn't have enough history for a given field. Either way, treat the
blended target as a directional anchor with a visible range
(`low_target`/`high_target`), not a precise number.

### 3. Timeframe estimation (`leap_projection/timeframe.py`)

Up to three independent estimates, blended (median):

- **historical_bottom_to_peak_cycles** — average duration of past swing-low
  → swing-high moves found in the stock's own price history.
- **fundamentals_growth_implied** — years of compounding at the current
  earnings/revenue growth rate needed to close the gap from current price to
  the projected peak target.
- **analyst_estimate_crossing** — *(only with `--estimates-file`)* the
  first future quarter whose consensus trailing-twelve-month EPS, at the
  reversion P/E, projects a price that reaches the peak target. Unlike the
  other two methods, this isn't a constant-rate extrapolation — it walks
  the actual quarter-by-quarter consensus trajectory and finds where it
  crosses, so different growth shapes (e.g. a slow next 2 quarters then an
  acceleration) show up as a non-uniform timeline instead of being smoothed
  into a single rate.

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
- Both stockanalysis.com enrichments (the financials export and the
  estimates paste) are **manual, point-in-time snapshots**, not a live
  fetch — they reflect whenever you downloaded/copied them, and have to be
  refreshed and re-passed for a current run. The financials export also has
  no analyst estimates or price targets, despite being a paid subscription.
- The estimates-paste parser is format-sensitive: it expects the exact
  "Fiscal Quarter" / "Period Ending" header rows and known metric labels
  (see `leap_projection/estimates.py`). If stockanalysis.com changes its
  table layout, or a paste gets reflowed by the source app, re-check the
  saved text file against the expected shape before relying on it.
- The `analyst_estimate_crossing` timeframe method is bounded by how far out
  the pasted estimates actually run (coverage thins fast — the real NFLX
  paste this was built against goes from 38 covering analysts down to 1 by
  the final quarters) and returns nothing if the target is never reached
  within that window, which doesn't mean the target won't be reached, only
  that this method can't see that far.
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
