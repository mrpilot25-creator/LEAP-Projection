"""Data access layer: price history and fundamental snapshots via yfinance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf


@dataclass
class Fundamentals:
    symbol: str
    current_price: Optional[float]
    trailing_eps: Optional[float]
    forward_eps: Optional[float]
    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    peg_ratio: Optional[float]
    earnings_growth: Optional[float]  # fraction, e.g. 0.15 = 15%/yr
    revenue_growth: Optional[float]  # fraction
    analyst_target_mean: Optional[float]
    analyst_target_high: Optional[float]
    analyst_target_low: Optional[float]
    sector: Optional[str]
    market_cap: Optional[float]


def fetch_price_history(symbol: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """Fetch adjusted OHLCV history for `symbol`."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, interval=interval, auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No price history returned for '{symbol}'. Check the ticker symbol.")
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    return hist


def fetch_fundamentals(symbol: str) -> Fundamentals:
    """Fetch a snapshot of current fundamental data for `symbol`."""
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # yfinance still returns a dict on unknown tickers; guard against empty/garbage payloads.
        if not any(info.get(k) for k in ("longName", "shortName", "symbol")):
            raise ValueError(f"No fundamental data returned for '{symbol}'. Check the ticker symbol.")

    return Fundamentals(
        symbol=symbol.upper(),
        current_price=info.get("currentPrice") or info.get("regularMarketPrice"),
        trailing_eps=info.get("trailingEps"),
        forward_eps=info.get("forwardEps"),
        trailing_pe=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        peg_ratio=info.get("pegRatio") or info.get("trailingPegRatio"),
        earnings_growth=info.get("earningsGrowth"),
        revenue_growth=info.get("revenueGrowth"),
        analyst_target_mean=info.get("targetMeanPrice"),
        analyst_target_high=info.get("targetHighPrice"),
        analyst_target_low=info.get("targetLowPrice"),
        sector=info.get("sector"),
        market_cap=info.get("marketCap"),
    )
