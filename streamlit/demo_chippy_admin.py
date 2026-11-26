"""Local demo of CHIPPY_ADMIN (admin app: replay controls and Settings) with sample data. No Snowflake needed.
Run from the project folder:  streamlit run streamlit/demo_chippy_admin.py --server.port 8502"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "demo"))
import demo_data  # noqa: E402

demo_data.install()
demo_data.badge()
runpy.run_path(str(HERE / "admin_app.py"), run_name="__main__")
