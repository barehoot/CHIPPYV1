-- Read-only views for the Shift detail analysis tabs (forecast, statistics, region map, SKU heatmaps), Insight Studio,
-- the share report and the Intelligence brief. They read ALL source weeks (2020 onwards) so the sidebar's as-of week can
-- go back in time; every app query caps its window at the chosen week (data.filters()), which defaults to
-- OPS.SETTINGS AS_OF_WEEK_END, so by default the app still moves with replay.
-- SR_UI reads them through the FUTURE VIEWS grant on SR_DB.APP (70_sec/701).
USE ROLE SR_DEV;

-- One row per week x market x SKU, with product and market attributes (market level TOTAL, RETAILER or CITY)
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_SKU_WEEK
COMMENT = 'Weekly SKU facts, all weeks, with product and market (region, city, coordinates) attributes'
AS
SELECT f.WEEK_END_DATE, f.MARKET_ID, m.MARKET_NAME, m.MARKET_LEVEL, m.PARENT_MARKET_ID, m.RETAILER, m.REGION,
       m.CITY, m.STATE, m.LATITUDE, m.LONGITUDE, m.CHANNEL,
       f.PRODUCT_ID, p.ITEM_DESC, p.BRAND, p.MANUFACTURER, p.CATEGORY, p.SEGMENT, p.PACK_SIZE,
       f.VALUE_SALES, f.VOLUME_SALES, f.UNIT_SALES, f.ACV_DIST_PCT, f.STORES_SELLING
FROM SR_DB.SRC.V_SRC_FACT_WEEKLY_ALL f
JOIN SR_DB.SRC.V_SRC_PRODUCT p ON p.PRODUCT_ID = f.PRODUCT_ID
JOIN SR_DB.SRC.V_SRC_MARKET  m ON m.MARKET_ID  = f.MARKET_ID;

-- One row per week x region/city market x category x brand: sales, category share and SKU count (map and heatmaps)
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_REGION_SUMMARY
COMMENT = 'Weekly brand sales, category value share and SKU count per region and city market'
AS
WITH b AS (
  SELECT WEEK_END_DATE, MARKET_ID, MARKET_NAME, MARKET_LEVEL, RETAILER, REGION, CITY, CATEGORY, MANUFACTURER, BRAND,
         SUM(VALUE_SALES) AS VALUE_SALES, SUM(UNIT_SALES) AS UNIT_SALES,
         COUNT_IF(VALUE_SALES > 0) AS SKUS_SELLING, MAX(STORES_SELLING) AS MAX_STORES_SELLING
  FROM SR_DB.APP.V_UI_SKU_WEEK
  WHERE MARKET_LEVEL IN ('RETAILER', 'CITY')
  GROUP BY WEEK_END_DATE, MARKET_ID, MARKET_NAME, MARKET_LEVEL, RETAILER, REGION, CITY, CATEGORY, MANUFACTURER, BRAND
)
SELECT b.*, b.VALUE_SALES / NULLIF(SUM(b.VALUE_SALES) OVER (PARTITION BY b.WEEK_END_DATE, b.MARKET_ID, b.CATEGORY), 0)
       AS VALUE_SHARE
FROM b;

-- Weeks the sidebar can pick: every source week, newest first, flagged when a stored run exists for it
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_WEEKS
COMMENT = 'Every data week with a flag for weeks that have a successful stored run'
AS
SELECT w.WEEK_END_DATE, (r.AS_OF_WEEK IS NOT NULL) AS HAS_RUN
FROM (SELECT DISTINCT WEEK_END_DATE FROM SR_DB.SRC.V_SRC_FACT_WEEKLY_ALL) w
LEFT JOIN (SELECT DISTINCT AS_OF_WEEK FROM SR_DB.OPS.RUN_LOG WHERE STATUS = 'SUCCEEDED') r ON r.AS_OF_WEEK = w.WEEK_END_DATE;

-- Filter choices for the sidebar: category x manufacturer x brand
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_PRODUCT_TREE
COMMENT = 'Distinct category, manufacturer and brand for the sidebar filters'
AS
SELECT DISTINCT CATEGORY, MANUFACTURER, BRAND FROM SR_DB.SRC.V_SRC_PRODUCT;
