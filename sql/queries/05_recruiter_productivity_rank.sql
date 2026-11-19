-- Title: Recruiter productivity ranking
-- Business question: Who closes the most hires, how do ties rank, and which quartile does each
--   recruiter fall in, overall and within their recruiting group?
-- Tables: dim_recruiter, dim_requisition, fact_application, fact_offer
-- Technique: RANK vs DENSE_RANK vs NTILE(4) over the same ordering, plus a PARTITION BY group rank.
-- Edge cases: recruiters with zero hires are kept (LEFT JOINs) and share the bottom rank; ties give
--   equal RANK with gaps and equal DENSE_RANK without gaps; NTILE breaks ties by recruiter_id so the
--   quartile is deterministic.
WITH hires AS (
    SELECT r.recruiter_id, COUNT(*) AS hires
    FROM fact_offer o
    JOIN fact_application a ON a.application_id = o.application_id
    JOIN dim_requisition r  ON r.requisition_id = a.requisition_id
    WHERE o.status = 'accepted'
    GROUP BY r.recruiter_id
),
reqs AS (
    SELECT recruiter_id, COUNT(*) AS requisitions FROM dim_requisition GROUP BY recruiter_id
),
base AS (
    SELECT rc.recruiter_id, rc.full_name, rc.team,
           COALESCE(q.requisitions, 0) AS requisitions,
           COALESCE(h.hires, 0)        AS hires
    FROM dim_recruiter rc
    LEFT JOIN hires h ON h.recruiter_id = rc.recruiter_id
    LEFT JOIN reqs  q ON q.recruiter_id = rc.recruiter_id
)
SELECT recruiter_id, full_name, team, requisitions, hires,
       ROUND(100.0 * hires / NULLIF(requisitions, 0), 2)         AS hires_per_100_reqs,
       RANK()       OVER (ORDER BY hires DESC)                    AS rank_overall,
       DENSE_RANK() OVER (ORDER BY hires DESC)                    AS dense_rank_overall,
       NTILE(4)     OVER (ORDER BY hires DESC, recruiter_id)      AS quartile,
       RANK()       OVER (PARTITION BY team ORDER BY hires DESC)  AS rank_in_group
FROM base
ORDER BY rank_overall, recruiter_id;
