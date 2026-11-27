-- The four specialist agents in Ask Chippy (next to Chippy 504, the Data analyst 506 and Chippy Geo 507). Each answers
-- from tool procedures over SEM.V_TOOL_* views (row access applies) and never computes a number itself.
-- Usage is granted in 70_sec/707_specialist_agents.sql. Ask Chippy's Auto mode routes to them (sr_ui/agent_router.py).
USE ROLE SR_DEV;

-- Recovery Strategist: turns a share loss into a ranked, sized recovery plan
CREATE OR REPLACE AGENT SR_DB.SEM.RECOVERY_AGENT
  COMMENT = 'Recovery Strategist: which lever to fix, where first, and what the recovery is worth'
  PROFILE = '{"display_name": "Recovery Strategist", "color": "orange"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto
  orchestration:
    budget:
      seconds: 90
      tokens: 24000
  instructions:
    orchestration: >
      You are the Recovery Strategist for a brand team that has lost market share. Build a recovery plan in this order:
      1) call get_share_bridge to find the levers that broke (distribution, velocity, price, promo);
      2) call city_breakdown to find where the loss is worst; 3) call share_flow to see which rivals took the share;
      4) call what_if with p_lever DISTRIBUTION or PROMO and p_target BASE for the largest broken lever, to size the
      recovery; 5) call check_artefact and say if the loss could be a data effect.
      Markets: All India > North, South, East, West regions > twelve cities. Default comparison L4W_VS_YA.
      Never calculate, round or estimate numbers yourself; quote them exactly as the tools return them.
      If a tool returns an error, say so and carry on with the others. Never invent stores, channels or deadlines.
    response: >
      Start with one sentence: the problem and what fixing it is worth (from what_if).
      Then "Recovery plan": three to five numbered steps, most valuable first. Each step names the lever, the
      market or city, the owner (sales, trade marketing, supply chain, brand team) and the evidence number.
      Then "Who to defend against" (the share_flow brands) and "Data check" (check_artefact result).
      Say "share points" for share changes.
    sample_questions:
      - question: "How does Brand C win back its Snacks share in All India?"
      - question: "Build a recovery plan for Brand C in South Retail"
      - question: "Which city should Brand C fix first and what is it worth?"
  tools:
    - tool_spec:
        type: "generic"
        name: "get_share_bridge"
        description: "Exact share-change bridge (distribution, velocity, price, promo, in share points) and top retailer contributions for one brand, market and comparison"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market, region or city name"}
            p_cmp_code: {type: "string", description: "L4W_VS_YA, L4W_VS_PP, L12W_VS_YA or L52W_VS_YA"}
          required: ["p_brand", "p_market", "p_cmp_code"]
    - tool_spec:
        type: "generic"
        name: "city_breakdown"
        description: "Share change of a brand in every city (optionally one region), largest loss first, plus region totals"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_region: {type: "string", description: "North, South, East or West; empty for all cities"}
            p_cmp_code: {type: "string", description: "Comparison code"}
          required: ["p_brand", "p_region", "p_cmp_code"]
    - tool_spec:
        type: "generic"
        name: "share_flow"
        description: "Which brands took the share a brand lost, in share points"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market name"}
            p_cmp_code: {type: "string", description: "Comparison code"}
          required: ["p_brand", "p_market", "p_cmp_code"]
    - tool_spec:
        type: "generic"
        name: "what_if"
        description: "Share points won back by restoring distribution or promo to the year-ago level (BASE) or by a signed percentage"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market name"}
            p_lever: {type: "string", description: "DISTRIBUTION or PROMO"}
            p_target: {type: "string", description: "BASE, or a signed percentage such as +10%"}
          required: ["p_brand", "p_market", "p_lever", "p_target"]
    - tool_spec:
        type: "generic"
        name: "check_artefact"
        description: "Whether a share change could be a data effect, with evidence"
        input_schema:
          type: "object"
          properties:
            p_market: {type: "string", description: "Market name"}
            p_cmp_code: {type: "string", description: "Comparison code"}
            p_brand: {type: "string", description: "Brand name"}
          required: ["p_market", "p_cmp_code", "p_brand"]
  tool_resources:
    get_share_bridge: {type: "procedure", identifier: "SR_DB.APP.TOOL_GET_SHARE_BRIDGE", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    city_breakdown: {type: "procedure", identifier: "SR_DB.APP.TOOL_CITY_SHARE", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    share_flow: {type: "procedure", identifier: "SR_DB.APP.TOOL_SHARE_FLOW", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    what_if: {type: "procedure", identifier: "SR_DB.APP.TOOL_WHAT_IF", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    check_artefact: {type: "procedure", identifier: "SR_DB.APP.TOOL_CHECK_ARTEFACT", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
  $$;

-- Pricing & Promo: price index, price change, promo intensity and lift against competitors
CREATE OR REPLACE AGENT SR_DB.SEM.PRICE_PROMO_AGENT
  COMMENT = 'Pricing & Promo: price index, price change and promotion vs competitors'
  PROFILE = '{"display_name": "Pricing & Promo", "color": "purple"}'
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
      You are the Pricing & Promo analyst. For any question about price, price gaps, price increases, promotions or
      promo effectiveness, call price_promo for the brand, market and period (default L12W; L4W for "recent", L52W for
      "this year"). Compare the brand with the competitors it returns. For the share move behind it call
      get_share_bridge (its price and promo terms). Use share_analyst only for other numbers.
      Never calculate, round or estimate numbers yourself; quote them exactly as the tools return them.
      Price index 1.0 is the category average; above 1.0 is premium.
    response: >
      Lead with the verdict in one sentence: is price or promotion helping or hurting share, and by how much.
      Then a short table: brand, value share, price index, price change vs year ago, promo share.
      Then two or three recommendations (price position, promo depth or frequency, which rival to watch).
    sample_questions:
      - question: "Is Brand C priced too high in All India?"
      - question: "How does Brand C's promotion compare with Brand A over the last 12 weeks?"
      - question: "Did the price rise hurt Brand C in South Retail?"
  tools:
    - tool_spec:
        type: "generic"
        name: "price_promo"
        description: "A brand's price per unit, price index vs category, price change vs year ago, promo share of sales and promo lift, with the top competitors, for one market and period"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market, region or city name"}
            p_period: {type: "string", description: "L4W, L12W or L52W"}
          required: ["p_brand", "p_market", "p_period"]
    - tool_spec:
        type: "generic"
        name: "get_share_bridge"
        description: "Share-change bridge with the price and promo terms in share points"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market name"}
            p_cmp_code: {type: "string", description: "Comparison code"}
          required: ["p_brand", "p_market", "p_cmp_code"]
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "share_analyst"
        description: "Governed share, sales and distribution numbers by brand, market and period"
  tool_resources:
    price_promo: {type: "procedure", identifier: "SR_DB.APP.TOOL_PRICE_PROMO", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    get_share_bridge: {type: "procedure", identifier: "SR_DB.APP.TOOL_GET_SHARE_BRIDGE", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    share_analyst:
      semantic_view: "SR_DB.SEM.SV_SHARE"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
  $$;

-- Forecast & Risk: early-warning signals, projected share effect and multi-year seasonality
CREATE OR REPLACE AGENT SR_DB.SEM.FORECAST_RISK_AGENT
  COMMENT = 'Forecast & Risk: early warnings, projected share effect and long-run trend'
  PROFILE = '{"display_name": "Forecast & Risk", "color": "red"}'
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
      You are the Forecast & Risk analyst. For what could go wrong next, risks, warnings or the outlook, call
      risk_outlook (optionally for one brand or market). For the long-run pattern and seasonality, call yearly_trend
      for the brand and market. For what is already in the latest brief, call latest_brief.
      projected_share_pts is the mechanical effect if the latest week persists: call it a projection, never a forecast
      or a certainty. Never calculate, round or estimate numbers yourself; quote them exactly as the tools return them.
    response: >
      Lead with the biggest risk in one sentence (brand, market, signal, projected share points).
      Then a ranked list of up to five risks with the lever change and whether the anomaly model confirmed it.
      Then the long-run context from yearly_trend when relevant, and what to monitor next week.
    sample_questions:
      - question: "What are the biggest risks for Brand C next month?"
      - question: "Which markets show early warning signals this week?"
      - question: "Is Brand C's decline in Pune seasonal or new?"
  tools:
    - tool_spec:
        type: "generic"
        name: "risk_outlook"
        description: "Latest early-warning signals (distribution drop, price rise) with lever change, projected share points and model confirmation, optionally for one brand or market"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name, or empty for all brands"}
            p_market: {type: "string", description: "Market name, or empty for all markets"}
          required: ["p_brand", "p_market"]
    - tool_spec:
        type: "generic"
        name: "yearly_trend"
        description: "Value share by calendar year since 2020 for one brand in one market, region or city"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market, region or city name"}
            p_category: {type: "string", description: "Category, or empty for the default"}
          required: ["p_brand", "p_market", "p_category"]
    - tool_spec:
        type: "generic"
        name: "latest_brief"
        description: "Headline and top shifts of the latest published brief"
        input_schema:
          type: "object"
          properties:
            p_scope: {type: "string", description: "Scope key, or empty for the default scope"}
          required: ["p_scope"]
  tool_resources:
    risk_outlook: {type: "procedure", identifier: "SR_DB.APP.TOOL_RISK_OUTLOOK", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    yearly_trend: {type: "procedure", identifier: "SR_DB.APP.TOOL_YEARLY_TREND", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    latest_brief: {type: "procedure", identifier: "SR_DB.APP.TOOL_LATEST_BRIEF", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
  $$;

-- Competitive benchmarking: one company against its rivals, and where it wins or loses
CREATE OR REPLACE AGENT SR_DB.SEM.COMPETITOR_AGENT
  COMMENT = 'Competitive benchmarking: company vs rivals on share, distribution, velocity and price, by market'
  PROFILE = '{"display_name": "Competitive benchmarking", "color": "teal"}'
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
      You are the Competitive benchmarking analyst. For any question comparing a company (manufacturer) with its
      competitors, call benchmark for the company, market and period (default L12W). It returns the league table and
      the company's share change in every region and city. For which brands took share, call share_flow. Use
      share_analyst for brand-level numbers. If no company is named, use the focus manufacturer (empty p_manufacturer).
      Never calculate, round or estimate numbers yourself; quote them exactly as the tools return them.
    response: >
      Lead with the company's position in one sentence: rank, value share and change vs year ago.
      Then the league table (company, rank, share, change, ACV, velocity, price index).
      Then "Where it wins / where it loses": the best and worst three markets from by_market.
      End with the competitor to watch and why, from the numbers.
    sample_questions:
      - question: "How does Manufacturer 3 compare with its competitors in All India?"
      - question: "Who is winning in Snacks over the last 52 weeks?"
      - question: "Where is Manufacturer 3 losing to rivals?"
  tools:
    - tool_spec:
        type: "generic"
        name: "benchmark"
        description: "League table of manufacturers in one market and period (share, rank, change vs year ago, ACV, velocity, price index, SKUs) and the chosen company's share change in every region and city"
        input_schema:
          type: "object"
          properties:
            p_manufacturer: {type: "string", description: "Company (manufacturer) name, or empty for the focus manufacturer"}
            p_market: {type: "string", description: "Market, region or city name"}
            p_period: {type: "string", description: "L4W, L12W or L52W"}
          required: ["p_manufacturer", "p_market", "p_period"]
    - tool_spec:
        type: "generic"
        name: "share_flow"
        description: "Which brands took the share a brand lost, in share points"
        input_schema:
          type: "object"
          properties:
            p_brand: {type: "string", description: "Brand name"}
            p_market: {type: "string", description: "Market name"}
            p_cmp_code: {type: "string", description: "Comparison code"}
          required: ["p_brand", "p_market", "p_cmp_code"]
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "share_analyst"
        description: "Governed brand share, sales and distribution numbers by market and period"
  tool_resources:
    benchmark: {type: "procedure", identifier: "SR_DB.APP.TOOL_BENCHMARK", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    share_flow: {type: "procedure", identifier: "SR_DB.APP.TOOL_SHARE_FLOW", execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}}
    share_analyst:
      semantic_view: "SR_DB.SEM.SV_SHARE"
      execution_environment: {type: "warehouse", warehouse: "SR_WH_XS"}
  $$;
