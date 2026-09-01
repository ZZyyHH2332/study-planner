#!/usr/bin/env python3
"""Scoring engine for AI-driven evaluation.

When the AI generates a question (via question_prompts.py), it also generates
scoring criteria. This engine provides the framework for:

1. Storing scoring criteria in session short-term memory
2. Evaluating user answers against criteria
3. Converting evaluation to BKT correct (bool) + FSRS rating (1-4)
4. Generating feedback for the user

The actual evaluation is performed by the AI (LLM), not by this script.
This script provides the data structure and conversion logic.

Usage:
  from scoring_engine import ScoringCriteria, evaluate_result

  # AI generates criteria alongside question
  criteria = ScoringCriteria(
      key_points=["突触前膜", "突触间隙", "突触后膜", "神经递质释放"],
      weights=[0.25, 0.25, 0.25, 0.25],
      common_errors=["混淆电突触和化学突触"],
      reference_answer="突触由突触前膜、突触间隙和突触后膜组成..."
  )

  # AI evaluates user's answer
  result = evaluate_result(
      hit_points=["突触前膜", "突触间隙", "突触后膜"],
      has_common_error=False,
      criteria=criteria
  )
  # → {"correct": True, "rating": 3, "score": 0.75, "feedback": "..."}
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ScoringCriteria:
    """Scoring criteria for a single question (stored in session memory)."""
    key_points: List[str] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)
    common_errors: List[str] = field(default_factory=list)
    reference_answer: str = ""
    difficulty: str = "intermediate"
    bloom_level: str = "应用/分析"

    def to_dict(self):
        return {
            "key_points": self.key_points,
            "weights": self.weights if self.weights else [1.0/len(self.key_points)] * len(self.key_points),
            "common_errors": self.common_errors,
            "reference_answer": self.reference_answer,
            "difficulty": self.difficulty,
            "bloom_level": self.bloom_level,
        }


def evaluate_result(hit_points, has_common_error, criteria, partial_credit=True):
    """Convert AI evaluation into BKT/FSRS-compatible result.

    Args:
        hit_points: List of key points the user mentioned (AI judgment)
        has_common_error: Whether the user made a common error (AI judgment)
        criteria: ScoringCriteria object
        partial_credit: Whether to allow partial credit

    Returns:
        dict with: correct (bool), rating (1-4), score (float), feedback (str)
    """
    total_points = len(criteria.key_points)
    if total_points == 0:
        return {
            "correct": True,
            "rating": 3,
            "score": 0.75,
            "feedback": "无评分标准，默认基本正确",
        }

    weights = criteria.weights if criteria.weights else [1.0/total_points] * total_points
    hit_weight = sum(w for i, w in enumerate(weights) if i < len(hit_points))

    if has_common_error:
        hit_weight *= 0.7  # Penalty for common errors

    score = min(1.0, hit_weight)

    if score >= 0.85:
        rating = 4
        correct = True
        feedback = "完全正确且深入"
    elif score >= 0.6:
        rating = 3
        correct = True
        feedback = "基本正确，可进一步深化"
    elif score >= 0.3:
        rating = 2
        correct = False
        feedback = "部分正确，但有重要遗漏"
    else:
        rating = 1
        correct = False
        feedback = "需要重新学习该知识点"

    if not partial_credit:
        correct = score >= 0.6

    missed_points = [p for i, p in enumerate(criteria.key_points)
                     if i >= len(hit_points) or criteria.key_points[i] not in hit_points]

    if missed_points:
        feedback += f"。建议关注: {', '.join(missed_points[:3])}"

    return {
        "correct": correct,
        "rating": rating,
        "score": round(score, 2),
        "feedback": feedback,
        "hit_points": hit_points,
        "missed_points": missed_points,
    }


def format_for_session(question_text, criteria, user_answer, eval_result):
    """Format the complete question interaction for session storage.

    This is stored in StudySession.reviews as short-term memory only.
    Not written to database or frontmatter.
    """
    return {
        "question": question_text,
        "scoring_criteria": criteria.to_dict() if isinstance(criteria, ScoringCriteria) else criteria,
        "user_answer": user_answer,
        "evaluation": eval_result,
        "correct": eval_result["correct"],
        "rating": eval_result["rating"],
    }


def should_reveal_answer(user_requests_answer, criteria):
    """Determine whether to reveal the standard answer.

    Answers are only shown when the user explicitly requests them.
    """
    if not user_requests_answer:
        return None

    lines = ["标准答案参考：", criteria.reference_answer or "（无参考答案）"]
    if criteria.key_points:
        lines.append("\n关键得分点：")
        for i, point in enumerate(criteria.key_points):
            weight = criteria.weights[i] if i < len(criteria.weights) else 0
            lines.append(f"  {i+1}. {point} (权重: {weight:.0%})")
    if criteria.common_errors:
        lines.append("\n常见错误：")
        for err in criteria.common_errors:
            lines.append(f"  • {err}")

    return "\n".join(lines)


if __name__ == "__main__":
    criteria = ScoringCriteria(
        key_points=["突触前膜", "突触间隙", "突触后膜", "神经递质释放与受体结合"],
        weights=[0.2, 0.2, 0.2, 0.4],
        common_errors=["混淆电突触和化学突触", "遗漏突触间隙的作用"],
        reference_answer="突触由突触前膜、突触间隙和突触后膜组成。神经递质从突触前膜释放，穿过突触间隙，与突触后膜上的受体结合。",
        difficulty="intermediate",
        bloom_level="应用/分析",
    )

    print("=== 测试 1: 完全正确 ===")
    result = evaluate_result(
        hit_points=["突触前膜", "突触间隙", "突触后膜", "神经递质释放与受体结合"],
        has_common_error=False,
        criteria=criteria
    )
    print(f"correct={result['correct']}, rating={result['rating']}, score={result['score']}")
    print(f"feedback: {result['feedback']}")

    print("\n=== 测试 2: 部分正确 ===")
    result = evaluate_result(
        hit_points=["突触前膜", "突触间隙", "突触后膜"],
        has_common_error=False,
        criteria=criteria
    )
    print(f"correct={result['correct']}, rating={result['rating']}, score={result['score']}")
    print(f"feedback: {result['feedback']}")

    print("\n=== 测试 3: 有常见错误 ===")
    result = evaluate_result(
        hit_points=["突触前膜", "突触间隙"],
        has_common_error=True,
        criteria=criteria
    )
    print(f"correct={result['correct']}, rating={result['rating']}, score={result['score']}")
    print(f"feedback: {result['feedback']}")

    print("\n=== 测试 4: 按需展示答案 ===")
    answer = should_reveal_answer(True, criteria)
    print(answer)
