"""Case Files (My workspace): structured investigations of shifts, with status filters, search, the five-step journey,
evidence, a session timeline and the Decision hub. Steps 1-3 are ticked only from the run's own results; steps 4-5,
notes and status are the viewer's, kept for this session only (sr_ui.workspace). Numbers come from data.py reads of the
run that detected the shift."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, nav, workspace

extra = nav.radar_header("Case Files", "Structured investigations of significant shifts")
cases = workspace.cases()
markets = data.market_names()
cur = data.cfg("CURRENCY") or ""
masked = data.cfg("DISPLAY_ALIAS") is True
st.html('<div class="sr-session-pill"><span class="sr-ico" aria-hidden="true">schedule</span><b>Session only.</b> '
        "Case files, notes and statuses last while this tab stays open; nothing is saved to Snowflake or shared.</div>")

if not cases:
    with st.container(key="sr_c_empty", horizontal=True, vertical_alignment="center", gap="small"):
        nav.mascot("resting", "No open case files.",
                   "On Radar, Shift Detail or Watchlist, press Open as Case File to start an investigation.", key="c_none")
        if st.button("Go to Radar", icon=":material/radar:", key="sr_c_radar"):
            st.switch_page("pages/0_Radar.py")
    nav.stop()

if st.session_state.pop("sr_case_new", False):
    nav.state("success", "Case file opened. Work through the steps below.", 36, "ok")
counts = {s_: sum(1 for c in cases.values() if c["status"] == s_) for s_ in workspace.STATUSES}
with st.container(key="sr_c_filters", horizontal=True, vertical_alignment="center", gap="small"):
    flt = st.radio("Status", ["All", *workspace.STATUSES], horizontal=True, key="sr_case_filter", label_visibility="collapsed",
                   format_func=lambda x: f"{x} {len(cases) if x == 'All' else counts[x]}", width="content")
    q = st.text_input("Search cases", key="sr_case_search", placeholder="Search brand or market", label_visibility="collapsed",
                      width=260)


def _label(k: str) -> str:
    c = cases[k]
    return f"{fmt.name(c['brand'])} · {markets.get(c['market_id'], c['market_id'])} · {c['status']}"


keys = [k for k, c in cases.items() if (flt in (None, "All") or c["status"] == flt)
        and (not q or q.lower() in _label(k).lower())]
if not keys:
    st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No case files match the filter.</div>')
    nav.stop()
if st.session_state.get("sr_case") not in keys:
    st.session_state["sr_case"] = keys[-1]

left, right = nav.stack("cases").columns([3, 9])
with left, st.container(key="sr_c_list"):
    st.html(f'<p class="sr-c-list-h">Cases · {len(keys)}</p>')
    k = st.radio("Case", keys, key="sr_case", format_func=_label, label_visibility="collapsed")
case = cases[k]
kid = list(cases).index(k)                            # widget keys: a number, not the brand|market|comparison key
s = data.shift(case["shift_id"])


def _sign(v) -> str:
    return "" if v is None or pd.isna(v) else ("neg" if float(v) < 0 else "pos")


def summary() -> str:
    b = data.bridge(case["shift_id"]) or {}
    return (f"{fmt.headline(s, markets)}. Movement {fmt.pts(s['D_SHARE_PTS'])} ({fmt.pct(s['SH0'])} → {fmt.pct(s['SH1'])}), "
            f"value at stake {fmt.money(s['VALUE_AT_STAKE'], cur)}, confidence {fmt.confidence(s['CONFIDENCE'])}, "
            f"{fmt.LABEL_CHIP.get(s['ARTEFACT_LABEL'], s['ARTEFACT_LABEL'])}. Bridge mode {b.get('MODE', '–')}. "
            f"Status: {case['status']}{', findings reviewed' if case['reviewed'] else ''}. "
            + " ".join(f"Note ({n['at']:%d %b %H:%M}): {n['text']}" for n in case["notes"]))


def head() -> None:
    with st.container(key="sr_c_head"):
        top = st.container(horizontal=True, vertical_alignment="center", gap="small")
        top.html(f'<div class="sr-c-title"><h2>{escape(fmt.headline(s, markets))}</h2>'
                 f'<p>Opened {case["opened"]:%d %b %H:%M} this session · run for week ending '
                 f'{escape(nav.nice_date(case["as_of_week"]))}</p></div>')
        with top.container(horizontal=True, horizontal_alignment="right", gap="small"):
            status = st.selectbox("Status", workspace.STATUSES, index=workspace.STATUSES.index(case["status"]),
                                  key=f"sr_case_status_{kid}", label_visibility="collapsed", width=150)
            if status != case["status"]:
                case["status"] = status
                workspace.log(k, f"Status set to {status}")
                st.rerun()
            with st.popover("Copy summary", icon=":material/content_copy:"):
                st.code(summary(), language=None, wrap_lines=True)
        st.html('<div class="sr-ctx-metrics">' + "".join(
            f'<div><span>{a}</span><b class="{c}">{escape(v)}</b></div>' for a, v, c in [
                ("Previous share", fmt.pct(s["SH0"]), ""), ("Current share", fmt.pct(s["SH1"]), ""),
                ("Movement", fmt.pts(s["D_SHARE_PTS"]), _sign(s["D_SHARE_PTS"])),
                ("Value at stake", fmt.money(s["VALUE_AT_STAKE"], cur), _sign(s["VALUE_AT_STAKE"])),
                ("Confidence", fmt.confidence(s["CONFIDENCE"]), "")])
            + f'<div><span>Data status</span><em class="sr-ctx-chip">{escape(fmt.LABEL_CHIP.get(s["ARTEFACT_LABEL"], s["ARTEFACT_LABEL"]))}'
            "</em></div></div>")


def steps() -> None:
    b = data.bridge(case["shift_id"]) or {}
    a = data.artefacts(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    label = fmt.LABEL_CHIP.get(s["ARTEFACT_LABEL"], s["ARTEFACT_LABEL"])
    checked = s.get("ARTEFACT_LABEL") is not None and not pd.isna(s.get("ARTEFACT_LABEL"))
    explained = bool(b) and b.get("STATUS") == "OK"
    rows = [
        (True, False, "Shift detected", f"run for week ending {nav.nice_date(case['as_of_week'])}"),
        (checked, False, "Evidence checked",
         (f"{label} · " + ("no data rule fired" if a.empty else f"{len(a)} data rule{'' if len(a) == 1 else 's'} fired"))
         if checked else "no data-check result"),
        (explained, False, "Drivers explained", f"exact bridge, mode {b['MODE']}" if explained
         else f"no exact bridge ({b.get('STATUS', 'none')})"),
        (case["reviewed"], True, "Findings reviewed", "by you, this session" if case["reviewed"] else "needs your review"),
        (case["status"] != "Open", True, "Monitor or resolve", case["status"] if case["status"] != "Open" else "needs a decision"),
    ]
    st.html('<p class="sr-c-h">Investigation</p><div class="sr-steps">' + "".join(
        f'<div class="sr-step{" done" if done else ""}{" manual" if manual else ""}">{i} · {escape(t)}'
        f'<span class="n">{escape(n)}</span></div>' for i, (done, manual, t, n) in enumerate(rows, 1)) + "</div>")


def evidence() -> None:
    b = data.bridge(case["shift_id"])
    st.html('<p class="sr-c-h">Evidence</p>')
    if b:
        st.altair_chart(charts.bridge_bars(b), width="stretch")
    else:
        st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No bridge for this shift.</div>')
    direction = "LOSS" if float(s["D_SHARE"]) < 0 else "GAIN"
    f = data.flow(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"], direction)
    w = data.where(case["shift_id"])
    w = w[w.METHOD == "EXACT_RETAILER"]
    notes = []
    if not f.empty:
        notes.append(("Who took it: " if direction == "LOSS" else "Where it came from: ")
                     + ", ".join(f"{fmt.name(r.COUNTERPART)} {fmt.pts(r.FLOW_PTS)}" for r in f.head(3).itertuples(index=False)))
    if not w.empty:
        top = w.reindex(w.TOTAL_PTS.abs().sort_values(ascending=False).index).iloc[0]
        notes.append(f"Largest retailer contribution: {top.CONTRIBUTOR} {fmt.pts(top.TOTAL_PTS)}")
    for n in notes:
        st.caption(n)


def decision_hub() -> None:
    st.html('<p class="sr-c-h">Decision hub</p>')
    with st.form(f"sr_case_note_{kid}", clear_on_submit=True, border=False):
        text = st.text_area("Review note", placeholder="What did you check, and what do you conclude?", height=80,
                            label_visibility="collapsed")
        if st.form_submit_button("Add note", icon=":material/note_add:"):
            workspace.add_note(k, text)
            st.rerun()
    reviewed = st.toggle("Findings reviewed", value=case["reviewed"], key=f"sr_case_rev_{kid}")
    if reviewed != case["reviewed"]:
        case["reviewed"] = reviewed
        workspace.log(k, "Findings marked reviewed" if reviewed else "Findings review cleared")
        st.rerun()
    events = sorted(case.get("events", []) + [(n["at"], f"Note: {n['text']}") for n in case["notes"]], key=lambda e: e[0])
    st.html('<p class="sr-c-h">Timeline · this session</p><ol class="sr-c-timeline">' + "".join(
        f"<li><time>{at:%d %b %H:%M}</time>{escape(what)}</li>" for at, what in reversed(events))
        + ("" if events else "<li>No actions yet.</li>") + "</ol>")
    with st.container(horizontal=True, gap="small", key=f"sr_case_actions_{kid}"):
        cur_run = data.current_run()
        if cur_run is not None and case["shift_id"] in set(data.shifts(cur_run.run_id).SHIFT_ID):
            if st.button("Investigate", key=f"sr_case_open_{kid}", icon=":material/search:"):
                st.session_state.shift_id = case["shift_id"]
                st.switch_page("pages/1_Shift_detail.py")
        if not masked and st.button("Ask Chippy", key=f"sr_case_ask_{kid}", icon=":material/forum:"):
            st.session_state["sr_ask_about"] = (f"Why did {s['BRAND']} {'lose' if float(s['D_SHARE']) < 0 else 'gain'} share "
                                                f"in {markets.get(s['MARKET_ID'], s['MARKET_ID'])}, "
                                                f"{fmt.CMP_TEXT.get(s['CMP_CODE'], s['CMP_CODE'])}?")
            st.switch_page("pages/5_Ask_Chippy.py")
        if st.button("Close case file", key=f"sr_case_close_{kid}", icon=":material/close:", type="tertiary"):
            workspace.close_case(k)
            st.rerun()


with right:
    nav.guarded("Case summary", head)
    with st.container(key="sr_c_body"):
        nav.guarded("Investigation steps", steps)
        with nav.stack("case_detail"):
            c1, c2 = st.columns(2)
            with c1:
                nav.guarded("Evidence", evidence)
            with c2:
                nav.guarded("Decision hub", decision_hub)
