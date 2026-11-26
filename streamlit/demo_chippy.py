"""Local demo of CHIPPY (the read-only app) with sample data. No Snowflake needed.
Run from the project folder:  streamlit run streamlit/demo_chippy.py"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "demo"))
import demo_data  # noqa: E402

demo_data.install()
demo_data.badge()
runpy.run_path(str(HERE / "streamlit_app.py"), run_name="__main__")
