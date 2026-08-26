# Graphify 生态调研报告

> 调研日期：2026-08-08 ｜ 数据来源：GitHub Search API + 各仓库 README
> 一句话定位：**Graphify 家族 = 「把任意文件夹（代码/文档/PDF/图片/视频）变成可查询知识图谱」的 AI 编程助手技能 + CLI 生态。**
> 起源：Andrej Karpathy 的 LLM Wiki 想法（gist）与 "/raw 文件夹工作流"推文 → Safi Shamsi 实现 graphify（safishamsi/graphify 已 Moved Permanently 至 Graphify-Labs）→ 公司化 Graphify Labs（YC S26），云平台 graphify.com。

---

## 1. 旗舰：Graphify-Labs/graphify（Python，104,059 ⭐）

**针对场景**
- AI 编程助手（Claude Code / Cursor / Codex / Gemini CLI / OpenCode / OpenClaw / Factory Droid）会话中的代码库理解
- 解决两大痛点：每次新会话重新读文件烧 token（宣称 71.5x token 节省）；跨会话失忆
- 让助手「查询图谱」而不是「grep 文件」

**架构（六步管线）**
```
detect → extract → build → cluster → analyze → export
```
- **双通道提取**：
  - Pass 1：tree-sitter AST 解析（21+ 语言）——确定性、免费、全本地、无 LLM
  - Pass 2：LLM 语义通道（docs/PDF/图片/视频），用助手模型或配置的 API key
- **边置信度标签**：EXTRACTED（源码显式）/ INFERRED（图谱推断）/ AMBIGUOUS——事实与猜测永远可区分
- **社区发现**：Leiden 算法（v8 之前的版本用 Louvain）
- **图分析**：God Nodes（枢纽概念）+ Surprising Connections（复合分数排序，代码-论文边权重高于代码-代码）
- **关键设计声明**：不是向量索引！无 embedding、无向量库，是真正的图遍历

**输出产物（graphify-out/）**
```
graph.html      力导向交互图（点击/搜索/按社区过滤）
GRAPH_REPORT.md 关键概念、意外连接、建议问题
graph.json      持久化图谱（数周后可查询，不再读源文件）
cache/          SHA256 增量缓存
```

**技术栈**：Python 3.10+，tree-sitter，PyPI 包名 `graphifyy`；安装 `uv tool install graphifyy` / `pip install graphifyy`；`graphify install` 注册到各助手平台（`--platform codex|claw|opencode|droid`）

**常用命令**：`/graphify .` ｜ `--mode deep`（激进推断边）｜ `--update`（增量）｜ `--cluster-only` ｜ `add <arXiv/推文URL>`（外部资源入图）｜ `query "..." [--dfs] [--budget N]` ｜ `path A B`

**实现灵感**
1. 免费确定性通道（AST）打底 + 按需付费通道（LLM）增强——成本与质量解耦
2. 边标签化建立「可审计信任」，这是它区别于普通 RAG 的核心卖点
3. 产物是三份文件而非一个服务——低侵入、可移植、易被二次开发
4. 社区发现制造「跨文档意外连接」的惊喜感，是传播点
5. 开源 CLI 引流 + graphify.com 云平台（always-on 后台增量）变现的双轨商业模式

---

## 2. 移植版家族（同管线，换语言实现）

### TtTRz/graphify-rs（Rust，58 ⭐）
- **场景**：对性能/资源敏感的环境（CI、大仓库、边缘设备）
- **架构**：与 Python 版同构（detect→extract→build→cluster→analyze→export），输出 `~/.graphify-rs/<name>-<hash>/`
- **技术栈**：Rust 1.85+，11 个原生 tree-sitter + regex 回退，Leiden（带 refinement），rayon 并行提取，内置 MCP server（16 tools，JSON-RPC 2.0），9 种导出格式（含 Obsidian vault、split HTML）
- **对比数据**：速度 ~24ms vs Python ~204ms（8.5x）；内存 ~1MB vs ~48MB（48x）
- **灵感**：用性能数字做营销；MCP server 让图谱可被任意 agent 工具调用

### elbruno/graphify-dotnet（C# / .NET 10，91 ⭐）
- **场景**：.NET 技术栈用户（微软生态）
- **架构**：同管线；AI provider 可插拔——Azure OpenAI / Ollama / GitHub Copilot SDK / None（纯 AST 零配置可用）
- **技术栈**：dotnet global tool（`dotnet tool install -g graphify-dotnet`）；NuGet 拆包：`graphify-dotnet`（CLI）+ `graphify-dotnet-core`（核心库）；18 种代码语言 + YAML/JSON/TOML/XML + PDF/图片
- **灵感**：`graphify config` 交互式向导降低上手门槛；「无 AI provider 也能用」的降级设计

### sjhorn/graphify（Go，9 ⭐）
- **场景**：Go 生态；需要缓存友好的增量分析
- **架构**：同管线；Louvain（gonum 图算法库）
- **技术栈**：Go + go-tree-sitter，24 种语言；输出 graph.json / graph.html / GRAPH_REPORT.md
- **特色**：SHA256 每文件缓存（Markdown 只 hash 正文，frontmatter 变更不失效）；`graphify claude` / `graphify agents` 一键把提示词写进 CLAUDE.md / AGENTS.md
- **灵感**：「把 skill 提示词注入 AGENTS.md/CLAUDE.md」是让 agent 生态自动采纳的巧招

---

## 3. 生态集成与应用层

| 仓库 | ⭐ | 定位 | 技术栈 | 实现灵感 |
|---|---|---|---|---|
| lucasrosati/claude-code-memory-setup | 921 | Obsidian Zettelkasten（声明式记忆）+ Graphify（结构地图）+ 聊天导入管线的完整方案；单 vault 跨项目；/resume /save 命令 | Python + Obsidian + Claude Code hooks | 「记忆分层」：什么被决定 vs 代码怎么组织，各司其职 |
| HKUST-KnowComp/DeepRefine-Skill | 89 | `/deeprefine` 命令在 test time 演化/精炼 LLM-Wiki（graphify）知识库，提升后续检索与 Q&A 质量；有 arXiv 论文（2605.10488） | Python，PyPI deeprefine-cli | 把「知识库维护」本身做成一个 agent 循环技能 |
| Anshler/graphify-novel | 55 | 小说写作助手：premise → story bible；章节→人物/地点/事件/主题知识图谱；矛盾检测、未闭合伏笔追踪；`--from-chapters` 分批 subagent 导入 | skills CLI（`npx skills add`），复用 graphify 内核 | 同一内核垂直化到创作领域；「写，别记账」的体验定位 |
| rhanka/graphify | 16 | 从代码图泛化到**本体驱动实体图**：实体消歧/归一（「Holmes」「Mr. Sherlock Holmes」合并为 canonical entity + aliases + provenance）、可配置 ontology 类型 + visual_encoding（形状/颜色）、关系端点校验 | TypeScript；旗舰语料：25 部福尔摩斯公版作品 → 1,193 实体 / 19 类型 / 99 社区 | 实体归一 + 本体类型化解决「同名不同物」；在线 studio 展示 |
| Rootly-AI-Labs/rootly-graphify-importer | 42 | 事件/告警/团队/服务目录 → 知识图谱：服务热力图、on-call 单点故障、告警→事故漏斗 | Python（`pip install "graphifyy[rootly]"`） | 数据管道（API 拉取→语料→图）与语义分析（--mode deep）分离 |
| sly-codechum/chum-mem | 39 | PCKC（Proof-Carrying Knowledge Compiler）：记忆单元=原子 Claim（fact/decision/task/constraint/bug/fix…），每条带 Proof（authority_class + verification_status + source_ref + excerpt）；belief gate 只收 tool_verified/user_confirmed/repository_derived/test_verified；矛盾引擎 + supersession 引擎；token 预算内编译最小证明集 | Rust；两层隔离图（结构层 + 声明层）；Leiden | 「模型生成的 prose 不算记忆」的信念门；claim 级版本控制 |
| gaodes/pi-graphify | 9 | Pi 扩展包装 graphify CLI | TypeScript | 把 CLI 包装成宿主平台的 extension |
| yetanotheraryan/graphify-chokidar | 6 | chokidar 文件监听 + 增量重建，图谱保持新鲜且不烧 token | TypeScript | 增量是刚需，watch 模式补全闭环 |
| grandamenium/understand-open-source | 28 | 工作流：opensrc 下载真实源码 → graphify 建图 → 阅读 | Python | 复读开源项目的标准化姿势 |
| JakeB-5/vela-union | 8 | 本地编排平台，统一 Paperclip / gstack / Graphify / PageIndex / gbrain 五个 OSS | TypeScript | 「编排层」思路：不重造轮子，统一入口 |
| roccodaffuso/brain-bar | 16 | macOS 菜单栏控制 Obsidian + Graphify vault 工作流 | JavaScript | 桌面集成让 CLI 工具「一直在场」 |
| CreatmanCEO/ai-context-hierarchy | 10 | 三级上下文层级，featured in Graphify v5.0 roadmap | Python | 与官方路线图联动做生态卡位 |
| franklywatson/claude-rig | 9 | Claude Code 栈 cockpit，检测 rtk / jcodemunch / graphify / Headroom / superpowers | TypeScript | 生态健康检查工具 |
| tijuthomas5/context-bridge-mcp | 3 | 基于 Graphify 索引的混合关键词+向量检索 MCP server | Python | 图谱 + 向量混合检索是 MCP 时代的标配 |

### 中文文档
- **chencore/graphify-knowledge-graph-docs**（27 ⭐）：完整中文安装/使用文档，明确支持 OpenClaw（`graphify install --platform claw`），覆盖 deep/update/cluster-only/add/query/path 全命令。

---

## 4. 竞品 / 替代方案

### crabbuild/compass（Rust，115 ⭐）
- **场景**：local-first 代码知识图谱引擎，强调「放在日常循环里」——`compass init` / `compass install` / `compass watch`
- **能力**：CompassQL 精确查询、Git 历史图 diff（对比不同版本架构）、VS Code 一官方扩展（右键函数看 callers/callees/impact/path）
- **灵感**：Graphify 是「一次性建图」，Compass 是「常驻同步 + 编辑器内体验」——watch 模式 + IDE 集成是差异化点

### grisuno/ReadMenator（6 ⭐）
- **场景**：完全离线、零 token 的代码知识图谱与架构健康分析（纯静态分析，无 LLM）
- **对比**：graphify 用 LLM 提取 vs readmenator 用 AST+regex 免费；4 种边类型（imports/calls/inherits/resolved_imports）；5 层架构检测；label propagation 社区发现；导出 JSON/HTML/SVG/GraphML/Obsidian，graph.json 标榜 GraphRAG-ready
- **灵感**：「免费版图」直接对标付费通道；架构分层检测（5 层）是差异化功能

### 其他
- CarlosVallejoRuiz/slurp（40 ⭐）：token 预算感知的图导航，给 LLM 只投喂需要的部分
- thewaifucorp/above-all-graphs（3 ⭐）：AAG Protocol 知识图谱工具

---

## 5. 无关同名项目（避坑）

| 仓库 | ⭐ | 说明 |
|---|---|---|
| kbastani/graphify | 445 | 2015 年 Neo4j 无管理扩展，图基文档/文本分类，与现 Graphify 无关 |
| warioddly/graphify | 96 | Dart 写的基于 Apache ECharts 的数据可视化图表库 |
| raufer/graphify | 96 | Python 非结构化文本→图解析库，概念相近但独立项目 |
| greim/json-graphify | 13 | JSON → Falcor JSON graph 转换 |

---

## 6. 横向观察：值得偷的设计

1. **双通道提取**：确定性免费（AST）+ 语义付费（LLM）分层，成本质量解耦
2. **边置信度标签**（EXTRACTED/INFERRED/AMBIGUOUS）：可审计性 = 信任 = 卖点
3. **产物文件化**（html/json/md）而非服务化：低侵入、易集成、生态可二次开发
4. **社区发现制造惊喜**：Leiden/Louvain 是「意外连接」的来源，也是演示效果最好的部分
5. **生态扩散打法**：一个 CLI + 全平台 skill 注册（含 OpenClaw `--platform claw`）
6. **增量 + 缓存是刚需**：SHA256 缓存、watch 模式、chokidar 监听都是围绕 token 经济
7. **垂直化**：novel（写作）/ rootly（事故）/ ontology（实体图谱）——同一内核换场景就是新产品
8. **商业化**：开源 CLI 引流 + 云平台（graphify.com always-on）收费的双轨

---

## 7. 对 Ryan 的启示

- **OpenClaw 可直接用**：`pip install graphifyy && graphify install --platform claw`，把 LearnFlow / d2l 笔记仓库建图试试
- **LearnFlow 借鉴**：graphify 的产物文件模式（html+json+md）、双通道提取、边标签、增量缓存，与 LearnFlow 的讲义/知识图谱方向高度相关，可对比参考
- **个人知识库**：配合 Obsidian（claude-code-memory-setup 方案）可以做「跨会话记忆」——正好补 OpenClaw/编程助手的上下文短板
- **读源码入口**：graphify-rs（Rust 精简版）比 Python 主仓库更容易通读全管线
