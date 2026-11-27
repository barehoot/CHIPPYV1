"""Auto mode on Ask Chippy: pick the agent for a question with a fixed keyword rule (no LLM, no data access).

Chippy (Ask-Why) explains share shifts: why, drivers, who took share, real or data effect, what-if, this week's brief.
The Data analyst answers open business questions as tables: rankings, comparisons, totals by retailer or period.
Chippy Geo answers where share moved (cities, regions, states, the map) and how it developed over several years.
Four specialists: the Recovery Strategist (plans), Pricing & Promo, Forecast & Risk, and Competitive benchmarking.
The rule scores every agent, breaks ties towards Chippy, and returns the words that decided it, so the page can show why.
"""
from __future__ import annotations

import re

CHIPPY = "SR_DB.SEM.SHARE_RADAR_AGENT"
ANALYST = "SR_DB.SEM.RADAR_ANALYST_AGENT"
GEO = "SR_DB.SEM.GEO_MARKET_AGENT"
RECOVERY = "SR_DB.SEM.RECOVERY_AGENT"
PRICE = "SR_DB.SEM.PRICE_PROMO_AGENT"
RISK = "SR_DB.SEM.FORECAST_RISK_AGENT"
COMPETITOR = "SR_DB.SEM.COMPETITOR_AGENT"
ORDER = (CHIPPY, ANALYST, GEO, RECOVERY, PRICE, RISK, COMPETITOR)   # tie-break order: earlier wins

_CITIES = ("delhi|lucknow|jaipur|bengaluru|bangalore|chennai|hyderabad|kolkata|bhubaneswar|patna|mumbai|pune|"
           "ahmedabad")
_STATES = ("uttar pradesh|rajasthan|karnataka|tamil nadu|telangana|west bengal|odisha|bihar|maharashtra|gujarat")

# (pattern, weight, reason shown to the viewer)
_RULES: dict[str, list[tuple[str, float, str]]] = {
    CHIPPY: [
        (r"\bwhy\b", 3, "a why question"),
        (r"\b(lose|lost|losing|loss|gain|gained|gaining|drop|dropped|decline|fell|grew)\b", 1.5, "a share move"),
        (r"\b(driver|drivers|bridge|cause|caused|explain|reason)\b", 2, "drivers of a move"),
        (r"\b(who took|took the share|came from|share flow|switch(ed|ing)?)\b", 2.5, "share flow"),
        (r"\b(real|artefact|artifact|data effect|data issue|trust)\b", 2.5, "a data check"),
        (r"\b(what if|scenario|restore|if .* (went|goes|were))\b", 2.5, "a what-if"),
        (r"\b(brief|this week|what changed|shift|shifts|held back|early warning)\b", 1.5, "this week's shifts"),
    ],
    ANALYST: [
        (r"\b(top|bottom|highest|lowest|best|worst|rank|ranking|leaderboard|largest|smallest)\b", 2.5, "a ranking"),
        (r"\b(compare|comparison|versus|vs\.?|against)\b", 1.2, "a comparison"),
        (r"\b(by retailer|by region|by brand|by manufacturer|by segment|by pack|by week|by month|per retailer)\b", 2.5,
         "a breakdown"),
        (r"\b(how much|how many|total|sum|average|sales of|value sales|unit sales|volume)\b", 2, "a total or measure"),
        (r"\b(show|list|table|which brands|which manufacturers|which retailers)\b", 1.5, "a table request"),
        (r"\b(last \d+ weeks|last year|year ago|over the last|trend of|over time)\b", 0.8, "a period"),
    ],
    GEO: [
        (r"\b(city|cities|town|towns|metro|metros|state|states|geograph\w*|map)\b", 2.5, "a city or map question"),
        (rf"\b({_CITIES})\b", 3, "a named city"),
        (rf"\b({_STATES})\b", 2.5, "a named state"),
        (r"\b(where|which (north|south|east|west)|regions|regional|across india)\b", 1.5, "where it happened"),
        (r"\b(since (19|20)\d\d|\d+ years|over the years|year by year|yearly|annual|multi-year|long[- ]term)\b", 3,
         "a multi-year trend"),
    ],
    RECOVERY: [
        (r"\b(recover|recovery|win back|winning back|regain|fix|turn around|turnaround|salvage|rescue)\b", 3.5,
         "a recovery question"),
        (r"\b(plan|action plan|what should we do|what do we do|next steps|how do we|how can we)\b", 2.5, "an action plan"),
    ],
    PRICE: [
        (r"\b(price|prices|pricing|priced|price index|price gap|premium|discount|cheaper|expensive)\b", 3, "a pricing question"),
        (r"\b(promo|promos|promotion|promotions|promotional|deal|deals|offer|lift)\b", 3, "a promotion question"),
    ],
    RISK: [
        (r"\b(risk|risks|risky|warning|warnings|early warning|outlook|forecast|next month|next quarter|threat)\b", 3.5,
         "a risk or outlook question"),
        (r"\b(seasonal|seasonality|going to|will .* (fall|drop|decline)|could go wrong)\b", 2.5, "what comes next"),
    ],
    COMPETITOR: [
        (r"\b(competitor|competitors|competition|competitive|rival|rivals|benchmark|benchmarking|league table)\b", 3.5,
         "a competitor question"),
        (r"\b(who is winning|who is leading|market leader|against (its|our) rivals|manufacturer \d|company)\b", 2.5,
         "a company comparison"),
    ],
}


def route(question: str) -> tuple[str, str]:
    """(agent id, short reason) for a question. Ties and questions with no signal go to Chippy, the default agent."""
    q = (question or "").lower()
    scores = {agent: 0.0 for agent in _RULES}
    why: dict[str, list[str]] = {agent: [] for agent in _RULES}
    for agent, rules in _RULES.items():
        for pattern, weight, reason in rules:
            if re.search(pattern, q):
                scores[agent] += weight
                if reason not in why[agent]:
                    why[agent].append(reason)
    # Highest score wins; ties go to the earlier agent in ORDER (Chippy first)
    agent = max(ORDER, key=lambda a: (scores[a], -ORDER.index(a)))
    reasons = why[agent][:2]
    if not reasons:
        return agent, "no clear signal, so the default agent"
    return agent, " and ".join(reasons)
