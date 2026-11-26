"""Signal Journey diagram (moved from Radar to Data & Trust, unchanged): candidates checked -> passed the gates ->
four mutually exclusive outcomes (data.signal_journey), with early warnings as a separate stream."""
from __future__ import annotations

import logging
from base64 import b64encode
from html import escape

import streamlit as st

from sr_ui import data, nav

CSS = """<style>
.st-key-sr_card_journey { container-type:inline-size; }
.st-key-sr_card_journey .sr-radar-section { display:grid; gap:3px; }
.st-key-sr_card_journey .sr-radar-section h3 { display:flex; align-items:center; gap:8px; margin:0; padding:0; font-size:18px !important; }
.st-key-sr_card_journey .sr-radar-section h3 .sr-ico { color:#1e5556; font-size:19px; }
.st-key-sr_card_journey .sr-radar-section p { margin:0; font-size:12.5px; color:#647c80; }
.sr-radar-flow {
 display:grid; grid-template-columns: minmax(72px,1fr) auto minmax(75px,1fr) minmax(25px,.65fr) minmax(112px,2.75fr);
 align-items:center; gap:7px; margin:7px 0;
}
.sr-flow-candidates, .sr-flow-passed {
 display:grid; place-items:center; padding:8px; background:#e9ecee; border-radius:14px;
 font-size:12px; line-height:1.15; text-align:center;
}
.sr-flow-passed { background:#d2f3e4; color:#10564a; }
.sr-flow-candidates b, .sr-flow-passed b { font:800 23px/1.05 Manrope,sans-serif; }
.sr-flow-next { font-size:22px; font-weight:700; }
.sr-radar-flow > img { display:block; width:100%; height:112px; }
.sr-radar-flow-outcomes { display:grid; grid-template-rows:repeat(4, 25px); gap:4px; }
.sr-radar-flow-outcomes > div {
 display:grid; grid-template-columns:auto 2.1ch 1fr; align-items:center; gap:7px; padding:0 7px;
 border:1px solid #cfe0e6; border-radius:14px; background:#fbfdfe; font-size:12px;
}
.sr-radar-flow-outcomes .sr-ico { color:#087e72; font-size:17px; }
.sr-radar-flow-outcomes > div:nth-child(3) .sr-ico { color:#a16516; }
.sr-flow-warnings {
 display:flex; align-items:center; gap:8px; padding:5px 10px; background:#fbefdb; border-radius:10px; font-size:12px; font-weight:700;
}
.sr-flow-warnings b { margin-left:auto; font-size:15px; }.sr-flow-warnings small { font-size:11px; font-weight:500; }
.sr-flow-warnings .sr-ico { color:#a16516; }
@container (max-width: 285px) {
 .sr-radar-flow { grid-template-columns:minmax(65px,1fr) 12px minmax(65px,1fr); gap:4px; }
 .sr-radar-flow > img { grid-column:2; transform:rotate(90deg); height:20px; width:25px; max-width:none; }
 .sr-radar-flow-outcomes { grid-column:1/-1; }
}
</style>"""


def signal_journey(run: data.Run) -> None:
    try:
        counts = data.signal_journey(run.run_id)
        warning_count = len(data.watchlist(run.run_id))
    except Exception:
        logging.getLogger(__name__).exception("Signal journey data unavailable")
        return

    st.html(CSS)
    with nav.card("journey"):
        st.html('<div class="sr-radar-section"><h3><span class="sr-ico" aria-hidden="true">hub</span>'
                f'{escape("Signal Journey")}</h3><p>{escape("From candidate detection to weekly intelligence")}</p></div>')
        outcomes = (
            ("In Brief", counts.get("N_SELECTED", 0), "check_circle"),
            ("Data Checks", counts.get("N_HELD", 0), "database"),
            ("Repeat Signals", counts.get("N_REPEAT", 0), "sync"),
            ("Other Exclusions", counts.get("N_OTHER_CMP", 0) + counts.get("N_BEYOND_TOP_N", 0), "layers"),
        )
        paths = "".join(f'<path d="M 2 80 C 27 80 29 {y} 57 {y} M 51 {y - 4} L 57 {y} L 51 {y + 4}"/>'
                        for y in (20, 60, 100, 140))
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 160" preserveAspectRatio="none">'
               f'<g fill="none" stroke="#008679" stroke-width="2">{paths}</g></svg>')
        arrows = b64encode(svg.encode("ascii")).decode("ascii")
        branches = "".join(f'<div><span class="sr-ico" aria-hidden="true">{icon}</span>'
                           f'<b>{value:,}</b><span>{label}</span></div>' for label, value, icon in outcomes)
        st.html('<div class="sr-radar-flow">'
                f'<div class="sr-flow-candidates"><b>{counts.get("N_DETECTED", 0):,}</b>Candidates Checked</div>'
                '<span class="sr-flow-next" aria-hidden="true">&#8594;</span>'
                f'<div class="sr-flow-passed"><b>{counts.get("N_PASSED", 0):,}</b>Passed Validation Gates</div>'
                f'<img src="data:image/svg+xml;base64,{arrows}" alt="">'
                f'<div class="sr-radar-flow-outcomes">{branches}</div></div>')
        with st.container(key="sr_radar_journey_footer", horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<div class="sr-flow-warnings"><span class="sr-ico" aria-hidden="true">bolt</span>'
                    f'<span>Early Warnings <small>(separate stream)</small></span><b>{warning_count:,}</b></div>')
        if sum(value for _, value, _ in outcomes) != counts.get("N_PASSED", 0):
            st.caption("Stored outcome counts do not reconcile to the number passing the gates.")
