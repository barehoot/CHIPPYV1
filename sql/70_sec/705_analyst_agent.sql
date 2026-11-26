-- Lets analysts and both Streamlit apps (through SR_ANALYST, granted in 704) call the Data analyst agent (50_sem/506).
USE ROLE SR_DEV;
GRANT USAGE ON AGENT SR_DB.SEM.RADAR_ANALYST_AGENT TO ROLE SR_ANALYST;
