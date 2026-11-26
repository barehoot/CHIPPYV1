"""Shift Detail, the investigation studio for one shift (L11). An investigation hero, then five views: Investigation
(what happened, why, where, who benefited, can we trust it, what could happen next), Future Trends (ARIMA, SARIMA,
Holt-Winters, TCN), Statistical Evidence, Market Footprint (region tiles and retailer stats) and Product Intelligence
(SKU heatmaps). Every number comes from data.py reads or the existing forecast module; nothing is re-calculated here."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, nav, workspace
nav.entry_guard("pages/1_Shift_detail.py")   # a refresh or direct link still opens inside the app

from pathlib import Path

st.html((Path(nav.__file__).with_name("radar.css")).read_text(encoding="utf-8"))   # Radar is the visual source


def page_header() -> None:
    """The Radar header (same key, so the same type, spacing and sidebar treatment), without the week selector."""
    with st.container(key="sr_radar_header"):
        title, controls = st.columns([5, 1], vertical_alignment="center")
        title.html('<div class="sr-radar-title"><h1>Shift Detail</h1>'
                   '<p>Investigate one shift: what happened, why, where, and whether to trust it</p></div>')
        with controls.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            if nav.is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
            if st.button("Refresh", icon=":material/refresh:", key="sr_btn_header_refresh"):
                data.clear_cache()
                st.rerun()


page_header()
run = data.current_run()
if run is None:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No run yet.", key="empty_run")
    nav.stop()

options = data.shifts(run.run_id)
if options.empty:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No shifts passed the gates in the current run.", key="empty_shifts")
    nav.stop()
markets = data.market_names()
ids = list(options.SHIFT_ID)
default = ids.index(st.session_state.shift_id) if st.session_state.shift_id in ids else 0
by_id = {r.SHIFT_ID: r._asdict() for r in options.itertuples(index=False)}


def _short(i: str) -> str:
    """Selector label: brand · market; the comparison is added only when the same brand and market appear twice."""
    r = by_id[i]
    label = f"{fmt.name(r['BRAND'])} · {markets.get(r['MARKET_ID'], r['MARKET_ID'])}"
    twins = [j for j, o in by_id.items() if o["BRAND"] == r["BRAND"] and o["MARKET_ID"] == r["MARKET_ID"]]
    return label + (f" · {fmt.CMP_TEXT.get(r['CMP_CODE'], r['CMP_CODE'])}" if len(twins) > 1 else "")


# ---- Compact context bar: the shift selector, its period and stored numbers, and the workspace actions -------------

def _step(delta: int) -> None:
    i = ids.index(st.session_state.shift_id) if st.session_state.shift_id in ids else 0
    st.session_state.shift_id = ids[(i + delta) % len(ids)]


context = st.container(key="sr_shift_context")
top = context.container(key="sr_shift_ctx_top", horizontal=True, vertical_alignment="center", gap="small")
with top:
    sid = st.selectbox("Shift", ids, index=default, format_func=_short, width=280, label_visibility="collapsed")
    with st.container(key="sr_shift_nav", horizontal=True, gap=None, width=72):
        st.button("", icon=":material/chevron_left:", key="sr_sd_prev", help="Previous shift", on_click=_step, args=(-1,),
                  disabled=len(ids) < 2)
        st.button("", icon=":material/chevron_right:", key="sr_sd_next", help="Next shift", on_click=_step, args=(1,),
                  disabled=len(ids) < 2)
if st.session_state.shift_id != sid:
    st.session_state.sr_open_checks = False                     # a new shift starts with the checks closed
st.session_state.shift_id = sid
s = data.shift(sid)
direction = "LOSS" if float(s["D_SHARE"]) < 0 else "GAIN"
cur = data.cfg("CURRENCY") or ""
flagged = s["ARTEFACT_LABEL"] in ("MIXED", "POSSIBLE_DATA_EFFECT")
masked = data.cfg("DISPLAY_ALIAS") is True


CMP_SHORT = {"L4W_VS_YA": "L4W vs YA", "L4W_VS_PP": "L4W vs PP", "L12W_VS_YA": "L12W vs YA", "L52W_VS_YA": "L52W vs YA"}


def _facts() -> dict:
    """This shift's stored results, read once: bridge terms, exact retailer split, flow and data checks."""
    b = data.bridge(sid) or {}
    terms = charts.bridge_frame(b) if b and b.get("STATUS") == "OK" and b.get("MODE") != "D" else pd.DataFrame()
    terms = terms[terms.term != "Total change"] if len(terms) else terms
    top_term = terms.reindex(terms.pts.abs().sort_values(ascending=False).index).iloc[0] if len(terms) else None
    w = data.where(sid)
    w = w[w.METHOD == "EXACT_RETAILER"]
    top_ret = w.reindex(w.TOTAL_PTS.abs().sort_values(ascending=False).index).iloc[0] if len(w) else None
    f = data.flow(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"], direction)
    top_flow = f.sort_values("FLOW_PTS", ascending=False).iloc[0] if len(f) else None
    a = data.artefacts(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    return {"bridge": b, "term": top_term, "retailer": top_ret, "flow": top_flow, "rules": len(a)}


def _takeaway(fx: dict) -> str:
    """One data-driven sentence from the stored results (template text, not AI)."""
    m = markets.get(s["MARKET_ID"], s["MARKET_ID"])
    pts = fmt.pts(abs(float(s["D_SHARE_PTS"]))).lstrip("+")
    out = (f"{fmt.name(s['BRAND'])} {'lost' if direction == 'LOSS' else 'gained'} {pts} in {m} "
           f"({fmt.pct(s['SH0'])} → {fmt.pct(s['SH1'])}), {fmt.CMP_TEXT.get(s['CMP_CODE'], s['CMP_CODE'])}")
    if fx["term"] is not None:
        out += f", mainly from {fx['term'].term.lower()} ({fmt.pts(fx['term'].pts)})"
    out += "."
    if fx["retailer"] is not None:
        out += f" {fx['retailer'].CONTRIBUTOR} contributed most ({fmt.pts(fx['retailer'].TOTAL_PTS)})."
    if fx["flow"] is not None:
        who = fmt.name(fx["flow"].COUNTERPART)
        out += (f" {who} took the largest share ({fmt.pts(fx['flow'].FLOW_PTS)})." if direction == "LOSS"
                else f" The largest share came from {who} ({fmt.pts(fx['flow'].FLOW_PTS)}).")
    out += (" No data rule fired." if fx["rules"] == 0 else
            f" {fx['rules']} data rule{'' if fx['rules'] == 1 else 's'} fired: review the checks before sharing.")
    return out


fx = _facts()
takeaway = _takeaway(fx)


def context_bar() -> None:
    outcome, _ = workspace.outcome(by_id[sid])
    k = workspace.row_key(s)
    tone = {"POSSIBLE_DATA_EFFECT": "bad", "MIXED": "warn"}.get(s["ARTEFACT_LABEL"], "ok")
    with top:
        st.html(f'<div class="sr-ctx-period" title="{escape(fmt.CMP_TEXT.get(s["CMP_CODE"], s["CMP_CODE"]))}">'
                f'<span class="sr-ico" aria-hidden="true">calendar_month</span>'
                f'{escape(CMP_SHORT.get(s["CMP_CODE"], s["CMP_CODE"]))}<span class="sep">·</span>{escape(outcome)}</div>'
                f'<em class="sr-ctx-chip {tone}" title="Data status">'
                f'{escape(fmt.LABEL_CHIP.get(s["ARTEFACT_LABEL"], s["ARTEFACT_LABEL"]))}</em>', width="content")
        with st.container(key="sr_shift_ctx_actions", horizontal=True, horizontal_alignment="right",
                          vertical_alignment="center", gap="small"):
            with st.popover("Copy takeaway", icon=":material/content_copy:", help="Copy the key takeaway"):
                st.caption("Copy with the icon at the top right of the box.")
                st.code(takeaway, language=None, wrap_lines=True)
            if workspace.is_watched(k):
                st.button("On your watchlist", key="sr_sd_watch", icon=":material/star:", disabled=True,
                          help="On your watchlist for this session")
            elif st.button("Add to Watchlist", key="sr_sd_watch", icon=":material/star_outline:", help="Add to Watchlist"):
                workspace.add_watch(s, run.run_id)
                st.toast("Added to your watchlist for this session.", icon=":material/star:")
                st.rerun()
            if st.button("Open as Case File", key="sr_sd_case", icon=":material/folder_open:", help="Open as Case File"):
                workspace.open_case({**s, "SHIFT_ID": sid}, run.run_id, run.as_of_week)
                st.switch_page("pages/7_Case_Files.py")


nav.guarded("Shift context", context_bar)


# ---- Investigation ------------------------------------------------------------------------------------------------

LEVER_TEXT = {  # plain-English lever definitions (share-methodology): each term is relative to the category
    "Distribution": "The brand's share of the category's distribution points (TDP): how widely it is stocked "
                    "compared with the category.",
    "Velocity": "Sales per distribution point, relative to the category: how well the brand sells where it is stocked.",
    "Price": "Value per unit, relative to the category.",
    "Promo": "Actual value over base (non-promoted) value, relative to the category: how much promotion lifted sales.",
}


def _say(text: str, label: str = "Takeaway") -> None:
    st.html(f'<div class="sr-takeaway"><span class="sr-ico" aria-hidden="true">lightbulb</span><div><span class="k">'
            f'{escape(label)}</span><p>{escape(text)}</p></div></div>')


def _cards(cards: list[tuple]) -> None:
    """(icon, label, value, tone, note) cards in one row; tone 'neg' / 'pos' / ''."""
    st.html('<div class="sr-findings">' + "".join(
        f'<div class="sr-find-card"><span class="sr-ico" aria-hidden="true">{i}</span><div><span class="k">{escape(k)}</span>'
        f'<b class="{c}">{escape(v)}</b><span class="n">{escape(n)}</span></div></div>' for i, k, v, c, n in cards)
        + "</div>")


def _empty(text: str) -> None:
    st.html(f'<div class="sr-empty"><span class="sr-ico" aria-hidden="true">info</span>{escape(text)}</div>')


def _sign(v) -> str:
    return "" if v is None or pd.isna(v) else ("neg" if float(v) < 0 else "pos")


def _best(v: float, noun: str) -> tuple[str, str, str]:
    """(card label, icon, takeaway word) for the highest value: 'strongest' only when it actually grew, so a list where
    every item fell says 'smallest decline' instead of calling a fall the strongest."""
    if v is not None and not pd.isna(v) and float(v) < 0:
        return f"Smallest {noun} decline", "south_east", "smallest decline"
    return f"Strongest {noun}", "north_east", "strongest"


def key_finding() -> None:
    """The takeaway, then four figure cards from this shift's stored results (template text, not AI)."""
    _say(takeaway + " Template text from the stored results, not written by AI.", "Key investigation finding")
    b, t, r = fx["bridge"], fx["term"], fx["retailer"]
    _cards([
        ("trending_down" if direction == "LOSS" else "trending_up", "Share movement", fmt.pts(s["D_SHARE_PTS"]),
         _sign(s["D_SHARE_PTS"]), f"{fmt.pct(s['SH0'])} → {fmt.pct(s['SH1'])} · {markets.get(s['MARKET_ID'], s['MARKET_ID'])}"),
        ("payments", "Value at stake", fmt.money(s["VALUE_AT_STAKE"], cur), _sign(s["VALUE_AT_STAKE"]),
         f"Confidence {fmt.confidence(s['CONFIDENCE'])}"),
        ("account_tree", "Largest driver", fmt.pts(t.pts) if t is not None else "–", _sign(t.pts) if t is not None else "",
         f"{t.term} · exact share bridge, mode {b['MODE']}" if t is not None else "No exact bridge terms for this shift"),
        ("storefront", "Largest retailer", fmt.pts(r.TOTAL_PTS) if r is not None else "–",
         _sign(r.TOTAL_PTS) if r is not None else "",
         f"{r.CONTRIBUTOR} · performance {fmt.pts(r.PERF_PTS)}, mix {fmt.pts(r.MIX_PTS)}" if r is not None
         else "Exact retailer split: selected shifts in the parent market only"),
    ])
    reason = s.get("SUPPRESS_REASON")
    if reason is not None and not pd.isna(reason):
        st.caption(str(reason))


def journey() -> None:
    """The investigation path as clickable steps, each with its stored status."""
    t, r, fl = fx["term"], fx["retailer"], fx["flow"]
    who = "Who took it" if direction == "LOSS" else "Where it came from"
    steps = [("What happened", "historical-trend", fmt.pts(s["D_SHARE_PTS"])),
             ("Why", "what-moved-share", f"{t.term} {fmt.pts(t.pts)}" if t is not None else "No bridge terms"),
             ("Where", "where-it-happened", f"{r.CONTRIBUTOR} {fmt.pts(r.TOTAL_PTS)}" if r is not None else "No exact split"),
             ("Who benefited" if direction == "LOSS" else "Who lost", who.lower().replace(" ", "-"),
              f"{fmt.name(fl.COUNTERPART)} {fmt.pts(fl.FLOW_PTS)}" if fl is not None else "No flow"),
             ("Can we trust it?", "evidence-and-data-trust",
              "✓ No rule fired" if fx["rules"] == 0 else f"⚠ {fx['rules']} rule{'' if fx['rules'] == 1 else 's'} fired"),
             ("What next", "scenario-lab", "Scenario lab")]
    st.html('<nav class="sr-steps-nav" aria-label="Investigation steps">' + "".join(
        f'<a href="#{a}" target="_self"><i>{n}</i><b>{escape(t_)}</b><span>{escape(v)}</span></a>'
        for n, (t_, a, v) in enumerate(steps, 1)) + "</nav>")


def trend_section() -> None:
    nav.section("Historical trend", "Value and distribution share by week. Shaded: the compared periods.")
    t = data.trend(s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    if t.empty:
        st.caption("No weekly history.")
        return
    as_of = pd.to_datetime(t.WEEK_END_DATE.max()).date()
    now, base = charts.period_bounds(as_of, s["CMP_CODE"], fmt.CUR_WEEKS.get(s["CMP_CODE"], 4))
    t = t.assign(WEEK_END_DATE=pd.to_datetime(t.WEEK_END_DATE))
    st.altair_chart(charts.trend_lines(t, now, base), width="stretch")


def _lever_evidence(lever: str) -> list[str]:
    """Evidence already in this run for one lever: the trend line, and an early warning on that lever."""
    out = ["The distribution share line in Historical trend above."] if lever == "Distribution" else []
    code = {"Distribution": "DIST_DROP", "Price": "PRICE"}.get(lever)
    if code:
        ew = data.watchlist(run.run_id)
        ew = ew[(ew.BRAND == s["BRAND"]) & (ew.MARKET_ID == s["MARKET_ID"]) & ew.SIGNAL.astype(str).str.startswith(code)]
        for r in ew.itertuples(index=False):
            out.append(f"Early warning: {lever.lower()} {'down' if (r.LEVER_CHG or 0) < 0 else 'up'} "
                       f"{fmt.pct(abs(float(r.LEVER_CHG)))} vs the last four weeks (projected change in next four-week share "
                       f"{fmt.pts(r.PROJECTED_SHARE_PTS)}).")
    return out


def driver_explorer() -> None:
    nav.section("What moved share", "The exact share bridge: each lever's contribution, in share points. Pick a lever "
                "to explore it.")
    b = data.bridge(sid)
    if not b:
        st.info("No bridge for this shift.")
        return
    if b["STATUS"] == "NEW":
        nav.badges([("New listing", "accent")])
        st.caption("No sales in the base period, so there is nothing to split.")
    elif b["STATUS"] == "EXIT":
        nav.badges([("Delisted", "warn")])
        st.caption("No sales in the current period.")
    elif b["STATUS"] == "NO_DATA":
        st.warning("A category total is missing in one period; the change cannot be split.")
    levers = [t for t in charts.bridge_frame(b).term if t != "Total change"]
    with st.container(key="sr_levers"):                         # a single-choice radio, styled as chips (nav.CSS)
        pick = st.radio("Explore a lever", ["All levers"] + levers, horizontal=True, key=f"sr_lever_{sid}") or "All levers"
    chart_col, info_col = st.columns([3, 2])
    with chart_col:
        st.altair_chart(charts.bridge_bars(b, highlight=None if pick == "All levers" else pick), width="stretch")
        if b["MODE"] == "D" or b["STATUS"] != "OK":
            st.caption(b.get("NOTE") or "No distribution data: share change only")
        else:
            resid = b.get("RESIDUAL_PTS")
            st.caption(f"Mode {b['MODE']}: the terms add up to {fmt.pts(100 * float(b['D_SHARE']))} "
                       f"(residual {0.0 if resid is None else float(resid):.1e} pts)."
                       + (" No price or promo split in mode C." if b["MODE"] == "C" else "")
                       + (" No promo split in mode B." if b["MODE"] == "B" else ""))
    with info_col:
        if pick == "All levers":
            body = ("<b>Every lever at once</b><br>Each bar is one lever's contribution with the others held; together "
                    "they add up exactly to the total change. Pick a lever for its meaning and the evidence behind it.")
        else:
            val = float(charts.bridge_frame(b).set_index("term").pts[pick])
            ev = _lever_evidence(pick)
            body = (f"<b>{escape(pick)} · {escape(fmt.pts(val))}</b><br>{escape(LEVER_TEXT.get(pick, ''))}"
                    + "<br><br><b>Supporting evidence in this run</b><br>"
                    + ("<br>".join("• " + escape(e) for e in ev) if ev else "No separate evidence in this run beyond the bridge."))
        st.markdown(f'<div class="sr-explain">{body}<span class="n">The bridge splits the change exactly; it does not '
                    "say why a lever moved.</span></div>", unsafe_allow_html=True)


def where_section() -> None:
    nav.section("Where it happened", "Retailer contribution: the exact split of the change into performance within "
                "each retailer, and mix.")
    w = data.where(sid)
    exact = w[w.METHOD == "EXACT_RETAILER"]
    if exact.empty:
        st.caption("The exact retailer split is computed for selected shifts in the parent market.")
    else:
        st.altair_chart(charts.retailer_bars(exact), width="stretch")
        with st.expander("Retailer breakdown", icon=":material/table_rows:"):
            st.dataframe(pd.DataFrame({"Retailer": exact.CONTRIBUTOR, "Performance": [fmt.pts(v) for v in exact.PERF_PTS],
                                       "Mix": [fmt.pts(v) for v in exact.MIX_PTS], "Total": [fmt.pts(v) for v in exact.TOTAL_PTS]}),
                         hide_index=True, width="stretch")
    ti = w[w.METHOD == "TOP_INSIGHTS"]
    if not ti.empty:
        with st.expander("Drivers of brand sales change", icon=":material/insights:"):
            st.caption("TOP_INSIGHTS: explains sales, not share.")
            st.dataframe(pd.DataFrame({"Segment": ti.CONTRIBUTOR, "Contribution": [fmt.money(v, cur) for v in ti.CONTRIBUTION],
                                       "Share of change": [fmt.signed_pct(v) for v in ti.RELATIVE_CONTRIBUTION],
                                       "Growth": [fmt.signed_pct(v) for v in ti.GROWTH_RATE]}),
                         hide_index=True, width="stretch")


def flow_section() -> None:
    nav.section("Who took it" if direction == "LOSS" else "Where it came from",
                "Competitor share allocation: proportional allocation of share points, an accounting split, not "
                "shopper switching.")
    f = data.flow(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"], direction)
    if f.empty:
        st.caption("No flow for this shift.")
        return
    f = f.assign(COUNTERPART=[fmt.name(b) for b in f.COUNTERPART])
    st.altair_chart(charts.flow_bars(f), width="stretch")
    with st.expander("Brand breakdown", icon=":material/table_rows:"):
        st.dataframe(pd.DataFrame({"Brand": f.COUNTERPART, "Share points": [fmt.pts(v) for v in f.FLOW_PTS]}),
                     hide_index=True, width="stretch")


def trust_section() -> None:
    nav.section("Evidence and data trust", "Whether this change could be a data artefact, how unusual it is, and "
                "whether the bridge reconciles.")
    a = data.artefacts(s["RUN_ID"], s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    b = data.bridge(sid) or {}
    z = s.get("Z_SCORE")
    zs = "–" if z is None or pd.isna(z) else f"{float(z):+.1f}"
    weeks = s.get("ANOMALY_WEEKS")
    wk = "–" if weeks is None or pd.isna(weeks) else f"{int(weeks)}"
    resid = b.get("RESIDUAL_PTS")
    tiles = [
        ("Data checks", fmt.LABEL_CHIP.get(s["ARTEFACT_LABEL"], s["ARTEFACT_LABEL"]),
         "No data rule fired" if a.empty else f"{len(a)} data rule{'' if len(a) == 1 else 's'} fired; see below",
         "bad" if s["ARTEFACT_LABEL"] == "POSSIBLE_DATA_EFFECT" else ("warn" if flagged else "ok")),
        ("Statistical anomaly", "Confirmed" if bool(s.get("ANOMALY_CONFIRMED")) else "Not confirmed",
         f"z-score {zs} · anomalous weeks {wk} · see Statistical Evidence", ""),
        ("Bridge reconciliation", (f"Mode {b['MODE']} · exact" if b.get("STATUS") == "OK" and b.get("MODE") != "D"
                                   else f"Mode {b.get('MODE', '–')}"),
         "–" if resid is None or pd.isna(resid) else f"Residual {float(resid):.1e} pts", ""),
    ]
    st.markdown('<div class="sr-tiles">' + "".join(
        f'<div class="sr-jbox {t}"><span class="k">{escape(k)}</span><b class="sm">{escape(v)}</b>'
        f'<span class="n">{escape(n)}</span></div>' for k, v, n, t in tiles) + "</div>", unsafe_allow_html=True)
    st.subheader("Data checks")                                    # anchor #data-checks (hero link)
    if a.empty:
        st.success("No data rule fired for this market and comparison.", icon=":material/check_circle:")
        return
    st.caption("Rules that test whether this change could be a data artefact. Open one for its evidence.")
    open_ = flagged or bool(st.session_state.get("sr_open_checks"))
    for r in a.itertuples(index=False):
        with st.expander(f"{'⚠' if r.SEVERITY == 'HIGH' else '◐'} {fmt.RULE_TEXT.get(r.RULE_ID, r.RULE_ID)} ({r.SEVERITY})",
                         expanded=open_):
            st.json(r.EVIDENCE)


def scenario_lab() -> None:
    """The existing What-if (data.what_if, unchanged): one lever moved, the others held. Results are kept for this
    session, up to three side by side; Reset clears them."""
    st.markdown('<h3 class="sr-h3" id="scenario-lab">Scenario lab <span class="sr-badge bad">Mechanical · not a forecast</span></h3>',
                unsafe_allow_html=True)
    st.caption("The mechanical effect on share of moving one lever, with the others held. For model projections, see "
               "Future Trends.")
    b = data.bridge(sid) or {}
    has_dist = b.get("DS1") is not None and not pd.isna(b.get("DS1")) and b.get("STATUS") == "OK"
    levers = ["DISTRIBUTION"] + (["PROMO"] if b.get("MODE") == "A" else [])
    store = st.session_state.setdefault("sr_scenarios", {}).setdefault(sid, [])
    left, right = st.columns([3, 2])
    with left:
        with st.form("what_if", border=False):
            c1, c2 = st.columns(2)
            lever = c1.radio("Lever", levers, disabled=not has_dist, horizontal=True, format_func=str.title)
            how = c2.radio("Target", ["Restore the base-period level", "Change by a percentage"], disabled=not has_dist)
            pct = st.number_input("Percentage change", value=10.0, step=5.0, disabled=not has_dist,
                                  help="Used when the target is 'Change by a percentage'")
            go = st.form_submit_button("Run scenario", disabled=not has_dist, type="primary", icon=":material/science:")
        if not has_dist:
            st.caption("Needs a distribution share (bridge mode A to C).")
        if go:
            target = "BASE" if how.startswith("Restore") else f"{pct:+g}%"
            r = data.what_if(sid, lever, target)
            if r.get("error"):
                st.warning(r.get("detail", r["error"]))
            else:
                store.append({"name": f"{lever.title()} " + ("to base level" if target == "BASE" else target),
                              "share_if_pts": r["share_if_pts"], "delta_pts": r["delta_pts"], "assumption": r["assumption"]})
                del store[:-3]
                st.rerun()
    with right:
        rows = [("Current", fmt.pct(s["SH1"], 2), "–")] + [
            (x["name"], fmt.pct(x["share_if_pts"] / 100, 2), fmt.pts(x["delta_pts"])) for x in store]
        st.dataframe(pd.DataFrame(rows, columns=["Scenario", "Share if", "vs current"]), hide_index=True, width="stretch")
        st.caption("Up to three scenarios side by side, kept for this session only.")
        if store and st.button("Reset scenarios", key="sr_scen_reset", icon=":material/restart_alt:", type="tertiary"):
            store.clear()
            st.rerun()
    if store:
        st.markdown('<div class="sr-explain"><b>Assumptions</b> (as returned by the calculation)<br>'
                    + "<br>".join(f"• {escape(x['name'])}: {escape(str(x['assumption']))}" for x in store)
                    + "</div>", unsafe_allow_html=True)


def ask_card() -> None:
    """Ask Chippy about this shift: the same question as before, for CoWork, and a button that opens Ask Chippy with
    it ready to send. Hidden when names are masked (as before)."""
    q = (f"Why did {s['BRAND']} {'lose' if direction == 'LOSS' else 'gain'} share in "
         f"{markets.get(s['MARKET_ID'], s['MARKET_ID'])}, {fmt.CMP_TEXT.get(s['CMP_CODE'], s['CMP_CODE'])}?")
    left, right = nav.stack("sd_ask").columns([4, 1], vertical_alignment="center")
    with left:
        nav.section("Ask Chippy about this shift", "Paste this question into the Chippy agent in CoWork, or open it in "
                    "Ask Chippy.")
        st.code(q, language=None, wrap_lines=True)
    with right:
        if st.button("Ask Chippy AI", key="sr_sd_ask", type="primary", icon=":material/forum:", width="stretch"):
            st.session_state["sr_ask_about"] = q
            st.switch_page("pages/5_Ask_Chippy.py")


def _in_card(key: str, render) -> None:
    with nav.card(key):
        render()


def investigation() -> None:
    nav.guarded("Key finding", key_finding)
    nav.guarded("Journey", journey)
    nav.guarded("Historical trend", lambda: _in_card("trend", trend_section))
    nav.guarded("Bridge", lambda: _in_card("bridge", driver_explorer))
    with nav.stack("sd_where"):
        left, right = st.columns(2)
        with left:
            nav.guarded("Where it happened", lambda: _in_card("where", where_section))
        with right:
            nav.guarded("Who took it", lambda: _in_card("flow", flow_section))
    nav.guarded("Data checks", lambda: _in_card("checks", trust_section))
    nav.guarded("What if", lambda: _in_card("what_if", scenario_lab))
    if not masked:                                       # names masked: no question with real names, as before
        nav.guarded("Ask why", lambda: _in_card("ask_why", ask_card))


# ---- Analysis views: Future Trends, Statistical Evidence, Market Footprint, Product Intelligence ------------------

MEASURES = {  # label -> (series loader key, axis title, number format)
    "Value share %": ("VALUE_SHARE_PCT", "Value share, % of category", ",.2f"),
    "Distribution share %": ("DIST_SHARE_PCT", "Distribution share, %", ",.2f"),
    "Value sales": ("VALUE_SALES", f"Value sales ({cur})" if cur else "Value sales", ",.0f"),
}


def _series(measure: str) -> pd.Series:
    """The weekly series for the shift's brand, market and category, indexed by week, oldest first."""
    col = MEASURES[measure][0]
    if col == "VALUE_SALES":
        df = data.brand_sales_week(s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    else:
        df = data.trend(s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    df = df.assign(WEEK_END_DATE=pd.to_datetime(df.WEEK_END_DATE)).sort_values("WEEK_END_DATE")
    return pd.Series(df[col].astype(float).to_numpy(), index=df.WEEK_END_DATE)


@st.cache_data(ttl=data.TTL_S, show_spinner=False)
def _forecast(dates: tuple, values: tuple, models: tuple, h: int):
    from sr_ui import forecast
    y = pd.Series(values, index=pd.to_datetime(list(dates)))
    results, errors = forecast.run(y, list(models), h)
    try:
        bt = forecast.backtest(y, list(models), holdout=min(8, max(4, len(y) // 8)))
    except forecast.ForecastError as e:
        bt, errors = None, {**errors, "Backtest": str(e)}
    return results, errors, bt


@st.cache_data(ttl=data.TTL_S, show_spinner=False)
def _stats(dates: tuple, values: tuple):
    from sr_ui import forecast
    return forecast.stats(pd.Series(values, index=pd.to_datetime(list(dates))))


def _subject() -> str:
    return f"{fmt.name(s['BRAND'])} in {markets.get(s['MARKET_ID'], s['MARKET_ID'])} · {s['CATEGORY']}"


def forecast_view() -> None:
    with nav.card("fc_controls"):
        nav.section("Future trends", f"{_subject()}. Model projections of the measured weekly history, not a plan or a target.")
        c1, c2, c3 = nav.stack("fc_ctl").columns([2, 1.5, 3], vertical_alignment="bottom")
        measure = c1.selectbox("Measure", list(MEASURES), key="fc_measure")
        h = c2.segmented_control("Horizon, weeks", [4, 8, 13], default=8, key="fc_h") or 8
        from sr_ui import forecast as _fc
        models = c3.pills("Models", ["ARIMA", "SARIMA", "Holt-Winters", "TCN"], selection_mode="multi",
                          default=["ARIMA", "SARIMA", "Holt-Winters"] + (["TCN"] if _fc.tcn_available() else []),
                          key="fc_models", help=None if _fc.tcn_available() else
                          "TCN needs PyTorch, which is not installed here; pick it to see why.") or []
    if not models:
        _empty("Pick at least one model.")
        return
    y = _series(measure)
    from sr_ui import forecast
    try:
        forecast.prepare(y)
    except forecast.ForecastError as e:
        st.warning(str(e), icon=":material/warning:")
        return
    thinking = st.empty()
    nav.mascot("working", "Crunching the numbers…", "Fitting " + ", ".join(models) + ".", key="thinking_fc", container=thinking)
    try:
        results, errors, bt = _forecast(tuple(y.index.astype(str)), tuple(y.to_numpy()), tuple(models), int(h))
    finally:
        thinking.empty()                                         # never leave Chippy working after an error
    _, title, f = MEASURES[measure]
    best = set(bt[bt.BEST].MODEL) if bt is not None and not bt.empty else set()
    lead = next((r for r in results if r["model"] in best), results[0] if results else None)
    if lead is not None:
        last = lead["forecast"].iloc[-1]
        _say(f"{lead['model']}{' (lowest backtest error)' if lead['model'] in best else ''} projects "
             f"{measure.lower()} at {last.MEAN:,.2f} in week {h} (80% band {last.LO80:,.2f} to {last.HI80:,.2f}), "
             f"against {float(y.iloc[-1]):,.2f} in the latest week. A projection of the measured pattern, not a plan.")
    if results:                                                  # each model's week-h value and 80% band, as returned
        cards = []
        for r in results:
            last = r["forecast"].iloc[-1]
            star = r["model"] in best
            cards.append(f'<div class="sr-jbox{" ok" if star else ""}"><span class="k">{escape(r["model"])} · week {h}'
                         + (" · lowest backtest MAE" if star else "") + f'</span><b>{last.MEAN:,.2f}</b>'
                         f'<span class="n">80%: {last.LO80:,.2f} to {last.HI80:,.2f}</span></div>')
        st.markdown('<div class="sr-tiles">' + "".join(cards) + "</div>", unsafe_allow_html=True)
    with nav.card("fc_chart"):
        nav.section(f"Actual and projected {measure.lower().replace(' %', '')}", "Pick a model in the legend to focus it.")
        fit = st.toggle("Fit the axis to the data", value=True, key="fc_fit",
                        help="On: the value axis spans the data, so small movements show. Off: it starts at zero.")
        hist = pd.DataFrame({"WEEK_END_DATE": y.index, "VALUE": y.to_numpy()})
        st.altair_chart(charts.forecast_chart(hist, results, title, f, zero=not fit), width="stretch")
        st.caption("Solid line: history. Dashed: forecasts. Shaded: 80% band. Click a legend entry to focus one model. "
                   "Drag to pan, scroll to zoom, double-click to reset.")
    for name, msg in errors.items():
        st.warning(f"{name}: {msg}", icon=":material/warning:")
    with nav.stack("fc_lower"):
        left, right = st.columns([3, 2])
        with left, nav.card("fc_backtest"):
            st.subheader("Backtest")
            if bt is None or bt.empty:
                st.caption("No backtest for this series.")
            else:
                holdout = min(8, max(4, len(y) // 8))
                st.caption(f"How well each model did: fitted without the last {holdout} weeks, then scored on them. "
                           "Lower is better.")
                st.dataframe(nav.striped(bt.assign(BEST=["✓" if b else "" for b in bt.BEST])), hide_index=True,
                             row_height=36, width="stretch", column_order=["MODEL", "MAE", "RMSE", "MAPE", "BEST", "NOTE"],
                             column_config={
                                 "MODEL": "Model", "MAE": st.column_config.NumberColumn("MAE", format="%.3f"),
                                 "RMSE": st.column_config.NumberColumn("RMSE", format="%.3f"),
                                 "MAPE": st.column_config.NumberColumn("MAPE %", format="%.2f"),
                                 "BEST": st.column_config.TextColumn("Best", width="small"),
                                 "NOTE": st.column_config.TextColumn("Note", width="medium")})
        with right, nav.card("fc_notes"):
            st.subheader("Models and limitations")
            for r in results:
                last = r["forecast"].iloc[-1]
                st.markdown(f"**{r['model']}** · week {h}: {last.MEAN:,.2f} (80% {last.LO80:,.2f} to {last.HI80:,.2f})")
                st.caption(r["note"] + (f" AIC {r['aic']:,.1f}." if r["aic"] is not None else ""))
            st.markdown('<div class="sr-explain">Forecasts extend the measured weekly pattern only. They do not know '
                        "about planned listings, price changes or promotions. A wide band means low certainty.</div>",
                        unsafe_allow_html=True)


def stats_view() -> None:
    with nav.card("st_anomaly"):
        nav.section("Is this move unusual?", "Anomaly evidence stored by the weekly run for this shift")
        z, weeks = s.get("Z_SCORE"), s.get("ANOMALY_WEEKS")
        tiles = [("Size of the move (z-score)", "–" if z is None or pd.isna(z) else f"{float(z):+.1f}",
                  "Standard deviations from the brand's normal change for this comparison"),
                 ("Anomaly model", "Confirmed" if bool(s.get("ANOMALY_CONFIRMED")) else "Not confirmed",
                  "Confirmed when 2 or more of the last 4 weeks are anomalous (ANOMALY_DETECTION)"),
                 ("Anomalous weeks", "–" if weeks is None or pd.isna(weeks) else f"{int(weeks)}",
                  "Of the last 4 weeks, those outside the model's expected range")]
        st.markdown('<div class="sr-tiles">' + "".join(
            f'<div class="sr-jbox"><span class="k">{escape(k)}</span><b>{escape(v)}</b><span class="n">{escape(n)}</span></div>'
            for k, v, n in tiles) + "</div>", unsafe_allow_html=True)
    with nav.card("st_controls"):
        nav.section("Series statistics", _subject())
        measure = st.selectbox("Measure", list(MEASURES), key="st_measure")
    y = _series(measure)
    from sr_ui import forecast
    try:
        res = _stats(tuple(y.index.astype(str)), tuple(y.to_numpy()))
    except forecast.ForecastError as e:
        st.warning(str(e), icon=":material/warning:")
        return
    sig = "significant" if res["trend_p"] < 0.05 else "not significant"
    z = s.get("Z_SCORE")
    _say(("The move is " + (f"z {float(z):+.1f}" if z is not None and not pd.isna(z) else "without a z-score")
          + (", confirmed by the anomaly model" if bool(s.get("ANOMALY_CONFIRMED")) else ", not confirmed by the anomaly model")
          + f". {measure} trends {'down' if res['trend_per_week'] < 0 else 'up'} {abs(res['trend_per_week']):,.3f} a week "
          f"(p {res['trend_p']:.3g}, {sig})."))
    nav.kpi_row([
        ("Mean", f"{res['mean']:,.2f}", f"Over {res['n']} weeks; last {res['last']:,.2f}"),
        ("Trend per week", f"{res['trend_per_week']:+,.3f}", f"Linear trend, p = {res['trend_p']:.3g} ({sig})"),
        ("Volatility (CV)", "–" if res["cv"] is None else f"{100 * res['cv']:.1f}%", "Standard deviation / mean"),
        ("Seasonality", "–" if res["seasonality_strength"] is None else f"{res['seasonality_strength']:.2f}",
         f"Strength 0 to 1 over a {res['season_length']}-week season (STL)"),
    ], prefix="stats")
    nav.badges([(f"ADF p = {res['adf_p']:.3f}: " + ("stationary" if res["stationary"] else "not stationary"),
                 "ok" if res["stationary"] else "warn"),
                (f"Week-on-week mean {res['wow_mean']:+,.3f} ± {res['wow_std']:,.3f}", ""),
                (f"Range {res['min']:,.2f} to {res['max']:,.2f}", "")])
    with nav.stack("st_lower"):
        left, right = st.columns([3, 2])
        with left, nav.card("st_decomp"):
            st.subheader("Trend, season and residual")
            if res["decomposition"] is None:
                st.caption("Too little history for a seasonal decomposition.")
            else:
                st.altair_chart(charts.decomposition_chart(res["decomposition"]), width="stretch")
        with right, nav.card("st_hist"):
            st.subheader("Week-on-week changes")
            st.altair_chart(charts.change_histogram(res["wow"], "Change per week"), width="stretch")
    with st.expander("How to read these statistics", icon=":material/help:"):
        st.markdown(
            "- **z-score**: how far this shift's change is from the brand's usual change, in standard deviations. "
            "The weekly run's gate uses the MIN_Z setting.\n"
            "- **Trend per week and p**: the slope of a straight line through the weeks. A p below 0.05 means the "
            "slope is unlikely to be chance.\n"
            "- **Volatility (CV)**: the standard deviation as a share of the mean. Higher means a noisier series.\n"
            "- **Seasonality (STL)**: how much of the movement repeats each season, from 0 (none) to 1 (all).\n"
            "- **ADF**: a test of whether the series drifts (not stationary) or returns to a level (stationary).\n"
            "- **Trend, season and residual**: the series split into its long-run path, its repeating pattern and "
            "what is left over.")


MAP_MEASURES = {  # label -> (column, legend title, format, diverging)
    "Share change, pts": ("SHARE_CHG_PTS", "Share change, pts", "+.2f", True),
    "Value share %": ("SHARE_PCT", "Value share %", ".2f", False),
    "Sales change %": ("SALES_CHG_PCT", "Sales change %", "+.1f", True),
    "Brand value sales": ("VALUE_SALES", "Brand value sales", ",.0f", False),
}


def _region_frame(weeks: int) -> pd.DataFrame:
    r = data.region_summary(s["CATEGORY"], s["BRAND"], weeks)
    if r.empty:
        return r
    r = r.copy()
    r["SHARE_PCT"] = 100 * r.VALUE_SALES / r.CAT_VALUE_SALES.where(r.CAT_VALUE_SALES != 0)
    share0 = 100 * r.VALUE_SALES_BEFORE / r.CAT_VALUE_SALES_BEFORE.where(r.CAT_VALUE_SALES_BEFORE != 0)
    r["SHARE_CHG_PTS"] = r.SHARE_PCT - share0
    r["SALES_CHG_PCT"] = 100 * (r.VALUE_SALES / r.VALUE_SALES_BEFORE.where(r.VALUE_SALES_BEFORE != 0) - 1)
    return r


def _regions_picked() -> list[str]:
    return list(st.session_state.get("sr_regions") or [])


def map_view() -> None:
    with nav.card("map_controls"):
        nav.section("Market footprint", f"{fmt.name(s['BRAND'])} · {s['CATEGORY']}: each tile is a region's "
                    "retailer. Hover a tile for the business stats; pick regions to focus the table and Product "
                    "Intelligence.")
        c1, c2 = nav.stack("map_ctl").columns([2, 1], vertical_alignment="bottom")
        measure = c1.segmented_control("Colour by", list(MAP_MEASURES), default="Share change, pts", key="map_measure") \
            or "Share change, pts"
        weeks = c2.segmented_control("Compare weeks", [4, 12], default=4, key="map_weeks",
                                     format_func=lambda w: f"Last {w} vs {w} before") or 4
    r = _region_frame(int(weeks))
    if r.empty:
        _empty("No retailer data for this brand and category.")
        return
    col, title, f, div = MAP_MEASURES[measure]
    ranked = r.dropna(subset=["SHARE_CHG_PTS"]).sort_values("SHARE_CHG_PTS")
    tot, tot0 = r.VALUE_SALES.sum(), r.VALUE_SALES_BEFORE.sum()
    if len(ranked):
        lo, hi = ranked.iloc[0], ranked.iloc[-1]
        best_k, best_i, best_w = _best(hi.SHARE_CHG_PTS, "region")
        _say(f"Largest share decline: {lo.RETAILER} ({lo.REGION}), {fmt.pts(lo.SHARE_CHG_PTS)}; {best_w}: {hi.RETAILER} "
             f"({hi.REGION}), {fmt.pts(hi.SHARE_CHG_PTS)}. Last {weeks} weeks vs the {weeks} before.")
        _cards([("payments", "Brand sales, all regions", fmt.money(tot, cur), "", f"Last {weeks} weeks"),
                ("percent", "Sales change", fmt.signed_pct(tot / tot0 - 1) if tot0 else "–",
                 _sign(tot / tot0 - 1) if tot0 else "", f"vs the {weeks} weeks before"),
                ("south_east", "Weakest region", fmt.pts(lo.SHARE_CHG_PTS), _sign(lo.SHARE_CHG_PTS), f"{lo.RETAILER} · {lo.REGION}"),
                (best_i, best_k, fmt.pts(hi.SHARE_CHG_PTS), _sign(hi.SHARE_CHG_PTS), f"{hi.RETAILER} · {hi.REGION}")])
    with nav.stack("map"):
        left, right = st.columns([1, 1])
        with left, nav.card("map_tiles"):
            # Region buttons above the map (Streamlit has no click selection on layered charts). The widget has its own
            # key; the choice is copied to sr_regions, which outlives this view, so the SKU view still sees it.
            regions = sorted(r.REGION.dropna().unique())
            held = st.session_state.get("map_regions")
            if held is None or any(g not in regions for g in held):     # first visit, or another brand's regions
                st.session_state.map_regions = [g for g in (_regions_picked() if held is None else held) if g in regions]
            picked = st.pills("Focus regions", regions, selection_mode="multi", key="map_regions",
                              help="Pick one or more regions; pick none to see all") or []
            st.session_state.sr_regions = list(picked)
            st.altair_chart(charts.region_tile_map(r, col, title, f, div, picked=list(picked)), width="stretch")
            st.caption("Diverging colours are centred on zero; picked regions are outlined.")
        with right, nav.card("map_table"):
            nav.section("Retailer stats")
            picked = _regions_picked()
            view = r[r.REGION.isin(picked)] if picked else r
            st.caption(("Selected: " + ", ".join(picked)) if picked else f"All regions · last {weeks} weeks vs {weeks} before")
            st.dataframe(nav.striped(pd.DataFrame({
                "Region": view.REGION, "Retailer": view.RETAILER,
                "Value sales": [fmt.money(v, cur) for v in view.VALUE_SALES],
                "Share": [fmt.pct(v / 100) for v in view.SHARE_PCT],
                "Change": [fmt.pts(v) for v in view.SHARE_CHG_PTS],
                "Sales change": [fmt.signed_pct(v / 100) for v in view.SALES_CHG_PCT],
                "SKUs": view.SKUS_SELLING, "Stores": view.STORES_SELLING})), hide_index=True, row_height=36, width="stretch")


SKU_MEASURES = {
    "Sales change %": ("SALES_CHG_PCT", "Sales change %", "+.0f", True),
    "Value sales": ("VALUE_SALES", "Value sales, last 4 weeks", ",.0f", False),
    "ACV distribution %": ("ACV_DIST_PCT", "ACV distribution %", ".0f", False),
}


def sku_view() -> None:
    picked = _regions_picked()
    with nav.card("sku_controls"):
        nav.section("Product intelligence", f"{fmt.name(s['BRAND'])} SKUs · last 4 weeks vs the 4 before"
                    + (f" · regions: {', '.join(picked)} (from Market Footprint)" if picked else " · all regions"))
        measure = st.segmented_control("Colour by", list(SKU_MEASURES), default="Sales change %", key="sku_measure") \
            or "Sales change %"
    k = data.sku_retailer(s["CATEGORY"], s["BRAND"], 4)
    if k.empty:
        _empty("No SKU data for this brand.")
        return
    k = k.copy()
    k["SALES_CHG_PCT"] = 100 * (k.VALUE_SALES / k.VALUE_SALES_BEFORE.where(k.VALUE_SALES_BEFORE != 0) - 1)
    if picked:
        k = k[k.REGION.isin(picked)]
    col, title, f, div = SKU_MEASURES[measure]
    agg = (k.groupby(["ITEM_DESC"], as_index=False)[["VALUE_SALES", "VALUE_SALES_BEFORE"]].sum())
    agg["SALES_CHG_PCT"] = 100 * (agg.VALUE_SALES / agg.VALUE_SALES_BEFORE.where(agg.VALUE_SALES_BEFORE != 0) - 1)
    ranked = agg.dropna(subset=["SALES_CHG_PCT"]).sort_values("SALES_CHG_PCT")
    if len(ranked):
        lo, hi = ranked.iloc[0], ranked.iloc[-1]
        best_k, best_i, best_w = _best(hi.SALES_CHG_PCT, "SKU")
        _say(f"Largest SKU decline: {lo.ITEM_DESC}, {lo.SALES_CHG_PCT:+.1f}% in value sales; {best_w}: {hi.ITEM_DESC}, "
             f"{hi.SALES_CHG_PCT:+.1f}%. Last 4 weeks vs the 4 before" + (f", regions {', '.join(picked)}." if picked else "."))
        acv = k.ACV_DIST_PCT.dropna()
        _cards([("inventory_2", "SKUs selling", f"{k.ITEM_DESC.nunique():,}", "", f"across {k.RETAILER.nunique():,} retailers"),
                ("south_east", "Weakest SKU", f"{lo.SALES_CHG_PCT:+.1f}%", _sign(lo.SALES_CHG_PCT), str(lo.ITEM_DESC)),
                (best_i, best_k, f"{hi.SALES_CHG_PCT:+.1f}%", _sign(hi.SALES_CHG_PCT), str(hi.ITEM_DESC)),
                ("store", "ACV distribution", f"{acv.min():.0f}–{acv.max():.0f}%" if len(acv) else "–", "", "lowest to highest")])
    with nav.card("sku_heat"):
        nav.section("SKUs by retailer", "Each cell is one SKU at one retailer. Hover a cell for its numbers.")
        st.altair_chart(charts.heatmap_retailer_sku(k, col, title, f, div), width="stretch")
    with nav.stack("sku_lower"):
        left, right = st.columns(2)
        with left, nav.card("sku_bars"):
            st.subheader("SKU change")
            st.altair_chart(charts.sku_bars(agg.dropna(subset=["SALES_CHG_PCT"])), width="stretch")
        with right, nav.card("brand_heat"):
            st.subheader("Brand share, week by week")
            b = data.brand_share_weeks(s["MARKET_ID"], s["CATEGORY"], 26)
            if b.empty:
                st.caption("No weekly share history.")
            else:
                b = b.assign(WEEK_END_DATE=pd.to_datetime(b.WEEK_END_DATE), BRAND=[fmt.name(x) for x in b.BRAND])
                st.altair_chart(charts.heatmap_week_brand(b, fmt.name(s["BRAND"])), width="stretch")
                st.caption(f"{markets.get(s['MARKET_ID'], s['MARKET_ID'])}, last 26 weeks. Darker is a higher share.")
    with nav.card("sku_detail"):
        nav.section("SKU detail", "The rows behind the heatmap. Sort by any column; download from the table's menu.")
        st.dataframe(nav.striped(pd.DataFrame({
            "SKU": k.ITEM_DESC.values, "Retailer": k.RETAILER.values, "Region": k.REGION.values,
            "Segment": k.SEGMENT.values, "Pack": k.PACK_SIZE.values, "Value sales": k.VALUE_SALES.values,
            "4 weeks before": k.VALUE_SALES_BEFORE.values, "Sales change %": k.SALES_CHG_PCT.values,
            "ACV distribution %": k.ACV_DIST_PCT.values})), hide_index=True, width="stretch", row_height=34,
            column_config={"Value sales": st.column_config.NumberColumn(format="localized"),
                           "4 weeks before": st.column_config.NumberColumn(format="localized"),
                           "Sales change %": st.column_config.NumberColumn(format="%+.1f"),
                           "ACV distribution %": st.column_config.NumberColumn(format="%.1f")})


def studio_view() -> None:
    """Insight Studio: role lenses, the workbench and the model lab (sr_ui/studio.py). Exploratory, not in the brief."""
    from sr_ui import studio
    studio.render(studio.Ctx(s, sid, run, markets, cur, takeaway, options, label=_short))


# The stored values (and so session state, deep links and tests) are unchanged; only the shown names changed.
VIEWS = {"Overview": ("Investigation", ":material/search_insights:", investigation),
         "Forecast": ("Future Trends", ":material/trending_up:", forecast_view),
         "Statistics": ("Statistical Evidence", ":material/functions:", stats_view),
         "Map and stores": ("Market Footprint", ":material/map:", map_view),
         "SKUs and heatmaps": ("Product Intelligence", ":material/grid_view:", sku_view),
         "Studio": ("Insight Studio", ":material/insights:", studio_view)}
URL_VIEW = {"investigation": "Overview", "trends": "Forecast", "statistics": "Statistics", "footprint": "Map and stores",
            "product": "SKUs and heatmaps", "studio": "Studio"}
_asked = URL_VIEW.get(str(st.query_params.get("view", "")))
if _asked and not st.session_state.get("_sr_view_from_url"):    # a link or refresh reopens the same tab, once
    st.session_state.shift_view = _asked
    st.session_state["_sr_view_from_url"] = True
if st.session_state.get("shift_view") not in VIEWS:          # first visit, or a value from an older session
    st.session_state.shift_view = "Overview"
with st.container(key="sr_tabs"):                                # a single-choice radio, styled as a tab bar (nav.CSS)
    view = st.radio("View", list(VIEWS), key="shift_view", horizontal=True, label_visibility="collapsed",
                    format_func=lambda v: VIEWS[v][0]) or "Overview"
st.query_params["view"] = {v: k for k, v in URL_VIEW.items()}[view]
if view == "Overview":
    investigation()
else:
    nav.guarded(VIEWS[view][0], VIEWS[view][2])
