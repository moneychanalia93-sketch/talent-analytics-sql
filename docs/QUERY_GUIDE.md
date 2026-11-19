# Query guide

Each section explains one technique in plain words, then shows the excerpt from the query that uses it. The full,
commented query is in `sql/queries/`. Run any of them with `python -m talentsql run <number>`.

Contents: [Conditional aggregation](#1-conditional-aggregation-pivots) · [Funnels](#2-funnel-analysis) ·
[Percentiles](#3-percentiles-without-a-percentile-function) · [Ranking](#4-rank-dense_rank-and-ntile) ·
[LAG/LEAD](#5-lag-and-lead) · [Running totals](#6-running-totals-and-moving-averages) ·
[Recursive CTEs](#7-recursive-ctes) · [Gaps and islands](#8-gaps-and-islands) · [Cohorts](#9-cohort-analysis) ·
[Confidence interval](#10-a-confidence-interval-in-sql) · [Suppression](#11-small-cell-suppression-k-anonymity) ·
[Four-fifths rule](#12-the-four-fifths-rule) · [Top-N](#13-top-n-per-group) · [Duplicates](#14-duplicate-detection) ·
[Data quality](#15-data-quality-checks) · [PERCENT_RANK](#16-peer-benchmarks-with-percent_rank) ·
[Indexes](#17-indexes-and-query-plans)

---

## 1. Conditional aggregation (pivots)

**Idea.** `SUM(CASE WHEN condition THEN 1 ELSE 0 END)` counts only the rows that meet the condition. Put several of
them in one `SELECT` and you turn row values into columns (a pivot) in a single pass over the data. Used in queries
**2, 6, 8, 11, 17, 23, 24, 26, 27**.

```sql
-- 17_hires_pivot_by_team_quarter.sql
SELECT e.team,
       SUM(CASE WHEN d.quarter = 1 THEN 1 ELSE 0 END) AS q1,
       SUM(CASE WHEN d.quarter = 2 THEN 1 ELSE 0 END) AS q2,
       SUM(CASE WHEN d.quarter = 3 THEN 1 ELSE 0 END) AS q3,
       SUM(CASE WHEN d.quarter = 4 THEN 1 ELSE 0 END) AS q4,
       COUNT(*) AS total_hires
FROM dim_employee e
JOIN dim_date d ON d.full_date = e.hire_date
WHERE e.source_application_id IS NOT NULL
GROUP BY e.team
```

**Watch for.** A team with no hires in a quarter must show 0, not disappear; the `ELSE 0` and a `GROUP BY` on the team do that.

## 2. Funnel analysis

**Idea.** A funnel counts how many things reach each step, then divides a step by the one before it (step conversion)
and by the first one (overall conversion). Query **1** does it for stages; query **2** does it per source; query **27**
shows who is waiting right now.

```sql
-- 01_funnel_by_stage.sql
SELECT stage_order,
       stage_name,
       n AS applications_reached,
       ROUND(100.0 * n / NULLIF(FIRST_VALUE(n) OVER (ORDER BY stage_order), 0), 2) AS pct_of_applied,
       ROUND(100.0 * n / NULLIF(LAG(n) OVER (ORDER BY stage_order), 0), 2)          AS pct_of_previous_stage
FROM reached
```

`FIRST_VALUE` reads the top of the funnel; `LAG` reads the previous row. `NULLIF(x, 0)` turns a zero divisor into NULL
so the query returns a blank instead of an error.

## 3. Percentiles without a percentile function

**Idea.** SQLite has no `PERCENTILE_CONT`. The nearest-rank method needs only a row number and a row count: the p-th
percentile of n sorted values is the value at position ceil(p x n / 100). Integer arithmetic `(p*n + 99) / 100` is the
same as `ceil`. Used in query **3** (time to hire p50 and p90).

```sql
-- 03_time_to_hire_percentiles.sql
ranked AS (
    SELECT team, days,
           ROW_NUMBER() OVER (PARTITION BY team ORDER BY days) AS rn,
           COUNT(*)     OVER (PARTITION BY team)               AS n
    FROM grouped
)
SELECT team,
       MIN(CASE WHEN rn = (50 * n + 99) / 100 THEN days END) AS p50_days,
       MIN(CASE WHEN rn = (90 * n + 99) / 100 THEN days END) AS p90_days
FROM ranked
GROUP BY team
```

**Watch for.** Other tools interpolate between two neighbours, so their p90 can differ slightly from nearest-rank.
PostgreSQL's `percentile_disc` equals nearest-rank; `percentile_cont` interpolates.

## 4. RANK, DENSE_RANK and NTILE

**Idea.** All three number rows in a sorted order. When two recruiters tie on hires: `RANK` gives both the same number and
skips the next (1, 1, 3); `DENSE_RANK` gives both the same number and does not skip (1, 1, 2); `NTILE(4)` cuts the
ordered list into four equal groups and has to break ties somehow, so the query adds `recruiter_id` to the order.
Used in query **5**.

```sql
-- 05_recruiter_productivity_rank.sql
RANK()       OVER (ORDER BY hires DESC)                    AS rank_overall,
DENSE_RANK() OVER (ORDER BY hires DESC)                    AS dense_rank_overall,
NTILE(4)     OVER (ORDER BY hires DESC, recruiter_id)      AS quartile,
RANK()       OVER (PARTITION BY team ORDER BY hires DESC)  AS rank_in_group
```

`PARTITION BY team` restarts the ranking inside each recruiting group.

## 5. LAG and LEAD

**Idea.** `LAG(col)` reads the same column from the previous row of the window; `LEAD(col)` reads the next one. That
turns "difference between consecutive events" into a plain subtraction. Used in query **16** (how long candidates wait
between stages) and query **21** (overlap checks).

```sql
-- 16_stage_dwell_times_lag_lead.sql
WITH seq AS (
    SELECT application_id, stage_order, entered_at, exited_at,
           LAG(exited_at)   OVER (PARTITION BY application_id ORDER BY stage_order) AS prev_exit,
           LEAD(entered_at) OVER (PARTITION BY application_id ORDER BY stage_order) AS next_entry
    FROM fact_stage_event
)
```

**Watch for.** Do the `LAG`/`LEAD` in a CTE and filter afterwards. A `WHERE` placed in the same `SELECT` runs first and
would remove the neighbour rows the window needs.

## 6. Running totals and moving averages

**Idea.** A window frame says which rows around the current row to include. `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`
is a running total; `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` is a 3-row moving average. Used in queries **7**
(headcount), **19** (applications), **26** (Pareto).

```sql
-- 07_headcount_over_time.sql
SUM(hires - terms) OVER (ORDER BY month_start ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ending_headcount,
SUM(terms)         OVER (ORDER BY month_start ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)       AS terms_12m,
```

**Watch for.** `ROWS` counts rows, so a missing month would silently stretch the window. That is why queries 7 and 19
first build a complete list of months and join the data onto it.

## 7. Recursive CTEs

**Idea.** A recursive CTE has a starting query and a step query that refers to the CTE itself; SQL repeats the step on
the newest rows until it returns nothing.

**a) A date spine (query 7).** Generates one row per month with no calendar table:

```sql
spine(month_start) AS (
    SELECT first_m FROM bounds
    UNION ALL
    SELECT date(s.month_start, '+1 month') FROM spine s, bounds b WHERE s.month_start < b.last_m
)
```

**b) The org tree (query 9).** Start at the person with no manager, then repeatedly add their reports. The query carries
`depth` and a `/id/id/` path string; sorting by `path` gives a top-down outline.

```sql
WITH RECURSIVE tree(employee_id, depth, path) AS (
    SELECT employee_id, 0, '/' || employee_id || '/'
    FROM dim_employee
    WHERE manager_id IS NULL AND term_date IS NULL
    UNION ALL
    SELECT e.employee_id, t.depth + 1, t.path || e.employee_id || '/'
    FROM dim_employee e
    JOIN tree t ON e.manager_id = t.employee_id
    WHERE e.term_date IS NULL
      AND t.depth < 25
      AND instr(t.path, '/' || e.employee_id || '/') = 0
)
```

**Cycle protection.** If bad data makes A report to B and B to A, the step would run forever. The last two conditions stop that:
a person already on the path is never added again, and a hard depth cap ends anything else. Tests build exactly that loop
and check the query still finishes.

**c) Subtree roll-up (query 10).** Climb from every employee up through their managers, which yields one row for every
(person, ancestor) pair. Grouping by ancestor then gives each manager's total organisation size, direct reports and depth.

```sql
WITH RECURSIVE chain(emp_id, ancestor_id, depth, path) AS (
    SELECT employee_id, manager_id, 1, '/' || employee_id || '/' || manager_id || '/'
    FROM dim_employee
    WHERE manager_id IS NOT NULL AND term_date IS NULL
    UNION ALL
    SELECT c.emp_id, e.manager_id, c.depth + 1, c.path || e.manager_id || '/'
    FROM chain c
    JOIN dim_employee e ON e.employee_id = c.ancestor_id
    WHERE e.manager_id IS NOT NULL
      AND c.depth < 30
      AND instr(c.path, '/' || e.manager_id || '/') = 0
)
```

## 8. Gaps and islands

**Idea.** Given spans of time, find the unbroken runs ("islands") separated by breaks ("gaps"). Three steps: (1) for each
span, find the latest end date seen so far; (2) mark a span as starting a new island if it begins more than 31 days after
that; (3) a running sum of those marks numbers the islands. Used in query **15**.

```sql
-- 15_continuous_employment_islands.sql
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
```

**Why the running maximum.** Comparing with only the previous row breaks when one spell sits inside an earlier, longer
one. The running maximum of all earlier end dates handles it; a test covers that case, plus gaps of exactly 31 and 32 days.

## 9. Cohort analysis

**Idea.** Group people by when they joined (their cohort) and follow each group over time. Query **24** gives, for each
hire quarter, the share still employed after 3, 6, 12, 18 and 24 months. Each column divides "still employed" by "old enough
to be measured", so recent cohorts show blank cells instead of a false 100%.

```sql
-- 24_cohort_retention_matrix.sql
ROUND(100.0 * SUM(CASE WHEN hire_date <= date(as_of, '-365 days') AND (term_date IS NULL OR term_date > date(hire_date, '+365 days')) THEN 1 ELSE 0 END)
      / NULLIF(SUM(CASE WHEN hire_date <= date(as_of, '-365 days') THEN 1 ELSE 0 END), 0), 1) AS ret_12m_pct
```

Query **8** is the simpler version by hire year (how many left, voluntary versus involuntary, tenure of leavers).

## 10. A confidence interval in SQL

**Idea.** An acceptance rate of 9 of 10 is less certain than 900 of 1,000. The Wilson score interval gives a range that
shrinks as the sample grows and stays between 0% and 100%. Query **4** computes it with `SQRT` and flags teams with fewer
than 30 decided offers.

```sql
-- 04_offer_acceptance_by_team.sql
ROUND(100.0 * ((p + z2 / (2 * n)) - 1.96 * SQRT(p * (1 - p) / n + z2 / (4.0 * n * n))) / (1 + z2 / n), 2) AS ci95_low_pct,
ROUND(100.0 * ((p + z2 / (2 * n)) + 1.96 * SQRT(p * (1 - p) / n + z2 / (4.0 * n * n))) / (1 + z2 / n), 2) AS ci95_high_pct,
```

## 11. Small-cell suppression (k-anonymity)

**Idea.** If only 3 women hold a level, publishing their average pay reveals roughly what each earns. The rule: never show a
statistic for a cell smaller than k (here 5). Query **13** does it inside SQL, so the number cannot leak by accident: the
size column shows `<5` and the pay columns are NULL.

```sql
-- 13_pay_equity_gap_by_level.sql
CASE WHEN c.n_women < p.min_n THEN '<' || p.min_n ELSE CAST(c.n_women AS TEXT) END AS women_n,
CASE WHEN c.n_women >= p.min_n THEN ROUND(c.avg_women, 0) END AS avg_base_women,
CASE WHEN c.n_women >= p.min_n AND c.n_men >= p.min_n
     THEN ROUND(100.0 * (c.avg_women - c.avg_men) / c.avg_men, 2) END AS gap_pct_women_vs_men,
```

The gap is **unadjusted** (no control for team, location or tenure). It is a screening number, not proof of anything.

## 12. The four-fifths rule

**Idea.** A common screening test for fairness in selection: compute each group's selection rate, divide by the highest
group's rate, and flag a ratio under 0.80. Query **14** runs it at every decision stage for two attributes. Groups with
fewer than 10 decisions are marked `insufficient data` and are never used as the benchmark.

```sql
-- 14_adverse_impact_four_fifths.sql
MAX(CASE WHEN g.considered >= p.min_considered THEN 1.0 * g.selected / g.considered END)
    OVER (PARTITION BY g.dimension, g.from_stage) AS best_rate
...
WHEN s.rate / s.best_rate < s.threshold THEN 'ADVERSE IMPACT (ratio < 0.80)'
```

The flag is a prompt to investigate, not a finding of discrimination. In the sample data one group is deliberately
screened out more often, so the query has something to catch.

## 13. Top-N per group

**Idea.** Number the rows inside each group with `ROW_NUMBER() OVER (PARTITION BY group ORDER BY measure DESC)`, then keep
numbers up to N in an outer query. Used in query **18** (top 3 hiring sources per team). Add a second sort column so ties
break the same way every run.

```sql
-- 18_top_sources_per_team.sql
ROW_NUMBER() OVER (PARTITION BY team ORDER BY hires DESC, source) AS rn,
SUM(hires)   OVER (PARTITION BY team)                             AS team_hires
```

## 14. Duplicate detection

**Idea.** Build a normalised key (lower-case, plus-tag removed), group by it and keep groups with more than one row. Query
**20** also counts repeat applications to the same requisition, which the table's unique constraint cannot see because the
duplicates have different candidate ids.

```sql
-- 20_duplicate_candidate_detection.sql
lower(CASE WHEN instr(email, '+') > 0 AND instr(email, '+') < instr(email, '@')
           THEN substr(email, 1, instr(email, '+') - 1) || substr(email, instr(email, '@'))
           ELSE email END) AS norm_email
```

## 15. Data-quality checks

**Idea.** Constraints catch one-row mistakes. Rules that span rows (a stage that starts before the previous one ended, a
manager loop, an accepted offer with no employee) need queries. Query **21** returns one row per check with its violation
count, including checks that pass, so a missing row can never be mistaken for a pass.

```sql
-- 21_data_quality_checks.sql
SELECT 'stage_overlap', 'error', 'a stage starts before the previous stage ended',
       (SELECT COUNT(*) FROM (
            SELECT entered_at,
                   LAG(exited_at) OVER (PARTITION BY application_id ORDER BY stage_order) AS prev_exit
            FROM fact_stage_event) WHERE prev_exit IS NOT NULL AND entered_at < prev_exit)
```

## 16. Peer benchmarks with PERCENT_RANK

**Idea.** Compare each person with the average of their peers (same level and location) in one pass: `AVG(...) OVER
(PARTITION BY level, location)` puts the peer average on every row, and `PERCENT_RANK()` gives the position in the group
from 0 to 100. Query **25** lists people whose pay is more than 15% below or above that average, in groups of at least 5.

```sql
-- 25_compa_ratio_outliers.sql
COUNT(*)         OVER (PARTITION BY level, location) AS peer_n,
AVG(base_salary) OVER (PARTITION BY level, location) AS peer_avg,
PERCENT_RANK()   OVER (PARTITION BY level, location ORDER BY base_salary) AS pct_rank
```

## 17. Indexes and query plans

**Idea.** An index lets the database jump to matching rows instead of reading the whole table. `EXPLAIN QUERY PLAN` shows
which it chose: `SCAN` reads every row; `SEARCH ... USING INDEX` jumps. `python -m talentsql explain <n>` prints the plan for
any query, and `python -m talentsql bench` times the heaviest queries with and without the secondary indexes in
`sql/indexes.sql`. Real timings and plans are in [PERFORMANCE.md](PERFORMANCE.md).

**Reading the numbers honestly.** Indexes do not help every query. Queries that must read most of a table (a funnel over all
100,000 applications) gain little, and a few can run a little slower. The benchmark reports whatever it measures.
