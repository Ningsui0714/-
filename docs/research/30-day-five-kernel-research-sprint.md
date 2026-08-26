# LearnFlow 五核研究：30 天高收益学习与实验包

> 本文现在作为“教育智能体与五核评测”支线。加入岗位-能力图谱后的总路线见
> [岗位-能力-学习闭环 30 天冲刺包](./30-day-role-competency-learning-loop-sprint.md)。

> 时间：2026-08-10 起，连续 30 天  
> 默认投入：每天 4.5-6 小时，每周 6 天；若时间不足，先保住标为 P0 的任务。  
> 目标：不是在一个月内“学完学术和强化学习”，而是形成一项可解释、可复现、可汇报的研究工作。

## 1. 30 天后必须交付什么

1. **一页研究主张**：明确问题、方法、基线、指标和结果，不再只描述“五核很有启发”。
2. **一张相关工作地图**：教育智能体、学习者建模、智能体记忆/规划、图结构记忆四条线，16 篇核心论文。
3. **一个小型评测集**：30-50 条多轮学习轨迹，包含可核验的学习者状态、帮助使用情况和掌握证据。
4. **三组可复现实验**：短对话上下文、单体摘要记忆、五核证据状态，使用相同模型和任务比较。
5. **一份 6-8 页技术报告**：接近 workshop/课程论文结构，而不是产品说明书。
6. **一个 8-12 分钟演示**：同一学习轨迹下，展示三种方法的状态判断与教学动作差异。

## 2. 本月唯一主问题

建议先锁定下面这个问题，不同时追三个创新方向：

> **显式的五核学习者状态，加上证据约束的状态更新，能否比最近对话或单体摘要记忆更忠实地追踪学习状态，并减少教育智能体的错误晋级和不一致教学决策？**

当前五核对应：

| 核 | 结构语义 | 当前可观测证据 | 主要风险 |
|---|---|---|---|
| structure | 学习路径中的位置、依赖、阻塞与返回锚点 | 项目/来源/检查点/导航事件 | 路线与真实学习状态脱节 |
| knowledge | 概念理解、缺口、错误推理与掌握证据 | 独立概念作答、理由、迁移任务 | 把“看过/说懂了”或一次答错误判为长期结论 |
| human | 当前负荷、注意、情绪反应与交互适配 | 明确反馈、求助、挫败表达、跨 session 行为信号 | 仅靠关键词推断，状态噪声大 |
| value | 学习目标、投入优先级、动机与相关性 | 目标陈述、项目选择、明确确认 | 目标会变化，长期状态易过期 |
| practice | 尝试、产物、辅助程度、反馈与迁移表现 | 代码/练习结果、提示使用、变式任务 | 辅助完成被当作独立能力 |

五核在研究中应作为五种决策状态，而不是五个相互替代的标签：结构用于导航，知识用于内容与验证对象，人因用于交互适配，价值用于优先级，实践用于能力验证。一个行为可以产生多个独立观测，但不能因为实践结果变化就顺带推断人因或价值。

### 推荐的贡献表述

- **系统贡献**：五类学习者状态的显式分解，以及事件溯源、可重建的状态运行时。
- **机制贡献**：接触证据、辅助完成、独立掌握之间的证据门控。
- **实验贡献**：面向长期教育对话的状态忠实度与错误晋级评测。

GraphRAG 和强化学习本月作为解释框架与扩展实验，不作为必须完成的主贡献。

### 当前实现最值得研究的五个问题

1. 五类状态目前是合理的工程分解，但还没有证明它优于单体学习者摘要。
2. 确定性规则与 LLM 语义观察同时更新状态，需要通过消融区分各自贡献。
3. kernel confidence 当前偏向取历史最大值，尚不能表达证据冲突、遗忘与置信度衰减。
4. human 核主要依靠关键词和固定过期时间，适合作为局限与后续可学习状态估计的入口。
5. 掌握门控采用固定证据数量和阈值，需要验证它是否真的降低错误晋级，而不是单纯延迟晋级。

本月优先验证第 1 和第 5 项；第 2 项做一个消融；第 3、4 项写入局限和下一阶段计划。

## 3. 优先级与止损线

### P0：必须完成

- 教育智能体评测、学习者建模、记忆机制各精读 3-4 篇。
- 把五核写成统一的状态、观测、更新、动作定义。
- 建立三组基线并完成小规模对照实验。
- 报告错误晋级率、状态忠实度、教学动作质量、成本与延迟。

### P1：完成 P0 后再做

- 把 EvidenceEvent 组织成概念-尝试-证据图，比较图检索与最近事件检索。
- 做一个简单 contextual bandit，演示如何依据五核状态选择提示类型。
- 做 1-2 个消融：移除 human/value 核；取消证据门控。

### P2：本月主动放弃

- 从头训练深度强化学习模型。
- 大规模真实学生实验或完整纵向研究。
- 重写整套多智能体架构、追逐所有新框架。
- 为了“更像论文”加入没有对照实验的新功能。

## 4. 每日时间结构

| 模块 | 时间 | 固定产物 |
|---|---:|---|
| 论文 | 90 分钟 | 1 张论文卡；最多精读 1 篇 |
| 研究/实验 | 150-210 分钟 | 当天可运行结果或数据 |
| 强化学习 | 45 分钟，前 14 天 | 公式推导或 1 个小练习 |
| 综合记录 | 30 分钟 | 今日结论、失败、明日唯一任务 |

阅读超过两小时但没有写出“它如何改变五核假设”，视为无效阅读。

## 5. 30 天逐日路线

### 第 1 周：锁定问题，建立教育与学习科学底座

| 天 | 精读/学习 | 项目动作 | 当日交付 |
|---|---|---|---|
| D1 | 教育智能体综述；区分答题能力与教学能力 | 画出现有五核信息流 | 研究问题 v0 + 五核定义表 |
| D2 | MRBench 的 8 个教学维度 | 将其改写成 LearnFlow 评分 rubric | 评测 rubric v0 |
| D3 | MathTutorBench；重点看开放式教学回复评测 | 选定 3 个基线 | 基线协议 v0 |
| D4 | Tutor CoPilot；关注真实教学干预和实验设计 | 写 10 条不同学习者情境 | 场景集 v0 |
| D5 | 25 年 BKT 综述；理解 latent mastery、slip、guess | 形式化 knowledge 核的观测与状态 | 学习者状态表 v0 |
| D6 | Deep Knowledge Tracing，只理解序列输入/输出与局限 | 标注 5 条多轮轨迹 | 标注规范 v0 |
| D7 | 周综合，不读新论文 | 向导师讲 10 分钟，冻结主问题 | 2 页周报 + 导师反馈 |

强化学习并行：D1-D2 多臂老虎机；D3-D4 MDP 五元组；D5 Bellman 方程；D6 value iteration；D7 用五核写一个教学 MDP。

### 第 2 周：记忆、规划与图结构，完成方法形式化

| 天 | 精读/学习 | 项目动作 | 当日交付 |
|---|---|---|---|
| D8 | 2026 agent memory survey；区分 storage/reflection/experience | 给五核标注 episodic/semantic/procedural 属性 | 记忆分类表 |
| D9 | Generative Agents；看 observation/reflection/planning | 对比当前 EvidenceEvent 管线 | 差异与可借鉴点 |
| D10 | A-MEM 或 Mem0；看记忆生成、链接、更新和检索 | 定义事件图节点与边 | 图模式 v0 |
| D11 | Reflexion；理解语言反馈如何进入下一轮 | 定义“反思可更新什么、不可更新什么” | 安全更新规则 |
| D12 | LLM planning survey；关注 plan validity 和重规划 | 形式化 structure 核及行动选择 | 方法描述 v0 |
| D13 | Microsoft GraphRAG | 选择一个纵向学习查询做图检索试验 | GraphRAG 最小方案 |
| D14 | HippoRAG；比较关联检索与最近/向量检索 | 冻结方法与实验协议 | 4 页研究设计稿 |

强化学习并行：D8 Q-learning；D9 exploration/exploitation；D10 contextual bandit；D11 reward design；D12 offline evaluation；D13 POMDP 概念；D14 只做一次总复习。到此停止系统学习 RL，后续按实验需要查缺补漏。

### 第 3 周：建立评测集和三组基线

| 天 | 核心任务 | 验收标准 |
|---|---|---|
| D15 | 定义轨迹 JSON schema 和 gold label | 能表示目标变化、误解、情绪、提示、独立作答和迁移 |
| D16 | 写 10 条种子轨迹并双轮自检 | 每条 8-15 回合，至少覆盖 2 个核的变化 |
| D17 | 实现 Baseline A：最近 N 轮对话 | 输出五类状态、下一教学动作、是否晋级 |
| D18 | 实现 Baseline B：单体滚动摘要记忆 | 与 A 使用相同模型、提示预算和输出结构 |
| D19 | 接入 Method C：五核 + EvidenceEvent + 证据门控 | 能从同一轨迹重放并给出状态 |
| D20 | 写评测脚本与人工评分表 | 一次运行得到 CSV/JSON 和失败样例 |
| D21 | 跑 10 条 pilot，检查指标是否能拉开差异 | 修正数据和 rubric，不修改结果迎合假设 |

### 第 4 周：正式实验、分析和写作

| 天 | 核心任务 | 当日交付 |
|---|---|---|
| D22 | 根据 pilot 修复协议，冻结模型、prompt、温度和预算 | experiment protocol v1 |
| D23 | 扩展到 30-50 条轨迹并完成 gold labels | benchmark v1 |
| D24 | 正式运行 A/B/C，至少 3 个随机种子或重复调用 | 原始结果 + 运行日志 |
| D25 | 消融：取消证据门控；时间允许再移除 human/value | ablation.csv |
| D26 | 错误分析：各挑 10 个成功/失败案例 | failure taxonomy |
| D27 | 统计与作图：均值、置信区间、错误晋级案例 | 3-4 张结果图 |
| D28 | 写方法、实验、相关工作 | 报告初稿 70% |
| D29 | 写摘要、讨论、局限；录制演示 | 报告完整稿 + demo |
| D30 | 用导师视角审查：贡献是否可证、基线是否公平 | 最终包 + 下一阶段问题 |

## 6. 必读包：16 篇，不再无限扩张

### 教育智能体与评测（P0）

1. [LLM Agents for Education: Advances and Applications](https://aclanthology.org/2025.findings-emnlp.743/)：先建立全景，只读 taxonomy、benchmark 和 challenge。
2. [Unifying AI Tutor Evaluation / MRBench](https://aclanthology.org/2025.naacl-long.57/)：直接借鉴教学能力维度。
3. [MathTutorBench](https://aclanthology.org/2025.emnlp-main.11/)：学习开放式 tutor response 的评测方式。
4. [Tutor CoPilot](https://arxiv.org/abs/2410.03017)：学习真实教学流程中的人机协作和因果评估意识。

### 学习行为与学习者建模（P0）

5. [Twenty-five years of Bayesian Knowledge Tracing](https://link.springer.com/article/10.1007/s11257-023-09389-4)：重点理解隐状态、观测噪声和可解释性。
6. [Deep Knowledge Tracing](https://proceedings.neurips.cc/paper_files/paper/2015/file/bac9162b47c56fc8a4d2a519803d51b3-Paper.pdf)：了解序列模型如何建模答题历史，不必复现深网。
7. [Retrieval-based Learning Review](https://learninglab.psych.purdue.edu/downloads/2025/2025_Karpicke_Retrieval_Based_Learning_Review.pdf)：为“接触不等于掌握、主动提取才是证据”提供学习科学依据。

### 智能体记忆与规划（P0）

8. [From Storage to Experience: A Survey on the Evolution of LLM Agent Memory Mechanisms](https://aclanthology.org/2026.findings-acl.2069/)：用 storage/reflection/experience 整理五核。
9. [Generative Agents](https://dl.acm.org/doi/10.1145/3586183.3606763)：观察、反思、规划的经典组合。
10. [A-MEM: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110)：重点看动态链接与记忆演化。
11. [Reflexion](https://arxiv.org/abs/2303.11366)：理解语言反馈式更新，同时警惕未经证据的自我强化。
12. [Understanding the Planning of LLM Agents](https://arxiv.org/abs/2402.02716)：只读规划分类、评测与失败模式。

### 图结构与强化学习（P1）

13. [From Local to Global: GraphRAG](https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/)：理解实体图、社区摘要和 global query；不要照搬完整管线。
14. [HippoRAG](https://proceedings.neurips.cc/paper_files/paper/2024/file/6ddc001d07ca4f319af96a3024f6dbd1-Paper-Conference.pdf)：关注关联路径如何支持长期记忆检索。
15. [Learning to Optimize Feedback for One Million Students](https://arxiv.org/abs/2508.00270)：看 bandit 如何服务反馈选择，比直接上深度 RL 更贴合一个月项目。
16. [Emotions as Implicit Feedback for Adapting Difficulty](https://link.springer.com/article/10.1007/s10639-024-12699-8)：把 human 核与状态、奖励和难度选择连接起来。

## 7. 强化学习极速包

主教材只用 [Sutton & Barto, Reinforcement Learning: An Introduction](http://incompleteideas.net/book/the-book-2nd.html)，避免同时开多门课。

| 主题 | 学到什么算过关 | 与 LearnFlow 的对应 |
|---|---|---|
| Bandit | 会写 epsilon-greedy，理解 regret | 选择解释/提示/练习类型 |
| MDP | 会定义 S、A、P、R、gamma | 五核状态、Tutor 动作、学习收益 |
| Bellman | 能手算 3-5 个状态 | 长期收益不是当前答对率 |
| Q-learning | 能实现 tabular toy | 模拟学生上的教学策略 |
| Contextual bandit | 理解“看状态后选动作” | 最适合本月的小扩展 |
| POMDP | 理解为什么掌握是隐变量 | 学生知识/情绪不能被直接读取 |
| Offline RL | 知道分布偏移和反事实困难 | 不能从历史日志轻易证明新策略更好 |

本月不要求 policy gradient、actor-critic、PPO 的实现。能看懂其目标和适用条件即可。

## 8. 实验协议

### 三组比较

| 组 | 可见信息 | 目的 |
|---|---|---|
| A Recent Context | 最近 N 轮原始对话 | 最小 LLM tutor 基线 |
| B Monolithic Memory | 最近对话 + 一段滚动学习者摘要 | 常见 agent memory 基线 |
| C Five-Kernel | 五核状态 + 相关证据 + 门控规则 | LearnFlow 方法 |

所有组固定模型、温度、任务、最大上下文预算和输出 schema。不要让 C 获得更多原始信息后宣称结构更好。

### 核心指标

- **State Fidelity**：五类状态字段与 gold label 的 micro/macro F1，或分字段准确率。
- **False Mastery Rate**：没有独立概念与实践证据却被判为掌握的比例，越低越好。
- **Action Quality**：下一教学动作是否符合状态与 MRBench 风格 rubric，由盲评或规则+人工复核完成。
- **Longitudinal Consistency**：相隔多轮后，同一长期事实是否保持；过期短期状态是否被清除。
- **Evidence Grounding**：每个关键状态更新能否指向真实 evidence id。
- **Efficiency**：token、延迟、失败率；防止以无限上下文换准确率。

### 至少覆盖的轨迹类型

1. 学生看过讲义并说“懂了”，但独立题目答错。
2. 学生在提示后做对，换题后失败。
3. 学生短期挫败，数小时或新会话后恢复。
4. 学习目标中途改变，旧目标不能永久支配策略。
5. 新资料加入后路线需要局部调整，而非全部重建。
6. 多轮后出现与旧掌握证据矛盾的新证据。
7. 同一概念在代码实践中成功，但口头解释不完整。
8. 能完成迁移任务，足以替代低层重复测验。

## 9. 三个固定模板

### 论文卡（每篇 15 分钟写完）

```text
论文：
一句话问题：
状态/记忆表示：
核心机制：
数据与基线：
指标与主要结果：
最大局限：
对应五核：
能改变我们的哪个实验或假设：
```

### 每日研究日志

```text
今天唯一问题：
做了什么可复现动作：
得到的证据：
反驳了什么想法：
当前最大风险：
明天唯一任务：
```

### 每周给导师的汇报

```text
本周结论（最多 3 条）：
目前研究问题：
证据/实验结果：
与最近工作的差异：
一个关键失败：
下周要验证的唯一假设：
需要导师判断的问题：
```

## 10. 决策检查点

- **D7**：若说不清基线和指标，暂停读新论文，先修研究问题。
- **D14**：若方法仍只是“五个模块”，必须补状态定义、证据更新规则和可证伪假设。
- **D21**：若 pilot 完全拉不开差异，先检查任务是否真的需要长期状态，不急着改模型。
- **D25**：若核心实验没完成，立即取消 GraphRAG 与 bandit 扩展。
- **D30**：即使结果不支持五核，也保留负结果和失败分析；它们比没有公平基线的正结果更有研究价值。

## 11. 最终汇报结构

1. 教育智能体的痛点：会回答，不等于会持续教学。
2. 现有记忆的问题：非结构化摘要难以区分接触、辅助成功和独立掌握。
3. LearnFlow 方法：五核状态、只追加证据、可重建投影、证据门控。
4. 实验：A/B/C、公平上下文预算、纵向学习轨迹。
5. 结果：状态忠实度、错误晋级、动作质量、效率。
6. 局限：合成轨迹、规则设计、缺少长期真实学生研究。
7. 下一步：证据图检索、真实日志和 contextual bandit 教学策略。
