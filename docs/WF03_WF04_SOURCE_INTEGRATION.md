# 学习型任务转化与个性化学习源码集成说明

## 当前集成状态

- 集成分支：`integration/wf03-wf04`
- 本仓库基线：学习型任务转化分支 `feat/learning-task-conversion-v1`
- 个性化学习源码基线：`killoppen/main` 的 `10f781e`
- 源码落位：`integrations/wf04/`
- 合入方式：保留双方 Git 历史，并将个性化学习仓库隔离到子目录；未修改或推送任何 `main`

当前 LearnFlow 的 FastAPI/React 运行入口仍然是权威入口。`start.sh` 会把
`integrations/wf04/` 作为同仓个性化学习运行时一并启动；它通过窄交接接口接收已校验 JSON，
不会直接写入主应用五核、掌握状态或学习证据。

## 已带入的可复用能力

| 位置 | 能力 | 后续用途 |
|---|---|---|
| `integrations/wf04/backend/server.py` | 个性化学习项目、诊断、题目、讲解、复习与学习路径 API | 作为下游服务能力来源，拆出稳定适配接口 |
| `integrations/wf04/backend/spark_client.py` | OpenAI 兼容内容模型客户端（历史文件名） | 当前默认 DeepSeek，失败时保留确定性降级 |
| `integrations/wf04/backend/learning_path_workflow.py` | 学习路径规划流程 | 接收知识点交接后生成下游学习计划 |
| `integrations/wf04/backend/teaching_contract.py` | 教学内容契约与校验 | 校验下游生成产物，不作为掌握证据 |
| `integrations/wf04/frontend/agent.html` | 对话和学习项目主界面 | 作为中央工作区嵌入与交互适配参考 |
| `integrations/wf04/workflows/current/` | 已有工作流定义与调试样例 | 用于核对请求字段和本地/远端行为 |

`demo-output/` 与 `eval-output/` 属于已生成运行产物，没有进入本集成分支的文件树。

对方远端 `main` 的 `server.py` 和测试已经引用 `backend/data/capability_catalog.py`，但该源码未随
主线提交。本集成分支依据其现有公开测试和调用契约补回了该目录模块，覆盖计算机信息技术专业群
的 5 个方向、正式/参考支持等级与可校验的前置依赖路径，避免合入后服务在导入阶段直接失败。

## 第一条对接链

学习型任务转化侧已经提供知识点级交接：

```text
GET/POST /api/learning-task-conversion/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry
POST     /api/learning-task-conversion/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-launch
POST     /api/learning-task-conversion/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-results
```

下游已有可落地能力主要集中在：

```text
POST /api/projects
POST /api/projects/{project_id}/diagnosis/start
POST /api/projects/{project_id}/assessments/intake
POST /api/projects/{project_id}/plan/regenerate
GET  /api/projects/{project_id}/plan
GET  /api/projects/{project_id}/learning-map
```

已新增窄适配接口：

```text
POST /api/integrations/learning-task-knowledge
```

它把知识点级交接 JSON 确定性映射成三阶段下游项目并返回：

```json
{
  "project_id": "stable-project-id",
  "created": true,
  "redirect_url": "/agent.html?student_id=...&project_id=...&knowledge_point_id=...&entry_id=...",
  "entry_id": "stable-idempotency-key",
  "content_generation": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "configured": true
  },
  "assessment": {
    "type": "provisional_self_check",
    "status": "ready",
    "formal_evidence": false
  }
}
```

适配层由服务端绑定当前学习者身份，双端校验 `task_card_id`、`knowledge_id`、来源步骤和强关联技能；
数据库事务将 `entry_id` 与项目唯一绑定，并发或重复交接会恢复同一项目。下游路径严格由“知识点 →
关联技能 → 原任务步骤”形成基础、核心、应用三阶段，不另造领域课程。打开入口和生成内容只记录零
kernel target 的导航/运营事件，不能被解释为掌握证据。

导入后会立即准备练习型初测。嵌入页完成初测后，通过精确 origin 约束的
`postMessage` 把结果交回主应用；主应用再核对 `entry_id`、`project_id`、
`knowledge_point_id` 和启动记录。回传只接受 `provisional_self_check` 且
`formal_evidence=false`，记录为 `personalized_learning_result_received` 零核审计事件。

## 运行配置边界

个性化学习源码可在无远端密钥时使用本地确定性模板。当前临时使用 DeepSeek 内容生成，只需在本地运行环境
配置以下变量，真实值不得提交：

```text
CONTENT_LLM_API_BASE=https://api.deepseek.com/chat/completions
CONTENT_LLM_API_KEY=<DeepSeek API Key>
CONTENT_LLM_MODEL=deepseek-v4-flash
```

只有继续调用星辰工作流时，才需要 `XINGCHEN_*` 配置。DeepSeek 密钥与星辰
`API_KEY:API_SECRET` 是两套凭据，不能混用。旧的 `SPARK_*` 变量仍作为兼容回退保留。

## 合入后的约束

1. 主应用继续使用 `CurrentLearner`、Action Board、Evidence Ledger 与架构注册表。
2. 个性化学习源码作为隔离运行时；正式调用只能经过服务端窄适配层。
3. 下游返回的页面地址必须是白名单内相对路径或可信来源，不接受模型生成的任意 URL。
4. 规划、讲解、题目和页面生成均是内容产物；只有正式提交和确定性评估可形成学习证据。
5. 后续稳定后再逐模块迁移，避免同时运行两套身份、数据库和证据体系。
