#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


DEFAULT_DB = Path("python_recognizer/data/app.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear selected SQLite tables or wipe the entire face recognition database.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="Path to the SQLite database file. Default: python_recognizer/data/app.db",
    )
    parser.add_argument(
        "--table",
        action="append",
        default=[],
        help="Table name to clear. Can be passed multiple times.",
    )
    parser.add_argument(
        "--tables",
        default="",
        help="Comma-separated list of tables to clear.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear all user tables in the database.",
    )
    parser.add_argument(
        "--drop-file",
        action="store_true",
        help="Delete the database file entirely instead of clearing rows.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts.",
    )
    return parser.parse_args()


def normalize_table_names(args: argparse.Namespace) -> list[str]:
    tables = list(args.table)
    if args.tables.strip():
        tables.extend(
            table.strip()
            for table in args.tables.split(",")
            if table.strip()
        )
    seen: set[str] = set()
    result: list[str] = []
    for table in tables:
        if table not in seen:
            seen.add(table)
            result.append(table)
    return result


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def confirm(message: str) -> bool:
    answer = input(f"{message} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def clear_tables(db_path: Path, tables: list[str]) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        existing_tables = set(list_user_tables(conn))
        selected = [table for table in tables if table in existing_tables]
        missing = [table for table in tables if table not in existing_tables]

        if not selected:
            raise SystemExit("No matching tables found to clear.")

        for table in selected:
            conn.execute(f'DELETE FROM "{table}"')

        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except sqlite3.OperationalError:
            pass

    if missing:
        print(f"Skipped missing tables: {', '.join(missing)}")
    print(f"Cleared tables: {', '.join(selected)}")


def drop_database_file(db_path: Path) -> None:
    if not db_path.exists():
        print(f"Database file already absent: {db_path}")
        return
    db_path.unlink()
    print(f"Deleted database file: {db_path}")


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    requested_tables = normalize_table_names(args)

    if args.drop_file:
        message = f"This will delete the database file at {db_path}"
        if not args.yes and not confirm(message):
            print("Cancelled.")
            return 1
        drop_database_file(db_path)
        return 0

    if args.all:
        if not db_path.exists():
            raise SystemExit(f"Database file not found: {db_path}")
        with sqlite3.connect(db_path) as conn:
            tables = list_user_tables(conn)
        if not tables:
            print("No tables found.")
            return 0
        message = f"This will clear all tables in {db_path}: {', '.join(tables)}"
        if not args.yes and not confirm(message):
            print("Cancelled.")
            return 1
        clear_tables(db_path, tables)
        return 0

    if not requested_tables:
        raise SystemExit("Choose --all or provide at least one table with --table/--tables.")

    message = f"This will clear tables in {db_path}: {', '.join(requested_tables)}"
    if not args.yes and not confirm(message):
        print("Cancelled.")
        return 1
    clear_tables(db_path, requested_tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
