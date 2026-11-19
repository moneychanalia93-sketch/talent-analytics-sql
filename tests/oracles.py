"""Independent re-implementations of every analytic query in plain Python.

Each oracle reads the raw table rows (plain SELECT *, no joins, no SQL aggregation) and computes the
expected result with dictionaries, loops and the standard library. The tests assert that the SQL
answer equals the oracle answer. Because the two share no code, an error in the SQL logic shows up as
a mismatch rather than being repeated on both sides.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import mean

D = date.fromisoformat
STAGES = {1: "Applied", 2: "Recruiter Screen", 3: "Hiring Manager Screen", 4: "Onsite", 5: "Offer"}


def days(a: str, b: str) -> int:
    return (D(a) - D(b)).days


def plus(s: str, n: int) -> str:
    return (D(s) + timedelta(days=n)).isoformat()


def pct(a, b):
    return None if not b else 100.0 * a / b


def avg(xs):
    xs = [x for x in xs if x is not None]
    return mean(xs) if xs else None


class World:
    """All tables loaded as lists of dicts, plus a few lookups."""

    def __init__(self, conn: sqlite3.Connection):
        def load(table):
            cur = conn.execute(f"SELECT * FROM {table}")
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

        self.emp = load("dim_employee")
        self.req = load("dim_requisition")
        self.rec = load("dim_recruiter")
        self.cand = load("dim_candidate")
        self.app = load("fact_application")
        self.ev = load("fact_stage_event")
        self.offer = load("fact_offer")
        self.spell = load("fact_employment_spell")
        self.comp = load("fact_compensation_snapshot")
        self.review = load("fact_performance_review")
        self.as_of = conn.execute("SELECT value FROM meta WHERE key='as_of_date'").fetchone()[0]
        self.emp_by = {e["employee_id"]: e for e in self.emp}
        self.req_by = {r["requisition_id"]: r for r in self.req}
        self.app_by = {a["application_id"]: a for a in self.app}
        self.cand_by = {c["candidate_id"]: c for c in self.cand}
        self.events_of = defaultdict(list)
        for e in sorted(self.ev, key=lambda e: (e["application_id"], e["stage_order"])):
            self.events_of[e["application_id"]].append(e)
        self.offer_of = {o["application_id"]: o for o in self.offer}

    def active(self):
        return [e for e in self.emp if e["term_date"] is None]

    def accepted(self):
        return [o for o in self.offer if o["status"] == "accepted"]

    def req_of_app(self, app_id):
        return self.req_by[self.app_by[app_id]["requisition_id"]]


def months_between(first: str, last: str):
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ---------------------------------------------------------------------------------------------
def q01(w: World):
    n = Counter(e["stage_order"] for e in w.ev)
    counts = [(k, STAGES[k], n[k]) for k in sorted(STAGES)] + [(6, "Offer Accepted", len(w.accepted()))]
    out = []
    for i, (k, name, c) in enumerate(counts):
        prev = counts[i - 1][2] if i else None
        out.append((k, name, c, pct(c, counts[0][2]), pct(c, prev) if i else None))
    return out


def q02(w: World):
    depth = {}
    for e in w.ev:
        depth[e["application_id"]] = max(depth.get(e["application_id"], 0), e["stage_order"])
    by = defaultdict(list)
    for a in w.app:
        if a["application_id"] in depth:
            by[a["source"]].append(a)
    out = []
    for src, apps in by.items():
        d = [depth[a["application_id"]] for a in apps]
        hires = sum(1 for a in apps if w.offer_of.get(a["application_id"], {}).get("status") == "accepted")
        n = len(apps)
        s2, s3, s4, s5 = (sum(1 for x in d if x >= k) for k in (2, 3, 4, 5))
        out.append((src, n, s2, s3, s4, s5, hires, 100.0 * s2 / n, pct(s5, s4), 1000.0 * hires / n))
    return out


def q03(w: World):
    groups = defaultdict(list)
    for o in w.accepted():
        a = w.app_by[o["application_id"]]
        d = days(o["decided_date"], a["applied_at"])
        groups[w.req_by[a["requisition_id"]]["team"]].append(d)
        groups["ALL"].append(d)
    out = []
    for team, vals in groups.items():
        vals.sort()
        n = len(vals)
        pick = lambda p: vals[(p * n + 99) // 100 - 1]  # noqa: E731  nearest rank = ceil(p*n/100)
        out.append((team, n, pick(50), pick(90), mean(vals), max(vals)))
    return out


def q04(w: World):
    g = defaultdict(lambda: [0, 0])
    for o in w.offer:
        if o["status"] == "pending":
            continue
        team = w.req_of_app(o["application_id"])["team"]
        g[team][0] += 1
        g[team][1] += o["status"] == "accepted"
    out = []
    z = 1.96
    for team, (n, acc) in g.items():
        p = acc / n
        z2 = z * z
        half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
        centre = p + z2 / (2 * n)
        out.append((team, n, acc, 100 * p, 100 * (centre - half) / (1 + z2 / n), 100 * (centre + half) / (1 + z2 / n),
                    "low sample (n<30): treat as indicative only" if n < 30 else "ok"))
    return out


def q05(w: World):
    hires, reqs = Counter(), Counter()
    for r in w.req:
        reqs[r["recruiter_id"]] += 1
    for o in w.accepted():
        hires[w.req_of_app(o["application_id"])["recruiter_id"]] += 1
    rows = [(r["recruiter_id"], r["full_name"], r["team"], reqs[r["recruiter_id"]], hires[r["recruiter_id"]]) for r in w.rec]
    ordered = sorted(rows, key=lambda r: (-r[4], r[0]))
    n = len(ordered)
    size, extra = divmod(n, 4)
    quartile, idx = {}, 0
    for b in range(4):
        take = size + (1 if b < extra else 0)
        for r in ordered[idx:idx + take]:
            quartile[r[0]] = b + 1
        idx += take
    out = []
    for rid, name, team, nreq, nh in rows:
        rank = 1 + sum(1 for r in rows if r[4] > nh)
        dense = 1 + len({r[4] for r in rows if r[4] > nh})
        in_group = 1 + sum(1 for r in rows if r[2] == team and r[4] > nh)
        out.append((rid, name, team, nreq, nh, pct(nh, nreq), rank, dense, quartile[rid], in_group))
    return out


def q06(w: World):
    g = defaultdict(list)
    for r in w.req:
        if r["status"] == "open":
            g[r["team"]].append(days(w.as_of, r["opened_date"]))
    out = []
    for team, ages in g.items():
        b = lambda lo, hi: sum(1 for a in ages if lo <= a <= hi)  # noqa: E731
        out.append((team, len(ages), b(-10**9, 30), b(31, 60), b(61, 90), b(91, 180), b(181, 10**9), mean(ages), max(ages)))
    return out


def q07(w: World):
    first = min(e["hire_date"] for e in w.emp)[:7]
    months = months_between(first, w.as_of[:7])
    ym = lambda s: (int(s[:4]), int(s[5:7]))  # noqa: E731
    hires = Counter(ym(e["hire_date"]) for e in w.emp)
    terms = Counter(ym(e["term_date"]) for e in w.emp if e["term_date"])
    ending = []
    for m in months:  # headcount by direct count, not by running sum
        ending.append(sum(1 for e in w.emp if ym(e["hire_date"]) <= m and (e["term_date"] is None or ym(e["term_date"]) > m)))
    out = []
    for i, m in enumerate(months):
        pctv = None
        if i >= 11:
            t12 = sum(terms[x] for x in months[i - 11:i + 1])
            avg_hc = mean(ending[i - 11:i + 1])
            pctv = pct(t12, avg_hc)
        out.append((f"{m[0]:04d}-{m[1]:02d}", hires[m], terms[m], hires[m] - terms[m], ending[i], pctv))
    return out


def q08(w: World):
    g = defaultdict(list)
    for e in w.emp:
        g[e["hire_date"][:4]].append(e)
    out = []
    for y, es in g.items():
        left = [e for e in es if e["term_date"]]
        out.append((y, len(es), len(left), sum(e["term_reason"] == "voluntary" for e in left),
                    sum(e["term_reason"] == "involuntary" for e in left), 100.0 * len(left) / len(es),
                    avg([days(e["term_date"], e["hire_date"]) for e in left]),
                    sum(1 for e in left if days(e["term_date"], e["hire_date"]) <= 90)))
    return out


def _tree(w: World):
    kids = defaultdict(list)
    for e in w.active():
        if e["manager_id"] is not None:
            kids[e["manager_id"]].append(e["employee_id"])
    out = []
    stack = [(e["employee_id"], 0, f"/{e['employee_id']}/") for e in w.active() if e["manager_id"] is None]
    while stack:
        eid, depth, path = stack.pop()
        out.append((eid, depth, path))
        if depth >= 25:
            continue
        for k in kids[eid]:
            if f"/{k}/" not in path:
                stack.append((k, depth + 1, f"{path}{k}/"))
    return out


def q09(w: World):
    out = []
    for eid, depth, path in sorted(_tree(w), key=lambda t: t[2]):
        e = w.emp_by[eid]
        out.append((eid, "  " * depth + e["full_name"], e["team"], e["level"], depth, path))
    return out


def q10(w: World):
    members = defaultdict(list)  # ancestor -> depths of each descendant
    for e in w.active():
        if e["manager_id"] is None:
            continue
        seen = {e["employee_id"]}
        cur, depth = e["manager_id"], 1
        while True:
            members[cur].append(depth)
            nxt = w.emp_by[cur]["manager_id"]
            if nxt is None or depth >= 30 or nxt in seen | {cur}:
                break
            seen.add(cur)
            cur, depth = nxt, depth + 1
    n_active = len(w.active())
    out = []
    for m, ds in members.items():
        e = w.emp_by[m]
        if e["term_date"] is not None:
            continue
        out.append((m, e["full_name"], e["team"], e["level"], sum(1 for d in ds if d == 1), len(ds), max(ds), 100.0 * len(ds) / n_active))
    return out


def q11(w: World):
    span = Counter()
    for e in w.active():
        m = w.emp_by.get(e["manager_id"])
        if m and m["term_date"] is None:
            span[m["employee_id"]] += 1

    def row(label, vals):
        return (label, len(vals), sum(vals), mean(vals), min(vals), max(vals), sum(v > 8 for v in vals), sum(v < 3 for v in vals))

    by = defaultdict(list)
    for m, n in span.items():
        by[w.emp_by[m]["level"]].append(n)
    out = [row(str(lv), vals) for lv, vals in by.items()]
    out.append(row("ALL", list(span.values())))
    return out


def q12(w: World):
    ratings = defaultdict(list)
    for r in w.review:
        ratings[r["employee_id"]].append(r["rating"])
    cutoff = plus(w.as_of, -365)
    g = defaultdict(list)
    for e in w.emp:
        if e["source_application_id"] is not None:
            g[w.app_by[e["source_application_id"]]["source"]].append(e)
    out = []
    for src, es in g.items():
        rated = [mean(ratings[e["employee_id"]]) for e in es if ratings[e["employee_id"]]]
        elig = [e for e in es if e["hire_date"] <= cutoff]
        ret = [e for e in elig if e["term_date"] is None or e["term_date"] > plus(e["hire_date"], 365)]
        out.append((src, len(es), len(rated), avg(rated), pct(sum(r >= 4 for r in rated), len(rated)), len(elig), len(ret),
                    pct(len(ret), len(elig)), "small sample (<30 rated)" if len(rated) < 30 else "ok"))
    return out


def q13(w: World, min_n: int = 5):
    latest = {}
    for c in w.comp:
        if c["employee_id"] not in latest or c["effective_date"] > latest[c["employee_id"]]["effective_date"]:
            latest[c["employee_id"]] = c
    cells = defaultdict(lambda: {"F": [], "M": []})
    for e in w.active():
        if e["gender"] in ("F", "M"):
            cells[e["level"]][e["gender"]].append(latest[e["employee_id"]]["base_salary"])
    out = []
    for lv, c in cells.items():
        f, m = c["F"], c["M"]
        ok_f, ok_m = len(f) >= min_n, len(m) >= min_n
        out.append((lv, str(len(f)) if ok_f else f"<{min_n}", str(len(m)) if ok_m else f"<{min_n}",
                    mean(f) if ok_f else None, mean(m) if ok_m else None,
                    100.0 * (mean(f) - mean(m)) / mean(m) if ok_f and ok_m else None,
                    "published" if ok_f and ok_m else f"suppressed: fewer than {min_n} people in a cell"))
    return out


def q14(w: World, min_considered: int = 10, threshold: float = 0.8):
    cells = defaultdict(lambda: [0, 0])
    for e in w.ev:
        if e["stage_order"] > 4 or e["outcome"] not in ("advanced", "rejected"):
            continue
        c = w.cand_by[w.app_by[e["application_id"]]["candidate_id"]]
        for dim, grp in (("gender", c["gender"]), ("demographic_group", c["demographic_group"])):
            cells[(dim, e["stage_order"], grp)][0] += 1
            cells[(dim, e["stage_order"], grp)][1] += e["outcome"] == "advanced"
    best = {}
    for (dim, st, grp), (n, s) in cells.items():
        if n >= min_considered:
            best[(dim, st)] = max(best.get((dim, st), 0.0), s / n)
    out = []
    for (dim, st, grp), (n, s) in cells.items():
        rate, b = s / n, best.get((dim, st))
        if n < min_considered:
            flag = "insufficient data"
        elif not b:
            flag = "n/a"
        elif rate / b < threshold:
            flag = "ADVERSE IMPACT (ratio < 0.80)"
        else:
            flag = "pass"
        out.append((dim, grp, STAGES[st], n, s, 100 * rate, None if b is None else 100 * b, rate / b if b else None, flag))
    return out


def q15(w: World):
    by = defaultdict(list)
    for s in w.spell:
        by[s["employee_id"]].append(s)
    out = []
    for eid, spells in by.items():
        spells.sort(key=lambda s: s["start_date"])
        islands, prev_max = [], None
        for s in spells:
            end = s["end_date"] or w.as_of
            if prev_max is None or days(s["start_date"], prev_max) > 31:
                islands.append([])
            islands[-1].append((s["start_date"], end, s["end_date"] is None))
            prev_max = end if prev_max is None else max(prev_max, end)
        for n, isl in enumerate(islands, start=1):
            start, end = min(i[0] for i in isl), max(i[1] for i in isl)
            out.append((eid, n, start, end, len(isl), days(end, start), 1 if any(i[2] for i in isl) else 0))
    return out


def q16(w: World):
    g = defaultdict(lambda: {"dwell": [], "wait": [], "next": []})
    for evs in w.events_of.values():
        for i, e in enumerate(evs):
            if e["exited_at"] is None:
                continue
            row = g[e["stage_order"]]
            row["dwell"].append(days(e["exited_at"], e["entered_at"]))
            if i > 0 and evs[i - 1]["exited_at"] is not None:
                row["wait"].append(days(e["entered_at"], evs[i - 1]["exited_at"]))
            if i + 1 < len(evs):
                row["next"].append(days(evs[i + 1]["entered_at"], e["entered_at"]))
    return [(k, STAGES[k], len(v["dwell"]), mean(v["dwell"]), avg(v["wait"]), avg(v["next"]), max(v["dwell"])) for k, v in g.items()]


def q17(w: World):
    g = defaultdict(lambda: [0, 0, 0, 0])
    for e in w.emp:
        if e["source_application_id"] is not None:
            g[e["team"]][(int(e["hire_date"][5:7]) - 1) // 3] += 1
    return [(t, *q, sum(q), 100.0 * q[0] / sum(q)) for t, q in g.items()]


def q18(w: World):
    g = defaultdict(Counter)
    for o in w.accepted():
        a = w.app_by[o["application_id"]]
        g[w.req_by[a["requisition_id"]]["team"]][a["source"]] += 1
    out = []
    for team, c in g.items():
        total = sum(c.values())
        for rank, (src, n) in enumerate(sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:3], start=1):
            out.append((team, rank, src, n, 100.0 * n / total))
    return out


def q19(w: World):
    ym = lambda s: (int(s[:4]), int(s[5:7]))  # noqa: E731
    counts = Counter(ym(a["applied_at"]) for a in w.app)
    months = months_between(min(a["applied_at"] for a in w.app), max(a["applied_at"] for a in w.app))
    vals = [counts[m] for m in months]
    out = []
    for i, m in enumerate(months):
        prior = vals[i - 12] if i >= 12 else None
        out.append((f"{m[0]:04d}-{m[1]:02d}", vals[i], mean(vals[i - 2:i + 1]) if i >= 2 else None, prior,
                    100.0 * (vals[i] - prior) / prior if prior else None))
    return out


def _norm_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local.split("+")[0] + "@" + domain).lower() if "+" in local else email.lower()


def q20(w: World):
    g = defaultdict(list)
    for c in w.cand:
        g[_norm_email(c["email"])].append(c["candidate_id"])
    apps = defaultdict(list)
    for a in w.app:
        apps[a["candidate_id"]].append(a["requisition_id"])
    out = []
    for key, ids in g.items():
        if len(ids) < 2:
            continue
        reqs = [r for i in ids for r in apps[i]]
        out.append((key, len(ids), min(ids), max(ids), len(reqs), len(set(reqs)), len(reqs) - len(set(reqs))))
    return out


def dq_counts(w: World) -> dict[str, int]:
    r: dict[str, int] = {}
    r["stage_events_have_gaps"] = sum(1 for evs in w.events_of.values() if len(evs) != max(e["stage_order"] for e in evs))
    n = 0
    for evs in w.events_of.values():
        for prev, cur in zip(evs, evs[1:]):
            if prev["exited_at"] is not None and cur["entered_at"] < prev["exited_at"]:
                n += 1
    r["stage_overlap"] = n
    r["applied_before_requisition_opened"] = sum(1 for a in w.app if a["applied_at"] < w.req_by[a["requisition_id"]]["opened_date"])
    r["stage1_date_differs_from_applied_at"] = sum(1 for e in w.ev if e["stage_order"] == 1 and e["entered_at"] != w.app_by[e["application_id"]]["applied_at"])
    has5 = {e["application_id"] for e in w.ev if e["stage_order"] == 5}
    r["offer_and_offer_stage_disagree"] = sum(1 for o in w.offer if o["application_id"] not in has5) + sum(
        1 for a in has5 if a not in w.offer_of)
    emp_apps = {e["source_application_id"] for e in w.emp if e["source_application_id"] is not None}
    r["accepted_offer_without_employee"] = sum(1 for o in w.accepted() if o["start_date"] <= w.as_of and o["application_id"] not in emp_apps)
    r["hire_date_differs_from_offer_start"] = sum(1 for e in w.emp if e["source_application_id"] in w.offer_of
                                                  and e["hire_date"] != w.offer_of[e["source_application_id"]]["start_date"])
    acc_by_req = Counter(w.app_by[o["application_id"]]["requisition_id"] for o in w.accepted())
    r["filled_requisition_without_accepted_offer"] = sum(1 for q in w.req if q["status"] == "filled" and acc_by_req[q["requisition_id"]] == 0)
    r["requisition_with_multiple_accepted_offers"] = sum(1 for v in acc_by_req.values() if v > 1)
    sp = defaultdict(list)
    for s in w.spell:
        sp[s["employee_id"]].append(s)
    bad = 0
    for e in w.emp:
        ss = sp.get(e["employee_id"])
        if not ss or min(s["start_date"] for s in ss) != e["hire_date"] or \
                max(s["end_date"] or "9999-12-31" for s in ss) != (e["term_date"] or "9999-12-31"):
            bad += 1
    r["employee_dates_differ_from_spells"] = bad
    over = 0
    for ss in sp.values():
        ss.sort(key=lambda s: s["start_date"])
        for cur, nxt in zip(ss, ss[1:]):
            if cur["end_date"] is None or nxt["start_date"] <= cur["end_date"]:
                over += 1
    r["overlapping_employment_spells"] = over
    r["review_outside_tenure"] = sum(1 for v in w.review if v["review_date"] < w.emp_by[v["employee_id"]]["hire_date"]
                                     or (w.emp_by[v["employee_id"]]["term_date"] and v["review_date"] > w.emp_by[v["employee_id"]]["term_date"]))
    r["compensation_outside_tenure"] = sum(1 for c in w.comp if c["effective_date"] < w.emp_by[c["employee_id"]]["hire_date"]
                                           or (w.emp_by[c["employee_id"]]["term_date"] and c["effective_date"] > w.emp_by[c["employee_id"]]["term_date"]))
    loops = 0
    for e in w.emp:
        cur, d = e["manager_id"], 1
        while cur is not None and d <= 50:
            if cur == e["employee_id"]:
                loops += 1
                break
            cur, d = w.emp_by[cur]["manager_id"], d + 1
    r["manager_loop_members"] = loops
    r["active_employee_with_departed_manager"] = sum(1 for e in w.emp if e["term_date"] is None and e["manager_id"] is not None
                                                     and w.emp_by[e["manager_id"]]["term_date"] is not None)
    r["manager_hired_after_report"] = sum(1 for e in w.emp if e["manager_id"] is not None
                                          and w.emp_by[e["manager_id"]]["hire_date"] > e["hire_date"])
    return r


def q21(w: World):
    return [(name, n) for name, n in dq_counts(w).items()]


def q22(w: World):
    ym = Counter((int(a["applied_at"][:4]), int(a["applied_at"][5:7])) for a in w.app)
    by = defaultdict(list)
    for (y, m), n in ym.items():
        by[m].append(n)
    avgs = {m: mean(v) for m, v in by.items()}
    overall = mean(avgs.values())
    return [(m, len(by[m]), sum(by[m]), avgs[m], avgs[m] / overall) for m in avgs]


def q23(w: World):
    g = defaultdict(list)
    for r in w.req:
        g[r["team"]].append(r)
    out = []
    for team, rs in g.items():
        f = [r for r in rs if r["status"] == "filled"]
        c = [r for r in rs if r["status"] == "cancelled"]
        out.append((team, len(rs), len(f), len(c), sum(r["status"] == "open" for r in rs), pct(len(f), len(f) + len(c)),
                    avg([days(r["closed_date"], r["opened_date"]) for r in f])))
    return out


def q24(w: World):
    g = defaultdict(list)
    for e in w.emp:
        g[f"{e['hire_date'][:4]}-Q{(int(e['hire_date'][5:7]) + 2) // 3}"].append(e)
    out = []
    for cohort, es in g.items():
        row = [cohort, len(es)]
        for k in (90, 180, 365, 545, 730):
            elig = [e for e in es if e["hire_date"] <= plus(w.as_of, -k)]
            kept = [e for e in elig if e["term_date"] is None or e["term_date"] > plus(e["hire_date"], k)]
            row.append(pct(len(kept), len(elig)))
        out.append(tuple(row))
    return out


def q25(w: World):
    latest = {}
    for c in w.comp:
        if c["employee_id"] not in latest or c["effective_date"] > latest[c["employee_id"]]["effective_date"]:
            latest[c["employee_id"]] = c
    cur = [(e, latest[e["employee_id"]]["base_salary"]) for e in w.active()]
    peers = defaultdict(list)
    for e, s in cur:
        peers[(e["level"], e["location"])].append(s)
    out = []
    for e, s in cur:
        ps = peers[(e["level"], e["location"])]
        if len(ps) < 5:
            continue
        ratio = s / mean(ps)
        if 0.85 <= ratio <= 1.15:
            continue
        prank = sum(1 for x in ps if x < s) / (len(ps) - 1)
        out.append((e["employee_id"], e["full_name"], e["team"], e["level"], e["location"], s, len(ps), mean(ps), ratio,
                    100.0 * prank, "below range" if ratio < 0.85 else "above range"))
    return out


def q26(w: World):
    rej = {k: sum(1 for e in w.ev if e["stage_order"] == k and e["outcome"] == "rejected") for k in STAGES}
    wd = {k: sum(1 for e in w.ev if e["stage_order"] == k and e["outcome"] == "withdrawn") for k in STAGES}
    total = sum(rej.values())
    out, run = [], 0
    for k in sorted(STAGES, key=lambda k: (-rej[k], k)):
        run += rej[k]
        out.append((STAGES[k], rej[k], wd[k], pct(rej[k], total), pct(run, total)))
    return out


def q27(w: World):
    g = defaultdict(list)
    for e in w.ev:
        if e["outcome"] == "open":
            g[e["stage_order"]].append(days(w.as_of, e["entered_at"]))
    out = []
    for k in sorted(STAGES):
        v = g[k]
        out.append((k, STAGES[k], len(v), avg(v), max(v) if v else None, sum(x > 14 for x in v), sum(x > 30 for x in v)))
    return out


def q28(w: World):
    ratings = defaultdict(list)
    for r in w.review:
        ratings[r["employee_id"]].append(r["rating"])
    reps = [e for e in w.emp if e["manager_id"] is not None]
    org = sum(1 for e in reps if e["term_date"]) / len(reps)
    g = defaultdict(list)
    for e in reps:
        g[e["manager_id"]].append(e)
    out = []
    for m, es in g.items():
        if len(es) < 5:
            continue
        left = sum(1 for e in es if e["term_date"])
        rate = left / len(es)
        rated = [mean(ratings[e["employee_id"]]) for e in es if ratings[e["employee_id"]]]
        mgr = w.emp_by[m]
        flag = "high attrition" if rate > 1.5 * org else "low attrition" if rate < 0.5 * org else "in range"
        out.append((m, mgr["full_name"], mgr["team"], mgr["level"], len(es), left, 100 * rate, 100 * org, avg(rated), flag))
    return out


ORACLES = {i: globals()[f"q{i:02d}"] for i in range(1, 29)}
