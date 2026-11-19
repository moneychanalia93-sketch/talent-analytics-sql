# Performance

Measured with `python -m talentsql bench --write` on the seeded dataset. Every number below was produced by
that command on the machine described here; nothing is estimated. Re-run it to get your own.

## Environment

- **CPU:** AMD Ryzen 5 PRO 8540U w/ Radeon 740M Graphics (12 logical cores)
- **RAM:** 31.3 GB
- **OS:** Windows 11
- **Python:** 3.13.5
- **SQLite:** 3.49.1

## Dataset

- `dim_employee`: 2,000 rows
- `fact_application`: 100,000 rows
- `fact_stage_event`: 149,828 rows
- `fact_offer`: 1,722 rows

## Method

1. Drop every secondary index listed in `sql/indexes.sql` (primary keys and UNIQUE constraints remain), run `ANALYZE`.
2. Time all 28 queries: one untimed warm-up, then 5 timed runs, fetching every row. The **median** is reported.
3. Take the 10 slowest queries. Re-create the indexes, run `ANALYZE`, time those queries again the same way.
4. Capture `EXPLAIN QUERY PLAN` for both states.

Timings are single-process wall-clock times on a warm OS cache and will vary run to run. Small queries
(a few milliseconds) are dominated by noise; treat differences under about 20% as unchanged.

## Results: the slowest queries, without and with indexes

| # | Query | Rows | No secondary indexes (ms) | With indexes (ms) | Speed-up | Plan scans before / after | Plan searches before / after |
|---|---|---|---|---|---|---|---|
| 21 | Data-quality checks | 16 | 2075.8 | 401.7 | 5.17x | 43 / 37 | 16 / 22 |
| 16 | Stage dwell and hand-off times (LAG / LEAD) | 5 | 1051.1 | 885.5 | 1.19x | 4 / 4 | 1 / 1 |
| 14 | Four-fifths adverse-impact check at each stage | 28 | 641.5 | 588.0 | 1.09x | 7 / 5 | 5 / 7 |
| 20 | Duplicate candidate detection | 1,203 | 324.5 | 191.1 | 1.70x | 3 / 3 | 3 / 3 |
| 02 | Funnel conversion by application source | 6 | 208.0 | 214.5 | 0.97x | 2 / 2 | 2 / 2 |
| 26 | Where candidates are rejected (Pareto) | 5 | 149.3 | 35.6 | 4.19x | 5 / 4 | 0 / 1 |
| 22 | Application seasonality index | 12 | 133.3 | 82.7 | 1.61x | 4 / 4 | 1 / 1 |
| 19 | Monthly application volume with moving average and year-over-year change | 60 | 102.4 | 45.9 | 2.23x | 8 / 8 | 0 / 0 |
| 01 | Hiring funnel conversion by stage | 6 | 64.4 | 12.7 | 5.06x | 6 / 4 | 0 / 2 |
| 27 | Open pipeline snapshot with stale-candidate counts | 5 | 28.4 | 0.6 | 45.39x | 2 / 1 | 2 / 3 |

7 of the 10 queries ran at least 1.2x faster with indexes; 3 were within noise or slower. Details and plans follow.

## All queries without secondary indexes

| # | Query | Rows | Median ms |
|---|---|---|---|
| 21 | Data-quality checks | 16 | 2075.8 |
| 16 | Stage dwell and hand-off times (LAG / LEAD) | 5 | 1051.1 |
| 14 | Four-fifths adverse-impact check at each stage | 28 | 641.5 |
| 20 | Duplicate candidate detection | 1,203 | 324.5 |
| 02 | Funnel conversion by application source | 6 | 208.0 |
| 26 | Where candidates are rejected (Pareto) | 5 | 149.3 |
| 22 | Application seasonality index | 12 | 133.3 |
| 19 | Monthly application volume with moving average and year-over-year change | 60 | 102.4 |
| 01 | Hiring funnel conversion by stage | 6 | 64.4 |
| 27 | Open pipeline snapshot with stale-candidate counts | 5 | 28.4 |
| 25 | Compa-ratio outliers within level and location | 328 | 23.2 |
| 15 | Continuous employment (gaps and islands) | 2,043 | 17.0 |
| 24 | Cohort retention matrix by hire quarter | 44 | 15.0 |
| 10 | Headcount rollup per manager subtree | 472 | 13.6 |
| 03 | Time to hire with p50 and p90 by team | 11 | 12.1 |
| 13 | Pay-equity gap by level with small-cell suppression | 8 | 7.2 |
| 18 | Top 3 hiring sources per team | 30 | 6.4 |
| 12 | Hiring quality by source | 6 | 6.2 |
| 04 | Offer acceptance rate by team with a confidence interval | 10 | 5.3 |
| 09 | Org tree with depth and path (recursive) | 1,187 | 5.3 |
| 05 | Recruiter productivity ranking | 40 | 4.7 |
| 28 | Manager attrition and team ratings (minimum 5 reports) | 150 | 4.1 |
| 23 | Requisition outcomes and time to fill by team | 10 | 3.8 |
| 07 | Monthly headcount with running totals and trailing attrition | 132 | 2.2 |
| 08 | Attrition and tenure by hire-year cohort | 11 | 1.4 |
| 17 | Pipeline hires pivoted by team and calendar quarter | 10 | 1.4 |
| 11 | Manager span of control by level | 8 | 1.1 |
| 06 | Open requisition ageing buckets | 10 | 0.4 |

## Query plans (`EXPLAIN QUERY PLAN`)

`SCAN t` reads every row of `t`. `SEARCH t USING INDEX i (col=?)` jumps straight to matching rows.
`COVERING INDEX` means the index alone answered the read, without touching the table.

### Query 21: Data-quality checks

Without secondary indexes:

```text
CO-ROUTINE checks
COMPOUND QUERY
LEFT-MOST SUBQUERY
SCAN CONSTANT ROW
SCALAR SUBQUERY 5
CO-ROUTINE (subquery-4)
SCAN fact_stage_event USING COVERING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-4)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 8
CO-ROUTINE (subquery-7)
CO-ROUTINE (subquery-47)
SCAN fact_stage_event USING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-47)
SCAN (subquery-7)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 10
SCAN a
SEARCH r USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 12
SCAN e
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 15
SCAN o USING COVERING INDEX sqlite_autoindex_fact_offer_1
CORRELATED SCALAR SUBQUERY 14
SEARCH e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=? AND stage_order=?)
SCALAR SUBQUERY 17
SCAN e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1
CORRELATED SCALAR SUBQUERY 16
SEARCH o USING COVERING INDEX sqlite_autoindex_fact_offer_1 (application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 20
SEARCH meta USING INDEX sqlite_autoindex_meta_1 (key=?)
SCAN o
CORRELATED SCALAR SUBQUERY 19
SEARCH e USING COVERING INDEX sqlite_autoindex_dim_employee_1 (source_application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 22
SCAN e
SEARCH o USING INDEX sqlite_autoindex_fact_offer_1 (application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 25
SCAN r
CORRELATED SCALAR SUBQUERY 24
SEARCH o USING AUTOMATIC PARTIAL COVERING INDEX (status=?)
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 28
CO-ROUTINE (subquery-27)
SCAN o
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
SCAN (subquery-27)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 31
MATERIALIZE s
SCAN fact_employment_spell USING INDEX sqlite_autoindex_fact_employment_spell_1
SCAN e
BLOOM FILTER ON s (employee_id=?)
SEARCH s USING AUTOMATIC COVERING INDEX (employee_id=?) LEFT-JOIN
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 34
CO-ROUTINE (subquery-33)
CO-ROUTINE (subquery-48)
SCAN fact_employment_spell USING INDEX sqlite_autoindex_fact_employment_spell_1
SCAN (subquery-48)
SCAN (subquery-33)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 36
SCAN e
SEARCH r USING INDEX sqlite_autoindex_fact_performance_review_1 (employee_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 38
SCAN e
SEARCH c USING COVERING INDEX sqlite_autoindex_fact_compensation_snapshot_1 (employee_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 40
CO-ROUTINE up
SETUP
SCAN dim_employee
RECURSIVE STEP
SCAN u
SEARCH e USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR count(DISTINCT)
SCAN up
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 42
SCAN e
SEARCH m USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 44
SCAN e
SEARCH m USING INTEGER PRIMARY KEY (rowid=?)
SCAN checks
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE checks
COMPOUND QUERY
LEFT-MOST SUBQUERY
SCAN CONSTANT ROW
SCALAR SUBQUERY 5
CO-ROUTINE (subquery-4)
SCAN fact_stage_event USING COVERING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-4)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 8
CO-ROUTINE (subquery-7)
CO-ROUTINE (subquery-47)
SCAN fact_stage_event USING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-47)
SCAN (subquery-7)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 10
SCAN r USING COVERING INDEX idx_requisition_status
SEARCH a USING INDEX idx_application_req (requisition_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 12
SEARCH e USING INDEX idx_stage_order_outcome (stage_order=?)
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 15
SCAN o USING COVERING INDEX sqlite_autoindex_fact_offer_1
CORRELATED SCALAR SUBQUERY 14
SEARCH e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=? AND stage_order=?)
SCALAR SUBQUERY 17
SEARCH e USING COVERING INDEX idx_stage_order_outcome (stage_order=?)
CORRELATED SCALAR SUBQUERY 16
SEARCH o USING COVERING INDEX sqlite_autoindex_fact_offer_1 (application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 20
SEARCH meta USING INDEX sqlite_autoindex_meta_1 (key=?)
SEARCH o USING INDEX idx_offer_status (status=?)
CORRELATED SCALAR SUBQUERY 19
SEARCH e USING COVERING INDEX sqlite_autoindex_dim_employee_1 (source_application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 22
SCAN e
SEARCH o USING INDEX sqlite_autoindex_fact_offer_1 (application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 25
SEARCH r USING COVERING INDEX idx_requisition_status (status=?)
CORRELATED SCALAR SUBQUERY 24
SEARCH a USING COVERING INDEX idx_application_req (requisition_id=?)
SEARCH o USING INDEX sqlite_autoindex_fact_offer_1 (application_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 28
CO-ROUTINE (subquery-27)
SEARCH o USING INDEX idx_offer_status (status=?)
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
SCAN (subquery-27)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 31
MATERIALIZE s
SCAN fact_employment_spell USING INDEX idx_spell_employee
SCAN e
BLOOM FILTER ON s (employee_id=?)
SEARCH s USING AUTOMATIC COVERING INDEX (employee_id=?) LEFT-JOIN
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 34
CO-ROUTINE (subquery-33)
CO-ROUTINE (subquery-48)
SCAN fact_employment_spell USING INDEX idx_spell_employee
SCAN (subquery-48)
SCAN (subquery-33)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 36
SCAN e
SEARCH r USING INDEX sqlite_autoindex_fact_performance_review_1 (employee_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 38
SCAN e
SEARCH c USING COVERING INDEX sqlite_autoindex_fact_compensation_snapshot_1 (employee_id=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 40
CO-ROUTINE up
SETUP
SEARCH dim_employee USING COVERING INDEX idx_employee_manager (manager_id>?)
RECURSIVE STEP
SCAN u
SEARCH e USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR count(DISTINCT)
SCAN up
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 42
SCAN e
SEARCH m USING INTEGER PRIMARY KEY (rowid=?)
UNION ALL
SCAN CONSTANT ROW
SCALAR SUBQUERY 44
SCAN e
SEARCH m USING INTEGER PRIMARY KEY (rowid=?)
SCAN checks
USE TEMP B-TREE FOR ORDER BY
```

### Query 16: Stage dwell and hand-off times (LAG / LEAD)

Without secondary indexes:

```text
CO-ROUTINE seq
CO-ROUTINE (subquery-3)
CO-ROUTINE (subquery-4)
SCAN fact_stage_event USING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-4)
SCAN (subquery-3)
SCAN d
BLOOM FILTER ON s (stage_order=?)
SEARCH s USING AUTOMATIC PARTIAL COVERING INDEX (stage_order=?)
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE seq
CO-ROUTINE (subquery-3)
CO-ROUTINE (subquery-4)
SCAN fact_stage_event USING INDEX sqlite_autoindex_fact_stage_event_1
SCAN (subquery-4)
SCAN (subquery-3)
SCAN d
BLOOM FILTER ON s (stage_order=?)
SEARCH s USING AUTOMATIC PARTIAL COVERING INDEX (stage_order=?)
USE TEMP B-TREE FOR ORDER BY
```

### Query 14: Four-fifths adverse-impact check at each stage

Without secondary indexes:

```text
CO-ROUTINE scored
CO-ROUTINE (subquery-7)
CO-ROUTINE by_group
COMPOUND QUERY
LEFT-MOST SUBQUERY
SCAN a USING COVERING INDEX sqlite_autoindex_fact_application_1
SEARCH e USING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=? AND stage_order>? AND stage_order<?)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
UNION ALL
SCAN a USING COVERING INDEX sqlite_autoindex_fact_application_1
SEARCH e USING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=? AND stage_order>? AND stage_order<?)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
MATERIALIZE params
SCAN CONSTANT ROW
SCAN g
SCAN p
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-7)
SCAN d
BLOOM FILTER ON s (from_stage=?)
SEARCH s USING AUTOMATIC COVERING INDEX (from_stage=?)
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE scored
CO-ROUTINE (subquery-7)
CO-ROUTINE by_group
COMPOUND QUERY
LEFT-MOST SUBQUERY
SEARCH e USING COVERING INDEX idx_stage_order_outcome (stage_order>? AND stage_order<?)
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
UNION ALL
SEARCH e USING COVERING INDEX idx_stage_order_outcome (stage_order>? AND stage_order<?)
SEARCH a USING INTEGER PRIMARY KEY (rowid=?)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
MATERIALIZE params
SCAN CONSTANT ROW
SCAN g
SCAN p
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-7)
SCAN d
BLOOM FILTER ON s (from_stage=?)
SEARCH s USING AUTOMATIC COVERING INDEX (from_stage=?)
USE TEMP B-TREE FOR ORDER BY
```

### Query 20: Duplicate candidate detection

Without secondary indexes:

```text
MATERIALIZE dup_groups
SCAN dim_candidate
USE TEMP B-TREE FOR GROUP BY
MATERIALIZE app_counts
SCAN dim_candidate
BLOOM FILTER ON g (norm_email=?)
SEARCH g USING AUTOMATIC COVERING INDEX (norm_email=?)
SEARCH a USING COVERING INDEX sqlite_autoindex_fact_application_1 (candidate_id=?) LEFT-JOIN
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR count(DISTINCT)
SCAN g
BLOOM FILTER ON c (norm_email=?)
SEARCH c USING AUTOMATIC COVERING INDEX (norm_email=?)
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
MATERIALIZE dup_groups
SCAN dim_candidate USING COVERING INDEX idx_candidate_email
USE TEMP B-TREE FOR GROUP BY
MATERIALIZE app_counts
SCAN dim_candidate USING COVERING INDEX idx_candidate_email
BLOOM FILTER ON g (norm_email=?)
SEARCH g USING AUTOMATIC COVERING INDEX (norm_email=?)
SEARCH a USING COVERING INDEX sqlite_autoindex_fact_application_1 (candidate_id=?) LEFT-JOIN
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR count(DISTINCT)
SCAN g
BLOOM FILTER ON c (norm_email=?)
SEARCH c USING AUTOMATIC COVERING INDEX (norm_email=?)
USE TEMP B-TREE FOR ORDER BY
```

### Query 02: Funnel conversion by application source

Without secondary indexes:

```text
CO-ROUTINE app_depth
SCAN a
SEARCH e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=?)
SCAN d
SEARCH o USING INDEX sqlite_autoindex_fact_offer_1 (application_id=?) LEFT-JOIN
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE app_depth
SCAN a
SEARCH e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1 (application_id=?)
SCAN d
SEARCH o USING INDEX sqlite_autoindex_fact_offer_1 (application_id=?) LEFT-JOIN
USE TEMP B-TREE FOR GROUP BY
USE TEMP B-TREE FOR ORDER BY
```

### Query 26: Where candidates are rejected (Pareto)

Without secondary indexes:

```text
CO-ROUTINE (subquery-3)
CO-ROUTINE (subquery-4)
CO-ROUTINE per_stage
SCAN s
SCAN e LEFT-JOIN
SCAN per_stage
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-4)
SCAN (subquery-3)
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE (subquery-3)
CO-ROUTINE (subquery-4)
CO-ROUTINE per_stage
SCAN s
SEARCH e USING COVERING INDEX idx_stage_order_outcome (stage_order=?) LEFT-JOIN
SCAN per_stage
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-4)
SCAN (subquery-3)
USE TEMP B-TREE FOR ORDER BY
```

### Query 22: Application seasonality index

Without secondary indexes:

```text
CO-ROUTINE (subquery-4)
CO-ROUTINE by_month
CO-ROUTINE monthly
SCAN a
SEARCH d USING INDEX sqlite_autoindex_dim_date_1 (full_date=?)
USE TEMP B-TREE FOR GROUP BY
SCAN monthly
USE TEMP B-TREE FOR GROUP BY
SCAN by_month
SCAN (subquery-4)
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE (subquery-4)
CO-ROUTINE by_month
CO-ROUTINE monthly
SCAN a USING COVERING INDEX idx_application_source
SEARCH d USING INDEX sqlite_autoindex_dim_date_1 (full_date=?)
USE TEMP B-TREE FOR GROUP BY
SCAN monthly
USE TEMP B-TREE FOR GROUP BY
SCAN by_month
SCAN (subquery-4)
USE TEMP B-TREE FOR ORDER BY
```

### Query 19: Monthly application volume with moving average and year-over-year change

Without secondary indexes:

```text
CO-ROUTINE windowed
CO-ROUTINE (subquery-7)
CO-ROUTINE (subquery-8)
MATERIALIZE bounds
SCAN fact_application
MATERIALIZE counts
SCAN fact_application
USE TEMP B-TREE FOR GROUP BY
SCAN d USING INDEX sqlite_autoindex_dim_date_1
SCAN b
SCAN c LEFT-JOIN
SCAN (subquery-8)
SCAN (subquery-7)
SCAN windowed
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
CO-ROUTINE windowed
CO-ROUTINE (subquery-7)
CO-ROUTINE (subquery-8)
MATERIALIZE bounds
SCAN fact_application USING COVERING INDEX idx_application_source
MATERIALIZE counts
SCAN fact_application USING COVERING INDEX idx_application_source
USE TEMP B-TREE FOR GROUP BY
SCAN d USING INDEX sqlite_autoindex_dim_date_1
SCAN b
SCAN c LEFT-JOIN
SCAN (subquery-8)
SCAN (subquery-7)
SCAN windowed
USE TEMP B-TREE FOR ORDER BY
```

### Query 01: Hiring funnel conversion by stage

Without secondary indexes:

```text
CO-ROUTINE (subquery-4)
CO-ROUTINE (subquery-5)
CO-ROUTINE reached
COMPOUND QUERY
LEFT-MOST SUBQUERY
SCAN s
SCAN e USING COVERING INDEX sqlite_autoindex_fact_stage_event_1 LEFT-JOIN
UNION ALL
SCAN fact_offer
SCAN reached
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-5)
SCAN (subquery-4)
```

With indexes:

```text
CO-ROUTINE (subquery-4)
CO-ROUTINE (subquery-5)
CO-ROUTINE reached
COMPOUND QUERY
LEFT-MOST SUBQUERY
SCAN s
SEARCH e USING COVERING INDEX idx_stage_order_outcome (stage_order=?) LEFT-JOIN
UNION ALL
SEARCH fact_offer USING COVERING INDEX idx_offer_status (status=?)
SCAN reached
USE TEMP B-TREE FOR ORDER BY
SCAN (subquery-5)
SCAN (subquery-4)
```

### Query 27: Open pipeline snapshot with stale-candidate counts

Without secondary indexes:

```text
MATERIALIZE waiting
SCAN e
SEARCH meta USING INDEX sqlite_autoindex_meta_1 (key=?)
SCAN s
BLOOM FILTER ON w (stage_order=?)
SEARCH w USING AUTOMATIC COVERING INDEX (stage_order=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```

With indexes:

```text
MATERIALIZE waiting
SEARCH e USING INDEX idx_stage_order_outcome (ANY(stage_order) AND outcome=?)
SEARCH meta USING INDEX sqlite_autoindex_meta_1 (key=?)
SCAN s
BLOOM FILTER ON w (stage_order=?)
SEARCH w USING AUTOMATIC COVERING INDEX (stage_order=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```

