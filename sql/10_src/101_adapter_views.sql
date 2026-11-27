-- SR-003 · L3 source adapter. THE ONLY FILE THAT NAMES NIQ OBJECTS (AGENTS.md rule 5).
--
-- Status: LOCAL DEMO MAPPING to SYNTHETIC data in UNIQ_202611.SYNTHETIC_RETAIL (scripts/synthetic_weekly_facts.sql).
-- Not NIQ data. Replace with the mapping approved in SR-003 before any real use. Nothing downstream changes.
--
-- | Contract column    | NIQ object.column | Transform                 | Note                           |
-- | ------------------ | ----------------- | ------------------------- | ------------------------------ |
-- | WEEK_END_DATE      | <fill>            | ::DATE                    |                                |
-- | MARKET_ID          | <fill>            | ::VARCHAR                 |                                |
-- | PRODUCT_ID         | <fill>            | ::VARCHAR                 | UPC or NIQ item code           |
-- | VALUE_SALES        | <fill>            | ::NUMBER(18,2)            | local currency                 |
-- | UNIT_SALES         | <fill>            | ::NUMBER(18,3)            | NULL if absent                 |
-- | ACV_DIST_PCT       | <fill>            | x100 if stored as 0-1     | NULL if absent -> mode C or D  |
-- | BASE_VALUE_SALES   | <fill>            | ::NUMBER(18,2)            | NULL if absent -> mode B       |
-- | BASE_UNIT_SALES    | <fill>            | ::NUMBER(18,3)            | NULL if absent -> mode B       |
-- | STORES_SELLING     | <fill>            | ::NUMBER(9,0)             | NULL if absent                 |
--
-- Optional columns may be NULL; SP_CAPABILITY_CHECK then caps the bridge mode (L3, E04).
USE ROLE SR_DEV;

CREATE OR REPLACE VIEW SR_DB.SRC.V_SRC_FACT_WEEKLY_ALL (
  WEEK_END_DATE, MARKET_ID, PRODUCT_ID, VALUE_SALES, VOLUME_SALES, UNIT_SALES,
  ACV_DIST_PCT, BASE_VALUE_SALES, BASE_UNIT_SALES, STORES_SELLING, DATA_VERSION
)
COMMENT = 'Item x market x week facts, all weeks (contract L3)'
AS
SELECT
  f.WEEK_END_DATE::DATE,
  f.MARKET_ID::VARCHAR,
  f.PRODUCT_ID::VARCHAR,
  f.VALUE_SALES::NUMBER(18,2),
  f.VOLUME_SALES::NUMBER(18,3),
  f.UNIT_SALES::NUMBER(18,3),
  f.ACV_DIST_PCT::NUMBER(9,4),           -- already 0-100
  f.BASE_VALUE_SALES::NUMBER(18,2),
  f.BASE_UNIT_SALES::NUMBER(18,3),
  f.STORES_SELLING::NUMBER(9,0),
  f.DATA_VERSION::VARCHAR
FROM UNIQ_202611.SYNTHETIC_RETAIL.SR_WEEKLY_FACTS f
WHERE f.VALUE_SALES IS NOT NULL;

-- Replay control: everything downstream reads this view, never the _ALL view (except SP_REPLAY_NEXT_WEEK).
CREATE OR REPLACE VIEW SR_DB.SRC.V_SRC_FACT_WEEKLY
COMMENT = 'V_SRC_FACT_WEEKLY_ALL up to OPS.SETTINGS AS_OF_WEEK_END (replay control)'
AS
SELECT f.WEEK_END_DATE, f.MARKET_ID, f.PRODUCT_ID, f.VALUE_SALES, f.VOLUME_SALES, f.UNIT_SALES,
       f.ACV_DIST_PCT, f.BASE_VALUE_SALES, f.BASE_UNIT_SALES, f.STORES_SELLING, f.DATA_VERSION
FROM SR_DB.SRC.V_SRC_FACT_WEEKLY_ALL f
WHERE f.WEEK_END_DATE <= (
  SELECT SETTING_VALUE::VARCHAR::DATE FROM SR_DB.OPS.SETTINGS WHERE SETTING_KEY = 'AS_OF_WEEK_END'
);

CREATE OR REPLACE VIEW SR_DB.SRC.V_SRC_PRODUCT (
  PRODUCT_ID, ITEM_DESC, BRAND, MANUFACTURER, CATEGORY, SEGMENT, PACK_SIZE, IS_PRIVATE_LABEL
)
COMMENT = 'Product hierarchy (contract L3)'
AS
SELECT p.PRODUCT_ID::VARCHAR, p.ITEM_DESC, p.BRAND, p.MANUFACTURER, p.CATEGORY,
       p.SEGMENT, p.PACK_SIZE::VARCHAR, COALESCE(p.IS_PRIVATE_LABEL, FALSE)::BOOLEAN
FROM UNIQ_202611.SYNTHETIC_RETAIL.SR_PRODUCTS p;

CREATE OR REPLACE VIEW SR_DB.SRC.V_SRC_MARKET (
  MARKET_ID, MARKET_NAME, MARKET_LEVEL, PARENT_MARKET_ID, RETAILER, CHANNEL, REGION,
  CITY, STATE, STATE_CODE, LATITUDE, LONGITUDE
)
COMMENT = 'Market hierarchy: TOTAL, CHANNEL, RETAILER, REGION, CITY, with map coordinates (contract L3)'
AS
SELECT m.MARKET_ID::VARCHAR, m.MARKET_NAME, m.MARKET_LEVEL, m.PARENT_MARKET_ID::VARCHAR,
       m.RETAILER, m.CHANNEL, m.REGION,
       m.CITY::VARCHAR, m.STATE::VARCHAR, m.STATE_CODE::VARCHAR,   -- STATE_CODE is ISO 3166-2
       m.LATITUDE::NUMBER(9,6), m.LONGITUDE::NUMBER(9,6)           -- WGS84 degrees; NULL when unknown
FROM UNIQ_202611.SYNTHETIC_RETAIL.SR_MARKETS m;

-- Optional (rule R1 uses it when present).
CREATE OR REPLACE VIEW SR_DB.SRC.V_SRC_MARKET_UNIVERSE (MARKET_ID, WEEK_END_DATE, STORE_COUNT) AS
SELECT u.MARKET_ID::VARCHAR, u.WEEK_END_DATE::DATE, u.STORE_COUNT::NUMBER(9,0)
FROM UNIQ_202611.SYNTHETIC_RETAIL.SR_MARKET_UNIVERSE u;
