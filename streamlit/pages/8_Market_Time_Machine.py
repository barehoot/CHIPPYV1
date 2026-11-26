"""Market Time Machine (My workspace): read-only view of an earlier weekly run, as it was stored. Nothing is replayed
or recomputed: every number comes from the per-run result tables through data.py (run_history, kpis, shifts,
held_back, watchlist, signal_journey, briefs); the differences shown are between two stored KPI values."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import data, format as fmt, nav

nav.radar_header("Market Time Machine", "Read-only: earlier weekly runs exactly as they were stored")
h = data.run_history()
if h.empty:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No completed weekly run yet.", key="tm_empty")
    nav.stop()

h = h.sort_values("AS_OF_WEEK")                                    # oldest first for the timeline
weeks = [str(pd.to_datetime(w).date()) for w in h.AS_OF_WEEK]
by_week = {w: r for w, r in zip(weeks, h.to_dict("records"))}
markets, cur = data.market_names(), data.cfg("CURRENCY") or ""
shown = weeks[-12:]                                                # the timeline: the latest 12 stored weeks

if st.session_state.get("sr_tm_week") not in weeks:               # first visit, or a week no longer listed
    st.session_state["sr_tm_week"] = weeks[-1]
st.html('<div class="sr-session-pill ro"><span class="sr-ico" aria-hidden="true">lock</span><b>Read-only.</b> '
        "Stored results of each run as published, made with the settings of the time; nothing is replayed.</div>")
with st.container(key="sr_tm_bar", horizontal=True, vertical_alignment="center", gap="small"):
    if len(weeks) > len(shown):
        older = st.selectbox("Any week", weeks[::-1], key="sr_tm_any", format_func=lambda w: f"Week ending {nav.nice_date(w)}",
                             label_visibility="collapsed", width=230, index=weeks[::-1].index(st.session_state["sr_tm_week"]))
        if older != st.session_state["sr_tm_week"]:
            st.session_state["sr_tm_week"] = older
            st.rerun()
    if st.session_state["sr_tm_week"] in shown:
        counts = {w: int(data.kpis(by_week[w]["RUN_ID"]).get("N_SELECTED", 0)) for w in shown}
        st.radio("Week ending", shown, key="sr_tm_week", horizontal=True, label_visibility="collapsed",
                 format_func=lambda w: f"{nav.nice_date(w)[:-5]} · {counts[w]} in brief")
week = st.session_state["sr_tm_week"]
_loading = st.empty()
if st.session_state.get("_sr_tm_seen") != week:                 # only when the week changes, not on every rerun
    with _loading.container():
        nav.state("loading", f"Opening the week ending {nav.nice_date(week)}…", 36)
st.session_state["_sr_tm_seen"] = week
r = by_week[week]
run_id = r["RUN_ID"]
latest = by_week[weeks[-1]]


def tiles() -> None:
    k, now = data.kpis(run_id), data.kpis(latest["RUN_ID"])
    is_latest = run_id == latest["RUN_ID"]

    def delta(key, money=False):
        if is_latest:
            return "Latest stored week"
        d = float(k.get(key, 0)) - float(now.get(key, 0))
        shown_d = (fmt.money(abs(d), cur) if money else f"{int(abs(d)):,}")
        return "Same as the latest week" if d == 0 else f"{'+' if d > 0 else '−'}{shown_d} vs the latest week"
    st.html('<div class="sr-findings">' + "".join(
        f'<div class="sr-find-card"><span class="sr-ico" aria-hidden="true">{i}</span><div><span class="k">{escape(lbl)}</span>'
        f'<b>{escape(v)}</b><span class="n">{escape(n)}</span></div></div>' for i, lbl, v, n in [
            ("filter_alt", "Shifts past the gates", f"{int(k.get('N_PASSED', 0)):,}", delta("N_PASSED")),
            ("article", "Shifts in the brief", f"{int(k.get('N_SELECTED', 0)):,}", delta("N_SELECTED")),
            ("shield", "Possible data effects", f"{int(k.get('N_DATA_EFFECT', 0)):,}", delta("N_DATA_EFFECT")),
            ("payments", "Value at stake in the brief", fmt.money(k.get("VALUE_SELECTED", 0), cur),
             delta("VALUE_SELECTED", money=True))]) + "</div>")


def that_week() -> None:
    with st.container(key="sr_tm_brief"):
        bid = r.get("BRIEF_ID")
        if bid is not None and not pd.isna(bid):
            b = data.brief(bid) or {}
            if b.get("HEADLINE") and b.get("STATUS") == "PUBLISHED":     # only a published brief
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    st.html(f'<div class="sr-tm-brief"><span class="k">Archived brief · week ending {escape(nav.nice_date(week))}</span>'
                            f'<b>“{escape(str(b["HEADLINE"]))}”</b></div>')
                    if bid in set(data.briefs().BRIEF_ID) and st.button("Open in Weekly Brief", key="sr_tm_open_brief",
                                                                       icon=":material/article:"):
                        st.session_state.brief_id = bid
                        st.switch_page("pages/2_Brief.py")
        df = data.shifts(run_id)
        sel = df[df.SELECTED].sort_values("RANK_NO")
        st.html('<p class="sr-c-h">Shift insights that week</p>')
        if sel.empty:
            st.html('<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>No shift made the brief that week.</div>')
            return
        st.dataframe(nav.striped(pd.DataFrame({
            "Rank": sel.RANK_NO, "Brand": [fmt.name(b) for b in sel.BRAND],
            "Market": [markets.get(m, m) for m in sel.MARKET_ID],
            "Comparison": [fmt.CMP_TEXT.get(c, c) for c in sel.CMP_CODE],
            "Change": [fmt.pts(v) for v in sel.D_SHARE_PTS],
            "Value at stake": [fmt.money(v, cur) for v in sel.VALUE_AT_STAKE],
            "Data status": [fmt.LABEL_CHIP.get(x, x) for x in sel.ARTEFACT_LABEL]})), hide_index=True, width="stretch")
        current = data.current_run()
        live = set(data.shifts(current.run_id).SHIFT_ID) if current is not None else set()
        with st.container(horizontal=True, gap="small", key="sr_tm_open"):
            for i, row in enumerate(sel.head(5).itertuples(index=False)):
                if row.SHIFT_ID in live and st.button(f"Investigate {fmt.name(row.BRAND)}", key=f"sr_tm_inv_{i}",
                                                      icon=":material/search:"):
                    st.session_state.shift_id = row.SHIFT_ID
                    st.switch_page("pages/1_Shift_detail.py")


def that_week_attention() -> None:
    held, warn = data.held_back(run_id), data.watchlist(run_id)
    lists = [("Held back for data checks", "bad", "database",
              [f"<b>{escape(fmt.name(x.BRAND))} · {escape(markets.get(x.MARKET_ID, x.MARKET_ID))}</b> {escape(fmt.pts(x.D_SHARE_PTS))}"
               for x in held.itertuples(index=False)]),
             ("Early warnings", "warn", "bolt",
              [f"<b>{escape(fmt.name(x.BRAND))} · {escape(markets.get(x.MARKET_ID, x.MARKET_ID))}</b> projected change in next "
               f"four-week share {escape(fmt.pts(x.PROJECTED_SHARE_PTS))}" for x in warn.itertuples(index=False)])]
    st.html('<div class="sr-brief-lists">' + "".join(
        f'<section class="{tone}"><h3><span class="sr-ico" aria-hidden="true">{icon}</span>{title} · {len(items)}</h3>'
        + ("".join(f"<p>{x}</p>" for x in items) or '<p class="none">None that week.</p>') + "</section>"
        for title, tone, icon, items in lists) + "</div>")


nav.guarded("Tiles", tiles)
nav.guarded("That week", that_week)
nav.guarded("That week's attention", that_week_attention)
with st.expander("Signal journey that week", icon=":material/hub:"):
    st.caption(f"Signal journey that week: how the run for week ending {nav.nice_date(week)} reached its brief.")
    nav.guarded("Signal journey", lambda: nav.journey(run_id))
_loading.empty()                                               # the week has rendered: drop the loading line
