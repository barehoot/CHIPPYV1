"""Brand explorer: any company, brand and market in any period, back to 2020, driven by the sidebar filters.

Shift Detail opens it as a second mode, and on its own when the filters match no ranked shift. Every figure is read from
SQL in data.py (brand_snapshot, trend, region_summary, price_ladder); this module only formats and lays them out.
Exploratory: the weekly brief stays the record.
"""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from sr_ui import charts, format as fmt, nav


class _Data:
    """sr_ui.data looked up at call time (like studio.py), so the installed data module is the one used."""
    def __getattr__(self, name):
        from sr_ui import data as current
        return getattr(current, name)


data = _Data()


def _kpi(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="sr-intel-card"><span>{escape(label)}</span><b>{escape(value)}</b>'
            f'<em>{escape(sub)}</em></div>')


def render() -> None:
    f = data.filters()
    markets = data.market_names()
    where = markets.get(f.market_id, f.market_id)
    cur = data.cfg("CURRENCY") or ""
    snap = data.brand_snapshot(f.market_id, f.category, f.weeks)
    if snap.empty:
        st.info(f"No {f.category} sales in {where} in the {f.weeks} weeks to {f.as_of}.", icon=":material/info:")
        return
    if f.manufacturer:
        snap_c = snap[snap.MANUFACTURER == f.manufacturer]
    else:
        snap_c = snap
    brands = list(snap_c.BRAND) or list(snap.BRAND)
    focus = f.brand if f.brand in brands else st.selectbox("Brand", brands, format_func=fmt.name, key="sr_ex_brand")
    row = snap[snap.BRAND == focus].iloc[0]

    nav.section(f"{fmt.name(focus)} · {where} · {f.category}",
                f"{f.weeks} weeks to {f.as_of}, against the {f.weeks} weeks before (PP) and the same weeks a year ago (YA)")
    ya = "no year-ago data" if pd.isna(row.SHARE_YA) else f"{fmt.pts(row.CHG_YA_PTS)} vs YA"
    st.html('<div class="sr-intel-cards">' + "".join([
        _kpi("Value share", fmt.pct(row.SHARE / 100), f"{fmt.pts(row.CHG_PP_PTS)} vs PP" if pd.notna(row.CHG_PP_PTS) else ""),
        _kpi("Share vs year ago", "–" if pd.isna(row.SHARE_YA) else fmt.pct(row.SHARE_YA / 100), ya),
        _kpi("Value sales", fmt.money(row.SALES, cur),
             "" if pd.isna(row.SALES_GROWTH_YA_PCT) else f"{fmt.signed_pct(row.SALES_GROWTH_YA_PCT / 100)} vs YA"),
        _kpi("Distribution (mean ACV)", f"{row.ACV:.1f}" if pd.notna(row.ACV) else "–",
             "" if pd.isna(row.ACV_CHG_YA) else f"{row.ACV_CHG_YA:+.1f} vs YA"),
        _kpi("Price index", f"{row.PRICE_INDEX:.2f}" if pd.notna(row.PRICE_INDEX) else "–", "1.00 = category average"),
    ]) + "</div>")

    c1, c2 = st.columns(2)
    with c1, nav.card("sr_ex_trend"):
        nav.section("Weekly value share", "Up to the as-of week")
        t = data.trend(f.market_id, f.category, focus, max(f.weeks, 104))
        if len(t):
            st.plotly_chart(charts.pl_explore(t.assign(ROW_ID=range(len(t))), "Line", "WEEK_END_DATE", "VALUE_SHARE_PCT",
                                              None, "Value share %", 300),
                            config=charts.PLOTLY_CONFIG, width="stretch")
        else:
            st.caption("No weekly share stored for this brand and market.")
    with c2, nav.card("sr_ex_where"):
        nav.section("Where it is moving", "Markets under the selected market, this period vs the one before")
        r = data.region_summary(f.category, focus, f.weeks)
        if len(r):
            r = r.sort_values("CHG_PTS")
            st.plotly_chart(charts.pl_bars_h(r[["RETAILER", "CHG_PTS"]].dropna(), "RETAILER", "CHG_PTS",
                                             "Share change, pts", signed=True, fmt=".2f"),
                            config=charts.PLOTLY_CONFIG, width="stretch")
        else:
            st.caption("No lower-level markets under this market.")

    with nav.card("sr_ex_table"):
        nav.section("Competitive benchmark", "Every brand in this market and period; your company first when one is chosen")
        mine = snap.MANUFACTURER == f.manufacturer if f.manufacturer else pd.Series(False, index=snap.index)
        shown = pd.concat([snap[mine], snap[~mine]])
        st.dataframe(nav.striped(pd.DataFrame({
            "Brand": shown.BRAND.map(fmt.name), "Company": shown.MANUFACTURER.map(lambda m: fmt.name(m, "MANUFACTURER")),
            "Value share": (shown.SHARE / 100).map(fmt.pct), "vs PP": shown.CHG_PP_PTS.map(fmt.pts),
            "vs YA": shown.CHG_YA_PTS.map(lambda v: "–" if pd.isna(v) else fmt.pts(v)),
            "Value sales": shown.SALES.map(lambda v: fmt.money(v, cur)),
            "ACV": shown.ACV.round(1), "Price index": shown.PRICE_INDEX.round(2)})),
            hide_index=True, width="stretch", row_height=34)
    st.caption("Shares, changes and indices are computed in SQL from the weekly panel. Exploratory: the weekly brief is the "
               "record. Ask Chippy (Recovery Strategist, Pricing & Promo, Forecast & Risk, Competitive benchmarking) "
               "explains and plans from the same data.")
