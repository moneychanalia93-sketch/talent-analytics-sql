-- Title: Headcount rollup per manager subtree
-- Business question: For every manager, how many people sit anywhere below them, how many report
--   directly, and how many layers deep does their organisation go?
-- Tables: dim_employee
-- Technique: RECURSIVE CTE that climbs from every current employee up to each ancestor (a closure
--   table built on the fly), then GROUP BY ancestor to roll counts up the tree.
-- Edge cases: loops in manager_id are cut with a path check (a person is never their own ancestor);
--   depth is capped at 30; only current employees are counted as members, and only current
--   employees are listed as managers; managers with no reports do not appear.
WITH RECURSIVE chain(emp_id, ancestor_id, depth, path) AS (
    SELECT employee_id, manager_id, 1, '/' || employee_id || '/' || manager_id || '/'
    FROM dim_employee
    WHERE manager_id IS NOT NULL AND term_date IS NULL
    UNION ALL
    SELECT c.emp_id, e.manager_id, c.depth + 1, c.path || e.manager_id || '/'
    FROM chain c
    JOIN dim_employee e ON e.employee_id = c.ancestor_id
    WHERE e.manager_id IS NOT NULL
      AND c.depth < 30
      AND instr(c.path, '/' || e.manager_id || '/') = 0
),
active AS (SELECT COUNT(*) AS n FROM dim_employee WHERE term_date IS NULL)
SELECT m.employee_id AS manager_id,
       m.full_name,
       m.team,
       m.level,
       SUM(CASE WHEN c.depth = 1 THEN 1 ELSE 0 END) AS direct_reports,
       COUNT(*)                                     AS total_org_size,
       MAX(c.depth)                                 AS layers_below,
       ROUND(100.0 * COUNT(*) / a.n, 2)             AS pct_of_company
FROM chain c
JOIN dim_employee m ON m.employee_id = c.ancestor_id
CROSS JOIN active a
WHERE m.term_date IS NULL
GROUP BY m.employee_id, m.full_name, m.team, m.level, a.n
ORDER BY total_org_size DESC, manager_id;
