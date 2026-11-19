-- Title: Continuous employment (gaps and islands)
-- Business question: Treating breaks of up to 31 days as continuous, how long was each unbroken run
--   of employment, and who has had more than one?
-- Tables: fact_employment_spell, meta
-- Technique: gaps-and-islands. A running MAX of earlier end dates (frame ends at 1 PRECEDING) is
--   compared with each start date to flag the start of a new island; a running SUM of those flags
--   numbers the islands; GROUP BY island collapses them.
-- Edge cases: running MAX (not just the previous row) so a spell nested inside an earlier longer one
--   cannot open a false island; an open-ended spell is measured to the as-of date; a gap of exactly
--   31 days is still merged, 32 days starts a new island.
WITH params AS (SELECT value AS as_of FROM meta WHERE key = 'as_of_date'),
spells AS (
    SELECT s.employee_id, s.start_date,
           COALESCE(s.end_date, p.as_of) AS end_eff,
           CASE WHEN s.end_date IS NULL THEN 1 ELSE 0 END AS is_open
    FROM fact_employment_spell s
    CROSS JOIN params p
),
marked AS (
    SELECT *,
           MAX(end_eff) OVER (PARTITION BY employee_id ORDER BY start_date
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_end
    FROM spells
),
flagged AS (
    SELECT *,
           CASE WHEN prev_max_end IS NULL
                  OR julianday(start_date) - julianday(prev_max_end) > 31 THEN 1 ELSE 0 END AS new_island
    FROM marked
),
numbered AS (
    SELECT *,
           SUM(new_island) OVER (PARTITION BY employee_id ORDER BY start_date
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS island_no
    FROM flagged
)
SELECT employee_id,
       island_no,
       MIN(start_date) AS island_start,
       MAX(end_eff)    AS island_end,
       COUNT(*)        AS spells_merged,
       CAST(ROUND(julianday(MAX(end_eff)) - julianday(MIN(start_date))) AS INTEGER) AS continuous_days,
       MAX(is_open)    AS is_current
FROM numbered
GROUP BY employee_id, island_no
ORDER BY spells_merged DESC, employee_id, island_no;
