"""Ask Chippy: the AI conversational workspace. The viewer chooses who answers (data.AGENTS, a fixed allow-list):
Chippy (Ask-Why, SR_DB.SEM.SHARE_RADAR_AGENT), the Data analyst (SR_DB.SEM.RADAR_ANALYST_AGENT), Chippy Geo (cities,
regions and multi-year trends, SR_DB.SEM.GEO_MARKET_AGENT), or Auto, which sends
each question to one of them by a fixed keyword rule (sr_ui/agent_router.py) and says why. One thread per choice
per session; switching keeps the other conversations. Any answer can be re-asked of the other agent. Answers are the
agent's own; tables are shown as returned and can be drawn as a chart of the same values (no calculation)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from sr_ui import agent_router, data, format as fmt, nav
nav.entry_guard("pages/5_Ask_Chippy.py")   # a refresh or direct link still opens inside the app

st.html((Path(nav.__file__).with_name("radar.css")).read_text(encoding="utf-8"))   # Radar is the visual source
st.session_state.setdefault("chats", {})   # choice -> {"msgs": [...], "thread": int | None, "parent": int} (Auto: "threads")
agents = data.AGENTS
AUTO = "AUTO"
OPTIONS = [AUTO] + list(agents)

# What each choice is for, shown on its card: "spec" is the one-line specialization under the examples.
CARDS = {
    AUTO: {"label": "Auto", "pose": "hello_mix", "tag": "Smart routing",
           "purpose": "Picks the best agent for each question (Chippy, Data analyst, Geo or a specialist) and shows you why. Switch any answer with one click.",
           "best": ["Not sure who to ask", "Mixed questions"],
           "spec": "Sending each question to the right specialist"},
    agent_router.CHIPPY: {"pose": "hero_mix", "tag": "Ask-Why",
                          "best": ["Why share moved", "Who took it", "Real or a data effect", "What if"],
                          "spec": "Explaining why share moved and who took it"},
    agent_router.ANALYST: {"pose": "think_mix", "tag": "Tables",
                           "best": ["Rankings", "Comparisons", "Sales by retailer", "Trends over time"],
                           "spec": "Rankings, comparisons and trend tables"},
    agent_router.GEO: {"pose": "think_mix", "tag": "Cities & years",
                       "best": ["Which cities drove it", "Region breakdowns", "Trends since 2020"],
                       "spec": "City and regional performance since 2020"},
    agent_router.RECOVERY: {"pose": "hero_mix", "tag": "Action plan",
                            "best": ["How to win share back", "Where to act first", "What recovery is worth"],
                            "spec": "Plans to win lost share back"},
    agent_router.PRICE: {"pose": "think_mix", "tag": "Price & promo",
                         "best": ["Price gaps", "Price rises", "Promo depth and lift"],
                         "spec": "Price gaps, price changes and promotions"},
    agent_router.RISK: {"pose": "think_mix", "tag": "Early warning",
                        "best": ["What could go wrong", "Projected share", "Seasonal or new"],
                        "spec": "Early warnings and projected share"},
    agent_router.COMPETITOR: {"pose": "think_mix", "tag": "Benchmark",
                              "best": ["Company vs rivals", "League table", "Where we win or lose"],
                              "spec": "Benchmarking against competitors"},
}


def _label(choice: str) -> str:
    return CARDS[AUTO]["label"] if choice == AUTO else agents[choice]["label"]


def _purpose(choice: str) -> str:
    return CARDS[AUTO]["purpose"] if choice == AUTO else agents[choice]["purpose"]


if st.session_state.get("chat_agent") not in OPTIONS:        # first visit, or a value from an older session
    st.session_state["chat_agent"] = data.AGENT


def _choose(choice: str) -> None:
    st.session_state["chat_agent"] = choice


def _new_chat(choice: str) -> dict:
    return {"msgs": [], "threads": {}} if choice == AUTO else {"msgs": [], "thread": None, "parent": 0}


def page_header() -> str:
    """The Radar header: title and New chat on one row, the agent switcher (Auto and every agent) on its own row below,
    so the eight choices have the full width and never overlap."""
    with st.container(key="sr_radar_header"):
        title, controls = st.columns([3, 1], vertical_alignment="center")
        title.html('<div class="sr-radar-title"><h1>Ask Chippy</h1>'
                   '<p>Questions about share shifts, answered with the exact numbers</p></div>')
        with controls.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            new = st.button("New chat", icon=":material/add_comment:", key="sr_btn_newchat")
            if nav.is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
        with st.container(key="sr_ask_switch"):
            a = st.radio("Agent", OPTIONS, key="chat_agent", horizontal=True,
                         format_func=lambda x: ("✦ " if x == AUTO else "") + _label(x), label_visibility="collapsed",
                         help=" · ".join(f"{_label(v)}: {_purpose(v)}" for v in OPTIONS)) or data.AGENT
    if new:
        st.session_state.chats[a] = _new_chat(a)
        st.session_state.pop("sr_ask_pending", None)
        st.rerun()
    return a


def _thread(chat: dict, target: str) -> tuple[int | None, int]:
    if "threads" in chat:
        return tuple(chat["threads"].get(target, (None, 0)))
    return chat["thread"], chat["parent"]


def _set_thread(chat: dict, target: str, thread_id, message_id) -> None:
    if "threads" in chat:
        chat["threads"][target] = (thread_id, message_id)
    else:
        chat["thread"], chat["parent"] = thread_id, message_id


choice = page_header()
chat = st.session_state.chats.setdefault(choice, _new_chat(choice))
label = _label(choice)
pending = st.session_state.get("sr_ask_pending")
if pending and pending.get("agent") != choice:     # a question sent from another choice stays with it
    pending = None
unavailable = getattr(data, "AI_UNAVAILABLE_REASON", None)
if unavailable:
    st.html('<div class="sr-dock-notice sr-ask-notice" role="status"><span class="sr-ico" aria-hidden="true">info</span>'
            f'<span>{escape(unavailable)} You can still choose an agent and see where Auto would send a question.</span></div>')
elif getattr(data, "AI_PREVIEW_NOTE", None):                     # local preview with a stand-in LLM (demo only)
    st.html('<div class="sr-dock-notice sr-ask-notice" role="status"><span class="sr-ico" aria-hidden="true">science</span>'
            f'<span>{escape(data.AI_PREVIEW_NOTE)}</span></div>')


def _target(question: str) -> tuple[str, str | None]:
    """(agent to ask, routing reason or None). Fixed choices ask themselves; Auto asks the routed agent."""
    if choice != AUTO:
        return choice, None
    return agent_router.route(question)


def starters() -> list[tuple[str, str]]:
    run = data.current_run()
    brand = "Brand C"
    if run:
        top = data.shifts(run.run_id)
        if len(top):
            brand = str(top.iloc[0].BRAND)
    market = data.market_names().get(str(data.cfg("SCOPE_PARENT_MARKET")), "Total Market")
    analyst = [("leaderboard", f"Which brands have the highest value share in {market} over the last 4 weeks?"),
               ("storefront", "Compare value sales by retailer for the last 12 weeks vs year ago"),
               ("factory", "Which manufacturers gained the most share in the last 52 weeks?"),
               ("table_chart", f"Show {brand}'s distribution and value share by retailer for the last 4 weeks")]
    chippy = [("trending_down", f"Why did {brand} lose share in {market} in the last 4 weeks vs year ago?"),
              ("groups", f"Who took the share {brand} lost in {market}?"),
              ("verified_user", f"Is the {brand} drop in {market} real or a data effect?"),
              ("calendar_month", "What changed this week?")]
    geo = [("location_city", f"Which cities drove {brand}'s share change in the last 4 weeks vs prior period?"),
           ("map", f"Which South cities lost the most share for {brand} in the last 12 weeks vs year ago?"),
           ("timeline", f"How has {brand}'s share in {market} developed since 2020?"),
           ("public", f"Compare {brand}'s share across the four regions in the last 4 weeks")]
    if choice == agent_router.ANALYST:
        return analyst
    if choice == agent_router.GEO:
        return geo
    focus = data.cfg("FOCUS_MANUFACTURER") or "our company"
    special = {
        agent_router.RECOVERY: [("healing", f"How does {brand} win back its share in {market}?"),
                                ("location_city", f"Which city should {brand} fix first and what is it worth?"),
                                ("checklist", f"Build a recovery plan for {brand} in South Retail"),
                                ("verified_user", f"Is the {brand} loss real enough to act on?")],
        agent_router.PRICE: [("sell", f"Is {brand} priced too high in {market}?"),
                             ("percent", f"How does {brand}'s promotion compare with its rivals over the last 12 weeks?"),
                             ("trending_up", f"Did a price rise hurt {brand} in the last 4 weeks?"),
                             ("storefront", "Which brands are the most premium in Snacks?")],
        agent_router.RISK: [("warning", f"What are the biggest risks for {brand} next month?"),
                            ("notifications", "Which markets show early warning signals this week?"),
                            ("timeline", f"Is {brand}'s decline in Pune seasonal or new?"),
                            ("calendar_month", "What should we monitor next week?")],
        agent_router.COMPETITOR: [("leaderboard", f"How does {focus} compare with its competitors in {market}?"),
                                  ("emoji_events", "Who is winning in Snacks over the last 52 weeks?"),
                                  ("map", f"Where is {focus} losing to rivals?"),
                                  ("groups", f"Which competitor is taking share from {brand}?")],
    }
    if choice in special:
        return special[choice]
    if choice == AUTO:
        return [chippy[0], analyst[0], geo[0], geo[2]]
    return chippy


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


def _ask_other(n: int, other: str) -> None:
    """Re-ask the question behind answer n of the other agent: in Auto, in the same thread; otherwise in that agent's
    own conversation, which then opens."""
    question = chat["msgs"][n]["question"]
    note = f"Asked {agents[other]['label']} instead"
    if choice == AUTO:
        chat["msgs"].append({"role": "user", "text": question, "note": note})
        st.session_state["sr_ask_pending"] = {"agent": AUTO, "question": question, "target": other, "asked": True}
        return
    dest = st.session_state.chats.setdefault(other, _new_chat(other))
    dest["msgs"].append({"role": "user", "text": question, "note": note})
    st.session_state["sr_ask_pending"] = {"agent": other, "question": question, "target": other}
    st.session_state["chat_agent"] = other


def show(msg: dict, n: int = 0) -> None:
    assistant = msg["role"] == "assistant"
    empty = assistant and not msg.get("failed") and not (msg.get("text") or "").strip() and not msg.get("tables")
    still = nav.RADAR_ANIM_DIR / ("resting.png" if (msg.get("failed") or empty) else "success.png")
    avatar = (str(still) if still.exists() else ":material/smart_toy:") if assistant else ":material/person:"
    with st.container(key=f"sr_ask_{'bot' if assistant else 'user'}_{n}"), st.chat_message(msg["role"], avatar=avatar):
        if assistant:
            when = f" · {msg['at']}" if msg.get("at") else ""
            st.html(f'<div class="sr-ask-who">{escape(msg.get("agent", label))}{escape(when)}</div>')
            if msg.get("routed"):
                st.html(f'<div class="sr-ask-route"><span class="sr-ico" aria-hidden="true">alt_route</span>'
                        f'<span>Auto sent this to <b>{escape(msg.get("agent", ""))}</b>: {escape(msg["routed"])}</span></div>')
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
                other = next((a for a in agents if a != msg.get("agent_id")), None)
                if msg.get("question") and other and not pending:
                    st.button(f"Ask {agents[other]['label']} instead", key=f"sr_ask_other_{n}",
                              icon=":material/swap_horiz:", type="tertiary", on_click=_ask_other, args=(n, other),
                              help=f"{agents[other]['label']}: {agents[other]['purpose']}")
                if msg.get("failed") and msg.get("question") and not pending:
                    if st.button("Retry", key=f"sr_ask_retry_{n}", icon=":material/refresh:"):
                        chat["msgs"].pop(n)
                        st.session_state["sr_ask_pending"] = {"agent": choice, "question": msg["question"],
                                                              "target": msg.get("agent_id", choice),
                                                              "why": msg.get("routed")}
                        st.rerun()
        else:
            if msg.get("note"):
                st.html(f'<div class="sr-ask-who">{escape(msg["note"])}</div>')
            st.markdown(msg["text"])


def answer(question: str, target: str, why: str | None) -> None:
    """Ask the target agent (data.ask_agent, unchanged) with the thinking Chippy shown; append the answer or a failure."""
    who = agents[target]["label"]
    thinking = st.empty()
    name, msg_ = (("investigating", f"Let me think… {who} is checking the numbers.") if target == data.AGENT
                  else ("loading", f"Gathering my acorns… {who} is fetching the data."))
    thinking.html(f'<div class="sr-ask-state">{nav.radar_anim(name, "Chippy is working", 64)}<span>{escape(msg_)}</span></div>')
    now = datetime.now().strftime("%H:%M")
    base = {"role": "assistant", "agent": who, "agent_id": target, "question": question, "at": now}
    if why:
        base["routed"] = why
    thread_id, parent = _thread(chat, target)
    try:
        r = data.ask_agent(question, thread_id, parent, agent=target)
    except Exception as e:                                           # noqa: BLE001 - fail soft, like every section
        thinking.empty()
        msg = {**base, "failed": True, "text": f"{who} couldn't answer that just now. Try again in a moment."}
        if nav.is_admin():
            msg["warnings"] = [str(e)[:300]]
        chat["msgs"].append(msg)
        return
    thinking.empty()
    _set_thread(chat, target, r["thread_id"], r["message_id"])
    chat["msgs"].append({**base, **{k: r[k] for k in ("text", "tables", "tools", "warnings")}})


def agent_cards() -> None:
    """Who answers: one card per choice. The chosen card comes alive (its Chippy animates); the others stay still."""
    st.html('<div class="sr-agent-pick-h"><b>Who should answer?</b><span>Pick an agent, or let Auto choose for each '
            "question.</span></div>")
    with nav.stack("sr_agent_cards"):
        cols = st.columns(len(OPTIONS), gap="small")
    for col, opt in zip(cols, OPTIONS):
        info, on = CARDS[opt], opt == choice
        slug = {AUTO: "auto", agent_router.CHIPPY: "chippy", agent_router.GEO: "geo", agent_router.RECOVERY: "recovery",
                agent_router.PRICE: "price", agent_router.RISK: "risk",
                agent_router.COMPETITOR: "competitor"}.get(opt, "analyst")
        with col, st.container(key=f"sr_agent_card_{slug}{'_on' if on else ''}"):
            pic = nav.pulse_img(info["pose"], _label(opt), 44, animate=on)
            st.html(f'<div class="sr-agent-card-body"><div class="sr-agent-top">{pic}<div class="sr-agent-name">'
                    f'{escape(_label(opt))}<em>{escape(info["tag"])}</em></div></div><p>{escape(_purpose(opt))}</p>'
                    '<div class="sr-agent-best">' + "".join(f"<span>{escape(b)}</span>" for b in info["best"]) + "</div>"
                    '<div class="sr-agent-spec"><span class="sr-ico" aria-hidden="true">workspace_premium</span><span>'
                    f'<b>Specializes in</b> {escape(info["spec"])}</span></div></div>')
            st.button("Selected" if on else f"Choose {_label(opt)}", key=f"sr_agent_pick_{slug}", width="stretch",
                      icon=":material/check_circle:" if on else ":material/radio_button_unchecked:",
                      type="primary" if on else "secondary", disabled=on, on_click=_choose, args=(opt,))


picked = None
if not chat["msgs"] and not pending:
    with st.container(key="sr_ask_welcome"):
        try:
            pic = nav.radar_anim("welcome", "Chippy waving", 132)
        except Exception:                                            # noqa: BLE001 - decoration never breaks the page
            pic = ""
        who = "Chippy" if choice == AUTO else _label(choice)
        st.html(f'<div class="sr-ask-hello">{pic}<h2>Hi, I\'m {escape(who)}. What would you like to explore?</h2>'
                f'<p>{escape(_purpose(choice))} Every number comes from an agent tool; nothing is estimated.</p></div>')
        nav.guarded("Agent picker", agent_cards)
        try:
            with st.container(key="sr_ask_starters"):
                for i, (icon, s) in enumerate(starters()):
                    to = _target(s)[0]
                    if st.button(s, key=f"starter_{i}", icon=f":material/{icon}:", width="stretch",
                                 help=f"Goes to {agents[to]['label']}" + (" (chosen by Auto)" if choice == AUTO else "")):
                        picked = s
            if choice == AUTO:
                st.caption("Auto: point at a starter to see which agent it goes to. The rule is a fixed keyword match, "
                           "not AI, and every answer says where it went and why.")
        except Exception:                                            # noqa: BLE001 - starters are optional
            pass
else:
    with st.container(key="sr_ask_thread"):
        for i, m in enumerate(chat["msgs"]):
            show(m, i)
        if pending:                                                  # the question is on screen; now ask the agent
            st.session_state.pop("sr_ask_pending", None)
            target = pending.get("target") or _target(pending["question"])[0]
            answer(pending["question"], target, None if pending.get("asked") else pending.get("why"))
            st.rerun()

about = st.session_state.get("sr_ask_about")
if about and choice != agent_router.ANALYST and data.cfg("DISPLAY_ALIAS") is not True:   # never offer real names when masked
    with st.container(key="sr_ask_about"):
        st.caption("From the page you were viewing")
        if st.button(about, key="sr_btn_ask_about", icon=":material/chat_bubble:", width="stretch"):
            picked = about
            st.session_state.pop("sr_ask_about", None)

placeholder = {AUTO: "Ask anything: Auto picks the agent…", agent_router.ANALYST: "Ask Data analyst a business question…",
               agent_router.GEO: "Ask Chippy Geo about cities, regions or years…",
               agent_router.RECOVERY: "Ask the Recovery Strategist how to win share back…",
               agent_router.PRICE: "Ask Pricing & Promo about price gaps and promotions…",
               agent_router.RISK: "Ask Forecast & Risk what could go wrong next…",
               agent_router.COMPETITOR: "Ask Competitive benchmarking how you compare with rivals…"}
question = st.chat_input(placeholder.get(choice, f"Ask {label} about a share shift…"), disabled=bool(pending))
if picked or question:
    q = picked or question
    target, why = _target(q)
    chat["msgs"].append({"role": "user", "text": q})
    st.session_state["sr_ask_pending"] = {"agent": choice, "question": q, "target": target, "why": why}
    st.rerun()                                       # draw the question first, then ask the agent
