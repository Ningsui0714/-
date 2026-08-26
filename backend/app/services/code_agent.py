"""
Code Review & Q&A Agent.

- Full code review: analyze code for correctness, performance, style
- Selected code Q&A: explain a specific code segment
"""
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings

REVIEW_PROMPT = """你是一名代码审阅导师。学生提交了一段代码，请从以下方面给出反馈：

## 代码
```python
{code}
```

## 题目背景
{exercise_context}

## 审阅要求
1. **正确性**：代码逻辑是否正确？有没有 bug？
2. **完整性**：TODO 部分是否已实现？
3. **性能**：有没有可以优化的地方？
4. **风格**：是否符合 Python 最佳实践？
5. **改进建议**：给出 1-2 个具体的改进方向（附代码片段）

⚠️ 注意：不要直接给出完整的"答案代码"，引导学生自己思考和修正。
指出问题所在，给出提示，而不是直接重写。"""

EXPLAIN_PROMPT = """你是一名代码学习辅导助手。学生选中了以下代码片段，请解释它的作用。

## 选中代码
```python
{selection}
```

## 完整代码上下文（题目）
{exercise_context}

## 解释要求
- 用通俗的语言解释这段代码做了什么
- 如果有关键算法或语法，解释其原理
- 控制在 200-400 字"""


class CodeAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.3,
            timeout=30,
            max_retries=0,
        )

    async def review(self, code: str, exercise_context: str) -> str:
        """Full code review."""
        prompt = REVIEW_PROMPT.format(code=code, exercise_context=exercise_context)
        resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content

    async def explain(self, selection: str, code: str, exercise_context: str) -> str:
        """Explain a selected code segment."""
        prompt = EXPLAIN_PROMPT.format(
            selection=selection,
            exercise_context=exercise_context,
        )
        # Add full code as context but highlight the selection
        full_context = f"## 完整代码\n```python\n{code}\n```\n\n## 题目\n{exercise_context}"
        messages = [
            SystemMessage(content=f"你是一名代码辅导助手。完整代码和题目如下：\n{full_context}"),
            HumanMessage(content=prompt),
        ]
        resp = await self.llm.ainvoke(messages)
        return resp.content
