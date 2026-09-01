#!/usr/bin/env python3
"""Phase 2 end-to-end verification script.

Verifies the full pipeline: BKT mastery update → FSRS scheduling
→ review_log back-fill → frontmatter sync → learner profile update.
"""

import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent / "skills" / "study-planner" / "scripts"
sys.path.insert(0, str(script_dir))

import db_manager
import profile_manager
import bkt_engine
import fsrs_engine
from session_sync import StudySession

config = db_manager.load_config()

print("=" * 60)
print("  PHASE 2 END-TO-END VERIFICATION")
print("=" * 60)

# 1. Check review_log has FSRS data
print("\n[1] review_log FSRS back-fill check:")
conn = db_manager.get_connection(config)
rows = conn.execute(
    "SELECT note_id, rating, correct, new_mastery, new_interval, ease_factor "
    "FROM review_log ORDER BY id"
).fetchall()
conn.close()

all_ok = True
for r in rows:
    d = dict(r)
    has_fsrs = d["new_interval"] is not None and d["ease_factor"] is not None
    status = "OK" if has_fsrs else "FAIL"
    if not has_fsrs:
        all_ok = False
    print(f"  [{status}] {d['note_id']}: rating={d['rating']}, "
          f"correct={d['correct']}, mastery={d['new_mastery']:.4f}, "
          f"interval={d['new_interval']}, ease={d['ease_factor']}")

# 2. Check frontmatter sync
print("\n[2] Frontmatter sync check:")
for note_id in ["202608311410", "202608311420"]:
    node = db_manager.get_node(note_id, config)
    fp = node.get("file_path") if node else None
    if not fp or not Path(fp).exists():
        print(f"  [FAIL] {note_id}: file not found")
        all_ok = False
        continue
    content = Path(fp).read_text(encoding="utf-8")
    fm = content.split("---", 2)[1] if content.startswith("---") else ""
    import re
    def get_field(fm, name):
        m = re.search(rf'{name}:\s*"?([^"\n]+)"?', fm)
        return m.group(1).strip() if m else None

    mastery = get_field(fm, "mastery")
    next_review = get_field(fm, "next_review")
    ease = get_field(fm, "ease_factor")
    review_count = get_field(fm, "review_count")
    print(f"  [{note_id}] mastery={mastery}, next_review={next_review}, "
          f"ease={ease}, reviews={review_count}")

# 3. Check due reviews query
print("\n[3] Due reviews query:")
due = fsrs_engine.get_due_reviews(config)
print(f"  Due: {len(due)} notes")
for d in due:
    print(f"  - {d['note_id']}: {d['title']} (mastery={d['mastery']:.4f})")

# 4. Check review queue
print("\n[4] Review queue:")
queue = fsrs_engine.get_review_queue(config=config)
print(f"  Queue: {len(queue)} notes")
for q in queue:
    print(f"  - {q['note_id']}: {q['title']} (mastery={q['mastery']:.4f})")

# 5. Check learner profile
print("\n[5] Learner profile:")
total_reviews = profile_manager.get_profile("total_reviews", config)
weak_areas = profile_manager.get_profile("weak_areas", config)
patterns = profile_manager.get_profile("study_patterns", config)
print(f"  Total reviews: {total_reviews}")
print(f"  Weak areas: {weak_areas}")
print(f"  Study patterns: {patterns}")

# 6. Check BKT mastery levels
print("\n[6] BKT mastery levels:")
for note_id in ["202608311410", "202608311420"]:
    node = db_manager.get_node(note_id, config)
    mastery = node.get("mastery", 0)
    level = bkt_engine.get_mastery_level(mastery)
    state = node.get("learning_state", "?")
    print(f"  {note_id}: mastery={mastery:.4f} ({level}), state={state}")

# 7. Check retention prediction
print("\n[7] Retention prediction:")
for note_id in ["202608311410", "202608311420"]:
    retention = fsrs_engine.predict_retention(note_id, config=config)
    print(f"  {note_id}: predicted retention = {retention:.4f}")

print("\n" + "=" * 60)
if all_ok:
    print("  RESULT: ALL CHECKS PASSED")
else:
    print("  RESULT: SOME CHECKS FAILED")
print("=" * 60)
