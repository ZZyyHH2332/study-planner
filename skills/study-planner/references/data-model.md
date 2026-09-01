# Data Model Reference

## Overview

SQLite database at `D:\UserData\Documents\study-planner\study.db`. All tables are created by `db_manager.py`.

## Schema Diagram

```
knowledge_nodes          knowledge_edges
┌──────────────────┐    ┌──────────────────┐
│ note_id (PK)     │◄───│ source_id (FK)   │
│ title            │    │ target_id (FK)   │──► knowledge_nodes
│ difficulty       │    │ edge_type        │
│ concept_type     │    │ weight           │
│ mastery          │    └──────────────────┘
│ learning_state   │
│ file_path        │    study_sessions
│ last_synced      │    ┌──────────────────┐
└──────────────────┘    │ id (PK)          │
                        │ start_time       │
review_log              │ end_time         │
┌──────────────────┐    │ duration_minutes │
│ id (PK)          │    │ notes            │
│ note_id (FK)     │──► │ created_at       │
│ session_id (FK)  │──► └──────────────────┘
│ review_date      │
│ rating           │    learner_profile
│ correct          │    ┌──────────────────┐
│ prev_mastery     │    │ key (PK)         │
│ new_mastery      │    │ value (JSON)     │
│ prev_interval    │    │ updated_at       │
│ new_interval     │    └──────────────────┘
│ ease_factor      │
│ created_at       │    profile_history
└──────────────────┘    ┌──────────────────┐
                        │ id (PK)          │
                        │ key              │
                        │ value (JSON)     │
                        │ recorded_at      │
                        └──────────────────┘
```

## Tables

### knowledge_nodes

Knowledge graph nodes extracted from Permanent Notes (and MOCs, Literature Notes).

| Column | Type | Description |
|--------|------|-------------|
| note_id | TEXT PK | Obsidian note ID (timestamp YYYYMMDDHHmm) |
| title | TEXT | Note title (from frontmatter or filename) |
| difficulty | INTEGER | Estimated difficulty 1-5 |
| concept_type | TEXT | claim / definition / process / moc / literature / stub |
| mastery | REAL | BKT mastery probability 0-1 (default 0.1) |
| learning_state | TEXT | pending / in_progress / reviewed / mastered |
| file_path | TEXT | Absolute path to .md file |
| last_synced | TEXT | ISO timestamp of last frontmatter sync |

### knowledge_edges

Directed edges between knowledge nodes.

| Column | Type | Description |
|--------|------|-------------|
| source_id | TEXT | Source node ID |
| target_id | TEXT | Target node ID |
| edge_type | TEXT | prerequisite / related / belongs_to / inspired |
| weight | REAL | Edge weight (default 1.0) |

**Edge type semantics**:
- `prerequisite`: source → target means "source is prerequisite of target" (DAG edge)
- `related`: source → target means "source is semantically related to target" (bidirectional)
- `belongs_to`: source → target means "source belongs to MOC target"
- `inspired`: source → target means "Literature source inspired Permanent target"

### study_sessions

Learning session records.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment session ID |
| start_time | TEXT | Session start (ISO) |
| end_time | TEXT | Session end (ISO) |
| duration_minutes | INTEGER | Total duration |
| notes | TEXT | Session notes |
| created_at | TEXT | Record creation time |

### review_log

Individual review/self-test records.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment review ID |
| note_id | TEXT | Reviewed knowledge node |
| session_id | INTEGER FK | Associated study session |
| review_date | TEXT | Review timestamp |
| rating | INTEGER | FSRS rating: 1=again, 2=hard, 3=good, 4=easy |
| correct | BOOLEAN | Whether answer was correct |
| prev_mastery | REAL | BKT mastery before review |
| new_mastery | REAL | BKT mastery after review |
| prev_interval | INTEGER | FSRS interval before review |
| new_interval | INTEGER | FSRS interval after review |
| ease_factor | REAL | FSRS ease factor |
| created_at | TEXT | Record creation time |

### learner_profile

Key-value store for holistic learner state (the "long-term memory").

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PK | Profile key (see keys below) |
| value | TEXT | JSON-serialized value |
| updated_at | TEXT | Last update time |

**Profile keys**:
- `learning_goals`: Array of `{goal, target_date, priority, moc_id}`
- `study_patterns`: `{peak_hours, avg_duration, frequency, preferred_days}`
- `retention_profile`: `{fsrs_params: {stability, difficulty, retrievability}}`
- `difficulty_calibration`: `{estimated_vs_actual: {bias, trend}}`
- `bkt_params`: `{domain: {p_slip, p_guess, p_transit}}`
- `content_affinity`: `{video: rate, text: rate, practice: rate}`
- `weak_areas`: Array of `{note_id, concept, failure_rate, last_attempt}`
- `trajectory_history`: Array of `{date, mastery_avg, goals_progress, notes_added}`

### profile_history

Append-only history of profile changes (ensures system "doesn't forget").

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| key | TEXT | Profile key |
| value | TEXT | JSON value at this point in time |
| recorded_at | TEXT | When this value was recorded |

## Indexes

- `idx_edges_source`: knowledge_edges(source_id) — find outgoing edges
- `idx_edges_target`: knowledge_edges(target_id) — find incoming edges
- `idx_review_note`: review_log(note_id) — find reviews for a node
- `idx_review_session`: review_log(session_id) — find reviews in a session
- `idx_history_key`: profile_history(key) — find history for a key

## SQLite Pragmas

```sql
PRAGMA journal_mode=WAL;    -- Write-Ahead Logging for concurrent reads
PRAGMA foreign_keys=ON;     -- Enforce foreign key constraints
```
