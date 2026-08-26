"""确定性对话理解：把一轮消息拆成意图、主题、自述与学习约束。

该模块不做最终判分，也不直接写入持久化状态。模型工作流可在后续提供
候选理解，但所有候选仍须归一化到本模块定义的稳定枚举后才能执行。
"""

from __future__ import annotations

import re
from typing import Any


PRIMARY_INTENTS = frozenset(
    {
        "create_project",
        "knowledge_question",
        "update_learning_context",
        "start_assessment",
        "show_path",
        "open_lesson",
        "general_assistant",
        "clarify_intent",
    }
)

SUBJECT_ALIASES = (
    ("python", ("python", "py语言")),
    ("java", ("java",)),
    ("javascript", ("javascript", "js", "前端")),
    ("c_language", ("c语言", "c程序设计", "c编程")),
    ("c_plus_plus", ("c++", "cpp")),
    ("sql", ("sql", "数据库", "mysql", "postgresql", "sqlite")),
    ("html_css", ("html", "css", "网页制作", "网页设计")),
    ("data_structures", ("数据结构", "算法基础", "算法与数据结构")),
    ("linux", ("linux", "shell", "命令行")),
    ("git", ("git", "github", "版本控制")),
    ("machine_learning", ("机器学习", "深度学习", "人工智能", "ai")),
    ("cybersecurity", ("网络安全", "信息安全", "渗透测试")),
    ("english", ("英语", "english")),
    ("project_management", ("项目管理", "pmp")),
)

GOAL_TYPE_MARKERS = (
    ("competition", ("大赛", "比赛", "竞赛", "备赛", "参赛")),
    ("certification", ("考证", "认证", "证书", "考级", "考试", "软考", "雅思", "托福")),
    ("job", ("岗位", "求职", "就业", "转行", "面试", "应聘", "工程师", "程序员")),
    ("remedial", ("补基础", "补弱", "薄弱", "错题", "总是错", "不会", "看不懂", "跟不上")),
    ("review", ("复习", "回顾", "巩固", "查漏补缺")),
    ("project", ("项目", "网站", "看板", "开发", "制作", "做出", "做一个", "搭建", "训练", "实现")),
)

APPLICATION_SCENARIOS = (
    ("data_analysis", ("数据分析", "数据看板", "销售报表", "pandas", "numpy")),
    ("web_development", ("web开发", "网站", "网页", "后端", "前端", "django", "flask", "fastapi")),
    ("automation", ("办公自动化", "自动处理", "批量处理", "爬虫")),
    ("algorithm_competition", ("算法", "程序设计", "刷题", "竞赛")),
    ("machine_learning", ("机器学习", "深度学习", "人工智能", "模型训练")),
    ("database", ("数据库", "mysql", "postgresql", "sql")),
    ("cybersecurity", ("网络安全", "信息安全", "渗透测试")),
    ("embedded", ("嵌入式", "单片机", "物联网")),
)


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _subject(text: str) -> str:
    lowered = text.lower()
    for subject, aliases in SUBJECT_ALIASES:
        if _contains_any(lowered, aliases):
            return subject
    return ""


def _learning_scope(text: str, subject: str) -> str:
    lowered = text.lower()
    if _contains_any(lowered, ("pandas", "numpy", "数据分析", "数据看板", "探索性分析", "eda", "数据可视化")):
        return "data_analysis"
    if _contains_any(lowered, ("web开发", "网站", "网页", "django", "flask", "fastapi")):
        return "web_development"
    if _contains_any(lowered, ("办公自动化", "自动处理excel", "自动处理文件", "爬虫")):
        return "automation"
    if _contains_any(lowered, ("基础知识", "基础语法", "编程基础", "入门", "从头学", "数据类型")):
        return "foundation"
    if subject and _contains_any(lowered, ("语法", "变量", "函数", "循环", "列表", "字典")):
        return "foundation"
    return ""


def _current_level(text: str) -> str:
    lowered = text.lower()
    if _contains_any(lowered, ("零基础", "没学过", "完全不会", "没有基础")):
        return "zero_foundation"
    if _contains_any(lowered, ("有一点基础", "有些基础", "学过一点", "入门基础")):
        return "basic"
    if _contains_any(lowered, ("有基础", "已经学过", "熟悉", "有经验")):
        return "experienced"
    return ""


def _goal_type(text: str, primary_intent: str) -> str:
    lowered = text.lower()
    for goal_type, markers in GOAL_TYPE_MARKERS:
        if _contains_any(lowered, markers):
            return goal_type
    if primary_intent == "update_learning_context":
        return ""
    if primary_intent in {"create_project", "knowledge_question"}:
        return "course"
    return ""


def _application_scenario(text: str) -> str:
    lowered = text.lower()
    for scenario, markers in APPLICATION_SCENARIOS:
        if _contains_any(lowered, markers):
            return scenario
    return ""


def _target_outcome(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    patterns = (
        r"(?:转行|进入|应聘|求职)(?:做|从事)?\s*([^。；！？?]{2,80})",
        r"(?:用|通过|为了)\s*[^，。；！？?]{0,24}?(?:做|完成|实现)\s*([^，。；！？?]{2,60})",
        r"(?:目标是|最终想(?:要)?|希望(?:能够)?|想做到|想实现|为了)([^，。；！？?]{2,80})",
        r"(?:成为|考取|拿到)([^，。；！？?]{2,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.I)
        if not match:
            continue
        value = match.group(1).strip(" ，。；：:")
        if value and not value.startswith(("学习", "学会", "掌握")):
            return value[:80]
    return ""


def _goal_constraints(text: str) -> dict[str, Any]:
    normalized = " ".join(str(text or "").split())
    constraints: dict[str, Any] = {}
    level = _current_level(normalized)
    if level:
        constraints["current_level"] = level
    daily = re.search(r"每天\s*(\d+(?:\.\d+)?)\s*(小时|小時|h|分钟|分鐘)", normalized, flags=re.I)
    weekly = re.search(r"每周\s*(\d+(?:\.\d+)?)\s*(小时|小時|h|分钟|分鐘)", normalized, flags=re.I)
    if daily:
        constraints["daily_time"] = f"{daily.group(1)}{daily.group(2)}"
    if weekly:
        constraints["weekly_time"] = f"{weekly.group(1)}{weekly.group(2)}"
    duration = re.search(
        r"(?:用|在|计划|准备)?\s*(\d+|半|一|二|两|三|四|五|六|七|八|九|十)\s*(天|周|个月|月|年)(?:内|之内)?",
        normalized,
    )
    if duration:
        constraints["duration"] = f"{duration.group(1)}{duration.group(2)}"
    deadline = re.search(r"(?:截止|之前|前|考试在|报名在)\s*([^，。；！？?]{2,24})", normalized)
    if deadline:
        constraints["deadline"] = deadline.group(1).strip()
    return constraints


def _learner_claims(text: str, subject: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    level = _current_level(text)
    if level:
        claims.append(
            {
                "type": "current_level",
                "subject": subject,
                "claim": level,
                "verification_state": "unverified",
            }
        )
    patterns = (
        ("familiar", r"(?:我|本人)(?:会|学过|熟悉)([^，。；？！?]{1,24})"),
        ("needs_support", r"(?:我|本人)(?:不会|不太会|看不懂|没学过)([^，。；？！?]{1,24})"),
    )
    for claim, pattern in patterns:
        for match in re.finditer(pattern, text):
            topic = match.group(1).strip(" ，。；")
            if topic:
                claims.append(
                    {
                        "type": "knowledge_self_report",
                        "subject": topic[:80],
                        "claim": claim,
                        "verification_state": "unverified",
                    }
                )
    return claims[:6]


def _response_preferences(text: str) -> dict[str, str]:
    lowered = text.lower()
    preferences: dict[str, str] = {}
    if _contains_any(lowered, ("简单讲", "简洁", "一句话", "精简")):
        preferences["style"] = "concise"
    elif _contains_any(lowered, ("详细", "讲慢", "一步一步", "分步骤")):
        preferences["style"] = "step_by_step"
    elif _contains_any(lowered, ("案例", "举例", "例子")):
        preferences["style"] = "case_based"
    if "视频" in lowered:
        preferences["delivery"] = "video"
    elif _contains_any(lowered, ("图文", "文字", "文档")):
        preferences["delivery"] = "text"
    return preferences


def _is_learning_context_update(text: str) -> bool:
    """是否为已有项目内的学习上下文更新（路径偏好/自述/时间约束）。

    对齐原 server 的 `_is_learning_context_update` 直连信号，并保留新模块
    新增的 视频/图文/简单讲 等表达。仅当 has_project=True 时才参与意图判定，
    避免把新建目标误判为上下文更新。
    """
    lowered = str(text or "").lower()
    direct_signals = (
        "每天", "每周", "只能学", "有时间", "没时间", "学习时间", "学习时长",
        "太难", "太简单", "看不懂", "跟不上", "想先学", "先跳过", "从第",
        "喜欢案例", "先看案例", "案例优先", "多举例", "讲慢", "讲快", "详细一点", "简单一点",
        "有基础", "零基础", "没学过", "不会", "视频", "图文", "简单讲",
    )
    if any(signal in lowered for signal in direct_signals):
        return True
    self_report_patterns = (
        r"(?:我|本人)[^，。；？?]{0,16}(?:已经会|会了|学过|没学过|不会|不太会|有基础|零基础)",
        r"(?:这个|这部分|这章)[^，。；？?]{0,8}(?:我会|我不会|学过|没学过)",
    )
    return any(re.search(pattern, lowered) for pattern in self_report_patterns)


def understand_turn(
    message: str,
    *,
    has_project: bool = False,
    has_goal_draft: bool = False,
) -> dict[str, Any]:
    """返回不含执行权限的结构化对话理解结果。"""
    text = " ".join(str(message or "").split())
    lowered = text.lower()
    subject = _subject(text)
    scope = _learning_scope(text, subject)
    question_markers = (
        "什么", "哪些", "怎么", "如何", "为什么", "区别", "是否", "能否",
        "吗", "么", "？", "?", "报错", "错误", "用法", "介绍", "解释",
    )
    is_question = _contains_any(lowered, question_markers)
    goal_markers = (
        "我想", "我要", "希望", "计划", "准备", "想学", "学习", "掌握",
        "入门", "提升", "备考", "备战", "实训", "项目", "规划", "制定路径", "补", "需要",
        "随便学", "学点",
        "大赛", "比赛", "竞赛", "备赛", "考证", "考试", "岗位", "求职", "转行",
    )
    has_goal_signal = _contains_any(lowered, goal_markers)
    general_markers = (
        "上网搜索", "联网搜索", "网上查", "搜索一下", "帮我查", "查找资料",
        "总结一下", "帮我总结", "对比一下", "翻译一下", "帮我翻译", "翻译成",
        "帮我润色", "帮我改写", "帮我写", "写一份", "列出", "提取", "整理",
    )
    command_map = (
        ("start_assessment", ("开始测评", "能力测评", "重新测评", "做测评", "测一下", "诊断一下")),
        ("show_path", ("查看学习路径", "学习路径", "课程安排", "学习计划", "下一步学什么")),
        ("open_lesson", ("开始学习", "继续学习", "打开课程", "打开章节", "学习章节", "下一课")),
    )
    primary_intent = ""
    for intent, markers in command_map:
        if (
            _contains_any(lowered, markers)
            and not is_question
            and not _contains_any(lowered, general_markers)
        ):
            primary_intent = intent
            break
    if not primary_intent and _contains_any(lowered, general_markers):
        primary_intent = "general_assistant"
    # “随便学点什么”里的“什么”不是知识问答。没有明确主题的学习意愿
    # 应进入目标澄清，避免直接按泛用聊天回答。
    if not primary_intent and is_question and not (has_goal_signal and not subject):
        primary_intent = "knowledge_question" if (subject or has_project or has_goal_draft) else "general_assistant"
    has_context_update = has_project and _is_learning_context_update(text)
    if not primary_intent and has_context_update:
        primary_intent = "update_learning_context"
    if not primary_intent and has_goal_signal:
        primary_intent = "create_project"
    if not primary_intent:
        primary_intent = "clarify_intent" if len(text) <= 4 else "general_assistant"

    secondary_intents: list[str] = []
    if has_goal_signal and primary_intent != "create_project":
        secondary_intents.append("goal_discovery")
    if has_context_update and primary_intent != "update_learning_context":
        secondary_intents.append("update_learning_context")
    if _contains_any(lowered, ("不是", "改成", "换成", "而是")) and has_project:
        secondary_intents.append("goal_or_path_correction")
    if is_question and primary_intent != "knowledge_question" and subject:
        secondary_intents.append("knowledge_question")

    freshness_required = _contains_any(lowered, ("最新", "近期", "官网", "版本", "政策"))
    clarification_needed = bool(
        primary_intent == "create_project"
        and not subject
        and not scope
    )
    confidence = 0.9 if primary_intent not in {"clarify_intent", "general_assistant"} else 0.6
    if clarification_needed:
        confidence = 0.35
    goal_type = _goal_type(text, primary_intent)
    target_outcome = _target_outcome(text) if has_goal_signal else ""
    application_scenario = _application_scenario(text)
    goal_constraints = _goal_constraints(text) if has_goal_signal else {}
    goal_missing_information: list[str] = []
    if has_goal_signal:
        if not subject:
            goal_missing_information.append("learning_subject")
        if not target_outcome and goal_type in {"project", "job", "certification", "competition"}:
            goal_missing_information.append("target_outcome")
        if not _current_level(text):
            goal_missing_information.append("current_level")
        if not goal_constraints.get("daily_time") and not goal_constraints.get("weekly_time"):
            goal_missing_information.append("time_budget")
    return {
        "schema_version": 1,
        "primary_intent": primary_intent if primary_intent in PRIMARY_INTENTS else "clarify_intent",
        "secondary_intents": secondary_intents,
        "topic": {"subject": subject, "learning_scope": scope},
        "goal": {
            "goal_type": goal_type,
            "target_outcome": target_outcome,
            "application_scenario": application_scenario,
            "constraints": goal_constraints,
            "missing_information": goal_missing_information,
        },
        "learner_claims": _learner_claims(text, subject),
        "response_preferences": _response_preferences(text),
        "knowledge_request": {
            "needs_answer": primary_intent == "knowledge_question" or "knowledge_question" in secondary_intents,
            "freshness_required": freshness_required,
        },
        "correction_requested": "goal_or_path_correction" in secondary_intents,
        "confidence": confidence,
        "missing_information": ["learning_subject"] if clarification_needed else [],
    }
