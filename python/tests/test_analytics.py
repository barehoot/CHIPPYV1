"""Insight Studio models (streamlit/sr_ui/analytics.py) and the Ask Chippy Auto rule (sr_ui/agent_router.py).

The synthetic panel in test_ui_pages.synthetic_panels() plants known truths: price elasticities per brand, a
distribution elasticity of 1.1, Crunchy losing distribution and Golden Bake gaining it over the last 10 weeks, and two
SKU anomalies. Each model must find what was planted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
from sr_ui import agent_router, analytics as an  # noqa: E402
from test_ui_pages import PANEL_BRANDS, synthetic_panels  # noqa: E402


@pytest.fixture(scope="module")
def panels():
    return synthetic_panels()


def test_elasticity_recovers_planted_values(panels):
    b, _ = panels
    for brand, (_, _, el, _) in PANEL_BRANDS.items():
        e = an.elasticity(b, brand)
        assert e["price"]["lo"] - 0.15 < el < e["price"]["hi"] + 0.15, (brand, e["price"], el)
        assert 0.8 < e["dist"]["coef"] < 1.4, (brand, e["dist"])
    assert len(an.elasticity_all(b)) == len(PANEL_BRANDS)


def test_change_point_dates_the_distribution_loss(panels):
    b, _ = panels
    s = an.brand_weekly(b, "Crunchy").set_index("WEEK_END_DATE").VALUE_SHARE_PCT
    cp = an.change_point(s)
    assert cp["delta"] < 0 and cp["p"] < 0.001
    assert cp["week"] >= s.index[-14]                          # within the planted last-10-weeks window (±4)


def test_causal_impact_finds_a_significant_loss(panels):
    b, _ = panels
    weeks = sorted(b.WEEK_END_DATE.unique())
    ci = an.causal_impact(b, "Crunchy", weeks[-8])
    assert ci["effect"] < 0 and ci["relative"] < -0.05 and ci["p"] < 0.01
    assert ci["weeks"] == 8 and "Crunchy" not in ci["controls"]
    assert {"ACTUAL", "PREDICTED", "LO", "HI", "POST"} <= set(ci["frame"].columns)


def test_driver_model_ranks_price_and_distribution_first(panels):
    b, _ = panels
    dm = an.driver_model(b, "Crunchy")
    assert set(dm["importance"].FEATURE.head(2)) == {"PRICE_INDEX", "ACV_DIST_PCT"}
    assert dm["folds"] >= 3 and dm["cv_r2"] is not None and dm["linear_r2"] is not None
    assert dm["curves"]


def test_segments_separate_the_distribution_loser(panels):
    b, _ = panels
    sg = an.segment_positions(b)
    assert 2 <= sg["k"] <= 5 and sg["silhouette"] > 0.2
    crunchy = sg["points"][sg["points"].BRAND == "Crunchy"].SEGMENT
    assert crunchy.nunique() == 1                                # every Crunchy retailer lands in the same segment
    assert (sg["points"].SEGMENT == crunchy.iloc[0]).sum() <= len(crunchy) + 1


def test_anomaly_scan_puts_the_planted_spike_first(panels):
    _, k = panels
    res = an.anomaly_scan(k)
    top = res["rows"].iloc[0]
    assert (top.RETAILER, top.ITEM_DESC) == ("North Retail", "Crunchy 300g")
    assert res["flagged"] >= 1


def test_cannibalisation_names_the_brand_that_took_share(panels):
    b, _ = panels
    cb = an.cannibalisation(b, "Crunchy")
    assert cb["pairs"].iloc[0].BRAND == "Golden Bake" and cb["pairs"].iloc[0].CORR < -0.3


def test_pareto_and_actions(panels):
    b, _ = panels
    pr = an.pareto(b, "Crunchy")
    assert pr.CHANGE.is_monotonic_increasing and abs(pr.SHARE_OF_LOSS.clip(lower=0).sum() - 1) < 1e-9
    acts = an.actions(b, "Crunchy", an.elasticity(b, "Crunchy"))
    assert acts.iloc[0].LEVER == "Distribution" and acts.VALUE_PER_WEEK.is_monotonic_decreasing
    assert set(acts.CERTAINTY) <= {"High", "Medium", "Low"}


def test_too_little_data_says_why():
    tiny = synthetic_panels()[0].groupby("BRAND").head(5)
    with pytest.raises(an.AnalyticsError, match="needs at least"):
        an.elasticity(tiny, "Crunchy")
    with pytest.raises(an.AnalyticsError, match="No weekly rows"):
        an.brand_weekly(tiny, "Nobody")


def test_evidence_score_reads_stored_and_model_checks():
    checks = an.evidence_score({"ANOMALY_CONFIRMED": True, "ARTEFACT_LABEL": "POSSIBLE_DATA_EFFECT"},
                               {"p": 1e-6}, {"p": 0.2})
    assert [ok for _, ok, _ in checks] == [True, False, True, False]
    assert checks[2][2] == "p < 0.001"


@pytest.mark.parametrize("question,agent", [
    ("Why did Crunchy lose share in All India?", agent_router.CHIPPY),
    ("Who took the share Crunchy lost?", agent_router.CHIPPY),
    ("Is the drop real or a data effect?", agent_router.CHIPPY),
    ("What if distribution went back to 80%?", agent_router.CHIPPY),
    ("Which brands have the highest value share over the last 4 weeks?", agent_router.ANALYST),
    ("Compare value sales by retailer for the last 12 weeks vs year ago", agent_router.ANALYST),
    ("Top 5 manufacturers by unit sales", agent_router.ANALYST),
    ("hello", agent_router.CHIPPY),
    ("Which cities drove Brand C's loss?", agent_router.GEO),
    ("How does Brand C win back its share in South Retail?", agent_router.RECOVERY),
    ("Is Brand C priced too high in All India?", agent_router.PRICE),
    ("What are the biggest risks for Brand C next month?", agent_router.RISK),
    ("How does Manufacturer 3 compare with its competitors?", agent_router.COMPETITOR),
])
def test_auto_routes_each_question(question, agent):
    got, why = agent_router.route(question)
    assert got == agent and why


def test_auto_ties_go_to_chippy_and_only_allowed_agents():
    from sr_ui import data
    assert agent_router.route("")[0] == agent_router.CHIPPY == data.AGENT
    assert set(agent_router.ORDER) == set(data.AGENTS)     # the rule can only pick allowed agents, and can pick each


# ---- SR-065 round 2: emerging shifts, share report, simulator, price ladder, the Intelligence brief lock -----------

def test_emerging_shifts_catch_the_planted_moves_no_later_than_reports(panels):
    b, _ = panels
    em = an.emerging_shifts(b, 0.3, 2.0)
    crunchy = em[em.BRAND == "Crunchy"]
    assert len(crunchy) == 4 and (crunchy.DIRECTION == "DOWN").all()          # every retailer, the right way
    assert (em.LEAD_WEEKS.dropna() >= 0).all()                                # same test, weekly: never later
    assert set(em.STATUS) <= {"Emerging: not in reports yet", "Flagged early", "Same time as reports"}
    assert (em.STATUS == "Flagged early").any()


def test_share_report_ranks_and_fair_share(panels):
    b, _ = panels
    r = an.share_report(b, 4, "year_ago")
    assert list(r.RANK) == sorted(r.RANK) and abs(r.SHARE.sum() - 100) < 1e-6 and abs(r.TDP_SHARE.sum() - 100) < 1e-6
    crunchy = r[r.BRAND == "Crunchy"].iloc[0]
    assert crunchy.SHARE_CHG_PTS < -3 and crunchy.ACV < 70                    # the planted distribution loss
    one = an.share_report(b, 4, "previous", "East Retail")
    assert abs(one.SHARE.sum() - 100) < 1e-6


def test_simulator_ranges_follow_the_elasticities(panels):
    b, _ = panels
    el = an.elasticity(b, "Crunchy")
    up = an.simulate(b, "Crunchy", el, 0, 10)
    assert up["value_change"][0] > 0 and up["p_gain"] > 0.95                  # more distribution sells more
    dear = an.simulate(b, "Crunchy", el, 10, 0)
    assert dear["value_change"][1] < 0                                        # elastic brand: +10% price loses value
    flat = an.simulate(b, "Crunchy", el, 0, 0)
    assert abs(flat["value_change"][1]) < 1e-6
    assert up["value_change"][0] <= up["value_change"][1] <= up["value_change"][2]


def test_price_ladder_index():
    from test_ui_pages import synthetic_ladder
    lad = an.price_ladder(synthetic_ladder())
    for pack, g in lad.groupby("PACK_SIZE"):
        avg = (g.PACK_INDEX * g.UNIT_SALES * g.PRICE_PER_UNIT).sum() / (g.UNIT_SALES * g.PRICE_PER_UNIT).sum()
        assert 50 < avg < 200, pack


def test_intelligence_brief_lock():
    from sr_ui import intel
    pk = intel.Pack()
    a, m = pk.add("share change", "-0.84 pts", "APP.SHIFT_RANKED"), pk.add("gap", "INR 5K", "model", model=True)
    assert intel.problems(f"Down {a}.", pk) == []
    assert intel.problems("Down 0.84 pts.", pk)                                # a typed number
    assert intel.problems("Down [F09].", pk)                                   # an unknown fact
    assert intel.problems(f"Down -{a}.", pk)                                   # a sign added to a signed fact
    assert intel.problems(f"A gap of {m}.", pk) and not intel.problems(f"A model estimate: {m}.", pk)
    assert "−" not in intel.render(f"Down {a}.", pk) and "-0.84 pts" in intel.render(f"Down {a}.", pk)
    assert intel.plain(f"Down {a}.", pk) == "Down -0.84 pts."
    for bad in ["Lost three points.", "Sales fell by half, an estimate.", f"{a}% of share.", f"{a} percentage points.",
                f"Worth INR {m}, an estimate.", f"Worth ₹{m}, a model estimate.", f"A gap of {m}. A model says so."]:
        assert intel.problems(bad, pk), bad
    assert not intel.problems("Crunchy is the one to watch.", pk)


def test_share_report_sql_matches_the_reference(panels):
    """data.share_report's SQL, run on DuckDB over a SKU-level table built from the synthetic panel, gives the same
    report as the pandas reference for both comparisons and for one retailer."""
    duckdb = pytest.importorskip("duckdb")
    sqlglot = pytest.importorskip("sqlglot")
    import sr_ui.data as real
    b, _ = panels
    rows = []
    for r in b.itertuples(index=False):                         # one row per SKU: the view's grain
        k = int(r.SKUS_SELLING)
        for i in range(k):
            rows.append({"WEEK_END_DATE": r.WEEK_END_DATE, "MARKET_ID": r.MARKET_ID, "MARKET_LEVEL": "RETAILER",
                         "RETAILER": r.RETAILER, "CATEGORY": "Biscuits", "MANUFACTURER": r.MANUFACTURER, "BRAND": r.BRAND,
                         "PRODUCT_ID": f"{r.BRAND}{i}", "VALUE_SALES": r.VALUE_SALES / k, "UNIT_SALES": r.UNIT_SALES / k,
                         "ACV_DIST_PCT": r.ACV_DIST_PCT, "STORES_SELLING": r.STORES_SELLING})
    con = duckdb.connect()
    con.register("sku", pd.DataFrame(rows))
    con.execute("CREATE TABLE V_UI_SKU_WEEK AS SELECT * FROM sku")

    def run(sql, params):
        for v in params:
            sql = sql.replace("?", "NULL" if v is None else (f"'{v}'" if isinstance(v, str) else str(v)), 1)
        sql = sql.replace("SR_DB.APP.V_UI_SKU_WEEK", "V_UI_SKU_WEEK")
        return con.execute(sqlglot.transpile(sql, read="snowflake", write="duckdb")[0]).df()
    for weeks, compare, retailer in [(4, "previous", None), (4, "year_ago", None), (12, "previous", "East Retail")]:
        sql_calls = []
        orig = real.q
        real.q = lambda sql, params=None: sql_calls.append((sql, params)) or pd.DataFrame()
        try:
            real.share_report.__wrapped__("Biscuits", weeks, compare, retailer)
        finally:
            real.q = orig
        got = run(*sql_calls[0]).set_index("BRAND").sort_index()
        ref = an.share_report(b, weeks, compare, retailer).set_index("BRAND").sort_index()
        for col in ["SHARE", "SHARE_CHG_PTS", "RANK", "RANK_CHG", "SALES", "SALES_GROWTH_PCT", "ACV", "PRICE_INDEX",
                    "VELOCITY", "TDP_SHARE", "FAIR_SHARE_INDEX"]:
            assert np.allclose(got[col].astype(float), ref[col].astype(float), rtol=1e-6, atol=1e-6), (weeks, compare, col)
