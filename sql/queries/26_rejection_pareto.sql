-- Title: Where candidates are rejected (Pareto)
-- Business question: Which stages account for most rejections, and how fast does the cumulative
--   share build up?
-- Tables: dim_stage, fact_stage_event
-- Technique: Pareto table with a running SUM() OVER (ORDER BY count DESC ROWS UNBOUNDED PRECEDING)
--   divided by a grand total SUM() OVER ().
-- Edge cases: a stage with no rejections still appears with 0; ties on the count are ordered by stage
--   so the running total is deterministic; withdrawals are shown but are not rejections and are left
--   out of the percentages; if there are no rejections at all the shares are NULL.
WITH per_stage AS (
    SELECT s.stage_order, s.stage_name,
           SUM(CASE WHEN e.outcome = 'rejected'  THEN 1 ELSE 0 END) AS rejected,
           SUM(CASE WHEN e.outcome = 'withdrawn' THEN 1 ELSE 0 END) AS withdrawn
    FROM dim_stage s
    LEFT JOIN fact_stage_event e ON e.stage_order = s.stage_order
    GROUP BY s.stage_order, s.stage_name
)
SELECT stage_name, rejected, withdrawn,
       ROUND(100.0 * rejected / NULLIF(SUM(rejected) OVER (), 0), 2) AS share_of_rejections_pct,
       ROUND(100.0 * SUM(rejected) OVER (ORDER BY rejected DESC, stage_order
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / NULLIF(SUM(rejected) OVER (), 0), 2) AS cumulative_pct
FROM per_stage
ORDER BY rejected DESC, stage_order;
