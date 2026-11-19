-- Title: Open pipeline snapshot with stale-candidate counts
-- Business question: Right now, how many candidates are waiting in each stage and how many have
--   waited too long?
-- Tables: dim_stage, fact_stage_event, meta
-- Technique: filter on outcome = 'open', age against the as-of date from meta, LEFT JOIN from the
--   stage dimension so empty stages still show, conditional aggregation for the stale counts.
-- Edge cases: stages with nobody waiting show 0 and NULL averages; "stale" thresholds are 14 and 30
--   days, a choice made for this demo; only the stage an application is currently in counts.
WITH params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
waiting AS (
    SELECT e.stage_order,
           CAST(ROUND(julianday(p.as_of) - julianday(e.entered_at)) AS INTEGER) AS days_waiting
    FROM fact_stage_event e CROSS JOIN params p
    WHERE e.outcome = 'open'
)
SELECT s.stage_order, s.stage_name,
       COUNT(w.days_waiting)                                   AS open_applications,
       ROUND(AVG(w.days_waiting), 1)                           AS avg_days_waiting,
       MAX(w.days_waiting)                                     AS longest_wait_days,
       SUM(CASE WHEN w.days_waiting > 14 THEN 1 ELSE 0 END)    AS over_14_days,
       SUM(CASE WHEN w.days_waiting > 30 THEN 1 ELSE 0 END)    AS over_30_days
FROM dim_stage s
LEFT JOIN waiting w ON w.stage_order = s.stage_order
GROUP BY s.stage_order, s.stage_name
ORDER BY s.stage_order;
