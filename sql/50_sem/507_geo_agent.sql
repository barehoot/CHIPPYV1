-- Geo agent ("Chippy Geo"): where share moved and how it developed over the years. City and region breakdowns
-- with coordinates, multi-year trends, and governed numbers from the share semantic view. Sits next to the Ask-Why
-- agent (504) and the Data analyst agent (506); Ask Chippy's Auto mode routes city, region, map and multi-year
-- questions here (streamlit/sr_ui/agent_router.py). Usage is granted in 70_sec/706.
USE ROLE SR_DEV;
CREATE OR REPLACE AGENT SR_DB.SEM.GEO_MARKET_AGENT
  COMMENT = 'Geo agent: city and region share breakdowns and multi-year trends'
  PROFILE = '{"display_name": "Chippy Geo", "color": "green"}'
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
      You are Chippy Geo. You explain where market share moved across India and how it developed over the years.
      Markets form a hierarchy: All India (total) > four regions (North, South, East, West) > twelve cities
      (North: Delhi, Lucknow, Jaipur; South: Bengaluru, Chennai, Hyderabad; East: Kolkata, Bhubaneswar, Patna;
      West: Mumbai, Pune, Ahmedabad).
      For which cities or regions drove a change, call city_breakdown. For trends across years, call yearly_trend.
      For any other number (sales, distribution, rankings within one level) use share_analyst.
      For definitions or method use method_search.
      Never calculate, round, add up or average numbers yourself; quote them exactly as tools return them.
      City shares are within each city and never add up to a region share; say so if asked to add them.
      If a tool returns an error or nothing, say so. If it returns AMBIGUOUS or NOT_FOUND, list the candidates.
      For why share moved (drivers, data effects), say the Chippy agent answers that and suggest the question.
    response: >
      Lead with the answer in one sentence, naming the comparison or years and the market level.
      Then a short table of cities or years (at most twelve rows), or at most four bullets.
      Show shares with one decimal and share changes with two, in "share points", never "percent".
    sample_questions:
      - question: "Which cities drove Brand C's Snacks share loss in the last 4 weeks vs prior period?"
      - question: "How has Brand C's share in Pune developed since 2020?"
      - question: "Which South cities lost the most share in the last 12 weeks vs year ago?"
  tools:
    - tool_spec:
        type: "generic"
        name: "city_breakdown"
        description: "Share change of a brand in every city (optionally one region), ordered from largest loss to largest gain, with state and coordinates, plus the region totals"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_region: {type: "string", description: "North, South, East or West; empty for all cities"}
            p_cmp_code: {type: "string", description: "L4W_VS_YA, L4W_VS_PP, L12W_VS_YA or L52W_VS_YA; default L4W_VS_YA"}
          required: ["p_brand", "p_region", "p_cmp_code"]
    - tool_spec:
        type: "generic"
        name: "yearly_trend"
        description: "Value share by calendar year (about six years) for one brand in one market, city or region"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "All India, a region (for example South Retail) or a city"}
            p_category: {type: "string", description: "Category, or empty for the default category"}
          required: ["p_brand", "p_market", "p_category"]
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "share_analyst"
        description: "Governed share, sales, distribution and share-change numbers by brand, market, region, city and period"
    - tool_spec:
        type: "cortex_search"
        name: "method_search"
        description: "Definitions and method: ACV, TDP, velocity, the share bridge, artefact rules, period codes"
  tool_resources:
    city_breakdown:
      type: "procedure"
      identifier: "SR_DB.APP.TOOL_CITY_SHARE"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
    yearly_trend:
      type: "procedure"
      identifier: "SR_DB.APP.TOOL_YEARLY_TREND"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
    share_analyst:
      semantic_view: "SR_DB.SEM.SV_SHARE"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
    method_search:
      search_service: "SR_DB.SEM.CSS_METHOD"
      max_results: 4
  $$;
