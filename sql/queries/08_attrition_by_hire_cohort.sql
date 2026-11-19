-- Title: Attrition and tenure by hire-year cohort
-- Business question: For each year's hires, how many have left, how (voluntary or not),
--   and how long did the leavers stay?
-- Tables: dim_employee
-- Technique: cohort grouping by hire year, conditional aggregation, tenure arithmetic with julianday.
-- Edge cases: tenure is averaged over leavers only (people still employed have no exit date);
--   cohorts with no leavers show NULL average tenure rather than 0; attrition is cumulative since
--   hire, so older cohorts naturally look worse (see query 24 for age-matched retention).
SELECT strftime('%Y', hire_date)                                            AS cohort_year,
       COUNT(*)                                                             AS hires,
       SUM(CASE WHEN term_date IS NOT NULL THEN 1 ELSE 0 END)               AS leavers,
       SUM(CASE WHEN term_reason = 'voluntary' THEN 1 ELSE 0 END)           AS voluntary,
       SUM(CASE WHEN term_reason = 'involuntary' THEN 1 ELSE 0 END)         AS involuntary,
       ROUND(100.0 * SUM(CASE WHEN term_date IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS cumulative_attrition_pct,
       ROUND(AVG(CASE WHEN term_date IS NOT NULL THEN julianday(term_date) - julianday(hire_date) END), 1) AS avg_tenure_days_leavers,
       SUM(CASE WHEN term_date IS NOT NULL AND julianday(term_date) - julianday(hire_date) <= 90 THEN 1 ELSE 0 END) AS left_within_90_days
FROM dim_employee
GROUP BY strftime('%Y', hire_date)
ORDER BY cohort_year;
