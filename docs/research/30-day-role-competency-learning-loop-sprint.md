# 岗位-能力-学习闭环：30 天研究与工程冲刺包

> 主线：岗位需求 → 能力图谱 → 个体能力差距 → 学习路径 → 学习证据 → 图谱更新  
> 支线：教育智能体、五核学习者状态、GraphRAG、强化学习  
> 目标：把“一次 LLM 生成 JSON”升级为有 schema、有证据、有质量门控、有版本和反馈回路的动态图谱系统。

## 1. 一个月只证明一件事

主研究问题：

> **与一次性 LLM JSON 生成相比，基于 schema、规范化、证据溯源、自动验证和迭代修复的能力图谱管线，能否持续提高图谱质量，并改善岗位能力差距识别和学习路径生成？**

五核承担第二层问题：

> 学习过程产生的独立作答、实践和迁移证据，能否比用户自述更可靠地更新个人能力图，并使后续路径更准确？

不要同时声称解决岗位匹配、课程推荐、图谱自进化、个性化教学和强化学习。一个月内的核心贡献是：**图谱质量闭环**；五核用于完成一个端到端案例。

## 2. 三张图，而不是一个大 JSON

### 2.1 岗位需求图 `G_job`

推荐节点：

- `JobFamily`：岗位族，如 AI 工程、数据分析。
- `Occupation`：具体岗位。
- `Task`：岗位真实任务。
- `Competency`：完成任务所需的综合能力。
- `Skill`：可训练、可观察的技能。
- `Knowledge`：概念和领域知识。
- `Tool`：框架、软件、平台。
- `EvidenceSource`：JD、职业标准、访谈或报告。

推荐边：

- `Occupation REQUIRES Competency`
- `Occupation PERFORMS Task`
- `Task REQUIRES Skill`
- `Competency COMPOSED_OF Skill|Knowledge`
- `Skill PREREQUISITE_OF Skill`
- `Skill USES Tool`
- `Node SUPPORTED_BY EvidenceSource`

### 2.2 学习供给图 `G_learning`

推荐节点：`Concept`、`LearningResource`、`Checkpoint`、`Assessment`、`Artifact`。

关键边：

- `LearningResource TEACHES Skill|Knowledge`
- `Assessment ASSESSES Skill|Knowledge`
- `Checkpoint PREREQUISITE_OF Checkpoint`
- `Artifact DEMONSTRATES Competency|Skill`

### 2.3 学习者证据图 `G_learner`

推荐节点：`Learner`、`LearningAttempt`、`EvidenceEvent`，并引用前两张图中的能力节点。

关键边：

- `Learner ATTEMPTED Assessment`
- `EvidenceEvent SUPPORTS|CONTRADICTS MasteryClaim`
- `Learner MASTERED Skill`
- `LearningAttempt USED_ASSISTANCE Hint|Review|Solution`
- `MasteryClaim VERIFIED_BY TransferTask`

五核与三张图的关系：

| 五核 | 图谱职责 | 不能替代的判断 |
|---|---|---|
| `structure` | 当前岗位目标、能力差距、先修图、学习路径和返回锚点 | 不代替知识掌握或学习动机 |
| `knowledge` | 知识/技能的掌握声明、缺口、错误与反例 | 不把接触、自述或一次答错当成长期结论 |
| `human` | 负荷、节奏、情绪和交互适配等短期约束 | 不从分数推断人格、医学状态或固定风格 |
| `value` | 岗位目标、偏好、优先级、相关性和时间预算 | 不代替学习者确认，也不是能力证据 |
| `practice` | 练习、作品、辅助程度、反馈与迁移证据 | 不把辅助完成或原题重做当成独立迁移 |

这张表描述的是五种决策状态的分工，而不是五套互相覆盖的标签。一个学习证据可以同时关联多个核，但每个关联都需要独立理由，并通过 `EvidenceEvent -> reducer` 进入状态链路。

## 3. “自我迭代”的严格定义

自我迭代不是让 LLM 反复改 JSON，直到它自己说满意。系统每一轮必须有外部触发、质量信号和可回滚更新。

```text
新 JD / 新职业标准 / 新学习证据
              ↓
候选实体与关系抽取
              ↓
定义与规范化：同义词合并、对齐 ESCO/O*NET/内部 schema
              ↓
确定性验证：类型、domain/range、重复、环、孤点、必填证据
              ↓
语义验证：冲突、缺失关系、候选合并、隐含连接
              ↓
candidate / accepted / quarantined / rejected
              ↓
生成 graph diff，版本化应用
              ↓
下游评测：岗位差距与学习路径是否更好
              ↓
失败样例进入下一轮修复队列
```

四种迭代必须分开记录：

1. **数据迭代**：新岗位数据改变技能需求频率、时效和来源覆盖。
2. **schema 迭代**：出现现有类型无法表达的新能力或关系，先作为 proposal，不直接修改生产 schema。
3. **质量迭代**：验证器发现重复、冲突、缺证据和错误方向，形成修复任务。
4. **学习迭代**：个人学习证据更新个人掌握状态；只有跨用户、跨任务的稳定统计才能候选性地校准公共能力图。

最后一点很关键：某个学生学不会，不能直接证明公共图谱里的先修边错误。

## 4. 每个节点和边都必须携带的工程字段

```json
{
  "id": "stable-id",
  "type": "Skill",
  "canonical_name": "retrieval-augmented generation",
  "aliases": ["RAG", "检索增强生成"],
  "description": "...",
  "status": "candidate|accepted|quarantined|rejected|deprecated",
  "confidence": 0.82,
  "source_refs": [
    {"document_id": "jd-17", "span": "...", "retrieved_at": "..."}
  ],
  "valid_from": "...",
  "valid_to": null,
  "version": 3,
  "created_by_run": "run-20260810-01"
}
```

边还要包含 `relation_type`、`source_node_id`、`target_node_id`、`weight`、`evidence_count`。没有来源片段的 LLM 关系只能进入 `candidate`，不能成为可信事实。

## 5. 一个可实现的数学骨架

把图表示为带时间和置信度的类型多重图：

```text
G_t = (V_t, E_t),
e = (u, r, v, confidence, provenance, valid_time, version)
```

岗位 `j` 对技能 `s` 在时间 `t` 的需求权重可先用可解释启发式：

```text
demand(j,s,t) = frequency × recency × source_reliability × edge_confidence
```

学习者 `u` 的技能差距：

```text
gap(u,j,s,t) = demand(j,s,t) × (1 - mastery(u,s,t))
```

路径生成先做约束排序，不必立刻上强化学习：

- 覆盖高 `gap` 技能；
- 满足 `PREREQUISITE_OF`；
- 控制总学习成本；
- 结合 human/value 核调整节奏与优先级；
- 每个节点都必须有可评估任务。

后续再把路径选择写成 contextual bandit 或 POMDP。一个月内，可靠的 gap 与 graph quality 比训练 RL 更重要。

## 6. 三组核心实验

### 实验 A：图谱构建质量

| 组 | 方法 |
|---|---|
| A One-shot | 当前知识库 + LLM 直接输出 JSON |
| B Structured | 固定 schema + 分阶段抽取 + canonicalization |
| C Iterative | B + provenance + 验证器 + graph diff + 迭代修复 |

指标：

- 节点/边 precision、recall、F1；
- schema valid rate；
- duplicate entity/relation rate；
- unsupported edge rate；
- conflict rate；
- provenance coverage；
- 每轮修复后的质量增量与 token/时间成本。

### 实验 B：增量更新稳定性

先用 20-30 份 JD 建图，再加入 10 份新 JD。

指标：

- 新增有效节点/边数量；
- 无关旧节点被改写的比例；
- 重复运行的幂等性；
- 旧查询结果稳定性；
- graph diff 是否可解释、可回滚。

### 实验 C：下游价值

给定同一岗位和同一学习者证据，比较 A/B/C 的：

- Top-K 能力差距是否合理；
- 学习路径是否满足先修关系；
- 路径是否覆盖岗位关键任务；
- 新的学习证据进入后，路径是否做局部调整而非整体漂移。

## 7. 30 天路线

### 第 1 周：schema、数据和 one-shot 基线

| 天 | 任务 | 交付物 |
|---|---|---|
| D1 | 只选一个岗位族；画三张图和节点/边 schema | ontology v0 + 研究问题 v0 |
| D2 | 研究 ESCO、O*NET；确定哪些复用、哪些内部扩展 | schema mapping 表 |
| D3 | 读 EDC；把抽取、定义、规范化拆开 | pipeline v0 |
| D4 | 读 PiVe、SHACL/KGValidator；定义确定性和语义规则 | validation rules v0 |
| D5 | 收集 30-40 份同岗位族 JD，去重并冻结数据快照 | corpus v1 |
| D6 | 人工标注 8-10 份 JD，建立 100-200 条 gold 边 | benchmark v0 |
| D7 | 跑当前 one-shot 方法，统计错误类型 | baseline report + 冻结指标 |

### 第 2 周：构建可控的迭代管线

| 天 | 任务 | 交付物 |
|---|---|---|
| D8 | 候选实体/关系抽取，强制保留 source span | candidate graph |
| D9 | entity/relation canonicalization，对齐内外 schema | canonicalizer v0 |
| D10 | 类型、domain/range、重复、环、孤点验证 | deterministic validator |
| D11 | 语义冲突、缺失、可疑合并检查 | semantic verifier |
| D12 | candidate/accepted/quarantined 状态机 | quality gate |
| D13 | graph diff、版本、运行批次、幂等键与回滚 | versioned updater |
| D14 | 在 10 份 JD 上跑 2-3 轮修复 | pilot result + 失败分类 |

### 第 3 周：连接学习系统，形成闭环

| 天 | 任务 | 交付物 |
|---|---|---|
| D15 | 将现有 checkpoint、讲义、题目对齐到 Skill/Knowledge | learning graph mapping |
| D16 | 将五核证据对齐到 MasteryClaim 与 PracticeEvidence | learner graph mapping |
| D17 | 实现 demand、mastery、gap 的透明评分 | gap engine v0 |
| D18 | 基于 gap + prerequisite 生成路径，先不用 RL | path planner v0 |
| D19 | 独立概念/实践/迁移证据更新个人能力图 | learner update loop |
| D20 | 新证据触发局部路径 reconcile | incremental replan |
| D21 | 完成岗位→能力→路径→证据→局部更新演示 | end-to-end demo v0 |

### 第 4 周：正式实验与研究表达

| 天 | 任务 | 交付物 |
|---|---|---|
| D22 | 冻结模型、prompt、schema、数据和阈值 | experiment protocol |
| D23 | 跑 A/B/C 图谱质量实验 | graph-quality.csv |
| D24 | 加入新 JD，跑增量更新实验 | evolution.csv |
| D25 | 跑下游 gap/path 实验 | downstream.csv |
| D26 | 消融 provenance、canonicalization 或 verifier | ablation.csv |
| D27 | 统计、画图、错误分析 | figures + failure taxonomy |
| D28 | 写方法与工程架构 | report 60% |
| D29 | 写实验、讨论和局限；录演示 | report 100% + demo |
| D30 | 导师审查：主张是否被证据支持 | 最终包 + 下一阶段问题 |

## 8. 图谱学习包：按收益排序

### P0：本月必须掌握

1. 类型图、多重图、属性图；节点/边 schema。
2. ontology、taxonomy、entity/relation canonicalization。
3. entity resolution、同义词合并和外部 ontology alignment。
4. provenance、confidence、uncertainty 和 conflict。
5. constraint validation、质量指标和 gold set。
6. temporal/versioned graph、增量更新、graph diff、幂等性。
7. BFS/DFS、DAG、topological sort、shortest path、Personalized PageRank 的用途。

### P1：主实验完成后学习

1. 图表示学习：TransE/RotatE 的目标函数与 link prediction 指标。
2. GCN/GAT 的 message passing 直觉。
3. temporal knowledge graph embedding。
4. active learning：把低置信候选边送给人审核。
5. contextual bandit：根据 learner context 选择教学动作。

### P2：本月不投入

- 自研 graph foundation model；
- 大规模多智能体自治建图；
- 复杂深度 RL；
- 为了展示效果搭建重型图数据库集群。

先用关系表或 NetworkX 完成实验也可以。研究创新来自更新机制和证据，不来自使用 Neo4j 这个名字。

## 9. 精读清单：先读 10 项

1. [ESCO API 与数据](https://esco.ec.europa.eu/en/use-esco/use-esco-services-api/esco-web-service-api)：职业与技能的规范外部锚点。
2. [O*NET Content Model](https://www.onetcenter.org/content.html)：岗位、任务、技能、知识和工作活动如何分层。
3. [HRGraph](https://aclanthology.org/2024.kallm-1.6/)：岗位和简历图谱及下游推荐基线。
4. [Extract, Define, Canonicalize](https://aclanthology.org/2024.emnlp-main.548/)：把 one-shot 抽取升级为结构化管线。
5. [PiVe](https://aclanthology.org/2024.findings-acl.400/)：迭代验证和细粒度纠错。
6. [KG-SEA](https://dblp.dagstuhl.de/rec/conf/bigdataconf/ChenMNLC25.html)：重复合并、schema 协调、缺失关系发现的自演化思路。
7. [KARMA](https://proceedings.neurips.cc/paper_files/paper/2025/file/517f9b9c227b9dd51dba4560f37165ed-Paper-Conference.pdf)：分工验证、冲突解决和图谱 enrichment。
8. [Uncertainty Management in KG Construction](https://arxiv.org/abs/2405.16929)：置信度不是一个随意的 LLM 分数。
9. [Temporal Knowledge Graph Survey](https://arxiv.org/abs/2403.04782)：时间、演化和历史状态。
10. [W3C SHACL](https://www.w3.org/TR/shacl/) 与 [PROV-O](https://www.w3.org/TR/prov-o/)：约束验证和证据溯源的成熟思想。

## 10. 今天立刻执行的六小时版本

### 第 1 小时：冻结一个垂域

只选一个岗位族，例如 AI 应用工程师、数据分析师或后端工程师。写清：

- 输入数据来自哪里；
- 最终服务哪类学习者；
- 下游只评测哪一个任务；
- 一个月内哪些岗位不处理。

### 第 2-3 小时：写 ontology v0

先写节点、边和字段，不写 prompt。用 3 份真实 JD 手工画图，检查 schema 是否能表达：

- 岗位任务；
- 综合能力；
- 可训练技能；
- 基础知识；
- 工具；
- 学习材料与考核；
- 来源和时间。

### 第 4 小时：跑现有 one-shot 基线

保存原始输入、prompt、模型参数和 JSON 输出。不要修结果，直接记录：

- 重复节点；
- 同义不同名；
- 无来源关系；
- 关系方向错误；
- 粒度混乱；
- 缺失任务或能力；
- 同一输入重复运行的漂移。

### 第 5 小时：人工标注 2 份 JD

建立第一批 gold nodes/edges 和 source spans。数量少没关系，必须可核验。

### 第 6 小时：写一页实验合同

```text
岗位族：
当前 one-shot 方法：
主要错误 Top 5：
新方法：extract → canonicalize → validate → versioned update
三个基线：
核心指标：
第 7 天必须看到的结果：
最大风险：
```

当天没有写业务 UI，也没有更换数据库，就是正确进展。

## 11. 每周向导师怎么汇报

不要说“这周做了自迭代图谱”。改成可验证的话：

```text
我们把一次性 LLM JSON 拆成了候选抽取、规范化、验证和版本化更新。
在 N 份岗位描述和 M 条人工标注边上：
- schema 合法率从 A 提升到 B；
- 重复率从 C 降到 D；
- 有来源支持的边比例从 E 提升到 F；
- 新数据加入时，仅有 G% 的旧图发生非预期变化。
下一周验证这些改进是否提升能力差距和学习路径质量。
```

这才是“工程强化”和“研究创新”开始重合的位置。
