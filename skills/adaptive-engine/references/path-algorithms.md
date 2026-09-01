# Path Algorithms — Technical Spec

## Overview

The adaptive engine generates personalized learning paths through the knowledge graph DAG using a four-stage pipeline:

1. **Topological Sort** (Kahn's algorithm with priority queue)
2. **Gap Insertion** (low-mastery prerequisites flagged)
3. **Dijkstra Optimization** (minimize (1-mastery) x difficulty)
4. **Review Insertion** (due reviews prepended)

---

## 1. Topological Sort (Priority Queue Kahn's)

### Standard Kahn's Algorithm

1. Calculate in-degree for each node (count of incoming prerequisite edges)
2. Initialize a queue with all nodes that have in-degree 0
3. Pop a node, add to result, decrement in-degree of its successors
4. When a successor's in-degree reaches 0, add to queue
5. Repeat until queue is empty

### Priority Queue Enhancement

Instead of a FIFO queue, use a **min-heap** keyed by `(1-mastery) * difficulty`.

When multiple nodes are available (all prerequisites met), the algorithm picks the one with the **lowest learning cost** — easier and less-mastered concepts come first.

```
cost(node) = (1 - mastery) * difficulty
```

This produces an order that:
- Respects prerequisites (hard constraint)
- Minimizes total effort (soft optimization)
- Front-loads easy wins to build momentum

### Cycle Detection

Uses DFS with three-color marking (white/gray/black):
- White: unvisited
- Gray: in current DFS path (if we revisit a gray node, there's a cycle)
- Black: fully processed

Cycles are reported but do not crash the sort — the algorithm skips nodes that can't be resolved.

---

## 2. Gap Insertion

After topological sort, each node is classified:

| Condition | Action | Reason |
|-----------|--------|--------|
| mastery >= threshold (0.7) | `learn` | Prerequisite met, proceed |
| mastery < threshold, depth=0 | `gap` | Starting concept with low mastery |
| mastery < threshold, depth>0 | `gap` | Prerequisite gap |
| node == target | `learn` | The target concept itself |

The gap label doesn't reorder the path (topo sort already ensures prerequisites come first). Instead, it flags which nodes need attention before the learner can proceed to the target.

---

## 3. Dijkstra Optimization

The priority-queue topological sort IS the Dijkstra optimization. By always expanding the lowest-cost node among available nodes, we achieve:

- **Minimum total cost path** from the starting frontier to the target
- **Greedy optimality** within DAG constraints
- **Natural difficulty progression** (easy -> hard)

### Edge Weight

```
weight(node) = (1 - mastery) * difficulty
```

- Already-mastered concepts have near-zero weight
- Hard, unlearned concepts have high weight

### Path Scope

When generating a path to a specific target:
1. Find all **ancestors** of the target (direct + indirect prerequisites)
2. Restrict the topological sort to this subgraph
3. The target is always the last node in the sorted order

---

## 4. Review Insertion

After generating the learning path, due reviews (next_review <= today) are inserted at the beginning.

### Logic

1. Query `get_due_reviews()` for all due nodes
2. For each due node:
   - If it's already in the path: upgrade its action to `review`
   - If it's NOT in the path: prepend as a standalone review step
3. Sort review steps by mastery ascending (weakest first)

### Rationale

Reviews serve as warm-up before learning new material. By doing reviews first:
- Reactivate prior knowledge (spaced repetition)
- Identify gaps that might affect new learning
- Build confidence before tackling harder concepts

---

## Data Structures

### Path Step

```python
{
    "note_id": "202608311410",
    "title": "Synapse",
    "action": "gap",          # "review" | "gap" | "learn"
    "mastery": 0.5333,
    "difficulty": 2,
    "reason": "low_mastery_start",
    "depth": 0,
}
```

### Path Summary

```python
{
    "total_steps": 3,
    "reviews": 1,
    "gaps": 1,
    "new_learning": 1,
    "avg_mastery": 0.42,
    "total_difficulty": 6,
    "estimated_effort": 1.43,
}
```
