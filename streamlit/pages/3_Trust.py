"""Data & Trust: golden set, reconciliation, bridge exactness, runs, cost, pipeline health, Signal Journey and the build
log (L11, L14). Failed checks first, in terracotta; technical detail in expanders. Reads and admin actions unchanged."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, nav

extra = nav.radar_header("Data & Trust", "Pipeline health, accuracy checks and run history")
run = data.current_run()
with extra:
    if nav.is_admin() and st.button("Check health now", icon=":material/monitor_heart:", key="sr_btn_health"):
        data.start_task("T_HEALTH")
        st.toast("Health check started; refresh in a minute.")

# Column headers for display only: values, order and the data behind them are unchanged.
HEADERS = {
    "CHECKED_AT": "Checked", "OBJECT_TYPE": "Type", "OBJECT_NAME": "Object", "STATE": "State", "DETAIL": "Detail",
    "QUESTION_ID": "Question", "QUESTION": "Text", "EXPECTED_TOOL": "Expected tool", "ACTUAL_TOOLS": "Tools used",
    "NOTE": "Note", "CHECK_ID": "Check", "DESCRIPTION": "Description", "REFERENCE_VALUE": "Reference",
    "SR_VALUE": "Share Radar", "ABS_DIFF": "Difference", "PASSED": "Passed", "TEST_ID": "Test", "FAILURES": "Failures",
    "RAN_AT": "Ran", "RUN_ID": "Run", "TRIGGER_TYPE": "Trigger", "AS_OF_WEEK": "Week", "STATUS": "Status",
    "BRIDGE_MODE": "Bridge", "N_CANDIDATES": "Candidates", "N_RANKED": "Ranked", "SECONDS": "Seconds",
    "CREDITS_EST": "Credits (est.)", "ERROR_MSG": "Error", "WAREHOUSE_CREDITS": "Warehouse credits",
    "AI_CREDITS": "AI credits", "AI_TOKENS": "AI tokens", "MODEL": "Model", "GENERATOR": "Generator",
    "COST_BASIS": "Basis", "USAGE_DATE": "Date", "SOURCE": "Source", "INTERFACE": "Interface", "CREDITS": "Credits",
    "TOKENS": "Tokens", "TICKET": "Ticket", "SURFACE": "Surface", "SESSIONS": "Sessions", "LINES_ADDED": "Lines added",
    "SESSIONS_WITH_TESTS": "With tests", "HUMAN_EDITS": "Human edits", "LAST_LOGGED": "Last logged",
}


def _fail_rows(df: pd.DataFrame, bad: pd.Series):
    """Failed rows tinted terracotta (display only)."""
    def shade(frame):
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        out.loc[bad[bad].index, :] = "background-color: rgba(200,121,112,0.14)"
        return out
    return df.style.apply(shade, axis=None) if len(df) and bad.any() else df


def table(df: pd.DataFrame, bad: pd.Series | None = None) -> None:
    shown = _fail_rows(df, bad) if bad is not None else nav.striped(df)
    st.dataframe(shown, hide_index=True, width="stretch", column_config={c: HEADERS[c] for c in df.columns if c in HEADERS})


def _passed(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _when(v) -> str:
    return "" if v is None or pd.isna(v) else f"Last checked {pd.to_datetime(v):%d %b %H:%M}"


def tiles() -> None:
    ev, rc = data.eval_latest(), data.recon_latest()
    resid = data.bridge_residual_max(run.run_id) if run else None
    cost = data.run_cost(2)
    cards = []
    if len(ev):
        n_ok = int(_passed(ev.PASSED).sum())
        cards.append(("ok" if n_ok == len(ev) else "bad", "quiz", "Golden set", f"{n_ok} of {len(ev)} passed",
                      ("All questions passed" if n_ok == len(ev) else f"{len(ev) - n_ok} failed · see Validation")
                      + (f" · {_when(ev.EVALUATED_AT.max())}" if "EVALUATED_AT" in ev else "")))
    else:
        cards.append(("", "quiz", "Golden set", "–", "Not run yet"))
    if len(rc):
        n_ok = int(_passed(rc.PASSED).sum())
        cards.append(("ok" if n_ok == len(rc) else "bad", "balance", "Reconciliation", f"{n_ok} of {len(rc)} passed",
                      _when(rc.CHECKED_AT.max()) if "CHECKED_AT" in rc else "reference checks"))
    else:
        cards.append(("", "balance", "Reconciliation", "–", "No reference numbers loaded"))
    cards.append(("" if resid is None else ("ok" if resid < 1e-6 else "bad"), "functions", "Bridge exactness",
                  "–" if resid is None else f"{resid:.1e} pts", "Largest residual · must stay below 1e-6"))
    if len(cost):
        r = cost.iloc[0]
        exact = r.COST_BASIS == "EXACT"
        val = r.WAREHOUSE_CREDITS if exact else r.CREDITS_EST
        prev = cost.iloc[1] if len(cost) > 1 else None
        pv = None if prev is None else (prev.WAREHOUSE_CREDITS if prev.COST_BASIS == "EXACT" else prev.CREDITS_EST)
        cards.append(("", "payments", "Credits, last run", "–" if pd.isna(val) else f"{float(val):.3f}",
                      ("exact" if exact else "estimate") + ("" if pv is None or pd.isna(pv) else f" · {float(pv):.3f} previous run")))
    else:
        cards.append(("", "payments", "Credits, last run", "–", "No runs yet"))
    tones = [c[0] for c in cards]
    if "bad" in tones:
        nav.state("detective", f"{tones.count('bad')} check{' needs' if tones.count('bad') == 1 else 's need'} a look. "
                  "Failures are listed first under Validation.", 40, "bad")
    elif "ok" in tones:
        nav.state("success", "All checks passed for the latest run.", 40, "ok")
    st.html('<div class="sr-trust-tiles">' + "".join(
        f'<div class="sr-find-card sr-tt {tone}"><span class="sr-ico" aria-hidden="true">{icon}</span><div>'
        f'<span class="k">{escape(k)}{" ✓" if tone == "ok" else (" ⚠" if tone == "bad" else "")}</span><b>{escape(v)}</b>'
        f'<span class="n">{escape(n)}</span></div></div>' for tone, icon, k, v, n in cards) + "</div>")


def health() -> None:
    nav.section("Pipeline health", "The state of every task, dynamic table and procedure the weekly run needs.")
    h = data.health_latest()
    if h.empty:
        st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No health check yet.</div>')
        return
    bad = h[h.STATE != "OK"]
    st.caption(f"{len(h) - len(bad)} of {len(h)} objects healthy · {_when(h.CHECKED_AT.max())}")
    order = h.assign(_o=(h.STATE == "OK").astype(int)).sort_values(["_o", "OBJECT_TYPE", "OBJECT_NAME"])
    tone = {"OK": "ok", "WARN": "warn", "FAILED": "bad", "SKIPPED": ""}
    st.html('<div class="sr-health">' + "".join(
        f'<span class="sr-ctx-chip {tone.get(x.STATE, "warn")}" title="{escape(str(x.OBJECT_TYPE))}">'
        f'{escape(fmt.STATUS_CHIP.get(x.STATE, x.STATE))} · {escape(str(x.OBJECT_NAME))}</span>'
        for x in order.itertuples(index=False)) + "</div>")
    with st.expander("Technical details", icon=":material/code:"):
        table(h.assign(STATE=[fmt.STATUS_CHIP.get(s, s) for s in h.STATE]), bad=(h.STATE != "OK"))


def validation() -> None:
    nav.section("Validation results", "Failed checks first, in terracotta.")
    ev = data.eval_latest()
    st.html('<p class="sr-c-h" id="golden-set">Golden set</p>')
    if ev.empty:
        st.caption("Not run yet: python3 eval/run_eval.py --connection sr")
    else:
        ok = _passed(ev.PASSED)
        if ok.all():
            st.success(f"All {len(ev)} questions passed (run {ev.EVAL_RUN_ID.iloc[0][:8]}).", icon=":material/check_circle:")
        else:
            failed = ev[~ok]
            table(failed[["QUESTION_ID", "QUESTION", "EXPECTED_TOOL", "ACTUAL_TOOLS", "NOTE"]], bad=pd.Series(True, index=failed.index))
        with st.expander(f"All {len(ev)} questions", icon=":material/list:"):
            table(ev[["QUESTION_ID", "QUESTION", "EXPECTED_TOOL", "ACTUAL_TOOLS", "PASSED", "NOTE"]], bad=~ok)
    st.html('<p class="sr-c-h">Reconciliation to NIQ reference numbers</p>')
    rc = data.recon_latest()
    if len(rc):
        srt = rc.assign(_o=_passed(rc.PASSED).astype(int)).sort_values("_o").drop(columns="_o")
        table(srt, bad=~_passed(srt.PASSED))
    else:
        st.caption("No reference numbers loaded.")
    st.html('<p class="sr-c-h">Latest SQL test run</p>')
    t = data.tests_latest()
    if t.empty:
        st.caption("Not run yet: snow sql -f tests/sql/run_all.sql -c sr")
    else:
        ok = _passed(t.PASSED)
        st.caption(f"{int(ok.sum())} of {len(t)} tests passed · {_when(t.RAN_AT.max())}")
        srt = t.assign(_o=ok.astype(int)).sort_values("_o")
        table(srt[["TEST_ID", "PASSED", "FAILURES", "RAN_AT"]], bad=~_passed(srt.PASSED))


def runs() -> None:
    nav.section("Run history", "The last 20 weekly runs, newest first. Pick a run for its step timeline.")
    r = data.runs(20)
    if r.empty:
        st.caption("No runs yet.")
        return
    flt = st.radio("Show", ["All", "Failed", "Skipped"], horizontal=True, key="sr_trust_runs", label_visibility="collapsed")
    v = r if flt in (None, "All") else r[r.STATUS == flt.upper()]
    if v.empty:
        st.html(f'<div class="sr-empty"><span class="sr-ico" aria-hidden="true">check_circle</span>No {flt.lower()} runs.</div>')
    else:
        table(v.assign(STATUS=[fmt.RUN_CHIP.get(s, s) for s in v.STATUS])[
            ["RUN_ID", "TRIGGER_TYPE", "AS_OF_WEEK", "STATUS", "BRIDGE_MODE", "N_CANDIDATES", "N_RANKED", "SECONDS",
             "CREDITS_EST", "ERROR_MSG"]], bad=v.STATUS.isin(["FAILED"]))
    st.html('<p class="sr-c-h">Step timeline of a run</p>')
    with st.container():
        pick = st.selectbox("Step timeline of run", list(r.RUN_ID), format_func=lambda i: i[:8], width=220,
                            label_visibility="collapsed")
        steps = data.step_log(pick)
        if len(steps):
            steps = steps.assign(ENDED_AT=steps.ENDED_AT.fillna(pd.Timestamp.now(tz=steps.STARTED_AT.dt.tz)))
            st.altair_chart(charts.step_timeline(steps), width="stretch")


def cost() -> None:
    nav.section("Credit trend", "Daily credits from the cost snapshot, where it has data.")
    d = data.cost_daily()
    if len(d) and {"USAGE_DATE", "CREDITS"} <= set(d.columns):
        daily = d.groupby("USAGE_DATE", as_index=True)["CREDITS"].sum().sort_index()
        st.area_chart(daily, height=180, color="#1E5556")
    else:
        st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No cost data yet. Exact daily costs '
                "appear after CALL SR_DB.OPS.SP_COST_SNAPSHOT(14) (needs account usage access).</div>")
    st.html('<p class="sr-c-h">Cost and tokens per run</p>')
    c = data.run_cost(10)
    table(c) if len(c) else st.caption("No runs yet.")
    if len(d):
        st.html('<p class="sr-c-h">Daily cost snapshot</p>')
        table(d)


def built_with() -> None:
    log = data.coco_log()
    if log.empty:
        st.caption("Session log not loaded yet: python3 scripts/coco_log.py --event flush")
        return
    st.caption(f"{log.TICKET.nunique()} tickets with a session record · {int(log.LINES_ADDED.fillna(0).sum()):,} lines added · "
               f"{int(log.SESSIONS_WITH_TESTS.sum())} sessions wrote tests")
    table(log)


def journey() -> None:
    from sr_ui.signal_journey_view import signal_journey
    if run is not None:
        signal_journey(run)


def _in_card(key: str, render) -> None:
    with nav.card(key):
        render()


nav.guarded("Tiles", tiles)
TABS = {"Overview": ":material/monitor_heart:", "Validation": ":material/fact_check:", "Run History": ":material/history:",
        "Cost & Usage": ":material/payments:"}
if st.session_state.get("sr_trust_tab") not in TABS:
    st.session_state.sr_trust_tab = "Overview"
with st.container(key="sr_tabs"):                                # the same underline tab bar as Shift Detail
    tab = st.radio("Section", list(TABS), key="sr_trust_tab", horizontal=True, label_visibility="collapsed",
                   format_func=lambda v: f"{TABS[v]} {v}") or "Overview"
if tab == "Overview":
    nav.guarded("Pipeline health", lambda: _in_card("health", health))
    nav.guarded("Signal journey", journey)
elif tab == "Validation":
    nav.guarded("Validation", lambda: _in_card("validation", validation))
elif tab == "Run History":
    nav.guarded("Runs", lambda: _in_card("runs", runs))
else:
    nav.guarded("Cost", lambda: _in_card("cost", cost))
with st.expander("Built with a coding agent (build log)", icon=":material/code_blocks:"):
    nav.guarded("Build log", built_with)