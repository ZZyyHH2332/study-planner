---
name: study-planner
description: "自适应学习管理：基于 Zettelkasten 知识库，通过 BKT/FSRS 双引擎拟合个人学习曲线。当用户提到创建学习计划、备考、复习、知识库管理、扫描 Obsidian Vault、查看学习进度、知识缺口分析时触发。"
---

# Study Planner — 自适应学习管理

基于 Zettelkasten 卡片盒法构建个人知识库，通过 BKT 贝叶斯知识追踪和 FSRS 间隔重复算法拟合个人学习曲线，自适应生成学习路径和复习计划。

## 定位与边界

**做**：知识库笔记管理、知识图谱构建、学习进度追踪、间隔重复复习调度、学习路径生成、知识缺口检测
**不做**：在线视频播放、文档编辑器功能、社交/协作功能、考试报名/日程管理

---

## 核心约束（始终遵守）

1. **不修改笔记正文**。系统只更新 frontmatter 中的学习者状态字段（mastery、learning_state、last_reviewed、next_review、review_count、ease_factor），不触碰笔记正文内容。
2. **先扫描再分析**。任何学习状态分析前，先运行 `vault_scanner.py` 确保数据库与 Vault 同步。
3. **会话级批量同步**。学习会话中的状态更新先在 SQLite 中计算，会话结束后批量同步到笔记 frontmatter，避免频繁写文件。
4. **不假设知识结构**。前置依赖关系由用户在笔记 frontmatter 中声明，系统只提取不推断（Phase 3 的 AI 推断功能除外）。
5. **D 盘优先**。所有数据写入 D 盘，数据库路径由 `config.json` 的 `db_path` 指定。
6. **循环检测**。每次扫描后检测知识图谱中的循环依赖，发现循环时报告但不崩溃。

---

## 架构分层

```
第5层  呈现层        ← TRAE Skill 接口 + HTML 看板（Phase 4）
第4层  自适应引擎     ← 拓扑排序路径 + Dijkstra + IRT + 缺口检测（Phase 3）
第3层  学习者模型     ← BKT 掌握概率 + FSRS 复习 + 学习者画像（Phase 2）
第2层  知识图谱层     ← 从 Obsidian 链接提取 DAG（当前 Phase）
第1层  知识库层       ← Zettelkasten · 4 种笔记类型 · Obsidian Vault
```

当前实施 Phase 1：知识库底层 + 知识图谱提取。

---

## 工作流

根据用户意图路由到以下路径。如果意图不明确，先运行路径 A（扫描）再询问。

### 路径 A：扫描 Vault 并构建知识图谱

**触发**：用户说"扫描知识库"、"同步 Vault"、"更新知识图谱"、"看看我的笔记"等。

**执行步骤**：

1. **初始化数据库**
   ```bash
   python scripts/db_manager.py
   ```
   - 读取 `config.json` 中的 `db_path`
   - 创建所有表（如不存在）

2. **扫描 Vault**
   ```bash
   python scripts/vault_scanner.py
   ```
   - 遍历 `00_Inbox`（跳过 Fleeting）、`10_Sources`、`20_Zettelkasten`、`30_MOCs`
   - 解析每个 `.md` 文件的 frontmatter
   - 提取知识节点（Permanent Note → knowledge_nodes）
   - 提取知识边（prerequisites → prerequisite 边，related → related 边，up → belongs_to 边，inspired → inspired 边）
   - 检测循环依赖
   - 输出扫描摘要

3. **报告扫描结果**
   - 节点总数、边总数、stub 节点数
   - 未解析的链接（指向不存在的笔记）
   - 检测到的循环依赖
   - 各 MOC 的子节点数

**示例交互**：
```
用户：扫描我的知识库

AI：我来扫描你的 Obsidian Vault 并构建知识图谱。

[运行 vault_scanner.py]

## 扫描结果

- 笔记总数：12
- 知识节点：8（Permanent）+ 2（MOC）+ 2（Literature）
- 知识边：15 条
  - 前置依赖：5 条
  - 语义关联：3 条
  - MOC 归属：4 条
  - 灵感来源：3 条
- 未解析链接：1 个（[[Neurotransmitter]] 尚未创建）
- 循环依赖：0

知识图谱已同步到数据库。你可以：
1. 查看学习进度
2. 创建学习计划
3. 开始复习
```

### 路径 B：创建笔记

**触发**：用户说"创建一个知识点"、"新建笔记"、"添加一个 Permanent Note"等。

**执行步骤**：

1. **确定笔记类型**
   - Fleeting（灵感速记）→ `00_Inbox/`
   - Literature（文献摘要）→ `10_Sources/`
   - Permanent（原子知识点）→ `20_Zettelkasten/`
   - MOC（结构索引）→ `30_MOCs/`

2. **生成 frontmatter**
   - 使用对应模板（参考 `references/note-templates.md`）
   - ID：时间戳 `YYYYMMDDHHmm`
   - Permanent Note 需要填写：title、prerequisites、difficulty、concept_type
   - MOC 需要填写：title、goal、target_date

3. **写入文件**
   - 文件名 = title（或 ID）
   - 路径 = 对应文件夹

4. **触发扫描**（可选）
   - 创建后询问是否立即扫描同步到数据库

### 路径 C：查看学习状态

**触发**：用户说"我的学习进度"、"知识掌握情况"、"还差什么没学"等。

**执行步骤**：

1. **确认数据库已同步**
   - 如果上次扫描后有新笔记，提示先扫描

2. **查询统计**
   ```bash
   python scripts/db_manager.py stats
   ```

3. **输出学习状态摘要**
   - 总节点数、已掌握数、平均掌握度
   - 各 MOC 域的进度
   - 待复习的知识点（next_review <= today）
   - 知识缺口（mastery < 阈值 的前置依赖）

### 路径 D：创建学习计划

**触发**：用户说"帮我制定学习计划"、"备考计划"、"接下来的学习路径"等。

**执行步骤**（Phase 1 简化版，Phase 3 实现自适应路径）：

1. **确认目标**
   - 问用户要备考什么、目标日期
   - 确认对应的 MOC

2. **查询该 MOC 下的知识节点**
   - 通过 belongs_to 边找到 MOC 的子节点
   - 检查前置依赖是否满足

3. **生成学习顺序**（Phase 1：简单拓扑排序）
   - 对该 MOC 子图做拓扑排序
   - 标注每个节点的当前掌握度
   - 高亮前置依赖未满足的节点

4. **输出学习计划**
   - 按拓扑顺序列出知识点
   - 标注每个知识点的难度、状态、前置依赖
   - 给出建议的学习时间分配

---

## 笔记类型参考

详见 `references/note-templates.md`。四种笔记类型：

| 类型 | 文件夹 | 角色 | 学习元数据 |
|------|--------|------|------------|
| Fleeting | 00_Inbox | 灵感速记，1-2天处理 | 无 |
| Literature | 10_Sources | 文献摘要，记录出处 | type, author, url, inspired |
| Permanent | 20_Zettelkasten | 原子知识点 = 图谱节点 | 全部学习字段 |
| MOC | 30_MOCs | 结构索引 = 学习域 | goal, target_date, aggregate_mastery |

---

## 数据模型参考

详见 `references/data-model.md`。核心表：

- `knowledge_nodes`：知识图谱节点（从 Permanent Notes 提取）
- `knowledge_edges`：知识图谱边（prerequisite / related / belongs_to / inspired）
- `learner_profile`：学习者画像（键值对 JSON）
- `profile_history`：画像历史轨迹（追加写入）
- `review_log`：复习记录
- `study_sessions`：学习会话

---

## 脚本清单

| 脚本 | 用途 | 阶段 |
|------|------|------|
| `scripts/db_manager.py` | SQLite 初始化、连接、CRUD | Phase 1 |
| `scripts/vault_scanner.py` | 扫描 Vault 提取知识图谱 | Phase 1 |
| `scripts/profile_manager.py` | 学习者画像读写 | Phase 2 |
| `scripts/bkt_engine.py` | BKT 掌握概率更新 | Phase 2 |
| `scripts/fsrs_engine.py` | FSRS 间隔重复调度 | Phase 2 |

运行方式：`python scripts/<script_name>.py`
