"""Insight Studio models (SR-065): exploratory statistics and machine learning on the weekly panel that
data.brand_panel and data.sku_week_panel return. Prices, shares and price indices come from SQL; this module only fits
models SQL cannot. Nothing here feeds the brief, the fact pack or any stored table: every result is labelled
exploratory on screen, with its method, fit and assumptions (the model card).

Pure functions of DataFrames: no Streamlit, no data access, deterministic (fixed seeds), so they are unit-tested in
python/tests/test_analytics.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 65


class AnalyticsError(ValueError):
    """The data cannot support this model; the message says why, in plain words."""


# ---- shared shaping ---------------------------------------------------------------------------------------------

def brand_weekly(panel: pd.DataFrame, brand: str) -> pd.DataFrame:
    """One brand across all retailers, by week: value and unit sales, value share of the category, mean ACV and the
    value-weighted price index. Oldest first."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    tot = d.groupby("WEEK_END_DATE").VALUE_SALES.sum()
    b = d[d.BRAND == brand]
    if b.empty:
        raise AnalyticsError(f"No weekly rows for {brand}.")
    g = b.groupby("WEEK_END_DATE")
    out = pd.DataFrame({"VALUE_SALES": g.VALUE_SALES.sum(), "UNIT_SALES": g.UNIT_SALES.sum(),
                        "ACV_DIST_PCT": g.ACV_DIST_PCT.mean(),
                        "PRICE_INDEX": g.apply(lambda x: np.average(x.PRICE_INDEX, weights=x.VALUE_SALES)
                                               if x.VALUE_SALES.sum() > 0 else np.nan, include_groups=False)})
    out["VALUE_SHARE_PCT"] = 100 * out.VALUE_SALES / tot.reindex(out.index)
    return out.sort_index().reset_index()


def _season(weeks: pd.Series) -> pd.DataFrame:
    t = (pd.to_datetime(weeks).dt.dayofyear / 365.25).to_numpy()
    return pd.DataFrame({"SEASON_SIN": np.sin(2 * np.pi * t), "SEASON_COS": np.cos(2 * np.pi * t)}, index=weeks.index)


def _need(n: int, at_least: int, what: str) -> None:
    if n < at_least:
        raise AnalyticsError(f"{what} needs at least {at_least} rows; this selection has {n}.")


# ---- 1. Price and distribution elasticity (log-log panel regression) ---------------------------------------------

def elasticity(panel: pd.DataFrame, brand: str) -> dict:
    """ln(units) = a + e_price ln(price) + e_dist ln(ACV) + retailer effects + season + trend, by OLS with HC3 robust
    errors on the brand's retailer-week rows. e_price is the % change in units for a 1% price change; e_dist the same
    for distribution. Returns the coefficients with 95% intervals, fit, and actual vs fitted."""
    import statsmodels.api as sm
    d = panel[(panel.BRAND == brand) & (panel.UNIT_SALES > 0) & (panel.PRICE_PER_UNIT > 0) & (panel.ACV_DIST_PCT > 0)].copy()
    _need(len(d), 30, "The elasticity model")
    d["WEEK_END_DATE"] = pd.to_datetime(d.WEEK_END_DATE)
    X = pd.DataFrame({"LN_PRICE": np.log(d.PRICE_PER_UNIT), "LN_ACV": np.log(d.ACV_DIST_PCT)}, index=d.index)
    X = X.join(_season(d.WEEK_END_DATE))
    X["TREND"] = (d.WEEK_END_DATE - d.WEEK_END_DATE.min()).dt.days / 365.25
    if d.RETAILER.nunique() > 1:
        X = X.join(pd.get_dummies(d.RETAILER, prefix="R", drop_first=True, dtype=float))
    X = sm.add_constant(X, has_constant="add")
    y = np.log(d.UNIT_SALES)
    fit = sm.OLS(y, X).fit(cov_type="HC3")
    ci = fit.conf_int()

    def term(name: str) -> dict:
        return {"coef": float(fit.params[name]), "lo": float(ci.loc[name, 0]), "hi": float(ci.loc[name, 1]),
                "p": float(fit.pvalues[name])}
    return {"price": term("LN_PRICE"), "dist": term("LN_ACV"), "r2": float(fit.rsquared), "n": int(fit.nobs),
            "frame": pd.DataFrame({"WEEK_END_DATE": d.WEEK_END_DATE, "RETAILER": d.RETAILER, "ACTUAL": d.UNIT_SALES,
                                   "FITTED": np.exp(fit.fittedvalues), "PRICE": d.PRICE_PER_UNIT})}


def elasticity_all(panel: pd.DataFrame) -> pd.DataFrame:
    """Price and distribution elasticity of every brand with enough rows (brand, coefficients, 95% intervals)."""
    rows = []
    for brand in sorted(panel.BRAND.unique()):
        try:
            e = elasticity(panel, brand)
        except AnalyticsError:
            continue
        rows.append({"BRAND": brand, "PRICE_EL": e["price"]["coef"], "PRICE_LO": e["price"]["lo"],
                     "PRICE_HI": e["price"]["hi"], "DIST_EL": e["dist"]["coef"], "R2": e["r2"], "N": e["n"]})
    return pd.DataFrame(rows)


# ---- 2. Change point: when did the move start? --------------------------------------------------------------------

def change_point(series: pd.Series, min_size: int = 4) -> dict:
    """The single split of a weekly series that best separates two levels (least squares), with Welch's t-test on the
    two sides. Returns the first week of the new level, both means, the step, its p-value and the segments."""
    from scipy import stats
    y = pd.Series(series).dropna().astype(float)
    _need(len(y), 2 * min_size + 2, "Change-point detection")
    v = y.to_numpy()
    n = len(v)
    cs, cs2 = np.cumsum(v), np.cumsum(v ** 2)
    best, best_i = np.inf, None
    for i in range(min_size, n - min_size + 1):
        left = cs2[i - 1] - cs[i - 1] ** 2 / i
        right = (cs2[-1] - cs2[i - 1]) - (cs[-1] - cs[i - 1]) ** 2 / (n - i)
        if left + right < best:
            best, best_i = left + right, i
    a, b = v[:best_i], v[best_i:]
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return {"week": y.index[best_i], "index": int(best_i), "before": float(a.mean()), "after": float(b.mean()),
            "delta": float(b.mean() - a.mean()), "p": float(p), "t": float(t),
            "segments": [(y.index[0], y.index[best_i - 1], float(a.mean())), (y.index[best_i], y.index[-1], float(b.mean()))]}


# ---- 3. Causal impact: what would sales have been without the shift? -----------------------------------------------

def causal_impact(panel: pd.DataFrame, brand: str, start, measure: str = "VALUE_SALES", level: float = 0.9) -> dict:
    """Counterfactual for the brand after `start`: ln(brand) regressed on ln(each other brand) and season over the
    weeks before `start`, then projected forward with prediction intervals. The gap between actual and projected is
    the estimated effect. Assumes the other brands were not themselves moved by the shift (a competitor that took
    the share breaks this, so the effect is then a lower bound)."""
    import statsmodels.api as sm
    from scipy import stats
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    wide = d.pivot_table(index="WEEK_END_DATE", columns="BRAND", values=measure, aggfunc="sum").sort_index()
    if brand not in wide:
        raise AnalyticsError(f"No weekly rows for {brand}.")
    wide = wide[(wide > 0).all(axis=1)]
    start = pd.Timestamp(start)
    pre, post = wide[wide.index < start], wide[wide.index >= start]
    _need(len(pre), 20, "The causal-impact model's pre-period")
    _need(len(post), 2, "The causal-impact model's post-period")
    controls = [c for c in wide.columns if c != brand]
    if not controls:
        raise AnalyticsError("Causal impact needs at least one other brand as a control.")

    def design(frame: pd.DataFrame) -> pd.DataFrame:
        X = np.log(frame[controls]).add_prefix("LN_")
        X = X.join(_season(pd.Series(frame.index, index=frame.index)))
        return sm.add_constant(X, has_constant="add")
    fit = sm.OLS(np.log(pre[brand]), design(pre)).fit()
    alpha = 1 - level
    pred = fit.get_prediction(design(wide)).summary_frame(alpha=alpha)
    frame = pd.DataFrame({"WEEK_END_DATE": wide.index, "ACTUAL": wide[brand].to_numpy(),
                          "PREDICTED": np.exp(pred["mean"]).to_numpy(), "LO": np.exp(pred["obs_ci_lower"]).to_numpy(),
                          "HI": np.exp(pred["obs_ci_upper"]).to_numpy(), "POST": wide.index >= start})
    p_ = frame[frame.POST]
    effect = float((p_.ACTUAL - p_.PREDICTED).sum())
    expected = float(p_.PREDICTED.sum())
    resid_sd = float(np.std(np.log(pre[brand]) - fit.fittedvalues, ddof=len(fit.params)))
    z = float(np.log(p_.ACTUAL / p_.PREDICTED).sum() / (resid_sd * np.sqrt(len(p_)))) if resid_sd > 0 else 0.0
    return {"frame": frame, "effect": effect, "relative": effect / expected if expected else None,
            "per_week": effect / len(p_), "p": float(2 * stats.norm.sf(abs(z))), "weeks": int(len(p_)),
            "pre_r2": float(fit.rsquared), "controls": controls, "start": start, "measure": measure}


# ---- 4. Driver model: gradient boosting on share, with permutation importance ----------------------------------------

DRIVER_FEATURES = {"PRICE_INDEX": "Price index vs category", "ACV_DIST_PCT": "Distribution (ACV %)",
                   "SKUS_SELLING": "SKUs on shelf", "PROMO_DEPTH": "Promotion depth",
                   "COMP_PRICE_INDEX": "Competitors' price index", "COMP_ACV": "Competitors' distribution",
                   "SEASON_SIN": "Season (sine)", "SEASON_COS": "Season (cosine)"}


def driver_features(panel: pd.DataFrame, brand: str) -> pd.DataFrame:
    """The brand's retailer-week rows with model features: its own price index, distribution, SKUs and promotion depth
    (price below its 8-week high), the value-weighted price index and mean distribution of the other brands at the same
    retailer and week, and the season. Target: VALUE_SHARE_PCT."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE)).sort_values("WEEK_END_DATE")
    comp = d[d.BRAND != brand].groupby(["WEEK_END_DATE", "RETAILER"]).apply(
        lambda x: pd.Series({"COMP_PRICE_INDEX": np.average(x.PRICE_INDEX, weights=x.VALUE_SALES)
                             if x.VALUE_SALES.sum() > 0 else np.nan, "COMP_ACV": x.ACV_DIST_PCT.mean()}),
        include_groups=False).reset_index()
    b = d[d.BRAND == brand].merge(comp, on=["WEEK_END_DATE", "RETAILER"], how="left")
    b["PROMO_DEPTH"] = 1 - b.PRICE_PER_UNIT / b.groupby("RETAILER").PRICE_PER_UNIT.transform(
        lambda s: s.rolling(8, min_periods=1).max())
    b = b.join(_season(b.WEEK_END_DATE))
    return b.dropna(subset=list(DRIVER_FEATURES) + ["VALUE_SHARE_PCT"]).reset_index(drop=True)


def driver_model(panel: pd.DataFrame, brand: str) -> dict:
    """Gradient boosting (scikit-learn) predicting the brand's value share per retailer-week from DRIVER_FEATURES.
    Scored out of time (5 expanding folds: always trained on earlier weeks, tested on later ones) against a linear
    model; permutation importance says how much each driver matters; partial dependence shows its response curve."""
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.inspection import partial_dependence, permutation_importance
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score
    b = driver_features(panel, brand)
    _need(len(b), 60, "The driver model")
    X, y = b[list(DRIVER_FEATURES)], b.VALUE_SHARE_PCT
    weeks = np.sort(b.WEEK_END_DATE.unique())
    cuts = [weeks[int(len(weeks) * f)] for f in (0.5, 0.6, 0.7, 0.8, 0.9)]
    gbm_r2, lin_r2 = [], []
    for i, cut in enumerate(cuts):
        end = cuts[i + 1] if i + 1 < len(cuts) else weeks[-1] + np.timedelta64(1, "D")
        tr, te = b.WEEK_END_DATE < cut, (b.WEEK_END_DATE >= cut) & (b.WEEK_END_DATE < end)
        if te.sum() < 4:
            continue
        g = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.9,
                                      random_state=SEED).fit(X[tr], y[tr])
        gbm_r2.append(r2_score(y[te], g.predict(X[te])))
        lin_r2.append(r2_score(y[te], LinearRegression().fit(X[tr], y[tr]).predict(X[te])))
    model = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.9,
                                      random_state=SEED).fit(X, y)
    imp = permutation_importance(model, X, y, n_repeats=5, random_state=SEED)
    importance = pd.DataFrame({"FEATURE": list(DRIVER_FEATURES), "LABEL": list(DRIVER_FEATURES.values()),
                               "IMPORTANCE": imp.importances_mean, "STD": imp.importances_std}
                              ).sort_values("IMPORTANCE", ascending=False).reset_index(drop=True)
    curves = {}
    for f in importance.FEATURE.head(3):
        if f.startswith("SEASON"):
            continue
        pdp = partial_dependence(model, X, [list(X.columns).index(f)], grid_resolution=25, kind="average")
        curves[f] = pd.DataFrame({"X": pdp["grid_values"][0], "Y": pdp["average"][0]})
    return {"importance": importance, "curves": curves, "cv_r2": float(np.mean(gbm_r2)) if gbm_r2 else None,
            "linear_r2": float(np.mean(lin_r2)) if lin_r2 else None, "folds": len(gbm_r2), "n": int(len(b)),
            "in_sample_r2": float(r2_score(y, model.predict(X)))}


# ---- 5. Competitive segmentation (k-means) -----------------------------------------------------------------------

SEGMENT_FEATURES = {"SHARE_PCT": "Value share %", "SHARE_CHG": "Share change, pts", "PRICE_INDEX": "Price index",
                    "ACV": "Distribution (ACV %)", "ACV_CHG": "Distribution change, pts", "GROWTH_PCT": "Sales growth %"}


def segment_positions(panel: pd.DataFrame, weeks: int = 4) -> dict:
    """Every brand at every retailer as one point: share, share change, price index, distribution, its change and
    sales growth (last `weeks` vs the `weeks` before). Standardised, then k-means for k = 2 to 5; the k with the best
    silhouette wins. Each segment gets a plain name from what sets its centre apart."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    w = np.sort(d.WEEK_END_DATE.unique())
    _need(len(w), 2 * weeks, "Segmentation")
    now, before = d[d.WEEK_END_DATE.isin(w[-weeks:])], d[d.WEEK_END_DATE.isin(w[-2 * weeks:-weeks])]
    keys = ["BRAND", "RETAILER"]
    a = now.groupby(keys).agg(SHARE_PCT=("VALUE_SHARE_PCT", "mean"), PRICE_INDEX=("PRICE_INDEX", "mean"),
                              ACV=("ACV_DIST_PCT", "mean"), SALES=("VALUE_SALES", "sum"))
    z = before.groupby(keys).agg(SHARE0=("VALUE_SHARE_PCT", "mean"), ACV0=("ACV_DIST_PCT", "mean"),
                                 SALES0=("VALUE_SALES", "sum"))
    pts = a.join(z, how="inner")
    pts["SHARE_CHG"] = pts.SHARE_PCT - pts.SHARE0
    pts["ACV_CHG"] = pts.ACV - pts.ACV0
    pts["GROWTH_PCT"] = 100 * (pts.SALES / pts.SALES0.where(pts.SALES0 > 0) - 1)
    pts = pts.dropna(subset=list(SEGMENT_FEATURES)).reset_index()
    _need(len(pts), 6, "Segmentation")
    Z = StandardScaler().fit_transform(pts[list(SEGMENT_FEATURES)])
    best = None
    for k in range(2, min(5, len(pts) - 1) + 1):
        lab = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(Z)
        s = silhouette_score(Z, lab)
        if best is None or s > best[0]:
            best = (s, k, lab)
    sil, k, lab = best
    pts["SEGMENT_NO"] = lab
    zc = pd.DataFrame(Z, columns=list(SEGMENT_FEATURES)).assign(SEGMENT_NO=lab).groupby("SEGMENT_NO").mean()
    names = {}
    for seg, row in zc.iterrows():
        f = row.abs().idxmax()
        up = row[f] > 0
        names[seg] = {"SHARE_CHG": ("Gaining share" if up else "Losing share"), "ACV_CHG": ("Gaining distribution" if up
                      else "Losing distribution"), "PRICE_INDEX": ("Premium priced" if up else "Value priced"),
                      "SHARE_PCT": ("Category leaders" if up else "Small players"), "ACV": ("Widely stocked" if up
                      else "Thinly stocked"), "GROWTH_PCT": ("Growing fast" if up else "Shrinking")}[f]
    seen: dict[str, int] = {}
    for seg in sorted(names):                                        # two segments can share a name: number them
        n = names[seg]
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            names[seg] = f"{n} ({seen[n]})"
    pts["SEGMENT"] = pts.SEGMENT_NO.map(names)
    profile = pts.groupby("SEGMENT")[list(SEGMENT_FEATURES)].mean().join(pts.groupby("SEGMENT").size().rename("POINTS"))
    return {"points": pts, "profile": profile.reset_index(), "k": int(k), "silhouette": float(sil)}


# ---- 6. Anomaly scan (Isolation Forest) ---------------------------------------------------------------------------

ANOMALY_FEATURES = {"SALES_WOW": "Sales change week on week", "PRICE_WOW": "Price change week on week",
                    "ACV_WOW": "Distribution change, pts", "UPS_DEV": "Units per store vs its usual level"}


def anomaly_scan(sku_panel: pd.DataFrame, top: int = 12, contamination: float = 0.02) -> dict:
    """Isolation Forest over SKU x retailer weeks on the week-on-week changes from SQL plus units per store against the
    SKU's own median. Returns the most isolated rows with the feature that stands out most (robust z), which is where to
    look for feed problems, listings and delistings."""
    from sklearn.ensemble import IsolationForest
    k = sku_panel.copy()
    k["UPS_DEV"] = np.log(k.UNITS_PER_STORE.where(k.UNITS_PER_STORE > 0)) - np.log(
        k.groupby(["RETAILER", "ITEM_DESC"]).UNITS_PER_STORE.transform("median").where(lambda s: s > 0))
    k = k.dropna(subset=list(ANOMALY_FEATURES)).reset_index(drop=True)
    _need(len(k), 40, "The anomaly scan")
    X = k[list(ANOMALY_FEATURES)].clip(-5, 5)
    forest = IsolationForest(n_estimators=300, contamination=contamination, random_state=SEED).fit(X)
    k["SCORE"] = -forest.score_samples(X)
    k["FLAGGED"] = forest.predict(X) == -1
    med, mad = X.median(), (X - X.median()).abs().median().replace(0, np.nan)
    rz = ((X - med) / (1.4826 * mad)).abs()
    k["WHY"] = rz.idxmax(axis=1).map(ANOMALY_FEATURES)
    k["WHY_Z"] = rz.max(axis=1)
    return {"rows": k.sort_values("SCORE", ascending=False).head(top).reset_index(drop=True), "all": k,
            "flagged": int(k.FLAGGED.sum()), "n": int(len(k))}


# ---- 7. Cannibalisation: who moves against the brand? --------------------------------------------------------------

def cannibalisation(panel: pd.DataFrame, brand: str) -> dict:
    """Weekly category value share of every brand (all retailers); the correlation of week-on-week share changes
    between the brand and each other brand, and the share each other brand gains per point the brand loses (OLS slope).
    A strong negative correlation means the two trade share directly."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    wide = d.pivot_table(index="WEEK_END_DATE", columns="BRAND", values="VALUE_SALES", aggfunc="sum").sort_index()
    share = 100 * wide.div(wide.sum(axis=1), axis=0)
    if brand not in share:
        raise AnalyticsError(f"No weekly rows for {brand}.")
    dd = share.diff().dropna()
    _need(len(dd), 20, "The cannibalisation analysis")
    x = dd[brand]
    rows = []
    for other in share.columns:
        if other == brand:
            continue
        slope = float(np.polyfit(x, dd[other], 1)[0]) if x.std() > 0 else np.nan
        rows.append({"BRAND": other, "CORR": float(x.corr(dd[other])), "GAIN_PER_PT_LOST": -slope})
    pairs = pd.DataFrame(rows).sort_values("CORR").reset_index(drop=True)
    return {"pairs": pairs, "matrix": dd.corr(), "weeks": int(len(dd))}


# ---- Manager and director views -----------------------------------------------------------------------------------

def pareto(panel: pd.DataFrame, brand: str, by: str = "RETAILER", weeks: int = 4) -> pd.DataFrame:
    """Change in the brand's value sales (last `weeks` vs the `weeks` before) by `by`, losses first, with each row's
    share of the total loss and the running total: where the loss is concentrated."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    d = d[d.BRAND == brand] if "BRAND" in d else d
    w = np.sort(d.WEEK_END_DATE.unique())
    _need(len(w), 2 * weeks, "The Pareto view")
    now = d[d.WEEK_END_DATE.isin(w[-weeks:])].groupby(by).VALUE_SALES.sum()
    before = d[d.WEEK_END_DATE.isin(w[-2 * weeks:-weeks])].groupby(by).VALUE_SALES.sum()
    out = pd.DataFrame({"NOW": now, "BEFORE": before}).fillna(0)
    out["CHANGE"] = out.NOW - out.BEFORE
    out = out.sort_values("CHANGE").reset_index().rename(columns={by: "ITEM"})
    loss = -out.CHANGE.clip(upper=0).sum()
    out["SHARE_OF_LOSS"] = (-out.CHANGE.clip(upper=0) / loss) if loss > 0 else 0.0
    out["CUM_SHARE_OF_LOSS"] = out.SHARE_OF_LOSS.cumsum()
    return out


def driver_matrix(panel: pd.DataFrame, brand: str, weeks: int = 4) -> pd.DataFrame:
    """Per retailer, the change (last `weeks` vs the `weeks` before) in the brand's share, distribution, price index and
    units per store: which lever moved where."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    d = d[d.BRAND == brand].assign(UNITS_PER_STORE=lambda x: x.UNIT_SALES / x.STORES_SELLING.where(x.STORES_SELLING > 0))
    w = np.sort(d.WEEK_END_DATE.unique())
    _need(len(w), 2 * weeks, "The driver matrix")
    cols = {"VALUE_SHARE_PCT": "Share, pts", "ACV_DIST_PCT": "Distribution, pts", "PRICE_INDEX": "Price index",
            "UNITS_PER_STORE": "Units per store"}
    now = d[d.WEEK_END_DATE.isin(w[-weeks:])].groupby("RETAILER")[list(cols)].mean()
    before = d[d.WEEK_END_DATE.isin(w[-2 * weeks:-weeks])].groupby("RETAILER")[list(cols)].mean()
    chg = now - before
    chg["UNITS_PER_STORE"] = 100 * (now.UNITS_PER_STORE / before.UNITS_PER_STORE - 1)
    return chg.rename(columns={**cols, "UNITS_PER_STORE": "Units per store, %"}).reset_index()


def actions(panel: pd.DataFrame, brand: str, el: dict, base_weeks: tuple[int, int] = (20, 11), weeks: int = 4) -> pd.DataFrame:
    """Candidate actions ranked by modelled weekly value recovery, using the brand's own elasticities:
    restore distribution to its level of `base_weeks` ago, a 5% price cut, and fixing the retailer that lost most.
    Each row says the assumption and how certain the elasticity behind it is (its 95% interval)."""
    wk = brand_weekly(panel, brand)
    _need(len(wk), max(base_weeks) + weeks, "The action list")
    value_now = float(wk.VALUE_SALES.tail(weeks).mean())
    acv_now = float(wk.ACV_DIST_PCT.tail(weeks).mean())
    acv_base = float(wk.ACV_DIST_PCT.iloc[-base_weeks[0]:-base_weeks[1]].mean())

    def certainty(t: dict) -> str:
        if t["lo"] < 0 < t["hi"]:
            return "Low"
        width = abs(t["hi"] - t["lo"]) / max(abs(t["coef"]), 1e-9)
        return "High" if width < 0.5 else "Medium"
    rows = []
    if acv_base > acv_now:
        uplift = (acv_base / acv_now) ** el["dist"]["coef"] - 1
        rows.append({"ACTION": f"Restore distribution from {acv_now:.0f}% to {acv_base:.0f}% ACV",
                     "LEVER": "Distribution", "UPLIFT_PCT": 100 * uplift, "VALUE_PER_WEEK": value_now * uplift,
                     "CERTAINTY": certainty(el["dist"]),
                     "ASSUMPTION": f"Distribution elasticity {el['dist']['coef']:.2f}; price and season held"})
    cut = 0.05
    uplift = (1 - cut) ** el["price"]["coef"] * (1 - cut) - 1
    rows.append({"ACTION": "Cut shelf price 5%", "LEVER": "Price", "UPLIFT_PCT": 100 * uplift,
                 "VALUE_PER_WEEK": value_now * uplift, "CERTAINTY": certainty(el["price"]),
                 "ASSUMPTION": f"Price elasticity {el['price']['coef']:.2f}; competitors do not react"})
    pr = pareto(panel, brand, "RETAILER", weeks)
    if len(pr) and pr.CHANGE.iloc[0] < 0:
        worst = pr.iloc[0]
        rows.append({"ACTION": f"Recover {worst.ITEM} to its level of {weeks} weeks before", "LEVER": "Retailer",
                     "UPLIFT_PCT": 100 * -worst.CHANGE / max(value_now * weeks, 1e-9),
                     "VALUE_PER_WEEK": -worst.CHANGE / weeks, "CERTAINTY": "Medium",
                     "ASSUMPTION": f"{worst.ITEM} holds {100 * worst.SHARE_OF_LOSS:.0f}% of the loss; measured, not modelled"})
    return pd.DataFrame(rows).sort_values("VALUE_PER_WEEK", ascending=False).reset_index(drop=True)


def _p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def evidence_score(stored: dict, cp: dict | None, ci: dict | None) -> list[tuple[str, bool, str]]:
    """Four independent checks that the move is real, for the director view: the stored anomaly model, the stored
    data checks, a significant change point, and a causal effect whose interval excludes zero."""
    label = str(stored.get("ARTEFACT_LABEL") or "")
    confirmed = stored.get("ANOMALY_CONFIRMED")
    confirmed = bool(confirmed) if confirmed is not None and not pd.isna(confirmed) else False   # NULL: ML step skipped
    return [
        ("Anomaly model (weekly run)", confirmed, "stored ANOMALY_DETECTION result" if stored.get("ANOMALY_CONFIRMED")
         is not None and not pd.isna(stored.get("ANOMALY_CONFIRMED")) else "not run this week"),
        ("Data checks (weekly run)", label not in ("POSSIBLE_DATA_EFFECT",), f"stored label {label or 'none'}"),
        ("Change point", bool(cp and cp["p"] < 0.01), _p_text(cp["p"]) if cp else "not available"),
        ("Causal effect", bool(ci and ci["p"] < 0.05), _p_text(ci["p"]) if ci else "not available"),
    ]


# ---- Emerging shifts: moves that build before the 4-week reports show them ----------------------------------------

def emerging_shifts(panel: pd.DataFrame, threshold_pts: float, min_z: float, scan_weeks: int = 16,
                    k: float = 0.5, h: float = 5.0, period: int = 4) -> pd.DataFrame:
    """Brand x retailer moves found before a 4-week report would show them.

    Both sides read the same seasonality-free series: y = value share this week - the same week a year ago.
    - The report view: a 4-weekly report (published at the end of each `period`-week period, counted back from the
      latest week) on the usual last-4-weeks vs year-ago change (the 4-week mean of y). It flags a move once that
      change is at least `threshold_pts` (MIN_SHARE_PTS) and at least `min_z` (MIN_Z) standard deviations from its
      normal level over a 26-week baseline, and keeps flagging it to the latest report.
    - Chippy, weekly: the same test every week (the first week of the run still flagged), or earlier when a two-sided
      CUSUM on weekly y (slack `k`, alarm at `h`) catches a slow drift in the same direction.
    Both use one statistical test, so the lead time comes only from the weekly cadence and the drift detector.
    Lead time = report week - alarm week, in weeks; an alarm the report has not caught yet is an emerging shift.
    """
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    weeks = np.sort(d.WEEK_END_DATE.unique())
    _need(len(weeks), 52 + 26 + scan_weeks, "Emerging-shift detection")
    rows = []
    for (brand, retailer), g in d.groupby(["BRAND", "RETAILER"]):
        s = g.set_index("WEEK_END_DATE").VALUE_SHARE_PCT.reindex(weeks).astype(float)
        if s.isna().mean() > 0.2:
            continue
        s = s.interpolate(limit_direction="both")
        y = (s - s.shift(52)).dropna()
        m4 = y.rolling(4).mean()
        base, base4 = y.iloc[-scan_weeks - 26:-scan_weeks], m4.iloc[-scan_weeks - 26:-scan_weeks].dropna()
        mu, sd = float(base.mean()), float(base.std(ddof=1))
        mu4, sd4 = float(base4.mean()), float(base4.std(ddof=1))
        if not sd or not sd4 or np.isnan(sd) or np.isnan(sd4):
            continue
        r4 = m4.iloc[-scan_weeks:]
        weekly = (r4.abs() >= threshold_pts) & (((r4 - mu4) / sd4).abs() >= min_z)

        def run_start(flags: pd.Series):                         # first week of the run of flags that is still on
            if not len(flags) or not bool(flags.iloc[-1]):
                return None
            on = flags[::-1].cumprod()[::-1].astype(bool)
            return on[on].index[0]
        ends = r4.index[::-1][::period][::-1]                     # report weeks: every `period`th week back from now
        report = run_start(weekly.loc[ends])
        alarm = run_start(weekly)
        sign = np.sign(r4.iloc[-1])
        z = (y.iloc[-scan_weeks:] - mu) / sd
        hi = lo = 0.0
        for wk, v in z.items():                                   # slow drift in the latest direction
            hi, lo = max(0.0, hi + v - k), min(0.0, lo + v + k)
            if (sign > 0 and hi > h) or (sign < 0 and lo < -h):
                alarm = wk if alarm is None or wk < alarm else alarm
                break
        side = "UP" if sign > 0 else "DOWN"
        if alarm is not None and report is not None and alarm > report:     # weekly can never be later than the report
            alarm = report
        if alarm is None and report is None:
            continue
        end = report if report is not None else weeks[-1]
        lead = int(round((pd.Timestamp(end) - pd.Timestamp(alarm)).days / 7)) if alarm is not None else None
        rows.append({"BRAND": brand, "RETAILER": retailer,
                     "DIRECTION": side or ("UP" if r4.iloc[-1] > 0 else "DOWN"), "ALARM_WEEK": alarm,
                     "REPORT_WEEK": report, "LEAD_WEEKS": lead, "IN_REPORTS": report is not None,
                     "SHARE_NOW": float(s.iloc[-1]), "L4W_VS_YA_PTS": float(r4.iloc[-1]),
                     "DRIFT_SD": float((r4.iloc[-1] - mu4) / sd4)})
    cols = ["BRAND", "RETAILER", "DIRECTION", "ALARM_WEEK", "REPORT_WEEK", "LEAD_WEEKS", "IN_REPORTS", "SHARE_NOW",
            "L4W_VS_YA_PTS", "DRIFT_SD"]
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out.assign(STATUS=pd.Series(dtype=str))
    out["STATUS"] = np.where(~out.IN_REPORTS, "Emerging: not in reports yet",
                             np.where(out.LEAD_WEEKS.fillna(0) > 0, "Flagged early", "Same time as reports"))
    order = out.STATUS.map({"Emerging: not in reports yet": 0, "Flagged early": 1, "Same time as reports": 2})
    return out.assign(_O=order, _D=-out.DRIFT_SD.abs()).sort_values(["_O", "_D"]).drop(columns=["_O", "_D"]).reset_index(drop=True)


# ---- Share report: competitive benchmark for one market and period ------------------------------------------------

def share_report(panel: pd.DataFrame, weeks: int = 4, compare: str = "previous", retailer: str | None = None,
                 measure: str = "value") -> pd.DataFrame:
    """The pandas reference for data.share_report (which computes the same in SQL for the app; this one backs the
    local preview's sample data and the tests). Every brand in the category for the last `weeks` against the `weeks` before (compare="previous") or the same
    weeks a year ago ("year_ago"), in all retailers combined or one: value share and its change in points, rank and
    rank change, value sales and growth, distribution (mean ACV), value-weighted price index, velocity (units per store
    per week), share of distribution points (ACV x SKUs, TDP-style) and the fair-share index (value share / that
    share x 100: above 100 sells more than its shelf presence)."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    if retailer:
        d = d[d.RETAILER == retailer]
    w = np.sort(d.WEEK_END_DATE.unique())
    back = weeks if compare == "previous" else 52
    _need(len(w), back + weeks, "The share report")
    now, before = w[-weeks:], (w[-2 * weeks:-weeks] if compare == "previous" else w[-52 - weeks:-52])

    def block(ws) -> pd.DataFrame:
        x = d[d.WEEK_END_DATE.isin(ws)].assign(TDP=lambda f: f.ACV_DIST_PCT * f.SKUS_SELLING,
                                               UPS=lambda f: f.UNIT_SALES / f.STORES_SELLING.where(f.STORES_SELLING > 0))
        g = x.groupby(["BRAND", "MANUFACTURER"])
        base = g.VOLUME_SALES.sum() if measure == "volume" else g.VALUE_SALES.sum()
        out = pd.DataFrame({"SALES": g.VALUE_SALES.sum(), "ACV": g.ACV_DIST_PCT.mean(), "TDP": g.TDP.sum(),
                            "VELOCITY": g.UPS.mean(),
                            "PRICE_INDEX": g.apply(lambda f: np.average(f.PRICE_INDEX, weights=f.VALUE_SALES)
                                                   if f.VALUE_SALES.sum() > 0 else np.nan, include_groups=False)})
        out["SHARE"] = 100 * base / base.sum()
        out["TDP_SHARE"] = 100 * out.TDP / out.TDP.sum()
        out["RANK"] = out.SHARE.rank(ascending=False, method="min").astype(int)
        return out
    a, b = block(now), block(before)
    r = a.join(b[["SHARE", "SALES", "RANK"]], rsuffix="_BEFORE", how="left")
    r["SHARE_CHG_PTS"] = r.SHARE - r.SHARE_BEFORE
    r["RANK_CHG"] = r.RANK_BEFORE - r.RANK                       # positive: moved up
    r["SALES_GROWTH_PCT"] = 100 * (r.SALES / r.SALES_BEFORE.where(r.SALES_BEFORE > 0) - 1)
    r["FAIR_SHARE_INDEX"] = 100 * r.SHARE / r.TDP_SHARE.where(r.TDP_SHARE > 0)
    return r.reset_index().sort_values("RANK").reset_index(drop=True)


def competitive_share_week(panel: pd.DataFrame, weeks: int = 52, measure: str = "value") -> pd.DataFrame:
    """The pandas reference for data.competitive_share_week (sample data and tests): weekly share of each brand, all
    retailers combined, last `weeks` weeks, on value or volume sales."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    d = d[d.WEEK_END_DATE.isin(np.sort(d.WEEK_END_DATE.unique())[-weeks:])]
    col = "VOLUME_SALES" if measure == "volume" else "VALUE_SALES"
    g = d.groupby(["WEEK_END_DATE", "MANUFACTURER", "BRAND"], as_index=False)[col].sum()
    g["SHARE_PCT"] = 100 * g[col] / g.groupby("WEEK_END_DATE")[col].transform("sum")
    return g[["WEEK_END_DATE", "MANUFACTURER", "BRAND", "SHARE_PCT"]].sort_values(["WEEK_END_DATE", "BRAND"])


def competitive_regions(panel: pd.DataFrame, weeks: int = 4, compare: str = "previous", measure: str = "value") -> pd.DataFrame:
    """The pandas reference for data.competitive_regions: per retailer and brand, share of the retailer's category now
    and in the comparison period, its change, mean ACV and velocity (units per store per week)."""
    d = panel.assign(WEEK_END_DATE=pd.to_datetime(panel.WEEK_END_DATE))
    w = np.sort(d.WEEK_END_DATE.unique())
    back = weeks if compare == "previous" else 52
    _need(len(w), back + weeks, "The regional view")
    now, before = w[-weeks:], (w[-2 * weeks:-weeks] if compare == "previous" else w[-52 - weeks:-52])
    col = "VOLUME_SALES" if measure == "volume" else "VALUE_SALES"
    keys = ["REGION", "RETAILER", "MARKET_ID", "MANUFACTURER", "BRAND"]

    def block(ws) -> pd.DataFrame:
        x = d[d.WEEK_END_DATE.isin(ws)].assign(UPS=lambda f: f.UNIT_SALES / f.STORES_SELLING.where(f.STORES_SELLING > 0))
        g = x.groupby(keys).agg(BASE=(col, "sum"), ACV=("ACV_DIST_PCT", "mean"), VELOCITY=("UPS", "mean")).reset_index()
        g["SHARE"] = 100 * g.BASE / g.groupby("MARKET_ID").BASE.transform("sum")
        return g
    a, b = block(now), block(before)
    r = a.merge(b[keys + ["SHARE"]].rename(columns={"SHARE": "SHARE_BEFORE"}), on=keys, how="left")
    r["SHARE_CHG_PTS"] = r.SHARE - r.SHARE_BEFORE
    return r[keys + ["SHARE", "SHARE_BEFORE", "SHARE_CHG_PTS", "ACV", "VELOCITY"]].sort_values(["REGION", "RETAILER", "BRAND"]) \
        .reset_index(drop=True)


# ---- Scenario simulator: Monte Carlo on the brand's own elasticities ----------------------------------------------

def simulate(panel: pd.DataFrame, brand: str, el: dict, price_pct: float, dist_pts: float, weeks: int = 4,
             n: int = 4000) -> dict:
    """Weekly value sales and category value share if the brand changes price by `price_pct` % and distribution by
    `dist_pts` ACV points, competitors unchanged. Elasticities are drawn from their sampling distribution (normal,
    from the 95% intervals) n times, so the answer is a range: P10, median, P90."""
    wk = brand_weekly(panel, brand)
    _need(len(wk), weeks, "The simulator")
    rng = np.random.default_rng(SEED)
    v0 = float(wk.VALUE_SALES.tail(weeks).mean())
    tot0 = float((wk.VALUE_SALES / (wk.VALUE_SHARE_PCT / 100)).tail(weeks).mean())
    acv0 = float(wk.ACV_DIST_PCT.tail(weeks).mean())
    acv1 = float(np.clip(acv0 + dist_pts, 1, 100))
    se = lambda t: max((t["hi"] - t["lo"]) / 3.92, 1e-9)        # noqa: E731
    ep = rng.normal(el["price"]["coef"], se(el["price"]), n)
    ed = rng.normal(el["dist"]["coef"], se(el["dist"]), n)
    p = 1 + price_pct / 100
    units = p ** ep * (acv1 / acv0) ** ed
    v1 = v0 * units * p
    share1 = 100 * v1 / (tot0 - v0 + v1)
    q = lambda x: np.percentile(x, [10, 50, 90])                 # noqa: E731
    return {"value_now": v0, "share_now": 100 * v0 / tot0, "acv_now": acv0, "acv_new": acv1,
            "value": q(v1), "value_change": q(v1 - v0), "share": q(share1), "share_change": q(share1 - 100 * v0 / tot0),
            "draws": pd.DataFrame({"VALUE_CHANGE": v1 - v0, "SHARE_CHANGE": share1 - 100 * v0 / tot0}),
            "p_gain": float((v1 > v0).mean())}


def price_ladder(ladder: pd.DataFrame) -> pd.DataFrame:
    """Price per unit by brand and pack, with each pack's index against the category's value-weighted price for the
    same pack size (100 = the category average for that pack)."""
    d = ladder.copy()
    cat = d.groupby("PACK_SIZE").apply(lambda f: f.VALUE_SALES.sum() / f.UNIT_SALES.sum(), include_groups=False)
    d["PACK_INDEX"] = 100 * d.PRICE_PER_UNIT / d.PACK_SIZE.map(cat)
    return d
