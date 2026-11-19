"""Differential tests: every analytic query is checked against an independent Python oracle.

Each test runs on two databases: the hand-built fixture (tests/fixture.py) and a small database made
by the real seeded generator. A SQL result must equal the oracle result on both.
"""
import unittest

from tests import fixture, oracles
from tests.support import assert_rows, run

OP = {i: oracles.ORACLES[i] for i in range(1, 29)}


def tearDownModule():
    fixture.close_all()


class QueryDifferentialTests(unittest.TestCase):
    def check(self, n, key=(0,), tol=0.0051, cols=None, want=None):
        for name, conn in (("fixture", fixture.fixture_db()), ("seeded", fixture.seeded_db())):
            with self.subTest(db=name, query=n):
                world = oracles.World(conn)
                got = run(conn, n)
                expected = OP[n](world) if want is None else want(world)
                self.assertTrue(len(expected) > 0, "oracle produced no rows; the dataset does not exercise this query")
                assert_rows(self, got, expected, key=key, tol=tol, cols=cols)

    def test_q01_funnel_by_stage(self):
        self.check(1)

    def test_q02_funnel_by_source(self):
        self.check(2)

    def test_q03_time_to_hire_percentiles(self):
        self.check(3, tol={4: 0.0051})

    def test_q04_offer_acceptance_wilson_interval(self):
        self.check(4)

    def test_q05_recruiter_rank_dense_rank_ntile(self):
        self.check(5)

    def test_q06_requisition_ageing(self):
        self.check(6, tol={7: 0.051})

    def test_q07_headcount_running_total_and_trailing_attrition(self):
        self.check(7)

    def test_q08_attrition_by_hire_cohort(self):
        self.check(8, tol={6: 0.051})

    def test_q09_org_tree_recursive(self):
        self.check(9)

    def test_q10_org_subtree_rollup(self):
        self.check(10)

    def test_q11_span_of_control(self):
        self.check(11)

    def test_q12_hiring_quality_by_source(self):
        self.check(12)

    def test_q13_pay_gap_with_suppression(self):
        self.check(13, tol={3: 0.51, 4: 0.51})

    def test_q14_adverse_impact(self):
        self.check(14, key=(0, 1, 2), tol={7: 0.0011})

    def test_q15_employment_islands(self):
        self.check(15, key=(0, 1))

    def test_q16_stage_dwell_lag_lead(self):
        self.check(16)

    def test_q17_hires_pivot_by_quarter(self):
        self.check(17, tol={6: 0.051})

    def test_q18_top_sources_per_team(self):
        self.check(18, key=(0, 1))

    def test_q19_moving_average_and_yoy(self):
        self.check(19)

    def test_q20_duplicate_candidates(self):
        self.check(20)

    def test_q21_data_quality_counts_match_python_checks(self):
        self.check(21, cols=(0, 2))

    def test_q22_seasonality_index(self):
        self.check(22, tol={3: 0.051, 4: 0.0011})

    def test_q23_requisition_outcomes(self):
        self.check(23, tol={6: 0.051})

    def test_q24_cohort_retention_matrix(self):
        self.check(24, tol=0.051)

    def test_q25_compa_ratio_outliers(self):
        self.check(25, tol={7: 0.51, 8: 0.0011, 9: 0.051})

    def test_q26_rejection_pareto(self):
        self.check(26)

    def test_q27_open_pipeline_snapshot(self):
        self.check(27, tol={3: 0.051})

    def test_q28_manager_attrition(self):
        self.check(28)


class QueryOrderingTests(unittest.TestCase):
    """Result order is part of the contract for these queries."""

    def test_funnel_rows_are_in_stage_order(self):
        rows = run(fixture.fixture_db(), 1)
        self.assertEqual([r[0] for r in rows], [1, 2, 3, 4, 5, 6])

    def test_headcount_months_ascend_without_gaps(self):
        for conn in (fixture.fixture_db(), fixture.seeded_db()):
            months = [r[0] for r in run(conn, 7)]
            self.assertEqual(months, sorted(months))
            self.assertEqual(len(months), len(set(months)))
            y, m = (int(x) for x in months[0].split("-"))
            for label in months:
                self.assertEqual(label, f"{y:04d}-{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    def test_time_to_hire_puts_all_row_first(self):
        self.assertEqual(run(fixture.fixture_db(), 3)[0][0], "ALL")

    def test_org_tree_lists_a_manager_before_their_reports(self):
        rows = run(fixture.fixture_db(), 9)
        position = {r[0]: i for i, r in enumerate(rows)}
        for emp_id, _chart, _team, _level, depth, path in rows:
            if depth:
                parent = int(path.strip("/").split("/")[-2])
                self.assertLess(position[parent], position[emp_id])


if __name__ == "__main__":
    unittest.main()
