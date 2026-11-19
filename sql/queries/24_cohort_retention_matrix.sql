-- Title: Cohort retention matrix by hire quarter
-- Business question: Of the people hired in each quarter, what share is still employed 3, 6, 12, 18
--   and 24 months (90/180/365/545/730 days) after their start?
-- Tables: dim_employee, meta
-- Technique: cohort analysis. Cohort label from the hire date, then one conditional-aggregation column
--   per checkpoint; each column divides retained people by the people old enough to be measured.
-- Edge cases: a person is only measured at a checkpoint if that many days have passed before the
--   as-of date, so young cohorts show NULL in later columns instead of a misleading 100%; "retained"
--   means no termination on or before the checkpoint day; terminations after it do not matter.
WITH params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
people AS (
    SELECT strftime('%Y', e.hire_date) || '-Q' || ((CAST(strftime('%m', e.hire_date) AS INTEGER) + 2) / 3) AS cohort,
           e.hire_date, e.term_date, p.as_of
    FROM dim_employee e CROSS JOIN params p
)
SELECT cohort,
       COUNT(*) AS cohort_size,
       ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-90 days')  AND (term_date IS NULL OR term_date > date(hire_date, '+90 days'))  THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-90 days')  THEN 1 ELSE 0 END), 0), 1) AS ret_3m_pct,
       ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-180 days') AND (term_date IS NULL OR term_date > date(hire_date, '+180 days')) THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-180 days') THEN 1 ELSE 0 END), 0), 1) AS ret_6m_pct,
       ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-365 days') AND (term_date IS NULL OR term_date > date(hire_date, '+365 days')) THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-365 days') THEN 1 ELSE 0 END), 0), 1) AS ret_12m_pct,
       ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-545 days') AND (term_date IS NULL OR term_date > date(hire_date, '+545 days')) THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-545 days') THEN 1 ELSE 0 END), 0), 1) AS ret_18m_pct,
       ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-730 days') AND (term_date IS NULL OR term_date > date(hire_date, '+730 days')) THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-730 days') THEN 1 ELSE 0 END), 0), 1) AS ret_24m_pct
FROM people
GROUP BY cohort
ORDER BY cohort;
