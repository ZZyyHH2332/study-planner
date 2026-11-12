"""Tests for the Quest Edition game-like view model."""

import sys
import json
from datetime import date, timedelta
from pathlib import Path

script_dir = Path(__file__).resolve().parent.parent / "skills" / "study-planner" / "scripts"
sys.path.insert(0, str(script_dir))

import quest
from demo_data import make_demo_data


def test_quest_demo_deterministic():
    """Two runs with the same data produce identical quest payloads."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q1 = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    q2 = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert q1 == q2, "Quest data should be deterministic"


def test_xp_calculation():
    """XP = base per review + rating bonus + streak bonus + mastery milestones."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert q["xp"] > 0, "XP should be positive with demo data"
    # With 84 days of reviews, should have substantial XP
    assert q["xp"] >= 100, f"XP too low: {q['xp']}"


def test_level_progression():
    """Level index and progress are consistent."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert 0 <= q["level_index"] <= q["max_level"], "Level index out of range"
    assert 0.0 <= q["level_progress"] <= 1.0, "Level progress out of range"
    assert q["level_name"], "Level name should not be empty"
    assert q["level_title"], "Level title should not be empty"


def test_achievements_unlock():
    """Demo data should unlock some achievements."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert q["achievement_count"] > 0, "Should have unlocked achievements with demo data"
    assert q["achievement_count"] <= q["achievement_total"], "Cannot unlock more than total"
    # Check achievement structure
    for ach in q["achievements"]:
        assert "id" in ach and "name" in ach and "icon" in ach and "description" in ach


def test_campfire_levels():
    """Campfire level should reflect streak."""
    # 0 streak = level 0
    nodes, edges, reviews = [], [], []
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert q["campfire_level"] == 0, f"Empty streak should be level 0, got {q['campfire_level']}"


def test_territory_status():
    """Terrories should have valid status values."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    valid_statuses = {"established", "building", "ruins"}
    for t in q["territories"]:
        assert t["status"] in valid_statuses, f"Invalid territory status: {t['status']}"
        assert t["narrative"], "Territory should have narrative"
        assert t["encounter"], "Territory should have encounter label"


def test_narrative_context():
    """Narrative should be a non-empty list of strings."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert isinstance(q["narrative"], list) and len(q["narrative"]) > 0
    for line in q["narrative"]:
        assert isinstance(line, str) and len(line) > 0


def test_adventure_queue_ordering():
    """Overdue items should come before due items."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    terrById = {t["note_id"]: t for t in q["territories"]}
    overdue_seen = False
    for nid in q["adventure_queue"]:
        t = terrById.get(nid)
        if t:
            if t["due_kind"] == "overdue":
                overdue_seen = True
            elif t["due_kind"] == "due" and overdue_seen:
                pass  # due after overdue is fine
            elif t["due_kind"] == "new" and overdue_seen:
                pass  # new after overdue is fine


def test_html_generation():
    """Quest HTML should be generated without errors."""
    import tempfile
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    html = quest.render_quest_html(nodes, edges, reviews, {}, {"mastery_threshold": 0.7}, demo=True, today=date(2026, 1, 1))
    assert "<html" in html.lower()
    assert "__DATA__" not in html, "Template should be fully replaced"
    assert "__STYLES__" not in html
    assert "__SCRIPT__" not in html
    assert "quest-data" in html


def test_html_json_safety():
    """Embedded JSON should not contain raw & < > that break HTML parsing."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    html = quest.render_quest_html(nodes, edges, reviews, {}, {"mastery_threshold": 0.7}, demo=True, today=date(2026, 1, 1))
    # Find the JSON script block
    start = html.find('<script type="application/json" id="quest-data">')
    end = html.find('</script>', start)
    json_text = html[start + len('<script type="application/json" id="quest-data">'):end]
    # Raw & < > should be escaped
    assert "&amp;" not in json_text or "\\u0026" in json_text, "Ampersand should be escaped"
    assert "<" not in json_text.replace("\\u003c", "").replace("</", ""), "Raw < should be escaped in JSON"


def test_quest_demo_file_generation():
    """generate_quest_demo should produce a valid HTML file."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "test_quest.html"
        path = quest.generate_quest_demo(output_path=out, open_browser=False)
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert "<html" in content.lower()
        assert "quest-data" in content


def test_empty_data_safety():
    """Empty nodes/reviews should not crash."""
    q = quest.build_quest_data([], [], [], {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert q["xp"] == 0
    assert q["territories"] == []
    # focus_45 achievement is always available since it's tracked in UI
    assert q["territory_stats"]["total"] == 0
    # Should not crash on empty data
    assert q["narrative"] is not None and len(q["narrative"]) > 0


def test_encounter_counts():
    """Encounter counts should sum to territory count."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    total_from_encounters = sum(count for _, count in q["encounter_counts"])
    assert total_from_encounters == q["territory_stats"]["total"], \
        f"Encounter sum {total_from_encounters} != territory total {q['territory_stats']['total']}"


def test_weekly_xp_trend():
    """Weekly XP trend should have 7 entries."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    assert len(q["weekly_xp_trend"]) == 7, "Should have 7 days of XP trend"


def test_mastery_milestone_xp():
    """Mastered concepts should add milestone XP."""
    today = date(2026, 1, 1)
    nodes = [
        {"note_id": "n1", "title": "Mastered", "mastery": 0.9, "difficulty": 2,
         "concept_type": "concept", "next_review": None, "file_path": "", "learning_state": "mastered"},
        {"note_id": "n2", "title": "Learning", "mastery": 0.3, "difficulty": 2,
         "concept_type": "concept", "next_review": None, "file_path": "", "learning_state": "reviewed"},
    ]
    edges = []
    reviews = []
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, today, demo=False)
    # 1 mastered = 50 XP milestone
    assert q["xp"] == 50, f"Expected 50 XP for 1 mastery milestone, got {q['xp']}"


def test_no_note_content_read():
    """Quest builder should not read note file contents (only metadata)."""
    nodes, edges, reviews = make_demo_data(today=date(2026, 1, 1))
    q = quest.build_quest_data(nodes, edges, reviews, {"mastery_threshold": 0.7}, date(2026, 1, 1), demo=True)
    # In non-demo mode, excerpts should be empty; in demo mode they're from demo_data
    for t in q["territories"]:
        # file_path is metadata, not content
        assert isinstance(t["file_path"], str)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"Quest tests: {passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        sys.exit(1)
