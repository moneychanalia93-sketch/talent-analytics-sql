-- Title: Offer acceptance rate by team with a confidence interval
-- Business question: What share of decided offers does each team win, and is the sample big
--   enough to trust the number?
-- Tables: fact_offer, fact_application, dim_requisition
-- Technique: conditional aggregation plus the Wilson 95% score interval computed in SQL
--   (SQRT is a standard math function; see README for the SQLite build note).
-- Edge cases: pending offers are not decided and are excluded; the caveat column flags teams
--   with fewer than 30 decided offers; the Wilson interval stays inside 0-100% even at 0 or n
--   successes, unlike the simple normal approximation.
WITH decided AS (
    SELECT r.team,
           COUNT(*) AS n,
           SUM(CASE WHEN o.status = 'accepted' THEN 1 ELSE 0 END) AS accepted
    FROM fact_offer o
    JOIN fact_application a ON a.application_id = o.application_id
    JOIN dim_requisition r  ON r.requisition_id = a.requisition_id
    WHERE o.status IN ('accepted', 'declined', 'expired')
    GROUP BY r.team
),
stats AS (
    SELECT team, n, accepted,
           1.0 * accepted / n AS p,
           1.96 * 1.96        AS z2
    FROM decided
)
SELECT team,
       n AS decided_offers,
       accepted,
       ROUND(100.0 * p, 2) AS acceptance_pct,
       ROUND(100.0 * ((p + z2 / (2 * n)) - 1.96 * SQRT(p * (1 - p) / n + z2 / (4.0 * n * n))) / (1 + z2 / n), 2) AS ci95_low_pct,
       ROUND(100.0 * ((p + z2 / (2 * n)) + 1.96 * SQRT(p * (1 - p) / n + z2 / (4.0 * n * n))) / (1 + z2 / n), 2) AS ci95_high_pct,
       CASE WHEN n < 30 THEN 'low sample (n<30): treat as indicative only' ELSE 'ok' END AS caveat
FROM stats
ORDER BY acceptance_pct DESC, team;
