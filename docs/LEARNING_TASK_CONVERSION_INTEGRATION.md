# 岗位典型工作任务转化模块接入 LearnFlow（v2）

## 功能定位

本模块把岗位方向或单个企业真实工作任务转化为可执行、可验收的学习型工作任务。讯飞星辰 Plan 负责输入判定、检索、候选生成与评审；独立任务服务负责语义锁、确定性门禁、持久化，以及 HTML、PDF 和结构化 JSON 交付；LearnFlow 负责登录态、会话、中央任务网页、批注复核及上下游接口。

它属于学习设计能力平面，不是第四类主 Agent。任务转化结果不能直接写五核、宣布掌握或替代个性化学习策略。

## 端到端链路

```text
右侧主 Agent：选择“生成学习型任务”
  -> POST /api/learning-task-conversion/generate
  -> 功能私有讯飞星辰工作流（每次使用独立 uid）
  -> 独立任务服务生成并保存任务包
  -> LearnFlow 从工作流结果提取 ltc_* 任务 ID
  -> 校验集成包与步骤—知识点—技能点引用
  -> 自动打开 /wf03/tasks/{task_card_id}
  -> 步骤资源链接、PDF、JSON、图谱回传均可点击
  -> 点击知识点，裁剪出知识点级交接 JSON 并进入个性化学习入口
  -> 批注提交给任务转化服务并形成可追溯复核事件
```

岗位输入会先由工作流选择一个可执行的典型工作任务；明确的单项任务则保持任务对象不变。步骤数量依据真实作业过程生成，不固定为五步。

## 功能私有配置

讯飞密钥不得写入全局 `backend/.env`。执行：

```bash
make setup-learning-task-conversion
```

随后填写被 Git 忽略的文件：

```text
backend/.private/learning_task_conversion.xfyun.env
```

必填键为：

```env
XFYUN_APP_ID=
XFYUN_API_KEY=
XFYUN_API_SECRET=
XFYUN_FLOW_ID=
```

任务服务地址仍由 LearnFlow 服务端固定配置，前端不能传入任意主机：

```env
LEARNING_TASK_CONVERSION_BASE_URL=http://82.156.199.145
LEARNING_TASK_CONVERSION_TIMEOUT_SECONDS=30
```

生产环境应替换为 HTTPS 域名。

## LearnFlow API

所有接口复用 LearnFlow 当前登录态：

| LearnFlow 接口 | 用途 | 远端/讯飞去向 |
|---|---|---|
| `POST /api/learning-task-conversion/generate` | 从右侧对话生成任务并解析任务 ID | 功能私有讯飞星辰 Plan + 任务集成包 |
| `POST /api/learning-task-conversion/workflow-runs` | 仅调试已绑定工作流 | 讯飞工作流 API |
| `GET /api/learning-task-conversion/capabilities` | 契约发现与健康检查 | `/api/v1/learning-task-conversion/capabilities` |
| `POST /api/learning-task-conversion/upstream-handoffs` | 接收岗位能力图谱确认的单项企业任务 | `/api/v1/learning-task-conversion/upstream-handoffs` |
| `GET /api/learning-task-conversion/tasks/{id}/bundle` | 获取中央页面需要的完整任务包 | `/api/v1/learning-task-conversion/tasks/{id}/bundle` |
| `GET /api/learning-task-conversion/tasks/{id}/personalized-learning` | 获取个性化学习输入 JSON | `/api/v1/learning-task-conversion/tasks/{id}/personalized-learning.json` |
| `GET /api/learning-task-conversion/tasks/{id}/knowledge/{knowledge_id}/personalized-learning-entry` | 获取单知识点级交接 JSON | 由 LearnFlow 从已校验任务包确定性裁剪 |
| `POST /api/learning-task-conversion/tasks/{id}/knowledge/{knowledge_id}/personalized-learning-entry` | 显式进入个性化学习并记录零核导航事件 | 返回同版本交接 JSON |
| `POST /api/learning-task-conversion/tasks/{id}/knowledge/{knowledge_id}/personalized-learning-launch` | 幂等创建/恢复知识点学习项目 | 同仓个性化学习导入接口 |
| `POST /api/learning-task-conversion/tasks/{id}/knowledge/{knowledge_id}/personalized-learning-results` | 接收已核对身份的练习型初测结果 | 只形成零核审计事件 |
| `POST /api/learning-task-conversion/downstream-feedback` | 回传弱关系、知识范围错误、步骤映射问题等批注 | `/api/v1/learning-task-conversion/downstream-feedback` |

任务包、能力发现和个性化学习 JSON 都是只读查询。远端出现 429、502、503、504
或连接中断时，LearnFlow 会在有限次数内退避重试；上游交接和下游反馈等写入接口
不会自动重放，避免产生重复任务或重复反馈。

`/generate` 只从工作流输出中接受真实 `ltc_*` 任务 ID。没有任务 ID 时必须返回 `needs_clarification` 或 `needs_revision`，不能把讯飞编排页或空 Markdown 链接伪装成任务网页。

## 中央任务网页

路由 `/wf03/tasks/{task_card_id}` 直接渲染已校验的结构化任务包，包含：

- 企业典型工作任务、学习型任务名称、描述和工作情境；
- 依据实际过程生成的可变数量步骤；
- 每步的操作动作、阶段产物、检查方式；
- 每步强关联的知识点、技能点；
- 知识点旁可直接点击的 B 站、抖音或其他学习资源；
- 安全要点、工具环境；
- 原交互页、PDF、个性化学习 JSON 和图谱回传 JSON；
- 步骤、知识点、技能点及任意选区的批注复核。

前端只渲染合法的 HTTP(S) 资源地址。空地址、相对空链接和工作流编排页不会被当作步骤资源。

## 上游岗位能力图谱交接

同仓上游页面点击任务节点时，推荐跳转到 `/learning-task-conversion/upstream`，并通过 React Router `state.handoff` 传入下列 JSON。也可以先写入 `sessionStorage` 的 `learnflow.upstream-handoff:{handoff_key}`，再携带 `?handoff_key=...`；同源嵌入页可发送 `learnflow:competency-task-selected` 窗口消息。该页面会完成交接校验、任务生成和中央工作区打开。

```json
{
  "schema_version": "competency-graph-learning-task-handoff-v1",
  "upstream_task_id": "network_vlan_001",
  "correlation_id": "learnflow-demo-001",
  "task_name": "交换机 VLAN 配置与连通性验收",
  "task_brief": "依据网络规划创建 VLAN、配置端口、验证终端连通性并提交验收记录。",
  "source_context": {"source_system": "岗位能力图谱生成功能"},
  "knowledge_points": [
    {
      "knowledge_id": "knowledge_vlan_01",
      "name": "VLAN 划分与 802.1Q 标记",
      "description": "理解 VLAN 广播域、Access/Trunk 端口及 802.1Q 标签的作用。"
    }
  ],
  "skill_points": [
    {
      "skill_id": "skill_vlan_01",
      "name": "创建 VLAN 并配置端口模式",
      "observable_action": "能够按规划创建 VLAN、配置 Access/Trunk 端口并保存配置。"
    }
  ],
  "relations": [
    {
      "relation_id": "relation_vlan_01",
      "knowledge_id": "knowledge_vlan_01",
      "skill_id": "skill_vlan_01",
      "relation_type": "required_for_step",
      "strength": "critical",
      "reason": "端口模式和 VLAN 标记知识直接支撑交换机配置与验收。",
      "applies_to_steps": ["configure_vlan"]
    }
  ]
}
```

## 个性化学习交付与回传

个性化学习功能接收任务简介、强相关知识技能点及步骤关系，继续组织“怎么学”；它不能改写企业任务名称、任务步骤或强关系。

发现不密切或理解错误时使用：

```json
{
  "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
  "task_card_id": "ltc_xxx",
  "correlation_id": "learnflow-demo-001",
  "source_system": "learnflow-task-review",
  "status": "accepted_with_feedback",
  "issues": [
    {
      "issue_id": "issue-001",
      "feedback_code": "step_mapping_mismatch",
      "severity": "warning",
      "step_id": "step_03",
      "knowledge_id": "knowledge_vlan_trunk",
      "message": "该知识点与当前步骤的直接关系不足。",
      "suggested_correction": "移动到 Trunk 配置步骤，或补充本步骤需要该知识的验收依据。"
    }
  ],
  "summary": "任务主体可用，建议修正一处步骤映射。"
}
```

反馈只形成可追溯复核请求，不会静默覆盖任务事实。修订结果必须重新经过内容与关系门禁。

### 知识点级生成入口

任务网页中的步骤知识标签和“支撑知识”卡片均可点击“个性化学习”。LearnFlow 不会把整份任务无差别交给下游，而是构造 `learning-task-knowledge-to-personalized-learning-v1`：

- `task_context`：企业任务名称、简介、学习型任务和工作情境；
- `focus.knowledge_point`：本次要学的唯一知识点及已整理资源；
- `focus.source_steps`：真正使用该知识点的任务步骤、动作、产物和验收点；
- `focus.strongly_related_skills`：上述步骤显式引用的技能点；
- `focus.relationships`：知识点—步骤—技能点强关系及来源依据；
- `generation_contract`：下游允许生成的学习目标、内容、顺序、练习、评价与学习者适配，以及不得改写的任务事实；
- `feedback_contract`：下游发现关系不密切或理解有误时的回传接口。

个性化学习导入由后端功能私有配置控制：

```env
PERSONALIZED_LEARNING_IMPORT_URL=http://127.0.0.1:4174/api/integrations/learning-task-knowledge
PERSONALIZED_LEARNING_TIMEOUT_SECONDS=20
PERSONALIZED_LEARNING_API_TOKEN=
```

用户点击“开始生成个性化学习”后，LearnFlow 后端调用 `POST .../personalized-learning-launch`，将已校验的知识点级 JSON 直接导入下游。启动交接 ID 使用基础交接与当前学习者作用域稳定派生，不暴露学习者 ID；下游按该 `entry_id` 幂等创建或恢复项目，因此同一学习者重试不会重复创建，不同学习者也不会串用项目。返回的任务、知识点、项目 ID 与地址经后端校验后，在 LearnFlow 中央工作区嵌入展示。用户不需要下载、上传 JSON，也不会离开左侧项目栏和右侧主 Agent。

`start.sh` 会启动同仓个性化学习运行时，并通过进程环境把实际端口交给主后端；私有配置仍可覆盖为拆分部署地址。未配置且未通过一键脚本启动时，`/personalized-learning/tasks/{task_card_id}/knowledge/{knowledge_id}` 仍可预览待交接内容，启动操作会返回明确错误，不会伪造成功项目。

个性化学习运行时当前默认使用 DeepSeek `deepseek-v4-flash`；只有配置 `integrations/wf04/backend/.env` 中的 `CONTENT_LLM_API_KEY` 才会调用远程模型，否则明确显示“本地确定性模板”。导入后立即预生成 `provisional_self_check` 练习型初测。完成初测时，嵌入页只向精确父窗口 origin 回传结果；主系统会复核交接 ID、项目 ID、知识点 ID 和启动事件。该结果的 `formal_evidence` 必须为 `false`，不更新五核、掌握度或学习路径。

结果回传协议为：

```json
{
  "schema_version": "personalized-learning-result-v1",
  "entry_id": "ple_xxx",
  "project_id": "PROJ-xxx",
  "knowledge_point_id": "knowledge_xxx",
  "result_type": "assessment_completed",
  "result_id": "ASSESS-xxx",
  "formal_evidence": false,
  "summary": {
    "assessment_type": "provisional_self_check",
    "score": 3,
    "total": 5,
    "weak_point_count": 1,
    "feedback": "练习型初测完成。"
  }
}
```

## 运行与验收

```bash
make start
make verify-learning-task-conversion
```

验证脚本不会打印密钥值，会检查功能私有配置字段、后端契约/API/架构测试和前端生产构建。

当前边界：上游节点接入、知识点交接、下游项目物化/恢复、临时自测、中央工作区展示、结果回传和关系纠偏已连通。这些导航与运营事件仍是零 kernel target；不会因生成项目、打开页面、完成临时自测或提交复核而写入五核掌握证据。
