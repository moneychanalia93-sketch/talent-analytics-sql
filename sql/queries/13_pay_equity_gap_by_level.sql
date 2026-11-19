-- Title: Pay-equity gap by level with small-cell suppression
-- Business question: Among current employees, how does average base pay for women compare with men
--   at each level, without publishing any cell small enough to identify a person?
-- Tables: dim_employee, fact_compensation_snapshot
-- Technique: latest snapshot per employee with ROW_NUMBER() OVER (PARTITION BY ... ORDER BY date DESC),
--   conditional aggregation, and k-anonymity style suppression (min_n = 5) done in SQL so a
--   suppressed cell returns NULL statistics, never the number.
-- Edge cases: any cell with fewer than 5 people shows only '<5' for its size and NULL for its pay;
--   the gap is published only when both sides pass the threshold; gender X is left out of the gap
--   (cells are too small to publish); this is an UNADJUSTED gap, not a controlled regression.
WITH params AS (SELECT 5 AS min_n),
latest AS (
    SELECT c.employee_id, c.base_salary,
           ROW_NUMBER() OVER (PARTITION BY c.employee_id ORDER BY c.effective_date DESC) AS rn
    FROM fact_compensation_snapshot c
),
current_pay AS (
    SELECT e.level, e.gender, l.base_salary
    FROM dim_employee e
    JOIN latest l ON l.employee_id = e.employee_id AND l.rn = 1
    WHERE e.term_date IS NULL AND e.gender IN ('F', 'M')
),
cells AS (
    SELECT level,
           SUM(CASE WHEN gender = 'F' THEN 1 ELSE 0 END)      AS n_women,
           SUM(CASE WHEN gender = 'M' THEN 1 ELSE 0 END)      AS n_men,
           AVG(CASE WHEN gender = 'F' THEN base_salary END)   AS avg_women,
           AVG(CASE WHEN gender = 'M' THEN base_salary END)   AS avg_men
    FROM current_pay
    GROUP BY level
)
SELECT c.level,
       CASE WHEN c.n_women < p.min_n THEN '<' || p.min_n ELSE CAST(c.n_women AS TEXT) END AS women_n,
       CASE WHEN c.n_men   < p.min_n THEN '<' || p.min_n ELSE CAST(c.n_men AS TEXT) END   AS men_n,
       CASE WHEN c.n_women >= p.min_n THEN ROUND(c.avg_women, 0) END AS avg_base_women,
       CASE WHEN c.n_men   >= p.min_n THEN ROUND(c.avg_men, 0) END   AS avg_base_men,
       CASE WHEN c.n_women >= p.min_n AND c.n_men >= p.min_n
            THEN ROUND(100.0 * (c.avg_women - c.avg_men) / c.avg_men, 2) END AS gap_pct_women_vs_men,
       CASE WHEN c.n_women >= p.min_n AND c.n_men >= p.min_n THEN 'published'
            ELSE 'suppressed: fewer than ' || p.min_n || ' people in a cell' END AS note
FROM cells c
CROSS JOIN params p
ORDER BY c.level;
