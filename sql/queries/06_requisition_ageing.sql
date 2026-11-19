-- Title: Open requisition ageing buckets
-- Business question: How old are our open requisitions, and which teams carry the stale ones?
-- Tables: dim_requisition, meta
-- Technique: CASE bucketing with conditional aggregation (a pivot); the as-of date is read from
--   meta so results are repeatable instead of depending on today's date.
-- Edge cases: only status = 'open' rows count; a requisition opened on the as-of date has age 0 and
--   lands in the first bucket; teams without open requisitions do not appear.
WITH params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
aged AS (
    SELECT r.team,
           CAST(ROUND(julianday(p.as_of) - julianday(r.opened_date)) AS INTEGER) AS age_days
    FROM dim_requisition r, params p
    WHERE r.status = 'open'
)
SELECT team,
       COUNT(*)                                                     AS open_reqs,
       SUM(CASE WHEN age_days <= 30 THEN 1 ELSE 0 END)              AS d0_30,
       SUM(CASE WHEN age_days BETWEEN 31 AND 60 THEN 1 ELSE 0 END)  AS d31_60,
       SUM(CASE WHEN age_days BETWEEN 61 AND 90 THEN 1 ELSE 0 END)  AS d61_90,
       SUM(CASE WHEN age_days BETWEEN 91 AND 180 THEN 1 ELSE 0 END) AS d91_180,
       SUM(CASE WHEN age_days > 180 THEN 1 ELSE 0 END)              AS d181_plus,
       ROUND(AVG(age_days), 1)                                      AS avg_age_days,
       MAX(age_days)                                                AS oldest_days
FROM aged
GROUP BY team
ORDER BY d181_plus DESC, open_reqs DESC, team;
