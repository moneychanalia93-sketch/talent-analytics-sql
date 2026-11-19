-- Title: Hiring funnel conversion by stage
-- Business question: How many applications reach each pipeline stage, and what share survives
--   from the previous stage and from the very first one?
-- Tables: dim_stage, fact_stage_event, fact_offer
-- Technique: GROUP BY over a reference table, UNION ALL for the final "accepted" step,
--   LAG and FIRST_VALUE window functions for step and cumulative conversion.
-- Edge cases: a stage nobody reached still appears (LEFT JOIN, count 0); division by a zero
--   previous count returns NULL through NULLIF instead of failing; applications that are
--   still in a stage count as having reached it.
WITH reached AS (
    SELECT s.stage_order, s.stage_name, COUNT(e.application_id) AS n
    FROM dim_stage s
    LEFT JOIN fact_stage_event e ON e.stage_order = s.stage_order
    GROUP BY s.stage_order, s.stage_name
    UNION ALL
    SELECT 6, 'Offer Accepted', COUNT(*) FROM fact_offer WHERE status = 'accepted'
)
SELECT stage_order,
       stage_name,
       n AS applications_reached,
       ROUND(100.0 * n / NULLIF(FIRST_VALUE(n) OVER (ORDER BY stage_order), 0), 2) AS pct_of_applied,
       ROUND(100.0 * n / NULLIF(LAG(n) OVER (ORDER BY stage_order), 0), 2)          AS pct_of_previous_stage
FROM reached
ORDER BY stage_order;
