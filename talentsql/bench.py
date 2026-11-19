"""Benchmark: time every query without and with secondary indexes, then compare the slowest ones.

Only measured numbers are printed or written. Nothing is estimated.
"""
from __future__ import annotations

import os
import platform
import sqlite3
import statistics
import sys
import time
from pathlib import Path

from . import db


def _ram_gb() -> str:
    try:
        if sys.platform == "win32":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            s = MemStatus()
            s.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return f"{s.ullTotalPhys / 2**30:.1f} GB"
        with open("/proc/meminfo", encoding="utf-8") as fh:
            kb = int(fh.readline().split()[1])
        return f"{kb / 2**20:.1f} GB"
    except Exception:  # pragma: no cover - environment dependent
        return "unknown"


def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # pragma: no cover
        pass
    return platform.processor() or "unknown"


def environment() -> dict[str, str]:
    return {
        "CPU": f"{_cpu_name()} ({os.cpu_count()} logical cores)",
        "RAM": _ram_gb(),
        "OS": f"{platform.system()} {platform.release()}",
        "Python": platform.python_version(),
        "SQLite": sqlite3.sqlite_version,
    }


def time_query(conn: sqlite3.Connection, sql: str, runs: int) -> tuple[float, int]:
    """Median wall time in milliseconds over `runs` executions (after one untimed warm-up), and row count."""
    conn.execute(sql).fetchall()
    samples, n = [], 0
    for _ in range(runs):
        t0 = time.perf_counter()
        n = len(conn.execute(sql).fetchall())
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples), n


def plan(conn: sqlite3.Connection, sql: str) -> list[str]:
    return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall()]


def _count(lines: list[str], word: str) -> int:
    return sum(1 for ln in lines if ln.lstrip().startswith(word))


def _table_counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("dim_employee", "fact_application", "fact_stage_event", "fact_offer")}


def run_bench(db_path: Path, runs: int = 5, top: int = 10, write: bool = False) -> int:
    if not db_path.exists():
        raise SystemExit(f"No database at {db_path}. Run: python -m talentsql seed")
    conn = db.connect(db_path)
    queries = db.load_queries()
    try:
        db.drop_indexes(conn)
        conn.execute("ANALYZE")
        before = {q.number: time_query(conn, q.sql, runs) for q in queries}
        slowest = sorted(queries, key=lambda q: -before[q.number][0])[:top]
        plans_before = {q.number: plan(conn, q.sql) for q in slowest}

        db.create_indexes(conn)
        conn.execute("ANALYZE")
        after = {q.number: time_query(conn, q.sql, runs) for q in slowest}
        plans_after = {q.number: plan(conn, q.sql) for q in slowest}
        counts = _table_counts(conn)
    finally:
        # leave the database with its indexes in place whatever happened above
        try:
            db.create_indexes(conn)
        except sqlite3.OperationalError:
            pass
        conn.close()

    env = environment()
    lines = [f"{'#':>2}  {'query':<36}{'no idx ms':>10}{'idx ms':>10}{'speed-up':>10}{'scans':>8}{'searches':>10}"]
    for q in slowest:
        b, a = before[q.number][0], after[q.number][0]
        lines.append(f"{q.number:>2}  {q.slug[:35]:<36}{b:>10.1f}{a:>10.1f}{b / a if a else float('inf'):>9.2f}x"
                     f"{_count(plans_before[q.number], 'SCAN'):>4}>{_count(plans_after[q.number], 'SCAN'):<3}"
                     f"{_count(plans_before[q.number], 'SEARCH'):>6}>{_count(plans_after[q.number], 'SEARCH'):<3}")
    print("\n".join(lines))
    print(f"\n{env['CPU']} | {env['RAM']} RAM | Python {env['Python']} | SQLite {env['SQLite']}")
    if write:
        out = db.ROOT / "docs" / "PERFORMANCE.md"
        out.write_text(_markdown(env, counts, runs, queries, before, after, slowest, plans_before, plans_after), encoding="utf-8")
        print(f"Wrote {out.relative_to(db.ROOT).as_posix()}")
    return 0


def _markdown(env, counts, runs, queries, before, after, slowest, pb, pa) -> str:
    md = ["# Performance", "",
          "Measured with `python -m talentsql bench --write` on the seeded dataset. Every number below was produced by",
          "that command on the machine described here; nothing is estimated. Re-run it to get your own.", "",
          "## Environment", ""]
    md += [f"- **{k}:** {v}" for k, v in env.items()]
    md += ["", "## Dataset", ""]
    md += [f"- `{t}`: {n:,} rows" for t, n in counts.items()]
    md += ["", "## Method", "",
           f"1. Drop every secondary index listed in `sql/indexes.sql` (primary keys and UNIQUE constraints remain), run `ANALYZE`.",
           f"2. Time all {len(queries)} queries: one untimed warm-up, then {runs} timed runs, fetching every row. The **median** is reported.",
           f"3. Take the {len(slowest)} slowest queries. Re-create the indexes, run `ANALYZE`, time those queries again the same way.",
           "4. Capture `EXPLAIN QUERY PLAN` for both states.", "",
           "Timings are single-process wall-clock times on a warm OS cache and will vary run to run. Small queries",
           "(a few milliseconds) are dominated by noise; treat differences under about 20% as unchanged.", "",
           "## Results: the slowest queries, without and with indexes", "",
           "| # | Query | Rows | No secondary indexes (ms) | With indexes (ms) | Speed-up | Plan scans before / after | Plan searches before / after |",
           "|---|---|---|---|---|---|---|---|"]
    for q in slowest:
        b, a = before[q.number][0], after[q.number][0]
        md.append(f"| {q.number:02d} | {q.title} | {before[q.number][1]:,} | {b:.1f} | {a:.1f} | {b / a if a else 0:.2f}x | "
                  f"{_count(pb[q.number], 'SCAN')} / {_count(pa[q.number], 'SCAN')} | "
                  f"{_count(pb[q.number], 'SEARCH')} / {_count(pa[q.number], 'SEARCH')} |")
    gained = sum(1 for q in slowest if before[q.number][0] / max(after[q.number][0], 1e-9) >= 1.2)
    md += ["", f"{gained} of the {len(slowest)} queries ran at least 1.2x faster with indexes; "
               f"{len(slowest) - gained} were within noise or slower. Details and plans follow.", "",
           "## All queries without secondary indexes", "", "| # | Query | Rows | Median ms |", "|---|---|---|---|"]
    for q in sorted(queries, key=lambda x: -before[x.number][0]):
        md.append(f"| {q.number:02d} | {q.title} | {before[q.number][1]:,} | {before[q.number][0]:.1f} |")
    md += ["", "## Query plans (`EXPLAIN QUERY PLAN`)", "",
           "`SCAN t` reads every row of `t`. `SEARCH t USING INDEX i (col=?)` jumps straight to matching rows.",
           "`COVERING INDEX` means the index alone answered the read, without touching the table.", ""]
    for q in slowest:
        md += [f"### Query {q.number:02d}: {q.title}", "", "Without secondary indexes:", "", "```text"]
        md += pb[q.number] + ["```", "", "With indexes:", "", "```text"] + pa[q.number] + ["```", ""]
    return "\n".join(md) + "\n"
