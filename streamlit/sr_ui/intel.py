"""The Intelligence brief (SR-065): one narrative that joins the weekly run, Radar, Shift Detail and Insight Studio.

Numbers are locked the same way as the stored brief's fact pack: build_pack() turns every figure into a numbered fact
(F01, F02, ...) with its formatted text and source; narratives may only write numbers as [Fnn] tokens; render() fills
the tokens in and refuses any text that types a digit itself. The narrative comes from the template here, or, when
the data module offers narrate() (the local preview's stand-in LLM), from the LLM, validated the same way and replaced
by the template section by section when it fails. Model facts say they are model estimates.

The stored weekly brief (SP_WRITE_BRIEF, the fact pack, the validator) stays the brief of record; this view never
writes to Snowflake.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html import escape

import pandas as pd

from sr_ui import analytics as an, format as fmt


class _Data:
    """sr_ui.data looked up at call time, like nav and format do, so whichever data module is installed (Snowflake, or
    the local preview's sample data) is the one used, whatever was installed when this module was first imported."""
    def __getattr__(self, name):
        from sr_ui import data as current
        return getattr(current, name)


data = _Data()

OUTLINE = ["Executive summary", "What moved", "Emerging shifts", "Held back for data checks", "Competitive landscape",
           "Outlook", "Recommended actions"]
TOKEN = re.compile(r"\[(F\d{2,3})\]")


@dataclass
class Pack:
    facts: dict[str, dict] = field(default_factory=dict)       # id -> {"label", "text", "source", "model"}
    shifts: list[dict] = field(default_factory=list)           # one per shift in the brief, with its fact ids
    actions: list[dict] = field(default_factory=list)
    emerging: list[dict] = field(default_factory=list)
    held: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    names: set[str] = field(default_factory=set)               # brands, markets, retailers: digits in them are names

    def add(self, label: str, text: str, source: str, model: bool = False) -> str:
        fid = f"F{len(self.facts) + 1:02d}"
        self.facts[fid] = {"label": label, "text": text, "source": source, "model": model}
        return f"[{fid}]"

    def key(self) -> str:
        return hashlib.sha1(json.dumps(self.facts, sort_keys=True).encode()).hexdigest()[:16]


# ---- build the pack -------------------------------------------------------------------------------------------------

def build_pack(run_id: str, category: str, masked: bool, cur: str, markets: dict) -> Pack:
    from sr_ui import studio
    pk = Pack()
    shifts = data.shifts(run_id)
    sel = shifts[shifts.SELECTED].sort_values("RANK_NO")
    pf = data.portfolio(run_id)
    k = data.kpis(run_id)
    pk.add("shifts past the gates", f"{int(k.get('N_PASSED', 0))}", "APP.SHIFT_CANDIDATE")
    pk.add("shifts in the brief", f"{int(pf.get('N_SHIFTS', 0))}", "APP.SHIFT_RANKED")
    pk.add("value at risk in the brief (losses)", fmt.money(abs(pf.get("VALUE_LOSS") or 0), cur), "APP.SHIFT_RANKED")
    pk.add("value in play in the brief (gains)", fmt.money(pf.get("VALUE_GAIN"), cur), "APP.SHIFT_RANKED")
    pk.add("possible data effects past the gates", f"{int(k.get('N_DATA_EFFECT', 0))}", "APP.SHIFT_RANKED")
    pk.add("projection horizon", "13 weeks", "Holt-Winters projection")
    pk.add("manual report period", "4-week", "report cadence")
    panel = studio._panel(category, masked)
    for r in sel.itertuples(index=False):
        brand, market = fmt.name(r.BRAND), markets.get(r.MARKET_ID, r.MARKET_ID)
        pk.names.update({brand, str(market)})
        d = {"brand": brand, "market": market, "cmp": fmt.CMP_TEXT.get(r.CMP_CODE, r.CMP_CODE),
             "direction": "lost" if r.D_SHARE_PTS < 0 else "gained", "shift_id": r.SHIFT_ID}
        d["cmp_tok"] = pk.add(f"{brand} comparison", d["cmp"], "APP.SHIFT_RANKED")
        d["pts"] = pk.add(f"{brand} share change", fmt.pts(r.D_SHARE_PTS), "APP.SHIFT_RANKED")
        d["size"] = pk.add(f"{brand} size of the share move", fmt.pts(abs(r.D_SHARE_PTS)).lstrip("+"), "APP.SHIFT_RANKED")
        d["sh0"] = pk.add(f"{brand} share before", fmt.pct(r.SH0), "APP.SHIFT_CANDIDATE")
        d["sh1"] = pk.add(f"{brand} share now", fmt.pct(r.SH1), "APP.SHIFT_CANDIDATE")
        d["vas"] = pk.add(f"{brand} value at stake", fmt.money(abs(r.VALUE_AT_STAKE), cur), "APP.SHIFT_RANKED")
        d["conf"] = pk.add(f"{brand} confidence", fmt.confidence(r.CONFIDENCE), "APP.SHIFT_RANKED")
        b = data.bridge(r.SHIFT_ID) or {}
        terms = [(t, b.get(c)) for c, t in (("DIST_PTS", "distribution"), ("VELOCITY_PTS", "velocity"),
                                            ("PRICE_PTS", "price"), ("PROMO_PTS", "promotion")) if b.get(c) is not None]
        if terms:
            t, v = max(terms, key=lambda x: abs(x[1]))
            d["driver"], d["driver_pts"] = t, pk.add(f"{brand} largest bridge term ({t})", fmt.pts(v), "APP.SHARE_BRIDGE")
        w = data.where(r.SHIFT_ID)
        w = w[w.METHOD == "EXACT_RETAILER"] if len(w) else w
        if len(w):
            top = w.reindex(w.TOTAL_PTS.abs().sort_values(ascending=False).index).iloc[0]
            d["retailer"], d["retailer_pts"] = str(top.CONTRIBUTOR), pk.add(f"{brand} largest retailer contribution",
                                                                             fmt.pts(top.TOTAL_PTS), "APP.SHIFT_WHERE")
        f = data.flow(run_id, r.CMP_CODE, r.MARKET_ID, r.CATEGORY, r.BRAND, "LOSS" if r.D_SHARE_PTS < 0 else "GAIN")
        if len(f):
            top = f.sort_values("FLOW_PTS", ascending=False).iloc[0]
            d["counter"], d["counter_pts"] = fmt.name(top.COUNTERPART), pk.add(
                f"{brand} largest counterpart flow", fmt.pts(top.FLOW_PTS), "APP.SHARE_FLOW")
        try:
            cp = studio._fit("changepoint", category, brand, "VALUE_SHARE_PCT", masked)
            ci = studio._fit("causal", category, brand, f"VALUE_SALES|{pd.Timestamp(cp['week']).date()}", masked)
            d["since"] = pk.add(f"{brand} change began (model)", pd.Timestamp(cp["week"]).strftime("%d %b"),
                                "change-point model", model=True)
            d["effect"] = pk.add(f"{brand} sales gap since the change (model)", fmt.money(ci["effect"], cur),
                                 "causal-impact model", model=True)
            d["effect_rel"] = pk.add(f"{brand} sales against expected (model)", fmt.signed_pct(ci["relative"]),
                                     "causal-impact model", model=True)
            checks = an.evidence_score(r._asdict(), cp, ci)
            d["evidence"] = pk.add(f"{brand} evidence checks passed", f"{sum(ok for _, ok, _ in checks)} of 4",
                                   "evidence score")
        except an.AnalyticsError:
            pass
        try:
            el = studio._fit("elasticity", category, brand, "", masked)
            acts = an.actions(panel, brand, el)
            if len(acts):
                a = acts.iloc[0]
                d["action"] = pk.add(f"{brand} top action (model)", a.ACTION[:1].lower() + a.ACTION[1:],
                                     "elasticity model", model=True)
                d["action_v"] = pk.add(f"{brand} top action value per week (model)", fmt.money(a.VALUE_PER_WEEK, cur),
                                       "elasticity model", model=True)
                for x in acts.itertuples():
                    pk.actions.append({"Brand": brand, "Action": x.ACTION, "Lever": x.LEVER,
                                       "Value per week (model)": fmt.money(x.VALUE_PER_WEEK, cur),
                                       "Certainty": x.CERTAINTY, "Owner": {"Distribution": "Sales / customer team",
                                       "Price": "Revenue management", "Retailer": "Key account manager"}.get(x.LEVER, "Category team"),
                                       "Assumption": x.ASSUMPTION})
        except an.AnalyticsError:
            pass
        try:
            cb = studio._fit("cannibal", category, brand, "", masked)
            if len(cb["pairs"]):
                p0 = cb["pairs"].iloc[0]
                d["rival"] = str(p0.BRAND)
                d["rival_corr"] = pk.add(f"{brand} share-change correlation with {p0.BRAND}", f"{p0.CORR:+.2f}",
                                         "cannibalisation analysis", model=True)
        except an.AnalyticsError:
            pass
        try:
            from sr_ui import forecast
            wk = an.brand_weekly(panel, brand)
            y = pd.Series(wk.VALUE_SALES.to_numpy(), index=pd.to_datetime(wk.WEEK_END_DATE))
            res, _ = forecast.run(y, ["Holt-Winters"], 13)
            if res:
                end = float(res[0]["forecast"].MEAN.iloc[-1])
                d["outlook"] = pk.add(f"{brand} weekly sales in 13 weeks vs now (projection)",
                                      fmt.signed_pct(end / float(y.iloc[-1]) - 1), "Holt-Winters projection", model=True)
        except Exception:                                        # noqa: BLE001 - an outlook is optional
            pass
        pk.shifts.append(d)
    try:
        em, _, _ = studio._emerging_frame(category, masked)
        new = em[~em.IN_REPORTS]
        pk.add("emerging shifts not in reports yet", f"{len(new)}", "emerging-shift scan", model=True)
        for r in new.head(3).itertuples():
            pk.emerging.append({"brand": r.BRAND, "retailer": r.RETAILER, "dir": "gaining" if r.DIRECTION == "UP" else "losing",
                                "weeks": pk.add(f"{r.BRAND} at {r.RETAILER}: weeks since flagged",
                                                f"{int(r.LEAD_WEEKS)}" if pd.notna(r.LEAD_WEEKS) else "–", "emerging-shift scan", model=True),
                                "chg": pk.add(f"{r.BRAND} at {r.RETAILER}: L4W vs YA", fmt.pts(r.L4W_VS_YA_PTS),
                                              "emerging-shift scan", model=True)})
    except an.AnalyticsError:
        pass
    pk.names.update(str(x) for x in panel.RETAILER.unique())
    pk.names.update(str(x) for x in panel.BRAND.unique())
    pk.names.update(str(markets.get(m, m)) for m in shifts.MARKET_ID.unique())
    held = shifts[~shifts.SELECTED & (shifts.ARTEFACT_LABEL == "POSSIBLE_DATA_EFFECT")]
    for r in held.itertuples(index=False):
        pk.held.append({"brand": fmt.name(r.BRAND), "market": markets.get(r.MARKET_ID, r.MARKET_ID),
                        "pts": pk.add(f"{fmt.name(r.BRAND)} held-back change", fmt.pts(r.D_SHARE_PTS), "APP.SHIFT_RANKED"),
                        "reason": str(r.SUPPRESS_REASON or "possible data effect")})
    return pk


# ---- template narrative (tokens only) ------------------------------------------------------------------------------

def template(pk: Pack) -> dict[str, str]:
    """The narrative from the facts alone, written with tokens like the LLM must, so both pass the same checks."""
    f = list(pk.facts)
    tok = lambda i: f"[{f[i]}]"                                  # noqa: E731 - the run-level facts, in add() order
    out = {}
    lead = pk.shifts[0] if pk.shifts else None
    s = f"{tok(1)} shifts made this week's brief out of {tok(0)} that passed the gates, with {tok(2)} at risk and " \
        f"{tok(3)} in play."
    if lead:
        s += f" The largest: {lead['brand']} {lead['direction']} {lead['size']} in {lead['market']} ({lead['cmp_tok']})"
        s += (f", driven mainly by {lead['driver']} ({lead['driver_pts']})." if "driver" in lead else ".")
        if "evidence" in lead:
            s += f" {lead['evidence']} independent checks say it is a real market move."
    out["Executive summary"] = s
    parts = []
    for d in pk.shifts:
        p = f"{d['brand']} {d['direction']} {d['size']} in {d['market']} ({d['sh0']} to {d['sh1']}), {d['vas']} at stake."
        if "driver" in d:
            p += f" The exact bridge puts most of it on {d['driver']} ({d['driver_pts']})."
        if "retailer" in d:
            p += f" {d['retailer']} contributed most ({d['retailer_pts']})."
        if "counter" in d:
            p += f" {d['counter']} {'took' if d['direction'] == 'lost' else 'gave up'} the largest share ({d['counter_pts']})."
        if "effect" in d:
            p += (f" Since {d['since']} (the change point a model estimates), sales differ from the model's path "
                  f"without the shift by {d['effect']} ({d['effect_rel']}).")
        parts.append(p)
    out["What moved"] = " ".join(parts) or "No shift made the brief this week."
    out["Emerging shifts"] = (" ".join(f"{e['brand']} is {e['dir']} at {e['retailer']} ({e['chg']}, flagged {e['weeks']} "
                                       f"weeks ago by the weekly scan) and no {tok(6)} report shows it yet."
                                       for e in pk.emerging)
                              or "Nothing is building outside its normal range ahead of the reports.")
    out["Held back for data checks"] = (" ".join(f"{h['brand']} in {h['market']} ({h['pts']}) was held back as a possible "
                                                 "data effect; check the data rules before acting on it." for h in pk.held)
                                        or "No shift was held back for data checks.")
    rivals = [d for d in pk.shifts if "rival" in d]
    out["Competitive landscape"] = (" ".join(f"{d['brand']} trades share most directly with {d['rival']} (correlation "
                                             f"{d['rival_corr']} in week-on-week share changes, a model estimate)."
                                             for d in rivals) or "No strong share trade-off between brands this week.")
    looks = [d for d in pk.shifts if "outlook" in d]
    out["Outlook"] = (" ".join(f"If nothing changes, {d['brand']}'s weekly sales move {d['outlook']} over the next "
                               f"{tok(5)} (a projection of the measured pattern, not a plan)." for d in looks)
                      or "No projection available.")
    acts = [d for d in pk.shifts if "action" in d]
    out["Recommended actions"] = (" ".join(f"For {d['brand']}: {d['action']}, worth about {d['action_v']} a "
                                           "week (a model estimate from the brand's own elasticities)." for d in acts)
                                  or "No action could be modelled this week.")
    return out


# ---- validate and render --------------------------------------------------------------------------------------------

NUMBER_WORDS = re.compile(r"\bone\s+(?:point|pts|percent|per cent|week|month|year|million|thousand|billion|in\s+\w+)\b|"
                          r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                          r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|dozen|hundred|"
                          r"thousand|million|billion|half|halved|double|doubled|twice|triple|tripled|quarter|"
                          r"percent|per cent|percentage)\b", re.I)
UNIT_AFTER = re.compile(r"F\d+\]\s*(%|pts?\b|points?\b|percent|percentage|bps\b)", re.I)
SIGN_OR_MONEY_BEFORE = re.compile(r"([-+−]|\b(?:INR|Rs\.?|USD|EUR|GBP)|[₹$€£])\s*\[F\d", re.I)
ESTIMATE = re.compile(r"estimat|model|project|scan|correlat", re.I)


def problems(text: str, pk: Pack) -> list[str]:
    """Why a section text cannot be shown: a figure that is not a fact token (digits outside a token or a known name,
    or a number word), a token that is not in the pack, a sign, currency or unit added to a fact that already carries
    its own, or a model figure in a sentence that does not call it an estimate."""
    out = []
    bare = TOKEN.sub("", text)
    for name in sorted(pk.names, key=len, reverse=True):         # a digit inside a known name is part of the name
        bare = bare.replace(name, "")
    if re.search(r"\d", bare):
        out.append("a number written without a fact token")
    if NUMBER_WORDS.search(bare):
        out.append("a number written as a word")
    unknown = [t for t in TOKEN.findall(text) if t not in pk.facts]
    if unknown:
        out.append("unknown fact " + ", ".join(unknown))
    if SIGN_OR_MONEY_BEFORE.search(text) or UNIT_AFTER.search(text):
        out.append("a sign, currency or unit added to a fact that already carries one")
    for sentence in re.split(r"(?<=[.!?;])\s+", text):           # each model figure is called an estimate where it is
        if any(pk.facts.get(t, {}).get("model") for t in TOKEN.findall(sentence)) and not ESTIMATE.search(sentence):
            out.append("a model figure not called an estimate")
            break
    return out


def narrative(pk: Pack, use_llm: bool = True) -> tuple[dict[str, str], str]:
    """(section texts with tokens, generator label). The LLM when offered, checked section by section; the template
    for any section it gets wrong, and for everything when there is no LLM."""
    base = template(pk)
    narrate = getattr(data, "narrate", None) if use_llm else None
    if narrate is None:
        return base, "Template (numbers locked)"
    listing = {k: f"{v['label']} = {v['text']}" + (" (model estimate)" if v["model"] else "") for k, v in pk.facts.items()}
    try:
        got = narrate(listing, OUTLINE, base)
    except Exception:                                            # noqa: BLE001 - fall back to the template
        return base, "Template (the AI narrative was unavailable)"
    out, fixed = {}, 0
    for sec in OUTLINE:
        t = got.get(sec, "")
        if t and not problems(t, pk):
            out[sec] = t
        else:
            out[sec], fixed = base[sec], fixed + 1
    label = "AI narrative (numbers locked)" + (f"; {fixed} section{'s' if fixed > 1 else ''} from the template" if fixed else "")
    return out, label


def render(text: str, pk: Pack) -> str:
    """HTML for one section: each token becomes its value with the fact's label and source on hover."""
    def one(m):
        f = pk.facts[m.group(1)]
        return (f'<span class="fact{" model" if f["model"] else ""}" title="{escape(f["label"])} · {escape(f["source"])}">'
                f'{escape(f["text"])}</span>')
    return TOKEN.sub(one, escape(text).replace("&#x27;", "'"))


def plain(text: str, pk: Pack) -> str:
    return TOKEN.sub(lambda m: pk.facts[m.group(1)]["text"], text)
