"""Auto mode on Ask Chippy: pick the agent for a question with a fixed keyword rule (no LLM, no data access).

Chippy (Ask-Why) explains share shifts: why, drivers, who took share, real or data effect, what-if, this week's brief.
The Data analyst answers open business questions as tables: rankings, comparisons, totals by retailer or period.
The rule scores both, breaks ties towards Chippy, and returns the words that decided it, so the page can show why.
"""
from __future__ import annotations

import re

CHIPPY = "SR_DB.SEM.SHARE_RADAR_AGENT"
ANALYST = "SR_DB.SEM.RADAR_ANALYST_AGENT"

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
}


def route(question: str) -> tuple[str, str]:
    """(agent id, short reason) for a question. Ties and questions with no signal go to Chippy, the default agent."""
    q = (question or "").lower()
    scores, why = {CHIPPY: 0.0, ANALYST: 0.0}, {CHIPPY: [], ANALYST: []}
    for agent, rules in _RULES.items():
        for pattern, weight, reason in rules:
            if re.search(pattern, q):
                scores[agent] += weight
                if reason not in why[agent]:
                    why[agent].append(reason)
    agent = ANALYST if scores[ANALYST] > scores[CHIPPY] else CHIPPY
    reasons = why[agent][:2]
    if not reasons:
        return agent, "no clear signal, so the default agent"
    return agent, " and ".join(reasons)
