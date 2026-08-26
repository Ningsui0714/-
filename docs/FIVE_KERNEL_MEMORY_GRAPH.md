# 五核可检查记忆图谱

## 五核的结构语义

五核是学习者状态的五个互补维度，不是五个 Agent，也不是五份可以互相覆盖的画像。它们分别承载不同对象和决策：`structure` 负责学习路径中的位置、依赖和返回；`knowledge` 负责概念理解、缺口、错误与掌握证据；`human` 负责当前负荷、注意、情绪反应和交互适配；`value` 负责目标、优先级、动机和相关性；`practice` 负责尝试、辅助、产物、反馈和迁移表现。

记忆图谱中的事实必须保留所属核、主题和证据等级。跨核关系用于表达“同一事件关联”或“一个事实支持另一个事实”，不表示核之间可以互相写入或互相替代。比如一次实践答错首先是 `practice` 事实；只有答案或理由足以定位概念问题时，才可以另外形成 `knowledge` 事实；它不会自动形成 `human` 或 `value` 事实。

短期状态用于当前教学决策，长期模块和声明只在对应核的证据门槛满足后形成。尤其是 `human` 的情绪/负荷默认短期有效，`knowledge` 的掌握需要评分证据，`practice` 的独立能力优先需要无辅助和变式证据。

## 数据分层

1. `EvidenceEvent` 是不可变动作账本，`occurred_at` 表示动作发生时间，`created_at` 表示系统记录时间，`learner_seq` 是学习者内单调序号。
2. `MemoryFact` 是由一次 `KernelMutation` 展开的原子事实。唯一键 `(source_mutation_id, fact_ordinal)` 保证重放幂等。
3. `MemoryModule` 只消费同一学习者、同一核、同一主题的事实。模块内容不可变，且不会再次成为合成输入。
4. `MemoryClaim` 是模块内可单独检查的声明。非历史导入声明必须由 `SUPPORTS` 边直接回到事实。
5. `MemoryEdge` 只保存高价值稀疏关系。跨核关系可以存在，但 `CONSOLIDATED_INTO` 两端必须同核。

`KernelState` 继续作为兼容投影。其短期区会附加 `memory_graph_recent_facts`，长期区会附加 `memory_graph_claims`。

## 复习如何维护长短期记忆

复习台不直接读取或修改一份独立的“错题画像”。它从原始题目、`LearningAttempt`、`RemediationCase` 和有作用域的五核投影构造当前题目状态，再由确定性调度器决定何时重现题目。

- 本轮答错或明确“不会”：Knowledge 短期 `retention_status` 标记检索缺口，Practice 短期 `review_history` 保留尝试；进入纠错和立即到期，但不凭一次失败形成固定误解。
- 辅助答对：记录 `retrieved_with_support` 与辅助等级，只形成过程证据。
- 独立答对：记录一次检索成功；原题成功不是迁移证明。
- 已校验变式独立答对：记录题目形式和迁移证据，但单次仍不等于长期稳定。
- 至少两次相隔 72 小时的独立成功，且包含已校验变式：Knowledge 长期区可形成 `spaced_stable` mastery，Practice 长期区形成 `spaced_independent_transfer` proof chain。
- 稳定后再次答错：短期状态回到 `needs_review`，调度阶梯重置并保留 lapse；既有事实、模块和声明不删除，以新事实表达风险并支持后续纠正。

`ReviewSchedule` 保存到期时间、阶梯、成功数、遗忘数和并发版本，但它是可从 Attempt 与纠错事件回填的运行投影。暂停、恢复、延期和跳过不会升级掌握，也不会生成 `MemoryFact`，因为对应事件的 kernel targets 为空。

## 写入与合成

事件写入请求不调用 LLM。归约器写入 `KernelMutation` 后同步生成事实和确定性边，并按五核规则创建 `MemorySynthesisRun`。

worker 的状态顺序为：

```text
queued -> running/reserved -> completed/consumed
                           -> failed/eligible
```

合成器只能引用运行记录中的候选 fact ID。越界引用、跨核候选和证据不足的知识掌握声明会整批拒绝。进程中断时，启动恢复会释放 reservation 并把运行重新排队。

自动合成默认关闭：

```env
MEMORY_AUTO_SYNTHESIS_ENABLED=false
```

在带标签轨迹的语义质量评测通过后，将其设为 `true` 并重启后端。未配置 LLM key 时，worker 使用确定性合成器，便于本地验证完整事务链路。

## API

- `GET /api/memory/graph`：按时间、核、节点类型、状态、项目和主题过滤，最多 300 节点。
- `GET /api/memory/timeline`：按发生时间分页读取节点。
- `GET /api/memory/nodes/{id}`：读取节点、邻居、原始动作、证据事实和合成审计。
- `GET /api/memory/consolidations`：读取持久化合成运行。
- `POST /api/memory/claims/{id}/feedback`：追加确认、纠正或撤回事件。

所有查询和反馈都使用当前登录学习者的 `learner_id`，不会接受客户端传入的学习者身份。

## 迁移与评测

v5 启动迁移会先创建 SQLite 一致性备份，然后回填双时间字段、mutation facts 和 `legacy_import` 模块。历史值无法精确定位事实时保持 `legacy/unverified`。

运行结构评测：

```bash
cd backend
./venv/bin/python scripts/evaluate_memory_graph.py
```

脚本对照字段覆盖、单体摘要和五核事实图，并检查声明证据覆盖、跨核输入、重复消费、模块不可变、纠错历史、幂等键、序号唯一性及 300 节点查询 p95。
