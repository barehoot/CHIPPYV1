"""Weekly Brief: the published brief as an executive report (L11). The stored brief HTML (sr_lib.render) is split into
its parts and laid out as insight cards; every number keeps its fact span, so its source shows on hover, and the
Sources table lists the fact pack. Business impact comes from the same run's stored shift results. No brief text is
rewritten and nothing is computed beyond sums of stored values."""
from __future__ import annotations

import json
import re
from html import escape, unescape
from pathlib import Path

import pandas as pd
import streamlit as st

from sr_ui import data, format as fmt, nav
nav.entry_guard("pages/2_Brief.py")   # a refresh or direct link still opens inside the app

st.html((Path(nav.__file__).with_name("radar.css")).read_text(encoding="utf-8"))   # Radar is the visual source


def page_header() -> None:
    with st.container(key="sr_radar_header"):
        title, controls = st.columns([5, 1], vertical_alignment="center")
        title.html('<div class="sr-radar-title"><h1>Weekly Brief</h1>'
                   '<p>Executive intelligence for the week, every number traced to its source</p></div>')
        with controls.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            if nav.is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
            if st.button("Refresh", icon=":material/refresh:", key="sr_btn_header_refresh"):
                data.clear_cache()
                st.rerun()


page_header()
lst = data.briefs()
if lst.empty:
    nav.mascot("sleepy", "Hmm, my basket is empty!", "No brief has been published yet.", key="empty_brief")
    nav.stop()
ids = list(lst.BRIEF_ID)
default = ids.index(st.session_state.brief_id) if st.session_state.brief_id in ids else 0
labels = {r.BRIEF_ID: f"Week ending {nav.nice_date(r.AS_OF_WEEK)} · {pd.to_datetime(r.PUBLISHED_AT):%d %b %H:%M}"
          for r in lst.itertuples(index=False)}


def _step(delta: int) -> None:
    i = ids.index(st.session_state.brief_id) if st.session_state.brief_id in ids else 0
    st.session_state.brief_id = ids[min(max(i + delta, 0), len(ids) - 1)]


bar = st.container(key="sr_brief_bar", horizontal=True, vertical_alignment="center", gap="small")
with bar:
    bid = st.selectbox("Brief", ids, index=default, format_func=lambda i: labels[i], width=230, label_visibility="collapsed")
    with st.container(key="sr_shift_nav", horizontal=True, gap=None, width=72):       # same ‹ › style as Shift Detail
        st.button("", icon=":material/chevron_left:", key="sr_brief_prev", help="Newer brief", on_click=_step, args=(-1,),
                  disabled=ids.index(bid) == 0)
        st.button("", icon=":material/chevron_right:", key="sr_brief_next", help="Older brief", on_click=_step, args=(1,),
                  disabled=ids.index(bid) == len(ids) - 1)
st.session_state.brief_id = bid
b = data.brief(bid)
cur = data.cfg("CURRENCY") or ""
masked = data.cfg("DISPLAY_ALIAS") is True


# ---- The stored brief HTML, split into its parts (sr_lib.render.render_html layout) ---------------------------------

def _signed(html: str) -> str:
    """Mark each number span positive or negative from its own sign, for the semantic colours."""
    def mark(m):
        text = unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        tone = " neg" if text[:1] in "-−" else (" pos" if text[:1] == "+" else "")
        return f'<span class="fact{tone}"{m.group(1)}>{m.group(2)}</span>'
    return re.sub(r'<span class="fact"([^>]*)>(.*?)</span>', mark, html, flags=re.S)


def _parts(body: str) -> dict | None:
    head = re.search(r"<h1>(.*?)</h1>\s*<p class=\"meta\">(.*?)</p>", body, re.S)
    if not head:
        return None
    shifts = []
    for block in re.findall(r'<div class="shift">(.*?)</div>', body, re.S):
        title = re.search(r"<h2>(.*?)</h2>", block, re.S)
        meta = re.search(r'<p class="meta">(.*?)</p>', block, re.S)
        paras = [p for p in re.findall(r"<p>(.*?)</p>", block, re.S)]
        why = next((p for p in paras if not p.startswith("<b>")), "")
        so = next((p[len("<b>So what:</b>"):].strip() for p in paras if p.startswith("<b>So what:</b>")), "")
        ask = next((p[len("<b>Ask next:</b>"):].strip() for p in paras if p.startswith("<b>Ask next:</b>")), "")
        extra = {k: next((p[len(f"<b>{lab}:</b>"):].strip() for p in paras if p.startswith(f"<b>{lab}:</b>")), "")
                 for k, lab in (("diagnosis", "What is wrong"), ("action", "What to do"), ("impact", "What it is worth"))}
        shifts.append({"title": title.group(1) if title else "", "meta": meta.group(1) if meta else "",
                       "why": why, "so_what": so, "ask": ask, **extra})
    held = re.search(r"<h2>Held back for data checks</h2><ul>(.*?)</ul>", body, re.S)
    watch = re.search(r"<h2>Watchlist</h2><ul>(.*?)</ul>", body, re.S)
    prio = re.search(r"<h2>This week's priorities</h2><ol>(.*?)</ol>", body, re.S)
    items = lambda m: re.findall(r"<li>(.*?)</li>", m.group(1), re.S) if m else []          # noqa: E731
    return {"headline": head.group(1), "meta": head.group(2), "shifts": shifts, "held": items(held), "watch": items(watch),
            "priorities": items(prio)}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html))).strip()


def _brief_shift_ids() -> list:
    llm = b.get("LLM_JSON")
    if isinstance(llm, str):
        try:
            llm = json.loads(llm)
        except ValueError:
            llm = {}
    return [x.get("shift_id") for x in (llm or {}).get("shifts", [])]


# ---- Toolbar metadata and actions ----------------------------------------------------------------------------------

def toolbar() -> None:
    notes = data.brief_notifications(bid)
    emailed = (notes[(notes.CHANNEL == "EMAIL") & (notes.STATUS == "SENT")].SENT_AT.max() if len(notes) else None)
    attempts = int(b.get("NOTIFY_ATTEMPTS") or 0)
    if emailed is not None and not pd.isna(emailed):
        mail, tone = f"✓ Emailed {pd.to_datetime(emailed):%d %b %H:%M}", "ok"
    elif attempts >= 3:
        mail, tone = "✕ Email not sent (3 attempts)", "bad"
    else:
        mail, tone = "Not emailed yet", "warn"
    gen = fmt.GENERATOR_CHIP.get(b.get("GENERATOR"), b.get("GENERATOR") or "")
    published = f"Published {pd.to_datetime(b['PUBLISHED_AT']):%d %b %H:%M}" if b.get("PUBLISHED_AT") is not None else ""
    with bar:
        st.html('<div class="sr-brief-meta">' + "".join(f"<span>{escape(x)}</span>" for x in
                                                         (gen, published, f"Model {b.get('MODEL') or '–'}") if x)
                + f'<em class="sr-ctx-chip {tone}">{escape(mail)}</em></div>', width="content")
        with st.container(key="sr_brief_actions", horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            with st.popover("Copy brief", icon=":material/content_copy:", help="Copy the brief as plain text"):
                st.caption("The brief as plain text. Copy with the icon at the top right of the box.")
                st.code(b.get("BODY_MD") or "", language=None, wrap_lines=True)


# ---- The report --------------------------------------------------------------------------------------------------

def report() -> None:
    parts = _parts(b.get("BODY_HTML") or "")
    if parts is None:                                     # an unexpected layout: show the stored brief as it is
        with nav.card("brief_body"):
            st.html(nav.CSS + (b.get("BODY_HTML") or ""))
        return
    run_shifts = data.shifts(b["RUN_ID"]) if b.get("RUN_ID") else pd.DataFrame()
    by_id = {r.SHIFT_ID: r for r in run_shifts.itertuples(index=False)} if len(run_shifts) else {}
    current = data.current_run()
    live = set(data.shifts(current.run_id).SHIFT_ID) if current is not None else set()
    sids = _brief_shift_ids()
    rows = [by_id.get(sids[i]) if i < len(sids) else None for i in range(len(parts["shifts"]))]
    stake = sum(abs(float(r.VALUE_AT_STAKE)) for r in rows if r is not None and pd.notna(r.VALUE_AT_STAKE))
    chips = [f"{len(parts['shifts'])} shift{'' if len(parts['shifts']) == 1 else 's'} in the brief"]
    if any(r is not None for r in rows):
        chips.append(f"{fmt.money(stake, cur)} value at stake")
    chips += [f"{len(parts['held'])} held back", f"{len(parts['watch'])} early warning{'' if len(parts['watch']) == 1 else 's'}"]
    st.html('<section class="sr-brief-summary"><span class="k">Executive summary</span>'
            f'<h2>{_signed(parts["headline"])}</h2><p class="meta">{parts["meta"]}</p><div class="chips">'
            + "".join(f"<span>{escape(c)}</span>" for c in chips) + "</div>"
            + ("<p class=\"meta\"><b>This week's priorities</b></p><ol>"
               + "".join(f"<li>{_signed(p)}</li>" for p in parts["priorities"]) + "</ol>" if parts["priorities"] else "")
            + "</section>")

    with st.container(key="sr_brief_cards"):
        for i, (sh, r) in enumerate(zip(parts["shifts"], rows)):
            with st.container(key=f"sr_brief_card_{i}"):
                pts = float(r.D_SHARE_PTS) if r is not None and pd.notna(r.D_SHARE_PTS) else None
                arrow = "" if pts is None else ("trending_down" if pts < 0 else "trending_up")
                impact = ""
                if r is not None:
                    tone = "neg" if pts is not None and pts < 0 else "pos"
                    impact = (f'<b class="{tone}">{escape(fmt.pts(r.D_SHARE_PTS))}</b> · '
                              f'<b class="{"neg" if float(r.VALUE_AT_STAKE) < 0 else "pos"}">'
                              f'{escape(fmt.money(r.VALUE_AT_STAKE, cur))}</b> · {escape(fmt.pct(r.SH0))} → '
                              f'{escape(fmt.pct(r.SH1))} · Confidence {escape(fmt.confidence(r.CONFIDENCE))} · '
                              f'{escape(fmt.LABEL_CHIP.get(r.ARTEFACT_LABEL, r.ARTEFACT_LABEL))}')
                rows_html = [("Finding", _signed(sh["why"])), ("What is wrong", _signed(sh["diagnosis"])),
                             ("Business impact", impact), ("What to do", _signed(sh["action"])),
                             ("What it is worth", _signed(sh["impact"])),
                             ("If nothing is done" if sh["action"] else "Recommended action", _signed(sh["so_what"])),
                             ("Ask next", _signed(sh["ask"]))]
                st.html(f'<div class="sr-brief-card-head"><span class="sr-ico {("neg" if pts is not None and pts < 0 else "pos")}" '
                        f'aria-hidden="true">{arrow}</span><div><h3>{_signed(sh["title"])}</h3><p>{sh["meta"]}</p></div></div>'
                        '<dl class="sr-brief-rows">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows_html if v) + "</dl>")
                with st.container(key=f"sr_brief_act_{i}", horizontal=True, gap="small"):
                    if sh["ask"] and not masked:
                        if st.button("Ask Chippy", key=f"sr_brief_ask_{i}", icon=":material/forum:"):
                            st.session_state["sr_ask_about"] = _plain(sh["ask"])
                            st.switch_page("pages/5_Ask_Chippy.py")
                    if r is not None and r.SHIFT_ID in live:
                        if st.button("Investigate shift", key=f"sr_brief_open_{i}", icon=":material/arrow_forward:"):
                            st.session_state.shift_id = r.SHIFT_ID
                            st.switch_page("pages/1_Shift_detail.py")

    lists = [("Held back for data checks", "bad", "database", parts["held"]),
             ("Early warnings", "warn", "bolt", parts["watch"])]
    st.html('<div class="sr-brief-lists">' + "".join(
        f'<section class="{tone}"><h3><span class="sr-ico" aria-hidden="true">{icon}</span>{title} · {len(items)}</h3>'
        + ("".join(f"<p>{_signed(x)}</p>" for x in items) or '<p class="none">None this week.</p>') + "</section>"
        for title, tone, icon, items in lists) + "</div>")


def sources() -> None:
    f = data.brief_facts(bid)
    with st.expander(f"Sources · {len(f)} numbers", icon=":material/source:"):
        shown = [{"share": fmt.pct, "pts": fmt.pts, "index": fmt.signed_pct}.get(u, lambda v, d: fmt.money(v, cur, d))(v, d)
                 for v, u, d in zip(f.V, f.UNIT, f.DECIMALS)]
        st.caption("Every number is locked to the fact pack. Hover over a number in the brief to see its source.")
        st.dataframe(pd.DataFrame({"Fact": f.FACT_ID, "Shown as": shown, "Source": f.SOURCE}),
                     hide_index=True, width="stretch")


def checks() -> None:
    attempts = b.get("VIOLATIONS") or []
    if not attempts:
        return
    with st.expander("How the brief was written", icon=":material/fact_check:"):
        for a in attempts:
            who = "Template" if a.get("attempt") == "template" else f"Attempt {a.get('attempt')} ({a.get('model')})"
            v = a.get("violations") or []
            if not v:
                st.markdown(f"**{who}**: passed every check")
            else:
                st.markdown(f"**{who}**: rejected")
                st.dataframe(pd.DataFrame(v), hide_index=True, width="stretch")


# ---- Intelligence brief (SR-065): the run, Radar, Shift Detail and Insight Studio in one narrative -------------------

@st.cache_data(ttl=data.TTL_S, show_spinner=False)
def _pack(run_id: str, category: str, masked_: bool, cur_: str, markets: tuple, fkey: str = ""):
    """fkey (the applied sidebar filters) is only part of the cache key: the pack's panels read data.filters()."""
    from sr_ui import intel
    return intel.build_pack(run_id, category, masked_, cur_, dict(markets))


def _category() -> str:
    return str(data.filters().category if hasattr(data, "filters") else data.cfg("SCOPE_CATEGORY"))


def intelligence() -> None:
    from sr_ui import intel
    fkey = repr(data.filters()) if hasattr(data, "filters") else ""
    pk = _pack(b["RUN_ID"], _category(), masked, cur, tuple(sorted(data.market_names().items())), fkey)
    cache = st.session_state.setdefault("sr_intel", {})
    key = f"{bid}|{pk.key()}"
    if key not in cache:
        with st.spinner("Chippy is writing the intelligence brief…"):
            cache[key] = intel.narrative(pk)
    secs, generator = cache[key]
    run = data.current_run()
    with st.container(key="sr_intel_bar", horizontal=True, vertical_alignment="center", gap="small"):
        st.html(f'<div class="sr-brief-meta"><span>{escape(generator)}</span><span>Built from the weekly run, Radar, Shift '
                'Detail and Insight Studio</span><em class="sr-ctx-chip warn">Exploratory · the weekly brief is the record'
                '</em></div>', width="content")
        with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            if getattr(data, "narrate", None) is not None and st.button("Rewrite", key="sr_intel_rewrite",
                                                                        icon=":material/autorenew:", type="tertiary"):
                cache.pop(key, None)
                st.rerun()
            with st.popover("Copy", icon=":material/content_copy:"):
                st.code("\n\n".join(f"{s.upper()}\n{intel.plain(secs[s], pk)}" for s in intel.OUTLINE),
                        language=None, wrap_lines=True)
    if run is not None and run.run_id != b["RUN_ID"]:
        st.caption("This brief is from an earlier run; model sections read the latest weekly panel.")
    with st.container(key="sr_intel_body"):
        st.html(f'<div class="sr-intel-exec"><span class="k">Executive summary</span><p>'
                f'{intel.render(secs["Executive summary"], pk)}</p></div>')
        for sec in intel.OUTLINE[1:]:
            st.html(f'<div class="sr-intel-sec"><h3>{escape(sec)}</h3><p>{intel.render(secs[sec], pk)}</p></div>')
            if sec == "What moved" and pk.shifts:
                st.html('<div class="sr-intel-cards">' + "".join(
                    f'<div class="sr-intel-card"><b>{escape(d["brand"])}</b><span>{escape(d["market"])} · {escape(d["cmp"])}</span>'
                    f'<em>{intel.render(d["pts"], pk)}</em><dl>'
                    + "".join(f"<dt>{escape(k)}</dt><dd>{intel.render(v, pk)}</dd>" for k, v in (
                        ("Value at stake", d["vas"]), ("Main driver", f'{d.get("driver", "–")} {d.get("driver_pts", "")}'),
                        ("Evidence", d.get("evidence", "–")), ("Sales gap (model)", d.get("effect", "–")),
                        ("Top action (model)", d.get("action_v", "–"))))
                    + "</dl></div>" for d in pk.shifts) + "</div>")
            if sec == "Recommended actions" and pk.actions:
                st.dataframe(nav.striped(pd.DataFrame(pk.actions)), hide_index=True, width="stretch", row_height=34)
    with st.expander("Methods and sources: every figure in this brief", icon=":material/fact_check:"):
        st.dataframe(pd.DataFrame([{"Fact": k, "What": v["label"], "Value": v["text"], "Source": v["source"],
                                    "Model estimate": "yes" if v["model"] else ""} for k, v in pk.facts.items()]),
                     hide_index=True, width="stretch")
        st.caption("Numbers are locked: the narrative writes every figure as a fact token, and the page fills in the "
                   "value from this table. A section that types a number itself is replaced by the template.")


def share_report() -> None:
    """The automated share report: every brand in the category, one market and period, ready to send."""
    from sr_ui import studio
    cat = _category()
    retailers = sorted(studio._panel(cat, masked).RETAILER.unique())
    c1, c2, c3 = nav.stack("sr_rep_ctl").columns([1, 1.4, 1.4], vertical_alignment="bottom")
    default_w = data.filters().weeks if hasattr(data, "filters") else 4
    opts = sorted({4, 12, 52, default_w})
    weeks = c1.selectbox("Period", opts, index=opts.index(default_w), key="rep_weeks",
                         format_func=lambda w: f"Last {w} weeks")
    compare = c2.selectbox("Compared with", ["year_ago", "previous"], key="rep_cmp",
                           format_func={"year_ago": "Same weeks a year ago", "previous": "The weeks before"}.get)
    rets = ["All markets"] + retailers
    where = c3.selectbox("Market", rets, key="rep_ret", help="The regions or cities under the sidebar's market")
    r = studio._shown(data.share_report(cat, int(weeks), compare, None if where == "All markets" else where))
    if r.empty:
        st.info("No sales in this market and period.", icon=":material/info:")
        return
    period = f"last {weeks} weeks vs {'the same weeks a year ago' if compare == 'year_ago' else f'the {weeks} weeks before'}"
    lead = r.iloc[0]
    mover = r.reindex(r.SHARE_CHG_PTS.abs().sort_values(ascending=False).index).iloc[0]
    st.html(f'<div class="sr-takeaway"><span class="sr-ico" aria-hidden="true">lightbulb</span><div><span class="k">'
            f'{escape(where)} · {escape(cat)} · {escape(period)}</span><p>{escape(str(lead.BRAND))} leads with '
            f'{escape(fmt.pct(lead.SHARE / 100))} value share. The biggest mover is {escape(str(mover.BRAND))} '
            f'({escape(fmt.pts(mover.SHARE_CHG_PTS))}), rank {int(mover.RANK)}.</p></div></div>')
    table = pd.DataFrame({
        "Rank": r.RANK, "Move": r.RANK_CHG.map(lambda v: "–" if pd.isna(v) or v == 0 else ("▲ " if v > 0 else "▼ ") + f"{abs(int(v))}"),
        "Brand": r.BRAND, "Manufacturer": r.MANUFACTURER, "Value share": (r.SHARE / 100).map(fmt.pct),
        "Change": r.SHARE_CHG_PTS.map(fmt.pts), "Value sales": r.SALES.map(lambda v: fmt.money(v, cur)),
        "Sales growth": (r.SALES_GROWTH_PCT / 100).map(fmt.signed_pct), "ACV %": r.ACV.round(1),
        "Price index": r.PRICE_INDEX.round(2), "Velocity": r.VELOCITY.round(2),
        "Fair-share index": r.FAIR_SHARE_INDEX.round(0)})
    with nav.card("sr_rep_table"):
        nav.section("Competitive share report", "Velocity: units per store per week. Fair-share index: value share / share "
                    "of distribution points x 100 (above 100 sells more than its shelf presence).")
        st.dataframe(nav.striped(table), hide_index=True, width="stretch", row_height=34)
        from sr_ui import charts
        st.plotly_chart(charts.pl_bars_h(r.sort_values("SHARE_CHG_PTS", ascending=False)[["BRAND", "SHARE_CHG_PTS"]],
                                         "BRAND", "SHARE_CHG_PTS", "Share change, pts", signed=True, fmt=".2f"),
                        config=charts.PLOTLY_CONFIG, width="stretch")
    html = ("<html><head><meta charset='utf-8'><title>Share report</title><style>body{font-family:Inter,Arial,sans-serif;"
            "color:#173f43;margin:32px}table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;border-bottom:1px "
            "solid #dcebe8;text-align:right}th{background:#173f43;color:#fff}td:nth-child(3),td:nth-child(4),th:nth-child(3),"
            "th:nth-child(4){text-align:left}</style></head><body>"
            f"<h1>Competitive share report</h1><p>{escape(cat)} · {escape(where)} · {escape(period)}</p>"
            + table.to_html(index=False, escape=True) + "<p>Generated by Chippy from the weekly panel. Exploratory: the "
            "weekly brief is the record.</p></body></html>")
    st.download_button("Download the report (HTML)", html.encode("utf-8"), "chippy_share_report.html", "text/html",
                       icon=":material/download:")


nav.guarded("Brief toolbar", toolbar)
with st.container(key="sr_brief_view"):
    view = st.radio("Brief view", ["record", "intel", "report"], horizontal=True, key="brief_view",
                    label_visibility="collapsed", format_func={"record": "Weekly brief (of record)",
                                                               "intel": "Intelligence brief", "report": "Share report"}.get)
if view == "intel":
    nav.guarded("Intelligence brief", intelligence)
elif view == "report":
    nav.guarded("Share report", share_report)
else:
    nav.guarded("Brief", report)
    nav.guarded("Sources", sources)
    nav.guarded("Checks", checks)
