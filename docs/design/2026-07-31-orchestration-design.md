# LearnFlow 下一阶段设计讨论 v0（2026-07-31）

> 状态：待与 Ryan 逐项敲定。本文是讨论底稿，不是最终方案。

## 0. 现状盘点（读代码后的关键观察）

- **RoadmapAgent**：单次 LLM 调用，全仓库 chunk 截断塞进 system prompt（每块 500 字符、只看前 15 个文件），`chunk_ids` 靠 LLM 从 `[chunk-N]` 标记里"猜" → 不可信、易错。
- **LectureAgent**：plan → generate 两段式，四级检索（文件路径 / topic_hints / 内容密度 / 向量）其实做得不错，但**没有利用仓库自身结构**，小节结构是 LLM 自由发挥，与仓库逻辑无关。
- **讲义生成绑定在 SSE 请求上**：前端 unmount 会主动 close SSE，后端 StreamingResponse 生成器随之被杀 → 退出页面 = 生成中断。
- **练习生成**：固定 2 题、JSON 解析脆弱（phase3 有 strict 失败后即使 lenient 修复成功也返回 error 的死代码）、`test_cases` 字段存在但生成流程不产出、没有"判题提交"语义。
- **路线变更**：只有 prompt 层面说"已完成的关卡不可删"，`_sync_checkpoints` 确实保护 completed，但没有任何进度迁移机制；来源没有主/辅之分；chunk 分配完全依赖 LLM 手写 id。

## 1. 主题一：智能体编排与工具调用

### 1.1 仓库理解分层（结构优先，检索按需，不是 RAG 提示词增强）

关键转变：把"一次塞上下文"改成"工具化按需读取"，语义检索只在需要时发生。

- **L0 结构层（确定性，无 LLM）**：readme_toc + dir_groups + heading 链 + 文件清单。已有，补充一个**结构置信度判定**：多策略一致 → high；冲突（TOC 与目录对不上）→ medium/low → 触发 LLM 复核。
- **L1 章节概要层（LLM，批量、缓存）**：每个章节目录/文件生成 1-2 行摘要，存 DB 缓存（新表或扩 meta_data）。规划对话前一次性生成，之后直接读，不重复烧 token。
- **L2 按需精读层（工具调用）**：`read_chunk(ids)` / `list_chunks(file)` —— 只有 agent 需要看细节时才调。
- **L3 语义检索层（工具调用）**：`search_chunks(query)` —— 仅在 L0-L2 信息不足时调用（用户问了个目录里看不出来的问题）。

RoadmapAgent 改用 function calling（DeepSeek 支持），绑定上述工具。

### 1.2 关卡信息契约 CheckpointBrief

路线确认后，系统为每个 checkpoint 物化一份结构化"交接单"，所有下游智能体（讲义 / 练习 / 追问 / 判题）只认这份契约：

```json
{
  "version": 3,
  "checkpoint_id": 12,
  "order": 4,
  "title": "线性回归从零实现",
  "objective": "…",
  "prerequisites": [3],
  "scope": {
    "main_source_id": 1,
    "files": ["chapter_linear-networks/linear-regression-scratch.md", "…"],
    "structure_logic": "tutorial-progression",
    "structure_confidence": "high"
  },
  "seed_chunks": [101, 102, 105],
  "chunk_mapping_confidence": "medium",
  "key_concepts": ["线性回归", "损失函数", "小批量随机梯度下降"],
  "retrieval_policy": {
    "boost_chunk_ids": [101, 102],
    "boost_weight": 1.5,
    "restrict_to_scope": true,
    "allow_fallback_global": true
  },
  "practice_plan": { "concept": true, "code": true, "suggested_count": 4 }
}
```

### 1.3 上下游检索状态传递

- CheckpointBrief.retrieval_policy 成为下游检索的初始化参数。LectureAgent 的 `_retrieve_relevant_chunks` 增加 `boost` 参数：命中 boost_chunk_ids 的 chunk score += boost_weight（1.5 ≈ 语义分 +50%）。
- `restrict_to_scope` 时检索池先限定在 scope.files；召回不足（top_k 中 scope 内占比 < 60%）再 fallback 全局 → 精度与兜底兼顾。
- 关卡智能体可自行调整策略：讲义某小节检索太稀 → 该节单独放宽 scope；练习发现概念覆盖不足 → 扩大检索。
- 反向传递：关卡智能体的发现（某 chunk 实际更贴近另一关）可写回 brief 下一版本。

### 1.4 进程管理（讲义生成不随页面死）

现状：SSE 生成器绑在 HTTP 请求上，前端 unmount 主动 close，后端生成器被 cancel。

方案：引入任务层（Task 表 + 进程内 asyncio 任务注册表；先不上 celery/arq，规模到了再换）：

- `POST /checkpoints/{id}/lecture/generate` → 创建 task（queued）→ 后台 asyncio 运行生成器 → **每生成一节立即增量落库**（现在只有全部完成才 save）。
- 前端改为订阅任务流（SSE 带 task_id 或轮询 + 事件流）；离开页面 / 重进 / 刷新都能恢复进度。
- 状态机：queued → running → completed / failed / canceled / partial；支持 resume（从失败节续跑）。
- 取消：显式 cancel 才停；浏览器关页面不 cancel 任务。

### 1.5 错误引导与回滚

- **错误分类**：LLM 配置缺失 / 网络 / LLM 格式不符 / 上下文超长 / 检索空 —— 每类不同文案与下一步（现在统一"生成失败，检查 API Key"）。
- **格式不符**：降 temperature 重试 1 次；仍失败则降级（如单节降为最小结构），并**警告用户降级发生**。
- **讲义版本化**：lecture_versions 表存旧版，重新生成不覆盖而是新建版本，一键回滚。
- **路线应用事务化**：diff 预览 → 确认 → 应用；失败回滚（见 §5）。

## 2. 主题二：讲义——结构感知分块 + 图片

### 2.1 分块策略：仓库逻辑为主，教学重组为辅

现在 plan 的 4-8 节是 LLM 自由发挥。改为"双信号输入，一个 planner 合并"：

1. **结构信号（确定性）**：从 CheckpointBrief.scope 取文件顺序 → 每文件 heading 链 → 形成"候选小节骨架"（每项标注来源：file+heading 或 readme-toc）。
2. **内容信号（LLM）**：读 seed_chunks，产出教学递进建议（哪些概念先讲、哪里该合并/拆开）。
3. **Planner（一次工具调用）**：默认**按仓库顺序**产出小节；只有结构置信度低、或教学确有必要（如仓库把定义放最后但教学应先讲定义）才调整，且每个调整输出理由。

仓库逻辑类型识别（新知识递进 / 项目步骤 / 论文逻辑）用确定性启发：目录名（chapter_*、src/*、paper/）、README 措辞 → 选择对应小节模板（教程按节推进、项目按步骤、论文按 section）。

配套 chunker 改进：按文件 → 按 heading 层级切，不跨 heading 乱切；meta 带完整 heading 链（现在截断 10 个）+ prev/next chunk id + 文件内序号 → 生成时保持"流动感"。

### 2.2 图片功能（分三档）

- **P0 仓库图片**：md 引用的图（相对路径/URL）在分块时登记 → 讲义生成时引用原样保留 → 后端静态服务 / 前端代理，LectureRenderer 渲染。
- **P1 AI 示意图**：生成时用 Mermaid 画结构图，后端 mermaid CLI 渲染为 SVG 内嵌（比 ASCII 好看且可控）。
- **P2 生成式配图**：调图像模型生图——质量/成本风险高，放最后，且做成"手动触发"（每节一个生成配图按钮），不自动。

## 3. 主题三：练习

### 3.1 概念考察题

- 模型：`ConceptQuestion { question, options[], answer_index, q_type, difficulty, explanation, source_chunk_ids, assessment_meta }`。`q_type` 只描述响应形式，学习目标与证据声明进入 `assessment_meta`。
- 生成：输入 brief + 讲义 + scope chunks → 动态 3-10 题（数量由内容复杂度决定）。
- 代码输出预测只是可选的 `code_output` 形式，仅在关卡确实考察程序追踪时使用，并由 `code_executor` 校验；WWPD/WWPP 只作为早期设计参考，不是 LearnFlow 的固定内容或题型体系。
- 题型体系仍处于研究与验证阶段。当前先固定“学习目标 → 证据声明 → 响应形式 → 判分解释”的设计协议，不把未经验证的题型分类写死为产品标准。
- UI：题卡 + 选项 + 提交判分 + 每题"🤖 解析"按钮（懒加载，点击才调 LLM，带该题上下文与用户答案）。

### 3.2 代码命题智能体（强健版）

把"一次生成 2 题"改为三段流水线：

1. **蓝图**：分析教学内容 + brief → 题目蓝图列表 `{ idea, 考察概念, 难度, 与其它题的关联, 工程价值, 建议位置 }`。做两件事：去重（等价考察合并）、数量定稿（有料才多出，没料就少出，绝不硬编）。
2. **逐题生成**：每道题独立生成 title/description/starter/solution/hints/test_cases；pydantic schema 校验，失败重试 1 次。
3. **可执行验证（关键）**：code_executor 跑 solution × test_cases，全部通过才入库；不过则自动修复（最多 2 轮）或废弃该题。解决"题是编的、答案跑不通"的信任问题。
4. **判题提交**：前端"提交"→ 后端隔离跑用户代码 × test_cases → 返回逐用例 passed/failed（现在 run 只是执行，没有判题语义）。

"互相关联但不等价"在蓝图阶段显式建模：题 2 的 starter 声明 `depends_on: 题1`，允许引用题 1 的解法（题 1 实现类，题 2 在其上扩展），生成器拿到前置题解法作为上下文。

顺带修 phase3 的 JSON 解析死代码 bug。

## 4. 主题四：工作台功能灵感（按性价比排序）

现状只有"划词 → 自由提问"。候选：

1. **快捷动作**（成本低、感知强）：划词后出现按钮组——解释 / 举例 / 总结 / 翻译 / 出思考题 / 溯源。每个是预设 prompt 模板。
2. **溯源**：划词 → 显示来自哪个源文件哪一段（chunk meta 有 file+heading），点击跳原文。
3. **笔记与高亮**：锚定到讲义段落（section+段落 id）的笔记，侧栏管理，可导出 Markdown。
4. **概念卡 + 概念图谱**：划词生成概念卡（定义/公式/例子/关联），存概念库；由讲义 headings + 概念卡自动生成该关卡迷你知识图谱（React Flow 已有，半档做概念卡，图谱后置）。
5. **段落级功能**：每节末尾思考题一键展开解析；"这节可能难"标记（公式密度/代码长度启发式）。
6. **间隔复习**：概念题/自查题接简易 SM-2，工作台出现"今日复习"。
7. **题目直达**：划词 → "根据这段出 2 题" → 直接进练习区。
8. **朗读**：选中文字 TTS（macOS say 零成本）。

第一波建议 1+2+3，4 做半档（概念卡），其余进 backlog。

## 5. 主题五：路线变更策略

### 5.1 变更分类（先分类再决定执行方式）

| 变更类型 | 处理 |
|---|---|
| A. 加节点 / 删未学节点 / 改未学节点描述 | diff 预览 → 直接应用 |
| B. 删/改已学节点 | 不删！标记 archived，学习产物（讲义/练习/进度/笔记）迁移到 agent 建议的替代节点，用户确认迁移映射 |
| C. 整体重构 | 双轨制：旧路线只读存档 → 生成新路线 → agent 产出"旧→新 checkpoint 映射表" → 用户确认 → 迁移进度和产物 → 切换 |

### 5.2 进度模型

Checkpoint 增加 progress JSON：`{ lecture_read_ratio, exercises_done, concept_accuracy, notes_count }`。
迁移：产物留在旧节点（有迹可查），新节点挂引用 + 搬 progress 摘要。

### 5.3 新增来源

新来源处理完 → 触发 reconcile 流程：对比新来源结构与当前路线（结构置信度 + 语义匹配），agent 给三选一：插新关卡 / 扩展现有关卡 scope / 忽略；用户确认后以 diff 应用。**不整条重规划**。

### 5.4 主线索 vs 辅助来源

- Source 加 `role: main | auxiliary`（默认 main）。
- 路线骨架只由 main 源决定；aux 源进检索池但加权 ×0.7，仅作补充。
- RoadmapAgent 结构上下文默认只展示 main 源；aux 源作为"可检索资源"按需调。

### 5.5 减少输出结束压力

- **不再让 LLM 在聊天里输出全量 roadmap JSON**。聊天只谈变更意图；确认时调用 `apply_roadmap_diff(diff)` 工具，diff 很小（如 `{insert_after: 3, checkpoint: {...}}`）。
- 全量 JSON 由系统在 apply 时确定性生成，LLM 不负责。
- chunk 分配不让 LLM 手写 id：brief 的 scope 确定后由系统按"文件归属"确定性分配，agent 只复核调整异常。
- 上下文瘦身：对话 system prompt 只带 L0 结构 + L1 章节摘要，不塞 chunk 原文；细节走 read_chunk 工具。

## 6. 任务拆分（建议执行顺序）

依赖：T1 是地基，T2/T3 是编排核心，T4-T6 讲义侧，T7/T8 练习侧，T9 工作台，T10 路线变更。

| # | 任务 | 核心内容 | 归属建议 |
|---|---|---|---|
| T1 | 任务/作业层 | Task 表 + asyncio 注册表、SSE 订阅重构、增量落库、resume/cancel、错误分类 | Melody 先做 |
| T2 | 仓库理解管线 + 工具化 RoadmapAgent | L0-L3 分层、function calling、CheckpointBrief 物化、apply_roadmap_diff | Melody 先做（方案 Ryan 审） |
| T3 | 检索上下文传递 | brief → 检索策略注入、boost 加权、scope 限定 + fallback、策略反写 | Melody 先做 |
| T4 | 结构感知讲义分块 | 双信号 planner、结构逻辑类型识别、chunker 改进 | 先讨论方案再实现 |
| T5 | 讲义版本化 + 回滚 | lecture_versions、一键回滚、partial 恢复 | 并入 T1 或独立 |
| T6 | 图片功能 | P0 仓库图、P1 Mermaid→SVG | 可后置 |
| T7 | 概念考察题 | 模型 + 生成 agent + WWPD 自校验 + UI + 解析按钮 | Melody 实现，题型设计 Ryan 把关 |
| T8 | 代码命题智能体 | 蓝图 → 逐题 → 可执行验证、判题提交、修 bug | Melody 实现，命题质量 Ryan 验收 |
| T9 | 工作台扩展 | 快捷动作 + 溯源 + 笔记（第一波） | Ryan 定功能，Melody 实现 |
| T10 | 路线变更策略 | 变更分类、双轨重构、进度迁移、来源角色、reconcile | 方案敏感，先一起敲定再动 |

## 7. 待拍板问题

1. 任务层用"进程内 asyncio + DB 持久化"起步（简单够用），还是直接上 arq/celery？
2. CheckpointBrief 作为统一契约的形态是否认可？特别是 retrieval_policy 那段。
3. 练习"动态数量"倾向宽松（3-10 题随内容）还是严格（只出高价值题，宁缺毋滥）？
4. 工作台第一波功能清单（建议 1+2+3+半档 4）是否同意？
5. 路线重构的双轨制 + 进度迁移，是否认可"产物留旧节点、新节点挂引用"？
