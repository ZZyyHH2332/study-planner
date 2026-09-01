# Study Planner — 自适应间隔复习系统

## 项目宗旨

**让 Obsidian 笔记变成一个懂你的自适应学习系统。**

传统 Zettelkasten 方法擅长知识收集和链接，但缺少两个关键能力：

1. **遗忘追踪** — 不知道哪些笔记快要忘了
2. **学习路径** — 不知道应该先学什么、再学什么

Study Planner 解决这两个问题：

- 用 **BKT（贝叶斯知识追踪）** 追踪每个概念的掌握概率

- 用 **FSRS（自由间隔重复调度）** 安排最优复习时间

- 用 **DAG 拓扑排序 + Dijkstra** 生成尊重前置依赖的学习路径

- 用 **IRT（项目反应理论）** 选择难度匹配的自测题目

### 核心差异

| 维度    | Anki / SuperMemo | Study Planner           |
| ----- | ---------------- | ----------------------- |
| 知识结构  | 孤立卡片             | 知识图谱 DAG                |
| 学习顺序  | 随机 / 手动          | 拓扑排序 + 最优路径             |
| 掌握度模型 | 简单分级             | BKT 概率追踪                |
| 复习调度  | SM-2 / FSRS      | FSRS                    |
| 题目选择  | 固定               | IRT 自适应                 |
| 数据存储  | 专有格式             | Obsidian 笔记 frontmatter |

### 设计哲学

- **笔记是真相源** — SQLite 数据库是缓存，frontmatter 是主数据

- **零摩擦** — 桌面快捷方式双击即用，无需记命令

- **数据主权** — 所有数据存储在本地，无云端依赖

- **可扩展** — 模块化架构，每个引擎独立可替换

***

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    Obsidian Vault                     │
│  (Markdown + Frontmatter: mastery, next_review ...)  │
└──────────────┬──────────────────────────┬────────────┘
               │ scan                     │ sync
               ▼                          ▼
┌──────────────────────┐    ┌──────────────────────────┐
│   Phase 1: 知识库    │    │   Phase 2: 学习者模型     │
│                      │    │                          │
│  vault_scanner.py    │───▶│  bkt_engine.py  (BKT)    │
│  db_manager.py       │    │  fsrs_engine.py (FSRS)   │
│  knowledge_nodes      │    │  profile_manager.py      │
│  knowledge_edges     │    │  session_sync.py         │
└──────────────────────┘    └─────────────┬────────────┘
                                          │
                            ┌─────────────▼────────────┐
                            │  Phase 3: 自适应引擎     │
                            │                          │
                            │  path_generator.py       │
                            │  (拓扑排序 + Dijkstra)    │
                            │                          │
                            │  gap_detector.py         │
                            │  (缺口检测 + 影响排序)    │
                            │                          │
                            │  quiz_selector.py        │
                            │  (IRT Rasch 模型)         │
                            └─────────────┬────────────┘
                                          │
                            ┌─────────────▼────────────┐
                            │  Phase 4: 看板+校准     │
                            │                          │
                            │  dashboard.py (ECharts)  │
                            │  param_calibrator.py     │
                            │  metacognition.py        │
                            │  data_io.py              │
                            └──────────────────────────┘
```

***

## 核心算法

### BKT — 贝叶斯知识追踪

四个参数追踪知识掌握概率：

| 参数    | 含义            | 默认值  |
| ----- | ------------- | ---- |
| P(L0) | 初始掌握概率        | 0.1  |
| P(T)  | 每次学习后过渡到掌握的概率 | 0.3  |
| P(S)  | 已掌握但答错的概率（失误） | 0.1  |
| P(G)  | 未掌握但答对的概率（猜测） | 0.25 |

每次复习后通过贝叶斯更新：`P(L|response) → P(L_new) = P(L|response) + (1-P(L|response)) × P(T)`

### FSRS — 间隔重复调度

四级评分体系：

| 评分        | 含义   | 间隔效果               |
| --------- | ---- | ------------------ |
| 1 = Again | 完全忘了 | 重置为 0，ease -0.2    |
| 2 = Hard  | 勉强想起 | 间隔 ×1.2，ease -0.15 |
| 3 = Good  | 正常回忆 | 间隔 ×ease           |
| 4 = Easy  | 瞬间记起 | 间隔 ×ease×1.3       |

### 学习路径生成

四阶段流水线：

1. **拓扑排序**（Kahn + 优先队列）— 确保前置依赖顺序，多个可选节点时选 cost 最低的
2. **缺口标记** — mastery < 0.7 的节点标记为 gap
3. **Dijkstra 优化** — cost = (1-mastery) × difficulty，最小总 cost 路径
4. **复习插入** — 到期复习项插入路径开头作为热身

### IRT — 题目选择

Rasch 模型（1PL）：

```
P(correct | θ, b) = exp(θ - b) / (1 + exp(θ - b))
```

- θ = 学习者能力（从 BKT mastery 经 logit 变换得到）

- b = 题目难度（从笔记 difficulty 1-5 映射到 -2 \~ +2）

- ZPD 区间：P(correct) ∈ \[0.6, 0.8] — 既不太容易也不太难

***

## 项目结构

```
study-planner/
├── launch.py                      # 交互式 CLI 入口
├── study-planner.bat               # Windows 启动脚本
├── logo.ico                        # 桌面快捷方式图标
├── config.json                     # 配置文件
├── .trae-plugin/
│   └── plugin.json                 # TRAE 插件清单
├── assets/
│   └── icon.svg                    # 插件图标
├── skills/
│   ├── study-planner/              # Phase 1 + 2
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── db_manager.py       # SQLite 数据层
│   │   │   ├── vault_scanner.py    # Vault → DAG 扫描器
│   │   │   ├── bkt_engine.py        # 贝叶斯知识追踪
│   │   │   ├── fsrs_engine.py       # 间隔重复调度
│   │   │   ├── profile_manager.py   # 学习者画像
│   │   │   ├── session_sync.py      # 会话级同步
│   │   │   ├── dashboard.py        # ECharts 数据看板
│   │   │   ├── param_calibrator.py  # BKT/FSRS 参数校准
│   │   │   └── data_io.py           # 数据导出/导入
│   │   └── references/
│   │       ├── data-model.md        # 数据库 schema
│   │       ├── note-templates.md     # frontmatter 模板
│   │       └── bkt-fsrs-spec.md     # BKT/FSRS 规格
│   └── adaptive-engine/            # Phase 3 + 4
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── path_generator.py    # 学习路径生成
│       │   ├── gap_detector.py      # 知识缺口检测
│       │   ├── quiz_selector.py     # IRT 题目选择
│       │   └── metacognition.py     # 元认知/慢思考层
│       └── references/
│           └── path-algorithms.md   # 算法规格
└── verify_*.py                     # 各阶段验证脚本
```

***

## 快速开始

### 前置条件

- Python 3.8+

- Obsidian Vault（已有 Zettelkasten 笔记）

- PyYAML（可选，推荐安装以获得更好的 frontmatter 解析）

### 安装

```bash
git clone https://github.com/yourname/study-planner.git
cd study-planner
pip install pyyaml
```

编辑 `config.json` 指向你的 Vault 路径：

```json
{
    "vault_path": "D:/MyVault",
    "db_path": "D:/Trae CN/study-planner/data/study_planner.db",
    "mastery_threshold": 0.7
}
```

### 使用

**方式一：桌面快捷方式（推荐）**

双击桌面 "Study Planner" 快捷方式，选择菜单：

```
╔══════════════════════════════════════════╗
║     Study Planner  间隔复习助手           ║
╚══════════════════════════════════════════╝

  [1] 开始复习 (2 张待复习)
  [2] 查看复习队列
  [3] 查看学习统计
  [4] 重新扫描 Vault
  [5] 生成学习路径
  [6] 知识缺口检测
  [7] IRT 自测
  [8] 查看数据看板
  [9] 数据管理
  [0] 退出
```

**方式二：命令行**

```bash
python launch.py
```

### 首次使用流程

1. 选择 `[4] 重新扫描 Vault` — 扫描笔记，构建知识图谱
2. 选择 `[5] 生成学习路径` — 选择目标概念，获取学习路径
3. 选择 `[1] 开始复习` — 复习到期卡片，评分后自动更新掌握度和调度
4. 选择 `[6] 知识缺口检测` — 查看哪些概念需要优先补强

### Frontmatter 字段

Permanent 笔记的 frontmatter 会自动同步以下字段：

```yaml
---
id: "202608311410"
title: "Synapse"
tags: [permanent, neuroscience]
difficulty: 2
concept_type: "definition"
mastery: 0.53              # BKT 掌握概率
learning_state: "reviewed"  # pending → in_progress → reviewed → mastered
last_reviewed: "2026-09-01"
next_review: "2026-09-03"
review_count: 2
ease_factor: 2.50
---
```

***

## 数据流

```
扫描 Vault                    复习评分
     │                          │
     ▼                          ▼
vault_scanner             session_sync.review()
     │                          │
     ▼                    ┌─────┴──────┐
knowledge_nodes          ▼            ▼
knowledge_edges     bkt_engine    fsrs_engine
                         │            │
                         ▼            ▼
                    mastery 更新   间隔调度
                         │            │
                         └─────┬──────┘
                               ▼
                        upsert_node()
                               │
                        ┌──────┴──────┐
                        ▼             ▼
                   SQLite DB     frontmatter 同步
                               (targeted line replace)
```

***

## 路线图

- [x] **Phase 1** — 知识库（Vault 扫描 + DAG + SQLite）

- [x] **Phase 2** — 学习者模型（BKT + FSRS + 画像 + 会话同步）

- [x] **Phase 3** — 自适应引擎（路径生成 + 缺口检测 + IRT 自测）

- [x] **Phase 4** — 数据看板（ECharts 可视化 + 参数校准 + 元认知 + 数据导入导出）

***

## License

MIT
