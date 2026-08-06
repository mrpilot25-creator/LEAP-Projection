import pandas as pd
import pytest

from leap_projection import bottom as bottom_mod
from leap_projection.bottom import SIGNAL_NAMES, assess_bottom
from leap_projection.data import Fundamentals


def _fundamentals(eps_growth_yoy=None) -> Fundamentals:
    return Fundamentals(
        symbol="TEST",
        current_price=100.0,
        trailing_eps=4.0,
        forward_eps=5.0,
        trailing_pe=25.0,
        forward_pe=20.0,
        peg_ratio=1.2,
        earnings_growth=0.20,
        revenue_growth=0.15,
        analyst_target_mean=None,
        analyst_target_high=None,
        analyst_target_low=None,
        sector="Technology",
        market_cap=5_000_000_000,
        eps_growth_yoy=eps_growth_yoy,
    )


def _all_false_signals(hist: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(False, index=hist.index, columns=SIGNAL_NAMES)


def _fire_on(hist: pd.DataFrame, fire_date, names) -> pd.DataFrame:
    df = pd.DataFrame(False, index=hist.index, columns=SIGNAL_NAMES)
    df.loc[fire_date, names] = True
    return df


def test_raises_on_insufficient_history():
    tiny = pd.DataFrame(
        {"Close": [10.0] * 10, "High": [10.5] * 10, "Low": [9.5] * 10, "Volume": [1000] * 10},
        index=pd.bdate_range("2024-01-01", periods=10),
    )
    with pytest.raises(ValueError):
        assess_bottom(tiny)


def test_not_confirmed_when_checklist_never_fires(sample_hist, monkeypatch):
    monkeypatch.setattr(bottom_mod, "compute_signals", lambda hist: _all_false_signals(hist))
    assessment = assess_bottom(sample_hist)
    assert assessment.confirmed is False
    assert assessment.score == 0.0
    assert assessment.bottom_date == sample_hist.index[-1]


def test_confirmed_when_checklist_fires_within_recent_window(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-5]
    fired_names = ["macd_cross", "stoch_rsi_recover", "cmf_cross"]
    monkeypatch.setattr(
        bottom_mod, "compute_signals", lambda hist: _fire_on(hist, fire_date, fired_names)
    )
    assessment = assess_bottom(sample_hist)
    assert assessment.confirmed is True
    assert assessment.bottom_date == fire_date
    assert assessment.score == pytest.approx(len(fired_names) / len(SIGNAL_NAMES))
    assert {s.name for s in assessment.signals if s.confirmed} == set(fired_names)
    assert len(assessment.signals) == len(SIGNAL_NAMES)


def test_not_confirmed_when_fire_is_outside_recent_window(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-(bottom_mod.RECENT_FIRE_WINDOW + 5)]
    monkeypatch.setattr(
        bottom_mod,
        "compute_signals",
        lambda hist: _fire_on(hist, fire_date, ["macd_cross", "stoch_rsi_recover"]),
    )
    assessment = assess_bottom(sample_hist)
    assert assessment.confirmed is False


def test_single_signal_below_min_signals_does_not_confirm(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-3]
    monkeypatch.setattr(
        bottom_mod, "compute_signals", lambda hist: _fire_on(hist, fire_date, ["hvn_hold"])
    )
    assessment = assess_bottom(sample_hist)
    assert assessment.confirmed is False


def test_fundamental_gate_blocks_confirmation_below_threshold(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-3]
    monkeypatch.setattr(
        bottom_mod,
        "compute_signals",
        lambda hist: _fire_on(hist, fire_date, ["macd_cross", "trend_break"]),
    )
    fundamentals = _fundamentals(eps_growth_yoy=0.05)
    assessment = assess_bottom(sample_hist, fundamentals=fundamentals, eps_growth_threshold=0.15)
    assert assessment.confirmed is False
    assert assessment.fundamental_gate is not None
    assert assessment.fundamental_gate.confirmed is False


def test_fundamental_gate_passes_above_threshold(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-3]
    monkeypatch.setattr(
        bottom_mod,
        "compute_signals",
        lambda hist: _fire_on(hist, fire_date, ["macd_cross", "trend_break"]),
    )
    fundamentals = _fundamentals(eps_growth_yoy=0.22)
    assessment = assess_bottom(sample_hist, fundamentals=fundamentals, eps_growth_threshold=0.15)
    assert assessment.confirmed is True
    assert assessment.fundamental_gate.confirmed is True


def test_fundamental_gate_without_fundamentals_data_fails_closed(sample_hist, monkeypatch):
    fire_date = sample_hist.index[-3]
    monkeypatch.setattr(
        bottom_mod,
        "compute_signals",
        lambda hist: _fire_on(hist, fire_date, ["macd_cross", "trend_break"]),
    )
    assessment = assess_bottom(sample_hist, fundamentals=None, eps_growth_threshold=0.15)
    assert assessment.confirmed is False
    assert assessment.fundamental_gate.confirmed is False


def test_v_shaped_recovery_triggers_real_checklist(checklist_fire_hist):
    """End-to-end sanity check against the real (unmocked) indicator math."""
    assessment = assess_bottom(checklist_fire_hist)
    assert assessment.confirmed is True
    assert 0 < assessment.score <= 1.0
    assert len(assessment.signals) == len(SIGNAL_NAMES)
