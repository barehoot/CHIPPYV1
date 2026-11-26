"""Smoke tests: every page of both apps runs headless (streamlit.testing AppTest) against a fake data module.

They catch errors in page code that only show at run time: a wrong column, a bad chart spec, a missing key.
No section may fall back to "Couldn't load ...", and the admin-only parts appear only in the admin app.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from sr_lib.render import render_html  # noqa: E402
from cases import GOOD_LLM, PACK  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[2] / "streamlit"
TS = pd.Timestamp("2026-11-09 06:00:00+00:00")

SETTINGS = {"AS_OF_WEEK_END": "2026-11-07", "SCOPE_CATEGORY": "Biscuits", "SCOPE_PARENT_MARKET": "M0",
            "FOCUS_MANUFACTURER": "Acme Foods", "CURRENCY": "INR", "DISPLAY_ALIAS": False, "TOP_N": 5,
            "MIN_SHARE_PTS": 0.3, "MIN_Z": 2.0, "EW_PRICE_RISE": 0.03, "NOTIFY_EMAILS": ["a@x.com"], "NOTIFY_ALLOWED": ["a@x.com"]}


PANEL_BRANDS = {  # brand -> (manufacturer, base price, price elasticity, base units) — invented sample brands
    "Crunchy": ("Acme Foods", 20.0, -1.9, 900), "Golden Bake": ("Rival Co", 18.0, -2.2, 700),
    "Tea Time": ("Tea Co", 15.0, -1.6, 500), "Nutri Crisp": ("Acme Foods", 22.0, -2.4, 300),
    "Store Brand": ("Private Label", 12.0, -1.4, 450)}
PANEL_RETAILERS = {"East Retail": ("M1", "East"), "North Retail": ("M2", "North"), "South Retail": ("M3", "South"),
                   "West Retail": ("M4", "West")}


def synthetic_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(brand panel, Crunchy SKU panel) for Insight Studio: 104 weeks x 4 retailers x 5 brands with known price
    elasticities and distribution response (units ~ price^e x ACV^1.1), promotions, a season, Crunchy losing
    distribution and Golden Bake gaining it over the last 10 weeks, and two planted SKU anomalies. Fixed seed. The
    derived columns repeat data.brand_panel's and data.sku_week_panel's SQL so the fake has the same shape."""
    global _PANELS
    if "_PANELS" in globals():
        return _PANELS
    rng = np.random.default_rng(65)
    weeks = pd.date_range(end="2026-11-07", periods=104, freq="7D")
    rows = []
    for retailer, (mid, region) in PANEL_RETAILERS.items():
        r_scale = rng.uniform(0.8, 1.2)
        for brand, (mfr, p0, el, u0) in PANEL_BRANDS.items():
            for t, wk in enumerate(weeks):
                late = max(0, t - 93) / 10                                  # 0 before the last 10 weeks, then up to 1
                acv = {"Crunchy": 82 - 20 * late, "Golden Bake": 70 + 12 * late}.get(brand, 76) + rng.normal(0, 1.2)
                promo = rng.random() < 0.12
                price = p0 * (1 + 0.0004 * t) * (0.85 if promo else 1.0) * rng.normal(1, 0.01)
                season = 1 + 0.08 * np.sin(2 * np.pi * t / 52)
                units = u0 * r_scale * season * (price / p0) ** el * (acv / 80) ** 1.1 * rng.lognormal(0, 0.05)
                rows.append({"WEEK_END_DATE": wk, "MARKET_ID": mid, "RETAILER": retailer, "REGION": region,
                             "MANUFACTURER": mfr, "BRAND": brand, "VALUE_SALES": units * price, "UNIT_SALES": units,
                             "VOLUME_SALES": units * 0.25, "ACV_DIST_PCT": min(acv, 99.0),
                             "STORES_SELLING": int(round(acv * 1.6)), "SKUS_SELLING": 4 if brand != "Store Brand" else 2})
    b = pd.DataFrame(rows)
    g = b.groupby(["WEEK_END_DATE", "MARKET_ID"])
    b["VALUE_SHARE_PCT"] = 100 * b.VALUE_SALES / g.VALUE_SALES.transform("sum")
    b["PRICE_PER_UNIT"] = b.VALUE_SALES / b.UNIT_SALES
    b["PRICE_INDEX"] = b.PRICE_PER_UNIT / (g.VALUE_SALES.transform("sum") / g.UNIT_SALES.transform("sum"))
    sk = []
    for r in b[b.BRAND == "Crunchy"].itertuples(index=False):
        for i, w in zip(range(1, 5), (0.2, 0.25, 0.25, 0.3)):
            v = r.VALUE_SALES * w * rng.lognormal(0, 0.04)
            u = r.UNIT_SALES * w * rng.lognormal(0, 0.04)
            sk.append({"WEEK_END_DATE": r.WEEK_END_DATE, "RETAILER": r.RETAILER, "REGION": r.REGION,
                       "PRODUCT_ID": f"P{i}", "ITEM_DESC": f"Crunchy {i}00g", "SEGMENT": "Chips", "PACK_SIZE": f"{i}00g",
                       "VALUE_SALES": v, "UNIT_SALES": u, "ACV_DIST_PCT": r.ACV_DIST_PCT - 2 * i,
                       "STORES_SELLING": r.STORES_SELLING})
    k = pd.DataFrame(sk)
    k = k[k.WEEK_END_DATE > weeks[-53]].reset_index(drop=True)
    spike = (k.WEEK_END_DATE == weeks[-6]) & (k.RETAILER == "North Retail") & (k.ITEM_DESC == "Crunchy 300g")
    k.loc[spike, ["VALUE_SALES", "UNIT_SALES"]] *= 3.2                     # planted: a feed spike
    gap = (k.WEEK_END_DATE == weeks[-3]) & (k.RETAILER == "West Retail") & (k.ITEM_DESC == "Crunchy 100g")
    k.loc[gap, "ACV_DIST_PCT"] = 12.0                                      # planted: a distribution gap
    k["PRICE_PER_UNIT"] = k.VALUE_SALES / k.UNIT_SALES
    k = k.sort_values(["RETAILER", "PRODUCT_ID", "WEEK_END_DATE"])
    gk = k.groupby(["RETAILER", "PRODUCT_ID"])
    k["SALES_WOW"] = k.VALUE_SALES / gk.VALUE_SALES.shift() - 1
    k["PRICE_WOW"] = k.PRICE_PER_UNIT / gk.PRICE_PER_UNIT.shift() - 1
    k["ACV_WOW"] = k.ACV_DIST_PCT - gk.ACV_DIST_PCT.shift()
    k["UNITS_PER_STORE"] = k.UNIT_SALES / k.STORES_SELLING
    _PANELS = (b, k.sort_values(["WEEK_END_DATE", "RETAILER", "ITEM_DESC"]).reset_index(drop=True))
    return _PANELS


def synthetic_ladder() -> pd.DataFrame:
    """Price per unit by brand and pack for the last 4 weeks of the synthetic panel: each brand's sales split over its
    packs, bigger packs dearer per unit but cheaper per gram (the same shape as data.price_ladder)."""
    b = synthetic_panels()[0]
    last = b[b.WEEK_END_DATE > b.WEEK_END_DATE.max() - pd.Timedelta(weeks=4)].groupby(["BRAND", "MANUFACTURER"])[
        ["VALUE_SALES", "UNIT_SALES"]].sum()
    rows = []
    for (brand, mfr), r in last.iterrows():
        packs = [("200g", 1.0, 0.6), ("400g", 1.75, 0.4)] if brand == "Store Brand" else \
            [("100g", 0.55, 0.2), ("200g", 1.0, 0.3), ("300g", 1.4, 0.25), ("400g", 1.75, 0.25)]
        base = r.VALUE_SALES / r.UNIT_SALES
        for pack, mult, w in packs:
            units = r.UNIT_SALES * w
            rows.append({"BRAND": brand, "MANUFACTURER": mfr, "PACK_SIZE": pack, "UNIT_SALES": units,
                         "VALUE_SALES": units * base * mult, "PRICE_PER_UNIT": base * mult})
    return pd.DataFrame(rows)


# data.promo_index for the fake: a fixed table (the synthetic panel has no base sales to derive it from)
PROMO_FIXTURE = pd.DataFrame({"BRAND": list(PANEL_BRANDS), "MANUFACTURER": [v[0] for v in PANEL_BRANDS.values()],
                              "PROMO_INDEX": [0.94, 1.18, 1.01, 0.88, 0.97],
                              "PROMO_INDEX_BEFORE": [1.03, 1.04, 0.99, 0.90, 0.98]})


def _share_report_ref(weeks, compare, retailer, measure="value"):
    """data.share_report for the fake: the pandas reference (analytics.share_report) on the synthetic panel, which the
    SQL mirrors."""
    from sr_ui import analytics
    return analytics.share_report(synthetic_panels()[0], int(weeks), compare, retailer, measure)


def _cv_ref(name, *args):
    """data.competitive_share_week / competitive_regions for the fake: their pandas references on the synthetic panel."""
    from sr_ui import analytics
    return getattr(analytics, name)(synthetic_panels()[0], *args)


def build_fake():
    import sr_ui.data as real
    fake = types.ModuleType("sr_ui.data")
    for k in ("Run", "Busy", "EDITABLE", "validate_setting", "TASKS", "STARTABLE", "TTL_S", "BUSY_MIN", "AGENT", "AGENTS"):
        setattr(fake, k, getattr(real, k))
    run = real.Run("r-0001", "REPLAY", date(2026, 11, 7), "Biscuits|M0|Acme Foods", "SUCCEEDED", "A", 12, 2, "b-0001",
                   0.42, TS, TS + pd.Timedelta(minutes=3), None)
    prev = real.Run("r-0000", "REPLAY", date(2026, 10, 31), "Biscuits|M0|Acme Foods", "SUCCEEDED", "A", 10, 2, "b-0000",
                    0.40, TS - pd.Timedelta(days=7), TS - pd.Timedelta(days=7, minutes=-3), None)
    shifts = pd.DataFrame({
        "SHIFT_ID": ["s1", "s2", "s3"], "RANK_NO": [1, 2, 3], "CMP_CODE": ["L4W_VS_YA", "L12W_VS_YA", "L4W_VS_YA"],
        "MARKET_ID": ["M0", "M1", "M2"], "CATEGORY": ["Biscuits"] * 3, "MANUFACTURER": ["Acme Foods", "Rival Co", "Tea Co"],
        "BRAND": ["Crunchy", "Golden Bake", "Tea Time"], "IS_FOCUS": [True, False, False], "SH1": [0.2341, 0.121, 0.08],
        "SH0": [0.2425, 0.1105, 0.097], "D_SHARE_PTS": [-0.84, 1.05, -1.7], "VALUE_AT_STAKE": [-1834220.5, 2290000.0, -900000.0],
        "Z_SCORE": [-3.1, 2.4, None], "ANOMALY_CONFIRMED": [True, False, False], "CONFIDENCE": [1.0, 0.8, 0.5],
        "ARTEFACT_LABEL": ["MARKET_MOVE", "MIXED", "POSSIBLE_DATA_EFFECT"], "SCORE": [2.7e6, 1.1e6, 1.3e5],
        "SUPPRESSED": [False, False, False], "SUPPRESS_REASON": [None, None, "Held back for data checks"],
        "SELECTED": [True, True, False]})
    detail = {**shifts.iloc[0].to_dict(), "RUN_ID": "r-0001", "D_SHARE": -0.0084, "ANOMALY_WEEKS": 3, "MODE": "A",
              "STATUS": "OK", "NOTE": None}
    bridge = {"SHIFT_ID": "s1", "MODE": "A", "STATUS": "OK", "SH1": 0.2341, "SH0": 0.2425, "D_SHARE": -0.0084,
              "LMDI_WEIGHT": 0.238, "DIST_PTS": -0.61, "VELOCITY_PTS": -0.30, "PRICE_PTS": 0.05, "PROMO_PTS": 0.02,
              "RESIDUAL_PTS": 1e-12, "DS1": 0.30, "DS0": 0.32, "PI1": 1.0, "PI0": 1.0, "PRI1": 1.1, "PRI0": 1.09, "NOTE": None}
    where = pd.DataFrame({"METHOD": ["EXACT_RETAILER"] * 3 + ["TOP_INSIGHTS"], "RANK_NO": [1, 2, 3, 1],
                          "CONTRIBUTOR": ["MegaMart", "QuickShop", "Rest of market", "MegaMart and 500g"],
                          "PERF_PTS": [-0.40, -0.25, 0.05, None], "MIX_PTS": [-0.12, -0.05, -0.07, None],
                          "TOTAL_PTS": [-0.52, -0.30, -0.02, None], "METRIC_CONTROL": [None] * 3 + [1e6],
                          "METRIC_TEST": [None] * 3 + [8e5], "CONTRIBUTION": [None] * 3 + [-2e5],
                          "RELATIVE_CONTRIBUTION": [None] * 3 + [0.6], "GROWTH_RATE": [None] * 3 + [-0.2]})
    weeks = pd.date_range(end="2026-11-07", periods=104, freq="7D")
    wave = np.sin(2 * np.pi * np.arange(104) / 13)
    trend = pd.DataFrame({"WEEK_END_DATE": weeks, "VALUE_SHARE_PCT": 24.0 + 0.8 * wave - 0.01 * np.arange(104),
                          "DIST_SHARE_PCT": 31.0 + 0.5 * wave})
    sales = pd.DataFrame({"WEEK_END_DATE": weeks, "VALUE_SALES": 50000 + 4000 * wave, "UNIT_SALES": 9000 + 600 * wave,
                          "SKUS_SELLING": 4})
    rnames = ["East", "North", "South", "West"]
    regions = pd.DataFrame({"REGION": rnames, "RETAILER": [f"{r} Retail" for r in rnames],
                            "MARKET_ID": ["M1", "M2", "M3", "M4"], "MARKET_NAME": [f"{r} Retail" for r in rnames],
                            "VALUE_SALES": [19000.0, 21300.0, 19800.0, 18700.0],
                            "VALUE_SALES_BEFORE": [30100.0, 29800.0, 29000.0, 29800.0],
                            "CAT_VALUE_SALES": [467000.0, 465000.0, 468000.0, 463000.0],
                            "CAT_VALUE_SALES_BEFORE": [470000.0, 466000.0, 469000.0, 464000.0],
                            "SKUS_SELLING": [4, 4, 4, 4], "STORES_SELLING": [120, 140, 110, 100], "BRANDS": [15] * 4})
    skus = pd.DataFrame([{"REGION": r, "RETAILER": f"{r} Retail", "MARKET_ID": f"M_{r}", "PRODUCT_ID": f"P{i}",
                          "ITEM_DESC": f"Crunchy {i}00g", "SEGMENT": "Chips", "PACK_SIZE": f"{i}00g",
                          "VALUE_SALES": 4000.0 + 300 * i, "VALUE_SALES_BEFORE": 6000.0 + 100 * i, "ACV_DIST_PCT": 70.0 + i}
                         for r in rnames for i in range(1, 5)])
    shares = pd.DataFrame([{"WEEK_END_DATE": w, "BRAND": b, "MANUFACTURER": "Acme Foods", "VALUE_SHARE_PCT": v}
                           for w in weeks[-26:] for b, v in (("Crunchy", 23.4), ("Golden Bake", 12.1), ("Tea Time", 8.0))])
    steps = pd.DataFrame({"STEP_NO": [1, 2, 4], "STEP": ["OPEN", "CAPABILITY", "DETECT"], "STATUS": ["OK", "OK", "WARN"],
                          "STARTED_AT": [TS, TS, TS], "ENDED_AT": [TS + pd.Timedelta(seconds=s) for s in (1, 3, 9)],
                          "ROWS_WRITTEN": [None, None, 40], "MESSAGE": [None, None, "L52W_VS_YA needs 104 weeks"],
                          "SECONDS": [1, 3, 9]})
    brief = {"BRIEF_ID": "b-0001", "RUN_ID": "r-0001", "SCOPE_KEY": "Biscuits|M0|Acme Foods", "AS_OF_WEEK": date(2026, 11, 7),
             "STATUS": "PUBLISHED", "GENERATOR": "LLM_RETRY", "MODEL": "model-b", "HEADLINE": "Acme Foods lost ground",
             "BODY_MD": "# x", "BODY_HTML": render_html(GOOD_LLM, PACK, "INR"), "LLM_JSON": GOOD_LLM,
             "VIOLATIONS": [{"attempt": 1, "model": "model-a",
                             "violations": [{"code": "V03_RAW_NUMBER", "path": "shifts[0].why", "detail": "raw number '0.61'"}]},
                            {"attempt": 2, "model": "model-b", "violations": []}],
             "TOKENS_IN": 1200, "TOKENS_OUT": 300, "PUBLISHED_AT": TS, "NOTIFIED_AT": TS, "NOTIFY_ATTEMPTS": 1}
    facts = pd.DataFrame([{"FACT_ID": k, "V": f["v"], "UNIT": f["u"], "DECIMALS": f["d"], "SOURCE": f["src"]}
                          for k, f in PACK["facts"].items()])
    calls = []
    fns = {
        "cfg": lambda k: SETTINGS.get(k), "scope_key": lambda: "Biscuits|M0|Acme Foods", "viewer_name": lambda: None,
        "aliases": lambda: {("BRAND", "Crunchy"): "Brand A"}, "market_names": lambda: {"M0": "All India", "M1": "Store 24", "M2": "QuickShop"},
        "total_market_name": lambda market_id: "All India" if market_id == "M0" else None,
        "current_run": lambda: run, "latest_attempt": lambda: run, "active_run": lambda: None,
        "run_started_since": lambda since: run, "step_log": lambda rid: steps,
        "task_last_run": lambda t: {"STATE": "SUCCEEDED", "ERROR_MESSAGE": None},
        "shifts": lambda rid: shifts,
        "held_back": lambda rid: shifts[~shifts.SELECTED][["SHIFT_ID", "CMP_CODE", "MARKET_ID", "BRAND", "D_SHARE_PTS", "SCORE"]].assign(RULES=[["R2_FEED"]]),
        "watchlist": lambda rid: pd.DataFrame({"MARKET_ID": ["M0"], "CATEGORY": ["Biscuits"], "BRAND": ["Crunchy"], "SIGNAL": ["DIST_DROP"],
                                               "LATEST_WEEK": [date(2026, 11, 7)], "LEVER_LATEST": [0.29], "LEVER_L4W": [0.315],
                                               "LEVER_CHG": [-0.081], "PROJECTED_SHARE_PTS": [-0.19], "ML_CONFIRMED": [True],
                                               "NOTE": ["Mechanical: if the latest week's distribution persists, other levers held; not a forecast"]}),
        "kpis": lambda rid: {"N_PASSED": 12, "N_SELECTED": 2, "N_DATA_EFFECT": 1, "VALUE_SELECTED": 4.1e6},
        "shift": lambda sid: detail, "bridge": lambda sid: bridge, "where": lambda sid: where,
        "flow": lambda *a: pd.DataFrame({"COUNTERPART": ["Golden Bake", "Tea Time"], "FLOW_PTS": [0.47, 0.2]}),
        "artefacts": lambda *a: pd.DataFrame({"RULE_ID": ["R5_SPIKE"], "SEVERITY": ["MEDIUM"], "BRAND": [None],
                                              "EVIDENCE": [{"weeks": ["2026-10-31"], "source": "CORE.DT_CAT_WEEK"}]}),
        "trend": lambda *a: trend, "brand_sales_week": lambda *a: sales, "region_summary": lambda *a, **k: regions,
        "sku_retailer": lambda *a, **k: skus, "brand_share_weeks": lambda *a, **k: shares,
        "brand_panel": lambda category, weeks=104: synthetic_panels()[0],
        "price_ladder": lambda category, weeks=4: synthetic_ladder(),
        "share_report": lambda category, weeks=4, compare="previous", retailer=None, measure="value":
            _share_report_ref(weeks, compare, retailer, measure),
        "competitive_share_week": lambda category, weeks=52, measure="value":
            _cv_ref("competitive_share_week", int(weeks), measure),
        "competitive_regions": lambda category, weeks=4, compare="previous", measure="value":
            _cv_ref("competitive_regions", int(weeks), compare, measure),
        "promo_index": lambda market_id, category, weeks=4, compare="previous": PROMO_FIXTURE.copy(),
        "portfolio": lambda rid: (lambda d: {"N_SHIFTS": len(d), "VALUE_LOSS": d.VALUE_AT_STAKE.clip(upper=0).sum(),
                                             "VALUE_GAIN": d.VALUE_AT_STAKE.clip(lower=0).sum(),
                                             "N_LOSS": int((d.VALUE_AT_STAKE < 0).sum()), "N_GAIN": int((d.VALUE_AT_STAKE > 0).sum()),
                                             "N_CONFIRMED": int(d.ANOMALY_CONFIRMED.fillna(False).astype(bool).sum()),
                                             "N_DATA_EFFECT": int((d.ARTEFACT_LABEL == "POSSIBLE_DATA_EFFECT").sum())}
                                  )(shifts[shifts.SELECTED]),
        "sku_week_panel": lambda category, brand, weeks=52: synthetic_panels()[1] if brand == "Crunchy"
        else synthetic_panels()[1].iloc[0:0],
        "ask_agent": lambda q, t=None, p=0, agent=None: calls.append(("ask", agent)) or {
            "text": "Answer", "tables": [], "tools": ["data_analyst"], "warnings": [], "thread_id": 1, "message_id": 2},
        "what_if": lambda *a: {"share_now_pts": 23.41, "share_if_pts": 24.9, "delta_pts": 1.49,
                                                          "assumption": "Other levers held constant; mechanical, not a forecast"},
        "briefs": lambda limit=12: pd.DataFrame([{k: brief[k] for k in ("BRIEF_ID", "RUN_ID", "AS_OF_WEEK", "HEADLINE", "GENERATOR",
                                                                        "MODEL", "PUBLISHED_AT", "NOTIFIED_AT", "NOTIFY_ATTEMPTS")}]),
        "brief": lambda bid: brief, "brief_facts": lambda bid: facts,
        "brief_notifications": lambda bid: pd.DataFrame({"CHANNEL": ["EMAIL"], "STATUS": ["SENT"], "SENT_AT": [TS], "MESSAGE": [None]}),
        "eval_latest": lambda: pd.DataFrame({"EVAL_RUN_ID": ["e1"] * 2, "QUESTION_ID": ["G01", "G29"], "QUESTION": ["q1", "q2"],
                                             "EXPECTED_TOOL": ["get_share_bridge", None], "ACTUAL_TOOLS": ['["get_share_bridge"]', "[]"],
                                             "PASSED": [True, False], "NOTE": ["", "stated figures"], "EVALUATED_AT": [TS, TS]}),
        "recon_latest": lambda: pd.DataFrame({"CHECK_ID": ["R01"], "DESCRIPTION": ["Category sales"], "REFERENCE_VALUE": [1e8],
                                              "SR_VALUE": [1.001e8], "ABS_DIFF": [1e5], "PASSED": [True], "CHECKED_AT": [TS]}),
        "bridge_residual_max": lambda rid: 3e-13,
        "runs": lambda limit=20: pd.DataFrame([{**{k.upper(): v for k, v in run.__dict__.items()}, "SECONDS": 180}]),
        "run_cost": lambda limit=10: pd.DataFrame({"RUN_ID": ["r-0001"], "TRIGGER_TYPE": ["REPLAY"], "AS_OF_WEEK": [date(2026, 11, 7)],
                                                   "STATUS": ["SUCCEEDED"], "SECONDS": [180], "CREDITS_EST": [0.42],
                                                   "WAREHOUSE_CREDITS": [None], "AI_CREDITS": [None], "AI_TOKENS": [1500],
                                                   "MODEL": ["model-b"], "GENERATOR": ["LLM_RETRY"], "COST_BASIS": ["ESTIMATE"]}),
        "coco_log": lambda: pd.DataFrame({"TICKET": ["SR-022"], "SURFACE": ["claude-code"], "SESSIONS": [1], "LINES_ADDED": [400],
                                          "SESSIONS_WITH_TESTS": [1], "HUMAN_EDITS": [0], "LAST_LOGGED": [TS]}),
        "tests_latest": lambda: pd.DataFrame({"TEST_ID": ["T-BR-01"], "PASSED": [True], "FAILURES": [0], "DETAIL": [None], "RAN_AT": [TS]}),
        "health_latest": lambda: pd.DataFrame({"CHECKED_AT": [TS], "OBJECT_TYPE": ["TASK"], "OBJECT_NAME": ["T_RUN_WEEK"],
                                               "STATE": ["OK"], "DETAIL": ['{"state": "started"}']}),
        "cost_daily": lambda days=14: pd.DataFrame(),
        "settings": lambda: pd.DataFrame({"SETTING_KEY": list(SETTINGS), "VALUE_JSON": [json.dumps(v) for v in SETTINGS.values()],
                                          "DESCRIPTION": [""] * len(SETTINGS), "UPDATED_AT": [TS] * len(SETTINGS)}),
        "start_task": lambda t: calls.append(("start", t)) or "2026-11-09 06:00:00.000 +0000",
        "reset_replay": lambda w: "AS_OF=2026-10-31", "save_setting": lambda k, v: calls.append(("save", k, v)),
        "clear_cache": lambda: None,
        "run_history": lambda limit=52: pd.DataFrame([{k.upper(): v for k, v in r.__dict__.items()} for r in (run, prev)]),
        "previous_week_run": lambda as_of_week: prev if str(as_of_week) > "2026-10-31" else None,
        "signal_journey": lambda rid: {"N_DETECTED": 31, "N_PASSED": 12, "N_RANKED": 12, "N_SELECTED": 2, "N_REPEAT": 4,
                                       "N_HELD": 1, "N_OTHER_CMP": 3, "N_BEYOND_TOP_N": 2},
    }
    for k, f in fns.items():
        setattr(fake, k, f)
    fake.calls = calls
    return fake


@pytest.fixture()
def fake_data(monkeypatch):
    import sr_ui
    fake = build_fake()
    monkeypatch.setitem(sys.modules, "sr_ui.data", fake)
    monkeypatch.setattr(sr_ui, "data", fake, raising=False)
    return fake


def _run(main: str, page: str | None = None) -> AppTest:
    at = AppTest.from_file(str(APP_DIR / main), default_timeout=30)
    at.run()
    if page:
        at.switch_page(page)
        at.run()
    return at


def _texts(at: AppTest) -> str:
    parts = [e.value for e in at.markdown] + [e.value for e in at.title] + [e.value for e in at.header] + \
            [e.value for e in at.subheader] + [e.value for e in at.caption] + [e.value for e in at.info] + \
            [e.value for e in at.warning] + [e.value for e in at.error] + [e.value for e in at.success]
    return "\n".join(str(p) for p in parts + [e.proto.body for e in at.get("html")])


@pytest.mark.parametrize("main", ["streamlit_app.py", "admin_app.py"])
@pytest.mark.parametrize("page,expect", [(None, "Detected Market Shifts"), ("pages/1_Shift_detail.py", "What moved share"),
                                         ("pages/2_Brief.py", "Brief"), ("pages/3_Trust.py", "Pipeline health")])
def test_every_page_renders(fake_data, main, page, expect):
    at = _run(main, page)
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert expect in text
    assert "Couldn't load" not in text, text


def test_replay_panel_only_in_admin(fake_data):
    ro, admin = _run("streamlit_app.py"), _run("admin_app.py")
    labels = lambda at: {b.label for b in at.button}  # noqa: E731
    assert "Load next week" not in labels(ro) and "Load next week" in labels(admin)


def test_settings_page_only_in_admin(fake_data):
    at = _run("admin_app.py", "pages/4_Settings.py")
    assert not at.exception and "Change a setting" in _texts(at)


def test_load_next_week_starts_the_replay_task(fake_data):
    at = _run("admin_app.py")
    next(b for b in at.button if b.label == "Load next week").click()
    at.run()
    assert ("start", "T_REPLAY_NEXT") in fake_data.calls


@pytest.mark.parametrize("view,expect", [("Forecast", "Backtest"), ("Statistics", "Trend, season and residual"),
                                         ("Map and stores", "Retailer stats"), ("SKUs and heatmaps", "SKU change")])
def test_shift_analysis_views_render(fake_data, view, expect):
    pytest.importorskip("statsmodels")
    at = AppTest.from_file(str(APP_DIR / "admin_app.py"), default_timeout=120)
    at.run()
    at.switch_page("pages/1_Shift_detail.py")
    at.session_state["shift_view"] = view
    if view == "Forecast":
        at.session_state["fc_models"] = ["ARIMA", "Holt-Winters"]          # keep the test fast; TCN is unit-tested
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert expect in text and "Couldn't load" not in text, text


def test_agent_picker_sends_the_selected_agent(fake_data):
    at = AppTest.from_file(str(APP_DIR / "streamlit_app.py"), default_timeout=30)
    at.run()
    at.switch_page("pages/5_Ask_Chippy.py")
    at.session_state["chat_agent"] = "SR_DB.SEM.RADAR_ANALYST_AGENT"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Open business questions" in _texts(at)
    at.chat_input[0].set_value("Top brands?").run()
    assert ("ask", "SR_DB.SEM.RADAR_ANALYST_AGENT") in fake_data.calls


# ---- Enterprise redesign (2026-11-25): Radar sections and the My workspace pages (session-only state) -------------

def test_radar_sections_present(fake_data):
    at = _run("streamlit_app.py")
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    sections = ["Market Movement Overview", "Market View", "Detected Market Shifts", "Market Momentum"]   # Signal Journey: Data & Trust (2026-11-26)
    assert all(section in text for section in sections)
    assert "Couldn't load" not in text
    assert {"Investigate shift", "Read brief"} <= {button.label for button in at.button}
    assert at.button(key="sr_radar_watch") and at.button(key="sr_radar_case")
    assert len(at.selectbox(key="sr_radar_week").options) == 2


def test_market_view_uses_scoped_national_result_and_keeps_data_checks(fake_data, monkeypatch):
    from sr_ui import market_view

    at = _run("streamlit_app.py")
    assert at.radio(key="sr_market_metric").value == "Movement"
    assert "Review data checks" in [popover.proto.popover.label for popover in at.get("popover")]
    assert at.button(key="sr_radar_held_s3")
    for mode, legend in [("Share", "Lower to higher share"), ("Value", "Negative to positive value")]:
        at.radio(key="sr_market_metric").set_value(mode).run()
        assert not at.exception and legend in _texts(at)

    run = fake_data.current_run()
    feature = market_view.market_feature(run)
    assert feature["id"] == "356" and feature["change"] == "-0.84 pts"
    assert feature["current"] == "23.4%" and "-0.19 pts projected" in feature["warning"]
    cfg = fake_data.cfg
    monkeypatch.setattr(fake_data, "cfg", lambda key: True if key == "DISPLAY_ALIAS" else cfg(key))
    assert market_view.market_feature(run)["brand"] == "Brand A"
    monkeypatch.setattr(fake_data, "total_market_name", lambda market_id: "Store 24")
    empty = market_view.market_feature(run)
    assert empty is None
    map_layer = market_view.map_spec(empty, "Movement", 0)["layer"][0]
    assert len(map_layer["layer"]) == 1
    countries = map_layer["data"]["values"]["objects"]["countries"]["geometries"]
    assert any(shape["properties"]["name"] == "India" for shape in countries)
    assert all(shape["properties"]["name"] != "Antarctica" for shape in countries)


@pytest.mark.parametrize("kind", ["ranked", "price", "empty"])
def test_radar_hero_early_warning_uses_ranked_run_results(fake_data, monkeypatch, kind):
    warnings = fake_data.watchlist("r-0001")
    if kind == "ranked":
        first = warnings.assign(BRAND="Golden Bake", MARKET_ID="M2", CATEGORY="Test category",
                                PROJECTED_SHARE_PTS=-0.28)
        warnings = pd.concat([first, warnings], ignore_index=True)
    elif kind == "price":
        warnings = warnings.assign(SIGNAL="PRICE_RISE", LEVER_CHG=0.04, PROJECTED_SHARE_PTS=None,
                                   NOTE="Share effect not projected (elasticity unknown)")
    else:
        warnings = warnings.iloc[:0]
    monkeypatch.setattr(fake_data, "watchlist", lambda run_id: warnings)

    at = _run("streamlit_app.py")
    assert not at.exception and "Couldn't load" not in _texts(at)
    hero = next(e.proto.body for e in at.get("html") if '<div class="sr-radar-hero-main">' in e.proto.body)
    assert "Pssst... I found something." in hero
    if kind == "empty":
        assert '<details class="sr-hero-warning">' not in hero
    elif kind == "price":
        assert "Price up 4.0%" in hero and "Not projected" in hero
        assert "Next 4 weeks" not in hero
    else:
        lead, remaining = hero.split('<div class="sr-hero-warning-more">', 1)
        assert "Early Warning &middot; 2" in lead
        assert "Golden Bake · " in lead and "Test category" in lead and "-0.28 pts" in lead
        assert '<details class="sr-hero-warning sr-hero-warning-secondary">' in remaining
        assert "Crunchy · " in remaining and "-0.19 pts" in remaining
        assert "Reporting week ending 7 Nov 2026" in hero
        assert "Next 4 weeks" in hero and "Crunchy is losing market share." in hero


def test_radar_assistant_docks_and_keeps_mock_conversation(fake_data):
    at = _run("streamlit_app.py")
    assert not any(button.key == "sr_radar_close" for button in at.button)
    launcher = at.button(key="sr_radar_open")
    assert launcher.label == "Ask Chippy AI"
    launcher.click().run()
    assert not at.exception
    assert '<div class="t">Ask Chippy AI</div>' in _texts(at)
    at.button(key="sr_fab_sugg_0").click().run()
    assert ("ask", fake_data.AGENT) in fake_data.calls
    at.button(key="sr_radar_close").click().run()
    assert not any(button.key == "sr_radar_close" for button in at.button)
    at.button(key="sr_radar_open").click().run()
    assert len(at.chat_message) == 2
    at.radio(key="sr_radar_chat_tab").set_value("History").run()
    assert len(at.chat_message) == 2


@pytest.mark.parametrize("main", ["streamlit_app.py", "admin_app.py"])
@pytest.mark.parametrize("page,expect", [("pages/6_Watchlist.py", "Nothing on your watchlist yet."),
                                         ("pages/7_Case_Files.py", "No open case files."),
                                         ("pages/8_Market_Time_Machine.py", "Signal journey that week")])
def test_workspace_pages_render_empty(fake_data, main, page, expect):
    at = _run(main, page)
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert expect in text and "Couldn't load" not in text, text
    if page != "pages/8_Market_Time_Machine.py":
        assert "Session only." in text                              # never presented as saved


def _seeded(page):
    from datetime import datetime
    at = AppTest.from_file(str(APP_DIR / "streamlit_app.py"), default_timeout=30)
    at.run()
    k = "Crunchy|M0|L4W_VS_YA"
    at.session_state["sr_ws"] = {
        "watch": {k: {"brand": "Crunchy", "market_id": "M0", "cmp_code": "L4W_VS_YA", "category": "Biscuits",
                      "run_id": "r-0001", "added": datetime(2026, 11, 25, 9, 0)}},
        "cases": {k: {"brand": "Crunchy", "market_id": "M0", "cmp_code": "L4W_VS_YA", "shift_id": "s1", "run_id": "r-0001",
                      "as_of_week": date(2026, 11, 7), "opened": datetime(2026, 11, 25, 9, 0), "reviewed": False,
                      "status": "Open", "notes": []}}}
    at.switch_page(page)
    at.run()
    return at


def test_watchlist_shows_this_week_and_since_last_week(fake_data):
    at = _seeded("pages/6_Watchlist.py")
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert "In the brief · rank 1" in text and "Since last week" in text and "31 Oct 2026" in text
    assert "Couldn't load" not in text


def test_case_file_steps_and_decision_hub(fake_data):
    at = _seeded("pages/7_Case_Files.py")
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert "Investigation" in text and "Decision hub" in text and "Evidence checked" in text
    assert "Couldn't load" not in text


# ---- Shift Detail investigation studio (Phase 4) ---------------------------------------------------------------

def test_investigation_sections_in_order(fake_data):
    at = _run("streamlit_app.py", "pages/1_Shift_detail.py")
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    order = ["Key investigation finding", "Historical trend", "What moved share", "Where it happened", "Who took it",
             "Evidence and data trust", "Data checks", "Scenario lab", "Ask Chippy about this shift"]
    missing = [t for t in order if t not in text]                 # AppTest groups text by element type: presence only
    assert not missing, missing
    assert "Couldn't load" not in text
    assert "Distribution · exact share bridge, mode A" in text and "-0.61 pts" in text   # compact findings (2026-11-26)


def test_scenario_lab_keeps_results_and_resets(fake_data):
    at = _run("streamlit_app.py", "pages/1_Shift_detail.py")
    next(b for b in at.button if b.label == "Run scenario").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    rows = at.dataframe[-1].value
    assert list(rows.Scenario) == ["Current", "Distribution to base level"] and rows["vs current"].iloc[1] == "+1.49 pts"
    next(b for b in at.button if b.label == "Reset scenarios").click()
    at.run()
    assert list(at.dataframe[-1].value.Scenario) == ["Current"]


def test_shift_detail_watchlist_and_ask_chippy_handoff(fake_data):
    at = _run("streamlit_app.py", "pages/1_Shift_detail.py")
    next(b for b in at.button if b.label == "Add to Watchlist").click()
    at.run()
    assert "Crunchy|M0|L4W_VS_YA" in at.session_state["sr_ws"]["watch"]
    ask = at.button(key="sr_sd_ask")
    assert ask.label == "Ask Chippy AI"
    ask.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.label.startswith("Why did Crunchy lose share in All India") for b in at.button)


def test_market_momentum_and_signal_journey_on_trust(fake_data):
    at = _run("streamlit_app.py")
    text = _texts(at)
    assert "Is market pressure building over time?" in text and "Signal Journey" not in text
    assert "Shifts past the gates" in text and "No earlier week stored" not in text      # two stored weeks in the fake
    trust = _run("streamlit_app.py", "pages/3_Trust.py")
    assert not trust.exception, [e.value for e in trust.exception]
    assert "Signal Journey" in _texts(trust) and "Couldn't load" not in _texts(trust)

def test_weekly_brief_report_keeps_sources(fake_data):
    at = _run("streamlit_app.py", "pages/2_Brief.py")
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    for part in ("Executive summary", "Finding", "Business impact", "Recommended action", "Ask next",
                 "Held back for data checks", "Early warnings"):
        assert part in text, part
    assert 'class="fact' in text and "title=" in text                      # every number keeps its source span
    assert "Couldn't load" not in text

def test_ask_chippy_welcome_then_thread(fake_data):
    at = _run("streamlit_app.py", "pages/5_Ask_Chippy.py")
    assert not at.exception, [e.value for e in at.exception]
    assert "What would you like to explore?" in _texts(at) and len([b for b in at.button if b.key.startswith("starter_")]) == 4
    next(b for b in at.button if b.key == "starter_3").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert ("ask", fake_data.AGENT) in fake_data.calls
    assert "What would you like to explore?" not in _texts(at)             # the welcome hides once a chat starts
    msgs = at.session_state["chats"][fake_data.AGENT]["msgs"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["text"] == "Answer"

# ---- SR-065: Insight Studio, the Ask Chippy agent picker, interval mascots, direct links ------------------------

def _studio(main: str = "streamlit_app.py") -> AppTest:
    at = AppTest.from_file(str(APP_DIR / main), default_timeout=120)
    at.run()
    at.switch_page("pages/1_Shift_detail.py")
    at.session_state["shift_view"] = "Studio"
    at.run()
    return at


def _clean(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    alerts = [w.value for w in at.warning] + [e.value for e in at.error]
    assert not alerts, alerts
    assert "Couldn't load" not in _texts(at)


def test_studio_every_lens_and_model_renders(fake_data):
    at = _studio()
    _clean(at)
    assert "Exploratory · not in the brief" in _texts(at) and "What to do" in _texts(at)   # Company Manager by default
    for lens, expect in [("director", "Board line"), ("amanager", "Priority list"), ("analyst", "Workbench"),
                         ("scientist", "**Method.**")]:
        at.session_state["studio_lens"] = lens
        at.run()
        _clean(at)
        assert expect in _texts(at), (lens, expect)
    for model in ["elasticity", "causal", "changepoint", "drivers", "segments", "anomaly", "cannibal"]:
        at.session_state["studio_model"] = model
        at.run()
        _clean(at)


def test_studio_workbench_chart_types(fake_data):
    at = _studio()
    at.session_state["studio_lens"] = "analyst"
    at.run()
    for kind in ["Line", "Bar", "Area", "Scatter", "Box", "Heatmap"]:
        at.session_state["wb_kind"] = kind
        at.run()
        _clean(at)
    at.session_state["wb_src"] = at.radio(key="wb_src").options[1]
    at.run()
    _clean(at)


def test_studio_save_to_case_file(fake_data):
    at = _studio()
    next(b for b in at.button if b.key == "sr_studio_case_mgr").click().run()
    _clean(at)
    cases = at.session_state["sr_ws"]["cases"]
    assert len(cases) == 1 and any("Decision brief" in n["text"] for c in cases.values() for n in c.get("notes", []))


def test_ask_chippy_auto_routes_and_offers_the_other_agent(fake_data):
    at = _run("streamlit_app.py", "pages/5_Ask_Chippy.py")
    assert {"sr_agent_pick_auto", "sr_agent_pick_chippy", "sr_agent_pick_analyst"} <= {b.key for b in at.button}
    next(b for b in at.button if b.key == "sr_agent_pick_auto").click().run()
    assert at.session_state["chat_agent"] == "AUTO" and not at.exception
    at.session_state["chat_agent"] = "AUTO"        # AppTest replays a radio's stale value after a callback set it
    at.run()
    at.chat_input[0].set_value("Which brands have the highest value share?").run()
    assert ("ask", "SR_DB.SEM.RADAR_ANALYST_AGENT") in fake_data.calls
    msg = at.session_state["chats"]["AUTO"]["msgs"][-1]
    assert msg["agent_id"] == "SR_DB.SEM.RADAR_ANALYST_AGENT" and "ranking" in msg["routed"]
    # The re-ask itself is checked in a browser: AppTest replays a stale radio value after the button's callback.
    other = at.button(key=f"sr_ask_other_{len(at.session_state['chats']['AUTO']['msgs']) - 1}")
    assert other.label == "Ask Chippy instead" and not at.exception


def test_floating_panel_asks_the_chosen_agent(fake_data):
    at = _run("streamlit_app.py", "pages/2_Brief.py")
    at.button(key="sr_radar_open").click().run()
    assert at.radio(key="sr_fab_agent").value == fake_data.AGENT
    at.radio(key="sr_fab_agent").set_value("SR_DB.SEM.RADAR_ANALYST_AGENT").run()
    assert not at.exception


def test_mascot_pulses_rest_and_vary_by_visit():
    from PIL import Image
    from sr_ui import nav
    for names in nav.PULSE_SETS.values():
        for n in names:
            im = Image.open(nav.PULSE_DIR / f"{n}.webp")
            assert im.size == (192, 192) and (nav.PULSE_DIR / f"{n}.png").exists()
            durations = []
            for i in range(im.n_frames):
                im.seek(i)
                im.load()
                durations.append(im.info.get("duration") or 0)
            assert max(durations) >= 5000, n                    # it rests for seconds between plays
    assert nav._pulse("investigating") is None                   # working states keep the live loop
    assert set(nav.PULSE_SETS["detective"]) == {"hero_mix", "detective", "think_mix"}


def test_entry_guard_is_on_every_page():
    for page in sorted((APP_DIR / "pages").glob("*.py")):
        assert f'nav.entry_guard("pages/{page.name}")' in page.read_text(encoding="utf-8"), page.name


def test_studio_masks_names_when_display_alias_is_on(fake_data, monkeypatch):
    real = list(PANEL_BRANDS) + sorted({m for m, *_ in PANEL_BRANDS.values()})
    alias = {**{("BRAND", b): f"Brand {chr(65 + i)}" for i, b in enumerate(PANEL_BRANDS)},
             **{("MANUFACTURER", m): f"Maker {i + 1}" for i, m in enumerate(sorted({m for m, *_ in PANEL_BRANDS.values()}))}}
    monkeypatch.setitem(SETTINGS, "DISPLAY_ALIAS", True)
    monkeypatch.setattr(fake_data, "aliases", lambda: alias)
    at = _studio()
    for lens in ["manager", "director", "amanager", "analyst", "scientist"]:
        at.session_state["studio_lens"] = lens
        at.run()
        _clean(at)
        shown = ""
        if lens == "analyst":                                       # also the manufacturer colour and the SKU source
            at.session_state["wb_colour"] = "MANUFACTURER"
            at.run()
            shown += " ".join(df.value.to_csv() for df in at.dataframe) + " ".join(str(e.proto) for e in at.get("plotly_chart"))
            at.session_state["wb_src"] = at.radio(key="wb_src").options[1]
            at.run()
            _clean(at)
        shown += " ".join(df.value.to_csv() for df in at.dataframe)
        shown += " ".join(str(e.proto) for e in at.get("plotly_chart"))
        leaked = [n for n in real if n in shown]
        assert not leaked, (lens, leaked)
        if lens in ("director", "analyst", "scientist"):
            assert "Brand A" in shown or "SKU 1" in shown, lens           # the check reads real chart and table content
    for model in ["anomaly", "segments", "cannibal", "elasticity"]:
        at.session_state["studio_model"] = model
        at.run()
        shown = " ".join(df.value.to_csv() for df in at.dataframe) + " ".join(str(e.proto) for e in at.get("plotly_chart"))
        assert not [n for n in real if n in shown], model
    for lens in ["early", "amanager"]:                                      # round 2 views
        at.session_state["studio_lens"] = lens
        at.run()
        _clean(at)
        shown = " ".join(df.value.to_csv() for df in at.dataframe) + " ".join(str(e.proto) for e in at.get("plotly_chart"))
        assert not [n for n in real if n in shown], lens
    at.switch_page("pages/2_Brief.py")
    for view in ["intel", "report"]:
        at.session_state["brief_view"] = view
        at.run()
        _clean(at)
        shown = _texts(at) + " ".join(df.value.to_csv() for df in at.dataframe)
        assert not [n for n in real if n in shown], view
    radar = _run("streamlit_app.py")
    radar.button(key="sr_btn_emerging_scan").click().run()
    shown = _texts(radar) + " ".join(df.value.to_csv() for df in radar.dataframe)
    assert not [n for n in real if n in shown] and "Brand A" in shown


def test_floating_panel_question_goes_to_the_chosen_agent(fake_data):
    at = _run("streamlit_app.py", "pages/2_Brief.py")
    at.button(key="sr_radar_open").click().run()
    at.session_state["sr_fab_agent"] = "SR_DB.SEM.RADAR_ANALYST_AGENT"
    at.run()
    next(b for b in at.button if (b.key or "").startswith("sr_fab_sugg_")).click().run()
    assert ("ask", "SR_DB.SEM.RADAR_ANALYST_AGENT") in fake_data.calls and not at.exception


# ---- SR-065 round 2: Intelligence brief, share report, emerging shifts, scenario, Ask this chart ------------------

def test_brief_views_render(fake_data):
    at = _run("streamlit_app.py", "pages/2_Brief.py")
    for view, expect in [("intel", "Executive summary"), ("report", "Competitive share report"), ("record", "Brief")]:
        at.session_state["brief_view"] = view
        at.run()
        _clean(at)
        assert expect in _texts(at), view
    at.session_state["brief_view"] = "intel"
    at.run()
    assert "Numbers are locked" in _texts(at)                               # the methods and sources table


def test_intelligence_brief_template_is_locked(fake_data):
    from sr_ui import intel
    run = fake_data.current_run()
    pk = intel.build_pack(run.run_id, "Biscuits", False, "INR", fake_data.market_names())
    secs, gen = intel.narrative(pk)
    assert gen.startswith("Template") and set(secs) == set(intel.OUTLINE)
    assert all(not intel.problems(t, pk) for t in secs.values()), {s: intel.problems(t, pk) for s, t in secs.items()}


def test_intelligence_brief_llm_sections_are_checked(fake_data, monkeypatch):
    from sr_ui import intel
    run = fake_data.current_run()
    pk = intel.build_pack(run.run_id, "Biscuits", False, "INR", fake_data.market_names())
    good = next(iter(pk.facts))
    monkeypatch.setattr(fake_data, "narrate", lambda facts, outline, draft=None, **k: {
        "Executive summary": f"Shifts in play: [{good}].", "What moved": "Crunchy lost 0.84 pts."}, raising=False)
    secs, gen = intel.narrative(pk)
    assert secs["Executive summary"] == f"Shifts in play: [{good}]."             # a clean LLM section is kept
    assert secs["What moved"] != "Crunchy lost 0.84 pts."                     # a typed number falls back
    assert "AI narrative" in gen and "from the template" in gen


def test_radar_shows_emerging_shifts(fake_data):
    at = _run("streamlit_app.py")
    _clean(at)
    assert "Emerging Shifts" in _texts(at) and "not in any report yet" not in _texts(at)    # on demand
    at.button(key="sr_btn_emerging_scan").click().run()
    _clean(at)
    assert "not in any report yet" in _texts(at)


def test_studio_emerging_lens_and_scenario(fake_data):
    at = _studio()
    at.session_state["studio_lens"] = "early"
    at.run()
    _clean(at)
    assert "Moves building now" in _texts(at)
    at.session_state["studio_lens"] = "manager"
    at.session_state["sc_price"], at.session_state["sc_dist"] = -5, 8
    at.run()
    _clean(at)
    assert "Chance sales rise" in _texts(at)


def test_ask_this_chart_builds_the_workbench(fake_data):
    at = _studio()
    at.session_state["studio_lens"] = "analyst"
    at.run()
    at.text_input(key="wb_ask").set_value("Golden Bake unit sales by retailer as bars, last 12 weeks")
    at.button(key="wb_ask_go").click().run()
    _clean(at)
    ss = at.session_state
    assert (ss["wb_kind"], ss["wb_x"], ss["wb_y"], ss["wb_brands"]) == ("Bar", "RETAILER", "UNIT_SALES", ["Golden Bake"])
    assert (ss["wb_weeks"][1] - ss["wb_weeks"][0]).days == 11 * 7


# ---- Competitive View ---------------------------------------------------------------------------------------------

CV = "pages/9_Competitive_View.py"
CV_VIEWS = {"Competitive Overview": ["Market share trends", "Share movement", "Competitor scorecard",
                                     "Positioning matrix", "Strategic interpretation", "Where each brand sits"],
            "Share Drivers": ["Competitive gap", "Performance assessment", "Strategic recommendation",
                              "Driver comparison"],
            "Opportunities & Risks": ["Regional competitive heatmap", "Opportunities", "Competitive threats",
                                      "Priority action plan", "Distribution gap, ACV points", "Share gained, points"]}
CV_ALWAYS = ["Competitive rank", "Lead over #2", "Distribution gap", "Here is how you stack up.", "Competitors gaining",
             "Opportunities"]


def test_competitive_view_sits_between_shift_detail_and_brief():
    from sr_ui import nav as _nav
    files = [f for f, *_ in _nav.PAGES]
    assert files.index("pages/1_Shift_detail.py") + 1 == files.index(CV) == files.index("pages/2_Brief.py") - 1
    assert next(t for f, t, *_ in _nav.PAGES if f == CV) == "Competitive View"


@pytest.mark.parametrize("main", ["streamlit_app.py", "admin_app.py"])
def test_competitive_view_every_tab_renders(fake_data, main):
    at = _run(main, CV)
    assert not at.exception, [e.value for e in at.exception]
    assert "Understand your position. Identify the gap." in _texts(at)
    assert not [e for e in CV_ALWAYS if e not in _texts(at)], [e for e in CV_ALWAYS if e not in _texts(at)]
    for view, expect in CV_VIEWS.items():
        at.session_state["cv_view"] = view
        at.run()
        assert not at.exception, (view, [e.value for e in at.exception])
        text = _texts(at)
        missing = [e for e in expect if e not in text]
        assert not missing and "Couldn't load" not in text, (view, missing)


@pytest.mark.parametrize("weeks,compare,measure", [(13, "previous", "volume"), (52, "year_ago", "value")])
def test_competitive_view_periods_and_share_basis(fake_data, weeks, compare, measure):
    at = _run("streamlit_app.py", CV)
    at.session_state["cv_weeks"], at.session_state["cv_compare"], at.session_state["cv_measure"] = weeks, compare, measure
    for view in CV_VIEWS:
        at.session_state["cv_view"] = view
        at.run()
        assert not at.exception, (view, [e.value for e in at.exception])
        assert "Couldn't load" not in _texts(at), view
    assert ("Volume share" if measure == "volume" else "Value share") in _texts(at)


def test_competitive_view_focus_and_competitors_follow_the_selection(fake_data):
    at = _run("streamlit_app.py", CV)
    assert at.session_state["cv_focus"] == "Crunchy"                     # the focus manufacturer's leading brand
    at.session_state["cv_focus"], at.session_state["cv_comp"] = "Golden Bake", ["Crunchy", "Store Brand"]
    at.run()
    matrix = at.dataframe[0].value
    assert list(matrix.columns) == ["Group", "Measure", "Golden Bake", "Crunchy", "Store Brand"]


def test_competitive_view_ask_chippy_handoff(fake_data):
    at = _run("streamlit_app.py", CV)
    at.button(key="cv_ask").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Crunchy" in at.session_state["sr_ask_about"]


def test_competitive_view_priority_plan_investigates_in_shift_detail(fake_data):
    at = _run("streamlit_app.py", CV)
    at.session_state["cv_view"] = "Opportunities & Risks"
    at.run()
    at.button(key="cv_inv_1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["shift_id"] and "What moved share" in _texts(at)


def test_competitive_view_suggested_question_opens_the_dock(fake_data):
    at = _run("streamlit_app.py", CV)
    label, prompt = at.button(key="cv_q_0").label, at.session_state["cv_suggestions"][0]
    assert "Crunchy" in label and len(label) < len(prompt) and "Crunchy" in prompt   # short label, full prompt
    at.button(key="cv_q_0").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["sr_radar_chat_open"] and ("ask", fake_data.AGENT) in fake_data.calls


def test_competitive_view_masks_names_when_display_alias_is_on(fake_data, monkeypatch):
    real = list(PANEL_BRANDS)
    alias = {**{("BRAND", b): f"Brand {chr(65 + i)}" for i, b in enumerate(PANEL_BRANDS)},
             **{("MANUFACTURER", m): f"Maker {i + 1}" for i, m in enumerate(sorted({m for m, *_ in PANEL_BRANDS.values()}))}}
    monkeypatch.setitem(SETTINGS, "DISPLAY_ALIAS", True)
    monkeypatch.setattr(fake_data, "aliases", lambda: alias)
    at = _run("streamlit_app.py", CV)
    for view in CV_VIEWS:
        at.session_state["cv_view"] = view
        at.run()
        assert not at.exception, (view, [e.value for e in at.exception])
        shown = _texts(at) + " ".join(df.value.to_csv() for df in at.dataframe) \
            + " ".join(str(e.proto) for e in at.get("arrow_vega_lite_chart"))
        assert not [n for n in real if n in shown], view
        assert "Brand A" in shown, view


def test_competitive_references_share_basis():
    from sr_ui import analytics
    panel = synthetic_panels()[0]
    val = analytics.competitive_share_week(panel, 8, "value")
    vol = analytics.competitive_share_week(panel, 8, "volume")
    assert val.groupby("WEEK_END_DATE").SHARE_PCT.sum().round(6).eq(100).all()
    assert vol.groupby("WEEK_END_DATE").SHARE_PCT.sum().round(6).eq(100).all()
    assert not np.allclose(val.SHARE_PCT, vol.SHARE_PCT)                 # volume share is not value share
    reg = analytics.competitive_regions(panel, 4, "previous", "value")
    assert reg.groupby("MARKET_ID").SHARE.sum().round(6).eq(100).all()
    assert analytics.share_report(panel, 4).SHARE.round(9).tolist() == \
        analytics.share_report(panel, 4, measure="value").SHARE.round(9).tolist()   # default unchanged
