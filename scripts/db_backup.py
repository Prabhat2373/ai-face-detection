#!/usr/bin/env python3
"""Create a consistent backup of the FaceAgent SQLite database."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from python_recognizer.store import SQLiteStore, get_canonical_db_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the FaceAgent SQLite database.")
    parser.add_argument("--output-dir", default="backups", help="Directory for the backup file.")
    parser.add_argument("--db", default=str(get_canonical_db_path()), help="Source database path.")
    args = parser.parse_args()

    source = Path(args.db).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Database not found: {source}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(args.output_dir).expanduser() / f"app-{timestamp}.db"
    SQLiteStore(source).backup_to(destination)
    print(f"Created database backup: {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
