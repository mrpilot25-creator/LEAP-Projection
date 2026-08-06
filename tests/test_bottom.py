from leap_projection.bottom import assess_bottom


def test_confirms_bottom_after_decline_and_basing(declining_then_basing_hist):
    assessment = assess_bottom(declining_then_basing_hist)
    assert assessment.drawdown_from_high > 0.15
    assert assessment.confirmed is True
    assert assessment.score >= 0.6


def test_no_bottom_signal_in_steady_uptrend(uptrend_hist):
    assessment = assess_bottom(uptrend_hist)
    assert assessment.confirmed is False
    # an uptrend has no meaningful drawdown, so that signal must fail
    drawdown_signal = next(s for s in assessment.signals if s.name == "meaningful_drawdown")
    assert drawdown_signal.confirmed is False


def test_raises_on_insufficient_history():
    import pandas as pd

    tiny = pd.DataFrame({"Close": [10, 11, 12]}, index=pd.bdate_range("2024-01-01", periods=3))
    try:
        assess_bottom(tiny)
        assert False, "expected ValueError"
    except ValueError:
        pass
