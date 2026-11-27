"""Local demo data for CHIPPY: lets both apps run on a laptop without Snowflake.

It replaces sr_ui.data (the only module that talks to Snowflake) with the sample data the project's UI tests use
(python/tests/test_ui_pages.py), extended so each sample shift has its own bridge, trend, flow and data checks.
Nothing here is real company data. Used only by demo_chippy.py and demo_chippy_admin.py.

Live mode (CHIPPY_MODE=live): sr_ui.data is left in place and reads Snowflake through a local Snowpark session made
from a connection in ~/.snowflake/config.toml (CHIPPY_CONNECTION, else the default connection). Ask Chippy then calls
the Cortex agents. Optional: CHIPPY_ROLE, CHIPPY_WAREHOUSE. No credentials are read or stored here.
"""
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]                   # the project folder
for p in (ROOT / "streamlit", ROOT / "python", ROOT / "python" / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import sr_ui  # noqa: E402
import test_ui_pages  # noqa: E402

_fake = test_ui_pages.build_fake()
_SH = _fake.shifts(None)
_BR = {"s1": (-0.61, -0.30, 0.05, 0.02), "s2": (0.62, 0.31, -0.04, 0.16), "s3": (-0.90, -0.60, -0.10, -0.10)}
_FLOW = {"s1": [("Golden Bake", 0.47), ("Tea Time", 0.20), ("Other brands", 0.17)],
         "s2": [("Crunchy", 0.58), ("Tea Time", 0.29), ("Other brands", 0.18)],
         "s3": [("Golden Bake", 0.82), ("Crunchy", 0.55), ("Other brands", 0.33)]}
_RULES = {"s1": [], "s2": [("R5_SPIKE", "MEDIUM", {"weeks": ["2026-10-31"], "source": "CORE.DT_CAT_WEEK"})],
          "s3": [("R2_FEED", "HIGH", {"retailer": "QuickShop", "source": "SRC.V_SRC_STORE_WEEK"})]}
_ORIG_WHERE = _fake.where


def _row(sid):
    return _SH[_SH.SHIFT_ID == sid].iloc[0].to_dict()


def _sid_for(brand):
    return _SH[_SH.BRAND == brand].SHIFT_ID.iloc[0]


def _shift(sid):
    r = _row(sid)
    return {**r, "RUN_ID": "r-0001", "D_SHARE": r["D_SHARE_PTS"] / 100, "ANOMALY_WEEKS": 3 if r["ANOMALY_CONFIRMED"] else 0,
            "MODE": "A", "STATUS": "OK", "NOTE": None}


def _bridge(sid):
    r, (d, v, p, pr) = _row(sid), _BR[sid]
    return {"SHIFT_ID": sid, "MODE": "A", "STATUS": "OK", "SH1": r["SH1"], "SH0": r["SH0"], "D_SHARE": r["D_SHARE_PTS"] / 100,
            "LMDI_WEIGHT": 0.2, "DIST_PTS": d, "VELOCITY_PTS": v, "PRICE_PTS": p, "PROMO_PTS": pr, "RESIDUAL_PTS": 1e-12,
            "DS1": 0.30, "DS0": 0.32, "PI1": 1.0, "PI0": 1.0, "PRI1": 1.1, "PRI0": 1.09, "NOTE": None}


def _where(sid):
    return _ORIG_WHERE(sid) if sid == "s1" else pd.DataFrame(columns=_ORIG_WHERE("s1").columns)


def _trend(market_id, category, brand, weeks=104):
    r = _row(_sid_for(brand))
    w = pd.date_range(end="2026-11-07", periods=104, freq="7D")
    path = np.linspace(100 * r["SH0"], 100 * r["SH1"], 104) + 0.5 * np.sin(2 * np.pi * np.arange(104) / 13)
    return pd.DataFrame({"WEEK_END_DATE": w, "VALUE_SHARE_PCT": path, "DIST_SHARE_PCT": path * 1.3})


def _flow(run_id, cmp_code, market_id, category, brand, direction):
    return pd.DataFrame(_FLOW[_sid_for(brand)], columns=["COUNTERPART", "FLOW_PTS"])


def _artefacts(run_id, cmp_code, market_id, category, brand):
    return pd.DataFrame([{"RULE_ID": a, "SEVERITY": b, "BRAND": None, "EVIDENCE": c} for a, b, c in _RULES[_sid_for(brand)]],
                        columns=["RULE_ID", "SEVERITY", "BRAND", "EVIDENCE"])


_fake.shift, _fake.bridge, _fake.where, _fake.trend = _shift, _bridge, _where, _trend
_fake.flow, _fake.artefacts = _flow, _artefacts


PREVIEW_NOTE = "Local preview · sample data · no Snowflake connection"
LIVE_NOTE = "Local app · live Snowflake data · Cortex agents"


def live() -> bool:
    return os.environ.get("CHIPPY_MODE", "").strip().lower() == "live"


_SESSION_LOCK = threading.Lock()


def _live_session():
    """One Snowpark session per process; sr_ui.data.session() finds it through get_active_session(). The lock stops two
    browser sessions that open at the same moment from each creating one: with two active sessions,
    get_active_session() fails and every query in the app errors until it restarts."""
    with _SESSION_LOCK:
        return _get_or_create_session()


def _get_or_create_session():
    from snowflake.snowpark import Session
    from snowflake.snowpark.context import get_active_session

    try:
        return get_active_session()
    except Exception:
        pass
    options = {}
    if os.environ.get("CHIPPY_CONNECTION"):
        options["connection_name"] = os.environ["CHIPPY_CONNECTION"]
    session = Session.builder.configs(options).create() if options else Session.builder.getOrCreate()
    if os.environ.get("CHIPPY_ROLE"):
        session.use_role(os.environ["CHIPPY_ROLE"])
    session.use_warehouse(os.environ.get("CHIPPY_WAREHOUSE", "SR_WH_XS"))
    return session


def _install_live() -> None:
    import streamlit as st

    try:
        _live_session()
    except Exception as e:                    # no silent fallback to sample data: say what failed and stop
        st.error("CHIPPY live mode could not connect to Snowflake. Check CHIPPY_CONNECTION (a connection name in "
                 f"~/.snowflake/config.toml) and CHIPPY_ROLE. Details: {e}")
        st.stop()
    from sr_ui import data
    data.AI_UNAVAILABLE_REASON = None


def _no_live_ai(*args, **kwargs):
    raise RuntimeError("Live Ask Chippy needs the Snowflake agent; it is not available in the local preview.")


def install() -> None:
    """Make every page read the sample data instead of Snowflake. The AI agent is not simulated: questions are refused
    with a clear notice, so no sample answer can be mistaken for a real one. In live mode, nothing is replaced."""
    if live():
        _install_live()
        return
    _fake.ask_agent = _no_live_ai
    _fake.AI_UNAVAILABLE_REASON = ("Live AI is unavailable in the local preview: no Snowflake session is connected, "
                                   "so Chippy cannot answer here.")
    import groq_agent                                         # Ask Chippy on Groq, when a key is configured locally
    if groq_agent.configured():
        _fake.ask_agent = groq_agent.ask_agent
        _fake.narrate = groq_agent.narrate
        _fake.chart_spec = groq_agent.chart_spec
        _fake.AI_UNAVAILABLE_REASON = None
        _fake.AI_PREVIEW_NOTE = (f"Local preview: answers come from {groq_agent.model()} on Groq, using tools over the "
                                 "sample data. In Snowflake, Ask Chippy uses the Cortex agents.")
    sys.modules["sr_ui.data"] = _fake
    sr_ui.data = _fake


def badge() -> None:
    """A small fixed label on every page, so the local preview is never mistaken for the live app."""
    import streamlit as st
    note = LIVE_NOTE if live() else PREVIEW_NOTE
    st.html('<style>[data-testid="stElementContainer"]:has(.sr-demo-badge){position:absolute;height:0;margin:0}</style>'
            '<div class="sr-demo-badge" style="position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:1000001;'
            'background:#fbefdf;color:#173f43;border:1px solid #c6a879;border-radius:999px;padding:3px 12px;'
            f'font:600 12px Inter,system-ui,sans-serif">{note}</div>')
