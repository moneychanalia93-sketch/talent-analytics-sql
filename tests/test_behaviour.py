"""Hand-checkable scenarios with literal expected values, plus constraint, seeding, CLI and data-quality tests."""
import contextlib
import hashlib
import io
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from talentsql import bench, cli, db
from talentsql.seed import seed_database
from tests import fixture, oracles
from tests.support import Mini, assert_rows, close_minis, mini_db, run


def tearDownModule():
    fixture.close_all()
    close_minis()


class PercentileTests(unittest.TestCase):
    def hires(self, spans):
        conn = mini_db()
        m = Mini(conn)
        for d in spans:
            m.hire("Engineering", "2024-01-01", oracles.plus("2024-01-01", d))
        return {r[0]: r for r in run(conn, 3)}

    def test_nearest_rank_with_ten_values(self):
        r = self.hires(range(1, 11))["Engineering"]
        self.assertEqual((r[1], r[2], r[3]), (10, 5, 9))   # ceil(.5*10)=5th, ceil(.9*10)=9th

    def test_nearest_rank_with_seven_values(self):
        r = self.hires([2, 4, 6, 8, 10, 12, 14])["Engineering"]
        self.assertEqual((r[1], r[2], r[3], r[4], r[5]), (7, 8, 14, 8.0, 14))   # ceil(3.5)=4th, ceil(6.3)=7th

    def test_single_hire_returns_that_hire_for_every_percentile(self):
        r = self.hires([33])["Engineering"]
        self.assertEqual((r[2], r[3]), (33, 33))

    def test_pending_and_declined_offers_are_excluded(self):
        conn = mini_db()
        m = Mini(conn)
        m.hire("Engineering", "2024-01-01", "2024-02-01")
        m.hire("Engineering", "2024-01-01", "2024-03-01", status="declined")
        m.hire("Engineering", "2024-01-01", None, status="pending")
        self.assertEqual(run(conn, 3)[0][1], 1)


class SuppressionTests(unittest.TestCase):
    def build(self):
        conn = mini_db()
        m = Mini(conn)
        for _ in range(5):
            m.employee("F", level=1, salary=90000)
            m.employee("M", level=1, salary=100000)
        m.employee("F", level=1, salary=1, term="2025-01-01")          # left: must not count
        for _ in range(4):
            m.employee("F", level=2, salary=95000)
        for _ in range(6):
            m.employee("M", level=2, salary=100000)
        for _ in range(5):
            m.employee("F", level=3, salary=110000)
        for _ in range(4):
            m.employee("M", level=3, salary=120000)
        return conn

    def test_cell_of_exactly_five_is_published_and_cell_of_four_is_not(self):
        rows = {r[0]: r for r in run(self.build(), 13)}
        self.assertEqual(rows[1], (1, "5", "5", 90000.0, 100000.0, -10.0, "published"))
        self.assertEqual(rows[2][1:6], ("<5", "6", None, 100000.0, None))
        self.assertEqual(rows[3][1:6], ("5", "<5", 110000.0, None, None))
        self.assertTrue(rows[2][6].startswith("suppressed"))

    def test_no_number_is_shown_for_a_cell_under_five_on_any_dataset(self):
        for conn in (self.build(), fixture.fixture_db(), fixture.seeded_db()):
            for _lvl, women_n, men_n, avg_w, avg_m, gap, note in run(conn, 13):
                if women_n.startswith("<"):
                    self.assertIsNone(avg_w)
                if men_n.startswith("<"):
                    self.assertIsNone(avg_m)
                if women_n.startswith("<") or men_n.startswith("<"):
                    self.assertIsNone(gap)
                    self.assertTrue(note.startswith("suppressed"))
                for shown in (women_n, men_n):
                    self.assertTrue(shown.startswith("<") or int(shown) >= 5)


class AdverseImpactTests(unittest.TestCase):
    def scenario(self, plan):
        """plan: {group: (considered, selected)}; every candidate is female so the gender rows are trivial."""
        conn = mini_db()
        m = Mini(conn)
        req = m.req()
        for group, (considered, selected) in plan.items():
            for i in range(considered):
                a = m.app(req, gender="F", group=group)
                m.event(a, 1, "2024-02-01", "2024-02-05", "advanced" if i < selected else "rejected")
        return {(r[1]): r for r in run(conn, 14) if r[0] == "demographic_group"}

    def test_ratio_below_four_fifths_is_flagged(self):
        rows = self.scenario({"G1": (100, 50), "G2": (100, 30), "G3": (100, 41), "G4": (5, 1)})
        self.assertEqual(rows["G1"][5:9], (50.0, 50.0, 1.0, "pass"))
        self.assertEqual(rows["G2"][5:9], (30.0, 50.0, 0.6, "ADVERSE IMPACT (ratio < 0.80)"))
        self.assertEqual(rows["G3"][5:9], (41.0, 50.0, 0.82, "pass"))
        self.assertEqual(rows["G4"][8], "insufficient data")

    def test_a_ratio_of_exactly_point_eight_passes(self):
        rows = self.scenario({"G1": (100, 50), "G2": (100, 40)})
        self.assertEqual(rows["G2"][7], 0.8)
        self.assertEqual(rows["G2"][8], "pass")

    def test_small_group_cannot_be_the_benchmark(self):
        rows = self.scenario({"G1": (100, 20), "G2": (9, 9)})   # G2 has 100% but only 9 decisions
        self.assertEqual(rows["G1"][8], "pass")
        self.assertEqual(rows["G2"][8], "insufficient data")

    def test_withdrawn_and_open_stages_are_not_decisions(self):
        conn = mini_db()
        m = Mini(conn)
        req = m.req()
        for i, outcome in enumerate(["advanced"] * 10 + ["rejected"] * 10 + ["withdrawn"] * 7):
            a = m.app(req, group="G1")
            m.event(a, 1, "2024-02-01", "2024-02-02", outcome)
        a = m.app(req, group="G1")
        m.event(a, 1, "2024-02-01", None, "open")
        row = [r for r in run(conn, 14) if r[0] == "demographic_group"][0]
        self.assertEqual((row[3], row[4]), (20, 10))


class OrgTreeTests(unittest.TestCase):
    def test_company_root_sees_every_current_employee(self):
        conn = fixture.fixture_db()
        active = conn.execute("SELECT COUNT(*) FROM dim_employee WHERE term_date IS NULL").fetchone()[0]
        root = [r for r in run(conn, 10) if r[0] == 1][0]
        self.assertEqual((root[4], root[5]), (2, active - 1))
        self.assertEqual(len(run(conn, 9)), active)

    def make_loop(self):
        c = fixture.copy_of(fixture.fixture_db())
        c.execute("UPDATE dim_employee SET manager_id = 3 WHERE employee_id = 2")
        c.execute("UPDATE dim_employee SET manager_id = 2 WHERE employee_id = 3")
        c.commit()
        self.addCleanup(c.close)
        return c

    def test_reporting_loop_does_not_hang_the_recursive_tree(self):
        c = self.make_loop()
        rows = run(c, 9)
        self.assertEqual([r[0] for r in rows], [1])    # everyone else hangs below the loop, unreachable from the root
        assert_rows(self, rows, oracles.q09(oracles.World(c)))

    def test_reporting_loop_does_not_hang_the_rollup_and_matches_oracle(self):
        c = self.make_loop()
        got = run(c, 10)
        assert_rows(self, got, oracles.q10(oracles.World(c)))
        self.assertTrue(all(r[5] < 1000 for r in got))

    def test_self_management_is_rejected_by_the_schema(self):
        conn = mini_db()
        with self.assertRaises(sqlite3.IntegrityError):
            Mini(conn).employee(manager=1)

    def test_loop_members_are_reported_by_the_data_quality_query(self):
        c = self.make_loop()
        dq = {r[0]: r[2] for r in run(c, 21)}
        self.assertEqual(dq["manager_loop_members"], 2)


class IslandTests(unittest.TestCase):
    def test_gap_of_31_days_merges_and_32_days_splits_and_nested_spells_do_not_split(self):
        conn = mini_db()
        m = Mini(conn)
        a = m.employee(hire="2023-01-01")
        b = m.employee(hire="2023-01-01")
        c = m.employee(hire="2023-01-01")
        conn.execute("DELETE FROM fact_employment_spell")
        m.spell(a, "2023-01-01", "2023-01-31"); m.spell(a, "2023-03-03", "2023-04-01")      # gap 31 days -> one island
        m.spell(b, "2023-01-01", "2023-01-31"); m.spell(b, "2023-03-04", "2023-04-01")      # gap 32 days -> two islands
        m.spell(c, "2023-01-01", "2023-12-31"); m.spell(c, "2023-02-01", "2023-02-10")      # nested inside the first
        m.spell(c, "2024-01-20", None)                                                      # 20 days after the long spell ends
        rows = {(r[0], r[1]): r for r in run(conn, 15)}
        self.assertEqual(rows[(a, 1)][2:7], ("2023-01-01", "2023-04-01", 2, 90, 0))
        self.assertEqual({k for k in rows if k[0] == b}, {(b, 1), (b, 2)})
        self.assertEqual({k for k in rows if k[0] == c}, {(c, 1)})
        self.assertEqual(rows[(c, 1)][4], 3)
        self.assertEqual(rows[(c, 1)][6], 1)   # the open-ended spell makes the island current

    def test_fixture_employees_with_breaks(self):
        rows = run(fixture.fixture_db(), 15)
        islands = {}
        for emp, island, *_ in rows:
            islands[emp] = max(islands.get(emp, 0), island)
        self.assertEqual((islands[11], islands[20], islands[21], islands[22]), (1, 2, 1, 2))


class RecruiterRankTests(unittest.TestCase):
    def test_tie_gives_equal_rank_with_a_gap_and_equal_dense_rank_without(self):
        rows = {r[0]: r for r in run(fixture.fixture_db(), 5)}
        self.assertEqual([(rows[i][4], rows[i][6], rows[i][7]) for i in (1, 2, 3, 4)],
                         [(3, 1, 1), (3, 1, 1), (2, 3, 2), (0, 4, 3)])
        self.assertEqual([rows[i][8] for i in (1, 2, 3, 4)], [1, 2, 3, 4])    # NTILE(4) of four rows: one each
        self.assertIsNone(rows[4][5])                                         # no requisitions: rate is NULL, not an error


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.conn = mini_db()
        self.m = Mini(self.conn)
        self.req = self.m.req()

    def test_unknown_candidate_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO fact_application VALUES (1, 999, ?, 'Referral', '2024-02-01')", (self.req,))

    def test_same_candidate_cannot_apply_twice_to_one_requisition(self):
        a = self.m.app(self.req)
        cand = self.conn.execute("SELECT candidate_id FROM fact_application WHERE application_id = ?", (a,)).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO fact_application VALUES (99, ?, ?, 'Referral', '2024-02-02')", (cand, self.req))

    def test_stage_name_must_match_its_number(self):
        a = self.m.app(self.req)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO fact_stage_event VALUES (1, ?, 1, 'Onsite', '2024-02-01', NULL, 'open')", (a,))

    def test_open_stage_needs_no_exit_date_and_closed_stage_needs_one(self):
        a = self.m.app(self.req)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO fact_stage_event VALUES (1, ?, 1, 'Applied', '2024-02-01', NULL, 'advanced')", (a,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO fact_stage_event VALUES (2, ?, 1, 'Applied', '2024-02-05', '2024-02-01', 'advanced')", (a,))

    def test_offer_state_rules(self):
        a = self.m.app(self.req)
        with self.assertRaises(sqlite3.IntegrityError):   # pending offer cannot have a decision date
            self.conn.execute("INSERT INTO fact_offer VALUES (1, ?, '2024-02-01', '2024-02-05', 'pending', 1, NULL)", (a,))
        with self.assertRaises(sqlite3.IntegrityError):   # accepted offer needs a start date
            self.conn.execute("INSERT INTO fact_offer VALUES (1, ?, '2024-02-01', '2024-02-05', 'accepted', 1, NULL)", (a,))

    def test_employee_rules(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.employee(level=9)
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.employee(hire="2024-05-01", term="2024-04-01")

    def test_requisition_status_must_agree_with_close_date(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.req(team="Sales", status="open", closed="2024-05-01")

    def test_foreign_key_check_is_clean_on_generated_data(self):
        for conn in (fixture.fixture_db(), fixture.seeded_db()):
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])


def digest(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        for row in conn.execute(f"SELECT * FROM {t} ORDER BY rowid"):
            h.update(repr(row).encode())
    return h.hexdigest()


class SeedingTests(unittest.TestCase):
    def test_reseeding_is_idempotent_and_does_not_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.db"
            first = seed_database(path, 40, 600, seed=5)
            conn = db.connect(path)
            d1 = digest(conn)
            conn.close()
            second = seed_database(path, 40, 600, seed=5)
            conn = db.connect(path)
            d2 = digest(conn)
            self.assertEqual(first, second)
            self.assertEqual(d1, d2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fact_application").fetchone()[0], 600)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.close()

    def test_different_seed_gives_different_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            digests = []
            for s in (1, 2):
                path = Path(tmp) / f"{s}.db"
                seed_database(path, 40, 600, seed=s)
                conn = db.connect(path)
                digests.append(digest(conn))
                conn.close()
            self.assertNotEqual(*digests)

    def test_exact_application_count_and_employee_count(self):
        conn = fixture.seeded_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM fact_application").fetchone()[0], 3000)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dim_employee").fetchone()[0], 150)

    def test_refuses_to_overwrite_a_foreign_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other.db"
            other = sqlite3.connect(path)
            other.execute("CREATE TABLE important (x)")
            other.commit()
            other.close()
            with self.assertRaises(SystemExit):
                seed_database(path, 40, 600)
            other = sqlite3.connect(path)
            self.assertEqual(other.execute("SELECT name FROM sqlite_master").fetchall(), [("important",)])
            other.close()

    def test_synthetic_names_and_emails_are_clearly_fictional(self):
        conn = fixture.seeded_db()
        emails = [r[0] for r in conn.execute("SELECT email FROM dim_candidate")]
        self.assertTrue(all(e.lower().endswith("@example.test") for e in emails))


class DataQualityTests(unittest.TestCase):
    def test_generated_data_passes_every_check(self):
        for conn in (fixture.fixture_db(), fixture.seeded_db()):
            rows = run(conn, 21)
            self.assertEqual(len(rows), 16)
            self.assertTrue(all(r[2] == 0 and r[3] == "pass" for r in rows), [r for r in rows if r[2]])

    def test_injected_defects_are_detected_and_counted_like_the_python_checks(self):
        c = fixture.copy_of(fixture.fixture_db())
        self.addCleanup(c.close)
        c.execute("UPDATE fact_application SET applied_at = '2000-01-01' WHERE application_id = 1")
        c.execute("UPDATE dim_employee SET manager_id = 3 WHERE employee_id = 2")
        c.execute("UPDATE dim_employee SET manager_id = 2 WHERE employee_id = 3")
        c.execute("UPDATE dim_employee SET manager_id = 5 WHERE employee_id = 6")
        c.execute("INSERT INTO fact_performance_review VALUES (9999, 6, 2019, '2019-12-15', 3, 4)")
        c.execute("INSERT INTO fact_employment_spell (employee_id, start_date, end_date) VALUES (6, '2022-01-20', '2022-02-20')")
        c.commit()
        got = {r[0]: r[2] for r in run(c, 21)}
        want = dict(oracles.q21(oracles.World(c)))
        self.assertEqual(got, want)
        for name in ("applied_before_requisition_opened", "stage1_date_differs_from_applied_at", "manager_loop_members",
                     "active_employee_with_departed_manager", "review_outside_tenure", "overlapping_employment_spells"):
            self.assertGreater(got[name], 0, name)
        self.assertEqual(got["manager_loop_members"], 2)


class DuplicateCandidateTests(unittest.TestCase):
    def test_email_variants_collapse_to_one_key(self):
        conn = mini_db()
        m = Mini(conn)
        r1, r2 = m.req("Engineering", "2024-01-01"), m.req("Sales", "2024-01-01")
        m.app(r1, email="Pat.Q@Example.test")
        m.app(r1, email="pat.q+jobs@example.test")
        m.app(r2, email="PAT.Q@EXAMPLE.TEST")
        m.app(r2, email="someone.else@example.test")
        rows = run(conn, 20)
        self.assertEqual(len(rows), 1)
        key, records, first, last, apps, reqs, repeats = rows[0]
        self.assertEqual((key, records, first, last, apps, reqs, repeats), ("pat.q@example.test", 3, 1, 3, 3, 2, 1))


class CohortBoundaryTests(unittest.TestCase):
    def test_leaving_exactly_on_the_checkpoint_day_counts_as_not_retained(self):
        conn = mini_db()
        m = Mini(conn)
        m.employee(hire="2023-01-01", term="2024-01-01")    # leaves on day 365: not retained
        m.employee(hire="2023-01-01", term="2024-01-02")    # leaves on day 366: retained at 12 months
        m.employee(hire="2023-01-01")                        # still here
        row = [r for r in run(conn, 24) if r[0] == "2023-Q1"][0]
        self.assertEqual(row[1], 3)
        self.assertAlmostEqual(row[4], 66.7, delta=0.051)

    def test_young_cohort_shows_null_not_a_misleading_hundred_percent(self):
        conn = mini_db()
        m = Mini(conn)
        m.employee(hire="2025-05-01")                        # only 60 days of history at the as-of date
        row = run(conn, 24)[0]
        self.assertEqual(row[2:], (None, None, None, None, None))

class RepositoryHygieneTests(unittest.TestCase):
    ROOT = db.ROOT

    def text_files(self):
        for p in self.ROOT.rglob("*"):
            rel = p.relative_to(self.ROOT).parts
            if p.is_file() and rel[0] not in ("var", ".git") and "__pycache__" not in rel and p.suffix in (
                    ".py", ".sql", ".md", ".toml", ".yml", ".gitignore", ""):
                yield p

    def test_no_absolute_user_paths_in_the_repository(self):
        needles = ["C:" + "\\Users", "/Users" + "/", "/home" + "/"]
        for p in self.text_files():
            text = p.read_text(encoding="utf-8", errors="ignore")
            for n in needles:
                self.assertNotIn(n, text, f"{p.relative_to(self.ROOT)} contains {n!r}")

    def test_every_query_is_listed_in_the_readme(self):
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        for q in db.load_queries():
            self.assertIn(q.filename, readme)

    def test_code_map_mentions_every_source_file(self):
        code_map = (self.ROOT / "CODE_MAP.md").read_text(encoding="utf-8")
        for p in self.text_files():
            rel = p.relative_to(self.ROOT).as_posix()
            if rel.startswith("sql/queries/"):
                continue
            self.assertIn(rel, code_map, rel)

class QueryFileTests(unittest.TestCase):
    def test_at_least_25_numbered_documented_queries(self):
        queries = db.load_queries()
        self.assertGreaterEqual(len(queries), 25)
        self.assertEqual([q.number for q in queries], list(range(1, len(queries) + 1)))
        for q in queries:
            self.assertTrue(q.question.endswith("?"), q.filename)
            for field in (q.title, q.tables, q.technique, q.edge_cases):
                self.assertTrue(len(field) > 10, q.filename)
            self.assertTrue(q.sql.rstrip().endswith(";"), q.filename)
            body = "".join(ln for ln in q.sql.splitlines() if not ln.startswith("--"))
            self.assertEqual(body.count(";"), 1, q.filename)   # one statement per file

    def test_every_query_has_a_row_on_both_test_databases(self):
        for conn in (fixture.fixture_db(), fixture.seeded_db()):
            for q in db.load_queries():
                self.assertGreater(len(db.run_query(conn, q)[1]), 0, q.filename)

    def test_schema_has_the_required_tables(self):
        names = {r[0] for r in fixture.fixture_db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("dim_date", "dim_employee", "dim_requisition", "dim_recruiter", "fact_application", "fact_stage_event",
                  "fact_offer", "fact_compensation_snapshot", "fact_performance_review"):
            self.assertIn(t, names)


class CliTests(unittest.TestCase):
    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = str(Path(cls.tmp.name) / "cli.db")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--db", cls.db, "seed", "--employees", "40", "--applications", "600", "--seed", "3"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_list_shows_every_query(self):
        code, out = self.call("--db", self.db, "list")
        self.assertEqual(code, 0)
        self.assertEqual(len(re.findall(r"^\s*\d+  ", out, re.M)), len(db.load_queries()))

    def test_run_prints_a_clean_table(self):
        code, out = self.call("--db", self.db, "run", "1")
        self.assertEqual(code, 0)
        self.assertIn("Offer Accepted", out)
        self.assertIn("(6 rows)", out)

    def test_run_limit_and_all(self):
        _, limited = self.call("--db", self.db, "run", "9", "--limit", "3")
        _, everything = self.call("--db", self.db, "run", "9", "--all")
        self.assertIn("more row(s)", limited)
        self.assertNotIn("more row(s)", everything)

    def test_explain_prints_a_plan(self):
        code, out = self.call("--db", self.db, "explain", "9")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(SCAN|SEARCH)")

    def test_report_writes_markdown_with_every_query(self):
        out_path = Path(self.tmp.name) / "report.md"
        self.call("--db", self.db, "report", "--out", str(out_path))
        text = out_path.read_text(encoding="utf-8")
        for q in db.load_queries():
            self.assertIn(f"## Query {q.number:02d}:", text)

    def test_unknown_query_number_is_a_clean_error(self):
        with self.assertRaises(SystemExit):
            self.call("--db", self.db, "run", "99")

    def test_missing_database_is_a_clean_error(self):
        with self.assertRaises(SystemExit):
            self.call("--db", str(Path(self.tmp.name) / "nope.db"), "run", "1")


class PerformanceTests(unittest.TestCase):
    def test_org_tree_uses_the_manager_index(self):
        conn = fixture.seeded_db()
        plan = " ".join(bench.plan(conn, db.get_query(9).sql))
        self.assertIn("idx_employee_manager", plan)

    def test_benchmark_runs_and_restores_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.db"
            seed_database(path, 40, 600, seed=3)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bench.run_bench(path, runs=1, top=3, write=False), 0)
            conn = db.connect(path)
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            conn.close()
            self.assertTrue(set(db.index_names()) <= present)


if __name__ == "__main__":
    unittest.main()
