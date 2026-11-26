-- Read-only views for the Shift detail analysis tabs (forecast, statistics, region map, SKU heatmaps).
-- They read the replay-filtered source views, so they move with AS_OF_WEEK_END like the rest of the app.
-- SR_UI reads them through the FUTURE VIEWS grant on SR_DB.APP (70_sec/701).
USE ROLE SR_DEV;

-- One row per week x market x SKU, with product and market attributes
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_SKU_WEEK
COMMENT = 'Weekly SKU facts with product and market attributes for the analysis tabs'
AS
SELECT f.WEEK_END_DATE, f.MARKET_ID, m.MARKET_NAME, m.MARKET_LEVEL, m.RETAILER, m.REGION, m.CHANNEL,
       f.PRODUCT_ID, p.ITEM_DESC, p.BRAND, p.MANUFACTURER, p.CATEGORY, p.SEGMENT, p.PACK_SIZE,
       f.VALUE_SALES, f.VOLUME_SALES, f.UNIT_SALES, f.ACV_DIST_PCT, f.STORES_SELLING
FROM SR_DB.SRC.V_SRC_FACT_WEEKLY f
JOIN SR_DB.SRC.V_SRC_PRODUCT p ON p.PRODUCT_ID = f.PRODUCT_ID
JOIN SR_DB.SRC.V_SRC_MARKET  m ON m.MARKET_ID  = f.MARKET_ID;

-- One row per week x retailer market x category x brand: sales, category share and SKU count (map and heatmaps)
CREATE OR REPLACE VIEW SR_DB.APP.V_UI_REGION_SUMMARY
COMMENT = 'Weekly brand sales, category value share and SKU count per retailer market and region'
AS
WITH b AS (
  SELECT WEEK_END_DATE, MARKET_ID, MARKET_NAME, RETAILER, REGION, CATEGORY, MANUFACTURER, BRAND,
         SUM(VALUE_SALES) AS VALUE_SALES, SUM(UNIT_SALES) AS UNIT_SALES,
         COUNT_IF(VALUE_SALES > 0) AS SKUS_SELLING, MAX(STORES_SELLING) AS MAX_STORES_SELLING
  FROM SR_DB.APP.V_UI_SKU_WEEK
  WHERE MARKET_LEVEL = 'RETAILER'
  GROUP BY WEEK_END_DATE, MARKET_ID, MARKET_NAME, RETAILER, REGION, CATEGORY, MANUFACTURER, BRAND
)
SELECT b.*, b.VALUE_SALES / NULLIF(SUM(b.VALUE_SALES) OVER (PARTITION BY b.WEEK_END_DATE, b.MARKET_ID, b.CATEGORY), 0)
       AS VALUE_SHARE
FROM b;
