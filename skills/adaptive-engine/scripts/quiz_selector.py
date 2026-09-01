#!/usr/bin/env python3
"""IRT-based quiz selector for Study Planner plugin.

Uses the Rasch model (1-parameter logistic IRT) to select quiz items
that match the learner's current ability — targeting the "zone of
proximal development" where P(correct) is between 0.6 and 0.8.

Rasch model:
    P(correct | θ, b) = exp(θ - b) / (1 + exp(θ - b))

    θ = learner ability (mapped from BKT mastery, range [-3, 3])
    b = item difficulty (mapped from note difficulty 1-5, range [-3, 3])

Item sources:
    1. Item bank: JSON file at config["item_bank_path"] (optional)
    2. Auto-generation: items synthesized from note metadata

Each item structure:
    {id, note_id, question, answer, difficulty, item_type}
    item_type: "recall" | "application" | "analysis"
"""

import sys
import json
import math
from pathlib import Path

script_dir = Path(__file__).resolve().parent
study_planner_scripts = script_dir.parent.parent / "study-planner" / "scripts"
sys.path.insert(0, str(study_planner_scripts))
sys.path.insert(0, str(script_dir))

import db_manager
import bkt_engine

ZPD_LOW = 0.6
ZPD_HIGH = 0.8

ABILITY_MIN = -3.0
ABILITY_MAX = 3.0

DIFFICULTY_MIN = -3.0
DIFFICULTY_MAX = 3.0


def rasch_probability(theta, b):
    """Rasch model: P(correct | theta, b).

    P = exp(theta - b) / (1 + exp(theta - b))

    Args:
        theta: Learner ability (logit scale, typically [-3, 3])
        b: Item difficulty (logit scale, typically [-3, 3])

    Returns:
        Probability of correct response [0, 1]
    """
    z = theta - b
    try:
        return math.exp(z) / (1.0 + math.exp(z))
    except OverflowError:
        return 1.0 if z > 0 else 0.0


def map_mastery_to_ability(mastery):
    """Map BKT mastery probability to IRT ability (theta).

    mastery 0.01 → ability -3.0 (very low)
    mastery 0.50 → ability  0.0 (average)
    mastery 0.99 → ability  3.0 (very high)

    Uses logit transform: theta = log(mastery / (1 - mastery))
    """
    mastery = max(0.01, min(0.99, mastery))
    theta = math.log(mastery / (1.0 - mastery))
    return max(ABILITY_MIN, min(ABILITY_MAX, round(theta, 3)))


def map_difficulty_to_param(difficulty):
    """Map note difficulty (1-5) to IRT difficulty parameter (b).

    difficulty 1 → b = -2.0 (easy)
    difficulty 3 → b =  0.0 (medium)
    difficulty 5 → b =  2.0 (hard)
    """
    diff = max(1, min(5, difficulty or 3))
    b = (diff - 3) * 1.0
    return round(b, 3)


def load_item_bank(config=None):
    """Load the item bank from JSON file if it exists.

    Returns:
        list of item dicts, or empty list if no bank
    """
    if config is None:
        config = db_manager.load_config()

    bank_path = config.get("item_bank_path")
    if not bank_path:
        return []

    path = Path(bank_path)
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _generate_items_from_node(node, config):
    """Auto-generate quiz items from a knowledge node's metadata.

    Generates one item per concept_type:
    - definition → recall item ("What is X?")
    - claim → analysis item ("Explain why X is true")
    - process → application item ("Apply X to solve Y")

    These are item *templates* — the actual question text is a prompt
    for the AI to elaborate during a study session.
    """
    note_id = node["note_id"]
    title = node.get("title", note_id)
    difficulty = node.get("difficulty", 3) or 3
    concept_type = node.get("concept_type", "definition")
    mastery = node.get("mastery", 0.1) or 0.1

    b = map_difficulty_to_param(difficulty)
    theta = map_mastery_to_ability(mastery)
    p_correct = rasch_probability(theta, b)

    templates = {
        "definition": {
            "item_type": "recall",
            "question": f"定义：{title}",
            "answer_hint": f"回顾 {title} 的核心定义和关键组成部分",
        },
        "claim": {
            "item_type": "analysis",
            "question": f"论证：{title}",
            "answer_hint": f"解释 {title} 的机制和证据支持",
        },
        "process": {
            "item_type": "application",
            "question": f"应用：{title}",
            "answer_hint": f"将 {title} 应用到一个新的场景中",
        },
    }

    template = templates.get(concept_type, templates["definition"])

    return [{
        "id": f"{note_id}_auto",
        "note_id": note_id,
        "title": title,
        "question": template["question"],
        "answer_hint": template["answer_hint"],
        "item_type": template["item_type"],
        "difficulty": difficulty,
        "b_param": b,
        "theta": theta,
        "p_correct": round(p_correct, 4),
        "source": "auto",
    }]


def select_items_for_node(note_id, config=None, target_range=None):
    """Select quiz items for a specific node that fall in the ZPD.

    ZPD (Zone of Proximal Development): P(correct) between 0.6 and 0.8.
    Items in this range are neither too easy nor too hard.

    Args:
        note_id: Knowledge node ID
        config: Plugin config
        target_range: Optional (low, high) override for ZPD

    Returns:
        list of item dicts sorted by closeness to ZPD center (0.7)
    """
    if config is None:
        config = db_manager.load_config()
    if target_range is None:
        target_range = (ZPD_LOW, ZPD_HIGH)

    node = db_manager.get_node(note_id, config)
    if node is None:
        return []

    bank_items = load_item_bank(config)
    node_bank_items = [i for i in bank_items if i.get("note_id") == note_id]

    auto_items = _generate_items_from_node(node, config)
    all_items = node_bank_items + auto_items

    mastery = node.get("mastery", 0.1) or 0.1
    theta = map_mastery_to_ability(mastery)

    zpd_low, zpd_high = target_range
    zpd_center = (zpd_low + zpd_high) / 2.0

    scored = []
    for item in all_items:
        b = item.get("b_param")
        if b is None:
            b = map_difficulty_to_param(item.get("difficulty", 3))
            item["b_param"] = b

        p = rasch_probability(theta, b)
        item["p_correct"] = round(p, 4)
        item["in_zpd"] = zpd_low <= p <= zpd_high
        item["zpd_distance"] = abs(p - zpd_center)
        scored.append(item)

    zpd_items = [i for i in scored if i["in_zpd"]]
    if zpd_items:
        zpd_items.sort(key=lambda x: x["zpd_distance"])
        return zpd_items

    scored.sort(key=lambda x: x["zpd_distance"])
    return scored[:1]


def generate_quiz(note_ids, config=None, items_per_node=1):
    """Generate a quiz for a set of knowledge nodes.

    For each node, selects the best-fitting item(s) from:
    1. Manual item bank (if available)
    2. Auto-generated items from node metadata

    Items are sorted to alternate between nodes and difficulty levels.

    Args:
        note_ids: List of knowledge node IDs to quiz on
        config: Plugin config
        items_per_node: Max items to select per node

    Returns:
        list of quiz item dicts, ready for presentation
    """
    if config is None:
        config = db_manager.load_config()

    quiz = []
    for note_id in note_ids:
        items = select_items_for_node(note_id, config)
        for item in items[:items_per_node]:
            node = db_manager.get_node(note_id, config)
            if node:
                item["mastery"] = round(node.get("mastery", 0.1) or 0.1, 4)
                item["learning_state"] = node.get("learning_state", "pending")
            quiz.append(item)

    quiz.sort(key=lambda x: (x.get("b_param", 0), x.get("mastery", 0)))

    return quiz


def get_quiz_summary(quiz):
    """Generate a summary of the quiz selection results."""
    if not quiz:
        return {"total_items": 0, "message": "No items selected"}

    in_zpd = sum(1 for q in quiz if q.get("in_zpd", False))
    avg_p = sum(q.get("p_correct", 0) for q in quiz) / len(quiz)

    types = {}
    for q in quiz:
        t = q.get("item_type", "unknown")
        types[t] = types.get(t, 0) + 1

    return {
        "total_items": len(quiz),
        "in_zpd": in_zpd,
        "zpd_coverage": round(in_zpd / max(len(quiz), 1), 4),
        "avg_p_correct": round(avg_p, 4),
        "item_types": types,
        "nodes_covered": len(set(q["note_id"] for q in quiz)),
    }


if __name__ == "__main__":
    print("=== Quiz Selector Test ===\n")

    config = db_manager.load_config()
    db_manager.init_database(config)

    print("1. Rasch model probabilities:")
    test_cases = [
        ("theta=0, b=0", 0.0, 0.0),
        ("theta=1, b=0", 1.0, 0.0),
        ("theta=-1, b=0", -1.0, 0.0),
        ("theta=0, b=1", 0.0, 1.0),
        ("theta=2, b=-1", 2.0, -1.0),
    ]
    for label, theta, b in test_cases:
        p = rasch_probability(theta, b)
        print(f"   {label}: P(correct) = {p:.4f}")

    print("\n2. Mastery → Ability mapping:")
    for m in [0.01, 0.1, 0.25, 0.5, 0.7, 0.85, 0.99]:
        theta = map_mastery_to_ability(m)
        print(f"   mastery={m:.2f} → theta={theta:+.3f}")

    print("\n3. Difficulty → b_param mapping:")
    for d in [1, 2, 3, 4, 5]:
        b = map_difficulty_to_param(d)
        print(f"   difficulty={d} → b={b:+.3f}")

    print("\n4. Item selection for Synapse (mastery=0.53, diff=2):")
    items = select_items_for_node("202608311410", config)
    for item in items:
        print(f"   [{item['item_type']}] {item['question']}")
        print(f"      b={item['b_param']:+.3f}, P={item['p_correct']:.4f}, "
              f"in_ZPD={item['in_zpd']}")

    print("\n5. Item selection for Dopamine (mastery=0.31, diff=4):")
    items = select_items_for_node("202608311420", config)
    for item in items:
        print(f"   [{item['item_type']}] {item['question']}")
        print(f"      b={item['b_param']:+.3f}, P={item['p_correct']:.4f}, "
              f"in_ZPD={item['in_zpd']}")

    print("\n6. Full quiz for both nodes:")
    quiz = generate_quiz(["202608311410", "202608311420"], config)
    for i, item in enumerate(quiz, 1):
        print(f"   Q{i}: [{item['item_type']}] {item['question']}")
        print(f"       b={item['b_param']:+.3f}, P={item['p_correct']:.4f}, "
              f"mastery={item.get('mastery', 0):.2f}")

    summary = get_quiz_summary(quiz)
    print(f"\n7. Quiz summary:")
    for k, v in summary.items():
        print(f"   {k}: {v}")
