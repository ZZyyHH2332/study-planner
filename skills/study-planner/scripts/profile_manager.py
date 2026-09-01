#!/usr/bin/env python3
"""Learner profile manager for Study Planner plugin.

Manages the holistic learner state stored in SQLite (learner_profile table).
Each profile update also appends to profile_history for trajectory tracking.

Profile keys:
  - learning_goals:       [{goal, target_date, priority, moc_id}]
  - study_patterns:       {peak_hours, avg_duration, frequency, preferred_days}
  - retention_profile:    {fsrs_stability, fsrs_difficulty, avg_ease_factor}
  - difficulty_calibration: {bias, trend, sample_count}
  - bkt_params:           {default: {p_init, p_transit, p_slip, p_guess}, <domain>: {...}}
  - content_affinity:     {video, text, practice, audio}
  - weak_areas:           [{note_id, concept, failure_rate, last_attempt}]
  - trajectory_history:   [{date, mastery_avg, goals_progress, notes_added}]
  - total_study_minutes:  integer
  - total_reviews:        integer
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager

DEFAULT_BKT = {
    "p_init": 0.1,
    "p_transit": 0.3,
    "p_slip": 0.1,
    "p_guess": 0.2,
}

DEFAULT_PROFILE = {
    "learning_goals": [],
    "study_patterns": {
        "peak_hours": [],
        "avg_duration": 0,
        "frequency": 0,
        "preferred_days": [],
    },
    "retention_profile": {
        "avg_ease_factor": 2.5,
        "stability_trend": [],
    },
    "difficulty_calibration": {
        "bias": 0.0,
        "trend": "stable",
        "sample_count": 0,
    },
    "bkt_params": {
        "default": DEFAULT_BKT,
    },
    "content_affinity": {
        "video": 0.0,
        "text": 0.0,
        "practice": 0.0,
        "audio": 0.0,
    },
    "weak_areas": [],
    "trajectory_history": [],
    "total_study_minutes": 0,
    "total_reviews": 0,
}


def init_profile(config=None):
    """Initialize the learner profile with defaults if not already present."""
    existing = db_manager.get_profile(config=config)
    existing_keys = {e["key"] for e in existing} if existing else set()

    for key, default_value in DEFAULT_PROFILE.items():
        if key not in existing_keys:
            db_manager.set_profile(key, default_value, config=config)

    return get_full_profile(config)


def get_profile(key, config=None):
    """Get a single profile value (parsed from JSON)."""
    entry = db_manager.get_profile(key, config=config)
    if entry is None:
        return DEFAULT_PROFILE.get(key)
    try:
        return json.loads(entry["value"])
    except (json.JSONDecodeError, TypeError):
        return entry["value"]


def get_full_profile(config=None):
    """Get the entire learner profile as a dict."""
    entries = db_manager.get_profile(config=config)
    if not entries:
        return dict(DEFAULT_PROFILE)

    profile = {}
    for entry in entries:
        try:
            profile[entry["key"]] = json.loads(entry["value"])
        except (json.JSONDecodeError, TypeError):
            profile[entry["key"]] = entry["value"]

    for key, default_val in DEFAULT_PROFILE.items():
        if key not in profile:
            profile[key] = default_val

    return profile


def update_profile(key, value, config=None):
    """Update a profile key. Also appends to history."""
    db_manager.set_profile(key, value, config)


def get_bkt_params(domain="default", config=None):
    """Get BKT parameters for a specific domain (or default)."""
    bkt_data = get_profile("bkt_params", config)
    if not isinstance(bkt_data, dict):
        bkt_data = {"default": DEFAULT_BKT}

    if domain in bkt_data:
        params = bkt_data[domain]
    else:
        params = bkt_data.get("default", DEFAULT_BKT)

    return {
        "p_init": float(params.get("p_init", DEFAULT_BKT["p_init"])),
        "p_transit": float(params.get("p_transit", DEFAULT_BKT["p_transit"])),
        "p_slip": float(params.get("p_slip", DEFAULT_BKT["p_slip"])),
        "p_guess": float(params.get("p_guess", DEFAULT_BKT["p_guess"])),
    }


def set_bkt_params(domain, params, config=None):
    """Set BKT parameters for a specific domain."""
    bkt_data = get_profile("bkt_params", config)
    if not isinstance(bkt_data, dict):
        bkt_data = {"default": DEFAULT_BKT}
    bkt_data[domain] = params
    update_profile("bkt_params", bkt_data, config)


def add_learning_goal(goal, target_date, priority="medium", moc_id=None, config=None):
    """Add a learning goal to the profile."""
    goals = get_profile("learning_goals", config)
    if not isinstance(goals, list):
        goals = []

    goals.append({
        "goal": goal,
        "target_date": target_date,
        "priority": priority,
        "moc_id": moc_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    update_profile("learning_goals", goals, config)
    return goals


def remove_learning_goal(goal_text, config=None):
    """Remove a learning goal by partial match."""
    goals = get_profile("learning_goals", config)
    if not isinstance(goals, list):
        return []

    goals = [g for g in goals if goal_text.lower() not in g.get("goal", "").lower()]
    update_profile("learning_goals", goals, config)
    return goals


def update_study_patterns(session_start, session_end, duration_minutes, config=None):
    """Update study patterns based on a completed session."""
    patterns = get_profile("study_patterns", config)
    if not isinstance(patterns, dict):
        patterns = DEFAULT_PROFILE["study_patterns"]

    try:
        start_hour = datetime.fromisoformat(session_start.replace("Z", "+00:00")).hour
    except (ValueError, AttributeError):
        start_hour = None

    peak = patterns.get("peak_hours", [])
    if start_hour is not None and start_hour not in peak:
        peak.append(start_hour)
        peak.sort()
        if len(peak) > 5:
            peak = peak[-5:]

    total_minutes = get_profile("total_study_minutes", config) or 0
    total_sessions = patterns.get("frequency", 0)
    avg_dur = patterns.get("avg_duration", 0)

    new_total = total_minutes + duration_minutes
    new_count = total_sessions + 1
    new_avg = new_total / new_count if new_count > 0 else 0

    try:
        weekday = datetime.fromisoformat(
            session_start.replace("Z", "+00:00")
        ).strftime("%A")
        preferred = patterns.get("preferred_days", [])
        if weekday not in preferred:
            preferred.append(weekday)
    except (ValueError, AttributeError):
        preferred = patterns.get("preferred_days", [])

    patterns["peak_hours"] = peak
    patterns["avg_duration"] = round(new_avg, 1)
    patterns["frequency"] = new_count
    patterns["preferred_days"] = preferred

    update_profile("study_patterns", patterns, config)
    update_profile("total_study_minutes", new_total, config)


def add_weak_area(note_id, concept, failure_rate, config=None):
    """Add or update a weak area."""
    weak = get_profile("weak_areas", config)
    if not isinstance(weak, list):
        weak = []

    existing = None
    for w in weak:
        if w.get("note_id") == note_id:
            existing = w
            break

    if existing:
        existing["failure_rate"] = failure_rate
        existing["last_attempt"] = datetime.now(timezone.utc).isoformat()
    else:
        weak.append({
            "note_id": note_id,
            "concept": concept,
            "failure_rate": failure_rate,
            "last_attempt": datetime.now(timezone.utc).isoformat(),
        })

    weak.sort(key=lambda w: w.get("failure_rate", 0), reverse=True)
    if len(weak) > 50:
        weak = weak[:50]

    update_profile("weak_areas", weak, config)
    return weak


def remove_weak_area(note_id, config=None):
    """Remove a weak area (e.g., after mastery is achieved)."""
    weak = get_profile("weak_areas", config)
    if not isinstance(weak, list):
        return []

    weak = [w for w in weak if w.get("note_id") != note_id]
    update_profile("weak_areas", weak, config)
    return weak


def update_content_affinity(content_type, retention_rate, config=None):
    """Update content affinity (how well user retains from different content types)."""
    affinity = get_profile("content_affinity", config)
    if not isinstance(affinity, dict):
        affinity = DEFAULT_PROFILE["content_affinity"]

    if content_type in affinity:
        old = affinity[content_type]
        n = get_profile("total_reviews", config) or 1
        affinity[content_type] = round((old * (n - 1) + retention_rate) / n, 3)

    update_profile("content_affinity", affinity, config)


def record_trajectory(mastery_avg, goals_progress, notes_added, config=None):
    """Append a trajectory data point."""
    trajectory = get_profile("trajectory_history", config)
    if not isinstance(trajectory, list):
        trajectory = []

    trajectory.append({
        "date": datetime.now(timezone.utc).isoformat(),
        "mastery_avg": round(mastery_avg, 3),
        "goals_progress": goals_progress,
        "notes_added": notes_added,
    })

    if len(trajectory) > 365:
        trajectory = trajectory[-365:]

    update_profile("trajectory_history", trajectory, config)


def increment_review_count(config=None):
    """Increment the total review counter."""
    count = get_profile("total_reviews", config) or 0
    update_profile("total_reviews", count + 1, config)
    return count + 1


def get_profile_history(key, limit=30, config=None):
    """Get historical values of a profile key."""
    return db_manager.get_profile_history(key, limit, config)


def print_profile(config=None):
    """Print a human-readable profile summary."""
    profile = get_full_profile(config)

    print("\n" + "=" * 50)
    print("  Learner Profile Summary")
    print("=" * 50)

    print(f"\n  Total study time: {profile.get('total_study_minutes', 0)} min")
    print(f"  Total reviews: {profile.get('total_reviews', 0)}")

    patterns = profile.get("study_patterns", {})
    print(f"\n  Study Patterns:")
    print(f"    Peak hours: {patterns.get('peak_hours', [])}")
    print(f"    Avg duration: {patterns.get('avg_duration', 0)} min")
    print(f"    Sessions: {patterns.get('frequency', 0)}")
    print(f"    Preferred days: {patterns.get('preferred_days', [])}")

    goals = profile.get("learning_goals", [])
    print(f"\n  Learning Goals ({len(goals)}):")
    for g in goals:
        print(f"    - {g.get('goal', 'N/A')} (by {g.get('target_date', '?')}, {g.get('priority', '?')})")

    weak = profile.get("weak_areas", [])
    print(f"\n  Weak Areas ({len(weak)}):")
    for w in weak[:5]:
        print(f"    - {w.get('concept', '?')}: {w.get('failure_rate', 0):.0%} failure")

    bkt = profile.get("bkt_params", {})
    print(f"\n  BKT Parameters:")
    for domain, params in bkt.items():
        print(f"    [{domain}] slip={params.get('p_slip', '?')} guess={params.get('p_guess', '?')}")

    affinity = profile.get("content_affinity", {})
    print(f"\n  Content Affinity:")
    for ctype, rate in affinity.items():
        print(f"    {ctype}: {rate:.1%}")

    trajectory = profile.get("trajectory_history", [])
    if trajectory:
        latest = trajectory[-1]
        print(f"\n  Latest Trajectory:")
        print(f"    Date: {latest.get('date', '?')}")
        print(f"    Avg mastery: {latest.get('mastery_avg', 0):.1%}")
        print(f"    Goals progress: {latest.get('goals_progress', '?')}")
        print(f"    Notes added: {latest.get('notes_added', 0)}")

    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    profile = init_profile()
    print(f"Profile initialized with {len(profile)} keys.")
    print_profile()
