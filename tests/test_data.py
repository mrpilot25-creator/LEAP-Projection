from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from leap_projection.data import (
    FMPError,
    fetch_fundamentals,
    fetch_price_history,
)


def _mock_response(json_body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


@pytest.fixture(autouse=True)
def fmp_api_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")


def test_fetch_price_history_parses_historical_payload():
    payload = {
        "symbol": "AAPL",
        "historical": [
            {"date": "2024-01-03", "open": 100, "high": 102, "low": 99, "close": 101,
             "adjClose": 101, "volume": 1_000_000},
            {"date": "2024-01-02", "open": 98, "high": 101, "low": 97, "close": 100,
             "adjClose": 100, "volume": 900_000},
        ],
    }
    with patch("leap_projection.data.requests.get", return_value=_mock_response(payload)) as mock_get:
        hist = fetch_price_history("AAPL", years=1)

    assert list(hist.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert hist.index.is_monotonic_increasing
    assert hist["Close"].iloc[-1] == 101
    called_url = mock_get.call_args[0][0]
    assert "historical-price-full/AAPL" in called_url


def test_fetch_price_history_raises_on_empty_result():
    payload = {"symbol": "ZZZZ", "historical": []}
    with patch("leap_projection.data.requests.get", return_value=_mock_response(payload)):
        with pytest.raises(ValueError):
            fetch_price_history("ZZZZ")


def test_fetch_fundamentals_derives_forward_eps_from_cagr():
    quote = [{"symbol": "TEST", "eps": 4.0, "pe": 20.0, "price": 80.0, "marketCap": 1_000_000_000}]
    profile = [{"sector": "Technology", "mktCap": 1_000_000_000}]
    # 5 years of annual EPS growing from 2.0 to 4.0 => 2x over 4 periods => ~18.9% CAGR
    annual = [
        {"eps": 4.0, "epsdiluted": 4.0, "revenue": 500},
        {"eps": 3.5, "epsdiluted": 3.5, "revenue": 450},
        {"eps": 3.0, "epsdiluted": 3.0, "revenue": 400},
        {"eps": 2.5, "epsdiluted": 2.5, "revenue": 350},
        {"eps": 2.0, "epsdiluted": 2.0, "revenue": 300},
    ]
    quarterly = [
        {"eps": 1.1, "epsdiluted": 1.1},
        {"eps": 1.0, "epsdiluted": 1.0},
        {"eps": 0.9, "epsdiluted": 0.9},
        {"eps": 0.8, "epsdiluted": 0.8},
        {"eps": 1.0, "epsdiluted": 1.0},  # year-ago quarter
    ]

    responses = {
        "quote/TEST": quote,
        "profile/TEST": profile,
        "income-statement/TEST": None,  # overridden by side_effect below
    }

    def side_effect(url, params=None, timeout=None):
        if "quote/TEST" in url:
            return _mock_response(quote)
        if "profile/TEST" in url:
            return _mock_response(profile)
        if "income-statement/TEST" in url:
            if params.get("period") == "annual":
                return _mock_response(annual)
            return _mock_response(quarterly)
        raise AssertionError(f"unexpected URL {url}")

    with patch("leap_projection.data.requests.get", side_effect=side_effect):
        fundamentals = fetch_fundamentals("TEST")

    assert fundamentals.trailing_eps == 4.0
    assert fundamentals.trailing_pe == 20.0
    assert fundamentals.earnings_growth == pytest.approx(0.1892, abs=0.01)
    assert fundamentals.forward_eps == pytest.approx(4.0 * 1.1892, abs=0.05)
    assert fundamentals.analyst_target_mean is None  # not available on Free/Starter
    # latest quarter eps 1.1 vs year-ago 1.0 => +10%
    assert fundamentals.eps_growth_yoy == pytest.approx(0.10, abs=1e-6)


def test_missing_api_key_raises_fmp_error(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    with pytest.raises(FMPError):
        fetch_price_history("AAPL")


def test_unauthorized_response_raises_fmp_error():
    with patch("leap_projection.data.requests.get", return_value=_mock_response({}, status_code=401)):
        with pytest.raises(FMPError):
            fetch_price_history("AAPL")
