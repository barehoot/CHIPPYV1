-- SYNTHETIC DATA for a local Share Radar demo run. Not NIQ data.
-- Builds weekly item x market facts in the shape of the L3 contract from the PRODUCTS and STORES tables of
-- synthetic_data_retail_demo.sql (run that first). 330 weeks ending Saturday (about 6.3 years).
-- Market hierarchy: All India (TOTAL) > 4 regions (RETAILER level, the children the pipeline reads) > 12 cities
-- (CITY level, with state and coordinates for the map). Facts are generated per city; regions and the total are sums.
-- Demo pattern kept: Brand C loses Snacks share over the last 6 weeks, driven mainly by distribution.
-- Also: about 4% yearly growth and a festive-season (Diwali, ISO weeks 42-45) peak.
USE SCHEMA UNIQ_202611.SYNTHETIC_RETAIL;

-- City reference: region, state, ISO 3166-2:IN code, coordinates, and the city's part of its region's stores
CREATE OR REPLACE TRANSIENT TABLE SR_CITY_REF AS
SELECT column1 AS city, column2 AS region, column3 AS state, column4 AS state_code,
       column5::NUMBER(9,6) AS latitude, column6::NUMBER(9,6) AS longitude, column7::FLOAT AS store_part
FROM VALUES
  ('Delhi',       'North', 'Delhi',          'IN-DL', 28.613900, 77.209000, 0.45),
  ('Lucknow',     'North', 'Uttar Pradesh',  'IN-UP', 26.846700, 80.946200, 0.30),
  ('Jaipur',      'North', 'Rajasthan',      'IN-RJ', 26.912400, 75.787300, 0.25),
  ('Bengaluru',   'South', 'Karnataka',      'IN-KA', 12.971600, 77.594600, 0.40),
  ('Chennai',     'South', 'Tamil Nadu',     'IN-TN', 13.082700, 80.270700, 0.32),
  ('Hyderabad',   'South', 'Telangana',      'IN-TG', 17.385000, 78.486700, 0.28),
  ('Kolkata',     'East',  'West Bengal',    'IN-WB', 22.572600, 88.363900, 0.50),
  ('Bhubaneswar', 'East',  'Odisha',         'IN-OR', 20.296100, 85.824500, 0.24),
  ('Patna',       'East',  'Bihar',          'IN-BR', 25.594100, 85.137600, 0.26),
  ('Mumbai',      'West',  'Maharashtra',    'IN-MH', 19.076000, 72.877700, 0.44),
  ('Pune',        'West',  'Maharashtra',    'IN-MH', 18.520400, 73.856700, 0.28),
  ('Ahmedabad',   'West',  'Gujarat',        'IN-GJ', 23.022500, 72.571400, 0.28);

-- Market hierarchy: one total, the four regions, the twelve cities
CREATE OR REPLACE TABLE SR_MARKETS AS
SELECT 'MKT_TOTAL' AS market_id, 'All India' AS market_name, 'TOTAL' AS market_level,
       NULL::VARCHAR AS parent_market_id, NULL::VARCHAR AS retailer, 'All' AS channel, NULL::VARCHAR AS region,
       NULL::VARCHAR AS city, NULL::VARCHAR AS state, NULL::VARCHAR AS state_code,
       20.593700::NUMBER(9,6) AS latitude, 78.962900::NUMBER(9,6) AS longitude
UNION ALL
SELECT 'MKT_' || UPPER(region), region || ' Retail', 'RETAILER', 'MKT_TOTAL', region || ' Retail', 'Grocery', region,
       NULL, NULL, NULL, AVG(latitude)::NUMBER(9,6), AVG(longitude)::NUMBER(9,6)
FROM SR_CITY_REF GROUP BY region
UNION ALL
SELECT 'MKT_' || UPPER(region) || '_' || UPPER(city), city, 'CITY', 'MKT_' || UPPER(region), region || ' Retail',
       'Grocery', region, city, state, state_code, latitude, longitude
FROM SR_CITY_REF;

-- Product hierarchy: each brand belongs to one of five synthetic manufacturers
CREATE OR REPLACE TABLE SR_PRODUCTS AS
SELECT product_id, product_name AS item_desc, brand_name AS brand,
       'Manufacturer ' || (1 + MOD(ASCII(RIGHT(brand_name, 1)) - 65, 5))::VARCHAR AS manufacturer,
       category, IFF(MOD(TRY_TO_NUMBER(RIGHT(product_id, 4)), 2) = 0, 'Standard', 'Large') AS segment,
       IFF(MOD(TRY_TO_NUMBER(RIGHT(product_id, 4)), 2) = 0, '200g', '500g') AS pack_size,
       FALSE AS is_private_label, unit_price
FROM PRODUCTS;

-- Store counts per city market (the universe); each region's stores are split across its cities
CREATE OR REPLACE TABLE SR_MARKET_STORES AS
SELECT 'MKT_' || UPPER(c.region) || '_' || UPPER(c.city) AS market_id, GREATEST(1, ROUND(s.n * c.store_part)) AS store_count
FROM SR_CITY_REF c JOIN (SELECT region, COUNT(*) AS n FROM STORES GROUP BY region) s ON s.region = c.region;

-- Random draws materialised once per row (RANDOM() in a CTE can be re-evaluated)
CREATE OR REPLACE TRANSIENT TABLE SR_FACT_RAW AS
WITH weeks AS (
  SELECT DATEADD(week, -SEQ4(), PREVIOUS_DAY(CURRENT_DATE(), 'sa')) AS week_end_date, SEQ4() AS weeks_ago
  FROM TABLE(GENERATOR(ROWCOUNT => 330))
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
         -- baseline units: skewed by product number, mild seasonality, ~4% yearly growth, festive peak
         (40 + 400 / SQRT(TRY_TO_NUMBER(RIGHT(r.product_id, 4))))
           * (1 + 0.08 * SIN(2 * PI() * r.weeks_ago / 52)) * (0.9 + 0.2 * r.u_vol)
           * POWER(1.04, -r.weeks_ago / 52)
           * IFF(WEEKOFYEAR(r.week_end_date) BETWEEN 42 AND 45, 1.15, 1.0)
           * r.store_count / 12.5 AS base_units_full,
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
       'SYN_V2'                                                               AS data_version
FROM shaped;

-- Region rows: the sum of their cities (ACV is store-weighted)
INSERT INTO SR_MARKET_STORES
SELECT m.parent_market_id, SUM(s.store_count)
FROM SR_MARKET_STORES s JOIN SR_MARKETS m ON m.market_id = s.market_id GROUP BY m.parent_market_id;

INSERT INTO SR_WEEKLY_FACTS
SELECT f.week_end_date, m.parent_market_id, f.product_id, SUM(f.value_sales), SUM(f.volume_sales), SUM(f.unit_sales),
       ROUND(100 * SUM(f.stores_selling) / MAX(u.store_count), 4), SUM(f.base_value_sales), SUM(f.base_unit_sales),
       SUM(f.stores_selling), 'SYN_V2'
FROM SR_WEEKLY_FACTS f
JOIN SR_MARKETS m ON m.market_id = f.market_id AND m.market_level = 'CITY'
JOIN SR_MARKET_STORES u ON u.market_id = m.parent_market_id
GROUP BY f.week_end_date, m.parent_market_id, f.product_id;

-- Total market rows: the sum of the four regions
INSERT INTO SR_MARKET_STORES
SELECT 'MKT_TOTAL', SUM(s.store_count)
FROM SR_MARKET_STORES s JOIN SR_MARKETS m ON m.market_id = s.market_id AND m.market_level = 'RETAILER';

INSERT INTO SR_WEEKLY_FACTS
SELECT f.week_end_date, 'MKT_TOTAL', f.product_id, SUM(f.value_sales), SUM(f.volume_sales), SUM(f.unit_sales),
       ROUND(100 * SUM(f.stores_selling) / MAX(t.store_count), 4), SUM(f.base_value_sales), SUM(f.base_unit_sales),
       SUM(f.stores_selling), 'SYN_V2'
FROM SR_WEEKLY_FACTS f
JOIN SR_MARKETS m ON m.market_id = f.market_id AND m.market_level = 'RETAILER'
CROSS JOIN (SELECT store_count FROM SR_MARKET_STORES WHERE market_id = 'MKT_TOTAL') t
GROUP BY f.week_end_date, f.product_id;

-- Weekly store universe per market
CREATE OR REPLACE TABLE SR_MARKET_UNIVERSE AS
SELECT m.market_id, w.week_end_date, m.store_count
FROM SR_MARKET_STORES m CROSS JOIN (SELECT DISTINCT week_end_date FROM SR_WEEKLY_FACTS) w;

DROP TABLE IF EXISTS SR_FACT_RAW;
DROP TABLE IF EXISTS SR_CITY_REF;

COMMENT ON TABLE SR_MARKETS         IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_PRODUCTS        IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_WEEKLY_FACTS    IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';
COMMENT ON TABLE SR_MARKET_UNIVERSE IS 'SYNTHETIC DATA: generated for demo and testing, not NiQ data';

-- CREATE OR REPLACE drops grants: the SR_DB adapter views (owner SR_DEV) must keep reading these tables
GRANT SELECT ON TABLE SR_WEEKLY_FACTS    TO ROLE SR_DEV;
GRANT SELECT ON TABLE SR_PRODUCTS        TO ROLE SR_DEV;
GRANT SELECT ON TABLE SR_MARKETS         TO ROLE SR_DEV;
GRANT SELECT ON TABLE SR_MARKET_UNIVERSE TO ROLE SR_DEV;

-- Check: weeks, rows, and the Brand C Snacks share (recent 6 weeks vs earlier), total market only
WITH snacks AS (
  SELECT f.week_end_date, f.value_sales, p.brand,
         f.week_end_date > DATEADD(week, -6, (SELECT MAX(week_end_date) FROM SR_WEEKLY_FACTS)) AS is_recent
  FROM SR_WEEKLY_FACTS f JOIN SR_PRODUCTS p ON p.product_id = f.product_id
  WHERE p.category = 'Snacks' AND f.market_id = 'MKT_TOTAL'
)
SELECT (SELECT COUNT(DISTINCT week_end_date) FROM SR_WEEKLY_FACTS) AS weeks,
       (SELECT MAX(week_end_date) FROM SR_WEEKLY_FACTS) AS last_week,
       (SELECT COUNT(*) FROM SR_WEEKLY_FACTS) AS fact_rows,
       SUM(IFF(brand = 'Brand C' AND is_recent, value_sales, 0)) / NULLIF(SUM(IFF(is_recent, value_sales, 0)), 0) AS c_share_recent,
       SUM(IFF(brand = 'Brand C' AND NOT is_recent, value_sales, 0)) / NULLIF(SUM(IFF(NOT is_recent, value_sales, 0)), 0) AS c_share_earlier
FROM snacks;
