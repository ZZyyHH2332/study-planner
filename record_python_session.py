#!/usr/bin/env python3
"""Record Python study session: Day 1 basics."""
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent / "skills" / "study-planner" / "scripts"
sys.path.insert(0, str(script_dir))

from session_sync import StudySession

session = StudySession()
session.start()

result = session.review("202609020906", 3, True, "python-fde")
mastery = result.get("new_mastery", 0)
interval = result.get("new_interval", 0)
print(f"202609020906: mastery={mastery:.4f}, next_review={interval}d")

summary = session.end(notes="Python基础语法 Day1: 变量+print+str+f-string")
print(f"\nSession: {summary.get('session_id', '?')}")
