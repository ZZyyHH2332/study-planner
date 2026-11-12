#!/usr/bin/env python3
"""Game-like view model builder for the Quest Edition workspace.

Transforms the same review/node data into a journey narrative:
  - XP and levels from review history
  - Achievements / badges unlocked by real milestones
  - Streak as a "campfire" that grows with consecutive days
  - Concepts as "territories" with building progress
  - Difficulty reframed as "encounter level"
  - Failures (Again ratings) reframed as "hard encounters survived"

No new database columns, no note writes, no CDN. Pure view-model layer.
"""

import math
from collections import Counter
from datetime import date, timedelta

# Reuse the safe primitives from the existing dashboard builder.
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from dashboard import _number, _day, build_workspace_data


# ── XP & Leveling ──────────────────────────────────────────────

XP_PER_REVIEW = 10          # base XP per review
XP_RATING_BONUS = {1: 0, 2: 5, 3: 10, 4: 20}   # Again/Hard/Good/Easy
XP_STREAK_BONUS = 2         # extra XP per day in current streak
XP_MASTERY_MILESTONE = 50   # one-time bonus when a concept hits "mastered"

LEVELS = [
    (0,    "萌芽",   "Seedling",    "你刚开始探索这片知识的荒原。"),
    (100,  "行者",   "Wanderer",    "脚步虽慢，但每一步都在丈量未知。"),
    (300,  "探索者", "Explorer",    "你已经能看见知识的轮廓了。"),
    (600,  "拓荒者", "Pioneer",     "废墟之上，你开始建立自己的大厦。"),
    (1000, "建造者", "Builder",     "知识不再是碎片，而是正在生长的结构。"),
    (1500, "守望者", "Guardian",    "你守护着已掌握的一切，也迎接新的挑战。"),
    (2200, "贤者",   "Sage",        "知识的星图在你心中连成星座。"),
    (3000, "传奇",   "Legend",      "你走过的路，本身就是一首史诗。"),
]


def compute_level(xp):
    """Return (level_index, level_name, level_title, level_desc, progress_to_next)."""
    current = 0
    for i, (threshold, name, title, desc) in enumerate(LEVELS):
        if xp >= threshold:
            current = i
        else:
            break
    if current + 1 < len(LEVELS):
        next_threshold = LEVELS[current + 1][0]
        progress = (xp - LEVELS[current][0]) / (next_threshold - LEVELS[current][0])
    else:
        next_threshold = None
        progress = 1.0
    return current, LEVELS[current][1], LEVELS[current][2], LEVELS[current][3], min(1.0, max(0.0, progress)), next_threshold


def compute_xp(reviews, nodes, streak):
    """Total XP from review history + mastery milestones + streak bonus."""
    xp = 0
    for r in reviews:
        rating = r.get("rating")
        if rating and 1 <= rating <= 4:
            xp += XP_PER_REVIEW + XP_RATING_BONUS[rating]
    # Streak bonus: compounding daily reward
    xp += streak * XP_STREAK_BONUS * (1 + streak // 7)  # bonus doubles every 7 days
    # Mastery milestones
    for n in nodes:
        if _number(n.get("mastery")) >= 0.7:
            xp += XP_MASTERY_MILESTONE
    return int(xp)


# ── Achievements ───────────────────────────────────────────────

ACHIEVEMENTS = [
    # (id, name, icon, description, condition_function)
    ("first_step", "第一步", "◈", "完成第一次复习", lambda ctx: ctx["total_reviews"] >= 1),
    ("streak_3",   "篝火初燃", "🔥", "连续 3 天学习", lambda ctx: ctx["streak"] >= 3),
    ("streak_7",   "一周不熄", "✨", "连续 7 天学习", lambda ctx: ctx["streak"] >= 7),
    ("streak_30",  "月之守护", "🌙", "连续 30 天学习", lambda ctx: ctx["streak"] >= 30),
    ("reviews_50", "半百之旅", "⚔", "累计 50 次复习", lambda ctx: ctx["total_reviews"] >= 50),
    ("reviews_200","二百征途", "🗻", "累计 200 次复习", lambda ctx: ctx["total_reviews"] >= 200),
    ("master_1",   "第一块领地", "⬡", "掌握 1 个概念", lambda ctx: ctx["mastered"] >= 1),
    ("master_5",   "领主",     "▲", "掌握 5 个概念", lambda ctx: ctx["mastered"] >= 5),
    ("master_10",  "建筑师",   "★", "掌握 10 个概念", lambda ctx: ctx["mastered"] >= 10),
    ("hard_won",   "逆风前行", "→", "在困难中坚持（10 次 Hard）", lambda ctx: ctx["hard_count"] >= 10),
    ("survivor",   "不屈之心", "♥", "从失败中站起（5 次 Again）", lambda ctx: ctx["again_count"] >= 5),
    ("easy_master","轻松自如", "◇", "10 次 Easy 评分", lambda ctx: ctx["easy_count"] >= 10),
    ("explorer",   "星图开拓", "◎", "学习 10 个不同概念", lambda ctx: ctx["unique_concepts"] >= 10),
    ("comeback",   "浴火重生", "✦", "中断后重新开始", lambda ctx: ctx["comeback"]),
    ("budget_45",  "深度探索", "◈", "完成一次 45 分钟专注", lambda ctx: ctx["focus_45"]),
]


def check_achievements(ctx):
    """Return list of unlocked achievement dicts."""
    unlocked = []
    for aid, name, icon, desc, check in ACHIEVEMENTS:
        if check(ctx):
            unlocked.append({"id": aid, "name": name, "icon": icon, "description": desc})
    return unlocked


def build_achievement_context(reviews, nodes, streak, learnable_nodes, threshold):
    """Gather stats needed for achievement checks."""
    ratings = Counter(r.get("rating") for r in reviews)
    unique = len(set(r.get("note_id") for r in reviews if r.get("note_id")))
    mastered = sum(1 for n in learnable_nodes if _number(n.get("mastery")) >= threshold)
    # Comeback: has a gap > 3 days in review history, then resumed
    review_days = sorted(set(_day(r.get("review_date")) for r in reviews if _day(r.get("review_date"))))
    comeback = False
    if len(review_days) >= 3:
        for i in range(1, len(review_days)):
            gap = (review_days[i] - review_days[i-1]).days
            if gap > 3:
                comeback = True
                break
    return {
        "total_reviews": len(reviews),
        "streak": streak,
        "mastered": mastered,
        "hard_count": ratings.get(2, 0),
        "again_count": ratings.get(1, 0),
        "easy_count": ratings.get(4, 0),
        "unique_concepts": unique,
        "comeback": comeback,
        "focus_45": True,  # always available; the UI tracks actual completion
    }


# ── Quest / Encounter reframing ────────────────────────────────

def reframe_concept(node, threshold):
    """Turn a concept node into a 'territory' with narrative framing."""
    mastery = _number(node.get("mastery"))
    difficulty = int(_number(node.get("difficulty"), 2, 1, 5))
    due_kind = node.get("due_kind", "future")

    # Territory status
    if mastery >= threshold:
        status = "established"
        status_label = "已建成"
        narrative = "这片领地已经稳固。偶尔回来巡逻，让记忆的城墙更加坚实。"
    elif mastery >= 0.3:
        status = "building"
        status_label = "建设中"
        narrative = "地基已打好，但还需要更多努力才能让它屹立不倒。"
    else:
        status = "ruins"
        status_label = "待开拓"
        narrative = "这里还是一片废墟。每一次复习，都是在搬起一块砖。"

    # Encounter difficulty reframing
    encounter_labels = {1: "轻松漫步", 2: "小有挑战", 3: "中等难关", 4: "险峻高峰", 5: "终极试炼"}
    encounter = encounter_labels.get(difficulty, "未知")

    # Due kind reframing
    due_labels = {
        "overdue": "呼唤你回去",
        "due": "今日的召唤",
        "new": "全新的领域",
        "future": "尚需等待",
        "invalid": "时间未定",
    }
    quest_label = due_labels.get(due_kind, "待命")

    return {
        "note_id": node["note_id"],
        "title": node["title"],
        "status": status,
        "status_label": status_label,
        "narrative": narrative,
        "encounter": encounter,
        "difficulty": difficulty,
        "mastery": mastery,
        "quest_label": quest_label,
        "due_kind": due_kind,
        "next_review": node.get("next_review", ""),
        "blockers": node.get("blockers", []),
        "minutes": node.get("minutes", 5),
        "concept_type": node.get("concept_type", ""),
        "learnable": node.get("learnable", True),
        "excerpt": node.get("excerpt", ""),
        "file_path": node.get("file_path", ""),
        "overdue_days": node.get("overdue_days", 0),
    }


# ── Journey narrative ──────────────────────────────────────────

JOURNEY_NARRATIVES = {
    "dawn": [
        "每一次出发，都是对未知的致敬。",
        "你不必知道终点在哪里，只需要迈出下一步。",
        "荒原之上，第一个脚印就是里程碑。",
    ],
    "rising": [
        "知识的轮廓正在浮现，你开始看见它们之间的联系。",
        "坚持的意义不在某一天，而在每一天。",
        "你正在把碎片拼成地图。",
    ],
    "peak": [
        "你站在这里，看见了来时的路。每一步都没有白走。",
        "已掌握的不只是知识，是信心。",
        "大厦的轮廓已经清晰。现在要做的，是让它更坚固。",
    ],
    "challenge": [
        "困难不是路断了，而是路变得更陡了。你还在走。",
        "失败是地图上的一个标记，告诉你'这里需要再来一次'。",
        "最黑的夜里，篝火最亮。",
    ],
}


def pick_narrative(ctx):
    """Choose a contextual narrative based on current state."""
    if ctx["again_count"] > 0 and ctx["streak"] < 3:
        return JOURNEY_NARRATIVES["challenge"]
    elif ctx["mastered"] >= 5:
        return JOURNEY_NARRATIVES["peak"]
    elif ctx["streak"] >= 3:
        return JOURNEY_NARRATIVES["rising"]
    else:
        return JOURNEY_NARRATIVES["dawn"]


# ── Main builder ───────────────────────────────────────────────

def build_quest_data(nodes, edges, reviews, config=None, today=None, demo=False):
    """Build the complete game-like view model."""
    base = build_workspace_data(nodes, edges, reviews, config, today, demo)
    today = today or date.today()
    config = config or {}
    threshold = _number(config.get("mastery_threshold", .7), .7, .01, 1)

    learnable = [n for n in base["nodes"] if n.get("learnable")]
    ctx = build_achievement_context(reviews, base["nodes"], base["streak"], learnable, threshold)
    xp = compute_xp(reviews, base["nodes"], base["streak"])
    level_idx, level_name, level_title, level_desc, level_progress, next_xp = compute_level(xp)
    achievements = check_achievements(ctx)
    territories = [reframe_concept(n, threshold) for n in base["nodes"] if n.get("learnable")]

    # Build "adventure map" — concepts ordered as a journey path
    # Overdue first (urgent calls), then due, then new with no blockers, then future
    adventure_order = {"overdue": 0, "due": 1, "new": 2, "future": 3, "invalid": 4}
    adventure_queue = sorted(
        [t for t in territories if t["due_kind"] in ("overdue", "due") or
         (t["due_kind"] == "new" and not t["blockers"])],
        key=lambda t: (adventure_order.get(t["due_kind"], 9), -t["overdue_days"],
                       t["mastery"], -t["difficulty"])
    )

    # Campfire streak visualization
    campfire_level = min(5, base["streak"] // 1)  # 0-5 intensity
    if base["streak"] >= 30:
        campfire_level = 5
    elif base["streak"] >= 14:
        campfire_level = 4
    elif base["streak"] >= 7:
        campfire_level = 3
    elif base["streak"] >= 3:
        campfire_level = 2
    elif base["streak"] >= 1:
        campfire_level = 1

    # Difficulty distribution for "encounter map"
    encounter_counts = Counter(t["difficulty"] for t in territories)

    # Narrative
    narrative = pick_narrative(ctx)

    # Weekly XP trend (last 7 days)
    xp_by_day = Counter()
    for r in reviews:
        day = _day(r.get("review_date"))
        if day and day <= today and (today - day).days < 7:
            rating = r.get("rating")
            if rating and 1 <= rating <= 4:
                xp_by_day[day] += XP_PER_REVIEW + XP_RATING_BONUS[rating]
    weekly_xp = [[(today - timedelta(days=6-i)).isoformat(),
                  xp_by_day.get(today - timedelta(days=6-i), 0)]
                 for i in range(7)]
    weekly_total = sum(v for _, v in weekly_xp)

    # Failures reframed
    again_reviews = [r for r in reviews if r.get("rating") == 1]
    hard_reviews = [r for r in reviews if r.get("rating") == 2]

    return {
        "demo": demo,
        "today": base["today"],
        "weekday": base["weekday"],
        "generated_at": base["generated_at"],
        "threshold": threshold,

        # Player profile
        "xp": xp,
        "weekly_xp": weekly_total,
        "weekly_xp_trend": weekly_xp,
        "level_index": level_idx,
        "level_name": level_name,
        "level_title": level_title,
        "level_desc": level_desc,
        "level_progress": level_progress,
        "next_level_xp": next_xp,
        "max_level": len(LEVELS) - 1,

        # Campfire
        "streak": base["streak"],
        "campfire_level": campfire_level,
        "today_reviews": base["today_reviews"],

        # Achievements
        "achievements": achievements,
        "achievement_count": len(achievements),
        "achievement_total": len(ACHIEVEMENTS),

        # Territories / adventure
        "territories": territories,
        "adventure_queue": [t["note_id"] for t in adventure_queue],
        "territory_stats": {
            "established": sum(1 for t in territories if t["status"] == "established"),
            "building": sum(1 for t in territories if t["status"] == "building"),
            "ruins": sum(1 for t in territories if t["status"] == "ruins"),
            "total": len(territories),
        },
        "encounter_counts": [[k, v] for k, v in sorted(encounter_counts.items())],

        # Journey narrative
        "narrative": narrative,
        "narrative_context": {
            "has_failures": len(again_reviews) > 0,
            "has_hardships": len(hard_reviews) > 0,
            "failures_survived": len(again_reviews),
            "hardships_endured": len(hard_reviews),
        },

        # Original data for compatibility
        "nodes": base["nodes"],
        "edges": base["edges"],
        "queue": base["queue"],
        "blocked_count": base["blocked_count"],
        "calendar": base["calendar"],
        "forecast": base["forecast"],
        "ratings": base["ratings"],
        "changes": base["changes"],
    }


def _safe_json(value):
    """Same safe embedding as dashboard._safe_json."""
    import json
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for char, escaped in [("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                          ("\u2028", "\\u2028"), ("\u2029", "\\u2029")]:
        text = text.replace(char, escaped)
    return text


QUEST_ASSET_DIR = script_dir.parents[2] / "assets" / "quest"


def render_quest_html(nodes, edges, reviews, profile, config=None, *, demo=False, today=None):
    """Render the Quest Edition HTML."""
    payload = build_quest_data(nodes, edges, reviews, config, today, demo)
    template = (QUEST_ASSET_DIR / "quest.html").read_text(encoding="utf-8")
    css = (QUEST_ASSET_DIR / "quest.css").read_text(encoding="utf-8")
    script = (QUEST_ASSET_DIR / "quest.js").read_text(encoding="utf-8")
    return (template.replace("__STYLES__", css)
            .replace("__SCRIPT__", script)
            .replace("__DATA__", _safe_json(payload)))


def generate_quest_demo(output_path=None, open_browser=True):
    """No config, no database; only a self-contained HTML."""
    from demo_data import make_demo_data
    nodes, edges, reviews = make_demo_data()
    html = render_quest_html(nodes, edges, reviews, {}, {"mastery_threshold": .7}, demo=True)
    target = Path(output_path) if output_path else script_dir.parents[2] / "data" / "quest_demo.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    if open_browser:
        import webbrowser
        webbrowser.open(target.resolve().as_uri())
    return str(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate the Quest Edition workspace")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true", help="Use synthetic data")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if args.demo:
        path = generate_quest_demo(args.output, not args.no_open)
    else:
        import db_manager, profile_manager
        config = db_manager.load_config(args.config) if args.config else db_manager.load_config()
        html = render_quest_html(
            db_manager.get_all_nodes(config),
            db_manager.get_edges(config=config),
            __import__("dashboard").query_review_log(config),
            profile_manager.get_full_profile(config), config)
        target = Path(args.output) if args.output else Path(db_manager.get_db_path(config)).parent / "quest.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        import webbrowser
        if not args.no_open:
            webbrowser.open(target.resolve().as_uri())
        path = str(target)
    print("Quest workspace generated: " + path)
