"""Command line entry point: python -m talentsql seed | list | run | explain | bench | report"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from . import db


def _open(args):
    path = Path(args.db)
    if not path.exists():
        raise SystemExit(f"No database at {path}. Create one first:  python -m talentsql seed")
    return db.connect(path)


def cmd_seed(args) -> int:
    from .seed import seed_database

    counts = seed_database(args.db, args.employees, args.applications, args.seed)
    shown = Path(args.db).resolve()
    try:
        shown = shown.relative_to(db.ROOT)
    except ValueError:
        pass
    print(f"Seeded {shown} (seed={args.seed}, employees={args.employees}, applications={args.applications})")
    for table, n in counts.items():
        print(f"  {table:<28}{n:>10,}")
    return 0


def cmd_list(args) -> int:
    queries = db.load_queries()
    width = max(len(q.title) for q in queries)
    print(f"{'#':>2}  {'Query'.ljust(width)}  Technique")
    for q in queries:
        print(f"{q.number:>2}  {q.title.ljust(width)}  {q.technique[:70]}")
    return 0


def cmd_run(args) -> int:
    q = db.get_query(args.number)
    conn = _open(args)
    cols, rows = db.run_query(conn, q)
    print(f"Query {q.number:02d}: {q.title}")
    print(textwrap.fill("Question: " + q.question, 100))
    print()
    print(db.format_table(cols, rows, None if args.all else args.limit))
    conn.close()
    return 0


def cmd_explain(args) -> int:
    q = db.get_query(args.number)
    conn = _open(args)
    plan = conn.execute("EXPLAIN QUERY PLAN " + q.sql).fetchall()
    print(f"Query {q.number:02d}: {q.title}")
    for _id, parent, _unused, detail in plan:
        print(f"  [{_id:>3}<-{parent:>3}] {detail}")
    conn.close()
    return 0


def cmd_bench(args) -> int:
    from .bench import run_bench

    return run_bench(Path(args.db), runs=args.runs, top=args.top, write=args.write)


def cmd_report(args) -> int:
    from .report import write_report

    out = write_report(Path(args.db), Path(args.out))
    try:
        out = out.resolve().relative_to(db.ROOT)
    except ValueError:
        pass
    print(f"Wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m talentsql", description="People/Talent analytics warehouse in SQL.")
    p.add_argument("--db", default=str(db.DEFAULT_DB), help="SQLite file (default: var/talent.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="(re)build the database with reproducible synthetic data")
    s.add_argument("--employees", type=int, default=2000)
    s.add_argument("--applications", type=int, default=100000)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(fn=cmd_seed)

    s = sub.add_parser("list", help="list the numbered queries")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("run", help="run one query and print a table")
    s.add_argument("number", type=int)
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--all", action="store_true", help="print every row")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("explain", help="show EXPLAIN QUERY PLAN for one query")
    s.add_argument("number", type=int)
    s.set_defaults(fn=cmd_explain)

    s = sub.add_parser("bench", help="time the heaviest queries without and with indexes")
    s.add_argument("--runs", type=int, default=5, help="timed runs per query (median is reported)")
    s.add_argument("--top", type=int, default=10, help="how many of the slowest queries to compare")
    s.add_argument("--write", action="store_true", help="write docs/PERFORMANCE.md")
    s.set_defaults(fn=cmd_bench)

    s = sub.add_parser("report", help="write a Markdown report from the real query output")
    s.add_argument("--out", default=str(db.ROOT / "docs" / "SAMPLE_REPORT.md"))
    s.set_defaults(fn=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
