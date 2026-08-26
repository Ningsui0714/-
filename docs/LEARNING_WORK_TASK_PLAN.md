# 学习型工作任务 Agent Plan 接入

本模块在远端基础 TaskPlan 之上增加了可审计的深度规划分析层。它真实生成分层任务树、依赖调度、三类候选 Plan、六维 Critic 评审、决策门禁、风险清单和版本化局部重规划；但仍不把规划产物描述为已经执行，也不保存隐藏思维链。

![证据先行的学习型任务 Agent Plan 深层微流程架构](competition/assets/learning-task-plan-deep-microflow-v7.png)

## 六阶段独立讲解版

总览图用于说明完整闭环；以下六张独立图用于逐阶段汇报，每张都展开该阶段内部的微步骤、分支、汇合门禁和版本化产物。

### 01 任务契约编译

![任务契约编译](competition/assets/learning-task-plan-stage-01-contract-v8.png)

### 02 环境落地与澄清

![环境落地与澄清](competition/assets/learning-task-plan-stage-02-grounding-v8.png)

### 03 证据检索规划

![证据检索规划](competition/assets/learning-task-plan-stage-03-evidence-search-v8.png)

### 04 证据驱动的学习任务规划

![证据驱动的学习任务规划](competition/assets/learning-task-plan-stage-04-planning-v8.png)

### 05 六维 Critic 与定稿

![六维 Critic 与定稿](competition/assets/learning-task-plan-stage-05-critic-v8.png)

### 06 执行观察与交接

![执行观察与交接](competition/assets/learning-task-plan-stage-06-handoff-v8.png)

## 运行链

```text
主 Agent 对话
  -> POST /api/learning-task-conversion/plans
  -> 远端 POST /api/v1/learning-work-task-agent/runs
  -> 01 任务契约：Schema / 稳定 ID / semantic_fingerprint
  -> 02 环境落地与澄清：事实 / 偏好 / 目标 / 成功与停止条件
  -> 03 证据检索规划：证据问题 / 来源路由 / 查询顺序 / 停止条件
  -> 中央工作区 /learning-task-plans/:runId
  -> 用户确认的是 evidence_search_plan，不是最终学习任务 Plan
  -> POST /api/learning-task-conversion/plans/:runId/confirm
  -> 远端 POST /api/v1/learning-work-task-agent/runs/:runId/plan
  -> PLAN_READY
  -> 执行检索并形成可验证 evidence_ledger
  -> 04 证据驱动的学习任务规划：四层任务树 / DAG / 三类候选
  -> 05 学习任务 Critic 与定稿：六维评审 / 决策 / 确认或局部修订
  -> 06 执行观察与交接：待执行清单 / Observation / 交付契约
  -> 用户检查层级、关键路径、候选、风险和版本账本
  -> 观察到局部失败时 POST /plans/:runId/replan
  -> 冻结未受影响工作包，只重算目标工作包及其后继子图
```

远端返回的 `learning-work-task-plan-v1` 是显式计划产物，不包含或接收隐藏思维链字段。LearnFlow 会再次校验：

- Run ID 与任务语义指纹一致；
- 工作包 ID 唯一，依赖存在且无环；
- 角色、工具和产物类型属于版本化白名单；
- Plan 版本确认时严格递增；
- 当前学习者只能恢复和确认自己会话中创建的 Run。

规划分析层额外输出 `learning-work-task-planning-analysis-v3`：

- 严格有序的六阶段状态，每个阶段带输入、输出、树状子步骤和阻塞状态；
- 每个大阶段都继续展开“输入读取 → 子问题分解 → 并行分支 → 汇合校验 → 决策门禁 → 版本化产物”，不是用若干评审维度代替真实过程；
- 证据未到位时仍输出约 146 个诚实标记为 `blocked / not_started` 的微步骤，证据与真实 `task_steps` 到位后扩展到约 195 个微步骤；
- 每个阶段输出微步骤数、主分支数、叶节点数和跨分支依赖数，便于前端检查规划深度；
- 证据前只输出 `evidence_search_plan.json`，不生成或伪造学习任务步骤；
- 证据账本与真实 `task_steps` 到位后，才输出四层学习任务层级：Goal → 作业阶段 → 任务步骤 → 原子操作；
- 拓扑波次、关键路径与依赖边；
- `fidelity_first`、`evidence_first`、`balanced_parallel` 三个候选；
- 任务同一性、依赖、证据、安全、交付、教学适配六维 Critic；
- 显式权重评分、硬门禁、选定候选和触发规则；
- 风险与缓解控制、修订预算、不可变版本账本；
- 局部失败时计算后继闭包，冻结无关工作包并生成新分析版本。
- 覆盖全部工作包的 `execution_checklist`，初始状态统一为 `pending / not_observed`；
- HTML、PDF、版本化 JSON、知识点级学习入口和 `feedback_contract` 五类交接契约，未生成前统一标为 `planned`。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/learning-task-conversion/plans` | 在当前 Tutor session 中创建真实远端 Run 和初始 Plan |
| `GET` | `/api/learning-task-conversion/plans/{run_id}` | 按 learner ownership 恢复远端状态；远端临时不可用时只读回退到已校验快照 |
| `POST` | `/api/learning-task-conversion/plans/{run_id}/confirm` | 幂等确认证据检索计划，并由远端校验后推进到 `PLAN_READY`；不代表最终学习任务 Plan 已确认 |
| `POST` | `/api/learning-task-conversion/plans/{run_id}/replan` | 基于失败工作包和观察结果生成局部子图修订版本，不伪装为已执行 |

创建、确认和局部重规划分别记录 `learning_work_task_plan_created`、`learning_work_task_plan_confirmed` 和 `learning_work_task_plan_replanned`。三者均为零 kernel target 的计划产物/操作事件，不代表学习、练习或掌握。

## 当前边界

- 已实现：六阶段显式状态、任务契约锁定、澄清规格、证据检索计划、证据账本门禁、证据后四层学习任务分解、依赖调度、三候选搜索、六维 Critic、决策门禁、风险清单、学习任务步骤级局部重规划、版本确认、待执行清单、下游交接契约、远端恢复、learner 隔离和审计事件。
- 尚未宣称实现：真实工具执行、证据内容抓取、Worker 产物生成、环境 Observation 自动采集和最终交付发布。页面中的所有状态明确标记为 `not_executed`。
- 旧的完整任务生成接口仍保留在后端用于兼容；主对话的任务工具现在先进入 Plan 页面，不再把一次最终文本调用伪装成可观察 Planning。

## Contract impact

规划分析响应仍为 `learning-work-task-planning-analysis-v3`，本次只扩展阶段内 `substeps` 的深度、父子关系、跨分支依赖和可视化统计，不新增破坏性字段。它继续明确区分证据检索计划与学习型任务 Plan，并允许在证据未就绪时返回空的学习任务树、候选、Critic 和执行清单。基础 `learning-work-task-plan-v1`、远端 Run 接口和已有确认/重规划请求保持不变；`replan.target_package_id` 必须引用证据后生成的学习任务步骤 ID。该模块继续复用 `plan_learning_work_task` 和中央工作台，所有 Plan 事件仍是零 kernel target；没有修改三类主 Agent、五核键、EvidenceEvent schema、确定性归约或现有任务 Bundle 契约。
