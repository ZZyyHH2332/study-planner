#!/usr/bin/env python3
"""Data export/import for Study Planner.

Full backup: SQLite database → JSON (all tables + profile)
Review export: review_log → CSV (for external analysis)
Restore: JSON backup → SQLite database

Usage:
  python data_io.py --export              # Full JSON backup
  python data_io.py --export-csv          # Review log CSV
  python data_io.py --import backup.json  # Restore from backup
"""

import json
import sys
import csv
import io
from pathlib import Path
from datetime import datetime, timezone

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager


def export_full(config=None):
    """Export all database tables to a JSON backup.

    Returns: dict with all tables and metadata.
    """
    conn = db_manager.get_connection(config)

    tables = {}
    for table in ["knowledge_nodes", "knowledge_edges", "study_sessions",
                   "review_log", "learner_profile", "profile_history"]:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        tables[table] = [dict(r) for r in rows]

    conn.close()

    backup = {
        "metadata": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
            "table_counts": {t: len(rows) for t, rows in tables.items()},
        },
        "data": tables,
    }
    return backup


def export_to_json(config=None, output_path=None):
    """Export full backup to a JSON file."""
    backup = export_full(config)

    if output_path is None:
        db_path = db_manager.get_db_path(config)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(db_path).parent / f"backup_{timestamp}.json")

    Path(output_path).write_text(
        json.dumps(backup, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    return output_path


def export_review_csv(config=None, output_path=None):
    """Export review_log to CSV for external analysis."""
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT rl.*, kn.title, kn.difficulty, kn.concept_type
           FROM review_log rl
           LEFT JOIN knowledge_nodes kn ON rl.note_id = kn.note_id
           ORDER BY rl.review_date"""
    ).fetchall()
    conn.close()

    if not rows:
        return None

    if output_path is None:
        db_path = db_manager.get_db_path(config)
        output_path = str(Path(db_path).parent / "review_log.csv")

    fieldnames = ["id", "note_id", "title", "session_id", "review_date",
                  "rating", "correct", "prev_mastery", "new_mastery",
                  "prev_interval", "new_interval", "ease_factor",
                  "difficulty", "concept_type", "created_at"]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    return output_path


def import_from_json(backup_path, config=None):
    """Restore database from a JSON backup.

    This will replace all existing data in the database.
    """
    backup = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    data = backup.get("data", backup)

    db_manager.init_database(config)
    conn = db_manager.get_connection(config)
    conn.execute("PRAGMA foreign_keys=OFF")

    for table in ["knowledge_edges", "review_log", "study_sessions",
                   "profile_history", "learner_profile", "knowledge_nodes"]:
        rows = data.get(table, [])
        if not rows:
            continue

        conn.execute(f"DELETE FROM {table}")

        for row in rows:
            cols = list(row.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            conn.execute(
                f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                [row[c] for c in cols]
            )

    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()
    return {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "table_counts": {t: len(rows) for t, rows in data.items()},
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Study Planner data export/import")
    parser.add_argument("--export", action="store_true", help="Full JSON backup")
    parser.add_argument("--export-csv", action="store_true", help="Review log CSV")
    parser.add_argument("--import", dest="import_path", type=str, help="Restore from JSON")
    args = parser.parse_args()

    if args.export:
        path = export_to_json()
        print(f"Backup exported: {path}")
    elif args.export_csv:
        path = export_review_csv()
        if path:
            print(f"CSV exported: {path}")
        else:
            print("No review data to export")
    elif args.import_path:
        result = import_from_json(args.import_path)
        print(f"Import complete: {json.dumps(result, indent=2)}")
    else:
        parser.print_help()
