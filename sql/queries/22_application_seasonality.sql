-- Title: Application seasonality index
-- Business question: Which calendar months are busy for applications, relative to an average month?
-- Tables: fact_application, dim_date
-- Technique: two-level aggregation (count per year-month, then average per calendar month), and an
--   empty-frame window AVG() OVER () to compare each month with the average of all months.
-- Edge cases: months are averaged over the years in which they appear (years_observed shows how
--   many), so partial years do not bias the average toward zero; an index of 1.000 is an average month.
WITH monthly AS (
    SELECT d.year, d.month, COUNT(*) AS apps
    FROM fact_application a
    JOIN dim_date d ON d.full_date = a.applied_at
    GROUP BY d.year, d.month
),
by_month AS (
    SELECT month, COUNT(*) AS years_observed, SUM(apps) AS total_apps, AVG(apps) AS avg_apps
    FROM monthly
    GROUP BY month
)
SELECT month AS calendar_month,
       years_observed,
       total_apps,
       ROUND(avg_apps, 1) AS avg_apps_per_year,
       ROUND(avg_apps / AVG(avg_apps) OVER (), 3) AS seasonal_index
FROM by_month
ORDER BY month;
