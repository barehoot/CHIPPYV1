@echo off
rem CHIPPY local demo (Windows). First run creates a virtual environment and installs the packages.
rem   run_chippy.bat        sample data, no Snowflake
rem   run_chippy.bat live   live Snowflake data and Cortex agents, through a connection in %USERPROFILE%\.snowflake\config.toml
rem                         (set CHIPPY_CONNECTION to pick one, CHIPPY_ROLE for the role; the default connection otherwise)
cd /d "%~dp0"
if not exist .venv (
  echo Creating the Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements-demo.txt
)
if /i "%~1"=="live" (
  set CHIPPY_MODE=live
  echo Live mode: reading Snowflake through connection "%CHIPPY_CONNECTION%" ^(blank = default connection^)
) else (
  set CHIPPY_MODE=
)
echo Starting CHIPPY on http://localhost:8501 and CHIPPY_ADMIN on http://localhost:8502
start "CHIPPY" .venv\Scripts\python -m streamlit run streamlit\demo_chippy.py --server.port 8501
start "CHIPPY_ADMIN" .venv\Scripts\python -m streamlit run streamlit\demo_chippy_admin.py --server.port 8502
