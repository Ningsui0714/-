# 三工作流后端

WF04 的错题优先个性化出题、错因级合并规则和联调验收方式见
[WF04错题优先个性化出题对接说明.md](./WF04错题优先个性化出题对接说明.md)。

后端只使用 Python 标准库，不需要安装第三方包。它同时提供：

- `frontend/` 静态页面；
- 上游测验/诊断结果入口；
- 学生画像、推荐、目标与路径规划、对话、出题与 WF04 等星辰工作流的代理；
- **讲解模块已本地化**（`backend/local_explanation_engine.py`）：正式章节讲解、
  候选讲解与纠错讲解由本地课程知识库 + 联网检索 + 内容模型直连生成，不再调用星辰工作流；
- 本地学生画像缓存、策略引擎和知识依据缓存；
- SQLite 学习状态和调用记录；
- 学习周期、任务实例、题目、作答、讲解会话和结构化来源持久化；
- 通知、账户、学习记录、设置与收藏 API；
- 原题重做、变式题生成和作答判定；
- 异常追问的恢复请求；
- 未配置星辰密钥时可用的本地模拟模式。

## 启动

```powershell
python backend\server.py
```

访问 `http://127.0.0.1:4173/`，不要再使用 `file:///.../frontend/index.html`，否则前端无法访问同源 API。

默认仅监听本机地址，跨域请求只允许 `APP_ALLOWED_ORIGINS` 中的来源。若需要监听 `0.0.0.0` 或其他非回环地址，必须配置 `APP_API_TOKEN`；除健康检查外的 API 请求需携带：

```http
Authorization: Bearer APP_API_TOKEN的值
```

```env
APP_ALLOWED_ORIGINS=http://127.0.0.1:4173,http://localhost:4173
APP_API_TOKEN=
```

## 本地知识库（FTS5）

- 种子数据：`backend/data/knowledge_seed.py`，**56 条**，覆盖 KN_JAVA_* 全部 7 个学习节点（类/封装/继承/多态/集合/异常/IO，每节点 8 条）。
- 每条字段：`entry_id`（KN-JAVA-{序号}）、`title/category/content/source/safety/job_role/knowledge_point_id`，另有 `source_type/document_id/locator/action/keywords`。
- 来源类型：《Java 核心技术·卷I》（原书第11版）、Oracle Java 教程、实训指导书（页码待访谈后回填）。
- 存储：`knowledge_entries` 普通表 + `knowledge_fts` 外部内容 FTS5（trigram tokenizer）；启动时幂等 `INSERT OR IGNORE` 灌入并重建索引，不重复入库。
- 检索增强：讲解（learning/remediation）与选中追问都先按 `knowledge_point_id` + 讲解动作召回 top-k，拼成 `kb_text` 交给本地讲解引擎/对话生成，并把命中条目以 `sources[]` 结构注入教学包来源（前端来源弹窗可见标准号/章节）。
- 无匹配时回退到原有 web_search/知识名证据链路，不影响无本地条目时的原行为。

## 本地讲解引擎（OpenAI 兼容直连）

讲解正文不再依赖星辰画布工作流，改由 `backend/local_explanation_engine.py` 在本地生成：

1. **来源门禁**：仅使用本地课程知识库（FTS5）与白名单联网检索证据；两者都没有时返回 `knowledge_unavailable`，绝不用无来源 AI 内容替代。
2. **LLM**：配置 `CONTENT_LLM_API_KEY` 后直连 OpenAI 兼容端点生成讲解；当前默认 DeepSeek `deepseek-v4-flash`，失败/未配置自动回退确定性模板。
3. 相关星辰配置项 `XINGCHEN_LEARNING_FLOW_ID`、`XINGCHEN_REMEDIATION_FLOW_ID`、`XINGCHEN_KNOWLEDGE_PLANNING_FLOW_ID`、`XINGCHEN_KNOWLEDGE_AUDIT_FLOW_ID` 已停用，保留仅为兼容历史配置。

## 接入讯飞星辰

1. 在星辰平台导入并发布 `学生画像分析工作流.yml` 与 `测验后个性化纠错讲解工作流_v5.yml`（纠错讲解已本地化，非必需；对话/出题/WF04 等按需发布对应工作流）。
2. 从发布页取得 `API_KEY`、`API_SECRET` 和对应工作流 ID。
3. 复制 `backend/.env.example` 为 `backend/.env`，填写密钥和工作流 ID，并将 `XINGCHEN_MODE` 改为 `remote`。
4. 可选：填写 `CONTENT_LLM_API_KEY`（当前为 DeepSeek API Key，与 `XINGCHEN_API_KEY` 是两套独立凭据）启用 AI 讲解生成；留空则讲解走本地模板。

```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
python backend\server.py
```

PowerShell 示例：

```powershell
$env:XINGCHEN_MODE = "remote"
$env:XINGCHEN_API_URL = "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
$env:XINGCHEN_API_KEY = "发布页的 API_KEY"
$env:XINGCHEN_API_SECRET = "发布页的 API_SECRET"
$env:XINGCHEN_PROFILE_FLOW_ID = "学生画像分析工作流 ID"
$env:XINGCHEN_LEARNING_FLOW_ID = "学习阶段讲解工作流 ID"
$env:XINGCHEN_REMEDIATION_FLOW_ID = "测验后纠错工作流 ID"
python backend\server.py
```

后端会按请求类型选择对应 Flow ID。迁移期间仍可只设置 `XINGCHEN_FLOW_ID`，三个入口会回退到该统一工作流；正式启用拆分架构时应配置三个专用 ID。

学生画像在无缓存时异步生成，之后每累计 5 个学习/纠错事件刷新一次。高频讲解请求由本地 `StrategyEngine` 完成策略选择，知识依据在内存中缓存 300 秒，学习和纠错工作流不再承担策略决策与知识检索。

## 外部学习资料插件

对话页的“学习资料”开关可选接入星辰导出的外部知识工具。该来源只用于即时资料查询，返回内容统一标记为“未经审核”，不会写入正式知识库、学习者画像或掌握度。

```env
MATERIAL_KNOWLEDGE_ENABLED=1
MATERIAL_KNOWLEDGE_URL=https://example.edu/material-search
MATERIAL_KNOWLEDGE_REQUEST_TYPE=0
MATERIAL_KNOWLEDGE_TIMEOUT=8
```

适配器按导出配置使用 `POST`，并通过查询参数发送 `input_source`、`input_memory`、`request_type`、`input_request`，读取 `resources` 和 `return_memory`。当前仅使用 `resources`；外部返回的 `return_memory` 不进入项目记忆。默认拒绝向非本机的明文 HTTP 地址发送学习内容；只允许在明确的本地联调环境设置 `MATERIAL_KNOWLEDGE_ALLOW_INSECURE_HTTP=1`。

## 联网视频资源

后端可在学习初始化、切换讲法、请求视频和测验讲解时，通过 Bing RSS 搜索教育视频。搜索结果只接受配置白名单中的视频站点，并把标题、链接、来源站点、检索服务和可嵌入地址一并传给工作流和前端。

```env
VIDEO_SEARCH_MODE=bing_rss
VIDEO_SEARCH_URL=https://www.bing.com/search?format=rss&q={query}
VIDEO_SEARCH_TIMEOUT=12
VIDEO_SEARCH_MAX_RESULTS=4
VIDEO_SEARCH_CACHE_SECONDS=3600
```

设置为 `VIDEO_SEARCH_MODE=off` 可关闭联网搜索。搜索失败不会生成虚构视频链接，页面会明确显示资源缺口。

## 联网文档资源（文档板块）

后端在开启视频检索的同时（或单独设置 `DOC_SEARCH_MODE=bing_rss`），会再执行一次官方文档检索：
只接受白名单域名（`docs.python.org`、`learn.microsoft.com`、`developer.mozilla.org`、`w3.org`、
国家标准与政府教育域名等），结果以 `type: "document"` 进入 `resources`，前端「文档教学」板块内联展示
标题、来源与内容摘要，可点「打开原文」跳转。

```env
# 空值跟随 VIDEO_SEARCH_MODE；off 单独关闭；bing_rss 单独开启
DOC_SEARCH_MODE=
```

文档检索与视频检索共用 `VIDEO_SEARCH_*` 的超时、数量与缓存配置；白名单外域名一律不进文档板块。

后端发送给星辰的实际请求为：

```json
{
  "flow_id": "按调用类型选择的三个 Flow ID 之一",
  "uid": "student_id",
  "parameters": {
    "AGENT_USER_INPUT": "序列化后的完整工作流输入 JSON"
  },
  "stream": false
}
```

请求头为 `Authorization: Bearer API_KEY:API_SECRET`。星辰把工作流结束节点结果放在 `choices[0].delta.content`，后端将其中的 JSON 解析后再返回前端。

## API

- `GET /api/health`
- `GET /api/bootstrap?student_id=STU-001`
- `GET /api/admin/profile-status?student_id=STU-001`
- `POST /api/upstream/assessment-result`
- `POST /api/admin/refresh-profile`
- `POST /api/explanations`：六场景统一入口；学习、换讲法和纠错场景路由到对应专用工作流，保留场景返回 `SCENE_NOT_READY`
- `POST /api/workflows/learning`
- `POST /api/workflows/review`
- `POST /api/workflows/review/resume`
- `GET /api/students/{student_id}/learning-state`
- `GET /api/students/{student_id}/profile|notifications|records|settings|portrait`
- `POST /api/students/{student_id}/settings|favorites`
- `POST /api/students/{student_id}/notifications/{notification_id}/read`
- `POST /api/practice/questions`
- `POST /api/question-instances/{question_instance_id}/attempts`
- `GET /api/explanations/{explanation_session_id}/sources?student_id=...`
- `GET /api/explanations/{explanation_session_id}/stream?student_id=...`：SSE 分节流式讲解（status/section/done/error）
- `POST /api/explanations/{explanation_session_id}/ask`：选中文本追问，支持澄清反问与多轮历史
- `GET /api/students/{student_id}/portrait`：画像页 9 区块聚合（kpi/能力/知识点/薄弱点/风格/成长/推荐/行为/对比）
- `GET /api/knowledge/search?q=&knowledge_point_id=&action=&category=&limit=`：本地 FTS5 知识库检索（BM25 排序、中文 trigram 子串匹配 + LIKE/分词兜底；`action` 把讲解动作映射到条目分类，如 concept/steps/example/warning）

`POST /api/upstream/assessment-result` 会自动判断：错误测验数据进入纠错讲解工作流，薄弱点诊断数据进入学习讲解工作流。同一份上游结果可以同时触发两类讲解；画像分析由后端按事件数异步触发。`event_id` 具备幂等语义，重复提交返回 `status=duplicate`，不会再次派发工作流或累计画像事件数。

本地 mock 模式的异常恢复令牌是随机、15 分钟过期且只能使用一次的数据库令牌，不再把完整题目或作答上下文编码到令牌中。令牌同时绑定创建时的 `student_id` 和 `session_id`，身份不匹配时拒绝恢复且不消耗令牌。
