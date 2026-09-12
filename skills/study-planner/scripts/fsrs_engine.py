#!/usr/bin/env python3
"""FSRS-inspired spaced repetition scheduler for Study Planner plugin.

Implements a simplified FSRS (Free Spaced Repetition Scheduler) that uses
4-level rating (again/hard/good/easy) and ease_factor-based interval scheduling.

Rating scale:
  1 = Again   (complete blackout, reset interval)
  2 = Hard    (significant effort, small interval increase)
  3 = Good    (correct with normal effort, standard interval increase)
  4 = Easy    (instant recall, accelerated interval increase)

Core parameters:
  ease_factor    - Controls interval growth rate (starts at 2.5, min 1.3)
  interval       - Days until next review
  repetition     - Number of successful reviews in a row

The scheduler also supports a desired retention rate (default 0.9 = 90%)
which can be personalized over time from the learner profile.
"""

import sys
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager

RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4

RATING_NAMES = {
    1: "again",
    2: "hard",
    3: "good",
    4: "easy",
}

DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
DEFAULT_DESIRED_RETENTION = 0.9


def get_desired_retention(config=None):
    """Get the desired retention rate from learner profile."""
    retention = profile_manager.get_profile("retention_profile", config)
    if isinstance(retention, dict):
        return retention.get("desired_retention", DEFAULT_DESIRED_RETENTION)
    return DEFAULT_DESIRED_RETENTION


def calculate_interval(repetition, ease_factor, rating, prev_interval=0):
    """Calculate the next review interval in days.

    Uses a modified SM-2/FSRS hybrid:
    - First review: short intervals based on rating
    - Subsequent: interval * ease_factor * rating_modifier

    Args:
        repetition: Number of consecutive successful reviews
        ease_factor: Current ease factor (>= 1.3)
        rating: 1-4 (again/hard/good/easy)
        prev_interval: Previous interval in days

    Returns:
        (new_interval_days, new_ease_factor, new_repetition)
    """
    if type(rating) is not int or rating not in RATING_NAMES:
        raise ValueError("Rating must be an integer from 1 to 4.")
    ease = max(MIN_EASE_FACTOR, ease_factor)

    if rating == RATING_AGAIN:
        return 0, round(max(MIN_EASE_FACTOR, ease - 0.2), 2), 0

    if repetition == 0:
        base_intervals = {RATING_HARD: 1, RATING_GOOD: 2, RATING_EASY: 4}
        new_interval = base_intervals.get(rating, 2)
    elif repetition == 1:
        modifier = {RATING_HARD: 3, RATING_GOOD: 4, RATING_EASY: 8}
        new_interval = modifier.get(rating, 4)
    else:
        modifier = {RATING_HARD: 1.2, RATING_GOOD: ease, RATING_EASY: ease * 1.3}
        growth = modifier.get(rating, ease)
        new_interval = max(1, round(prev_interval * growth))

    new_interval = min(new_interval, 365 * 2)

    ease_delta = {RATING_HARD: -0.15, RATING_GOOD: 0.0, RATING_EASY: 0.15}
    new_ease = ease + ease_delta.get(rating, 0.0)
    new_ease = max(MIN_EASE_FACTOR, min(3.0, new_ease))

    new_repetition = repetition + 1

    return new_interval, round(new_ease, 2), new_repetition


def schedule_review(note_id, rating, config=None):
    """Schedule the next review for a knowledge node.

    This is the main entry point for the FSRS engine during a study session.
    Updates the node's review scheduling fields in the database.

    Args:
        note_id: The knowledge node ID
        rating: 1-4 (again/hard/good/easy)
        config: Plugin config

    Returns:
        dict with scheduling info
    """
    if type(rating) is not int or rating not in RATING_NAMES:
        raise ValueError("Rating must be an integer from 1 to 4.")
    node = db_manager.get_node(note_id, config)
    if node is None:
        return {"error": f"Node {note_id} not found"}

    prev_ease = 2.5
    if "ease_factor" in node and node["ease_factor"]:
        try:
            prev_ease = float(node["ease_factor"])
        except (ValueError, TypeError):
            pass

    prev_interval = 0
    repetition = 0
    try:
        repetition = int(node.get("review_count", 0) or 0)
    except (ValueError, TypeError):
        repetition = 0

    conn = db_manager.get_connection(config)
    last_review_row = conn.execute(
        """SELECT new_interval FROM review_log
           WHERE note_id = ? AND new_interval IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1""",
        (note_id,)
    ).fetchone()
    conn.close()

    if last_review_row and last_review_row["new_interval"]:
        prev_interval = last_review_row["new_interval"]

    if rating == RATING_AGAIN:
        repetition = 0

    new_interval, new_ease, new_repetition = calculate_interval(
        repetition, prev_ease, rating, prev_interval
    )

    today = datetime.now().astimezone()
    if new_interval > 0:
        next_review_date = today + timedelta(days=new_interval)
    else:
        next_review_date = today + timedelta(minutes=10)

    next_review_str = next_review_date.strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    db_manager.upsert_node(
        note_id=note_id,
        ease_factor=new_ease,
        review_count=new_repetition,
        last_reviewed=today_str,
        next_review=next_review_str,
        config=config,
    )

    retention_profile = profile_manager.get_profile("retention_profile", config)
    if isinstance(retention_profile, dict):
        all_eases = retention_profile.get("ease_factors", [])
        all_eases.append(new_ease)
        if len(all_eases) > 100:
            all_eases = all_eases[-100:]
        retention_profile["ease_factors"] = all_eases
        retention_profile["avg_ease_factor"] = round(
            sum(all_eases) / len(all_eases), 2
        )
        profile_manager.update_profile("retention_profile", retention_profile, config)

    return {
        "note_id": note_id,
        "rating": rating,
        "rating_name": RATING_NAMES.get(rating, "?"),
        "prev_interval": prev_interval,
        "new_interval": new_interval,
        "next_review": next_review_str,
        "ease_factor": new_ease,
        "repetition": new_repetition,
    }


def get_due_reviews(config=None):
    """Return all due/new learnable nodes, including mastered nodes when due."""
    return get_review_queue(limit=None, config=config)


def get_review_queue(limit=20, config=None):
    """Prioritize overdue, then due today, then never scheduled.

    Scheduled dates use the local calendar, matching schedule_review and the
    offline workspace. Mastery is not an exemption from future reviews.
    """
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("Limit must be a non-negative integer or None.")
    today = datetime.now().strftime("%Y-%m-%d")
    conn = db_manager.get_connection(config)
    try:
        rows = conn.execute(
            """SELECT * FROM knowledge_nodes
               WHERE TRIM(COALESCE(concept_type, '')) NOT IN ('', 'moc', 'literature', 'stub')
               AND (next_review IS NULL OR next_review = '' OR next_review <= ?)
               ORDER BY
                 CASE WHEN next_review IS NULL OR next_review = '' THEN 2
                      WHEN next_review < ? THEN 0 ELSE 1 END,
                 next_review ASC, mastery ASC, difficulty DESC, note_id ASC
               LIMIT ?""",
            (today, today, -1 if limit is None else limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def predict_retention(note_id, days_since_review=None, config=None):
    """Predict the probability of retaining a knowledge point.

    Uses an exponential decay model based on ease_factor and time.
    This is a simplified FSRS retrievability calculation.

    R(t) = exp(-t / (ease_factor * stability_constant))
    """
    node = db_manager.get_node(note_id, config)
    if node is None:
        return 0.0

    last_reviewed = node.get("last_reviewed")
    if not last_reviewed:
        return 0.0

    try:
        review_time = datetime.strptime(last_reviewed, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if days_since_review is None:
            now = datetime.now(timezone.utc)
            days_since = (now - review_time).total_seconds() / 86400
        else:
            days_since = days_since_review

        ease = 2.5
        try:
            ease = float(node.get("ease_factor", 2.5) or 2.5)
        except (ValueError, TypeError):
            pass

        interval = 1
        conn = db_manager.get_connection(config)
        last_log = conn.execute(
            "SELECT new_interval FROM review_log WHERE note_id = ? AND new_interval IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1",
            (note_id,)
        ).fetchone()
        conn.close()
        if last_log and last_log["new_interval"]:
            interval = last_log["new_interval"]

        decay_constant = interval * ease
        retention = math.exp(-days_since / max(decay_constant, 1))

        return max(0.0, min(1.0, retention))

    except (ValueError, TypeError):
        return 0.0


if __name__ == "__main__":
    print("=== FSRS Engine Test ===\n")

    print("1. Simulating review schedule for a new card (rating=good):")
    interval, ease, rep = calculate_interval(0, 2.5, RATING_GOOD)
    print(f"   Interval: {interval} days, Ease: {ease}, Repetition: {rep}\n")

    print("2. Second review (rating=good, prev_interval=2):")
    interval, ease, rep = calculate_interval(1, 2.5, RATING_GOOD, prev_interval=2)
    print(f"   Interval: {interval} days, Ease: {ease}, Repetition: {rep}\n")

    print("3. Third review (rating=easy, prev_interval=4):")
    interval, ease, rep = calculate_interval(2, 2.5, RATING_EASY, prev_interval=4)
    print(f"   Interval: {interval} days, Ease: {ease}, Repetition: {rep}\n")

    print("4. Lapse (rating=again, prev_interval=10):")
    interval, ease, rep = calculate_interval(3, 2.8, RATING_AGAIN, prev_interval=10)
    print(f"   Interval: {interval} days, Ease: {ease}, Repetition: {rep}\n")

    print("5. After lapse, next review (rating=hard):")
    interval, ease, rep = calculate_interval(0, 2.6, RATING_HARD, prev_interval=0)
    print(f"   Interval: {interval} days, Ease: {ease}, Repetition: {rep}")
