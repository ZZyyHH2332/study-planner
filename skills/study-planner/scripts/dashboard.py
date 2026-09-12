#!/usr/bin/env python3
"""Generate a fully offline, read-only learning workspace.

The HTML bundles its CSS, JavaScript and data. No CDN, server, note scanning,
telemetry or database writes are required to view it. Reviews are still recorded
through StudySession in the existing CLI; regenerate to refresh this snapshot.
"""

import json
import math
import sys
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager
import profile_manager

ASSET_DIR = script_dir.parents[2] / "assets" / "dashboard"
EXCLUDED_TYPES = {"moc", "literature", "stub", ""}


def _number(value, default=0.0, minimum=0.0, maximum=1.0):
    try:
        number = float(value)
        if math.isfinite(number):
            return max(minimum, min(maximum, number))
    except (ValueError, TypeError):
        pass
    return default


def _day(value):
    """Convert timestamps to local calendar days; date-only values stay dates."""
    if not value:
        return None
    try:
        text = str(value)
        if len(text) == 10:
            return date.fromisoformat(text)
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone()
        return timestamp.date()
    except (ValueError, TypeError):
        return None


def query_review_log(config=None):
    conn = db_manager.get_connection(config)
    try:
        rows = conn.execute(
            """SELECT rl.*, kn.title, kn.difficulty FROM review_log rl
               LEFT JOIN knowledge_nodes kn ON rl.note_id = kn.note_id
               ORDER BY rl.review_date, rl.id"""
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def query_calendar_data(reviews):
    today = date.today()
    counts = Counter(_day(r.get("review_date")) for r in reviews)
    start = today - timedelta(days=83)
    days = [start + timedelta(days=i) for i in range(84)]
    return [[d.isoformat(), counts[d]] for d in days], start.isoformat(), today.isoformat()


def query_mastery_trends(reviews):
    """Group by stable note ID, not by potentially duplicate titles."""
    grouped = defaultdict(list)
    for review in reviews:
        day = _day(review.get("review_date"))
        if day and review.get("new_mastery") is not None:
            grouped[str(review.get("note_id", ""))].append(
                [day.isoformat(), _number(review["new_mastery"])]
            )
    return [{"name": key, "type": "line", "data": values}
            for key, values in sorted(grouped.items())]


def query_rating_distribution(reviews):
    counts = Counter(r.get("rating") for r in reviews)
    return [{"name": name, "value": counts[rating]}
            for rating, name in enumerate(["Again", "Hard", "Good", "Easy"], 1)]


def query_mastery_distribution(nodes):
    counts = [0, 0, 0]
    for node in nodes:
        mastery = _number(node.get("mastery"))
        counts[0 if mastery < 0.3 else 1 if mastery < 0.7 else 2] += 1
    return list(zip(["Learning", "Familiar", "Mastered"], counts))


def query_graph_data(nodes, edges):
    return {"nodes": [{"id": n["note_id"], "name": n.get("title") or n["note_id"]}
                      for n in nodes],
            "links": [{"source": e["source_id"], "target": e["target_id"]} for e in edges]}


def query_review_forecast(config=None):
    today = date.today()
    counts = Counter(_day(n.get("next_review")) for n in db_manager.get_all_nodes(config)
                     if str(n.get("concept_type") or "").strip() not in EXCLUDED_TYPES)
    return [[(today + timedelta(days=i)).isoformat(), counts[today + timedelta(days=i)]]
            for i in range(30)]


def query_learning_velocity(reviews):
    grouped = defaultdict(list)
    for review in reviews:
        if review.get("new_mastery") is not None:
            grouped[review.get("note_id")].append(review)
    results = []
    for note_id, events in grouped.items():
        if len(events) < 2:
            continue
        first = _number(events[0]["new_mastery"])
        last = _number(events[-1]["new_mastery"])
        results.append({"note_id": note_id, "name": events[-1].get("title") or note_id,
                        "velocity": round((last-first)/(len(events)-1), 4),
                        "reviews": len(events), "start_mastery": first, "end_mastery": last})
    return sorted(results, key=lambda item: item["velocity"], reverse=True)


def build_workspace_data(nodes, edges, reviews, config=None, today=None, demo=False):
    """Build a safe, bounded view model without reading any note contents."""
    today = today or date.today()
    config = config or {}
    threshold = _number(config.get("mastery_threshold", .7), .7, .01, 1)
    clean_nodes = []
    for source in nodes:
        kind = str(source.get("concept_type") or "").strip()
        due = _day(source.get("next_review"))
        difficulty = int(_number(source.get("difficulty"), 2, 1, 5))
        due_kind = ("new" if not source.get("next_review") else
                    "invalid" if due is None else "overdue" if due < today else
                    "due" if due == today else "future")
        clean_nodes.append({
            "note_id": str(source["note_id"]),
            "title": str(source.get("title") or source["note_id"]),
            "concept_type": kind, "difficulty": difficulty,
            "mastery": _number(source.get("mastery")),
            "next_review": str(source.get("next_review") or ""),
            "file_path": str(source.get("file_path") or ""),
            "excerpt": str(source.get("excerpt") or "") if demo else "",
            "learnable": kind not in EXCLUDED_TYPES, "due_kind": due_kind,
            "overdue_days": max(0, (today-due).days) if due else 0,
            "minutes": 3+difficulty if due_kind == "new" else 2+(difficulty+1)//2,
            "blockers": [],
        })
    by_id = {n["note_id"]: n for n in clean_nodes}
    prerequisites = defaultdict(list)
    clean_edges = []
    for edge in edges:
        source, target = str(edge["source_id"]), str(edge["target_id"])
        kind = str(edge.get("edge_type") or "prerequisite")
        clean_edges.append({"source_id": source, "target_id": target, "edge_type": kind})
        if kind == "prerequisite":
            prerequisites[target].append(source)
    for node in clean_nodes:
        # Iterative traversal also handles deep graphs and missing/cyclic parents.
        pending = list(prerequisites[node["note_id"]])
        seen = set()
        blockers = set()
        while pending:
            parent_id = pending.pop()
            if parent_id in seen:
                continue
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent_id == node["note_id"] or parent is None or parent["mastery"] < threshold:
                blockers.add(parent_id)
            pending.extend(prerequisites[parent_id])
        node["blockers"] = sorted(blockers)
    queue = [n for n in clean_nodes if n["learnable"] and
             (n["due_kind"] in {"overdue", "due"} or
              n["due_kind"] == "new" and not n["blockers"])]
    queue.sort(key=lambda n: ({"overdue": 0, "due": 1, "new": 2}[n["due_kind"]],
                             -n["overdue_days"], n["mastery"], -n["difficulty"], n["note_id"]))
    counts = Counter(day for day in (_day(r.get("review_date")) for r in reviews) if day and day <= today)
    streak = 0
    cursor = today if counts[today] else today-timedelta(days=1)
    while counts[cursor]:
        streak += 1
        cursor -= timedelta(days=1)
    calendar = [[(today-timedelta(days=83-i)).isoformat(), counts[today-timedelta(days=83-i)]]
                for i in range(84)]
    forecast_counts = Counter(_day(n["next_review"]) for n in clean_nodes if n["learnable"])
    forecast = [[(today+timedelta(days=i)).isoformat(), forecast_counts[today+timedelta(days=i)]]
                for i in range(7)]
    valid_reviews = [r for r in reviews if _day(r.get("review_date")) and _day(r.get("review_date")) <= today]
    ratings = Counter(r.get("rating") for r in valid_reviews)
    changes = query_learning_velocity(valid_reviews)
    return {
        "demo": demo, "today": today.isoformat(),
        "weekday": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][today.weekday()],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "threshold": threshold, "nodes": clean_nodes, "edges": clean_edges,
        "queue": [n["note_id"] for n in queue],
        "blocked_count": sum(n["learnable"] and n["due_kind"] == "new" and bool(n["blockers"]) for n in clean_nodes),
        "streak": streak, "today_reviews": counts[today], "calendar": calendar,
        "forecast": forecast,
        "ratings": [[name, ratings[index]] for index, name in enumerate(["重来 · 完全忘记", "困难 · 勉强想起", "良好 · 正常回忆", "简单 · 轻松记起"], 1)],
        "changes": [{"title": c["name"], "before": c["start_mastery"], "after": c["end_mastery"]} for c in changes[:8]],
    }


def _safe_json(value):
    # JSON is embedded in an HTML raw-text element, not an HTML-escaped string.
    # Escape the parser boundary as well as JS line separators (defense in depth).
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for char, escaped in [("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                          ("\u2028", "\\u2028"), ("\u2029", "\\u2029")]:
        text = text.replace(char, escaped)
    return text


def render_html(stats, nodes, edges, reviews, profile, config=None, *, demo=False, today=None):
    """Keep the existing renderer interface while replacing the CDN dashboard."""
    payload = build_workspace_data(nodes, edges, reviews, config, today, demo)
    template = (ASSET_DIR / "workspace.html").read_text(encoding="utf-8")
    css = (ASSET_DIR / "workspace.css").read_text(encoding="utf-8")
    script = (ASSET_DIR / "workspace.js").read_text(encoding="utf-8")
    # Insert data last so user text that contains a template token stays literal.
    return template.replace("__STYLES__", css).replace("__SCRIPT__", script).replace("__DATA__", _safe_json(payload))


def generate_dashboard(config=None, output_path=None, open_browser=True):
    config = db_manager.load_config() if config is None else config
    html = render_html(db_manager.get_stats(config), db_manager.get_all_nodes(config),
                       db_manager.get_edges(config=config), query_review_log(config),
                       profile_manager.get_full_profile(config), config)
    target = Path(output_path) if output_path else Path(db_manager.get_db_path(config)).parent / "dashboard.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(target.resolve().as_uri())
    return str(target)


def generate_demo(output_path=None, open_browser=True):
    """No config, no database, no vault; only a self-contained HTML is written."""
    from demo_data import make_demo_data
    nodes, edges, reviews = make_demo_data()
    html = render_html({}, nodes, edges, reviews, {}, {"mastery_threshold": .7}, demo=True)
    target = Path(output_path) if output_path else script_dir.parents[2] / "data" / "demo.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(target.resolve().as_uri())
    return str(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate an offline learning workspace")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true", help="Use synthetic data without reading a vault")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if args.demo:
        path = generate_demo(args.output, not args.no_open)
    else:
        path = generate_dashboard(db_manager.load_config(args.config), args.output, not args.no_open)
    print("Workspace generated: " + path)
