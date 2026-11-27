"""Page list, sidebar and session-state defaults (L11), plus the section guard every page uses.

Also the design system (Deep Teal & Mist): colour tokens (mirrored in .streamlit/config.toml and charts.py), one CSS block keyed to
.st-key-* classes, and small layout helpers (header, KPI cards, cards, badges, dates) the pages share.
"""
from __future__ import annotations

import base64
import functools
from collections.abc import Callable, Sequence
from datetime import date, datetime
from html import escape
from pathlib import Path

import streamlit as st

DEFAULTS = {"sr_admin": False, "shift_id": None, "brief_id": None, "awaiting": None}
# awaiting = {"kind": "REPLAY" | "RERUN", "since": <Snowflake timestamp text>, "t0": <time.monotonic()>}

TOKENS = {
    # Deep Teal & Mist palette (mirrored in .streamlit/config.toml and charts.py). No other colours.
    "teal": "#1E5556", "deep": "#173F43", "mist": "#F5F8F8", "sea": "#A6C1BD", "slate": "#647C80",
    "pale": "#DCEBE8", "gold": "#C6A879", "terra": "#C87970", "white": "#FFFFFF",
    # Roles
    "page": "#F5F8F8", "card": "#FFFFFF", "ink": "#173F43", "muted": "#647C80",
    "line": "rgba(166, 193, 189, 0.45)", "line_strong": "#A6C1BD", "hover": "#DCEBE8",
    # Status tones: always next to their text and symbol (✓ ! ✕)
    "ok": "#1E5556", "ok_bg": "#DCEBE8", "warn": "#C6A879", "warn_bg": "rgba(198, 168, 121, 0.18)",
    "bad": "#C87970", "bad_bg": "rgba(200, 121, 112, 0.15)",
}
T = TOKENS
HEAD = "Manrope, 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"   # headings, KPI figures
SANS = "Inter, 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"     # everything else
SHADOW = "0 1px 2px rgba(23, 63, 67, 0.04), 0 1px 3px rgba(23, 63, 67, 0.04)"
SHADOW_HOVER = "0 2px 4px rgba(23, 63, 67, 0.05), 0 8px 20px rgba(23, 63, 67, 0.08)"
FOCUS = "0 0 0 3px rgba(30, 85, 86, 0.15)"
RADIUS, RADIUS_SM = "12px", "8px"
# Type scale (px): helper 12 · KPI label 13 · table 13 · body 14 · sidebar 14 · section 19 · title 28 · KPI figure 30

def _fab_image() -> str:
    still = Path(__file__).resolve().parent / "mascot" / "anim" / "welcome_still.png"
    return ("data:image/png;base64," + base64.b64encode(still.read_bytes()).decode("ascii")) if still.exists() else ""


FAB_IMG = _fab_image()

CSS = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Manrope:wght@600;700&display=swap');

/* ---- Base ------------------------------------------------------------------------------------------------- */
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], button, input, textarea, select,
[data-baseweb="select"], [data-testid="stMetricLabel"], [data-testid="stDataFrame"],
[data-testid="stSidebarNav"] span:not([data-testid="stIconMaterial"]), [data-testid="stExpander"] summary p,
[data-testid="stCaptionContainer"], [data-testid="stMarkdownContainer"] {{
  font-family: {SANS} }}
[data-testid="stIconMaterial"] {{ font-family: 'Material Symbols Rounded' !important; font-weight: 400 }}
[data-testid="stAppViewContainer"] {{ background: {T['page']} }}
[data-testid="stHeader"] {{ background: transparent }}
[data-testid="stMainBlockContainer"] {{ max-width: 1360px; padding-top: 1.5rem; padding-bottom: 4rem }}
[data-testid="stMainBlockContainer"] p, [data-testid="stMainBlockContainer"] li {{ font-size: 14px }}
::selection {{ background: {T['pale']}; color: {T['deep']} }}

/* ---- Typography: Manrope SemiBold for headings, Inter for everything else -------------------------------- */
h1, h2, h3, .sr-head, h1 *, h2 *, h3 * {{ font-family: {HEAD} !important; font-weight: 600 !important;
  color: {T['deep']} }}
h1 {{ font-size: 28px !important; letter-spacing: -0.02em; line-height: 1.2 }}
h2 {{ font-size: 22px !important; letter-spacing: -0.015em; line-height: 1.3 }}
h3 {{ font-size: 19px !important; letter-spacing: -0.01em; line-height: 1.35 }}
h1 a, h2 a, h3 a, [data-testid="stHeaderActionElements"] {{ display: none !important }}   /* no anchor icons */
p, li {{ line-height: 1.55 }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, [data-testid="stCaptionContainer"] * {{
  color: {T['slate']} !important; opacity: 1 !important; font-size: 12.5px !important }}
[data-testid="stWidgetLabel"] p {{ font-size: 13px !important; font-weight: 500; color: {T['ink']} }}
[data-testid="stMarkdownContainer"] p.sr-label {{ font-size: 12px !important; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: {T['muted']}; margin: 0 0 4px 0 }}
code {{ font-size: 0.85em }}
hr {{ border-color: {T['line']} }}
a {{ color: {T['teal']} }}

/* Brief numbers: dotted underline with the source on hover (used inside BODY_HTML) */
.fact {{ border-bottom: 1px dotted {T['teal']}; cursor: help; font-variant-numeric: tabular-nums }}

/* The published brief (BODY_HTML from sr_lib.render): a reading column */
.sr-brief {{ max-width: 720px; font-family: {SANS}; font-size: 15px; line-height: 1.7; color: {T['ink']};
  padding: 4px 8px 8px 4px }}
.sr-brief h1 {{ font-size: 24px !important; line-height: 1.3; margin: 0 0 6px 0; padding: 0 }}
.sr-brief h2 {{ font-size: 17px !important; margin: 0 0 4px 0; padding: 0 }}
.sr-brief > h2 {{ margin-top: 28px; padding-top: 18px; border-top: 1px solid {T['line']} }}
.sr-brief .meta {{ color: {T['muted']}; font-size: 12px; letter-spacing: 0.01em; margin: 0 0 6px 0 }}
.sr-brief > .meta {{ margin-bottom: 20px }}
.sr-brief .shift {{ border-left: 3px solid {T['teal']}; padding: 2px 0 2px 18px; margin: 22px 0 }}
.sr-brief .shift p {{ margin: 0 0 8px 0 }}
.sr-brief b {{ font-weight: 600 }}
.sr-brief ul {{ padding-left: 20px; margin: 6px 0 0 0 }}
.sr-brief li {{ margin: 4px 0 }}

/* ---- Badges and chips ------------------------------------------------------------------------------------- */
.sr-chip, .sr-badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; margin: 0 6px 4px 0;
  border-radius: 999px; font-family: {SANS}; font-size: 12px; font-weight: 500; line-height: 1.45;
  letter-spacing: 0.01em; background: {T['white']}; color: {T['slate']}; border: 1px solid {T['line']};
  white-space: nowrap; font-variant-numeric: tabular-nums }}
.sr-badge.ok   {{ background: {T['ok_bg']};   color: {T['ok']};   border-color: transparent; font-weight: 600 }}
.sr-badge.warn {{ background: {T['warn_bg']}; color: {T['ink']};  border-color: {T['warn']} }}
.sr-badge.bad  {{ background: {T['bad_bg']};  color: {T['ink']};  border-color: {T['bad']} }}
.sr-badge.accent {{ background: {T['teal']}; color: {T['white']}; border-color: transparent }}
.sr-badge.gold {{ background: {T['warn_bg']}; color: {T['ink']}; border-color: {T['gold']}; font-weight: 600 }}

/* ---- Page header: open, no box; title, scope line and status, then a hairline ----------------------------- */
.st-key-sr_header {{ background: transparent; border: 0; border-bottom: 1px solid {T['line']}; border-radius: 0;
  padding: 0 0 14px 0; margin-bottom: 10px; gap: 0 }}
.st-key-sr_header h1 {{ padding: 0; margin: 0 }}
[data-testid="stMarkdownContainer"] p.sr-eyebrow {{ font-size: 12px !important; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: {T['muted']}; margin: 0 0 4px 0; line-height: 1.4 }}
.st-key-sr_header .sr-badge {{ margin-bottom: 0 }}
.st-key-sr_header [data-testid="stHorizontalBlock"] {{ align-items: flex-end }}
.sr-meta {{ text-align: right; font-size: 12px; color: {T['muted']}; margin-top: 6px; font-variant-numeric: tabular-nums }}

/* ---- Cards: white on mist, soft hairline, minimal shadow -------------------------------------------------- */
[class*="st-key-sr_card"], [class*="st-key-sr_kpi"] {{ background: {T['card']}; border: 1px solid {T['line']} !important;
  border-radius: {RADIUS} !important; box-shadow: {SHADOW}; padding: 20px 22px !important }}
[class*="st-key-sr_card"] h3 {{ margin-bottom: 2px }}

/* KPI cards: 13px label, 30px Manrope Bold figure, a short rich-teal rule at the top */
[class*="st-key-sr_kpi"] {{ padding: 18px 20px 16px 20px !important; transition: box-shadow 0.18s ease;
  background-image: linear-gradient({T['teal']}, {T['teal']}); background-size: 32px 3px;
  background-position: 20px 0; background-repeat: no-repeat }}
[class*="st-key-sr_kpi"]:hover {{ box-shadow: {SHADOW_HOVER} }}
[class*="st-key-sr_kpi"] [data-testid="stMetricLabel"] p {{ font-size: 13px !important; font-weight: 500;
  color: {T['muted']}; white-space: normal }}
[class*="st-key-sr_kpi"] [data-testid="stMetricLabel"] div {{ overflow: visible; white-space: normal }}
[class*="st-key-sr_kpi"] [data-testid="stMetricValue"] {{ color: {T['deep']}; font-family: {HEAD}; font-weight: 700;
  font-size: 30px; letter-spacing: -0.02em; line-height: 1.2; font-variant-numeric: tabular-nums }}
[class*="st-key-sr_kpi"] [data-testid="stMetricValue"] div {{ overflow: visible; text-overflow: clip }}
[data-testid="stMetric"] [data-testid="stMetricValue"] {{ font-family: {HEAD}; font-weight: 700; color: {T['deep']};
  font-variant-numeric: tabular-nums }}

/* ---- Toolbars, section heads, filter bar --------------------------------------------------------------- */
.st-key-sr_toolbar {{ background: {T['card']}; border: 1px solid {T['line']}; border-radius: {RADIUS};
  padding: 16px 20px; box-shadow: {SHADOW}; margin-bottom: 8px }}
.sr-toolbar-line {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: {T['ink']} }}
.sr-toolbar-line .sr-badge {{ margin: 0 }}
span.sr-label {{ font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: {T['muted']} }}
.sr-section-head {{ display: flex; justify-content: space-between; align-items: baseline; margin: 14px 0 4px 0 }}
.sr-meta-inline {{ font-size: 12px; color: {T['muted']}; font-variant-numeric: tabular-nums }}
[class*="st-key-sr_card_filters"] {{ padding: 14px 20px 16px 20px !important }}
[data-testid="stMarkdownContainer"] p.sr-filter-title {{ display: flex; flex-direction: column; align-items: flex-start;
  gap: 6px; margin: 0 0 6px 0 }}
p.sr-filter-title .sr-badge {{ margin: 0 }}

/* Stat strip: label over value, in a row, hairlines between */
.sr-stats {{ display: flex; flex-wrap: wrap; gap: 0; margin: 6px 0 2px 0 }}
.sr-stat {{ display: flex; flex-direction: column; gap: 2px; padding: 2px 28px 2px 0; margin-right: 28px;
  border-right: 1px solid {T['line']} }}
.sr-stat:last-child {{ border-right: 0; margin-right: 0 }}
.sr-stat .k {{ font-size: 12px; font-weight: 500; color: {T['muted']} }}
.sr-stat .v {{ font-family: {HEAD}; font-size: 19px; font-weight: 700; color: {T['deep']};
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em }}
[class*="st-key-sr_card_shift_pick"] h2 {{ margin-top: 4px }}

/* Ask Chippy: the agent picker (st.radio, key chat_agent) as two cards; the chosen one has a teal edge */
.st-key-chat_agent [role="radiogroup"] {{ gap: 10px; flex-wrap: wrap }}
.st-key-chat_agent label[data-baseweb="radio"] {{ margin: 0; padding: 10px 18px 10px 12px; min-width: 180px;
  background: {T['card']}; border: 1px solid {T['line']}; border-radius: {RADIUS_SM}; cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease }}
.st-key-chat_agent label[data-baseweb="radio"]:hover {{ border-color: {T['line_strong']}; background: {T['mist']} }}
.st-key-chat_agent label[data-baseweb="radio"]:has(input:checked) {{ border-color: {T['teal']}; background: {T['pale']};
  box-shadow: inset 0 0 0 1px {T['teal']} }}
.st-key-chat_agent label[data-baseweb="radio"]:has(input:focus-visible) {{ outline: 2px solid {T['teal']}; outline-offset: 2px }}
.st-key-chat_agent label[data-baseweb="radio"] p {{ font-weight: 500; color: {T['ink']} }}

/* Ask Chippy: starter questions as quiet cards; chat messages as cards; the chat box */
[class*="st-key-sr_card_starter"] {{ padding: 12px 16px !important; transition: border-color 0.15s ease, background 0.15s ease }}
[class*="st-key-sr_card_starter"]:hover {{ border-color: {T['line_strong']} !important; background: {T['mist']} }}
[class*="st-key-sr_card_starter"] button {{ width: 100%; justify-content: flex-start; text-align: left; padding: 0 }}
[class*="st-key-sr_card_starter"] button p {{ text-align: left; font-size: 14px; color: {T['ink']} }}
[class*="st-key-sr_card_starter"] button:hover {{ text-decoration: none }}
[data-testid="stChatMessage"] {{ background: {T['card']}; border: 1px solid {T['line']}; border-radius: {RADIUS};
  padding: 14px 18px; box-shadow: {SHADOW}; margin-bottom: 10px }}
[data-testid="stChatMessage"] [data-testid="stCaptionContainer"] p {{ font-weight: 500 }}
[data-testid^="stChatMessageAvatar"] {{ background: {T['teal']}; color: {T['white']}; border-radius: 8px }}
[data-testid^="stChatMessageAvatar"] [data-testid="stIconMaterial"] {{ color: {T['white']} }}
[data-testid="stChatInput"] > div {{ background: {T['card']}; border: 1px solid {T['line_strong']}; border-radius: {RADIUS} }}
[data-testid="stChatInput"] > div:focus-within {{ border-color: {T['teal']}; box-shadow: {FOCUS} }}
[data-testid="stBottom"] > div {{ background: {T['page']} }}

/* Forms inside cards: no second border */
[class*="st-key-sr_card"] [data-testid="stForm"] {{ border: 0; padding: 0 }}

/* ---- Expanders, alerts, code ------------------------------------------------------------------------------ */
[data-testid="stExpander"] details {{ background: {T['card']}; border: 1px solid {T['line']}; border-radius: {RADIUS};
  box-shadow: {SHADOW} }}
[data-testid="stExpander"] summary {{ padding-top: 12px; padding-bottom: 12px }}
[data-testid="stExpander"] summary p {{ font-weight: 500; color: {T['ink']} }}
[data-testid="stExpander"] summary:hover p, [data-testid="stExpander"] summary:hover svg {{ color: {T['teal']} }}
[data-testid="stAlert"] > div {{ border-radius: {RADIUS_SM} }}
[data-testid="stCode"] pre, .stCode pre {{ border-radius: {RADIUS_SM}; border: 1px solid {T['line']} }}

/* ---- Buttons: rich-teal primary; white outlined secondary; same height everywhere ------------------------ */
.stButton button, .stFormSubmitButton button, [data-testid="stPopover"] > div > button,
.stDownloadButton button {{ min-height: 38px; padding: 0 16px; font-family: {SANS}; font-weight: 500;
  font-size: 14px; border-radius: {RADIUS_SM}; box-shadow: none;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease }}
.stButton button p, .stFormSubmitButton button p, [data-testid="stPopover"] button p {{ font-size: 14px }}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {{ background: {T['teal']};
  border: 1px solid {T['teal']}; color: {T['white']} }}
.stButton button[kind="primary"] p, .stFormSubmitButton button[kind="primaryFormSubmit"] p {{ color: {T['white']} }}
.stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primaryFormSubmit"]:hover {{
  background: {T['deep']}; border-color: {T['deep']}; color: {T['white']}; box-shadow: {SHADOW_HOVER} }}
.stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondaryFormSubmit"],
[data-testid="stPopover"] > div > button {{ background: {T['card']}; border: 1px solid {T['line_strong']}; color: {T['ink']} }}
.stButton button[kind="secondary"] p, .stFormSubmitButton button[kind="secondaryFormSubmit"] p,
[data-testid="stPopover"] > div > button p {{ color: {T['ink']} }}
.stButton button[kind="secondary"]:hover, .stFormSubmitButton button[kind="secondaryFormSubmit"]:hover,
[data-testid="stPopover"] > div > button:hover {{ background: {T['pale']}; border-color: {T['teal']}; color: {T['deep']} }}
.stButton button[kind="tertiary"] {{ color: {T['ink']}; min-height: 0; padding: 0 }}
.stButton button[kind="tertiary"]:hover {{ color: {T['teal']}; text-decoration: underline; text-underline-offset: 3px }}
.stButton button:active, .stFormSubmitButton button:active {{ transform: translateY(1px); box-shadow: none }}
.stButton button:focus-visible, .stFormSubmitButton button:focus-visible, [data-testid="stPopover"] button:focus-visible,
a:focus-visible {{ outline: 2px solid {T['teal']}; outline-offset: 2px }}
.stButton button:disabled, .stFormSubmitButton button:disabled, [data-testid="stPopover"] > div > button:disabled {{
  background: {T['mist']} !important; border-color: {T['line']} !important; color: {T['muted']} !important;
  opacity: 0.7; box-shadow: none; cursor: not-allowed }}
.stButton button:disabled p, [data-testid="stPopover"] > div > button:disabled p {{ color: {T['muted']} !important }}
[class*="st-key-sr_btn_next"] button, [class*="st-key-sr_btn_rerun"] button,
[class*="st-key-sr_btn_reset"] button {{ min-width: 160px; white-space: nowrap }}

/* ---- Segmented controls and pills: white track, rich-teal selection ------------------------------------- */
[data-testid="stButtonGroup"] button {{ font-family: {SANS}; font-size: 13px; font-weight: 500; min-height: 34px;
  background: {T['card']}; border-color: {T['line_strong']}; color: {T['ink']} }}
[data-testid="stButtonGroup"] button:hover {{ background: {T['pale']}; border-color: {T['teal']}; color: {T['deep']} }}
[data-testid="stButtonGroup"] button[kind$="Active"] {{ background: {T['teal']}; border-color: {T['teal']}; color: {T['white']} }}
[data-testid="stButtonGroup"] button[kind$="Active"] p, [data-testid="stButtonGroup"] button[kind$="Active"] span {{
  color: {T['white']} }}

/* ---- Inputs: white, sea-glass hairline, rich-teal focus ring; pale-teal chips --------------------------- */
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"], .stDateInput > div > div,
.stNumberInput [data-baseweb="input"] {{ border-color: {T['line_strong']} !important; background: {T['card']} !important;
  border-radius: {RADIUS_SM} !important }}
[data-baseweb="select"] > div:hover, [data-baseweb="input"]:hover {{ border-color: {T['slate']} !important }}
[data-baseweb="select"] > div:focus-within, [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within {{
  border-color: {T['teal']} !important; box-shadow: {FOCUS}; outline: none }}
[data-baseweb="tag"] {{ background: {T['pale']} !important; color: {T['deep']} !important; border-radius: 6px !important }}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg {{ color: {T['deep']} !important; fill: {T['deep']} !important }}
[data-baseweb="popover"] li[aria-selected="true"] {{ background: {T['pale']} }}

/* ---- Tables and charts ---------------------------------------------------------------------------------- */
[data-testid="stDataFrame"] {{ border: 1px solid {T['line']}; border-radius: {RADIUS_SM}; overflow: hidden;
  font-variant-numeric: tabular-nums }}
[data-testid="stVegaLiteChart"] {{ border-radius: {RADIUS_SM} }}
[data-testid="stProgress"] p {{ font-size: 13px; color: {T['ink']} }}

/* ---- Sidebar: deep teal, white text, pale-teal active item ---------------------------------------------- */
[data-testid="stSidebar"] {{ border-right: 0 }}
[data-testid="stSidebarNav"] a {{ border-radius: {RADIUS_SM}; margin: 2px 0; padding-top: 7px; padding-bottom: 7px;
  transition: background 0.15s ease }}
[data-testid="stSidebarNav"] a:hover {{ background: rgba(255, 255, 255, 0.08) }}
[data-testid="stSidebarNav"] a span:not([data-testid="stIconMaterial"]) {{ color: {T['white']} !important;
  font-weight: 500; font-size: 14px !important }}
[data-testid="stSidebarNav"] a [data-testid="stIconMaterial"] {{ color: {T['sea']} !important }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: {T['pale']} }}
[data-testid="stSidebarNav"] a[aria-current="page"] span:not([data-testid="stIconMaterial"]) {{ color: {T['deep']} !important;
  font-weight: 600 }}
[data-testid="stSidebarNav"] a[aria-current="page"] [data-testid="stIconMaterial"] {{ color: {T['teal']} !important }}
[data-testid="stSidebar"] .stButton button {{ background: transparent; border: 1px solid rgba(255, 255, 255, 0.3);
  color: {T['white']} }}
[data-testid="stSidebar"] .stButton button p {{ color: {T['white']} }}
[data-testid="stSidebar"] .stButton button:hover {{ background: rgba(255, 255, 255, 0.08); border-color: {T['pale']} }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
  color: {T['sea']} }}
[data-testid="stSidebar"] [data-testid="stAlert"] > div {{ background: rgba(255, 255, 255, 0.1); border-color: transparent }}
[data-testid="stSidebar"] [data-testid="stAlert"] p, [data-testid="stSidebar"] [data-testid="stAlert"] [data-testid="stIconMaterial"] {{
  color: {T['white']} !important }}
/* Brand (st.logo) above the links; section headings in the page list; hairline between links and details */
[data-testid="stSidebarHeader"] {{ padding-bottom: 8px; margin-bottom: 4px }}
[data-testid="stSidebarHeader"] img, [data-testid="stLogo"] {{ height: 38px; max-width: 210px }}
[data-testid="stSidebarHeader"] > div:first-child {{ display: flex; align-items: center; gap: 10px }}
[data-testid="stSidebarHeader"] > div:first-child::after {{ content: "CHIPPY"; font-family: {HEAD}; font-weight: 700;
  font-size: 17px; letter-spacing: 0.18em; color: {T['white']}; line-height: 1 }}
[data-testid="stNavSectionHeader"] {{ font-size: 11px !important; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: {T['sea']} !important; padding-top: 14px; margin-bottom: 2px }}
[data-testid="stNavSectionHeader"] span {{ color: {T['sea']} !important }}
[data-testid="stSidebarNav"] {{ border-bottom: 1px solid rgba(255, 255, 255, 0.12); padding-bottom: 12px }}
[data-testid="stSidebarNavSeparator"] {{ display: none }}
[data-testid="stMarkdownContainer"] p.sr-side-label {{ font-size: 11px !important; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: {T['sea']}; margin: 16px 0 4px 0 }}
.sr-side-row {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 13px;
  padding: 6px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.08) }}
.sr-side-row .k {{ color: {T['sea']} }}
.sr-side-row .v {{ color: {T['white']}; font-weight: 500; text-align: right; font-variant-numeric: tabular-nums }}
.sr-side-row .sr-badge {{ margin: 0; padding: 1px 9px; font-size: 12px }}
/* ---- Sidebar Filters panel ------------------------------------------------------------------------------------
   The sidebar is deep teal with white text, but Streamlit paints the select/input control white, which leaves the
   selected value white-on-white. Repaint the controls in rich teal so the value, the caret and the slider read. */
[data-testid="stSidebar"] :is([data-testid="stSelectbox"], [data-testid="stTextInput"]) [data-baseweb="select"] > div,
[data-testid="stSidebar"] :is([data-testid="stSelectbox"], [data-testid="stTextInput"]) [data-baseweb="input"] > div {{
  background: {T['teal']} !important; border-color: rgba(255, 255, 255, 0.28) !important }}
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] * {{ color: {T['white']} !important }}
[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {{ fill: {T['sea']} !important }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ border-color: rgba(255, 255, 255, 0.18) !important }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{ font-weight: 600 }}
/* The options list renders in a body-level portal, so give it the same dark treatment. */
[data-baseweb="popover"] [role="listbox"] {{ background: {T['deep']} !important }}
[data-baseweb="popover"] [role="option"] {{ color: {T['white']} !important }}
[data-baseweb="popover"] [role="option"][aria-selected="true"] {{ background: {T['teal']} !important }}
/* ---- Chippy mascot: a small white card, the pose at 64px and a pale-teal speech bubble ------------------------- */
[class*="st-key-sr_mascot"] {{ background: {T['card']}; border: 1px solid {T['line']} !important; border-radius: {RADIUS};
  box-shadow: {SHADOW}; padding: 8px 16px 8px 10px !important; align-items: center }}
[class*="st-key-sr_mascot"] [data-testid="stImage"] img {{ width: 64px; height: 64px; object-fit: contain }}
.sr-bubble {{ position: relative; display: inline-block; background: #e3efec; color: #1e5556; border: 0;
  border-radius: 999px; padding: 7px 16px; margin-left: 20px }}
.sr-bubble::before, .sr-bubble::after {{ content: ""; position: absolute; border-radius: 50%; background: #e3efec }}
.sr-bubble::before {{ width: 7px; height: 7px; left: -10px; bottom: 6px }}
.sr-bubble::after {{ width: 4px; height: 4px; left: -17px; bottom: 3px }}
.sr-bubble .msg {{ font-family: {HEAD}; font-weight: 600; font-size: 15px; line-height: 1.35 }}
.sr-bubble .note {{ display: block; font-family: {SANS}; font-size: 12px; color: {T['slate']}; margin-top: 2px }}
/* Chippy as the assistant's avatar: an image avatar is a bare image element at the start of the chat message */
[data-testid="stChatMessage"] > img {{ width: 48px !important; height: 48px !important; object-fit: contain;
  border-radius: 0; background: transparent }}
.sr-chippy, .sr-chippy img {{ display: block; width: 72px; height: 72px; border: 0; border-radius: 10px }}
[class*="st-key-sr_mascot"] {{ padding: 6px 16px 6px 8px !important }}
.sr-emoji {{ font-size: 40px; line-height: 64px; width: 64px; text-align: center }}
/* Findings (held back, watchlist): brand and market, then what happened, then the detail */
.sr-find {{ padding: 10px 0; border-bottom: 1px solid {T['line']} }}
.sr-find:last-child {{ border-bottom: 0 }}
.sr-find .who {{ font-weight: 600; color: {T['deep']}; font-size: 14px }}
.sr-find .what {{ color: {T['deep']}; font-size: 14px; margin-top: 1px }}
.sr-find .meta {{ color: {T['slate']}; font-size: 12.5px; margin-top: 2px; font-variant-numeric: tabular-nums }}
.st-key-sr_filterbar {{ margin: 2px 0 6px 0 }}
/* KPI cards in a row share one height, so their labels and figures line up */
[data-testid="stHorizontalBlock"]:has([class*="st-key-sr_kpi"]) > [data-testid="stColumn"] > div,
[class*="st-key-sr_kpi"] {{ height: 100% }}
[class*="st-key-sr_kpi"] [data-testid="stMetricLabel"] {{ min-height: 20px }}
[class*="st-key-sr_kpi_trust"] {{ min-height: 150px }}
.sr-kpi-note {{ font-size: 12.5px; color: {T['slate']}; margin-top: 2px }}
.sr-kpi-note a {{ display: inline-block; color: {T['teal']}; font-weight: 600; text-decoration: none; margin: 4px 0 0 0 }}
.sr-kpi-note a:hover {{ text-decoration: underline }}
/* Radar weekly summary: one row (Chippy, message, action), never wrapped onto three lines */
[class*="st-key-sr_mascot"][class*="_summary"] {{ flex-wrap: nowrap !important; gap: 14px }}
[class*="st-key-sr_mascot"][class*="_summary"] > div:nth-child(2) {{ flex: 1 1 auto; min-width: 0; width: auto !important }}
[class*="st-key-sr_mascot"][class*="_summary"] .sr-bubble {{ display: block }}
[class*="st-key-sr_mascot"][class*="_summary"] > div:last-child {{ flex: 0 0 auto; width: auto !important }}
/* ---- Sidebar: pinned (Streamlit's expanded state) or unpinned: a 72px icon rail that opens over the page on
   hover or keyboard focus. Desktop widths only; on small screens Streamlit's own slide-in sidebar is kept. ---- */
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{ font-size: 0 !important; width: 20px }}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::after,
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after {{ content: "keep";
  font-family: 'Material Symbols Rounded'; font-size: 17px; line-height: 1; opacity: .85 }}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::after {{ font-variation-settings: 'FILL' 1;
  color: {T['pale']} }}
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after {{ color: {T['pale']} }}
[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] {{ display: block !important;
  visibility: visible !important; opacity: 1 !important }}
[data-testid="stExpandSidebarButton"] {{ border-radius: 8px }}
[data-testid="stExpandSidebarButton"]:hover {{ background: rgba(255, 255, 255, 0.1) }}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"] {{ position: relative }}
[data-testid="stSidebarCollapseButton"] button::before, [data-testid="stExpandSidebarButton"]::before {{
  position: absolute; left: 50%; top: calc(100% + 6px); transform: translateX(-50%); white-space: nowrap;
  background: {T['deep']}; color: {T['white']}; font: 500 12px/1.3 {SANS}; padding: 4px 8px; border-radius: 6px;
  opacity: 0; pointer-events: none; transition: opacity .15s ease; z-index: 2 }}
[data-testid="stSidebarCollapseButton"] button::before {{ content: "Unpin sidebar"; left: auto; right: 0; transform: none }}
[data-testid="stExpandSidebarButton"]::before {{ content: "Pin sidebar"; left: 0; transform: none }}
[data-testid="stSidebarCollapseButton"] button:is(:hover, :focus-visible)::before,
[data-testid="stExpandSidebarButton"]:is(:hover, :focus-visible)::before {{ opacity: 1 }}
.sr-ico {{ font-family: 'Material Symbols Rounded'; font-size: 20px; line-height: 1; font-weight: 400;
  -webkit-font-feature-settings: 'liga'; color: {T['sea']} }}
/* Compact scope block at the foot of the sidebar */
.sr-scope {{ display: flex; gap: 10px; align-items: flex-start; padding: 10px 10px; margin-top: 10px; border-radius: 10px;
  background: rgba(255, 255, 255, 0.06); outline: none }}
.sr-scope:focus-visible {{ box-shadow: 0 0 0 2px {T['pale']} }}
.sr-scope .sr-scope-body {{ flex: 1; min-width: 0 }}
.sr-scope .sr-side-row {{ padding: 3px 0; font-size: 12.5px; border-bottom: 0 }}
.sr-scope .sr-side-label {{ margin: 0 0 2px 0 !important }}
@media (min-width: 769px) {{
  [data-testid="stSidebar"][aria-expanded="false"] {{ position: fixed !important; left: 0 !important; top: 0; bottom: 0; height: 100vh !important;
    width: 68px !important; min-width: 68px !important; max-width: 68px !important; margin-left: 0 !important;
    transform: none !important; visibility: visible !important; overflow: hidden; z-index: 999989;
    transition: width .22s ease .12s, min-width .22s ease .12s, max-width .22s ease .12s, box-shadow .22s ease .12s }}
  [data-testid="stSidebar"][aria-expanded="false"]:is(:hover, :has(:focus-visible), body:has([data-testid="stExpandSidebarButton"]:hover) *) {{ width: 264px !important; min-width: 264px !important; max-width: 264px !important;
    box-shadow: 8px 0 28px rgba(23, 63, 67, 0.28); transition-delay: .08s }}
  [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMain"] {{ padding-left: 68px }}
  [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMainBlockContainer"] {{ max-width: 1480px }}
  [data-testid="stHeader"] {{ pointer-events: none }}
  [data-testid="stHeader"] [data-testid="stToolbar"], [data-testid="stHeader"] [data-testid="stToolbar"] div {{ pointer-events: none }}
  [data-testid="stHeader"] button, [data-testid="stHeader"] a {{ pointer-events: auto }}
  [data-testid="stHeader"] [data-testid="stSidebarLogo"], [data-testid="stHeader"] img.stLogo {{ display: none }}
  [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] {{ display: none }}
  [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] > span[label] {{ white-space: nowrap }}
  /* the pin: a small 30px control on the centre axis under the logo; top-right when the rail is open */
  [data-testid="stExpandSidebarButton"] {{ position: fixed !important; left: 17px; top: 62px;
    width: 30px; height: 30px; padding: 0; display: flex; align-items: center; justify-content: center;
    z-index: 999999; transition: left .22s ease .12s, top .22s ease .12s }}
  body:has([data-testid="stSidebar"][aria-expanded="false"]:is(:hover, :has(:focus-visible))) [data-testid="stExpandSidebarButton"],
  body:has([data-testid="stSidebar"][aria-expanded="false"]):has([data-testid="stExpandSidebarButton"]:hover) [data-testid="stExpandSidebarButton"] {{ left: 220px; top: 20px; transition-delay: .08s }}
  /* Keep the first track aligned with the icon rail as the sidebar reveals its labels. */
  [data-testid="stSidebarContent"] {{ scrollbar-gutter: stable; padding-inline-start: 0 }}
  [data-testid="stSidebarHeader"] {{ box-sizing: border-box; padding: 14px 0 0 !important;
    height: 52px; min-height: 52px; align-items: flex-start }}
  [data-testid="stSidebarHeader"] > div:first-child {{ display: grid; grid-template-columns: 68px auto;
    align-items: center; gap: 0 }}
  [data-testid="stSidebarHeader"] img {{ grid-column: 1; justify-self: center; height: 38px !important;
    width: auto; max-width: 44px; object-fit: contain; margin: 0 !important }}
  [data-testid="stSidebarNav"] {{ margin-inline-start: 20px }}
  [data-testid="stSidebarUserContent"] {{ margin-inline-start: 27.5px }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarHeader"] > div:first-child::after,
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavLink"] > span[label],
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:not(:has(.sr-scope)),
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) .sr-scope .sr-scope-body {{ display: none !important }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNav"] {{ padding: 40px 0 8px 0 !important; margin: 0 }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavItems"] {{ padding: 0 !important; margin: 0 }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavLinkContainer"] {{ display: flex; justify-content: center; width: 68px }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavLink"] {{ width: 44px; height: 44px; min-height: 44px; margin: 3px auto !important;
    padding: 0 !important; gap: 0; justify-content: center; align-items: center; border-radius: 10px;
    box-shadow: none !important }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavLink"] > span:first-child {{ margin: 0 !important; width: auto }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] {{ font-size: 20px !important }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stNavSectionHeader"] {{ display: block !important; height: 1px; padding: 0 !important;
    margin: 10px 18px !important; font-size: 0 !important; background: rgba(255, 255, 255, 0.14); overflow: hidden }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarUserContent"] {{ padding: 4px 0 !important }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) .sr-scope {{ width: 44px; height: 44px; margin: 4px auto 0 auto; padding: 0; justify-content: center;
    align-items: center; background: transparent; border-radius: 10px }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) .sr-scope:hover {{ background: rgba(255, 255, 255, 0.08) }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) .sr-scope .sr-ico {{ font-size: 20px }}
  /* Streamlit reserves a scrollbar gutter on both sides; a closed rail never scrolls, so the rail gets all 68px */
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarContent"] {{ scrollbar-gutter: auto !important; overflow: hidden !important }}
  /* Streamlit pads the sidebar's inner wrappers; in the closed rail every wrapper spans the full 68px instead */
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarContent"], [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarContent"] > div,
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNav"], [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavItems"], [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarNavItems"] li,
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarUserContent"], [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarUserContent"] > div {{
    padding-left: 0 !important; padding-right: 0 !important; margin-left: 0 !important; margin-right: 0 !important;
    width: 68px !important; min-width: 0 !important; max-width: 68px !important }}
  [data-testid="stSidebar"][aria-expanded="false"]:not(:hover):not(:has(:focus-visible)):not(body:has([data-testid="stExpandSidebarButton"]:hover) *) [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:has(.sr-scope) {{
    width: 68px !important; display: flex; justify-content: center }}
}}
/* ---- Floating Ask Chippy: a 64px Chippy button bottom-right that opens a compact chat panel ---- */
[data-testid="stMain"] {{ padding-bottom: 96px }}
.st-key-sr_fab {{ position: fixed !important; right: 24px; bottom: 24px; z-index: 999980; width: auto !important }}
.st-key-sr_fab [data-testid="stPopoverButton"] {{ width: 64px; height: 64px; min-height: 64px; padding: 0;
  border-radius: 50%; border: 1px solid {T['line_strong']}; background: {T['white']} url("{FAB_IMG}") center / 92%
  no-repeat; box-shadow: {SHADOW_HOVER} }}
.st-key-sr_fab [data-testid="stPopoverButton"]:hover {{ border-color: {T['teal']}; background-color: {T['white']} }}
.st-key-sr_fab [data-testid="stPopoverButton"]:focus-visible {{ outline: 2px solid {T['teal']}; outline-offset: 3px }}
.st-key-sr_fab [data-testid="stPopoverButton"] p,
.st-key-sr_fab [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {{ font-size: 0 !important;
  color: transparent !important; width: 0; margin: 0 }}
[data-testid="stPopoverBody"]:has(.st-key-sr_fab_panel) {{ width: 400px; max-width: calc(100vw - 32px);
  border-radius: {RADIUS}; border: 1px solid {T['line']}; box-shadow: 0 12px 40px rgba(23, 63, 67, 0.22) }}
.sr-fab-head {{ display: flex; align-items: center; gap: 10px }}
.sr-fab-head img {{ width: 40px; height: 40px; border-radius: 10px }}
.sr-fab-head .t {{ font-family: {HEAD}; font-weight: 700; font-size: 16px; color: {T['deep']}; line-height: 1.2 }}
.sr-fab-head .s {{ font-size: 12px; color: {T['slate']} }}
.st-key-sr_fab_panel [data-testid="stChatMessage"] {{ padding: 8px 10px; box-shadow: none; margin-bottom: 6px }}
.st-key-sr_fab_panel [data-testid="stChatMessage"] > img {{ width: 32px !important; height: 32px !important }}
.st-key-sr_fab_panel [class*="st-key-sr_mascot"] .sr-chippy, .st-key-sr_fab_panel [class*="st-key-sr_mascot"] .sr-chippy img {{
  width: 56px; height: 56px }}
.st-key-sr_fab_panel [data-testid="stForm"] {{ border: 0; padding: 0 }}
.st-key-sr_fab_panel [data-testid="InputInstructions"] {{ display: none }}
.st-key-sr_fab_panel .stButton button[kind="tertiary"] {{ justify-content: flex-start; text-align: left; width: 100% }}
.st-key-sr_fab_panel .stButton button[kind="tertiary"] p {{ text-align: left }}
/* Footer: operational metadata, quiet, one line where it fits */
.sr-footer {{ display: flex; flex-wrap: wrap; align-items: center; gap: 2px 0; margin-top: 28px; padding-top: 12px;
  border-top: 1px solid {T['line']}; font-size: 11.5px; color: {T['slate']}; font-variant-numeric: tabular-nums }}
.sr-footer .sep {{ margin: 0 8px; opacity: .6 }}
.sr-footer .dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px;
  vertical-align: 1px; background: {T['sea']} }}
.sr-footer .dot.ok {{ background: {T['teal']} }}
.sr-footer .dot.warn {{ background: {T['gold']} }}
.sr-footer .dot.bad {{ background: {T['terra']} }}
.sr-footer .st-bad {{ color: {T['deep']}; font-weight: 600 }}
.sr-side-foot {{ border-top: 1px solid rgba(255, 255, 255, 0.12); margin-top: 6px }}
/* ---- Enterprise redesign (2026-11-25): header subtitle, hero, attention, journey, workspace ---------------------- */
[data-testid="stMarkdownContainer"] p.sr-subtitle {{ font-size: 13.5px !important; color: {T['muted']}; margin: 4px 0 0 0 }}
.sr-narrow-only {{ display: none }}
.sr-scope details summary {{ cursor: pointer; list-style: none; font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: {T['sea']}; margin: 0 0 2px 0 }}
.sr-scope details summary::-webkit-details-marker {{ display: none }}
.sr-scope details summary::after {{ content: " ▾"; letter-spacing: 0 }}
.sr-scope details:not([open]) summary::after {{ content: " ▸" }}
[class*="st-key-sr_hero"] {{ background: linear-gradient(120deg, {T['deep']} 0%, {T['teal']} 100%); border-radius: 14px;
  padding: 18px 22px !important; margin-bottom: 6px; box-shadow: {SHADOW_HOVER} }}
[class*="st-key-sr_hero"] .sr-chippy, [class*="st-key-sr_hero"] .sr-chippy img {{ width: 84px; height: 84px;
  background: {T['white']}; border-radius: 12px }}
.sr-hero {{ padding-bottom: 10px }}
.sr-hero .k {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: {T['pale']}; font-weight: 600 }}
.sr-hero h2 {{ color: {T['white']} !important; font-size: 21px !important; margin: 4px 0 10px 0; padding: 0 }}
.sr-hero .m {{ display: flex; flex-wrap: wrap; gap: 8px 26px }}
.sr-hero .m div {{ font-size: 12px; color: {T['pale']} }}
.sr-hero .m b {{ display: block; font-family: {HEAD}; font-size: 18px; color: {T['white']}; font-variant-numeric: tabular-nums }}
.sr-hero .q {{ font-size: 13px; color: {T['pale']}; margin-top: 10px; max-width: 820px }}
.sr-hero .q b {{ color: {T['white']}; font-weight: 600 }}
[class*="st-key-sr_hero"] .stButton button {{ background: {T['white']}; color: {T['deep']}; border: 0; font-weight: 600 }}
[class*="st-key-sr_hero"] .stButton button:hover {{ background: {T['pale']}; color: {T['deep']} }}
[class*="st-key-sr_hero"] .stButton button p {{ color: {T['deep']} }}
.sr-att-h {{ font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: {T['muted']}; font-weight: 600;
  margin: 12px 0 4px 0 }}
.sr-att {{ border-left: 3px solid {T['gold']}; background: rgba(198, 168, 121, 0.08); border-radius: 0 8px 8px 0;
  padding: 7px 12px; margin: 6px 0 }}
.sr-att.bad {{ border-color: {T['terra']}; background: rgba(200, 121, 112, 0.08) }}
.sr-att.ok {{ border-color: {T['teal']}; background: {T['mist']} }}
.sr-att .who {{ font-weight: 600; color: {T['deep']}; font-size: 14px }}
.sr-att .what {{ color: {T['slate']}; font-size: 12.5px; font-variant-numeric: tabular-nums }}
.sr-jwrap {{ container-type: inline-size }}
.sr-journey {{ display: grid; grid-template-columns: minmax(0, 1.1fr) auto minmax(0, 1.1fr) auto minmax(0, 5fr); gap: 8px;
  align-items: stretch; margin: 4px 0 6px 0 }}
.sr-jouts {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px }}
@container (max-width: 900px) {{
  .sr-journey {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) }}
  .sr-journey > .sr-jarrow {{ display: none }}
  .sr-jouts {{ grid-column: 1 / -1; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)) }}
}}
/* Width-aware stacking: keyed sections stack their columns when they themselves are narrow */
[class*="st-key-sr_stack"] {{ container: srstack / inline-size }}
[class*="st-key-sr_hero"] {{ container: srhero / inline-size }}
@container srhero (max-width: 600px) {{
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {{ flex-wrap: wrap !important; row-gap: .6rem }}
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) > [data-testid="stColumn"] {{
    flex: 1 1 100% !important; min-width: 100% !important; width: 100% !important }}
}}
@container srstack (max-width: 820px) {{
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {{ flex-wrap: wrap !important; row-gap: 1rem }}
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) > [data-testid="stColumn"] {{
    flex: 1 1 100% !important; min-width: 100% !important; width: 100% !important }}
}}
.st-key-sr_hero_shift [data-testid="stColumn"]:first-child {{ flex: 0 0 96px !important; min-width: 96px !important; width: 96px !important }}
.st-key-sr_hero_shift [data-testid="stColumn"]:nth-child(2) {{ flex: 1 1 0 !important; min-width: 0 !important; width: auto !important }}
.st-key-sr_hero_shift [data-testid="stColumn"]:last-child {{ flex: 0 0 200px !important; min-width: 200px !important; width: 200px !important }}
.st-key-sr_hero_radar [data-testid="stColumn"]:first-child {{ flex: 0 0 96px !important; min-width: 96px !important; width: 96px !important }}
.st-key-sr_hero_radar [data-testid="stColumn"]:nth-child(2) {{ flex: 1 1 0 !important; min-width: 0 !important; width: auto !important }}
.st-key-sr_hero_radar [data-testid="stColumn"]:last-child {{ flex: 0 0 184px !important; min-width: 184px !important; width: 184px !important }}
@media (max-width: 768px) {{ [data-testid="stMainBlockContainer"] {{ padding-top: 3.75rem }} }}
@container srhero (max-width: 600px) {{
  .st-key-sr_hero_shift [data-testid="stColumn"]:nth-child(n),
  .st-key-sr_hero_radar [data-testid="stColumn"]:nth-child(n) {{ flex: 1 1 100% !important; width: 100% !important; min-width: 100% !important }}
}}
.sr-jbox {{ flex: 1 1 140px; border: 1px solid {T['line']}; border-radius: 10px; padding: 9px 12px; background: {T['white']} }}
.sr-jbox .k {{ display: block; font-size: 12px; color: {T['muted']}; line-height: 1.3 }}
.sr-jbox b {{ display: block; font-family: {HEAD}; font-size: 22px; color: {T['deep']}; font-variant-numeric: tabular-nums }}
.sr-jbox .n {{ display: block; font-size: 11.5px; color: {T['slate']} }}
.sr-jbox.ok {{ border-color: {T['teal']}; box-shadow: inset 0 3px 0 {T['teal']} }}
.sr-jbox.bad {{ border-color: {T['terra']}; box-shadow: inset 0 3px 0 {T['terra']} }}
.sr-jarrow {{ align-self: center; color: {T['slate']}; font-size: 16px }}
.sr-session {{ display: flex; gap: 8px; align-items: flex-start; background: rgba(198, 168, 121, 0.12);
  border: 1px solid {T['gold']}; border-radius: 8px; padding: 7px 12px; font-size: 13px; color: {T['ink']}; margin: 0 0 10px 0 }}
.sr-session .sr-ico {{ font-size: 18px; color: {T['deep']} }}
.st-key-sr_actionbar {{ background: {T['mist']}; border-radius: 8px; padding: 8px 12px !important; margin-top: 4px }}
.sr-steps {{ display: flex; margin: 10px 0 4px 0 }}
.sr-step {{ flex: 1; text-align: center; font-size: 12px; color: {T['slate']}; position: relative; padding-top: 24px }}
.sr-step::before {{ content: ""; position: absolute; top: 6px; left: 50%; width: 13px; height: 13px; border-radius: 50%;
  transform: translateX(-50%); background: {T['white']}; border: 2px solid {T['sea']}; z-index: 1 }}
.sr-step::after {{ content: ""; position: absolute; top: 12px; left: calc(50% + 9px); right: calc(-50% + 9px); height: 2px;
  background: {T['sea']} }}
.sr-step:last-child::after {{ display: none }}
.sr-step.done {{ color: {T['deep']}; font-weight: 600 }}
.sr-step.done::before {{ background: {T['teal']}; border-color: {T['teal']} }}
.sr-step.manual::before {{ border-style: dashed }}
.sr-step .n {{ display: block; font-weight: 400; color: {T['slate']}; font-size: 11.5px }}
/* ---- Shift Detail: investigation studio ---- */
.st-key-sr_shift_pick {{ margin-bottom: 2px }}
.sr-hero a.sr-hero-link {{ color: {T['white']}; font-weight: 600; margin-left: 6px; text-decoration: underline }}
.st-key-sr_tabs [role="radiogroup"] {{ display: flex; flex-wrap: wrap; gap: 4px; background: {T['white']};
  border: 1px solid {T['line']}; border-radius: 10px; padding: 4px; margin: 6px 0 4px 0; box-shadow: {SHADOW} }}
.st-key-sr_tabs [role="radiogroup"] label {{ margin: 0 !important; padding: 7px 14px; border-radius: 7px; cursor: pointer;
  transition: background .15s ease }}
.st-key-sr_tabs [role="radiogroup"] label > div:first-child {{ display: none }}          /* no radio circle */
.st-key-sr_tabs [role="radiogroup"] label p {{ font-size: 13.5px !important; font-weight: 500; color: {T['slate']}; white-space: nowrap }}
.st-key-sr_tabs [role="radiogroup"] label:hover {{ background: {T['mist']} }}
.st-key-sr_tabs [role="radiogroup"] label:has(input:checked) {{ background: {T['teal']} }}
.st-key-sr_tabs [role="radiogroup"] label:has(input:checked) p {{ color: {T['white']} !important }}
.st-key-sr_tabs [role="radiogroup"] label:has(input:focus-visible) {{ outline: 2px solid {T['teal']}; outline-offset: 2px }}
.st-key-sr_levers [role="radiogroup"] {{ display: flex; flex-wrap: wrap; gap: 6px }}
.st-key-sr_levers [role="radiogroup"] label {{ margin: 0 !important; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid {T['sea']}; background: {T['white']} }}
.st-key-sr_levers [role="radiogroup"] label > div:first-child {{ display: none }}
.st-key-sr_levers [role="radiogroup"] label p {{ font-size: 13px !important; color: {T['deep']} }}
.st-key-sr_levers [role="radiogroup"] label:has(input:checked) {{ background: {T['deep']}; border-color: {T['deep']} }}
.st-key-sr_levers [role="radiogroup"] label:has(input:checked) p {{ color: {T['white']} !important }}
.st-key-sr_levers [role="radiogroup"] label:has(input:focus-visible) {{ outline: 2px solid {T['teal']}; outline-offset: 2px }}
.sr-path {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px 0 }}
.sr-path a {{ font-size: 12.5px; padding: 4px 11px; border-radius: 999px; background: {T['pale']}; color: {T['teal']};
  text-decoration: none; font-weight: 500 }}
.sr-path a:hover {{ background: {T['sea']}; color: {T['deep']} }}
[data-testid="stMarkdownContainer"] p.sr-q {{ display: flex; align-items: center; gap: 10px; font-size: 11.5px !important;
  letter-spacing: 0.1em; text-transform: uppercase; color: {T['teal']}; font-weight: 700; margin: 16px 0 4px 0 }}
p.sr-q::after {{ content: ""; flex: 1; height: 1px; background: {T['line']} }}
.sr-finding {{ background: {T['white']}; border: 1px solid {T['line']}; border-left: 4px solid {T['teal']};
  border-radius: 0 12px 12px 0; padding: 12px 18px; margin: 0 0 4px 0; box-shadow: {SHADOW} }}
.sr-finding .k {{ display: block; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: {T['teal']}; font-weight: 700 }}
.sr-finding b {{ display: block; font-family: {HEAD}; font-size: 16px; color: {T['deep']}; margin: 2px 0 }}
.sr-finding .n {{ font-size: 12px; color: {T['slate']} }}
.sr-explain {{ background: {T['mist']}; border-radius: 10px; padding: 12px 14px; font-size: 13px; color: {T['ink']}; line-height: 1.55 }}
.sr-explain .n {{ display: block; margin-top: 10px; font-size: 12px; color: {T['slate']} }}
.sr-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 4px 0 10px 0 }}
.sr-jbox b.sm {{ font-size: 17px; margin: 2px 0 }}
.sr-jbox.warn {{ border-color: {T['gold']}; box-shadow: inset 0 3px 0 {T['gold']} }}
h3.sr-h3 {{ font-size: 19px !important; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0 0 2px 0; padding: 0 }}
h3.sr-h3 .sr-badge {{ font-family: {SANS}; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; margin: 0 }}
.sr-ro {{ background: rgba(198, 168, 121, 0.12); border: 1px solid {T['gold']}; border-radius: 8px; padding: 7px 12px;
  font-size: 13px; color: {T['ink']}; margin: 6px 0 10px 0 }}
@media (max-width: 1320px) {{
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-sr_kpi"]) {{ flex-wrap: wrap; row-gap: 1rem }}
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-sr_kpi"]) > [data-testid="stColumn"] {{
    flex: 1 1 calc(50% - 1rem) !important; min-width: calc(50% - 1rem) !important }}
}}
@media (max-width: 768px) {{
  .sr-narrow-only {{ display: block }}
  .sr-steps {{ flex-direction: column; gap: 6px }}
  .sr-step {{ text-align: left; padding: 0 0 0 26px }}
  .sr-step::before {{ top: 2px; left: 6px }}
  .sr-step::after {{ display: none }}
  .sr-jarrow {{ display: none }}
  .sr-hero h2 {{ font-size: 18px !important }}
  [class*="st-key-sr_hero"] .sr-chippy, [class*="st-key-sr_hero"] .sr-chippy img {{ width: 56px; height: 56px }}
}}
</style>"""

PAGES = [  # (file, title, Material icon, sidebar section); Settings is added in the admin app only.
    # File names (and so URL paths: /Brief, /Trust ...) are unchanged; only the shown titles were renamed (2026-11-25).
    ("pages/0_Radar.py", "Radar", ":material/radar:", "Intelligence"),
    ("pages/1_Shift_detail.py", "Shift Detail", ":material/insights:", "Intelligence"),
    ("pages/9_Competitive_View.py", "Competitive View", ":material/compare_arrows:", "Intelligence"),
    ("pages/2_Brief.py", "Weekly Brief", ":material/article:", "Intelligence"),
    ("pages/5_Ask_Chippy.py", "Ask Chippy", ":material/forum:", "Intelligence"),
    ("pages/6_Watchlist.py", "Watchlist", ":material/star:", "My workspace"),
    ("pages/7_Case_Files.py", "Case Files", ":material/folder_open:", "My workspace"),
    ("pages/8_Market_Time_Machine.py", "Market Time Machine", ":material/history:", "My workspace"),
    ("pages/3_Trust.py", "Data & Trust", ":material/verified:", "Operations"),
]
SETTINGS_PAGE = ("pages/4_Settings.py", "Settings", ":material/settings:", "Operations")

# Brand for st.logo: a radar mark drawn with shapes, then the wordmark as text. An image cannot load web fonts, so the
# wordmark uses the system sans-serif fallback of the Manrope stack.
_MARK = ('<rect width="32" height="32" rx="9" fill="#DCEBE8"/>'
         '<circle cx="16" cy="16" r="9.5" fill="none" stroke="#1E5556" stroke-width="1.6" opacity="0.4"/>'
         '<circle cx="16" cy="16" r="5" fill="none" stroke="#1E5556" stroke-width="1.6" opacity="0.7"/>'
         '<path d="M16 16 L23 9" stroke="#173F43" stroke-width="1.8" stroke-linecap="round"/>'
         '<circle cx="16" cy="16" r="2" fill="#173F43"/><circle cx="21.2" cy="11.6" r="1.7" fill="#C6A879"/>')
LOGO_ICON = f'<svg width="32" height="32" viewBox="0 0 32 32">{_MARK}</svg>'
LOGO = (f'<svg width="150" height="32" viewBox="0 0 150 32">{_MARK}'
        '<text x="43" y="22" font-family="Manrope, \'Segoe UI\', system-ui, sans-serif" font-size="19" '
        'font-weight="700" fill="#FFFFFF" letter-spacing="-0.2">Chippy</text></svg>')

# The official CHIPPY silhouette logo, if its files are present; otherwise the radar mark above stays in use
BRAND_DIR = Path(__file__).resolve().parent / "brand"
if (BRAND_DIR / "chippy_logo_light.png").exists():
    # inlined as a data URL: a /media/ URL lives only in the server's memory, so after a restart an open tab shows "Logo"
    import base64
    LOGO = LOGO_ICON = "data:image/png;base64," + base64.b64encode(
        (BRAND_DIR / "chippy_logo_light.png").read_bytes()).decode("ascii")
FAVICON = BRAND_DIR / "chippy_favicon.png"     # browser tab icon: local Streamlit only (Snowflake ignores page_icon)


def entry_guard(page_file: str) -> None:
    """Call first on every page. On a fresh server process, a first visit straight to a page address (a refresh, a
    bookmark, a shared link) runs that page in Streamlit's legacy pages/ mode, without the entry script: no session
    defaults, no admin flag, a sidebar of raw file names. Send that visit through the entry script, which opens the
    asked-for page again with its query (for example ?view=) once st.navigation is in place."""
    if "sr_admin" in st.session_state:                  # nav.run already ran in this session
        return
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    if ctx is None:
        return
    st.session_state["_sr_goto"] = (page_file, dict(st.query_params))
    # pages_manager is internal to Streamlit; it is stable on the pinned 1.51.0 (environment.yml). Recheck on upgrade.
    st.switch_page(Path(ctx.pages_manager.main_script_path).name)


def run(admin: bool) -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)
    st.session_state["sr_admin"] = admin
    entries = PAGES + ([SETTINGS_PAGE] if admin else [])
    sections: dict[str, list] = {}
    for n, (f, t, i, section) in enumerate(entries):
        sections.setdefault(section, []).append(st.Page(f, title=t, icon=i, default=(n == 0)))
    if FAVICON.exists():
        st.set_page_config(page_icon=str(FAVICON))       # additive: overrides only the entry point's icon
    st.logo(LOGO, size="large", icon_image=LOGO_ICON)
    page = st.navigation(sections)     # with st.navigation, Streamlit ignores automatic pages/ discovery
    goto = st.session_state.pop("_sr_goto", None)       # a direct visit sent here by entry_guard: reopen that page
    if goto and goto[0] in {f for f, *_ in entries}:   # never a page this app does not list (Settings in read-only)
        st.session_state["_sr_goto_query"] = goto[1]
        st.switch_page(goto[0])
    if (query := st.session_state.pop("_sr_goto_query", None)):
        for k, v in query.items():
            st.query_params.setdefault(k, v)
    # Remember the page shown before this one, so Radar can say "You're back!" (same session only)
    if st.session_state.get("chippy_page") != page.title:
        st.session_state["chippy_visit"] = st.session_state.get("chippy_visit", 0) + 1     # one per page visit
        st.session_state["chippy_prev_page"] = st.session_state.get("chippy_page")
        st.session_state["chippy_page"] = page.title
    st.html(CSS)
    guarded("Sidebar", sidebar, container=st.sidebar)
    if page.title != "Ask Chippy":
        guarded("Ask Chippy assistant", lambda: assistant(page.title))
    st.session_state["_sr_footer_done"] = False
    page.run()
    if not st.session_state["_sr_footer_done"]:
        guarded("Footer", footer)


def is_admin() -> bool:
    return bool(st.session_state.get("sr_admin"))


def guarded(title: str, render: Callable[[], None], container=None) -> None:
    """Run one section; on failure show a short message and a retry button, never a stack trace (L13).
    The admin app adds the first 300 characters of the Snowflake message.
    When container is given, the section renders inside it, so a section that uses bare st.* calls
    (filter_panel) lands in the sidebar instead of the page body."""
    try:
        if container is not None:
            with container:
                render()
        else:
            render()
    except Exception as e:                                    # noqa: BLE001 - every section fails soft
        box = container or st
        box.warning(f"Couldn't load {title.lower()}.")
        if is_admin():
            box.caption(str(e)[:300])
        if box.button("Retry", key=f"retry_{title}"):
            from sr_ui import data
            data.clear_cache()
            st.rerun()


# ---- Design helpers ---------------------------------------------------------------------------------------------

def nice_date(value) -> str:
    """date, datetime or ISO text -> '21 Nov 2026'; anything else as text."""
    if value is None or value == "":
        return "–"
    if isinstance(value, (date, datetime)):
        d = value
    else:
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    return f"{d.day} {d:%b %Y}"


TONE = {"SUCCEEDED": "ok", "OK": "ok", "MARKET_MOVE": "ok", "RUNNING": "accent", "WARN": "warn", "MIXED": "warn",
        "SKIPPED": "", "FAILED": "bad", "POSSIBLE_DATA_EFFECT": "bad"}


def badge(text: str, tone: str = "") -> str:
    """One pill as HTML; tone is '', 'ok', 'warn', 'bad' or 'accent'. Text is escaped."""
    return f'<span class="sr-badge {tone}">{escape(str(text))}</span>'


def badges(items: Sequence[tuple[str, str]], container=None) -> None:
    (container or st).markdown("".join(badge(t, tone) for t, tone in items), unsafe_allow_html=True)


def label(text: str, container=None) -> None:
    (container or st).markdown(f'<p class="sr-label">{escape(text)}</p>', unsafe_allow_html=True)


def section(title: str, caption: str | None = None) -> None:
    """A card heading: the title as st.subheader (tests and screen readers see it) and an optional one-line caption."""
    st.subheader(title)
    if caption:
        st.caption(caption)


def stat_strip(items: Sequence[tuple[str, object]], container=None) -> None:
    """A row of small label and value pairs inside a card (display only). Text is escaped."""
    cells = "".join(f'<div class="sr-stat"><span class="k">{escape(k)}</span><span class="v">{escape(str(v))}</span></div>'
                    for k, v in items)
    (container or st).markdown(f'<div class="sr-stats">{cells}</div>', unsafe_allow_html=True)


MASCOT_DIR = Path(__file__).resolve().parent / "mascot"
POSES = {"welcome", "ai", "thinking", "detective", "happy", "loading", "sleepy", "peek"}
_mascot_n = [0]


def mascot_path(pose: str) -> str | None:
    p = MASCOT_DIR / f"chippy_{pose}.png"
    return str(p) if pose in POSES and p.exists() else None


ANIM_DIR = MASCOT_DIR / "anim"
# Which supplied animation plays for each mascot state (the pages keep their existing pose names)
ANIM = {"welcome": "welcome", "thinking": "investigating", "investigating": "investigating", "detective": "detective",
        "loading": "loading", "working": "working", "ai": "working", "happy": "success", "success": "success",
        "peek": "peeking", "peeking": "peeking", "sleepy": "resting", "resting": "resting"}


@functools.lru_cache(maxsize=32)
def _data_uri(path: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def mascot_html(pose: str, alt: str, size: int = 72, *, html_safe: bool = False) -> str | None:
    """Chippy as an <img>: the supplied animation (animated WebP), or its first frame when the viewer prefers reduced
    motion or the browser cannot show WebP. Bundled as data URIs: no external hosting. None if the files are missing."""
    name = ANIM.get(pose)
    anim, still = ANIM_DIR / f"{name}.webp", ANIM_DIR / f"{name}_still.png"
    radar_dir = MASCOT_DIR / "radar"                     # transparent set first, on every page
    radar_anim, radar_still = radar_dir / f"{name}.webp", radar_dir / f"{name}.png"
    if radar_anim.exists() and radar_still.exists():
        anim, still = radar_anim, radar_still
    motion = ""
    if name and (pulse := _pulse(name)):                 # idle states: play, rest, and a different pose per visit
        anim, still, motion = pulse
    if not name or not anim.exists() or not still.exists():
        return None
    if html_safe:
        # st.html sanitizes data-URI srcset attributes. Switch ordinary img sources via the motion media query.
        return (f'<picture class="sr-chippy sr-chippy-html {motion}">'
                f'<img class="sr-chippy-animated" src="{_data_uri(str(anim), "image/webp")}" '
                f'width="{size}" height="{size}" alt="{escape(alt)}">'
                f'<img class="sr-chippy-still" src="{_data_uri(str(still), "image/png")}" '
                f'width="{size}" height="{size}" alt="{escape(alt)}"></picture>')
    # The animation is offered only when motion is welcome; otherwise (or without WebP) the browser shows the still.
    return (f'<picture class="sr-chippy {motion}"><source type="image/webp" media="(prefers-reduced-motion: no-preference)" '
            f'srcset="{_data_uri(str(anim), "image/webp")}">'
            f'<img src="{_data_uri(str(still), "image/png")}" width="{size}" height="{size}" alt="{escape(alt)}" '
            f'decoding="async"></picture>')


def mascot(pose: str, message: str, note: str | None = None, key: str | None = None, container=None):
    """Chippy in a small card: the pose's animation at 72px and the message in a speech bubble (real text, so it reads
    without the image). The same markup on every rerun, so Streamlit does not restart the animation. Falls back to
    the static pose, then to a squirrel emoji. Display only."""
    _mascot_n[0] += 1
    box = (container or st).container(horizontal=True, vertical_alignment="center", gap="small",
                                      key=f"sr_mascot_{pose}_{key or _mascot_n[0]}")
    with box:
        try:                                     # the picture is decoration: never let it break a page
            anim = mascot_html(pose, f"Chippy, {message}")
            path = mascot_path(pose)
            if anim:
                st.markdown(anim, unsafe_allow_html=True, width="content")
            elif path:
                st.image(path, width=64)
            else:
                st.markdown('<div class="sr-emoji">🐿️</div>', unsafe_allow_html=True, width="content")
        except Exception:                                     # noqa: BLE001 - fail soft: the message still shows
            st.markdown('<div class="sr-emoji">🐿️</div>', unsafe_allow_html=True, width="content")
        st.markdown(f'<div class="sr-bubble"><span class="msg">{escape(message)}</span>'
                    + (f'<span class="note">{escape(note)}</span>' if note else "") + "</div>",
                    unsafe_allow_html=True, width="content")
    return box


def radar_header(title: str, subtitle: str):
    """The Radar header (same key, so the same type, spacing and sidebar treatment) on the redesigned pages. Loads the
    Radar stylesheet, shows Admin and Refresh, and returns the right-hand controls container for page controls."""
    from sr_ui import data
    st.html((Path(__file__).with_name("radar.css")).read_text(encoding="utf-8"))
    with st.container(key="sr_radar_header"):
        left, right = st.columns([2, 3], vertical_alignment="center")
        left.html(f'<div class="sr-radar-title"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>')
        controls = right.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small")
        with controls:
            extra = st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small")
            if is_admin():
                st.html('<span class="sr-radar-admin">Admin</span>', width="content")
            if st.button("Refresh", icon=":material/refresh:", key="sr_btn_header_refresh"):
                data.clear_cache()
                st.rerun()
    return extra


RADAR_ANIM_DIR = MASCOT_DIR / "radar"     # the supplied animations with transparent backgrounds (looping WebP + still)
PULSE_DIR = RADAR_ANIM_DIR / "pulse"      # interval versions built by scripts/build_mascot_pulse.py from the same frames
# Idle states play their pose, then rest for several seconds, and show a different pose (or mix of poses) on each page
# visit. States that mean "working" (investigating, loading, working) keep the live loop, so activity reads as activity.
PULSE_SETS = {"welcome": ["welcome", "hello_mix"], "detective": ["hero_mix", "detective", "think_mix"],
              "success": ["success", "hello_mix"], "resting": ["resting", "rest_mix"]}
IDLE_MOTION = ["sr-idle-hop", "sr-idle-tilt", "sr-idle-bob"]     # small CSS moves between plays (radar.css)


def _pulse(name: str) -> tuple[Path, Path, str] | None:
    """(animation, still, motion class) for an idle state, chosen by the page-visit count: the same on every rerun of
    one visit (so Streamlit does not restart it), different on the next visit. None for working states."""
    options = PULSE_SETS.get(name)
    if not options:
        return None
    try:
        n = int(st.session_state.get("chippy_visit", 0))
    except Exception:                                    # noqa: BLE001 - outside a script run (imports, tests)
        n = 0
    pick = options[n % len(options)]
    anim, still = PULSE_DIR / f"{pick}.webp", PULSE_DIR / f"{pick}.png"
    if not (anim.exists() and still.exists()):
        return None
    return anim, still, IDLE_MOTION[n % len(IDLE_MOTION)]


def pulse_img(pick: str, alt: str, size: int = 64, animate: bool = True) -> str:
    """One pulse animation by name (PULSE_DIR), or only its still when animate is False (so a page can bring one
    mascot to life, for example the chosen agent card, and keep the rest still). Empty if the files are missing."""
    anim, still = PULSE_DIR / f"{pick}.webp", PULSE_DIR / f"{pick}.png"
    if not still.exists():
        return ""
    s = f'<img class="sr-anim-still" src="{_data_uri(str(still), "image/png")}" width="{size}" height="{size}" alt="{escape(alt)}">'
    if not animate or not anim.exists():
        return f'<span class="sr-anim sr-anim-static">{s.replace("sr-anim-still", "sr-anim-play")}</span>'
    return (f'<span class="sr-anim sr-idle-hop"><img class="sr-anim-play" src="{_data_uri(str(anim), "image/webp")}" '
            f'width="{size}" height="{size}" alt="{escape(alt)}">{s}</span>')


def radar_anim(name: str, alt: str, size: int = 72) -> str:
    """A supplied transparent Chippy animation as a <picture>: the animated WebP, or its still frame when the viewer
    prefers reduced motion. Bundled as data URIs. Empty if the files are missing (the text still reads on its own)."""
    anim, still = RADAR_ANIM_DIR / f"{name}.webp", RADAR_ANIM_DIR / f"{name}.png"
    motion = ""
    if (pulse := _pulse(name)):
        anim, still, motion = pulse
    if not anim.exists() or not still.exists():
        return ""
    # st.html removes data-URI srcset attributes, so both images are plain <img>; CSS shows one by motion preference.
    return (f'<span class="sr-anim {motion}"><img class="sr-anim-play" src="{_data_uri(str(anim), "image/webp")}" '
            f'width="{size}" height="{size}" alt="{escape(alt)}"><img class="sr-anim-still" '
            f'src="{_data_uri(str(still), "image/png")}" width="{size}" height="{size}" alt="{escape(alt)}"></span>')


def state(name: str, text: str, size: int = 40, tone: str = "") -> None:
    """A one-line status with a supplied transparent animation beside plain text (the text reads on its own)."""
    st.html(f'<div class="sr-state {tone}">{radar_anim(name, "Chippy", size) or mascot_html(name, "Chippy", size, html_safe=True) or ""}'
            f'<span>{escape(text)}</span></div>')


def stack(key: str):
    """A container whose columns stack when the container itself is narrow (container query), so a layout follows
    the space it has: pinned or collapsed sidebar, laptop, tablet or zoom. Use as a context manager."""
    return st.container(key=f"sr_stack_{key}")


def hero(key: str):
    """The dark-teal hero card (Radar, Shift Detail, Case Files); use as a context manager."""
    return st.container(key=f"sr_hero_{key}")


def session_note(text: str | None = None) -> None:
    """The banner every workspace page shows: its state is session-only (never presented as saved)."""
    from sr_ui import workspace
    st.markdown(f'<div class="sr-session"><span class="sr-ico" aria-hidden="true">schedule</span>'
                f'<span><b>Session only.</b> {escape(text or workspace.SESSION_NOTE.split(": ", 1)[1])}</span></div>',
                unsafe_allow_html=True)


def journey(run_id: str, n_warnings: int | None = None) -> None:
    """Signal Journey for one run (data.signal_journey): candidates -> passed the gates -> one outcome each, in the
    SP_RANK reason order. Counts are shown as stored; if the outcomes do not add up, it says so instead of an equation.
    Early warnings are a separate stream and are only mentioned, never counted in the journey."""
    from sr_ui import data
    j = data.signal_journey(run_id)
    outs = [("In the brief", j.get("N_SELECTED", 0), "ok"), ("Held for data checks", j.get("N_HELD", 0), "bad"),
            ("Repeat of an earlier week", j.get("N_REPEAT", 0), ""),
            ("Another comparison ranks higher", j.get("N_OTHER_CMP", 0), ""),
            ("Beyond the top N", j.get("N_BEYOND_TOP_N", 0), "")]
    box = lambda k, v, note="", tone="": (f'<div class="sr-jbox {tone}"><span class="k">{escape(k)}</span><b>{v:,}</b>'  # noqa: E731
                                          + (f'<span class="n">{escape(note)}</span>' if note else "") + "</div>")
    st.markdown('<div class="sr-jwrap"><div class="sr-journey">' + box("Candidates checked", j.get("N_DETECTED", 0), "brand × market × comparison")
                + '<span class="sr-jarrow" aria-hidden="true">→</span>'
                + box("Passed the gates", j.get("N_PASSED", 0), "size and significance")
                + '<span class="sr-jarrow" aria-hidden="true">→</span><div class="sr-jouts">'
                + "".join(box(k, v, tone=t) for k, v, t in outs) + "</div></div></div>", unsafe_allow_html=True)
    total = sum(v for _, v, _ in outs)
    if total == j.get("N_PASSED", 0) == j.get("N_RANKED", 0):
        st.caption(f"Each shift that passed the gates has exactly one outcome ({' + '.join(str(v) for _, v, _ in outs)} "
                   f"= {total}), in the order the weekly ranking applies its reasons. A shift that is both a repeat and a "
                   "possible data effect counts as a repeat, so this box can differ from the Possible data effects tile."
                   + (f" Early warnings ({n_warnings}) are a separate stream and are not part of this journey."
                      if n_warnings is not None else ""))
    else:
        st.caption(f"The outcome counts ({total}) do not match the shifts that passed the gates "
                   f"({j.get('N_PASSED', 0)}). Open All candidates for each shift's reason.")


def cheer() -> None:
    """Ask for 'All stocked up!' on the next page draw (after a weekly run finishes loading)."""
    st.session_state["chippy_cheer"] = True


def card(key: str, border: bool = True):
    """A white card with a soft hairline; use as a context manager. The key gives it the card style."""
    return st.container(border=border, key=f"sr_card_{key}")


def kpi_row(items: Sequence[tuple[str, object, str | None]], prefix: str = "kpi") -> None:
    """KPI cards: (label, value, help) each, one card per column, a short rich-teal rule at the top."""
    for i, (col, (name, value, tip)) in enumerate(zip(st.columns(len(items)), items)):
        with col.container(border=True, key=f"sr_kpi_{prefix}_{i}"):
            st.metric(name, value, help=tip)


def striped(df):
    """A Styler that shades every second row with mist. Display only: values and columns are unchanged."""
    def shade(frame):
        import pandas as pd
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        out.iloc[1::2, :] = f"background-color: {T['mist']}"
        return out
    return df.style.apply(shade, axis=None) if len(df) else df


def _run_attention() -> tuple[str, str] | None:
    """A header badge only when the weekly run needs attention: in progress, failed, or (admin) skipped."""
    from sr_ui import data
    if data.active_run() is not None:
        return ("Updating…", "accent")
    attempt = data.latest_attempt()
    if attempt is not None and attempt.status == "FAILED":
        return ("✕ Latest run failed", "bad")
    if attempt is not None and attempt.status == "SKIPPED" and is_admin():
        return ("– Latest run skipped", "warn")
    return None


def footer() -> None:
    """One quiet line at the foot of every page: data as of, last run, run status, bridge mode, page refreshed."""
    from sr_ui import data, format as fmt
    run, attempt = data.current_run(), data.latest_attempt()
    parts = [f"Data as of {nice_date(data.cfg('AS_OF_WEEK_END'))}"]
    if run is not None:
        last = run.ended_at or run.started_at
        parts.append(f"Last run {nice_date(last)} {last:%H:%M}")
    shown = attempt if attempt is not None and attempt.status != "SUCCEEDED" else run
    status = ""
    if shown is not None:
        tone = {"SUCCEEDED": "ok", "RUNNING": "ok", "SKIPPED": "warn", "FAILED": "bad"}.get(shown.status, "")
        label = fmt.RUN_CHIP.get(shown.status, shown.status).lstrip("✓✕–… ").strip()
        status = (f'<span class="st-{tone}"><span class="dot {tone}"></span>'
                  f'{escape(("Latest run " + label.lower()) if shown is attempt and shown is not run else label)}</span>')
    if run is not None and run.bridge_mode:
        parts.append(f"Bridge mode {run.bridge_mode}")
    parts.append(f"Page refreshed {datetime.now():%H:%M}")
    items = [escape(p) for p in parts[:2]] + ([status] if status else []) + [escape(p) for p in parts[2:]]
    st.session_state["_sr_footer_done"] = True
    st.markdown('<div class="sr-footer" role="contentinfo">' + '<span class="sep">·</span>'.join(items) + "</div>",
                unsafe_allow_html=True)


def stop() -> None:
    """st.stop() for pages that end early: draws the footer first (anything drawn after st.stop() is discarded)."""
    guarded("Footer", footer)
    st.stop()


def header(title: str, icon: str | None = None, subtitle: str | None = None) -> None:
    """Page header: a scope eyebrow and the title (st.title, so tests and screen readers see it); on the right the
    Admin tag, a status badge only when a run needs attention, and the refresh button. Routine run metadata (data as
    of, last run, status, bridge mode, page refreshed) is in the footer (footer())."""
    from sr_ui import data, format as fmt
    eyebrow, items = None, []
    try:
        markets = data.market_names()
        market = markets.get(str(data.cfg("SCOPE_PARENT_MARKET")), data.cfg("SCOPE_PARENT_MARKET"))
        eyebrow = " · ".join(escape(str(p)) for p in (
            "Share Radar", data.cfg("SCOPE_CATEGORY"), market,
            f"Focus {fmt.name(data.cfg('FOCUS_MANUFACTURER'), 'MANUFACTURER')}"))
        if is_admin():
            items.append(("Admin", "gold"))
        attention = _run_attention()
        if attention:
            items.append(attention)
    except Exception:                                         # noqa: BLE001 - the header never blocks a page
        pass
    with st.container(key="sr_header"):
        left, right = st.columns([1, 1], vertical_alignment="bottom")
        if eyebrow:                     # scope line: narrow screens only, where the sidebar is hidden
            left.markdown(f'<p class="sr-eyebrow sr-narrow-only">{eyebrow}</p>', unsafe_allow_html=True)
        left.title(f"{icon} {title}" if icon else title)
        if subtitle:
            left.markdown(f'<p class="sr-subtitle">{escape(subtitle)}</p>', unsafe_allow_html=True)
        with right:
            with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
                if items:
                    st.markdown("".join(badge(t, k) for t, k in items), unsafe_allow_html=True, width="content")
                if st.button("Refresh", icon=":material/refresh:", key="sr_btn_header_refresh",
                             help="Reload the latest data"):
                    data.clear_cache()
                    st.rerun()
    if st.session_state.pop("chippy_cheer", False):
        mascot("happy", "All stocked up!", "The latest data is loaded.", key="cheer")


# ---- Sidebar ----------------------------------------------------------------------------------------------------

def filter_panel() -> None:
    """Sidebar filters that drive Radar, Shift Detail (incl. the Brand explorer and Insight Studio), the Intelligence
    brief and the share report. Collapsed by default and labelled with the applied scope, so the side menu stays a
    menu; opening it shows the widgets. Widgets edit a draft; 'Run analysis' applies it (data.filters() reads the
    applied sr_f_* keys, defaulting to the configured scope), so one click recomputes every page from SQL."""
    from sr_ui import data, format as fmt
    ss = st.session_state
    f = data.filters()
    tree, mkts, weeks = data.product_tree(), data.market_tree(), data.filter_weeks()
    labels = {r.MARKET_ID: ("" if r.MARKET_LEVEL == "TOTAL" else "· " if r.MARKET_LEVEL != "CITY" else "· · ")
              + str(r.MARKET_NAME) for r in mkts.itertuples()}
    market_name = str(labels.get(f.market_id, f.market_id)).lstrip("· ")
    summary = " · ".join([str(f.category), market_name, f"{f.weeks}w"])
    with st.expander(f"Filters · {summary}", expanded=bool(ss.pop("sr_filters_open", False)),
                     icon=":material/tune:"):
        with st.form("sr_filter_form", border=False):
            wk_opts = weeks or [f.as_of]
            week = st.selectbox("As-of week", wk_opts, index=wk_opts.index(f.as_of) if f.as_of in wk_opts else 0,
                                help="Analyse the data as it stood at the end of this week (back to 2020).")
            cats = sorted(tree.CATEGORY.unique())
            cat = st.selectbox("Category", cats, index=cats.index(f.category) if f.category in cats else 0)
            mfrs = ["All companies"] + sorted(tree[tree.CATEGORY == cat].MANUFACTURER.unique())
            mfr = st.selectbox("Company", mfrs,
                               format_func=lambda m: m if m == "All companies" else fmt.name(m, "MANUFACTURER"),
                               index=mfrs.index(f.manufacturer) if f.manufacturer in mfrs else 0)
            sub = tree[(tree.CATEGORY == cat) & ((mfr == "All companies") | (tree.MANUFACTURER == mfr))]
            brands = ["All brands"] + sorted(sub.BRAND.unique())
            brand = st.selectbox("Brand", brands, format_func=lambda b: b if b == "All brands" else fmt.name(b),
                                 index=brands.index(f.brand) if f.brand in brands else 0)
            ids = list(labels)
            market = st.selectbox("Market", ids, format_func=labels.get,
                                  index=ids.index(f.market_id) if f.market_id in ids else 0,
                                  help="All India splits into regions; a region splits into its cities.")
            period = st.select_slider("Period (weeks)", data.PERIODS, value=f.weeks if f.weeks in data.PERIODS else 4)
            go = st.form_submit_button("Run analysis", icon=":material/play_arrow:", type="primary", width="stretch")
        if go:
            ss["sr_f_week"], ss["sr_f_cat"] = week, cat
            ss["sr_f_mfr"] = "" if mfr == "All companies" else mfr
            ss["sr_f_brand"] = None if brand == "All brands" else brand
            ss["sr_f_market"], ss["sr_f_period"] = market, period
            st.rerun()
        if data.filters_active():
            run = data.run_for_week(f.as_of)
            st.caption("Stored radar run for this week." if run else
                       "No stored radar run for this week: Radar shows the nearest run; analysis pages use this week.")
            if st.button("Reset filters", icon=":material/restart_alt:", key="sr_btn_filters_reset", width="stretch"):
                data.reset_filters()
                st.rerun()


def _rows(pairs: Sequence[tuple[str, object]]) -> str:
    return "".join(f'<div class="sr-side-row"><span class="k">{escape(k)}</span><span class="v">{escape(str(v))}</span></div>'
                   for k, v in pairs)


def sidebar() -> None:
    """Below the page links: 'Names masked' when aliases are on, the compact scope block, then the viewer and the
    CoWork agent. The brand sits above the links (st.logo in run()). Run metadata is in the footer (footer()), run
    alerts and the refresh button are in the header (header())."""
    from sr_ui import data, format as fmt
    sb = st.sidebar
    markets = data.market_names()
    scope = [("Category", data.cfg("SCOPE_CATEGORY")),
             ("Market", markets.get(str(data.cfg("SCOPE_PARENT_MARKET")), data.cfg("SCOPE_PARENT_MARKET"))),
             ("Focus", fmt.name(data.cfg("FOCUS_MANUFACTURER"), "MANUFACTURER"))]
    if data.cfg("DISPLAY_ALIAS") is True:
        sb.markdown(badge("Names masked", "accent"), unsafe_allow_html=True)
    if hasattr(data, "filters") and hasattr(data, "product_tree"):
        guarded("Filters", filter_panel, container=sb)
    else:                                                     # data modules without filters (tests): the scope text
        tip = "Scope · " + " · ".join(f"{k}: {v}" for k, v in scope)
        sb.markdown(f'<div class="sr-scope" tabindex="0" role="group" aria-label="{escape(tip)}" title="{escape(tip)}">'
                    '<span class="sr-ico" aria-hidden="true">tune</span><div class="sr-scope-body"><details open>'
                    '<summary class="sr-side-label">Current scope</summary>' + _rows(scope) + "</details></div></div>",
                    unsafe_allow_html=True)
    sb.markdown('<div class="sr-side-foot"></div>', unsafe_allow_html=True)
    viewer = data.viewer_name() or "Viewer unknown"
    if st.session_state.get("chippy_page") == "Radar":
        masking = "Names masked" if data.cfg("DISPLAY_ALIAS") is True else "Names shown"
        sb.html(f'<div class="sr-radar-viewer"><span class="sr-ico">account_circle</span>'
                f'<div><strong>{escape(viewer)}</strong><small>{masking}</small></div></div>')
        return
    sb.caption(f"Viewer: {viewer}")
    sb.caption("Ask follow-up questions on the Ask Chippy page, or in CoWork: AI & ML › Agents › Chippy.")


# ---- Floating Ask Chippy ----------------------------------------------------------------------------------------
# The same agent, the same conversation and the same message format as the Ask Chippy page (data.ask_agent with
# st.session_state.chats[data.AGENT]); this is only a second, compact view of it.

def _fab_suggestions(page_title: str) -> list[str]:
    from sr_ui import data, format as fmt
    run = data.current_run()
    markets = data.market_names()
    if page_title == "Shift Detail" and run is not None and st.session_state.get("shift_id"):
        s = data.shift(st.session_state.shift_id)
        if s:
            b, m = fmt.name(s["BRAND"]), markets.get(s["MARKET_ID"], s["MARKET_ID"])
            verb = "lose" if float(s["D_SHARE_PTS"]) < 0 else "gain"
            return [f"Why did {b} {verb} share in {m}, {fmt.CMP_TEXT.get(s['CMP_CODE'], s['CMP_CODE'])}?",
                    f"Who {'took the share' if verb == 'lose' else 'did the share come from'} for {b} in {m}?",
                    f"Is the {b} change in {m} real or a data effect?"]
    if page_title == "Radar" and run is not None:
        top = data.shifts(run.run_id)
        top = top[top.SELECTED].sort_values("RANK_NO")
        if len(top):
            r = top.iloc[0]
            b, m = fmt.name(r.BRAND), markets.get(r.MARKET_ID, r.MARKET_ID)
            direction = "losing" if float(r.D_SHARE_PTS) < 0 else "gaining"
            return [f"Why is {b} {direction} market share in {m}?",
                    f"Which driver had the largest impact on {b} in {m}?",
                    f"Which brands gained market share in {m}?",
                    f"What should I investigate next for {b} in {m}?"]
    if page_title == "Competitive View" and st.session_state.get("cv_suggestions"):
        return list(st.session_state["cv_suggestions"])        # built from the page's own figures
    if page_title == "Weekly Brief":
        return ["Summarise this week's brief in three points.", "What changed this week?"]
    return ["What changed this week?", "Which shifts were held back for data checks, and why?"]


def _fab_show(msg: dict, docked: bool = False) -> None:
    from sr_ui import data
    assistant_ = msg["role"] == "assistant"
    empty = assistant_ and not msg.get("failed") and not (msg.get("text") or "").strip() and not msg.get("tables")
    pose = "sleepy" if assistant_ and (msg.get("failed") or empty) else "ai"
    avatar = ":material/person:"
    if assistant_:
        avatar = (None if docked else mascot_path(pose)) or ":material/smart_toy:"
    with st.chat_message(msg["role"], avatar=avatar if not docked else None):
        if docked and assistant_:
            animation = mascot_html("sleepy" if msg.get("failed") else "welcome", "", 30) or ""
            st.html(f'<div class="sr-dock-response-avatar" aria-hidden="true">{animation}</div>')
        st.markdown(msg.get("text") or ("_Hmm, my basket is empty!_" if empty else ""))
        if docked and (msg.get("tables") or msg.get("tools")):
            st.markdown("**Evidence & References**")
        for title, df in msg.get("tables") or []:
            if title:
                st.caption(title)
            st.dataframe(df, hide_index=True, width="stretch")
        if docked and msg.get("tools"):
            st.caption("Tools: " + ", ".join(msg["tools"]))
        for w in msg.get("warnings") or []:
            st.caption(w)


def _fab_agent() -> str:
    """The agent the floating panel asks: the panel's own switch, else Chippy. Always one of data.AGENTS."""
    from sr_ui import data
    a = st.session_state.get("sr_fab_agent")
    return a if a in data.AGENTS else data.AGENT


def _fab_ask(chat: dict, question: str, slot) -> None:
    from sr_ui import data
    agent = _fab_agent()
    who = data.AGENTS[agent]["label"]
    chat["msgs"].append({"role": "user", "text": question})
    mascot("thinking", "Let me think…", f"{who} is checking the numbers.", key="fab_wait", container=slot)
    try:
        r = data.ask_agent(question, chat["thread"], chat["parent"], agent=agent)
    except Exception as e:                                       # noqa: BLE001 - fail soft, like the Ask Chippy page
        slot.empty()
        msg = {"role": "assistant", "agent": who, "agent_id": agent, "failed": True,
               "text": f"{who} couldn't answer that just now. Try again in a moment."}
        if is_admin():
            msg["warnings"] = [str(e)[:300]]
        chat["msgs"].append(msg)
        return
    slot.empty()
    chat["thread"], chat["parent"] = r["thread_id"], r["message_id"]
    chat["msgs"].append({"role": "assistant", "agent": who, "agent_id": agent, "question": question,
                         **{k: r[k] for k in ("text", "tables", "tools", "warnings")}})


def _toggle_radar_assistant() -> None:
    st.session_state["sr_radar_chat_open"] = not st.session_state.get("sr_radar_chat_open", False)


def assistant(page_title: str) -> None:
    """Use a dock on Radar and the existing popover on other pages."""
    if page_title not in ("Radar", "Shift Detail", "Competitive View", "Weekly Brief", "Watchlist", "Case Files", "Market Time Machine",
                          "Data & Trust", "Settings"):
        with st.container(key="sr_fab"), st.popover("Ask Chippy AI", help="Ask Chippy AI"):
            _assistant_panel(page_title)
        return

    if st.session_state.get("sr_radar_chat_open"):
        _assistant_panel(page_title, docked=True)
        return

    with st.container(key="sr_radar_launcher"):
        st.button("Ask Chippy AI", key="sr_radar_open", on_click=_toggle_radar_assistant)
        welcome = PULSE_DIR if (PULSE_DIR / "welcome.webp").exists() else MASCOT_DIR / "radar"   # waves, then rests
        animated = _data_uri(str(welcome / "welcome.webp"), "image/webp")
        still = _data_uri(str(welcome / "welcome.png"), "image/png")
        target = ".st-key-sr_radar_launcher button::before"
        st.html(f'<style>{target} {{background-image:url("{animated}");}}'
                f'@media (prefers-reduced-motion: reduce) {{{target} {{background-image:url("{still}");}}}}</style>')


def _assistant_panel(page_title: str, docked: bool = False) -> None:
    from sr_ui import data

    chats = st.session_state.setdefault("chats", {})
    agent = _fab_agent()
    chat = chats.setdefault(agent, {"msgs": [], "thread": None, "parent": 0})   # shared with the Ask Chippy page
    key = "sr_radar_dock" if docked else "sr_fab_panel"
    with st.container(key=key):
        if docked:
            with st.container(key="sr_dock_header", horizontal=True, vertical_alignment="center", gap="small"):
                head, act = st.container(), st.container()
        else:
            head, act = st.columns([3, 2], gap="small", vertical_alignment="center")
        icon = mascot_path("ai")
        avatar = (mascot_html("welcome", "", 42) or "") if docked else (f'<img src="{_fab_avatar()}" alt="">' if icon else "")
        description = "Your AI market analyst" if docked else "Explains share shifts with the exact numbers"
        heading = ('<div class="sr-fab-head">' + avatar
                   + f'<div><div class="t">Ask Chippy AI</div><div class="s">{description}</div></div></div>')
        if docked:
            head.html(heading)
        else:
            head.markdown(heading, unsafe_allow_html=True)
        with act.container(key="sr_dock_header_actions" if docked else None, horizontal=True,
                           horizontal_alignment="right", gap="small"):
            if docked:
                st.button("", icon=":material/close:", key="sr_radar_close", on_click=_toggle_radar_assistant,
                          help="Close Ask Chippy", type="tertiary")
            if st.button("", icon=":material/open_in_full:", key="sr_fab_full", help="Open the full Ask Chippy page",
                         type="tertiary"):
                st.switch_page("pages/5_Ask_Chippy.py")
            if (docked or chat["msgs"]) and st.button("", icon=":material/add_comment:", key="sr_fab_new", help="New conversation",
                                          type="tertiary"):
                chats[agent] = {"msgs": [], "thread": None, "parent": 0}
                st.rerun()
        if st.session_state.get("sr_fab_agent") not in data.AGENTS:
            st.session_state["sr_fab_agent"] = data.AGENT
        with st.container(key="sr_fab_agent_pick"):       # a radio styled as chips (B17: AppTest reruns radios)
            st.radio("Who answers", list(data.AGENTS), key="sr_fab_agent", horizontal=True,
                     format_func=lambda a: data.AGENTS[a]["label"], label_visibility="collapsed",
                     help=" · ".join(f"{v['label']}: {v['purpose']}" for v in data.AGENTS.values()))
        unavailable = getattr(data, "AI_UNAVAILABLE_REASON", None) if docked else None
        if docked:
            tab = st.radio("Assistant view", ["Ask", "History"], horizontal=True, label_visibility="collapsed",
                           key="sr_radar_chat_tab")
            run = data.current_run()
            context = [page_title]
            if run and run.scope_key == data.scope_key():
                market = data.cfg("SCOPE_PARENT_MARKET")
                context += [data.cfg("SCOPE_CATEGORY"), data.market_names().get(str(market), market)]
            if run and run.as_of_week:
                context.append(f"W/E {nice_date(run.as_of_week)}")
            summary = " &middot; ".join(escape(str(item)) for item in context if item)
            st.html('<div class="sr-dock-context"><span class="sr-ico" aria-hidden="true">layers</span>'
                    f'<div><strong>Current context</strong><br>{summary}</div></div>')
            if unavailable:
                st.html('<div class="sr-dock-notice" role="status"><span class="sr-ico" aria-hidden="true">info</span>'
                        f'<span>{escape(unavailable)}</span></div>')
            if tab == "History":
                with st.container(key="sr_fab_history", height="stretch"):
                    if not chat["msgs"]:
                        st.caption("No conversation yet.")
                    for msg in chat["msgs"]:
                        _fab_show(msg, docked=True)
                return
        history = st.container(height="stretch" if docked else (300 if chat["msgs"] else "content"),
                               key="sr_fab_history")
        picked = None
        with history:
            for m in chat["msgs"][-10:]:
                _fab_show(m, docked=docked)
            if not docked and not chat["msgs"]:
                st.caption("Try a question about this page")
                for i, q in enumerate(_fab_suggestions(page_title)):
                    if st.button(q, key=f"sr_fab_sugg_{i}", icon=":material/chat_bubble:", type="tertiary"):
                        picked = q
            slot = st.empty()
            if docked:
                with st.container(key="sr_radar_suggestions", gap=None):
                    st.markdown("**Suggested questions**")
                    for i, q in enumerate(_fab_suggestions(page_title)):
                        if st.button(q, key=f"sr_fab_sugg_{i}", icon=":material/chat_bubble:",
                                     width="stretch", disabled=bool(unavailable)):
                            picked = q
        with st.form("sr_fab_form", clear_on_submit=True, border=False):
            c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
            text = c1.text_input("Message Chippy", placeholder="Ask a follow-up?" if docked else "Ask about a share shift",
                                 label_visibility="collapsed", disabled=bool(unavailable))
            sent = c2.form_submit_button("", icon=":material/send:", help="Send", type="primary", disabled=bool(unavailable))
        if not docked:
            st.caption("Click Chippy or anywhere outside to minimise. The conversation is kept.")
        question = (picked or (text.strip() if sent and text else None)
                    or (st.session_state.pop("sr_dock_pending", None) if docked else None))   # a page's suggested question
        if question and not unavailable:
            _fab_ask(chat, question, slot)
            st.rerun()


def _fab_avatar() -> str:
    p = MASCOT_DIR / "chippy_ai.png"
    return ("data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")) if p.exists() else ""
