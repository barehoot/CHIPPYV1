"""Local preview only: Ask Chippy answered by an LLM on Groq, using tools over the sample data.

In Snowflake, Ask Chippy calls the Cortex agents through data.ask_agent and nothing here is deployed. Locally there is
no Snowflake session, so demo_data.install() swaps data.ask_agent for ask_agent() below when a Groq key is configured
(GROQ_API_KEY in ~/.streamlit/secrets.toml or the environment; never in this repository).

The tools mirror the real agents' tools (sql/50_sem/504 and 506): the share bridge, share flow, data checks, what-if
and the latest brief for Chippy; a fixed-spec query over the weekly panel for the Data analyst; and the Insight Studio
models for both. Numbers are locked: every number in an answer must come from a tool result (or the question). An
answer that quotes any other number is sent back once with the list of untraceable numbers; if it still has them,
the answer is shown with a warning naming them.

The same module offers narrate() for the Intelligence brief (numbers only as [F..] fact tokens) and chart_spec() for
the workbench's "Ask this chart".
"""
from __future__ import annotations

import itertools
import json
import os
import re
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

URL = "https://api.groq.com/openai/v1/chat/completions"
CHIPPY = "SR_DB.SEM.SHARE_RADAR_AGENT"
ANALYST = "SR_DB.SEM.RADAR_ANALYST_AGENT"
MAX_TOOL_ROUNDS = 6
_THREADS: dict[int, list[dict]] = {}
RETRY = "These numbers in your answer are not in any tool result: "
_IDS = itertools.count(1)


# ---- configuration and transport --------------------------------------------------------------------------------

def _secret(name: str, default: str | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:                                            # noqa: BLE001 - no secrets file is fine
        return default


def configured() -> bool:
    return bool(_secret("GROQ_API_KEY"))


def model() -> str:
    return _secret("GROQ_MODEL", "openai/gpt-oss-120b")


def _post(body: dict) -> dict:
    """One chat completion. Falls back to the smaller model when the main one is rate-limited or unavailable."""
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("No GROQ_API_KEY configured for the local preview.")
    models = [body.get("model") or model(), _secret("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")]
    last = None
    for m in dict.fromkeys(models):
        req = urllib.request.Request(URL, data=json.dumps({**body, "model": m}).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "User-Agent": "chippy-local-preview"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = RuntimeError(f"Groq {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
            if e.code not in (429, 500, 502, 503, 404):
                break
        except urllib.error.URLError as e:
            last = RuntimeError(f"Groq unreachable: {e.reason}")
            break
    raise last


# ---- tool helpers -----------------------------------------------------------------------------------------------

def _data():
    from sr_ui import data
    return data


def _name(x) -> str:
    from sr_ui import format as fmt
    return fmt.name(x)


def _round(v):
    if isinstance(v, (float, np.floating)):
        return None if pd.isna(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (pd.Timestamp,)):
        return str(v.date())
    return v


def _rows(df: pd.DataFrame, limit: int = 40) -> list[dict]:
    return [{k: _round(v) for k, v in r.items()} for r in df.head(limit).to_dict("records")]


def _shift_for(brand: str, market: str | None = None, cmp_code: str | None = None) -> dict:
    """The current run's shift for a brand (as shown, aliases included), best match on market and comparison."""
    d = _data()
    run = d.current_run()
    if run is None:
        raise ValueError("There is no completed weekly run yet.")
    markets = d.market_names()
    best, score = None, -1
    for r in d.shifts(run.run_id).itertuples(index=False):
        if brand.strip().lower() not in {str(r.BRAND).lower(), _name(r.BRAND).lower()}:
            continue
        sc = 1 + 2 * bool(r.SELECTED)
        if market and market.lower() in str(markets.get(r.MARKET_ID, r.MARKET_ID)).lower():
            sc += 4
        if cmp_code and cmp_code.upper() == r.CMP_CODE:
            sc += 3
        if sc > score:
            best, score = r, sc
    if best is None:
        raise ValueError(f"No shift for brand '{brand}' in the current run.")
    return {**best._asdict(), "MARKET": markets.get(best.MARKET_ID, best.MARKET_ID)}


def _masked() -> bool:
    return _data().cfg("DISPLAY_ALIAS") is True


def _panel() -> pd.DataFrame:
    """The weekly panel exactly as the app shows it: brands and manufacturers aliased when DISPLAY_ALIAS is on."""
    from sr_ui import studio
    p = studio._panel(str(_data().cfg("SCOPE_CATEGORY")), _masked())
    return p.assign(WEEK_END_DATE=pd.to_datetime(p.WEEK_END_DATE))


# ---- the tools ----------------------------------------------------------------------------------------------------

def t_list_shifts() -> dict:
    d = _data()
    run = d.current_run()
    if run is None:
        return {"error": "No completed weekly run yet."}
    m = d.market_names()
    s = d.shifts(run.run_id)
    out = pd.DataFrame({"brand": s.BRAND.map(_name), "market": s.MARKET_ID.map(lambda x: m.get(x, x)),
                        "comparison": s.CMP_CODE, "share_change_pts": s.D_SHARE_PTS, "share_now_pct": 100 * s.SH1,
                        "share_before_pct": 100 * s.SH0, "value_at_stake": s.VALUE_AT_STAKE, "confidence": s.CONFIDENCE,
                        "data_status": s.ARTEFACT_LABEL, "in_brief": s.SELECTED})
    from sr_ui import format as fmt
    out["value_at_stake_shown"] = s.VALUE_AT_STAKE.map(lambda v: fmt.money(v, d.cfg("CURRENCY") or ""))
    return {"as_of_week": str(run.as_of_week), "currency": d.cfg("CURRENCY"), "shifts": _rows(out),
            "note": "Quote money as in value_at_stake_shown."}


def t_get_share_bridge(brand: str, market: str | None = None, cmp_code: str | None = None) -> dict:
    s = _shift_for(brand, market, cmp_code)
    b = _data().bridge(s["SHIFT_ID"]) or {}
    return {"brand": _name(s["BRAND"]), "market": s["MARKET"], "comparison": s["CMP_CODE"],
            "share_now_pct": _round(100 * b.get("SH1", s["SH1"])), "share_before_pct": _round(100 * b.get("SH0", s["SH0"])),
            "share_change_pts": _round(s["D_SHARE_PTS"]), "bridge_mode": b.get("MODE"),
            "terms_pts": {k: _round(b.get(f"{k.upper()}_PTS")) for k in ("dist", "velocity", "price", "promo")},
            "residual_pts": _round(b.get("RESIDUAL_PTS")),
            "note": "Exact LMDI bridge: the four terms add up to the share change."}


def t_where_it_happened(brand: str, market: str | None = None, cmp_code: str | None = None) -> dict:
    s = _shift_for(brand, market, cmp_code)
    w = _data().where(s["SHIFT_ID"])
    w = w[w.METHOD == "EXACT_RETAILER"][["CONTRIBUTOR", "PERF_PTS", "MIX_PTS", "TOTAL_PTS"]] if len(w) else w
    return {"brand": _name(s["BRAND"]), "market": s["MARKET"], "retailers": _rows(w)}


def t_share_flow(brand: str, market: str | None = None, cmp_code: str | None = None) -> dict:
    s = _shift_for(brand, market, cmp_code)
    direction = "LOSS" if float(s["D_SHARE_PTS"]) < 0 else "GAIN"
    f = _data().flow(_data().current_run().run_id, s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"], direction)
    f = f.assign(COUNTERPART=f.COUNTERPART.map(_name))
    return {"brand": _name(s["BRAND"]), "direction": direction, "counterparts_pts": _rows(f),
            "note": "Proportional allocation of share points: an accounting split, not shopper switching."}


def t_check_artefact(brand: str, market: str | None = None, cmp_code: str | None = None) -> dict:
    s = _shift_for(brand, market, cmp_code)
    a = _data().artefacts(_data().current_run().run_id, s["CMP_CODE"], s["MARKET_ID"], s["CATEGORY"], s["BRAND"])
    return {"brand": _name(s["BRAND"]), "data_status": s["ARTEFACT_LABEL"], "rules_fired": _rows(a[["RULE_ID", "SEVERITY"]])
            if len(a) else [], "anomaly_confirmed": bool(s.get("ANOMALY_CONFIRMED")), "z_score": _round(s.get("Z_SCORE"))}


def t_what_if(brand: str, lever: str, target: str, market: str | None = None) -> dict:
    s = _shift_for(brand, market)
    r = _data().what_if(s["SHIFT_ID"], lever.upper(), target)
    return {"brand": _name(s["BRAND"]), "lever": lever.upper(), "target": target, **{k: _round(v) for k, v in r.items()}}


def t_latest_brief() -> dict:
    d = _data()
    b = d.briefs(1)
    if b.empty:
        return {"error": "No brief has been published yet."}
    brief = d.brief(b.iloc[0].BRIEF_ID)
    facts = d.brief_facts(brief["BRIEF_ID"])
    return {"headline": brief.get("HEADLINE"), "as_of_week": str(brief.get("AS_OF_WEEK")),
            "facts": _rows(facts[["FACT_ID", "V", "UNIT"]], 30)}


def t_studio_model(model: str, brand: str) -> dict:
    """Insight Studio models on the weekly panel (exploratory)."""
    from sr_ui import analytics as an
    p = _panel()
    b = _name(brand) if brand not in set(p.BRAND) else brand
    m = model.lower()
    if m == "elasticity":
        e = an.elasticity(p, b)
        return {"brand": b, "price_elasticity": _round(e["price"]["coef"]), "price_ci95": [_round(e["price"]["lo"]), _round(e["price"]["hi"])],
                "distribution_elasticity": _round(e["dist"]["coef"]), "r2": _round(e["r2"]), "rows": e["n"]}
    if m == "change_point":
        s = an.brand_weekly(p, b).set_index("WEEK_END_DATE").VALUE_SHARE_PCT
        cp = an.change_point(s)
        return {"brand": b, "change_week": str(pd.Timestamp(cp["week"]).date()), "share_before_pct": _round(cp["before"]),
                "share_after_pct": _round(cp["after"]), "step_pts": _round(cp["delta"]), "p_value": _round(cp["p"])}
    if m == "causal_impact":
        s = an.brand_weekly(p, b).set_index("WEEK_END_DATE").VALUE_SHARE_PCT
        ci = an.causal_impact(p, b, an.change_point(s)["week"])
        return {"brand": b, "since": str(pd.Timestamp(ci["start"]).date()), "weeks": ci["weeks"],
                "cumulative_sales_effect": _round(ci["effect"]), "relative_effect_pct": _round(100 * ci["relative"]),
                "per_week": _round(ci["per_week"]), "p_value": _round(ci["p"])}
    if m == "cannibalisation":
        cb = an.cannibalisation(p, b)
        return {"brand": b, "pairs": _rows(cb["pairs"])}
    if m == "anomaly_scan":
        d = _data()
        real = next((x for x in d.brand_panel(str(d.cfg("SCOPE_CATEGORY")), 104).BRAND.unique() if _name(x) == b), b)
        from sr_ui import studio
        res = an.anomaly_scan(studio._sku_panel(str(d.cfg("SCOPE_CATEGORY")), real, _masked()))
        return {"brand": b, "flagged": res["flagged"], "top": _rows(res["rows"][["WEEK_END_DATE", "RETAILER", "ITEM_DESC", "WHY"]], 5)}
    if m == "emerging_shifts":
        from sr_ui import studio
        em, _, _ = studio._emerging_frame(str(_data().cfg("SCOPE_CATEGORY")), _masked())
        return {"emerging": _rows(em.head(8))}
    return {"error": f"Unknown model {model}"}


MEASURES = ["VALUE_SALES", "UNIT_SALES", "VALUE_SHARE_PCT", "PRICE_PER_UNIT", "PRICE_INDEX", "ACV_DIST_PCT", "STORES_SELLING"]
DIMS = ["BRAND", "MANUFACTURER", "RETAILER", "REGION", "WEEK"]
SHARE_LIKE = {"VALUE_SHARE_PCT", "PRICE_PER_UNIT", "PRICE_INDEX", "ACV_DIST_PCT"}


def t_query_panel(measure: str, group_by: list[str] | None = None, weeks: int = 4, compare: str = "none",
                  brands: list[str] | None = None, retailers: list[str] | None = None, top_n: int = 15,
                  sort: str = "desc") -> dict:
    """The Data analyst's query: one measure, grouped, over the last `weeks`, optionally against the `weeks` before or
    the same weeks a year ago. Shares, prices and indices are averaged; sales and units are summed."""
    measure = measure.upper()
    if measure not in MEASURES:
        return {"error": f"measure must be one of {MEASURES}"}
    group_by = [g.upper() for g in (group_by or ["BRAND"]) if g.upper() in DIMS] or ["BRAND"]
    p = _panel()
    if brands:
        p = p[p.BRAND.str.lower().isin([b.lower() for b in brands])]
    if retailers:
        p = p[p.RETAILER.str.lower().isin([r.lower() for r in retailers])]
    p = p.assign(WEEK=p.WEEK_END_DATE.dt.date)
    w = sorted(p.WEEK_END_DATE.unique())
    weeks = max(1, min(int(weeks), 52))
    how = "mean" if measure in SHARE_LIKE else "sum"

    def agg(frame):
        return frame.groupby(group_by)[measure].agg(how)
    now = agg(p[p.WEEK_END_DATE.isin(w[-weeks:])]).rename(f"{measure}_NOW")
    out = now.to_frame()
    if compare in ("previous", "year_ago") and "WEEK" not in group_by:
        base = w[-2 * weeks:-weeks] if compare == "previous" else w[-52 - weeks:-52]
        before = agg(p[p.WEEK_END_DATE.isin(base)]).rename(f"{measure}_BEFORE")
        out = out.join(before)
        out["CHANGE"] = out[f"{measure}_NOW"] - out[f"{measure}_BEFORE"]
        if measure not in SHARE_LIKE:
            out["CHANGE_PCT"] = 100 * (out[f"{measure}_NOW"] / out[f"{measure}_BEFORE"] - 1)
    key = "CHANGE" if "CHANGE" in out else f"{measure}_NOW"
    out = out.reset_index().sort_values(key, ascending=(sort == "asc")).head(max(1, min(int(top_n), 60)))
    if "WEEK" in group_by:
        out = out.sort_values("WEEK")
    return {"table": _rows(out, 60), "weeks": weeks, "compare": compare, "aggregation": how,
            "_frame": out.reset_index(drop=True)}


def t_describe_data() -> dict:
    p = _panel()
    return {"brands": sorted(p.BRAND.unique()), "retailers": sorted(p.RETAILER.unique()),
            "regions": sorted(p.REGION.unique()), "measures": MEASURES, "dimensions": DIMS,
            "first_week": str(p.WEEK_END_DATE.min().date()), "last_week": str(p.WEEK_END_DATE.max().date())}


_BRAND_ARGS = {"type": "object", "properties": {
    "brand": {"type": "string", "description": "Brand name as the user wrote it"},
    "market": {"type": "string", "description": "Market or retailer name, if given"},
    "cmp_code": {"type": "string", "description": "L4W_VS_YA, L4W_VS_PP, L12W_VS_YA or L52W_VS_YA"}}, "required": ["brand"]}


def _fn(name, desc, params):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}


STUDIO_TOOL = _fn("studio_model", "Insight Studio model on the weekly panel (exploratory, not the brief): elasticity, "
                  "change_point (when the move started), causal_impact (sales lost or gained since the change), "
                  "cannibalisation (who trades share with the brand), anomaly_scan (unusual SKU weeks), emerging_shifts "
                  "(moves building before the 4-week reports show them).",
                  {"type": "object", "properties": {"model": {"type": "string", "enum": [
                      "elasticity", "change_point", "causal_impact", "cannibalisation", "anomaly_scan", "emerging_shifts"]},
                      "brand": {"type": "string"}}, "required": ["model", "brand"]})
TOOLS = {
    CHIPPY: [
        _fn("list_shifts", "This week's share shifts that passed the gates, with share change, value at stake, "
            "confidence, data status and whether they are in the brief.", {"type": "object", "properties": {}}),
        _fn("get_share_bridge", "Exact share bridge for a brand's shift: distribution, velocity, price and promo "
            "contributions in share points.", _BRAND_ARGS),
        _fn("where_it_happened", "Exact retailer split of a brand's share change (performance and mix).", _BRAND_ARGS),
        _fn("share_flow", "Which competitors took the share a brand lost (or gave the share it gained).", _BRAND_ARGS),
        _fn("check_artefact", "Data checks for a brand's shift: rules fired, anomaly confirmation, z-score.", _BRAND_ARGS),
        _fn("what_if", "Mechanical what-if: move one lever, others held.", {"type": "object", "properties": {
            "brand": {"type": "string"}, "lever": {"type": "string", "enum": ["DISTRIBUTION", "PROMO"]},
            "target": {"type": "string", "description": "BASE to restore the year-ago level, or a signed percentage like +10%"},
            "market": {"type": "string"}}, "required": ["brand", "lever", "target"]}),
        _fn("latest_brief", "The latest published weekly brief: headline and its locked facts.",
            {"type": "object", "properties": {}}),
        STUDIO_TOOL],
    ANALYST: [
        _fn("describe_data", "Brands, retailers, regions, measures, dimensions and the date range available.",
            {"type": "object", "properties": {}}),
        _fn("query_panel", "Query the weekly brand x retailer panel: one measure grouped by dimensions over the last N "
            "weeks, optionally compared with the previous N weeks or the same weeks a year ago.", {"type": "object", "properties": {
                "measure": {"type": "string", "enum": MEASURES},
                "group_by": {"type": "array", "items": {"type": "string", "enum": DIMS}},
                "weeks": {"type": "integer", "description": "Last N weeks, 1 to 52; default 4"},
                "compare": {"type": "string", "enum": ["none", "previous", "year_ago"]},
                "brands": {"type": "array", "items": {"type": "string"}},
                "retailers": {"type": "array", "items": {"type": "string"}},
                "top_n": {"type": "integer"}, "sort": {"type": "string", "enum": ["desc", "asc"]}},
                "required": ["measure"]}),
        STUDIO_TOOL],
}
IMPL = {"list_shifts": t_list_shifts, "get_share_bridge": t_get_share_bridge, "where_it_happened": t_where_it_happened,
        "share_flow": t_share_flow, "check_artefact": t_check_artefact, "what_if": t_what_if,
        "latest_brief": t_latest_brief, "studio_model": t_studio_model, "query_panel": t_query_panel,
        "describe_data": t_describe_data}

PROMPT = {
    CHIPPY: ("You are Chippy, the Ask-Why analyst for retail measurement share shifts (NIQ-style data). Explain why "
             "share moved using your tools: the exact bridge (distribution, velocity, price, promo), where it happened, "
             "who took the share, whether it could be a data effect, and what-if. Lead with the answer in one sentence and "
             "name the period comparison. Then 2 to 4 short bullets of evidence. Shares are in %, changes in points (pts)."),
    ANALYST: ("You are the Data analyst for a retail measurement panel. Answer business questions about sales, share, "
              "distribution, price and rankings by calling query_panel (call describe_data first if unsure of names). "
              "Give a one-sentence answer, then the key rows. The table is shown to the user automatically."),
}
RULES = ("\n\nRules: quote money in the short form the tools give (for example INR 1.8M) and shares to 1 or 2 decimals. "
         "Every number you write must appear in a tool result in this conversation or in the user's question; "
         "never estimate, compute new figures or round to different precision than needed (rounding a tool value to "
         "1 or 2 decimals is fine). If the tools cannot answer, say so. Keep it under 150 words. Use markdown bullets.")


# ---- numbers lock -------------------------------------------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])([-+−]?\d[\d,]*(?:\.\d+)?)(?:\s?([KMB])(?![A-Za-z]))?")
_COUNT_AFTER = re.compile(r"^\s*(?:-\s*)?(?:weeks?|wks?|months?|days?|retailers?|brands?|shifts?|checks?|skus?|stores?|"
                          r"rules?|of\s+\d|out of)\b", re.I)
_COUNT_BEFORE = re.compile(r"(?:rank|top|last|first|next|past|no\.|of|out of)\s*#?\s*$", re.I)
_ABS_WORDS = re.compile(r"(lost|loss|lose|losing|down|fell|fall|declin|drop|lower|less|minus|negative|gave|stake|risk|"
                        r"cost|gap|worth|shortfall|by)\W", re.I)
_MONEY_BEFORE = re.compile(r"(INR|Rs\.?|USD|EUR|GBP|[₹$€£])\s*$", re.I)


def _numbers_in(obj, out: list[float]) -> list[float]:
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float, np.integer, np.floating)) and not pd.isna(obj):
        out.append(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            v = _parse(m)
            if v is not None:
                out.append(v)
    return out


def _parse(m: re.Match) -> float | None:
    s = m.group(1).replace(",", "").replace("−", "-")
    mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
    try:
        return float(s) * mult
    except ValueError:
        return None


def untraced(text: str, sources: list[float], question: str = "") -> list[str]:
    """Numbers in `text` that no tool value explains, at the precision written (as-is, x100 or /100). A signed number
    must match the sign; an unsigned one may match the size of a negative value only when the words before it say
    the direction or that it is a size (lost, down, at stake, gap...). Small whole numbers are allowed only as counts
    (4 weeks, rank 2, 3 of 4); years only without a currency or K/M/B. Numbers in the question are allowed."""
    allowed = sources + _numbers_in(question, [])
    bad = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).strip()
        x = _parse(m)
        if x is None:
            continue
        digits = m.group(1).replace(",", "").lstrip("+-−")
        dec = len(digits.split(".")[1]) if "." in digits else 0
        before, after = text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 14]
        money = bool(_MONEY_BEFORE.search(before[-6:]))
        if dec == 0 and not m.group(2) and not money and "," not in m.group(1):
            if abs(x) <= 52 and (_COUNT_AFTER.search(after) or _COUNT_BEFORE.search(before)):
                continue
            if 1990 <= x <= 2100:
                continue
        signed = m.group(1)[0] in "+-−"
        size_ok = not signed and bool(_ABS_WORDS.search(before + " ") or _ABS_WORDS.search(" " + after[:20] + " "))
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
        tol = 0.5 * 10 ** -dec * mult * 1.0001 + 1e-9
        ok = False
        for v in allowed:
            for rep in (v, 100 * v, v / 100):
                if abs(rep - x) <= tol or (size_ok and abs(abs(rep) - abs(x)) <= tol) or \
                        (not signed and rep >= 0 and abs(rep - x) <= tol):
                    ok = True
                    break
            if ok:
                break
        if not ok:
            bad.append(raw)
    return list(dict.fromkeys(bad))


# ---- the agent loop ----------------------------------------------------------------------------------------------

def _run_tool(name: str, args: dict, tables: list, sources: list[float]) -> str:
    fn = IMPL.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool {name}"})
    try:
        res = fn(**args)
    except Exception as e:                                       # noqa: BLE001 - the model sees the error and adapts
        res = {"error": str(e)[:300]}
    frame = res.pop("_frame", None) if isinstance(res, dict) else None
    if frame is not None and len(frame):
        tables.append((f"{args.get('measure', '').replace('_', ' ').title()} by {', '.join(args.get('group_by') or ['brand']).lower()}",
                       frame))
    _numbers_in(res, sources)
    return json.dumps(res, default=str)[:6000]


def ask_agent(question: str, thread_id: int | None = None, parent_message_id: int = 0, agent: str = CHIPPY) -> dict:
    """Same contract as data.ask_agent: text, tables, tools, warnings, thread_id, message_id."""
    if agent not in TOOLS:
        raise ValueError(f"Unknown agent {agent}")
    tid = thread_id if thread_id in _THREADS else next(_IDS)
    history = _THREADS.setdefault(tid, [{"role": "system", "content": PROMPT[agent] + RULES}])
    msgs = history + [{"role": "user", "content": question}]
    tables, tools, sources, warnings = [], [], [], []
    text = ""
    for attempt in range(2):
        for _ in range(MAX_TOOL_ROUNDS):
            r = _post({"messages": msgs, "tools": TOOLS[agent], "tool_choice": "auto", "temperature": 0.2,
                       "max_completion_tokens": 1200})
            m = r["choices"][0]["message"]
            calls = m.get("tool_calls") or []
            msgs.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls") and v is not None})
            if not calls:
                text = (m.get("content") or "").strip()
                break
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tools.append(name)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": _run_tool(name, args, tables, sources)})
        bad = untraced(text, sources, question)
        if not bad:
            break
        if attempt == 0:
            msgs.append({"role": "user", "content": RETRY +
                         f"{', '.join(bad)}. Rewrite the answer using only numbers from the tool results."})
        else:
            warnings.append("Some figures could not be traced to a tool result: " + ", ".join(bad))
    kept = [x for x in msgs[1:] if x["role"] in ("user", "assistant") and x.get("content")
            and not str(x.get("content")).startswith(RETRY)]
    _THREADS[tid] = msgs[:1] + kept[-12:]
    return {"text": text, "tables": tables, "tools": tools or ["(no tool)"], "warnings": warnings,
            "thread_id": tid, "message_id": len(_THREADS[tid])}


# ---- Intelligence brief narrative ([F..] tokens only) --------------------------------------------------------------

def narrate(facts: dict[str, str], outline: list[str], draft: dict[str, str] | None = None) -> dict[str, str]:
    """Section texts for the Intelligence brief. The model sees each fact's id, label and formatted value plus a
    template draft, and must write numbers only as [Fnn] tokens; the page renders the values and rejects any raw digit."""
    listing = "\n".join(f"[{k}] {v}" for k, v in facts.items())
    prompt = ("You are the editor of a weekly market intelligence brief for an FMCG category team. Rewrite the draft "
              "below into sharp, executive prose: lead each section with the 'so what', connect cause and effect, and "
              "keep it to 2 to 4 sentences per section.\n\nHard rules:\n"
              "- Write every number ONLY as a fact token such as [F03], exactly as in the draft or the fact list. Never "
              "type a digit yourself, not even in words like '4-week' or '13 weeks' (use the token).\n"
              "- A token's value already includes its unit and sign (pts, %, INR); do not add units or signs after it.\n"
              "- Facts marked (model estimate) must be called estimates.\n"
              "- Keep every brand and retailer name as written.\n\n"
              "Sections: " + ", ".join(outline) + ".\n\nFacts:\n" + listing + "\n\nDraft:\n"
              + json.dumps(draft or {}, indent=1) + "\n\nReturn JSON {\"<section>\": \"<text>\"} for every section.")
    r = _post({"messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_completion_tokens": 6000,
               "reasoning_effort": "low", "response_format": {"type": "json_object"}})
    out = json.loads(r["choices"][0]["message"]["content"])
    return {k: str(v) for k, v in out.items() if k in outline}


# ---- Ask this chart ----------------------------------------------------------------------------------------------

def chart_spec(request: str, allowed: dict) -> dict:
    """A workbench spec for a plain-English chart request, constrained to `allowed` (lists of valid values)."""
    prompt = ("Turn the chart request into JSON with keys kind, x, y, agg, colour, brands, retailers, weeks. "
              f"Allowed values: {json.dumps(allowed)}. weeks is an integer (last N weeks). Use null when unspecified.\n"
              f"Request: {request}")
    r = _post({"messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_completion_tokens": 1500,
               "reasoning_effort": "low", "response_format": {"type": "json_object"}})
    return json.loads(r["choices"][0]["message"]["content"])
