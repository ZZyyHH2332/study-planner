#!/usr/bin/env python3
"""AI question generation templates for Study Planner.

Instead of a static question bank, questions are generated dynamically from
knowledge node content. Templates vary by concept_type and difficulty
adjusts based on the learner's current mastery level.

Question types by concept_type:
  definition   → recall ("请解释XXX的概念")
  principle    → analysis ("为什么XXX会发生YYY？")
  application  → scenario ("在场景ZZZ中，如何应用XXX？")
  comparison    → compare ("比较XXX和YYY的异同")
  procedure    → steps ("请描述完成XXX的步骤")
  (fallback)   → mixed

Difficulty levels by mastery:
  mastery < 0.3 → basic (直接回忆定义)
  mastery 0.3-0.7 → intermediate (理解+应用)
  mastery > 0.7  → advanced (分析+评价+综合)

Usage:
  from question_prompts import generate_prompt
  prompt = generate_prompt(node, mastery=0.4)
  # → {"question": "...", "concept_type": "definition",
  #    "difficulty": "intermediate", "hint": "..."}

  # TRAE AI uses this prompt to generate the actual question text.
  # The AI can also search the internet for relevant cases/scenarios.
"""

import json
from pathlib import Path

DIFFICULTY_LEVELS = {
    "basic": {
        "mastery_range": (0.0, 0.3),
        "instruction": "生成基础回忆题，要求学习者直接陈述核心定义或关键事实",
        "bloom_level": "记忆/理解",
    },
    "intermediate": {
        "mastery_range": (0.3, 0.7),
        "instruction": "生成中等理解题，要求学习者解释原理或应用到具体场景",
        "bloom_level": "应用/分析",
    },
    "advanced": {
        "mastery_range": (0.7, 1.0),
        "instruction": "生成高级综合题，要求学习者比较、评价或综合多个概念",
        "bloom_level": "综合/评价",
    },
}

CONCEPT_TEMPLATES = {
    "definition": {
        "basic": '请陈述「{title}」的定义，列出其核心组成部分。\n\n参考笔记内容：\n{content}',
        "intermediate": '请解释「{title}」的工作原理，并说明每个组成部分的功能。\n\n参考笔记内容：\n{content}',
        "advanced": '请比较「{title}」与相关概念的异同，并分析其在更大系统中的角色。\n\n参考笔记内容：\n{content}',
    },
    "principle": {
        "basic": '请说明「{title}」的基本原理是什么。\n\n参考笔记内容：\n{content}',
        "intermediate": '请解释为什么「{title}」会这样运作，其背后的机制是什么？\n\n参考笔记内容：\n{content}',
        "advanced": '请分析「{title}」的原理在什么条件下会失效，并解释为什么。\n\n参考笔记内容：\n{content}',
    },
    "application": {
        "basic": '请举一个「{title}」的实际应用例子。\n\n参考笔记内容：\n{content}',
        "intermediate": '在以下场景中如何应用「{title}」？请说明你的推理过程。\n场景：{scenario}\n\n参考笔记内容：\n{content}',
        "advanced": '请设计一个需要综合运用「{title}」的方案，并论证你的设计选择。\n\n参考笔记内容：\n{content}',
    },
    "comparison": {
        "basic": '请分别列出「{title}」和相关概念的要点。\n\n参考笔记内容：\n{content}',
        "intermediate": '请比较「{title}」和类似概念，指出关键差异。\n\n参考笔记内容：\n{content}',
        "advanced": '请从多个维度评价「{title}」与其他方案的优劣，并给出你的推荐及理由。\n\n参考笔记内容：\n{content}',
    },
    "procedure": {
        "basic": '请列出完成「{title}」的步骤。\n\n参考笔记内容：\n{content}',
        "intermediate": '请描述「{title}」的流程，并解释每一步的目的。\n\n参考笔记内容：\n{content}',
        "advanced": '如果在执行「{title}」时某步出现问题，你会如何诊断和修正？\n\n参考笔记内容：\n{content}',
    },
}

FALLBACK_TEMPLATE = {
    "basic": '请回顾「{title}」的核心要点。\n\n参考笔记内容：\n{content}',
    "intermediate": '请解释「{title}」的关键内容，并举例说明。\n\n参考笔记内容：\n{content}',
    "advanced": '请深入分析「{title}」，评价其意义并提出改进建议。\n\n参考笔记内容：\n{content}',
}

SCENARIO_HINTS = [
    "一个需要该知识的实际工作场景",
    "一个常见的误解或错误案例",
    "一个跨学科的应用场景",
    "一个极限或边界条件下的场景",
]


def get_difficulty_level(mastery):
    """Determine difficulty level from mastery score."""
    for level, config in DIFFICULTY_LEVELS.items():
        lo, hi = config["mastery_range"]
        if lo <= mastery < hi:
            return level
    return "advanced"


def get_template(concept_type, difficulty):
    """Get question template for a concept_type and difficulty."""
    templates = CONCEPT_TEMPLATES.get(concept_type, FALLBACK_TEMPLATE)
    return templates.get(difficulty, FALLBACK_TEMPLATE[difficulty])


def read_note_content(node, config=None):
    """Read note content from Obsidian file."""
    file_path = node.get("file_path")
    if not file_path or not Path(file_path).exists():
        return node.get("title", "未知概念")

    try:
        content = Path(file_path).read_text(encoding="utf-8")
        lines = content.split("\n")
        body_start = 0
        in_frontmatter = False
        fm_count = 0
        for i, line in enumerate(lines):
            if line.strip() == "---":
                fm_count += 1
                if fm_count == 2:
                    body_start = i + 1
                    break
        body = "\n".join(lines[body_start:]).strip()
        return body[:500] if len(body) > 500 else body
    except Exception:
        return node.get("title", "未知概念")


def generate_prompt(node, mastery=None, config=None):
    """Generate a question prompt for the AI to use.

    Args:
        node: Knowledge node dict (must have title, concept_type, mastery)
        mastery: Override mastery (uses node['mastery'] if None)
        config: Plugin config

    Returns:
        dict with: prompt, concept_type, difficulty, bloom_level,
                   question_hint, scenario_hint
    """
    title = node.get("title", node.get("note_id", "未知"))
    concept_type = node.get("concept_type", "definition")
    mastery = mastery if mastery is not None else node.get("mastery", 0.1)
    difficulty = get_difficulty_level(mastery)
    content = read_note_content(node, config)

    template = get_template(concept_type, difficulty)

    import random
    scenario = random.choice(SCENARIO_HINTS)
    prompt = template.format(title=title, content=content, scenario=scenario)

    diff_config = DIFFICULTY_LEVELS[difficulty]

    return {
        "prompt": prompt,
        "concept_type": concept_type,
        "difficulty": difficulty,
        "bloom_level": diff_config["bloom_level"],
        "instruction": diff_config["instruction"],
        "note_id": node.get("note_id"),
        "title": title,
        "mastery": round(mastery, 2),
        "scenario_hint": scenario,
        "internet_search_hint": (
            f"搜索互联网获取关于「{title}」的{concept_type}类题目参考、"
            f"实际案例和常见考试题型，融入题目生成"
        ),
    }


def generate_prompt_batch(nodes, config=None):
    """Generate prompts for multiple nodes.

    Returns: list of prompt dicts, ordered by priority (lowest mastery first)
    """
    sorted_nodes = sorted(nodes, key=lambda n: n.get("mastery", 0))
    return [generate_prompt(n, config=config) for n in sorted_nodes]


def format_scoring_prompt(question_prompt, config=None):
    """Generate a scoring criteria prompt for the AI.

    The AI uses this to generate scoring criteria when it creates the question.
    Criteria are stored in session short-term memory, not shown to user
    unless requested.

    Args:
        question_prompt: Output from generate_prompt()

    Returns:
        str: Prompt for AI to generate scoring criteria
    """
    title = question_prompt["title"]
    difficulty = question_prompt["difficulty"]
    bloom = question_prompt["bloom_level"]

    return (
        f"你刚才为「{title}」生成了一道{difficulty}级别({bloom})的题目。\n"
        f"请同时生成评分标准，格式如下：\n\n"
        f"评分标准(不展示给学习者，除非其要求查看标准答案)：\n"
        f"1. 关键得分点(列出3-5个必须提到的要点)\n"
        f"2. 部分得分规则(每个要点权重)\n"
        f"3. 常见错误(学习者在回答此题时常犯的1-2个错误)\n"
        f"4. 标准答案参考(简短)\n\n"
        f"当学习者作答后，请对照评分标准评估：\n"
        f"- 命中几个关键点\n"
        f"- 是否有常见错误\n"
        f"- 输出: correct (True/False) + rating (1-4) + 简短反馈\n"
        f"  rating 1=完全错误, 2=部分正确但有大错, 3=基本正确, 4=完全正确且深入"
    )


if __name__ == "__main__":
    import sys
    script_dir = Path(__file__).resolve().parent
    sp_dir = script_dir.parent.parent / "study-planner" / "scripts"
    sys.path.insert(0, str(sp_dir))
    import db_manager

    config = db_manager.load_config()
    nodes = db_manager.get_all_nodes(config)

    for node in nodes[:3]:
        result = generate_prompt(node, config=config)
        print(f"\n{'='*60}")
        print(f"节点: {result['title']}")
        print(f"类型: {result['concept_type']} | 难度: {result['difficulty']} | Bloom: {result['bloom_level']}")
        print(f"Mastery: {result['mastery']}")
        print(f"\n出题模板:")
        print(result["prompt"][:200] + "...")
        print(f"\n评分提示:")
        scoring = format_scoring_prompt(result)
        print(scoring[:200] + "...")
