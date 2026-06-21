"""Interactive SQL shell for MiniDB.

Run with ``python -m minidb.cli [db_path]`` (or the ``minidb`` console script).
Type SQL statements terminated by ``;``. Dot-commands provide introspection:

    .tables            list tables
    .schema [table]    show column definitions
    .stats             buffer-pool hit ratio and page counts
    .help              this help
    .exit / .quit      checkpoint and leave

SELECT results print as an aligned table; everything else prints a status line.
EXPLAIN <select> prints the chosen physical plan.
"""

from __future__ import annotations

import sys
from typing import List

from .engine import Connection, Database
from .sql.executor import ExecResult


def _render_table(columns: List[str], rows: List[List]) -> str:
    if not columns:
        return "(no columns)"
    widths = [len(c) for c in columns]
    str_rows = []
    for row in rows:
        cells = ["NULL" if v is None else str(v) for v in row]
        str_rows.append(cells)
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
    sep = "+".join("-" * (w + 2) for w in widths)
    out = [sep,
           "|".join(f" {c.ljust(widths[i])} " for i, c in enumerate(columns)),
           sep]
    for cells in str_rows:
        out.append("|".join(f" {c.ljust(widths[i])} " for i, c in enumerate(cells)))
    out.append(sep)
    out.append(f"{len(rows)} row(s)")
    return "\n".join(out)


def _print_result(res: ExecResult) -> None:
    if res.kind == "select":
        print(_render_table(res.columns, res.rows))
    else:
        print(res.message or str(res))


def _dot_command(conn: Connection, line: str) -> bool:
    """Handle a .command. Returns False if the shell should exit."""
    parts = line.split()
    cmd = parts[0].lower()
    cat = conn.db.catalog
    if cmd in (".exit", ".quit"):
        return False
    elif cmd == ".help":
        print(__doc__)
    elif cmd == ".tables":
        names = cat.list_tables()
        print("\n".join(names) if names else "(no tables)")
    elif cmd == ".schema":
        targets = parts[1:] or cat.list_tables()
        for name in targets:
            if not cat.has_table(name):
                print(f"no such table: {name}")
                continue
            t = cat.get_table(name)
            cols = ", ".join(
                f"{c.name} {c.type.value}"
                + (" PK" if c.name == t.pk_column else "")
                + ("" if c.nullable else " NOT NULL")
                for c in t.schema.columns)
            idxs = ", ".join(i.name for i in t.indexes.values())
            print(f"{name} ({cols})" + (f"  indexes: {idxs}" if idxs else ""))
    elif cmd == ".stats":
        bp = conn.db.buffer_pool
        print(f"pages on disk : {conn.db.disk.num_pages}")
        print(f"buffer pool   : {bp.pool_size} frames, "
              f"hit ratio {bp.hit_ratio():.2%}")
        print(f"bp stats      : {bp.stats}")
    else:
        print(f"unknown command: {cmd} (try .help)")
    return True


def repl(db: Database) -> None:
    conn = db.connect()
    print("MiniDB shell - type .help for commands, .exit to quit.")
    buffer = ""
    while True:
        prompt = "minidb> " if not buffer else "    ...> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()
        if not buffer and stripped.startswith("."):
            if not _dot_command(conn, stripped):
                break
            continue

        buffer += line + "\n"
        if ";" not in line:
            continue

        statement = buffer.strip()
        buffer = ""
        for chunk in statement.split(";"):
            if not chunk.strip():
                continue
            try:
                _print_result(conn.execute(chunk))
            except Exception as exc:  # noqa: BLE001 - surface any error to the user
                print(f"Error: {exc}")
    db.close()
    print("bye.")


def main(argv: List[str] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else "data/minidb"
    db = Database(path)
    if db.recovery_report is not None and (db.recovery_report.redo_count
                                           or db.recovery_report.losers):
        print(db.recovery_report.summary())
    repl(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
