# Study Planner — 基于学习者行为与特征的个性化学习 AI

## Focus Edition：离线学习工作台

保留原有 Python / SQLite / Obsidian 学习流程，把数据看板升级为可操作的学习工作台。

```bash
# 无需配置、无需安装依赖、不读取笔记库：用合成数据体验
python launch.py --demo

# 不自动打开浏览器，指定单文件 HTML 输出
python launch.py --demo --no-open --output data/demo.html

# 已配置并完成初次扫描后，从自己的数据库生成工作台
python launch.py --dashboard --no-open

# 运行安全回归测试：只使用临时数据库，不扫描真实 Vault
python -m unittest discover -s tests -v
```

- **今日计划**：15 / 25 / 45 分钟预算；逾期复习优先、到期复习其次、新概念最后。新概念存在未掌握、缺失或循环前置依赖时不自动排入。时长为启发式估算。
- **知识库**：搜索、到期/未开始/已掌握筛选、概念详情、前置依赖提示。
- **专注计时**：开始、暂停、继续、重置；后台标签页通过截止时间校正计时。刷新页面会重置，不自动产生学习记录。
- **学习洞察**：84 天活动、7 天复习预报、评分分布、掌握度变化、前置关系。统计以本地日历日为准。
- **真正离线**：HTML 内嵌样式、脚本和数据，不依赖 CDN、外部字体或服务端。适配桌面与手机。
- **安全边界**：工作台为只读快照，不提供浏览器评分写入。请继续在命令行中复习评分，再重新生成；演示数据与真实数据库完全分离。真实快照包含概念标题和本地路径，分享前注意隐私。

本版修复配置文件定位、相对路径解析、已掌握概念不再进入到期队列、Hard 间隔大于 Good、同秒日志排序不稳定，以及会话中新建的未排期日志遮挡上次复习间隔的问题。无效评分在会话开始前即被拒绝。

> 算法说明：当前 `fsrs_engine.py` 是 ease-factor 驱动的简化 SM-2 / FSRS-inspired 调度器，不是完整标准 FSRS 实现。Again 仍采用当天复习的日期粒度，尚未实现精确的 10 分钟重学队列。原有参数校准、元认知诊断和数据管理继续通过命令行使用。

## Quest Edition：学习冒险旅程

把同样的学习数据，用游戏化的视角重新讲述。不是把学习包装成游戏，而是让真实的成长被看见、被记住、被期待。

灵感来自星露谷物语的每日节奏（早晨出发 → 劳作 → 收获）、我的世界的从零建设（空手砍树 → 造工具 → 建庇护所 → 探索矿洞）、以及三角洲行动的关卡推进（任务简报 → 挑战 → 战果 → 成长）。

```bash
# 用合成数据体验 Quest Edition
python launch.py --quest-demo

# 从自己的数据库生成冒险旅程
python launch.py --quest

# 或在交互菜单中按 q
python launch.py
```

### 游戏化要素

| 要素     | 对应学习数据              | 叙事重构                         |
| -------- | ----------------------- | -------------------------------- |
| 经验值 XP | 复习次数 × 评分加成      | 每次复习都在积累经验，困难越大收获越多 |
| 等级     | XP 累积阈值              | 萌芽 → 行者 → 探索者 → 拓荒者 → 建造者 → 守望者 → 贤者 → 传奇 |
| 篝火连击 | 连续学习天数             | 火焰从微弱到冲天，每 7 天加倍奖励   |
| 成就徽章 | 真实里程碑（复习50次/掌握5个/从失败站起） | 15 枚可解锁，每枚都是一段故事     |
| 知识领地 | 概念掌握度               | 废墟（<30%）→ 建设中（30-70%）→ 已建成（≥70%）|
| 遭遇难度 | 概念 difficulty 1-5     | 轻松漫步 → 小有挑战 → 中等难关 → 险峻高峰 → 终极试炼 |
| 远征队列 | 到期复习 + 新概念        | 今日的召唤 / 呼唤你回去 / 全新领域  |
| 足迹地图 | 84 天活动热力图          | 每一步都算数                      |
| 星图洞察 | XP趋势/预报/难度分布/进度 | 知识的星座如何生长                |

### 设计原则

- **没有虚假奖励**：所有 XP、等级、成就都来自真实复习数据，不存在"点击就赢"的机制。
- **困难被正面讲述**：Again 评分 = "从失败中站起"，Hard 评分 = "逆风前行"，不是挫折而是成长信号。
- **叙事适配状态**：当你连续学习时看到"盛夏"，当你中断后回来看到"浴火重生"，当你遇到困难时看到"最黑的夜里篝火最亮"。
- **完全离线**：与 Focus Edition 相同，单文件 HTML，内嵌 CSS/JS/数据，无 CDN。


## 项目宗旨

**让 Obsidian 笔记变成一个懂你的个性化学习 AI。**

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
                            │  dashboard.py (离线 HTML)  │
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
│   │   │   ├── dashboard.py        # 离线 HTML 数据看板
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
git clone https://github.com/ZZyyHH2332/study-planner.git
cd study-planner
# PyYAML 仅在需要完整 YAML 解析时安装；演示工作台不需要它
python -m pip install pyyaml
```

将 `config.example.json` 复制为项目根目录的 `config.json`，编辑 Vault 路径。相对路径以配置文件所在目录为基准，而不是运行命令时的工作目录：

```json
{
    "vault_path": "D:/MyVault",
    "db_path": "data/study_planner.db",
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

- [x] **Phase 4** — 数据看板（离线 HTML 可视化 + 参数校准 + 元认知 + 数据导入导出）

***

## 关联项目：TRAE Memory System

本项目使用 [trae-memory-system](https://github.com/ZZyyHH2332/trae-memory-system) 作为开发记忆基础设施。

### 协作关系

| 维度   | Study Planner                         | TRAE Memory System              |
| ---- | ------------------------------------- | ------------------------------- |
| 角色   | 学习者自适应系统（终端用户产品）                      | 开发者记忆系统（AI 助手基础设施）              |
| 数据   | 学习者的掌握度、复习记录、知识图谱                     | 开发决策、项目状态、经验教训                  |
| 存储   | SQLite + Obsidian frontmatter         | Markdown 文件（D 盘 + junction）     |
| 用户   | 终端学习者                                 | AI 助手（TRAE）                     |
| 依赖方向 | Study Planner 的开发过程被 memory system 记录 | Memory system 不依赖 study-planner |

### 数据隔离

- **Study Planner 的数据**（knowledge\_nodes, review\_log, learner\_profile）存储在 SQLite，路径由 config.json 的 db\_path 指定

- **Memory System 的数据**（project\_memory.md, status.md, decisions.md）存储在 `~/.trae-cn/memory/`（junction 到 D 盘）

- 两套数据完全独立，不交叉读写，不共享表

### 开发协作流程

```
开发 Study Planner
  → AI 助手读取 memory system 的 status.md 获取上下文
  → AI 助手读取 project_memory.md 获取项目规范
  → 开发过程中做关键决策 → 写入 decisions.md
  → 会话结束 → 更新 status.md
  → AI 助手运行 compile_memory.py → 生成 BRAIN.md

Study Planner 运行时
  → 不触碰 memory system
  → 只读写 SQLite + Obsidian frontmatter
  → 面向终端用户的学习行为
```

### 注意事项

1. **不要混淆两套记忆** — Study Planner 的"学习者画像"（profile\_manager）是给学习者的，Memory System 的"user\_profile.md"是给 AI 助手的
2. **Memory System 的 junction 迁移** — 如果 D 盘路径变更，需更新 junction（见 trae-memory-system 仓库的 README）
3. **session 日志丢失** — 2026-09-01 迁移过程中丢失了部分会话日志，已从代码和对话重建 project\_memory.md 和 decisions.md，详见 trae-memory-system 的 lessons.md
4. **Memory System 不随 Study Planner 发布** — Memory System 是开发工具，不是终端用户的依赖。Study Planner 的用户不需要安装 memory system

***

## License

MIT
