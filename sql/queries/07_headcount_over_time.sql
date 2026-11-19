-- Title: Monthly headcount with running totals and trailing attrition
-- Business question: How did headcount move month by month, and what is the trailing
--   12-month attrition rate?
-- Tables: dim_employee, meta
-- Technique: RECURSIVE CTE as a date spine (one row per month, no calendar table needed),
--   running total with SUM() OVER (ROWS UNBOUNDED PRECEDING), trailing sums and averages with
--   ROWS BETWEEN 11 PRECEDING AND CURRENT ROW.
-- Edge cases: months with no hires or exits still appear (spine LEFT JOINed, COALESCE to 0);
--   a person leaving in a month is out of that month's ending headcount; attrition is only shown
--   once a full 12-month window exists; the recursion stops at the as-of month.
WITH RECURSIVE
params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
bounds AS (
    SELECT date(MIN(e.hire_date), 'start of month') AS first_m,
           date(p.as_of, 'start of month')          AS last_m
    FROM dim_employee e, params p
),
spine(month_start) AS (
    SELECT first_m FROM bounds
    UNION ALL
    SELECT date(s.month_start, '+1 month') FROM spine s, bounds b WHERE s.month_start < b.last_m
),
hires AS (
    SELECT date(hire_date, 'start of month') AS m, COUNT(*) AS n FROM dim_employee GROUP BY 1
),
terms AS (
    SELECT date(term_date, 'start of month') AS m, COUNT(*) AS n
    FROM dim_employee WHERE term_date IS NOT NULL GROUP BY 1
),
monthly AS (
    SELECT s.month_start, COALESCE(h.n, 0) AS hires, COALESCE(t.n, 0) AS terms
    FROM spine s
    LEFT JOIN hires h ON h.m = s.month_start
    LEFT JOIN terms t ON t.m = s.month_start
),
running AS (
    SELECT month_start, hires, terms,
           SUM(hires - terms) OVER (ORDER BY month_start ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ending_headcount,
           SUM(terms)         OVER (ORDER BY month_start ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)       AS terms_12m,
           ROW_NUMBER()       OVER (ORDER BY month_start)                                                 AS rn
    FROM monthly
),
windowed AS (
    SELECT *, AVG(ending_headcount) OVER (ORDER BY month_start ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS avg_headcount_12m
    FROM running
)
SELECT strftime('%Y-%m', month_start) AS month,
       hires,
       terms,
       hires - terms                  AS net_change,
       ending_headcount,
       CASE WHEN rn >= 12 THEN ROUND(100.0 * terms_12m / NULLIF(avg_headcount_12m, 0), 2) END AS trailing_12m_attrition_pct
FROM windowed
ORDER BY month_start;
