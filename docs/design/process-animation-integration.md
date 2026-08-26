# LearnFlow × process-animator 集成设计稿

> 日期：2026-08-08 ｜ 状态：草稿，待 Ryan 确认后再动工
> 背景：process-animator skill（workspace/skills/process-animator）已跑通「过程文本 → 可交互分步演示」。本文评估其与 LearnFlow 的集成方案。

## 0. 结论

可行。LearnFlow 的讲义管线、工作台、闯关图三处都有天然挂载点。MVP 只做 interactive 模式（JSON + React 组件），manim 视频模式不集成（需服务端 manim/ffmpeg，重）。

## 1. 数据模型（新增）

```python
class ProcessAnimation(Base):
    __tablename__ = "process_animations"
    id: int
    project_id: FK
    title: str
    subtitle: str = ""
    legend: JSON = []            # [[color, label], ...]
    steps: JSON = []             # [{title, text, bars?, svg?}, ...]
    source: str = "manual"       # manual | lecture | checkpoint
    ref_id: int = None           # lecture_id / checkpoint_id / chunk_id
    meta_data: JSON = {}
    created_at: DateTime
```

- `steps` 的 pydantic 校验：`title: str`, `text: str`, `bars: {values: list[number], highlight/pivot/sorted/done: list[int]}`（可选）, `svg: str`（可选，需消毒）
- 版本化：跟着 lecture_versions 走（动画 JSON 作为 lecture 内容的一部分快照），不单独做版本表

## 2. 后端

### 2.1 新服务 `services/animation_agent.py`
- `extract_steps(text) -> {title, subtitle, legend?, steps[]}`：LLM 一次调用，prompt 复用 process-animator SKILL.md 的步骤提取规范（6–15 步、每步状态快照、bars/svg 二选一）
- `validate(data) -> ProcessAnimation`：pydantic 校验 + svg 白名单过滤（DOMPurify 由前端做，后端限制长度与标签集合）
- `quick_action(selected_text, ...)`：T9 工作台动作入口

### 2.2 新 API
```
POST /api/animations/generate   {text, source?, ref_id?}  -> ProcessAnimation
GET  /api/animations/{id}
GET  /api/animations?project_id=&ref_type=&ref_id=
DELETE /api/animations/{id}
```

### 2.3 lecture_agent 集成（阶段 2）
- generate_section 之后：用轻量正则/关键词检测「过程型内容」（算法/流程/步骤/传导/遍历…），命中则并行调 extract_steps
- 讲义 markdown 里插入占位标记：`:::process-anim {animation_id}`（块级），LectureRenderer 解析后渲染组件
- 失败降级：动画生成失败不影响讲义落库（try/except，标记 meta_data.anim_error）

## 3. 前端

### 3.1 新组件 `components/animation/ProcessAnimationViewer.tsx`
- 从 interactive-template.html port：状态机（idx/timer）、控制条（上一步/播放/下一步/scrub/计数）、bars 渲染（SVG rect + 颜色语义）、svg 注入（**DOMPurify 消毒后**）、legend、键盘 ←→/空格
- 样式对齐 LearnFlow 主题（CSS variables），非模板的独立样式

### 3.2 挂载点
- **LectureRenderer**：识别 `:::process-anim {id}` → 内嵌 `<ProcessAnimationViewer animation={...} />`
- **BottomWorkspace 快捷动作**：「生成过程动画」→ 选中文本 → POST generate → 弹窗展示 → 可保存（锚定到 chunk/lecture）
- **CheckpointGraph 节点详情**：checkpoint 关联的动画列表（阶段 3，可选）

## 4. 安全

- svg 注入是 XSS 向量：前端 DOMPurify（allowlist: svg/g/circle/rect/line/path/text/polygon/marker/defs + 常见属性）——必做
- 后端限制 steps 数量（≤30）、svg 长度（≤64KB）、bars.values 长度（≤64）
- LLM 输出永远不可信，pydantic 校验兜底

## 5. 工作量（MVP）

| 项 | 估时 |
|---|---|
| 模型 + 迁移 + animation_agent + API | 0.5–1 天 |
| ProcessAnimationViewer 组件 + DOMPurify | 0.5–1 天 |
| 工作台快捷动作闭环 | 0.5 天 |
| LectureRenderer 标记解析 + lecture_agent 集成 | 1 天 |
| 闯关图挂载（可选） | 0.5 天 |

## 6. 建议路径

1. **先做最小闭环**（工作台动作）：选中「快速排序的过程…」→ 生成 → 弹窗可交互 → 体验价值立现，不碰讲义管线
2. **再接入讲义自动配图**：lecture_agent 检测 + 占位符渲染
3. 闯关图挂载最后做

## 7. 不做（Non-goals）

- manim 视频模式（服务端渲染重，留待 code_executor 环境成熟后作为扩展）
- 动画在线编辑（v1 只读展示，改内容重新生成）
- 多语言/导出（v1 单文件 HTML 导出可由前端「下载快照」实现，低成本可选）

---

## 8. 触发边界 v2（2026-08-09 与 Ryan 讨论定稿）

### 决策
- 全自动；**默认不触发**
- 动画判据（四条，全中才 animation）：① 状态容器（数组/树/图/矩阵/栈/网络层…）② 状态随步骤演化 ③ 机械因果（顺序不可调换）④ 空间增益
- 不适合动画但有静态结构 → **static**（一张 SVG 图，注入讲义同动画块，前端无控制条渲染）
- 其余（操作清单/配置流程/概念叙述/经验）→ **none**

### 两层架构
1. **规则层（零成本，只做快速拒绝）**：`NEGATIVE_KEYWORDS`（安装/配置/注册/登录/部署/下载/创建/启动实例/选择镜像/SSH…）命中 → 直接 none，不进 LLM；无负向词但有过程/结构特征 → maybe 交 LLM；无任何特征 → none
2. **LLM 层（最终裁决，一次调用）**：`decide_and_generate` 输出 `{"decision": animation|static|none, "reason", "animation"?|"static_svg"?}`，prompt 明确「默认倾向 none」
   - 实测：TCP 握手→animation（规则层词表抓不到，语义裁决救回）；烹饪步骤→none（默认偏置生效）
3. **用户兜底**：工作台手动生成（未实现，计划中）；讲义动画块可移除

### 数据
- `process_animations.kind` 列：animation | static（EXTRA_COLUMNS 迁移）
- 静态图 = kind=static + steps=[{svg}]，前端 `ProcessAnimationViewer` 静态分支只渲染图

### 回归测试（2026-08-09）
| 内容 | 规则层 | LLM 层 |
|---|---|---|
| AWS EC2 配置流程（原误触发） | none ✅ | — |
| 快速排序 | maybe | animation ✅ |
| CNN 前向传播 | maybe | animation ✅ |
| TCP 三次握手 | maybe（词表 v2 修复） | animation ✅ |
| 系统架构介绍 | maybe | static ✅ |
| 损失函数概念 | none ✅ | — |
| 烹饪步骤 | maybe | none ✅ |
