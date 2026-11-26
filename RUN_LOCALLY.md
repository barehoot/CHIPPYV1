# Running CHIPPY on your laptop

CHIPPY is two Streamlit apps built from one codebase:

- **CHIPPY**: the read-only app. Intelligence: Radar, Shift Detail, Weekly Brief, Ask Chippy. My workspace:
  Watchlist, Case Files, Market Time Machine. Operations: Data & Trust.
- **CHIPPY_ADMIN**: the same app plus the weekly-run controls and the Settings page.

In production both run inside Snowflake. This package runs them locally on **built-in sample data**, so you don't
need a Snowflake account. The sample brands, markets and numbers (Crunchy, Golden Bake, Acme Foods and so on) are
made up.

## What you need

- Python 3.11, 3.12 or 3.13 ([python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH").
- About 500 MB of disk space for the packages.
- An internet connection the first time, to install the packages.

## Quick start

**Windows:** double-click `run_chippy.bat`.

**macOS / Linux:** open a terminal in this folder and run `bash run_chippy.sh`.

The first run creates a `.venv` folder and installs the packages, which takes a few minutes. Then two windows open:

| App | Address |
| --- | --- |
| CHIPPY (read-only) | http://localhost:8501 |
| CHIPPY_ADMIN | http://localhost:8502 |

Open the addresses in your browser if they don't open by themselves.

## Manual start

From this folder:

```
python -m venv .venv
.venv\Scripts\activate            (Windows)   or   source .venv/bin/activate   (macOS / Linux)
pip install -r requirements-demo.txt
streamlit run streamlit/demo_chippy.py --server.port 8501
streamlit run streamlit/demo_chippy_admin.py --server.port 8502      (in a second terminal)
```

## What works in the demo

- Every page, chart, filter, mascot animation, the retractable sidebar and the floating Ask Chippy panel.
- **Insight Studio** (Shift Detail, last tab): all five role lenses and every model run on a built-in synthetic
  panel. Its numbers are invented and only show what the models do.
- **Ask Chippy** agent cards and Auto routing work; Auto shows which agent a starter would go to.
- A refresh or a link straight to a page (for example `/Shift_detail?view=studio`) opens inside the app.
- **Watchlist** and **Case Files** keep what you add only while the browser tab stays open (as in Snowflake:
  nothing is saved). The sample data has two weeks, so Market Time Machine and "Since last week" have a
  week to compare.
- **Future Trends** shows TCN as unavailable unless PyTorch is installed; the other three models run.
- **Ask Chippy** needs the Snowflake agent, so it is switched off locally: the panel says live AI is
  unavailable and sends nothing. No sample answers are shown.
- A small "Local preview · sample data" label at the top of every page marks the preview mode. The sample
  data lives in `demo/` and `python/tests/`, separate from the app; nothing here is production data.
- **Load next week**, **Rerun this week**, **Reset to week** and **Save** (Settings) don't change anything. They only
  call the sample-data stand-ins.

## Tests (optional)

```
pip install pytest
pytest -q python/tests
```

The tests in `tests/local` need two more packages (`pip install duckdb sqlglot`).

## Running against Snowflake

That needs a Snowflake account with the Share Radar objects deployed. See `README.md` and `docs/`. Deploying uses the
Snowflake CLI: `snow streamlit deploy` from the `streamlit/` folder. Each person sets up their own connection.
Credentials are never stored in this project.
