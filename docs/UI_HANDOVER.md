# CHIPPY UI handover (November 2026)

This document covers the CHIPPY and CHIPPY_ADMIN Streamlit apps after the November 2026 UI redesign: what changed,
how the UI code is organised, how to run and deploy it, what was tested, and what is still open. The pipeline, SQL
objects, calculations, agents and prompts are unchanged; see `README.md` and `docs/HLD.md`, `docs/LLD.md` for those.

## 1. The two apps

| App | Snowflake object | Entry file | Role | Can do |
| --- | --- | --- | --- | --- |
| CHIPPY | `SR_DB.APP.CHIPPY` | `streamlit/streamlit_app.py` | `SR_UI` | Read only |
| CHIPPY_ADMIN | `SR_DB.APP.CHIPPY_ADMIN` | `streamlit/admin_app.py` | `SR_APP` | Read, plus start the replay, rerun and health tasks, and edit Settings |

Both apps share `streamlit/pages/` and `streamlit/sr_ui/`. Admin mode is set by the entry file on every run
(`nav.is_admin()`); it cannot be set from the address bar or a widget. Snowflake roles are the real enforcement: the
read-only app's owner role cannot execute tasks or write settings.

## 2. Pages

| Section | Page | File | Main elements |
| --- | --- | --- | --- |
| Intelligence | Radar | `pages/0_Radar.py` | Hero (top shift, Chippy detective, "Pssst… I found something." whisper with typing dots), four KPI cards, Market Movement Overview, Market View map (Share / Movement / Value), Detected Market Shifts (filters, gain/loss colours, row actions), Market Momentum (four cards with sparklines; a click opens that week in Market Time Machine), All candidates |
| | Shift Detail | `pages/1_Shift_detail.py` | One-row toolbar (shift selector, ‹ ›, period, data status, icon-only Copy / Watch / Case file); underline tabs Investigation, Future Trends, Statistical Evidence, Market Footprint, Product Intelligence (the tab is kept in the address as `?view=`) |
| | Weekly Brief | `pages/2_Brief.py` | One-row toolbar (brief selector, ‹ ›, metadata, icon-only Copy); executive summary; one insight card per shift (Finding, Business impact, Recommended action, Ask next); held-back and early-warning lists; sources; print layout |
| | Ask Chippy | `pages/5_Ask_Chippy.py` | Agent switch, welcome with four starters, thread with Table/Chart toggle, evidence chips, copy and retry; animated thinking, loading, success and error states |
| My workspace | Watchlist | `pages/6_Watchlist.py` | Followed shifts as cards with sparklines and "Since last week"; early warnings with Add to Watchlist |
| | Case Files | `pages/7_Case_Files.py` | Status filter with counts, search, steps, evidence, decision hub (notes, reviewed flag, timeline) |
| | Market Time Machine | `pages/8_Market_Time_Machine.py` | Read-only view of any stored week: week chips, KPI cards with difference from the latest week, archived brief, signal journey |
| Operations | Data & Trust | `pages/3_Trust.py` | Chippy status line and four KPI cards; underline tabs Overview (pipeline health, Signal Journey), Validation (golden set, reconciliation, SQL tests), Run History (run table, step timeline), Cost & Usage |
| Admin only | Settings | `pages/4_Settings.py` | Edits `OPS.SETTINGS`; viewers are sent back to Radar |

The floating **Ask Chippy AI** launcher (bottom right) opens the assistant panel on Radar, Shift Detail, Weekly Brief,
the workspace pages, Data & Trust and Settings.

**Workspace is session only.** Watchlist, Case Files, notes and statuses live in `st.session_state["sr_ws"]`
(`sr_ui/workspace.py`). Nothing is written to Snowflake, so they are lost when the browser tab closes.

## 3. UI code map

| File | Purpose |
| --- | --- |
| `sr_ui/data.py` | Every query and action (rule 9). Reads cached with `st.cache_data(ttl=120)`; values bound with `?` parameters; task and agent names checked against fixed allow-lists |
| `sr_ui/nav.py` | Navigation, theme tokens, headers (`radar_header`), cards, guarded sections, mascot helpers (`mascot`, `mascot_html`, `radar_anim`, `state`), the assistant launcher and panel |
| `sr_ui/radar.css` | The shared stylesheet (Deep Teal & Mist: `#173F43`, `#F5F8F8`, teal `#1E5556`, terracotta `#C87970`, gold `#C6A879`; Manrope and Inter). New rules are appended before `</style>` |
| `sr_ui/charts.py`, `sr_ui/market_view.py` | Altair charts and the Market View map |
| `sr_ui/signal_journey_view.py` | Signal Journey (Data & Trust, Time Machine) |
| `sr_ui/workspace.py` | Session-only Watchlist and Case Files |
| `sr_ui/forecast.py` | Future Trends models (statsmodels; TCN only with PyTorch) |
| `sr_ui/mascot/` | Original Chippy art: `radar/` holds the transparent looping WebP animations with PNG stills (welcome, investigating, loading, success, resting, detective); `anim/` holds further animations; `chippy_*.png` are static fallbacks |

## 4. Animation and motion

- **Mascot animations** are the supplied WebP files, not regenerated assets or CSS-animated mascots:
  - Radar hero: detective
  - Empty states: resting
  - Ask Chippy: welcome, investigating (thinking), loading, success and resting (error)
  - Data & Trust: success when every check passes, detective when one fails
  - Case Files: success once a case opens
  - Time Machine: loading while a newly chosen week opens
- **Reduced motion.** Each animation is embedded as a data URI next to its PNG still. CSS shows the still to viewers
  who prefer reduced motion.
- **Interface motion** is CSS only and starts no reruns:
  - cards rise in, charts fade in
  - buttons lift on hover, sidebar links fade on hover
  - a shimmer shows on elements that are reloading
  - a short pulse on "On your watchlist"

  All of it is switched off for reduced motion.
- **Speech bubbles** use the Whisper style: a soft pill with two trailing dots towards Chippy. On dark backgrounds
  they are `#143F43` with `#C6E3DE` text; on light backgrounds `#E3EFEC` with teal text.

Added, modified and deleted files compared with the original project, the backend impact (none outside four
read-only queries) and the rollback steps are in `docs/CHANGELOG_UI.md`.

## 5. Run locally (no Snowflake)

See `RUN_LOCALLY.md`. In short: `run_chippy.bat` (Windows) or `bash run_chippy.sh`. CHIPPY opens on port 8501 and
CHIPPY_ADMIN on 8502, both on invented sample data:
- the sample data lives in `demo/` and `python/tests/`, separate from the app code
- every page shows a "Local preview · sample data" label
- Ask Chippy is switched off locally

## 6. Deploy to Snowflake

The apps are defined in `streamlit/snowflake.yml` (warehouse runtime, `environment.yml`, Streamlit 1.51.0). From
`streamlit/`:

```
snow streamlit deploy share_radar --replace --role SR_UI -c sr
snow streamlit deploy share_radar_admin --replace --role SR_APP -c sr
```

Each person's `sr` connection lives in `~/.snowflake/config.toml`, never in this repository. The demo files
(`demo_chippy*.py`, `demo/`, `run_chippy.*`, `requirements-demo.txt`) are not in the deployment artifacts. The full
pipeline deployment order is in `README.md`.

## 7. Tests and verification (26 November 2026)

**Verified locally, without Snowflake:**
- `pytest -q python/tests tests/local`: 184 passed, 1 skipped (the TCN test, which needs PyTorch), 1 deselected
  (integration).
- This covers:
  - every page of both apps run headless
  - Watchlist and Case Files flows, and the Ask Chippy hand-off and message flow (with a stubbed agent)
  - Scenario lab, forecasts and backtests
  - bridge, validator, renderer and fact pack calculations
  - the repository's SQL on DuckDB against synthetic data
- Browser walk-through of all nine pages in viewer and admin mode: no exceptions, no error alerts, no failed
  sections. Settings redirects viewers to Radar.
- Static checks:
  - no SQL, `AI_COMPLETE`, `SELECT *`, `SHOW` or `DESCRIBE` outside `sr_ui/data.py`
  - no credentials or keys in files
  - every task start sits behind `is_admin()` and an allow-list
  - the agent question is a bound parameter

**Needs live Snowflake (not verifiable here):**
- Ask Chippy answers from the Cortex agents (`DATA_AGENT_RUN`), including the evidence chips and tables.
- Role privileges (`SR_UI` read only, `SR_APP` task execution), row access policy `RAP_ENTITLED`, and
  `CURRENT_USER()` (READ SESSION) for the viewer name.
- Load next week, Rerun this week, Reset and Check health now against the real tasks, and their progress panel.
- Rendering inside Snowflake: Streamlit 1.51 on the warehouse runtime, the content security policy for data-URI
  images and Google Fonts, and the Anaconda packages in `environment.yml` (PyTorch for TCN).
- Email of the brief, cost snapshot data (needs account usage access), and real NIQ data volumes.

## 8. Performance and security notes

- **Caching.** All 37 read functions are cached for 120 seconds. Forecast fits are cached per series. Run and step
  reads stay uncached because they drive progress.
- **Page weight.** Server-side render is about 1 to 1.5 seconds per page with sample data; the first Forecast
  backtest is about 11 seconds, then cached.
- **Mascots.** Animations are about 85 to 235 KB each, inlined as data URIs. Streamlit's message cache stops
  repeated reruns from resending them. The PNGs are already losslessly optimal.
- **Viewer name.** It is kept per session rather than in the shared cache, so a shared (container) runtime never
  shows one viewer's name to another.
- **Row access and caching.** The cached reads assume the warehouse runtime, where each viewer has their own app
  process. If the apps move to the container runtime, the reads behind the row access policy must be cached per
  viewer as well.

## 9. Known limitations

- Workspace data (Watchlist, Case Files, notes) is session only by design.
- The `anim/peeking` and `anim/working` animations have a white background, so they are not used where transparency
  matters. There is no dedicated error, brief-reading, time-travel or data-check animation; resting, success, loading
  and detective stand in.
- The sample data shows a "Market move" status on a shift where a medium data rule fired. This is a quirk of the
  sample data only.
- The TCN forecast needs PyTorch. Without it, the model shows as unavailable and the other three models run.
- In Ask Chippy, the user's own message bubbles are not right-aligned.
