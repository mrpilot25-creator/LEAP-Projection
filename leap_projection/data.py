"""Data access layer: price history and fundamental snapshots via
Financial Modeling Prep (FMP).

Requires an FMP_API_KEY environment variable. On the Free/Starter plan,
analyst-estimates and price-target endpoints aren't available, so forward
EPS and growth rates are derived from historical income-statement trends
(CAGR) rather than sell-side consensus.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd
import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
DEFAULT_TIMEOUT = 15

# Growth rates outside this range are almost always a data artifact (e.g. a
# near-zero prior-year EPS base), not a real sustainable trend.
GROWTH_CLIP_LOW = -0.5
GROWTH_CLIP_HIGH = 1.5


class FMPError(RuntimeError):
    """Raised for FMP API/config errors (missing key, bad symbol, HTTP failure)."""


@dataclass
class Fundamentals:
    symbol: str
    current_price: Optional[float]
    trailing_eps: Optional[float]
    forward_eps: Optional[float]
    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    peg_ratio: Optional[float]
    earnings_growth: Optional[float]  # fraction/yr, derived from historical EPS CAGR
    revenue_growth: Optional[float]  # fraction/yr, derived from historical revenue CAGR
    analyst_target_mean: Optional[float]
    analyst_target_high: Optional[float]
    analyst_target_low: Optional[float]
    sector: Optional[str]
    market_cap: Optional[float]
    eps_growth_yoy: Optional[float] = None  # latest-quarter trailing YoY EPS growth


def _api_key() -> str:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise FMPError(
            "FMP_API_KEY is not set. Get a key at https://financialmodelingprep.com/ "
            "and export it, e.g.: export FMP_API_KEY=your_key_here"
        )
    return key


def _get(path: str, **params):
    url = f"{FMP_BASE_URL}/{path}"
    params["apikey"] = _api_key()
    try:
        response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise FMPError(f"Network error calling FMP endpoint '{path}': {exc}") from exc

    if response.status_code == 401:
        raise FMPError("FMP rejected the API key (401 Unauthorized). Check FMP_API_KEY.")
    if response.status_code == 403:
        raise FMPError(
            f"FMP endpoint '{path}' returned 403 Forbidden -- likely gated behind a "
            "higher plan tier than the current API key has."
        )
    if response.status_code == 429:
        raise FMPError("FMP rate limit hit (429 Too Many Requests). Slow down or upgrade your plan.")
    if response.status_code != 200:
        raise FMPError(
            f"FMP endpoint '{path}' returned HTTP {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    if isinstance(data, dict) and ("Error Message" in data or "error" in data):
        raise FMPError(f"FMP error for '{path}': {data.get('Error Message') or data.get('error')}")
    return data


def fetch_price_history(symbol: str, years: int = 3) -> pd.DataFrame:
    """Fetch daily OHLCV history for `symbol` over the trailing `years` years."""
    to_date = date.today()
    from_date = to_date - timedelta(days=int(years * 365.25) + 10)
    payload = _get(
        f"historical-price-full/{symbol.upper()}",
        **{"from": from_date.isoformat(), "to": to_date.isoformat()},
    )
    records = payload.get("historical") if isinstance(payload, dict) else None
    if not records:
        raise ValueError(f"No price history returned for '{symbol}'. Check the ticker symbol.")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    close = df["adjClose"] if "adjClose" in df.columns else df["close"]

    out = pd.DataFrame(
        {
            "Open": df["open"] if "open" in df.columns else close,
            "High": df["high"] if "high" in df.columns else close,
            "Low": df["low"] if "low" in df.columns else close,
            "Close": close,
            "Volume": df["volume"] if "volume" in df.columns else 0,
        }
    )
    return out.dropna(subset=["Close"])


def _clip_growth(rate: Optional[float]) -> Optional[float]:
    if rate is None:
        return None
    return max(GROWTH_CLIP_LOW, min(GROWTH_CLIP_HIGH, rate))


def _cagr(oldest: Optional[float], newest: Optional[float], years: float) -> Optional[float]:
    if oldest is None or newest is None or oldest <= 0 or years <= 0:
        return None
    ratio = newest / oldest
    if ratio <= 0:
        return None
    return ratio ** (1 / years) - 1


def _series_cagr(records: List[dict], field: str) -> Optional[float]:
    """CAGR between the oldest and newest values of `field` in `records`
    (expected newest-first, as FMP returns them)."""
    values = [r.get(field) for r in records if r.get(field) is not None]
    if len(values) < 2:
        return None
    newest, oldest = values[0], values[-1]
    years = len(values) - 1
    return _clip_growth(_cagr(oldest, newest, years))


def fetch_fundamentals(symbol: str) -> Fundamentals:
    """Fetch a snapshot of current fundamental data for `symbol` from FMP."""
    symbol = symbol.upper()

    quote_list = _get(f"quote/{symbol}")
    if not quote_list:
        raise ValueError(f"No quote data returned for '{symbol}'. Check the ticker symbol.")
    quote = quote_list[0]

    profile_list = _get(f"profile/{symbol}")
    profile = profile_list[0] if profile_list else {}

    annual_income = _get(f"income-statement/{symbol}", period="annual", limit=6) or []
    quarterly_income = _get(f"income-statement/{symbol}", period="quarter", limit=8) or []

    trailing_eps = quote.get("eps")
    trailing_pe = quote.get("pe")
    current_price = quote.get("price")

    eps_cagr = _series_cagr(annual_income, "epsdiluted") or _series_cagr(annual_income, "eps")
    revenue_cagr = _series_cagr(annual_income, "revenue")
    growth_for_projection = eps_cagr if eps_cagr is not None else revenue_cagr

    forward_eps = (
        trailing_eps * (1 + growth_for_projection)
        if trailing_eps and growth_for_projection is not None
        else None
    )
    forward_pe = (
        current_price / forward_eps if current_price and forward_eps and forward_eps > 0 else None
    )
    peg_ratio = (
        trailing_pe / (eps_cagr * 100) if trailing_pe and eps_cagr and eps_cagr > 0 else None
    )

    eps_growth_yoy = None
    if len(quarterly_income) >= 5:
        latest = quarterly_income[0].get("epsdiluted") or quarterly_income[0].get("eps")
        year_ago = quarterly_income[4].get("epsdiluted") or quarterly_income[4].get("eps")
        eps_growth_yoy = _clip_growth(_cagr(year_ago, latest, 1))

    return Fundamentals(
        symbol=symbol,
        current_price=current_price,
        trailing_eps=trailing_eps,
        forward_eps=forward_eps,
        trailing_pe=trailing_pe,
        forward_pe=forward_pe,
        peg_ratio=peg_ratio,
        earnings_growth=eps_cagr,
        revenue_growth=revenue_cagr,
        analyst_target_mean=None,
        analyst_target_high=None,
        analyst_target_low=None,
        sector=profile.get("sector"),
        market_cap=quote.get("marketCap") or profile.get("mktCap"),
        eps_growth_yoy=eps_growth_yoy,
    )
