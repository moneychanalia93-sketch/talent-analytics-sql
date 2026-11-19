-- Title: Manager attrition and team ratings (minimum 5 reports)
-- Business question: Which managers lose people at a clearly higher or lower rate than the company,
--   and what do their teams' performance ratings look like?
-- Tables: dim_employee, fact_performance_review
-- Technique: CTEs for per-employee ratings, per-manager roll-up with HAVING COUNT(*) >= 5, and a
--   company-wide benchmark joined in with CROSS JOIN; flags use ratios to the benchmark.
-- Edge cases: managers with fewer than 5 reports (ever) are not shown, since a rate on 2 people is
--   noise; attrition counts everyone who ever reported to the manager (manager_id is the last known
--   manager); employees with no review are left out of the rating average only.
WITH reports AS (
    SELECT employee_id, manager_id, term_date FROM dim_employee WHERE manager_id IS NOT NULL
),
ratings AS (
    SELECT employee_id, AVG(rating) AS avg_rating FROM fact_performance_review GROUP BY employee_id
),
benchmark AS (
    SELECT 1.0 * SUM(CASE WHEN term_date IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*) AS org_rate FROM reports
),
mgr AS (
    SELECT r.manager_id,
           COUNT(*) AS reports_ever,
           SUM(CASE WHEN r.term_date IS NOT NULL THEN 1 ELSE 0 END) AS left_count,
           AVG(t.avg_rating) AS avg_report_rating
    FROM reports r
    LEFT JOIN ratings t ON t.employee_id = r.employee_id
    GROUP BY r.manager_id
    HAVING COUNT(*) >= 5
)
SELECT m.manager_id, e.full_name, e.team, e.level,
       m.reports_ever, m.left_count,
       ROUND(100.0 * m.left_count / m.reports_ever, 2) AS attrition_pct,
       ROUND(100.0 * b.org_rate, 2)                    AS company_attrition_pct,
       ROUND(m.avg_report_rating, 2)                   AS avg_report_rating,
       CASE WHEN 1.0 * m.left_count / m.reports_ever > 1.5 * b.org_rate THEN 'high attrition'
            WHEN 1.0 * m.left_count / m.reports_ever < 0.5 * b.org_rate THEN 'low attrition'
            ELSE 'in range' END AS flag
FROM mgr m
JOIN dim_employee e ON e.employee_id = m.manager_id
CROSS JOIN benchmark b
ORDER BY attrition_pct DESC, m.manager_id;
