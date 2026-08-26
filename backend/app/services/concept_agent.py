"""Generate source-grounded formative checks for a checkpoint.

Question type describes the response format, not the learning construct. Code
output prediction is one optional format and is executable-verified when used.
"""
import hashlib
import json
import re
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.services.code_executor import execute_code

SUPPORTED_QUESTION_TYPES = {"single", "multi", "judge", "code_output"}
LEGACY_QUESTION_TYPES = {"wwpd": "code_output", "wwpp": "code_output"}


GENERATE_PROMPT = """你是学习评价设计专家。根据下面的关卡目标、讲义和来源，设计形成性概念检查。

## 关卡
{checkpoint_title}: {checkpoint_description}

## 学生水平
{user_level}

## 讲义内容
{lecture_content}

## 参考资料切片
{chunk_context}

## 题目要求
1. 出 3-8 道题，数量由内容复杂度决定：内容有料就多出，没料就少出，绝不硬凑。
2. 每道题先明确一个细粒度学习目标（learning_target），再写出学生怎样的可观察回答能支持判断（evidence_claim），最后选择响应形式。不要先按题型凑配额。
3. 当前支持的响应形式只有：
   - single：一个正确选项；可用于解释原因、概念辨析、情境应用或错误定位。
   - multi：多个正确选项；用于需要同时识别多个条件或关系的目标。
   - judge：正确/错误；只在一个明确命题足以提供证据时使用，避免靠措辞猜题。
   - code_output：代码推演；仅当关卡目标本身需要追踪 Python 执行语义，且讲义或来源确实包含相关代码时使用。系统支持这种形式不构成出题理由。
4. 响应形式不等于认知层次。优先考察解释、辨析、错误定位、预测和近迁移，不考孤立术语记忆。
5. 难度根据推理步数、概念组合和情境新颖度确定，不强制每档都出现。
6. 每题附简要解析，说明答案依据以及其他选项为何不成立。
7. 干扰项可以表示“待验证的常见混淆”，但没有学习者回答或研究证据时，不得称为已确认误解。
8. 每题列出它实际依据的 source_chunk_ids。不得引入讲义、关卡目标和参考切片中没有出现的专有内容。

## 输出格式（JSON）
```json
{{
  "questions": [
    {{
      "q_type": "single",
      "difficulty": "medium",
      "learning_target": "本题要检查的细粒度目标",
      "evidence_claim": "什么样的回答能说明学生理解了什么",
      "target_concepts": ["概念A"],
      "source_chunk_ids": [123],
      "question": "题干",
      "code": "仅 code_output 使用的纯 Python 代码，其他题型为空字符串",
      "options": ["选项A", "选项B", "选项C", "选项D"],
      "answer_indexes": [0],
      "explanation": "解析"
    }}
  ]
}}
```

规则：
- code_output 的 code 必须是自包含、可直接运行的 Python（只依赖标准库），不要读文件/网络；题干中也要展示这段代码。
- judge 题 options 必须是 ["正确", "错误"]。
- source_chunk_ids 只能取自参考资料切片标题中给出的 ID。
- JSON 中所有字符串的双引号要正确转义。
- **输出必须是单个合法的 JSON 对象**（不要 markdown 代码块包裹，不要额外文字）。"""

EXPLAIN_PROMPT = """你是学习辅导助手。学生回答了一道概念题，请给出解析。

## 题目（{q_type}）
{question}

## 选项
{options_text}

## 正确答案
{answer_text}

## 学生的回答
{user_answer_text}

## 要求
- 解释为什么正确答案是对的（200-400 字）
- 如果学生答错，指出本次回答暴露的待确认缺口；不要仅凭一道题断言稳定误解
- code_output 题要解释代码的执行过程
- 用 KaTeX 写公式（如有）"""


GRAPH_PROMPT = """你是知识图谱专家。根据讲义的章节结构，提取一份**概念知识图谱**。

## 讲义小节
{section_outline}

## 概念图谱要求
1. 节点 = 核心概念/方法/术语（8-25 个），每个节点标注它出自哪个小节（section_index）。
2. 边 = 概念之间的关系，关系词用简短动词/介词：使用、基于、应用于、区别于、包含、前置、改进、类比等。
3. 只保留有价值的关系（教学上能帮助学生理解概念联系），不要全连接。
4. 概念用中文（英文术语保留原文，如 "梯度下降"、"Tensor"）。

## 输出格式（JSON，只输出 JSON）
{{
  "nodes": [{{"id": "c1", "label": "概念名", "section_index": 0}}],
  "edges": [{{"source": "c1", "target": "c2", "relation": "使用"}}]
}}"""


class ConceptAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            timeout=120,
            max_retries=0,
            max_tokens=8000,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        # plain LLM for free-text outputs (explain) — json_object mode would
        # require the prompt to contain the word "json", which explains don't
        self.llm_text = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.5,
            timeout=60,
            max_retries=0,
            max_tokens=2000,
        )

    # ── Response normalization and executable verification ──

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Robust JSON extraction: ```json block first, then raw_decode from
        each '{' (LLM output may contain literal braces inside string fields)."""
        m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        decoder = json.JSONDecoder()
        for i, ch in enumerate(content):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(content[i:])
                    return obj
                except (json.JSONDecodeError, ValueError):
                    continue
        raise ValueError("no JSON object found")

    @staticmethod
    def _norm_option(o: str) -> str:
        """Strip 'A. ' / 'B、' / 'C)' style prefixes from LLM-generated options."""
        o = (o or "").strip()
        m = re.match(r"^[A-Ha-h][\.、\):：]?\s*(.*)$", o)
        if m and m.group(1).strip():
            return m.group(1).strip()
        return o

    @staticmethod
    def _canonical_question_type(value: str) -> Optional[str]:
        q_type = str(value or "single").strip().lower()
        q_type = LEGACY_QUESTION_TYPES.get(q_type, q_type)
        return q_type if q_type in SUPPORTED_QUESTION_TYPES else None

    @staticmethod
    def _verified_code_options(
        question: str,
        expected: str,
        options: List[str],
    ) -> tuple[List[str], List[int]]:
        """Insert the executed answer once at a stable non-fixed position."""
        distractors = [item for item in options if item != expected][:3]
        if not distractors:
            return [], []
        position = int(
            hashlib.sha256(f"{question}\n{expected}".encode("utf-8")).hexdigest()[:8],
            16,
        ) % (len(distractors) + 1)
        verified = list(distractors)
        verified.insert(position, expected)
        return verified, [position]

    @staticmethod
    def _verify_code_answer(code: str) -> Optional[str]:
        """Execute reference code; return the authoritative answer string.

        stdout → printed output; exception → the exception line (e.g.
        "NameError: name 'x' is not defined"); empty/None → verification failed.
        """
        if not code or not code.strip():
            return None
        res = execute_code(code, timeout=5)
        if res.get("timed_out"):
            return None
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or "").strip()
        if out:
            return out
        if res.get("exit_code") != 0 and err:
            # first meaningful line of the traceback (the exception itself)
            lines = [l for l in err.splitlines() if l.strip()]
            for l in lines:
                if "Error" in l:
                    return l.strip()[:120]
            return lines[-1][:120] if lines else None
        return None

    async def generate(
        self,
        checkpoint_title: str,
        checkpoint_description: str,
        user_level: str,
        lecture_sections: List[Dict],
        chunks: List[Dict],
    ) -> List[Dict]:
        """Generate verified concept questions."""
        lecture_text = ""
        for s in (lecture_sections or [])[:3]:
            lecture_text += s.get("content", "")[:1500] + "\n\n"
        chunk_text = "\n".join(
            f"[source_chunk_id={c.get('id', 'unknown')}] {c.get('content', '')[:500]}"
            for c in chunks[:6]
        )
        valid_chunk_ids = {
            int(c["id"]) for c in chunks if c.get("id") is not None
        }

        prompt = GENERATE_PROMPT.format(
            checkpoint_title=checkpoint_title,
            checkpoint_description=checkpoint_description or "",
            user_level=user_level,
            lecture_content=lecture_text[:4500] or "（暂无讲义，请基于参考资料出题）",
            chunk_context=chunk_text[:3000] or "（无）",
        )

        try:
            resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = resp.content
            parsed = self._extract_json(content)
            raw_qs = parsed.get("questions", [])
        except Exception as e:
            print(f"[ConceptAgent] generate failed: {type(e).__name__}: {str(e)[:150]}")
            return []

        questions = []
        seen = set()
        for q in raw_qs:
            q_type = self._canonical_question_type(q.get("q_type", "single"))
            if not q_type:
                continue
            question = (q.get("question") or "").strip()
            options = [self._norm_option(o) for o in (q.get("options") or [])]
            options = list(dict.fromkeys(o for o in options if o))
            try:
                ans = list(dict.fromkeys(int(i) for i in (q.get("answer_indexes") or [])))
            except (TypeError, ValueError):
                continue

            if not question or len(options) < 2 or not ans:
                continue
            if any(i >= len(options) for i in ans):
                continue
            if question in seen:
                continue
            seen.add(question)

            code = (q.get("code") or "").strip()
            expected = ""
            if q_type == "code_output":
                if not code:
                    continue
                expected = self._verify_code_answer(code)
                if expected is None:
                    continue  # code doesn't run / no output → discard
                options, ans = self._verified_code_options(question, expected, options)
                if len(options) < 2 or not ans:
                    continue
            elif q_type == "judge":
                options = ["正确", "错误"]
                if not ans or ans[0] not in (0, 1):
                    continue
                ans = [ans[0]]
                code = ""
            else:
                code = ""

            source_chunk_ids = []
            for value in q.get("source_chunk_ids") or []:
                try:
                    chunk_id = int(value)
                except (TypeError, ValueError):
                    continue
                if chunk_id in valid_chunk_ids and chunk_id not in source_chunk_ids:
                    source_chunk_ids.append(chunk_id)

            questions.append({
                "question": question,
                "code": code,
                "q_type": q_type,
                "difficulty": q.get("difficulty", "medium"),
                "options": options,
                "answer_indexes": ans,
                "expected_output": expected,
                "explanation": (q.get("explanation") or "").strip(),
                "learning_target": str(q.get("learning_target") or "").strip()[:500],
                "evidence_claim": str(q.get("evidence_claim") or "").strip()[:500],
                "target_concepts": [
                    str(item).strip()[:100]
                    for item in (q.get("target_concepts") or [])[:8]
                    if str(item).strip()
                ],
                "source_chunk_ids": source_chunk_ids,
            })

        return questions

    async def explain(
        self,
        question: Dict,
        user_answer: Optional[List[int]],
    ) -> str:
        """Lazy explanation for a single question (with the user's answer)."""
        opts = question.get("options") or []
        ans = question.get("answer_indexes") or []
        answer_text = "；".join(opts[i] for i in ans if i < len(opts))
        if self._canonical_question_type(question.get("q_type", "")) == "code_output" and question.get("expected_output"):
            answer_text = f"输出：{question['expected_output']}"
        if user_answer:
            user_text = "；".join(opts[i] for i in user_answer if i < len(opts)) or "（未选择）"
        else:
            user_text = "（未作答）"

        opts_text = "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(opts))
        prompt = EXPLAIN_PROMPT.format(
            q_type=question.get("q_type", ""),
            question=question.get("question", ""),
            options_text=opts_text,
            answer_text=answer_text,
            user_answer_text=user_text,
        )
        try:
            resp = await self.llm_text.ainvoke([HumanMessage(content=prompt)])
            return resp.content
        except Exception as e:
            return f"解析生成失败：{type(e).__name__}: {str(e)[:120]}"

    async def generate_graph(self, sections: List[Dict]) -> dict:
        """Extract a concept knowledge graph from lecture sections (single LLM call)."""
        outline = []
        for i, s in enumerate(sections or []):
            title = s.get("title", "")
            content = s.get("content", "")[:500].replace("\n", " ")
            outline.append(f"[{i}] {title}: {content[:300]}")
        prompt = GRAPH_PROMPT.format(
            section_outline="\n".join(outline) or "（无讲义内容）",
        )
        try:
            resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
            data = self._extract_json(resp.content)
        except Exception as e:
            print(f"[ConceptAgent] graph failed: {type(e).__name__}: {str(e)[:150]}")
            return {"nodes": [], "edges": []}

        nodes, edges = [], []
        seen = set()
        for n in data.get("nodes") or []:
            label = str(n.get("label", "")).strip()
            if not label or label in seen:
                continue
            seen.add(label)
            nodes.append({
                "id": str(n.get("id", f"c{len(nodes)}")),
                "label": label[:30],
                "section_index": int(n.get("section_index", 0) or 0),
            })
        id_by_label = {n["label"]: n["id"] for n in nodes}
        for e in data.get("edges") or []:
            src = str(e.get("source", ""))
            tgt = str(e.get("target", ""))
            # accept label references or ids
            src_id = src if src in {n["id"] for n in nodes} else id_by_label.get(src)
            tgt_id = tgt if tgt in {n["id"] for n in nodes} else id_by_label.get(tgt)
            if src_id and tgt_id and src_id != tgt_id:
                edges.append({
                    "source": src_id,
                    "target": tgt_id,
                    "relation": str(e.get("relation", "相关")).strip()[:12] or "相关",
                })
        return {"nodes": nodes, "edges": edges}
