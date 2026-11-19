-- Title: Data-quality checks
-- Business question: Does the warehouse obey the business rules that column constraints cannot
--   express, before anyone trusts a number built on it?
-- Tables: fact_stage_event, fact_application, dim_requisition, fact_offer, dim_employee,
--   fact_employment_spell, fact_performance_review, fact_compensation_snapshot, meta
-- Technique: one UNION ALL of named checks, each returning its violation count; a RECURSIVE CTE
--   detects reporting loops; LAG/LEAD detect overlaps; NOT EXISTS finds missing partners.
-- Edge cases: every check returns a row even at zero violations (so a missing row means a broken
--   check, not a pass); the loop check is depth-capped at 50 so a loop cannot run forever; checks
--   only count rows, they never change data.
WITH RECURSIVE
params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
up(start_id, cur_id, depth) AS (
    SELECT employee_id, manager_id, 1 FROM dim_employee WHERE manager_id IS NOT NULL
    UNION ALL
    SELECT u.start_id, e.manager_id, u.depth + 1
    FROM up u
    JOIN dim_employee e ON e.employee_id = u.cur_id
    WHERE e.manager_id IS NOT NULL AND u.cur_id <> u.start_id AND u.depth < 50
),
checks AS (
    SELECT 'stage_events_have_gaps' AS check_name, 'error' AS severity,
           'applications whose stage numbers are not 1..n without gaps' AS description,
           (SELECT COUNT(*) FROM (SELECT application_id FROM fact_stage_event
                                  GROUP BY application_id HAVING COUNT(*) <> MAX(stage_order))) AS violations
    UNION ALL
    SELECT 'stage_overlap', 'error', 'a stage starts before the previous stage ended',
           (SELECT COUNT(*) FROM (
                SELECT entered_at,
                       LAG(exited_at) OVER (PARTITION BY application_id ORDER BY stage_order) AS prev_exit
                FROM fact_stage_event) WHERE prev_exit IS NOT NULL AND entered_at < prev_exit)
    UNION ALL
    SELECT 'applied_before_requisition_opened', 'error', 'application dated before its requisition opened',
           (SELECT COUNT(*) FROM fact_application a JOIN dim_requisition r ON r.requisition_id = a.requisition_id
            WHERE a.applied_at < r.opened_date)
    UNION ALL
    SELECT 'stage1_date_differs_from_applied_at', 'error', 'Applied stage entered on a different day than applied_at',
           (SELECT COUNT(*) FROM fact_stage_event e JOIN fact_application a ON a.application_id = e.application_id
            WHERE e.stage_order = 1 AND e.entered_at <> a.applied_at)
    UNION ALL
    SELECT 'offer_and_offer_stage_disagree', 'error', 'offer without an Offer stage event, or Offer stage event without an offer',
           (SELECT COUNT(*) FROM fact_offer o WHERE NOT EXISTS (
                SELECT 1 FROM fact_stage_event e WHERE e.application_id = o.application_id AND e.stage_order = 5))
           + (SELECT COUNT(*) FROM fact_stage_event e WHERE e.stage_order = 5 AND NOT EXISTS (
                SELECT 1 FROM fact_offer o WHERE o.application_id = e.application_id))
    UNION ALL
    SELECT 'accepted_offer_without_employee', 'error', 'accepted offer whose start date has passed but no employee row exists',
           (SELECT COUNT(*) FROM fact_offer o, params p
            WHERE o.status = 'accepted' AND o.start_date <= p.as_of
              AND NOT EXISTS (SELECT 1 FROM dim_employee e WHERE e.source_application_id = o.application_id))
    UNION ALL
    SELECT 'hire_date_differs_from_offer_start', 'error', 'employee hire_date is not the accepted offer start_date',
           (SELECT COUNT(*) FROM dim_employee e JOIN fact_offer o ON o.application_id = e.source_application_id
            WHERE e.hire_date <> o.start_date)
    UNION ALL
    SELECT 'filled_requisition_without_accepted_offer', 'error', 'requisition marked filled but none of its applications has an accepted offer',
           (SELECT COUNT(*) FROM dim_requisition r WHERE r.status = 'filled' AND NOT EXISTS (
                SELECT 1 FROM fact_application a JOIN fact_offer o ON o.application_id = a.application_id
                WHERE a.requisition_id = r.requisition_id AND o.status = 'accepted'))
    UNION ALL
    SELECT 'requisition_with_multiple_accepted_offers', 'warning', 'requisition with more than one accepted offer (each requisition has one seat)',
           (SELECT COUNT(*) FROM (SELECT a.requisition_id FROM fact_application a
                                  JOIN fact_offer o ON o.application_id = a.application_id
                                  WHERE o.status = 'accepted'
                                  GROUP BY a.requisition_id HAVING COUNT(*) > 1))
    UNION ALL
    SELECT 'employee_dates_differ_from_spells', 'error', 'hire/term dates do not match first spell start and last spell end',
           (SELECT COUNT(*) FROM dim_employee e
            LEFT JOIN (SELECT employee_id, MIN(start_date) AS first_start,
                              MAX(COALESCE(end_date, '9999-12-31')) AS last_end
                       FROM fact_employment_spell GROUP BY employee_id) s ON s.employee_id = e.employee_id
            WHERE s.employee_id IS NULL OR s.first_start <> e.hire_date
               OR s.last_end <> COALESCE(e.term_date, '9999-12-31'))
    UNION ALL
    SELECT 'overlapping_employment_spells', 'error', 'two spells of one employee overlap in time',
           (SELECT COUNT(*) FROM (
                SELECT end_date, LEAD(start_date) OVER (PARTITION BY employee_id ORDER BY start_date) AS next_start
                FROM fact_employment_spell) WHERE next_start IS NOT NULL AND (end_date IS NULL OR next_start <= end_date))
    UNION ALL
    SELECT 'review_outside_tenure', 'error', 'performance review dated before hire or after termination',
           (SELECT COUNT(*) FROM fact_performance_review r JOIN dim_employee e ON e.employee_id = r.employee_id
            WHERE r.review_date < e.hire_date OR (e.term_date IS NOT NULL AND r.review_date > e.term_date))
    UNION ALL
    SELECT 'compensation_outside_tenure', 'error', 'salary snapshot dated before hire or after termination',
           (SELECT COUNT(*) FROM fact_compensation_snapshot c JOIN dim_employee e ON e.employee_id = c.employee_id
            WHERE c.effective_date < e.hire_date OR (e.term_date IS NOT NULL AND c.effective_date > e.term_date))
    UNION ALL
    SELECT 'manager_loop_members', 'error', 'employees who are their own manager through a chain of managers',
           (SELECT COUNT(DISTINCT start_id) FROM up WHERE cur_id = start_id)
    UNION ALL
    SELECT 'active_employee_with_departed_manager', 'warning', 'current employee whose manager has left',
           (SELECT COUNT(*) FROM dim_employee e JOIN dim_employee m ON m.employee_id = e.manager_id
            WHERE e.term_date IS NULL AND m.term_date IS NOT NULL)
    UNION ALL
    SELECT 'manager_hired_after_report', 'warning', 'manager hire_date later than the report''s hire_date',
           (SELECT COUNT(*) FROM dim_employee e JOIN dim_employee m ON m.employee_id = e.manager_id
            WHERE m.hire_date > e.hire_date)
)
SELECT check_name, severity, violations,
       CASE WHEN violations = 0 THEN 'pass' ELSE 'FAIL' END AS status,
       description
FROM checks
ORDER BY CASE WHEN violations = 0 THEN 1 ELSE 0 END, severity, check_name;
