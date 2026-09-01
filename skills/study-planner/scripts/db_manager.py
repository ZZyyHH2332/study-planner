#!/usr/bin/env python3
"""SQLite database manager for Study Planner plugin.

Handles database initialization, connection management, and common operations.
All tables are created from the schema defined in the plan.
"""

import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone


def load_config(config_path=None):
    """Load plugin configuration from config.json.

    Falls back to a default path relative to this script if not specified.
    """
    if config_path is None:
        script_dir = Path(__file__).resolve().parent
        config_path = script_dir.parent.parent.parent / "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db_path(config=None):
    """Get the database file path from config."""
    if config is None:
        config = load_config()
    db_path = Path(config["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)


def get_connection(config=None):
    """Get a SQLite connection with recommended pragmas."""
    db_path = get_db_path(config)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(config=None):
    """Create all tables if they don't exist.

    Tables:
      - knowledge_nodes: Permanent Notes as graph nodes
      - knowledge_edges: prerequisite/related edges between nodes
      - study_sessions: learning session records
      - review_log: flashcard review and self-test records
      - learner_profile: key-value store for holistic learner state
      - profile_history: append-only history of profile changes
    """
    conn = get_connection(config)
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS knowledge_nodes (
        note_id         TEXT PRIMARY KEY,
        title           TEXT,
        difficulty      INTEGER,
        concept_type    TEXT,
        mastery         REAL DEFAULT 0.1,
        learning_state  TEXT DEFAULT 'pending',
        file_path       TEXT,
        last_synced     TEXT,
        ease_factor     REAL DEFAULT 2.5,
        review_count    INTEGER DEFAULT 0,
        last_reviewed   TEXT,
        next_review     TEXT
    );

    CREATE TABLE IF NOT EXISTS knowledge_edges (
        source_id   TEXT NOT NULL,
        target_id   TEXT NOT NULL,
        edge_type   TEXT DEFAULT 'prerequisite',
        weight      REAL DEFAULT 1.0,
        PRIMARY KEY (source_id, target_id)
    );

    CREATE TABLE IF NOT EXISTS study_sessions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time      TEXT NOT NULL,
        end_time        TEXT,
        duration_minutes INTEGER,
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS review_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        note_id         TEXT NOT NULL,
        session_id      INTEGER REFERENCES study_sessions(id),
        review_date     TEXT NOT NULL,
        rating          INTEGER NOT NULL,
        correct         BOOLEAN,
        prev_mastery    REAL,
        new_mastery     REAL,
        prev_interval   INTEGER,
        new_interval    INTEGER,
        ease_factor     REAL,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS learner_profile (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS profile_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key         TEXT NOT NULL,
        value       TEXT,
        recorded_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges(source_id);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges(target_id);
    CREATE INDEX IF NOT EXISTS idx_review_note ON review_log(note_id);
    CREATE INDEX IF NOT EXISTS idx_review_session ON review_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_history_key ON profile_history(key);
    """)

    conn.commit()

    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(knowledge_nodes)").fetchall()}
    migrations = [
        ("ease_factor", "REAL DEFAULT 2.5"),
        ("review_count", "INTEGER DEFAULT 0"),
        ("last_reviewed", "TEXT"),
        ("next_review", "TEXT"),
    ]
    for col, typedef in migrations:
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE knowledge_nodes ADD COLUMN {col} {typedef}")

    conn.commit()
    conn.close()


def upsert_node(note_id, title=None, difficulty=None, concept_type=None,
                mastery=None, learning_state=None, file_path=None,
                ease_factor=None, review_count=None,
                last_reviewed=None, next_review=None, config=None):
    """Insert or update a knowledge node."""
    conn = get_connection(config)
    now = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT note_id FROM knowledge_nodes WHERE note_id = ?", (note_id,)
    ).fetchone()

    if existing:
        updates = []
        params = []
        for field, val in [("title", title), ("difficulty", difficulty),
                           ("concept_type", concept_type), ("mastery", mastery),
                           ("learning_state", learning_state),
                           ("file_path", file_path), ("last_synced", now),
                           ("ease_factor", ease_factor),
                           ("review_count", review_count),
                           ("last_reviewed", last_reviewed),
                           ("next_review", next_review)]:
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(val)
        if updates:
            params.append(note_id)
            conn.execute(
                f"UPDATE knowledge_nodes SET {', '.join(updates)} WHERE note_id = ?",
                params
            )
    else:
        conn.execute(
            """INSERT INTO knowledge_nodes
               (note_id, title, difficulty, concept_type, mastery,
                learning_state, file_path, last_synced,
                ease_factor, review_count, last_reviewed, next_review)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (note_id, title, difficulty, concept_type,
             mastery if mastery is not None else 0.1,
             learning_state or "pending", file_path, now,
             ease_factor if ease_factor is not None else 2.5,
             review_count if review_count is not None else 0,
             last_reviewed, next_review)
        )

    conn.commit()
    conn.close()


def upsert_edge(source_id, target_id, edge_type="prerequisite",
                weight=1.0, config=None):
    """Insert or update a knowledge graph edge."""
    conn = get_connection(config)
    conn.execute(
        """INSERT INTO knowledge_edges (source_id, target_id, edge_type, weight)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(source_id, target_id)
           DO UPDATE SET edge_type=excluded.edge_type, weight=excluded.weight""",
        (source_id, target_id, edge_type, weight)
    )
    conn.commit()
    conn.close()


def clear_edges(note_id, config=None):
    """Remove edges owned by this note (for re-scan).

    A note owns:
    - Outgoing non-prerequisite edges (source_id = note_id AND edge_type != 'prerequisite')
    - Incoming prerequisite edges (target_id = note_id AND edge_type = 'prerequisite')
    """
    conn = get_connection(config)
    conn.execute(
        """DELETE FROM knowledge_edges
           WHERE (source_id = ? AND edge_type != 'prerequisite')
              OR (target_id = ? AND edge_type = 'prerequisite')""",
        (note_id, note_id)
    )
    conn.commit()
    conn.close()


def get_node(note_id, config=None):
    """Retrieve a single knowledge node."""
    conn = get_connection(config)
    row = conn.execute(
        "SELECT * FROM knowledge_nodes WHERE note_id = ?", (note_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_nodes(config=None):
    """Retrieve all knowledge nodes."""
    conn = get_connection(config)
    rows = conn.execute("SELECT * FROM knowledge_nodes ORDER BY note_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_edges(note_id=None, edge_type=None, config=None):
    """Retrieve edges, optionally filtered by node or type."""
    conn = get_connection(config)
    query = "SELECT * FROM knowledge_edges"
    conditions = []
    params = []

    if note_id is not None:
        conditions.append("(source_id = ? OR target_id = ?)")
        params.extend([note_id, note_id])
    if edge_type is not None:
        conditions.append("edge_type = ?")
        params.append(edge_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_profile(key, value, config=None):
    """Set a learner profile key-value pair and append to history."""
    conn = get_connection(config)
    now = datetime.now(timezone.utc).isoformat()
    value_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value

    conn.execute(
        """INSERT INTO learner_profile (key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key)
           DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value_str, now)
    )
    conn.execute(
        "INSERT INTO profile_history (key, value, recorded_at) VALUES (?, ?, ?)",
        (key, value_str, now)
    )
    conn.commit()
    conn.close()


def get_profile(key=None, config=None):
    """Get one or all learner profile entries."""
    conn = get_connection(config)
    if key is not None:
        row = conn.execute(
            "SELECT * FROM learner_profile WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        if row:
            result = dict(row)
            try:
                result["parsed_value"] = json.loads(result["value"])
            except (json.JSONDecodeError, TypeError):
                pass
            return result
        return None
    else:
        rows = conn.execute("SELECT * FROM learner_profile ORDER BY key").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_profile_history(key, limit=30, config=None):
    """Get history of a specific profile key."""
    conn = get_connection(config)
    rows = conn.execute(
        """SELECT * FROM profile_history
           WHERE key = ? ORDER BY recorded_at DESC LIMIT ?""",
        (key, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_session(start_time=None, config=None):
    """Create a new study session and return its ID."""
    conn = get_connection(config)
    if start_time is None:
        start_time = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO study_sessions (start_time) VALUES (?)",
        (start_time,)
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id


def close_session(session_id, end_time=None, duration_minutes=None,
                   notes=None, config=None):
    """Close a study session with end time and duration."""
    conn = get_connection(config)
    if end_time is None:
        end_time = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE study_sessions
           SET end_time = ?, duration_minutes = ?, notes = ?
           WHERE id = ?""",
        (end_time, duration_minutes, notes, session_id)
    )
    conn.commit()
    conn.close()


def log_review(note_id, rating, correct=None, session_id=None,
               prev_mastery=None, new_mastery=None,
               prev_interval=None, new_interval=None,
               ease_factor=None, config=None):
    """Log a single review event."""
    conn = get_connection(config)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO review_log
           (note_id, session_id, review_date, rating, correct,
            prev_mastery, new_mastery, prev_interval, new_interval, ease_factor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (note_id, session_id, now, rating, correct,
         prev_mastery, new_mastery, prev_interval, new_interval, ease_factor)
    )
    conn.commit()
    conn.close()


def get_stats(config=None):
    """Get summary statistics for dashboard."""
    conn = get_connection(config)
    stats = {}

    stats["total_nodes"] = conn.execute(
        "SELECT COUNT(*) as c FROM knowledge_nodes"
    ).fetchone()["c"]

    stats["total_edges"] = conn.execute(
        "SELECT COUNT(*) as c FROM knowledge_edges"
    ).fetchone()["c"]

    stats["mastered_nodes"] = conn.execute(
        "SELECT COUNT(*) as c FROM knowledge_nodes WHERE mastery >= 0.7"
    ).fetchone()["c"]

    stats["total_reviews"] = conn.execute(
        "SELECT COUNT(*) as c FROM review_log"
    ).fetchone()["c"]

    stats["total_sessions"] = conn.execute(
        "SELECT COUNT(*) as c FROM study_sessions"
    ).fetchone()["c"]

    stats["avg_mastery"] = conn.execute(
        "SELECT AVG(mastery) as avg FROM knowledge_nodes"
    ).fetchone()["avg"] or 0.0

    conn.close()
    return stats


def reset_database(config=None):
    """Drop all tables and recreate (use with caution)."""
    conn = get_connection(config)
    conn.executescript("""
    DROP TABLE IF EXISTS review_log;
    DROP TABLE IF EXISTS study_sessions;
    DROP TABLE IF EXISTS knowledge_edges;
    DROP TABLE IF EXISTS knowledge_nodes;
    DROP TABLE IF EXISTS profile_history;
    DROP TABLE IF EXISTS learner_profile;
    """)
    conn.commit()
    conn.close()
    init_database(config)


if __name__ == "__main__":
    import sys

    config = load_config()
    db_path = get_db_path(config)
    print(f"Database path: {db_path}")

    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        response = input("This will DELETE all data. Type 'yes' to confirm: ")
        if response.lower() == "yes":
            reset_database(config)
            print("Database reset complete.")
        else:
            print("Cancelled.")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        init_database(config)
        stats = get_stats(config)
        print("\n=== Study Planner Database Stats ===")
        for key, val in stats.items():
            print(f"  {key}: {val}")
    else:
        init_database(config)
        print(f"Database initialized at: {db_path}")
        print("Tables: knowledge_nodes, knowledge_edges, study_sessions,")
        print("        review_log, learner_profile, profile_history")
