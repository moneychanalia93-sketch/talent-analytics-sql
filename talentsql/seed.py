"""Reproducible synthetic data generator for a fictional company (Brightloom Inc.).

Everything here is invented: names are built from random syllables, e-mail addresses use the
reserved `.test` domain, and no real person or employer is represented.

Story baked into the data (so the analytics have something to find):
  * requisition openings are seasonal (busy Jan-Mar and Sep-Oct, quiet in August and December)
  * sources differ in quality: referrals convert and perform best, job boards worst
  * an injected screening bias against group G3 so the four-fifths check has something to flag
  * a small unadjusted pay gap for women, applied to every salary
  * about 1% duplicate candidate records (case / "+tag" e-mail variants)
  * about 6% of employees have a leave or re-hire (two employment spells)

The same (employees, applications, seed) triple always yields byte-identical table contents.
"""
from __future__ import annotations

import random
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from . import db as dbmod

AS_OF = date(2025, 12, 31)
FIRST_REQ_DATE = date(2021, 1, 1)
LAST_REQ_DATE = date(2025, 12, 15)
FILL_CUTOFF = date(2025, 10, 31)  # requisitions opened later are never pre-selected to be filled

# team: (headcount weight, pay multiplier, application volume, recruiting group, offer volume, attrition multiplier)
TEAMS = {
    "Engineering": (0.28, 1.15, 1.4, "TA Tech", 1.5, 1.00),
    "Data Science": (0.06, 1.15, 1.0, "TA Tech", 1.3, 1.00),
    "Product": (0.07, 1.10, 0.8, "TA Tech", 1.2, 0.90),
    "Design": (0.05, 1.00, 0.7, "TA Tech", 1.0, 0.90),
    "Sales": (0.17, 0.95, 1.5, "TA GTM", 1.0, 1.40),
    "Marketing": (0.06, 0.95, 0.8, "TA GTM", 0.9, 1.10),
    "Support": (0.14, 0.80, 1.6, "TA GTM", 0.5, 1.50),
    "People Ops": (0.04, 0.95, 0.6, "TA Corporate", 0.8, 0.80),
    "Finance": (0.05, 1.00, 0.6, "TA Corporate", 0.8, 0.70),
    "Operations": (0.08, 0.90, 0.8, "TA Corporate", 0.7, 1.00),
}
ROLES = {
    "Engineering": "Software Engineer", "Data Science": "Data Scientist", "Product": "Product Manager",
    "Design": "Product Designer", "Sales": "Account Executive", "Marketing": "Marketing Specialist",
    "Support": "Support Specialist", "People Ops": "People Partner", "Finance": "Financial Analyst",
    "Operations": "Operations Analyst",
}
LEVEL_BASE = {1: 68000, 2: 85000, 3: 105000, 4: 130000, 5: 160000, 6: 200000, 7: 260000, 8: 350000}
LOCATIONS = {  # location: (weight, pay multiplier)
    "Seattle": (0.20, 1.08), "Austin": (0.14, 1.00), "New York": (0.16, 1.10), "Remote - US": (0.25, 1.00),
    "Toronto": (0.07, 0.92), "London": (0.08, 1.00), "Bengaluru": (0.10, 0.70),
}
# source: (share of applications, conversion multiplier, performance offset, attrition multiplier)
SOURCES = {
    "Referral": (0.10, 2.0, 0.25, 0.7), "LinkedIn": (0.27, 1.0, 0.0, 1.0), "Career Site": (0.20, 0.9, -0.05, 1.0),
    "Job Board": (0.30, 0.55, -0.20, 1.3), "Agency": (0.08, 1.3, 0.05, 1.2), "Campus": (0.05, 1.1, 0.10, 0.9),
}
STAGE_NAMES = {1: "Applied", 2: "Recruiter Screen", 3: "Hiring Manager Screen", 4: "Onsite", 5: "Offer"}
PASS_P = {1: 0.28, 2: 0.50, 3: 0.45, 4: 0.07}  # base chance to advance out of stages 1-4
GENDERS = (("F", 0.43), ("M", 0.52), ("X", 0.05))
GROUPS = (("G1", 0.45), ("G2", 0.25), ("G3", 0.18), ("G4", 0.12))
YEAR_W = {2021: 0.14, 2022: 0.22, 2023: 0.18, 2024: 0.20, 2025: 0.26}
MONTH_W = [1.25, 1.20, 1.15, 1.00, 0.95, 0.90, 0.80, 0.80, 1.15, 1.10, 0.90, 0.50]

_FIRST_A = ["Ka", "Lu", "Mar", "Zen", "Tor", "Nia", "Vel", "Ori", "Sab", "Dar", "Elo", "Fen", "Gia", "Hal", "Ive",
            "Jun", "Kel", "Lor", "Mio", "Nev", "Pri", "Quin", "Rya", "Sol", "Tam", "Ula", "Vik", "Wen", "Xan", "Yor", "Zia"]
_FIRST_B = ["a", "o", "ian", "el", "is", "en", "ar", "on", "ira", "us"]
_LAST_A = ["Ash", "Brook", "Cald", "Dun", "Ever", "Fair", "Glen", "Har", "Ing", "Jar", "Kes", "Lin", "Mor", "Nor",
           "Oak", "Pen", "Quil", "Rav", "Sten", "Thorn", "Ul", "Vard", "Wick", "Yar", "Zell"]
_LAST_B = ["ford", "well", "man", "son", "ley", "stead", "mere", "field", "by", "ton"]


def _wchoice(rng: random.Random, pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def _name(rng: random.Random) -> tuple[str, str]:
    return (rng.choice(_FIRST_A) + rng.choice(_FIRST_B), rng.choice(_LAST_A) + rng.choice(_LAST_B))


def _iso(d: int) -> str:
    return date.fromordinal(d).isoformat()


def _iso_or_none(d: int | None) -> str | None:
    return None if d is None else _iso(d)


def salary(rng: random.Random, level: int, team: str, location: str, gender: str, year: int) -> int:
    """Base salary for a level/team/location, with a small synthetic gender gap and 3%/yr inflation."""
    gender_mult = {"F": 0.975, "M": 1.0, "X": 0.99}[gender]
    value = (LEVEL_BASE[level] * TEAMS.get(team, (0, 1.0))[1] * LOCATIONS[location][1] * gender_mult
             * (1.03 ** (year - 2025)) * rng.uniform(0.93, 1.07))
    return int(round(value / 500.0) * 500)


def populate_dim_date(conn: sqlite3.Connection, first: date = date(2014, 1, 1), last: date = date(2026, 12, 31)) -> None:
    rows = []
    d = first
    while d <= last:
        dow = (d.weekday() + 1) % 7  # 0 = Sunday
        rows.append((d.year * 10000 + d.month * 100 + d.day, d.isoformat(), d.year, (d.month - 1) // 3 + 1,
                     d.month, d.day, dow, 1 if dow in (0, 6) else 0))
        d += timedelta(days=1)
    conn.executemany("INSERT OR IGNORE INTO dim_date VALUES (?,?,?,?,?,?,?,?)", rows)


# ----------------------------------------------------------------------------------------------
# Funnel simulation for one application
# ----------------------------------------------------------------------------------------------
def _dwell(rng: random.Random, stage: int) -> int:
    mu = {1: 1.3, 2: 1.1, 3: 1.6, 4: 1.8}[stage]
    return 1 + int(rng.lognormvariate(mu, 0.6))


def simulate_path(rng, applied: int, cutoff: int, winner: bool, src: str, grp: str, gender: str, team: str):
    """Return (events, offer). events: [stage, entered, exited|None, outcome]. offer: dict or None.

    Everything is clipped to `cutoff` (the requisition close date, or the as-of date): an application
    still in a stage on the cutoff day stays 'open'; one that would run past a close date is rejected on it.
    """
    q = SOURCES[src][1]
    events: list[list] = []
    offer = None
    entered = applied
    closed_req = cutoff < AS_OF.toordinal()  # cutoff is a real requisition close date
    for stage in (1, 2, 3, 4):
        base = PASS_P[stage]
        if stage <= 2:
            p = min(0.95, base * q)
        elif stage == 3:
            p = min(0.95, base * (1 + (q - 1) * 0.5))
        else:
            p = min(0.60, base * (1 + (q - 1) * 0.5) * TEAMS[team][4])
        if stage == 2 and grp == "G3":
            p *= 0.72  # injected screening bias
        if stage == 3 and gender == "F":
            p *= 0.93
        passed = winner or rng.random() < p
        outcome = "advanced" if passed else ("withdrawn" if rng.random() < 0.12 else "rejected")
        exit_ = entered + _dwell(rng, stage)
        if exit_ > cutoff:
            if closed_req:
                events.append([stage, entered, cutoff, "rejected"])
            else:
                events.append([stage, entered, None, "open"])
            return events, None
        events.append([stage, entered, exit_, outcome])
        if outcome != "advanced":
            return events, None
        entered = exit_ + rng.randint(0, 3)
        if entered > cutoff:
            return events, None
    # stage 5: offer
    decided = entered + rng.randint(2, 9)
    offer = {"extended": entered, "decided": None, "status": "pending", "start": None}
    if decided > cutoff and closed_req:  # requisition closed first: the offer lapses on the close date
        offer.update(decided=cutoff, status="expired")
        events.append([5, entered, cutoff, "withdrawn"])
        return events, offer
    if decided > cutoff:
        events.append([5, entered, None, "open"])
        return events, offer
    status = "accepted" if winner else ("declined" if rng.random() < 0.7 else "expired")
    offer.update(decided=decided, status=status)
    if status == "accepted":
        offer["start"] = decided + rng.randint(14, 42)
        events.append([5, entered, decided, "advanced"])
    else:
        events.append([5, entered, decided, "withdrawn"])
    return events, offer


# ----------------------------------------------------------------------------------------------
# Main generator
# ----------------------------------------------------------------------------------------------
def generate(employees: int, applications: int, seed: int) -> dict:
    if employees < 20 or applications < employees:
        raise ValueError("need employees >= 20 and applications >= employees")
    rng = random.Random(seed)
    as_of = AS_OF.toordinal()

    # --- recruiters -------------------------------------------------------------------------
    groups = ["TA Tech", "TA GTM", "TA Corporate"]
    n_rec = max(6, employees // 50)
    recruiters, skill = [], {}
    for i in range(1, n_rec + 1):
        first, last = _name(rng)
        start = date(2018, 1, 1).toordinal() + rng.randint(0, 6 * 365)
        recruiters.append((i, f"{first} {last}", groups[(i - 1) % 3], _iso(start)))
        skill[i] = rng.lognormvariate(0, 0.35)
    rec_by_group = {g: [r[0] for r in recruiters if r[2] == g] for g in groups}

    # --- requisitions (header data only; status/closing decided below) -----------------------
    n_req = max(4, round(employees * 1.1))
    ym = [(y, m) for y in YEAR_W for m in range(1, 13)]
    ym_w = [YEAR_W[y] * MONTH_W[m - 1] for y, m in ym]
    team_names = list(TEAMS)
    reqs = []
    for _ in range(n_req):
        y, m = rng.choices(ym, weights=ym_w)[0]
        dim = (date(y + (m == 12), m % 12 + 1, 1) - date(y, m, 1)).days
        opened = date(y, m, rng.randint(1, dim))
        opened = min(max(opened, FIRST_REQ_DATE), LAST_REQ_DATE)
        team = rng.choices(team_names, weights=[TEAMS[t][0] for t in team_names])[0]
        level = rng.choices([1, 2, 3, 4, 5, 6], weights=[0.22, 0.30, 0.25, 0.13, 0.07, 0.03])[0]
        loc = rng.choices(list(LOCATIONS), weights=[v[0] for v in LOCATIONS.values()])[0]
        rec = rng.choice(rec_by_group[TEAMS[team][3]])
        reqs.append({"opened": opened.toordinal(), "team": team, "level": level, "location": loc, "recruiter": rec})
    reqs.sort(key=lambda r: (r["opened"], r["team"], r["level"]))
    for i, r in enumerate(reqs, 1):
        r.update(id=i, title=f"{ROLES[r['team']]} L{r['level']}", closed=None, status="open", hire_app=None, manager=None)

    # application volume per requisition
    weights = [rng.lognormvariate(0, 0.6) * TEAMS[r["team"]][2] for r in reqs]
    counts = Counter(rng.choices(range(n_req), weights=weights, k=applications))

    # which requisitions are intended to be filled
    target = min(int(employees * 0.62), employees - 12)
    elig = [r for r in reqs if counts[r["id"] - 1] >= 2 and r["opened"] <= FILL_CUTOFF.toordinal()]
    keyed = sorted(elig, key=lambda r: -(rng.random() ** (1.0 / skill[r["recruiter"]])))
    to_fill = {r["id"] for r in keyed[:target]}

    # --- applications, funnel events, offers -------------------------------------------------
    candidates: list[tuple] = []          # (id, name, email, gender, group)
    cand_info: list[tuple] = []           # parallel: (name, gender, group, email)
    apps, events_out, offers_out = [], [], []
    hires = []                            # dicts describing winners who actually start by as_of
    hired_cands: set[int] = set()
    src_names = list(SOURCES)
    src_w = [SOURCES[s][0] for s in src_names]

    def new_candidate() -> int:
        first, last = _name(rng)
        cid = len(candidates) + 1
        email = f"{first}.{last}{rng.randint(1, 999)}@example.test".lower()
        g, grp = _wchoice(rng, GENDERS), _wchoice(rng, GROUPS)
        candidates.append((cid, f"{first} {last}", email, g, grp))
        cand_info.append((f"{first} {last}", g, grp, email))
        return cid

    def duplicate_candidate() -> int:
        base = rng.choice(candidates)
        cid = len(candidates) + 1
        local, domain = base[2].split("@")
        email = rng.choice([f"{local.upper()}@{domain}", f"{local}+jobs@{domain}", f"{local.capitalize()}@{domain.upper()}"])
        candidates.append((cid, base[1], email, base[3], base[4]))
        cand_info.append((base[1], base[3], base[4], email))
        return cid

    for r in reqs:
        n_apps = counts[r["id"] - 1]
        if n_apps == 0:
            continue
        opened = r["opened"]
        # applications for this requisition (attributes first, dates after the close date is known)
        pool = []
        used = set()
        for _ in range(n_apps):
            src = rng.choices(src_names, weights=src_w)[0]
            cid = None
            u = rng.random()
            if u < 0.12 and candidates:
                for _try in range(5):
                    c = rng.randint(1, len(candidates))
                    if c not in used:
                        cid = c
                        break
            elif u < 0.132 and candidates:
                cid = duplicate_candidate()
            if cid is None:
                cid = new_candidate()
            used.add(cid)
            _n, g, grp, _e = cand_info[cid - 1]
            applied = min(opened + min(90, int(rng.expovariate(1 / 18))), as_of)
            pool.append({"cid": cid, "src": src, "g": g, "grp": grp, "applied": applied})

        # decide the close date and the winner
        winner = None
        cutoff = as_of
        if r["id"] in to_fill:
            wts = [SOURCES[a["src"]][1] ** 1.5 if a["cid"] not in hired_cands else 0.0 for a in pool]
            if sum(wts) > 0:
                winner = rng.choices(range(len(pool)), weights=wts)[0]
        win_events = win_offer = None
        if winner is not None:
            a = pool[winner]
            win_events, win_offer = simulate_path(rng, a["applied"], as_of, True, a["src"], a["grp"], a["g"], r["team"])
            if win_offer and win_offer["status"] == "accepted":
                cutoff = win_offer["decided"]
                r["status"], r["closed"] = "filled", cutoff
                hired_cands.add(a["cid"])
            else:
                r["status"] = "open"
        else:
            if opened >= date(2025, 7, 1).toordinal():
                keep_open = rng.random() < 0.5
            else:
                keep_open = rng.random() < 0.06
            if not keep_open:
                cutoff = min(as_of, opened + rng.randint(30, 150))
                r["status"], r["closed"] = "cancelled", cutoff

        # materialise applications
        for i, a in enumerate(pool):
            if a["applied"] > cutoff:
                a["applied"] = opened + rng.randint(0, max(0, cutoff - opened))
            app_id = len(apps) + 1
            apps.append((app_id, a["cid"], r["id"], a["src"], _iso(a["applied"])))
            if i == winner:
                events, offer = win_events, win_offer
            else:
                events, offer = simulate_path(rng, a["applied"], cutoff, False, a["src"], a["grp"], a["g"], r["team"])
            for ev in events:
                events_out.append((len(events_out) + 1, app_id, ev[0], STAGE_NAMES[ev[0]], _iso(ev[1]),
                                   _iso_or_none(ev[2]), ev[3]))
            if offer:
                lvl_sal = salary(rng, r["level"], r["team"], r["location"], a["g"], date.fromordinal(offer["extended"]).year)
                offers_out.append((len(offers_out) + 1, app_id, _iso(offer["extended"]), _iso_or_none(offer["decided"]),
                                   offer["status"], lvl_sal, _iso_or_none(offer["start"])))
                if i == winner and offer["status"] == "accepted" and offer["start"] <= as_of:
                    hires.append({"app": app_id, "cid": a["cid"], "req": r, "start": offer["start"], "salary": lvl_sal,
                                  "src": a["src"]})

    # --- employees ---------------------------------------------------------------------------
    emps = []
    for h in hires:
        name, g, grp, _ = cand_info[h["cid"] - 1]
        r = h["req"]
        emps.append({"name": name, "team": r["team"], "level": r["level"], "loc": r["location"], "g": g, "grp": grp,
                     "hire": h["start"], "app": h["app"], "src": h["src"], "salary": h["salary"], "req": r})
    n_legacy = employees - len(emps)
    n_exec = max(1, round(employees * 0.005))
    for i in range(n_legacy):
        first, last = _name(rng)
        if i == 0:
            level, team, hire = 8, "Executive", date(2015, 1, 5).toordinal()
        else:
            if i <= n_exec:
                level = 7
            else:
                level = rng.choices([1, 2, 3, 4, 5, 6], weights=[0.20, 0.28, 0.24, 0.15, 0.08, 0.045])[0]
            team = team_names[(i - 1) % len(team_names)] if level == 7 else \
                rng.choices(team_names, weights=[TEAMS[t][0] for t in team_names])[0]
            lo, hi = {7: (2015, 2016), 6: (2015, 2017), 5: (2015, 2019), 4: (2015, 2019)}.get(level, (2016, 2020))
            span = date(hi, 12, 31).toordinal() - date(lo, 1, 6).toordinal()
            hire = date(lo, 1, 6).toordinal() + rng.randint(0, span)
        loc = rng.choices(list(LOCATIONS), weights=[v[0] for v in LOCATIONS.values()])[0]
        g, grp = _wchoice(rng, GENDERS), _wchoice(rng, GROUPS)
        emps.append({"name": f"{first} {last}", "team": team, "level": level, "loc": loc, "g": g, "grp": grp,
                     "hire": hire, "app": None, "src": None, "salary": None, "req": None})

    # terminations (decided before managers so a report never outlives its manager)
    for e in emps:
        e["ability"] = rng.gauss(0, 0.5)
        if e["level"] == 8:
            e["term"], e["reason"] = None, None
            continue
        rate = 0.12 * TEAMS.get(e["team"], (0, 1, 0, "", 0, 1.0))[5] * (SOURCES[e["src"]][3] if e["src"] else 1.0)
        rate *= {7: 0.4, 6: 0.6}.get(e["level"], 1.0)
        days = rng.expovariate(1.5 * rate / 365)
        if days >= 365:
            days = 365 + rng.expovariate(rate / 365)
        term = e["hire"] + 1 + int(days)
        if term <= as_of:
            e["term"] = term
            invol = 0.55 if date.fromordinal(term).year == 2023 else 0.30
            e["reason"] = "involuntary" if rng.random() < invol else "voluntary"
        else:
            e["term"], e["reason"] = None, None

    emps.sort(key=lambda e: (e["hire"], e["app"] or 0, e["name"]))
    for i, e in enumerate(emps, 1):
        e["id"] = i
        e["reports"] = 0
        e["manager"] = None

    # managers
    by_level: dict[int, list] = {}
    cap = {2: 10, 3: 10, 4: 10, 5: 10, 6: 8, 7: 12, 8: 10_000}
    ceo = emps[0]
    for e in emps:
        if e is not ceo:
            def ok(m, relax=1):
                return (m["reports"] < cap[m["level"]] * relax
                        and (m["term"] is None or (e["term"] is not None and m["term"] >= e["term"])))
            chosen = None
            if e["level"] < 7:
                cands = [m for lv in (e["level"] + 1, e["level"] + 2) for m in by_level.get(lv, []) if ok(m)]
                same = [m for m in cands if m["team"] == e["team"]]
                if same or cands:
                    chosen = rng.choice(same or cands)
                else:
                    cands = [m for lv in range(e["level"] + 1, 8) for m in by_level.get(lv, []) if ok(m, 2)]
                    chosen = rng.choice(cands) if cands else None
            e["manager"] = (chosen or ceo)["id"]
            (chosen or ceo)["reports"] += 1
        by_level.setdefault(e["level"], []).append(e)

    emp_by_id = {e["id"]: e for e in emps}
    # requisition hiring managers
    by_team_mgr: dict[str, list] = {}
    for e in emps:
        if e["level"] >= 4:
            by_team_mgr.setdefault(e["team"], []).append(e)
    app_to_emp = {e["app"]: e for e in emps if e["app"]}
    for r in reqs:
        hired = [app_to_emp[h["app"]] for h in hires if h["req"] is r]
        if hired:
            r["manager"] = hired[0]["manager"]
        else:
            opts = [m for m in by_team_mgr.get(r["team"], [])
                    if m["hire"] <= r["opened"] and (m["term"] is None or m["term"] >= r["opened"])]
            r["manager"] = rng.choice(opts)["id"] if opts else 1

    # spells, compensation, reviews
    spells, comp, reviews = [], [], []
    for e in emps:
        end = e["term"]
        horizon = end if end is not None else as_of
        tenure = horizon - e["hire"]
        if tenure >= 450 and rng.random() < 0.06:
            s1_end = e["hire"] + rng.randint(120, tenure - 201)
            gap = rng.randint(7, 25) if rng.random() < 0.5 else rng.randint(45, 200)
            spells.append((len(spells) + 1, e["id"], _iso(e["hire"]), _iso(s1_end)))
            spells.append((len(spells) + 1, e["id"], _iso(s1_end + gap), _iso_or_none(end)))
        else:
            spells.append((len(spells) + 1, e["id"], _iso(e["hire"]), _iso_or_none(end)))
        hd = date.fromordinal(e["hire"])
        base = e["salary"] or salary(rng, e["level"], e["team"], e["loc"], e["g"], hd.year)
        bonus = {1: 5, 2: 5, 3: 8, 4: 10, 5: 15, 6: 20, 7: 30, 8: 50}[e["level"]]
        comp.append((e["id"], hd.isoformat(), base, e["level"], bonus))
        y = hd.year + 1
        while date(y, 1, 1).toordinal() <= min(horizon, as_of):
            base = int(round(base * (1 + max(0.0, rng.gauss(0.035, 0.02))) / 100.0) * 100)
            comp.append((e["id"], date(y, 1, 1).isoformat(), base, e["level"], bonus))
            y += 1
        offset = SOURCES[e["src"]][2] if e["src"] else 0.0
        for cy in range(2021, 2026):
            rdate = date(cy, 12, 15).toordinal()
            if e["hire"] <= date(cy, 6, 30).toordinal() and rdate <= as_of and (e["term"] is None or e["term"] >= rdate):
                score = 3.2 + offset + e["ability"] + rng.gauss(0, 0.6)
                reviews.append((len(reviews) + 1, e["id"], cy, _iso(rdate), max(1, min(5, int(round(score)))), e["manager"]))

    employees_out = [(e["id"], e["name"], e["manager"], e["team"], e["level"], e["loc"], e["g"], e["grp"], _iso(e["hire"]),
                      _iso_or_none(e["term"]), e["reason"], e["app"]) for e in emps]
    reqs_out = [(r["id"], r["title"], r["team"], r["level"], r["location"], r["recruiter"], r["manager"], _iso(r["opened"]),
                 _iso_or_none(r["closed"]), r["status"]) for r in reqs]
    return {
        "recruiters": recruiters, "employees": employees_out, "requisitions": reqs_out, "candidates": candidates,
        "applications": apps, "stage_events": events_out, "offers": offers_out, "spells": spells,
        "compensation": comp, "reviews": reviews,
    }


def _table_is_ours(conn: sqlite3.Connection) -> bool:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not names:
        return True
    if "meta" not in names:
        return False
    row = conn.execute("SELECT value FROM meta WHERE key='generator'").fetchone()
    return bool(row) and row[0] == "talentsql"


def _wipe(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    for typ in ("view", "index", "table"):
        for (name,) in conn.execute(f"SELECT name FROM sqlite_master WHERE type='{typ}' AND name NOT LIKE 'sqlite_%'").fetchall():
            conn.execute(f"DROP {typ.upper()} IF EXISTS {name}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def seed_database(db_path: str | Path, employees: int = 2000, applications: int = 100000, seed: int = 42,
                  with_indexes: bool = True) -> dict:
    """Rebuild the database at db_path from scratch. Safe to run repeatedly: the result depends only on the arguments."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(db_path)
    try:
        if not _table_is_ours(conn):
            raise SystemExit(f"{db_path} holds tables that talentsql did not create; refusing to overwrite it.")
        _wipe(conn)
        data = generate(employees, applications, seed)
        dbmod.apply_schema(conn, with_indexes=False)
        populate_dim_date(conn)
        conn.execute("PRAGMA defer_foreign_keys = ON")  # employees, requisitions and applications reference each other
        ins = lambda sql, rows: conn.executemany(sql, rows)  # noqa: E731
        ins("INSERT INTO dim_recruiter VALUES (?,?,?,?)", data["recruiters"])
        ins("INSERT INTO dim_candidate VALUES (?,?,?,?,?)", data["candidates"])
        ins("INSERT INTO dim_employee VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", data["employees"])
        ins("INSERT INTO dim_requisition VALUES (?,?,?,?,?,?,?,?,?,?)", data["requisitions"])
        ins("INSERT INTO fact_application VALUES (?,?,?,?,?)", data["applications"])
        ins("INSERT INTO fact_stage_event VALUES (?,?,?,?,?,?,?)", data["stage_events"])
        ins("INSERT INTO fact_offer VALUES (?,?,?,?,?,?,?)", data["offers"])
        ins("INSERT INTO fact_employment_spell VALUES (?,?,?,?)", data["spells"])
        ins("INSERT INTO fact_compensation_snapshot VALUES (?,?,?,?,?)", data["compensation"])
        ins("INSERT INTO fact_performance_review VALUES (?,?,?,?,?,?)", data["reviews"])
        meta = {"generator": "talentsql", "schema_version": "1", "as_of_date": AS_OF.isoformat(), "seed": str(seed),
                "employees_arg": str(employees), "applications_arg": str(applications), "company": "Brightloom Inc. (fictional)"}
        conn.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
        conn.commit()
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"foreign key violations after seeding: {bad[:5]}")
        if with_indexes:
            dbmod.create_indexes(conn)
        conn.execute("ANALYZE")
        conn.commit()
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (
            "dim_employee", "dim_requisition", "dim_candidate", "dim_recruiter", "fact_application", "fact_stage_event",
            "fact_offer", "fact_employment_spell", "fact_compensation_snapshot", "fact_performance_review", "dim_date")}
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    print(seed_database(dbmod.DEFAULT_DB))
