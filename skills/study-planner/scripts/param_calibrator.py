#!/usr/bin/env python3
"""Parameter auto-calibration for BKT and FSRS.

Analyzes review_log to compute empirical BKT transition/slip/guess
probabilities and FSRS ease factor adjustments from actual forgetting curves.

Minimum data requirement: 10 review_log entries. Below that, defaults are kept.

Usage:
  from param_calibrator import calibrate_parameters
  results = calibrate_parameters(config)
  # results = {"bkt": {"p_transit": 0.35, ...}, "fsrs": {"ease_adjust": -0.1, ...}}
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager

MIN_REVIEWS = 10


def query_review_sequence(config=None):
    """Get all reviews ordered by note_id then date.

    Returns: dict {note_id: [review_dict, ...]}
    """
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT * FROM review_log ORDER BY note_id, review_date"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calibrate_bkt(reviews):
    """Compute empirical BKT parameters from review history.

    P(T) = P(correct at t+1 | incorrect at t)   — learning transition
    P(S) = P(incorrect at t | mastery >= 0.7)   — slip rate
    P(G) = P(correct at t | mastery < 0.3)      — guess rate
    """
    transitions = []
    slips = []
    guesses = []

    by_note = defaultdict(list)
    for r in reviews:
        by_note[r["note_id"]].append(r)

    for note_id, seq in by_note.items():
        for i in range(len(seq) - 1):
            curr = seq[i]
            nxt = seq[i + 1]
            curr_mastery = curr.get("new_mastery", 0)
            curr_correct = bool(curr.get("correct"))
            nxt_correct = bool(nxt.get("correct"))

            if not curr_correct and nxt_correct:
                transitions.append(1)
            elif not curr_correct and not nxt_correct:
                transitions.append(0)

            if curr_mastery >= 0.7 and not curr_correct:
                slips.append(1)
            elif curr_mastery >= 0.7 and curr_correct:
                slips.append(0)

            if curr_mastery < 0.3 and curr_correct:
                guesses.append(1)
            elif curr_mastery < 0.3 and not curr_correct:
                guesses.append(0)

    p_transit = sum(transitions) / len(transitions) if transitions else None
    p_slip = sum(slips) / len(slips) if slips else None
    p_guess = sum(guesses) / len(guesses) if guesses else None

    return {
        "p_transit": round(p_transit, 3) if p_transit is not None else None,
        "p_slip": round(p_slip, 3) if p_slip is not None else None,
        "p_guess": round(p_guess, 3) if p_guess is not None else None,
        "sample_transit": len(transitions),
        "sample_slip": len(slips),
        "sample_guess": len(guesses),
    }


def calibrate_fsrs(reviews, config=None):
    """Compute FSRS ease factor adjustment from actual retention.

    Logic: For each review where rating=3 (Good), compare expected vs actual
    retention. If the learner got it wrong too soon, ease should decrease.
    """
    by_note = defaultdict(list)
    for r in reviews:
        by_note[r["note_id"]].append(r)

    ease_adjustments = []

    for note_id, seq in by_note.items():
        for i in range(len(seq) - 1):
            curr = seq[i]
            nxt = seq[i + 1]
            interval = curr.get("new_interval", 0)

            if interval and interval > 0:
                actual_retention = 1.0 if bool(nxt.get("correct")) else 0.0
                expected_retention = 0.9

                error = actual_retention - expected_retention
                adjustment = error * 0.1
                ease_adjustments.append(adjustment)

    avg_adjust = sum(ease_adjustments) / len(ease_adjustments) if ease_adjustments else 0.0

    current_ease = 2.5
    try:
        retention = profile_manager.get_profile("retention_profile", config)
        if retention and "avg_ease_factor" in retention:
            current_ease = retention["avg_ease_factor"]
    except Exception:
        pass

    new_ease = max(1.3, round(current_ease + avg_adjust, 2))

    return {
        "current_ease": round(current_ease, 2),
        "avg_adjustment": round(avg_adjust, 3),
        "new_ease": new_ease,
        "sample_count": len(ease_adjustments),
    }


def apply_calibration(bkt_result, fsrs_result, config=None):
    """Apply calibrated parameters to learner profile."""
    updates = {}

    if bkt_result["p_transit"] is not None:
        params = profile_manager.get_bkt_params("default", config)
        params["p_transit"] = bkt_result["p_transit"]
        if bkt_result["p_slip"] is not None:
            params["p_slip"] = bkt_result["p_slip"]
        if bkt_result["p_guess"] is not None:
            params["p_guess"] = bkt_result["p_guess"]
        profile_manager.set_bkt_params("default", params, config)
        updates["bkt"] = params

    if fsrs_result["sample_count"] > 0:
        retention = profile_manager.get_profile("retention_profile", config) or {}
        retention["avg_ease_factor"] = fsrs_result["new_ease"]
        profile_manager.update_profile("retention_profile", retention, config)
        updates["fsrs_ease"] = fsrs_result["new_ease"]

    return updates


def calibrate_parameters(config=None):
    """Run full calibration: BKT + FSRS.

    Returns dict with before/after parameters and sample sizes.
    """
    reviews = query_review_sequence(config)

    if len(reviews) < MIN_REVIEWS:
        return {
            "status": "skipped",
            "reason": f"Insufficient data ({len(reviews)}/{MIN_REVIEWS} reviews)",
            "min_required": MIN_REVIEWS,
        }

    old_bkt = profile_manager.get_bkt_params("default", config)

    bkt_result = calibrate_bkt(reviews)
    fsrs_result = calibrate_fsrs(reviews, config)
    applied = apply_calibration(bkt_result, fsrs_result, config)

    return {
        "status": "calibrated",
        "total_reviews": len(reviews),
        "bkt": {
            "before": old_bkt,
            "after": bkt_result,
        },
        "fsrs": {
            "before": fsrs_result["current_ease"],
            "after": fsrs_result,
        },
        "applied": applied,
    }


if __name__ == "__main__":
    result = calibrate_parameters()
    print(json.dumps(result, indent=2, ensure_ascii=False))
