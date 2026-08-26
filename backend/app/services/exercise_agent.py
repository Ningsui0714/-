"""
Exercise generation agent (T8): blueprint → per-exercise → executable verification.

Pipeline:
1. blueprint: analyze checkpoint + lecture → list of exercise ideas with
   {concept, difficulty, engineering value, depends_on}; dedupe equivalent
   ideas; decide the final count (never pad).
2. per-exercise generation with pydantic-style validation + 1 retry.
3. verification: run solution against test_cases with code_executor; only
   exercises that pass ALL cases are kept (auto-repair up to 2 rounds).

test_cases format: [{"input": str, "expected": str}] — compared on stdout.
"""
import json
import re
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.services.code_executor import execute_code

BLUEPRINT_PROMPT = """你是算法竞赛与工程命题专家。根据关卡的学习内容设计**编程练习题蓝图**。

## 关卡
{checkpoint_title}: {checkpoint_description}

## 讲义内容
{lecture_content}

## 参考资料
{chunk_context}

## 蓝图要求
1. 列出所有值得做的题目想法，每个包含：
   - idea：一句话题目想法
   - concept：考察的核心知识点（1-2 个）
   - difficulty：easy | medium | hard
   - engineering_value：high | medium | low（工程实践价值）
   - depends_on：前置题目序号（-1 表示无依赖；若题目 B 需要复用题目 A 的解法，写 A 的序号）
2. **去重**：考察等价知识点的想法合并，只留最好的。
3. **数量定稿**：按内容复杂度决定最终题目数（1-5 道）。内容有料就多出，没料就少出，绝不硬凑。
4. 只保留值得做的题：经典、高价值、强工程属性。
5. 题目之间互相关联但不等价（递进式：题 2 在题 1 基础上扩展）。
6. **输出必须是单个合法的 JSON 对象**（不要 markdown 代码块包裹，不要额外文字）。

## 输出格式（JSON）
```json
{{
  "exercises": [
    {{
      "idea": "实现 X，考察 Y",
      "concept": "X",
      "difficulty": "easy",
      "engineering_value": "high",
      "depends_on": -1
    }}
  ]
}}
```"""

GENERATE_PROMPT = """你是算法竞赛与工程命题专家。根据蓝图生成一道完整的 Python 编程题。

## 关卡
{checkpoint_title}

## 题目蓝图
{blueprint}

## 讲义上下文
{lecture_content}

## 参考资料
{chunk_context}

## 前置题目解法（depends_on 指向的题，可复用其思路/代码）
{previous_solution}

## 要求
1. 题目清晰、自包含，考察理解而非套路。
2. starter_code 包含 TODO 注释，让用户补全核心逻辑。
3. solution 是完整可运行的参考解答。
4. test_cases 是 3-6 个 {{"input": "...", "expected": "..."}} 用例（stdin/stdout 比较，expected 为程序输出，不含多余空格）。
5. hints 2-3 条，从提示到引导，不要直接给答案。

## 输出格式（JSON）
```json
{{
  "title": "题目名称",
  "description": "题目描述（可含公式，用 KaTeX）",
  "starter_code": "带 TODO 的 Python 代码",
  "solution": "完整参考解答",
  "hints": ["提示1", "提示2"],
  "test_cases": [{{"input": "", "expected": "预期输出"}}]
}}
```

规则：
- 代码只依赖标准库。
- description 里示例 I/O 要和 test_cases 一致。
- 字符串中的双引号要正确转义。
- **输出必须是单个合法的 JSON 对象**（不要 markdown 代码块包裹，不要额外文字）。"""


class ExerciseAgent:
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

    def _extract_json(self, content: str) -> dict:
        if not content or not content.strip():
            raise ValueError("LLM returned empty response (no JSON)")
        m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        # Fallback: raw_decode from each '{' — LLM output may contain literal
        # braces inside string fields (starter_code etc.), so find/rfind
        # truncation is unreliable.
        decoder = json.JSONDecoder()
        for i, ch in enumerate(content):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(content[i:])
                    return obj
                except (json.JSONDecodeError, ValueError):
                    continue
        raise ValueError("no JSON object found")

    # ── Verification ──

    @staticmethod
    def verify_exercise(solution: str, test_cases: List[dict]) -> List[dict]:
        """Run solution against all test cases; return per-case results."""
        results = []
        for tc in test_cases or []:
            inp = tc.get("input", "")
            expected = (tc.get("expected") or "").strip()
            res = execute_code(solution, test_input=inp, timeout=5)
            actual = (res.get("stdout") or "").strip()
            passed = (actual == expected) and res.get("exit_code") == 0
            results.append({
                "passed": passed,
                "input": inp[:80],
                "expected": expected[:120],
                "actual": actual[:120],
                "stderr": (res.get("stderr") or "")[:120],
            })
        return results

    # ── Pipeline ──

    async def blueprint(self, checkpoint_title, checkpoint_description,
                        lecture_content, chunk_context) -> List[dict]:
        prompt = BLUEPRINT_PROMPT.format(
            checkpoint_title=checkpoint_title,
            checkpoint_description=checkpoint_description or "",
            lecture_content=lecture_content[:4000] or "（暂无讲义）",
            chunk_context=chunk_context[:3000] or "（无）",
        )
        items = []
        for attempt in range(2):  # 1 retry on transient bad output
            try:
                resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
                data = self._extract_json(resp.content)
                for i, ex in enumerate(data.get("exercises", [])):
                    items.append({
                        "index": i,
                        "idea": ex.get("idea", ""),
                        "concept": ex.get("concept", ""),
                        "difficulty": ex.get("difficulty", "medium"),
                        "engineering_value": ex.get("engineering_value", "medium"),
                        "depends_on": int(ex.get("depends_on", -1)),
                    })
                items = [it for it in items if it["idea"]]
                if items:
                    return items
            except Exception as e:
                print(f"[ExerciseAgent] blueprint failed (attempt {attempt}): {str(e)[:120]}")
        return items

    async def generate_one(
        self,
        checkpoint_title: str,
        blueprint_item: dict,
        lecture_content: str,
        chunk_context: str,
        previous_solution: str = "",
    ) -> dict:
        prompt = GENERATE_PROMPT.format(
            checkpoint_title=checkpoint_title,
            blueprint=json.dumps(blueprint_item, ensure_ascii=False),
            lecture_content=lecture_content[:3000] or "（暂无讲义）",
            chunk_context=chunk_context[:2500] or "（无）",
            previous_solution=previous_solution[:2000] or "（无前置题）",
        )
        resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
        data = self._extract_json(resp.content)
        return {
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "starter_code": str(data.get("starter_code", "")),
            "solution": str(data.get("solution", "")),
            "hints": [str(h) for h in (data.get("hints") or [])][:3],
            "test_cases": [{"input": str(t.get("input", "")), "expected": str(t.get("expected", ""))}
                           for t in (data.get("test_cases") or []) if t.get("expected") is not None],
            "concept": blueprint_item.get("concept", ""),
            "difficulty": blueprint_item.get("difficulty", "medium"),
        }

    async def generate_all(
        self,
        checkpoint_title: str,
        checkpoint_description: str,
        lecture_content: str,
        chunk_context: str,
        progress_cb=None,
    ) -> List[dict]:
        """Blueprint → parallel per-exercise generation → verify.

        Depends_on chain: independent exercises generate concurrently
        (Semaphore 3); dependent ones wait for their prerequisite solution.
        """
        import asyncio as _ai
        bp = await self.blueprint(checkpoint_title, checkpoint_description,
                                  lecture_content, chunk_context)
        if not bp:
            return []

        sem = _ai.Semaphore(3)
        solutions = {}   # item index -> verified solution
        results = {}     # item index -> exercise dict or None
        total = len(bp)

        async def _do(item: dict):
            # wait for prerequisite first
            dep = item.get("depends_on", -1)
            if dep >= 0:
                for _ in range(200):  # up to ~100s
                    if dep in results:
                        break
                    await _ai.sleep(0.5)
                prev = solutions.get(dep, "")
            else:
                prev = ""
            async with sem:
                exercise = None
                for attempt in range(2):  # 1 retry
                    try:
                        exercise = await self.generate_one(
                            checkpoint_title, item, lecture_content, chunk_context, prev)
                    except Exception as e:
                        print(f"[ExerciseAgent] gen failed (attempt {attempt}): {str(e)[:120]}")
                        continue
                    if not exercise.get("title") or not exercise.get("solution") or not exercise.get("test_cases"):
                        continue
                    v = self.verify_exercise(exercise["solution"], exercise["test_cases"])
                    if sum(1 for r in v if r["passed"]) == len(v) and len(v) >= 2:
                        exercise["verification"] = {"passed": len(v), "total": len(v)}
                        solutions[item["index"]] = exercise["solution"]
                        results[item["index"]] = exercise
                        return
                    if attempt == 0:
                        failing = [r for r in v if not r["passed"]][:2]
                        item = {**item, "verify_feedback": json.dumps(failing, ensure_ascii=False)[:800]}
                results[item["index"]] = None

        # Layer by layer: independent items first, dependents after
        remaining = list(bp)
        while remaining:
            layer = [it for it in remaining
                     if it.get("depends_on", -1) < 0 or it.get("depends_on") in results]
            if not layer:
                layer = remaining  # circular/unknown dep → just do them
            await _ai.gather(*[_do(it) for it in layer])
            remaining = [it for it in remaining if it not in layer]
            if progress_cb:
                progress_cb(len([k for k in results if results[k]]), total)

        return [results[i] for i in sorted(results) if results[i]]
