-- Title: Manager span of control by level
-- Business question: How many direct reports do managers at each level carry, and how many are
--   outside a healthy 3-8 range?
-- Tables: dim_employee
-- Technique: two-step aggregation (reports per manager, then per level), UNION ALL for a total row,
--   a hidden sort key so the total row sorts last.
-- Edge cases: only current employees reporting to a current manager are counted; people with no
--   reports are not managers and are not in the denominator; the range 3-8 is a rule of thumb, not
--   a standard.
WITH span AS (
    SELECT m.employee_id, m.level, COUNT(*) AS reports
    FROM dim_employee e
    JOIN dim_employee m ON m.employee_id = e.manager_id
    WHERE e.term_date IS NULL AND m.term_date IS NULL
    GROUP BY m.employee_id, m.level
),
by_level AS (
    SELECT CAST(level AS TEXT) AS manager_level, level AS sort_key,
           COUNT(*) AS managers, SUM(reports) AS total_reports,
           ROUND(AVG(reports), 2) AS avg_span, MIN(reports) AS min_span, MAX(reports) AS max_span,
           SUM(CASE WHEN reports > 8 THEN 1 ELSE 0 END) AS over_8,
           SUM(CASE WHEN reports < 3 THEN 1 ELSE 0 END) AS under_3
    FROM span
    GROUP BY level
    UNION ALL
    SELECT 'ALL', 99, COUNT(*), SUM(reports), ROUND(AVG(reports), 2), MIN(reports), MAX(reports),
           SUM(CASE WHEN reports > 8 THEN 1 ELSE 0 END), SUM(CASE WHEN reports < 3 THEN 1 ELSE 0 END)
    FROM span
)
SELECT manager_level, managers, total_reports, avg_span, min_span, max_span, over_8, under_3
FROM by_level
ORDER BY sort_key;
