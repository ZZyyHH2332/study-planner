#!/usr/bin/env python3
"""Study Planner — interactive CLI launcher.

Double-click this script (or the desktop shortcut) to start reviewing.
Provides a simple menu: review due cards, view stats, scan vault, exit.
"""

import sys
import os
import subprocess
from pathlib import Path

if os.name == "nt":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

script_dir = Path(__file__).resolve().parent / "skills" / "study-planner" / "scripts"
ae_dir = Path(__file__).resolve().parent / "skills" / "adaptive-engine" / "scripts"
sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(ae_dir))

import db_manager
import profile_manager
import bkt_engine
import fsrs_engine
from session_sync import StudySession
import path_generator
import gap_detector
import quiz_selector
import dashboard
import data_io

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"

RATING_LABELS = {
    1: f"{RED}重来{RESET}",
    2: f"{YELLOW}困难{RESET}",
    3: f"{GREEN}良好{RESET}",
    4: f"{CYAN}简单{RESET}",
}

RATING_TO_CORRECT = {1: False, 2: True, 3: True, 4: True}


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    clear_screen()
    print(f"{BOLD}{CYAN}")
    print("╔══════════════════════════════════════════╗")
    print("║     Study Planner  间隔复习助手           ║")
    print("╚══════════════════════════════════════════╝")
    print(f"{RESET}")


def show_stats(config):
    stats = db_manager.get_stats(config)
    due = fsrs_engine.get_due_reviews(config)

    print(f"  {DIM}总笔记数:{RESET} {stats['total_nodes']}    "
          f"{DIM}已掌握:{RESET} {GREEN}{stats['mastered_nodes']}{RESET}    "
          f"{DIM}总复习:{RESET} {stats['total_reviews']} 次")
    print(f"  {DIM}平均掌握度:{RESET} {stats['avg_mastery']*100:.1f}%    "
          f"{DIM}今日待复习:{RESET} {YELLOW}{len(due)}{RESET} 张")
    print()


def show_main_menu(config):
    print_header()
    show_stats(config)
    due_count = len(fsrs_engine.get_due_reviews(config))
    review_label = f"开始复习 ({due_count} 张待复习)" if due_count > 0 else "开始复习 (无待复习)"
    print(f"  [{BOLD}1{RESET}] {review_label}")
    print(f"  [{BOLD}2{RESET}] 查看复习队列")
    print(f"  [{BOLD}3{RESET}] 查看学习统计")
    print(f"  [{BOLD}4{RESET}] 重新扫描 Vault")
    print(f"  [{BOLD}5{RESET}] 生成学习路径")
    print(f"  [{BOLD}6{RESET}] 知识缺口检测")
    print(f"  [{BOLD}7{RESET}] IRT 自测")
    print(f"  [{BOLD}8{RESET}] 查看数据看板")
    print(f"  [{BOLD}q{RESET}] 生成冒险旅程 (Quest Edition)")
    print(f"  [{BOLD}9{RESET}] 数据管理")
    print(f"  [{BOLD}0{RESET}] 退出")
    print()


def start_review(config):
    due = fsrs_engine.get_due_reviews(config)
    if not due:
        print(f"\n  {GREEN}今天没有待复习的卡片！{RESET}")
        input(f"\n  {DIM}按回车返回菜单...{RESET}")
        return

    session = StudySession(config)
    session.start()

    total = len(due)
    for idx, node in enumerate(due, 1):
        result = review_one_card(session, node, idx, total, config)
        if result == "quit":
            break

    summary = session.end(notes=f"Reviewed {len(session.reviews)} cards")
    print_review_summary(summary)

    # Auto metacognition check after review
    if len(session.reviews) > 0:
        try:
            import metacognition
            diag = metacognition.diagnose(config=config)
            if diag["alerts"]:
                print(f"\n  {YELLOW}⚠ 元认知诊断发现 {len(diag['alerts'])} 个问题:{RESET}")
                for a in diag["alerts"][:2]:
                    sev_color = RED if a["severity"] == "high" else YELLOW
                    print(f"    {sev_color}[{a['severity'].upper()}]{RESET} {a['title']}: {a['diagnosis'][:40]}...")
                print(f"  {DIM}详情请看 [8] 数据看板 → 元认知诊断面板{RESET}")
        except Exception:
            pass

    input(f"\n  {DIM}按回车返回菜单...{RESET}")


def review_one_card(session, node, idx, total, config):
    while True:
        print_header()
        title = node.get("title", node["note_id"])
        difficulty = node.get("difficulty", 0)
        mastery = node.get("mastery", 0)
        state = node.get("learning_state", "pending")
        file_path = node.get("file_path", "")

        stars = "★" * difficulty + "☆" * (5 - difficulty) if difficulty else "—"
        state_map = {
            "pending": f"{DIM}待学习{RESET}",
            "in_progress": f"{YELLOW}学习中{RESET}",
            "reviewed": f"{GREEN}已复习{RESET}",
            "mastered": f"{GREEN}已掌握{RESET}",
        }
        state_label = state_map.get(state, state)

        print(f"  {DIM}卡片 {idx}/{total}{RESET}")
        print(f"  {BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        print(f"  {BOLD}{title}{RESET}")
        print(f"  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        print(f"  {DIM}难度:{RESET} {stars}    "
              f"{DIM}掌握度:{RESET} {mastery*100:.1f}%    "
              f"{DIM}状态:{RESET} {state_label}")
        print()

        if file_path and Path(file_path).exists():
            try:
                os.startfile(file_path)
            except Exception:
                try:
                    subprocess.Popen(["notepad", file_path],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                except Exception:
                    pass

        print(f"  请打开笔记复习，然后评分:")
        print(f"    {BOLD}1{RESET} = {RATING_LABELS[1]}   完全忘了")
        print(f"    {BOLD}2{RESET} = {RATING_LABELS[2]}   勉强想起")
        print(f"    {BOLD}3{RESET} = {RATING_LABELS[3]}   正常回忆")
        print(f"    {BOLD}4{RESET} = {RATING_LABELS[4]}   瞬间记起")
        print(f"    {BOLD}q{RESET} = 退出复习")
        print()

        choice = input(f"  {BOLD}评分:{RESET} ").strip().lower()

        if choice == "q":
            return "quit"
        if choice not in ("1", "2", "3", "4"):
            continue

        rating = int(choice)
        correct = RATING_TO_CORRECT[rating]
        domain = "default"
        content_type = node.get("concept_type")

        result = session.review(
            note_id=node["note_id"],
            rating=rating,
            correct=correct,
            domain=domain,
            content_type=content_type,
        )

        new_mastery = result.get("new_mastery", 0)
        next_review = result.get("next_review", "?")
        ease = result.get("ease_factor", 2.5)
        level = bkt_engine.get_mastery_level(new_mastery)

        print()
        print(f"  {GREEN}✓ 复习完成{RESET}")
        print(f"    掌握度: {mastery*100:.1f}% → {new_mastery*100:.1f}% ({level})")
        print(f"    下次复习: {next_review}", end="")
        interval = result.get("new_interval", 0)
        if interval > 0:
            print(f" ({interval} 天后)")
        else:
            print(f" {YELLOW}(今天再复习一次){RESET}")
        print(f"    Ease: {ease:.2f}")
        print()
        return "done"


def print_review_summary(summary):
    print()
    print(f"  {BOLD}═══════════════════════════════════════════{RESET}")
    print(f"  {BOLD}  复习总结{RESET}")
    print(f"  {BOLD}═══════════════════════════════════════════{RESET}")
    print(f"    复习卡片: {summary.get('reviews_count', 0)} 张")
    synced = summary.get('frontmatter_synced', {}).get('synced', 0)
    print(f"    \u540c\u6b65\u7b14\u8bb0: {synced} \u7bc7")
    print(f"    平均掌握度: {summary.get('avg_mastery', 0)*100:.1f}%")
    print()


def show_review_queue(config):
    queue = fsrs_engine.get_review_queue(config=config)
    print_header()
    print(f"  {BOLD}复习队列 (优先级排序){RESET}\n")
    if not queue:
        print(f"  {GREEN}队列为空，没有待复习的卡片。{RESET}")
    else:
        for i, q in enumerate(queue, 1):
            title = q.get("title", q["note_id"])
            mastery = q.get("mastery", 0)
            difficulty = q.get("difficulty", 0)
            stars = "★" * difficulty + "☆" * (5 - difficulty) if difficulty else "—"
            print(f"  {BOLD}{i:2d}.{RESET} {title}")
            print(f"      {DIM}难度:{RESET} {stars}  {DIM}掌握度:{RESET} {mastery*100:.1f}%")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def show_full_stats(config):
    stats = db_manager.get_stats(config)
    total_reviews = profile_manager.get_profile("total_reviews", config)
    weak_areas = profile_manager.get_profile("weak_areas", config)
    patterns = profile_manager.get_profile("study_patterns", config)
    retention = profile_manager.get_profile("retention_profile", config)

    print_header()
    print(f"  {BOLD}学习统计{RESET}\n")
    print(f"  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"  {BOLD}知识图谱{RESET}")
    print(f"    总节点数: {stats['total_nodes']}")
    print(f"    总边数: {stats['total_edges']}")
    print(f"    已掌握: {stats['mastered_nodes']}")
    print(f"    平均掌握度: {stats['avg_mastery']*100:.1f}%")
    print()
    print(f"  {BOLD}复习记录{RESET}")
    print(f"    累计复习次数: {total_reviews or 0}")
    print(f"    累计学习会话: {stats['total_sessions']}")
    print()

    if patterns:
        print(f"  {BOLD}学习习惯{RESET}")
        peak_hours = patterns.get("peak_hours", [])
        preferred_days = patterns.get("preferred_days", [])
        avg_duration = patterns.get("avg_duration", 0)
        print(f"    高峰时段: {', '.join(str(h) for h in peak_hours)}")
        print(f"    偏好日期: {', '.join(preferred_days)}")
        print(f"    平均时长: {avg_duration:.0f} 分钟")
        print()

    if weak_areas:
        print(f"  {BOLD}薄弱领域{RESET}")
        for wa in weak_areas[:5]:
            concept = wa.get("concept", "?")
            rate = wa.get("failure_rate", 0)
            print(f"    {RED}●{RESET} {concept} (失败率 {rate*100:.0f}%)")
        print()

    if retention and isinstance(retention, dict):
        avg_ease = retention.get("avg_ease_factor", 2.5)
        print(f"  {BOLD}FSRS 参数{RESET}")
        print(f"    平均 Ease Factor: {avg_ease}")
        print()

    input(f"  {DIM}按回车返回菜单...{RESET}")


def scan_vault(config):
    import vault_scanner
    print_header()
    print(f"  {BOLD}扫描 Vault...{RESET}\n")
    result = vault_scanner.scan_vault(config)
    print(f"  扫描完成:")
    print(f"    总笔记: {result.get('total_notes_scanned', 0)}")
    print(f"    新建节点: {result.get('nodes_created', 0)}")
    print(f"    更新节点: {result.get('nodes_updated', 0)}")
    print(f"    新建边: {result.get('edges_created', 0)}")
    if result.get("cycles_detected"):
        print(f"    {YELLOW}检测到循环: {result['cycles_detected']}{RESET}")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def show_learning_path(config):
    conn = db_manager.get_connection(config)
    rows = conn.execute(
        """SELECT * FROM knowledge_nodes
           WHERE concept_type NOT IN ('moc', 'literature', 'stub')
           AND concept_type IS NOT NULL
           ORDER BY title"""
    ).fetchall()
    conn.close()

    if not rows:
        print(f"\n  {YELLOW}知识图谱中没有可学习的概念。{RESET}")
        input(f"\n  {DIM}按回车返回菜单...{RESET}")
        return

    print_header()
    print(f"  {BOLD}生成学习路径{RESET}\n")
    print(f"  选择目标概念:\n")
    for i, row in enumerate(rows, 1):
        mastery = row["mastery"] or 0
        level = bkt_engine.get_mastery_level(mastery)
        print(f"  {BOLD}{i:2d}.{RESET} {row['title']} "
              f"{DIM}({level}, {mastery*100:.0f}%){RESET}")
    print(f"  {BOLD} 0{RESET} 返回")
    print()

    choice = input(f"  {BOLD}选择目标:{RESET} ").strip()
    if choice == "0" or not choice:
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(rows):
            return
    except ValueError:
        return

    target = rows[idx]
    print_header()
    print(f"  {BOLD}学习路径 → {target['title']}{RESET}\n")

    path = path_generator.generate_learning_path(target["note_id"], config)

    if not path:
        print(f"  {YELLOW}无法生成路径。{RESET}")
        input(f"\n  {DIM}按回车返回菜单...{RESET}")
        return

    for i, step in enumerate(path, 1):
        action = step["action"]
        if action == "review":
            icon = f"{YELLOW}[复习]{RESET}"
        elif action == "gap":
            icon = f"{RED}[缺口]{RESET}"
        else:
            icon = f"{GREEN}[学习]{RESET}"

        print(f"  {BOLD}{i:2d}.{RESET} {icon} {step['title']}")
        print(f"      {DIM}掌握度:{RESET} {step['mastery']*100:.0f}%  "
              f"{DIM}难度:{RESET} {step['difficulty']}  "
              f"{DIM}原因:{RESET} {step['reason']}")

    summary = path_generator.get_path_summary(path)
    print(f"\n  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"  {BOLD}路径概要{RESET}")
    print(f"    总步骤: {summary['total_steps']}  "
          f"复习: {summary['reviews']}  "
          f"缺口: {summary['gaps']}  "
          f"新学: {summary['new_learning']}")
    print(f"    平均掌握度: {summary['avg_mastery']*100:.1f}%  "
          f"预计努力: {summary['estimated_effort']}")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def show_gap_detection(config):
    print_header()
    print(f"  {BOLD}知识缺口检测{RESET}\n")

    suggestions = gap_detector.generate_suggestions(config)
    report = gap_detector.get_gap_report(config)

    if not suggestions:
        print(f"  {GREEN}没有检测到知识缺口！{RESET}")
        print(f"  所有概念掌握度均在阈值之上。")
    else:
        print(f"  {DIM}可学概念:{RESET} {report['total_learnable']}  "
              f"{DIM}缺口数:{RESET} {YELLOW}{report['total_gaps']}{RESET}  "
              f"{DIM}缺口率:{RESET} {report['gap_ratio']*100:.0f}%")
        print(f"  {DIM}平均掌握度:{RESET} {report['avg_gap_mastery']*100:.1f}%")
        print(f"  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")

        for s in suggestions:
            priority_colors = {
                "critical": RED,
                "important": YELLOW,
                "moderate": DIM,
            }
            color = priority_colors.get(s["priority"], DIM)
            print(f"  {color}[{s['priority'].upper()}]{RESET} "
                  f"{BOLD}{s['rank']}. {s['title']}{RESET}")
            print(f"      {DIM}掌握度:{RESET} {s['mastery']*100:.0f}% "
                  f"({s['mastery_level']})  "
                  f"{DIM}难度:{RESET} {s['difficulty']}  "
                  f"{DIM}阻塞:{RESET} {s['blocked_count']} 个概念")
            if s["blocked_titles"]:
                print(f"      {DIM}阻塞概念:{RESET} "
                      f"{', '.join(s['blocked_titles'])}")
            print(f"      {DIM}建议:{RESET} {s['suggested_action']} — "
                  f"{s['reason']}")
            print()

    input(f"  {DIM}按回车返回菜单...{RESET}")


def start_quiz(config):
    due = fsrs_engine.get_due_reviews(config)
    if not due:
        print(f"\n  {GREEN}没有待复习的卡片可用于自测。{RESET}")
        input(f"\n  {DIM}按回车返回菜单...{RESET}")
        return

    note_ids = [d["note_id"] for d in due]
    quiz = quiz_selector.generate_quiz(note_ids, config)

    if not quiz:
        print(f"\n  {YELLOW}无法生成自测题目。{RESET}")
        input(f"\n  {DIM}按回车返回菜单...{RESET}")
        return

    print_header()
    print(f"  {BOLD}IRT 自测 (Rasch 模型){RESET}\n")
    qsum = quiz_selector.get_quiz_summary(quiz)
    print(f"  {DIM}题目数:{RESET} {qsum['total_items']}  "
          f"{DIM}ZPD 覆盖:{RESET} {qsum['zpd_coverage']*100:.0f}%  "
          f"{DIM}平均 P(correct):{RESET} {qsum['avg_p_correct']:.2f}")
    print(f"  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")

    session = StudySession(config)
    session.start()

    for i, item in enumerate(quiz, 1):
        print(f"  {BOLD}Q{i}:{RESET} [{item['item_type']}] {item['question']}")
        zpd = f"{GREEN}ZPD{RESET}" if item.get("in_zpd") else f"{YELLOW}过难{RESET}"
        print(f"      {DIM}P(correct)={item['p_correct']:.2f} {zpd}  "
              f"{DIM}b={item['b_param']:+.2f}{RESET}")

        if item.get("answer_hint"):
            print(f"      {DIM}提示:{RESET} {item['answer_hint']}")

        file_path = item.get("file_path")
        if not file_path:
            node = db_manager.get_node(item["note_id"], config)
            if node:
                file_path = node.get("file_path")
        if file_path and Path(file_path).exists():
            try:
                os.startfile(file_path)
            except Exception:
                pass

        print(f"\n      {BOLD}1{RESET}=重来  {BOLD}2{RESET}=困难  "
              f"{BOLD}3{RESET}=良好  {BOLD}4{RESET}=简单  "
              f"{BOLD}q{RESET}=退出")
        choice = input(f"      {BOLD}评分:{RESET} ").strip().lower()
        if choice == "q":
            break
        if choice not in ("1", "2", "3", "4"):
            continue

        rating = int(choice)
        correct = RATING_TO_CORRECT[rating]
        session.review(
            note_id=item["note_id"],
            rating=rating,
            correct=correct,
            domain="default",
            content_type=item.get("item_type"),
        )
        print(f"      {GREEN}✓ 已记录{RESET}\n")

    session.end(notes=f"Quiz with {len(session.reviews)} items")
    input(f"\n  {DIM}按回车返回菜单...{RESET}")


def show_dashboard(config):
    print_header()
    print(f"  {BOLD}生成数据看板...{RESET}\n")
    path = dashboard.generate_dashboard(config=config)
    print(f"  {GREEN}✓ 看板已生成并在浏览器打开{RESET}")
    print(f"  {DIM}文件: {path}{RESET}")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def show_quest(config):
    print_header()
    print(f"  {BOLD}生成冒险旅程 (Quest Edition)...{RESET}\n")
    import quest
    html = quest.render_quest_html(
        db_manager.get_all_nodes(config),
        db_manager.get_edges(config=config), dashboard.query_review_log(config),
        profile_manager.get_full_profile(config), config)
    target = Path(db_manager.get_db_path(config)).parent / "quest.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    import webbrowser
    webbrowser.open(target.resolve().as_uri())
    print(f"  {GREEN}✓ 冒险旅程已生成并在浏览器打开{RESET}")
    print(f"  {DIM}文件: {target}{RESET}")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def show_data_management(config):
    print_header()
    print(f"  {BOLD}数据管理{RESET}\n")
    print(f"  [{BOLD}1{RESET}] 导出 JSON 备份")
    print(f"  [{BOLD}2{RESET}] 导出复习记录 CSV")
    print(f"  [{BOLD}3{RESET}] 导入 JSON 备份")
    print(f"  [{BOLD}4{RESET}] 参数自动校准")
    print(f"  [{BOLD}5{RESET}] 元认知诊断")
    print(f"  [{BOLD}0{RESET}] 返回")
    print()
    choice = input(f"  {BOLD}选择:{RESET} ").strip()

    if choice == "1":
        path = data_io.export_to_json(config=config)
        print(f"\n  {GREEN}✓ 备份已导出{RESET}")
        print(f"  {DIM}文件: {path}{RESET}")
    elif choice == "2":
        path = data_io.export_review_csv(config=config)
        if path:
            print(f"\n  {GREEN}✓ CSV 已导出{RESET}")
            print(f"  {DIM}文件: {path}{RESET}")
        else:
            print(f"\n  {YELLOW}暂无复习记录{RESET}")
    elif choice == "3":
        json_path = input(f"  {BOLD}JSON 文件路径:{RESET} ").strip()
        if json_path and Path(json_path).exists():
            result = data_io.import_from_json(json_path, config=config)
            print(f"\n  {GREEN}✓ 导入完成{RESET}")
            for table, count in result["table_counts"].items():
                print(f"    {table}: {count} 条")
        else:
            print(f"\n  {RED}文件不存在{RESET}")
    elif choice == "4":
        import param_calibrator
        print(f"\n  {DIM}校准中...{RESET}")
        result = param_calibrator.calibrate_parameters(config=config)
        if result["status"] == "skipped":
            print(f"  {YELLOW}{result['reason']}{RESET}")
        else:
            print(f"  {GREEN}✓ 校准完成{RESET}")
            print(f"    复习样本: {result['total_reviews']}")
            bkt = result["bkt"]
            if bkt["after"]["p_transit"] is not None:
                print(f"    P(T): {bkt['before']['p_transit']} → {bkt['after']['p_transit']}")
            if bkt["after"]["p_slip"] is not None:
                print(f"    P(S): {bkt['before']['p_slip']} → {bkt['after']['p_slip']}")
            if bkt["after"]["p_guess"] is not None:
                print(f"    P(G): {bkt['before']['p_guess']} → {bkt['after']['p_guess']}")
            fsrs = result["fsrs"]
            print(f"    Ease: {fsrs['before']} → {fsrs['after']['new_ease']}")
    elif choice == "5":
        import metacognition
        print(f"\n  {DIM}分析中...{RESET}")
        result = metacognition.diagnose(config=config)
        print(f"\n  {BOLD}元认知诊断{RESET}")
        print(f"  {result['summary']}")
        print()
        for alert in result["alerts"]:
            severity_color = RED if alert["severity"] == "high" else YELLOW
            print(f"  {severity_color}[{alert['severity'].upper()}]{RESET} "
                  f"{BOLD}{alert['title']}{RESET}")
            print(f"    {DIM}类型:{RESET} {alert['type']}")
            print(f"    {DIM}诊断:{RESET} {alert['diagnosis']}")
            print(f"    {DIM}建议:{RESET} {alert['action']}")
            print()
        for rec in result["recommendations"]:
            print(f"  {CYAN}→ {rec}{RESET}")
    print()
    input(f"  {DIM}按回车返回菜单...{RESET}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Study Planner - local learning assistant")
    parser.add_argument("--demo", action="store_true", help="Generate an offline Focus Edition demo without config or vault access")
    parser.add_argument("--quest", action="store_true", help="Generate the Quest Edition game-like workspace")
    parser.add_argument("--quest-demo", action="store_true", help="Generate a Quest Edition demo with synthetic data")
    parser.add_argument("--dashboard", action="store_true", help="Generate a read-only Focus Edition workspace from your database")
    parser.add_argument("--config", type=Path, help="Configuration file path")
    parser.add_argument("--output", type=Path, help="Dashboard HTML output path")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser")
    args = parser.parse_args()
    if args.quest_demo:
        import quest
        print(quest.generate_quest_demo(args.output, not args.no_open))
        return
    if args.demo:
        print(dashboard.generate_demo(args.output, not args.no_open))
        return
    try:
        config = db_manager.load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"配置错误: {exc}\n先运行 python launch.py --demo，或复制 config.example.json 为 config.json 并填写路径。\n")
    if args.quest:
        import quest
        html = quest.render_quest_html(
            db_manager.get_all_nodes(config),
            db_manager.get_edges(config=config),
            dashboard.query_review_log(config),
            profile_manager.get_full_profile(config), config)
        target = args.output or Path(db_manager.get_db_path(config)).parent / "quest.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        if not args.no_open:
            import webbrowser
            webbrowser.open(target.resolve().as_uri())
        print(f"Quest workspace generated: {target}")
        return
    if args.dashboard:
        print(dashboard.generate_dashboard(config, args.output, not args.no_open))
        return
    db_manager.init_database(config)
    profile_manager.init_profile(config)

    while True:
        show_main_menu(config)
        choice = input(f"  {BOLD}选择:{RESET} ").strip()

        if choice == "1":
            start_review(config)
        elif choice == "2":
            show_review_queue(config)
        elif choice == "3":
            show_full_stats(config)
        elif choice == "4":
            scan_vault(config)
        elif choice == "5":
            show_learning_path(config)
        elif choice == "6":
            show_gap_detection(config)
        elif choice == "7":
            start_quiz(config)
        elif choice == "8":
            show_dashboard(config)
        elif choice == "q" or choice == "Q":
            show_quest(config)
        elif choice == "9":
            show_data_management(config)
        elif choice == "0":
            print(f"\n  {DIM}再见！{RESET}")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}已退出。{RESET}")
