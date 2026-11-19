-- Title: Org tree with depth and path (recursive)
-- Business question: What does the current reporting structure look like, from the top, and
--   how deep is each person?
-- Tables: dim_employee
-- Technique: RECURSIVE CTE walking manager -> report, carrying depth and a '/id/id/' path string;
--   the path doubles as the sort key for a depth-first outline.
-- Edge cases: only current employees are walked; the root is the employee with no manager; a
--   reporting loop is cut by refusing to revisit an id already on the path, and a hard depth cap
--   of 25 stops runaway data; people unreachable from the root (for example, inside a loop) are
--   simply absent and are reported by the data-quality query 21.
WITH RECURSIVE tree(employee_id, depth, path) AS (
    SELECT employee_id, 0, '/' || employee_id || '/'
    FROM dim_employee
    WHERE manager_id IS NULL AND term_date IS NULL
    UNION ALL
    SELECT e.employee_id, t.depth + 1, t.path || e.employee_id || '/'
    FROM dim_employee e
    JOIN tree t ON e.manager_id = t.employee_id
    WHERE e.term_date IS NULL
      AND t.depth < 25
      AND instr(t.path, '/' || e.employee_id || '/') = 0
)
SELECT t.employee_id,
       replace(hex(zeroblob(t.depth)), '00', '  ') || e.full_name AS org_chart,
       e.team,
       e.level,
       t.depth,
       t.path
FROM tree t
JOIN dim_employee e ON e.employee_id = t.employee_id
ORDER BY t.path;
