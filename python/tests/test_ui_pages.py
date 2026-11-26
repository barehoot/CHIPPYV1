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
            "MIN_SHARE_PTS": 0.3, "NOTIFY_EMAILS": ["a@x.com"], "NOTIFY_ALLOWED": ["a@x.com"]}


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