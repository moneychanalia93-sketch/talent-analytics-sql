-- Title: Hiring quality by source
-- Business question: Do some sourcing channels bring people who perform better and stay longer?
-- Tables: dim_employee, fact_application, fact_performance_review, meta
-- Technique: join employees back to the application that hired them (source_application_id),
--   per-employee CTEs first so every employee counts once, then aggregate by source.
-- Edge cases: only people hired through the pipeline have a source (earlier staff are excluded);
--   employees with no review yet are excluded from rating averages but kept in retention; 12-month
--   retention only counts people hired at least 365 days before the as-of date; the caveat column
--   warns when fewer than 30 hires have a rating.
WITH params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
hires AS (
    SELECT e.employee_id, a.source, e.hire_date, e.term_date
    FROM dim_employee e
    JOIN fact_application a ON a.application_id = e.source_application_id
),
emp_rating AS (
    SELECT employee_id, AVG(rating) AS avg_rating FROM fact_performance_review GROUP BY employee_id
),
flags AS (
    SELECT h.source, h.employee_id, r.avg_rating,
           CASE WHEN h.hire_date <= date(p.as_of, '-365 days') THEN 1 ELSE 0 END AS eligible,
           CASE WHEN h.hire_date <= date(p.as_of, '-365 days')
                 AND (h.term_date IS NULL OR h.term_date > date(h.hire_date, '+365 days'))
                THEN 1 ELSE 0 END AS retained
    FROM hires h
    CROSS JOIN params p
    LEFT JOIN emp_rating r ON r.employee_id = h.employee_id
)
SELECT source,
       COUNT(*)                       AS hires,
       COUNT(avg_rating)              AS rated_hires,
       ROUND(AVG(avg_rating), 2)      AS avg_rating,
       ROUND(100.0 * SUM(CASE WHEN avg_rating >= 4 THEN 1 ELSE 0 END) / NULLIF(COUNT(avg_rating), 0), 2) AS pct_rated_4_plus,
       SUM(eligible)                  AS eligible_12m,
       SUM(retained)                  AS retained_12m,
       ROUND(100.0 * SUM(retained) / NULLIF(SUM(eligible), 0), 2) AS retention_12m_pct,
       CASE WHEN COUNT(avg_rating) < 30 THEN 'small sample (<30 rated)' ELSE 'ok' END AS caveat
FROM flags
GROUP BY source
ORDER BY avg_rating DESC, source;
