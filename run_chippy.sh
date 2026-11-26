#!/usr/bin/env bash
# CHIPPY local demo (macOS / Linux). First run creates a virtual environment and installs the packages.
#   ./run_chippy.sh        sample data, no Snowflake
#   ./run_chippy.sh live   live Snowflake data and Cortex agents, through a connection in ~/.snowflake/config.toml
#                          (set CHIPPY_CONNECTION to pick one, CHIPPY_ROLE for the role; the default connection otherwise)
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creating the Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-demo.txt
fi
if [ "${1:-}" = "live" ]; then
  export CHIPPY_MODE=live
  echo "Live mode: reading Snowflake through connection '${CHIPPY_CONNECTION:-<default>}'"
else
  unset CHIPPY_MODE
fi
echo "Starting CHIPPY on http://localhost:8501 and CHIPPY_ADMIN on http://localhost:8503 (Ctrl+C stops both)"
.venv/bin/python -m streamlit run streamlit/demo_chippy.py --server.port 8501 &
.venv/bin/python -m streamlit run streamlit/demo_chippy_admin.py --server.port 8503
