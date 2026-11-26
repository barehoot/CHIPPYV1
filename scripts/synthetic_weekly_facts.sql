-- SYNTHETIC DATA for a local Share Radar demo run. Not NIQ data.
-- Builds weekly item x market facts in the shape of the L3 contract from the PRODUCTS and STORES tables of
-- synthetic_data_retail_demo.sql (run that first). 70 weeks ending Saturday, 4 retailer markets under MKT_TOTAL.
-- Demo pattern kept: Brand C loses Snacks share over the last 6 weeks, driven mainly by distribution.
USE SCHEMA UNIQ_202611.SYNTHETIC_RETAIL;

-- Market hierarchy: one total, the four regions as retailer markets
CREATE OR REPLACE TABLE SR_MARKETS AS
SELECT 'MKT_TOTAL' AS market_id, 'Total Market' AS market_name, 'TOTAL' AS market_level,
       NULL::VARCHAR AS parent_market_id, NULL::VARCHAR AS retailer, 'All' AS channel, NULL::VARCHAR AS region
UNION ALL
SELECT 'MKT_' || UPPER(region), region || ' Retail', 'RETAILER', 'MKT_TOTAL', region || ' Retail', 'Grocery', region
FROM (SELECT DISTINCT region FROM STORES);

-- Product hierarchy: each brand belongs to one of five synthetic manufacturers
CREATE OR REPLACE TABLE SR_PRODUCTS AS
SELECT product_id, product_name AS item_desc, brand_name AS brand,
       'Manufacturer ' || (1 + MOD(ASCII(RIGHT(brand_name, 1)) - 65, 5))::VARCHAR AS manufacturer,
       category, IFF(MOD(TRY_TO_NUMBER(RIGHT(product_id, 4)), 2) = 0, 'Standard', 'Large') AS segment,
       IFF(MOD(TRY_TO_NUMBER(RIGHT(product_id, 4)), 2) = 0, '200g', '500g') AS pack_size,
       FALSE AS is_private_label, unit_price
FROM PRODUCTS;

-- Store counts per retailer market (the universe)
CREATE OR REPLACE TABLE SR_MARKET_STORES AS
SELECT 'MKT_' || UPPER(region) AS market_id, COUNT(*) AS store_count FROM STORES GROUP BY region;

-- Random draws materialised once per row (RANDOM() in a CTE can be re-evaluated)
CREATE OR REPLACE TEMPORARY TABLE SR_FACT_RAW AS
WITH weeks AS (
  SELECT DATEADD(week, -SEQ4(), PREVIOUS_DAY(CURRENT_DATE(), 'sa')) AS week_end_date, SEQ4() AS weeks_ago
  FROM TABLE(GENERATOR(ROWCOUNT => 70))
)
SELECT w.week_end_date, w.weeks_ago, m.market_id, m.store_count, p.product_id, p.brand, p.category, p.unit_price,
       UNIFORM(0::FLOAT, 1::FLOAT, RANDOM()) AS u_vol,
       UNIFORM(0::FLOAT, 1::FLOAT, RANDOM()) AS u_promo,
       UNIFORM(0::FLOAT, 1::FLOAT, RANDOM()) AS u_dist
FROM weeks w CROSS JOIN SR_MARKET_STORES m CROSS JOIN SR_PRODUCTS p;

CREATE OR REPLACE TABLE SR_WEEKLY_FACTS AS
WITH shaped AS (
  SELECT r.*,
         -- distribution: 70-95 ACV, Brand C Snacks drops to about half in the last 6 weeks
         (70 + 25 * r.u_dist) * IFF(r.brand = 'Brand C' AND r.category = 'Snacks' AND r.weeks_ago < 6, 0.5, 1) AS acv,
         -- baseline units: skewed by product number, mild seasonality
         (40 + 400 / SQRT(TRY_TO_NUMBER(RIGHT(r.product_id, 4))))
           * (1 + 0.08 * SIN(2 * PI() * r.weeks_ago / 52)) * (0.9 + 0.2 * r.u_vol) AS base_units_full,
         IFF(r.u_promo < 0.12, 1.35, 1.0) AS promo_lift
  FROM SR_FACT_RAW r
)
SELECT week_end_date, market_id, product_id,
       ROUND(base_units_full * acv / 85 * promo_lift * unit_price, 2)          AS value_sales,
       ROUND(base_units_full * acv / 85 * promo_lift, 3)                      AS volume_sales,
       ROUND(base_units_full * acv / 85 * promo_lift, 3)                      AS unit_sales,
       ROUND(acv, 4)                                                          AS acv_dist_pct,
       ROUND(base_units_full * acv / 85 * unit_price, 2)                      AS base_value_sales,
       ROUND(base_units_full * acv / 85, 3)                                   AS base_unit_sales,
       ROUND(store_count * acv / 100)::NUMBER(9,0)                            AS stores_selling,
       'SYN_V1'                                                               AS data_version
FROM shaped;

-- Total market rows: the sum of the four retailer markets (ACV is store-weighted)
INSERT INTO SR_WEEKLY_FACTS
SELECT f.week_end_date, 'MKT_TOTAL', f.product_id, SUM(f.value_sales), SUM(f.volume_sales), SUM(f.unit_sales),
       ROUND(100 * SUM(f.stores_selling) / MAX(t.total_stores), 4), SUM(f.base_value_sales), SUM(f.base_unit_sales),
       SUM(f.stores_selling), 'SYN_V1'
FROM SR_WEEKLY_FACTS f CROSS JOIN (SELECT SUM(store_count) AS total_stores FROM SR_MARKET_STORES) t
GROUP BY f.week_end_date, f.product_id;

-- Weekly store universe per market
INSERT INTO SR_MARKET_STORES SELECT 'MKT_TOTAL', SUM(store_count) FROM SR_MARKET_STORES;
CREATE OR REPLACE TABLE SR_MARKET_UNIVERSE AS
SELECT m.market_id, w.week_end_date, m.store_count
FROM SR_MARKET_STORES m CROSS JOIN (SELECT DISTINCT week_end_date FROM SR_WEEKLY_FACTS) w;

COMMENT ON TABLE SR_MARKETS         IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_PRODUCTS        IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_WEEKLY_FACTS    IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_MARKET_UNIVERSE IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';

-- Check: weeks, rows, and the Brand C Snacks share (recent 6 weeks vs earlier), retailer markets summed
WITH snacks AS (
  SELECT f.week_end_date, f.value_sales, p.brand,
         f.week_end_date > DATEADD(week, -6, (SELECT MAX(week_end_date) FROM SR_WEEKLY_FACTS)) AS is_recent
  FROM SR_WEEKLY_FACTS f JOIN SR_PRODUCTS p ON p.product_id = f.product_id
  WHERE p.category = 'Snacks'
)
SELECT (SELECT COUNT(DISTINCT week_end_date) FROM SR_WEEKLY_FACTS) AS weeks,
       (SELECT MAX(week_end_date) FROM SR_WEEKLY_FACTS) AS last_week,
       (SELECT COUNT(*) FROM SR_WEEKLY_FACTS) AS fact_rows,
       SUM(IFF(brand = 'Brand C' AND is_recent, value_sales, 0)) / NULLIF(SUM(IFF(is_recent, value_sales, 0)), 0) AS c_share_recent,
       SUM(IFF(brand = 'Brand C' AND NOT is_recent, value_sales, 0)) / NULLIF(SUM(IFF(NOT is_recent, value_sales, 0)), 0) AS c_share_earlier
FROM snacks;
