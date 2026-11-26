# CHIPPY UI redesign: change log and rollback (25–26 November 2026)

Baseline: the original project download (`chippy-main.zip`, 25 November 2026). Compared file by file (line endings
ignored; caches and virtual environments excluded): **54 added, 21 modified, 1 deleted**.

## Backend impact: none

- **No changes** under `sql/`, `python/sr_lib/`, `kb/`, `eval/`, `scripts/` or `tests/sql/`. No new database
  objects, grants, roles, tasks, policies, prompts or agents.
- **Changes in `streamlit/sr_ui/data.py`, the only file in the apps that queries Snowflake:**
  - Four new functions, all read-only `SELECT`s on objects the app roles can already read (`701_grants.sql`):
    `previous_week_run`, `run_history` (`OPS.RUN_LOG`), `signal_journey` (`APP.SHIFT_CANDIDATE`, `APP.SHIFT_RANKED`)
    and `total_market_name` (`SRC.V_SRC_MARKET`).
  - `viewer_name` now keeps the viewer's name in their own session instead of the shared cache.
  - `watchlist` changed without touching which objects it reads.
- **Unchanged:** no calculation, threshold or fact-pack logic changed. The admin task starts (`start_task`) and
  the agent call (`ask_agent`) are the same.

## Added (54)

| Area | Files |
| --- | --- |
| New pages | `streamlit/pages/6_Watchlist.py`, `7_Case_Files.py`, `8_Market_Time_Machine.py` |
| UI modules | `streamlit/sr_ui/radar.css` (shared stylesheet), `workspace.py` (session-only Watchlist and Case Files), `market_view.py` (map), `signal_journey_view.py`, `world_countries_110m.json` with its LICENSE (map shapes) |
| Brand and mascot | `streamlit/sr_ui/brand/` (logo, favicon), `streamlit/sr_ui/mascot/` (35 files: original Chippy poses, transparent animations in `radar/`, further animations in `anim/`) |
| Local demo (not deployed) | `streamlit/demo_chippy.py`, `demo_chippy_admin.py`, `demo/demo_data.py`, `run_chippy.bat`, `run_chippy.sh`, `requirements-demo.txt`, `RUN_LOCALLY.md` |
| Documentation | `docs/UI_HANDOVER.md`, `docs/CHANGELOG_UI.md` |

## Modified (21)

| Area | Files |
| --- | --- |
| Pages | `streamlit/pages/0_Radar.py`, `1_Shift_detail.py`, `2_Brief.py`, `3_Trust.py`, `4_Settings.py`, `5_Ask_Chippy.py` |
| UI modules | `streamlit/sr_ui/nav.py`, `charts.py`, `data.py` (see above) |
| Entry and config | `streamlit/streamlit_app.py`, `admin_app.py`, `.streamlit/config.toml` (theme) |
| Tests | `python/tests/test_ui_pages.py` (new pages and sections; no assertion weakened) |
| Docs and agent config | `README.md`, `docs/LLD.md`, `docs/TESTS_AND_COCO.md`, `docs/decisions.md`, `docs/demo_script.md`, `.claude/skills/sr-streamlit/SKILL.md`, `.cortex/skills/sr-streamlit/SKILL.md` (kept identical), `.sr_ticket` |

## Deleted (1)

`streamlit/local_run.py`, a preview-only launcher that nothing referenced. The demo starts from `demo_chippy*.py`.

## Rollback

The redesign touches only the Streamlit apps, so any rollback is an app redeploy and leaves data, pipeline and
agents alone.

1. **Whole UI.** Restore `streamlit/` from the original download (or from
   `chippy-main_backup/chippy-main_before_final_radar_ai_20261125/`). Then from `streamlit/` run
   `snow streamlit deploy share_radar --replace --role SR_UI -c sr` and the same for `share_radar_admin` with
   `--role SR_APP`. Nothing in Snowflake needs undoing.
2. **One page.** Replace that file under `streamlit/pages/`. Per-page backups taken before each change are in
   `chippy-main_backup/` (suffix `_20261126`). Redeploy as above.
3. **Styling only.** Restore `streamlit/sr_ui/radar.css`; pages fall back to the base theme in `nav.py`.
4. **Data access.** Revert `streamlit/sr_ui/data.py` together with the pages, because the new pages call its four
   new read functions.

Keep a copy of the ZIP you deploy from: it is the rollback point for the next release.
