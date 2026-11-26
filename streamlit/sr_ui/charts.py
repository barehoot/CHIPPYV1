"""Altair chart builders (L11). Polarity: a gain is rich teal, a loss is terracotta, and the total is pale teal with a
deep-teal outline, so it reads as neither; every bar also carries a signed value label, so direction never rests on
colour alone. Two-series charts use rich teal (solid) and slate (dashed); status colours only for run states, always
next to their text. Every bar sits on a zero baseline, every mark has a tooltip, and every chart goes through _theme()."""
from __future__ import annotations


from datetime import date, timedelta

import altair as alt
import numpy as np
import pandas as pd

# Deep Teal & Mist palette (mirrored in nav.TOKENS and .streamlit/config.toml). No other colours.
TEAL, DEEP, MIST, SEA, SLATE = "#1E5556", "#173F43", "#F5F8F8", "#A6C1BD", "#647C80"
PALE, GOLD, TERRA, WHITE = "#DCEBE8", "#C6A879", "#C87970", "#FFFFFF"
GRID = "rgba(166, 193, 189, 0.35)"                                # sea-glass hairlines
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"

GAIN, LOSS, TOTAL = TEAL, TERRA, PALE                             # fills
OUTLINE = {"gain": TEAL, "loss": TERRA, "total": DEEP}            # the total's pale fill gets a deep-teal edge
SERIES = [TEAL, SLATE]                                            # value share teal (solid), distribution slate (dashed)
STATUS = {"OK": TEAL, "WARN": GOLD, "FAILED": TERRA, "SKIPPED": SEA}
INK_2, AXIS, SHADE = DEEP, SEA, PALE
TERMS = [("DIST_PTS", "Distribution"), ("VELOCITY_PTS", "Velocity"), ("PRICE_PTS", "Price"), ("PROMO_PTS", "Promo")]

# Analysis views. Models share two supporting inks and are told apart by dash pattern.
MODEL_STYLE = {"History": (TEAL, [1, 0]), "ARIMA": (SLATE, [7, 3]), "SARIMA": (SEA, [3, 3]),
               "Holt-Winters": (SLATE, [10, 3, 2, 3]), "TCN": (SEA, [1, 3])}
SEQ = [MIST, PALE, SEA, TEAL, DEEP]                                # low to high
DIV = [TERRA, MIST, TEAL]                                          # loss, zero, gain (cells also carry signed labels)
REGION_TILES = {"North": (1, 0), "West": (0, 1), "East": (2, 1), "South": (1, 2)}   # compass layout (col, row)

BAR_ROW, BAR_AXIS = 30, 46          # px per bar row, and room for the x axis and its title


def _num(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)


def _theme(chart):
    """One look for every chart: transparent on the card, Inter, quiet sea-glass axes and grid, no view border."""
    return (chart.configure(background="transparent", font=FONT)
            .configure_view(stroke=None)
            .configure_axis(labelColor=SLATE, labelFont=FONT, labelFontSize=11, labelPadding=6,
                            titleColor=SLATE, titleFont=FONT, titleFontSize=11, titleFontWeight=500, titlePadding=10,
                            domainColor=SEA, tickColor=SEA, gridColor=GRID)
            .configure_axisBand(domain=False, ticks=False, labelPadding=8, labelColor=DEEP)
            .configure_legend(labelColor=SLATE, labelFont=FONT, labelFontSize=11, titleColor=SLATE, titleFont=FONT,
                              titleFontSize=11, titleFontWeight=500, symbolStrokeWidth=2)
            .configure_title(font=FONT, fontSize=12, fontWeight=600, color=DEEP, anchor="start", offset=8)
            .configure_text(font=FONT))


def _cell_scale(v: pd.Series, diverging: bool) -> tuple[alt.Scale, pd.Series]:
    """Colour scale for heatmap cells and tiles, and which cells are dark enough to need white text.
    Diverging scales are symmetric about zero, so a colour always means the same size of change in either direction
    (without this, an all-negative column stretches the scale and a mid-size loss looks like no change). Only the
    teal (gain) end is dark: terracotta cells keep deep-teal text, which reads better on them than white."""
    v = v.astype(float)
    if diverging:
        m = v.abs().max()
        if pd.isna(m) or m == 0:
            return alt.Scale(range=DIV, interpolate="rgb", domainMid=0), v > 0
        return alt.Scale(domain=[-m, 0, m], range=DIV, interpolate="rgb"), v > 0.55 * m
    return alt.Scale(range=SEQ, interpolate="rgb"), v > v.min() + 0.6 * (v.max() - v.min())


def bridge_frame(b: dict) -> pd.DataFrame:
    """One SHARE_BRIDGE row -> (term, pts, kind): the terms its mode has, then 'Total change'. Points throughout."""
    rows = [(label, float(b[col])) for col, label in TERMS if _num(b.get(col)) is not None]
    rows.append(("Total change", 100.0 * float(b["D_SHARE"])))
    df = pd.DataFrame(rows, columns=["term", "pts"])
    df["kind"] = ["total" if t == "Total change" else ("gain" if p >= 0 else "loss") for t, p in zip(df.term, df.pts)]
    return df


def _polarity(kinds: list[str]) -> tuple[alt.Color, alt.Stroke]:
    fills = {"gain": GAIN, "loss": LOSS, "total": TOTAL}
    color = alt.Color("kind:N", scale=alt.Scale(domain=kinds, range=[fills[k] for k in kinds]), legend=None)
    stroke = alt.Stroke("kind:N", scale=alt.Scale(domain=kinds, range=[OUTLINE[k] for k in kinds]), legend=None)
    return color, stroke


def _signed_bars(df: pd.DataFrame, cat: str, val: str, color: alt.Color, tooltip: list, sort: list | str,
                 x_title: str, stroke: alt.Stroke | None = None, emphasis: str | None = None,
                 opacity=None) -> alt.LayerChart:
    axis = alt.Axis(labelFontWeight=alt.ExprRef(f"datum.value == '{emphasis}' ? 600 : 400")) if emphasis else alt.Axis()
    y = alt.Y(f"{cat}:N", sort=sort, title=None, axis=axis)
    x = alt.X(f"{val}:Q", title=x_title, scale=alt.Scale(padding=40))   # room for the value labels at both ends
    enc = {"y": y, "x": x, "color": color, "tooltip": tooltip}
    if stroke is not None:
        enc["stroke"] = stroke
    if opacity is not None:
        enc["opacity"] = opacity
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=3, size=14, strokeWidth=1).encode(**enc)
    pos = alt.Chart(df).transform_filter(f"datum.{val} >= 0").mark_text(
        align="left", dx=5, color=INK_2, fontSize=11, fontWeight=500).encode(
        y=y, x=f"{val}:Q", text=alt.Text(f"{val}:Q", format="+.2f"))
    neg = alt.Chart(df).transform_filter(f"datum.{val} < 0").mark_text(
        align="right", dx=-5, color=INK_2, fontSize=11, fontWeight=500).encode(
        y=y, x=f"{val}:Q", text=alt.Text(f"{val}:Q", format="+.2f"))
    zero = alt.Chart(pd.DataFrame({"x": [0.0]})).mark_rule(color=SLATE, strokeWidth=1).encode(x="x:Q")
    return (bars + pos + neg + zero).properties(height=BAR_ROW * max(len(df), 1) + BAR_AXIS, width="container")


def bridge_bars(b: dict, highlight: str | None = None) -> alt.LayerChart:
    """The share bridge. highlight names one lever to emphasise (Driver Explorer): the others and the total fade.
    Presentation only: the same terms and values."""
    df = bridge_frame(b)
    color, stroke = _polarity(["gain", "loss", "total"])
    tooltip = [alt.Tooltip("term:N", title="Driver"), alt.Tooltip("pts:Q", title="Share points", format="+.2f")]
    opacity = (alt.condition(f"datum.term == '{highlight}'", alt.value(1.0), alt.value(0.3))
               if highlight and highlight in set(df.term) else None)
    return _theme(_signed_bars(df, "term", "pts", color, tooltip, list(df.term), "Share points", stroke,
                               emphasis=highlight if opacity is not None else "Total change", opacity=opacity))


def momentum_spark(df: pd.DataFrame) -> alt.Chart:
    """Market Momentum: one KPI over the stored weekly runs (WEEK, VALUE, LABEL, SHOWN). A single mark (area with its
    line and points), so a click selects a week (selection 'pt' on WEEK)."""
    pick = alt.selection_point(name="pt", fields=["WEEK"], on="click")
    chart = alt.Chart(df).mark_area(
        line={"color": TEAL, "strokeWidth": 1.8}, point={"filled": True, "fill": TEAL, "size": 26, "cursor": "pointer"},
        color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color="rgba(30,85,86,0.22)", offset=0),
                                                     alt.GradientStop(color="rgba(30,85,86,0.02)", offset=1)],
                           x1=1, x2=1, y1=0, y2=1),
        interpolate="monotone", cursor="pointer").encode(
        x=alt.X("WEEK:O", sort=None, axis=None),
        y=alt.Y("VALUE:Q", axis=None, scale=alt.Scale(zero=True, nice=False)),
        tooltip=[alt.Tooltip("LABEL:N", title="Week ending"), alt.Tooltip("SHOWN:N", title="Value")]).add_params(pick)
    return chart.properties(height=34, width="container").configure(background="transparent").configure_view(stroke=None)


def sparkline(df: pd.DataFrame, value_title: str = "Value share %") -> alt.Chart:
    """A small stored-history line with light shading (WEEK_END_DATE, VALUE); hover shows the week and value."""
    return (alt.Chart(df).mark_area(
        line={"color": TEAL, "strokeWidth": 1.6}, interpolate="monotone",
        color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color="rgba(30,85,86,0.18)", offset=0),
                                                     alt.GradientStop(color="rgba(30,85,86,0.01)", offset=1)],
                           x1=1, x2=1, y1=0, y2=1)).encode(
        x=alt.X("WEEK_END_DATE:T", axis=None), y=alt.Y("VALUE:Q", axis=None, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("WEEK_END_DATE:T", title="Week ending"), alt.Tooltip("VALUE:Q", title=value_title, format=".2f")])
        .properties(height=42, width="container").configure(background="transparent").configure_view(stroke=None))


def retailer_bars(where_df: pd.DataFrame) -> alt.LayerChart:
    """EXACT_RETAILER rows: TOTAL_PTS by CONTRIBUTOR, sorted by ABS(TOTAL_PTS), gain/loss colours, signed labels,
    zero rule; the tooltip adds PERF_PTS and MIX_PTS."""
    df = where_df[where_df.METHOD == "EXACT_RETAILER"].copy()
    df["kind"] = ["gain" if p >= 0 else "loss" for p in df.TOTAL_PTS]
    order = list(df.assign(a=df.TOTAL_PTS.abs()).sort_values("a", ascending=False).CONTRIBUTOR)
    color, stroke = _polarity(["gain", "loss"])
    tooltip = [alt.Tooltip("CONTRIBUTOR:N", title="Retailer"), alt.Tooltip("TOTAL_PTS:Q", title="Total", format="+.2f"),
               alt.Tooltip("PERF_PTS:Q", title="Performance", format="+.2f"), alt.Tooltip("MIX_PTS:Q", title="Mix", format="+.2f")]
    return _theme(_signed_bars(df, "CONTRIBUTOR", "TOTAL_PTS", color, tooltip, order, "Share points", stroke))


def flow_bars(flow_df: pd.DataFrame) -> alt.LayerChart:
    """COUNTERPART by FLOW_PTS in SERIES[0], value labels, no legend; the section title says which way share moved."""
    df = flow_df.copy()
    y = alt.Y("COUNTERPART:N", sort="-x", title=None)
    x = alt.X("FLOW_PTS:Q", title="Share points", scale=alt.Scale(padding=40))
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=3, size=14, color=SERIES[0]).encode(
        y=y, x=x,
        tooltip=[alt.Tooltip("COUNTERPART:N", title="Brand"), alt.Tooltip("FLOW_PTS:Q", title="Share points", format=".2f")])
    text = alt.Chart(df).mark_text(align="left", dx=5, color=INK_2, fontSize=11, fontWeight=500).encode(
        y=y, x="FLOW_PTS:Q", text=alt.Text("FLOW_PTS:Q", format=".2f"))
    zero = alt.Chart(pd.DataFrame({"x": [0.0]})).mark_rule(color=SLATE, strokeWidth=1).encode(x="x:Q")
    return _theme((bars + text + zero).properties(height=BAR_ROW * max(len(df), 1) + BAR_AXIS, width="container"))


def period_bounds(as_of: date, cmp_code: str, cur_weeks: int) -> tuple[tuple[date, date], tuple[date, date]]:
    """Current period = the last N weeks to the as-of week; base = the same weeks 52 weeks earlier, or the previous
    N weeks for L4W_VS_PP. Each as (first week end, last week end)."""
    now = (as_of - timedelta(weeks=cur_weeks - 1), as_of)
    shift = timedelta(weeks=cur_weeks if cmp_code == "L4W_VS_PP" else 52)
    return now, (now[0] - shift, now[1] - shift)


def trend_lines(trend_df: pd.DataFrame, now: tuple[date, date], base: tuple[date, date] | None) -> alt.LayerChart:
    """Long format (WEEK_END_DATE, series, pct) on one % axis: value share SERIES[0], distribution share SERIES[1],
    2px lines, legend plus direct labels at the last week, stone bands labelled Now and Before for the compared
    periods, crosshair rule with tooltip."""
    long = trend_df.melt(id_vars="WEEK_END_DATE", value_vars=["VALUE_SHARE_PCT", "DIST_SHARE_PCT"],
                         var_name="series", value_name="pct")
    long["series"] = long.series.map({"VALUE_SHARE_PCT": "Value share", "DIST_SHARE_PCT": "Distribution share"})
    color = alt.Color("series:N", scale=alt.Scale(domain=["Value share", "Distribution share"], range=SERIES),
                      legend=alt.Legend(orient="top", title=None))
    x = alt.X("WEEK_END_DATE:T", title=None)
    spans = [{"start": now[0] - timedelta(days=6), "end": now[1], "label": "Now"}]
    if base:
        spans.append({"start": base[0] - timedelta(days=6), "end": base[1], "label": "Before"})
    spans_df = pd.DataFrame(spans)
    spans_df["mid"] = spans_df.start + (spans_df.end - spans_df.start) / 2
    # "Now" in muted gold, "Before" in pale teal: fixed values, so the lines keep their own colour scale
    shade = alt.Chart(spans_df).mark_rect(opacity=0.45).encode(
        x="start:T", x2="end:T", tooltip=[alt.Tooltip("label:N", title="Compared period")],
        color=alt.condition("datum.label == 'Now'", alt.value(GOLD), alt.value(SHADE)))
    tags = alt.Chart(spans_df).mark_text(baseline="top", color=SLATE, fontSize=10, fontWeight=600).encode(
        x="mid:T", y=alt.value(4), text="label:N")
    lines = alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=x, y=alt.Y("pct:Q", title="% of category"), color=color,
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=["Value share", "Distribution share"],
                                                              range=[[1, 0], [6, 3]]), legend=None))
    last = long[long.WEEK_END_DATE == long.WEEK_END_DATE.max()]
    labels = alt.Chart(last).mark_text(align="left", dx=6, color=INK_2, fontSize=11, fontWeight=600).encode(
        x=x, y="pct:Q", text=alt.Text("pct:Q", format=".1f"))
    hover = alt.selection_point(fields=["WEEK_END_DATE"], nearest=True, on="pointerover", empty=False)
    rule = alt.Chart(long).mark_rule(color=SLATE, strokeDash=[2, 2]).encode(
        x=x, opacity=alt.condition(hover, alt.value(0.6), alt.value(0)),
        tooltip=[alt.Tooltip("WEEK_END_DATE:T", title="Week ending"), alt.Tooltip("series:N"),
                 alt.Tooltip("pct:Q", title="%", format=".2f")]).add_params(hover)
    zoom = alt.selection_interval(bind="scales", encodings=["x"])      # drag to pan, scroll to zoom the weeks
    return _theme((shade + tags + lines.add_params(zoom) + labels + rule).properties(height=260, width="container"))


def step_timeline(steps_df: pd.DataFrame) -> alt.Chart:
    """Bars from STARTED_AT to ENDED_AT per STEP, coloured by STATUS with a legend; tooltip: rows written, message."""
    return _theme(alt.Chart(steps_df).mark_bar(size=12, cornerRadius=2).encode(
        y=alt.Y("STEP:N", sort=list(steps_df.STEP), title=None),
        x=alt.X("STARTED_AT:T", title=None, axis=alt.Axis(format="%H:%M:%S", labelOverlap=True)), x2="ENDED_AT:T",
        color=alt.Color("STATUS:N", scale=alt.Scale(domain=list(STATUS), range=list(STATUS.values())),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["STEP", "STATUS", alt.Tooltip("ROWS_WRITTEN:Q", title="Rows"), "MESSAGE"],
    ).properties(height=alt.Step(28), width="container"))      # a fixed row height: legend and axis add their own room


# ---- Shift analysis tabs ---------------------------------------------------------------------------------------------

def forecast_chart(history: pd.DataFrame, results: list[dict], value_title: str, fmt: str = ",.2f",
                   zero: bool = True) -> alt.LayerChart:
    """History (WEEK_END_DATE, VALUE) as a solid plum line and each model's forecast as a dashed line with its 80% band.
    Click a legend entry to show one model; hover for a crosshair with the values for that week; drag to pan and scroll
    to zoom the weeks (double-click resets). zero=False fits the value axis to the data (a line chart, not bars)."""
    hist = history.assign(MODEL="History")[["WEEK_END_DATE", "VALUE", "MODEL"]]
    fc = pd.concat([r["forecast"].assign(MODEL=r["model"]) for r in results], ignore_index=True) if results else \
        pd.DataFrame(columns=["WEEK_END_DATE", "MEAN", "LO80", "HI80", "LO95", "HI95", "MODEL"])
    # each forecast starts from the last observed week, so the dashed line joins the history
    last = hist.iloc[[-1]]
    joins = pd.DataFrame([{"WEEK_END_DATE": last.WEEK_END_DATE.iloc[0], "MEAN": last.VALUE.iloc[0], "MODEL": r["model"]}
                          for r in results])
    lines_df = pd.concat([fc[["WEEK_END_DATE", "MEAN", "MODEL"]], joins], ignore_index=True)
    names = ["History"] + [r["model"] for r in results]
    color = alt.Color("MODEL:N", scale=alt.Scale(domain=names, range=[MODEL_STYLE[n][0] for n in names]),
                      legend=alt.Legend(orient="top", title=None))
    dash = alt.StrokeDash("MODEL:N", scale=alt.Scale(domain=names, range=[MODEL_STYLE[n][1] for n in names]), legend=None)
    pick = alt.selection_point(fields=["MODEL"], bind="legend")
    x = alt.X("WEEK_END_DATE:T", title=None)
    shown = alt.condition(pick, alt.value(1), alt.value(0.12))
    band = alt.Chart(fc).mark_area(opacity=0.45, color=PALE).encode(
        x=x, y=alt.Y("LO80:Q", title=value_title, scale=alt.Scale(zero=zero)), y2="HI80:Q",
        tooltip=[alt.Tooltip("MODEL:N", title="Model"), alt.Tooltip("WEEK_END_DATE:T", title="Week ending"),
                 alt.Tooltip("LO80:Q", title="80% low", format=fmt), alt.Tooltip("HI80:Q", title="80% high", format=fmt),
                 alt.Tooltip("LO95:Q", title="95% low", format=fmt), alt.Tooltip("HI95:Q", title="95% high", format=fmt)]
    ).transform_filter(pick)
    h_line = alt.Chart(hist).mark_line(strokeWidth=2.2).encode(x=x, y=alt.Y("VALUE:Q", title=value_title,
                                                                             scale=alt.Scale(zero=zero)), color=color,
                                                               opacity=shown)
    f_line = alt.Chart(lines_df).mark_line(strokeWidth=2).encode(x=x, y="MEAN:Q", color=color, strokeDash=dash,
                                                                 opacity=shown)
    hover = alt.selection_point(fields=["WEEK_END_DATE"], nearest=True, on="pointerover", empty=False)
    all_pts = pd.concat([hist.rename(columns={"VALUE": "Y"}), fc.rename(columns={"MEAN": "Y"})[["WEEK_END_DATE", "Y", "MODEL"]]],
                        ignore_index=True)
    pts = alt.Chart(all_pts).mark_point(filled=True, size=40).encode(
        x=x, y="Y:Q", color=color, opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("WEEK_END_DATE:T", title="Week ending"), alt.Tooltip("MODEL:N", title="Series"),
                 alt.Tooltip("Y:Q", title=value_title, format=fmt)]).add_params(hover)
    rule = alt.Chart(all_pts).mark_rule(color=SLATE, strokeDash=[2, 2], opacity=0.6).encode(x=x).transform_filter(hover)
    cut = alt.Chart(last).mark_rule(color=GOLD, strokeDash=[2, 2], strokeWidth=1.5).encode(x=x)
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    return _theme((band + h_line.add_params(zoom) + f_line + cut + rule + pts).add_params(pick)
                  .properties(height=320, width="container"))


def decomposition_chart(decomp: pd.DataFrame) -> alt.VConcatChart:
    """STL parts stacked: observed and trend, seasonal, residual (each with its own scale), shared week axis."""
    x = alt.X("WEEK_END_DATE:T", title=None)
    base = alt.Chart(decomp).properties(height=110, width="container")
    obs = base.mark_line(color=SEA, strokeWidth=1.6).encode(
        x=x, y=alt.Y("OBSERVED:Q", title="Observed", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("WEEK_END_DATE:T"), alt.Tooltip("OBSERVED:Q", format=",.3f")]
    ).add_params(alt.selection_interval(bind="scales", encodings=["x"]))   # zooms all three panels (shared x)
    trend = base.mark_line(color=TEAL, strokeWidth=2.2).encode(x=x, y="TREND:Q",
                                                               tooltip=[alt.Tooltip("TREND:Q", title="Trend", format=",.3f")])
    seas = base.mark_line(color=SLATE, strokeWidth=1.8).encode(x=x, y=alt.Y("SEASONAL:Q", title="Seasonal"),
                                                               tooltip=[alt.Tooltip("WEEK_END_DATE:T"), alt.Tooltip("SEASONAL:Q", format=",.3f")])
    resid = base.mark_bar(color=SLATE, opacity=0.7).encode(x=x, y=alt.Y("RESID:Q", title="Residual"),
                                                              tooltip=[alt.Tooltip("WEEK_END_DATE:T"), alt.Tooltip("RESID:Q", format=",.3f")])
    return _theme(alt.vconcat((obs + trend).properties(title="Observed and trend"), seas, resid, spacing=10)
                  .resolve_scale(x="shared"))


def change_histogram(wow: pd.DataFrame, title: str) -> alt.LayerChart:
    """Distribution of week-on-week changes with a zero rule."""
    bars = alt.Chart(wow).mark_bar(color=SEA, cornerRadiusEnd=2).encode(
        x=alt.X("CHANGE:Q", bin=alt.Bin(maxbins=20), title=title), y=alt.Y("count()", title="Weeks"),
        tooltip=[alt.Tooltip("count()", title="Weeks"), alt.Tooltip("CHANGE:Q", bin=alt.Bin(maxbins=20), title="Change")])
    zero = alt.Chart(pd.DataFrame({"x": [0.0]})).mark_rule(color=DEEP, strokeDash=[3, 3]).encode(x="x:Q")
    return _theme((bars + zero).properties(height=200, width="container"))


def region_tile_map(df: pd.DataFrame, measure: str, measure_title: str, fmt: str, diverging: bool,
                    picked: list[str] | None = None) -> alt.LayerChart:
    """One tile per region in a compass layout. Colour shows the measure; hover lists retailer, sales, share, change,
    SKUs and stores. Regions in `picked` stay at full strength and the others dim; the page picks regions with buttons
    above the map, because Streamlit does not support selections on layered charts."""
    d = df.copy()
    d["COL"] = [REGION_TILES.get(r, (3, 1))[0] for r in d.REGION]
    d["ROW"] = [REGION_TILES.get(r, (3, 1))[1] for r in d.REGION]
    d["FOCUS"] = [not picked or r in picked for r in d.REGION]
    scale, d["DARK"] = _cell_scale(d[measure], diverging)
    x = alt.X("COL:O", axis=None, scale=alt.Scale(domain=[0, 1, 2]))
    y = alt.Y("ROW:O", axis=None, scale=alt.Scale(domain=[0, 1, 2]))
    ink = alt.condition("datum.DARK", alt.value(WHITE), alt.value(DEEP))
    tip = [alt.Tooltip("REGION:N", title="Region"), alt.Tooltip("RETAILER:N", title="Retailer"),
           alt.Tooltip("VALUE_SALES:Q", title="Brand value sales", format=",.0f"),
           alt.Tooltip("SHARE_PCT:Q", title="Value share %", format=".2f"),
           alt.Tooltip("SHARE_CHG_PTS:Q", title="Share change, pts", format="+.2f"),
           alt.Tooltip("SALES_CHG_PCT:Q", title="Sales change %", format="+.1f"),
           alt.Tooltip("SKUS_SELLING:Q", title="SKUs selling"), alt.Tooltip("STORES_SELLING:Q", title="Stores selling"),
           alt.Tooltip("BRANDS:Q", title="Brands in category")]
    tiles = alt.Chart(d).mark_rect(cornerRadius=10, stroke=WHITE, strokeWidth=4).encode(
        x=x, y=y, color=alt.Color(f"{measure}:Q", scale=scale, legend=alt.Legend(title=measure_title, orient="bottom")),
        opacity=alt.condition("datum.FOCUS", alt.value(1), alt.value(0.35)), tooltip=tip)
    name = alt.Chart(d).mark_text(dy=-12, fontSize=14, fontWeight=600).encode(x=x, y=y, text="REGION:N", color=ink,
                                                                               tooltip=tip)
    val = alt.Chart(d).mark_text(dy=10, fontSize=13).encode(
        x=x, y=y, text=alt.Text(f"{measure}:Q", format=fmt), color=ink, tooltip=tip)
    return _theme((tiles + name + val).properties(height=330, width="container"))


def heatmap_retailer_sku(df: pd.DataFrame, measure: str, measure_title: str, fmt: str, diverging: bool) -> alt.LayerChart:
    """Retailer x SKU cells coloured by the measure, with the value printed in each cell and full details on hover."""
    df = df.copy()
    scale, df["DARK"] = _cell_scale(df[measure], diverging)
    base = alt.Chart(df).encode(x=alt.X("ITEM_DESC:N", title=None, axis=alt.Axis(labelAngle=-30, labelLimit=180)),
                                y=alt.Y("RETAILER:N", title=None))
    tip = [alt.Tooltip("RETAILER:N", title="Retailer"), alt.Tooltip("ITEM_DESC:N", title="SKU"),
           alt.Tooltip("SEGMENT:N", title="Segment"), alt.Tooltip("PACK_SIZE:N", title="Pack"),
           alt.Tooltip("VALUE_SALES:Q", title="Value sales, last 4 weeks", format=",.0f"),
           alt.Tooltip("VALUE_SALES_BEFORE:Q", title="Value sales, 4 weeks before", format=",.0f"),
           alt.Tooltip("SALES_CHG_PCT:Q", title="Change %", format="+.1f"),
           alt.Tooltip("ACV_DIST_PCT:Q", title="ACV distribution %", format=".1f")]
    cells = base.mark_rect(cornerRadius=3, stroke=WHITE, strokeWidth=2).encode(
        color=alt.Color(f"{measure}:Q", scale=scale, legend=alt.Legend(title=measure_title, orient="bottom")), tooltip=tip)
    text = base.mark_text(fontSize=11, fontWeight=500).encode(
        text=alt.Text(f"{measure}:Q", format=fmt),
        color=alt.condition("datum.DARK", alt.value(WHITE), alt.value(DEEP)), tooltip=tip)
    rows = max(df.RETAILER.nunique(), 1)
    return _theme((cells + text).properties(height=46 * rows + 70, width="container"))


def heatmap_week_brand(df: pd.DataFrame, focus: str | None = None) -> alt.Chart:
    """Week x brand cells coloured by value share; the focus brand's label is bold. Hover shows the exact share."""
    order = list(df.groupby("BRAND").VALUE_SHARE_PCT.mean().sort_values(ascending=False).index)
    return _theme(alt.Chart(df).mark_rect(stroke=WHITE, strokeWidth=1).encode(
        x=alt.X("WEEK_END_DATE:O", title=None, timeUnit="yearmonthdate",
                axis=alt.Axis(format="%d %b", labelAngle=-45, labelOverlap=True)),
        y=alt.Y("BRAND:N", sort=order, title=None,
                axis=alt.Axis(labelFontWeight=alt.ExprRef(f"datum.value == '{focus}' ? 700 : 400") if focus else 400)),
        color=alt.Color("VALUE_SHARE_PCT:Q", scale=alt.Scale(range=SEQ, interpolate="rgb"), legend=alt.Legend(title="Value share %", orient="bottom")),
        tooltip=[alt.Tooltip("BRAND:N", title="Brand"), alt.Tooltip("MANUFACTURER:N", title="Manufacturer"),
                 alt.Tooltip("WEEK_END_DATE:T", title="Week ending"),
                 alt.Tooltip("VALUE_SHARE_PCT:Q", title="Value share %", format=".2f")],
    ).properties(height=24 * max(df.BRAND.nunique(), 1) + 130, width="container"))   # + angled dates and legend


def sku_bars(df: pd.DataFrame) -> alt.LayerChart:
    """SKUs by sales change % across the selected retailers, gains and losses in the Radar polarity, signed labels."""
    d = df.copy()
    d["kind"] = ["gain" if v >= 0 else "loss" for v in d.SALES_CHG_PCT]
    color, stroke = _polarity(["gain", "loss"])
    tip = [alt.Tooltip("ITEM_DESC:N", title="SKU"), alt.Tooltip("SALES_CHG_PCT:Q", title="Change %", format="+.1f"),
           alt.Tooltip("VALUE_SALES:Q", title="Value sales, last 4 weeks", format=",.0f"),
           alt.Tooltip("VALUE_SALES_BEFORE:Q", title="4 weeks before", format=",.0f")]
    return _theme(_signed_bars(d, "ITEM_DESC", "SALES_CHG_PCT", color, tip, "-x", "Value sales change, %", stroke))


# ---- Insight Studio: interactive Plotly charts (SR-065) ----------------------------------------------------------
# Plotly adds what Altair cannot: box and lasso selection that the page reads back, and freehand drawing (lines,
# open paths, rectangles, circles, eraser) on any chart from the toolbar. Same palette and type as the Altair charts.
# Plotly is imported inside each builder, so pages that never open the studio never load it.

CAT = [TEAL, GOLD, TERRA, SLATE, SEA, DEEP]                       # categorical series, in this order
PLOTLY_CONFIG = {"displaylogo": False, "scrollZoom": True,
                 "modeBarButtonsToAdd": ["drawline", "drawopenpath", "drawrect", "drawcircle", "eraseshape"],
                 "toImageButtonOptions": {"format": "png", "scale": 2, "filename": "chippy_chart"}}


def _pl(fig, height: int = 380, title: str | None = None, legend: bool = True):
    """The house style for a Plotly figure: Inter, deep-teal ink, sea-glass grid, transparent background, drawn shapes in
    gold, and the legend on top."""
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=40 if title else 16, b=8), title=dict(text=title or ""),
                      font=dict(family=FONT, size=12, color=DEEP), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(font_family=FONT, bgcolor=WHITE),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title=None) if legend else None,
                      showlegend=legend, dragmode="zoom",
                      newshape=dict(line=dict(color=GOLD, width=3), fillcolor="rgba(198,168,121,0.18)"))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=SEA, linecolor=SEA)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=SEA, linecolor=SEA)
    return fig


def pl_explore(df: pd.DataFrame, kind: str, x: str, y: str, color: str | None, y_title: str, height: int = 420):
    """Workbench chart from an aggregated frame (x, y, optional colour, ROW_ID). Every mark carries its ROW_ID in
    customdata, so a box or lasso selection maps back to rows. kind: Line, Bar, Area, Scatter, Box, Heatmap."""
    import plotly.graph_objects as go
    fig = go.Figure()
    groups = [(None, df)] if not color else list(df.groupby(color, sort=False))
    if kind == "Heatmap" and color:
        z = df.pivot_table(index=color, columns=x, values=y, aggfunc="sum")
        fig.add_trace(go.Heatmap(z=z.values, x=[str(c) for c in z.columns], y=[str(i) for i in z.index],
                                 colorscale=[[0, MIST], [0.35, PALE], [0.6, SEA], [0.85, TEAL], [1, DEEP]],
                                 colorbar=dict(title=y_title), hovertemplate=f"%{{y}} · %{{x}}<br>{y_title}: %{{z:,.2f}}<extra></extra>"))
        return _pl(fig, height, legend=False)
    for i, (name, g) in enumerate(groups):
        c = CAT[i % len(CAT)]
        label = str(name) if name is not None else y_title
        common = dict(name=label, customdata=g["ROW_ID"], legendgroup=label)
        hover = f"{label}<br>%{{x}}<br>{y_title}: %{{y:,.2f}}<extra></extra>"
        if kind == "Bar":
            fig.add_trace(go.Bar(x=g[x], y=g[y], marker_color=c, hovertemplate=hover, **common))
        elif kind == "Box":
            fig.add_trace(go.Box(x=g[x] if x != y else None, y=g[y], marker_color=c, boxpoints="outliers", **common))
        elif kind == "Scatter":
            fig.add_trace(go.Scatter(x=g[x], y=g[y], mode="markers", marker=dict(color=c, size=8, opacity=0.75,
                                     line=dict(color=WHITE, width=0.5)), hovertemplate=hover, **common))
        else:
            fig.add_trace(go.Scatter(x=g[x], y=g[y], mode="lines+markers", marker=dict(size=4), line=dict(color=c, width=2,
                                     dash=["solid", "dash", "dot", "dashdot"][(i // len(CAT)) % 4]),
                                     fill="tozeroy" if kind == "Area" else None, hovertemplate=hover, **common))
    if kind == "Bar":
        fig.update_layout(barmode="group")
    fig.update_yaxes(title=y_title)
    return _pl(fig, height, legend=bool(color))


def pl_causal(frame: pd.DataFrame, start, y_title: str):
    """Actual (solid teal) against the counterfactual (dashed slate) with its prediction band; the shaded gap after
    the change is the estimated effect; a gold line marks the change."""
    import plotly.graph_objects as go
    f = frame
    post = f[f.POST]
    fig = go.Figure([
        go.Scatter(x=f.WEEK_END_DATE, y=f.HI, line=dict(width=0), showlegend=False, hoverinfo="skip"),
        go.Scatter(x=f.WEEK_END_DATE, y=f.LO, fill="tonexty", fillcolor="rgba(166,193,189,0.30)", line=dict(width=0),
                   name="90% band without the shift", hoverinfo="skip"),
        go.Scatter(x=f.WEEK_END_DATE, y=f.PREDICTED, line=dict(color=SLATE, dash="dash", width=2), name="Without the shift (model)",
                   hovertemplate="%{x|%d %b %Y}<br>Model: %{y:,.0f}<extra></extra>"),
        go.Scatter(x=f.WEEK_END_DATE, y=f.ACTUAL, line=dict(color=TEAL, width=2.4), name="Actual",
                   hovertemplate="%{x|%d %b %Y}<br>Actual: %{y:,.0f}<extra></extra>"),
        go.Bar(x=post.WEEK_END_DATE, y=post.ACTUAL - post.PREDICTED, name="Weekly effect", yaxis="y2",
               marker_color=[TERRA if v < 0 else TEAL for v in post.ACTUAL - post.PREDICTED], opacity=0.35,
               hovertemplate="%{x|%d %b %Y}<br>Effect: %{y:+,.0f}<extra></extra>"),
    ])
    fig.add_vline(x=pd.Timestamp(start), line=dict(color=GOLD, dash="dot", width=2))
    gap = (post.ACTUAL - post.PREDICTED)
    m = float(max(gap.abs().max(), 1e-9)) if len(gap) else 1.0
    # the effect bars keep to the lower third: zero sits a third of the way up, so they do not cover the lines
    rng = [-1.1 * m, 2.2 * m] if (gap <= 0).all() else ([-2.2 * m, 1.1 * m] if (gap >= 0).all() else [-1.6 * m, 1.6 * m])
    fig.update_layout(yaxis=dict(title=y_title), yaxis2=dict(overlaying="y", side="right", showgrid=False,
                      title="Weekly effect", zeroline=True, range=rng))
    return _pl(fig, 400)


def pl_change_point(series: pd.Series, cp: dict, y_title: str):
    """The weekly series with the two fitted levels and the change week."""
    import plotly.graph_objects as go
    fig = go.Figure([go.Scatter(x=series.index, y=series.values, mode="lines+markers", marker=dict(size=4),
                                line=dict(color=TEAL, width=2), name=y_title,
                                hovertemplate="%{x|%d %b %Y}<br>%{y:,.2f}<extra></extra>")])
    for (a, b, m), c in zip(cp["segments"], (SLATE, TERRA if cp["delta"] < 0 else TEAL)):
        fig.add_trace(go.Scatter(x=[a, b], y=[m, m], mode="lines", line=dict(color=c, width=3, dash="dash"),
                                 name=f"Level {m:,.2f}", hoverinfo="skip"))
    fig.add_vline(x=cp["week"], line=dict(color=GOLD, dash="dot", width=2))
    fig.update_yaxes(title=y_title)
    return _pl(fig, 340)


def pl_bars_h(df: pd.DataFrame, label: str, value: str, title: str, err: str | None = None, signed: bool = False,
              fmt: str = ",.3f", height: int | None = None):
    """Horizontal bars, largest on top, optional error bars; signed bars are teal for gains and terracotta for losses."""
    import plotly.graph_objects as go
    d = df.iloc[::-1]
    colors = [TERRA if v < 0 else TEAL for v in d[value]] if signed else TEAL
    fig = go.Figure(go.Bar(y=d[label], x=d[value], orientation="h", marker_color=colors,
                           error_x=dict(type="data", array=d[err], color=SLATE) if err else None,
                           text=None if err else [format(v, ("+" + fmt) if signed else fmt) for v in d[value]],
                           textposition="outside", cliponaxis=False,
                           hovertemplate=f"%{{y}}<br>{title}: %{{x:{fmt}}}<extra></extra>"))
    fig.update_xaxes(title=title, zeroline=True)
    return _pl(fig, height or max(180, 44 * len(d) + 60), legend=False)


def pl_curves(curves: dict[str, pd.DataFrame], labels: dict[str, str], y_title: str):
    """Partial dependence: one small panel per driver, the model's average prediction as that driver moves."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    names = list(curves)
    fig = make_subplots(rows=1, cols=max(1, len(names)), subplot_titles=[labels.get(n, n) for n in names],
                        shared_yaxes=True)
    for i, n in enumerate(names, 1):
        c = curves[n]
        fig.add_trace(go.Scatter(x=c.X, y=c.Y, mode="lines", line=dict(color=CAT[i - 1], width=2.5), name=labels.get(n, n),
                                 hovertemplate=f"{labels.get(n, n)}: %{{x:,.2f}}<br>{y_title}: %{{y:,.2f}}<extra></extra>"),
                      row=1, col=i)
    fig.update_yaxes(title=y_title, row=1, col=1)
    return _pl(fig, 300, legend=False)


def pl_segments(points: pd.DataFrame, x: str, y: str, x_title: str, y_title: str):
    """Brand x retailer positions coloured by k-means segment, sized by sales; hover names the brand and retailer."""
    import plotly.graph_objects as go
    fig = go.Figure()
    size = 10 + 30 * (points.SALES / points.SALES.max()).fillna(0) ** 0.5
    for i, (seg, g) in enumerate(points.groupby("SEGMENT")):
        fig.add_trace(go.Scatter(x=g[x], y=g[y], mode="markers", name=seg,
                                 marker=dict(size=size[g.index], color=CAT[i % len(CAT)], opacity=0.8,
                                             line=dict(color=WHITE, width=1)),
                                 customdata=g[["BRAND", "RETAILER"]],
                                 hovertemplate="%{customdata[0]} at %{customdata[1]}<br>" + f"{x_title}: %{{x:,.2f}}<br>"
                                               f"{y_title}: %{{y:,.2f}}<extra>{seg}</extra>"))
    fig.add_hline(y=0, line=dict(color=SEA, width=1))
    fig.update_xaxes(title=x_title)
    fig.update_yaxes(title=y_title)
    return _pl(fig, 420)


def pl_heat(matrix: pd.DataFrame, title: str, diverging: bool = True, fmt: str = "+.2f", height: int | None = None):
    """A labelled heatmap; diverging matrices are centred on zero (terracotta below, teal above)."""
    import plotly.graph_objects as go
    z = matrix.values.astype(float)
    m = float(np.nanmax(np.abs(z))) if z.size else 1.0
    scale = [[0, TERRA], [0.5, MIST], [1, TEAL]] if diverging else [[0, MIST], [0.5, SEA], [1, DEEP]]
    fig = go.Figure(go.Heatmap(z=z, x=[str(c) for c in matrix.columns], y=[str(i) for i in matrix.index],
                               colorscale=scale, zmin=-m if diverging else None, zmax=m if diverging else None,
                               text=[[format(v, fmt) if v == v else "" for v in row] for row in z],
                               texttemplate="%{text}", colorbar=dict(title=title),
                               hovertemplate="%{y} · %{x}<br>" + title + ": %{z:" + fmt + "}<extra></extra>"))
    return _pl(fig, height or max(260, 46 * len(matrix) + 80), legend=False)


def pl_pareto(df: pd.DataFrame, title: str, money: str = ""):
    """Loss by item (bars, losses first) with the running share of the total loss (line, right axis)."""
    import plotly.graph_objects as go
    fig = go.Figure([
        go.Bar(x=df.ITEM, y=df.CHANGE, marker_color=[TERRA if v < 0 else TEAL for v in df.CHANGE], name="Change in value sales",
               hovertemplate="%{x}<br>Change: %{y:+,.0f}" + (f" {money}" if money else "") + "<extra></extra>"),
        go.Scatter(x=df.ITEM, y=100 * df.CUM_SHARE_OF_LOSS, yaxis="y2", mode="lines+markers", line=dict(color=GOLD, width=2.5),
                   name="Running share of the loss, %", hovertemplate="%{x}<br>%{y:.0f}% of the loss so far<extra></extra>"),
    ])
    fig.add_hline(y=80, line=dict(color=GOLD, dash="dot", width=1), yref="y2")
    fig.update_layout(yaxis=dict(title=title), yaxis2=dict(overlaying="y", side="right", range=[0, 105], showgrid=False,
                                                           title="% of loss"))
    return _pl(fig, 340)


def pl_risk(shifts: pd.DataFrame, names: dict, money: str = "", focus: str | None = None, high: float = 0.8):
    """The director's risk matrix: each shift in the run at its confidence (x) and value at stake (y), sized by the share
    move, teal for gains and terracotta for losses, the focus shift outlined in gold. The "Act now" line sits at
    `high`, the confidence where format.confidence starts saying High. Not selectable (B21); the page offers a picker."""
    import plotly.graph_objects as go
    d = shifts.assign(ABS=shifts.VALUE_AT_STAKE.abs(), MOVE=shifts.D_SHARE_PTS.abs())
    fig = go.Figure(go.Scatter(
        x=d.CONFIDENCE, y=d.ABS, mode="markers+text", text=[names.get(s, s) for s in d.SHIFT_ID], textposition="top center",
        customdata=d.SHIFT_ID, marker=dict(size=18 + 28 * (d.MOVE / max(d.MOVE.max(), 1e-9)),
                                           color=[TERRA if v < 0 else TEAL for v in d.D_SHARE_PTS], opacity=0.8,
                                           line=dict(color=[GOLD if s == focus else WHITE for s in d.SHIFT_ID],
                                                     width=[4 if s == focus else 1 for s in d.SHIFT_ID])),
        hovertemplate="%{text}<br>Confidence %{x:.2f}<br>Value at stake %{y:,.0f}" + (f" {money}" if money else "")
                      + "<extra></extra>"))
    fig.add_vline(x=high, line=dict(color=SEA, dash="dot"))
    fig.add_annotation(x=1.0, y=1.0, xref="paper", yref="paper", text="Act now", showarrow=False, font=dict(color=TERRA))
    fig.add_annotation(x=0.0, y=1.0, xref="paper", yref="paper", text="Verify first", showarrow=False, font=dict(color=SLATE),
                       xanchor="left")
    fig.update_xaxes(title="Confidence (stored)", range=[0, 1.1])
    fig.update_yaxes(title="Value at stake" + (f" ({money})" if money else ""), range=[0, 1.22 * float(d.ABS.max() or 1)])
    return _pl(fig, 420, legend=False)
