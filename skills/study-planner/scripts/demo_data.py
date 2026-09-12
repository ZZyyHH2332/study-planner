"""Deterministic synthetic data for the no-configuration offline demo."""

from datetime import date, datetime, timedelta
import random


def make_demo_data(today=None):
    today = today or date.today()
    # title, mastery, difficulty, kind, due offset (None = not scheduled)
    examples = [
        ("主动回忆", .58, 2, "method", -2),
        ("间隔重复", .66, 3, "principle", -1),
        ("费曼学习法", .43, 2, "method", 0),
        ("认知负荷", .32, 3, "concept", 0),
        ("元认知", .19, 4, "concept", 0),
        ("精细加工", .81, 2, "method", 0),
        ("工作记忆", .89, 2, "concept", 2),
        ("长时记忆", .92, 2, "concept", 3),
        ("遗忘曲线", .86, 3, "principle", 1),
        ("组块化", .78, 3, "method", 4),
        ("双编码理论", .74, 3, "principle", 5),
        ("交错练习", .54, 3, "method", 2),
        ("检索练习", .49, 2, "method", 3),
        ("迁移学习", .16, 4, "concept", None),
        ("刻意练习", .10, 3, "method", None),
        ("学习科学索引", .0, 1, "moc", None),
    ]
    excerpts = {
        "主动回忆": "先合上资料，尝试从记忆中提取答案，再核对原文。关键不是熟悉内容，而是能够独立解释。\n\n练习：给自己提出三个问题，不看笔记回答。",
        "间隔重复": "把多次复习分散在不同时间，而不是集中在一次长时间学习中。复习间隔应随回忆表现调整。",
        "费曼学习法": "选择一个概念，用清晰简单的语言解释它；遇到说不清的地方，再返回资料补全。避免只重复术语。",
        "认知负荷": "工作记忆容量有限。分解任务、减少无关信息，并利用已有知识结构，可以降低理解新内容的负担。",
    }
    nodes = []
    for index, (title, mastery, difficulty, kind, due) in enumerate(examples):
        nodes.append({"note_id": "demo-{:02d}".format(index+1), "title": title,
                      "mastery": mastery, "difficulty": difficulty, "concept_type": kind,
                      "next_review": (today+timedelta(days=due)).isoformat() if due is not None else None,
                      "last_reviewed": (today-timedelta(days=4+index%5)).isoformat() if due is not None else None,
                      "learning_state": "mastered" if mastery >= .7 else "reviewed" if due is not None else "pending",
                      "review_count": 3+index%8 if due is not None else 0,
                      "ease_factor": 2.5, "file_path": "", "excerpt": excerpts.get(title, "这是合成示例概念，用于演示知识库与学习计划，不是你的真实笔记。")})
    pairs = [(7,4),(8,1),(9,2),(1,3),(4,5),(1,13),(5,14),(7,10),(10,11)]
    edges = [{"source_id":"demo-{:02d}".format(a), "target_id":"demo-{:02d}".format(b),
              "edge_type":"prerequisite"} for a,b in pairs]
    randomizer = random.Random(41)
    reviews = []
    for ago in range(83, -1, -1):
        day = today-timedelta(days=ago)
        count = randomizer.randint(1, 8) if ago < 6 or randomizer.random() > .28 else 0
        if ago == 0:
            count = 3
        for index in range(count):
            node = nodes[(ago+index)%13]
            target_mastery = node["mastery"]
            progress = 1-ago/110
            after = round(max(.08, target_mastery*progress), 3)
            reviews.append({"id":len(reviews)+1, "note_id":node["note_id"], "title":node["title"],
                            "review_date":datetime.combine(day, datetime.min.time()).replace(hour=9, minute=index).isoformat(),
                            "rating":randomizer.choices([1,2,3,4], weights=[1,2,6,3])[0],
                            "prev_mastery":max(.05, after-.04), "new_mastery":after})
    return nodes, edges, reviews
