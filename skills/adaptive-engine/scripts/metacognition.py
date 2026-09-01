#!/usr/bin/env python3
"""Metacognition layer — slow thinking for Study Planner.

Scans review history to detect abnormal patterns and generate diagnostic
suggestions. This is a diagnostic tool only — it does not modify learning
paths automatically.

Detection rules:
  1. Consecutive "Again" (3+) → attribution analysis
  2. Mastery stagnation (5+ reviews, mastery <0.5) → revisit prerequisites
  3. Prerequisite mastered but target still failing → comprehension gap
  4. High-difficulty concept sudden forget → check surface learning

Usage:
  from metacognition import diagnose
  report = diagnose(config)
  # report = {"alerts": [...], "summary": "...", "recommendations": [...]}
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

script_dir = Path(__file__).resolve().parent
study_planner_dir = script_dir.parent.parent / "study-planner" / "scripts"
sys.path.insert(0, str(study_planner_dir))
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager


def query_reviews_by_note(config=None):
    """Get reviews grouped by note_id, ordered by date."""
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT rl.*, kn.title, kn.difficulty
           FROM review_log rl
           LEFT JOIN knowledge_nodes kn ON rl.note_id = kn.note_id
           ORDER BY rl.note_id, rl.review_date"""
    ).fetchall()
    conn.close()

    by_note = defaultdict(list)
    for r in rows:
        by_note[r["note_id"]].append(dict(r))
    return by_note


def detect_consecutive_again(reviews_by_note):
    """Rule 1: 3+ consecutive 'Again' ratings."""
    alerts = []
    for note_id, seq in reviews_by_note.items():
        consecutive = 0
        max_consecutive = 0
        for r in seq:
            if r.get("rating") == 1:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive >= 3:
            title = seq[0].get("title", note_id)
            alerts.append({
                "type": "consecutive_again",
                "severity": "high",
                "note_id": note_id,
                "title": title,
                "consecutive_count": max_consecutive,
                "diagnosis": "连续遗忘 — 可能原因：前置概念缺口、理解断裂、或表面学习",
                "action": "检查前置概念掌握度，考虑回到前置概念重新学习",
            })
    return alerts


def detect_mastery_stagnation(reviews_by_note, config=None):
    """Rule 2: 5+ reviews but mastery still <0.5."""
    alerts = []
    for note_id, seq in reviews_by_note.items():
        if len(seq) >= 5:
            latest_mastery = seq[-1].get("new_mastery", 0)
            if latest_mastery < 0.5:
                title = seq[0].get("title", note_id)
                node = db_manager.get_node(note_id, config)
                prereqs = []
                if node:
                    edges = db_manager.get_edges(note_id=node["note_id"],
                                                edge_type="prerequisite", config=config)
                    for e in edges:
                        if e["target_id"] == note_id:
                            prereq = db_manager.get_node(e["source_id"], config)
                            if prereq:
                                prereqs.append({
                                    "title": prereq.get("title", prereq["note_id"]),
                                    "mastery": prereq.get("mastery", 0),
                                })

                alerts.append({
                    "type": "mastery_stagnation",
                    "severity": "medium",
                    "note_id": note_id,
                    "title": title,
                    "review_count": len(seq),
                    "current_mastery": round(latest_mastery, 2),
                    "prerequisites": prereqs,
                    "diagnosis": "多次复习后掌握度仍低 — 可能是深层理解问题而非记忆衰退",
                    "action": "检查前置概念是否真正掌握，考虑更换学习材料或方法",
                })
    return alerts


def detect_comprehension_gap(reviews_by_note, config=None):
    """Rule 3: Prerequisites mastered but target still failing."""
    alerts = []
    for note_id, seq in reviews_by_note.items():
        latest_mastery = seq[-1].get("new_mastery", 0)
        if latest_mastery < 0.4 and len(seq) >= 2:
            node = db_manager.get_node(note_id, config)
            if not node:
                continue

            edges = db_manager.get_edges(note_id=node["note_id"],
                                        edge_type="prerequisite", config=config)
            all_prereqs_mastered = False
            weak_prereqs = []
            for e in edges:
                if e["target_id"] == note_id:
                    prereq = db_manager.get_node(e["source_id"], config)
                    if prereq:
                        p_mastery = prereq.get("mastery", 0)
                        if p_mastery >= 0.7:
                            all_prereqs_mastered = True
                        else:
                            weak_prereqs.append({
                                "title": prereq.get("title", prereq["note_id"]),
                                "mastery": round(p_mastery, 2),
                            })

            if all_prereqs_mastered and not weak_prereqs:
                alerts.append({
                    "type": "comprehension_gap",
                    "severity": "high",
                    "note_id": note_id,
                    "title": node.get("title", note_id),
                    "current_mastery": round(latest_mastery, 2),
                    "diagnosis": "前置概念已掌握但目标概念仍失败 — 存在理解断裂",
                    "action": "该概念可能需要不同角度的解释或更多实践，而非简单重复复习",
                })
    return alerts


def detect_surface_learning(reviews_by_note):
    """Rule 4: High-difficulty concept with rapid mastery → then forgetting."""
    alerts = []
    for note_id, seq in reviews_by_note.items():
        if len(seq) < 2:
            continue

        difficulty = seq[0].get("difficulty", 1) or 1
        if difficulty < 3:
            continue

        first_mastery = seq[0].get("new_mastery", 0)
        last_mastery = seq[-1].get("new_mastery", 0)

        if first_mastery > 0.6 and last_mastery < first_mastery - 0.2:
            title = seq[0].get("title", note_id)
            alerts.append({
                "type": "surface_learning",
                "severity": "medium",
                "note_id": note_id,
                "title": title,
                "difficulty": difficulty,
                "peak_mastery": round(first_mastery, 2),
                "current_mastery": round(last_mastery, 2),
                "diagnosis": "高难度概念先升后降 — 可能是表面学习（死记硬背而非真正理解）",
                "action": "用应用题或分析题检验理解深度，避免纯记忆型复习",
            })
    return alerts


def diagnose(config=None):
    """Run all metacognition checks and generate a diagnostic report.

    Returns:
        dict with alerts (list), summary (str), recommendations (list)
    """
    reviews_by_note = query_reviews_by_note(config)

    if not reviews_by_note:
        return {
            "alerts": [],
            "summary": "暂无复习数据，无法进行元认知分析",
            "recommendations": [],
        }

    alerts = []
    alerts.extend(detect_consecutive_again(reviews_by_note))
    alerts.extend(detect_mastery_stagnation(reviews_by_note, config))
    alerts.extend(detect_comprehension_gap(reviews_by_note, config))
    alerts.extend(detect_surface_learning(reviews_by_note))

    recommendations = []
    high_count = sum(1 for a in alerts if a["severity"] == "high")
    medium_count = sum(1 for a in alerts if a["severity"] == "medium")

    if high_count > 0:
        recommendations.append(f"发现 {high_count} 个高优先级问题，建议优先处理连续遗忘和理解断裂的概念")
    if medium_count > 0:
        recommendations.append(f"发现 {medium_count} 个中优先级问题，关注掌握度停滞和表面学习")
    if not alerts:
        recommendations.append("未检测到异常模式，学习节奏良好")

    by_type = defaultdict(int)
    for a in alerts:
        by_type[a["type"]] += 1

    type_names = {
        "consecutive_again": "连续遗忘",
        "mastery_stagnation": "掌握度停滞",
        "comprehension_gap": "理解断裂",
        "surface_learning": "表面学习",
    }

    summary_parts = [f"{type_names.get(t, t)}: {c}" for t, c in by_type.items()]
    summary = f"共检测到 {len(alerts)} 个问题（高 {high_count} / 中 {medium_count}）"
    if summary_parts:
        summary += " — " + "，".join(summary_parts)

    return {
        "alerts": alerts,
        "summary": summary,
        "recommendations": recommendations,
        "total_notes_analyzed": len(reviews_by_note),
    }


if __name__ == "__main__":
    result = diagnose()
    print(json.dumps(result, indent=2, ensure_ascii=False))
