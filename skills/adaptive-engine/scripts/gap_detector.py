#!/usr/bin/env python3
"""Knowledge gap detector for Study Planner plugin.

Identifies concepts with low mastery and ranks them by impact:
1. Scan all nodes with mastery < threshold
2. Find downstream nodes that depend on each gap (via prerequisite edges)
3. Sort by impact (most blocking gaps first)
4. Generate actionable "fill the gap" suggestions

Suggestion structure:
  {note_id, title, mastery, difficulty, blocked_count, blocked_nodes, suggestion}
"""

import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
study_planner_scripts = script_dir.parent.parent / "study-planner" / "scripts"
sys.path.insert(0, str(study_planner_scripts))
sys.path.insert(0, str(script_dir))

import db_manager
import bkt_engine


def _get_downstream_nodes(node_id, config):
    """Get all nodes that directly or indirectly depend on node_id.

    Traverses prerequisite edges: if A is prerequisite of B,
    and B is prerequisite of C, then A's downstream includes {B, C}.
    """
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        "SELECT source_id, target_id FROM knowledge_edges WHERE edge_type = 'prerequisite'"
    ).fetchall()
    conn.close()

    adj = {}
    for r in rows:
        adj.setdefault(r["source_id"], []).append(r["target_id"])

    visited = set()
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for downstream in adj.get(current, []):
            if downstream not in visited:
                visited.add(downstream)
                queue.append(downstream)

    visited.discard(node_id)
    return visited


def detect_gaps(config=None, mastery_threshold=None):
    """Scan all knowledge nodes for low-mastery gaps.

    Excludes MOCs, literature notes, and stubs — only permanent notes
    (definitions, claims, processes) are considered learnable concepts.

    Args:
        config: Plugin config
        mastery_threshold: Override config threshold

    Returns:
        list of gap dicts, each containing:
        {note_id, title, mastery, difficulty, learning_state, concept_type}
    """
    if config is None:
        config = db_manager.load_config()
    if mastery_threshold is None:
        mastery_threshold = config.get("mastery_threshold", 0.7)

    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT * FROM knowledge_nodes
           WHERE mastery < ?
           AND concept_type NOT IN ('moc', 'literature', 'stub')
           AND concept_type IS NOT NULL
           ORDER BY mastery ASC""",
        (mastery_threshold,)
    ).fetchall()
    conn.close()

    gaps = []
    for row in rows:
        gaps.append({
            "note_id": row["note_id"],
            "title": row["title"],
            "mastery": round(row["mastery"] or 0.1, 4),
            "difficulty": row["difficulty"] or 3,
            "learning_state": row["learning_state"],
            "concept_type": row["concept_type"],
        })

    return gaps


def calculate_impact(note_id, config=None):
    """Calculate the impact of a knowledge gap.

    Impact = number of downstream nodes that are blocked by this gap.
    A node is "blocked" if it depends on this gap and hasn't been mastered.

    Args:
        note_id: The gap node ID
        config: Plugin config

    Returns:
        dict with blocked_count, blocked_node_ids, blocked_titles
    """
    if config is None:
        config = db_manager.load_config()

    downstream = _get_downstream_nodes(note_id, config)
    if not downstream:
        return {"blocked_count": 0, "blocked_node_ids": [], "blocked_titles": []}

    conn = db_manager.get_connection(config)
    placeholders = ",".join("?" * len(downstream))
    rows = conn.execute(
        f"""SELECT note_id, title, mastery FROM knowledge_nodes
            WHERE note_id IN ({placeholders})""",
        list(downstream)
    ).fetchall()
    conn.close()

    blocked = []
    for row in rows:
        mastery = row["mastery"] or 0
        if mastery < 0.7:
            blocked.append({
                "note_id": row["note_id"],
                "title": row["title"],
                "mastery": round(mastery, 4),
            })

    return {
        "blocked_count": len(blocked),
        "blocked_node_ids": [b["note_id"] for b in blocked],
        "blocked_titles": [b["title"] for b in blocked],
    }


def rank_gaps(config=None, mastery_threshold=None):
    """Rank knowledge gaps by impact (most blocking first).

    Sort order:
    1. Blocked count (descending) — gaps that block more concepts first
    2. Mastery (ascending) — lower mastery = more urgent
    3. Difficulty (ascending) — easier gaps to fix first

    Returns:
        list of gap dicts with impact info, sorted by priority
    """
    if config is None:
        config = db_manager.load_config()
    if mastery_threshold is None:
        mastery_threshold = config.get("mastery_threshold", 0.7)

    gaps = detect_gaps(config, mastery_threshold)
    if not gaps:
        return []

    for gap in gaps:
        impact = calculate_impact(gap["note_id"], config)
        gap["blocked_count"] = impact["blocked_count"]
        gap["blocked_titles"] = impact["blocked_titles"]

    gaps.sort(key=lambda g: (
        -g["blocked_count"],
        g["mastery"],
        g["difficulty"],
    ))

    return gaps


def generate_suggestions(config=None, top_n=5):
    """Generate actionable "fill the gap" learning suggestions.

    Each suggestion includes:
    - The gap concept and its current mastery
    - How many downstream concepts it blocks
    - Suggested action (review vs relearn)
    - Priority level (critical/important/moderate)

    Args:
        config: Plugin config
        top_n: Maximum number of suggestions

    Returns:
        list of suggestion dicts
    """
    if config is None:
        config = db_manager.load_config()

    gaps = rank_gaps(config)

    suggestions = []
    for i, gap in enumerate(gaps[:top_n]):
        mastery = gap["mastery"]
        blocked = gap["blocked_count"]

        if blocked >= 2:
            priority = "critical"
            action = "relearn"
            reason = f"Blocks {blocked} downstream concepts — fix this first"
        elif blocked == 1:
            priority = "important"
            action = "review"
            reason = f"Blocks 1 downstream concept"
        elif mastery < 0.25:
            priority = "important"
            action = "relearn"
            reason = "Very low mastery — needs foundational review"
        else:
            priority = "moderate"
            action = "review"
            reason = "Below mastery threshold"

        level = bkt_engine.get_mastery_level(mastery)

        suggestions.append({
            "rank": i + 1,
            "note_id": gap["note_id"],
            "title": gap["title"],
            "mastery": mastery,
            "difficulty": gap["difficulty"],
            "mastery_level": level,
            "blocked_count": blocked,
            "blocked_titles": gap.get("blocked_titles", []),
            "priority": priority,
            "suggested_action": action,
            "reason": reason,
        })

    return suggestions


def get_gap_report(config=None):
    """Generate a comprehensive gap analysis report.

    Returns:
        dict with summary stats and top suggestions
    """
    if config is None:
        config = db_manager.load_config()

    gaps = detect_gaps(config)
    suggestions = generate_suggestions(config)

    conn = db_manager.get_connection(config)
    total_learnable = conn.execute(
        """SELECT COUNT(*) as c FROM knowledge_nodes
           WHERE concept_type NOT IN ('moc', 'literature', 'stub')
           AND concept_type IS NOT NULL"""
    ).fetchone()["c"]
    conn.close()

    critical = sum(1 for s in suggestions if s["priority"] == "critical")
    important = sum(1 for s in suggestions if s["priority"] == "important")

    return {
        "total_learnable": total_learnable,
        "total_gaps": len(gaps),
        "gap_ratio": round(len(gaps) / max(total_learnable, 1), 4),
        "critical_gaps": critical,
        "important_gaps": important,
        "avg_gap_mastery": round(sum(g["mastery"] for g in gaps) / max(len(gaps), 1), 4),
        "top_suggestions": suggestions,
    }


if __name__ == "__main__":
    print("=== Gap Detector Test ===\n")

    config = db_manager.load_config()
    db_manager.init_database(config)

    print("1. Detected gaps (mastery < 0.7):")
    gaps = detect_gaps(config)
    for g in gaps:
        print(f"   - {g['title']} (mastery={g['mastery']:.2f}, "
              f"difficulty={g['difficulty']}, state={g['learning_state']})")

    print(f"\n2. Ranked by impact:")
    ranked = rank_gaps(config)
    for g in ranked:
        print(f"   - {g['title']}: blocks {g['blocked_count']} nodes, "
              f"mastery={g['mastery']:.2f}")

    print(f"\n3. Suggestions:")
    suggestions = generate_suggestions(config)
    for s in suggestions:
        print(f"   [{s['priority'].upper()}] {s['title']}")
        print(f"       mastery={s['mastery']:.2f} ({s['mastery_level']}), "
              f"blocks={s['blocked_count']}")
        print(f"       action: {s['suggested_action']}, reason: {s['reason']}")

    print(f"\n4. Gap report:")
    report = get_gap_report(config)
    for k, v in report.items():
        if k != "top_suggestions":
            print(f"   {k}: {v}")
