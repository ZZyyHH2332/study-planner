#!/usr/bin/env python3
"""Session-level synchronization for Study Planner plugin.

Orchestrates a study session: starts session → processes reviews (BKT + FSRS)
→ ends session → batch-syncs frontmatter → updates learner profile.

Usage:
  from session_sync import StudySession
  session = StudySession(config)
  session.start()
  session.review("202608311410", rating=3, correct=True, domain="neuroscience")
  session.review("202608311420", rating=2, correct=False, domain="neuroscience")
  session.end(notes="Reviewed synapse and dopamine")

Frontmatter sync uses targeted line replacement to preserve original formatting.
Only learner-state fields are updated: mastery, learning_state, last_reviewed,
next_review, review_count, ease_factor.
"""

import re
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager
import bkt_engine
import fsrs_engine

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

SYNC_FIELDS = {
    "mastery", "learning_state", "last_reviewed",
    "next_review", "review_count", "ease_factor",
}


class StudySession:
    """Manages a single study session lifecycle."""

    def __init__(self, config=None):
        self.config = config or db_manager.load_config()
        self.session_id = None
        self.start_time = None
        self.reviews = []
        self.updated_nodes = set()

    def start(self):
        """Start a new study session."""
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.session_id = db_manager.create_session(self.start_time, self.config)
        return self.session_id

    def review(self, note_id, rating, correct, domain="default",
               content_type=None, question=None, scoring_criteria=None,
               user_answer=None, evaluation=None):
        """Process a single review during the session.

        Args:
            note_id: Knowledge node ID
            rating: 1=again, 2=hard, 3=good, 4=easy
            correct: Boolean
            domain: Knowledge domain for BKT params
            content_type: Content type for affinity tracking
            question: AI-generated question text (optional, AI mode)
            scoring_criteria: Scoring criteria dict (optional, AI mode)
            user_answer: User's answer text (optional, AI mode)
            evaluation: Evaluation result dict (optional, AI mode)

        Returns:
            dict with BKT and FSRS results
        """
        if self.session_id is None:
            self.start()

        bkt_result = bkt_engine.process_review(
            note_id=note_id,
            rating=rating,
            correct=correct,
            domain=domain,
            session_id=self.session_id,
            config=self.config,
        )

        fsrs_result = fsrs_engine.schedule_review(
            note_id=note_id,
            rating=rating,
            config=self.config,
        )

        if content_type and correct is not None:
            retention = 1.0 if correct else 0.0
            profile_manager.update_content_affinity(
                content_type, retention, self.config
            )

        self._update_review_log_fsrs(note_id, fsrs_result)

        review_entry = {
            "note_id": note_id,
            "rating": rating,
            "correct": correct,
            "bkt": bkt_result,
            "fsrs": fsrs_result,
        }

        # AI mode: store question + scoring + answer in session short-term memory
        if question:
            review_entry["question"] = question
            review_entry["scoring_criteria"] = scoring_criteria
            review_entry["user_answer"] = user_answer
            review_entry["evaluation"] = evaluation

        self.reviews.append(review_entry)
        self.updated_nodes.add(note_id)

        return {**bkt_result, **fsrs_result}

    def _update_review_log_fsrs(self, note_id, fsrs_result):
        """Patch the latest review_log row with FSRS scheduling data.

        BKT logs the review first (without FSRS fields); this method
        back-fills new_interval, prev_interval, and ease_factor so that
        review_log is a complete record and due-review queries work.
        """
        conn = db_manager.get_connection(self.config)
        conn.execute(
            """UPDATE review_log
               SET new_interval = ?, prev_interval = ?, ease_factor = ?
               WHERE id = (
                   SELECT id FROM review_log
                   WHERE note_id = ?
                   ORDER BY created_at DESC LIMIT 1
               )""",
            (
                fsrs_result.get("new_interval"),
                fsrs_result.get("prev_interval"),
                fsrs_result.get("ease_factor"),
                note_id,
            ),
        )
        conn.commit()
        conn.close()

    def end(self, notes=None):
        """End the session: close session record, sync frontmatter, update profile.

        Args:
            notes: Optional session notes

        Returns:
            dict with session summary
        """
        if self.session_id is None:
            return {"error": "Session not started"}

        end_time = datetime.now(timezone.utc).isoformat()
        duration = 0
        try:
            start_dt = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration = int((end_dt - start_dt).total_seconds() / 60)
        except (ValueError, TypeError):
            pass

        db_manager.close_session(
            session_id=self.session_id,
            end_time=end_time,
            duration_minutes=duration,
            notes=notes,
            config=self.config,
        )

        profile_manager.update_study_patterns(
            self.start_time, end_time, duration, self.config
        )

        sync_results = self._sync_frontmatter()

        self._update_trajectory()

        stats = db_manager.get_stats(self.config)
        profile_manager.record_trajectory(
            mastery_avg=stats.get("avg_mastery", 0),
            goals_progress=len(self.reviews),
            notes_added=0,
            config=self.config,
        )

        summary = {
            "session_id": self.session_id,
            "duration_minutes": duration,
            "reviews_count": len(self.reviews),
            "nodes_updated": len(self.updated_nodes),
            "frontmatter_synced": sync_results,
            "avg_mastery": stats.get("avg_mastery", 0),
        }
        return summary

    def _sync_frontmatter(self):
        """Batch-sync learner state to Obsidian note frontmatter.

        For each reviewed note, update the learner-state fields in the .md file.
        Uses targeted line replacement to preserve original formatting.
        """
        results = {"synced": 0, "skipped": 0, "errors": []}

        review_map = {}
        for r in self.reviews:
            review_map[r["note_id"]] = r

        for note_id in self.updated_nodes:
            node = db_manager.get_node(note_id, self.config)
            if not node:
                results["skipped"] += 1
                continue

            file_path = node.get("file_path")
            if not file_path or not Path(file_path).exists():
                results["skipped"] += 1
                continue

            try:
                self._update_note_file(file_path, node, review_map.get(note_id))
                results["synced"] += 1
            except Exception as e:
                results["errors"].append({
                    "note_id": note_id,
                    "file": file_path,
                    "error": str(e),
                })

        return results

    def _update_note_file(self, file_path, node, review_data=None):
        """Update learner-state fields in a note's frontmatter.

        Uses regex line replacement to preserve formatting.
        Prefers in-memory review_data (BKT + FSRS results from this session);
        falls back to querying review_log for non-session syncs.
        """
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) < 3:
            return

        fm_text = parts[1]
        body = parts[2]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        conn = db_manager.get_connection(self.config)
        review_count_row = conn.execute(
            "SELECT COUNT(*) as c FROM review_log WHERE note_id = ?",
            (node["note_id"],)
        ).fetchone()
        conn.close()
        review_count = review_count_row["c"] if review_count_row else 0

        if review_data:
            bkt = review_data.get("bkt", {})
            fsrs = review_data.get("fsrs", {})
            mastery = bkt.get("new_mastery", node.get("mastery", 0.1))
            learning_state = bkt.get("learning_state", node.get("learning_state", "pending"))
            ease = fsrs.get("ease_factor", 2.5)
            next_review = fsrs.get("next_review", today)
        else:
            mastery = node.get("mastery", 0.1)
            learning_state = node.get("learning_state", "pending")
            ease = 2.5
            next_review = today

        updates = {
            "mastery": f"{mastery:.4f}" if mastery is not None else "0.1",
            "learning_state": f'"{learning_state}"' if learning_state else '"pending"',
            "last_reviewed": f'"{today}"',
            "next_review": f'"{next_review}"',
            "review_count": str(review_count),
            "ease_factor": f"{ease:.2f}" if ease else "2.50",
        }

        updated_fm = self._replace_fields(fm_text, updates)

        new_content = f"---{updated_fm}---{body}"
        path.write_text(new_content, encoding="utf-8")

    def _replace_fields(self, fm_text, updates):
        """Replace field values in frontmatter text using regex.

        Preserves comments, indentation, and formatting of non-updated fields.
        """
        lines = fm_text.split("\n")
        result = []

        for line in lines:
            replaced = False
            for field, new_value in updates.items():
                pattern = re.compile(
                    rf'^(\s*{re.escape(field)}\s*:\s*)(.+)$'
                )
                match = pattern.match(line)
                if match:
                    prefix = match.group(1)
                    comment_idx = line.find("#")
                    comment = ""
                    if comment_idx > match.end():
                        comment = "  " + line[comment_idx:]
                    result.append(f"{prefix}{new_value}{comment}")
                    replaced = True
                    break

            if not replaced:
                result.append(line)

        return "\n".join(result)

    def _update_trajectory(self):
        """Record a trajectory data point for this session."""
        stats = db_manager.get_stats(self.config)
        profile_manager.record_trajectory(
            mastery_avg=stats.get("avg_mastery", 0),
            goals_progress=len(self.reviews),
            notes_added=0,
            config=self.config,
        )


def run_review_session(note_id, rating, correct, domain="default", config=None):
    """Convenience function: run a single-review session.

    Creates a session, processes one review, and closes the session with
    full frontmatter sync and profile update.
    """
    session = StudySession(config)
    session.start()
    result = session.review(note_id, rating, correct, domain)
    summary = session.end(notes=f"Single review of {note_id}")
    return {"review": result, "session": summary}


if __name__ == "__main__":
    print("=== Session Sync Test ===\n")

    config = db_manager.load_config()
    db_manager.init_database(config)
    profile_manager.init_profile(config)

    session = StudySession(config)
    session.start()
    print(f"Session started: ID={session.session_id}")

    print("\nReviewing 'Synapse' (202608311410) - rating=good, correct=True:")
    r1 = session.review("202608311410", rating=3, correct=True, domain="neuroscience")
    print(f"  Mastery: {r1.get('prev_mastery', '?')} → {r1.get('new_mastery', '?')}")
    print(f"  Next review: {r1.get('next_review', '?')}")
    print(f"  Ease: {r1.get('ease_factor', '?')}")

    print("\nReviewing 'Dopamine Prediction Error' (202608311420) - rating=again, correct=False:")
    r2 = session.review("202608311420", rating=1, correct=False, domain="neuroscience")
    print(f"  Mastery: {r2.get('prev_mastery', '?')} → {r2.get('new_mastery', '?')}")
    print(f"  Next review: {r2.get('next_review', '?')}")

    print("\nEnding session...")
    summary = session.end(notes="Test session: reviewed 2 cards")
    print(f"\nSession Summary:")
    print(f"  Duration: {summary.get('duration_minutes', 0)} min")
    print(f"  Reviews: {summary.get('reviews_count', 0)}")
    print(f"  Frontmatter synced: {summary.get('frontmatter_synced', {})}")
    print(f"  Avg mastery: {summary.get('avg_mastery', 0):.4f}")

    print("\n=== Learner Profile After Session ===")
    profile_manager.print_profile(config)
