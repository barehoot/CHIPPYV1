"""Forecasting and statistics for the Shift detail analysis tabs: ARIMA, SARIMA, Holt-Winters and a small TCN, plus a
backtest and descriptive statistics. Pure functions over a weekly pandas Series (no Streamlit, no Snowflake), so they
are unit-tested (python/tests/test_forecast.py). Forecasts are model projections of measured history, not plans.

Every model returns the same shape: a dict with "model", "forecast" (DataFrame: WEEK_END_DATE, MEAN, LO80, HI80, LO95,
HI95), "fitted_mae", "aic" (None where it does not apply) and "note". Bad input raises ForecastError with a message.
"""
from __future__ import annotations

import warnings
from datetime import timedelta

import numpy as np
import pandas as pd

MIN_POINTS = 20
Z80, Z95 = 1.2816, 1.96
TCN_LOOKBACK, TCN_EPOCHS, TCN_SEED = 12, 300, 7


class ForecastError(ValueError):
    """The series cannot be modelled (too short, flat, or a missing package); the message says why."""


def prepare(series: pd.Series) -> pd.Series:
    """Sorted float series without gaps in the index order; raises ForecastError when it cannot be modelled."""
    s = pd.Series(series, dtype="float64").dropna().sort_index()
    if len(s) < MIN_POINTS:
        raise ForecastError(f"Needs at least {MIN_POINTS} weeks of history; this series has {len(s)}.")
    if float(s.std()) == 0.0:
        raise ForecastError("The series is flat, so there is nothing to forecast.")
    return s


def season_length(n: int) -> int | None:
    """52 weeks when there are two full years, else a 13-week quarter when there are three, else none."""
    return 52 if n >= 104 else 13 if n >= 39 else None


def _future_index(s: pd.Series, h: int) -> list:
    last = s.index[-1]
    if isinstance(last, (pd.Timestamp,)) or hasattr(last, "toordinal"):
        return [pd.Timestamp(last) + timedelta(weeks=k) for k in range(1, h + 1)]
    return list(range(len(s), len(s) + h))


def _frame(s: pd.Series, mean, lo80, hi80, lo95, hi95) -> pd.DataFrame:
    h = len(mean)
    return pd.DataFrame({"WEEK_END_DATE": _future_index(s, h), "MEAN": np.asarray(mean, dtype=float),
                         "LO80": np.asarray(lo80, dtype=float), "HI80": np.asarray(hi80, dtype=float),
                         "LO95": np.asarray(lo95, dtype=float), "HI95": np.asarray(hi95, dtype=float)})


def _sigma_bands(s: pd.Series, mean: np.ndarray, sigma: float):
    """Bands widening with the square root of the horizon, from the in-sample one-step error."""
    k = np.sqrt(np.arange(1, len(mean) + 1))
    return mean - Z80 * sigma * k, mean + Z80 * sigma * k, mean - Z95 * sigma * k, mean + Z95 * sigma * k


def _result(model: str, s: pd.Series, frame: pd.DataFrame, fitted_mae: float | None, aic: float | None,
            note: str) -> dict:
    return {"model": model, "forecast": frame, "fitted_mae": None if fitted_mae is None else float(fitted_mae),
            "aic": None if aic is None or not np.isfinite(aic) else float(aic), "note": note, "n": len(s)}


# ---- Statistical models ---------------------------------------------------------------------------------------------

def arima(series: pd.Series, h: int = 8) -> dict:
    """ARIMA(p, d, q) with the order chosen by AIC over p, q in 0..2 and d in 0..1."""
    from statsmodels.tsa.arima.model import ARIMA
    s = prepare(series)
    y = s.to_numpy()
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for d in (0, 1):
            for p in range(3):
                for q in range(3):
                    try:
                        fit = ARIMA(y, order=(p, d, q)).fit()
                    except Exception:                         # noqa: BLE001 - skip orders that do not converge
                        continue
                    if np.isfinite(fit.aic) and (best is None or fit.aic < best[1].aic):
                        best = ((p, d, q), fit)
    if best is None:
        raise ForecastError("ARIMA did not converge for any order on this series.")
    order, fit = best
    f80, f95 = fit.get_forecast(h).conf_int(alpha=0.2), fit.get_forecast(h).conf_int(alpha=0.05)
    mean = fit.get_forecast(h).predicted_mean
    resid = np.asarray(fit.resid)[1:]
    return _result("ARIMA", s, _frame(s, mean, f80[:, 0], f80[:, 1], f95[:, 0], f95[:, 1]), np.mean(np.abs(resid)),
                   fit.aic, f"ARIMA{order}, chosen by AIC.")


def sarima(series: pd.Series, h: int = 8) -> dict:
    """Seasonal ARIMA(1, 1, 1) x (P, 0, Q, m) with m = 52 or 13 weeks; P, Q in 0..1 chosen by AIC."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    s = prepare(series)
    m = season_length(len(s))
    if m is None:
        raise ForecastError("SARIMA needs at least 39 weeks for a 13-week season.")
    y = s.to_numpy()
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for P in (0, 1):
            for Q in (0, 1):
                try:
                    fit = SARIMAX(y, order=(1, 1, 1), seasonal_order=(P, 0, Q, m), enforce_stationarity=False,
                                  enforce_invertibility=False).fit(disp=False)
                except Exception:                             # noqa: BLE001
                    continue
                if np.isfinite(fit.aic) and (best is None or fit.aic < best[1].aic):
                    best = ((P, 0, Q, m), fit)
    if best is None:
        raise ForecastError("SARIMA did not converge on this series.")
    sorder, fit = best
    fc = fit.get_forecast(h)
    f80, f95 = np.asarray(fc.conf_int(alpha=0.2)), np.asarray(fc.conf_int(alpha=0.05))
    resid = np.asarray(fit.resid)[m:] if len(s) > m + 5 else np.asarray(fit.resid)[1:]
    note = f"SARIMA(1,1,1)x{sorder}." + ("" if m == 52 else " Season of 13 weeks: under two years of history.")
    return _result("SARIMA", s, _frame(s, fc.predicted_mean, f80[:, 0], f80[:, 1], f95[:, 0], f95[:, 1]),
                   np.mean(np.abs(resid)), fit.aic, note)


def holt_winters(series: pd.Series, h: int = 8) -> dict:
    """Holt-Winters exponential smoothing: additive trend, additive season (52 or 13 weeks), or trend only."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    s = prepare(series)
    m = season_length(len(s))
    seasonal = "add" if m and len(s) >= 2 * m else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(s.to_numpy(), trend="add", damped_trend=True, seasonal=seasonal,
                                   seasonal_periods=m if seasonal else None, initialization_method="estimated").fit()
    mean = np.asarray(fit.forecast(h))
    resid = s.to_numpy() - np.asarray(fit.fittedvalues)
    sigma = float(np.std(resid, ddof=1))
    note = ("Damped additive trend" + (f", additive {m}-week season." if seasonal else ", no season (short history).")
            + " Bands from in-sample error.")
    return _result("Holt-Winters", s, _frame(s, mean, *_sigma_bands(s, mean, sigma)), np.mean(np.abs(resid)),
                   getattr(fit, "aic", None), note)


# ---- Temporal convolutional network ---------------------------------------------------------------------------------

def tcn(series: pd.Series, h: int = 8, lookback: int = TCN_LOOKBACK, epochs: int = TCN_EPOCHS) -> dict:
    """A small temporal convolutional network: three dilated causal 1-D convolution blocks (dilation 1, 2, 4) over a
    12-week window, trained on the standardised series with a fixed seed, forecasting one step at a time."""
    try:
        import torch
        from torch import nn
    except ImportError as e:
        raise ForecastError("TCN needs PyTorch, which is not installed in this environment.") from e
    s = prepare(series)
    if len(s) < lookback + 10:
        raise ForecastError(f"TCN needs at least {lookback + 10} weeks of history.")
    torch.manual_seed(TCN_SEED)
    torch.set_num_threads(1)
    y = s.to_numpy(dtype="float32")
    # model week-on-week changes, not levels, so a recent level shift (like a share drop) is not pulled back
    # towards the old mean; the forecast is the last value plus the cumulative predicted changes
    dy = np.diff(y)
    mu, sd = float(dy.mean()), float(dy.std()) or 1.0
    z = (dy - mu) / sd
    X = np.stack([z[i:i + lookback] for i in range(len(z) - lookback)])
    Y = z[lookback:]

    class Block(nn.Module):
        def __init__(self, cin: int, cout: int, dilation: int):
            super().__init__()
            self.pad = (3 - 1) * dilation
            self.conv = nn.Conv1d(cin, cout, 3, dilation=dilation)
            self.act = nn.ReLU()
            self.skip = nn.Conv1d(cin, cout, 1) if cin != cout else nn.Identity()

        def forward(self, x):
            out = self.act(self.conv(nn.functional.pad(x, (self.pad, 0))))
            return out + self.skip(x)

    class TCN(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = nn.Sequential(Block(1, 16, 1), Block(16, 16, 2), Block(16, 16, 4))
            self.head = nn.Linear(16, 1)

        def forward(self, x):
            return self.head(self.body(x)[:, :, -1]).squeeze(-1)

    net = TCN()
    opt = torch.optim.Adam(net.parameters(), lr=0.01)
    xt, yt = torch.tensor(X).unsqueeze(1), torch.tensor(Y)
    for _ in range(epochs):
        opt.zero_grad()
        loss = nn.functional.mse_loss(net(xt), yt)
        loss.backward()
        opt.step()
    net.eval()
    with torch.no_grad():
        fitted_dy = net(xt).numpy() * sd + mu
        window = list(z[-lookback:])
        out = []
        for _ in range(h):
            nxt = float(net(torch.tensor(window[-lookback:], dtype=torch.float32).view(1, 1, -1))[0])
            out.append(nxt)
            window.append(nxt)
    mean = float(y[-1]) + np.cumsum(np.asarray(out) * sd + mu)
    fitted = y[lookback:-1] + fitted_dy                       # one-step-ahead level predictions
    resid = y[lookback + 1:] - fitted
    # the network fits its training windows closely, so in-sample error understates uncertainty: never claim more
    # confidence than a random walk (the spread of week-on-week changes)
    sigma = max(float(np.std(resid, ddof=1)), float(np.std(dy, ddof=1)))
    return _result("TCN", s, _frame(s, mean, *_sigma_bands(s, mean, sigma)), np.mean(np.abs(resid)), None,
                   f"Dilated causal CNN on week-on-week changes, {lookback}-week window, {epochs} epochs, seed {TCN_SEED}. "
                   "Indicative only: neural models need more history than this to be reliable.")


MODELS = {"ARIMA": arima, "SARIMA": sarima, "Holt-Winters": holt_winters, "TCN": tcn}


def run(series: pd.Series, models: list[str], h: int = 8) -> tuple[list[dict], dict[str, str]]:
    """Fit each selected model; returns (results, errors by model). One failing model never stops the others."""
    results, errors = [], {}
    for name in models:
        try:
            results.append(MODELS[name](series, h))
        except ForecastError as e:
            errors[name] = str(e)
        except Exception as e:                                 # noqa: BLE001 - report, keep the other models
            errors[name] = f"{type(e).__name__}: {e}"[:200]
    return results, errors


# ---- Backtest -------------------------------------------------------------------------------------------------------

def backtest(series: pd.Series, models: list[str], holdout: int = 8) -> pd.DataFrame:
    """Fit on all but the last `holdout` weeks, forecast them, and score against what happened.
    Columns: MODEL, MAE, RMSE, MAPE (percent; zero actuals skipped), BEST (lowest MAE), NOTE."""
    s = prepare(series)
    train, test = s.iloc[:-holdout], s.iloc[-holdout:].to_numpy()
    rows = []
    for name in models:
        try:
            pred = MODELS[name](train, holdout)["forecast"].MEAN.to_numpy()
            err = pred - test
            nz = test != 0
            rows.append({"MODEL": name, "MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err ** 2))),
                         "MAPE": float(np.mean(np.abs(err[nz] / test[nz])) * 100) if nz.any() else None, "NOTE": ""})
        except Exception as e:                                 # noqa: BLE001
            rows.append({"MODEL": name, "MAE": None, "RMSE": None, "MAPE": None, "NOTE": str(e)[:160]})
    df = pd.DataFrame(rows, columns=["MODEL", "MAE", "RMSE", "MAPE", "NOTE"])
    ok = df.MAE.notna()
    df["BEST"] = False
    if ok.any():
        df.loc[df[ok].MAE.astype(float).idxmin(), "BEST"] = True
    return df


# ---- Descriptive statistics -----------------------------------------------------------------------------------------

def stats(series: pd.Series) -> dict:
    """Mean, spread, linear trend per week with its p-value, week-on-week change, seasonality strength, an ADF
    stationarity test, and an STL decomposition (DataFrame: WEEK_END_DATE, OBSERVED, TREND, SEASONAL, RESID)."""
    import statsmodels.api as sm
    from statsmodels.tsa.seasonal import STL
    from statsmodels.tsa.stattools import adfuller
    s = prepare(series)
    y = s.to_numpy()
    t = np.arange(len(y))
    ols = sm.OLS(y, sm.add_constant(t)).fit()
    wow = np.diff(y)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        adf_stat, adf_p = adfuller(y, autolag="AIC")[:2]
    m = season_length(len(y))
    decomp, strength = None, None
    if m:
        res = STL(y, period=m, robust=True).fit()
        decomp = pd.DataFrame({"WEEK_END_DATE": list(s.index), "OBSERVED": y, "TREND": res.trend,
                               "SEASONAL": res.seasonal, "RESID": res.resid})
        denom = np.var(res.seasonal + res.resid)
        strength = float(max(0.0, 1 - np.var(res.resid) / denom)) if denom > 0 else 0.0
    return {"n": len(y), "mean": float(y.mean()), "std": float(y.std(ddof=1)),
            "cv": float(y.std(ddof=1) / y.mean()) if y.mean() else None,
            "min": float(y.min()), "max": float(y.max()), "last": float(y[-1]),
            "trend_per_week": float(ols.params[1]), "trend_p": float(ols.pvalues[1]),
            "wow_mean": float(wow.mean()), "wow_std": float(wow.std(ddof=1)),
            "adf_stat": float(adf_stat), "adf_p": float(adf_p), "stationary": bool(adf_p < 0.05),
            "season_length": m, "seasonality_strength": strength, "decomposition": decomp,
            "wow": pd.DataFrame({"WEEK_END_DATE": list(s.index[1:]), "CHANGE": wow})}
