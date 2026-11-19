-- Title: Stage dwell and hand-off times (LAG / LEAD)
-- Business question: How long do candidates sit in each stage, and how long do they wait between
--   one stage ending and the next one starting?
-- Tables: fact_stage_event, dim_stage
-- Technique: LAG(exited_at) and LEAD(entered_at) over each application's stages, computed in a CTE
--   BEFORE filtering so neighbouring rows are still visible; then averaged per stage.
-- Edge cases: stage 1 has no previous stage, so its wait-before is NULL and excluded from the
--   average; the last stage an application reached has no next stage, so it is excluded from the
--   average of days-to-next-entry; open stages have no exit date and are excluded from dwell.
WITH seq AS (
    SELECT application_id, stage_order, entered_at, exited_at,
           LAG(exited_at)   OVER (PARTITION BY application_id ORDER BY stage_order) AS prev_exit,
           LEAD(entered_at) OVER (PARTITION BY application_id ORDER BY stage_order) AS next_entry
    FROM fact_stage_event
)
SELECT d.stage_order,
       d.stage_name,
       COUNT(*) AS completed_stages,
       ROUND(AVG(julianday(s.exited_at) - julianday(s.entered_at)), 2)   AS avg_dwell_days,
       ROUND(AVG(julianday(s.entered_at) - julianday(s.prev_exit)), 2)   AS avg_wait_before_days,
       ROUND(AVG(julianday(s.next_entry) - julianday(s.entered_at)), 2)  AS avg_days_to_next_stage_entry,
       CAST(ROUND(MAX(julianday(s.exited_at) - julianday(s.entered_at))) AS INTEGER) AS longest_dwell_days
FROM seq s
JOIN dim_stage d ON d.stage_order = s.stage_order
WHERE s.exited_at IS NOT NULL
GROUP BY d.stage_order, d.stage_name
ORDER BY d.stage_order;
