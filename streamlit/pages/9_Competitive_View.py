"""Competitive View (Intelligence): the focus brand against the competitors the analyst picks, in the current scope's
category. Three views: Competitive Overview (position), Share Drivers (why) and Opportunities & Risks (where to act).

Every figure comes from data.py reads on the app's existing views (share_report, competitive_share_week,
competitive_regions, promo_index, watchlist, shifts). The page only compares those figures (a focus value against the
competitor average) and states them; Chippy's sentences and suggested questions are templates filled with the same
numbers, never model text. Session-only actions (Watchlist, Case Files) go through sr_ui.workspace, and only for a
shift in the current run. Chippy's hero, KPI cards and docked assistant reuse the Radar components."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, nav, workspace
nav.entry_guard("pages/9_Competitive_View.py")   # a refresh or direct link still opens inside the app

PARITY = 5.0          # % either side of the competitor average that reads as parity (presentation band, not a gate)
VIEWS = ["Competitive Overview", "Share Drivers", "Opportunities & Risks"]
PERIODS = {4: "Last 4 weeks", 13: "Last 13 weeks", 52: "Last 52 weeks"}
COMPARE = {"previous": "vs prior period", "year_ago": "vs year ago"}

extra = nav.radar_header("Competitive View", "Understand your position. Identify the gap.")
run = data.current_run()
category = data.cfg("SCOPE_CATEGORY")
parent = str(data.cfg("SCOPE_PARENT_MARKET"))
focus_mfr = data.cfg("FOCUS_MANUFACTURER")
cur = data.cfg("CURRENCY") or ""
markets = data.market_names()
show = fmt.name                                     # display names (aliases when DISPLAY_ALIAS is on)


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _rel(a, b) -> float | None:
    """Relative gap of a against b, in %."""
    a, b = _num(a), _num(b)
    return None if a is None or b in (None, 0) else 100 * (a / b - 1)


def _f(v, spec: str, suffix: str = "") -> str:
    v = _num(v)
    return "–" if v is None else f"{v:{spec}}{suffix}"


def _shown(df: pd.DataFrame) -> pd.DataFrame:
    """Brand and manufacturer names as the app shows them, so no chart, table or export leaks a masked name."""
    out = df.copy()
    if "BRAND" in out:
        out["BRAND"] = out.BRAND.map(show)
    if "MANUFACTURER" in out:
        out["MANUFACTURER"] = out.MANUFACTURER.map(lambda m: show(m, "MANUFACTURER"))
    return out


# ---- Filters: one row ------------------------------------------------------------------------------------------------

if run is None:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No weekly run yet, so there is nothing to compare.", key="cv_empty")
    nav.stop()

with st.container(key="sr_cv_filters"):
    c1, c2, c3, c4, c5 = st.columns([1.3, 3, 1.15, 1.2, 1], vertical_alignment="bottom", gap="small")
    weeks = c3.selectbox("Period", list(PERIODS), key="cv_weeks", format_func=PERIODS.get) or 4
    compare = c4.selectbox("Compared with", list(COMPARE), key="cv_compare", format_func=COMPARE.get) or "previous"
    measure = c5.selectbox("Share basis", ["value", "volume"], key="cv_measure", format_func=str.title) or "value"
    try:
        rep = data.share_report(category, int(weeks), compare, None, measure)
    except Exception as e:                                   # too few weeks for this period and comparison
        rep = pd.DataFrame()
        st.warning(f"This period cannot be compared yet: {e}", icon=":material/warning:")
    brands = list(rep.BRAND) if len(rep) else []
    if not brands:
        nav.mascot("sleepy", "No brand sales in this period.", "Try a shorter period or the prior-period comparison.",
                   key="cv_nodata")
        nav.stop()
    own = [b for b in brands if (rep.loc[rep.BRAND == b, "MANUFACTURER"] == focus_mfr).any()]
    if st.session_state.get("cv_focus") not in brands:
        st.session_state["cv_focus"] = own[0] if own else brands[0]
    focus = c1.selectbox("Focus brand", brands, key="cv_focus", format_func=show)
    others = [b for b in brands if b != focus]
    kept = [b for b in st.session_state.get("cv_comp", []) if b in others]
    st.session_state["cv_comp"] = kept or others[:3]
    comps = c2.multiselect("Competitors", others, key="cv_comp", format_func=show, max_selections=6,
                           placeholder="Pick competitors") or others[:3]

basis = "Volume share" if measure == "volume" else "Value share"
period = f"last {weeks} weeks vs {'the prior ' + str(weeks) if compare == 'previous' else 'the same weeks a year ago'}"
sel = rep[rep.BRAND.isin([focus] + comps)].copy()
f_row = rep[rep.BRAND == focus].iloc[0]
c_rows = rep[rep.BRAND.isin(comps)]
promo = data.promo_index(parent, category, int(weeks), compare)
sel = sel.merge(promo[["BRAND", "PROMO_INDEX", "PROMO_INDEX_BEFORE"]], on="BRAND", how="left")
shifts = data.shifts(run.run_id)
f_shift = shifts[(shifts.BRAND == focus) & (shifts.MARKET_ID == parent)]
f_shift = f_shift.reindex(f_shift.D_SHARE_PTS.abs().sort_values(ascending=False).index).iloc[0].to_dict() \
    if len(f_shift) else None
st.html(f'<div class="sr-cv-scope"><span class="sr-ico" aria-hidden="true">tune</span>'
        f'<span>{escape(str(category))} · {escape(markets.get(parent, parent))} · all retailers · {escape(basis.lower())}, '
        f'{escape(period)} · names {"masked" if data.cfg("DISPLAY_ALIAS") is True else "shown"}</span></div>')


# ---- Shared figures (all read from the share report, the regional view and the run) ------------------------------

leader = rep.iloc[0]
runner = rep.iloc[1] if len(rep) > 1 else None
gap_leader = _num(leader.SHARE) - _num(f_row.SHARE)
comp_acv = c_rows.ACV.mean() if len(c_rows) else np.nan
comp_vel = c_rows.VELOCITY.mean() if len(c_rows) else np.nan


def _sign(v) -> str:
    v = _num(v)
    return "" if v is None or v == 0 else ("pos" if v > 0 else "neg")


def _regions(category: str, weeks: int, compare: str, measure: str) -> pd.DataFrame | None:
    try:
        return data.competitive_regions(category, weeks, compare, measure)
    except Exception:                                         # too few weeks for this comparison
        return None


def retailer_gaps() -> pd.DataFrame:
    """Per retailer: the focus brand's share, change, ACV and velocity against the competitor average there, and the
    competitor that gained most. Empty when the regional view has no data for this selection."""
    reg = _regions(category, int(weeks), compare, measure)
    if reg is None or reg.empty:
        return pd.DataFrame()
    f = reg[reg.BRAND == focus].set_index("MARKET_ID")
    c = reg[reg.BRAND.isin(comps)]
    if f.empty or c.empty:
        return pd.DataFrame()
    cg = c.groupby("MARKET_ID").agg(C_ACV=("ACV", "mean"), C_BEST_ACV=("ACV", "max"), C_VEL=("VELOCITY", "mean"))
    top = c.sort_values("SHARE_CHG_PTS", ascending=False).groupby("MARKET_ID").head(1).set_index("MARKET_ID")
    o = f.join(cg).join(top[["BRAND", "SHARE_CHG_PTS"]].rename(columns={"BRAND": "TOP_GAINER",
                                                                       "SHARE_CHG_PTS": "TOP_GAIN_PTS"}))
    o["ACV_GAP_PTS"] = o.ACV - o.C_ACV
    o["VEL_GAP_PCT"] = 100 * (o.VELOCITY / o.C_VEL - 1)
    return o


def threats_and_opportunities() -> tuple[list[tuple], list[tuple]]:
    """(title, evidence, tone, value, unit, bar label) lists, strongest first; value is None where there is no bar: competitor gains overall and where the focus brand lost, early
    warnings on competitors; retailers where the focus brand trails on distribution or velocity."""
    o = retailer_gaps()
    threats = [(f"{show(r.BRAND)} gained {fmt.pts(r.SHARE_CHG_PTS)}",
                f"sales {_f(r.SALES_GROWTH_PCT, '+.1f', '%')}" + (f", up {int(r.RANK_CHG)} rank"
                                                                 if _num(r.RANK_CHG) and r.RANK_CHG > 0 else ""), "warn",
                float(r.SHARE_CHG_PTS), "pts", f"{show(r.BRAND)} · all retailers")
               for r in c_rows[c_rows.SHARE_CHG_PTS > 0].sort_values("SHARE_CHG_PTS", ascending=False).itertuples()]
    if len(o):
        for _, r in o[(o.SHARE_CHG_PTS < 0) & (o.TOP_GAIN_PTS > 0)].sort_values("SHARE_CHG_PTS").iterrows():
            threats.append((f"{show(r.TOP_GAINER)} took ground at {r.RETAILER}",
                            f"{fmt.pts(r.TOP_GAIN_PTS)} while {show(focus)} moved {fmt.pts(r.SHARE_CHG_PTS)}", "bad",
                            float(r.TOP_GAIN_PTS), "pts", f"{show(r.TOP_GAINER)} · {r.RETAILER}"))
    ew = data.watchlist(run.run_id)
    for r in ew[ew.BRAND.isin(comps)].itertuples():
        threats.append((f"Early warning: {show(r.BRAND)} · {markets.get(r.MARKET_ID, r.MARKET_ID)}",
                        f"{'Distribution' if r.SIGNAL == 'DIST_DROP' else 'Price'} signal, projected "
                        f"{fmt.pts(r.PROJECTED_SHARE_PTS)} next four weeks", "warn", None, "", ""))
    opps = []
    if len(o):
        for _, r in o.sort_values("ACV_GAP_PTS").iterrows():
            if r.ACV_GAP_PTS < -PARITY:
                opps.append((f"Distribution at {r.RETAILER}", f"ACV {r.ACV:.1f}% vs {r.C_ACV:.1f}% competitor average "
                             f"(best {r.C_BEST_ACV:.1f}%)", "ok", float(-r.ACV_GAP_PTS), "ACV pts", r.RETAILER))
        for _, r in o.sort_values("VEL_GAP_PCT").iterrows():
            if r.VEL_GAP_PCT < -PARITY:
                opps.append((f"Velocity at {r.RETAILER}", f"{r.VELOCITY:,.2f} vs {r.C_VEL:,.2f} units/store/wk "
                             "competitor average", "ok", float(-r.VEL_GAP_PCT), "%", r.RETAILER))
    return threats, opps


def driver_table() -> pd.DataFrame:
    """Focus brand, competitor average and the relative gap on each driver; kind sets the bar's polarity."""
    p_f = sel.loc[sel.BRAND == focus, "PROMO_INDEX"]
    p_c = sel.loc[sel.BRAND.isin(comps), "PROMO_INDEX"].mean()
    rows = [("Distribution (ACV)", f_row.ACV, comp_acv, ".1f", "%", True),
            ("Velocity", f_row.VELOCITY, comp_vel, ",.2f", "", True),
            ("Price index", f_row.PRICE_INDEX, c_rows.PRICE_INDEX.mean(), ".2f", "", None),
            ("Promo index", p_f.iloc[0] if len(p_f) else np.nan, p_c, ".2f", "", None),
            ("Fair-share index", f_row.FAIR_SHARE_INDEX, c_rows.FAIR_SHARE_INDEX.mean(), ".0f", "", True)]
    out = []
    for name, a, b, spec, suf, good_up in rows:
        g = _rel(a, b)
        if g is None:
            continue
        kind = "total" if good_up is None else ("gain" if g >= 0 else "loss")
        out.append({"DRIVER": name, "GAP": round(g, 2), "UNIT": "%", "kind": kind, "FOCUS": _num(a), "COMP": _num(b),
                    "FOCUS_TXT": _f(a, spec, suf), "COMP_TXT": _f(b, spec, suf)})
    gr_f, gr_c = _num(f_row.SALES_GROWTH_PCT), c_rows.SALES_GROWTH_PCT.mean()
    if gr_f is not None and not pd.isna(gr_c):
        out.append({"DRIVER": "Sales growth", "GAP": round(gr_f - gr_c, 2), "UNIT": "pts",   # a difference, not a ratio
                    "kind": "gain" if gr_f >= gr_c else "loss", "FOCUS": gr_f, "COMP": float(gr_c),
                    "FOCUS_TXT": _f(gr_f, "+.1f", "%"), "COMP_TXT": _f(gr_c, "+.1f", "%")})
    return pd.DataFrame(out)


def suggestions(threats, opps) -> list[tuple[str, str]]:
    """(short label, full prompt) pairs built from this selection's figures. Buttons show the label; Chippy is asked the
    full prompt, and the docked assistant lists the same prompts."""
    fb = show(focus)
    verb = "lose" if (_num(f_row.SHARE_CHG_PTS) or 0) < 0 else "gain"
    qs = [(f"Why did {fb} {verb} share?", f"Why did {fb} {verb} {basis.lower()} in {category}, {period}?")]
    top = c_rows[c_rows.SHARE_CHG_PTS > 0].sort_values("SHARE_CHG_PTS", ascending=False)
    if len(top):
        rival = show(top.iloc[0].BRAND)
        qs.append((f"Where is {rival} gaining?", f"Where is {rival} taking share from {fb}?"))
    d = driver_table()
    sig = d[d.kind != "total"] if len(d) else d
    if len(sig) and sig.GAP.min() < -PARITY:
        drv = sig.loc[sig.GAP.idxmin()].DRIVER
        qs.append((f"How to close the {drv} gap?", f"How can {fb} close its {drv} gap against competitors?"))
    if opps:
        gap = opps[0][0][0].lower() + opps[0][0][1:]
        qs.append((f"Worth of the {gap} gap?", f"What would closing the {gap} gap be worth for {fb}?"))
    return qs[:4]


# ---- KPI cards (the Radar KPI card markup and styles) ------------------------------------------------------------

def _kpi(col, key: str, icon: str, label: str, value: str, context: str, chip: str = "", tone: str = "",
         prior: str = "") -> None:
    chip_html = f'<span class="sr-cv-chip {tone}">{escape(chip)}</span>' if chip else ""
    with col.container(border=True, key=f"sr_kpi_radar_cv_{key}"):
        st.html(f'<div class="sr-cv-kpi"><div class="h"><span class="sr-ico" aria-hidden="true">{icon}</span>'
                f'<span class="l">{escape(label)}</span>{chip_html}</div><b>{escape(value)}</b>'
                f'<em class="sr-cv-ctx">{escape(context)}</em>'
                + (f'<small class="sr-cv-prior">{escape(prior)}</small>' if prior else "") + "</div>")


def _chip(v: float | None, up: str, down: str, flat: str = "No change") -> tuple[str, str]:
    if v is None or abs(v) < 1e-9:
        return flat, "no-change"
    return (f"▲ {up}", "higher") if v > 0 else (f"▼ {down}", "lower")


def kpi_cards() -> None:
    chg = _num(f_row.SHARE_CHG_PTS)
    rank, rank_chg = int(f_row.RANK), _num(f_row.RANK_CHG)
    with st.container(key="sr_radar_kpis"):
        cols = st.columns(4)
        chip, tone = _chip(chg, f"{fmt.pts(chg)}", f"{fmt.pts(chg)}")
        _kpi(cols[0], "share", "pie_chart", basis, _f(f_row.SHARE, ".1f", "%"),
             f"of {category}, all retailers", chip, tone, f"Before: {_f(f_row.SHARE_BEFORE, '.1f', '%')}")
        chip, tone = _chip(rank_chg, f"Up {abs(int(rank_chg or 0))}", f"Down {abs(int(rank_chg or 0))}")
        _kpi(cols[1], "rank", "leaderboard", "Competitive rank", f"#{rank} of {len(rep)}",
             "Category leader" if rank == 1 else f"Behind {show(leader.BRAND)}", chip, tone,
             f"Before: #{int(f_row.RANK_BEFORE)}" if _num(f_row.RANK_BEFORE) else "")
        other = runner if rank == 1 else leader                      # the brand the gap is measured against
        if other is not None:
            gap_now = _num(f_row.SHARE) - _num(other.SHARE)
            gap_before = (_num(f_row.SHARE_BEFORE) - _num(other.SHARE_BEFORE)
                          if _num(f_row.SHARE_BEFORE) is not None and _num(other.SHARE_BEFORE) is not None else None)
            move = None if gap_before is None else gap_now - gap_before
            chip, tone = _chip(move, "Gap improved", "Gap worsened")
            _kpi(cols[2], "gap", "flag", "Lead over #2" if rank == 1 else "Gap to leader", fmt.pts(gap_now),
                 f"{'over' if rank == 1 else 'behind'} {show(other.BRAND)}", chip, tone,
                 f"Before: {fmt.pts(gap_before)}" if gap_before is not None else "")
        adv = (_num(f_row.ACV) - comp_acv) if len(c_rows) and _num(f_row.ACV) is not None else None
        chip, tone = _chip(adv, "Ahead on shelf", "Behind on shelf")
        _kpi(cols[3], "dist", "storefront", "Distribution advantage" if (adv or 0) >= 0 else "Distribution gap",
             "–" if adv is None else f"{adv:+.1f} pts ACV",
             f"Mean ACV {_f(f_row.ACV, '.1f', '%')} vs {_f(comp_acv, '.1f', '%')} competitor average", chip, tone,
             f"Fair-share index {_f(f_row.FAIR_SHARE_INDEX, '.0f')}")


# ---- Chippy: the Radar hero, with threats, opportunities and suggested questions -----------------------------------

def _ask_in_dock(question: str) -> None:
    st.session_state["sr_radar_chat_open"] = True          # the docked assistant, as on Radar
    st.session_state["sr_dock_pending"] = question


def _pill(icon: str, label: str, item, tone: str, empty: str) -> str:
    body = (f"<b>{escape(item[0])}</b><span>{escape(item[1])}</span>" if item else f"<span>{escape(empty)}</span>")
    return (f'<div class="sr-cv-pill {tone}"><span class="sr-ico" aria-hidden="true">{icon}</span>'
            f'<em>{escape(label)}</em>{body}</div>')


def chippy(threats, opps, qs) -> None:
    """Compact Chippy summary (the Radar hero): headline, the top threat and the top opportunity; the rest of the
    threats, opportunities and questions open from popovers, so the tabs and charts stay near the fold."""
    chg = _num(f_row.SHARE_CHG_PTS) or 0
    rank = int(f_row.RANK)
    head = (f"{show(focus)} {'leads' if rank == 1 else f'ranks #{rank} in'} {category} at {_f(f_row.SHARE, '.1f', '%')} "
            f"{basis.lower()}, {'losing' if chg < 0 else 'gaining' if chg > 0 else 'holding'} ground.")
    numbers = [("Share movement", fmt.pts(chg), "negative" if chg < 0 else "positive" if chg > 0 else ""),
               ("Competitors gaining", str(int((c_rows.SHARE_CHG_PTS > 0).sum())), ""),
               ("Retailer gaps", str(len(opps)), "")]
    nums = "".join(f'<div><span>{escape(k)}</span><b class="{t}">{escape(v)}</b></div>' for k, v, t in numbers)
    with nav.hero("radar"):
        avatar = nav.mascot_html("detective", "Detective Chippy", 112, html_safe=True) or ""
        st.html(f'<div class="sr-radar-hero-main">{avatar}<div class="sr-radar-finding">'
                '<span class="sr-radar-speech sr-typing" aria-label="Here is how you stack up."><span class="sr-dots" '
                'aria-hidden="true"><i></i><i></i><i></i></span><span class="sr-type">Here is how you stack up.</span></span>'
                f'<h2>{escape(head)}</h2><div>{escape(markets.get(parent, parent))} · {escape(period)}</div></div>'
                f'<div class="sr-radar-numbers">{nums}</div></div>'
                '<div class="sr-cv-pills">'
                + _pill("warning", "Top threat", threats[0] if threats else None, "warn", "No competitor is gaining.")
                + _pill("lightbulb", "Top opportunity", opps[0] if opps else None, "ok",
                        "At or above the competitor average everywhere.") + "</div>")
        with st.container(key="sr_cv_questions", horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<span class="sr-cv-qlabel">Ask Chippy</span>', width="content")
            for i, (label, q) in enumerate(qs[:2]):           # two suggested questions; the rest under View more
                st.button(label, key=f"cv_q_{i}", icon=":material/chat_bubble:", on_click=_ask_in_dock, args=(q,),
                          help=q)
            if len(qs) > 2:
                with st.popover("View more", icon=":material/more_horiz:"):
                    for i, (label, q) in enumerate(qs[2:], 2):
                        st.button(q, key=f"cv_q_{i}", icon=":material/chat_bubble:", on_click=_ask_in_dock,
                                  args=(q,), type="tertiary")
        with st.container(key="sr_radar_actions", horizontal=True, vertical_alignment="center", gap="small"):
            if f_shift is not None and st.button("Investigate shift", key="cv_shift", type="primary",
                                                 icon=":material/arrow_forward:"):
                st.session_state.shift_id = f_shift["SHIFT_ID"]
                st.switch_page("pages/1_Shift_detail.py")
            if st.button("Open Ask Chippy", key="cv_ask", icon=":material/forum:",
                         help="Opens Ask Chippy with a question about this comparison"):
                st.session_state["sr_ask_about"] = qs[0][1]
                st.session_state["chat_agent"] = data.AGENT
                st.switch_page("pages/5_Ask_Chippy.py")
            if len(threats) + len(opps) > 2:
                with st.popover(f"All risks & gaps ({len(threats) + len(opps)})", icon=":material/list:"):
                    st.html('<p class="sr-cv-pop-h">Watch out</p><ul class="sr-cv-threats">'
                            + _items(threats, "No competitor is gaining on this brand.") + "</ul>"
                            '<p class="sr-cv-pop-h">Opportunities</p><ul class="sr-cv-threats">'
                            + _items(opps, "At or above the competitor average everywhere.") + "</ul>")
            if f_shift is not None:                           # right-aligned (radar.css: margin-left:auto)
                watched = workspace.is_watched(workspace.row_key(f_shift))
                if st.button("", key="cv_watch", disabled=watched, icon=":material/bookmark:",
                             help="On your watchlist" if watched else "Add to Watchlist"):
                    workspace.add_watch(f_shift, run.run_id)
                    st.toast("Added to your watchlist for this session.")
                    st.rerun()
                if st.button("", key="cv_case", icon=":material/folder_open:", help="Save to Case file"):
                    ck = workspace.open_case(f_shift, run.run_id, run.as_of_week)
                    workspace.add_note(ck, "Competitive View: " + head + " "
                                       + " ".join(f"{a} ({b})." for a, b, *_ in (threats[:2] + opps[:2])))
                    st.switch_page("pages/7_Case_Files.py")


def _export(df: pd.DataFrame, name: str, key: str) -> None:
    st.download_button("Export CSV", _shown(df).to_csv(index=False).encode("utf-8"),
                       file_name=f"competitive_view_{name}_{weeks}w.csv", mime="text/csv", key=f"cv_dl_{key}",
                       icon=":material/download:", type="tertiary")


# ---- Competitive Overview: trends and movement, the scorecard, then positioning and what it means ------------------

# (group, [(measure, column, format, direction)]): direction +1 higher is better, -1 lower is better, 0 neither
SCORE = [("Share", [("Share %", "SHARE", ".2f", 1), ("Share change, pts", "SHARE_CHG_PTS", "+.2f", 1),
                    ("Rank", "RANK", ".0f", -1)]),
         ("Sales", [(f"Value sales{' (' + cur + ')' if cur else ''}", "SALES", ",.0f", 1),
                    ("Sales growth %", "SALES_GROWTH_PCT", "+.1f", 1)]),
         ("Distribution", [("Mean ACV %", "ACV", ".1f", 1), ("Share of distribution points %", "TDP_SHARE", ".1f", 1),
                           ("Fair-share index", "FAIR_SHARE_INDEX", ".0f", 1)]),
         ("Rate of sale and price", [("Velocity, units/store/wk", "VELOCITY", ",.2f", 1),
                                     ("Price index", "PRICE_INDEX", ".2f", 0), ("Promo index", "PROMO_INDEX", ".2f", 0)])]
BEST, WORST = "background-color: #dcebe8; color: #173f43; font-weight: 700", \
    "background-color: rgba(200, 121, 112, 0.16); color: #7f3a33"


def scorecard():
    """The scorecard as a Styler: metrics grouped, the best value in each row teal and the weakest terracotta (rows
    where higher or lower is better), the focus brand's column bold. Values are the share report's, formatted."""
    order = [focus] + comps
    names = [show(b) for b in order]
    disp, num, dirs, band = [], [], [], []
    for g, (group, rows) in enumerate(SCORE):
        for k, (label, col, spec, direction) in enumerate(rows):
            vals = [_num(sel.loc[sel.BRAND == b, col].iloc[0]) if col in sel else None for b in order]
            disp.append([group if k == 0 else "", label] + [_f(v, spec) for v in vals])
            num.append(vals)
            dirs.append(direction)
            band.append(g % 2)
    shown_df = pd.DataFrame(disp, columns=["Group", "Measure"] + names)

    def style(frame):
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        for i in frame.index:
            if band[i]:
                out.iloc[i, :] = "background-color: #f5f8f8"
            out.iloc[i, 0] += "; font-weight: 600; color: #1e5556"
            out.iloc[i, 2] += "; font-weight: 700; color: #1e5556"          # the focus brand
            vals = [v for v in num[i] if v is not None]
            if dirs[i] and len(vals) > 1 and max(vals) != min(vals):
                best = max(vals) if dirs[i] > 0 else min(vals)
                worst = min(vals) if dirs[i] > 0 else max(vals)
                for j, v in enumerate(num[i]):
                    if v == best:
                        out.iloc[i, 2 + j] = BEST
                    elif v == worst:
                        out.iloc[i, 2 + j] = WORST
        return out
    return shown_df.style.apply(style, axis=None), len(shown_df)


def interpretation() -> str:
    """What the positioning matrix says, from the plotted figures only: each brand's quadrant against the selected
    brands' averages, what that means for the focus brand, and its closest rival on the matrix."""
    d = sel.dropna(subset=["ACV", "VELOCITY"])
    if d.empty or focus not in set(d.BRAND):
        return "<p>No distribution and velocity figures for this selection.</p>"
    ax, ay = d.ACV.mean(), d.VELOCITY.mean()
    quad = {r.BRAND: charts.CV_QUADRANTS[(r.ACV >= ax, r.VELOCITY >= ay)] for r in d.itertuples()}
    f = d[d.BRAND == focus].iloc[0]
    fb, q = show(focus), quad[focus]
    acv_gap, vel_rel = f.ACV - ax, 100 * (f.VELOCITY / ay - 1)
    evid = f"ACV {f.ACV:.1f}% vs {ax:.1f}% average, velocity {f.VELOCITY:,.2f} vs {ay:,.2f}"
    means = {"Leaders": f"{fb} is broad and fast-selling: defend shelf space and price position ({evid}).",
             "Under-distributed": f"{fb} sells {vel_rel:+.0f}% faster than average on {abs(acv_gap):.1f} fewer ACV "
                                  "points: wider distribution is the best-evidenced growth lever.",
             "Wide but slow": f"{fb} is on {acv_gap:.1f} more ACV points but sells {abs(vel_rel):.0f}% slower: review "
                              "range, price and visibility before adding stores.",
             "Niche or at risk": f"{fb} is below average on both distribution and rate of sale ({evid}): concentrate "
                                 "on the core range and the retailers where it sells best."}[q]
    others = d[d.BRAND != focus]
    rival = ""
    if len(others):
        dist = (((others.ACV - f.ACV) / max(d.ACV.std(), 1e-9)) ** 2
                + ((others.VELOCITY - f.VELOCITY) / max(d.VELOCITY.std(), 1e-9)) ** 2)
        r = others.loc[dist.idxmin()]
        rival = (f"Closest rival on the matrix: <b>{escape(show(r.BRAND))}</b> ({escape(quad[r.BRAND])}, ACV "
                 f"{r.ACV:.1f}%, velocity {r.VELOCITY:,.2f}).")
    rows = "".join(f'<li><span class="sr-cv-q {"focus" if b == focus else ""}">{escape(show(b))}</span>'
                   f'<em>{escape(quad[b])}</em><small>ACV {a:.1f}% · {v:,.2f} u/s/wk</small></li>'
                   for b, a, v in zip(d.BRAND, d.ACV, d.VELOCITY))
    return (f'<div class="sr-cv-interp"><p class="lead"><span class="sr-ico" aria-hidden="true">insights</span>'
            f'<span><b>{escape(fb)}: {escape(q)}.</b> {escape(means)}</span></p>'
            + (f'<p class="rival">{rival}</p>' if rival else "")
            + f'<p class="h">Where each brand sits</p><ul>{rows}</ul>'
            f'<p class="n">Quadrants split at the selected brands\' averages: ACV {ax:.1f}%, velocity {ay:,.2f}.</p></div>')


def overview() -> None:
    top_l, top_r = nav.stack("cv_ov1").columns([3, 2])
    with top_l, nav.card("cv_trend"):
        nav.section("Market share trends", f"Weekly {basis.lower()}, all retailers. Solid teal is {show(focus)}; "
                    "hover for each week.")
        tr = data.competitive_share_week(category, max(int(weeks), 26), measure)
        if tr.empty:
            st.caption("No weekly sales in this window.")
        else:
            st.altair_chart(charts.cv_share_trend(_shown(tr), show(focus), [show(c) for c in comps], f"{basis} %"),
                            width="stretch")
    with top_r, nav.card("cv_move"):
        nav.section("Share movement", f"Change in {basis.lower()}, points, {period}.")
        st.altair_chart(charts.cv_movement_bars(_shown(sel), show(focus), [show(c) for c in comps]), width="stretch")
    with nav.card("cv_matrix"):
        nav.section("Competitor scorecard", "Grouped measures; in each row the best value is teal and the weakest "
                    "terracotta (price and promo are not ranked). The focus brand is the first, bold column.")
        styled, n = scorecard()
        st.dataframe(styled, hide_index=True, width="stretch", row_height=30, height=30 * (n + 1) + 4,
                     column_config={"Group": st.column_config.TextColumn("Group", width="small"),
                                    "Measure": st.column_config.TextColumn("Measure", width="medium")})
        _export(sel, "scorecard", "ov")
    bot_l, bot_r = nav.stack("cv_ov3").columns([3, 2])
    with bot_l, nav.card("cv_bubble"):
        nav.section("Positioning matrix", "Distribution against velocity; bubble size is value sales. Quadrants split "
                    "at the selected brands' averages.")
        st.altair_chart(charts.cv_bubble(_shown(sel), show(focus), [show(c) for c in comps], cur), width="stretch")
    with bot_r, nav.card("cv_interp"):
        nav.section("Strategic interpretation", "What the matrix means for the focus brand.")
        st.html(interpretation())


# ---- Share Drivers ---------------------------------------------------------------------------------------------------

def _gap_txt(r) -> str:
    return f"{r.GAP:+.1f} pts" if r.UNIT == "pts" else f"{r.GAP:+.1f}% vs avg"


def assessment(d: pd.DataFrame) -> str:
    """Strengths, weaknesses, parity and price/promo positioning as colour-coded sections; empty sections are hidden.
    Each line keeps its evidence: the focus value, the competitor average and the gap in its own unit."""
    ranked = d[d.kind != "total"]
    sections = [("Strengths", ranked[ranked.GAP > PARITY], "pos", "trending_up", True),
                ("Weaknesses", ranked[ranked.GAP < -PARITY], "neg", "trending_down", True),
                ("At parity", ranked[ranked.GAP.abs() <= PARITY], "", "drag_handle", True),
                ("Price and promo positioning", d[d.kind == "total"], "price", "sell", False)]
    html = ""
    for title, frame, tone, icon, gap in sections:
        if frame.empty:
            continue
        items = "".join(f'<li><b>{escape(r.DRIVER)}</b><span>{escape(r.FOCUS_TXT)} vs {escape(r.COMP_TXT)}'
                        + (f' <i>{escape(_gap_txt(r))}</i>' if gap else f' <i>{r.GAP:+.1f}% vs avg</i>')
                        + "</span></li>" for r in frame.sort_values("GAP", ascending=tone == "neg").itertuples())
        html += (f'<div class="sr-cv-sw {tone}"><p><span class="sr-ico" aria-hidden="true">{icon}</span>'
                 f'{escape(title)}<em>{len(frame)}</em></p><ul>{items}</ul></div>')
    return html or "<p>No comparable drivers for this selection.</p>"


def recommendation(d: pd.DataFrame) -> str:
    """One recommendation from the gaps above: close the largest weakness, using the clearest strength as the case for
    it; then where price and promotion sit. Every number is a figure already shown on this tab."""
    fb = show(focus)
    ranked = d[d.kind != "total"]
    weak = ranked[ranked.GAP < -PARITY].sort_values("GAP")
    strong = ranked[ranked.GAP > PARITY].sort_values("GAP", ascending=False)
    if len(weak):
        w = weak.iloc[0]
        head = f"Prioritise {w.DRIVER}."
        body = (f"{fb} trails the selected competitors on {w.DRIVER} ({w.FOCUS_TXT} vs {w.COMP_TXT}, "
                f"{_gap_txt(w)}), the largest gap on this tab.")
        if len(strong):
            s = strong.iloc[0]
            body += f" Its lead on {s.DRIVER} ({_gap_txt(s)}) is the case to make for closing it."
    elif len(strong):
        s = strong.iloc[0]
        head = f"Defend the {s.DRIVER} lead."
        body = f"{fb} has no driver below parity; {s.DRIVER} is its clearest edge ({s.FOCUS_TXT} vs {s.COMP_TXT})."
    else:
        head, body = "Hold position.", f"{fb} is within ±{PARITY:.0f}% of the competitor average on every ranked driver."
    pp = d[d.kind == "total"].set_index("DRIVER")
    if "Price index" in pp.index and abs(pp.loc["Price index", "GAP"]) > PARITY:
        g = pp.loc["Price index", "GAP"]
        body += (f" It is priced {abs(g):.0f}% {'above' if g > 0 else 'below'} the competitor average"
                 + (f", with {abs(pp.loc['Promo index', 'GAP']):.0f}% {'more' if pp.loc['Promo index', 'GAP'] > 0 else 'less'}"
                    " promotional lift" if "Promo index" in pp.index else "") + ".")
    return (f'<div class="sr-cv-reco"><span class="sr-ico" aria-hidden="true">flag</span><div><p class="h">Strategic '
            f'recommendation</p><p><b>{escape(head)}</b> {escape(body)}</p></div></div>')


def drivers() -> None:
    d = driver_table()
    if d.empty:
        st.caption("No comparable drivers for this selection.")
        return
    rel, pts = d[d.UNIT == "%"], d[d.UNIT == "pts"]
    left, right = nav.stack("cv_dr").columns([3, 2])
    with left, nav.card("cv_gaps"):
        nav.section("Competitive gap", f"{show(focus)} against the selected competitors' average, as a relative gap (%). "
                    "Teal: ahead; terracotta: behind; pale: price and promo, where neither direction is better.")
        st.altair_chart(charts.cv_gap_bars(rel), width="stretch")
        if len(pts):
            r = pts.iloc[0]
            st.caption(f"{r.DRIVER} is a difference in percentage points, so it is not on this axis: {show(focus)} "
                       f"{r.FOCUS_TXT} vs {r.COMP_TXT} average ({_gap_txt(r)}).")
    with right, nav.card("cv_sw"):
        nav.section("Performance assessment", f"Beyond ±{PARITY:.0f}% of the competitor average; inside it is parity.")
        st.html(assessment(d))
    st.html(recommendation(d))
    with nav.card("cv_drv_tbl"):
        nav.section("Driver comparison", f"Every selected brand on the five drivers, {period}.")
        cols = {"BRAND": "Brand", "ACV": "Mean ACV %", "VELOCITY": "Units/store/wk", "PRICE_INDEX": "Price index",
                "PROMO_INDEX": "Promo index", "SALES_GROWTH_PCT": "Sales growth %", "SHARE_CHG_PTS": "Share change, pts"}
        t = _shown(sel)[list(cols)].rename(columns=cols)
        t["Brand"] = pd.Categorical(t.Brand, [show(b) for b in [focus] + comps], ordered=True)
        st.dataframe(nav.striped(t.sort_values("Brand")), hide_index=True, width="stretch", row_height=34,
                     column_config={c: st.column_config.NumberColumn(c, format=f) for c, f in
                                    [("Mean ACV %", "%.1f"), ("Units/store/wk", "%.2f"), ("Price index", "%.2f"),
                                     ("Promo index", "%.2f"), ("Sales growth %", "%+.1f"), ("Share change, pts", "%+.2f")]})
        st.caption("Promo index is stored for the whole market only (no retailer split). 1.00 = promoted in line with "
                   "the category.")
        _export(d.drop(columns=["kind"]) if len(d) else d, "drivers", "dr")


# ---- Opportunities & Risks -----------------------------------------------------------------------------------------

def _items(items, empty: str) -> str:
    return "".join(f'<li class="{t}"><b>{escape(a)}</b><span>{escape(b)}</span></li>' for a, b, t, *_ in items) \
        or f"<li><span>{escape(empty)}</span></li>"


def _bars(items, unit: str) -> pd.DataFrame:
    rows = [{"LABEL": lab, "VALUE": v, "EVIDENCE": f"{t}: {e}"} for t, e, _, v, u, lab in items if v is not None and u == unit]
    return pd.DataFrame(rows)


def _ranked(title: str, items, unit: str, color: str) -> None:
    df = _bars(items, unit)
    if df.empty:
        return
    st.html(f'<p class="sr-cv-sub">{escape(title)}</p>')
    st.altair_chart(charts.cv_ranked_bars(df, color, unit), width="stretch")


def _retailer_shift(market_id: str) -> dict | None:
    """The focus brand's shift in this retailer market in this run (largest move), else its shift in the scope's
    market, else None: the same Shift Detail hand-off the hero uses."""
    s = shifts[(shifts.BRAND == focus) & (shifts.MARKET_ID == market_id)]
    if len(s):
        return s.reindex(s.D_SHARE_PTS.abs().sort_values(ascending=False).index).iloc[0].to_dict()
    return f_shift


def opportunities(threats, opps) -> None:
    reg = _regions(category, int(weeks), compare, measure)
    if reg is None or reg.empty:
        st.caption("The regional view needs more weeks of retailer sales for this comparison.")
        return
    with nav.card("cv_heat"):
        head, ctl = st.columns([3, 1], vertical_alignment="center")
        with head:
            nav.section("Regional competitive heatmap", f"{basis} of each retailer's category, by brand. "
                        "Hover a cell for distribution and velocity.")
        mode = ctl.radio("Show", ["Share", "Change"], key="cv_heat_mode", horizontal=True, label_visibility="collapsed",
                         format_func={"Share": "Share %", "Change": "Change, pts"}.get) or "Share"
        col, title, spec, div = (("SHARE", f"{basis} %", ".1f", False) if mode == "Share"
                                 else ("SHARE_CHG_PTS", "Change, pts", "+.2f", True))
        st.altair_chart(charts.cv_region_heatmap(_shown(reg), show(focus), [show(b) for b in [focus] + comps], col,
                                                 title, spec, div), width="stretch")
    left, right = nav.stack("cv_op").columns(2)
    with left, nav.card("cv_opps"):
        nav.section("Opportunities", f"Retailers where {show(focus)} trails the competitor average by more than "
                    f"{PARITY:.0f} ACV points or {PARITY:.0f}% in velocity, largest first.")
        if not opps:
            st.caption(f"{show(focus)} is at or above the competitor average in every retailer.")
        _ranked("Distribution gap, ACV points", opps, "ACV pts", charts.TEAL)
        _ranked("Velocity gap, % below average", opps, "%", charts.SEA)
    with right, nav.card("cv_threats"):
        nav.section("Competitive threats", f"Competitors gaining share overall or where {show(focus)} lost, "
                    "largest first, plus this week's early warnings.")
        if not threats:
            st.caption("No competitor is gaining on the focus brand in this period.")
        _ranked("Share gained, points", threats, "pts", charts.GOLD)
        warn = [t for t in threats if t[3] is None]
        if warn:
            st.html('<ul class="sr-cv-ew">' + "".join(f'<li><span class="sr-ico" aria-hidden="true">notifications</span>'
                                                      f'<b>{escape(a)}</b> {escape(b)}</li>' for a, b, *_ in warn) + "</ul>")
    o = retailer_gaps()
    with nav.card("cv_recs"):
        nav.section("Priority action plan", f"Retailers ranked by {show(focus)}'s share loss, with the distribution gap "
                    "and the competitor that gained most there.")
        loss = o[o.SHARE_CHG_PTS < 0].sort_values("SHARE_CHG_PTS") if len(o) else o
        if loss.empty:
            st.caption(f"{show(focus)} did not lose share in any retailer in this period.")
            return
        widths = [0.55, 1.4, 1, 1, 1.9, 1.5, 1.05]
        hdr = st.columns(widths, vertical_alignment="center", gap="small")
        for c, h in zip(hdr, ["#", "Retailer", "Share change", "ACV gap", "Top competitor gain", "Lever to check", ""]):
            c.html(f'<span class="sr-cv-th">{h}</span>')
        plan = []
        for i, (mid, r) in enumerate(loss.iterrows(), 1):
            lever = ("Distribution" if r.ACV_GAP_PTS < -PARITY else "Velocity" if r.VEL_GAP_PCT < -PARITY
                     else "Price or promotion")
            rival = (f"{show(r.TOP_GAINER)} {fmt.pts(r.TOP_GAIN_PTS)}" if _num(r.TOP_GAIN_PTS) and r.TOP_GAIN_PTS > 0
                     else "–")
            plan.append({"Priority": i, "Retailer": r.RETAILER, "Share change, pts": round(float(r.SHARE_CHG_PTS), 2),
                         "ACV gap, pts": round(float(r.ACV_GAP_PTS), 1), "Top competitor gain": rival, "Lever": lever})
            with st.container(key=f"sr_cv_plan_{i}"):
                cells = st.columns(widths, vertical_alignment="center", gap="small")
                cells[0].html(f'<span class="sr-cv-rank">{i}</span>')
                cells[1].html(f'<b class="sr-cv-td">{escape(r.RETAILER)}</b>')
                cells[2].html(f'<span class="sr-cv-td neg">{escape(fmt.pts(r.SHARE_CHG_PTS))}</span>')
                cells[3].html(f'<span class="sr-cv-td {"neg" if r.ACV_GAP_PTS < 0 else "pos"}">{r.ACV_GAP_PTS:+.1f} pts</span>'
                              f'<small class="sr-cv-tdn">{r.ACV:.1f}% vs {r.C_ACV:.1f}%</small>')
                cells[4].html(f'<span class="sr-cv-td">{escape(rival)}</span>')
                cells[5].html(f'<span class="sr-cv-lever">{escape(lever)}</span>')
                target = _retailer_shift(mid)
                if cells[6].button("Investigate", key=f"cv_inv_{i}", icon=":material/arrow_forward:", type="tertiary",
                                   disabled=target is None,
                                   help="Opens this brand's shift in Shift Detail" if target is not None
                                   else "No shift for this brand in this week's run"):
                    st.session_state.shift_id = target["SHIFT_ID"]
                    st.switch_page("pages/1_Shift_detail.py")
        _export(pd.DataFrame(plan), "priority_action_plan", "op")


threats, opps = threats_and_opportunities()
qs = suggestions(threats, opps)
st.session_state["cv_suggestions"] = [q for _, q in qs]         # the docked assistant's suggested questions
kpi_cards()
chippy(threats, opps, qs)
if st.session_state.get("cv_view") not in VIEWS:
    st.session_state["cv_view"] = VIEWS[0]
with st.container(key="sr_tabs"):                                # the Shift Detail tab bar style (nav.CSS)
    view = st.radio("View", VIEWS, key="cv_view", horizontal=True, label_visibility="collapsed")
nav.guarded(view, {"Competitive Overview": overview, "Share Drivers": drivers,
                   "Opportunities & Risks": lambda: opportunities(threats, opps)}[view])
