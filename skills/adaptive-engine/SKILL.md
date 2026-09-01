# Adaptive Engine Skill

## Overview

The adaptive engine generates personalized learning paths, detects knowledge gaps, and selects quiz items at the right difficulty level. It builds on the learner model (BKT + FSRS) from Phase 2.

## Core Capabilities

### 1. Learning Path Generation (`path_generator.py`)

**Entry point:** `generate_learning_path(target_node_id, config)`

Generates a step-by-step path from the learner's current state to a target concept:
- Topological sort ensures prerequisites come first
- Priority queue picks lowest-cost nodes when multiple are available
- Low-mastery nodes are flagged as gaps
- Due reviews are inserted at the beginning

**Output:** List of path steps, each with action (`review`/`gap`/`learn`), mastery, difficulty, and reason.

### 2. Knowledge Gap Detection (`gap_detector.py`)

**Entry point:** `generate_suggestions(config, top_n=5)`

Scans all permanent notes for mastery below threshold (0.7), then:
- Calculates how many downstream concepts each gap blocks
- Ranks by impact (most blocking first)
- Generates actionable suggestions with priority levels (critical/important/moderate)

### 3. Quiz Item Selection (`quiz_selector.py`)

**Entry point:** `generate_quiz(note_ids, config)`

Uses the Rasch model (1PL IRT) to select items in the Zone of Proximal Development:
- Maps BKT mastery to ability theta via logit transform
- Maps note difficulty (1-5) to IRT difficulty parameter b
- Selects items where P(correct) is between 0.6 and 0.8
- Auto-generates item templates from note metadata when no manual item bank exists

## Usage Workflow

```
1. User wants to learn concept X
2. generate_learning_path(X) → ordered path with gaps and reviews
3. User studies along the path
4. After each review, BKT/FSRS update mastery and scheduling
5. Re-generate path → it auto-adjusts based on new mastery levels
```

## Integration Points

- **Input:** `db_manager.py` (knowledge_nodes, knowledge_edges, review_log)
- **Input:** `fsrs_engine.py` (get_due_reviews for review insertion)
- **Input:** `bkt_engine.py` (mastery levels for gap classification)
- **Output:** Path steps, gap suggestions, quiz items — consumable by the launcher CLI or future HTML dashboard

## References

- `references/path-algorithms.md` — detailed algorithm specification
- Phase 2 `references/bkt-fsrs-spec.md` — learner model specification
