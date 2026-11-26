-- Data analyst agent: open business questions over the governed share semantic view (sales, share, distribution,
-- rankings, comparisons), returned as answers and tables. Sits next to the Ask-Why agent (504); the app's agent
-- picker (pages/5_Ask_Chippy.py) lets the user choose. Usage is granted in 70_sec/705.
USE ROLE SR_DEV;
CREATE OR REPLACE AGENT SR_DB.SEM.RADAR_ANALYST_AGENT
  COMMENT = 'Data analyst agent for open questions over SV_SHARE'
  PROFILE = '{"display_name": "Data analyst", "color": "gray"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto
  orchestration:
    budget:
      seconds: 60
      tokens: 16000
  instructions:
    orchestration: >
      You are the Radar data analyst for NIQ client-service analysts. Answer business questions about sales, value
      share, distribution, prices and trends by brand, manufacturer, market, retailer and period.
      Use data_analyst for every number. Use method_search only for definitions and method.
      Prefer one query that answers the whole question; show rankings and comparisons as a table.
      Never calculate, round or estimate numbers yourself; quote them exactly as the tool returns them.
      If the question needs a forecast or causal explanation, say this agent reports measured data only and suggest
      the Forecast tab on the Shift detail page or the Chippy agent for why share moved.
      If the tool returns nothing, say so and suggest a nearby supported question.
    response: >
      Lead with the answer in one sentence, naming the period and market.
      Then a short table or at most four bullets. Say "share points" for share changes, never "percent".
    sample_questions:
      - question: "Which brands have the highest value share in Total Market over the last 4 weeks?"
      - question: "Compare value sales by retailer for the last 12 weeks vs year ago"
      - question: "Which manufacturers gained the most share in the last 52 weeks?"
  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "data_analyst"
        description: "Governed share, sales, distribution, price and share-change numbers by brand, manufacturer, market and period"
    - tool_spec:
        type: "cortex_search"
        name: "method_search"
        description: "Definitions and method: ACV, TDP, velocity, the share bridge, artefact rules, period codes"
  tool_resources:
    data_analyst:
      semantic_view: "SR_DB.SEM.SV_SHARE"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
    method_search:
      search_service: "SR_DB.SEM.CSS_METHOD"
      max_results: 4
  $$;
