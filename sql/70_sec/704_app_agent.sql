-- Local addition (not in the L12 design): lets the two Streamlit apps call the agent from the Chippy chat page.
-- The app owners get exactly the analyst's access (CORTEX_USER, agent, tools, SEM views), and the row access
-- policy on SEM applies SR_ANALYST's entitlements to their answers. Remove this file to take chat out again.
USE ROLE SECURITYADMIN;
GRANT ROLE SR_ANALYST TO ROLE SR_UI;
GRANT ROLE SR_ANALYST TO ROLE SR_APP;

USE ROLE SR_DEV;
GRANT USAGE ON AGENT SR_DB.SEM.SHARE_RADAR_AGENT TO ROLE SR_ANALYST;
