"""Ask Chippy: the AI conversational workspace. The switcher chooses the agent for the purpose (data.AGENTS): Chippy
(Ask-Why, SR_DB.SEM.SHARE_RADAR_AGENT) or the Data analyst (SR_DB.SEM.RADAR_ANALYST_AGENT). One thread per agent per
session; switching agent keeps the other conversation. Answers are the agent's own; tables are shown as returned and
can be drawn as a chart of the same values (no calculation)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from sr_ui import data, format as fmt, nav

st.html((Path(nav.__file__).with_name("radar.css")).read_text(encoding="utf-8"))   # Radar is the visual source
st.session_state.setdefault("chats", {})          # agent -> {"msgs": [...], "thread": int | None, "parent": int}
agents = data.AGENTS


def page_header() -> str:
    """The Radar header with the compact agent switcher (purpose in its tooltip) and New chat."""
    with st.container(key="sr_radar_header"):
        title, controls = st.columns([2, 3], vertical_alignment="center")
        title.html('<div class="sr-radar-title"><h1>Ask Chippy</h1>'
                   '<p>Questions about share shifts, answered with the exact numbers</p></div>')
        with controls.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            a = st.radio("Agent", list(agents), key="chat_agent", horizontal=True, index=list(agents).index(data.AGENT),
                         format_func=lambda x: agents[x]["label"], label_visibility="collapsed", width="content",
                         help=" · ".join(f"{v['label']}: {v['purpose']}" for v in agents.values())) or data.AGENT
            if st.button("New chat", icon=":material/add_comment:", key="sr_btn_newchat"):
                st.session_state.chats[a] = {"msgs": [], "thread": None, "parent": 0}
                st.session_state.pop("sr_ask_pending", None)
                st.rerun()
            if nav.is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
    return a


agent = page_header()
chat = st.session_state.chats.setdefault(agent, {"msgs": [], "thread": None, "parent": 0})
label = agents[agent]["label"]
pending = st.session_state.get("sr_ask_pending")
if pending and pending.get("agent") != agent:     # a question sent to the other agent stays with that agent
    pending = None


def starters() -> list[tuple[str, str]]:
    run = data.current_run()
    brand = "Brand C"
    if run:
        top = data.shifts(run.run_id)
        if len(top):
            brand = str(top.iloc[0].BRAND)
    market = data.market_names().get(str(data.cfg("SCOPE_PARENT_MARKET")), "Total Market")
    if agent == "SR_DB.SEM.RADAR_ANALYST_AGENT":
        return [("leaderboard", f"Which brands have the highest value share in {market} over the last 4 weeks?"),
                ("storefront", "Compare value sales by retailer for the last 12 weeks vs year ago"),
                ("factory", "Which manufacturers gained the most share in the last 52 weeks?"),
                ("table_chart", f"Show {brand}'s distribution and value share by retailer for the last 4 weeks")]
    return [("trending_down", f"Why did {brand} lose share in {market} in the last 4 weeks vs year ago?"),
            ("groups", f"Who took the share {brand} lost in {market}?"),
            ("verified_user", f"Is the {brand} drop in {market} real or a data effect?"),
            ("calendar_month", "What changed this week?")]


BRIDGE_TOOLS = {"get_share_bridge"}


def _evidence_shift(text: str):
    """The current run's shift a bridge answer is about: the brand must be named in the question or answer; market and
    comparison period break ties. Returns the shift row, or None when the text does not name one clearly."""
    run = data.current_run()
    if run is None or not text:
        return None
    t, markets = text.lower(), data.market_names()
    best, score = None, 0
    for r in data.shifts(run.run_id).itertuples(index=False):
        names = {str(r.BRAND).lower(), fmt.name(r.BRAND).lower()}
        if not any(n in t for n in names):
            continue
        sc = 2 + (str(markets.get(r.MARKET_ID, r.MARKET_ID)).lower() in t) \
            + (fmt.CMP_TEXT.get(r.CMP_CODE, "").lower() in t) + 0.1 * bool(r.SELECTED)
        if sc > score:
            best, score = r, sc
    return best


def _open_bridge(sid: str) -> None:
    st.session_state.shift_id = sid
    st.session_state.sr_open_checks = False
    st.session_state.pop("shift_view", None)                       # Shift detail opens on Investigation: bridge first
    st.switch_page("pages/1_Shift_detail.py")


def _chartable(df: pd.DataFrame) -> tuple[str, list[str]] | None:
    """(label column, numeric columns) when a returned table has exactly one label column and numeric columns."""
    if df is None or df.empty or len(df) > 60:
        return None
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    other = [c for c in df.columns if c not in num]
    return (other[0], num) if len(other) == 1 and num else None


def _table(df: pd.DataFrame, title: str, key: str) -> None:
    shape = _chartable(df)
    head = st.container(horizontal=True, vertical_alignment="center", gap="small")
    head.html(f'<span class="sr-ask-tbl">{escape(title or "Table")}</span>', width="content")
    as_chart = shape is not None and head.radio("View", ["Table", "Chart"], horizontal=True, key=key,
                                                 label_visibility="collapsed", width="content") == "Chart"
    if as_chart:
        x, ys = shape
        plot = df.set_index(x)[ys]
        if pd.api.types.is_datetime64_any_dtype(df[x]) or "date" in x.lower() or "week" in x.lower():
            st.line_chart(plot, height=240, color=["#1E5556", "#C6A879", "#647C80", "#C87970"][:len(ys)])
        else:
            st.bar_chart(plot, height=240, horizontal=len(df) > 6, color=["#1E5556", "#C6A879", "#647C80", "#C87970"][:len(ys)])
    else:
        st.dataframe(nav.striped(df), hide_index=True, width="stretch")


def show(msg: dict, n: int = 0) -> None:
    assistant = msg["role"] == "assistant"
    empty = assistant and not msg.get("failed") and not (msg.get("text") or "").strip() and not msg.get("tables")
    still = nav.RADAR_ANIM_DIR / ("resting.webp" if (msg.get("failed") or empty) else "success.webp")
    avatar = (str(still) if still.exists() else ":material/smart_toy:") if assistant else ":material/person:"
    with st.chat_message(msg["role"], avatar=avatar):
        if assistant:
            when = f" · {msg['at']}" if msg.get("at") else ""
            st.html(f'<div class="sr-ask-who">{escape(msg.get("agent", label))}{escape(when)}</div>')
            st.markdown(msg.get("text") or ("_Hmm, my basket is empty!_" if empty else "_No answer text returned._"))
            for j, (title, df) in enumerate(msg.get("tables") or []):
                _table(df, title, key=f"sr_ask_view_{n}_{j}")
            for w in msg.get("warnings") or []:
                st.warning(w)
            if msg.get("failed"):
                st.html(f'<div class="sr-ask-state small">{nav.radar_anim("resting", "Chippy resting", 40)}'
                        "<span>Something went wrong reaching the agent. Retry below.</span></div>")
            elif n == len(chat["msgs"]) - 1 and not empty:
                st.html(f'<div class="sr-ask-state small">{nav.radar_anim("success", "Chippy", 34)}'
                        "<span>Chippy figured it out!</span></div>")
            with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"sr_ask_foot_{n}"):
                if msg.get("tools"):
                    st.html('<div class="sr-ask-evidence"><span>Evidence</span>' + "".join(
                        f"<em>{escape(t)}</em>" for t in dict.fromkeys(msg["tools"])) + "</div>", width="content")
                if BRIDGE_TOOLS & set(msg.get("tools") or []):
                    hit = _evidence_shift(f"{msg.get('question', '')} {msg.get('text', '')}")
                    if hit is not None and st.button("View share bridge", key=f"sr_btn_bridge_{n}",
                                                     icon=":material/bar_chart:", type="tertiary",
                                                     help=f"Opens Shift Detail on {fmt.name(hit.BRAND)}"):
                        _open_bridge(hit.SHIFT_ID)
                if msg.get("text") and not msg.get("failed"):
                    with st.popover("Copy", icon=":material/content_copy:"):
                        st.code(msg["text"], language=None, wrap_lines=True)
                if msg.get("failed") and msg.get("question") and not pending:
                    if st.button("Retry", key=f"sr_ask_retry_{n}", icon=":material/refresh:"):
                        chat["msgs"].pop(n)
                        st.session_state["sr_ask_pending"] = {"agent": agent, "question": msg["question"]}
                        st.rerun()
        else:
            st.markdown(msg["text"])


def answer(question: str) -> None:
    """Ask the agent (data.ask_agent, unchanged) with the thinking Chippy shown; append the answer or a failure."""
    thinking = st.empty()
    name, msg_ = (("investigating", f"Let me think… {label} is checking the numbers.") if agent == data.AGENT
                  else ("loading", f"Gathering my acorns… {label} is fetching the data."))
    thinking.html(f'<div class="sr-ask-state">{nav.radar_anim(name, "Chippy is working", 64)}<span>{escape(msg_)}</span></div>')
    now = datetime.now().strftime("%H:%M")
    try:
        r = data.ask_agent(question, chat["thread"], chat["parent"], agent=agent)
    except Exception as e:                                           # noqa: BLE001 - fail soft, like every section
        thinking.empty()
        msg = {"role": "assistant", "agent": label, "agent_id": agent, "failed": True, "question": question, "at": now,
               "text": f"{label} couldn't answer that just now. Try again in a moment."}
        if nav.is_admin():
            msg["warnings"] = [str(e)[:300]]
        chat["msgs"].append(msg)
        return
    thinking.empty()
    chat["thread"], chat["parent"] = r["thread_id"], r["message_id"]
    chat["msgs"].append({"role": "assistant", "agent": label, "agent_id": agent, "question": question, "at": now,
                         **{k: r[k] for k in ("text", "tables", "tools", "warnings")}})


picked = None
if not chat["msgs"] and not pending:
    with st.container(key="sr_ask_welcome"):
        try:
            pic = nav.radar_anim("welcome", "Chippy waving", 132)
        except Exception:                                            # noqa: BLE001 - decoration never breaks the page
            pic = ""
        st.html(f'<div class="sr-ask-hello">{pic}<h2>Hi, I\'m {escape(label)}. What would you like to explore?</h2>'
                f'<p>{escape(agents[agent]["purpose"])} Every number comes from an agent tool; nothing is estimated.</p></div>')
        try:
            with st.container(key="sr_ask_starters"):
                for i, (icon, s) in enumerate(starters()):
                    if st.button(s, key=f"starter_{i}", icon=f":material/{icon}:", width="stretch"):
                        picked = s
        except Exception:                                            # noqa: BLE001 - starters are optional
            pass
else:
    with st.container(key="sr_ask_thread"):
        for i, m in enumerate(chat["msgs"]):
            show(m, i)
        if pending:                                                  # the question is on screen; now ask the agent
            st.session_state.pop("sr_ask_pending", None)
            answer(pending["question"])
            st.rerun()

about = st.session_state.get("sr_ask_about")
if about and agent == data.AGENT and data.cfg("DISPLAY_ALIAS") is not True:   # never offer real names when masked
    with st.container(key="sr_ask_about"):
        st.caption("From the page you were viewing")
        if st.button(about, key="sr_btn_ask_about", icon=":material/chat_bubble:", width="stretch"):
            picked = about
            st.session_state.pop("sr_ask_about", None)

question = st.chat_input(f"Ask {label}" + (" about a share shift…" if agent == data.AGENT else " a business question…"),
                         disabled=bool(pending))
if picked or question:
    chat["msgs"].append({"role": "user", "text": picked or question})
    st.session_state["sr_ask_pending"] = {"agent": agent, "question": picked or question}
    st.rerun()                                       # draw the question first, then ask the agent
