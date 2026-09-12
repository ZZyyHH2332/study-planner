#!/usr/bin/env python3
"""Record today's study session: Chinese literature - Day 1."""
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent / "skills" / "study-planner" / "scripts"
sys.path.insert(0, str(script_dir))

from session_sync import StudySession

session = StudySession()
session.start()

reviews = [
    ("202609020901", 3, True, "chinese-literature"),
    ("202609020902", 3, True, "chinese-literature"),
    ("202609020903", 3, True, "chinese-literature"),
    ("202609020904", 3, True, "chinese-literature"),
    ("202609020905", 3, True, "chinese-literature"),
]

for note_id, rating, correct, domain in reviews:
    result = session.review(note_id, rating, correct, domain)
    mastery = result.get("new_mastery", 0)
    interval = result.get("new_interval", 0)
    print(f"{note_id}: mastery={mastery:.4f}, next_review={interval}d")

summary = session.end(notes="第一天语文学习：先秦文学三座大山 + 唐宋八大家")
print(f"\nSession: {summary.get('session_id', '?')}")
print(f"Reviews: {summary.get('review_count', 0)}")
print(f"Updated nodes: {summary.get('updated_nodes', 0)}")
