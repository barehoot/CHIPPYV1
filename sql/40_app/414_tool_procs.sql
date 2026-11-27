-- SR-042 · L10 tool procedures for the Cortex Agent, and the L13 name resolver.
-- Each tool takes names as people type them, resolves them with APP.SP_RESOLVE, reads ONLY SEM.V_TOOL_* views
-- (so the row access policy always applies and callers need no table grants), and returns its L10 payload or an
-- L13 error object as a JSON string: NOT_FOUND, AMBIGUOUS, NO_DATA, BAD_INPUT or TOOL_FAILED. Never a partial number.
USE ROLE SR_DEV;

-- Resolver: candidates are the distinct brands (or market names and IDs) in SEM.V_TOOL_BRIDGE for the comparison.
-- Score 0 = exact case-insensitive match on name or ID; 1 = the name contains the input (3+ characters);
-- otherwise EDITDISTANCE. Best score <= 2 and unique -> OK; tied -> AMBIGUOUS; else NOT_FOUND with the 3 closest.
CREATE OR REPLACE PROCEDURE SR_DB.APP.SP_RESOLVE(P_KIND VARCHAR, P_TEXT VARCHAR, P_CMP_CODE VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  kind    VARCHAR DEFAULT UPPER(TRIM(COALESCE(P_KIND, '')));
  txt     VARCHAR DEFAULT UPPER(TRIM(COALESCE(P_TEXT, '')));
  cmp     VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_CMP_CODE)), ''), 'L4W_VS_YA');
  best    NUMBER;
  n_best  NUMBER;
  val     VARCHAR;
  nm      VARCHAR;
  tied    ARRAY;
  closest ARRAY;
BEGIN
  IF (kind NOT IN ('BRAND', 'MARKET')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'BAD_INPUT', 'detail', 'Kind must be BRAND or MARKET');
  END IF;
  IF (txt = '') THEN
    RETURN OBJECT_CONSTRUCT('status', 'NOT_FOUND', 'what', LOWER(kind), 'input', COALESCE(P_TEXT, ''), 'candidates', ARRAY_CONSTRUCT());
  END IF;
  -- c: candidate values and names; s: their scores; r: ranks
  WITH c AS (
    SELECT DISTINCT IFF(:kind = 'BRAND', BRAND, MARKET_ID) AS VAL, IFF(:kind = 'BRAND', BRAND, MARKET_NAME) AS NAME
    FROM SR_DB.SEM.V_TOOL_BRIDGE WHERE CMP_CODE = :cmp
  ),
  s AS (
    SELECT VAL, NAME,
           CASE WHEN UPPER(NAME) = :txt OR UPPER(VAL) = :txt THEN 0
                WHEN LENGTH(:txt) >= 3 AND CONTAINS(UPPER(NAME), :txt) THEN 1
                ELSE EDITDISTANCE(UPPER(NAME), :txt) END AS SCORE
    FROM c
  ),
  r AS (
    SELECT VAL, NAME, SCORE, MIN(SCORE) OVER () AS BEST, ROW_NUMBER() OVER (ORDER BY SCORE, NAME) AS RN FROM s
  )
  SELECT MIN(BEST), COUNT_IF(SCORE = BEST), MAX(IFF(SCORE = BEST, VAL, NULL)), MAX(IFF(SCORE = BEST, NAME, NULL)),
         ARRAY_AGG(IFF(SCORE = BEST AND RN <= 10, NAME, NULL)) WITHIN GROUP (ORDER BY NAME),
         ARRAY_AGG(IFF(RN <= 3, NAME, NULL)) WITHIN GROUP (ORDER BY RN)
    INTO :best, :n_best, :val, :nm, :tied, :closest
    FROM r;
  IF (best IS NOT NULL AND best <= 2 AND n_best = 1) THEN
    RETURN OBJECT_CONSTRUCT('status', 'OK', 'value', val, 'name', nm);
  ELSEIF (best IS NOT NULL AND best <= 2) THEN
    RETURN OBJECT_CONSTRUCT('status', 'AMBIGUOUS', 'what', LOWER(kind), 'input', P_TEXT, 'candidates', tied);
  END IF;
  RETURN OBJECT_CONSTRUCT('status', 'NOT_FOUND', 'what', LOWER(kind), 'input', P_TEXT,
                          'candidates', COALESCE(closest, ARRAY_CONSTRUCT()));
END;
$$;

-- get_share_bridge: why did share move? Bridge terms in points, top retailers, artefact label.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_GET_SHARE_BRIDGE(P_BRAND VARCHAR, P_MARKET VARCHAR, P_CMP_CODE VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  cmp      VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_CMP_CODE)), ''), 'L4W_VS_YA');
  b        VARIANT;
  m        VARIANT;
  res      VARIANT;
  retail   ARRAY;
  in_scope BOOLEAN;
  n_high   NUMBER;
  n_med    NUMBER;
BEGIN
  IF (cmp NOT IN ('L4W_VS_YA', 'L4W_VS_PP', 'L12W_VS_YA', 'L52W_VS_YA')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Unknown comparison ' || cmp ||
                                    '; use L4W_VS_YA, L4W_VS_PP, L12W_VS_YA or L52W_VS_YA'));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, :cmp) INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, :cmp) INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;

  SELECT OBJECT_CONSTRUCT('brand', BRAND, 'market', MARKET_NAME, 'cmp_code', CMP_CODE, 'as_of_week', AS_OF_WEEK::VARCHAR,
                          'share_now_pct', 100 * SH1, 'share_before_pct', 100 * SH0, 'change_pts', 100 * D_SHARE,
                          'mode', MODE, 'status', STATUS,
                          'terms_pts', OBJECT_CONSTRUCT('distribution', DIST_PTS, 'velocity', VELOCITY_PTS,
                                                        'price', PRICE_PTS, 'promo', PROMO_PTS),
                          'source', 'SEM.V_TOOL_BRIDGE'),
         IN_SCOPE
    INTO :res, :in_scope
    FROM SR_DB.SEM.V_TOOL_BRIDGE
   WHERE BRAND = :bv AND MARKET_ID = :mv AND CMP_CODE = :cmp AND D_SHARE IS NOT NULL
   ORDER BY ABS(D_SHARE) DESC
   LIMIT 1;
  IF (res IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No share change for this brand, market and comparison; try another comparison'));
  END IF;

  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('retailer', CONTRIBUTOR, 'total_pts', TOTAL_PTS, 'performance_pts', PERF_PTS,
                                    'mix_pts', MIX_PTS)) WITHIN GROUP (ORDER BY RANK_NO)
    INTO :retail
    FROM SR_DB.SEM.V_TOOL_WHERE
   WHERE BRAND = :bv AND MARKET_ID = :mv AND CMP_CODE = :cmp AND METHOD = 'EXACT_RETAILER' AND RANK_NO <= 3;
  res := OBJECT_INSERT(res, 'top_retailers', COALESCE(retail, ARRAY_CONSTRUCT()));
  IF (retail IS NULL OR ARRAY_SIZE(retail) = 0) THEN
    res := OBJECT_INSERT(res, 'note', 'Retailer contributions are computed only for shifts in the latest brief');
  END IF;

  IF (in_scope) THEN
    SELECT COUNT_IF(SEVERITY = 'HIGH'), COUNT_IF(SEVERITY = 'MEDIUM') INTO :n_high, :n_med
      FROM SR_DB.SEM.V_TOOL_ARTEFACT
     WHERE MARKET_ID = :mv AND CMP_CODE = :cmp AND (BRAND IS NULL OR BRAND = :bv);
    res := OBJECT_INSERT(res, 'artefact_label',
                         IFF(n_high > 0, 'POSSIBLE_DATA_EFFECT', IFF(n_med > 0, 'MIXED', 'MARKET_MOVE')));
  ELSE
    res := OBJECT_INSERT(res, 'artefact_label', 'NOT_CHECKED');
  END IF;
  RETURN TO_JSON(res);
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- check_artefact: is the change real or a data effect? Label and rule hits with evidence.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_CHECK_ARTEFACT(P_MARKET VARCHAR, P_CMP_CODE VARCHAR, P_BRAND VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  cmp      VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_CMP_CODE)), ''), 'L4W_VS_YA');
  b        VARIANT;
  m        VARIANT;
  bv       VARCHAR;
  rules    ARRAY;
  in_scope BOOLEAN;
  n_high   NUMBER;
  n_med    NUMBER;
BEGIN
  IF (cmp NOT IN ('L4W_VS_YA', 'L4W_VS_PP', 'L12W_VS_YA', 'L52W_VS_YA')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Unknown comparison ' || cmp));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, :cmp) INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  IF (TRIM(COALESCE(P_BRAND, '')) <> '') THEN
    CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, :cmp) INTO :b;
    IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
    bv := GET(b, 'value')::VARCHAR;
  END IF;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;

  SELECT BOOLOR_AGG(IN_SCOPE) INTO :in_scope FROM SR_DB.SEM.V_TOOL_BRIDGE WHERE MARKET_ID = :mv AND CMP_CODE = :cmp;
  IF (NOT COALESCE(in_scope, FALSE)) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('label', 'NOT_CHECKED', 'market', GET(m, 'name'), 'cmp_code', cmp,
                                    'note', 'The data checks run on the Chippy scope markets only'));
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('rule_id', RULE_ID, 'severity', SEVERITY, 'evidence', EVIDENCE))
           WITHIN GROUP (ORDER BY SEVERITY, RULE_ID),
         COUNT_IF(SEVERITY = 'HIGH'), COUNT_IF(SEVERITY = 'MEDIUM')
    INTO :rules, :n_high, :n_med
    FROM SR_DB.SEM.V_TOOL_ARTEFACT
   WHERE MARKET_ID = :mv AND CMP_CODE = :cmp AND (BRAND IS NULL OR BRAND = :bv);
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'label', IFF(n_high > 0, 'POSSIBLE_DATA_EFFECT', IFF(n_med > 0, 'MIXED', 'MARKET_MOVE')),
    'market', GET(m, 'name'), 'brand', bv, 'cmp_code', cmp,
    'rules', COALESCE(rules, ARRAY_CONSTRUCT()), 'source', 'SEM.V_TOOL_ARTEFACT (latest successful run)'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- share_flow: who took the share (or whose share was taken), proportional allocation.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_SHARE_FLOW(P_BRAND VARCHAR, P_MARKET VARCHAR, P_CMP_CODE VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  cmp   VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_CMP_CODE)), ''), 'L4W_VS_YA');
  b     VARIANT;
  m     VARIANT;
  d     FLOAT;
  flows ARRAY;
BEGIN
  IF (cmp NOT IN ('L4W_VS_YA', 'L4W_VS_PP', 'L12W_VS_YA', 'L52W_VS_YA')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Unknown comparison ' || cmp));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, :cmp) INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, :cmp) INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;

  SELECT SUM(D_SHARE) INTO :d FROM SR_DB.SEM.V_TOOL_BRIDGE WHERE BRAND = :bv AND MARKET_ID = :mv AND CMP_CODE = :cmp;
  IF (d IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No share change for this brand, market and comparison'));
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('brand', IFF(:d < 0, TO_BRAND, FROM_BRAND), 'pts', FLOW_PTS))
           WITHIN GROUP (ORDER BY FLOW_PTS DESC)
    INTO :flows
    FROM SR_DB.SEM.V_TOOL_FLOW
   WHERE MARKET_ID = :mv AND CMP_CODE = :cmp AND IFF(:d < 0, FROM_BRAND, TO_BRAND) = :bv;
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'brand', bv, 'market', GET(m, 'name'), 'cmp_code', cmp, 'change_pts', 100 * d,
    'direction', IFF(d < 0, 'LOSS', IFF(d > 0, 'GAIN', 'FLAT')),
    'flows', COALESCE(flows, ARRAY_CONSTRUCT()),
    'method_note', 'Proportional allocation: the points a losing brand gave up are shared among the gaining brands in '
                   || 'proportion to their gains. An accounting split, not evidence of shoppers switching.'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- what_if: mechanical share effect of restoring or changing distribution or promo (L4W vs year ago), as SP_WHAT_IF.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_WHAT_IF(P_BRAND VARCHAR, P_MARKET VARCHAR, P_LEVER VARCHAR, P_TARGET VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  cmp    VARCHAR DEFAULT 'L4W_VS_YA';
  lever  VARCHAR DEFAULT UPPER(TRIM(COALESCE(P_LEVER, '')));
  target VARCHAR DEFAULT UPPER(REPLACE(TRIM(COALESCE(P_TARGET, '')), ' ', ''));
  pct    FLOAT;
  ratio  FLOAT;
  b      VARIANT;
  m      VARIANT;
  sh1    FLOAT;
  ds1    FLOAT;
  ds0    FLOAT;
  pri1   FLOAT;
  pri0   FLOAT;
  mode   VARCHAR;
BEGIN
  IF (lever NOT IN ('DISTRIBUTION', 'PROMO')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Lever must be DISTRIBUTION or PROMO'));
  END IF;
  IF (target <> 'BASE') THEN
    pct := TRY_TO_DOUBLE(REPLACE(REPLACE(target, '%', ''), '+', '')) / 100;
    IF (pct IS NULL) THEN
      RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Target must be BASE or a signed percentage such as +10%'));
    END IF;
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, :cmp) INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, :cmp) INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;

  SELECT SH1, DS1, DS0, PRI1, PRI0, MODE INTO :sh1, :ds1, :ds0, :pri1, :pri0, :mode
    FROM SR_DB.SEM.V_TOOL_BRIDGE
   WHERE BRAND = :bv AND MARKET_ID = :mv AND CMP_CODE = :cmp AND STATUS = 'OK'
   ORDER BY ABS(D_SHARE) DESC LIMIT 1;
  IF (sh1 IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No comparable share for this brand and market, last 4 weeks vs year ago'));
  END IF;
  IF (lever = 'DISTRIBUTION') THEN
    IF (ds1 IS NULL OR ds0 IS NULL OR ds1 = 0) THEN
      RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No distribution share for this brand (bridge mode ' || mode || ')'));
    END IF;
    ratio := IFF(target = 'BASE', ds0 / ds1, 1 + pct);
  ELSE
    IF (mode <> 'A' OR pri1 IS NULL OR pri0 IS NULL OR pri1 = 0) THEN
      RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'The promo lever needs bridge mode A; this is mode ' || mode));
    END IF;
    ratio := IFF(target = 'BASE', pri0 / pri1, 1 + pct);
  END IF;
  RETURN TO_JSON(OBJECT_CONSTRUCT('brand', bv, 'market', GET(m, 'name'), 'cmp_code', cmp, 'lever', lever, 'target', P_TARGET,
                                  'share_now_pts', 100 * sh1, 'share_if_pts', 100 * sh1 * ratio,
                                  'delta_pts', 100 * sh1 * (ratio - 1),
                                  'assumption', 'Other levers held constant; mechanical, not a forecast'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- latest_brief: what changed this week? Headline, top shifts and held-back shifts of the newest published brief.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_LATEST_BRIEF(P_SCOPE VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  scope  VARCHAR DEFAULT TRIM(COALESCE(P_SCOPE, ''));
  bid    VARCHAR;
  wk     VARCHAR;
  head   VARCHAR;
  shifts ARRAY;
  held   ARRAY;
BEGIN
  SELECT BRIEF_ID, AS_OF_WEEK::VARCHAR, HEADLINE INTO :bid, :wk, :head
    FROM SR_DB.SEM.V_TOOL_BRIEF
   WHERE :scope = '' OR SCOPE_KEY = :scope OR STARTSWITH(SCOPE_KEY, :scope)
   ORDER BY PUBLISHED_AT DESC LIMIT 1;
  IF (bid IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No published brief for this scope yet'));
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
           'brand', s.value:brand::VARCHAR, 'market', s.value:market::VARCHAR, 'cmp_code', s.value:cmp_code::VARCHAR,
           'title', s.value:brand::VARCHAR || IFF(s.value:direction::VARCHAR = 'LOSS', ' lost', ' gained')
                    || ' share in ' || s.value:market::VARCHAR,
           'change_pts', GET(p.PACK:facts, s.value:delta::VARCHAR):v::FLOAT,
           'label', s.value:label::VARCHAR)) WITHIN GROUP (ORDER BY s.value:rank::NUMBER)
    INTO :shifts
    FROM (SELECT PACK FROM SR_DB.SEM.V_TOOL_BRIEF WHERE BRIEF_ID = :bid) p, LATERAL FLATTEN(INPUT => p.PACK:shifts) s;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
           'brand', h.value:brand::VARCHAR, 'market', h.value:market::VARCHAR,
           'change_pts', GET(p.PACK:facts, h.value:delta::VARCHAR):v::FLOAT, 'rules', h.value:rules))
    INTO :held
    FROM (SELECT PACK FROM SR_DB.SEM.V_TOOL_BRIEF WHERE BRIEF_ID = :bid) p, LATERAL FLATTEN(INPUT => p.PACK:held_back) h;
  RETURN TO_JSON(OBJECT_CONSTRUCT('brief_id', bid, 'as_of_week', wk, 'headline', head,
                                  'shifts', COALESCE(shifts, ARRAY_CONSTRUCT()), 'held_back', COALESCE(held, ARRAY_CONSTRUCT()),
                                  'source', 'SEM.V_TOOL_BRIEF'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- city_breakdown: where did it happen? Every city (optionally one region) ranked by share change, with coordinates.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_CITY_SHARE(P_BRAND VARCHAR, P_REGION VARCHAR, P_CMP_CODE VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  cmp     VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_CMP_CODE)), ''), 'L4W_VS_YA');
  reg_in  VARCHAR DEFAULT UPPER(TRIM(REPLACE(COALESCE(P_REGION, ''), ' Retail', '')));
  b       VARIANT;
  reg     VARCHAR;
  cat     VARCHAR;
  cities  ARRAY;
  regions ARRAY;
BEGIN
  IF (cmp NOT IN ('L4W_VS_YA', 'L4W_VS_PP', 'L12W_VS_YA', 'L52W_VS_YA')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Unknown comparison ' || cmp));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, :cmp) INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  IF (reg_in NOT IN ('', 'ALL', 'ALL INDIA', 'INDIA')) THEN
    SELECT MAX(REGION) INTO :reg FROM SR_DB.SEM.V_TOOL_CITY_SHARE WHERE UPPER(REGION) = :reg_in;
    IF (reg IS NULL) THEN
      LET known ARRAY := (SELECT ARRAY_AGG(DISTINCT REGION) FROM SR_DB.SEM.V_TOOL_CITY_SHARE);
      RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NOT_FOUND', 'what', 'region', 'input', P_REGION, 'candidates', known));
    END IF;
  END IF;
  -- The brand's scope category when it sells there, else its largest category in the comparison
  LET scope_cat VARCHAR := SR_DB.OPS.CFG('SCOPE_CATEGORY')::VARCHAR;
  SELECT CATEGORY INTO :cat FROM SR_DB.SEM.V_TOOL_CITY_SHARE
   WHERE BRAND = :bv AND CMP_CODE = :cmp
   GROUP BY CATEGORY
   ORDER BY IFF(CATEGORY = :scope_cat, 0, 1), SUM(ABS(VALUE_AT_STAKE)) DESC
   LIMIT 1;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('city', CITY, 'state', STATE, 'state_code', STATE_CODE, 'region', REGION,
                                    'lat', LATITUDE, 'lon', LONGITUDE, 'share_now_pct', 100 * SH1,
                                    'share_before_pct', 100 * SH0, 'change_pts', 100 * D_SHARE,
                                    'value_at_stake', VALUE_AT_STAKE))
           WITHIN GROUP (ORDER BY D_SHARE)
    INTO :cities
    FROM SR_DB.SEM.V_TOOL_CITY_SHARE
   WHERE BRAND = :bv AND CMP_CODE = :cmp AND CATEGORY = :cat AND MARKET_LEVEL = 'CITY'
     AND (:reg IS NULL OR REGION = :reg);
  IF (cities IS NULL OR ARRAY_SIZE(cities) = 0) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No city markets for this brand and comparison'));
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('region', REGION, 'change_pts', 100 * D_SHARE, 'value_at_stake', VALUE_AT_STAKE))
           WITHIN GROUP (ORDER BY D_SHARE)
    INTO :regions
    FROM SR_DB.SEM.V_TOOL_CITY_SHARE
   WHERE BRAND = :bv AND CMP_CODE = :cmp AND CATEGORY = :cat AND MARKET_LEVEL = 'RETAILER'
     AND (:reg IS NULL OR REGION = :reg);
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'brand', bv, 'category', cat, 'cmp_code', cmp, 'region', COALESCE(reg, 'ALL'),
    'cities', cities, 'regions', COALESCE(regions, ARRAY_CONSTRUCT()),
    'note', 'Cities are ordered from the largest loss to the largest gain. City shares are within each city; '
            || 'they do not add up to the region share.',
    'source', 'SEM.V_TOOL_CITY_SHARE'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- yearly_trend: the multi-year view. Value share by calendar year for one brand and market (city, region or total).
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_YEARLY_TREND(P_BRAND VARCHAR, P_MARKET VARCHAR, P_CATEGORY VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  b     VARIANT;
  m     VARIANT;
  cat   VARCHAR;
  years ARRAY;
BEGIN
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, 'L52W_VS_YA') INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, 'L52W_VS_YA') INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;
  SELECT MAX(CATEGORY) INTO :cat FROM SR_DB.SEM.V_TOOL_YEARLY_SHARE
   WHERE BRAND = :bv AND MARKET_ID = :mv
     AND UPPER(CATEGORY) = UPPER(COALESCE(NULLIF(TRIM(:P_CATEGORY), ''), SR_DB.OPS.CFG('SCOPE_CATEGORY')::VARCHAR));
  IF (cat IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No yearly data for this brand, market and category'));
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('year', CAL_YEAR, 'weeks', WEEKS, 'value_share_pct', 100 * VALUE_SHARE,
                                    'value_sales', VALUE_SALES, 'cat_value_sales', CAT_VALUE_SALES))
           WITHIN GROUP (ORDER BY CAL_YEAR)
    INTO :years
    FROM SR_DB.SEM.V_TOOL_YEARLY_SHARE
   WHERE BRAND = :bv AND MARKET_ID = :mv AND CATEGORY = :cat;
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'brand', bv, 'market', GET(m, 'name'), 'category', cat, 'years', years,
    'note', 'Years with fewer than 52 weeks are partial; compare their share, not their sales, with full years.',
    'source', 'SEM.V_TOOL_YEARLY_SHARE'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- price_promo: is price or promotion the problem? The brand vs every competitor in one market and period, vs year ago.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_PRICE_PROMO(P_BRAND VARCHAR, P_MARKET VARCHAR, P_PERIOD VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  per    VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_PERIOD)), ''), 'L12W');
  b      VARIANT;
  m      VARIANT;
  cat    VARCHAR;
  mine   VARIANT;
  rivals ARRAY;
BEGIN
  IF (per NOT IN ('L4W', 'L12W', 'L52W')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Period must be L4W, L12W or L52W'));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, 'L4W_VS_YA') INTO :b;
  IF (GET(b, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(b, 'error', GET(b, 'status'))); END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, 'L4W_VS_YA') INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET bv VARCHAR := GET(b, 'value')::VARCHAR;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;
  SELECT MAX(CATEGORY) INTO :cat FROM SR_DB.SEM.V_TOOL_PRICE_PROMO WHERE BRAND = :bv AND MARKET_ID = :mv AND PERIOD_CODE = :per;
  IF (cat IS NULL) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No sales for this brand, market and period'));
  END IF;
  SELECT OBJECT_CONSTRUCT('value_share_pct', 100 * VALUE_SHARE, 'share_chg_ya_pts', 100 * SHARE_CHG_YA,
                          'price_per_unit', PRICE_PER_UNIT, 'price_index', PRICE_INDEX, 'price_index_ya', PRICE_INDEX_YA,
                          'price_chg_ya_pct', 100 * PRICE_CHG_YA, 'promo_share_pct', 100 * PROMO_SHARE,
                          'promo_share_ya_pct', 100 * PROMO_SHARE_YA, 'promo_lift_pct', 100 * PROMO_LIFT)
    INTO :mine
    FROM SR_DB.SEM.V_TOOL_PRICE_PROMO WHERE BRAND = :bv AND MARKET_ID = :mv AND PERIOD_CODE = :per AND CATEGORY = :cat;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('brand', BRAND, 'value_share_pct', 100 * VALUE_SHARE, 'price_index', PRICE_INDEX,
                                    'price_chg_ya_pct', 100 * PRICE_CHG_YA, 'promo_share_pct', 100 * PROMO_SHARE,
                                    'share_chg_ya_pts', 100 * SHARE_CHG_YA))
           WITHIN GROUP (ORDER BY VALUE_SHARE DESC)
    INTO :rivals
    FROM (SELECT * FROM SR_DB.SEM.V_TOOL_PRICE_PROMO
          WHERE MARKET_ID = :mv AND PERIOD_CODE = :per AND CATEGORY = :cat AND BRAND <> :bv
          ORDER BY VALUE_SHARE DESC LIMIT 8);
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'brand', bv, 'market', GET(m, 'name'), 'category', cat, 'period', per, 'brand_metrics', mine,
    'top_competitors', COALESCE(rivals, ARRAY_CONSTRUCT()),
    'note', 'Price index: brand price per unit / category price per unit (1.0 = category average). Promo share: '
            || 'sales above base (incremental) / sales. Year-ago (_ya) values cover the same weeks a year earlier.',
    'source', 'SEM.V_TOOL_PRICE_PROMO'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- benchmark: one company against its rivals in one market and period, and where it is winning or losing.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_BENCHMARK(P_MANUFACTURER VARCHAR, P_MARKET VARCHAR, P_PERIOD VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  per     VARCHAR DEFAULT COALESCE(NULLIF(UPPER(TRIM(P_PERIOD)), ''), 'L12W');
  txt     VARCHAR DEFAULT UPPER(TRIM(COALESCE(P_MANUFACTURER, '')));
  m       VARIANT;
  mfr     VARCHAR;
  n_match NUMBER;
  cat     VARCHAR;
  table_  ARRAY;
  wins    ARRAY;
BEGIN
  IF (per NOT IN ('L4W', 'L12W', 'L52W')) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'BAD_INPUT', 'detail', 'Period must be L4W, L12W or L52W'));
  END IF;
  CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, 'L4W_VS_YA') INTO :m;
  IF (GET(m, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(m, 'error', GET(m, 'status'))); END IF;
  LET mv VARCHAR := GET(m, 'value')::VARCHAR;
  -- company: exact name, else a unique name containing the input; default the configured focus manufacturer
  IF (txt = '') THEN
    txt := UPPER(SR_DB.OPS.CFG('FOCUS_MANUFACTURER')::VARCHAR);
  END IF;
  SELECT MAX(MANUFACTURER), COUNT(DISTINCT MANUFACTURER) INTO :mfr, :n_match FROM SR_DB.SEM.V_TOOL_BENCHMARK
   WHERE MARKET_ID = :mv AND PERIOD_CODE = :per AND UPPER(MANUFACTURER) = :txt;
  IF (n_match = 0) THEN
    SELECT MAX(MANUFACTURER), COUNT(DISTINCT MANUFACTURER) INTO :mfr, :n_match FROM SR_DB.SEM.V_TOOL_BENCHMARK
     WHERE MARKET_ID = :mv AND PERIOD_CODE = :per AND CONTAINS(UPPER(MANUFACTURER), :txt);
  END IF;
  IF (n_match <> 1) THEN
    LET known ARRAY := (SELECT ARRAY_AGG(DISTINCT MANUFACTURER) FROM SR_DB.SEM.V_TOOL_BENCHMARK WHERE MARKET_ID = :mv);
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', IFF(n_match = 0, 'NOT_FOUND', 'AMBIGUOUS'), 'what', 'manufacturer',
                                    'input', P_MANUFACTURER, 'candidates', known));
  END IF;
  LET scope_cat VARCHAR := SR_DB.OPS.CFG('SCOPE_CATEGORY')::VARCHAR;
  SELECT CATEGORY INTO :cat FROM SR_DB.SEM.V_TOOL_BENCHMARK
   WHERE MANUFACTURER = :mfr AND MARKET_ID = :mv AND PERIOD_CODE = :per
   GROUP BY CATEGORY ORDER BY IFF(CATEGORY = :scope_cat, 0, 1), SUM(VALUE_SALES) DESC LIMIT 1;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('manufacturer', MANUFACTURER, 'is_focus', MANUFACTURER = :mfr, 'rank', SHARE_RANK,
                                    'rank_ya', SHARE_RANK_YA, 'value_share_pct', 100 * VALUE_SHARE,
                                    'share_chg_ya_pts', 100 * SHARE_CHG_YA, 'acv', ACV_DIST_PCT, 'acv_chg_ya', ACV_CHG_YA,
                                    'velocity', VELOCITY, 'price_index', PRICE_INDEX, 'skus', SKUS, 'brands', BRANDS,
                                    'sales_growth_ya_pct', 100 * SALES_GROWTH_YA))
           WITHIN GROUP (ORDER BY SHARE_RANK)
    INTO :table_
    FROM SR_DB.SEM.V_TOOL_BENCHMARK WHERE MARKET_ID = :mv AND PERIOD_CODE = :per AND CATEGORY = :cat;
  -- where the company wins or loses: its share change vs year ago in each region and city
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('market', MARKET_NAME, 'level', MARKET_LEVEL, 'rank', SHARE_RANK,
                                    'value_share_pct', 100 * VALUE_SHARE, 'share_chg_ya_pts', 100 * SHARE_CHG_YA))
           WITHIN GROUP (ORDER BY SHARE_CHG_YA)
    INTO :wins
    FROM SR_DB.SEM.V_TOOL_BENCHMARK
   WHERE MANUFACTURER = :mfr AND PERIOD_CODE = :per AND CATEGORY = :cat AND MARKET_LEVEL IN ('RETAILER', 'CITY');
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'manufacturer', mfr, 'market', GET(m, 'name'), 'category', cat, 'period', per,
    'league_table', COALESCE(table_, ARRAY_CONSTRUCT()), 'by_market', COALESCE(wins, ARRAY_CONSTRUCT()),
    'note', 'Velocity: units per store-week selling. Price index: company price per unit / category price per unit. '
            || 'by_market is ordered from the largest share loss vs year ago to the largest gain.',
    'source', 'SEM.V_TOOL_BENCHMARK'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;

-- risk_outlook: what is about to go wrong? The latest early-warning signals, optionally for one brand or market.
CREATE OR REPLACE PROCEDURE SR_DB.APP.TOOL_RISK_OUTLOOK(P_BRAND VARCHAR, P_MARKET VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  bv   VARCHAR DEFAULT NULL;
  mv   VARCHAR DEFAULT NULL;
  r    VARIANT;
  sigs ARRAY;
BEGIN
  IF (TRIM(COALESCE(P_BRAND, '')) <> '') THEN
    CALL SR_DB.APP.SP_RESOLVE('BRAND', :P_BRAND, 'L4W_VS_YA') INTO :r;
    IF (GET(r, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(r, 'error', GET(r, 'status'))); END IF;
    bv := GET(r, 'value')::VARCHAR;
  END IF;
  IF (TRIM(COALESCE(P_MARKET, '')) <> '') THEN
    CALL SR_DB.APP.SP_RESOLVE('MARKET', :P_MARKET, 'L4W_VS_YA') INTO :r;
    IF (GET(r, 'status')::VARCHAR <> 'OK') THEN RETURN TO_JSON(OBJECT_INSERT(r, 'error', GET(r, 'status'))); END IF;
    mv := GET(r, 'value')::VARCHAR;
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('brand', BRAND, 'market', MARKET_NAME, 'level', MARKET_LEVEL, 'signal', SIGNAL,
                                    'latest_week', LATEST_WEEK, 'lever_latest', LEVER_LATEST, 'lever_l4w', LEVER_L4W,
                                    'lever_chg_pct', 100 * LEVER_CHG, 'projected_share_pts', PROJECTED_SHARE_PTS,
                                    'ml_confirmed', ML_CONFIRMED))
           WITHIN GROUP (ORDER BY ABS(COALESCE(PROJECTED_SHARE_PTS, 0)) DESC)
    INTO :sigs
    FROM SR_DB.SEM.V_TOOL_EARLY_WARNING
   WHERE (:bv IS NULL OR BRAND = :bv) AND (:mv IS NULL OR MARKET_ID = :mv);
  IF (sigs IS NULL OR ARRAY_SIZE(sigs) = 0) THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'NO_DATA', 'detail', 'No early-warning signal in the latest run for this filter'));
  END IF;
  RETURN TO_JSON(OBJECT_CONSTRUCT(
    'brand', bv, 'market_id', mv, 'signals', sigs,
    'note', 'DIST_DROP: latest-week distribution share against its last-four-week average; PRICE_RISE: latest-week price '
            || 'index against its last-four-week average. projected_share_pts: the mechanical effect on next L4W share if '
            || 'the latest week persists; not a forecast. ml_confirmed: the anomaly model also flagged it.',
    'source', 'SEM.V_TOOL_EARLY_WARNING'));
EXCEPTION
  WHEN OTHER THEN
    RETURN TO_JSON(OBJECT_CONSTRUCT('error', 'TOOL_FAILED', 'sqlcode', SQLCODE, 'detail', LEFT(SQLERRM, 300)));
END;
$$;
