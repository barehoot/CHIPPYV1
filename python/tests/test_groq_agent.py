"""The local-preview Groq agent (demo/groq_agent.py) with a stubbed LLM: no network, no key.

It must call the tools the model asks for, return the data.ask_agent contract, and lock numbers: an answer that
quotes a figure no tool returned is sent back once, then shown with a warning.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "demo"))
import groq_agent as g  # noqa: E402
from test_ui_pages import fake_data  # noqa: E402,F401  (the sample data module as sr_ui.data)


def _reply(content=None, calls=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = [{"id": f"c{i}", "type": "function",
                            "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]
    return {"choices": [{"message": m}]}


@pytest.fixture()
def scripted(fake_data, monkeypatch):
    seen = []

    def run(script):
        it = iter(script)
        monkeypatch.setattr(g, "_post", lambda body: seen.append(body) or next(it))
        return seen
    return run


def test_chippy_calls_the_bridge_and_answers_with_traced_numbers(scripted, fake_data):
    seen = scripted([_reply(calls=[("get_share_bridge", {"brand": "Crunchy"})]),
                     _reply("Crunchy lost 0.84 pts, mainly distribution (-0.61 pts) and velocity (-0.30 pts).")])
    r = g.ask_agent("Why did Crunchy lose share?", agent=g.CHIPPY)
    assert r["tools"] == ["get_share_bridge"] and not r["warnings"] and "0.84" in r["text"]
    assert {"text", "tables", "tools", "warnings", "thread_id", "message_id"} <= set(r)
    assert any(m["role"] == "tool" for m in seen[-1]["messages"])


def test_untraced_numbers_are_sent_back_then_flagged(scripted, fake_data):
    scripted([_reply(calls=[("get_share_bridge", {"brand": "Crunchy"})]),
              _reply("Crunchy lost 3.75 pts."),                          # not in any tool result
              _reply("Crunchy lost 3.75 pts.")])
    r = g.ask_agent("Why did Crunchy lose share?", agent=g.CHIPPY)
    assert r["warnings"] and "3.75" in r["warnings"][0]


def test_analyst_query_returns_a_table(scripted, fake_data):
    scripted([_reply(calls=[("query_panel", {"measure": "VALUE_SHARE_PCT", "group_by": ["BRAND"], "compare": "previous"})]),
              _reply("Crunchy leads.")])
    r = g.ask_agent("Top brands by share?", agent=g.ANALYST)
    assert r["tables"] and {"BRAND", "VALUE_SHARE_PCT_NOW", "CHANGE"} <= set(r["tables"][0][1].columns)


def test_threads_continue(scripted, fake_data):
    scripted([_reply("Hello."), _reply("Again.")])
    first = g.ask_agent("hi", agent=g.CHIPPY)
    second = g.ask_agent("and?", thread_id=first["thread_id"], agent=g.CHIPPY)
    assert second["thread_id"] == first["thread_id"]


@pytest.mark.parametrize("text,ok", [
    ("down 0.84 pts", True), ("share 23.41%", True), ("share fell 23.41pts", True), ("lost 9.99 pts", False),
    ("over 4 weeks in 2026", True), ("INR 1.8M at stake", True), ("lost 12 points", False), ("down 25% this year", False),
    ("worth INR 2,050", False), ("INR 2K", False), ("gained 0.84 pts", False), ("-0.84 pts", True), ("+0.84 pts", False),
    ("rank 2 of 5", True), ("3 of 4 checks", True)])
def test_untraced(text, ok):
    sources = [-0.84, 0.2341, -1834220.5]
    assert (not g.untraced(text, sources)) is ok, g.untraced(text, sources)


def test_unknown_agent_is_refused():
    with pytest.raises(ValueError):
        g.ask_agent("x", agent="SR_DB.SEM.OTHER")


def test_query_panel_without_a_comparison(fake_data):
    for group in (["MANUFACTURER"], ["WEEK"], ["BRAND", "RETAILER"]):
        r = g.t_query_panel("VALUE_SALES", group)
        assert "error" not in r and len(r["_frame"]), group


def test_agent_tools_respect_display_alias(fake_data, monkeypatch):
    from test_ui_pages import PANEL_BRANDS, SETTINGS
    alias = {**{("BRAND", b): f"Brand {chr(65 + i)}" for i, b in enumerate(PANEL_BRANDS)},
             **{("MANUFACTURER", m): f"Maker {i + 1}" for i, m in enumerate(sorted({m for m, *_ in PANEL_BRANDS.values()}))}}
    monkeypatch.setitem(SETTINGS, "DISPLAY_ALIAS", True)
    monkeypatch.setattr(fake_data, "aliases", lambda: alias)
    out = json.dumps(g.t_query_panel("VALUE_SALES", ["MANUFACTURER", "BRAND"]), default=str)
    out += json.dumps(g.t_studio_model("anomaly_scan", "Brand A"), default=str)
    real = list(PANEL_BRANDS) + [m for m, *_ in PANEL_BRANDS.values()]
    assert not [n for n in real if n in out] and "Maker 1" in out
