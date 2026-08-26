# LearnFlow 架构权威与维护边界

本文规定 LearnFlow 的架构权威、两个维护域的边界和交叉修改流程。设计语义以 `docs/AGENT_ARCHITECTURE_GUIDE.md` 为准；可执行枚举、归属与写权限以 `backend/app/services/architecture_registry.py` 为准；实现是否符合契约以测试为准。

## 1. 权威层级

1. `architecture_registry.py`：三类主 Agent、五核、能力、工具、产品技能、工作台和重要事件的机器可读清单。
2. `AGENT_ARCHITECTURE_GUIDE.md`：角色边界、证据规则、上下文装配和产品空间的规范说明。
3. `learning_runtime.py` 与 `memory_graph.py`：事件归约、五核投影与记忆图谱的运行实现。
4. 领域模块和页面文档：只能细化，不得重新定义上述权威。

运行中的注册表可以从 `GET /api/architecture/registry` 查看；`GET /api/architecture/validate` 返回是否发生注册漂移。注册表包含内容摘要 `digest`，方便演示环境和验收记录固定版本。

## 2. 三类主 Agent 契约

“三类主 Agent”是三个责任接口，不是三个同时争夺用户身份的聊天人格。

| 主契约 | 包含的实现 | 主要输入 | 结构化输出 | 禁止事项 |
|---|---|---|---|---|
| Tutor 控制 Agent | Global Main Agent、Project Tutor、Checkpoint Tutor | CurrentLearner、页面上下文、有作用域的五核只读投影、近期证据 | 意图、自然回复、Action、handoff 引用 | 直接写库、宣布掌握、绕过确认策略 |
| 学习设计 Agent | Roadmap、Lecture、Concept、Animation | 项目 brief、已处理来源、学习者投影、provenance | 路线提案、讲义、评估规格、视觉产物 | 未确认应用路线、伪造来源、写五核 |
| 实践与验证 Agent | Exercise、Code、Remediation renderer | 评估规格、提交、测试结果、错误证据 | 实践任务、反馈、讲解段落 | 选择纠错策略、覆盖确定性评分、写五核 |

纠错讲解中的文字可以由模板或受约束生成器渲染，但教学策略、阶段跳转和通过条件必须来自 `RemediationStrategy` 与确定性评分。

## 3. 五核与记忆上下文

五核是学习者状态的五个互补维度，不是五个 Agent、五张独立画像表，也不是五种可以互相替代的评分。每个核都应同时说明：它回答的决策问题、状态所指向的对象、可接受的证据和不能越界推断的内容。

短期键空间由注册表维护，`learning_runtime.py` 直接导入该定义，避免两份 allow-list 漂移。当前统一结构如下：

| Kernel | 核心问题 | 状态对象 | 典型状态与证据 | 不应越界承担 |
|---|---|---|---|---|
| `structure` | 学习者现在位于哪里，下一步如何走，离开后怎样回来？ | 学习路径、项目、检查点与依赖 | 当前位置、路径转向、阻塞、返回锚点；项目/检查点/来源和导航事件 | 概念掌握、目标动机、情绪或实践能力 |
| `knowledge` | 学习者对哪个概念理解到什么程度，证据支持什么结论？ | 概念、问题、错误推理与理解状态 | 待解问题、知识缺口、近期错误、可定位误解；评分答案、理由和迁移证据 | 仅凭接触、讲解、自述或一次答错宣布掌握/稳定误解 |
| `human` | 在当前情境下，怎样教、怎样交互更合适？ | 学习者当下的负荷、注意、情绪反应与交互偏好 | 明确反馈、持续负荷信号、讲法有效/无效和跨 session 一致偏好 | 从分数或行为单独推断人格、医学状态或固定学习风格 |
| `value` | 为什么学，当前什么目标和投入更值得优先？ | 学习目标、优先级、动机、兴趣与相关性 | 目标候选、优先级陈述、兴趣信号、相关性理由；用户确认的目标 | 用模型猜测替代用户确认，或把目标当成能力证据 |
| `practice` | 能否在给定约束下独立做出来，并迁移到新情境？ | 尝试、辅助、产物、反馈与迁移表现 | `LearningAttempt`、辅助等级、测试/判题、产物、重做与变式结果 | 把有提示成功、原题重做或生成内容等同独立迁移能力 |

五核在决策链中的分工可以概括为：`structure` 决定“走哪儿”，`knowledge` 决定“学什么/哪里没懂”，`human` 决定“怎么教”，`value` 决定“为什么现在学这个”，`practice` 决定“怎样验证能不能做”。它们可以由同一行为分别产生证据，但每个目标都必须有独立理由；一个核的变化不能自动推导其他核的变化。

长期巩固不是把短期字段复制到长期区，而是按核使用不同门槛：

| Kernel | 长期巩固门槛 |
|---|---|
| `structure` | 稳定路径模式或已确认项目结构 |
| `knowledge` | 被评分证据支持的掌握，或由具体证据支持且可纠正的误解 |
| `human` | 学习者明确确认，或跨 session 的一致证据；情绪和负荷默认短期有效 |
| `value` | 学习者明确确认的长期目标或价值排序 |
| `practice` | 独立完成与变式迁移证据优先，辅助完成只保留为辅助等级与过程证据 |

跨核协作必须保留边界。例如，学习者在实践任务中答错：`practice` 记录失败尝试和辅助等级；只有错误答案或理由足以定位概念问题时，`knowledge` 才记录相应缺口；只有路径确实因此受阻时，`structure` 才记录阻塞；没有明确表达时，不得顺带写入 `human` 或 `value`。

唯一直接写入路径是：

```text
用户/工具/Agent 行为
  -> EvidenceEvent（只追加、带统一 provenance）
  -> five_kernel_reducer（确定性）
  -> KernelMutation + KernelState
  -> MemoryFact -> MemoryModule -> MemoryClaim
```

工具和 Agent 只能读取经过 learner/project/checkpoint scope 的投影。它们不能直接更新 `KernelState`，也不能把模型生成的教学内容当成掌握证据。

### 复习调度与事实权威

`ReviewSchedule` 是由 `LearningAttempt`、`RemediationCase` 和已登记事件重建的运行投影，不是第六个 Kernel，也不是第二套掌握事实。全局 `/review` 工作台可以读取题目、历史 Attempt、纠错案例、Knowledge/Practice 的有作用域投影与调度状态，形成 `QuestionLearningState`；但它只有在完成确定性判题后，才可追加 `review_attempt_evaluated`。

```text
原练习 / 复习提交
  -> LearningAttempt(attempt_role=review)
  -> review_attempt_evaluated
  -> five_kernel_reducer -> Knowledge / Practice
  -> ReviewSchedule 重投影
```

跳过、延期、暂停和恢复是零 kernel target 的运行事件。`review-policy-v1` 使用固定 `1/3/7/14/30/60 天`阶梯；失败、辅助、独立成功和已校验变式只改变可审计调度，不自行宣布掌握。长期稳定至少需要两次相隔 72 小时的独立复习成功，且至少一次来自已校验变式。稳定后再次失败只增加风险与重新调度，不删除历史证据或长期声明。

## 4. 两个维护域

### 维护域 A：主要架构与记忆权威

维护范围：

- 三类主 Agent 的请求/结果边界和身份边界。
- 五核短期键、长期巩固门槛、上下文装配与 handoff。
- EvidenceEvent schema、确定性 reducer、Memory Graph 和可纠正历史。
- learner ownership、幂等、证据等级与通过条件。

### 维护域 B：工具、产品技能、工作台与流程事件

维护范围：

- Action Board handler、来源处理、RAG、生成器、代码执行器和外部工作流 adapter。
- 路线规划、教学产物、实践验证、纠错等产品技能的实现。
- `/agent`、项目、讲义、练习、纠错、全局复习、画像、记忆、demo 等工作台。
- 工具运行状态、页面行为、第三方工作流和比赛演示资产。

### 重合区处理

维护域 B 需要五核信息时，只声明 `reads_kernels` 并消费只读投影；需要改变学习状态时，先在注册表新增或复用 capability 与 event contract，再通过 `record_event` 写证据。维护域 A 的确定性规则决定该事件是否归约、写入哪些核以及能否长期巩固。任何模块都不得创建第二套画像缓存作为权威事实。

仓库来源的目录、章节和文件摘要可以被 `repository_knowledge_domains` 整理为路线规划上下文。它是来源内容约束，不是第六个 kernel，也不是学习者状态：只能帮助学习设计 Agent 选择可覆盖的主题，不能据此推断掌握、跳过验证或直接写入 `KernelState`。

## 5. 标准变更流程

新增工具、产品技能、工作台或重要事件时：

1. 在 `architecture_registry.py` 声明稳定 ID、owner、origin 和允许的五核读取范围。
2. 复用或新增 Action Board capability，明确 side effect、确认策略和 evidence target。
3. 为重要行为注册 EventContract；所有写入经过 `record_event`。
4. 若需要五核变化，在 reducer 中增加确定性规则与测试。
5. 外部工作流输出先校验为 LearnFlow artifact；不得直接写五核或决定纠错状态。
6. 更新架构/融合/比赛文档，提升注册表版本，并运行注册漂移、后端、前端与 demo 验收。

岗位典型工作任务转化功能向个性化学习交付时，必须使用版本化、知识点级的 JSON，保留任务步骤—知识点—技能点关系和回传地址。`personalized_learning_handoff_opened` 只记录跨功能导航；`personalized_learning_result_received` 只记录经身份核对的练习型初测回传。两者均为零 kernel target；不能由“点击进入”或临时自测推断学习者已学习、已练习或已掌握。

任务转化进入生成前，`plan_learning_work_task` 可以创建、确认并局部重规划版本化 `TaskPlan`。`learning_work_task_plan_created`、`learning_work_task_plan_confirmed` 与 `learning_work_task_plan_replanned` 只记录计划产物、明确确认和运营修订，均为零 kernel target；Plan 内容、确认和后续执行状态都不能作为掌握证据。具体接口与阶段边界见 `docs/LEARNING_WORK_TASK_PLAN.md`。

破坏性接口调整必须保留迁移说明。仅增加讲法、模型或供应商 adapter，不应改变 EvidenceEvent 和五核语义。

路线确认后若已物化出可进入的首关，`apply_learning_path` 可以在同一高层事务中立即
触发标准 `checkpoint_entered` 导航事件。这只是结构核的可回放上下文切换，不是自动
开课、自动出题或能力升级；讲义、评估和证据写回仍分别受其自身 Action 与确定性规则约束。

## 6. 桌面工作区的权威边界

`desktop_workspace` 是 Tutor 控制 Agent 所有的产品工作台，不是第四类主 Agent。`workspace_file_service` 可读取和修改用户明确关联的项目目录，但没有五核写权限。

- 普通项目文件以本地磁盘为权威。
- GitHub/网页链接和用户上传文件属于项目参考来源；来源原件与处理缓存保存在应用数据中，不进入项目工作区，也不参与普通文件树。
- 讲义、练习、测试和判题规则以数据库为权威；`.lflecture/.lfexercise` 只是受管引用。
- Agent 修改普通文件必须形成 `WorkspaceOperation` diff，并由用户确认；不能直接写文件。
- `checkpoint` 会话以 `learner_id + project_id + checkpoint_id` 唯一恢复，建立后作用域不可原地切换。
- 同一关讲义和练习显示同一个关卡 Tutor；学习设计与实践验证 Agent 仍是内部能力接口，不成为第四类主 Agent，也不维护另一份聊天历史。
- 关卡上下文只装配本关 brief、分配资源摘要、讲义/练习摘要、项目文件树和本关消息；文件正文必须按需读取，其他关卡资源与聊天不得进入。
- `workspace_linked`、`workspace_change_applied` 属于零 kernel target 的操作事件。
- 普通项目文件只有查看和轻量文本编辑能力，不提供编译、解释器、终端或运行入口。
- `.lflecture/.lfexercise` 是数据库学习对象的逻辑文件入口；讲义修改通过 `base_version` 版本化保存，练习只能修改个人草稿与批注。
- 练习草稿和原有练习“运行”都不写掌握证据；正式提交继续走 `LearningAttempt -> EvidenceEvent`，重复 `client_submission_id` 只产生一次尝试与评估事件。
- 本地代码 Agent 通过独立 `local_agent_broker` 工具接入，它仍由 Tutor 控制 Agent 所有，不构成第四类主 Agent，也不能修改学习对象和五核。Tutor 只提交任务类型、目标、约束和所需能力；Broker 按 capability 与 priority 确定性选择已启用 Profile。
- 本地 Agent 固定经过两次确认：第一次确认只在隔离副本启动；第二次确认才通过 `workspace_file_service` 批量写回。写回前重新校验全部基础 hash，删除和移动必须逐项确认，失败时恢复批量回滚快照。
- `local_agent_started`、`local_agent_completed`、`local_agent_canceled`、`local_agent_result_applied` 是零 kernel target 的操作事件。执行、测试成功或文件写回都不是掌握证据。

桌面令牌、路径规范化、符号链接和恢复规则见 `docs/DESKTOP_WORKSPACE_SECURITY.md`。任何放宽 WebView 文件权限、允许访问 `.learnflow`、或把草稿/运行当作学习证据的改动，均视为架构契约变更。
