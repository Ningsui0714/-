# LearnFlow — 项目规划书

> AI 驱动的自适应学习平台
> 版本：v0.1 (MVP)
> 创建日期：2026-07-30

---

## 1. 项目概述

### 1.1 愿景

让学习任何复杂知识像玩游戏闯关一样自然。学生指定一个学习主题并提供参考来源，AI 协助规划学习路线，每关自动生成讲义和练习，过程中可自由追问。

### 1.2 核心能力矩阵

| 模块 | 能力 |
|------|------|
| **来源管理** | 接受 GitHub repo、网页 URL、本地文档等来源，自动切片并编号 |
| **学习路线 Agent** | 对话式交互 → 生成闯关图路线，分配每个关卡的参考切片 |
| **闯关图** | 可视化进度（未解锁 / 进行中 / 已完成），支持路线编辑并继承进度 |
| **讲义生成 Agent** | Chunk + 大模型 + 联网搜索 → 生成分段式结构化讲义 |
| **讲义追问** | 选中文本 → 底部工作区提问，不覆盖主讲义 |
| **IDE 训练** | 内嵌 Monaco Editor，提供半完成代码，支持选中代码提问 / 审阅 |

### 1.3 技术栈

```
后端：  FastAPI (Python 3.11+) + SQLAlchemy + SQLite
前端：  React 18 + TypeScript + Vite + TailwindCSS
公式：  KaTeX
代码：  Monaco Editor (VS Code)
图流：  React Flow (闯关图)
AI：    LangChain + 任意 OpenAI 兼容 API
切片：  LangChain RecursiveCharacterTextSplitter
```

> **为什么选分离架构？**
> FastAPI 做 AI 编排（Python 生态无替代品），React 做复杂交互 UI（Monaco Editor / KaTeX / React Flow 都是 React 生态原生支持），两者通过 REST + SSE 通信。

---

## 2. 开发阶段

### Phase 0 — 项目骨架（预计 1-2 天）

**目标**：搭建前后端基础骨架，跑通数据流。

- [ ] 后端：FastAPI 应用 + 路由结构 + SQLAlchemy 模型 + SQLite
- [ ] 前端：React + Vite + 路由配置 + TailwindCSS + API 客户端
- [ ] 基础布局：侧边栏 + 主内容区
- [ ] Docker Compose (可选，本地同时跑前后端方便)
- [ ] CORS 配置，前后端联调

**产出**：`/api/health` 返回 200，前端首页显示 "LearnFlow"。

---

### Phase 1 — 来源管理 + 学习路线（预计 3-4 天）

**目标**：能创建学习项目，添加来源，自动切片，通过对话生成闯关图。

#### 1.1 来源管理

- **模型**：
  - `Project`: id, name, description, created_at
  - `Source`: id, project_id, type (github|url|file), url/path, status (pending|processed|failed)
  - `Chunk`: id, source_id, index, content, token_count, metadata
- **后端逻辑**：
  - 添加来源 → 后台拉取/读取 → RecursiveCharacterTextSplitter 切片 → 存储
  - GitHub 支持：`git clone` 仓库（或 GitHub API 拉取 README/关键文件）
  - 网页支持：`requests` + `BeautifulSoup` / `trafilatura` 提取正文
- **前端页面**：
  - 新建项目页（名称 + 描述 + 添加来源列表）
  - 来源列表展示（类型图标 + 状态 badge）
  - 切片预览（可展开查看切片内容编号）

#### 1.2 学习路线 Agent

- **核心 Prompt**：
  > 用户定义了学习主题 {topic}，参考来源已被切片为 {chunks}。
  > 请与用户对话，了解其基础水平、学习目标、时间预期。
  > 最终输出一个 JSON 格式的学习路线，包含若干关卡，每关必须有：
  > - id, title, description, order
  > - assigned_chunk_ids: 该关对应的切片 ID 列表
  > - prerequisites: 前置关卡 ID 列表
  - 使用 LangChain 构建 Agent 循环（带记忆的对话窗口）
  - 第一轮为用户根据主题和来源主动给出初始路线草案
  - 用户可反驳、调整、增减
  - 最终确认后生成闯关图 JSON 并存入数据库
- **前端页面**：
  - 对话界面对话框 (Chat-like UI)
  - 确认按钮 → 跳转到闯关图页面
- **模型**：LearnFlow 查表 `Project.chunk` + `Project.roadmap`

#### 1.3 闯关图

- `react-flow` 渲染 DAG（有向无环图）
- 节点样式 = 卡片（标题 + 简短描述 + chunk 数量 + 学习状态 badge）
- 连线方向 = 先修关系（prerequisites → current）
- 交互：
  - 点击节点 → 进入该关（跳转到 Phase 2 讲义页）
  - 右键/编辑按钮 → 修改路线（回到路线 Agent 对话界面，传入已有路线）
- 路线修改：
  - 点「修改路线」→ 打开与路线 Agent 的新对话
  - Agent 已有关卡进度标记，用户可增删改关卡
  - 确认后更新闯关图（已完成关卡不可删除，但可插入新关）

---

### Phase 2 — 讲义生成 + 底部工作区（预计 4-5 天）

**目标**：进入某一关后，AI 生成结构化讲义，支持选中追问。

#### 2.1 讲义生成 Agent

- **核心 Prompt（分两步）**：

  **Step 1 — 规划**：
  > 主题：{checkpoint.title}
  > 参考切片：{assigned_chunks}
  > 学生水平：{user_level}
  > 请规划讲义的结构，给出章节大纲，每章的目标和关键词。

  **Step 2 — 逐节生成**（流式 SSE，逐章节渲染到前端）：
  > 按照大纲逐节生成讲义内容。要求：
  > - 每节以标题开头
  > - 关键概念用 **加粗** 或公式 `$$L(θ) = Σ(y - ŷ)²$$`
  > - 公式使用 KaTeX 语法
  > - 复杂结构用 ASCII 图示意，例如：
  >   ```
  >       输入层    隐藏层    输出层
  >      x₁ → ○ → ○ → ŷ
  >      x₂ → ○ → ○
  >   ```
  > - 每节结尾有 1-2 个自查问题
  > - 引用切片时标注 `[chunk-012]`

- **联网搜索增强**：Agent 可调用 `web_search` 获取最新博客/论文/示例
- **前端**：流式渲染（打字机效果，使用 SSE 或 WebSocket）
- **公式渲染**：插入 KaTeX，`renderMathInElement` 自动扫描

#### 2.2 讲义交互

- 鼠标选中讲义中的文本 → 弹出浮动工具条「追问 selected_text」
- 点击「追问」→ 底部工作区出现：
  - 上半部分：被选中文本的引用（引用块样式）
  - 下半部分：输入框 + 发送按钮
  - 下面是对话历史（与追问 Agent 的上下文）
- **追问 Agent**：
  - 上下文 = 被选中的文本 + 该关卡的 chunks + 之前的追问历史
  - 专注解释被选中内容，可引述公式、扩展例子
  - 不覆盖主讲义内容

---

### Phase 3 — IDE 训练模块（预计 4-5 天）

**目标**：每关配套代码练习，内嵌编辑器 + 代码工作区。

#### 3.1 IDE 页面布局

```
┌──────────────────────────────────────────────┐
│  题目描述（Markdown 渲染）                    │
│  提示：完成下面代码中的 TODO 部分              │
├─────────────────────┬────────────────────────┤
│  代码编辑器          │  (右侧/底部) 输出面板  │
│  (Monaco Editor)    │  stdout / stderr       │
│                     │  test results          │
│  ┌───────────────┐  │                        │
│  │  def train(   │  │                        │
│  │    model, ... │  │                        │
│  │  ):           │  │                        │
│  │    # TODO     │  │                        │
│  └───────────────┘  │                        │
├─────────────────────┴────────────────────────┤
│  底部代码工作区                                │
│  [选中代码提问] [检查代码]                     │
│  Agent 的回复/建议在这里                       │
└──────────────────────────────────────────────┘
```

#### 3.2 代码题目来源

- 来自关卡 chunks 中的示例代码片段
- 来自讲义生成 Agent 在生成时自动产出的练习建议
- 手动补充的题目（题库表）

**题目数据结构**：
```json
{
  "id": "ex-001",
  "checkpoint_id": "cp-03",
  "title": "实现一次梯度下降迭代",
  "description": "根据讲义中的公式，完成 ...",
  "starter_code": "def gradient_descent(...):\n    # TODO: ...",
  "solution": "...",
  "test_cases": [
    {"input": "...", "expected": "..."}
  ],
  "hints": ["先写出损失函数", "再求偏导"]
}
```

#### 3.3 代码执行

- **本地执行**（MVP）：Python 沙箱执行（`subprocess` 限制资源）
- 或前端 Pyodide（浏览器内 Python，但库支持有限）
- **输出捕获**：stdout + stderr → 输出面板

> ⚠️ MVP 阶段建议本地执行，Python 脚本在 sandbox 中运行（限制 CPU 时间、内存、磁盘写入）。

#### 3.4 代码审阅 Agent

- **选中代码提问**：选中编辑器中某段代码 → 底部工作区出现，追问 Agent 解释这段代码
- **检查代码**：发送当前编辑器全部内容给 Agent，返回：
  - 是否符合要求
  - 性能问题
  - 风格问题
  - 改进建议（带代码片段）
  - **不直接给出完整答案**（学习目的）

---

## 3. 数据模型（ER 概要）

```
Project
├── id, name, description, user_level, created_at
├── Source (1:N)
│   └── id, type, url/path, status
├── Chunk (1:N via Source)
│   └── id, source_id, index, content, tokens, metadata
├── Roadmap (1:1)
│   └── id, raw_json (路线图的完整 JSON 结构)
└── Checkpoint (1:N via Roadmap)
    ├── id, roadmap_id, title, description, order
    ├── assigned_chunks (M:N with Chunk)
    ├── completed (boolean)
    └── Lecture
        └── id, sections (JSON, 存储生成的章节内容)
        └── Exercises (1:N)
            └── id, title, description, starter_code, solution, tests
```

---

## 4. API 设计（概览）

```
POST   /api/projects                   创建项目
GET    /api/projects                   项目列表
GET    /api/projects/:id               项目详情

POST   /api/projects/:id/sources       添加来源
GET    /api/projects/:id/sources       来源列表
GET    /api/projects/:id/chunks        查看切片

POST   /api/projects/:id/roadmap       启动路线 Agent 对话
POST   /api/projects/:id/roadmap/msg   发送对话消息
GET    /api/projects/:id/roadmap       获取已确认的路线图

GET    /api/checkpoints/:id            关卡详情

POST   /api/checkpoints/:id/lecture    触发讲义生成 (SSE)
GET    /api/checkpoints/:id/lecture    获取已生成的讲义

POST   /api/checkpoints/:id/ask        追问 (讲义选中文本)
       Body: { selection, question, history }

GET    /api/checkpoints/:id/exercises  获取练习题列表
POST   /api/exercises/:id/run          运行代码
       Body: { code }
POST   /api/exercises/:id/review       代码审阅
       Body: { code, selection? }
POST   /api/exercises/:id/ask          选中代码提问
       Body: { selection, question }
```

---

## 5. 关键设计决策

### 5.1 公式渲染

- 后端 Agent 输出 **KaTeX 格式**公式 (`$inline$` / `$$block$$`)
- 前端用 KaTeX 库实时渲染
- 讲义存储为 Markdown 格式，含 KaTeX 块

### 5.2 流式讲义生成

- 使用 Server-Sent Events (SSE) 将讲义逐段推送给前端
- 前端逐节渲染，用户看到"打字机效果"
- 每节生成完毕自动触发 KaTeX 重新渲染

### 5.3 切片策略

- 默认：RecursiveCharacterTextSplitter (chunk_size=2000, chunk_overlap=200)
- 支持按 Markdown 标题层级分割（更语义化）
- 每个切片记录来源、索引、token 数

### 5.4 Agent 可替换性

- 所有 Agent 调用通过统一的 `LLMService` 抽象层
- 默认支持 OpenAI / DeepSeek / Anthropic 等兼容 API
- 通过 `.env` 配置模型、API Key、Base URL

### 5.5 安全与本地优先

- 所有数据本地 SQLite 存储
- 不在外部存储用户数据
- API Key 仅存于 `.env`，不提交 Git
- 代码执行沙箱化（限制资源）

---

## 6. 开发顺序

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3
  骨架        来源+路线       讲义+追问      IDE训练
  1-2天        3-4天          4-5天         4-5天

         ←─── 每个 Phase 都有可展示产出 ──→
         总 MVP 预估：12-16 天
```

每个 Phase 结束时：
- 功能可用（即使粗糙）
- 前后端联调通过
- Ryan 可以上手试用并反馈

---

## 7. 非目标（MVP 不做的）

- ❌ 用户注册/登录系统
- ❌ 多人协作
- ❌ 课程市场 / 公开分享
- ❌ 复杂权限管理
- ❌ 视频/音频支持
- ❌ 移动端适配（优先桌面端）
- ❌ PWA
- ❌ Docker 镜像发布

---

## 8. 启动方式（Phase 0 完成后）

```bash
# 后端
cd LearnFlow/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd LearnFlow/frontend
npm install
npm run dev  # 默认 :5173
```

---

> 本规划书为指导文档，随开发迭代可调整。目标是保持进度可见、产出可用。
