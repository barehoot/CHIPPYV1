"""sr_ui.forecast: every model returns the agreed shape on a series with a known trend and season; guards and the
backtest behave; TCN is reproducible with its fixed seed."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "streamlit"))
pytest.importorskip("statsmodels")
from sr_ui import forecast as fc  # noqa: E402

WEEKS = pd.date_range(end="2026-11-21", periods=70, freq="7D")


def synthetic(n: int = 70, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    y = 100 + 0.4 * t + 6 * np.sin(2 * np.pi * t / 13) + rng.normal(0, 1.0, n)
    return pd.Series(y, index=pd.date_range(end="2026-11-21", periods=n, freq="7D"))


@pytest.mark.parametrize("name", ["ARIMA", "SARIMA", "Holt-Winters"])
def test_statistical_models_shape_and_bands(name):
    s = synthetic()
    r = fc.MODELS[name](s, 8)
    f = r["forecast"]
    assert r["model"] == name and len(f) == 8 and list(f.columns) == ["WEEK_END_DATE", "MEAN", "LO80", "HI80", "LO95", "HI95"]
    assert np.isfinite(f[["MEAN", "LO80", "HI80", "LO95", "HI95"]].to_numpy()).all()
    assert (f.LO95 <= f.LO80).all() and (f.LO80 <= f.MEAN).all() and (f.MEAN <= f.HI80).all() and (f.HI80 <= f.HI95).all()
    assert f.WEEK_END_DATE.iloc[0] == s.index[-1] + pd.Timedelta(weeks=1)
    # the forecast continues the upward trend roughly where the series ends
    assert abs(f.MEAN.iloc[0] - s.iloc[-1]) < 15


def test_tcn_shape_and_reproducible():
    pytest.importorskip("torch")
    s = synthetic()
    a, b = fc.tcn(s, 6, epochs=60), fc.tcn(s, 6, epochs=60)
    assert len(a["forecast"]) == 6 and np.isfinite(a["forecast"].MEAN).all()
    assert np.allclose(a["forecast"].MEAN, b["forecast"].MEAN)
    assert (a["forecast"].LO95 <= a["forecast"].MEAN).all() and (a["forecast"].MEAN <= a["forecast"].HI95).all()


def test_guards():
    with pytest.raises(fc.ForecastError, match="at least"):
        fc.arima(pd.Series(range(10), dtype=float))
    with pytest.raises(fc.ForecastError, match="flat"):
        fc.holt_winters(pd.Series([5.0] * 40))
    assert fc.season_length(104) == 52 and fc.season_length(70) == 13 and fc.season_length(30) is None


def test_run_collects_errors_without_stopping():
    results, errors = fc.run(pd.Series(np.arange(30, dtype=float) + np.sin(np.arange(30))), ["ARIMA", "SARIMA"], 4)
    assert [r["model"] for r in results] == ["ARIMA"] and "SARIMA" in errors


def test_backtest_marks_one_best():
    bt = fc.backtest(synthetic(), ["ARIMA", "Holt-Winters"], holdout=8)
    assert list(bt.MODEL) == ["ARIMA", "Holt-Winters"] and bt.BEST.sum() == 1
    assert bt.MAE.notna().all() and (bt.MAPE.astype(float) < 20).all()


def test_stats_trend_season_and_decomposition():
    st = fc.stats(synthetic())
    assert st["n"] == 70 and st["season_length"] == 13
    assert 0.3 < st["trend_per_week"] < 0.5 and st["trend_p"] < 0.001
    assert st["seasonality_strength"] > 0.5
    d = st["decomposition"]
    assert list(d.columns) == ["WEEK_END_DATE", "OBSERVED", "TREND", "SEASONAL", "RESID"] and len(d) == 70
    assert np.allclose(d.TREND + d.SEASONAL + d.RESID, d.OBSERVED)
