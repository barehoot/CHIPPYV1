-- Lets analysts and both Streamlit apps (through SR_ANALYST, granted in 704) call the geo agent (50_sem/507).
USE ROLE SR_DEV;
GRANT USAGE ON AGENT SR_DB.SEM.GEO_MARKET_AGENT TO ROLE SR_ANALYST;
