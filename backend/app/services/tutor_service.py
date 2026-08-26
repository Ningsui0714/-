from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.learning import (
    AgentSession, AgentMessage, AgentAction, EvidenceEvent, LearningProjectProposal,
)
from app.models.project import Project, Source, Roadmap, Checkpoint, Task
from app.schemas.agent import TutorModelOutput
from app.services.action_board import ACTION_BOARD, definition
from app.services.learning_runtime import (
    record_event, apply_semantic_observations,
    get_kernel_projection, get_state_summary, evaluate_checkpoint_status,
)
from app.services.project_proposals import (
    evolve_project_proposal, get_latest_active_proposal, list_session_proposals,
    proposal_view, start_resource_search,
)
from app.services.checkpoint_context import build_checkpoint_tutor_context


CONFIRM_WORDS = {
    "好", "好的", "可以", "是", "确认", "就这个", "开始", "执行", "进入",
    "确认路线", "确认这个路线", "确认学习路线", "选它", "创建吧", "加进去",
    "yes", "ok", "okay", "do it",
}
CREATE_RE = re.compile(
    r"(?:创建|新建|建立|帮我建|建)(?:一个|个)?(?:关于|学习)?\s*[「『\"']?"
    r"([^，。,.!?！？\n]{1,48}?)[」』\"']?\s*(?:的)?项目"
)
URL_RE = re.compile(r"https?://[^\s，。!?！？)\]}>]+", re.I)
ADD_SOURCE_HINTS = ("添加", "加入", "加到", "加进", "导入", "作为来源", "作为资料")
TUTOR_SYSTEM_PROMPT = """你是 LearnFlow 中常驻的学习 Tutor。你可以处理任何学习相关对话，而不只是规划路线。

你的教学判断同时考虑五类内部信息：当前学习位置与项目结构、知识理解与误解、情绪负荷与偏好、目标价值、独立实践能力。不要向用户提及这些内部分类、Kernel、路由分数、JSON 或工具名。

回复原则：
1. 先直接回应用户当前问题，再按需要给一个小例子、类比、延伸或检查问题。
2. 不要把每次对话都变成问卷、考试或创建项目的推销。
3. 讲解、讲义和题目不是掌握证据；不要因为用户说“懂了”就断言已掌握。
4. 感到用户吃力时缩短步骤、降低一次信息量；已有基础时直接进入关键差异和实践。
5. 同时区分当前要解决的短期问题和值得持续推进的长期目标。明确产物、多步骤目标、系统学习诉求或持续讨论应形成项目机会；单次事实问答不要提项目。
6. 每次最多给一个明确下一步。
7. 在项目会话中，你是这个学习项目持续负责的 Tutor：资料选择、正式路线规划、阶段推进和零散问题都由你承接，并保持同一份项目上下文。
8. 正式路线必须主要依据已接入来源、学习画像和对话中确认的信息；项目提案里的阶段预览只能作为低权重参考。
9. 项目 Tutor 是课前、课后与路线协商入口，不是正式课堂。可以简短回答具体疑问，但不要在聊天中连续展开完整讲义、整套课程或多步骤作业。
10. 正式学习内容必须进入路线关卡：讲义、练习、代码任务和验证都由对应关卡承载。用户说“开始”或“继续”时，应先完成路线确认或进入关卡，不能直接在聊天里发一份练习代替关卡。
11. 用户要求调整阶段、增删关卡或改变节奏时，先生成路线修订方案；确认后再写入正式路线。聊天中的路线描述本身不算已建立路线。
12. 严格区分结构观察与知识观察：结构只记录学习者位于哪条路径、哪个阶段、依赖什么、为何转向以及回来时从哪里继续；知识只记录某个具体知识点的理解程度、待解疑问、明确误解与验证结果。学习目标属于价值，学习负荷属于人因，实践产物属于实践。
13. 普通疑问或答错只能形成知识缺口，不能自动写成“误解”。只有用户明确表达了可指出其错误之处的具体理解，或评估证据诊断出稳定错误模式时，才记录 misconceptions。两个维度需要联动时，用检查点、概念或证据引用关联，不在两个维度重复同一段判断。

严格返回结构化结果。reply 是给用户看的自然中文；observations 只记录本轮可由用户输入支持的短期观察，不能写长期掌握。结构观察只可使用 path_position、path_dependencies、resume_anchor、focus_transition、deferred_threads、navigation_blocker；知识观察只可使用 concept_understanding、knowledge_gap、pending_question、misconceptions、active_concepts、recent_errors。learning_intent 要分开 immediate_need、long_term_goal 和 artifact_intent；project_opportunity 仅在确实值得持续跟踪时填写。已有项目提案时，relevant_proposal_key 应指向本轮信息真正影响的提案。major_event_candidates 只允许记录用户用第一人称明确确定的职业理想；探索、疑问、假设或替别人描述时必须为空，置信度必须至少 0.90。只有在 checkpoint 会话中，且任务确实需要修改或测试共享项目文件时，才可设置 local_agent_task.should_delegate=true；只描述任务类型、目标、约束与能力，不选择 Agent、不拼接命令，也不要声称已经启动。"""

GLOBAL_MAIN_AGENT_PROMPT = """当前是 global 主 Agent 会话。你的主要职责是帮助学习者：
- 梳理学习方向、目标价值与优先级，尤其接住“我不知道学什么、怎么选、是否适合”的迷茫；
- 对简单知识问题做简明概述、类比或最小示例，但不代替某个项目里的系统教学；
- 关注挫败、焦虑、负荷和节奏，用教师式支持帮助用户恢复可行动状态，不做医学诊断；
- 识别值得长期推进的目标，维护项目提案，并在用户明确授权时创建或进入项目。

项目列表、最近活跃项目、关卡位置以及结构/知识短期记忆都只是理解学习者的参考，不代表你正在负责那个项目。不要自称某个项目的负责人，不要主动续接某个项目的当前关卡、路线、来源或课前后辅导，也不要把最近活跃项目当作本轮默认主题。涉及正式路线、关卡学习、深入练习或项目推进时，说明应由对应项目 Tutor 或关卡承接。除非用户明确要求操作某个项目，否则保持全局视角。"""

PROJECT_TUTOR_PROMPT = """当前是 project 项目 Tutor 会话。你只负责当前绑定项目，并持续承接它的来源、正式路线、路线修订、阶段推进和课前后答疑。其他项目及全局记忆只能作为背景参考，不能替换当前项目上下文。正式教学与验证必须落入路线关卡。"""

CHECKPOINT_TUTOR_PROMPT = """当前是 checkpoint 关卡 Tutor 会话。你只负责当前绑定关卡，并在本关讲义、练习和项目文件之间保持同一段会话历史。
- 学习设计与实践验证是你按需调用的内部能力，不要把自己切换或介绍成另一个主 Agent。
- 只使用当前关卡上下文；不要引用其他关卡的讲义、练习或聊天。
- 文件树只表示文件存在。需要正文时必须按需读取，不得假设内容。
- 官方讲义和练习由数据库领域能力维护；不得用普通文件写入绕过版本、测试、答案或判题保护。
- 可以把明确的项目代码修改或测试委派给已配置的本地代码 Agent。它是工具而非第四类主 Agent；由 Broker 确定性选择配置，用户确认后才在隔离副本启动，结果再次确认后才写回。
- 编辑文件或运行成功不代表掌握；只有正式判题结果可以形成掌握证据。
- 回答围绕用户当前选中的讲义、练习或文件，最多给一个明确下一步。"""


def _normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _extract_url(message: str) -> str | None:
    match = URL_RE.search(message)
    return _normalize_url(match.group(0).rstrip(".,;:")) if match else None


def _decode_tutor_content(
    content: str,
) -> tuple[str, list[dict], dict | None, dict | None, list[dict], dict | None]:
    """Unwrap JSON returned by models that ignore the structured-output request."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    payload: Any = None
    decoder = json.JSONDecoder()
    candidates = [text]
    object_start = text.find("{")
    if object_start > 0:
        candidates.append(text[object_start:])
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate)
            break
        except json.JSONDecodeError:
            continue

    if isinstance(payload, dict) and isinstance(payload.get("reply"), str):
        observations = payload.get("observations")
        opportunity = payload.get("project_opportunity")
        learning_intent = payload.get("learning_intent")
        major_events = payload.get("major_event_candidates")
        local_agent_task = payload.get("local_agent_task")
        return (
            payload["reply"].strip(),
            [item for item in observations if isinstance(item, dict)] if isinstance(observations, list) else [],
            opportunity if isinstance(opportunity, dict) else None,
            learning_intent if isinstance(learning_intent, dict) else None,
            [item for item in major_events if isinstance(item, dict)] if isinstance(major_events, list) else [],
            local_agent_task if isinstance(local_agent_task, dict) else None,
        )
    return text, [], None, None, [], None


def _extract_project_name(message: str) -> str | None:
    match = CREATE_RE.search(message)
    if not match:
        return None
    name = match.group(1).strip(" ，。,.!?！？:：")
    if name in {"", "学习", "一个", "个"}:
        return None
    return name[:80]


def _is_confirmation(message: str) -> bool:
    normalized = message.strip().lower().rstrip("。.!！")
    if normalized in CONFIRM_WORDS:
        return True
    # Project Tutor often asks for a natural-language confirmation such as
    # “我确认这条路线” or “好的，采用这个方案”. Treat only short, explicit
    # route/plan confirmations as confirmations; ordinary questions remain chat.
    if len(normalized) <= 32 and any(word in normalized for word in ("确认", "同意", "采用")) and any(
        word in normalized for word in ("路线", "方案", "安排", "计划")
    ):
        return True
    return any(
        normalized.startswith(prefix) for prefix in ("就按", "按这个", "用这个", "选第")
    )


def _is_project_proposal_confirmation(message: str) -> bool:
    """Accept continuation wording only at the project-proposal boundary.

    "继续" is deliberately not a general confirmation word: inside a project it means
    resume the learning path.  In a global session with a ready proposal, however,
    it is the explicit handoff the UI and Tutor invite the learner to make.
    """
    normalized = message.strip().lower().rstrip("。.!！")
    return _is_confirmation(message) or normalized in {"继续", "继续吧"}


def _looks_like_create_command(message: str) -> bool:
    return bool(CREATE_RE.search(message)) or bool(re.search(r"(?:创建|新建|建立).{0,8}项目", message))


def _looks_like_source_command(message: str) -> bool:
    return any(word in message for word in ADD_SOURCE_HINTS) and (
        bool(_extract_url(message))
        or any(word in message for word in ("来源", "链接", "网址", "资料", "这个"))
    )


def _looks_like_route_command(message: str) -> bool:
    return any(word in message for word in (
        "规划路线", "制定路线", "学习路径", "安排学习路线", "修改路线",
        "调整路线", "更改路线", "重排路线", "路线改成", "增加关卡",
        "新增关卡", "删除关卡", "加一关", "删掉一关",
    ))


def _looks_like_apply_route_command(message: str) -> bool:
    return any(word in message for word in (
        "按这个路线", "按此路线", "采用这个路线", "应用这个路线",
        "建立这条路线", "就按这个学习路径",
    ))


def _looks_like_advance_command(message: str) -> bool:
    return any(word in message for word in ("推进下一关", "进入下一关", "开始下一关", "下一关"))


def _looks_like_lecture_command(message: str) -> bool:
    return "讲义" in message and any(word in message for word in ("生成", "写", "做", "开始"))


def _looks_like_assessment_command(message: str) -> bool:
    return any(word in message for word in ("生成题目", "出题", "自测", "练习题", "生成练习"))


def _looks_like_local_agent_delegation(message: str) -> bool:
    normalized = message.casefold()
    actor = any(token in normalized for token in (
        "本地agent", "本地 agent", "代码agent", "代码 agent", "codex", "子agent", "子 agent",
    ))
    task = any(token in normalized for token in (
        "修改", "实现", "修复", "重构", "测试", "写代码", "构建", "补全", "文档",
    ))
    delegation = any(token in normalized for token in ("让", "交给", "委派", "调用", "请"))
    return actor and task and delegation


def _local_agent_task_type(message: str) -> str:
    if any(token in message for token in ("修复", "bug", "报错")):
        return "bug_fix"
    if "重构" in message:
        return "refactor"
    if any(token in message for token in ("测试", "test")):
        return "test"
    if any(token in message for token in ("文档", "README", "说明")):
        return "documentation"
    return "code_change"


def _learning_flow(session: AgentSession) -> dict[str, Any]:
    return dict((session.context_summary or {}).get("learning_flow") or {})


def _set_learning_flow(session: AgentSession, **patch: Any) -> None:
    summary = dict(session.context_summary or {})
    flow = dict(summary.get("learning_flow") or {})
    flow.update(patch)
    flow["updated_at"] = datetime.utcnow().isoformat()
    session.context_summary = {**summary, "learning_flow": flow}


def _looks_like_roadmap_intake_answer(message: str) -> bool:
    """Recognize a compact answer to route-planning intake, not a quiz answer."""
    text = message.strip().lower()
    if not text:
        return False
    if re.search(r"(?:^|\s|[，,；;])a[.：:]?.*(?:\s|[，,；;])b[.：:]?.*(?:\s|[，,；;])c[.：:]?", text, re.S):
        return True
    categories = (
        ("pytorch", "没用过", "写过模型", "训练循环", "编程基础", "python 基础", "cs61a"),
        ("transformer", "自注意力", "多头注意力", "张量形状", "shape", "掩码", "缩放"),
        ("gpu", "cpu", "colab", "云环境", "本机", "租卡", "租 gpu"),
        ("每周", "小时", "投入时间", "学习节奏", "周末"),
        ("跑通闭环", "扩展功能", "完整测试", "最终产物", "仓库", "验收"),
    )
    return sum(any(token in text for token in group) for group in categories) >= 2


def _looks_like_project_start(message: str) -> bool:
    normalized = message.strip().lower().rstrip("。.!！")
    return normalized in {
        "开始", "开始学习", "开始吧", "继续", "继续学习", "继续吧",
        "从第一关开始", "进入第一关", "开始第一关",
    } or any(phrase in normalized for phrase in (
        "直接进入关卡", "进入关卡学习", "开始关卡学习", "进入正式关卡",
        "开始正式学习", "按关卡学习",
    ))


async def _has_recent_roadmap_proposal(
    db: AsyncSession,
    session: AgentSession,
) -> bool:
    messages = list((await db.execute(
        select(AgentMessage)
        .where(
            AgentMessage.session_id == session.id,
            AgentMessage.role == "assistant",
        )
        .order_by(AgentMessage.id.desc())
        .limit(12)
    )).scalars().all())
    for item in messages:
        content = _decode_tutor_content(item.content)[0]
        if "确认后生效" in content:
            return True
        if (
            any(marker in content for marker in ("正式学习路线", "正式路线提案"))
            and any(marker in content for marker in ("阶段", "关卡"))
            and "确认" in content
        ):
            return True
        # The Tutor is allowed to phrase the proposal naturally. Once the
        # immediately recent assistant message both presents a route and asks
        # for confirmation, the next explicit confirmation must enter the
        # deterministic apply action instead of falling back to free chat.
        if "路线" in content and "确认" in content and any(
            marker in content for marker in ("关卡", "阶段", "建立", "生效", "生成")
        ):
            return True
    return False


def _claims_roadmap_was_applied(message: str) -> bool:
    return any(marker in message for marker in (
        "正式路线已生效", "正式路线已经生效", "路线已保存", "路线已经保存",
        "路线已写入", "路线已经写入", "路线已建立", "路线已经建立",
        "正式路线已建立", "正式路线已经建立", "路线已生成", "路线已经生成",
        "学习路线已生成", "学习路线已经生成",
    ))


async def _effective_learning_flow_phase(
    db: AsyncSession,
    session: AgentSession,
) -> str:
    phase = str(_learning_flow(session).get("phase") or "")
    if not session.project_id:
        return phase
    checkpoint_id = (await db.execute(
        select(Checkpoint.id)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Project.id == session.project_id,
            Project.learner_id == session.learner_id,
            Checkpoint.archived.is_(False),
        )
        .limit(1)
    )).scalar_one_or_none()
    if checkpoint_id:
        _set_learning_flow(session, phase="roadmap_ready")
        return "roadmap_ready"
    return phase


async def _first_open_checkpoint(
    db: AsyncSession,
    session: AgentSession,
) -> Checkpoint | None:
    if not session.project_id:
        return None
    return (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Project.id == session.project_id,
            Project.learner_id == session.learner_id,
            Checkpoint.archived.is_(False),
            or_(
                Checkpoint.learning_status.is_(None),
                Checkpoint.learning_status != "completed",
            ),
        )
        .order_by(Checkpoint.order)
        .limit(1)
    )).scalar_one_or_none()


async def _enter_checkpoint(
    db: AsyncSession,
    action: AgentAction,
    session: AgentSession,
    checkpoint: Checkpoint,
    project_id: int | None,
    *,
    entry_mode: str,
) -> dict[str, Any]:
    """Enter a verified checkpoint through the single navigation event path.

    Applying a confirmed roadmap is allowed to make this context-only handoff
    automatically.  It deliberately does not generate a lecture or assessment:
    those artifact-producing actions remain learner-controlled after arrival.
    """
    if project_id:
        _bind_project_session(session, project_id, checkpoint.id)
        _record_session_handoff(session, project_id, {
            **dict(action.target or {}),
            "checkpoint_id": checkpoint.id,
            "entry_mode": entry_mode,
        })
    action.project_id = project_id
    action.checkpoint_id = checkpoint.id
    if checkpoint.learning_status in (None, "", "not_started"):
        checkpoint.learning_status = "in_progress"
    await record_event(
        db, event_type="checkpoint_entered", source="tutor_tool",
        learner_id=action.learner_id,
        project_id=project_id, checkpoint_id=checkpoint.id, session_id=session.id,
        payload={"title": checkpoint.title, "entry_mode": entry_mode},
        provenance={
            "action_id": action.id,
            "trigger_capability": action.capability,
            "entry_mode": entry_mode,
        },
        client_event_id=f"action:{action.id}:checkpoint:{checkpoint.id}:entered",
    )
    return {
        "checkpoint": {"id": checkpoint.id, "title": checkpoint.title},
        "entry_mode": entry_mode,
    }


async def _ensure_project_welcome_message(
    db: AsyncSession,
    session: AgentSession,
) -> None:
    if session.session_type != "project" or not session.project_id:
        return
    idempotency_key = f"project-welcome:{session.id}"
    exists = (await db.execute(select(AgentMessage.id).where(
        AgentMessage.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if exists:
        return

    project = (await db.execute(select(Project).where(
        Project.id == session.project_id,
        Project.learner_id == session.learner_id,
    ))).scalar_one_or_none()
    if not project:
        return
    sources = list((await db.execute(
        select(Source).where(Source.project_id == project.id).order_by(Source.id)
    )).scalars().all())
    checkpoints = list((await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .where(Roadmap.project_id == project.id, Checkpoint.archived.is_(False))
        .order_by(Checkpoint.order)
    )).scalars().all())
    proposal = (await db.execute(
        select(LearningProjectProposal).where(
            LearningProjectProposal.accepted_project_id == project.id,
            LearningProjectProposal.learner_id == session.learner_id,
            LearningProjectProposal.status == "accepted",
        ).order_by(LearningProjectProposal.updated_at.desc()).limit(1)
    )).scalar_one_or_none()

    processed_count = sum(source.status == "processed" for source in sources)
    completed_count = sum(
        checkpoint.learning_status == "completed" for checkpoint in checkpoints
    )
    paragraphs = [
        f"我会负责「{project.name}」的资料选择、正式路线规划和课前后辅导。"
        "项目里的小问题也都直接在这里问；正式讲义、练习和验证会进入路线关卡，"
        "我会沿用同一份项目上下文陪你推进。"
    ]
    if checkpoints:
        paragraphs.append(
            f"当前正式路线有 {len(checkpoints)} 个阶段，已验证 {completed_count} 个。"
            "你可以从当前阶段继续，也可以先让我调整路线或解释一个具体问题。"
        )
    elif processed_count:
        paragraphs.append(
            f"目前已有 {processed_count} 个可用来源。下一步我会结合这些来源、你的学习画像，"
            "以及我们在对话里确认的起点和投入，形成正式学习路线。"
        )
    elif proposal:
        paragraphs.append(
            "我们先把资料基础定下来，再确认你的起点和投入，随后生成正式学习路线。"
        )
    else:
        paragraphs.append("我们先确认学习目标、当前起点和可用资料，再规划正式路线。")
    if proposal:
        paragraphs.append(
            "下面是我按项目目标筛选的候选来源。你可以直接添加，也可以让我重新检索。"
        )

    meta_data: dict[str, Any] = {
        "message_kind": "project_welcome",
        "project_owner": True,
        "project_id": project.id,
    }
    if proposal:
        meta_data["attachment"] = {
            "type": "candidate_sources",
            "proposal_id": proposal.id,
        }
    statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="assistant",
        content="\n\n".join(paragraphs),
        meta_data=meta_data,
        idempotency_key=idempotency_key,
        created_at=datetime.utcnow(),
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    await db.execute(statement)


async def get_or_create_session(
    db: AsyncSession,
    *,
    learner_id: int,
    session_type: str = "global",
    project_id: int | None = None,
    checkpoint_id: int | None = None,
) -> AgentSession:
    query = select(AgentSession).where(
        AgentSession.learner_id == learner_id,
        AgentSession.session_type == session_type,
        AgentSession.status == "active",
    )
    if session_type == "checkpoint":
        if not project_id or not checkpoint_id:
            raise ValueError("checkpoint session requires project_id and checkpoint_id")
        query = query.where(
            AgentSession.project_id == project_id,
            AgentSession.checkpoint_id == checkpoint_id,
        )
    elif session_type == "project":
        query = query.where(AgentSession.project_id == project_id)
    else:
        query = query.where(AgentSession.project_id.is_(None))
    session = (await db.execute(
        query.order_by(AgentSession.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not session:
        context_summary = {}
        if session_type == "project" and project_id:
            global_session = (await db.execute(select(AgentSession).where(
                AgentSession.learner_id == learner_id,
                AgentSession.session_type == "global",
                AgentSession.project_id.is_(None),
                AgentSession.status == "active",
            ).order_by(AgentSession.updated_at.desc()).limit(1))).scalar_one_or_none()
            if global_session:
                handoff = dict((global_session.context_summary or {}).get("handoff") or {})
                if handoff.get("project_id") not in {None, project_id}:
                    handoff = {}
                message_refs = list(handoff.get("message_refs") or [])
                evidence_refs = list(handoff.get("evidence_refs") or [])
                if not message_refs:
                    message_refs = list(reversed((await db.execute(
                        select(AgentMessage.id).where(
                            AgentMessage.session_id == global_session.id
                        ).order_by(AgentMessage.id.desc()).limit(12)
                    )).scalars().all()))
                context_summary = {
                    "handoff": {
                        **handoff,
                        "from_session_id": global_session.id,
                        "message_refs": message_refs,
                        "evidence_refs": evidence_refs,
                        "project_id": project_id,
                    }
                }
        session = AgentSession(
            learner_id=learner_id,
            session_type=session_type,
            project_id=project_id,
            checkpoint_id=checkpoint_id,
            title=(
                "关卡 Tutor" if session_type == "checkpoint"
                else "项目 Tutor" if project_id else "学习 Tutor"
            ),
            status="active",
            context_summary=context_summary,
        )
        db.add(session)
        await db.flush()
    await _ensure_project_welcome_message(db, session)
    return session


async def get_messages(db: AsyncSession, session_id: int, limit: int = 100) -> list[AgentMessage]:
    rows = (await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.id.desc())
        .limit(limit)
    )).scalars().all()
    return list(reversed(rows))


def action_card(action: AgentAction | None) -> dict | None:
    if not action:
        return None
    spec = ACTION_BOARD.get(action.capability)
    target = dict(action.target or {})
    reason = target.get("reason", "")
    expected = target.get("expected_result", "")
    public_keys = {
        "name", "project_name", "description", "url", "mode",
        "initial_concepts", "practice_artifact", "goal",
        "task_type", "profile_name", "adapter", "sandbox_policy",
        "network_policy", "network_boundary_enforced", "excluded_paths",
    }
    primary_label = "确认" if action.status == "pending_confirmation" else "查看结果"
    if action.capability == "apply_learning_path" and action.status == "pending_confirmation":
        primary_label = "确认并生成关卡图"
    return {
        "id": action.id,
        "title": spec.title if spec else action.capability,
        "reason": reason,
        "expected_result": expected,
        "status": action.status,
        "requires_confirmation": action.status == "pending_confirmation",
        "primary_label": primary_label,
        "target_summary": {key: value for key, value in target.items() if key in public_keys and value},
        "task_id": action.task_id,
        "result": action.result or {},
        "error": action.error or {},
    }


def action_result(action: AgentAction | None) -> dict | None:
    if not action:
        return None
    return action_card(action)


async def _new_action(
    db: AsyncSession,
    session: AgentSession,
    capability: str,
    target: dict,
    status: str,
) -> AgentAction:
    spec = definition(capability)
    action = AgentAction(
        session_id=session.id,
        learner_id=session.learner_id,
        project_id=session.project_id,
        checkpoint_id=session.checkpoint_id,
        capability=capability,
        status=status,
        side_effect=spec.side_effect,
        confirmation_policy=spec.confirmation_policy,
        target=target,
        evidence_target=spec.evidence_target,
        next_affordances=list(spec.next_affordances),
    )
    db.add(action)
    await db.flush()
    if status in {"pending_confirmation", "needs_input"}:
        session.pending_action_id = action.id
    return action


async def _active_context_ids(
    db: AsyncSession,
    session: AgentSession,
) -> tuple[int | None, int | None]:
    project_id = session.project_id
    checkpoint_id = session.checkpoint_id
    if project_id and checkpoint_id:
        return project_id, checkpoint_id
    projection = await get_kernel_projection(db, session.learner_id)
    structure = projection.get("structure", {}).get("short_term", {})
    return (
        project_id or structure.get("active_project_id"),
        checkpoint_id or structure.get("active_checkpoint_id"),
    )


async def get_session_state_summary(
    db: AsyncSession,
    session: AgentSession,
) -> dict:
    """Return UI state without presenting remembered projects as global scope."""
    state = await get_state_summary(
        db,
        session.project_id if session.session_type in {"project", "checkpoint"} else None,
        session.checkpoint_id if session.session_type == "checkpoint" else None,
        learner_id=session.learner_id,
    )
    if session.session_type == "checkpoint":
        return {**state, "session_scope": "checkpoint", "tutor_role": "checkpoint_tutor"}
    if session.session_type == "project":
        return {**state, "session_scope": "project", "tutor_role": "project_tutor"}

    referenced_project = state.get("active_project")
    referenced_checkpoint = state.get("active_checkpoint")
    return {
        **state,
        "stage": "全局学习规划",
        "session_scope": "global",
        "tutor_role": "main_agent",
        "active_project": None,
        "active_checkpoint": None,
        "progress": {"total": 0, "completed": 0, "verification_due": 0},
        "referenced_project": referenced_project,
        "referenced_checkpoint": referenced_checkpoint,
    }


def _bind_project_session(
    session: AgentSession,
    project_id: int,
    checkpoint_id: int | None = None,
):
    if session.session_type != "project":
        return
    session.project_id = project_id
    session.checkpoint_id = checkpoint_id


def _record_session_handoff(session: AgentSession, project_id: int, target: dict):
    if session.session_type != "global":
        return
    session.context_summary = {
        **dict(session.context_summary or {}),
        "active_project_id": project_id,
        "handoff": {
            "project_id": project_id,
            "message_refs": list(target.get("context_message_ids") or []),
            "evidence_refs": list(target.get("context_evidence_ids") or []),
            "goal": target.get("goal") or target.get("description") or "",
            "initial_concepts": list(target.get("initial_concepts") or []),
            "practice_artifact": target.get("practice_artifact") or "",
        },
    }


async def _project_for_context(db: AsyncSession, session: AgentSession, project_id: int | None = None) -> Project | None:
    active_project_id, _ = await _active_context_ids(db, session)
    candidate = project_id or active_project_id
    if not candidate:
        return None
    return (await db.execute(select(Project).where(
        Project.id == candidate,
        Project.learner_id == session.learner_id,
    ))).scalar_one_or_none()


async def _checkpoint_for_learner(
    db: AsyncSession, learner_id: int, checkpoint_id: int | None,
) -> Checkpoint | None:
    if not checkpoint_id:
        return None
    return (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Checkpoint.id == checkpoint_id,
            Project.learner_id == learner_id,
        )
    )).scalar_one_or_none()


async def _project_named_in_message(
    db: AsyncSession, learner_id: int, message: str,
) -> Project | None:
    matches = await _projects_named_in_message(db, learner_id, message)
    return matches[0] if len(matches) == 1 else None


async def _projects_named_in_message(
    db: AsyncSession, learner_id: int, message: str,
) -> list[Project]:
    projects = (await db.execute(select(Project).where(
        Project.learner_id == learner_id,
    ).order_by(Project.id))).scalars().all()
    normalized = message.lower().replace("「", "").replace("」", "")
    return [project for project in projects if project.name.lower() in normalized]


def _project_choice(message: str, candidates: list[dict]) -> int | None:
    if not candidates:
        return None
    candidate_ids = [int(item["id"]) for item in candidates]
    id_match = re.search(r"(?:项目|id)\s*[:：#]?\s*(\d+)", message, re.I)
    if id_match and int(id_match.group(1)) in candidate_ids:
        return int(id_match.group(1))
    numbers = [int(value) for value in re.findall(r"\d+", message)]
    for number in numbers:
        if 1 <= number <= len(candidate_ids):
            return candidate_ids[number - 1]
    ordinal_words = {"第一个": 0, "第1个": 0, "第二个": 1, "第三个": 2}
    for word, index in ordinal_words.items():
        if word in message and index < len(candidate_ids):
            return candidate_ids[index]
    return None


def _project_choice_prompt(candidates: list[dict]) -> str:
    if not candidates:
        return "要使用哪个学习项目？"
    options = "、".join(
        f"选项 {index}：{item['name']}（ID {item['id']}）"
        for index, item in enumerate(candidates, start=1)
    )
    return f"找到多个同名项目，请选一次：{options}。"


async def search_learning_projects(
    db: AsyncSession, learner_id: int, message: str,
) -> list[Project]:
    """Local, read-only project matching used before proposing new work."""
    projects = (await db.execute(
        select(Project).where(Project.learner_id == learner_id).order_by(Project.updated_at.desc())
    )).scalars().all()
    normalized = re.sub(r"\s+", "", message).lower()
    ranked: list[tuple[int, Project]] = []
    for project in projects:
        name = re.sub(r"\s+", "", project.name).lower()
        description = re.sub(r"\s+", "", project.description or "").lower()
        score = 100 if name and name in normalized else 0
        if not score and name and len(name) >= 2:
            overlap = sum(1 for char in set(name) if char in normalized)
            score = int(60 * overlap / len(set(name)))
        if description and any(token in description for token in re.findall(r"[A-Za-z0-9+#.-]{2,}", normalized)):
            score += 10
        if score >= 45:
            ranked.append((score, project))
    ranked.sort(key=lambda item: (item[0], item[1].updated_at or datetime.min), reverse=True)
    return [project for _, project in ranked[:5]]


def draft_learning_project(message: str, opportunity: dict | None) -> dict:
    """Build a side-effect-free project draft for the confirmation card."""
    data = opportunity or {}
    title = str(data.get("title") or "").strip()
    if not title:
        title = re.sub(r"[？?。！!]", "", message).strip()[:24]
    concepts = [
        str(value).strip()[:80]
        for value in list(data.get("initial_concepts") or [])[:8]
        if str(value).strip()
    ]
    return {
        "name": title,
        "description": data.get("description") or message[:500],
        "goal": message[:500],
        "initial_concepts": concepts,
        "practice_artifact": str(
            data.get("practice_artifact")
            or "一份可以独立检查结果的练习或项目产物"
        )[:240],
        "reason": data.get("reason") or "这个目标适合持续跟踪和实践",
        "expected_result": "建立项目并把当前学习目标带入项目上下文",
    }


async def _create_source_task(
    db: AsyncSession,
    action: AgentAction,
    project: Project,
    url: str,
) -> tuple[Source, Task, bool]:
    normalized = _normalize_url(url)
    sources = (await db.execute(
        select(Source).where(Source.project_id == project.id)
    )).scalars().all()
    duplicate = next((s for s in sources if _normalize_url(s.url or "") == normalized), None)
    if duplicate and duplicate.status == "processed":
        return duplicate, Task(id=0, status="completed"), True
    source = duplicate
    if not source:
        source = Source(
            project_id=project.id,
            type="github" if "github.com" in url.lower() else "url",
            url=normalized,
            status="pending",
        )
        db.add(source)
        await db.flush()
        await record_event(
            db, event_type="source_added", source="tutor_tool",
            learner_id=action.learner_id,
            project_id=project.id, session_id=action.session_id,
            payload={"source_id": source.id, "url": normalized, "type": source.type},
            provenance={"action_id": action.id},
            client_event_id=f"action:{action.id}:source:{source.id}:added",
        )
    task = Task(
        learner_id=action.learner_id,
        project_id=project.id,
        type="source_ingest",
        status="queued",
        payload={"project_id": project.id, "source_id": source.id},
        progress={"current": 0, "total": 1, "message": "等待处理来源..."},
        agent_action_id=action.id,
    )
    db.add(task)
    await db.flush()
    action.task_id = task.id
    action.status = "running"
    action.result = {
        "project": {"id": project.id, "name": project.name},
        "source": {"id": source.id, "url": source.url, "status": source.status},
    }
    return source, task, False


async def execute_action(db: AsyncSession, action: AgentAction) -> str:
    if action.status == "completed" or (action.status == "running" and action.task_id is not None):
        result = dict(action.result or {})
        return result.get("user_message") or "这个行动已经在执行或已完成。"

    action.status = "running"
    action.started_at = datetime.utcnow()
    target = dict(action.target or {})
    session = await db.get(AgentSession, action.session_id)
    if not session:
        raise ValueError("Tutor 会话不存在")
    if session.learner_id != action.learner_id:
        raise ValueError("Tutor 行动归属无效")

    if action.capability == "delegate_local_agent_task":
        from app.models.project import LocalAgentProfile
        from app.services.local_agent_broker import LocalAgentError, create_run_for_action

        profile_id = target.get("profile_id")
        profile = (await db.execute(select(LocalAgentProfile).where(
            LocalAgentProfile.id == profile_id,
            LocalAgentProfile.learner_id == action.learner_id,
            LocalAgentProfile.enabled.is_(True),
        ))).scalar_one_or_none() if profile_id else None
        if not profile:
            action.status = "needs_input"
            session.pending_action_id = action.id
            await db.commit()
            return "请先在桌面版为当前账号启用一个满足任务能力的本地代码 Agent。"
        try:
            run = await create_run_for_action(db, action, profile, target)
        except LocalAgentError as exc:
            action.status = "failed"
            action.error = {"code": exc.code, "message": exc.detail}
            action.finished_at = datetime.utcnow()
            session.pending_action_id = None
            await db.commit()
            return f"本地 Agent 没有启动：{exc.detail}"
        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            "local_agent_run": {
                "id": run.id, "status": run.status, "profile_id": profile.id,
                "profile_name": profile.name, "task_type": run.task_type,
            },
            "user_message": "已在隔离副本启动本地代码 Agent；完成后会展示完整 diff，写回前还会再次确认。",
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    if action.capability in {"create_project", "bootstrap_project"}:
        name = str(target.get("name") or "").strip()
        if not name:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "这个学习项目准备聚焦什么主题？"
        project = Project(
            learner_id=action.learner_id,
            name=name[:255],
            description=str(target.get("description") or f"围绕{name}持续学习与实践"),
            user_level=str(target.get("user_level") or "beginner"),
        )
        db.add(project)
        await db.flush()
        _bind_project_session(session, project.id)
        action.project_id = project.id
        _record_session_handoff(session, project.id, target)
        await record_event(
            db, event_type="project_created", source="tutor_tool",
            learner_id=action.learner_id,
            project_id=project.id, session_id=session.id,
            payload={
                "project_id": project.id,
                "name": project.name,
                "description": project.description,
                "goal": target.get("goal") or project.description,
                "initial_concepts": list(target.get("initial_concepts") or []),
                "practice_artifact": target.get("practice_artifact") or "",
                "context_message_refs": list(target.get("context_message_ids") or []),
                "context_evidence_refs": list(target.get("context_evidence_ids") or []),
            },
            provenance={"action_id": action.id, "explicit": target.get("explicit", False)},
            client_event_id=f"action:{action.id}:project:{project.id}:created",
        )
        url = target.get("url")
        if action.capability == "bootstrap_project" and url:
            source, task, duplicate = await _create_source_task(db, action, project, url)
            if duplicate:
                action.status = "completed"
            action.result = {
                **dict(action.result or {}),
                "project": {"id": project.id, "name": project.name},
                "source": {"id": source.id, "url": source.url, "status": source.status},
                "navigate_to_project": True,
                "user_message": (
                    f"已建立并进入「{project.name}」，来源正在处理；"
                    "项目 Tutor 与路径规划 Agent 已接手。"
                    if session.session_type == "global"
                    else f"已建立并进入「{project.name}」，来源已接入并开始处理。"
                ),
            }
            session.pending_action_id = None
            await db.commit()
            if task.id:
                from app.services.task_manager import manager
                from app.services.task_runners import run_source_ingestion
                manager.submit(task.id, run_source_ingestion(task.id))
            return action.result["user_message"]

        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            "project": {"id": project.id, "name": project.name},
            "navigate_to_project": True,
            "user_message": (
                f"已建立并进入「{project.name}」，"
                "项目 Tutor 与路径规划 Agent 已接手。"
                if session.session_type == "global"
                else f"已建立并进入「{project.name}」。下一步可以添加资料，或直接告诉我你想先学什么。"
            ),
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    if action.capability == "enter_project":
        project = (await db.execute(select(Project).where(
            Project.id == target.get("project_id"),
            Project.learner_id == action.learner_id,
        ))).scalar_one_or_none() if target.get("project_id") else None
        if not project:
            action.status = "needs_input"
            session.pending_action_id = action.id
            await db.commit()
            return _project_choice_prompt(list(target.get("project_candidates") or []))
        _bind_project_session(session, project.id)
        _record_session_handoff(session, project.id, target)
        action.project_id = project.id
        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            "project": {"id": project.id, "name": project.name},
            "navigate_to_project": True,
            "user_message": (
                f"已定位到「{project.name}」。现在进入项目，由项目 Tutor 继续承接。"
                if session.session_type == "global"
                else f"已进入「{project.name}」。"
            ),
        }
        session.pending_action_id = None
        await record_event(
            db, event_type="project_selected", source="tutor_tool",
            learner_id=action.learner_id,
            project_id=project.id, session_id=session.id,
            payload={"project_id": project.id, "name": project.name},
            provenance={"action_id": action.id},
            client_event_id=f"action:{action.id}:project:{project.id}:selected",
        )
        await db.commit()
        return action.result["user_message"]

    if action.capability == "add_source":
        if target.get("project_candidates") and not target.get("project_id"):
            project = None
        else:
            project = await _project_for_context(db, session, target.get("project_id"))
        url = target.get("url")
        if not project:
            action.status = "needs_input"
            session.pending_action_id = action.id
            await db.commit()
            return _project_choice_prompt(list(target.get("project_candidates") or []))
        if not url:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "请把要添加的网页或 GitHub 链接发给我。"
        _bind_project_session(session, project.id, session.checkpoint_id)
        _record_session_handoff(session, project.id, target)
        action.project_id = project.id
        source, task, duplicate = await _create_source_task(db, action, project, url)
        session.pending_action_id = None
        if duplicate:
            action.status = "completed"
            action.finished_at = datetime.utcnow()
            action.result = {
                "project": {"id": project.id, "name": project.name},
                "source": {"id": source.id, "url": source.url, "status": source.status},
                "user_message": f"这个来源已经在「{project.name}」中，并且处理完成。",
            }
            await db.commit()
            return action.result["user_message"]
        action.result["user_message"] = f"已加入「{project.name}」，正在处理来源内容。"
        await db.commit()
        from app.services.task_manager import manager
        from app.services.task_runners import run_source_ingestion
        manager.submit(task.id, run_source_ingestion(task.id))
        return action.result["user_message"]

    if action.capability == "navigate_checkpoint":
        checkpoint_id = target.get("checkpoint_id") or session.checkpoint_id
        checkpoint = await _checkpoint_for_learner(db, action.learner_id, checkpoint_id)
        if not checkpoint:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "你想进入哪一个检查点？"
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
        project_id = roadmap.project_id if roadmap else (session.project_id or action.project_id)
        entry = await _enter_checkpoint(
            db, action, session, checkpoint, project_id,
            entry_mode=str(target.get("entry_mode") or "explicit"),
        )
        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            **entry,
            "user_message": f"已进入「{checkpoint.title}」。",
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    if action.capability == "generate_lecture":
        _, active_checkpoint_id = await _active_context_ids(db, session)
        checkpoint_id = target.get("checkpoint_id") or active_checkpoint_id
        if not checkpoint_id:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要为哪一个检查点生成讲义？"
        checkpoint = await _checkpoint_for_learner(db, action.learner_id, checkpoint_id)
        if not checkpoint:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要为哪一个检查点生成讲义？"
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        project_id = roadmap.project_id if roadmap else (session.project_id or action.project_id)
        if project_id:
            _bind_project_session(session, project_id, checkpoint_id)
            _record_session_handoff(session, project_id, target)
        action.project_id = project_id
        from app.api.phase2 import generate_lecture_task
        from app.services.auth import load_current_learner
        current = await load_current_learner(db, action.learner_id)
        response = await generate_lecture_task(checkpoint_id, db, {"mode": "fresh"}, current)
        task = await db.get(Task, response["task_id"])
        if task:
            task.agent_action_id = action.id
        action.checkpoint_id = checkpoint_id
        action.task_id = response["task_id"]
        action.status = "running"
        action.result = {
            "task_id": response["task_id"],
            "user_message": "讲义生成已启动，完成前不会把这一关标记为已掌握。",
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    if action.capability == "generate_assessment":
        _, active_checkpoint_id = await _active_context_ids(db, session)
        checkpoint_id = target.get("checkpoint_id") or active_checkpoint_id
        if not checkpoint_id:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要验证哪一个检查点？"
        checkpoint = await _checkpoint_for_learner(db, action.learner_id, checkpoint_id)
        if not checkpoint:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要验证哪一个检查点？"
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        project_id = roadmap.project_id if roadmap else (session.project_id or action.project_id)
        if project_id:
            _bind_project_session(session, project_id, checkpoint_id)
            _record_session_handoff(session, project_id, target)
        action.project_id = project_id
        mode = target.get("mode", "concept")
        from app.services.auth import load_current_learner
        current = await load_current_learner(db, action.learner_id)
        if mode == "practice":
            from app.api.phase3 import generate_exercises
            response = await generate_exercises(checkpoint_id, db, current)
        else:
            from app.api.phase3 import generate_concepts
            response = await generate_concepts(checkpoint_id, db, current)
        task = await db.get(Task, response["task_id"])
        if task:
            task.agent_action_id = action.id
        action.checkpoint_id = checkpoint_id
        action.task_id = response["task_id"]
        action.status = "running"
        action.result = {
            "task_id": response["task_id"],
            "mode": mode,
            "user_message": "验证任务已启动生成。只有你的作答或实践结果会成为学习证据。",
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    if action.capability in {"plan_learning_path", "apply_learning_path"}:
        project = await _project_for_context(db, session, target.get("project_id"))
        if not project:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要为哪一个学习项目规划路线？"
        _bind_project_session(session, project.id, session.checkpoint_id)
        _record_session_handoff(session, project.id, target)
        action.project_id = project.id
        from app.api.phase1 import roadmap_chat
        from app.schemas.project import AgentChatRequest, AgentMessage as LegacyMessage
        history_rows = await get_messages(db, session.id, limit=20)
        history = [
            LegacyMessage(role=m.role, content=m.content)
            for m in history_rows[:-1] if m.role in {"user", "assistant"}
        ]
        prompt = str(target.get("message") or "请根据当前资料规划一条可验证、包含实践目标的学习路线。")
        from app.services.auth import load_current_learner
        current = await load_current_learner(db, action.learner_id)
        response = await roadmap_chat(
            project.id,
            AgentChatRequest(
                message=prompt,
                history=history,
                require_submission=action.capability == "apply_learning_path",
                action_id=action.id,
            ),
            db,
            current,
        )
        confirmation_action_id = None
        entered_checkpoint = None
        if response.updated_roadmap:
            _set_learning_flow(
                session,
                phase="roadmap_ready",
                roadmap_applied_at=datetime.utcnow().isoformat(),
            )
            first_checkpoint = await _first_open_checkpoint(db, session)
            follow_up = (
                "正式路线已写入项目。讲义、练习、代码任务和验证会放在各自关卡中；"
                "Tutor 对话继续负责路线调整和课前后答疑。"
            )
            if first_checkpoint:
                roadmap = await db.get(Roadmap, first_checkpoint.roadmap_id)
                entered_checkpoint = await _enter_checkpoint(
                    db, action, session, first_checkpoint,
                    roadmap.project_id if roadmap else project.id,
                    entry_mode="automatic_after_roadmap",
                )
                follow_up += f" 已直接进入第一关「{first_checkpoint.title}」。"
            user_message = "\n\n".join(
                item for item in (response.message.strip(), follow_up) if item
            )
        else:
            _set_learning_flow(session, phase="roadmap_proposal")
            user_message = response.message.strip()
            if action.capability == "plan_learning_path":
                confirmation = await _new_action(
                    db,
                    session,
                    "apply_learning_path",
                    {
                        "project_id": project.id,
                        "workflow_stage": "roadmap_confirmation_card",
                        "message": (
                            "学习者已经明确确认上一轮正式路线方案（通过界面的确认按钮）。"
                            "请保持已协商的目标、节奏和关卡结构，立即调用 submit_roadmap 一次"
                            "写入路线，不要再次提问，也不要在聊天中展开讲义或布置练习。"
                        ),
                        "reason": "确认后会立即把路线写入项目，并显示可进入的关卡图。",
                        "expected_result": "生成正式关卡图；之后仍可在项目 Tutor 中提出路线修订。",
                        "explicit": True,
                    },
                    "pending_confirmation",
                )
                confirmation_action_id = confirmation.id
                user_message = "\n\n".join(item for item in (
                    user_message,
                    "路线可以后续迭代；点击下方按钮后会立即生成关卡图。",
                ) if item)
            elif action.capability == "apply_learning_path":
                user_message = "\n\n".join((
                    response.message.strip(),
                    "这次还没有写入正式路线；路线仍处于待确认状态，关卡内容也尚未开始。",
                ))
        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            "updated_roadmap": response.updated_roadmap,
            "learning_flow_phase": _learning_flow(session).get("phase"),
            "user_message": user_message,
            **(entered_checkpoint or {}),
            **({"confirmation_action_id": confirmation_action_id}
               if confirmation_action_id else {}),
        }
        session.pending_action_id = confirmation_action_id
        await record_event(
            db,
            learner_id=action.learner_id,
            event_type="roadmap_applied" if response.updated_roadmap else "roadmap_discussed",
            source="tutor_tool",
            project_id=project.id, session_id=session.id,
            payload={"applied": bool(response.updated_roadmap)},
            confidence=1.0, provenance={"action_id": action.id},
            client_event_id=f"action:{action.id}:roadmap",
        )
        await db.commit()
        return user_message

    if action.capability == "advance_checkpoint":
        project = await _project_for_context(db, session, target.get("project_id"))
        if not project:
            action.status = "needs_input"
            session.pending_action_id = action.id
            return "要推进哪个学习项目？"
        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.project_id == project.id)
        )).scalar_one_or_none()
        if not roadmap:
            action.status = "failed"
            action.error = {"message": "当前项目还没有学习路线"}
            await db.commit()
            return "当前项目还没有学习路线，先规划路线后才能推进下一关。"
        checkpoints = (await db.execute(
            select(Checkpoint).where(
                Checkpoint.roadmap_id == roadmap.id,
                Checkpoint.archived.is_(False),
            ).order_by(Checkpoint.order)
        )).scalars().all()
        current = next((cp for cp in checkpoints if cp.id == session.checkpoint_id), None)
        candidates = [cp for cp in checkpoints if cp.learning_status != "completed"]
        if current:
            candidates = [cp for cp in candidates if cp.order > current.order]
        checkpoint = candidates[0] if candidates else None
        if not checkpoint:
            action.status = "completed"
            action.finished_at = datetime.utcnow()
            action.result = {"user_message": "当前路线已经没有待推进的检查点。"}
            await db.commit()
            return action.result["user_message"]
        entry = await _enter_checkpoint(
            db, action, session, checkpoint, project.id,
            entry_mode="explicit_advance",
        )
        action.status = "completed"
        action.finished_at = datetime.utcnow()
        action.result = {
            "project": {"id": project.id, "name": project.name},
            **entry,
            "user_message": f"已进入下一关「{checkpoint.title}」。",
        }
        session.pending_action_id = None
        await db.commit()
        return action.result["user_message"]

    action.status = "failed"
    action.error = {"message": "当前版本尚未接入这个能力"}
    await db.commit()
    return "这个能力当前还没有接入。"


async def _recent_url(db: AsyncSession, session_id: int) -> str | None:
    messages = await get_messages(db, session_id, limit=12)
    for message in reversed(messages):
        url = _extract_url(message.content)
        if url:
            return url
    return None


async def _source_url_from_context(
    db: AsyncSession, learner_id: int, context: dict | None,
) -> str | None:
    values = context or {}
    for key in ("selected_source_url", "source_url", "url"):
        value = values.get(key)
        if isinstance(value, str) and URL_RE.fullmatch(value.strip()):
            return _normalize_url(value)
    source_id = values.get("selected_source_id")
    source = (await db.execute(
        select(Source).join(Project, Project.id == Source.project_id).where(
            Source.id == source_id,
            Project.learner_id == learner_id,
        )
    )).scalar_one_or_none() if isinstance(source_id, int) else None
    return _normalize_url(source.url) if source and source.url else None


async def _explicit_action(
    db: AsyncSession,
    session: AgentSession,
    message: str,
    context: dict | None = None,
) -> AgentAction | None:
    if session.session_type == "checkpoint":
        if _looks_like_local_agent_delegation(message):
            return await _local_agent_action(
                db, session,
                task_type=_local_agent_task_type(message), goal=message,
                constraints=[], required_capabilities=["code_edit"],
                reason="这项任务需要修改或验证本地项目文件",
            )
        if _looks_like_lecture_command(message):
            return await _new_action(
                db, session, "generate_lecture",
                {"checkpoint_id": session.checkpoint_id, "explicit": True},
                "running",
            )
        if _looks_like_assessment_command(message):
            mode = "practice" if any(word in message for word in ("练习", "代码", "实践")) else "concept"
            return await _new_action(
                db, session, "generate_assessment",
                {"checkpoint_id": session.checkpoint_id, "mode": mode, "explicit": True},
                "running",
            )
        return None
    url = _extract_url(message) or await _source_url_from_context(db, session.learner_id, context)
    if _looks_like_create_command(message):
        name = _extract_project_name(message)
        capability = "bootstrap_project" if url else "create_project"
        return await _new_action(
            db, session, capability,
            {"name": name or "", "url": url, "explicit": True,
             "description": f"围绕{name}持续学习与实践" if name else ""},
            "running" if name else "needs_input",
        )
    if _looks_like_source_command(message):
        url = url or await _recent_url(db, session.id)
        named_projects = await _projects_named_in_message(db, session.learner_id, message)
        named_project = named_projects[0] if len(named_projects) == 1 else None
        active_project_id, _ = await _active_context_ids(db, session)
        project_id = named_project.id if named_project else (None if len(named_projects) > 1 else active_project_id)
        return await _new_action(
            db, session, "add_source",
            {"url": url, "project_id": project_id, "explicit": True,
             "project_candidates": [{"id": p.id, "name": p.name} for p in named_projects]},
            "running" if project_id and url else "needs_input",
        )
    if "项目" in message and any(word in message for word in ("进入", "打开", "切换")):
        named_projects = await _projects_named_in_message(db, session.learner_id, message)
        named_project = named_projects[0] if len(named_projects) == 1 else None
        active_project_id, _ = await _active_context_ids(db, session)
        project_id = named_project.id if named_project else (
            active_project_id if "当前" in message and not named_projects else None
        )
        return await _new_action(
            db, session, "enter_project",
            {"project_id": project_id, "explicit": True,
             "project_candidates": [{"id": p.id, "name": p.name} for p in named_projects]},
            "ready" if project_id else "needs_input",
        )
    if _looks_like_apply_route_command(message):
        active_project_id, _ = await _active_context_ids(db, session)
        return await _new_action(
            db, session, "apply_learning_path",
            {"project_id": active_project_id, "message": message, "explicit": True},
            "running" if active_project_id else "needs_input",
        )
    if _looks_like_route_command(message):
        active_project_id, _ = await _active_context_ids(db, session)
        return await _new_action(
            db, session, "plan_learning_path",
            {"project_id": active_project_id, "message": message, "explicit": True},
            "running" if active_project_id else "needs_input",
        )
    if _looks_like_lecture_command(message):
        _, active_checkpoint_id = await _active_context_ids(db, session)
        return await _new_action(
            db, session, "generate_lecture",
            {"checkpoint_id": active_checkpoint_id, "explicit": True},
            "running" if active_checkpoint_id else "needs_input",
        )
    if _looks_like_assessment_command(message):
        _, active_checkpoint_id = await _active_context_ids(db, session)
        mode = "practice" if any(word in message for word in ("练习", "代码", "实践")) else "concept"
        return await _new_action(
            db, session, "generate_assessment",
            {"checkpoint_id": active_checkpoint_id, "mode": mode, "explicit": True},
            "running" if active_checkpoint_id else "needs_input",
        )
    if _looks_like_advance_command(message):
        active_project_id, _ = await _active_context_ids(db, session)
        return await _new_action(
            db, session, "advance_checkpoint",
            {"project_id": active_project_id, "explicit": True},
            "running" if active_project_id else "needs_input",
        )
    return None


async def _local_agent_action(
    db: AsyncSession,
    session: AgentSession,
    *,
    task_type: str,
    goal: str,
    constraints: list[str],
    required_capabilities: list[str],
    reason: str,
) -> AgentAction:
    from app.services.local_agent_broker import select_profile

    if session.session_type != "checkpoint" or not session.project_id or not session.checkpoint_id:
        raise ValueError("本地代码 Agent 只能由关卡 Tutor 委派")
    normalized_capabilities = list(dict.fromkeys(
        item for item in required_capabilities if item in {"code_edit", "test"}
    )) or ["code_edit"]
    profile = await select_profile(
        db, session.learner_id, task_type, normalized_capabilities,
    )
    target = {
        "project_id": session.project_id,
        "checkpoint_id": session.checkpoint_id,
        "task_type": task_type,
        "goal": goal[:2000],
        "constraints": [str(item)[:500] for item in constraints[:20]],
        "required_capabilities": normalized_capabilities,
        "reason": reason[:500],
        "expected_result": "在隔离副本生成事件、测试、风险和完整 diff；不会直接改动真实工作区",
        "profile_id": profile.id if profile else None,
        "profile_name": profile.name if profile else "未找到可用配置",
        "adapter": profile.adapter if profile else "",
        "sandbox_policy": profile.sandbox_policy if profile else "workspace_write",
        "network_policy": profile.network_policy if profile else "",
        "network_boundary_enforced": bool(profile and profile.adapter == "deterministic_fake"),
        "excluded_paths": [".learnflow", ".git", ".env/密钥", "符号链接", "缓存与构建目录"],
    }
    return await _new_action(
        db, session, "delegate_local_agent_task", target,
        "pending_confirmation" if profile else "needs_input",
    )


async def _candidate_sources_follow_up(
    db: AsyncSession,
    session: AgentSession,
) -> str:
    sources = list((await db.execute(
        select(Source).where(Source.project_id == session.project_id)
    )).scalars().all()) if session.project_id else []
    processed = sum(item.status == "processed" for item in sources)
    available = processed or len(sources)
    return (
        f"好的，这一轮来源选择先到这里。目前项目有 {available} 个可用于规划的来源。\n\n"
        "正式路线会先确认必要前置，再沿来源建立核心概念链，随后安排逐步实践，"
        "最后用独立产物和验证任务收口；项目提案里的阶段预览只作为参考。\n\n"
        "生成正式路线前，请先确认两个点：你每周准备投入多少时间；最终产物希望先以"
        "“跑通核心闭环”为目标，还是同时包含扩展功能和完整测试？"
    )


async def _generate_tutor_reply(
    db: AsyncSession,
    session: AgentSession,
) -> tuple[str, list[dict], dict | None, dict | None, list[dict], dict | None]:
    latest_messages = await get_messages(db, session.id, limit=1)
    latest_interaction = str(
        ((latest_messages[-1].meta_data or {}).get("interaction") if latest_messages else "") or ""
    )
    if not settings.llm_api_key or settings.llm_api_key in {"", "***", "sk-your-key-here"}:
        return "未接入模型。", [], None, None, [], None

    projection = await get_kernel_projection(db, session.learner_id)
    prompt_projection = deepcopy(projection)
    if session.session_type == "global":
        structure_memory = prompt_projection.get("structure", {}).get("short_term", {})
        if structure_memory.get("active_project_id") is not None:
            structure_memory["recent_project_reference_id"] = structure_memory.pop("active_project_id")
        if structure_memory.get("active_checkpoint_id") is not None:
            structure_memory["recent_checkpoint_reference_id"] = structure_memory.pop("active_checkpoint_id")
    state = await get_session_state_summary(db, session)
    projects = (await db.execute(
        select(Project).where(Project.learner_id == session.learner_id)
        .order_by(Project.updated_at.desc()).limit(20)
    )).scalars().all() if session.session_type != "checkpoint" else []
    proposals = await list_session_proposals(db, session.id)
    project_workspace: dict[str, Any] = {}
    checkpoint_workspace: dict[str, Any] = {}
    if session.session_type == "project" and session.project_id:
        active_project = (await db.execute(select(Project).where(
            Project.id == session.project_id,
            Project.learner_id == session.learner_id,
        ))).scalar_one_or_none()
        project_sources = list((await db.execute(
            select(Source).where(Source.project_id == session.project_id).order_by(Source.id)
        )).scalars().all()) if active_project else []
        project_checkpoints = list((await db.execute(
            select(Checkpoint)
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .where(
                Roadmap.project_id == session.project_id,
                Checkpoint.archived.is_(False),
            )
            .order_by(Checkpoint.order)
        )).scalars().all()) if active_project else []
        accepted_proposal = (await db.execute(
            select(LearningProjectProposal).where(
                LearningProjectProposal.accepted_project_id == session.project_id,
                LearningProjectProposal.learner_id == session.learner_id,
                LearningProjectProposal.status == "accepted",
            ).order_by(LearningProjectProposal.updated_at.desc()).limit(1)
        )).scalar_one_or_none() if active_project else None
        proposal_artifact = dict(accepted_proposal.artifact or {}) if accepted_proposal else {}
        project_workspace = {
            "responsibility": (
                "你持续负责本项目的资料、正式路线、路线修订和课前后问答；"
                "讲义、练习与验证必须放入正式关卡，不能在聊天中用整套教学内容替代关卡"
            ),
            "project": {
                "id": active_project.id,
                "name": active_project.name,
                "description": active_project.description,
                "user_level": active_project.user_level,
            } if active_project else None,
            "sources": [
                {
                    "id": item.id, "type": item.type, "url": item.url,
                    "role": item.role, "status": item.status,
                }
                for item in project_sources
            ],
            "formal_roadmap": [
                {
                    "id": item.id, "order": item.order, "title": item.title,
                    "description": item.description,
                    "status": item.learning_status or "not_started",
                }
                for item in project_checkpoints
            ],
            "accepted_goal": {
                "learning_goal": proposal_artifact.get("learning_goal", ""),
                "practice_goal": proposal_artifact.get("practice_goal", ""),
                "estimated_effort": proposal_artifact.get("estimated_effort", ""),
                "stage_preview": proposal_artifact.get("milestones", []),
                "stage_preview_weight": "low_reference_only",
                "candidate_sources": [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "reason": item.get("reason", ""),
                        "stars": item.get("stars", 0),
                    }
                    for item in proposal_artifact.get("candidate_sources", [])[:8]
                    if isinstance(item, dict)
                ],
            } if accepted_proposal else None,
        }
    elif session.session_type == "checkpoint" and session.project_id and session.checkpoint_id:
        latest = await get_messages(db, session.id, limit=1)
        latest_context = dict(latest[-1].meta_data or {}) if latest else {}
        checkpoint_workspace = await build_checkpoint_tutor_context(
            db,
            learner_id=session.learner_id,
            project_id=session.project_id,
            checkpoint_id=session.checkpoint_id,
            surface_context=latest_context,
        )
        prompt_projection = checkpoint_workspace["five_kernel_projection"]
    role = {
        "global": "main_agent",
        "project": "project_tutor",
        "checkpoint": "checkpoint_tutor",
    }.get(session.session_type, "main_agent")
    context = {
        "session_scope": {
            "type": session.session_type,
            "role": role,
            "project_information_policy": (
                "current_checkpoint_only" if session.session_type == "checkpoint"
                else "current_project_workspace" if session.session_type == "project"
                else "portfolio_and_memory_reference_only"
            ),
        },
        "current_state": state,
        "available_projects": [{"id": p.id, "name": p.name, "description": p.description} for p in projects],
        "learning_projection": prompt_projection,
        "session_handoff": dict(session.context_summary or {}) if session.session_type == "project" else {},
        "recent_project_reference": dict(session.context_summary or {}) if session.session_type == "global" else {},
        "project_workspace": project_workspace,
        "checkpoint_workspace": checkpoint_workspace,
        "active_project_proposals": [
            {
                "proposal_key": item.proposal_key,
                "proposal_type": item.proposal_type,
                "revision": item.revision,
                "title": (item.artifact or {}).get("title", ""),
                "learning_goal": (item.artifact or {}).get("learning_goal", ""),
                "practice_goal": (item.artifact or {}).get("practice_goal", ""),
                "locked_fields": list(item.locked_fields or []),
            }
            for item in proposals
        ],
    }
    scope_prompt = (
        CHECKPOINT_TUTOR_PROMPT if session.session_type == "checkpoint"
        else PROJECT_TUTOR_PROMPT if session.session_type == "project"
        else GLOBAL_MAIN_AGENT_PROMPT
    )
    system = (
        TUTOR_SYSTEM_PROMPT
        + "\n\n"
        + scope_prompt
        + "\n\n当前内部上下文：\n"
        + json.dumps(context, ensure_ascii=False)[:12000]
    )
    history = await get_messages(db, session.id, limit=18)
    messages: list[Any] = [SystemMessage(content=system)]
    handoff_ids = list(
        ((session.context_summary or {}).get("handoff") or {}).get("message_refs") or []
    )[:12] if session.session_type == "project" else []
    if handoff_ids:
        referenced = (await db.execute(
            select(AgentMessage)
            .where(AgentMessage.id.in_(handoff_ids))
            .order_by(AgentMessage.id)
        )).scalars().all()
        for item in referenced:
            if item.role == "user":
                messages.append(HumanMessage(content=item.content))
            elif item.role == "assistant":
                messages.append(AIMessage(content=_decode_tutor_content(item.content)[0]))
    for item in history:
        if item.role == "user":
            selected_text = str((item.meta_data or {}).get("selected_text") or "").strip()
            interaction = str((item.meta_data or {}).get("interaction") or "")
            content = item.content
            if selected_text:
                content += f"\n\n用户当前选中的学习内容：\n{selected_text[:12000]}"
            if interaction == "candidate_sources_completed":
                content += (
                    "\n\n界面行动语义：用户已结束本轮候选来源选择。"
                    "请结合项目中真实已接入的来源、学习画像和已确认目标，先概述正式学习路线的安排逻辑，"
                    "再集中询问生成正式路线前仍必须确认的 1-3 个要点。"
                    "此时不要直接应用正式路线，也不要把项目提案的阶段预览原样复制为正式路线。"
                )
            messages.append(HumanMessage(content=content))
        elif item.role == "assistant":
            messages.append(AIMessage(content=_decode_tutor_content(item.content)[0]))

    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.45,
        timeout=60,
        max_retries=0,
    )
    try:
        structured = llm.with_structured_output(TutorModelOutput)
        output = await structured.ainvoke(messages)
        opportunity = output.project_opportunity.model_dump() if output.project_opportunity else None
        learning_intent = output.learning_intent.model_dump() if output.learning_intent else None
        local_agent_task = output.local_agent_task.model_dump() if output.local_agent_task else None
        return (
            output.reply,
            [o.model_dump() for o in output.observations],
            opportunity,
            learning_intent,
            [item.model_dump() for item in output.major_event_candidates],
            local_agent_task,
        )
    except Exception:
        try:
            response = await llm.ainvoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)
            return _decode_tutor_content(content)
        except Exception:
            if latest_interaction == "candidate_sources_completed" and session.project_id:
                return await _candidate_sources_follow_up(db, session), [], None, None, [], None
            return "这次模型服务没有响应。你仍然可以直接让我创建项目、添加来源或推进当前检查点。", [], None, None, [], None


async def proposal_acceptance_action(
    db: AsyncSession,
    proposal: LearningProjectProposal,
) -> AgentAction:
    if proposal.accepted_action_id:
        existing = await db.get(AgentAction, proposal.accepted_action_id)
        if existing:
            return existing
    session = await db.get(AgentSession, proposal.session_id)
    if not session:
        raise ValueError("项目提案所属会话不存在")
    artifact = dict(proposal.artifact or {})
    if proposal.action_type == "enter_existing" and proposal.target_project_id:
        capability = "enter_project"
        target = {
            "project_id": proposal.target_project_id,
            "project_name": artifact.get("title", ""),
            "goal": artifact.get("learning_goal", ""),
            "practice_artifact": artifact.get("practice_goal", ""),
            "reason": "这个提案与已有学习项目高度相关",
            "expected_result": "进入已有项目并保留当前学习上下文",
        }
    else:
        capability = "create_project"
        learner_start = "；".join(str(value) for value in artifact.get("learner_start", []) if value)
        target = {
            "name": str(artifact.get("title") or "学习项目")[:255],
            "description": str(artifact.get("learning_goal") or artifact.get("practice_goal") or "")[:1000],
            "goal": artifact.get("learning_goal", ""),
            "practice_artifact": artifact.get("practice_goal", ""),
            "initial_concepts": [
                str(item.get("title"))[:80]
                for item in artifact.get("milestones", [])
                if isinstance(item, dict) and item.get("title")
            ][:10],
            "user_level": "beginner" if any(
                token in learner_start for token in ("没用过", "尚未", "从零", "待建立")
            ) else "intermediate",
            "reason": "用户已接受这份持续学习提案",
            "expected_result": "创建并进入项目，保留提案、上下文和候选来源",
        }
    target.update({
        "proposal_id": proposal.id,
        "proposal_revision": proposal.revision,
        "proposal_snapshot": artifact,
        "context_message_ids": list(proposal.message_refs or []),
        "context_evidence_ids": list(proposal.evidence_refs or []),
    })
    action = await _new_action(db, session, capability, target, "running")
    action.idempotency_key = f"proposal:{proposal.id}:accept"
    proposal.accepted_action_id = action.id
    await db.flush()
    return action


async def finalize_proposal_acceptance(
    db: AsyncSession,
    proposal: LearningProjectProposal,
    action: AgentAction,
):
    if action.status != "completed":
        return
    project_data = dict((action.result or {}).get("project") or {})
    project_id = project_data.get("id") or action.project_id or proposal.target_project_id
    proposal.status = "accepted"
    proposal.accepted_project_id = project_id
    proposal.updated_at = datetime.utcnow()
    await record_event(
        db, event_type="project_proposal_accepted", source="user",
        learner_id=proposal.learner_id,
        project_id=project_id, session_id=proposal.session_id,
        payload={
            "proposal_id": proposal.id, "proposal_key": proposal.proposal_key,
            "proposal_revision": proposal.revision, "project_id": project_id,
            "learning_goal": (proposal.artifact or {}).get("learning_goal", ""),
            "practice_goal": (proposal.artifact or {}).get("practice_goal", ""),
        },
        confidence=1.0, provenance={"action_id": action.id, "proposal_id": proposal.id},
        client_event_id=f"proposal:{proposal.id}:accepted",
        artifact_refs=[{"type": "project_proposal", "id": proposal.id, "revision": proposal.revision}],
    )


async def process_turn(
    db: AsyncSession,
    session: AgentSession,
    *,
    message: str,
    project_id: int | None = None,
    checkpoint_id: int | None = None,
    selected_action_id: int | None = None,
    client_turn_id: str | None = None,
    context: dict | None = None,
) -> dict:
    replay_message = None
    if client_turn_id:
        replay_message = (await db.execute(select(AgentMessage).where(
            AgentMessage.session_id == session.id,
            AgentMessage.idempotency_key == f"{session.id}:{client_turn_id}",
        ))).scalar_one_or_none()
        cached_response = dict((replay_message.meta_data or {}).get("turn_response") or {}) if replay_message else {}
        if cached_response:
            return cached_response

    if session.session_type == "checkpoint":
        if project_id is not None and project_id != session.project_id:
            raise ValueError("关卡 Tutor 不能切换到其他项目")
        if checkpoint_id is not None and checkpoint_id != session.checkpoint_id:
            raise ValueError("关卡 Tutor 不能切换到其他关卡")
        project_id = session.project_id
        checkpoint_id = session.checkpoint_id
    if project_id is not None and session.session_type != "checkpoint":
        project = await _project_for_context(db, session, project_id)
        if not project:
            raise ValueError("学习项目不存在")
        session.project_id = project.id
        session.session_type = "project"
    if checkpoint_id is not None:
        checkpoint = await _checkpoint_for_learner(db, session.learner_id, checkpoint_id)
        if not checkpoint:
            raise ValueError("检查点不存在")
        if session.session_type == "checkpoint" and checkpoint.id != session.checkpoint_id:
            raise ValueError("关卡 Tutor 作用域不可修改")
        if checkpoint.learning_status in (None, "", "not_started"):
            checkpoint.learning_status = "in_progress"

    incoming_context = context or {}
    candidate_sources_completed = incoming_context.get("interaction") == "candidate_sources_completed"
    message_context = {}
    if isinstance(incoming_context.get("selected_text"), str):
        message_context["selected_text"] = incoming_context["selected_text"][:12000]
    for key in (
        "selected_source_id", "selected_source_url", "surface", "resource_kind",
        "resource_id", "title", "section_index", "selected_path", "open_file", "language",
    ):
        if key in incoming_context:
            message_context[key] = incoming_context[key]
    if candidate_sources_completed:
        message_context["interaction"] = "candidate_sources_completed"
        proposal_id = incoming_context.get("proposal_id")
        if isinstance(proposal_id, int):
            message_context["proposal_id"] = proposal_id
        _set_learning_flow(
            session,
            phase="roadmap_intake",
            proposal_id=proposal_id if isinstance(proposal_id, int) else None,
            source_selection_completed=True,
        )
    if replay_message:
        user_message = replay_message
        user_event = None
    else:
        user_message = AgentMessage(
            session_id=session.id,
            role="user",
            content=message,
            meta_data=message_context,
            idempotency_key=f"{session.id}:{client_turn_id}" if client_turn_id else None,
        )
        db.add(user_message)
        await db.flush()
        user_event = None
    if not user_event:
        user_event = await record_event(
            db, event_type="user_message", source="user",
            learner_id=session.learner_id,
            project_id=session.project_id, checkpoint_id=session.checkpoint_id,
            session_id=session.id, payload={"text": message},
            confidence=0.25 if message.strip().lower() in {
                "懂了", "明白了", "会了", "got it", "understood",
            } else 1.0,
            provenance={"message_id": user_message.id},
            client_event_id=f"message:{user_message.id}:user",
        )
    await db.commit()

    action = None
    proposal_for_action: LearningProjectProposal | None = None
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    learning_phase = await _effective_learning_flow_phase(db, session)
    if candidate_sources_completed:
        pass
    elif selected_action_id:
        candidate = (await db.execute(select(AgentAction).where(
            AgentAction.id == selected_action_id,
            AgentAction.session_id == session.id,
            AgentAction.learner_id == session.learner_id,
        ))).scalar_one_or_none()
        if candidate:
            action = candidate
    elif pending and pending.status == "pending_confirmation" and _is_confirmation(message):
        # The UI normally calls /actions/{id}/confirm.  Keep the old text
        # confirmation path as a backwards-compatible fallback for API users
        # and existing conversations, while steering the product UI to the card.
        action = pending
        action.status = "ready"
    elif pending and pending.status == "needs_input":
        target = dict(pending.target or {})
        if pending.capability in {"create_project", "bootstrap_project"}:
            target["name"] = message.strip()[:80]
        elif pending.capability == "add_source":
            url = (
                _extract_url(message)
                or await _source_url_from_context(db, session.learner_id, context)
                or await _recent_url(db, session.id)
            )
            if url:
                target["url"] = url
            if not target.get("project_id"):
                selected_project_id = _project_choice(
                    message, list(target.get("project_candidates") or [])
                )
                named_projects = await _projects_named_in_message(db, session.learner_id, message)
                named_project = named_projects[0] if len(named_projects) == 1 else None
                if len(named_projects) > 1:
                    target["project_candidates"] = [
                        {"id": project.id, "name": project.name}
                        for project in named_projects
                    ]
                active_project_id, _ = await _active_context_ids(db, session)
                target["project_id"] = selected_project_id or (
                    named_project.id if named_project else (
                        None if target.get("project_candidates") else active_project_id
                    )
                )
        elif pending.capability == "enter_project":
            selected_project_id = _project_choice(
                message, list(target.get("project_candidates") or [])
            )
            named_projects = await _projects_named_in_message(db, session.learner_id, message)
            named_project = named_projects[0] if len(named_projects) == 1 else None
            if len(named_projects) > 1:
                target["project_candidates"] = [
                    {"id": project.id, "name": project.name}
                    for project in named_projects
                ]
            target["project_id"] = selected_project_id or (
                named_project.id if named_project else None
            )
        pending.target = target
        pending.status = "running"
        action = pending
    elif pending and pending.status == "pending_confirmation" and _is_confirmation(message):
        action = pending
        action.status = "running"
    else:
        active_project_id, _ = await _active_context_ids(db, session)
        recent_roadmap_proposal = (
            await _has_recent_roadmap_proposal(db, session)
            if (
                session.session_type == "project"
                and active_project_id
                and _is_confirmation(message)
                and learning_phase != "roadmap_ready"
            )
            else False
        )
        if (
            session.session_type == "project"
            and active_project_id
            and learning_phase == "roadmap_intake"
            and _looks_like_roadmap_intake_answer(message)
        ):
            action = await _new_action(
                db,
                session,
                "plan_learning_path",
                {
                    "project_id": active_project_id,
                    "workflow_stage": "roadmap_intake_complete",
                    "message": (
                        "用户已经完成候选来源选择，下面是对正式路线前置信息的回答：\n\n"
                        f"{message}\n\n"
                        "请结合项目中真实已接入的来源、用户画像、五核记忆和项目对话，"
                        "主动给出一份正式路线提案。提案要说明关卡顺序、每关可验证产物和"
                            "需要用户确认的取舍；项目阶段预览只能作低权重参考。"
                            "这一轮不要调用 submit_roadmap，不要在聊天里发布完整讲义或练习。"
                            "系统会以确认按钮承接写入路线；说明路线可在后续迭代即可，不要要求用户"
                            "通过自然语言确认。"
                    ),
                    "explicit": True,
                },
                "running",
            )
        elif (
            session.session_type == "project"
            and active_project_id
            and (
                learning_phase == "roadmap_proposal"
                or recent_roadmap_proposal
            )
            and _is_confirmation(message)
        ):
            action = await _new_action(
                db,
                session,
                "apply_learning_path",
                {
                    "project_id": active_project_id,
                    "workflow_stage": "roadmap_confirmation",
                    "message": (
                        "用户已经明确确认上一轮正式路线方案。请保持已协商的目标、节奏和"
                        "关卡结构，立即调用 submit_roadmap 一次写入正式路线，不要再次提问，"
                        "也不要在聊天中展开讲义或布置练习。"
                    ),
                    "explicit": True,
                },
                "running",
            )
        elif (
            session.session_type == "project"
            and active_project_id
            and _looks_like_project_start(message)
        ):
            if learning_phase == "roadmap_ready":
                checkpoint = await _first_open_checkpoint(db, session)
                action = await _new_action(
                    db,
                    session,
                    "navigate_checkpoint" if checkpoint else "advance_checkpoint",
                    {
                        "project_id": active_project_id,
                        "checkpoint_id": checkpoint.id if checkpoint else None,
                        "explicit": True,
                    },
                    "running",
                )
            elif learning_phase == "roadmap_proposal":
                action = await _new_action(
                    db,
                    session,
                    "apply_learning_path",
                    {
                        "project_id": active_project_id,
                        "workflow_stage": "roadmap_confirmation",
                        "message": (
                            "用户以“开始”明确确认了上一轮正式路线方案。请立即调用 "
                            "submit_roadmap 一次写入路线，不要再次确认，也不要在聊天中开课。"
                        ),
                        "explicit": True,
                    },
                    "running",
                )
            else:
                action = await _new_action(
                    db,
                    session,
                    "plan_learning_path",
                    {
                        "project_id": active_project_id,
                        "workflow_stage": "roadmap_start_requested",
                        "message": (
                            "用户希望开始这个项目，但项目还没有可进入的正式关卡。请根据真实来源、"
                            "用户画像和已有对话主动给出正式路线提案；缺少关键约束时最多集中询问一次。"
                            "不要调用 submit_roadmap，也不要直接在聊天中发布讲义或完整练习。"
                        ),
                        "explicit": True,
                    },
                    "running",
                )
        if not action:
            action = await _explicit_action(db, session, message, context)
        if not action and _is_project_proposal_confirmation(message):
            proposal_for_action = await get_latest_active_proposal(db, session.id)
            if proposal_for_action:
                action = await proposal_acceptance_action(db, proposal_for_action)

    if action:
        target = dict(action.target or {})
        target["context_message_ids"] = list(dict.fromkeys([
            *list(target.get("context_message_ids") or []), user_message.id,
        ]))
        target["context_evidence_ids"] = list(dict.fromkeys([
            *list(target.get("context_evidence_ids") or []), user_event.id,
        ]))
        action.target = target
        try:
            if action.status == "pending_confirmation":
                reply = "本地代码 Agent 任务已准备好。确认后只会在隔离副本启动，不会直接改动真实工作区。"
                await db.commit()
            else:
                reply = await execute_action(db, action)
            proposal_id = (action.target or {}).get("proposal_id")
            if proposal_id:
                proposal_for_action = proposal_for_action or await db.get(
                    LearningProjectProposal, proposal_id,
                )
                if proposal_for_action and proposal_for_action.learner_id == session.learner_id:
                    await finalize_proposal_acceptance(db, proposal_for_action, action)
        except Exception as exc:
            action.status = "failed"
            action.error = {"message": str(exc)[:500]}
            action.finished_at = datetime.utcnow()
            session.pending_action_id = None
            await record_event(
                db, event_type="tool_failed", source="tutor_tool",
                learner_id=session.learner_id,
                project_id=session.project_id, checkpoint_id=session.checkpoint_id,
                session_id=session.id, payload={"message": str(exc)[:500]},
                confidence=1.0, provenance={"action_id": action.id},
                client_event_id=f"action:{action.id}:failed",
            )
            await db.commit()
            reply = f"没有执行成功：{str(exc)[:240]}"
        assistant = AgentMessage(
            session_id=session.id, role="assistant", content=reply,
            meta_data={
                "action_id": action.id,
                "local_agent_run_id": (
                    ((action.result or {}).get("local_agent_run") or {}).get("id")
                ),
            },
        )
        db.add(assistant)
        await db.commit()
        state = await get_session_state_summary(db, session)
        proposals = await list_session_proposals(db, session.id)
        response = {
            "session_id": session.id,
            "message": reply,
            "state_summary": state,
            "executed_action": action_result(action),
            "action_card": (
                action_card(action) if action.status in {"needs_input", "pending_confirmation"}
                else action_card(await db.get(AgentAction, session.pending_action_id))
                if session.pending_action_id else None
            ),
            "project_proposals": [proposal_view(item) for item in proposals],
            "proposal_update": proposal_view(proposal_for_action) if proposal_for_action else None,
        }
        user_message.meta_data = {**dict(user_message.meta_data or {}), "turn_response": response}
        await db.commit()
        return response

    reply, observations, opportunity, learning_intent, major_event_candidates, local_agent_task = (
        await _generate_tutor_reply(db, session)
    )
    generated_local_action = None
    if (
        session.session_type == "checkpoint"
        and isinstance(local_agent_task, dict)
        and local_agent_task.get("should_delegate")
        and str(local_agent_task.get("goal") or "").strip()
    ):
        generated_local_action = await _local_agent_action(
            db, session,
            task_type=str(local_agent_task.get("task_type") or "code_change"),
            goal=str(local_agent_task.get("goal") or message),
            constraints=list(local_agent_task.get("constraints") or []),
            required_capabilities=list(local_agent_task.get("required_capabilities") or ["code_edit"]),
            reason=str(local_agent_task.get("reason") or "这项任务需要本地代码能力"),
        )
        if generated_local_action.status == "pending_confirmation":
            reply = "我已把任务收敛为一张本地代码 Agent 委派卡。确认后先在隔离副本执行；完成后你会看到测试、风险和完整 diff，再决定是否写回。"
        else:
            reply = "当前没有满足任务能力的本地代码 Agent。请先在桌面版配置并启用一个 Agent。"
    if (
        session.session_type == "project"
        and learning_phase != "roadmap_ready"
        and _claims_roadmap_was_applied(reply)
    ):
        reply = (
            "正式路线还没有通过工具写入项目，因此当前不能宣称已经生效。"
            "请直接回复“确认路线”，我会执行路线提交并以实际生成的关卡结果为准。"
        )
    await apply_semantic_observations(db, user_event, observations)
    from app.services.profile import process_major_event_candidates
    life_events, awarded_badges = await process_major_event_candidates(
        db,
        learner_id=session.learner_id,
        message=message,
        message_id=user_message.id,
        candidates=major_event_candidates,
    )
    proposal_update = None
    if not candidate_sources_completed and session.session_type != "checkpoint":
        proposal_update = await evolve_project_proposal(
            db, session,
            message=message,
            user_message_id=user_message.id,
            evidence=user_event,
            opportunity=opportunity,
            learning_intent=learning_intent,
        )
    assistant = AgentMessage(
        session_id=session.id, role="assistant", content=reply,
        meta_data={"proposal_id": proposal_update.id if proposal_update else None},
    )
    db.add(assistant)
    await db.commit()
    if proposal_update and proposal_update.action_type == "create":
        await start_resource_search(db, proposal_update)
    state = await get_session_state_summary(db, session)
    proposals = await list_session_proposals(db, session.id)
    response = {
        "session_id": session.id,
        "message": reply,
        "state_summary": state,
        "executed_action": None,
        "action_card": (
            action_card(generated_local_action) if generated_local_action
            else action_card(pending) if pending and pending.status in {"needs_input", "pending_confirmation"}
            else None
        ),
        "project_proposals": [proposal_view(item) for item in proposals],
        "proposal_update": proposal_view(proposal_update) if proposal_update else None,
        "life_events": life_events,
        "awarded_badges": awarded_badges,
    }
    user_message.meta_data = {**dict(user_message.meta_data or {}), "turn_response": response}
    await db.commit()
    return response


async def finalize_action_for_task(task: Task):
    if not task.agent_action_id:
        return
    from app.db.database import async_session
    async with async_session() as db:
        action = await db.get(AgentAction, task.agent_action_id)
        if not action or action.status in {"completed", "failed", "canceled"}:
            return
        action.status = task.status
        action.result = {**dict(action.result or {}), **dict(task.result or {}), "task_id": task.id}
        action.error = dict(task.error or {})
        if task.status in {"completed", "failed", "canceled"}:
            action.finished_at = task.finished_at or datetime.utcnow()
        success_messages = {
            "source_ingest": "来源处理完成，可以开始规划路线或继续提问。",
            "lecture_generate": "讲义已经生成；这一关仍需通过作答或实践来验证。",
            "concept_generate": "概念验证题已经生成。",
            "exercise_generate": "实践题已经生成。",
        }
        if task.status == "completed":
            action.result["user_message"] = success_messages.get(task.type, "任务已完成。")
        event_map = {
            "lecture_generate": "lecture_generated",
            "concept_generate": "assessment_generated",
            "exercise_generate": "assessment_generated",
            "source_ingest": "source_processed",
        }
        event_type = event_map.get(task.type, "task_completed") if task.status == "completed" else "task_failed"
        await record_event(
            db, event_type=event_type, source="task",
            learner_id=task.learner_id or action.learner_id,
            project_id=task.project_id, checkpoint_id=task.checkpoint_id,
            session_id=action.session_id,
            payload={"task_id": task.id, "task_type": task.type,
                     "message": (task.error or {}).get("message", ""), **dict(task.result or {})},
            confidence=1.0, provenance={"action_id": action.id},
            client_event_id=f"task:{task.id}:{task.status}",
        )
        if task.checkpoint_id:
            await evaluate_checkpoint_status(
                db, task.checkpoint_id,
                learner_id=task.learner_id or action.learner_id,
            )
        if task.project_id:
            from app.services.profile import evaluate_project_badge
            await evaluate_project_badge(
                db,
                learner_id=task.learner_id or action.learner_id,
                project_id=task.project_id,
            )
        await db.commit()
