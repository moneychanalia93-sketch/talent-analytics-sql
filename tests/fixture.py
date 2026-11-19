"""A small, fully deterministic dataset (no randomness) used to test every query.

It is built so that each query meets its edge cases: a tie in recruiter hires, a recruiter with no
hires, a manager whose report left with them, two employment spells that merge and two that do not,
cells of 5 and of fewer than 5 people for suppression, open requisitions of different ages, and
candidates entered twice. Expected answers are computed independently in tests/oracles.py.
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from talentsql import db
from talentsql.seed import populate_dim_date, seed_database

AS_OF = "2025-06-30"
STAGE_NAMES = {1: "Applied", 2: "Recruiter Screen", 3: "Hiring Manager Screen", 4: "Onsite", 5: "Offer"}
SOURCES = ["Referral", "LinkedIn", "Career Site", "Job Board", "Agency", "Campus"]
LEVEL_BASE = {1: 70000, 2: 85000, 3: 105000, 4: 130000, 5: 160000, 7: 260000, 8: 350000}
MANAGER_FOR_TEAM = {"Engineering": 4, "Sales": 3, "Design": 2}

D = date.fromisoformat


def iso(d: date) -> str:
    return d.isoformat()


def plus(s: str, days: int) -> str:
    return iso(D(s) + timedelta(days=days))


# id, manager, team, level, location, gender, group, hire, term, reason
LEGACY = [
    (1, None, "Executive", 8, "Seattle", "F", "G1", "2020-01-06", None, None),
    (2, 1, "Engineering", 7, "Seattle", "M", "G1", "2020-02-03", None, None),
    (3, 1, "Sales", 7, "New York", "F", "G2", "2020-03-02", None, None),
    (4, 2, "Engineering", 5, "Seattle", "M", "G1", "2021-01-04", None, None),
    (5, 2, "Engineering", 5, "Seattle", "F", "G2", "2021-02-01", "2024-08-30", "voluntary"),
    (6, 4, "Engineering", 2, "Seattle", "F", "G1", "2022-01-10", None, None),
    (7, 4, "Engineering", 2, "Seattle", "M", "G2", "2022-02-14", None, None),
    (8, 4, "Engineering", 2, "Seattle", "F", "G3", "2022-03-14", None, None),
    (9, 4, "Engineering", 2, "Seattle", "M", "G1", "2022-06-06", None, None),
    (10, 4, "Engineering", 2, "Seattle", "F", "G2", "2022-09-12", "2024-02-29", "involuntary"),
    (11, 4, "Engineering", 3, "Seattle", "M", "G1", "2023-01-09", None, None),
    (12, 3, "Sales", 2, "New York", "F", "G1", "2022-05-02", None, None),
    (13, 3, "Sales", 2, "New York", "M", "G4", "2023-02-06", None, None),
    (14, 3, "Sales", 2, "New York", "F", "G2", "2023-07-03", "2025-01-31", "voluntary"),
    (15, 5, "Engineering", 2, "Seattle", "M", "G1", "2021-06-07", "2024-08-30", "voluntary"),
    (16, 5, "Engineering", 2, "Seattle", "F", "G3", "2022-04-04", "2024-06-28", "involuntary"),
]
for _k in range(6):      # ids 17-22: six women, level 3, Seattle
    LEGACY.append((17 + _k, 4, "Engineering", 3, "Seattle", "F", ("G1", "G2", "G3")[_k % 3], plus("2022-07-01", 7 * _k), None, None))
for _k in range(5):      # ids 23-27: five men, level 3, Seattle
    LEGACY.append((23 + _k, 4, "Engineering", 3, "Seattle", "M", ("G1", "G2", "G4")[_k % 3], plus("2022-08-01", 7 * _k), None, None))
LEGACY += [
    (28, 4, "Engineering", 4, "Austin", "F", "G1", "2022-10-03", None, None),
    (29, 4, "Engineering", 4, "Austin", "F", "G2", "2022-10-10", None, None),
    (30, 4, "Engineering", 4, "Austin", "M", "G1", "2022-10-17", None, None),
    (31, 3, "Sales", 2, "New York", "F", "G1", "2023-03-06", None, None),
    (32, 3, "Sales", 2, "New York", "M", "G3", "2023-03-13", None, None),
    (33, 3, "Sales", 2, "New York", "M", "G2", "2023-03-20", "2024-11-29", "voluntary"),
    (34, 3, "Sales", 2, "New York", "F", "G4", "2023-03-27", "2025-03-31", "involuntary"),
    (35, 3, "Sales", 2, "New York", "X", "G1", "2023-04-03", None, None),
]

# id, team, level, location, recruiter, opened, kind
REQS = [
    (1, "Engineering", 2, "Seattle", 1, "2024-01-08", "filled"),
    (2, "Engineering", 3, "Seattle", 1, "2024-02-05", "filled"),
    (3, "Engineering", 2, "Remote - US", 2, "2024-03-04", "filled"),
    (4, "Sales", 2, "New York", 3, "2024-04-01", "filled"),
    (5, "Sales", 2, "New York", 3, "2024-06-03", "cancelled"),
    (6, "Design", 2, "Austin", 2, "2024-09-02", "filled"),
    (7, "Engineering", 2, "Seattle", 1, "2025-01-06", "open"),
    (8, "Sales", 3, "New York", 3, "2025-03-03", "open"),
    (9, "Engineering", 4, "Seattle", 2, "2025-05-12", "open"),
    (10, "Design", 2, "Austin", 2, "2024-02-05", "open"),
    (11, "Engineering", 2, "Seattle", 1, "2024-10-07", "filled"),
    (12, "Sales", 2, "Remote - US", 3, "2024-11-04", "filled"),
    (13, "Engineering", 3, "Seattle", 2, "2023-09-11", "filled"),
]

# outcome sequences by application index (i % 6); the last item may be replaced by an open stage
PATHS = {
    0: ["rejected"],
    1: ["advanced", "rejected"],
    2: ["advanced", "advanced", "rejected"],
    3: ["advanced", "advanced", "advanced", "rejected"],
    4: ["advanced", "withdrawn"],
    5: ["advanced", "advanced", "advanced", "advanced"],  # reaches the offer stage, declines
}
SPLITS = {  # employee id -> (days in first spell, gap in days)
    11: (300, 15),   # gap of 15 days: one island
    20: (100, 40),   # gap of 40 days: two islands
    21: (90, 31),    # gap of exactly 31 days: still one island
    22: (90, 32),    # gap of 32 days: two islands
}


def build(path: str = ":memory:") -> sqlite3.Connection:
    conn = db.connect(path)
    db.apply_schema(conn, with_indexes=True)
    populate_dim_date(conn, date(2022, 1, 1), date(2026, 12, 31))
    conn.execute("INSERT INTO meta VALUES ('as_of_date', ?)", (AS_OF,))
    conn.execute("INSERT INTO meta VALUES ('generator', 'fixture')")
    conn.execute("PRAGMA defer_foreign_keys = ON")

    conn.executemany("INSERT INTO dim_recruiter VALUES (?,?,?,?)", [
        (1, "Recruiter One", "TA Tech", "2019-01-07"), (2, "Recruiter Two", "TA Tech", "2019-02-04"),
        (3, "Recruiter Three", "TA GTM", "2019-03-04"), (4, "Recruiter Four", "TA GTM", "2023-05-01")])

    candidates, apps, events, offers, hires = [], [], [], [], []
    closed = {}
    for rid, team, level, loc, rec, opened, kind in REQS:
        winner = (rid * 5) % 12 if kind == "filled" else None
        for i in range(12):
            cid = len(candidates) + 1
            gender = ["F", "M", "F", "M", "X"][(i * 3 + rid) % 5]
            group = ["G1", "G2", "G3", "G4", "G1", "G2"][(i + rid) % 6]
            candidates.append((cid, f"Candidate {cid:03d}", f"cand{cid}@example.test", gender, group))
            applied = plus(opened, (i * 3) % 25)
            aid = len(apps) + 1
            apps.append((aid, cid, rid, SOURCES[(i + rid) % 6], applied))
            outcomes = list(PATHS[i % 6]) if i != winner else ["advanced"] * 4
            if i == winner or i % 6 == 5:
                make_offer = True
            else:
                make_offer = False
            entered = applied
            for stage, outcome in enumerate(outcomes, start=1):
                if D(entered) > D(AS_OF):
                    break
                exited = plus(entered, 1 + (i + stage + rid) % 6)
                is_open = kind == "open" and i % 6 == 2 and stage == len(outcomes)
                if is_open or D(exited) > D(AS_OF):
                    events.append((len(events) + 1, aid, stage, STAGE_NAMES[stage], entered, None, "open"))
                    make_offer = False
                    break
                events.append((len(events) + 1, aid, stage, STAGE_NAMES[stage], entered, exited, outcome))
                entered = plus(exited, 1 + (i % 3))
            if make_offer and kind != "cancelled" and D(entered) <= D(AS_OF) and len(outcomes) == 4 and outcomes[-1] == "advanced":
                decided = plus(entered, 3)
                accepted = i == winner
                status = "accepted" if accepted else "declined"
                salary = LEVEL_BASE[level] + 1000 * ((i + rid) % 7)
                start = plus(decided, 21) if accepted else None
                offers.append((len(offers) + 1, aid, entered, decided, status, salary, start))
                events.append((len(events) + 1, aid, 5, "Offer", entered, decided, "advanced" if accepted else "withdrawn"))
                if accepted:
                    closed[rid] = decided
                    hires.append((aid, cid, rid, team, level, loc, gender, group, start, salary))

    employees = [(e[0], f"Employee {e[0]:02d}", e[1], e[2], e[3], e[4], e[5], e[6], e[7], e[8], e[9], None) for e in LEGACY]
    for k, (aid, cid, rid, team, level, loc, gender, group, start, salary) in enumerate(hires):
        eid = 40 + k
        term = reason = None
        if eid % 3 == 0 and D(plus(start, 200)) <= D(AS_OF):
            term, reason = plus(start, 200), "voluntary"
        employees.append((eid, f"Employee {eid:02d}", MANAGER_FOR_TEAM[team], team, level, loc, gender, group, start, term, reason, aid))

    reqs = []
    for rid, team, level, loc, rec, opened, kind in REQS:
        status = {"filled": "filled", "cancelled": "cancelled", "open": "open"}[kind]
        closed_date = closed.get(rid) if kind == "filled" else ("2024-09-02" if kind == "cancelled" else None)
        reqs.append((rid, f"{team} L{level}", team, level, loc, rec, MANAGER_FOR_TEAM.get(team, 2), opened, closed_date, status))

    # duplicate candidates: a pair on different requisitions, a pair on the same requisition, and a triple
    emails = {c[0]: c[2] for c in candidates}
    emails[14] = emails[2].upper()                          # req 1, req 2 apps -> same person
    emails[4] = emails[3].replace("@", "+jobs@")            # same requisition 1
    emails[30], emails[31] = emails[25].upper(), emails[25].replace("@", "+x@")   # triple
    candidates = [(c[0], c[1], emails[c[0]], c[3], c[4]) for c in candidates]

    conn.executemany("INSERT INTO dim_candidate VALUES (?,?,?,?,?)", candidates)
    conn.executemany("INSERT INTO dim_employee VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", employees)
    conn.executemany("INSERT INTO dim_requisition VALUES (?,?,?,?,?,?,?,?,?,?)", reqs)
    conn.executemany("INSERT INTO fact_application VALUES (?,?,?,?,?)", apps)
    conn.executemany("INSERT INTO fact_stage_event VALUES (?,?,?,?,?,?,?)", events)
    conn.executemany("INSERT INTO fact_offer VALUES (?,?,?,?,?,?,?)", offers)

    spells, comp, reviews = [], [], []
    for e in employees:
        eid, mgr, level, gender, hire, term = e[0], e[2], e[4], e[6], e[8], e[9]
        if eid in SPLITS:
            first_days, gap = SPLITS[eid]
            end1 = plus(hire, first_days)
            spells += [(len(spells) + 1, eid, hire, end1), (len(spells) + 2, eid, plus(end1, gap), term)]
        else:
            spells.append((len(spells) + 1, eid, hire, term))
        base = LEVEL_BASE.get(level, 100000) + (eid % 5) * 1000 - (3000 if gender == "F" else 0)
        if eid == 27:
            base += 50000   # a pay outlier among the level-3 Seattle peers
        comp.append((eid, hire, base, level, 10))
        for jan in ("2024-01-01", "2025-01-01"):
            if hire < jan and (term is None or term >= jan):
                base = int(base * 1.04)
                comp.append((eid, jan, base, level, 10))
        for cy in (2023, 2024):
            rdate = f"{cy}-12-15"
            if hire <= f"{cy}-06-30" and (term is None or term >= rdate):
                reviews.append((len(reviews) + 1, eid, cy, rdate, 1 + (eid * 7 + cy) % 5, mgr))
    conn.executemany("INSERT INTO fact_employment_spell VALUES (?,?,?,?)", spells)
    conn.executemany("INSERT INTO fact_compensation_snapshot VALUES (?,?,?,?,?)", comp)
    conn.executemany("INSERT INTO fact_performance_review VALUES (?,?,?,?,?,?)", reviews)
    conn.commit()
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert not bad, bad
    return conn


_CACHE: dict[str, sqlite3.Connection] = {}


def fixture_db() -> sqlite3.Connection:
    if "fixture" not in _CACHE:
        _CACHE["fixture"] = build()
    return _CACHE["fixture"]


def seeded_db() -> sqlite3.Connection:
    """A small database made by the real generator (a different shape from the hand-built fixture)."""
    if "seeded" not in _CACHE:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seeded.db"
            seed_database(path, employees=150, applications=3000, seed=11)
            src = db.connect(path)
            mem = db.connect(":memory:")
            src.backup(mem)
            src.close()
        _CACHE["seeded"] = mem
    return _CACHE["seeded"]

def copy_of(conn: sqlite3.Connection) -> sqlite3.Connection:
    dest = db.connect(":memory:")
    conn.backup(dest)
    return dest


def close_all() -> None:
    for conn in _CACHE.values():
        conn.close()
    _CACHE.clear()
