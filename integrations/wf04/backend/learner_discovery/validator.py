"""题目 / 输入 Validator 与失败回退（任务书第 10 节）。

- 候选题目必须通过独立 Validator 才能展示；
- 校验失败安全回退：丢弃不完整题目，绝不让非法题进入发现会话；
- 开放题无法可靠评分时返回 need_review / insufficient_evidence，不强行二分。
"""

from __future__ import annotations

from typing import Any

MIN_OPTIONS = 3
VALID_DIFFICULTY = (1, 2, 3)


def validate_question(question: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验一道可评分选择题。返回 (是否合法, 问题列表)。"""
    problems: list[str] = []
    question_id = str(question.get("id") or question.get("question_id") or "").strip()
    if not question_id:
        problems.append("题目缺少稳定 id")
    kp_id = str(question.get("knowledge_point_id") or "").strip()
    if not kp_id:
        problems.append("题目缺少 knowledge_point_id")
    title = str(question.get("title") or "").strip()
    if not title:
        problems.append("题目缺少题干")
    options = question.get("options")
    if not isinstance(options, dict) or len(options) < MIN_OPTIONS:
        problems.append(f"选项必须是 dict 且不少于 {MIN_OPTIONS} 个")
    else:
        answer = str(question.get("answer") or "").strip().lower()
        if answer not in options:
            problems.append("答案必须存在于选项中")
        valid_labels = {str(k).strip().lower() for k in options}
        if answer and answer not in valid_labels:
            problems.append("答案标签必须与选项键一致")
    if not str(question.get("explanation") or "").strip():
        problems.append("题目缺少解析/理由")
    difficulty = question.get("difficulty")
    if difficulty not in (None, "") and int(difficulty) not in VALID_DIFFICULTY:
        problems.append("难度必须为 1-3")
    return (not problems), problems


def filter_valid_questions(questions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """批量校验：返回 (通过列表, 被丢弃列表)。"""
    valid: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for question in questions:
        ok, problems = validate_question(question)
        if ok:
            valid.append(question)
        else:
            item = dict(question)
            item["validation_problems"] = problems
            dropped.append(item)
    return valid, dropped


def freeze_question(question: dict[str, Any], version: str = "v1") -> dict[str, Any]:
    """冻结题目：附加 question_version / grading_version，供 provenance 使用。"""
    frozen = {k: v for k, v in question.items()}
    frozen["question_version"] = version
    frozen["grading_version"] = "v1"
    return frozen


def validate_answer_input(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验一轮作答输入。区分 跳过 / 含糊 / 正常作答。"""
    problems: list[str] = []
    action = str(payload.get("action") or "answer").strip().lower()
    selected = str(payload.get("selected") or "").strip().lower()
    if action not in ("answer", "skip", "hazy", "clarify", "probe_answer", "preference", "confirm"):
        problems.append(f"未知的 action：{action}")
    if action == "answer" and selected not in {"a", "b", "c", "d"}:
        problems.append("answer 需要有效的 selected 选项")
    if not str(payload.get("client_event_id") or "").strip():
        problems.append("缺少 client_event_id（幂等键）")
    return (not problems), problems
