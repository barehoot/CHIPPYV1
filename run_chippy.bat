@echo off
rem CHIPPY local demo (Windows). First run creates a virtual environment and installs the packages.
cd /d "%~dp0"
if not exist .venv (
  echo Creating the Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements-demo.txt
)
echo Starting CHIPPY on http://localhost:8501 and CHIPPY_ADMIN on http://localhost:8502
start "CHIPPY" .venv\Scripts\python -m streamlit run streamlit\demo_chippy.py --server.port 8501
start "CHIPPY_ADMIN" .venv\Scripts\python -m streamlit run streamlit\demo_chippy_admin.py --server.port 8502
