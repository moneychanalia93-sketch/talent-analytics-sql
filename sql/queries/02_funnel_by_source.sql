-- Title: Funnel conversion by application source
-- Business question: Which sourcing channels turn applications into hires, and where does each lose people?
-- Tables: fact_application, fact_stage_event, fact_offer
-- Technique: per-application CTE (highest stage reached), then conditional aggregation
--   SUM(CASE ...) to pivot the stages into columns.
-- Edge cases: every application has a stage-1 event, so an inner join to events loses nothing;
--   LEFT JOIN to fact_offer keeps applications with no offer; rates use NULLIF to avoid dividing by zero.
WITH app_depth AS (
    SELECT a.application_id, a.source, MAX(e.stage_order) AS max_stage
    FROM fact_application a
    JOIN fact_stage_event e ON e.application_id = a.application_id
    GROUP BY a.application_id, a.source
)
SELECT d.source,
       COUNT(*)                                          AS applications,
       SUM(CASE WHEN d.max_stage >= 2 THEN 1 ELSE 0 END) AS recruiter_screens,
       SUM(CASE WHEN d.max_stage >= 3 THEN 1 ELSE 0 END) AS manager_screens,
       SUM(CASE WHEN d.max_stage >= 4 THEN 1 ELSE 0 END) AS onsites,
       SUM(CASE WHEN d.max_stage >= 5 THEN 1 ELSE 0 END) AS offers,
       SUM(CASE WHEN o.status = 'accepted' THEN 1 ELSE 0 END) AS hires,
       ROUND(100.0 * SUM(CASE WHEN d.max_stage >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS apply_to_screen_pct,
       ROUND(100.0 * SUM(CASE WHEN d.max_stage >= 5 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN d.max_stage >= 4 THEN 1 ELSE 0 END), 0), 2)       AS onsite_to_offer_pct,
       ROUND(1000.0 * SUM(CASE WHEN o.status = 'accepted' THEN 1 ELSE 0 END) / COUNT(*), 2) AS hires_per_1000_apps
FROM app_depth d
LEFT JOIN fact_offer o ON o.application_id = d.application_id
GROUP BY d.source
ORDER BY hires_per_1000_apps DESC, d.source;
