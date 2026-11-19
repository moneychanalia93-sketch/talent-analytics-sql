-- Title: Compa-ratio outliers within level and location
-- Business question: Which current employees are paid well below or above their peers
--   (same level, same location)?
-- Tables: dim_employee, fact_compensation_snapshot
-- Technique: latest salary with ROW_NUMBER(); peer average, peer count and PERCENT_RANK() as window
--   functions with PARTITION BY level, location; filter on the window results in an outer query.
-- Edge cases: peer groups smaller than 5 are skipped (an average of two people is not a benchmark);
--   compa-ratio = own pay / peer average, flagged below 0.85 or above 1.15; the peer average includes
--   the employee, so a very large outlier pulls its own benchmark; team and tenure are not controlled.
WITH latest AS (
    SELECT employee_id, base_salary,
           ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) AS rn
    FROM fact_compensation_snapshot
),
cur AS (
    SELECT e.employee_id, e.full_name, e.team, e.level, e.location, l.base_salary
    FROM dim_employee e
    JOIN latest l ON l.employee_id = e.employee_id AND l.rn = 1
    WHERE e.term_date IS NULL
),
peers AS (
    SELECT *,
           COUNT(*)       OVER (PARTITION BY level, location) AS peer_n,
           AVG(base_salary) OVER (PARTITION BY level, location) AS peer_avg,
           PERCENT_RANK() OVER (PARTITION BY level, location ORDER BY base_salary) AS pct_rank
    FROM cur
)
SELECT employee_id, full_name, team, level, location, base_salary, peer_n,
       ROUND(peer_avg, 0)                    AS peer_avg_salary,
       ROUND(base_salary / peer_avg, 3)      AS compa_ratio,
       ROUND(100.0 * pct_rank, 1)            AS percentile_in_peer_group,
       CASE WHEN base_salary / peer_avg < 0.85 THEN 'below range' ELSE 'above range' END AS flag
FROM peers
WHERE peer_n >= 5
  AND (base_salary / peer_avg < 0.85 OR base_salary / peer_avg > 1.15)
ORDER BY ABS(base_salary / peer_avg - 1) DESC, employee_id;
