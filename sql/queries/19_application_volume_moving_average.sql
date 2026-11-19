-- Title: Monthly application volume with moving average and year-over-year change
-- Business question: Is application volume trending up or down once month-to-month noise is smoothed out?
-- Tables: fact_application, dim_date
-- Technique: month spine from dim_date (rows where day_of_month = 1) LEFT JOINed to counts so empty
--   months stay in; AVG() OVER (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) for the 3-month moving
--   average; LAG(n, 12) for the same month a year earlier.
-- Edge cases: the moving average is NULL until three months exist; year-over-year is NULL when there
--   is no prior-year month or it was zero; a missing month would shift ROWS-based windows, which is
--   why the spine is built first.
WITH bounds AS MATERIALIZED (
    SELECT date(MIN(applied_at), 'start of month') AS first_m,
           date(MAX(applied_at), 'start of month') AS last_m
    FROM fact_application
),
months AS (
    SELECT d.full_date AS month_start
    FROM dim_date d, bounds b
    WHERE d.day_of_month = 1 AND d.full_date BETWEEN b.first_m AND b.last_m
),
counts AS MATERIALIZED (
    SELECT date(applied_at, 'start of month') AS m, COUNT(*) AS n FROM fact_application GROUP BY 1
),
monthly AS (
    SELECT ms.month_start, COALESCE(c.n, 0) AS applications
    FROM months ms
    LEFT JOIN counts c ON c.m = ms.month_start
),
windowed AS (
    SELECT month_start, applications,
           ROW_NUMBER() OVER (ORDER BY month_start) AS rn,
           AVG(applications) OVER (ORDER BY month_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS ma3,
           LAG(applications, 12) OVER (ORDER BY month_start) AS prior_year
    FROM monthly
)
SELECT strftime('%Y-%m', month_start) AS month,
       applications,
       CASE WHEN rn >= 3 THEN ROUND(ma3, 2) END AS moving_avg_3m,
       prior_year AS same_month_last_year,
       CASE WHEN prior_year > 0 THEN ROUND(100.0 * (applications - prior_year) / prior_year, 2) END AS yoy_change_pct
FROM windowed
ORDER BY month_start;
