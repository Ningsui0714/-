"""Process-animator agent v2：讲义内容 → 可视化（动画/静态图/不生成）三态决策。

触发边界（与 Ryan 讨论定稿）：
- 全自动；默认不触发
- 动画判据：存在「可观察状态随步骤演化」（状态容器 + 状态变化 + 机械因果 + 空间增益）
- 不适合动画但有静态结构可展示 → 生成静态 SVG 图
- 其余（操作清单/配置流程/概念叙述）→ 不生成

两层架构：
1. 规则层（零成本，只做「快速拒绝」）：负向词表命中 → none；正向强信号不足 → none
2. LLM 层（最终裁决）：decision = animation | static | none，一次调用输出对应载荷

安全：LLM 输出永不可信 → SVG 白名单消毒 + 结构校验 + 上限。
"""
import json
import re
from typing import Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings

# ── 规则层词表 ──
# 负向词：操作清单/配置流程类动作，命中即「不生成」（快速拒绝，不进 LLM）
NEGATIVE_KEYWORDS = [
    "安装", "配置", "注册", "登录", "部署", "下载", "上传", "设置", "填写",
    "点击", "打开", "启动实例", "选择镜像", "克隆", "导入", "导出", "申请",
    "购买", "付费", "开通", "绑定", "环境变量", "控制台", "仪表盘", "编辑器",
]
# 正向强信号：状态变换类动词（含协议/并发等过程动作）
POSITIVE_STRONG = [
    "交换", "比较", "递归", "遍历", "传播", "传导", "收敛", "迭代", "回退",
    "滑动窗口", "指针", "入栈", "出栈", "压栈", "堆化", "旋转", "回溯",
    "分治", "归并", "置换", "前向传播", "反向传播", "梯度下降", "卷积",
    "池化", "激活函数", "状态转移", "失配", "命中",
    "发送", "接收", "回复", "握手", "请求", "响应", "切换", "调度",
    "缺页", "同步", "等待", "唤醒", "迁移", "合并", "拆分", "匹配", "溢出",
]
# 正向结构信号：状态容器/静态结构描述
POSITIVE_STRUCT = [
    "数组", "列表", "树", "图", "矩阵", "栈", "队列", "堆", "链表", "哈希",
    "状态机", "网络层", "神经元", "节点", "边", "权重",
    "架构", "结构", "模块", "组件", "依赖", "数据流", "层次", "拓扑",
    "流水线", "协议", "状态",
]

ANIMATION_PROMPT = """你是可视化决策专家。判断给定内容是否适合可视化，并按要求输出 JSON。

## 决策规则（先决策，再生成）

1. **animation（动态动画）**：存在「可观察状态随步骤演化」——同时满足：
   - 状态容器：数组/树/图/矩阵/栈/队列/堆/指针/网络层/权重等可观察结构
   - 状态变化：步骤之间状态真的在变（交换/比较/传播/收敛/递归…），不是单纯追加事实
   - 机械因果：变化由确定规则驱动，步骤顺序不可任意调换
   → decision="animation"，并生成 animation 载荷（见下）

2. **static（静态图）**：不满足动画条件，但有静态结构可展示（架构/层次/数据流/流程框图/对比），
   画成一张 SVG 图比纯文字更清晰
   → decision="static"，生成一张 SVG

3. **none（不生成）**：操作清单、安装/配置流程、概念叙述、历史叙述、经验建议等
   → decision="none"

4. **默认倾向 none**，不要为了生成而生成。拿不准就 none。

## animation 载荷（decision="animation" 时）
{"title": "...", "subtitle": "...", "legend": [["#22c55e","树边"], ...], "steps": [...]}
- steps 6-15 个，每步 {"title": "第 N 步：…", "text": "说明（中文，独立可读）", "bars" 或 "svg" 二选一}
- bars: {"values":[数字], "highlight":[索引], "pivot":[索引], "sorted":[索引], "done":[索引]}
  （highlight=当前操作黄, pivot=基准橙, sorted=已就位绿, done=已完成深绿）
- svg: 内联 SVG，viewBox 建议 0 0 640 320

## static 载荷（decision="static" 时）
{"title": "图标题", "static_svg": "<svg …>…</svg>"}
- 一张信息完整、标签清晰的 SVG 图（架构/流程/层次等）
- 外层必须包含 `viewBox="0 0 宽 高"`，所有内容与标签必须落在画布内并保留至少 16px 边距
- `rect`、`line`、`path`、`circle` 等图元必须用 `/>` 正确闭合；优先直接写 fill/stroke/font-size 等属性，不依赖 CSS class
- 连接线不得穿过文字；流程标签应与连线错开，或使用浅色背景/白色描边保证清晰

## 输出格式（只输出 JSON，不要 markdown 代码块）
{"decision": "animation"|"static"|"none", "reason": "一句话理由", "animation": {...}|null, "static_svg": "..."|null}"""


class AnimationAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.4,
            timeout=120,
            max_retries=0,
        )

    # ── 规则层：快速拒绝（零成本） ──
    # 策略：负向词是唯一硬拒绝；其余只要有一点过程/结构特征就交给 LLM 裁决（语义判断是 LLM 的职责）
    def classify_fast(self, text: str) -> str:
        """返回 'none'（直接拒绝）或 'maybe'（交给 LLM 裁决）。"""
        if not text:
            return "none"
        if any(k in text for k in NEGATIVE_KEYWORDS):
            return "none"
        strong = [k for k in POSITIVE_STRONG if k in text]
        struct = [k for k in POSITIVE_STRUCT if k in text]
        if strong or struct:
            return "maybe"
        # 无特征词但有强过程结构线索（编号步骤/首先然后最后）→ 给 LLM 一次机会
        if re.search(r"(^\s*\d+[.、)）]|第\s*\d+\s*步|首先|然后|最后)", text, re.M):
            return "maybe"
        return "none"

    # ── SVG 白名单消毒 ──
    SVG_TAGS = {
        "svg", "g", "circle", "rect", "line", "path", "text", "polygon",
        "polyline", "marker", "defs", "title", "tspan", "ellipse",
        "lineargradient", "radialgradient", "stop",
    }
    SVG_ATTRS = {
        name: name for name in {
            "fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "transform",
            "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
            "width", "height", "d", "font-size", "font-weight", "text-anchor",
            "font-family", "marker-end", "id", "offset", "stop-color", "stop-opacity",
            "paint-order", "stroke-linejoin",
        }
    }
    SVG_ATTRS.update({
        "viewbox": "viewBox",
        "preserveaspectratio": "preserveAspectRatio",
        "gradientunits": "gradientUnits",
    })
    SVG_STYLE_ATTRS = {
        name: name for name in {
            "fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "rx", "ry",
            "font-size", "font-weight", "text-anchor", "font-family", "stop-color",
            "stop-opacity",
        }
    }
    SVG_LEAF_TAGS = {"circle", "rect", "line", "path", "polygon", "polyline", "ellipse", "stop"}

    @staticmethod
    def _numeric_svg_attr(source: str, name: str) -> Optional[float]:
        match = re.search(rf'\b{re.escape(name)}\s*=\s*["\']([0-9]+(?:\.[0-9]+)?)["\']', source, re.I)
        if not match:
            return None
        return float(match.group(1))

    def _infer_svg_viewbox(self, svg: str) -> tuple[float, float]:
        svg_attrs = (re.search(r"<svg\b([^>]*)>", svg, re.I) or [None, ""])[1]
        existing = re.search(
            r'\bviewBox\s*=\s*["\']\s*-?[0-9.]+\s+-?[0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["\']',
            svg_attrs,
            re.I,
        )
        existing_width = float(existing.group(1)) if existing else 0
        existing_height = float(existing.group(2)) if existing else 0
        width = self._numeric_svg_attr(svg_attrs, "width")
        height = self._numeric_svg_attr(svg_attrs, "height")

        max_width = 0.0
        max_height = 0.0
        for rect in re.findall(r"<rect\b[^>]*>", svg, re.I):
            rect_width = self._numeric_svg_attr(rect, "width")
            rect_height = self._numeric_svg_attr(rect, "height")
            if not rect_width or rect_width <= 0 or not rect_height or rect_height <= 0:
                continue
            x = self._numeric_svg_attr(rect, "x") or 0
            y = self._numeric_svg_attr(rect, "y") or 0
            max_width = max(max_width, x + rect_width)
            max_height = max(max_height, y + rect_height)
        for line in re.findall(r"<line\b[^>]*>", svg, re.I):
            max_width = max(
                max_width,
                self._numeric_svg_attr(line, "x1") or 0,
                self._numeric_svg_attr(line, "x2") or 0,
            )
            max_height = max(
                max_height,
                self._numeric_svg_attr(line, "y1") or 0,
                self._numeric_svg_attr(line, "y2") or 0,
            )
        for text in re.findall(r"<text\b[^>]*>", svg, re.I):
            x = self._numeric_svg_attr(text, "x") or 0
            y = self._numeric_svg_attr(text, "y") or 0
            font_size = self._numeric_svg_attr(text, "font-size") or 14
            max_width = max(max_width, x)
            max_height = max(max_height, y + font_size * 0.4)

        base_width = existing_width or (width if width and width > 0 else 0) or max_width or 800
        base_height = existing_height or (height if height and height > 0 else 0) or max_height or 450
        return (
            max_width + 12 if max_width > base_width else base_width,
            max_height + 12 if max_height > base_height else base_height,
        )

    @staticmethod
    def _safe_style_value(value: str) -> Optional[str]:
        cleaned = value.strip()
        if not cleaned or re.search(r'[<>";]|javascript:|expression\s*\(', cleaned, re.I):
            return None
        if re.search(r"url\s*\(", cleaned, re.I) and not re.fullmatch(r"url\(#[A-Za-z][\w:.-]*\)", cleaned, re.I):
            return None
        return cleaned

    def _parse_style_declarations(self, source: str) -> Dict[str, str]:
        declarations = {}
        for declaration in source.split(";"):
            if ":" not in declaration:
                continue
            property_name, value = declaration.split(":", 1)
            safe_name = self.SVG_STYLE_ATTRS.get(property_name.strip().lower())
            safe_value = self._safe_style_value(value)
            if safe_name and safe_value:
                declarations[safe_name] = safe_value
        return declarations

    def _extract_css_classes(self, svg: str) -> Dict[str, Dict[str, str]]:
        return {
            name: self._parse_style_declarations(body)
            for name, body in re.findall(r"\.([A-Za-z_][\w-]*)\s*\{([^{}]*)\}", svg)
        }

    def sanitize_svg(self, svg: str) -> str:
        if not svg:
            return ""
        svg = svg[:65536]
        inferred_width, inferred_height = self._infer_svg_viewbox(svg)
        css_classes = self._extract_css_classes(svg)
        had_css_rules = bool(css_classes)
        rect_bounds = []
        for rect in re.findall(r"<rect\b[^>]*>", svg, re.I):
            x = self._numeric_svg_attr(rect, "x") or 0
            y = self._numeric_svg_attr(rect, "y") or 0
            width = self._numeric_svg_attr(rect, "width") or 0
            height = self._numeric_svg_attr(rect, "height") or 0
            if width > 0 and height > 0:
                rect_bounds.append((x, y, width, height))
        svg = re.sub(r"<script.*?</script>", "", svg, flags=re.I | re.S)
        svg = re.sub(r"<style\b[^>]*>.*?</style>", "", svg, flags=re.I | re.S)
        svg = re.sub(r"\.[A-Za-z_][\w-]*\s*\{[^{}]*\}", "", svg)
        svg = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", svg, flags=re.I)
        svg = re.sub(r"javascript:", "", svg, flags=re.I)

        def _clean_tag(m: re.Match) -> str:
            closing = bool(m.group(1))
            tag = m.group(2).lower()
            if tag not in self.SVG_TAGS:
                return ""
            if closing:
                return "" if tag in self.SVG_LEAF_TAGS else f"</{tag}>"

            kept = {}
            kept_names = set()
            class_match = re.search(r'\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', m.group(3), re.I)
            class_value = (class_match.group(1) or class_match.group(2)) if class_match else ""
            for class_name in class_value.split():
                kept.update(css_classes.get(class_name, {}))
            for name, value in re.findall(r'([\w-]+)\s*=\s*("[^"]*"|\'[^\']*\')', m.group(3)):
                source_name = name.lower()
                if source_name in {"class", "style"}:
                    continue
                safe_name = self.SVG_ATTRS.get(source_name)
                if not safe_name:
                    continue
                kept[safe_name] = value[1:-1]
                kept_names.add(source_name)
            inline_match = re.search(r'\bstyle\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', m.group(3), re.I)
            inline_value = (inline_match.group(1) or inline_match.group(2)) if inline_match else ""
            kept.update(self._parse_style_declarations(inline_value))
            if had_css_rules and tag == "rect" and "fill" not in kept:
                kept.update({"fill": "#f8fafc", "stroke": "#334155", "stroke-width": "1.5"})
            if had_css_rules and tag == "text":
                kept.setdefault("fill", "#1e293b")
                kept.setdefault("font-family", "Arial, sans-serif")
                kept.setdefault("font-size", "13px")
                kept.setdefault("text-anchor", "middle")
                x = self._numeric_svg_attr(m.group(3), "x") or 0
                y = self._numeric_svg_attr(m.group(3), "y") or 0
                inside_node = any(
                    left <= x <= left + width and top <= y <= top + height
                    for left, top, width, height in rect_bounds
                )
                if not inside_node:
                    kept.update({
                        "paint-order": "stroke",
                        "stroke": "#ffffff",
                        "stroke-width": "4",
                        "stroke-linejoin": "round",
                    })
            if tag == "svg":
                kept["viewBox"] = f"0 0 {inferred_width:g} {inferred_height:g}"
                if "preserveaspectratio" not in kept_names:
                    kept["preserveAspectRatio"] = "xMidYMid meet"
                kept["style"] = "display:block;width:100%;height:auto"
            serialized = " ".join(
                f'{name}="{self._escape_svg_attr(value)}"' for name, value in kept.items()
            )
            opening = f"<{tag}" + (" " + serialized if serialized else "")
            return opening + (" />" if tag in self.SVG_LEAF_TAGS else ">")

        svg = re.sub(r"<(\/)?(\w+)([^>]*)>", _clean_tag, svg)
        return svg

    @staticmethod
    def _escape_svg_attr(value: str) -> str:
        return str(value).replace("&", "&amp;").replace('"', "&quot;")

    # ── 结构校验与上限 ──
    def validate_steps(self, data: Dict) -> Dict:
        steps = data.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps 为空")
        steps = steps[:30]
        cleaned = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            step = {
                "title": str(s.get("title", ""))[:80],
                "text": str(s.get("text", ""))[:2000],
            }
            bars = s.get("bars")
            if isinstance(bars, dict) and isinstance(bars.get("values"), list):
                values = bars["values"]
                if values and len(values) <= 64 and all(isinstance(v, (int, float)) for v in values):
                    step["bars"] = {
                        "values": [float(v) for v in values],
                        "highlight": [int(i) for i in bars.get("highlight", []) if isinstance(i, int)],
                        "pivot": [int(i) for i in bars.get("pivot", []) if isinstance(i, int)],
                        "sorted": [int(i) for i in bars.get("sorted", []) if isinstance(i, int)],
                        "done": [int(i) for i in bars.get("done", []) if isinstance(i, int)],
                    }
            if s.get("svg"):
                svg = self.sanitize_svg(str(s["svg"]))
                if svg:
                    step["svg"] = svg
            if "bars" not in step and "svg" not in step:
                continue
            cleaned.append(step)
        if not cleaned:
            raise ValueError("没有合法的可视化步骤")
        legend = data.get("legend") or []
        legend = [list(p) for p in legend if isinstance(p, (list, tuple)) and len(p) == 2][:8]
        return {
            "title": str(data.get("title", "过程演示"))[:120],
            "subtitle": str(data.get("subtitle", ""))[:200],
            "legend": legend,
            "steps": cleaned,
        }

    # ── LLM 层：三态决策 + 生成（一次调用） ──
    async def decide_and_generate(self, text: str) -> Dict:
        """返回 {"kind": "animation"|"static"|"none", "data": {...}|None}"""
        resp = await self.llm.ainvoke([
            SystemMessage(content=ANIMATION_PROMPT),
            HumanMessage(content=f"内容：\n{text[:4000]}"),
        ])
        raw = resp.content
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
        if m:
            raw = m.group(1)
        data = json.loads(raw)
        decision = data.get("decision", "none")
        reason = str(data.get("reason", ""))[:200]
        if decision == "animation" and data.get("animation"):
            try:
                return {"kind": "animation", "data": self.validate_steps(data["animation"]), "reason": reason}
            except Exception:
                return {"kind": "none", "reason": reason}
        if decision == "static" and data.get("static_svg"):
            svg = self.sanitize_svg(str(data["static_svg"]))
            if svg:
                return {
                    "kind": "static",
                    "data": {
                        "title": str(data.get("title", "结构图"))[:120],
                        "subtitle": "",
                        "legend": [],
                        "steps": [{"title": "", "text": "", "svg": svg}],
                    },
                    "reason": reason,
                }
        return {"kind": "none", "reason": reason}

    # ── 讲义集成入口 ──
    async def maybe_create_visual(
        self, project_id: Optional[int], checkpoint_id: int,
        section_index: int, content: str, db,
    ) -> Optional[Dict]:
        """规则快速拒绝 → LLM 裁决 → 落库。返回 {"kind", "id"} 或 None。失败/不命中不阻塞讲义。"""
        if ":::process-anim" in content:
            return None  # 已注入过（resume 场景）
        if self.classify_fast(content) == "none":
            return None
        try:
            res = await self.decide_and_generate(content)
        except Exception:
            return None
        if res["kind"] == "none":
            return None
        data = res["data"]
        from app.models.project import ProcessAnimation
        anim = ProcessAnimation(
            project_id=project_id,
            checkpoint_id=checkpoint_id,
            source="lecture",
            kind=res["kind"],
            section_index=section_index,
            title=data["title"],
            subtitle=data.get("subtitle", ""),
            legend=data.get("legend", []),
            steps=data["steps"],
        )
        db.add(anim)
        await db.commit()
        await db.refresh(anim)
        return {"kind": res["kind"], "id": anim.id}
