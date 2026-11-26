"""Insight Studio models (streamlit/sr_ui/analytics.py) and the Ask Chippy Auto rule (sr_ui/agent_router.py).

The synthetic panel in test_ui_pages.synthetic_panels() plants known truths: price elasticities per brand, a
distribution elasticity of 1.1, Crunchy losing distribution and Golden Bake gaining it over the last 10 weeks, and two
SKU anomalies. Each model must find what was planted.
"""
from __future__ import annotations

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
])
def test_auto_routes_each_question(question, agent):
    got, why = agent_router.route(question)
    assert got == agent and why


def test_auto_ties_go_to_chippy_and_only_allowed_agents():
    from sr_ui import data
    assert agent_router.route("")[0] == agent_router.CHIPPY == data.AGENT
    assert {agent_router.CHIPPY, agent_router.ANALYST} == set(data.AGENTS)     # the rule can only pick allowed agents
