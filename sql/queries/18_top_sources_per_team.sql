-- Title: Top 3 hiring sources per team
-- Business question: For each team, which three channels produce the most hires, and how
--   concentrated is hiring in them?
-- Tables: fact_offer, fact_application, dim_requisition
-- Technique: top-N per group with ROW_NUMBER() OVER (PARTITION BY team ORDER BY hires DESC, source),
--   filtered in an outer query; a SUM() OVER (PARTITION BY team) gives each team's total for the share.
-- Edge cases: ties are broken alphabetically so the result is stable (use RANK instead to keep ties);
--   a team with fewer than three sources returns fewer rows; the share is of ALL the team's hires,
--   not of the top three.
WITH hires AS (
    SELECT r.team, a.source, COUNT(*) AS hires
    FROM fact_offer o
    JOIN fact_application a ON a.application_id = o.application_id
    JOIN dim_requisition r  ON r.requisition_id = a.requisition_id
    WHERE o.status = 'accepted'
    GROUP BY r.team, a.source
),
ranked AS (
    SELECT team, source, hires,
           ROW_NUMBER() OVER (PARTITION BY team ORDER BY hires DESC, source) AS rn,
           SUM(hires)   OVER (PARTITION BY team)                             AS team_hires
    FROM hires
)
SELECT team, rn AS source_rank, source, hires,
       ROUND(100.0 * hires / team_hires, 2) AS share_of_team_hires_pct
FROM ranked
WHERE rn <= 3
ORDER BY team, rn;
