-- Title: Requisition outcomes and time to fill by team
-- Business question: What share of closed requisitions get filled rather than cancelled, and how
--   long do the filled ones take?
-- Tables: dim_requisition
-- Technique: conditional aggregation over status, date arithmetic with julianday, rates that use
--   only closed requisitions as the denominator.
-- Edge cases: open requisitions are counted but excluded from the fill rate (they have no outcome yet);
--   days-to-fill averages filled requisitions only; a team with no closed requisitions gets a NULL rate.
SELECT team,
       COUNT(*) AS requisitions,
       SUM(CASE WHEN status = 'filled'    THEN 1 ELSE 0 END) AS filled,
       SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
       SUM(CASE WHEN status = 'open'      THEN 1 ELSE 0 END) AS still_open,
       ROUND(100.0 * SUM(CASE WHEN status = 'filled' THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN status IN ('filled', 'cancelled') THEN 1 ELSE 0 END), 0), 2) AS fill_rate_pct,
       ROUND(AVG(CASE WHEN status = 'filled' THEN julianday(closed_date) - julianday(opened_date) END), 1) AS avg_days_to_fill
FROM dim_requisition
GROUP BY team
ORDER BY fill_rate_pct DESC, team;
