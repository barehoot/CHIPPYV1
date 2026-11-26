"""My workspace: the viewer's watchlist and case files, kept in st.session_state only (decision 2026-11-25, option a).

Nothing here is written to Snowflake: no table, no grant, no query. The state lasts while the browser tab keeps its
Streamlit session; a refresh or a new tab starts empty, and nothing is shared with other viewers. Every page that shows
this state says so (SESSION_NOTE). Items are keyed by brand x market x comparison, so a followed shift is found again
in later runs, whose shift IDs differ.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

STATE = "sr_ws"
STATUSES = ["Open", "Monitoring", "Resolved"]
SESSION_NOTE = ("Session only: Kept while this browser tab stays open. Refreshing or closing the tab clears it. "
                "Nothing is saved to Snowflake or shared with anyone.")


def _ws() -> dict:
    return st.session_state.setdefault(STATE, {"watch": {}, "cases": {}})


def key(brand: str, market_id: str, cmp_code: str) -> str:
    return f"{brand}|{market_id}|{cmp_code}"


def row_key(row) -> str:
    return key(row["BRAND"], row["MARKET_ID"], row["CMP_CODE"])


# ---- Watchlist ----------------------------------------------------------------------------------------------------

def watched() -> dict[str, dict]:
    return _ws()["watch"]


def is_watched(k: str) -> bool:
    return k in watched()


def add_watch(row, run_id: str) -> str:
    k = row_key(row)
    watched().setdefault(k, {"brand": row["BRAND"], "market_id": row["MARKET_ID"], "cmp_code": row["CMP_CODE"],
                             "category": row.get("CATEGORY"), "run_id": run_id, "added": datetime.now()})
    return k


def remove_watch(k: str) -> None:
    watched().pop(k, None)


# ---- Case files -----------------------------------------------------------------------------------------------------

def cases() -> dict[str, dict]:
    return _ws()["cases"]


def open_case(row, run_id: str, as_of_week) -> str:
    """Open (or reopen) the case for a shift and make it the selected case."""
    k = row_key(row)
    cases().setdefault(k, {"brand": row["BRAND"], "market_id": row["MARKET_ID"], "cmp_code": row["CMP_CODE"],
                           "shift_id": row["SHIFT_ID"], "run_id": run_id, "as_of_week": as_of_week,
                           "opened": datetime.now(), "reviewed": False, "status": "Open", "notes": [],
                           "events": [(datetime.now(), "Case opened")]})
    st.session_state["sr_case"] = k
    st.session_state["sr_case_new"] = True                  # Case Files shows a one-time success line
    return k


def add_note(k: str, text: str) -> None:
    c = cases().get(k)
    if c is not None and text.strip():
        c["notes"].append({"at": datetime.now(), "text": text.strip()})
        log(k, "Note added")


def log(k: str, what: str) -> None:
    """Record one action the viewer took on a case this session (the case timeline)."""
    c = cases().get(k)
    if c is not None:
        c.setdefault("events", []).append((datetime.now(), what))


def close_case(k: str) -> None:
    """Remove a case; the Case Files page picks another on its next run (its selector cannot be changed mid-run)."""
    cases().pop(k, None)


# ---- Outcome of a followed item in one run (display only; reads the run's own ranking fields) ----------------------

def find(shifts: pd.DataFrame, k: str) -> dict | None:
    brand, market_id, cmp_code = k.split("|", 2)
    m = shifts[(shifts.BRAND == brand) & (shifts.MARKET_ID == market_id) & (shifts.CMP_CODE == cmp_code)]
    return None if m.empty else m.iloc[0].to_dict()


def outcome(row: dict | None) -> tuple[str, str]:
    """(text, tone) for a shift row in one run, in the SP_RANK reason order: in the brief, repeat, held for data
    checks, another comparison ranks higher, beyond the top N; or not among the shifts that passed the gates."""
    if row is None:
        return "Not among the shifts that passed the gates", ""
    if bool(row.get("SELECTED")):
        return f"In the brief · rank {int(row['RANK_NO'])}", "ok"
    reason = row.get("SUPPRESS_REASON")
    if bool(row.get("SUPPRESSED")):
        return (str(reason) if reason is not None and not pd.isna(reason) else "Repeat of an earlier week"), ""
    if row.get("ARTEFACT_LABEL") == "POSSIBLE_DATA_EFFECT":
        return "Held back for data checks", "bad"
    if reason is not None and not pd.isna(reason):
        return str(reason), ""
    return "Passed the gates, beyond the brief's top N", ""
