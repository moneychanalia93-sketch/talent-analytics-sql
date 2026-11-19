-- Title: Four-fifths adverse-impact check at each stage
-- Business question: At every screening decision, is any group advanced at less than 80% of the
--   rate of the best-treated group?
-- Tables: fact_stage_event, fact_application, dim_candidate
-- Technique: selection rate per group, MAX() OVER (PARTITION BY dimension, stage) for the benchmark
--   group, impact ratio = group rate / best rate, flag below 0.80 (the EEOC four-fifths rule of thumb).
-- Edge cases: only decided outcomes count (advanced or rejected); withdrawals and in-progress stages
--   are not selection decisions; a group needs at least 10 decisions to be scored and to be
--   used as the benchmark, otherwise the row says 'insufficient data'; the rule is a screening
--   heuristic, not proof of discrimination, and says nothing about causes.
WITH params AS (SELECT 10 AS min_considered, 0.8 AS threshold),
decisions AS (
    SELECT e.stage_order AS from_stage, e.outcome, c.gender, c.demographic_group
    FROM fact_stage_event e
    JOIN fact_application a ON a.application_id = e.application_id
    JOIN dim_candidate c    ON c.candidate_id = a.candidate_id
    WHERE e.stage_order BETWEEN 1 AND 4
      AND e.outcome IN ('advanced', 'rejected')
),
by_group AS (
    SELECT 'gender' AS dimension, gender AS grp, from_stage,
           COUNT(*) AS considered,
           SUM(CASE WHEN outcome = 'advanced' THEN 1 ELSE 0 END) AS selected
    FROM decisions GROUP BY gender, from_stage
    UNION ALL
    SELECT 'demographic_group', demographic_group, from_stage,
           COUNT(*),
           SUM(CASE WHEN outcome = 'advanced' THEN 1 ELSE 0 END)
    FROM decisions GROUP BY demographic_group, from_stage
),
scored AS (
    SELECT g.*, p.min_considered, p.threshold,
           1.0 * g.selected / g.considered AS rate,
           MAX(CASE WHEN g.considered >= p.min_considered THEN 1.0 * g.selected / g.considered END)
               OVER (PARTITION BY g.dimension, g.from_stage) AS best_rate
    FROM by_group g
    CROSS JOIN params p
)
SELECT s.dimension,
       s.grp AS group_value,
       d.stage_name AS decision_at,
       s.considered,
       s.selected,
       ROUND(100.0 * s.rate, 2)      AS selection_rate_pct,
       ROUND(100.0 * s.best_rate, 2) AS best_group_rate_pct,
       ROUND(s.rate / NULLIF(s.best_rate, 0), 3) AS impact_ratio,
       CASE WHEN s.considered < s.min_considered THEN 'insufficient data'
            WHEN s.best_rate IS NULL OR s.best_rate = 0 THEN 'n/a'
            WHEN s.rate / s.best_rate < s.threshold THEN 'ADVERSE IMPACT (ratio < 0.80)'
            ELSE 'pass' END AS four_fifths_flag
FROM scored s
JOIN dim_stage d ON d.stage_order = s.from_stage
ORDER BY s.dimension, s.from_stage, s.grp;
