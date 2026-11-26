"""Settings (admin app only): thresholds and recipients (L11). Scope and replay keys are read-only here."""
from __future__ import annotations

import json

import streamlit as st

from sr_ui import data, nav
nav.entry_guard("pages/4_Settings.py")   # a refresh or direct link still opens inside the app

nav.radar_header("Settings", "Thresholds and options for the weekly run")     # loads radar.css (floating assistant)
if not nav.is_admin():
    st.error("Settings are available in the admin app only.", icon=":material/lock:")
    nav.stop()

st.info("Saving any setting makes the dynamic tables refresh once, because they read OPS.SETTINGS. "
        "Scope and the as-of week are changed by SR-004 and the replay controls, not here.", icon=":material/info:")


def table() -> None:
    with nav.card("settings_table"):
        nav.section("Current settings", "Every key in OPS.SETTINGS. Ticked keys can be changed in the form.")
        s = data.settings()
        s = s.assign(EDITABLE=[k in data.EDITABLE for k in s.SETTING_KEY])
        st.dataframe(s, hide_index=True, row_height=38, width="stretch", column_config={
            "SETTING_KEY": "Setting", "VALUE_JSON": "Value", "DESCRIPTION": "Description", "UPDATED_AT": "Updated",
            "EDITABLE": st.column_config.CheckboxColumn("Editable")})


def form() -> None:
    with nav.card("settings_form"):
        _form()


def _form() -> None:
    nav.section("Change a setting", "Values are checked against their allowed range before they are saved.")
    key = st.selectbox("Setting", sorted(data.EDITABLE))
    kind, lo, hi = data.EDITABLE[key]
    current = data.cfg(key)
    if kind in (int, float):
        st.caption(f"Allowed: {lo if lo is not None else 'any'} to {hi if hi is not None else 'any'}")
    with st.form("edit_setting", border=False):
        if kind is bool:
            value = st.toggle(key, value=bool(current))
        elif kind is list:
            text = st.text_area("Email addresses, one per line", value="\n".join(current or []))
            value = [line.strip() for line in text.splitlines() if line.strip()]
        elif kind is int:
            value = int(st.number_input(key, value=int(current or 0), min_value=int(lo) if lo is not None else None,
                                        max_value=int(hi) if hi is not None else None, step=1))
        else:
            value = float(st.number_input(key, value=float(current or 0), min_value=float(lo) if lo is not None else None,
                                          max_value=float(hi) if hi is not None else None, format="%.4f"))
        if st.form_submit_button("Save", type="primary", icon=":material/save:"):
            try:
                data.save_setting(key, value)
                st.success(f"{key} = {json.dumps(value)}")
            except ValueError as e:
                st.error(str(e))


nav.guarded("Settings table", table)
left, _ = st.columns([2, 3])
with left:
    nav.guarded("Settings form", form)
