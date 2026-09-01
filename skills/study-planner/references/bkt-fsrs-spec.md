# BKT + FSRS Adaptive Learning Engine — Technical Spec

## Overview

The Study Planner plugin uses two complementary models to drive adaptive learning:

- **BKT (Bayesian Knowledge Tracing)** — tracks the probability that a learner *knows* a concept, updating after each correct/incorrect response.
- **FSRS (Free Spaced Repetition Scheduler)** — schedules *when* to review a concept next, based on rating and ease factor.

Both engines run inside a `StudySession` (see `session_sync.py`), which orchestrates the full review pipeline and synchronizes results to the Obsidian vault.

---

## Architecture

```
StudySession.review(note_id, rating, correct)
  │
  ├── bkt_engine.process_review()
  │     ├── update_mastery()         ← Bayes' rule + transit
  │     ├── get_learning_state()     ← mastery → state label
  │     ├── db_manager.upsert_node() ← write mastery + state to DB
  │     ├── db_manager.log_review()  ← insert review_log row (BKT fields)
  │     └── profile_manager updates  ← weak areas, review count
  │
  ├── fsrs_engine.schedule_review()
  │     ├── calculate_interval()     ← SM-2/FSRS hybrid
  │     ├── _update_node_scheduling() ← update last_synced
  │     └── profile_manager updates  ← retention profile, ease history
  │
  ├── session._update_review_log_fsrs()  ← back-fill interval + ease into review_log
  │
  └── (on session.end)
        ├── _sync_frontmatter()       ← batch write to .md files
        └── profile_manager.record_trajectory()
```

---

## BKT: Bayesian Knowledge Tracing

### Model

Each knowledge node has a latent binary state: *known* or *unknown*. BKT maintains a probability `P(L)` that the learner currently knows the concept.

### Four Parameters

| Parameter  | Symbol  | Default | Range        | Meaning                                          |
|------------|---------|---------|--------------|--------------------------------------------------|
| P(L0)      | p_init  | 0.1     | [0.01, 0.5]  | Prior probability of knowing before any review  |
| P(T)       | p_transit | 0.3   | [0.05, 0.5]  | Probability of learning (unknown → known) per trial |
| P(S)       | p_slip  | 0.1     | [0.01, 0.3]  | Probability of incorrect response despite knowing |
| P(G)       | p_guess | 0.2     | [0.01, 0.3]  | Probability of correct response despite not knowing |

Parameters are stored per-domain in the learner profile and can be calibrated from review history (see `calibrate_bkt_params()`).

### Update Rules

After a **correct** response:

```
P(L|correct) = P(L)(1-P(S)) / [P(L)(1-P(S)) + (1-P(L))P(G)]
```

After an **incorrect** response:

```
P(L|incorrect) = P(L)P(S) / [P(L)P(S) + (1-P(L))(1-P(G))]
```

Then apply transit (learning can occur during practice):

```
P(L_new) = P(L|response) + (1 - P(L|response)) * P(T)
```

All probabilities are clamped to `[0.01, 0.99]` to prevent degenerate cases.

### Mastery Levels

| Mastery Range | Level        | learning_state |
|---------------|-------------|----------------|
| >= 0.85       | mastered     | mastered       |
| >= 0.70       | proficient  | reviewed        |
| >= 0.50       | familiar    | reviewed        |
| >= 0.25       | learning    | in_progress     |
| < 0.25        | novice      | in_progress     |

### Calibration

`calibrate_bkt_params(domain, review_data)` adjusts P(S), P(G), P(T) from actual review history. Requires >= 10 reviews per domain for meaningful calibration. Results are clamped to safe ranges and stored in the learner profile.

---

## FSRS: Spaced Repetition Scheduler

### Rating Scale

| Rating | Name  | Meaning                              | Effect on interval          |
|--------|-------|--------------------------------------|-----------------------------|
| 1      | Again | Complete blackout                    | Reset to 0, ease -0.2       |
| 2      | Hard  | Significant effort, recalled         | Small increase, ease -0.15  |
| 3      | Good  | Correct with normal effort           | Standard increase, ease ±0  |
| 4      | Easy  | Instant recall                       | Accelerated increase, ease +0.15 |

### Interval Calculation

Uses a modified SM-2/FSRS hybrid algorithm:

**First review (repetition = 0):**
| Rating | Base interval (days) |
|--------|---------------------|
| Hard   | 1                   |
| Good   | 2                   |
| Easy   | 4                   |

**Second review (repetition = 1):**
| Rating | Interval (days) |
|--------|----------------|
| Hard   | 3              |
| Good   | 4              |
| Easy   | 8              |

**Subsequent reviews (repetition >= 2):**
```
interval = prev_interval * growth_factor
growth_factor = ease * {Hard: 1.2, Good: 1.0, Easy: 1.3}
```

**Again rating:** Always resets interval to 0 and repetition to 0.

### Ease Factor

- Starts at 2.5, minimum 1.3, maximum 3.0
- Adjusted by rating: Hard -0.15, Good ±0, Easy +0.15, Again -0.2
- Rounded to 2 decimal places

### Next Review Date

```
if new_interval > 0:
    next_review = today + timedelta(days=new_interval)
else:
    next_review = today + timedelta(minutes=10)  # same-day re-review
```

### Retention Prediction

Exponential decay model for retrievability:

```
R(t) = exp(-t / (interval * ease_factor))
```

Where `t` is days since last review. Returns a probability in [0, 1].

---

## Session Synchronization

### Review Pipeline

The `StudySession.review()` method processes a single review:

1. **BKT** updates mastery probability and learning state in `knowledge_nodes`
2. **BKT** logs the review to `review_log` (without FSRS fields initially)
3. **FSRS** calculates new interval, ease factor, and next review date
4. **Session** back-fills FSRS data (`new_interval`, `ease_factor`) into the latest `review_log` row via `_update_review_log_fsrs()`
5. Results stored in-memory in `self.reviews`

### Frontmatter Sync

On `session.end()`, the `_sync_frontmatter()` method batch-updates each reviewed note's frontmatter:

- **Source:** in-memory `self.reviews` list (primary), `review_log` table (fallback)
- **Target fields:** `mastery`, `learning_state`, `last_reviewed`, `next_review`, `review_count`, `ease_factor`
- **Method:** Targeted line replacement via regex, preserving comments and formatting
- **Scope:** Only `SYNC_FIELDS` are touched; all other frontmatter and body content is preserved

### Learner Profile Updates

On session end, the profile is updated with:
- Study patterns (peak hours, preferred days, duration)
- Trajectory snapshot (avg mastery, goals progress)
- Retention profile (ease factor history, average ease)

---

## Database Schema (relevant tables)

### review_log

```sql
CREATE TABLE review_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id         TEXT NOT NULL,
    session_id      INTEGER REFERENCES study_sessions(id),
    review_date     TEXT NOT NULL,
    rating          INTEGER NOT NULL,      -- 1=again, 2=hard, 3=good, 4=easy
    correct         BOOLEAN,
    prev_mastery    REAL,                  -- BKT: P(L) before update
    new_mastery     REAL,                  -- BKT: P(L) after update
    prev_interval   INTEGER,              -- FSRS: previous interval
    new_interval    INTEGER,              -- FSRS: new interval (days)
    ease_factor     REAL,                  -- FSRS: updated ease factor
    created_at      TEXT DEFAULT (datetime('now'))
);
```

### knowledge_nodes (learner-state columns)

```sql
CREATE TABLE knowledge_nodes (
    note_id         TEXT PRIMARY KEY,
    mastery         REAL DEFAULT 0.1,      -- BKT: current P(L)
    learning_state  TEXT DEFAULT 'pending', -- pending → in_progress → reviewed → mastered
    ...
);
```

---

## Due Review Queries

### get_due_reviews()

Returns all nodes where:
- `learning_state != 'mastered'`
- `concept_type NOT IN ('moc', 'literature', 'stub')`
- Latest review_log entry's calculated due date <= today

Due date is computed as: `date(review_log.created_at, '+' || new_interval || ' days')`

### get_review_queue(limit=20)

Same filter as due reviews, ordered by:
1. Never reviewed first
2. Lowest mastery ascending
3. Highest difficulty descending

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/bkt_engine.py` | BKT mastery tracking, calibration, level mapping |
| `scripts/fsrs_engine.py` | FSRS interval scheduling, retention prediction, due review queries |
| `scripts/session_sync.py` | Session orchestration, frontmatter sync, review_log back-fill |
| `scripts/profile_manager.py` | Learner profile CRUD, BKT parameter storage, trajectory recording |
| `scripts/db_manager.py` | SQLite schema, connection management, CRUD operations |
