#!/usr/bin/env python3
"""Adaptive learning path generator for Study Planner plugin.

Generates personalized learning paths through the knowledge graph DAG:
1. Topological sort (Kahn's algorithm with priority queue)
2. Gap insertion (low-mastery prerequisites flagged)
3. Dijkstra optimization (minimize (1-mastery) × difficulty cost)
4. Review insertion (due reviews prepended)

Path structure: list of dicts, each containing:
  note_id, title, action, mastery, difficulty, reason, depth
"""

import sys
import heapq
from pathlib import Path
from datetime import datetime, timezone

script_dir = Path(__file__).resolve().parent
study_planner_scripts = script_dir.parent.parent / "study-planner" / "scripts"
sys.path.insert(0, str(study_planner_scripts))
sys.path.insert(0, str(script_dir))

import db_manager
import fsrs_engine


def _get_prerequisite_graph(config):
    """Build adjacency list and in-degree map from prerequisite edges.

    Returns:
        adj: {node_id: [target_ids]} (outgoing edges: A is prerequisite of B)
        in_degree: {node_id: count}
        all_nodes: set of node_ids that appear in prerequisite edges
    """
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        "SELECT source_id, target_id FROM knowledge_edges WHERE edge_type = 'prerequisite'"
    ).fetchall()
    conn.close()

    adj = {}
    in_degree = {}
    all_nodes = set()

    for r in rows:
        src = r["source_id"]
        tgt = r["target_id"]
        all_nodes.add(src)
        all_nodes.add(tgt)

        if src not in adj:
            adj[src] = []
        adj[src].append(tgt)

        in_degree[tgt] = in_degree.get(tgt, 0) + 1
        in_degree.setdefault(src, in_degree.get(src, 0))

    return adj, in_degree, all_nodes


def _get_ancestors(target_id, config):
    """Get all nodes that are direct or indirect prerequisites of target."""
    adj, _, all_nodes = _get_prerequisite_graph(config)

    ancestors = set()
    queue = [target_id]

    while queue:
        node = queue.pop(0)
        for src, targets in adj.items():
            if node in targets and src not in ancestors:
                ancestors.add(src)
                queue.append(src)

    return ancestors


def _node_cost(node, mastery_threshold=0.7):
    """Calculate learning cost for a node.

    Cost = (1 - mastery) × difficulty
    Already-mastered nodes have near-zero cost.
    """
    mastery = node.get("mastery", 0.1) or 0.1
    difficulty = node.get("difficulty", 3) or 3
    return max(0.1, (1.0 - mastery) * difficulty)


def detect_cycles(config):
    """Detect cycles in the prerequisite graph using DFS.

    Returns:
        list of cycles, each cycle is a list of node IDs
    """
    adj, _, all_nodes = _get_prerequisite_graph(config)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in all_nodes}
    cycles = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for neighbor in adj.get(node, []):
            if color.get(neighbor, WHITE) == GRAY:
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in all_nodes:
        if color[node] == WHITE:
            dfs(node, [])

    return cycles


def topological_sort(config):
    """Kahn's algorithm topological sort with priority queue.

    When multiple nodes are available (in-degree 0), picks the one with
    lowest (1-mastery) × difficulty cost. This produces an optimal learning
    order that respects prerequisites and minimizes effort.

    Returns:
        list of node IDs in topological order
    """
    adj, in_degree, all_nodes = _get_prerequisite_graph(config)

    if not all_nodes:
        return []

    conn = db_manager.get_connection(config)
    node_map = {}
    for n in all_nodes:
        row = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE note_id = ?", (n,)
        ).fetchone()
        if row:
            node_map[n] = dict(row)
    conn.close()

    for n in all_nodes:
        in_degree.setdefault(n, 0)

    heap = []
    counter = 0
    for n in all_nodes:
        if in_degree.get(n, 0) == 0:
            node = node_map.get(n, {"mastery": 0.1, "difficulty": 3})
            cost = _node_cost(node)
            counter += 1
            heapq.heappush(heap, (cost, counter, n))

    result = []
    while heap:
        _, _, node_id = heapq.heappop(heap)
        result.append(node_id)
        for neighbor in adj.get(node_id, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                node = node_map.get(neighbor, {"mastery": 0.1, "difficulty": 3})
                cost = _node_cost(node)
                counter += 1
                heapq.heappush(heap, (cost, counter, neighbor))

    if len(result) < len(all_nodes):
        cycles = detect_cycles(config)
        print(f"WARNING: Graph has cycles, sorted {len(result)}/{len(all_nodes)} nodes")
        if cycles:
            print(f"  Cycles detected: {cycles}")

    return result


def generate_learning_path(target_node_id, config=None,
                           mastery_threshold=None):
    """Generate a personalized learning path to reach a target concept.

    Pipeline:
    1. Find all ancestors (prerequisites) of the target
    2. Topological sort those nodes with Dijkstra-style cost optimization
    3. Flag gaps (mastery < threshold)
    4. Insert due reviews at the beginning

    Args:
        target_node_id: The concept the learner wants to reach
        config: Plugin config
        mastery_threshold: Override config threshold for gap detection

    Returns:
        list of path steps, each:
          {note_id, title, action, mastery, difficulty, reason, depth}
          action: "review" | "gap" | "learn"
    """
    if config is None:
        config = db_manager.load_config()
    if mastery_threshold is None:
        mastery_threshold = config.get("mastery_threshold", 0.7)

    ancestors = _get_ancestors(target_node_id, config)
    ancestors.add(target_node_id)

    conn = db_manager.get_connection(config)
    node_map = {}
    for n in ancestors:
        row = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE note_id = ?", (n,)
        ).fetchone()
        if row:
            node_map[n] = dict(row)
    conn.close()

    adj, in_degree, _ = _get_prerequisite_graph(config)

    for n in ancestors:
        in_degree.setdefault(n, 0)
        for neighbor in adj.get(n, []):
            if neighbor not in ancestors:
                in_degree[n] = 0

    heap = []
    counter = 0
    for n in ancestors:
        if in_degree.get(n, 0) == 0:
            node = node_map.get(n, {"mastery": 0.1, "difficulty": 3})
            cost = _node_cost(node)
            counter += 1
            heapq.heappush(heap, (cost, counter, n))

    topo_order = []
    visited = set()
    while heap:
        _, _, node_id = heapq.heappop(heap)
        if node_id in visited:
            continue
        visited.add(node_id)
        topo_order.append(node_id)
        for neighbor in adj.get(node_id, []):
            if neighbor in ancestors and neighbor not in visited:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] <= 0:
                    node = node_map.get(neighbor, {"mastery": 0.1, "difficulty": 3})
                    cost = _node_cost(node)
                    counter += 1
                    heapq.heappush(heap, (cost, counter, neighbor))

    for n in ancestors:
        if n not in visited:
            topo_order.append(n)

    path = []
    for depth, node_id in enumerate(topo_order):
        node = node_map.get(node_id, {})
        mastery = node.get("mastery", 0.1) or 0.1
        difficulty = node.get("difficulty", 3) or 3
        concept_type = node.get("concept_type", "")
        title = node.get("title", node_id)

        if concept_type in ("moc", "literature", "stub"):
            continue

        if mastery >= mastery_threshold:
            action = "learn"
            reason = "mastered_prerequisite"
        elif mastery >= 0.1 and depth == 0:
            action = "gap"
            reason = "low_mastery_start"
        else:
            action = "gap"
            reason = "prerequisite_gap"

        if node_id == target_node_id:
            action = "learn"
            reason = "target_concept"

        path.append({
            "note_id": node_id,
            "title": title,
            "action": action,
            "mastery": round(mastery, 4),
            "difficulty": difficulty,
            "reason": reason,
            "depth": depth,
        })

    path = _insert_due_reviews(path, config)
    return path


def _insert_due_reviews(path, config):
    """Insert due review tasks at the beginning of the learning path.

    Reviews are sorted by mastery (lowest first) to prioritize
    the weakest concepts.
    """
    due = fsrs_engine.get_due_reviews(config)
    path_node_ids = {p["note_id"] for p in path}

    review_steps = []
    for node in due:
        if node["note_id"] in path_node_ids:
            for p in path:
                if p["note_id"] == node["note_id"] and p["action"] != "review":
                    p["action"] = "review"
                    p["reason"] = "due_review_and_" + p["reason"]
            continue

        review_steps.append({
            "note_id": node["note_id"],
            "title": node.get("title", node["note_id"]),
            "action": "review",
            "mastery": round(node.get("mastery", 0.1), 4),
            "difficulty": node.get("difficulty", 3) or 3,
            "reason": "due_review",
            "depth": -1,
        })

    review_steps.sort(key=lambda x: x["mastery"])
    return review_steps + path


def get_path_summary(path):
    """Generate a human-readable summary of the learning path."""
    if not path:
        return {"total_steps": 0, "message": "No path generated"}

    reviews = sum(1 for p in path if p["action"] == "review")
    gaps = sum(1 for p in path if p["action"] == "gap")
    learn = sum(1 for p in path if p["action"] == "learn")

    avg_mastery = sum(p["mastery"] for p in path) / len(path)
    total_difficulty = sum(p["difficulty"] for p in path)

    return {
        "total_steps": len(path),
        "reviews": reviews,
        "gaps": gaps,
        "new_learning": learn,
        "avg_mastery": round(avg_mastery, 4),
        "total_difficulty": total_difficulty,
        "estimated_effort": _estimate_effort(path),
    }


def _estimate_effort(path):
    """Estimate total learning effort as sum of (1-mastery) × difficulty."""
    total = 0.0
    for p in path:
        if p["action"] == "review":
            total += 0.5
        else:
            total += (1.0 - p["mastery"]) * p["difficulty"]
    return round(total, 2)


if __name__ == "__main__":
    print("=== Path Generator Test ===\n")

    config = db_manager.load_config()
    db_manager.init_database(config)

    print("1. Topological sort of all nodes:")
    topo = topological_sort(config)
    for i, nid in enumerate(topo):
        node = db_manager.get_node(nid, config)
        title = node.get("title", nid) if node else nid
        mastery = node.get("mastery", 0) if node else 0
        print(f"   {i+1}. {title} (mastery={mastery:.2f})")

    print(f"\n2. Cycles detected: {detect_cycles(config)}")

    target = "202608311420"
    print(f"\n3. Learning path to 'Dopamine signals prediction error' ({target}):")
    path = generate_learning_path(target, config)
    for i, step in enumerate(path):
        icon = {"review": "[REVIEW]", "gap": "[GAP]", "learn": "[LEARN]"}[step["action"]]
        print(f"   {i+1}. {icon} {step['title']}")
        print(f"      mastery={step['mastery']:.2f}, difficulty={step['difficulty']}, "
              f"reason={step['reason']}")

    summary = get_path_summary(path)
    print(f"\n4. Path summary:")
    for k, v in summary.items():
        print(f"   {k}: {v}")
