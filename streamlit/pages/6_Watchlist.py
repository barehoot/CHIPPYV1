"""Watchlist (My workspace): the brand x market x comparison items the viewer follows, as cards with this week's stored
numbers, a stored share trend and what changed since last week; then the system's early warnings. Session only
(sr_ui.workspace); every number comes from data.py reads."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, nav, workspace
nav.entry_guard("pages/6_Watchlist.py")   # a refresh or direct link still opens inside the app

extra = nav.radar_header("Watchlist", "The shifts you follow, with this week's validated numbers")
run = data.current_run()
items = workspace.watched()
markets = data.market_names()
cur = data.cfg("CURRENCY") or ""
masked = data.cfg("DISPLAY_ALIAS") is True
CMP_SHORT = {"L4W_VS_YA": "L4W vs YA", "L4W_VS_PP": "L4W vs PP", "L12W_VS_YA": "L12W vs YA", "L52W_VS_YA": "L52W vs YA"}

with extra:
    sort = st.radio("Sort", ["Movement", "Value at stake", "Name"], horizontal=True, key="sr_w_sort", width="content",
                    label_visibility="collapsed") if items else None
    if items and st.button("Clear all", key="sr_w_clear", icon=":material/delete_sweep:"):
        items.clear()
        st.rerun()
st.html('<div class="sr-session-pill"><span class="sr-ico" aria-hidden="true">schedule</span><b>Session only.</b> '
        "Kept while this tab stays open; nothing is saved to Snowflake or shared.</div>")


def _name(it: dict) -> str:
    return f"{fmt.name(it['brand'])} · {markets.get(it['market_id'], it['market_id'])}"


def _sign(v) -> str:
    return "" if v is None or pd.isna(v) else ("neg" if float(v) < 0 else "pos")


def following() -> None:
    shifts = data.shifts(run.run_id)
    prev = data.previous_week_run(str(run.as_of_week)) if run.as_of_week and run.scope_key == data.scope_key() else None
    before = data.shifts(prev.run_id) if prev is not None else None
    warned = {(r.BRAND, r.MARKET_ID) for r in data.watchlist(run.run_id).itertuples(index=False)}
    live = set(shifts.SHIFT_ID)
    rows = [(k, it, workspace.find(shifts, k)) for k, it in items.items()]
    key = {"Movement": lambda x: -abs(float(x[2]["D_SHARE_PTS"])) if x[2] else 0,
           "Value at stake": lambda x: -abs(float(x[2]["VALUE_AT_STAKE"])) if x[2] else 0,
           "Name": lambda x: _name(x[1])}[sort or "Movement"]
    with st.container(key="sr_w_cards"):
        for i, (k, it, row) in enumerate(sorted(rows, key=key)):
            with st.container(key=f"sr_w_card_{i}"):
                outcome, tone = workspace.outcome(row)
                pts = row["D_SHARE_PTS"] if row else None
                arrow = "" if pts is None else ("trending_down" if float(pts) < 0 else "trending_up")
                head = (f'<div class="sr-w-head"><span class="sr-ico {_sign(pts)}" aria-hidden="true">{arrow or "remove"}</span>'
                        f'<div><b>{escape(_name(it))}</b><span>{escape(CMP_SHORT.get(it["cmp_code"], it["cmp_code"]))}</span></div></div>')
                if row:
                    figs = (f'<div class="sr-w-figs"><div><span>Movement</span><b class="{_sign(pts)}">{escape(fmt.pts(pts))}</b></div>'
                            f'<div><span>Value at stake</span><b class="{_sign(row["VALUE_AT_STAKE"])}">'
                            f'{escape(fmt.money(row["VALUE_AT_STAKE"], cur))}</b></div>'
                            f'<div><span>Confidence</span><b>{escape(fmt.confidence(row["CONFIDENCE"]))}</b></div></div>')
                else:
                    figs = '<p class="sr-w-none">Not among this week\'s shifts that passed the gates.</p>'
                chips = (f'<em class="sr-ctx-chip {tone or "ok"}">{escape(outcome)}</em>'
                         + ('<em class="sr-ctx-chip warn">⚠ Early warning</em>' if (it["brand"], it["market_id"]) in warned else ""))
                if before is not None:
                    a = workspace.find(before, k)
                    ta, tb = workspace.outcome(a)[0], outcome
                    since = (f"Since last week (week ending {nav.nice_date(prev.as_of_week)}): "
                             + (f"was {ta}" if ta != tb else "unchanged")
                             + (f" · {fmt.pts(a['D_SHARE_PTS'])} → {fmt.pts(pts)}" if a and row else ""))
                else:
                    since = "No earlier week stored to compare with."
                st.html(head + figs + f'<div class="sr-w-chips">{chips}</div>')
                t = data.trend(it["market_id"], it.get("category") or data.cfg("SCOPE_CATEGORY"), it["brand"])
                if len(t):
                    t = t.assign(WEEK_END_DATE=pd.to_datetime(t.WEEK_END_DATE)).sort_values("WEEK_END_DATE").tail(12)
                    st.altair_chart(charts.sparkline(pd.DataFrame({"WEEK_END_DATE": t.WEEK_END_DATE,
                                                                   "VALUE": t.VALUE_SHARE_PCT.astype(float)})),
                                    width="stretch", key=f"sr_w_spark_{i}")
                    st.html('<p class="sr-w-note">Value share, last 12 stored weeks</p>')
                st.html(f'<p class="sr-w-since">{escape(since)}</p>')
                with st.container(key=f"sr_w_act_{i}", horizontal=True, gap="small"):
                    if row and row["SHIFT_ID"] in live and st.button("Investigate", key=f"sr_w_open_{i}", icon=":material/search:"):
                        st.session_state.shift_id = row["SHIFT_ID"]
                        st.switch_page("pages/1_Shift_detail.py")
                    if row and st.button("Open case", key=f"sr_w_case_{i}", icon=":material/folder_open:"):
                        workspace.open_case(row, run.run_id, run.as_of_week)
                        st.switch_page("pages/7_Case_Files.py")
                    if not masked and st.button("Ask Chippy", key=f"sr_w_ask_{i}", icon=":material/forum:"):
                        st.session_state["sr_ask_about"] = (f"What changed for {it['brand']} in "
                                                            f"{markets.get(it['market_id'], it['market_id'])}, "
                                                            f"{fmt.CMP_TEXT.get(it['cmp_code'], it['cmp_code'])}?")
                        st.switch_page("pages/5_Ask_Chippy.py")
                    if st.button("", key=f"sr_w_rm_{i}", icon=":material/close:", help="Stop following", type="tertiary"):
                        workspace.remove_watch(k)
                        st.rerun()


def early_warnings() -> None:
    warn = data.watchlist(run.run_id)
    shifts = data.shifts(run.run_id).sort_values("RANK_NO")
    st.html(f'<h3 class="sr-w-section"><span class="sr-ico" aria-hidden="true">bolt</span>Early warnings · {len(warn)}'
            '<span>raised by the weekly run for every brand; mechanical projections, not forecasts</span></h3>')
    if warn.empty:
        st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No early warnings this week.</div>')
        return
    with st.container(key="sr_w_warnings"):
        for i, r in enumerate(warn.itertuples(index=False)):
            with st.container(key=f"sr_w_ew_{i}", horizontal=True, vertical_alignment="center", gap="small"):
                chg = "" if pd.isna(r.LEVER_CHG) else f" {fmt.signed_pct(float(r.LEVER_CHG))} vs the last four weeks"
                st.html(f'<div class="sr-w-ew"><b>{escape(fmt.name(r.BRAND))} · {escape(markets.get(r.MARKET_ID, r.MARKET_ID))}</b>'
                        f'<span>{"Distribution" if r.SIGNAL == "DIST_DROP" else "Price"}{escape(chg)} · projected change in '
                        f'next four-week share {escape(fmt.pts(r.PROJECTED_SHARE_PTS))}'
                        + (" · confirmed by the anomaly model" if r.ML_CONFIRMED else "") + "</span></div>")
                match = shifts[(shifts.BRAND == r.BRAND) & (shifts.MARKET_ID == r.MARKET_ID)]
                if len(match):
                    m = match.iloc[0].to_dict()
                    if workspace.is_watched(workspace.row_key(m)):
                        st.button("Following", key=f"sr_w_ewadd_{i}", icon=":material/star:", disabled=True)
                    elif st.button("Add to Watchlist", key=f"sr_w_ewadd_{i}", icon=":material/star_outline:"):
                        workspace.add_watch(m, run.run_id)
                        st.rerun()


if run is None:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No weekly run yet, so there is nothing to follow.", key="w_empty")
    nav.stop()
if not items:
    with st.container(key="sr_w_empty", horizontal=True, vertical_alignment="center", gap="small"):
        nav.mascot("resting", "Nothing on your watchlist yet.",
                   "On Radar or Shift Detail, press Add to Watchlist. You can also follow an early warning below.",
                   key="w_none")
        if st.button("Go to Radar", icon=":material/radar:", key="sr_w_radar"):
            st.switch_page("pages/0_Radar.py")
else:
    nav.guarded("Following", following)
nav.guarded("Early warnings", early_warnings)
