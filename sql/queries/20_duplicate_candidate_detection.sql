-- Title: Duplicate candidate detection
-- Business question: Which candidates were entered more than once (same e-mail written differently),
--   and did any of them apply twice to the same requisition?
-- Tables: dim_candidate, fact_application
-- Technique: normalise a key in SQL (lower-case, drop a "+tag" in the local part with instr/substr),
--   GROUP BY ... HAVING COUNT(*) > 1, then join applications to the duplicate groups.
-- Edge cases: the UNIQUE (candidate_id, requisition_id) constraint cannot see duplicates that have
--   different candidate_ids, so double applications only show up here; candidates with no
--   applications still count as records; the key is e-mail only (names are not unique enough).
WITH norm AS (
    SELECT candidate_id,
           lower(CASE WHEN instr(email, '+') > 0 AND instr(email, '+') < instr(email, '@')
                      THEN substr(email, 1, instr(email, '+') - 1) || substr(email, instr(email, '@'))
                      ELSE email END) AS norm_email
    FROM dim_candidate
),
dup_groups AS (
    SELECT norm_email, COUNT(*) AS candidate_records, MIN(candidate_id) AS first_id, MAX(candidate_id) AS last_id
    FROM norm
    GROUP BY norm_email
    HAVING COUNT(*) > 1
),
app_counts AS (
    SELECT g.norm_email,
           COUNT(a.application_id)           AS applications,
           COUNT(DISTINCT a.requisition_id)  AS distinct_requisitions
    FROM dup_groups g
    JOIN norm n ON n.norm_email = g.norm_email
    LEFT JOIN fact_application a ON a.candidate_id = n.candidate_id
    GROUP BY g.norm_email
)
SELECT g.norm_email, g.candidate_records, g.first_id, g.last_id,
       c.applications, c.distinct_requisitions,
       c.applications - c.distinct_requisitions AS repeat_applications_same_req
FROM dup_groups g
JOIN app_counts c ON c.norm_email = g.norm_email
ORDER BY g.candidate_records DESC, c.applications DESC, g.norm_email;
