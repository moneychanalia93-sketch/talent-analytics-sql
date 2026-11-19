"""Database helpers: connect, apply schema/indexes, load and run the numbered query files."""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
QUERY_DIR = SQL_DIR / "queries"
DEFAULT_DB = ROOT / "var" / "talent.db"

HEADER_KEYS = ("Title", "Business question", "Tables", "Technique", "Edge cases")


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("SELECT sqrt(4)")
    except sqlite3.OperationalError:  # SQLite built without SQLITE_ENABLE_MATH_FUNCTIONS
        conn.create_function("sqrt", 1, lambda x: None if x is None else math.sqrt(x), deterministic=True)
    return conn

def apply_schema(conn: sqlite3.Connection, with_indexes: bool = True) -> None:
    conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    if with_indexes:
        create_indexes(conn)


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript((SQL_DIR / "indexes.sql").read_text(encoding="utf-8"))


def index_names() -> list[str]:
    text = (SQL_DIR / "indexes.sql").read_text(encoding="utf-8")
    return re.findall(r"CREATE INDEX (\w+)", text)


def drop_indexes(conn: sqlite3.Connection) -> None:
    for name in index_names():
        conn.execute(f"DROP INDEX IF EXISTS {name}")


@dataclass(frozen=True)
class Query:
    number: int
    slug: str
    path: Path
    title: str
    question: str
    tables: str
    technique: str
    edge_cases: str
    sql: str

    @property
    def filename(self) -> str:
        return self.path.name


def parse_header(text: str) -> dict[str, str]:
    """Read the leading `-- Key: value` comment block. Indented `--   text` lines continue a value."""
    fields: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if not line.startswith("--"):
            break
        body = line[2:]
        m = re.match(r"\s?([A-Za-z ]+):\s*(.*)$", body)
        if m and m.group(1) in HEADER_KEYS and not body.startswith("   "):
            current = m.group(1)
            fields[current] = m.group(2).strip()
        elif current and body.strip():
            fields[current] += " " + body.strip()
    return fields


def load_queries() -> list[Query]:
    queries = []
    for path in sorted(QUERY_DIR.glob("[0-9][0-9]_*.sql")):
        text = path.read_text(encoding="utf-8")
        h = parse_header(text)
        missing = [k for k in HEADER_KEYS if not h.get(k)]
        if missing:
            raise ValueError(f"{path.name}: missing header field(s) {missing}")
        number = int(path.name[:2])
        queries.append(Query(number, path.stem[3:], path, h["Title"], h["Business question"],
                             h["Tables"], h["Technique"], h["Edge cases"], text))
    return queries


def get_query(number: int) -> Query:
    for q in load_queries():
        if q.number == number:
            return q
    raise SystemExit(f"No query numbered {number}. Run `python -m talentsql list`.")


def run_sql(conn: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple]]:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def run_query(conn: sqlite3.Connection, q: Query) -> tuple[list[str], list[tuple]]:
    return run_sql(conn, q.sql)


def _cell(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 1e15 else str(v)
    return str(v)


def format_table(cols: list[str], rows: list[tuple], limit: int | None = 25, width: int = 44) -> str:
    shown = rows if limit is None else rows[:limit]
    body = [[_cell(v)[:width] for v in r] for r in shown]
    widths = [max([len(c)] + [len(r[i]) for r in body]) for i, c in enumerate(cols)]
    numeric = [all(isinstance(r[i], (int, float)) or r[i] is None for r in shown) and bool(shown)
               for i in range(len(cols))]

    def fmt(vals):
        return "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(vals, widths, numeric))

    lines = [fmt(cols), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in body]
    if limit is not None and len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more row(s); use --all to print every row")
    lines.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)


def markdown_table(cols: list[str], rows: list[tuple], limit: int = 12) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows[:limit]:
        out.append("| " + " | ".join(_cell(v).replace("|", "\\|")[:60] for v in r) + " |")
    if len(rows) > limit:
        out.append(f"\n_{len(rows) - limit} more row(s) not shown ({len(rows)} total)._")
    return "\n".join(out)
