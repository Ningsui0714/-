# AGENTS.md

## 0. 项目永久记忆

- 本项目对应的 Obsidian 记忆索引为 `D:\obsidian\study\Codex永久记忆\项目\2\索引.md`。
- 每个项目会话首次任务开始前，使用 `$project-memory` 读取全局索引和本项目索引，并按任务只加载必要记忆。
- 若本项目最近 Codex 沟通晚于索引中的 `last_synced_at`，先将稳定结论同步到本项目记忆。
- 任务产生长期有效的状态、决定、风险或交接结论时，结束前更新相应记忆文件；不要记录密钥、`.env` 值、私有用户数据或日志正文。
- 该记忆只提供上下文，真实代码、最新测试和当前远端状态始终优先。

## 1. 项目定位

- 产品名：知行课径。
- 产品定位：面向计算机信息技术专业群的目标驱动型个性化学习智能体。
- 用户目标可来自专业方向、课程、岗位、技能竞赛或自我提升。
- 主闭环：目标澄清 -> 能力图谱 -> 初始测评 -> 薄弱点 -> 个性化路径 -> 学习/实操 -> 阶段测评 -> 纠错/复测 -> 画像更新。
- Java 应用开发是当前首个成熟示范内容包，不是产品的最终范围。
- 未具备正式能力包的方向只能提供参考规划或临时自测，不得宣称为正式能力诊断。
- AI 负责理解与生成；判题、掌握度、前置依赖、证据写入和来源校验必须由确定性代码控制。

## 2. 技术栈

### 前端

- 原生 HTML、CSS、JavaScript，无 React/Vue 构建链。
- 主入口：`frontend/agent.html`，根路径 `/` 由后端映射到该文件。
- 旧学习中心：`frontend/index.html`，仅保留兼容能力。
- 通用前端逻辑：`frontend/app.js`、`frontend/api.js`。
- 样式：`frontend/styles.css`；优先复用 `:root` CSS 变量。
- 本地依赖：`frontend/vendor/marked.min.js`、`frontend/vendor/katex/`、`frontend/vendor/lucide.min.js`。
- 前端由后端同源托管，不要通过 `file:///` 打开页面。

### 后端与数据

- Python 3.11+，后端主要使用 Python 标准库。
- 服务入口：`backend/server.py`，默认监听 `127.0.0.1:4173`。
- 持久化：SQLite；运行库路径由 `APP_DATABASE` 控制。
- 领域存储与证据：`backend/domain.py`。
- 目标解析/路径逻辑：`backend/goal_engine.py`、`backend/data/goal_graph.py`。
- 内容资产：`backend/data/knowledge_seed.py`、`diagnosis_bank.py`、`error_cards.py`。
- 学习者状态发现：`backend/learner_discovery/`。
- 检索：SQLite FTS5；联网资料只允许可信来源，并保留原始 URL/定位信息。

### 智能工作流

- 使用讯飞星辰工作流 OpenAPI，开发/测试可使用本地 mock。
- 当前工作流位于 `workflows/current/`：目标规划、测评出题、学习讲解、纠错讲解、画像、推荐、对话问答。
- 工作流输入使用 `AGENT_USER_INPUT` 承载序列化业务 JSON。
- 生成类能力放在工作流；题目校验、判题、路径依赖、数值聚合和持久化留在后端。
- 任何工作流结构变更都要同步其独立调试数据和后端解析契约。

## 3. 目录结构

```text
backend/                       后端、领域逻辑、SQLite 与单元测试
  data/                        能力图谱、知识条目、题库、错误卡
  learner_discovery/           学习者状态发现子系统
frontend/                      Web 页面、样式、交互与本地前端依赖
  assets/                      图片等静态资源
  vendor/                      固定版本第三方前端库
workflows/current/             当前有效的星辰工作流资产
  debug-data/                  每条工作流一份 JSON 调试数据
workflow-nodes/                工作流自定义节点源码
docs/                          过程设计和专项说明（通常不提交）
references/                    外部参考项目/材料，只读使用
prototype/                     原型，不是正式页面入口
tools/                         构建、校验和辅助工具
test-screenshots/              浏览器测试生成截图
demo-output/、eval-output/     演示与评估产物
_archive/                      历史归档，只读
```

新增正式代码应进入 `backend/` 或 `frontend/`；不要继续向根目录堆放临时脚本。

## 4. 命名规范

### Python

- 文件、函数、变量：`snake_case`。
- 类：`PascalCase`。
- 常量：`UPPER_SNAKE_CASE`。
- 私有辅助函数以 `_` 开头。
- ID 使用稳定业务前缀，如 `KN_`、`GOAL-`、`ASSESS-`、`ATTEMPT-`。
- 类型注解沿用 `dict[str, Any]`、`list[str]` 等 Python 3.11 写法。
- 时间统一使用带时区 ISO 8601；不要存无时区本地时间。

### JavaScript、HTML、CSS

- JavaScript 变量和函数：`camelCase`；常量可用 `UPPER_SNAKE_CASE`。
- CSS 类名：`kebab-case`；新颜色和尺寸优先定义为 CSS 变量。
- DOM `id` 必须唯一且语义明确，不使用无意义缩写。
- API JSON 字段统一使用 `snake_case`，不要在前后端之间引入第二套命名。
- 事件名使用 `kebab-case`，例如 `workflow-request`。
- 用户可见文案使用简体中文；内部状态值保持稳定英文枚举。

### 数据、工作流与文档

- 知识点 ID、目标 ID 一经被数据引用不得随意改名。
- 工作流文件使用清晰中文业务名；不要新增“最终版”“新新版本”等文件名。
- 每条工作流仅保留一份对应调试 JSON，文件名与工作流名一致。
- 正式知识条目必须包含来源、定位符、来源类型和审核状态。
- AI 生成内容不得写回权威知识库，必须带“AI 生成”标识。

## 5. 禁止或限制修改

除非用户明确要求，以下内容不得修改、移动或删除：

- `比赛方案_XA-202603_智能体开发比赛.md`：比赛原始依据。
- `references/`、`_archive/`：外部参考和历史证据。
- `frontend/vendor/`：固定第三方依赖；升级必须说明版本、来源与兼容性。
- `backend/.env`：本地私密配置；不得读取后输出、提交或复制其中密钥。
- `backend/data/*.db*`、`*.sqlite`：运行数据；不得作为源码编辑或提交。
- `server.out.log`、`server.err.log`、`test-report.*`、`test-screenshots/`：生成产物，不手工维护。
- `.git/`：不得直接修改。

以下内容只在相关任务中修改：

- `workflows/current/*.yml`：修改后必须同步调试数据、输入输出契约和远程联调记录。
- `backend/data/knowledge_seed.py`：不得加入无来源 AI 内容；来源占位不能冒充已核实页码。
- `backend/data/diagnosis_bank.py`：修改答案或映射时必须补判题/归因测试。
- `backend/data/goal_graph.py`：修改节点 ID 或依赖前先检查历史数据兼容性。
- `frontend/index.html`：旧入口；新 Agent 页面需求默认修改 `frontend/agent.html`。
- 核心定稿文档：实现发生变化时才同步更新，不用文档改写代替代码实现。

工作区可能已有用户未提交修改。开始前必须运行 `git status --short`，不得覆盖、回退或格式化无关改动。

## 6. 修改前检查清单

1. 阅读本文件以及目标目录下更深层的 `AGENTS.md`（如以后新增）。
2. 运行 `git status --short`，识别用户已有改动和未跟踪文件。
3. 用 `rg` 找到真实入口、调用方、数据结构和测试；不要只依据旧文档推断。
4. 确认需求属于正式支持方向、试验支持方向还是通用咨询，避免伪造正式能力结论。
5. 区分用户数据、权威知识、AI 生成内容和系统推断，并确定各自能否写入画像。
6. 涉及目标/路径时检查能力图谱、前置依赖、版本和目标完成标准。
7. 涉及测评时检查题目来源、唯一答案、知识点映射、难度、审核状态和证据权重。
8. 涉及画像时检查每个数字能否追溯到真实事件，禁止固定样例冒充真实统计。
9. 涉及工作流时检查 `AGENT_USER_INPUT` 输入、结束节点 JSON、失败降级和本地解析器。
10. 涉及 API 时检查鉴权、CORS、错误码、幂等、SQLite 迁移和旧前端兼容性。
11. 涉及代码运行时检查超时、输出限制、文件隔离和命令注入风险；当前执行器仅是演示级沙箱。
12. 涉及联网内容时检查域名白名单、可核验 URL、来源展示和失败时诚实降级。
13. 涉及密钥时只使用环境变量；不得把真实 Key、Secret、Token 写入源码、测试数据或日志。
14. 明确最小改动范围和对应测试，再开始编辑。

## 7. 实现规则

- 优先修复根因，保持改动小而聚焦；不要顺手重构无关模块。
- 保留现有 API 和数据兼容性；确需破坏性变更时先增加迁移或兼容层。
- 所有正式能力结论必须可追溯到 `source_event_ids`、文档来源或版本化规则。
- AI 不负责最终判分，不得用模型自由文本直接更新掌握度。
- 网络/工作流失败必须返回明确降级状态，不得伪造搜索结果、来源或成功响应。
- 新方向按“目标标准、能力图谱、知识库、审核题库、实操 Rubric、错误模式”能力包接入。
- 不引入大型框架或新依赖，除非任务确实需要并说明维护、体积和安全成本。
- 修改数据库结构时使用幂等迁移，兼容已有 SQLite 数据。
- 修改前端交互时检查多项目独立会话、多标签、空工作区和项目折叠行为。
- 不创建重复工作流、重复调试数据或同功能平行实现。

## 8. 测试命令

### 快速检查

```powershell
python -m py_compile backend\server.py backend\domain.py backend\goal_engine.py
node --check frontend\app.js
node --check frontend\api.js
```

若修改 `frontend/agent.html` 中的内联脚本，还需通过浏览器测试验证；不要假定 `node --check` 已覆盖 HTML 内联代码。

### 后端定向测试

```powershell
python -m unittest backend.test_agent_projects
python -m unittest backend.test_learner_discovery
python -m unittest backend.test_backend
```

只改一个模块时先跑对应测试；修复测试失败时最多聚焦本任务相关问题，不处理无关失败。

### 后端完整测试

```powershell
python -m unittest discover -s backend -p "test_*.py"
```

### 浏览器回归

浏览器测试依赖 Playwright；只有环境已安装时运行：

```powershell
python test_browser.py
```

测试已启动的服务：

```powershell
python test_browser.py --base-url http://127.0.0.1:4173
```

### 本地启动与健康检查

```powershell
.\启动系统.ps1
Invoke-RestMethod http://127.0.0.1:4173/api/health
```

默认访问 `http://127.0.0.1:4173/`。测试远程星辰工作流前，先用 mock 完成本地回归；远程测试不得输出凭据。

## 9. 完成标准

- 改动与用户需求直接对应，没有破坏其他项目会话或既有数据。
- 相关定向测试通过；高风险改动再跑完整后端测试和浏览器回归。
- 页面控制台无新增错误，API 失败有用户可理解的反馈。
- 测评、路径、画像的结果可说明数据来源、知识来源和计算规则。
- 新生成内容有 AI 标识；引用可以追溯，缺少来源时明确提示。
- 不提交密钥、数据库、日志、截图和临时调试产物。
- 若无法验证某项能力，在交付说明中明确写出未验证范围，不将推测描述为事实。
