"""SHARE_RADAR_ADMIN: the same app plus the replay controls and the Settings page (owner SR_APP, team only)."""
import streamlit as st

from sr_ui import nav

st.set_page_config(page_title="Chippy admin", page_icon="📡", layout="wide", initial_sidebar_state="expanded")
nav.run(admin=True)
