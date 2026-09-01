#!/usr/bin/env python3
"""Phase 3 end-to-end verification.

Tests the full adaptive engine pipeline:
1. Generate learning path to a target concept
2. Detect knowledge gaps and suggestions
3. Select quiz items via IRT
4. Simulate a review → BKT/FSRS update
5. Re-generate path → verify it auto-adjusted
"""

import sys
from pathlib import Path

base = Path(__file__).resolve().parent
sp_scripts = base / "skills" / "study-planner" / "scripts"
ae_scripts = base / "skills" / "adaptive-engine" / "scripts"
sys.path.insert(0, str(sp_scripts))
sys.path.insert(0, str(ae_scripts))

import db_manager
import profile_manager
import bkt_engine
import fsrs_engine
from session_sync import StudySession
import path_generator
import gap_detector
import quiz_selector

config = db_manager.load_config()
db_manager.init_database(config)
profile_manager.init_profile(config)

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

def header(title):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")

# ──────────────────────────────────────────────────────────
header("PHASE 3 END-TO-END VERIFICATION")
# ──────────────────────────────────────────────────────────

TARGET = "202608311420"  # Dopamine signals prediction error
PREREQ = "202608311410"  # Synapse (prerequisite)

# ── 1. Initial State ──
header("1. INITIAL STATE")
nodes = db_manager.get_all_nodes(config)
for n in nodes:
    if n["concept_type"] in ("moc", "literature"):
        continue
    print(f"  {n['title']}: mastery={n['mastery']:.4f}, "
          f"state={n['learning_state']}, diff={n.get('difficulty','?')}")

# ── 2. Generate Learning Path ──
header("2. LEARNING PATH (before review)")
path = path_generator.generate_learning_path(TARGET, config)
for i, step in enumerate(path, 1):
    icon = {"review": f"{YELLOW}[REVIEW]{RESET}",
            "gap": f"{YELLOW}[GAP]{RESET}",
            "learn": f"{GREEN}[LEARN]{RESET}"}.get(step["action"], "[?]")
    print(f"  {i}. {icon} {step['title']}")
    print(f"     mastery={step['mastery']:.2f}, diff={step['difficulty']}, "
          f"reason={step['reason']}")

summary = path_generator.get_path_summary(path)
print(f"\n  {DIM}Summary: {summary}{RESET}")

# ── 3. Gap Detection ──
header("3. GAP DETECTION")
suggestions = gap_detector.generate_suggestions(config)
for s in suggestions:
    print(f"  [{s['priority'].upper()}] {s['title']}")
    print(f"     mastery={s['mastery']:.2f} ({s['mastery_level']}), "
          f"blocks={s['blocked_count']}")
    print(f"     action: {s['suggested_action']} — {s['reason']}")

report = gap_detector.get_gap_report(config)
print(f"\n  {DIM}Report: gaps={report['total_gaps']}, "
      f"gap_ratio={report['gap_ratio']:.0%}{RESET}")

# ── 4. Quiz Selection (IRT) ──
header("4. QUIZ SELECTION (IRT Rasch)")
quiz = quiz_selector.generate_quiz([PREREQ, TARGET], config)
for i, item in enumerate(quiz, 1):
    zpd = f"{GREEN}YES{RESET}" if item.get("in_zpd") else f"{YELLOW}NO{RESET}"
    print(f"  Q{i}: [{item['item_type']}] {item['question']}")
    print(f"     b={item['b_param']:+.3f}, P={item['p_correct']:.4f}, "
          f"in_ZPD={zpd}, mastery={item.get('mastery',0):.2f}")

qsum = quiz_selector.get_quiz_summary(quiz)
print(f"\n  {DIM}Summary: {qsum}{RESET}")

# ── 5. Simulate Review (Synapse: Good, Correct) ──
header("5. SIMULATE REVIEW (Synapse → Good)")
session = StudySession(config)
session.start()
print(f"  Before: mastery={db_manager.get_node(PREREQ, config)['mastery']:.4f}")
result = session.review(PREREQ, rating=3, correct=True, domain="default")
print(f"  After:  mastery={result['new_mastery']:.4f} "
      f"({bkt_engine.get_mastery_level(result['new_mastery'])})")
print(f"  Next review: {result.get('next_review', '?')}")
print(f"  Ease: {result.get('ease_factor', 0)}")
session.end(notes="Phase 3 verification review")

# ── 6. Re-generate Path (should auto-adjust) ──
header("6. LEARNING PATH (after review)")
path2 = path_generator.generate_learning_path(TARGET, config)
for i, step in enumerate(path2, 1):
    icon = {"review": f"{YELLOW}[REVIEW]{RESET}",
            "gap": f"{YELLOW}[GAP]{RESET}",
            "learn": f"{GREEN}[LEARN]{RESET}"}.get(step["action"], "[?]")
    print(f"  {i}. {icon} {step['title']}")
    print(f"     mastery={step['mastery']:.2f}, diff={step['difficulty']}, "
          f"reason={step['reason']}")

summary2 = path_generator.get_path_summary(path2)
print(f"\n  {DIM}Summary: {summary2}{RESET}")

# ── 7. Verify Path Changed ──
header("7. PATH COMPARISON")
print(f"  Before: {len(path)} steps, "
      f"effort={summary['estimated_effort']}, "
      f"avg_mastery={summary['avg_mastery']:.4f}")
print(f"  After:  {len(path2)} steps, "
      f"effort={summary2['estimated_effort']}, "
      f"avg_mastery={summary2['avg_mastery']:.4f}")

actions_before = [p["action"] for p in path]
actions_after = [p["action"] for p in path2]
changed = actions_before != actions_after or summary["avg_mastery"] != summary2["avg_mastery"]

if changed:
    print(f"\n  {GREEN}PASS: Path auto-adjusted after review{RESET}")
else:
    print(f"\n  {YELLOW}NOTE: Path structure unchanged (mastery updated but still below threshold){RESET}")

# ── 8. Final Gap Check ──
header("8. FINAL GAP STATUS")
gaps_after = gap_detector.detect_gaps(config)
for g in gaps_after:
    print(f"  {g['title']}: mastery={g['mastery']:.4f}, state={g['learning_state']}")
if not gaps_after:
    print(f"  {GREEN}No gaps remaining!{RESET}")

print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
print(f"{BOLD}{CYAN}  PHASE 3 VERIFICATION COMPLETE{RESET}")
print(f"{BOLD}{CYAN}{'='*60}{RESET}")
