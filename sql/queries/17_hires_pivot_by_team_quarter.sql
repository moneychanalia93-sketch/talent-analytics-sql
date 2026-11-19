-- Title: Pipeline hires pivoted by team and calendar quarter
-- Business question: In which part of the year does each team do its hiring?
-- Tables: dim_employee, dim_date
-- Technique: pivot by conditional aggregation (SUM(CASE WHEN quarter = n ...)) after joining the date
--   dimension, so quarter comes from dim_date rather than string maths.
-- Edge cases: only employees hired through the pipeline (source_application_id not null) are counted;
--   quarters are calendar quarters pooled across all years; a team with no hires in a quarter shows 0.
SELECT e.team,
       SUM(CASE WHEN d.quarter = 1 THEN 1 ELSE 0 END) AS q1,
       SUM(CASE WHEN d.quarter = 2 THEN 1 ELSE 0 END) AS q2,
       SUM(CASE WHEN d.quarter = 3 THEN 1 ELSE 0 END) AS q3,
       SUM(CASE WHEN d.quarter = 4 THEN 1 ELSE 0 END) AS q4,
       COUNT(*) AS total_hires,
       ROUND(100.0 * SUM(CASE WHEN d.quarter = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_in_q1
FROM dim_employee e
JOIN dim_date d ON d.full_date = e.hire_date
WHERE e.source_application_id IS NOT NULL
GROUP BY e.team
ORDER BY total_hires DESC, e.team;
