-- Title: Time to hire with p50 and p90 by team
-- Business question: From application to accepted offer, how many days does a typical hire take,
--   and how bad is the slow tail, for each team?
-- Tables: fact_offer, fact_application, dim_requisition
-- Technique: nearest-rank percentiles built from ROW_NUMBER() and COUNT() OVER (no percentile
--   function needed); an ALL row made by appending the data to itself with UNION ALL.
-- Edge cases: nearest rank = ceil(p*n/100), written as integer arithmetic (p*n+99)/100 so it is
--   portable; a team with one hire returns that hire for every percentile; pending or declined
--   offers are excluded because they have no accepted date.
WITH hire_days AS (
    SELECT r.team,
           CAST(ROUND(julianday(o.decided_date) - julianday(a.applied_at)) AS INTEGER) AS days
    FROM fact_offer o
    JOIN fact_application a ON a.application_id = o.application_id
    JOIN dim_requisition r  ON r.requisition_id = a.requisition_id
    WHERE o.status = 'accepted'
),
grouped AS (
    SELECT team, days FROM hire_days
    UNION ALL
    SELECT 'ALL', days FROM hire_days
),
ranked AS (
    SELECT team, days,
           ROW_NUMBER() OVER (PARTITION BY team ORDER BY days) AS rn,
           COUNT(*)     OVER (PARTITION BY team)               AS n
    FROM grouped
)
SELECT team,
       MAX(n)                                                AS hires,
       MIN(CASE WHEN rn = (50 * n + 99) / 100 THEN days END) AS p50_days,
       MIN(CASE WHEN rn = (90 * n + 99) / 100 THEN days END) AS p90_days,
       ROUND(AVG(days), 2)                                   AS mean_days,
       MAX(days)                                             AS max_days
FROM ranked
GROUP BY team
ORDER BY CASE WHEN team = 'ALL' THEN 0 ELSE 1 END, hires DESC, team;
