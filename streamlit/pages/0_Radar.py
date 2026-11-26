"""Radar (home, L11): Chippy's weekly intelligence, this week at a glance, market movement, what needs attention, the
detected shifts with their actions, the Signal Journey and all candidates; the weekly-run panel in the admin app."""
from __future__ import annotations

import logging
import time
from base64 import b64encode
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from sr_ui import charts, data, format as fmt, market_view, nav, studio, workspace
nav.entry_guard("pages/0_Radar.py")   # a refresh or direct link still opens inside the app

N_STEPS = 14
ROW_H = 26                     # table row height in px: room to read, still dense
MOVE_MAX = 10                  # bars in the market movement overview


def replay_panel() -> None:
    busy = data.active_run() is not None or st.session_state.awaiting is not None
    with st.expander("Manage weekly run" + (" · run in progress" if busy else ""), expanded=busy,
                     icon=":material/tune:"), st.container(key="sr_toolbar"):
        info, actions = st.columns([2, 3], vertical_alignment="center")
        with info:
            nav.label("Replay controls")
            st.markdown(f'<div class="sr-toolbar-line">Data as of <b>{nav.nice_date(data.cfg("AS_OF_WEEK_END"))}</b> '
                        + (nav.badge("Run in progress", "accent") if busy else nav.badge("Ready", "ok")) + "</div>",
                        unsafe_allow_html=True)
        with actions:
            row = st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small")
            try:
                with row.container(key="sr_btn_next", width=172):
                    if st.button("Load next week", disabled=busy, type="primary", icon=":material/skip_next:"):
                        st.session_state.awaiting = {"kind": "REPLAY", "since": data.start_task("T_REPLAY_NEXT"),
                                                     "t0": time.monotonic()}
                        st.rerun()
                with row.container(key="sr_btn_rerun", width=172):
                    if st.button("Rerun this week", disabled=busy, icon=":material/replay:"):
                        st.session_state.awaiting = {"kind": "RERUN", "since": data.start_task("T_RUN_WEEK_MANUAL"),
                                                     "t0": time.monotonic()}
                        st.rerun()
            except data.Busy:
                st.warning("A run is in progress; wait for it to finish.")
            with row.container(key="sr_btn_reset", width=172):
                with st.popover("Reset to week…", disabled=busy, icon=":material/restart_alt:"):
                    week = st.date_input("Week ending")
                    if st.button("Reset"):
                        st.toast(data.reset_replay(week))
                        data.clear_cache()
                        st.rerun()
        if busy or st.session_state.awaiting:
            progress_panel()


@st.fragment(run_every="5s")
def progress_panel() -> None:
    a = st.session_state.awaiting
    run = data.run_started_since(a["since"]) if a else data.active_run()
    if run is None:
        task = data.task_last_run("T_REPLAY_NEXT" if a and a["kind"] == "REPLAY" else "T_RUN_WEEK_MANUAL")
        if task and task.get("STATE") == "FAILED":
            st.error(task.get("ERROR_MESSAGE") or "The task failed")
            st.session_state.awaiting = None
        elif a and time.monotonic() - a["t0"] > 900:
            st.warning("No run started within 15 minutes; check the task history (Data & Trust page).")
            st.session_state.awaiting = None
        else:
            nav.mascot("loading", "Gathering my acorns… 🐿️", "Loading the new week; the run starts when the stream sees it.",
                       key="loading_wait")
        if st.button("Refresh", key="refresh_progress", icon=":material/refresh:"):
            st.rerun()
        return
    steps = data.step_log(run.run_id)
    done = steps.STEP_NO.nunique() if len(steps) else 0
    if run.status == "RUNNING":
        nav.mascot("loading", "Gathering my acorns… 🐿️", "The weekly run is in progress.", key="loading_run")
    st.progress(min(1.0, done / N_STEPS), text=f"{fmt.RUN_CHIP.get(run.status, run.status)} · "
                                               f"{steps.STEP.iloc[-1] if done else 'OPEN'}")
    if len(steps):
        st.dataframe(steps[["STEP", "STATUS", "SECONDS", "ROWS_WRITTEN", "MESSAGE"]], hide_index=True,
                     row_height=ROW_H, column_config={"STEP": "Step", "STATUS": "Status", "SECONDS": "Seconds",
                                                      "ROWS_WRITTEN": "Rows written", "MESSAGE": "Message"})
    if run.status != "RUNNING":
        if run.status == "SKIPPED":
            st.caption(f"Run skipped: {run.error_msg}")
        elif run.status == "SUCCEEDED":
            nav.cheer()
        st.session_state.awaiting = None
        data.clear_cache()
        st.rerun()                                  # whole app


def banners() -> None:
    attempt = data.latest_attempt()
    if attempt is None:
        return
    if attempt.status == "FAILED":
        msg = attempt.error_msg or ""
        if msg.startswith("CAPABILITY") and "NO_DATA" in msg:
            st.error("This week's data has not arrived. The last good brief stays on screen.", icon=":material/error:")
        else:
            st.error(f"The latest run failed at {msg.split(':')[0] or 'a step'}. The last good brief stays on screen.",
                     icon=":material/error:")
        if nav.is_admin():
            st.caption(msg[:2000])
    elif attempt.status == "SKIPPED" and nav.is_admin():
        st.caption(f"Latest run skipped: {attempt.error_msg}")


def _open_shift(sid: str, checks: bool = False) -> None:
    st.session_state.shift_id = sid
    st.session_state.sr_open_checks = checks
    st.switch_page("pages/1_Shift_detail.py")


# ---- 2. Chippy Weekly Intelligence (hero) --------------------------------------------------------------------------

def radar_header(run: data.Run | None) -> None:
    with st.container(key="sr_radar_header"):
        title, controls = st.columns([2, 3], vertical_alignment="center")
        title.html('<div class="sr-radar-title"><h1>Radar</h1>'
                   '<p>This week\'s material share shifts, explained and checked</p></div>')
        with controls.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            if run and run.as_of_week:
                current_week = str(pd.Timestamp(run.as_of_week).date())
                history = data.run_history()
                weeks = [] if history.empty else [str(pd.Timestamp(w).date()) for w in history.AS_OF_WEEK]
                week = st.selectbox("Week ending", [current_week, *[w for w in weeks if w != current_week]],
                                    format_func=lambda w: f"Week ending {nav.nice_date(w)}",
                                    label_visibility="collapsed", width=222, key="sr_radar_week")
                if week and week != current_week:
                    st.session_state.sr_tm_week = week
                    st.switch_page("pages/8_Market_Time_Machine.py")
            if nav.is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
            if st.button("Refresh", icon=":material/refresh:", key="sr_btn_header_refresh"):
                data.clear_cache()
                st.rerun()


def hero_warning(run: data.Run, markets: dict) -> str:
    try:
        warnings = data.watchlist(run.run_id)
    except Exception:
        logging.getLogger(__name__).warning("Radar hero early warning unavailable")
        return ""
    if warnings.empty:
        return ""

    # watchlist() already orders warnings by projected impact and then by driver movement.
    rows = warnings.itertuples(index=False)
    first = next(rows)
    remaining = "".join(_hero_warning_details(run, row, markets, ordinal=i) for i, row in enumerate(rows, start=2))
    more = f'<div class="sr-hero-warning-more"><b>More early warnings</b>{remaining}</div>' if remaining else ""
    return _hero_warning_details(run, first, markets, count=len(warnings), more=more)


def _hero_warning_details(run: data.Run, row, markets: dict, *, count: int | None = None,
                          ordinal: int | None = None, more: str = "") -> str:
    has_projection = pd.notna(row.PROJECTED_SHARE_PTS)
    finding = "Share impact to watch"
    if has_projection:
        finding = ("Share decline projected" if row.PROJECTED_SHARE_PTS < 0 else
                   "Share gain projected" if row.PROJECTED_SHARE_PTS > 0 else "No share change projected")
    projection = fmt.pts(row.PROJECTED_SHARE_PTS) if has_projection else "Not projected"
    horizon = "Next 4 weeks" if has_projection else "Share impact"

    brand = fmt.name(row.BRAND)
    market = markets.get(row.MARKET_ID, row.MARKET_ID)
    context = " · ".join(str(value) for value in (brand, market, row.CATEGORY) if pd.notna(value) and value)
    driver = _signal(row.SIGNAL, row.LEVER_CHG)
    note = str(row.NOTE) if pd.notna(row.NOTE) else ""
    corroboration = ""
    if pd.notna(row.ML_CONFIRMED) and row.ML_CONFIRMED:
        corroboration = "The anomaly model corroborated the warning."
    driver_levels = ""
    if pd.notna(row.LEVER_LATEST) and pd.notna(row.LEVER_L4W):
        if row.SIGNAL == "DIST_DROP":
            driver_levels = f"Distribution share {fmt.pct(row.LEVER_LATEST)} latest week vs {fmt.pct(row.LEVER_L4W)} last four weeks"
        elif row.SIGNAL == "PRICE_RISE":
            driver_levels = f"Price index {row.LEVER_LATEST:.2f} latest week vs {row.LEVER_L4W:.2f} last four weeks"
    period = f"Reporting week ending {nav.nice_date(run.as_of_week)}"
    evidence_week = f"Latest driver week ending {nav.nice_date(row.LATEST_WEEK)}"
    notes = " · ".join(line for line in (note, corroboration) if line)
    evidence = "".join(f"<p>{escape(line)}</p>" for line in (driver_levels, notes) if line)
    classes = "sr-hero-warning"
    if count is None:
        classes += " sr-hero-warning-secondary"
        label = f"{ordinal} &middot; {escape(str(brand))} &middot; {escape(str(market))}"
    else:
        label = f"Early Warning &middot; {count}"
    return (
        f'<details class="{classes}"><summary>'
        '<span class="sr-hero-warning-lead"><span class="sr-ico" aria-hidden="true">notifications</span>'
        f'<span class="sr-hero-warning-label">{label}</span><strong>{finding}</strong></span>'
        f'<span class="sr-hero-warning-driver">{escape(driver)}</span>'
        f'<span class="sr-hero-warning-result"><strong>{escape(projection)}</strong><span>{horizon}</span>'
        '<span class="sr-ico sr-hero-warning-chevron" aria-hidden="true">chevron_right</span></span>'
        '</summary><div class="sr-hero-warning-evidence">'
        f'<p><strong>{escape(context)}</strong></p>'
        f'<p><strong>{escape(period)}</strong> &middot; {escape(evidence_week)}</p>'
        f'{evidence}{more}</div></details>'
    )


def hero(run: data.Run) -> None:
    ranked = data.shifts(run.run_id)
    selected = ranked[ranked.SELECTED].sort_values("RANK_NO")
    markets = data.market_names()
    warning = hero_warning(run, markets)
    if selected.empty:
        nav.mascot("sleepy", "No shift made the brief this week.", key="summary")
        if warning:
            with nav.hero("radar"):
                st.html(warning)
        return
    top = selected.iloc[0].to_dict()
    cur = data.cfg("CURRENCY") or ""
    market = markets.get(top["MARKET_ID"], top["MARKET_ID"])
    comparison = fmt.CMP_TEXT.get(top["CMP_CODE"], top["CMP_CODE"])
    brand = fmt.name(top["BRAND"])
    verb = "losing" if top["D_SHARE_PTS"] < 0 else "gaining" if top["D_SHARE_PTS"] > 0 else "holding"
    tone = "negative" if top["D_SHARE_PTS"] < 0 else "positive" if top["D_SHARE_PTS"] > 0 else ""
    stake_tone = "negative" if top["VALUE_AT_STAKE"] < 0 else "positive" if top["VALUE_AT_STAKE"] > 0 else ""
    status = top["ARTEFACT_LABEL"]
    brief = {}
    if run.brief_id:
        try:
            brief = data.brief(run.brief_id) or {}
        except Exception:  # The investigation remains available if the brief cannot be read.
            pass
    published = brief.get("STATUS") == "PUBLISHED"
    brief_summary = (f"Week ending {nav.nice_date(run.as_of_week)}" if data.cfg("DISPLAY_ALIAS") is True
                     else brief.get("HEADLINE") or "")
    metrics = (
        ("Share", fmt.pct(top["SH1"]), "", f"Previous: {fmt.pct(top['SH0'])}"),
        ("Share movement", fmt.pts(top["D_SHARE_PTS"]), tone, ""),
        ("Value at stake", fmt.money(top["VALUE_AT_STAKE"], cur), stake_tone, ""),
        ("Confidence", fmt.confidence(top["CONFIDENCE"]), "", ""),
    )
    with nav.hero("radar"):
        avatar = nav.mascot_html("detective", "Detective Chippy", 112, html_safe=True) or ""
        status_text = fmt.LABEL_CHIP.get(status, status) or "Data status unavailable"
        numbers = "".join(                         # the previous share shows on hover of the dotted value
            f'<div><span>{escape(label)}</span><b class="{color}{" sr-has-prev" if previous else ""}"'
            + (f' title="{escape(previous)}"' if previous else "") + f'>{escape(str(value))}</b></div>'
            for label, value, color, previous in metrics)
        # The animation's pale floor is baked into its lowest pixels. Mask it at render time.
        floor_filter = '''<svg xmlns="http://www.w3.org/2000/svg">
          <filter id="sr-radar-detective-floor" x="0" y="0" width="100%" height="100%"
                  primitiveUnits="objectBoundingBox" color-interpolation-filters="sRGB">
            <feColorMatrix in="SourceGraphic" type="matrix"
              values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0"/>
            <feComponentTransfer result="pale">
              <feFuncA type="linear" slope="7" intercept="-2.9"/>
            </feComponentTransfer>
            <feFlood x="0" y=".90" width="1" height=".10" flood-color="white" result="floor"/>
            <feComposite in="pale" in2="floor" operator="in" result="artifact"/>
            <feComposite in="SourceGraphic" in2="artifact" operator="out"/>
          </filter>
        </svg>'''
        filter_uri = b64encode(floor_filter.encode("utf-8")).decode("ascii")
        st.html(f'<style>.sr-radar-hero-main .sr-chippy img {{'
                f'filter:url("data:image/svg+xml;base64,{filter_uri}#sr-radar-detective-floor");}}</style>'
                f'<div class="sr-radar-hero-main">{avatar}<div class="sr-radar-finding">'
                '<span class="sr-radar-speech sr-typing" aria-label="Pssst... I found something."><span class="sr-dots" aria-hidden="true">'
                '<i></i><i></i><i></i></span><span class="sr-type">Pssst... I found something.</span></span>'
                f'<h2>{escape(brand)} is '
                f'{verb} market share.</h2><div>{escape(str(market))} &middot; {escape(comparison)}</div></div>'
                f'<div class="sr-radar-numbers">{numbers}</div>'
                f'<span class="sr-radar-status {escape(str(status))}">{escape(str(status_text))}</span>'
                f'{warning}</div>')
        with st.container(key="sr_radar_actions", horizontal=True, vertical_alignment="center", gap="small"):
            if st.button("Investigate shift", key="sr_btn_summary", type="primary", icon=":material/arrow_forward:"):
                _open_shift(top["SHIFT_ID"], status == "MIXED")
            if published and st.button("Read brief", key="sr_btn_hero_brief", icon=":material/article:"):
                st.session_state.brief_id = run.brief_id
                st.switch_page("pages/2_Brief.py")
            watched = workspace.is_watched(workspace.row_key(top))
            if st.button("", key="sr_radar_watch", disabled=watched, icon=":material/bookmark:",
                         help="On your watchlist" if watched else "Add to Watchlist"):
                workspace.add_watch(top, run.run_id)
                st.toast("Added to your watchlist for this session.")
                st.rerun()
            if st.button("", key="sr_radar_case", icon=":material/folder_open:", help="Open Case File"):
                workspace.open_case(top, run.run_id, run.as_of_week)
                st.switch_page("pages/7_Case_Files.py")


def tiles(run: data.Run) -> None:
    k = data.kpis(run.run_id)
    cur = data.cfg("CURRENCY") or ""
    same_scope = run.scope_key == data.scope_key()
    previous = data.previous_week_run(str(run.as_of_week)) if run.as_of_week and same_scope else None
    prior = data.kpis(previous.run_id) if previous else {}
    items = (
        ("Shifts past the gates", "N_PASSED", "layers", int),
        ("Shifts in the brief", "N_SELECTED", "description", int),
        ("Possible data effects", "N_DATA_EFFECT", "shield", int),
        ("Value at stake in the brief", "VALUE_SELECTED", "database", lambda value: fmt.money(value, cur)),
    )
    with st.container(key="sr_radar_kpis"):
        for col, (label, key, icon, display) in zip(st.columns(4), items):
            value = k.get(key, 0)
            prior_value = prior.get(key)
            trend = "Higher" if prior_value is not None and value > prior_value else (
                "Lower" if prior_value is not None and value < prior_value else "No change")
            compare = ""
            if prior_value is not None:
                compare = (f'<div class="sr-kpi-prior"><span class="{trend.lower().replace(" ", "-")}">{trend}</span>'
                           f'<small title="Week ending {nav.nice_date(previous.as_of_week)}">Previous: {display(prior_value)}</small></div>')
            with col.container(border=True, key=f"sr_kpi_radar_{key}"):
                st.html(f'<div class="sr-radar-kpi"><span class="sr-ico" aria-hidden="true">{icon}</span>'
                        f'<div><span>{label}</span><b>{display(value)}</b></div>{compare}</div>')
                if key == "N_DATA_EFFECT":
                    with st.popover("Review data checks", type="tertiary", width="stretch"):
                        nav.guarded("Data checks", lambda: data_checks(run))


def radar_section(title: str, subtitle: str, icon: str) -> None:
    st.html(f'<div class="sr-radar-section"><h3><span class="sr-ico" aria-hidden="true">{icon}</span>'
            f'{escape(title)}</h3><p>{escape(subtitle)}</p></div>')


def movement(run: data.Run) -> None:
    with nav.card("movement"):
        radar_section("Market Movement Overview", "Share movement in percentage points", "bar_chart")
        df = data.shifts(run.run_id)
        df = df[df.SELECTED | (df.ARTEFACT_LABEL == "POSSIBLE_DATA_EFFECT")]
        ranked = df.sort_values(["SELECTED", "SCORE"], ascending=[False, False])
        if ranked.empty:
            st.caption("No shifts in the brief or held for checks.")
            return
        markets = data.market_names()
        df = ranked.head(MOVE_MAX)
        shares = df.D_SHARE_PTS.astype(float)
        low, high = min(0.0, shares.min()), max(0.0, shares.max())
        if len(df) > 4:
            pages = range(0, len(df), 4)
            start = st.selectbox("Market movement rows", pages, key=f"sr_movement_rows_{run.run_id}",
                                 format_func=lambda i: f"Shifts {i + 1}–{min(i + 4, len(df))} of {len(df)}",
                                 label_visibility="collapsed", width=152)
            df = df.iloc[start:start + 4]
        span = high - low or 1.0
        zero = -100 * low / span
        styles = [f".st-key-sr_move_chart [class*=st-key-sr_move_plot_] {{ --zero: {zero:.5f}%; }}"]
        with st.container(key="sr_move_chart", gap=None):
            for i, row in enumerate(df.itertuples(index=False)):
                change = float(row.D_SHARE_PTS)
                edge = 100 * (change - low) / span
                tone = "gain" if change >= 0 else "loss"
                held = not row.SELECTED
                brand, market = fmt.name(row.BRAND), markets.get(row.MARKET_ID, row.MARKET_ID)
                comparison = fmt.CMP_TEXT.get(row.CMP_CODE, row.CMP_CODE)
                status = "Held for Checks" if held else (
                    "Share Gain" if change > 0 else "Share Loss" if change < 0 else "No change"
                )
                value = fmt.pts(change)
                detail = f"{brand} / {market} / {comparison} / {value} / {status}"
                styles.append(
                    f".st-key-sr_move_bar_{i} {{ --start: {min(edge, zero):.5f}%; "
                    f"--extent: {abs(edge - zero):.5f}%; --bar-fill: {charts.GAIN if tone == 'gain' else charts.LOSS}; "
                    f"--bar-opacity: {0.4 if held else 1}; }}")
                with st.container(key=f"sr_move_row_{i}", horizontal=True, vertical_alignment="center", gap=None):
                    st.html(f'<div class="sr-move-label" title="{escape(detail)}">'
                            f'<strong>{escape(brand)}</strong>'
                            f'<span>{escape(str(market))} &middot; {escape(comparison)}</span></div>')
                    with st.container(key=f"sr_move_plot_{i}"):
                        if st.button(f"{change:+.2f}", key=f"sr_move_bar_{i}", help=detail):
                            _open_shift(row.SHIFT_ID, checks=held)
                    st.html(f'<div class="sr-move-value {("held" if held else tone)}">'
                            f'<strong>{escape(value)}</strong><span>{status}</span></div>')
            ticks = "".join(
                f'<span style="left:{100 * (value - low) / span:.5f}%">{value:.2f}</span>'
                for value in sorted({low, 0.0, high}))
            st.html(f'<div class="sr-move-axis"><div class="sr-move-ticks">{ticks}</div></div>')
            st.html('<div class="sr-radar-legend"><span class="gain">Share gain</span><span class="loss">Share loss</span>'
                    '<span class="held">Held for checks</span></div>')
            st.html("<style>" + "".join(styles) + "</style>")


# ---- 5. Market View and Data Checks ---------------------------------------------------------------------------------

def _signal(code: str, chg) -> str:
    lever = "Distribution" if code == "DIST_DROP" else "Price"
    way = "down" if chg is not None and not pd.isna(chg) and float(chg) < 0 else "up"
    return f"{lever} {way} {fmt.pct(abs(float(chg)))} vs last four weeks" if chg is not None and not pd.isna(chg) \
        else f"{lever} {way}"


def data_checks(run: data.Run) -> None:
    markets = data.market_names()
    held = data.held_back(run.run_id)
    with st.container(key="sr_radar_checks"):
        st.html('<div class="sr-radar-att-title"><span class="sr-ico" aria-hidden="true">database</span>'
                f'<b>Data Checks &middot; {len(held)}</b></div>')
        if held.empty:
            st.caption("No shifts held for checks.")
        for row in held.itertuples(index=False):
            label = f"{fmt.name(row.BRAND)} · {markets.get(row.MARKET_ID, row.MARKET_ID)}"
            rules = ", ".join(fmt.RULE_TEXT.get(rule, rule) for rule in row.RULES) or "Data rule fired"
            comparison = fmt.CMP_TEXT.get(row.CMP_CODE, row.CMP_CODE)
            detail = f"{rules} · {comparison}"
            with st.container(key=f"sr_check_row_{row.SHIFT_ID}", horizontal=True,
                              vertical_alignment="center", gap="small"):
                st.html(f'<div class="sr-att-copy"><div><strong>{escape(label)}</strong><span>{escape(detail)}</span></div>'
                        f'<div class="sr-att-value"><strong>{escape(fmt.pts(row.D_SHARE_PTS))}</strong>'
                        '<span>Held back</span></div></div>')
                if st.button("", icon=":material/chevron_right:", help="Review data checks",
                             key=f"sr_radar_held_{row.SHIFT_ID}"):
                    _open_shift(row.SHIFT_ID, True)


def _map_zoom(level: int) -> None:
    st.session_state.sr_market_zoom = level


def market_map(run: data.Run) -> None:
    with nav.card("market_view"):
        with st.container(key="sr_market_view_header", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center", gap="small"):
            st.html('<div class="sr-radar-section"><h3><span class="sr-ico" aria-hidden="true">'
                    'public</span>Market View</h3><p class="sr-market-sub">Explore market performance across geographies</p>'
                    '</div>', width="content")
            mode = st.radio("Map metric", market_view.MODES, index=1, horizontal=True,
                            label_visibility="collapsed", key="sr_market_metric", width="content")

        feature = market_view.market_feature(run)
        zoom = st.session_state.get("sr_market_zoom", 0)
        with st.container(key="sr_market_map_frame", gap=None):
            st.vega_lite_chart(spec=market_view.map_spec(feature, mode, zoom), key="sr_market_chart",
                               theme=None, width="stretch", height="stretch")
            with st.container(key="sr_market_map_tools", horizontal=True, gap=None):
                st.button("", icon=":material/add:", help="Zoom in", key="sr_market_zoom_in",
                          disabled=zoom == 3, on_click=_map_zoom, args=(zoom + 1,))
                st.button("", icon=":material/remove:", help="Zoom out", key="sr_market_zoom_out",
                          disabled=zoom == 0, on_click=_map_zoom, args=(zoom - 1,))
                st.button("", icon=":material/restart_alt:", help="Reset map", key="sr_market_zoom_reset",
                          disabled=zoom == 0, on_click=_map_zoom, args=(0,))

        if mode == "Movement":
            keys = [("Loss", charts.LOSS), ("No change", market_view.MINT), ("Gain", charts.GAIN)]
        elif mode == "Share":
            keys = [("Lower to higher share", f"linear-gradient(90deg,{market_view.SHARE_LOW},{charts.GAIN})")]
        else:
            keys = [("Negative to positive value", f"linear-gradient(90deg,{charts.LOSS},{market_view.MINT},{charts.GAIN})")]
        keys += [("Unavailable", market_view.UNAVAILABLE), ("Early warning", "transparent")]
        legend = "".join(f'<span><i style="--market-swatch:{color}"></i>{label}</span>' for label, color in keys)
        st.html(f'<div class="sr-market-legend">{legend}</div>')


def _clear_filters() -> None:
    st.session_state.radar_markets, st.session_state.radar_brands, st.session_state.radar_dir = [], [], "All"


def filters(run: data.Run) -> None:
    """Market, brand and direction filters for this table and All candidates; empty means all."""
    df = data.shifts(run.run_id)
    markets = data.market_names()
    with st.container(key="sr_filterbar"):
        active = (len(st.session_state.get("radar_markets") or []) + len(st.session_state.get("radar_brands") or [])
                  + (st.session_state.get("radar_dir") not in (None, "All")))
        row = st.container(horizontal=True, vertical_alignment="center", gap="small")
        row.multiselect("Market", sorted(df.MARKET_ID.dropna().unique()), key="radar_markets", width=150,
                        format_func=lambda m: markets.get(m, m), placeholder="All markets", label_visibility="collapsed")
        row.multiselect("Brand", sorted(df.BRAND.dropna().unique()), key="radar_brands", width=150, format_func=fmt.name,
                        placeholder="All brands", label_visibility="collapsed")
        if st.session_state.get("radar_dir") not in ("All", "Gains", "Losses"):
            st.session_state.radar_dir = "All"
        row.radio("Direction", ["All", "Gains", "Losses"], key="radar_dir", horizontal=True, label_visibility="collapsed",
                  width="content")
        row.button("Clear filters", icon=":material/filter_alt_off:", on_click=_clear_filters, disabled=not active,
                   key="sr_btn_clear")


def _filtered(df: pd.DataFrame) -> pd.DataFrame:
    m, b, d = st.session_state.get("radar_markets"), st.session_state.get("radar_brands"), st.session_state.get("radar_dir")
    if m:
        df = df[df.MARKET_ID.isin(m)]
    if b:
        df = df[df.BRAND.isin(b)]
    if d == "Gains":
        df = df[df.D_SHARE_PTS.astype(float) >= 0]
    elif d == "Losses":
        df = df[df.D_SHARE_PTS.astype(float) < 0]
    return df


def _view(df: pd.DataFrame) -> pd.DataFrame:
    markets, cur = data.market_names(), data.cfg("CURRENCY") or ""
    return pd.DataFrame({
        "SHIFT_ID": df.SHIFT_ID,
        "Rank": df.RANK_NO,
        "Brand": [fmt.name(b) for b in df.BRAND],
        "Market": [markets.get(m, m) for m in df.MARKET_ID],
        "Comparison": [fmt.CMP_TEXT.get(c, c) for c in df.CMP_CODE],
        "Change": [fmt.pts(v) for v in df.D_SHARE_PTS],
        "Value at stake": [fmt.money(v, cur) for v in df.VALUE_AT_STAKE],
        "Confidence": [fmt.confidence(c) for c in df.CONFIDENCE],
        "Data status": [fmt.LABEL_CHIP.get(lbl, lbl) for lbl in df.ARTEFACT_LABEL],
    })


SHIFT_COLS = {
    "SHIFT_ID": None,
    "Rank": st.column_config.NumberColumn("Rank", width=48),
    "Change": st.column_config.TextColumn("Change", width=70, help="Share change in points"),
    "Value at stake": st.column_config.TextColumn("Value at stake", width=100),
    "Confidence": st.column_config.TextColumn("Confidence", width=96),
    "Data status": st.column_config.TextColumn("Data status", help="Result of the data-artefact checks"),
}


def action_bar(row: dict, run: data.Run) -> None:
    """Actions for the selected shift: explore it, follow it, or open it as a case file (session only)."""
    markets = data.market_names()
    k = workspace.row_key(row)
    with st.container(key="sr_actionbar", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"**{escape(fmt.name(row['BRAND']))} · {escape(markets.get(row['MARKET_ID'], row['MARKET_ID']))}**",
                    width="content")
        if st.button("Investigate", key="sr_act_explore", type="primary", icon=":material/arrow_forward:"):
            _open_shift(row["SHIFT_ID"], row["ARTEFACT_LABEL"] == "MIXED")
        if workspace.is_watched(k):
            st.button("On your watchlist", key="sr_act_watch", icon=":material/star:", disabled=True)
        elif st.button("Add to Watchlist", key="sr_act_watch", icon=":material/star_outline:"):
            workspace.add_watch(row, run.run_id)
            st.toast("Added to your watchlist for this session.", icon=":material/star:")
            st.rerun()
        if st.button("Open Case File", key="sr_act_case", icon=":material/folder_open:"):
            workspace.open_case(row, run.run_id, run.as_of_week)
            st.switch_page("pages/7_Case_Files.py")


def detected_shifts(run: data.Run) -> None:
    with nav.card("shifts"):
        radar_section("Detected Market Shifts", "Ranked shifts in this week's brief. Select a row for its actions.", "bar_chart")
        nav.guarded("Filters", lambda: filters(run))
        df = _filtered(data.shifts(run.run_id))
        sel = df[df.SELECTED]
        if sel.empty:
            nav.mascot("sleepy", "Hmm, my basket is empty!",
                       "No shift in the brief matches the filters." if len(data.shifts(run.run_id)[lambda d: d.SELECTED])
                       else "No material shift passed the gates and the data checks this week.", key="empty_shifts")
            return
        view = _view(sel)
        tint = lambda v: ("color:#b0564b;font-weight:600" if str(v).lstrip()[:1] in "-−"            # noqa: E731
                          else "color:#1e5556;font-weight:600" if str(v).lstrip()[:1] == "+" or str(v)[:1].isdigit() else "")
        styled = nav.striped(view)
        styled = styled.map(tint, subset=["Change", "Value at stake"]) if hasattr(styled, "map") else styled
        event = st.dataframe(styled, on_select="rerun", selection_mode="single-row", column_config=SHIFT_COLS,
                             hide_index=True, key="radar_shifts", row_height=ROW_H, width="stretch")
        rows = event.selection.rows if event is not None and hasattr(event, "selection") else []
        if rows:
            action_bar(sel.iloc[rows[0]].to_dict(), run)
        else:
            with st.container(key="sr_actionbar", horizontal=True, vertical_alignment="center", gap="small"):
                st.html('<span class="sr-act-hint">Select a row to act on it</span>', width="content")
                st.button("Investigate", key="sr_act_explore", icon=":material/arrow_forward:", disabled=True)
                st.button("Add to Watchlist", key="sr_act_watch", icon=":material/bookmark:", disabled=True)
                st.button("Open Case File", key="sr_act_case", icon=":material/folder_open:", disabled=True)


# ---- 7. Signal Journey · 8. All candidates ------------------------------------------------------------------------

MOMENTUM = [("Shifts past the gates", "N_PASSED", "filter_alt", False), ("Shifts in the brief", "N_SELECTED", "article", False),
            ("Possible data effects", "N_DATA_EFFECT", "shield", False), ("Value at stake in the brief", "VALUE_SELECTED", "payments", True)]


def _momentum_history(run: data.Run, weeks: int) -> pd.DataFrame:
    """The stored completed runs of this scope up to the Radar's reporting week (no later runs), one per week
    (run_history keeps the latest run of each week), oldest first, with each run's stored KPI counts."""
    h = data.run_history()
    if h.empty or not run.as_of_week:
        return pd.DataFrame()
    h = h.assign(WEEK=[str(pd.Timestamp(w).date()) for w in h.AS_OF_WEEK])
    h = h[h.WEEK <= str(pd.Timestamp(run.as_of_week).date())].drop_duplicates("WEEK").sort_values("WEEK").tail(weeks)
    rows = [{"WEEK": w, "RUN_ID": rid, **data.kpis(rid)} for w, rid in zip(h.WEEK, h.RUN_ID)]
    return pd.DataFrame(rows)


def market_momentum(run: data.Run) -> None:
    with nav.card("momentum"):
        with st.container(key="sr_momentum_head", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center", gap="small"):
            st.html('<div class="sr-radar-section"><h3><span class="sr-ico" aria-hidden="true">monitoring</span>'
                    'Market Momentum</h3><p>Is market pressure building over time?</p></div>', width="content")
            n = st.radio("Weeks shown", [8, 12], horizontal=True, key="sr_momentum_weeks", width="content",
                         label_visibility="collapsed", format_func=lambda w: f"Last {w} weeks")
        if run.scope_key != data.scope_key():
            st.caption("The current run belongs to another scope, so there is no comparable run history.")
            return
        h = _momentum_history(run, int(n or 8))
        if h.empty:
            st.caption("No stored run history for this scope yet.")
            return
        cur = data.cfg("CURRENCY") or ""
        if len(h) < 3:
            st.caption(f"Only {len(h)} stored week{'' if len(h) == 1 else 's'} so far (week ending "
                       f"{nav.nice_date(h.WEEK.iloc[-1])}); the trend fills in as weekly runs are stored.")
        else:
            st.caption(f"{len(h)} stored weekly runs, {nav.nice_date(h.WEEK.iloc[0])} to {nav.nice_date(h.WEEK.iloc[-1])}. "
                       "Click a point to open that week in Market Time Machine.")
        with st.container(key="sr_momentum_grid"):
            for i, (label, key, icon, money) in enumerate(MOMENTUM):
                shown = (lambda v: fmt.money(v, cur)) if money else (lambda v: f"{int(v):,}")
                vals = [float(v or 0) for v in h[key]]
                now = vals[-1]
                if len(vals) > 1:
                    d = now - vals[-2]
                    tone = "flat" if d == 0 else "up" if d > 0 else "down"
                    delta = ("No change" if d == 0 else (("+" if d > 0 else "−") + (fmt.money(abs(d), cur) if money
                                                                                   else f"{int(abs(d)):,}")))
                    prev = f"{delta} vs {nav.nice_date(h.WEEK.iloc[-2])}"
                else:
                    tone, prev = "flat", "No earlier week stored"
                with st.container(key=f"sr_mom_{i}"):
                    st.html(f'<div class="sr-mom-head"><span class="sr-ico" aria-hidden="true">{icon}</span>'
                            f'<span class="t" title="{escape(label)}">{escape(label)}</span></div>'
                            f'<b class="sr-mom-val">{escape(shown(now))}</b>'
                            f'<div class="sr-mom-delta {tone}" title="{escape(prev)}">{escape(prev)}</div>')
                    if len(vals) < 2:
                        continue
                    frame = pd.DataFrame({"WEEK": h.WEEK, "VALUE": vals,
                                          "LABEL": [nav.nice_date(w) for w in h.WEEK], "SHOWN": [shown(v) for v in vals]})
                    event = st.altair_chart(charts.momentum_spark(frame), width="stretch", on_select="rerun",
                                            selection_mode="pt", key=f"sr_mom_chart_{i}")
                    picked = (event.selection.get("pt") if event is not None and hasattr(event, "selection") else None) or []
                    if picked and picked[0].get("WEEK"):
                        st.session_state.sr_tm_week = picked[0]["WEEK"]
                        st.switch_page("pages/8_Market_Time_Machine.py")
        if st.button("Open Market Time Machine", key="sr_momentum_tm", icon=":material/history:", type="tertiary"):
            st.switch_page("pages/8_Market_Time_Machine.py")


def all_candidates(run: data.Run) -> None:
    with st.expander("All candidates", icon=":material/table_rows:"):
        df = _filtered(data.shifts(run.run_id))
        view = _view(df).drop(columns=["SHIFT_ID"])
        view["In brief"] = ["yes" if s else "" for s in df.SELECTED]
        view["Why not"] = df.SUPPRESS_REASON.fillna("").values
        st.caption("Every candidate that passed the gates, with the reason it is not in the brief.")
        st.dataframe(nav.striped(view), hide_index=True, row_height=ROW_H, width="stretch")


st.html((Path(nav.__file__).with_name("radar.css")).read_text(encoding="utf-8"))
current = data.current_run()
with st.container(key="sr_radar_overview"):
    nav.guarded("Radar header", lambda: radar_header(current))
    nav.guarded("Status", banners)
    if current is None:
        nav.mascot("sleepy", "Hmm, my basket is empty!", "No brief yet. The first run starts when a data week lands" +
                   (" — or open Manage weekly run below and press Load next week." if nav.is_admin() else "."), key="empty_run")
    else:
        nav.guarded("Weekly intelligence", lambda: hero(current))
        nav.guarded("Tiles", lambda: tiles(current))
        with nav.stack("radar_mid"):
            left, right = st.columns([5, 4])
            with left:
                nav.guarded("Market movement", lambda: movement(current))
            with right:
                nav.guarded("Market View", lambda: market_map(current))

with st.container(key="sr_radar_detail"):
    if current is not None:
        with st.container(key="sr_stack_radar_lower", gap="small"):          # stacked, both full width
            nav.guarded("Detected Market Shifts", lambda: detected_shifts(current))
            nav.guarded("Emerging Shifts", lambda: studio.emerging_radar(current))
            nav.guarded("Market Momentum", lambda: market_momentum(current))
        nav.guarded("All candidates", lambda: all_candidates(current))
    if nav.is_admin():
        nav.guarded("Replay panel", replay_panel)
