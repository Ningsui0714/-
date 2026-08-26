# 可视化插件/工具生态调研：智能体可视化 · 教育可视化 · AI 驱动可视化

> 调研日期：2026-08-08 ｜ 数据来源：GitHub Search API + 仓库 README（星数为当日实时值）

## 0. 全景图

```
智能体可视化 ── 实时编排可视化（调试直觉）→ agent-flow / mindwalk / Agentshire
            └─ 观测追踪平台（生产可观测）→ Langfuse / Opik / Phoenix / AgentOps / agentscope-studio
教育可视化   ── 数学动画 → manim 家族
            ├─ 算法可视化 → algorithm-visualizer / PathFinding.js
            ├─ 编程教学 → p5.js / Blockly / JSXGraph
            └─ ML 机制可视化 → transformer-explainer / llm-viz / netron
AI 驱动可视化 ── 文本→图表 → LIDA / Flint / WrenAI / Vanna
            ├─ 文本→动画/视频 → ManimCat / generative-manim / TheoremExplainAgent
            └─ 文本/草图→UI → screenshot-to-code / make-real
通用底座     ── 图: G6/cytoscape ｜ 节点编辑: React Flow/LogicFlow ｜ 图表: ECharts/D3 ｜ 白板: Excalidraw/tldraw
```

---

## 1. 智能体可视化（Agent Visualization）

### 1.1 运行过程实时可视化（把黑盒变白盒）

| 仓库 | ⭐ | 定位 | 技术栈 | 实现灵感 |
|---|---|---|---|---|
| **patoles/agent-flow** | 1,458 | Claude Code + Codex 实时编排可视化：看 agent 思考/分支/协作 | TypeScript；Claude Code hooks（HTTP server 零延迟流）+ Codex rollout JSONL tailing | 双运行时并存同屏；文件关注热力图；`npx agent-flow-app` 免 VS Code |
| **cosmtrek/mindwalk** | 1,151 | 在代码库「3D 夜光地图」上回放 coding-agent 会话 | Go 单二进制，全本地；读 Claude/Codex/pi 会话日志 | 「足迹即理解」——agent 搜索/读过哪里哪里发光；可选 analyze 模式用自己的 CLI 模型评估会话 |
| **Agentshire/Agentshire** | 1,266 | **OpenClaw/QClaw 插件**：把 agent 变成 3D 小镇里的 NPC，可观看/对话/捏人 | TypeScript；Town Mode（低模 3D）+ Chat Mode 双模式；UGC 地图编辑器+角色工坊 | 游戏化让 agent 状态「被看见」；双语文案（中/英）；注意版本兼容（推荐 2026.3.13） |
| Yuyz0112/claude-code-reverse | 2,413 | 可视化 Claude Code 的 LLM 交互 | JavaScript | 逆向分析事件流做可视化 |
| weiesky/cc-viewer | 1,058 | Claude Code 请求监控：捕获并可视化全部 API 请求/响应 | JavaScript | 请求级监控面板 |
| paulrobello/claude-office | 486 | 像素画办公室实时模拟 Claude Code 操作 | TypeScript | 像素风轻量可视化 |
| affaan-m/claude-swarm | 313 | 多 agent 编排 + 全量可视化 | Python | 编排与可视化一体 |
| 长尾（<10⭐）：vibisual（气泡图）、claude-village（Minecraft 风村庄）、pepeclaw（3D 房间）、caosmos-ui（React19+PixiJS8） | | 说明「游戏化可视化」正成为新趋势 | | |

### 1.2 Agent 观测/追踪平台（生产级）

| 仓库 | ⭐ | 定位 |
|---|---|---|
| **langfuse/langfuse** | 32,723 | LLM 观测 + eval + 指标 + prompt 管理 + playground（开源首选） |
| **comet-ml/opik** | 21,206 | LLM 应用/RAG/agentic 工作流调试、评估、监控一体化 |
| **Arize-ai/phoenix** | 10,939 | AI 可观测性与评估（trace 可视化 + 实验对比） |
| **AgentOps-AI/agentops** | 5,758 | Python SDK：agent 监控、LLM 成本追踪、benchmark |
| **agentscope-ai/agentscope**（原 modelscope） | 28,713 | 多 agent 框架，「Build and run agents you can see, understand and trust」；配套 **agentscope-studio**（629⭐，开发向可视化工具箱） |
| langchain-ai/langgraph | 39,175 | 图式 agent 运行时，配套 LangGraph Studio 桌面可视化 |
| crewAIInc/crewAI | 56,766 | 角色扮演多 agent 框架，配套可视化平台 |
| ag2ai/ag2（原 microsoft/autogen） | 4,839 | AgentOS；**dustland/agentok**（420⭐）= AG2 可视化拖拽搭建 |
| raga-ai-hub/RagaAI-Catalyst | 16,142 | agent AI 可观测/监控/eval SDK |
| katanemo/plano | 6,981 | Rust AI-native 代理：LLM 路由 + 可观测数据面 |
| pydantic/logfire | 4,416 | 生产 LLM/agent 系统 AI 可观测性 |
| lmnr-ai/lmnr | 3,152 | 专为 AI agent 打造的观测平台（YC S24） |
| wandb/weave | 1,113 | W&B 的 agent 开发工具包 |
| Repello-AI/Agent-Wiz | 385 | 威胁建模 + 可视化 LangGraph/AutoGen 等框架的 agent 图 |

### 1.3 研究向

- **EddyLuo1232/AgentLens**（8⭐）：论文 "AgentLens: Interpretable Safety Steering via Mechanistic Subspaces"
- **RobertTLange/agentlens**（36⭐）：coding-agent 会话的本地深度观测
- AgentLens 学术线（CHI 系）：LLM 自治系统的行为可视分析，是「agent 可视化」方向的开山论文之一

---

## 2. 教育可视化（Education Visualization）

### 2.1 数学动画引擎（manim 家族）

| 仓库 | ⭐ | 定位 | 技术栈/灵感 |
|---|---|---|---|
| **3b1b/manim** | 89,201 | 3Blue1Brown 数学动画引擎（原版） | Python；SVG/LaTeX 渲染；「数学可被看见」的标杆 |
| **ManimCommunity/manim** | 39,913 | 社区维护版，活跃开发 | Python；插件生态：manim-voiceover（311⭐ 配音）、manim-slides（909⭐ 现场演示）、manim-physics（402⭐）、awesome-manim（510⭐） |
| initialcommit-com/git-sim | 4,672 | 终端一条命令可视化模拟 git 操作 | Python + manim；教学 git 的杀手级场景 |
| helblazer811/ManimML | 3,469 | ML 概念动画（神经网络前向传播等） | Python + manim；ML 教学可视化 |
| AzurIce/ranim | 630 | Rust 版动画引擎，inspired by manim | Rust |
| cai-hust/manim-tutorial-CN | 1,231 | manim 中文入门教程 | 中文生态 |

### 2.2 算法/数据结构可视化

- **algorithm-visualizer/algorithm-visualizer**（48,659⭐）：代码驱动的交互算法可视化平台；tracers.js 可视化库 + server
- **qiao/PathFinding.js**（8,707⭐）：网格寻路算法可视化（Dijkstra/A*/BFS/DFS）
- TamimEhsan/AlgorithmVisualizer（447⭐）、LucasPilla/Sorting-Algorithms-Visualizer（453⭐）、H-SM/GraphPathGuru（17⭐）

### 2.3 编程/图形/硬件教学

- **processing/p5.js**（23,854⭐）：创意编程教学的事实标准（原 p5js org 已并入 processing org）
- **RaspberryPiFoundation/blockly**（google/blockly 已移交）：积木式可视化编程
- **jsxgraph/jsxgraph**（1,405⭐）：交互几何、函数绘图、图表，跨浏览器
- arm-education/Graphical-Micro-Architecture-Simulator（140⭐）：浏览器 CPU 单周期/流水线可视化（教育）
- Imperial-visualizations/Physics-Visualizations（19⭐）：帝国理工物理交互教学可视化

### 2.4 ML/LLM 内部机制可视化

| 仓库 | ⭐ | 定位 | 实现灵感 |
|---|---|---|---|
| **poloclub/transformer-explainer** | 8,366 | Transformer 交互式讲解（嵌入→注意力→前向传播逐步可点） | 交互即教学；单页可部署 |
| **lutzroeder/netron** | 33,323 | 神经网络模型结构可视化器（onnx/tf/pt 全支持） | 纯前端解析模型文件 |
| jessevig/bertviz | 8,149 | Attention 可视化（经典之作） | 注意力头矩阵热力图 |
| bbycroft/llm-viz | 5,485 | GPT 结构 3D 可视化；中文版 czhixin/llm-viz-cn（154⭐） | 3D 空间隐喻 |
| tensorspace-team/tensorspace | 5,194 | 神经网络 3D 可视化框架 | Three.js 3D 网络结构 |

---

## 3. AI 驱动可视化（NL → 图表/动画/UI）

### 3.1 文本 → 图表

| 仓库 | ⭐ | 定位 | 技术栈 | 实现灵感 |
|---|---|---|---|---|
| **microsoft/flint-chart** | 3,501 | **面向 AI 时代的可视化中间语言**：agent 用简洁 spec 产出精美图表 | TS；编译到 Vega-Lite/ECharts/Chart.js/Plotly/Excel；**flint-chart-mcp** MCP server；arXiv 2607.20775 | 70+ 语义类型（Rank/Temperature/Country…）+ 自动布局 + 视觉主题 → agent 不用调轴距/标签 |
| **microsoft/lida** | 3,271 | 自动生成可视化与 infographic，「可视化即代码」 | Python；语法无关（matplotlib/seaborn/altair/d3 都可） | 管线：summarize→goals→visualize→**edit→explain→evaluate→repair**（生成并执行代码，注意沙箱） |
| Canner/WrenAI | 17,183 | GenBI：面向 agent 的开源 text-to-SQL（上下文层 + 治理） | Python | 语义层解决「agent 乱猜 schema」 |
| vanna-ai/vanna | 23,822 | 用 LLM 对话 SQL 数据库，agentic RAG 生成 SQL + 图表 | Python | Text-to-SQL + 可视化一体 |
| whoiskatrin/chart-gpt | 3,582 | 文本输入直接建图表 | TypeScript | 单功能做到极致 |
| **markdown-viewer/skills** | 3,115 | 让 AI coding agent 直接在 Markdown 里产出精美图表/图表的 skills | skills 包 | 「产物即 markdown」——零工具链 |
| larashero3-dotcom/lieflat-charts | 703 | 面向 AI agent 的数据可视化 skill，输出交互 HTML 图表 | HTML | 单文件交付 |
| Zafer-Liu/Data-Analysis-Agent | 2,414 | 中文对话式数据分析助手：聊天→自动报表+洞察 | JavaScript | 中文 BI 场景 |
| zhongyu09/openchatbi | 617 | LLM 驱动的 chat BI | Python | 国产 chatBI |
| modem-dev/sideshow | 490 | agent 的「视觉面板」：UI mockup / 数据可视化 / 代码讲解 | TypeScript | 给 agent 补一个视觉输出面 |
| JetBrains/databao-agent | 142 | 对话数据 agent（JetBrains 出品） | Python | 大厂入场 |

### 3.2 文本 → 动画/视频/演示

| 仓库 | ⭐ | 定位 | 实现灵感 |
|---|---|---|---|
| **TIGER-AI-Lab/TheoremExplainAgent** | 1,502 | LLM 自动生成定理讲解长视频（Manim）；ACL 2025 Oral，arXiv 2502.19400 | 多阶段 agent 管线（规划→代码→执行→修复）；「视频暴露纯文本掩盖的推理缺陷」 |
| marcelo-earth/generative-manim | 903 | GPT 驱动 manim 视频生成 | 文生动画工作流 |
| **Wing900/ManimCat** | 425 | 自然语言→高质量数学动画（双模式：直接生成 + agent 工作室） | React 19 + ManimCE；中文 README |
| jeertmans/manim-slides | 909 | manim 现场演示（演讲场景） | 动画+演讲合一 |

### 3.3 文本/草图 → UI

- **abi/screenshot-to-code**（73,887⭐）：截图 → HTML/Tailwind/React/Vue 代码
- **tldraw/make-real**（5,434⭐）：手绘 UI 草稿 → 真实界面
- **tldraw/tldraw**（49,659⭐）：infinite canvas SDK（"agent recommended #1"），是 make-real 的底座

---

## 4. 通用可视化底座（选型参考）

| 类别 | 仓库（⭐） |
|---|---|
| 图/关系 | antvis/G6（12,225）、cytoscape.js（11,145）、vis-network（3,612）、antvis/Graphin（1,098，React） |
| 节点/流程编辑 | **xyflow/xyflow = React Flow**（37,954，LearnFlow 在用）、didi/LogicFlow（11,623，脑图/ER/UML/工作流） |
| 图表 | d3（113,402）、apache/echarts（67,003）、observablehq/plot（5,345） |
| BI | apache/superset（74,179）、metabase（48,601）、dataease（24,303，国产中文 BI） |
| 图表达/白板 | mermaid（89,637）、excalidraw（129,150） |
| 应用壳 | streamlit（45,513）、gradio（43,313）、reflex（28,792）、plotly/dash（24,367） |
| 2D 渲染 | pixijs（47,976） |

---

## 5. 横向洞察

1. **agent 可视化分三层**：实时编排可视化（agent-flow，练调试直觉）／观测平台（Langfuse/Opik，生产可观测）／会话回放（mindwalk，复盘理解）——三层解决不同问题
2. **「3D 化/游戏化」是 2026 agent 可视化新趋势**：Agentshire 小镇、mindwalk 夜光地图、claude-village 像素村、pepeclaw 3D 房间——把 agent 状态变成「可居住的空间」
3. **AI 驱动可视化已分化出「图表语言」路线**：Flint（中间语言 + MCP，agent 可靠出图）vs LIDA（可视化即代码，生成+执行+修复闭环）vs skills 路线（markdown-viewer/skills、lieflat-charts，产物即文件）
4. **教育方向 manim 系仍是王者**（原版+社区合计 13 万星），AI 化入口 = ManimCat / generative-manim / TheoremExplainAgent（自然语言→动画）
5. **通用底座选型口诀**：图→G6/cytoscape；节点编辑→React Flow/LogicFlow；图表→ECharts/D3；快速 app→Streamlit/Gradio；白板→Excalidraw/tldraw
6. **中文生态已入场**：Data-Analysis-Agent、openchatbi、dataease、llm-viz-cn、manim-tutorial-CN、Agentshire（中英双语）

---

## 6. 对 Ryan 的启示

- **LearnFlow 直接可抄**：React Flow 已有；AI 生成讲义配图可借鉴 Flint 的「语义类型+主题」思路；学习过程可视化可借鉴 agent-flow 的时间线+文件热力图
- **OpenClaw 现成玩具**：Agentshire 是 OpenClaw 插件（注意版本兼容）；`npx agent-flow-app` 可立即可视化你自己的 agent 会话
- **教育×AI 交叉机会**：他的学习文章可配 transformer-explainer 式交互图、ManimCat 生成数学动画——「AI 学习路径可视化」是个可做的小工具方向
- **读源码优先级**：agent-flow（TS 结构清晰）、LIDA（Python 管线完整）、flint-chart（MCP 集成范例）
