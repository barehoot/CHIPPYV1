"""Insight Studio (SR-065): the Shift Detail tab that gives each role the analysis it acts on.

Lenses, most senior first:
  Analytics Director  the run's portfolio as a risk matrix, and how strong the evidence is for this shift
  Company Manager     a one-screen decision brief: what it costs, why, and the actions ranked by modelled recovery
  Analytics Manager   where the loss is concentrated, which lever moved at which retailer, and a priority list
  Data Analyst        a freehand workbench: any measure by any dimension, box and lasso selection, drawing tools, pivot
  Data Scientist      a model lab: elasticity, causal impact, change point, gradient boosting, k-means, Isolation
                      Forest and cannibalisation, each with a model card

Reads go through data.py (brand_panel, sku_week_panel, shifts); the models live in analytics.py; every chart is built
in charts.py. Results are exploratory: they explain and prioritise, and never feed the brief or any stored table.
"""
from __future__ import annotations

from datetime import timedelta
from html import escape

import numpy as np
import pandas as pd
import streamlit as st

from sr_ui import analytics as an, charts, format as fmt, nav, workspace


class _Data:
    """sr_ui.data looked up at call time, like nav and format do, so whichever data module is installed (Snowflake, or
    the local preview's sample data) is the one used, whatever was installed when this module was first imported."""
    def __getattr__(self, name):
        from sr_ui import data as current
        return getattr(current, name)


data = _Data()


def _fkey() -> str:
    """The applied sidebar filters as text; part of every studio cache key, so a filter change never reuses a panel."""
    get = getattr(data, "filters", None)
    return repr(get()) if get else ""


def _cached(fn):
    """st.cache_data keyed by the function name, the applied filters and the call's own arguments."""
    import functools

    @st.cache_data(ttl=data.TTL_S, show_spinner=False)
    def run(name: str, fkey: str, args: tuple, kwargs: tuple):
        return fn(*args, **dict(kwargs))

    @functools.wraps(fn)
    def call(*args, **kwargs):
        return run(fn.__name__, _fkey(), args, tuple(sorted(kwargs.items())))
    call.clear = run.clear
    return call

LENSES = {"director": ("Analytics Director", "Is this worth my attention, and how sure are we?"),
          "manager": ("Company Manager", "What does it cost, why, and what do we do on Monday?"),
          "amanager": ("Analytics Manager", "Where is it concentrated, which lever, and who does what?"),
          "analyst": ("Data Analyst", "Slice it any way you like: build, select, draw, pivot and export."),
          "scientist": ("Data Scientist", "Models that explain the move, with fit, uncertainty and assumptions."),
          "early": ("Emerging Shifts", "Which moves are building before the 4-week reports show them?")}
MODELS = {"elasticity": "Elasticity", "causal": "Causal impact", "changepoint": "Change point",
          "drivers": "Driver model · ML", "segments": "Segments · ML", "anomaly": "Anomaly scan · ML",
          "cannibal": "Cannibalisation"}
MEASURE_LABELS = {"VALUE_SALES": "Value sales", "UNIT_SALES": "Unit sales", "VOLUME_SALES": "Volume sales",
                  "VALUE_SHARE_PCT": "Value share %", "PRICE_PER_UNIT": "Price per unit", "PRICE_INDEX": "Price index",
                  "ACV_DIST_PCT": "Distribution (ACV %)", "STORES_SELLING": "Stores selling", "SKUS_SELLING": "SKUs selling",
                  "SALES_WOW": "Sales change week on week", "PRICE_WOW": "Price change week on week",
                  "ACV_WOW": "Distribution change, pts", "UNITS_PER_STORE": "Units per store"}
DIM_LABELS = {"WEEK_END_DATE": "Week", "RETAILER": "Retailer", "REGION": "Region", "BRAND": "Brand",
              "MANUFACTURER": "Manufacturer", "BRAND_RETAILER": "Brand · retailer", "ITEM_DESC": "SKU",
              "SEGMENT": "Segment", "PACK_SIZE": "Pack"}
AGGS = {"Sum": "sum", "Average": "mean", "Median": "median", "Max": "max", "Min": "min"}
MATERIAL = {"Distribution, pts": 2.0, "Units per store, %": 5.0}   # display heuristics (B28); price: EW_PRICE_RISE
PLAY = {"Distribution, pts": "Ranging and listing conversation with the buyer",
        "Price index": "Price-gap review against the competitors on shelf",
        "Units per store, %": "Shelf visibility, availability and promotion at store level",
        "Share, pts": "Joint business review: share lost without a single lever"}


# ---- context and cached fits --------------------------------------------------------------------------------------

class Ctx:
    """The shift the studio is about, and what the page already read."""
    def __init__(self, s: dict, sid: str, run, markets: dict, cur: str, takeaway: str, shifts: pd.DataFrame,
                 label=None):
        self.s, self.sid, self.run, self.markets, self.cur, self.takeaway, self.shifts = s, sid, run, markets, cur, takeaway, shifts
        self.brand = fmt.name(s["BRAND"])
        self.category = s["CATEGORY"]
        self.masked = data.cfg("DISPLAY_ALIAS") is True                  # names are aliased: mask every new view too
        self.label = label or (lambda i: i)                              # the page's shift label (brand · market · cmp)


def _shown(df: pd.DataFrame) -> pd.DataFrame:
    """Brand and manufacturer names as the app shows them (aliases when DISPLAY_ALIAS is on), so no view leaks a
    masked name."""
    out = df.assign(BRAND=df.BRAND.map(fmt.name)) if "BRAND" in df else df
    if "MANUFACTURER" in out:
        out = out.assign(MANUFACTURER=out.MANUFACTURER.map(lambda m: fmt.name(m, "MANUFACTURER")))
    return out


@_cached
def _panel(category: str, masked: bool) -> pd.DataFrame:
    """The brand panel with display names; `masked` is part of the cache key, so a masked view never reuses names."""
    return _shown(data.brand_panel(category, 104))


@_cached
def _sku_panel(category: str, real_brand: str, masked: bool) -> pd.DataFrame:
    """The brand's SKU panel. When names are masked, SKU descriptions (which carry the brand) become 'SKU 1', 'SKU 2'…
    in product-id order, and segment and pack stay as they are."""
    k = data.sku_week_panel(category, real_brand, 52)
    if masked and len(k):
        order = {p: f"SKU {i}" for i, p in enumerate(sorted(k.PRODUCT_ID.astype(str).unique()), 1)}
        k = k.assign(ITEM_DESC=k.PRODUCT_ID.astype(str).map(order))
    return k


@_cached
def _ladder(category: str, masked: bool) -> pd.DataFrame:
    lad = data.price_ladder(category, 4)
    return an.price_ladder(_shown(lad)) if len(lad) else lad


@_cached
def _fit(kind: str, category: str, brand: str, arg: str = "", masked: bool = False):
    """One cached model fit per (model, category, brand, argument, masking); the argument is the start week or the
    measure."""
    p = _panel(category, masked)
    if kind == "elasticity":
        return an.elasticity(p, brand)
    if kind == "elasticity_all":
        return an.elasticity_all(p)
    if kind == "changepoint":
        wk = an.brand_weekly(p, brand).set_index("WEEK_END_DATE")
        return an.change_point(wk[arg or "VALUE_SHARE_PCT"])
    if kind == "causal":
        measure, start = arg.split("|")
        return an.causal_impact(p, brand, start, measure)
    if kind == "drivers":
        return an.driver_model(p, brand)
    if kind == "segments":
        return an.segment_positions(p)
    if kind == "cannibal":
        return an.cannibalisation(p, brand)
    raise ValueError(kind)


def _try(kind: str, c: Ctx, arg: str = ""):
    """A fit, or None with a plain message when the data cannot support it."""
    try:
        return _fit(kind, c.category, c.brand, arg, c.masked)
    except an.AnalyticsError as e:
        st.info(str(e), icon=":material/info:")
        return None


def _default_start(c: Ctx) -> pd.Timestamp:
    cp = _fit("changepoint", c.category, c.brand, "VALUE_SHARE_PCT", c.masked)
    return pd.Timestamp(cp["week"])


# ---- small shared pieces --------------------------------------------------------------------------------------------

def _plot(fig, key: str, select: bool = False):
    """A Plotly chart with the drawing tools; select=True returns the box or lasso selection."""
    if select:
        return st.plotly_chart(fig, key=key, config=charts.PLOTLY_CONFIG, on_select="rerun",
                               selection_mode=("points", "box", "lasso"), width="stretch")
    st.plotly_chart(fig, config=charts.PLOTLY_CONFIG, width="stretch")   # no key: a keyed chart is a widget (B17)
    return None


def _tiles(items: list[tuple[str, str, str, str]]) -> None:
    """(label, value, note, tone) tiles; tone 'neg', 'pos' or ''."""
    st.html('<div class="sr-studio-tiles">' + "".join(
        f'<div class="sr-studio-tile"><span class="k">{escape(k)}</span><b class="{t}">{escape(v)}</b>'
        f'<span class="n">{escape(n)}</span></div>' for k, v, n, t in items) + "</div>")


def _card(title: str, method: str, fit: str, assumptions: str) -> None:
    """The model card: what was fitted, how well, and what it assumes. Always says exploratory."""
    with st.expander(f"Model card · {title}", icon=":material/description:"):
        st.markdown(f"**Method.** {method}\n\n**Fit.** {fit}\n\n**Assumptions and limits.** {assumptions}\n\n"
                    "_Exploratory: computed in the app from the weekly panel. It explains and prioritises; it never "
                    "changes the brief, the bridge or any stored number._")


def _tone(v) -> str:
    return "" if v is None or pd.isna(v) else ("neg" if float(v) < 0 else "pos")


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _actions_row(c: Ctx, key: str, summary: str, ask: str) -> None:
    """Explain this view (opens Ask Chippy with the question) and Save to Case file (with the summary as a note)."""
    with st.container(horizontal=True, gap="small", key=f"sr_studio_act_{key}"):
        if st.button("Explain this with Chippy", key=f"sr_studio_ask_{key}", icon=":material/forum:", type="tertiary",
                     help="Opens Ask Chippy with a question about this view"):
            st.session_state["sr_ask_about"] = ask
            st.session_state["chat_agent"] = data.AGENT
            st.switch_page("pages/5_Ask_Chippy.py")
        if st.button("Save to Case file", key=f"sr_studio_case_{key}", icon=":material/note_add:", type="tertiary",
                     help="Opens this shift's case file and adds this finding as a note"):
            k = workspace.open_case({**c.s, "SHIFT_ID": c.sid}, c.run.run_id, c.run.as_of_week)
            workspace.add_note(k, summary)
            st.toast("Saved to the case file for this session.", icon=":material/note_add:")


# ---- Analytics Director -----------------------------------------------------------------------------------------------

def director(c: Ctx) -> None:
    sh = c.shifts.copy()
    pf = data.portfolio(c.run.run_id)                    # totals in SQL, over the brief's shifts only (no double count)
    n = int(pf.get("N_SHIFTS", 0))
    _tiles([("Value at risk, losses", fmt.money(pf.get("VALUE_LOSS"), c.cur),
             f"{int(pf.get('N_LOSS', 0))} losing shifts in this week's brief", "neg"),
            ("Value in play, gains", fmt.money(pf.get("VALUE_GAIN"), c.cur),
             f"{int(pf.get('N_GAIN', 0))} gaining shifts in the brief", "pos"),
            ("Confirmed by the anomaly model", f"{int(pf.get('N_CONFIRMED', 0))} of {n}", "shifts in the brief", ""),
            ("Possible data effects", f"{int(pf.get('N_DATA_EFFECT', 0))}", "in the brief: verify before acting",
             "neg" if pf.get("N_DATA_EFFECT") else "")])
    nav.guarded("Time to insight", lambda: _time_to_insight(c))
    left, right = nav.stack("studio_dir").columns([3, 2])
    with left, nav.card("studio_risk"):
        nav.section("Risk matrix", "Every shift past the gates this run (all comparisons and markets): confidence "
                    "against value at stake. Bigger bubble, bigger share move; the gold ring is the shift you are "
                    "viewing. Open another one below.")
        names = {r.SHIFT_ID: c.label(r.SHIFT_ID) for r in sh.itertuples()}
        _plot(charts.pl_risk(sh, names, c.cur, focus=c.sid, high=fmt.HIGH_CONFIDENCE), "studio_risk_chart")
        others = [i for i in names if i != c.sid]
        if others:
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                go_to = st.selectbox("Focus a shift", others, format_func=names.get, key="studio_focus_pick", width=280)
                if st.button("Open", key="sr_studio_open_shift", icon=":material/open_in_new:"):
                    st.session_state.shift_id = go_to
                    st.rerun()
    with right, nav.card("studio_evidence"):
        nav.section("How sure are we?", f"{c.brand}: four independent checks")
        cp = ci = None
        try:
            cp = _fit("changepoint", c.category, c.brand, "VALUE_SHARE_PCT", c.masked)
            ci = _fit("causal", c.category, c.brand, f"VALUE_SALES|{pd.Timestamp(cp['week']).date()}", c.masked)
        except an.AnalyticsError:
            pass
        checks = an.evidence_score(c.s, cp, ci)
        passed = sum(ok for _, ok, _ in checks)
        st.html(f'<div class="sr-evidence-score"><b>{passed}/4</b><span>checks support a real market move</span></div>'
                + "".join(f'<div class="sr-evidence-row {"ok" if ok else "bad"}"><span class="sr-ico" aria-hidden="true">'
                          f'{"check_circle" if ok else "cancel"}</span><div><b>{escape(n)}</b><em>{escape(d)}</em></div></div>'
                          for n, ok, d in checks))
        verdict = ("Act: the evidence agrees." if passed >= 3 else "Verify before acting: the evidence is split."
                   if passed == 2 else "Hold: most checks do not support a real move.")
        board = (f"{c.brand} in {c.markets.get(c.s['MARKET_ID'], c.s['MARKET_ID'])}: {fmt.pts(c.s['D_SHARE_PTS'])}, "
                 f"{fmt.money(c.s['VALUE_AT_STAKE'], c.cur)} at stake; {passed} of 4 checks support it. {verdict}")
        st.html(f'<div class="sr-board-line"><span class="k">Board line</span>{escape(board)}</div>')
    _actions_row(c, "dir", board, f"How confident should we be in the {c.brand} shift, and what would change that?")


def _time_to_insight(c: Ctx) -> None:
    """Days to minutes, measured: the weekly run's own timestamps, from start to the brief being published."""
    r = c.run
    run_min = (pd.Timestamp(r.ended_at) - pd.Timestamp(r.started_at)).total_seconds() / 60 if r.ended_at is not None else None
    pub = data.brief(r.brief_id).get("PUBLISHED_AT") if r.brief_id else None
    to_brief = (pd.Timestamp(pub) - pd.Timestamp(r.started_at)).total_seconds() / 60 if pub is not None else None
    show = lambda m: "–" if m is None or pd.isna(m) else (f"{m:.0f} min" if m >= 1 else "under 1 min")   # noqa: E731
    st.html('<div class="sr-tti"><span class="sr-ico" aria-hidden="true">timer</span><b>Time to insight</b>'
            f'<span>Weekly run <em>{escape(show(run_min))}</em></span><span>Data in to brief published <em>'
            f'{escape(show(to_brief))}</em></span><span>Manual review baseline <em>to be measured (SR-060)</em></span></div>')


# ---- Company Manager ----------------------------------------------------------------------------------------------

def manager(c: Ctx) -> None:
    el = _try("elasticity", c)
    p = _panel(c.category, c.masked)
    ci = None
    try:
        start = _default_start(c)
        ci = _fit("causal", c.category, c.brand, f"VALUE_SALES|{start.date()}", c.masked)
    except an.AnalyticsError:
        start = None
    acts = None
    if el is not None:
        try:
            acts = an.actions(p, c.brand, el)
        except an.AnalyticsError as e:
            st.info(str(e), icon=":material/info:")
    best = acts.iloc[0] if acts is not None and len(acts) else None
    _tiles([("Value at stake (weekly run)", fmt.money(c.s["VALUE_AT_STAKE"], c.cur), "stored; the brief's number", _tone(c.s["VALUE_AT_STAKE"])),
            ("Sales gap since the change", fmt.money(ci["effect"], c.cur) if ci else "–",
             (f"since {start:%d %b} · {fmt.signed_pct(ci['relative'])} vs expected · model") if ci else "not available",
             _tone(ci["effect"]) if ci else ""),
            ("Run-rate gap per week", fmt.money(ci["per_week"], c.cur) if ci else "–", "causal-impact model", _tone(ci["per_week"]) if ci else ""),
            ("Best recovery per week", fmt.money(best.VALUE_PER_WEEK, c.cur) if best is not None else "–",
             best.LEVER if best is not None else "no action modelled", "pos" if best is not None else "")])
    st.caption(f"Value at stake is the weekly run's figure for this shift ({c.markets.get(c.s['MARKET_ID'], c.s['MARKET_ID'])}, "
               f"{fmt.CMP_TEXT.get(c.s['CMP_CODE'], c.s['CMP_CODE'])}). The model figures, actions and projection cover "
               f"{c.brand} across all retailers in the weekly panel.")
    st.html(f'<div class="sr-takeaway"><span class="sr-ico" aria-hidden="true">lightbulb</span><div><span class="k">Why it '
            f'happened</span><p>{escape(c.takeaway)}</p></div></div>')
    with nav.card("studio_actions"):
        nav.section("What to do: actions ranked by modelled recovery",
                    "Built from this brand's own price and distribution elasticities (Data Scientist lens). "
                    "Estimates to prioritise, not promises.")
        if acts is None or acts.empty:
            st.caption("No actions could be modelled for this brand.")
        else:
            st.html('<div class="sr-action-list">' + "".join(
                f'<div class="sr-action"><i>{i}</i><div><b>{escape(r.ACTION)}</b><span>{escape(r.ASSUMPTION)}</span></div>'
                f'<div class="sr-action-v"><b class="pos">{escape(fmt.money(r.VALUE_PER_WEEK, c.cur))}</b>'
                f'<span>per week · {r.UPLIFT_PCT:+.1f}%</span></div><em class="c-{r.CERTAINTY.lower()}">{escape(r.CERTAINTY)} '
                f'certainty</em></div>' for i, r in enumerate(acts.itertuples(), 1)) + "</div>")
    if el is not None:
        nav.guarded("Scenario simulator", lambda: _scenario(c, el))
    with nav.card("studio_nothing"):
        nav.section("If nothing changes", f"{c.brand} weekly value sales, next 13 weeks (Holt-Winters projection of the "
                    "measured pattern; it does not know about plans or promotions)")
        from sr_ui import forecast
        wk = an.brand_weekly(p, c.brand)
        y = pd.Series(wk.VALUE_SALES.to_numpy(), index=pd.to_datetime(wk.WEEK_END_DATE))
        try:
            res, _ = forecast.run(y, ["Holt-Winters"], 13)
            hist = pd.DataFrame({"WEEK_END_DATE": y.index, "VALUE": y.to_numpy()})
            st.altair_chart(charts.forecast_chart(hist, res, f"Value sales ({c.cur})" if c.cur else "Value sales",
                                                  ",.0f", zero=False), width="stretch")
        except forecast.ForecastError as e:
            st.caption(str(e))
    summary = (f"Decision brief, {c.brand}: {fmt.money(c.s['VALUE_AT_STAKE'], c.cur)} at stake. "
               + (f"Top action: {best.ACTION}, about {fmt.money(best.VALUE_PER_WEEK, c.cur)} a week ({best.CERTAINTY.lower()} "
                  "certainty)." if best is not None else ""))
    _actions_row(c, "mgr", summary, f"What should we do first about {c.brand}, and what is it worth?")


def _scenario(c: Ctx, el: dict) -> None:
    """Move price and distribution; competitors held; a Monte Carlo range from the brand's own elasticities."""
    with nav.card("studio_scenario"):
        nav.section("Try a scenario", "Move shelf price and distribution; competitors held. 4,000 simulations draw the "
                    "brand's elasticities from their uncertainty, so the answer is a range, not a point.")
        a, b = nav.stack("sc_ctl").columns(2)
        price = a.slider("Shelf price change, %", -20, 20, 0, 1, key="sc_price")
        dist = b.slider("Distribution change, ACV points", -20, 20, 0, 1, key="sc_dist")
        sim = an.simulate(_panel(c.category, c.masked), c.brand, el, float(price), float(dist))
        v, sh = sim["value_change"], sim["share_change"]
        _tiles([("Weekly value change, median", fmt.money(v[1], c.cur),
                 f"80% range {fmt.money(v[0], c.cur)} to {fmt.money(v[2], c.cur)}", _tone(v[1])),
                ("Value share change, median", fmt.pts(sh[1]), f"80% range {fmt.pts(sh[0])} to {fmt.pts(sh[2])}", _tone(sh[1])),
                ("Chance sales rise", f"{100 * sim['p_gain']:.0f}%", "of the simulations", ""),
                ("Distribution", f"{sim['acv_now']:.0f}% → {sim['acv_new']:.0f}%", f"ACV · price {price:+d}%", "")])
        if price or dist:
            _plot(charts.pl_hist(sim["draws"].VALUE_CHANGE, f"Weekly value change ({c.cur})" if c.cur else "Weekly value change",
                                 {"P10": v[0], "Median": v[1], "P90": v[2]}), "sc_hist")
        else:
            st.caption("Move a slider to simulate.")


# ---- Analytics Manager --------------------------------------------------------------------------------------------

def analytics_manager(c: Ctx) -> None:
    p = _panel(c.category, c.masked)
    weeks = st.radio("Compare", [4, 12], horizontal=True, key="studio_am_weeks",
                     format_func=lambda w: f"Last {w} weeks vs the {w} before")
    try:
        pr = an.pareto(p, c.brand, "RETAILER", weeks)
        dm = an.driver_matrix(p, c.brand, weeks)
    except an.AnalyticsError as e:
        st.info(str(e), icon=":material/info:")
        return
    k = _sku_panel(c.category, c.s["BRAND"], c.masked)
    left, right = nav.stack("studio_am").columns(2)
    with left, nav.card("studio_pareto_r"):
        nav.section("Where the loss sits: retailers", "Bars: change in value sales. Gold: running share of the loss; "
                    "the dotted line is 80%.")
        _plot(charts.pl_pareto(pr, f"Change in value sales ({c.cur})" if c.cur else "Change", c.cur), "studio_pareto_r_chart")
    with right, nav.card("studio_pareto_s"):
        nav.section("Where the loss sits: SKUs", "The same view by SKU, all retailers")
        if k.empty:
            st.caption("No SKU rows for this brand.")
        else:
            try:
                _plot(charts.pl_pareto(an.pareto(k, c.brand, "ITEM_DESC", weeks), "Change in value sales", c.cur),
                      "studio_pareto_s_chart")
            except an.AnalyticsError as e:
                st.caption(str(e))
    with nav.card("studio_matrix"):
        nav.section("Which lever moved where", f"Change by retailer, last {weeks} weeks vs the {weeks} before. "
                    "Terracotta fell, teal rose.")
        _plot(charts.pl_heat(dm.set_index("RETAILER"), "Change"), "studio_matrix_chart")
    with nav.card("studio_priority"):
        nav.section("Priority list", "Retailers ranked by their share of the loss, each with the lever that moved most "
                    "and the play that fits it")
        z = dm.set_index("RETAILER")
        # A lever "moved" when its change is material: 2 ACV points, 3% price index, 5% units per store (display
        # heuristics for ranking plays, not pipeline gates). Share is the outcome, so it is never the lever.
        material = dict(MATERIAL)
        if data.cfg("EW_PRICE_RISE") is not None:                 # the early-warning price threshold (rule 4)
            material["Price index"] = float(data.cfg("EW_PRICE_RISE"))
        scaled = z[list(material)].abs() / pd.Series(material)
        scaled = scaled.where(scaled >= 1)
        rows = []
        for r in pr[pr.CHANGE < 0].itertuples():
            row = scaled.loc[r.ITEM].abs().dropna() if r.ITEM in scaled.index else pd.Series(dtype=float)
            lever = row.idxmax() if len(row) else "Share, pts"
            rows.append({"Retailer": r.ITEM, "Change in value sales": fmt.money(r.CHANGE, c.cur),
                         "Share of the loss": f"{100 * r.SHARE_OF_LOSS:.0f}%", "Lever that moved most": lever,
                         "Change": f"{z.loc[r.ITEM, lever]:+.2f}" if r.ITEM in z.index and pd.notna(z.loc[r.ITEM, lever]) else "–",
                         "Suggested play": PLAY.get(lever, PLAY["Share, pts"])})
        plan = pd.DataFrame(rows)
        if plan.empty:
            st.caption("No retailer lost value sales in this window.")
        else:
            st.dataframe(nav.striped(plan), hide_index=True, width="stretch", row_height=36)
    left2, right2 = nav.stack("studio_am2").columns(2)
    with left2, nav.card("studio_fair"):
        nav.section("Fair share", f"Value share against share of distribution points, last {weeks} weeks, all retailers. "
                    "Above the dotted line a brand sells more than its shelf presence; teal above 100 on the index.")
        rep = _shown(data.share_report(c.category, int(weeks), "previous", None))
        if rep.empty:
            st.caption("No sales in this period.")
        else:
            _plot(charts.pl_fair_share(rep, c.brand), "studio_fair_chart")
    with right2, nav.card("studio_ladder"):
        nav.section("Price ladder", "Price per unit by pack size, last 4 weeks, all retailers. Hover for each pack's "
                    "index against the category's average price for that pack.")
        lad = _ladder(c.category, c.masked)
        if lad.empty:
            st.caption("No pack-level prices for this category.")
        else:
            _plot(charts.pl_ladder(lad, c.brand), "studio_ladder_chart")
    summary = ("Priorities for " + c.brand + ": " + "; ".join(f"{r['Retailer']} ({r['Share of the loss']} of loss, "
               f"{r['Lever that moved most'].split(',')[0].lower()})" for r in rows[:3]) + ".") if rows else f"No retailer loss for {c.brand}."
    _actions_row(c, "am", summary, f"Which retailers should we prioritise for {c.brand}, and why?")


# ---- Data Analyst: the workbench ----------------------------------------------------------------------------------

CHART_WORDS = [("heat", "Heatmap"), ("box", "Box"), ("scatter", "Scatter"), ("area", "Area"), ("bar", "Bar"),
               ("column", "Bar"), ("line", "Line"), ("trend", "Line")]
MEASURE_WORDS = [("price index", "PRICE_INDEX"), ("value share", "VALUE_SHARE_PCT"), ("share", "VALUE_SHARE_PCT"),
                 ("price", "PRICE_PER_UNIT"), ("unit", "UNIT_SALES"), ("volume", "VOLUME_SALES"),
                 ("acv", "ACV_DIST_PCT"), ("distribution", "ACV_DIST_PCT"), ("store", "STORES_SELLING"),
                 ("sku", "SKUS_SELLING"), ("sales", "VALUE_SALES"), ("value", "VALUE_SALES")]
DIM_WORDS = [("retailer", "RETAILER"), ("region", "REGION"), ("manufacturer", "MANUFACTURER"), ("brand", "BRAND")]


def _rule_spec(text: str, allowed: dict) -> dict:
    """A workbench spec from a plain-English request by keywords (used when no LLM is available, and to fill gaps)."""
    import re as _re
    q = text.lower()
    y = next((m for w, m in MEASURE_WORDS if w in q), "VALUE_SHARE_PCT")
    by = next((d for w, d in DIM_WORDS if f"by {w}" in q or f"per {w}" in q or f"across {w}" in q), None)
    over_time = any(w in q for w in ("over time", "trend", "weekly", "week by week", "by week", "line"))
    x = "WEEK_END_DATE" if over_time or by is None else by
    brands = [b for b in allowed["brands"] if b.lower() in q]
    rets = [r for r in allowed["retailers"] if r.lower() in q]
    colour = by if x == "WEEK_END_DATE" and by else ("BRAND" if x != "BRAND" and len(brands) != 1 else None)
    kind = next((k for w, k in CHART_WORDS if w in q), "Line" if x == "WEEK_END_DATE" else "Bar")
    m = _re.search(r"(\d+)\s*weeks?", q)
    weeks = int(m.group(1)) if m else (52 if "year" in q else 13 if "quarter" in q else None)
    agg = "Average" if y in ("VALUE_SHARE_PCT", "PRICE_INDEX", "ACV_DIST_PCT", "PRICE_PER_UNIT") else "Sum"
    return {"kind": kind, "x": x, "y": y, "agg": agg, "colour": colour, "brands": brands, "retailers": rets, "weeks": weeks}


def _ask_chart(c: Ctx) -> None:
    """Build the workbench from the request: the LLM when the app offers one (local preview), the keyword rule
    otherwise. Every value is checked against what the workbench allows before it is used."""
    text = (st.session_state.get("wb_ask") or "").strip()
    if not text:
        return
    p = _panel(c.category, c.masked)
    allowed = {"kind": ["Line", "Bar", "Area", "Scatter", "Box", "Heatmap"],
               "x": ["WEEK_END_DATE", "RETAILER", "REGION", "BRAND", "MANUFACTURER"],
               "y": [m for m in MEASURE_LABELS if m in p.columns], "agg": list(AGGS),
               "colour": [None, "BRAND", "MANUFACTURER", "RETAILER", "REGION", "BRAND_RETAILER"],
               "brands": sorted(p.BRAND.unique()), "retailers": sorted(p.RETAILER.unique())}
    rule = _rule_spec(text, allowed)
    spec, how = rule, "keyword rule"
    llm = getattr(data, "chart_spec", None)
    if llm is not None:
        try:
            got = llm(text, allowed)
            spec = {k: (got.get(k) if got.get(k) in allowed[k] else rule[k]) for k in ("kind", "x", "y", "agg", "colour")}
            spec["brands"] = [b for b in (got.get("brands") or []) if b in allowed["brands"]] or rule["brands"]
            spec["retailers"] = [r for r in (got.get("retailers") or []) if r in allowed["retailers"]] or rule["retailers"]
            spec["weeks"] = got.get("weeks") if isinstance(got.get("weeks"), int) else rule["weeks"]
            how = "AI, checked against the workbench"
        except Exception:                                        # noqa: BLE001 - the rule still answers
            spec, how = rule, "keyword rule (the AI was unavailable)"
    ss = st.session_state
    ss["wb_src"] = "Brands by retailer and week"
    ss["wb_kind"], ss["wb_x"], ss["wb_y"], ss["wb_agg"] = spec["kind"], spec["x"], spec["y"], spec["agg"]
    ss["wb_colour"] = spec["colour"] if spec["colour"] != spec["x"] else None
    if len(spec["brands"]) > 1 and ss["wb_colour"] in ("RETAILER", "REGION") and spec["x"] == "WEEK_END_DATE":
        ss["wb_colour"] = "BRAND_RETAILER"        # several brands split by retailer: one line each, never an average
    if spec["kind"] == "Heatmap" and not ss["wb_colour"]:
        ss["wb_colour"] = "BRAND" if spec["x"] != "BRAND" else "RETAILER"
    ss["wb_brands"] = spec["brands"] or [c.brand] + [b for b in allowed["brands"] if b != c.brand][:3]
    ss["wb_rets"] = spec["retailers"]
    weeks = sorted(pd.to_datetime(p.WEEK_END_DATE).dt.date.unique())
    n = max(2, min(int(spec["weeks"] or 52), len(weeks)))
    ss["wb_weeks"] = (weeks[-n], weeks[-1])
    ss["wb_ask_note"] = (f"Built by the {how}: {MEASURE_LABELS[spec['y']]} by {DIM_LABELS.get(spec['x'], spec['x']).lower()}"
                         f", {spec['kind'].lower()} chart, last {n} weeks.")


def analyst(c: Ctx) -> None:
    with st.container(key="sr_wb_ask", horizontal=True, vertical_alignment="bottom", gap="small"):
        st.text_input("Ask this chart", key="wb_ask", placeholder=f"e.g. {c.brand} value share by retailer over time, "
                      "last 12 weeks")
        st.button("Build chart", key="wb_ask_go", icon=":material/auto_awesome:", on_click=_ask_chart, args=(c,))
    if st.session_state.get("wb_ask_note"):
        st.caption(st.session_state["wb_ask_note"])
    src = st.radio("Data", ["Brands by retailer and week", f"{c.brand} SKUs by retailer and week"], horizontal=True,
                   key="wb_src", label_visibility="collapsed")
    sku = src != "Brands by retailer and week"
    df = _sku_panel(c.category, c.s["BRAND"], c.masked) if sku else _panel(c.category, c.masked)
    if df.empty:
        st.info("No rows for this selection.", icon=":material/info:")
        return
    df = df.assign(WEEK_END_DATE=pd.to_datetime(df.WEEK_END_DATE))
    if not sku:
        df = df.assign(BRAND_RETAILER=df.BRAND + " · " + df.RETAILER)
    dims = [d for d in DIM_LABELS if d in df.columns]
    measures = [m for m in MEASURE_LABELS if m in df.columns]
    with nav.card("wb_controls"):
        nav.section("Workbench", "Build any view. Drag to zoom, box or lasso to select, draw with the pen tools in the "
                    "chart toolbar (top right), double-click to reset.")
        # Defaults live in session state only (no index/default/value arguments), so "Ask this chart" can set them;
        # a stored value that the current data source does not offer falls back to the default.
        ss = st.session_state

        def keep(key: str, options: list, preferred):
            if ss.get(key) not in options:
                ss[key] = preferred if preferred in options else options[0]
        kinds = ["Line", "Bar", "Area", "Scatter", "Box", "Heatmap"]
        keep("wb_kind", kinds, "Line")
        c1, c2, c3, c4, c5 = nav.stack("wb_ctl").columns([1.2, 1.4, 1.6, 1, 1.4], vertical_alignment="bottom")
        kind = c1.selectbox("Chart", kinds, key="wb_kind")
        x_opts = dims + (measures if kind == "Scatter" else [])
        keep("wb_x", x_opts, "WEEK_END_DATE")
        x = c2.selectbox("X axis", x_opts, key="wb_x", format_func=lambda v: DIM_LABELS.get(v, MEASURE_LABELS.get(v, v)))
        keep("wb_y", measures, "VALUE_SHARE_PCT")
        y = c3.selectbox("Measure", measures, key="wb_y", format_func=MEASURE_LABELS.get)
        keep("wb_agg", list(AGGS), "Average" if y in ("VALUE_SHARE_PCT", "PRICE_INDEX", "ACV_DIST_PCT", "PRICE_PER_UNIT")
             else "Sum")
        agg = c4.selectbox("Aggregate", list(AGGS), key="wb_agg")
        colour_opts = [None] + [d for d in dims if d != x and d != "WEEK_END_DATE"]
        if "wb_colour" not in ss or ss["wb_colour"] not in colour_opts:
            ss["wb_colour"] = ("ITEM_DESC" if sku else "BRAND") if ("ITEM_DESC" if sku else "BRAND") in colour_opts else None
        colour = c5.selectbox("Colour by", colour_opts, key="wb_colour",
                              format_func=lambda v: "None" if v is None else DIM_LABELS[v])
        f1, f2, f3 = nav.stack("wb_flt").columns([2, 2, 3], vertical_alignment="bottom")
        if not sku:
            order = list(df.groupby("BRAND").VALUE_SALES.sum().sort_values(ascending=False).index)
            if "wb_brands" not in ss:
                ss["wb_brands"] = [b for b in [c.brand] + [b for b in order if b != c.brand][:3] if b in order]
            ss["wb_brands"] = [b for b in ss["wb_brands"] if b in order]
            brands = f1.multiselect("Brands", order, key="wb_brands")
            if brands:
                df = df[df.BRAND.isin(brands)]
        else:
            skus = f1.multiselect("SKUs", sorted(df.ITEM_DESC.unique()), key="wb_skus", placeholder="All SKUs")
            if skus:
                df = df[df.ITEM_DESC.isin(skus)]
        ss["wb_rets"] = [r for r in ss.get("wb_rets", []) if r in set(df.RETAILER)]
        rets = f2.multiselect("Retailers", sorted(df.RETAILER.unique()), key="wb_rets", placeholder="All retailers")
        if rets:
            df = df[df.RETAILER.isin(rets)]
        weeks = sorted(df.WEEK_END_DATE.dt.date.unique())
        if len(weeks) > 1:
            held = ss.get("wb_weeks")
            if not held or held[0] < weeks[0] or held[1] > weeks[-1] or held[0] >= held[1]:
                ss["wb_weeks"] = (weeks[max(0, len(weeks) - 52)], weeks[-1])
            lo, hi = f3.slider("Weeks", min_value=weeks[0], max_value=weeks[-1], step=timedelta(weeks=1),
                               key="wb_weeks", format="DD MMM YY")
            df = df[(df.WEEK_END_DATE.dt.date >= lo) & (df.WEEK_END_DATE.dt.date <= hi)]
    if df.empty:
        st.info("No rows match these filters.", icon=":material/info:")
        return
    if kind in ("Scatter", "Box") and (x in measures or kind == "Box"):
        view = df.reset_index(drop=True)                       # raw rows: each point is one row of the panel
        if len(view) > 4000:
            st.caption(f"Showing a random 4,000 of {len(view):,} rows (seeded, so it is the same each time). Narrow the "
                       "filters to see every row.")
            view = view.sample(4000, random_state=an.SEED).sort_values("WEEK_END_DATE").reset_index(drop=True)
    else:
        keys = [x] + ([colour] if colour else [])
        view = df.groupby(keys, as_index=False)[y].agg(AGGS[agg])
    if kind == "Heatmap" and not colour:
        st.caption("A heatmap needs a Colour by dimension for its rows; showing bars instead.")
        kind = "Bar"
    view = view.assign(ROW_ID=range(len(view)))
    y_title = f"{MEASURE_LABELS[y]} ({agg.lower()})" if x not in measures and kind not in ("Box", "Scatter") else MEASURE_LABELS[y]
    with nav.card("wb_chart_card"):
        # Selection is opt-in: a selectable chart is a widget Streamlit's test harness cannot rerun (as B17), so the
        # default view stays click-testable; switch it on to box- or lasso-select and summarise points.
        selecting = st.toggle("Select points", key="wb_select", help="On: box or lasso select in the chart toolbar, "
                              "and the selection is summarised below the chart.")
        ev = _plot(charts.pl_explore(view, kind, x, y, colour, y_title), "wb_chart_sel" if selecting else "wb_chart",
                   select=selecting)
        pts = (ev or {}).get("selection", {}).get("points", []) if ev else []
        ids = []
        for p in pts:
            cd = p.get("customdata")
            cd = cd[0] if isinstance(cd, list) else cd
            if cd is not None and not (isinstance(cd, float) and np.isnan(cd)):
                ids.append(int(cd))
        sel = view[view.ROW_ID.isin(ids)] if ids else None
        if sel is not None and len(sel):
            v = sel[y]
            st.html(f'<div class="sr-selection"><span class="sr-ico" aria-hidden="true">select_all</span><b>{len(sel)} selected</b>'
                    f'<span>sum {v.sum():,.2f}</span><span>average {v.mean():,.2f}</span><span>min {v.min():,.2f}</span>'
                    f'<span>max {v.max():,.2f}</span></div>')
            st.dataframe(sel.drop(columns="ROW_ID").rename(columns={**DIM_LABELS, **MEASURE_LABELS}), hide_index=True,
                         width="stretch", height=min(300, 38 + 35 * len(sel)))
        else:
            st.caption("Turn on Select points, then pick Box select or Lasso select in the chart toolbar and drag "
                       "over points to summarise them here." if not selecting else
                       "Pick Box select or Lasso select in the chart toolbar and drag over points.")
    with st.expander("Pivot table", icon=":material/pivot_table_chart:"):
        p1, p2, p3, p4 = st.columns(4)
        rows_ = p1.selectbox("Rows", dims, key="pv_rows", index=dims.index("RETAILER"), format_func=DIM_LABELS.get)
        cols_ = p2.selectbox("Columns", [None] + [d for d in dims if d != rows_], key="pv_cols",
                             format_func=lambda v: "None" if v is None else DIM_LABELS[v])
        val = p3.selectbox("Value", measures, key="pv_val", format_func=MEASURE_LABELS.get)
        how = p4.selectbox("Aggregate", list(AGGS), key="pv_agg")
        pv = df.pivot_table(index=rows_, columns=cols_, values=val, aggfunc=AGGS[how]) if cols_ else \
            df.groupby(rows_)[val].agg(AGGS[how]).to_frame(MEASURE_LABELS[val])
        if cols_ == "WEEK_END_DATE":
            pv.columns = [d.strftime("%d %b %y") for d in pv.columns]
        st.dataframe(pv.round(3), width="stretch")
    with st.expander(f"The {len(df):,} filtered rows", icon=":material/table_rows:"):
        st.caption("Sort by any column; download as CSV from the table's menu (top right of the table).")
        st.dataframe(df.rename(columns={**DIM_LABELS, **MEASURE_LABELS}), hide_index=True, width="stretch", height=320)


# ---- Data Scientist: the model lab -----------------------------------------------------------------------------------

def scientist(c: Ctx) -> None:
    with st.container(key="sr_studio_models"):
        m = st.radio("Model", list(MODELS), horizontal=True, key="studio_model", format_func=MODELS.get,
                     label_visibility="collapsed")
    {"elasticity": _m_elasticity, "causal": _m_causal, "changepoint": _m_changepoint, "drivers": _m_drivers,
     "segments": _m_segments, "anomaly": _m_anomaly, "cannibal": _m_cannibal}[m](c)


def _m_elasticity(c: Ctx) -> None:
    e = _try("elasticity", c)
    if e is None:
        return
    pr, di = e["price"], e["dist"]
    _tiles([("Price elasticity", f"{pr['coef']:.2f}", f"95%: {pr['lo']:.2f} to {pr['hi']:.2f}", ""),
            ("Distribution elasticity", f"{di['coef']:.2f}", f"95%: {di['lo']:.2f} to {di['hi']:.2f}", ""),
            ("Fit (R²)", f"{e['r2']:.2f}", f"{e['n']} retailer-weeks", ""),
            ("Reads as", f"{-pr['coef']:.1f}% units", "lost for each 1% price rise", "")])
    allb = _fit("elasticity_all", c.category, c.brand, "", c.masked)
    h = max(420, charts.bars_h_height(len(allb)))                  # both charts as tall as the brand bars, so the cards end level
    left, right = nav.stack("studio_el").columns(2)
    with left, nav.card("studio_el_all"):
        nav.section("Every brand's price elasticity", "With 95% intervals. More negative: more price sensitive.")
        if len(allb):
            allb = allb.assign(ERR=(allb.PRICE_HI - allb.PRICE_LO) / 2).sort_values("PRICE_EL")
            _plot(charts.pl_bars_h(allb, "BRAND", "PRICE_EL", "Price elasticity", err="ERR", fmt=".2f", height=h),
                  "studio_el_all_chart")
    with right, nav.card("studio_el_fit"):
        nav.section("Actual against fitted units", "Each point is one retailer-week; the closer the points lie to a "
                    "straight rising line, the better the fit.")
        f = e["frame"].reset_index(drop=True)
        _plot(charts.pl_explore(f.assign(ROW_ID=range(len(f))), "Scatter", "FITTED", "ACTUAL", "RETAILER", "Actual units",
                                height=h, x_title="Fitted units (model)"), "studio_el_fit_chart")
    _card("Elasticity", "OLS on the log of units: log price, log distribution (ACV), retailer fixed effects, a yearly "
          "season and a trend, with HC3 robust standard errors.",
          f"R² {e['r2']:.2f} on {e['n']} retailer-weeks; price {_p(pr['p'])}, distribution {_p(di['p'])}.",
          "Price and distribution are taken as given (no supply response); promotions show up through price. "
          "Elasticities are averages over the period and the retailers.")


def _m_causal(c: Ctx) -> None:
    p = _panel(c.category, c.masked)
    weeks = sorted(pd.to_datetime(p.WEEK_END_DATE).dt.date.unique())
    try:
        start0 = _default_start(c).date()
    except an.AnalyticsError:
        start0 = weeks[-8] if len(weeks) >= 8 else None
    a, b = st.columns([1, 2], vertical_alignment="bottom")
    measure = a.selectbox("Measure", ["VALUE_SALES", "UNIT_SALES"], key="studio_ci_measure", format_func=MEASURE_LABELS.get)
    choices = weeks[20:-2]
    if len(choices) < 6:
        st.info("Causal impact needs at least 28 weeks of history for this category; there are "
                f"{len(weeks)}.", icon=":material/info:")
        return
    start = b.slider("Change starts (default: the detected change point)", min_value=choices[0], max_value=choices[-1],
                     value=start0 if start0 in choices else choices[-6], step=timedelta(weeks=1), key="studio_ci_start",
                     format="DD MMM YY")
    start = min(choices, key=lambda d: abs((d - start).days))          # snap to a stored week
    ci = _try("causal", c, f"{measure}|{start}")
    if ci is None:
        return
    money = measure == "VALUE_SALES"
    show = (lambda v: fmt.money(v, c.cur)) if money else (lambda v: f"{v:+,.0f}")
    _tiles([("Cumulative effect", show(ci["effect"]), f"over {ci['weeks']} weeks since {start:%d %b}", _tone(ci["effect"])),
            ("Against expected", fmt.signed_pct(ci["relative"]), "actual vs the model's no-shift path", _tone(ci["relative"])),
            ("Per week", show(ci["per_week"]), "average weekly effect", _tone(ci["per_week"])),
            ("Significance", _p(ci["p"]), "chance of a gap this large with no real change", "")])
    with nav.card("studio_ci_chart"):
        nav.section("Actual against the path without the shift", "Dashed: the model's counterfactual from the other "
                    "brands before the change. Bars: the weekly gap.")
        _plot(charts.pl_causal(ci["frame"], ci["start"], MEASURE_LABELS[measure]), "studio_ci_plot")
    _card("Causal impact", "Regression of the brand's log sales on each other brand's log sales and a season, fitted on "
          "the weeks before the change, then projected forward with 90% prediction intervals (a synthetic control).",
          f"Pre-period R² {ci['pre_r2']:.2f}; controls: {', '.join(ci['controls'])}.",
          "The other brands must not be moved by the shift itself. A competitor that took the share breaks this, which "
          "makes the effect a lower bound. Other events in the same weeks are attributed to the shift.")


def _m_changepoint(c: Ctx) -> None:
    measure = st.selectbox("Series", ["VALUE_SHARE_PCT", "VALUE_SALES", "ACV_DIST_PCT", "PRICE_INDEX"], key="studio_cp_measure",
                           format_func=MEASURE_LABELS.get)
    cp = _try("changepoint", c, measure)
    if cp is None:
        return
    _tiles([("Change starts", pd.Timestamp(cp["week"]).strftime("%d %b %Y"), "first week at the new level", ""),
            ("Level before", f"{cp['before']:,.2f}", MEASURE_LABELS[measure], ""),
            ("Level after", f"{cp['after']:,.2f}", f"step {cp['delta']:+,.2f}", _tone(cp["delta"])),
            ("Significance", _p(cp["p"]), f"Welch t = {cp['t']:.1f}", "")])
    with nav.card("studio_cp_chart"):
        wk = an.brand_weekly(_panel(c.category, c.masked), c.brand).set_index("WEEK_END_DATE")[measure]
        _plot(charts.pl_change_point(wk, cp, MEASURE_LABELS[measure]), "studio_cp_plot")
    _card("Change point", "Exhaustive search for the one split of the weekly series that minimises the squared error of "
          "two flat levels (at least 4 weeks each side), then Welch's t-test between the two sides.",
          f"Step {cp['delta']:+,.2f}, {_p(cp['p'])}.",
          "Finds one step change, not gradual drift or several steps; seasonality can create or hide a step. Use it to "
          "date the move and to start the causal-impact window.")


def _m_drivers(c: Ctx) -> None:
    with st.spinner("Training the gradient-boosting model…"):
        dm = _try("drivers", c)
    if dm is None:
        return
    better = dm["cv_r2"] is not None and dm["linear_r2"] is not None and dm["cv_r2"] > dm["linear_r2"]
    _tiles([("Out-of-time R², boosting", "–" if dm["cv_r2"] is None else f"{dm['cv_r2']:.2f}", f"{dm['folds']} expanding folds", ""),
            ("Out-of-time R², linear", "–" if dm["linear_r2"] is None else f"{dm['linear_r2']:.2f}", "baseline", ""),
            ("Top driver", dm["importance"].LABEL.iloc[0], "by permutation importance", ""),
            ("Verdict", "Non-linear" if better else "Close to linear",
             "boosting beats linear" if better else "trust the elasticity model", "")])
    left, right = nav.stack("studio_dm").columns([2, 3])
    with left, nav.card("studio_dm_imp"):
        nav.section("What drives share", "Drop in accuracy when a driver is shuffled (permutation importance)")
        _plot(charts.pl_bars_h(dm["importance"], "LABEL", "IMPORTANCE", "Importance", err="STD", fmt=".3f"), "studio_dm_imp_chart")
    with right, nav.card("studio_dm_pdp"):
        nav.section("How share responds", "Partial dependence: the model's average share as one driver moves")
        if dm["curves"]:
            # as tall as the importance bars beside it, so the two cards end level
            _plot(charts.pl_curves(dm["curves"], an.DRIVER_FEATURES, "Value share %",
                                   height=max(320, charts.bars_h_height(len(dm["importance"])))), "studio_dm_pdp_chart")
    _card("Driver model", "Gradient boosting (scikit-learn, 150 trees of depth 3) on the brand's value share per "
          "retailer-week, from its price index, distribution, SKUs and promotion depth, the competitors' price index and "
          "distribution, and the season. Scored out of time against a linear model.",
          f"Out-of-time R² {dm['cv_r2']:.2f} (linear {dm['linear_r2']:.2f}); in-sample {dm['in_sample_r2']:.2f}; {dm['n']} rows."
          if dm["cv_r2"] is not None else "Too few weeks for an out-of-time score.",
          "Importance is predictive, not causal: drivers that move together share credit. When the linear model scores "
          "higher, the relationships are close to linear and the elasticity model is the better guide.")


def _m_segments(c: Ctx) -> None:
    sg = _try("segments", c)
    if sg is None:
        return
    pts = sg["points"]
    a, b = st.columns(2)
    xs = list(an.SEGMENT_FEATURES)
    x = a.selectbox("X axis", xs, index=xs.index("ACV_CHG"), key="studio_sg_x", format_func=an.SEGMENT_FEATURES.get)
    y = b.selectbox("Y axis", xs, index=xs.index("SHARE_CHG"), key="studio_sg_y", format_func=an.SEGMENT_FEATURES.get)
    mine = pts[pts.BRAND == c.brand].SEGMENT.value_counts()
    _tiles([("Segments found", str(sg["k"]), "k chosen by silhouette", ""), ("Silhouette", f"{sg['silhouette']:.2f}",
            "separation, 0 to 1", ""), (f"{c.brand} mostly in", mine.index[0] if len(mine) else "–", "across its retailers", ""),
            ("Positions", str(len(pts)), "brand x retailer", "")])
    with nav.card("studio_sg_chart"):
        _plot(charts.pl_segments(pts, x, y, an.SEGMENT_FEATURES[x], an.SEGMENT_FEATURES[y]), "studio_sg_plot")
    prof = sg["profile"].rename(columns={**an.SEGMENT_FEATURES, "SEGMENT": "Segment", "POINTS": "Positions"})
    st.dataframe(nav.striped(prof.round(2)), hide_index=True, width="stretch",
                 column_config={col: st.column_config.NumberColumn(format="%.0f" if col == "Positions" else "%.2f")
                                for col in prof.columns if pd.api.types.is_numeric_dtype(prof[col])})
    _card("Segments", "k-means on six standardised features of every brand at every retailer (share, share change, price "
          "index, distribution and its change, sales growth; last 4 weeks vs the 4 before); k from 2 to 5 by silhouette.",
          f"k = {sg['k']}, silhouette {sg['silhouette']:.2f}.",
          "Names come from the feature that sets each segment's centre apart most. k-means assumes round, similar-sized "
          "groups; a low silhouette means the segments overlap.")


def _m_anomaly(c: Ctx) -> None:
    k = _sku_panel(c.category, c.s["BRAND"], c.masked)
    try:
        res = an.anomaly_scan(k)
    except an.AnalyticsError as e:
        st.info(str(e), icon=":material/info:")
        return
    rows = res["rows"]
    _tiles([("Rows scanned", f"{res['n']:,}", "SKU x retailer weeks", ""), ("Flagged", str(res["flagged"]),
            "most isolated 2%", "neg" if res["flagged"] else ""),
            ("Top anomaly", f"{rows.ITEM_DESC.iloc[0]}" if len(rows) else "–",
             f"{rows.RETAILER.iloc[0]} · {pd.Timestamp(rows.WEEK_END_DATE.iloc[0]):%d %b}" if len(rows) else "", ""),
            ("Stands out on", rows.WHY.iloc[0] if len(rows) else "–", f"robust z {rows.WHY_Z.iloc[0]:.1f}" if len(rows) else "", "")])
    with nav.card("studio_an_table"):
        nav.section("Most unusual SKU weeks", "Check these against the data rules before trusting a move built on them")
        st.dataframe(nav.striped(pd.DataFrame({
            "Week": pd.to_datetime(rows.WEEK_END_DATE).dt.strftime("%d %b %Y"), "Retailer": rows.RETAILER, "SKU": rows.ITEM_DESC,
            "Stands out on": rows.WHY, "Robust z": rows.WHY_Z.round(1), "Sales WoW": (100 * rows.SALES_WOW).round(1),
            "Price WoW": (100 * rows.PRICE_WOW).round(1), "ACV change": rows.ACV_WOW.round(1),
            "Anomaly score": rows.SCORE.round(3)})), hide_index=True, width="stretch", row_height=34,
            column_config={"Robust z": st.column_config.NumberColumn(format="%.1f"),
                           "Sales WoW": st.column_config.NumberColumn(format="%+.1f%%"),
                           "Price WoW": st.column_config.NumberColumn(format="%+.1f%%"),
                           "ACV change": st.column_config.NumberColumn(format="%+.1f"),
                           "Anomaly score": st.column_config.NumberColumn(format="%.3f")})
    with nav.card("studio_an_chart"):
        allr = res["all"].assign(FLAG=np.where(res["all"].FLAGGED, "Flagged", "Normal"))
        allr = allr.assign(ROW_ID=range(len(allr)))
        _plot(charts.pl_explore(allr, "Scatter", "PRICE_WOW", "SALES_WOW", "FLAG", "Sales change week on week",
                                x_title="Price change week on week"), "studio_an_plot")
        st.caption("Each point is one SKU at one retailer in one week: price change (x) against sales change (y).")
    _card("Anomaly scan", "Isolation Forest (scikit-learn, 300 trees, 2% contamination) on week-on-week sales, price and "
          "distribution changes from SQL, plus units per store against the SKU's own median.",
          f"{res['flagged']} of {res['n']:,} rows flagged.",
          "Unusual is not wrong: a genuine promotion or listing is also isolated. The weekly run's data rules remain the "
          "check of record.")


def _m_cannibal(c: Ctx) -> None:
    cb = _try("cannibal", c)
    if cb is None:
        return
    pr = cb["pairs"]
    top = pr.iloc[0] if len(pr) else None
    _tiles([("Strongest trade", top.BRAND if top is not None else "–", f"correlation {top.CORR:+.2f}" if top is not None else "", ""),
            ("Share it takes per point lost", f"{top.GAIN_PER_PT_LOST:.2f} pts" if top is not None else "–", "OLS slope", ""),
            ("Weeks", str(cb["weeks"]), "week-on-week share changes", ""), ("Brands", str(len(pr) + 1), "in the category", "")])
    h = max(charts.heat_height(len(cb["matrix"])), charts.bars_h_height(len(pr)))   # one height, so the cards end level
    left, right = nav.stack("studio_cb").columns(2)
    with left, nav.card("studio_cb_pairs"):
        nav.section(f"Who moves against {c.brand}", "Correlation of week-on-week share changes; negative means they trade share")
        _plot(charts.pl_bars_h(pr.sort_values("CORR", ascending=False), "BRAND", "CORR", "Correlation", signed=True, fmt=".2f",
                               height=h), "studio_cb_pairs_chart")
    with right, nav.card("studio_cb_matrix"):
        nav.section("All brands", "Correlation matrix of week-on-week share changes")
        _plot(charts.pl_heat(cb["matrix"].round(2), "Correlation", height=h), "studio_cb_matrix_chart")
    _card("Cannibalisation", "Pearson correlation of week-on-week changes in category value share between brands, and the "
          "OLS slope of each brand's change on this brand's change.", f"{cb['weeks']} weeks.",
          "Correlation shows who moves together, not who caused it; shares sum to 100, so some negative correlation is "
          "built in. The weekly run's share flow is the allocation of record.")


# ---- Emerging shifts (a studio lens and a Radar card) -------------------------------------------------------------

@_cached
def _emerging(category: str, masked: bool, threshold: float, min_z: float) -> pd.DataFrame:
    return an.emerging_shifts(_panel(category, masked), threshold, min_z)


def _emerging_frame(category: str, masked: bool) -> tuple[pd.DataFrame, float, float]:
    """The scan with the run's own gates as thresholds: MIN_SHARE_PTS and MIN_Z from OPS.SETTINGS (rule 4)."""
    thr, mz = data.cfg("MIN_SHARE_PTS"), data.cfg("MIN_Z")
    if thr is None or mz is None:
        raise an.AnalyticsError("The emerging-shift scan needs the MIN_SHARE_PTS and MIN_Z settings.")
    return _emerging(category, masked, float(thr), float(mz)), float(thr), float(mz)


def _emerging_table(em: pd.DataFrame) -> pd.DataFrame:
    wk = lambda v: "–" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d %b")   # noqa: E731
    return pd.DataFrame({"Brand": em.BRAND, "Retailer": em.RETAILER,
                         "Move": np.where(em.DIRECTION == "UP", "↑ gaining", "↓ losing"), "Status": em.STATUS,
                         "Chippy flagged": em.ALARM_WEEK.map(wk), "4-week report": em.REPORT_WEEK.map(wk),
                         "Weeks earlier": em.LEAD_WEEKS.map(lambda v: "–" if pd.isna(v) else f"{int(v)}"),
                         "L4W vs YA, pts": em.L4W_VS_YA_PTS.map(fmt.pts), "Drift, sd": em.DRIFT_SD.round(1)})


def emerging(c: Ctx) -> None:
    try:
        em, thr, mz = _emerging_frame(c.category, c.masked)
    except an.AnalyticsError as e:
        st.info(str(e), icon=":material/info:")
        return
    if em.empty:
        st.info("No brand at any retailer is moving outside its normal range.", icon=":material/info:")
        return
    new = em[~em.IN_REPORTS]
    early = em[em.STATUS == "Flagged early"]
    _tiles([("Emerging: not in reports yet", str(len(new)), "moving now; no 4-week report has flagged it", "neg" if len(new) else ""),
            ("Flagged before the report", str(len(early)), "caught in a weekly run before the period report", ""),
            ("Average lead", f"{early.LEAD_WEEKS.mean():.1f} weeks" if len(early) else "–", "for moves the report also caught", ""),
            ("Series watched", f"{em.shape[0]} moving", "brand x retailer, scanned weekly", "")])
    with nav.card("studio_em_table"):
        nav.section("Moves building now", f"Same test as the reports (change at least {thr:g} pts and at least {mz:g} "
                    "standard deviations from normal, last 4 weeks vs year ago), run every week instead of every 4 weeks, "
                    "plus a drift detector for slow moves.")
        st.dataframe(nav.striped(_emerging_table(em)), hide_index=True, width="stretch", row_height=34)
    lead = em[~em.IN_REPORTS].dropna(subset=["LEAD_WEEKS"]).assign(ITEM=lambda x: x.BRAND + " · " + x.RETAILER)
    if len(lead):
        with nav.card("studio_em_lead"):
            nav.section("Weeks ahead of the 4-week report", "For moves not yet in a report: weeks since Chippy flagged them")
            _plot(charts.pl_bars_h(lead.head(12)[["ITEM", "LEAD_WEEKS"]], "ITEM", "LEAD_WEEKS", "Weeks", fmt=".0f"),
                  "studio_em_lead_chart")
    _card("Emerging shifts", "For each brand at each retailer: weekly value share minus the same week a year ago (no "
          "season). The 4-week report view tests the last-4-weeks change once per 4-week period; Chippy runs the same "
          "test every week and a two-sided CUSUM (slack 0.5, alarm at 5 standard deviations) for slow drift.",
          f"Thresholds from the settings: MIN_SHARE_PTS {thr:g}, MIN_Z {mz:g}.",
          "Lead time comes from the weekly cadence and the drift detector, not from a different test. Drift alarms on "
          "small brands can be noise; treat them as a watch list, and the weekly run's gates as the shifts of record.")
    _actions_row(c, "em", f"Emerging shifts: {len(new)} moving and not in reports yet; " + "; ".join(
        f"{r.BRAND} at {r.RETAILER} {'up' if r.DIRECTION == 'UP' else 'down'}" for r in new.head(3).itertuples()) + ".",
        "Which emerging shifts should we look at before the next 4-week report?")


def emerging_radar(run) -> None:
    """The Radar card: what is building before the reports show it, top five, with a link into Insight Studio."""
    masked = data.cfg("DISPLAY_ALIAS") is True
    with nav.card("emerging_radar"):
        st.html('<div class="sr-radar-section"><h3><span class="sr-ico" aria-hidden="true">radar</span>Emerging Shifts'
                '</h3><p>Moves building now, found by the weekly scan before a 4-week report shows them</p></div>')
        if not st.session_state.get("sr_emerging_on"):          # on demand: the scan reads the full weekly panel
            if st.button("Scan every brand at every retailer", key="sr_btn_emerging_scan", icon=":material/radar:"):
                st.session_state["sr_emerging_on"] = True
                st.rerun()
            return
        try:
            em, thr, mz = _emerging_frame(str(data.filters().category if hasattr(data, "filters")
                                              else data.cfg("SCOPE_CATEGORY")), masked)
        except an.AnalyticsError as e:
            st.caption(str(e))
            return
        if em.empty:
            st.caption("Nothing is moving outside its normal range at any retailer.")
            return
        new = em[~em.IN_REPORTS]
        early = em[em.STATUS == "Flagged early"]
        st.html(f'<div class="sr-em-strip"><b>{len(new)}</b><span>not in any report yet</span><b>{len(early)}</b>'
                f'<span>caught before the period report</span><b>{early.LEAD_WEEKS.mean():.1f}</b><span>weeks average lead'
                f'</span></div>' if len(early) else f'<div class="sr-em-strip"><b>{len(new)}</b><span>not in any report yet'
                '</span></div>')
        st.dataframe(nav.striped(_emerging_table(em.head(5))), hide_index=True, width="stretch", row_height=34)
        if st.button("Open Emerging Shifts in Insight Studio", key="sr_btn_emerging", icon=":material/insights:",
                     type="tertiary"):
            st.session_state["shift_view"] = "Studio"
            st.session_state["studio_lens"] = "early"
            st.switch_page("pages/1_Shift_detail.py")


# ---- entry point ----------------------------------------------------------------------------------------------------

def render(c: Ctx) -> None:
    if st.session_state.get("studio_lens") not in LENSES:
        st.session_state["studio_lens"] = "manager"           # the decision brief first
    with st.container(key="sr_studio_lens"):
        lens = st.radio("Lens", list(LENSES), horizontal=True, key="studio_lens", format_func=lambda k: LENSES[k][0],
                        label_visibility="collapsed")
    st.html(f'<div class="sr-studio-q"><span class="sr-ico" aria-hidden="true">psychology_alt</span>'
            f'<b>{escape(LENSES[lens][0])}</b><span>{escape(LENSES[lens][1])}</span>'
            '<em>Exploratory · not in the brief</em></div>')
    {"director": director, "manager": manager, "amanager": analytics_manager, "analyst": analyst,
     "scientist": scientist, "early": emerging}[lens](c)
