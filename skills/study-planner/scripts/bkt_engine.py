#!/usr/bin/env python3
"""Bayesian Knowledge Tracing (BKT) engine for Study Planner plugin.

BKT models each knowledge point as a binary latent state (known/unknown).
After each response (correct/incorrect), the mastery probability is updated
using Bayes' rule and a learning transition.

Parameters:
  P(L0)  = prior probability of knowing the skill (initial mastery)
  P(T)   = transition probability from unknown to known after practice
  P(S)   = slip probability (knows but answers wrong)
  P(G)   = guess probability (doesn't know but answers right)

Update rules:
  After correct:
    P(L|correct) = P(L)(1-P(S)) / [P(L)(1-P(S)) + (1-P(L))P(G)]
  After incorrect:
    P(L|incorrect) = P(L)P(S) / [P(L)P(S) + (1-P(L))(1-P(G))]
  Then apply transition:
    P(L_new) = P(L|response) + (1-P(L|response)) * P(T)
"""

import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager


def clamp_probability(p):
    """Clamp a probability to [0.01, 0.99] to avoid degenerate cases."""
    return max(0.01, min(0.99, p))


def update_mastery(current_mastery, correct, domain="default", config=None):
    """Update mastery probability after a response.

    Args:
        current_mastery: Current P(L) probability (0-1)
        correct: True if the response was correct, False if incorrect
        domain: Knowledge domain for parameter lookup (e.g., "neuroscience")
        config: Plugin config dict

    Returns:
        dict with:
          new_mastery: updated P(L)
          prev_mastery: original P(L)
          params: the BKT parameters used
          correct: the response
    """
    params = profile_manager.get_bkt_params(domain, config)

    p_l = clamp_probability(current_mastery)
    p_t = params["p_transit"]
    p_s = params["p_slip"]
    p_g = params["p_guess"]

    if correct:
        p_l_given = (p_l * (1 - p_s)) / (p_l * (1 - p_s) + (1 - p_l) * p_g)
    else:
        p_l_given = (p_l * p_s) / (p_l * p_s + (1 - p_l) * (1 - p_g))

    p_l_new = p_l_given + (1 - p_l_given) * p_t
    p_l_new = clamp_probability(p_l_new)

    return {
        "new_mastery": p_l_new,
        "prev_mastery": current_mastery,
        "params": params,
        "correct": correct,
        "domain": domain,
    }


def get_mastery_level(mastery):
    """Map mastery probability to a discrete level.

    Returns one of: 'novice', 'learning', 'familiar', 'proficient', 'mastered'
    """
    if mastery >= 0.85:
        return "mastered"
    elif mastery >= 0.70:
        return "proficient"
    elif mastery >= 0.50:
        return "familiar"
    elif mastery >= 0.25:
        return "learning"
    else:
        return "novice"


def get_learning_state(mastery, review_count=0):
    """Determine the learning_state field value based on mastery and reviews.

    Maps to the frontmatter field: pending → in_progress → reviewed → mastered
    """
    if review_count == 0:
        return "pending"
    elif mastery >= 0.85:
        return "mastered"
    elif mastery >= 0.50:
        return "reviewed"
    else:
        return "in_progress"


def calibrate_bkt_params(domain, review_data, config=None):
    """Calibrate BKT parameters from review history.

    Analyzes actual performance to adjust slip/guess/transit probabilities.
    Requires sufficient data (>= 10 reviews per domain) for meaningful calibration.

    Args:
        domain: The knowledge domain to calibrate
        review_data: List of {mastery_before, correct, mastery_after} dicts
        config: Plugin config

    Returns:
        Updated parameters dict, or None if insufficient data
    """
    if len(review_data) < 10:
        return None

    correct_when_known = 0
    total_when_known = 0
    correct_when_unknown = 0
    total_when_unknown = 0
    transitions = 0
    transition_opportunities = 0

    for entry in review_data:
        mastery = entry.get("mastery_before", 0.5)
        was_correct = entry.get("correct", False)

        if mastery > 0.5:
            total_when_known += 1
            if was_correct:
                correct_when_known += 1
        else:
            total_when_unknown += 1
            if not was_correct:
                pass

            transition_opportunities += 1
            mastery_after = entry.get("mastery_after", 0.5)
            if mastery_after > mastery:
                transitions += 1

    new_slip = 1 - (correct_when_known / total_when_known) if total_when_known > 0 else 0.1
    new_guess = correct_when_unknown / total_when_unknown if total_when_unknown > 0 else 0.2
    new_transit = transitions / transition_opportunities if transition_opportunities > 0 else 0.3

    new_slip = max(0.01, min(0.3, new_slip))
    new_guess = max(0.01, min(0.3, new_guess))
    new_transit = max(0.05, min(0.5, new_transit))

    new_params = {
        "p_init": 0.1,
        "p_transit": round(new_transit, 3),
        "p_slip": round(new_slip, 3),
        "p_guess": round(new_guess, 3),
    }

    profile_manager.set_bkt_params(domain, new_params, config)
    return new_params


def process_review(note_id, rating, correct, domain="default",
                   session_id=None, config=None):
    """Process a single review: update mastery in DB and log the review.

    This is the main entry point for the BKT engine during a study session.

    Args:
        note_id: The knowledge node ID being reviewed
        rating: FSRS rating (1=again, 2=hard, 3=good, 4=easy)
        correct: Boolean whether the answer was correct
        domain: Knowledge domain for BKT params
        session_id: Associated study session ID
        config: Plugin config

    Returns:
        dict with mastery update and review log info
    """
    node = db_manager.get_node(note_id, config)
    if node is None:
        return {"error": f"Node {note_id} not found"}

    prev_mastery = node.get("mastery", 0.1)
    review_count = node.get("review_count", 0)

    result = update_mastery(prev_mastery, correct, domain, config)
    new_mastery = result["new_mastery"]

    new_state = get_learning_state(new_mastery, review_count + 1)

    db_manager.upsert_node(
        note_id=note_id,
        mastery=new_mastery,
        learning_state=new_state,
        config=config,
    )

    db_manager.log_review(
        note_id=note_id,
        rating=rating,
        correct=correct,
        session_id=session_id,
        prev_mastery=prev_mastery,
        new_mastery=new_mastery,
        config=config,
    )

    profile_manager.increment_review_count(config)

    if not correct:
        node_title = node.get("title", note_id)
        profile_manager.add_weak_area(note_id, node_title, 1.0, config)
    elif new_mastery >= 0.70:
        profile_manager.remove_weak_area(note_id, config)

    return {
        "note_id": note_id,
        "prev_mastery": prev_mastery,
        "new_mastery": new_mastery,
        "mastery_level": get_mastery_level(new_mastery),
        "learning_state": new_state,
        "correct": correct,
        "rating": rating,
    }


if __name__ == "__main__":
    print("=== BKT Engine Test ===\n")

    print("1. Simulating correct answer on a new node (mastery=0.1):")
    result = update_mastery(0.1, correct=True)
    print(f"   0.10 → {result['new_mastery']:.4f} (level: {get_mastery_level(result['new_mastery'])})\n")

    print("2. Simulating incorrect answer on same node:")
    result = update_mastery(result["new_mastery"], correct=False)
    print(f"   → {result['new_mastery']:.4f} (level: {get_mastery_level(result['new_mastery'])})\n")

    print("3. Simulating 5 correct answers in a row:")
    mastery = 0.1
    for i in range(5):
        result = update_mastery(mastery, correct=True)
        mastery = result["new_mastery"]
        print(f"   Round {i+1}: → {mastery:.4f} ({get_mastery_level(mastery)})")
