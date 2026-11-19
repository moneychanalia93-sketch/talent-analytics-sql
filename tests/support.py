"""Shared test helpers: running queries, comparing rows, and tiny hand-built databases."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from talentsql import db
from talentsql.seed import populate_dim_date


def run(conn: sqlite3.Connection, number: int) -> list[tuple]:
    return db.run_query(conn, db.get_query(number))[1]


def assert_rows(tc: unittest.TestCase, got, want, key=(0,), tol=0.0051, cols=None):
    """Compare two row lists ignoring order. `key` = column positions that identify a row.
    `tol` is a float, or a dict {column_index: tolerance} (default 0.0051 covers 2-3 dp rounding)."""
    if cols is not None:
        got = [tuple(r[i] for i in cols) for r in got]
    k = lambda r: tuple(str(r[i]) for i in key)  # noqa: E731
    got, want = sorted(got, key=k), sorted(want, key=k)
    tc.assertEqual(len(got), len(want), f"row count: SQL {len(got)} vs oracle {len(want)}")
    for g, w in zip(got, want):
        tc.assertEqual(len(g), len(w), f"column count: {g} vs {w}")
        for i, (a, b) in enumerate(zip(g, w)):
            if a is None or b is None:
                tc.assertIs(a, b, f"column {i}: SQL {a!r} vs oracle {b!r} in row SQL={g} oracle={w}")
            elif isinstance(a, float) or isinstance(b, float):
                t = tol.get(i, 0.0051) if isinstance(tol, dict) else tol
                tc.assertAlmostEqual(a, b, delta=t, msg=f"column {i} in row SQL={g} oracle={w}")
            else:
                tc.assertEqual(a, b, f"column {i} in row SQL={g} oracle={w}")


_OPEN: list = []


def close_minis() -> None:
    while _OPEN:
        _OPEN.pop().close()


def mini_db(as_of: str = "2025-06-30") -> sqlite3.Connection:
    """An empty schema with one recruiter, one requisition per team on demand, and the as-of date."""
    conn = db.connect(":memory:")
    _OPEN.append(conn)
    db.apply_schema(conn, with_indexes=True)
    populate_dim_date(conn, date(2022, 1, 1), date(2026, 12, 31))
    conn.execute("INSERT INTO meta VALUES ('as_of_date', ?)", (as_of,))
    conn.execute("INSERT INTO dim_recruiter VALUES (1, 'Recruiter One', 'TA Tech', '2020-01-01')")
    return conn


class Mini:
    """Insert helpers for tiny scenarios. Ids are handed out in order."""

    def __init__(self, conn):
        self.c = conn
        self.n_emp = self.n_req = self.n_cand = self.n_app = self.n_ev = self.n_offer = 0
        self.reqs: dict[str, int] = {}

    def req(self, team="Engineering", opened="2024-01-01", status="open", closed=None, level=2):
        key = f"{team}|{opened}|{status}|{level}"
        if key not in self.reqs:
            self.n_req += 1
            self.c.execute("INSERT INTO dim_requisition VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (self.n_req, f"{team} L{level}", team, level, "Seattle", 1, None, opened, closed, status))
            self.reqs[key] = self.n_req
        return self.reqs[key]

    def candidate(self, gender="F", group="G1", email=None):
        self.n_cand += 1
        self.c.execute("INSERT INTO dim_candidate VALUES (?,?,?,?,?)",
                       (self.n_cand, f"Cand {self.n_cand}", email or f"c{self.n_cand}@example.test", gender, group))
        return self.n_cand

    def app(self, req_id, applied="2024-02-01", source="LinkedIn", **cand):
        cid = self.candidate(**cand)
        self.n_app += 1
        self.c.execute("INSERT INTO fact_application VALUES (?,?,?,?,?)", (self.n_app, cid, req_id, source, applied))
        return self.n_app

    def event(self, app_id, stage, entered, exited, outcome):
        names = {1: "Applied", 2: "Recruiter Screen", 3: "Hiring Manager Screen", 4: "Onsite", 5: "Offer"}
        self.n_ev += 1
        self.c.execute("INSERT INTO fact_stage_event VALUES (?,?,?,?,?,?,?)",
                       (self.n_ev, app_id, stage, names[stage], entered, exited, outcome))

    def hire(self, team, applied, decided, status="accepted"):
        """An application with an offer decided on `decided`."""
        r = self.req(team)
        a = self.app(r, applied)
        self.n_offer += 1
        start = decided if status == "accepted" else None
        self.c.execute("INSERT INTO fact_offer VALUES (?,?,?,?,?,?,?)",
                       (self.n_offer, a, applied, decided if status != "pending" else None, status, 100000, start))
        return a

    def employee(self, gender="F", level=1, hire="2024-01-01", term=None, manager=None, team="Engineering",
                 location="Seattle", group="G1", salary=100000):
        self.n_emp += 1
        self.c.execute("INSERT INTO dim_employee VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.n_emp, f"Emp {self.n_emp}", manager, team, level, location, gender, group, hire, term,
                        "voluntary" if term else None, None))
        self.c.execute("INSERT INTO fact_compensation_snapshot VALUES (?,?,?,?,?)", (self.n_emp, hire, salary, level, 10))
        self.c.execute("INSERT INTO fact_employment_spell VALUES (?,?,?,?)", (self.n_emp, self.n_emp, hire, term))
        return self.n_emp

    def spell(self, emp_id, start, end):
        self.c.execute("INSERT INTO fact_employment_spell (employee_id, start_date, end_date) VALUES (?,?,?)", (emp_id, start, end))
