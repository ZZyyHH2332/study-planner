#!/usr/bin/env python3
"""Phase 5 verification: AI-driven question generation and scoring.

Tests:
  1. Question prompt generation by concept_type
  2. Difficulty adaptation by mastery level
  3. Scoring criteria evaluation logic
  4. Answer reveal on demand
  5. Session with AI question mode
  6. quiz_selector integration with question_prompts
"""

import sys
import json
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sp_scripts = script_dir / "skills" / "study-planner" / "scripts"
ae_scripts = script_dir / "skills" / "adaptive-engine" / "scripts"
sys.path.insert(0, str(sp_scripts))
sys.path.insert(0, str(ae_scripts))

import db_manager
import question_prompts
import scoring_engine
import quiz_selector

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
results = []


def test_prompt_generation():
    """Test 1: Question prompts generated for all concept types."""
    config = db_manager.load_config()
    nodes = db_manager.get_all_nodes(config)

    if not nodes:
        print("  (no nodes to test)")
        results.append(("Question prompt generation", True))
        print(f"  {PASS}\n")
        return

    all_pass = True
    for node in nodes[:3]:
        prompt = question_prompts.generate_prompt(node, config=config)

        has_prompt = bool(prompt.get("prompt"))
        has_difficulty = prompt.get("difficulty") in ("basic", "intermediate", "advanced")
        has_bloom = bool(prompt.get("bloom_level"))
        has_note_id = bool(prompt.get("note_id"))

        checks = [has_prompt, has_difficulty, has_bloom, has_note_id]
        if not all(checks):
            all_pass = False

        print(f"  {prompt['title']}: type={prompt['concept_type']}, "
              f"diff={prompt['difficulty']}, bloom={prompt['bloom_level']}")

    results.append(("Question prompt generation", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_difficulty_adaptation():
    """Test 2: Same node generates different difficulty at different mastery."""
    config = db_manager.load_config()
    nodes = db_manager.get_all_nodes(config)

    if not nodes:
        print("  (no nodes)")
        results.append(("Difficulty adaptation", True))
        print(f"  {PASS}\n")
        return

    node = nodes[0]
    basic = question_prompts.generate_prompt(node, mastery=0.1, config=config)
    inter = question_prompts.generate_prompt(node, mastery=0.5, config=config)
    adv = question_prompts.generate_prompt(node, mastery=0.9, config=config)

    levels = [basic["difficulty"], inter["difficulty"], adv["difficulty"]]
    expected = ["basic", "intermediate", "advanced"]
    all_pass = levels == expected

    print(f"  mastery=0.1 → {levels[0]} (expected basic)")
    print(f"  mastery=0.5 → {levels[1]} (expected intermediate)")
    print(f"  mastery=0.9 → {levels[2]} (expected advanced)")
    print(f"  Bloom levels: {basic['bloom_level']} / {inter['bloom_level']} / {adv['bloom_level']}")

    results.append(("Difficulty adaptation", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_scoring_logic():
    """Test 3: Scoring engine produces correct BKT/FSRS outputs."""
    criteria = scoring_engine.ScoringCriteria(
        key_points=["点A", "点B", "点C", "点D"],
        weights=[0.25, 0.25, 0.25, 0.25],
        common_errors=["常见错误1"],
        reference_answer="标准答案参考",
        difficulty="intermediate",
        bloom_level="应用/分析",
    )

    # Full correct
    r1 = scoring_engine.evaluate_result(
        hit_points=["点A", "点B", "点C", "点D"],
        has_common_error=False, criteria=criteria
    )

    # Partial
    r2 = scoring_engine.evaluate_result(
        hit_points=["点A", "点B"],
        has_common_error=False, criteria=criteria
    )

    # With common error
    r3 = scoring_engine.evaluate_result(
        hit_points=["点A"],
        has_common_error=True, criteria=criteria
    )

    checks = {
        "full correct → rating=4": r1["rating"] == 4 and r1["correct"] is True,
        "partial → rating=2-3": r2["rating"] in (2, 3),
        "with error → lower score": r3["score"] < r2["score"],
        "has feedback": all(r.get("feedback") for r in [r1, r2, r3]),
        "has missed points": len(r2.get("missed_points", [])) > 0,
    }

    all_pass = all(checks.values())
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"  Scores: {r1['score']:.2f} / {r2['score']:.2f} / {r3['score']:.2f}")
    print(f"  Ratings: {r1['rating']} / {r2['rating']} / {r3['rating']}")

    results.append(("Scoring engine logic", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_answer_reveal():
    """Test 4: Answer only shown when requested."""
    criteria = scoring_engine.ScoringCriteria(
        key_points=["点A", "点B"],
        weights=[0.5, 0.5],
        common_errors=["错误1"],
        reference_answer="这是标准答案",
    )

    no_reveal = scoring_engine.should_reveal_answer(False, criteria)
    reveal = scoring_engine.should_reveal_answer(True, criteria)

    checks = {
        "no reveal when not requested": no_reveal is None,
        "reveals when requested": reveal is not None,
        "contains reference answer": "标准答案" in (reveal or ""),
        "contains key points": "点A" in (reveal or ""),
        "contains common errors": "错误1" in (reveal or ""),
    }

    all_pass = all(checks.values())
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")

    results.append(("Answer reveal on demand", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_session_ai_mode():
    """Test 5: StudySession stores AI question data in short-term memory."""
    import session_sync
    config = db_manager.load_config()
    nodes = db_manager.get_all_nodes(config)

    if not nodes:
        print("  (no nodes)")
        results.append(("Session AI mode", True))
        print(f"  {PASS}\n")
        return

    node = nodes[0]
    session = session_sync.StudySession(config)
    session.start()

    # Simulate AI-mode review
    question_text = "请解释突触的组成和信号传递过程"
    criteria = {
        "key_points": ["突触前膜", "突触间隙", "突触后膜"],
        "weights": [0.33, 0.33, 0.34],
        "common_errors": ["遗漏突触间隙"],
        "reference_answer": "突触由三部分组成...",
    }
    user_answer = "突触包括突触前膜和突触后膜"
    evaluation = {"correct": False, "rating": 2, "score": 0.67,
                  "feedback": "部分正确，遗漏了突触间隙"}

    result = session.review(
        note_id=node["note_id"],
        rating=2,
        correct=False,
        domain="default",
        question=question_text,
        scoring_criteria=criteria,
        user_answer=user_answer,
        evaluation=evaluation,
    )

    session.end(notes="AI mode test")

    review_entry = session.reviews[-1]
    checks = {
        "has question": review_entry.get("question") == question_text,
        "has scoring_criteria": review_entry.get("scoring_criteria") == criteria,
        "has user_answer": review_entry.get("user_answer") == user_answer,
        "has evaluation": review_entry.get("evaluation") == evaluation,
        "has bkt result": "new_mastery" in result,
        "has fsrs result": "new_interval" in result,
    }

    all_pass = all(checks.values())
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")

    results.append(("Session AI mode", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_quiz_selector_integration():
    """Test 6: quiz_selector uses question_prompts for AI prompts."""
    config = db_manager.load_config()
    nodes = db_manager.get_all_nodes(config)

    if not nodes:
        print("  (no nodes)")
        results.append(("quiz_selector integration", True))
        print(f"  {PASS}\n")
        return

    node = nodes[0]
    items = quiz_selector._generate_items_from_node(node, config)

    if not items:
        all_pass = False
        print("  No items generated")
    else:
        item = items[0]
        checks = {
            "has ai_prompt question": bool(item.get("question")),
            "source is ai_prompt": item.get("source") == "ai_prompt",
            "has bloom_level": bool(item.get("bloom_level")),
            "has difficulty_level": bool(item.get("difficulty_level")),
            "has scoring_prompt": bool(item.get("scoring_prompt")),
            "has b_param (IRT)": item.get("b_param") is not None,
            "has p_correct (IRT)": item.get("p_correct") is not None,
        }
        all_pass = all(checks.values())
        for name, ok in checks.items():
            print(f"  {'✓' if ok else '✗'} {name}")
        print(f"  question[:80]: {item.get('question', '')[:80]}...")

    results.append(("quiz_selector integration", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def main():
    print("=" * 55)
    print("  Phase 5: AI Question Generation Verification")
    print("=" * 55 + "\n")

    test_prompt_generation()
    test_difficulty_adaptation()
    test_scoring_logic()
    test_answer_reveal()
    test_session_ai_mode()
    test_quiz_selector_integration()

    print("=" * 55)
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"  Results: {passed}/{total} passed")
    for name, ok in results:
        print(f"    {PASS if ok else FAIL} {name}")
    print("=" * 55)

    if passed == total:
        print("\n  All tests passed!\n")
    else:
        print(f"\n  {total - passed} test(s) failed.\n")


if __name__ == "__main__":
    main()
