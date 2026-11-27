"""Every query and action of the two apps (L11). Bind values with params; never format user input into SQL.

Reads are cached per viewer session (st.cache_data, TTL_S); run and step reads are not cached, because they drive
the progress panel; actions are never cached and clear the cache after them. The apps run with their owner's
rights, so the read-only app (SR_UI) can only read, and only the admin app (SR_APP) can execute tasks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

TTL_S = 120             # per viewer session on the warehouse runtime
BUSY_MIN = 30           # a RUNNING run younger than this blocks replay and rerun
TASKS = {"T_REPLAY_NEXT", "T_RUN_WEEK_MANUAL", "T_RUN_WEEK", "T_HEALTH"}
STARTABLE = {"T_REPLAY_NEXT", "T_RUN_WEEK_MANUAL", "T_HEALTH"}


@dataclass(frozen=True)
class Run:
    run_id: str
    trigger_type: str           # STREAM | REPLAY | MANUAL
    as_of_week: date | None
    scope_key: str | None
    status: str                 # RUNNING | SUCCEEDED | FAILED | SKIPPED
    bridge_mode: str | None
    n_candidates: int | None
    n_ranked: int | None
    brief_id: str | None
    credits_est: float | None
    started_at: pd.Timestamp
    ended_at: pd.Timestamp | None
    error_msg: str | None


class Busy(Exception):
    """A run is in progress; replay and rerun wait for it."""


def session():
    from snowflake.snowpark.context import get_active_session
    return get_active_session()


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    return session().sql(sql, params=params).to_pandas()


def _one(sql: str, params: list | None = None) -> dict | None:
    df = q(sql, params)
    return None if df.empty else df.iloc[0].to_dict()


def _variant(v):
    """VARIANT columns arrive as JSON text."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


# ---- Context (cached) -----------------------------------------------------------------------------------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def _settings_map() -> dict[str, object]:
    df = q("SELECT SETTING_KEY, TO_JSON(SETTING_VALUE) AS VALUE_JSON FROM SR_DB.OPS.SETTINGS")
    return {k: json.loads(v) for k, v in zip(df.SETTING_KEY, df.VALUE_JSON)}


def cfg(key: str) -> object:
    return _settings_map().get(key)


def scope_key() -> str:
    return f"{cfg('SCOPE_CATEGORY')}|{cfg('SCOPE_PARENT_MARKET')}|{cfg('FOCUS_MANUFACTURER')}"


# ---- Sidebar filters (session state; defaults are the configured scope, so nothing changes until a viewer picks) ----

PERIODS = (4, 12, 26, 52, 104)
_F_KEYS = ("sr_f_week", "sr_f_cat", "sr_f_mfr", "sr_f_brand", "sr_f_market", "sr_f_period")


@dataclass(frozen=True)
class Filters:
    as_of: str              # ISO week-end date the analysis looks back from (never after AS_OF_WEEK_END)
    category: str
    manufacturer: str | None
    brand: str | None
    market_id: str          # TOTAL, a region or a city
    weeks: int              # analysis period


def filters() -> Filters:
    ss = st.session_state
    week = ss.get("sr_f_week") or str(cfg("AS_OF_WEEK_END"))
    return Filters(as_of=str(week), category=ss.get("sr_f_cat") or str(cfg("SCOPE_CATEGORY")),
                   manufacturer=ss.get("sr_f_mfr", cfg("FOCUS_MANUFACTURER")) or None,
                   brand=ss.get("sr_f_brand") or None,
                   market_id=ss.get("sr_f_market") or str(cfg("SCOPE_PARENT_MARKET")),
                   weeks=int(ss.get("sr_f_period") or 4))


def filters_active() -> bool:
    """True when the viewer moved any filter away from the configured scope."""
    f = filters()
    return (f.as_of != str(cfg("AS_OF_WEEK_END")) or f.category != str(cfg("SCOPE_CATEGORY"))
            or f.manufacturer != (cfg("FOCUS_MANUFACTURER") or None) or f.brand is not None
            or f.market_id != str(cfg("SCOPE_PARENT_MARKET")))


def reset_filters() -> None:
    for k in _F_KEYS:
        st.session_state.pop(k, None)


@st.cache_data(ttl=TTL_S, show_spinner=False)
def filter_weeks() -> list[str]:
    """Every data week up to the replay position, newest first (2020 onwards)."""
    df = q("SELECT TO_VARCHAR(WEEK_END_DATE) AS W FROM SR_DB.APP.V_UI_WEEKS WHERE WEEK_END_DATE <= TRY_TO_DATE(?) "
           "ORDER BY WEEK_END_DATE DESC", [str(cfg("AS_OF_WEEK_END"))])
    return list(df.W)


@st.cache_data(ttl=TTL_S, show_spinner=False)
def product_tree() -> pd.DataFrame:
    return q("SELECT CATEGORY, MANUFACTURER, BRAND FROM SR_DB.APP.V_UI_PRODUCT_TREE ORDER BY CATEGORY, MANUFACTURER, BRAND")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def market_tree() -> pd.DataFrame:
    return q("SELECT MARKET_ID, MARKET_NAME, MARKET_LEVEL, PARENT_MARKET_ID, REGION, CITY FROM SR_DB.SRC.V_SRC_MARKET "
             "ORDER BY IFF(MARKET_LEVEL = 'TOTAL', 0, 1), REGION, IFF(MARKET_LEVEL = 'CITY', 1, 0), MARKET_NAME")


def _children_clause(alias: str = "s") -> tuple[str, list]:
    """SQL condition and binds for the markets the filtered market splits into: its children when it has any
    (All India -> regions, a region -> its cities), else the market itself. The SQL text is fixed; only binds vary."""
    m = filters().market_id
    tree = market_tree()
    if (tree.PARENT_MARKET_ID == m).any():
        return f"{alias}.MARKET_ID IN (SELECT MARKET_ID FROM SR_DB.SRC.V_SRC_MARKET WHERE PARENT_MARKET_ID = ?)", [m]
    return f"{alias}.MARKET_ID = ?", [m]


@st.cache_data(ttl=TTL_S, show_spinner=False)
def _qc(sql: str, params: tuple) -> pd.DataFrame:
    """Cached read keyed by its SQL and binds, so a filter change (week, market) is a new cache entry."""
    return q(sql, list(params))


def viewer_name() -> str | None:
    """Kept in this viewer's session, never in the shared cache: on a shared (container) runtime a cached value would
    show one viewer's name to everyone."""
    if "_sr_viewer" not in st.session_state:
        try:
            st.session_state["_sr_viewer"] = q("SELECT CURRENT_USER() AS U").U.iloc[0]
        except Exception:                    # needs READ SESSION on the owner role (L11)
            st.session_state["_sr_viewer"] = None
    return st.session_state["_sr_viewer"]


@st.cache_data(ttl=TTL_S, show_spinner=False)
def aliases() -> dict[tuple[str, str], str]:
    df = q("SELECT KIND, REAL_NAME, ALIAS FROM SR_DB.APP.V_ALIAS")
    return {(k, r): a for k, r, a in zip(df.KIND, df.REAL_NAME, df.ALIAS)}


@st.cache_data(ttl=TTL_S, show_spinner=False)
def market_names() -> dict[str, str]:
    df = q("SELECT MARKET_ID, MARKET_NAME FROM SR_DB.SRC.V_SRC_MARKET")
    return dict(zip(df.MARKET_ID, df.MARKET_NAME))


@st.cache_data(ttl=TTL_S, show_spinner=False)
def total_market_name(market_id: str) -> str | None:
    row = _one("""SELECT MARKET_NAME FROM SR_DB.SRC.V_SRC_MARKET
                    WHERE MARKET_ID = ? AND MARKET_LEVEL = 'TOTAL' AND PARENT_MARKET_ID IS NULL""", [market_id])
    return row["MARKET_NAME"] if row else None


@st.cache_data(ttl=TTL_S, show_spinner=False)
def city_shares(cmp_code: str, category: str, brand: str) -> pd.DataFrame:
    """City markets with coordinates for one brand and comparison (Market View points)."""
    return q("""SELECT MARKET_ID, CITY, REGION, STATE, STATE_CODE, LATITUDE, LONGITUDE, SH1, SH0, D_SHARE, VALUE_AT_STAKE
                FROM SR_DB.APP.V_UI_CITY_SHARE
                WHERE CMP_CODE = ? AND CATEGORY = ? AND BRAND = ?
                ORDER BY CITY""", [cmp_code, category, brand])


# ---- Runs (not cached: they drive the progress panel) ---------------------------------------------------------

_RUN_COLS = ("RUN_ID, TRIGGER_TYPE, AS_OF_WEEK, SCOPE_KEY, STATUS, BRIDGE_MODE, N_CANDIDATES, N_RANKED, BRIEF_ID, "
             "CREDITS_EST, STARTED_AT, ENDED_AT, ERROR_MSG")


def _run(row: dict | None) -> Run | None:
    if not row:
        return None
    clean = {k.lower(): (None if (v is None or (isinstance(v, float) and pd.isna(v))) else v) for k, v in row.items()}
    return Run(**clean)


def current_run() -> Run | None:
    """The newest SUCCEEDED run, preferring the sidebar's as-of week (default: the configured week) and scope."""
    week = st.session_state.get("sr_f_week") or str(cfg("AS_OF_WEEK_END"))
    return _run(_one(f"SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG WHERE STATUS = 'SUCCEEDED' "
                     "ORDER BY IFF(AS_OF_WEEK = TRY_TO_DATE(?), 0, 1), IFF(SCOPE_KEY = ?, 0, 1), STARTED_AT DESC LIMIT 1",
                     [str(week), scope_key()]))


def run_for_week(week: str) -> Run | None:
    """The newest successful stored run for that as-of week, or None (the analysis views still cover the week)."""
    return _run(_one(f"SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG WHERE STATUS = 'SUCCEEDED' AND AS_OF_WEEK = TRY_TO_DATE(?) "
                     "ORDER BY STARTED_AT DESC LIMIT 1", [str(week)]))


def latest_attempt() -> Run | None:
    """The newest run of any status for the current as-of week (drives the 'data has not arrived' banner)."""
    return _run(_one(f"SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG WHERE AS_OF_WEEK = TRY_TO_DATE(?) "
                     "ORDER BY STARTED_AT DESC LIMIT 1", [str(cfg("AS_OF_WEEK_END"))]))


def active_run() -> Run | None:
    return _run(_one(f"SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG WHERE STATUS = 'RUNNING' "
                     f"AND STARTED_AT > DATEADD(minute, -{BUSY_MIN}, CURRENT_TIMESTAMP()) ORDER BY STARTED_AT DESC LIMIT 1"))


def run_started_since(since: str) -> Run | None:
    return _run(_one(f"SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG WHERE STARTED_AT >= TO_TIMESTAMP_LTZ(?) "
                     "ORDER BY STARTED_AT DESC LIMIT 1", [since]))


def step_log(run_id: str) -> pd.DataFrame:
    return q("SELECT STEP_NO, STEP, STATUS, STARTED_AT, ENDED_AT, ROWS_WRITTEN, MESSAGE, "
             "DATEDIFF(second, STARTED_AT, COALESCE(ENDED_AT, CURRENT_TIMESTAMP())) AS SECONDS "
             "FROM SR_DB.OPS.STEP_LOG WHERE RUN_ID = ? ORDER BY STARTED_AT, STEP_NO", [run_id])


def task_last_run(task: str) -> dict | None:
    if task not in TASKS:
        raise ValueError(f"Unknown task {task}")
    return _one("SELECT STATE, ERROR_MESSAGE, SCHEDULED_TIME, COMPLETED_TIME "
                f"FROM TABLE(SR_DB.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => '{task}', RESULT_LIMIT => 1))")


# ---- Radar (cached) -------------------------------------------------------------------------------------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def _shifts(run_id: str) -> pd.DataFrame:
    return q("""SELECT r.SHIFT_ID, r.RANK_NO, r.CMP_CODE, r.MARKET_ID, r.CATEGORY, r.MANUFACTURER, r.BRAND, r.IS_FOCUS,
                       c.SH1, c.SH0, 100 * r.D_SHARE AS D_SHARE_PTS, r.VALUE_AT_STAKE, c.Z_SCORE, c.ANOMALY_CONFIRMED,
                       r.CONFIDENCE, r.ARTEFACT_LABEL, r.SCORE, r.SUPPRESSED, r.SUPPRESS_REASON, r.SELECTED
                FROM SR_DB.APP.SHIFT_RANKED r
                JOIN SR_DB.APP.SHIFT_CANDIDATE c ON c.RUN_ID = r.RUN_ID AND c.SHIFT_ID = r.SHIFT_ID
                WHERE r.RUN_ID = ? ORDER BY r.SELECTED DESC, r.SCORE DESC""", [run_id])


def shifts(run_id: str) -> pd.DataFrame:
    """The run's ranked shifts, narrowed by the sidebar filters the viewer set (company, brand, market and the
    markets under it). Untouched filters narrow nothing, so the default view is every shift of the run."""
    df = _shifts(run_id)
    ss = st.session_state
    if ss.get("sr_f_mfr"):
        df = df[df.MANUFACTURER == ss["sr_f_mfr"]]
    if ss.get("sr_f_brand"):
        df = df[df.BRAND == ss["sr_f_brand"]]
    m = ss.get("sr_f_market")
    if m and m != str(cfg("SCOPE_PARENT_MARKET")):
        tree = market_tree()
        keep = {m} | set(tree[tree.PARENT_MARKET_ID == m].MARKET_ID)
        keep |= set(tree[tree.PARENT_MARKET_ID.isin(keep)].MARKET_ID)
        df = df[df.MARKET_ID.isin(keep)]
    return df


@st.cache_data(ttl=TTL_S, show_spinner=False)
def held_back(run_id: str) -> pd.DataFrame:
    """POSSIBLE_DATA_EFFECT shifts, one per brand x market (B05), top 3 by SCORE, with the HIGH rules that matched
    them (the SP_RANK match)."""
    df = q("""SELECT r.SHIFT_ID, r.CMP_CODE, r.MARKET_ID, r.BRAND, 100 * ANY_VALUE(r.D_SHARE) AS D_SHARE_PTS,
                     ANY_VALUE(r.SCORE) AS SCORE, ARRAY_AGG(DISTINCT a.RULE_ID) AS RULES
              FROM SR_DB.APP.SHIFT_RANKED r
              LEFT JOIN SR_DB.APP.ARTEFACT_CHECK a
                ON a.RUN_ID = r.RUN_ID AND a.CMP_CODE = r.CMP_CODE AND a.MARKET_ID = r.MARKET_ID
               AND a.CATEGORY = r.CATEGORY AND (a.BRAND IS NULL OR a.BRAND = r.BRAND) AND a.SEVERITY = 'HIGH'
              WHERE r.RUN_ID = ? AND r.ARTEFACT_LABEL = 'POSSIBLE_DATA_EFFECT'
              GROUP BY r.SHIFT_ID, r.CMP_CODE, r.MARKET_ID, r.BRAND
              QUALIFY ROW_NUMBER() OVER (PARTITION BY r.MARKET_ID, r.BRAND ORDER BY ANY_VALUE(r.SCORE) DESC) = 1
              ORDER BY SCORE DESC LIMIT 3""", [run_id])
    df["RULES"] = [_variant(v) or [] for v in df.RULES]
    return df


@st.cache_data(ttl=TTL_S, show_spinner=False)
def watchlist(run_id: str) -> pd.DataFrame:
    return q("""SELECT MARKET_ID, CATEGORY, BRAND, SIGNAL, LATEST_WEEK, LEVER_LATEST, LEVER_L4W, LEVER_CHG, PROJECTED_SHARE_PTS,
                       ML_CONFIRMED, NOTE
                FROM SR_DB.APP.EARLY_WARNING WHERE RUN_ID = ?
                ORDER BY ABS(COALESCE(PROJECTED_SHARE_PTS, 0)) DESC, ABS(LEVER_CHG) DESC""", [run_id])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def kpis(run_id: str) -> dict[str, float]:
    row = _one("""SELECT (SELECT COUNT_IF(PASSED_GATES) FROM SR_DB.APP.SHIFT_CANDIDATE WHERE RUN_ID = ?) AS N_PASSED,
                         COUNT_IF(SELECTED) AS N_SELECTED, COUNT_IF(ARTEFACT_LABEL = 'POSSIBLE_DATA_EFFECT') AS N_DATA_EFFECT,
                         SUM(IFF(SELECTED, ABS(VALUE_AT_STAKE), 0)) AS VALUE_SELECTED
                  FROM SR_DB.APP.SHIFT_RANKED WHERE RUN_ID = ?""", [run_id, run_id]) or {}
    return {k: (0 if v is None or pd.isna(v) else float(v)) for k, v in row.items()}


# ---- Shift detail (cached, except what_if) --------------------------------------------------------------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def shift(shift_id: str) -> dict:
    return _one("""SELECT r.RUN_ID, r.SHIFT_ID, r.RANK_NO, r.CMP_CODE, r.MARKET_ID, r.CATEGORY, r.MANUFACTURER, r.BRAND,
                          r.IS_FOCUS, r.D_SHARE, 100 * r.D_SHARE AS D_SHARE_PTS, r.VALUE_AT_STAKE, r.CONFIDENCE,
                          r.ARTEFACT_LABEL, r.SCORE, r.SUPPRESSED, r.SUPPRESS_REASON, r.SELECTED,
                          c.SH1, c.SH0, c.Z_SCORE, c.ANOMALY_WEEKS, c.ANOMALY_CONFIRMED, b.MODE, b.STATUS, b.NOTE
                   FROM SR_DB.APP.SHIFT_RANKED r
                   JOIN SR_DB.APP.SHIFT_CANDIDATE c ON c.RUN_ID = r.RUN_ID AND c.SHIFT_ID = r.SHIFT_ID
                   LEFT JOIN SR_DB.APP.SHARE_BRIDGE b ON b.RUN_ID = r.RUN_ID AND b.SHIFT_ID = r.SHIFT_ID
                   WHERE r.SHIFT_ID = ?""", [shift_id]) or {}


@st.cache_data(ttl=TTL_S, show_spinner=False)
def bridge(shift_id: str) -> dict | None:
    return _one("""SELECT SHIFT_ID, MODE, STATUS, SH1, SH0, D_SHARE, LMDI_WEIGHT, DIST_PTS, VELOCITY_PTS, PRICE_PTS,
                          PROMO_PTS, RESIDUAL_PTS, DS1, DS0, PI1, PI0, PRI1, PRI0, NOTE
                   FROM SR_DB.APP.SHARE_BRIDGE WHERE SHIFT_ID = ?""", [shift_id])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def where(shift_id: str) -> pd.DataFrame:
    return q("""SELECT METHOD, RANK_NO, CONTRIBUTOR, PERF_PTS, MIX_PTS, TOTAL_PTS, METRIC_CONTROL, METRIC_TEST,
                       CONTRIBUTION, RELATIVE_CONTRIBUTION, GROWTH_RATE
                FROM SR_DB.APP.SHIFT_WHERE WHERE SHIFT_ID = ? ORDER BY METHOD, RANK_NO""", [shift_id])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def flow(run_id: str, cmp_code: str, market_id: str, category: str, brand: str, direction: str) -> pd.DataFrame:
    """LOSS: TO_BRAND AS COUNTERPART where FROM_BRAND = brand; GAIN: FROM_BRAND AS COUNTERPART where TO_BRAND = brand."""
    mine, other = ("FROM_BRAND", "TO_BRAND") if direction == "LOSS" else ("TO_BRAND", "FROM_BRAND")
    return q(f"""SELECT {other} AS COUNTERPART, FLOW_PTS FROM SR_DB.APP.SHARE_FLOW
                 WHERE RUN_ID = ? AND CMP_CODE = ? AND MARKET_ID = ? AND CATEGORY = ? AND {mine} = ?
                 ORDER BY FLOW_PTS DESC LIMIT 8""", [run_id, cmp_code, market_id, category, brand])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def artefacts(run_id: str, cmp_code: str, market_id: str, category: str, brand: str) -> pd.DataFrame:
    df = q("""SELECT RULE_ID, SEVERITY, BRAND, EVIDENCE FROM SR_DB.APP.ARTEFACT_CHECK
              WHERE RUN_ID = ? AND CMP_CODE = ? AND MARKET_ID = ? AND CATEGORY = ? AND (BRAND IS NULL OR BRAND = ?)
              ORDER BY SEVERITY, RULE_ID""", [run_id, cmp_code, market_id, category, brand])
    df["EVIDENCE"] = [_variant(v) for v in df.EVIDENCE]
    return df


def trend(market_id: str, category: str, brand: str, weeks: int = 104) -> pd.DataFrame:
    return _qc("""SELECT WEEK_END_DATE, 100 * VALUE_SHARE AS VALUE_SHARE_PCT, 100 * DIST_SHARE AS DIST_SHARE_PCT
                FROM SR_DB.APP.V_UI_SHARE_WEEK WHERE MARKET_ID = ? AND CATEGORY = ? AND BRAND = ?
                  AND WEEK_END_DATE <= TRY_TO_DATE(?)
                QUALIFY ROW_NUMBER() OVER (ORDER BY WEEK_END_DATE DESC) <= ? ORDER BY WEEK_END_DATE""",
               (market_id, category, brand, filters().as_of, weeks))


def what_if(shift_id: str, lever: str, target: str) -> dict:
    r = session().call("SR_DB.APP.SP_WHAT_IF", shift_id, lever, target)
    return r if isinstance(r, dict) else json.loads(r)


# ---- Shift analysis tabs (cached; read the APP.V_UI_* views from 40_app/416) -----------------------------------

def brand_sales_week(market_id: str, category: str, brand: str) -> pd.DataFrame:
    """Weekly value, unit sales and SKUs selling for one brand in one market (any level), oldest first, up to the
    filter week."""
    return _qc("""SELECT WEEK_END_DATE, SUM(VALUE_SALES) AS VALUE_SALES, SUM(UNIT_SALES) AS UNIT_SALES,
                       COUNT_IF(VALUE_SALES > 0) AS SKUS_SELLING
                FROM SR_DB.APP.V_UI_SKU_WEEK WHERE MARKET_ID = ? AND CATEGORY = ? AND BRAND = ?
                  AND WEEK_END_DATE <= TRY_TO_DATE(?)
                GROUP BY WEEK_END_DATE ORDER BY WEEK_END_DATE""", (market_id, category, brand, filters().as_of))


def region_summary(category: str, brand: str, weeks: int = 4) -> pd.DataFrame:
    """Per market the filtered market splits into (regions, or a region's cities): the brand's value sales, value share
    and SKUs over the last N weeks and the N weeks before, plus the category total (region tile map and table)."""
    cond, binds = _children_clause("s")
    return _qc(f"""WITH r AS (SELECT s.*, IFF(s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)), 'NOW', 'BEFORE') AS P
                           FROM SR_DB.APP.V_UI_REGION_SUMMARY s
                           WHERE s.CATEGORY = ? AND {cond} AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                             AND s.WEEK_END_DATE > DATEADD(week, -2 * ?, TRY_TO_DATE(?)))
                SELECT REGION, COALESCE(CITY, RETAILER) AS RETAILER, MARKET_ID, MARKET_NAME,
                       SUM(IFF(P = 'NOW' AND BRAND = ?, VALUE_SALES, 0)) AS VALUE_SALES,
                       SUM(IFF(P = 'BEFORE' AND BRAND = ?, VALUE_SALES, 0)) AS VALUE_SALES_BEFORE,
                       SUM(IFF(P = 'NOW', VALUE_SALES, 0)) AS CAT_VALUE_SALES,
                       SUM(IFF(P = 'BEFORE', VALUE_SALES, 0)) AS CAT_VALUE_SALES_BEFORE,
                       MAX(IFF(P = 'NOW' AND BRAND = ?, SKUS_SELLING, NULL)) AS SKUS_SELLING,
                       MAX(IFF(P = 'NOW' AND BRAND = ?, MAX_STORES_SELLING, NULL)) AS STORES_SELLING,
                       COUNT(DISTINCT IFF(P = 'NOW', BRAND, NULL)) AS BRANDS,
                       100 * SUM(IFF(P = 'NOW' AND BRAND = ?, VALUE_SALES, 0)) / NULLIF(SUM(IFF(P = 'NOW', VALUE_SALES, 0)), 0)
                           AS SHARE_PCT,
                       100 * SUM(IFF(P = 'BEFORE' AND BRAND = ?, VALUE_SALES, 0))
                           / NULLIF(SUM(IFF(P = 'BEFORE', VALUE_SALES, 0)), 0) AS SHARE_BEFORE_PCT,
                       SHARE_PCT - SHARE_BEFORE_PCT AS CHG_PTS
                FROM r GROUP BY REGION, COALESCE(CITY, RETAILER), MARKET_ID, MARKET_NAME ORDER BY REGION, RETAILER""",
               tuple([weeks, filters().as_of, category, *binds, filters().as_of, weeks, filters().as_of,
                      brand, brand, brand, brand, brand, brand]))


def sku_retailer(category: str, brand: str, weeks: int = 4) -> pd.DataFrame:
    """Per market x SKU of the brand: value sales over the last N weeks and the N weeks before (SKU heatmap)."""
    cond, binds = _children_clause("s")
    a = filters().as_of
    return _qc(f"""SELECT s.REGION, COALESCE(s.CITY, s.RETAILER) AS RETAILER, s.MARKET_ID, s.PRODUCT_ID, s.ITEM_DESC,
                       s.SEGMENT, s.PACK_SIZE,
                       SUM(IFF(s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)), s.VALUE_SALES, 0)) AS VALUE_SALES,
                       SUM(IFF(s.WEEK_END_DATE <= DATEADD(week, -?, TRY_TO_DATE(?)), s.VALUE_SALES, 0)) AS VALUE_SALES_BEFORE,
                       AVG(IFF(s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)), s.ACV_DIST_PCT, NULL)) AS ACV_DIST_PCT
                FROM SR_DB.APP.V_UI_SKU_WEEK s
                WHERE {cond} AND s.CATEGORY = ? AND s.BRAND = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                  AND s.WEEK_END_DATE > DATEADD(week, -2 * ?, TRY_TO_DATE(?))
                GROUP BY s.REGION, COALESCE(s.CITY, s.RETAILER), s.MARKET_ID, s.PRODUCT_ID, s.ITEM_DESC, s.SEGMENT,
                         s.PACK_SIZE
                ORDER BY RETAILER, s.ITEM_DESC""",
               tuple([weeks, a, weeks, a, weeks, a, *binds, category, brand, a, weeks, a]))


def brand_share_weeks(market_id: str, category: str, weeks: int = 26) -> pd.DataFrame:
    """Weekly value share of every brand in one market and category, last N weeks (week x brand heatmap)."""
    return _qc("""SELECT WEEK_END_DATE, BRAND, MANUFACTURER, 100 * VALUE_SHARE AS VALUE_SHARE_PCT
                FROM SR_DB.APP.V_UI_SHARE_WEEK WHERE MARKET_ID = ? AND CATEGORY = ? AND WEEK_END_DATE <= TRY_TO_DATE(?)
                QUALIFY DENSE_RANK() OVER (ORDER BY WEEK_END_DATE DESC) <= ?
                ORDER BY WEEK_END_DATE, BRAND""", (market_id, category, filters().as_of, weeks))


# ---- Insight Studio (SR-065; cached; SELECT only, on the same APP.V_UI_SKU_WEEK view the analysis tabs read) -------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def portfolio(run_id: str) -> dict[str, float]:
    """The director's totals over the shifts in this run's brief (SELECTED), so no move is counted twice across
    comparisons or markets: losses and gains at stake, how many the anomaly model confirmed (NULL counts as not
    confirmed) and how many are possible data effects."""
    row = _one("""SELECT COUNT(*) AS N_SHIFTS,
                         SUM(IFF(r.VALUE_AT_STAKE < 0, r.VALUE_AT_STAKE, 0)) AS VALUE_LOSS,
                         SUM(IFF(r.VALUE_AT_STAKE > 0, r.VALUE_AT_STAKE, 0)) AS VALUE_GAIN,
                         COUNT_IF(r.VALUE_AT_STAKE < 0) AS N_LOSS, COUNT_IF(r.VALUE_AT_STAKE > 0) AS N_GAIN,
                         COUNT_IF(c.ANOMALY_CONFIRMED) AS N_CONFIRMED,
                         COUNT_IF(r.ARTEFACT_LABEL = 'POSSIBLE_DATA_EFFECT') AS N_DATA_EFFECT
                  FROM SR_DB.APP.SHIFT_RANKED r
                  JOIN SR_DB.APP.SHIFT_CANDIDATE c ON c.RUN_ID = r.RUN_ID AND c.SHIFT_ID = r.SHIFT_ID
                  WHERE r.RUN_ID = ? AND r.SELECTED""", [run_id]) or {}
    return {k: (0 if v is None or pd.isna(v) else float(v)) for k, v in row.items()}


def brand_panel(category: str, weeks: int = 104) -> pd.DataFrame:
    """Week x market x brand for one category, in the markets the filtered market splits into (regions, or a
    region's cities), up to the filter week: sales, units, distribution, stores and SKUs, with the brand's value share
    of the market's category, its price per unit and its price index against the category, all in SQL. The model lab,
    the workbench and the manager views read this one panel."""
    cond, binds = _children_clause("s")
    a = filters().as_of
    return _qc(f"""WITH b AS (SELECT s.WEEK_END_DATE, s.MARKET_ID, COALESCE(s.CITY, s.RETAILER) AS RETAILER, s.REGION,
                                  s.MANUFACTURER, s.BRAND,
                                  SUM(s.VALUE_SALES) AS VALUE_SALES, SUM(s.UNIT_SALES) AS UNIT_SALES,
                                  SUM(s.VOLUME_SALES) AS VOLUME_SALES, MAX(s.ACV_DIST_PCT) AS ACV_DIST_PCT,
                                  MAX(s.STORES_SELLING) AS STORES_SELLING, COUNT_IF(s.VALUE_SALES > 0) AS SKUS_SELLING
                           FROM SR_DB.APP.V_UI_SKU_WEEK s
                           WHERE {cond} AND s.CATEGORY = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                             AND s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?))
                           GROUP BY s.WEEK_END_DATE, s.MARKET_ID, COALESCE(s.CITY, s.RETAILER), s.REGION,
                                    s.MANUFACTURER, s.BRAND)
                SELECT WEEK_END_DATE, MARKET_ID, RETAILER, REGION, MANUFACTURER, BRAND, VALUE_SALES, UNIT_SALES,
                       VOLUME_SALES, ACV_DIST_PCT, STORES_SELLING, SKUS_SELLING,
                       100 * VALUE_SALES / NULLIF(SUM(VALUE_SALES) OVER (PARTITION BY WEEK_END_DATE, MARKET_ID), 0)
                           AS VALUE_SHARE_PCT,
                       VALUE_SALES / NULLIF(UNIT_SALES, 0) AS PRICE_PER_UNIT,
                       (VALUE_SALES / NULLIF(UNIT_SALES, 0))
                         / NULLIF(SUM(VALUE_SALES) OVER (PARTITION BY WEEK_END_DATE, MARKET_ID)
                                  / NULLIF(SUM(UNIT_SALES) OVER (PARTITION BY WEEK_END_DATE, MARKET_ID), 0), 0)
                           AS PRICE_INDEX
                FROM b ORDER BY WEEK_END_DATE, RETAILER, BRAND""", tuple([*binds, category, a, weeks, a]))


def share_report(category: str, weeks: int = 4, compare: str = "previous", retailer: str | None = None,
                 measure: str = "value") -> pd.DataFrame:
    """The competitive share report, all in SQL: every brand's value share, change, rank and rank change, value sales
    and growth, mean ACV, value-weighted price index, velocity (units per store per week), share of distribution points
    (ACV x SKUs) and fair-share index, for the N weeks up to the filter week against the N before ("previous") or the
    same weeks a year ago ("year_ago"), across the filtered market's regions or cities, or one of them.
    measure="volume" bases share and rank on volume sales instead of value (SALES and growth stay value)."""
    off = weeks if compare == "previous" else 52
    cond, binds = _children_clause("s")
    a = filters().as_of
    return _qc(f"""WITH b AS (SELECT s.WEEK_END_DATE, s.MARKET_ID, s.MANUFACTURER, s.BRAND,
                                  SUM(s.VALUE_SALES) AS VALUE_SALES, SUM(s.UNIT_SALES) AS UNIT_SALES,
                                  SUM(IFF(? = 'volume', s.VOLUME_SALES, s.VALUE_SALES)) AS BASE,
                                  MAX(s.ACV_DIST_PCT) AS ACV, MAX(s.STORES_SELLING) AS STORES,
                                  COUNT_IF(s.VALUE_SALES > 0) AS SKUS,
                                  CASE WHEN s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)) THEN 'NOW'
                                       WHEN s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?))
                                        AND s.WEEK_END_DATE <= DATEADD(week, -?, TRY_TO_DATE(?)) THEN 'BEFORE' END AS P
                           FROM SR_DB.APP.V_UI_SKU_WEEK s
                           WHERE {cond} AND s.CATEGORY = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                             AND (? IS NULL OR COALESCE(s.CITY, s.RETAILER) = ?)
                           GROUP BY s.WEEK_END_DATE, s.MARKET_ID, s.MANUFACTURER, s.BRAND),
                     x AS (SELECT b.*, (VALUE_SALES / NULLIF(UNIT_SALES, 0))
                                  / NULLIF(SUM(VALUE_SALES) OVER (PARTITION BY WEEK_END_DATE, MARKET_ID)
                                           / NULLIF(SUM(UNIT_SALES) OVER (PARTITION BY WEEK_END_DATE, MARKET_ID), 0), 0)
                                  AS PRICE_INDEX
                           FROM b WHERE P IS NOT NULL),
                     g AS (SELECT BRAND, MANUFACTURER, P, SUM(VALUE_SALES) AS SALES, SUM(BASE) AS BASE, AVG(ACV) AS ACV,
                                  SUM(ACV * SKUS) AS TDP, AVG(UNIT_SALES / NULLIF(STORES, 0)) AS VELOCITY,
                                  SUM(PRICE_INDEX * VALUE_SALES) / NULLIF(SUM(IFF(PRICE_INDEX IS NULL, 0, VALUE_SALES)), 0)
                                  AS PRICE_INDEX
                           FROM x GROUP BY BRAND, MANUFACTURER, P),
                     r AS (SELECT g.*, 100 * BASE / NULLIF(SUM(BASE) OVER (PARTITION BY P), 0) AS SHARE,
                                  100 * TDP / NULLIF(SUM(TDP) OVER (PARTITION BY P), 0) AS TDP_SHARE,
                                  RANK() OVER (PARTITION BY P ORDER BY BASE DESC) AS RNK
                           FROM g)
                SELECT n.BRAND, n.MANUFACTURER, n.SALES, n.ACV, n.TDP, n.VELOCITY, n.PRICE_INDEX, n.SHARE, n.TDP_SHARE,
                       n.RNK AS RANK, o.SHARE AS SHARE_BEFORE, o.SALES AS SALES_BEFORE, o.RNK AS RANK_BEFORE,
                       n.SHARE - o.SHARE AS SHARE_CHG_PTS, o.RNK - n.RNK AS RANK_CHG,
                       100 * (n.SALES / NULLIF(o.SALES, 0) - 1) AS SALES_GROWTH_PCT,
                       100 * n.SHARE / NULLIF(n.TDP_SHARE, 0) AS FAIR_SHARE_INDEX
                FROM r n LEFT JOIN r o ON o.BRAND = n.BRAND AND o.MANUFACTURER = n.MANUFACTURER AND o.P = 'BEFORE'
                WHERE n.P = 'NOW' ORDER BY RANK, n.BRAND""",
               tuple([measure, weeks, a, off + weeks, a, off, a, *binds, category, a, retailer, retailer]))


# ---- Competitive View (cached; SELECT only, on the same APP.V_UI_SKU_WEEK and APP.V_UI_SHARE_WEEK views) -------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def competitive_share_week(category: str, weeks: int = 52, measure: str = "value") -> pd.DataFrame:
    """Weekly share of every brand in the category, all retailers combined, last N weeks: value share, or volume share
    with measure="volume" (the Competitive View trend)."""
    return q("""WITH w AS (SELECT MAX(WEEK_END_DATE) AS MX FROM SR_DB.APP.V_UI_SKU_WEEK),
                     b AS (SELECT s.WEEK_END_DATE, s.MANUFACTURER, s.BRAND,
                                  SUM(IFF(? = 'volume', s.VOLUME_SALES, s.VALUE_SALES)) AS BASE
                           FROM SR_DB.APP.V_UI_SKU_WEEK s, w
                           WHERE s.MARKET_LEVEL = 'RETAILER' AND s.CATEGORY = ?
                             AND s.WEEK_END_DATE > DATEADD(week, -?, w.MX)
                           GROUP BY s.WEEK_END_DATE, s.MANUFACTURER, s.BRAND)
                SELECT WEEK_END_DATE, MANUFACTURER, BRAND,
                       100 * BASE / NULLIF(SUM(BASE) OVER (PARTITION BY WEEK_END_DATE), 0) AS SHARE_PCT
                FROM b ORDER BY WEEK_END_DATE, BRAND""", [measure, category, weeks])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def competitive_regions(category: str, weeks: int = 4, compare: str = "previous", measure: str = "value") -> pd.DataFrame:
    """Per retailer market and brand: share of that retailer's category (value, or volume) in the last N weeks and the
    comparison period, its change, mean ACV and velocity (units per store per week), all in SQL (the Competitive View
    regional heatmap and opportunity list)."""
    off = weeks if compare == "previous" else 52
    return q("""WITH w AS (SELECT MAX(WEEK_END_DATE) AS MX FROM SR_DB.APP.V_UI_SKU_WEEK),
                     b AS (SELECT s.WEEK_END_DATE, s.REGION, s.RETAILER, s.MARKET_ID, s.MANUFACTURER, s.BRAND,
                                  SUM(IFF(? = 'volume', s.VOLUME_SALES, s.VALUE_SALES)) AS BASE,
                                  SUM(s.UNIT_SALES) AS UNIT_SALES, MAX(s.ACV_DIST_PCT) AS ACV,
                                  MAX(s.STORES_SELLING) AS STORES,
                                  CASE WHEN s.WEEK_END_DATE > DATEADD(week, -?, w.MX) THEN 'NOW'
                                       WHEN s.WEEK_END_DATE > DATEADD(week, -?, w.MX)
                                        AND s.WEEK_END_DATE <= DATEADD(week, -?, w.MX) THEN 'BEFORE' END AS P
                           FROM SR_DB.APP.V_UI_SKU_WEEK s, w
                           WHERE s.MARKET_LEVEL = 'RETAILER' AND s.CATEGORY = ?
                           GROUP BY s.WEEK_END_DATE, s.REGION, s.RETAILER, s.MARKET_ID, s.MANUFACTURER, s.BRAND, w.MX),
                     g AS (SELECT REGION, RETAILER, MARKET_ID, MANUFACTURER, BRAND, P, SUM(BASE) AS BASE,
                                  AVG(ACV) AS ACV, AVG(UNIT_SALES / NULLIF(STORES, 0)) AS VELOCITY
                           FROM b WHERE P IS NOT NULL GROUP BY REGION, RETAILER, MARKET_ID, MANUFACTURER, BRAND, P),
                     r AS (SELECT g.*, 100 * BASE / NULLIF(SUM(BASE) OVER (PARTITION BY MARKET_ID, P), 0) AS SHARE
                           FROM g)
                SELECT n.REGION, n.RETAILER, n.MARKET_ID, n.MANUFACTURER, n.BRAND, n.SHARE, o.SHARE AS SHARE_BEFORE,
                       n.SHARE - o.SHARE AS SHARE_CHG_PTS, n.ACV, n.VELOCITY
                FROM r n LEFT JOIN r o ON o.MARKET_ID = n.MARKET_ID AND o.BRAND = n.BRAND
                                      AND o.MANUFACTURER = n.MANUFACTURER AND o.P = 'BEFORE'
                WHERE n.P = 'NOW' ORDER BY n.REGION, n.RETAILER, n.BRAND""",
             [measure, weeks, off + weeks, off, category])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def promo_index(market_id: str, category: str, weeks: int = 4, compare: str = "previous") -> pd.DataFrame:
    """Each brand's mean promo index (its promoted-over-base sales ratio against the category's; 1 = in line with the
    category) in the last N weeks and the comparison period, from the stored weekly index (one market; there is no
    retailer split for this lever)."""
    off = weeks if compare == "previous" else 52
    return q("""WITH w AS (SELECT MAX(WEEK_END_DATE) AS MX FROM SR_DB.APP.V_UI_SHARE_WEEK
                           WHERE MARKET_ID = ? AND CATEGORY = ?)
                SELECT s.BRAND, s.MANUFACTURER,
                       AVG(IFF(s.WEEK_END_DATE > DATEADD(week, -?, w.MX), s.PROMO_INDEX, NULL)) AS PROMO_INDEX,
                       AVG(IFF(s.WEEK_END_DATE > DATEADD(week, -?, w.MX) AND s.WEEK_END_DATE <= DATEADD(week, -?, w.MX),
                               s.PROMO_INDEX, NULL)) AS PROMO_INDEX_BEFORE
                FROM SR_DB.APP.V_UI_SHARE_WEEK s, w
                WHERE s.MARKET_ID = ? AND s.CATEGORY = ? AND s.WEEK_END_DATE > DATEADD(week, -?, w.MX)
                GROUP BY s.BRAND, s.MANUFACTURER ORDER BY s.BRAND""",
             [market_id, category, weeks, off + weeks, off, market_id, category, off + weeks])


def brand_snapshot(market_id: str, category: str, weeks: int) -> pd.DataFrame:
    """Brand explorer: every brand in one market and category for the N weeks to the filter week (NOW), the N weeks
    before (PP) and the same weeks a year ago (YA): value share, value sales, mean ACV and price index, all in SQL."""
    a = filters().as_of
    return _qc("""WITH b AS (SELECT s.MANUFACTURER, s.BRAND,
                                  CASE WHEN s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)) THEN 'NOW'
                                       WHEN s.WEEK_END_DATE > DATEADD(week, -2 * ?, TRY_TO_DATE(?)) THEN 'PP'
                                       WHEN s.WEEK_END_DATE <= DATEADD(week, -52, TRY_TO_DATE(?))
                                        AND s.WEEK_END_DATE > DATEADD(week, -52 - ?, TRY_TO_DATE(?)) THEN 'YA' END AS P,
                                  SUM(s.VALUE_SALES) AS SALES, SUM(s.UNIT_SALES) AS UNITS, AVG(s.ACV_DIST_PCT) AS ACV
                           FROM SR_DB.APP.V_UI_SKU_WEEK s
                           WHERE s.MARKET_ID = ? AND s.CATEGORY = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                             AND s.WEEK_END_DATE > DATEADD(week, -52 - ?, TRY_TO_DATE(?))
                           GROUP BY s.MANUFACTURER, s.BRAND, P),
                     t AS (SELECT P, SUM(SALES) AS CAT_SALES, SUM(SALES) / NULLIF(SUM(UNITS), 0) AS CAT_PRICE
                           FROM b WHERE P IS NOT NULL GROUP BY P),
                     s AS (SELECT b.*, 100 * b.SALES / NULLIF(t.CAT_SALES, 0) AS SHARE,
                                  (b.SALES / NULLIF(b.UNITS, 0)) / NULLIF(t.CAT_PRICE, 0) AS PRICE_INDEX
                           FROM b JOIN t ON t.P = b.P)
                SELECT n.MANUFACTURER, n.BRAND, n.SALES, n.SHARE, n.ACV, n.PRICE_INDEX,
                       p.SHARE AS SHARE_PP, y.SHARE AS SHARE_YA, n.SHARE - p.SHARE AS CHG_PP_PTS,
                       n.SHARE - y.SHARE AS CHG_YA_PTS, 100 * (n.SALES / NULLIF(y.SALES, 0) - 1) AS SALES_GROWTH_YA_PCT,
                       n.ACV - y.ACV AS ACV_CHG_YA
                FROM s n
                LEFT JOIN s p ON p.BRAND = n.BRAND AND p.MANUFACTURER = n.MANUFACTURER AND p.P = 'PP'
                LEFT JOIN s y ON y.BRAND = n.BRAND AND y.MANUFACTURER = n.MANUFACTURER AND y.P = 'YA'
                WHERE n.P = 'NOW' ORDER BY n.SHARE DESC""",
               (weeks, a, weeks, a, a, weeks, a, market_id, category, a, weeks, a))


def price_ladder(category: str, weeks: int = 4) -> pd.DataFrame:
    """Price per unit by brand and pack size over the N weeks to the filter week, in the filtered market's
    regions or cities (the price ladder)."""
    cond, binds = _children_clause("s")
    a = filters().as_of
    return _qc(f"""SELECT s.BRAND, s.MANUFACTURER, s.PACK_SIZE, SUM(s.VALUE_SALES) AS VALUE_SALES,
                       SUM(s.UNIT_SALES) AS UNIT_SALES, SUM(s.VALUE_SALES) / NULLIF(SUM(s.UNIT_SALES), 0) AS PRICE_PER_UNIT
                FROM SR_DB.APP.V_UI_SKU_WEEK s
                WHERE {cond} AND s.CATEGORY = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                  AND s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?))
                GROUP BY s.BRAND, s.MANUFACTURER, s.PACK_SIZE
                HAVING SUM(s.UNIT_SALES) > 0
                ORDER BY s.PACK_SIZE, PRICE_PER_UNIT""", tuple([*binds, category, a, weeks, a]))


def sku_week_panel(category: str, brand: str, weeks: int = 52) -> pd.DataFrame:
    """Week x market x SKU for one brand: sales, units, price per unit, distribution and stores, with the week-on-week
    changes the anomaly scan reads, all in SQL, up to the filter week."""
    cond, binds = _children_clause("s")
    a = filters().as_of
    return _qc(f"""WITH k AS (SELECT s.WEEK_END_DATE, COALESCE(s.CITY, s.RETAILER) AS RETAILER, s.REGION, s.PRODUCT_ID,
                                  s.ITEM_DESC, s.SEGMENT, s.PACK_SIZE,
                                  s.VALUE_SALES, s.UNIT_SALES, s.ACV_DIST_PCT, s.STORES_SELLING,
                                  s.VALUE_SALES / NULLIF(s.UNIT_SALES, 0) AS PRICE_PER_UNIT
                           FROM SR_DB.APP.V_UI_SKU_WEEK s
                           WHERE {cond} AND s.CATEGORY = ? AND s.BRAND = ? AND s.WEEK_END_DATE <= TRY_TO_DATE(?)
                             AND s.WEEK_END_DATE > DATEADD(week, -?, TRY_TO_DATE(?)))
                SELECT k.WEEK_END_DATE, k.RETAILER, k.REGION, k.PRODUCT_ID, k.ITEM_DESC, k.SEGMENT, k.PACK_SIZE,
                       k.VALUE_SALES, k.UNIT_SALES, k.ACV_DIST_PCT, k.STORES_SELLING, k.PRICE_PER_UNIT,
                       VALUE_SALES / NULLIF(LAG(VALUE_SALES) OVER (PARTITION BY RETAILER, PRODUCT_ID ORDER BY WEEK_END_DATE), 0) - 1
                           AS SALES_WOW,
                       PRICE_PER_UNIT / NULLIF(LAG(PRICE_PER_UNIT) OVER (PARTITION BY RETAILER, PRODUCT_ID ORDER BY WEEK_END_DATE), 0) - 1
                           AS PRICE_WOW,
                       ACV_DIST_PCT - LAG(ACV_DIST_PCT) OVER (PARTITION BY RETAILER, PRODUCT_ID ORDER BY WEEK_END_DATE)
                           AS ACV_WOW,
                       UNIT_SALES / NULLIF(STORES_SELLING, 0) AS UNITS_PER_STORE
                FROM k ORDER BY WEEK_END_DATE, RETAILER, ITEM_DESC""", tuple([*binds, category, brand, a, weeks, a]))


# ---- Brief (cached) -------------------------------------------------------------------------------------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def briefs(limit: int = 12) -> pd.DataFrame:
    return q("""SELECT BRIEF_ID, RUN_ID, AS_OF_WEEK, HEADLINE, GENERATOR, MODEL, PUBLISHED_AT, NOTIFIED_AT, NOTIFY_ATTEMPTS
                FROM SR_DB.APP.BRIEF WHERE STATUS = 'PUBLISHED'
                ORDER BY AS_OF_WEEK DESC, PUBLISHED_AT DESC LIMIT ?""", [limit])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def brief(brief_id: str) -> dict:
    row = _one("""SELECT BRIEF_ID, RUN_ID, SCOPE_KEY, AS_OF_WEEK, STATUS, GENERATOR, MODEL, HEADLINE, BODY_MD, BODY_HTML,
                         LLM_JSON, VIOLATIONS, TOKENS_IN, TOKENS_OUT, PUBLISHED_AT, NOTIFIED_AT, NOTIFY_ATTEMPTS
                  FROM SR_DB.APP.BRIEF WHERE BRIEF_ID = ?""", [brief_id]) or {}
    for k in ("LLM_JSON", "VIOLATIONS"):
        row[k] = _variant(row.get(k))
    return row


@st.cache_data(ttl=TTL_S, show_spinner=False)
def brief_facts(brief_id: str) -> pd.DataFrame:
    return q("""SELECT f.KEY AS FACT_ID, f.VALUE:v::FLOAT AS V, f.VALUE:u::VARCHAR AS UNIT, f.VALUE:d::INT AS DECIMALS,
                       f.VALUE:src::VARCHAR AS SOURCE
                FROM SR_DB.APP.FACT_PACK p, LATERAL FLATTEN(INPUT => p.PACK:facts) f
                WHERE p.BRIEF_ID = ? ORDER BY TRY_TO_NUMBER(SUBSTR(f.KEY, 2))""", [brief_id])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def brief_notifications(brief_id: str) -> pd.DataFrame:
    return q("SELECT CHANNEL, STATUS, SENT_AT, MESSAGE FROM SR_DB.OPS.NOTIFY_LOG WHERE BRIEF_ID = ? ORDER BY SENT_AT DESC",
             [brief_id])


# ---- Trust (cached) -------------------------------------------------------------------------------------------

@st.cache_data(ttl=TTL_S, show_spinner=False)
def eval_latest() -> pd.DataFrame:
    return q("""SELECT EVAL_RUN_ID, QUESTION_ID, QUESTION, EXPECTED_TOOL, ACTUAL_TOOLS, PASSED, NOTE, EVALUATED_AT
                FROM SR_DB.OPS.EVAL_RESULT
                WHERE EVAL_RUN_ID = (SELECT EVAL_RUN_ID FROM SR_DB.OPS.EVAL_RESULT ORDER BY EVALUATED_AT DESC LIMIT 1)
                ORDER BY QUESTION_ID""")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def recon_latest() -> pd.DataFrame:
    return q("""SELECT CHECK_ID, DESCRIPTION, REFERENCE_VALUE, SR_VALUE, ABS_DIFF, PASSED, CHECKED_AT
                FROM SR_DB.OPS.RECON_RESULT
                QUALIFY ROW_NUMBER() OVER (PARTITION BY CHECK_ID ORDER BY CHECKED_AT DESC) = 1 ORDER BY CHECK_ID""")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def bridge_residual_max(run_id: str) -> float | None:
    row = _one("SELECT MAX(ABS(RESIDUAL_PTS)) AS R FROM SR_DB.APP.SHARE_BRIDGE WHERE RUN_ID = ? AND STATUS = 'OK'", [run_id])
    return None if not row or row["R"] is None or pd.isna(row["R"]) else float(row["R"])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def runs(limit: int = 20) -> pd.DataFrame:
    return q(f"""SELECT {_RUN_COLS}, DATEDIFF(second, STARTED_AT, ENDED_AT) AS SECONDS
                 FROM SR_DB.OPS.RUN_LOG ORDER BY STARTED_AT DESC LIMIT ?""", [limit])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def run_history(limit: int = 52) -> pd.DataFrame:
    """Market Time Machine: one completed run per as-of week for the current scope (the latest attempt of each week,
    so reruns of a week are not listed twice), newest week first."""
    return q(f"""SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG
                 WHERE STATUS = 'SUCCEEDED' AND SCOPE_KEY = ? AND AS_OF_WEEK IS NOT NULL
                 QUALIFY ROW_NUMBER() OVER (PARTITION BY AS_OF_WEEK ORDER BY STARTED_AT DESC) = 1
                 ORDER BY AS_OF_WEEK DESC LIMIT ?""", [scope_key(), limit])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def previous_week_run(as_of_week: str) -> Run | None:
    """'Since last week': the latest completed run of the previous distinct as-of week in the current scope. A rerun of
    the same week is never returned, so the comparison is always week against the week before."""
    return _run(_one(f"""SELECT {_RUN_COLS} FROM SR_DB.OPS.RUN_LOG
                         WHERE STATUS = 'SUCCEEDED' AND SCOPE_KEY = ? AND AS_OF_WEEK < TRY_TO_DATE(?)
                         ORDER BY AS_OF_WEEK DESC, STARTED_AT DESC LIMIT 1""", [scope_key(), str(as_of_week)]))


@st.cache_data(ttl=TTL_S, show_spinner=False)
def signal_journey(run_id: str) -> dict[str, int]:
    """Signal Journey counts for one run. Outcomes follow the SP_RANK reason order (L6, 406_sp_rank.sql), so each
    ranked shift is counted once: selected, else repeat, else held for data checks, else another comparison ranks
    higher, else beyond the top N. Early warnings are a separate stream and are not counted here."""
    row = _one("""SELECT (SELECT COUNT(*) FROM SR_DB.APP.SHIFT_CANDIDATE WHERE RUN_ID = ?) AS N_DETECTED,
                         (SELECT COUNT_IF(PASSED_GATES) FROM SR_DB.APP.SHIFT_CANDIDATE WHERE RUN_ID = ?) AS N_PASSED,
                         COUNT(*) AS N_RANKED,
                         COUNT_IF(SELECTED) AS N_SELECTED,
                         COUNT_IF(NOT SELECTED AND SUPPRESSED) AS N_REPEAT,
                         COUNT_IF(NOT SELECTED AND NOT SUPPRESSED
                                  AND ARTEFACT_LABEL = 'POSSIBLE_DATA_EFFECT') AS N_HELD,
                         COUNT_IF(NOT SELECTED AND NOT SUPPRESSED
                                  AND COALESCE(ARTEFACT_LABEL, '') <> 'POSSIBLE_DATA_EFFECT'
                                  AND SUPPRESS_REASON IS NOT NULL) AS N_OTHER_CMP,
                         COUNT_IF(NOT SELECTED AND SUPPRESS_REASON IS NULL) AS N_BEYOND_TOP_N
                  FROM SR_DB.APP.SHIFT_RANKED WHERE RUN_ID = ?""", [run_id, run_id, run_id]) or {}
    return {k: (0 if v is None or pd.isna(v) else int(v)) for k, v in row.items()}


@st.cache_data(ttl=TTL_S, show_spinner=False)
def run_cost(limit: int = 10) -> pd.DataFrame:
    return q("""SELECT RUN_ID, TRIGGER_TYPE, AS_OF_WEEK, STATUS, SECONDS, CREDITS_EST, WAREHOUSE_CREDITS, AI_CREDITS,
                       AI_TOKENS, MODEL, GENERATOR, COST_BASIS
                FROM SR_DB.OPS.V_RUN_COST ORDER BY STARTED_AT DESC LIMIT ?""", [limit])


@st.cache_data(ttl=TTL_S, show_spinner=False)
def coco_log() -> pd.DataFrame:
    return q("""SELECT TICKET, SURFACE, COUNT(*) AS SESSIONS, SUM(LINES_ADDED) AS LINES_ADDED,
                       COUNT_IF(ARRAY_SIZE(TESTS) > 0) AS SESSIONS_WITH_TESTS, COUNT_IF(HUMAN_EDITS) AS HUMAN_EDITS,
                       MAX(LOGGED_AT) AS LAST_LOGGED
                FROM SR_DB.OPS.COCO_LOG GROUP BY TICKET, SURFACE ORDER BY TICKET""")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def tests_latest() -> pd.DataFrame:
    return q("""SELECT TEST_ID, PASSED, FAILURES, DETAIL, RAN_AT FROM SR_DB.OPS.TEST_RESULT
                WHERE TEST_RUN_ID = (SELECT TEST_RUN_ID FROM SR_DB.OPS.TEST_RESULT ORDER BY RAN_AT DESC LIMIT 1)
                ORDER BY PASSED, TEST_ID""")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def health_latest() -> pd.DataFrame:
    return q("SELECT CHECKED_AT, OBJECT_TYPE, OBJECT_NAME, STATE, DETAIL FROM SR_DB.OPS.V_HEALTH_LATEST "
             "ORDER BY IFF(STATE = 'OK', 1, 0), OBJECT_TYPE, OBJECT_NAME")


@st.cache_data(ttl=TTL_S, show_spinner=False)
def cost_daily(days: int = 14) -> pd.DataFrame:
    return q("SELECT USAGE_DATE, SOURCE, INTERFACE, CREDITS, TOKENS FROM SR_DB.OPS.COST_DAILY "
             "WHERE USAGE_DATE >= DATEADD(day, -?, CURRENT_DATE()) ORDER BY USAGE_DATE, SOURCE", [days])


# ---- Chippy chat (never cached: every call is a new agent turn) -------------------------------------------------

AGENT = "SR_DB.SEM.SHARE_RADAR_AGENT"

# The agents the app may call; the picker on Ask Chippy chooses from this fixed list only.
AGENTS = {
    "SR_DB.SEM.SHARE_RADAR_AGENT": {
        "label": "Chippy", "icon": ":material/radar:",
        "purpose": "Ask-Why: explains share shifts with the exact bridge, data checks, share flow and what-if."},
    "SR_DB.SEM.RADAR_ANALYST_AGENT": {
        "label": "Data analyst", "icon": ":material/query_stats:",
        "purpose": "Open business questions: sales, share, distribution, rankings and comparisons, answered as tables."},
    "SR_DB.SEM.GEO_MARKET_AGENT": {
        "label": "Chippy Geo", "icon": ":material/public:",
        "purpose": "Where share moved: cities, regions and states with coordinates, and multi-year trends since 2020."},
    "SR_DB.SEM.RECOVERY_AGENT": {
        "label": "Recovery Strategist", "icon": ":material/healing:",
        "purpose": "Turns a share loss into a ranked recovery plan: which lever, where first, who owns it, what it is worth."},
    "SR_DB.SEM.PRICE_PROMO_AGENT": {
        "label": "Pricing & Promo", "icon": ":material/sell:",
        "purpose": "Price index, price changes, promo intensity and lift against competitors, by market and period."},
    "SR_DB.SEM.FORECAST_RISK_AGENT": {
        "label": "Forecast & Risk", "icon": ":material/warning:",
        "purpose": "Early-warning signals, projected share effect and long-run trend: what could go wrong next."},
    "SR_DB.SEM.COMPETITOR_AGENT": {
        "label": "Competitive benchmarking", "icon": ":material/leaderboard:",
        "purpose": "One company against its rivals: league table, distribution, velocity, price, and where it wins or loses."},
}


def ask_agent(question: str, thread_id: int | None = None, parent_message_id: int = 0, agent: str = AGENT) -> dict:
    """One agent turn through SNOWFLAKE.CORTEX.DATA_AGENT_RUN (non-streaming). Continues the thread when given one.
    Returns text, tables (DataFrames), the tools called, warnings, and the ids the next turn needs."""
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent {agent}")
    body: dict = {"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}]}
    if thread_id is not None:
        body.update(thread_id=thread_id, parent_message_id=parent_message_id)
    raw = q(f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('{agent}', ?, TRUE) AS R", [json.dumps(body)]).R.iloc[0]
    resp = json.loads(raw) if isinstance(raw, str) else raw
    if resp.get("code") and not resp.get("content"):
        raise RuntimeError(resp.get("message") or "The agent returned an error")
    text, tables, tools = [], [], []
    for item in resp.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            text.append(item.get("text") or "")
        elif kind in ("tool_use", "tool_result"):
            text = []                         # text before a tool call is planning, not the answer
            if kind == "tool_use":
                tools.append((item.get("tool_use") or {}).get("name"))
        elif kind == "table":
            rs = (item.get("table") or {}).get("result_set") or {}
            cols = [c.get("name") for c in (rs.get("resultSetMetaData") or {}).get("rowType") or []]
            tables.append((item["table"].get("title") or "", pd.DataFrame(rs.get("data") or [], columns=cols or None)))
    meta = resp.get("metadata") or {}
    return {"text": "\n\n".join(t for t in text if t).strip(), "tables": tables, "tools": [t for t in tools if t],
            "warnings": [w.get("message") for w in resp.get("warnings") or []],
            "thread_id": meta.get("thread_id", thread_id), "message_id": meta.get("assistant_message_id", 0)}


# ---- Admin actions (admin app only; never cached) -------------------------------------------------------------

def clear_cache() -> None:
    st.cache_data.clear()


def start_task(task: str) -> str:
    """Raises Busy while a run is in progress. Returns the anchor time the progress panel watches from."""
    if task not in STARTABLE:
        raise ValueError(f"Task {task} cannot be started from the app")
    if task != "T_HEALTH" and active_run() is not None:
        raise Busy("A run is in progress")
    anchor = q("SELECT TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS.FF3 TZHTZM') AS T").T.iloc[0]
    session().sql(f"EXECUTE TASK SR_DB.OPS.{task}").collect()          # task name from the fixed set above
    clear_cache()
    return anchor


def reset_replay(week: date) -> str:
    return str(session().call("SR_DB.APP.SP_REPLAY_RESET", week.isoformat()))


def settings() -> pd.DataFrame:
    return q("SELECT SETTING_KEY, TO_JSON(SETTING_VALUE) AS VALUE_JSON, DESCRIPTION, UPDATED_AT "
             "FROM SR_DB.OPS.SETTINGS ORDER BY SETTING_KEY")


EDITABLE: dict[str, tuple[type, float | None, float | None]] = {
    "MIN_SHARE_PTS": (float, 0.05, 5), "MIN_VALUE_AT_STAKE": (float, 0, None), "MIN_Z": (float, 0, 10),
    "TOP_N": (int, 1, 10), "SUPPRESS_RUNS": (int, 0, 12), "SUPPRESS_GROWTH": (float, 0, 5),
    "ART_STORE_CHG": (float, 0, 1), "ART_CAT_TDP_JUMP": (float, 0, 2), "ART_CAT_SPPD_FLAT": (float, 0, 1),
    "ART_RECODE_TOL": (float, 0, 1), "ART_SPIKE_K": (float, 1, 20), "EW_DIST_DROP": (float, -1, 0),
    "EW_PRICE_RISE": (float, 0, 1), "MAX_CREDITS_PER_RUN": (float, 0, 50),
    "DISPLAY_ALIAS": (bool, None, None), "TEAMS_ENABLED": (bool, None, None), "NOTIFY_EMAILS": (list, None, None)}


def validate_setting(key: str, value: object, allowed_emails: list[str] | None = None) -> object:
    """The value to store, or ValueError. Pure, so it is unit-tested."""
    if key not in EDITABLE:
        raise ValueError(f"{key} cannot be edited here")
    kind, lo, hi = EDITABLE[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if kind is list:
        if not isinstance(value, list) or not value or not all(isinstance(e, str) and "@" in e for e in value):
            raise ValueError("NOTIFY_EMAILS must be a non-empty list of email addresses")
        allowed = {e.lower() for e in (allowed_emails or [])}
        outside = [e for e in value if e.lower() not in allowed]
        if outside:
            raise ValueError(f"Not in the email integration's allowed recipients: {', '.join(outside)}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if kind is int and float(value) != int(value):
        raise ValueError(f"{key} must be a whole number")
    v = kind(value)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"{key} must be between {lo} and {hi if hi is not None else 'any'}")
    return v


def save_setting(key: str, value: object) -> None:
    v = validate_setting(key, value, cfg("NOTIFY_ALLOWED") or [])
    session().sql("UPDATE SR_DB.OPS.SETTINGS SET SETTING_VALUE = PARSE_JSON(?), UPDATED_AT = CURRENT_TIMESTAMP() "
                  "WHERE SETTING_KEY = ?", params=[json.dumps(v), key]).collect()
    clear_cache()
