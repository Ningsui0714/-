"""
Phase 3 API routes:
- Exercise CRUD
- Code execution
- Code review agent
"""
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.database import get_db
from app.models.learning import LearningAttempt
from app.models.project import (
    Checkpoint, Exercise, ExerciseDraft, ConceptQuestion, Task, Roadmap,
)
from app.schemas.project import ExerciseOut, CodeRunRequest, CodeRunResult
from app.services.code_executor import execute_code
from app.services.code_agent import CodeAgent
from app.services.concept_agent import ConceptAgent
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_checkpoint,
    require_owned_exercise, require_owned_project,
)
from app.services.profile import evaluate_project_badge
from app.services.workspace_files import sync_managed_layout_for_project
from langchain_core.messages import HumanMessage

router = APIRouter()


# ── Exercise CRUD ──

@router.get("/checkpoints/{checkpoint_id}/exercises")
async def list_exercises(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """List exercises for a checkpoint."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Exercise)
        .where(Exercise.checkpoint_id == checkpoint_id)
        .order_by(Exercise.order)
    )
    exercises = result.scalars().all()
    return [
        ExerciseOut(
            id=e.id, checkpoint_id=e.checkpoint_id, title=e.title,
            description=e.description, starter_code=e.starter_code,
            test_cases=e.test_cases or [], hints=e.hints or [], order=e.order,
            files=e.files or [], entrypoint=e.entrypoint or "",
            requirements=e.requirements or [], judge_mode=e.judge_mode or "test_cases",
            judge_config=e.judge_config or {},
        )
        for e in exercises
    ]


@router.post("/checkpoints/{checkpoint_id}/exercises")
async def create_exercise(
    checkpoint_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Create a new exercise."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)

    exercise = Exercise(
        checkpoint_id=checkpoint_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        starter_code=data.get("starter_code", ""),
        solution=data.get("solution", ""),
        test_cases=data.get("test_cases", []),
        hints=data.get("hints", []),
        order=data.get("order", 0),
        assessment_meta=data.get("assessment_meta", {
            "mode": "practice",
            "evidence_target": {"practice": "independent_success"},
        }),
        files=data.get("files", []),
        entrypoint=data.get("entrypoint", ""),
        requirements=data.get("requirements", []),
        judge_mode=data.get("judge_mode", "test_cases"),
        judge_config=data.get("judge_config", {}),
    )
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)
    checkpoint = await db.get(Checkpoint, checkpoint_id)
    roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
    if roadmap:
        await sync_managed_layout_for_project(db, roadmap.project_id)
    return ExerciseOut(
        id=exercise.id, checkpoint_id=exercise.checkpoint_id,
        title=exercise.title, description=exercise.description,
        starter_code=exercise.starter_code,
        test_cases=exercise.test_cases or [],
        hints=exercise.hints or [], order=exercise.order,
        files=exercise.files or [], entrypoint=exercise.entrypoint or "",
        requirements=exercise.requirements or [],
        judge_mode=exercise.judge_mode or "test_cases",
        judge_config=exercise.judge_config or {},
    )


@router.get("/exercises/{exercise_id}")
async def get_exercise(
    exercise_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Get exercise details."""
    e = await require_owned_exercise(db, current.learner.id, exercise_id)
    return ExerciseOut(
        id=e.id, checkpoint_id=e.checkpoint_id, title=e.title,
        description=e.description, starter_code=e.starter_code,
        test_cases=e.test_cases or [], hints=e.hints or [], order=e.order,
        files=e.files or [], entrypoint=e.entrypoint or "",
        requirements=e.requirements or [], judge_mode=e.judge_mode or "test_cases",
        judge_config=e.judge_config or {},
    )


@router.get("/exercises/{exercise_id}/draft")
async def get_exercise_draft(
    exercise_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)
    draft = (await db.execute(select(ExerciseDraft).where(
        ExerciseDraft.exercise_id == exercise_id,
        ExerciseDraft.learner_id == current.learner.id,
    ))).scalar_one_or_none()
    saved_files = {
        item.get("name"): item for item in (draft.files or [])
        if draft and isinstance(item, dict)
    }
    files = []
    for item in (exercise.files or []):
        if not isinstance(item, dict):
            continue
        saved = saved_files.get(item.get("name"))
        files.append({
            **item,
            "content": item.get("content", "") if item.get("read_only") else (
                saved.get("content", item.get("content", "")) if saved else item.get("content", "")
            ),
        })
    return {
        "exercise_id": exercise_id,
        "code": draft.code if draft else exercise.starter_code or "",
        "files": files,
        "updated_at": draft.updated_at.isoformat() if draft and draft.updated_at else None,
    }


@router.put("/exercises/{exercise_id}/draft")
async def put_exercise_draft(
    exercise_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)
    draft = (await db.execute(select(ExerciseDraft).where(
        ExerciseDraft.exercise_id == exercise_id,
        ExerciseDraft.learner_id == current.learner.id,
    ))).scalar_one_or_none()
    if not draft:
        draft = ExerciseDraft(learner_id=current.learner.id, exercise_id=exercise_id)
        db.add(draft)
    if "code" in data:
        draft.code = str(data.get("code") or "")[:2_000_000]
    if "files" in data:
        editable = {
            item.get("name") for item in (exercise.files or [])
            if isinstance(item, dict) and not item.get("read_only")
        }
        draft.files = [
            {"name": item.get("name", ""), "content": str(item.get("content", ""))[:2_000_000]}
            for item in (data.get("files") or [])
            if isinstance(item, dict) and item.get("name") in editable
        ]
    await db.commit()
    await db.refresh(draft)
    return {"status": "ok", "updated_at": draft.updated_at.isoformat() if draft.updated_at else None}


# ── Code Execution ──

@router.post("/exercises/{exercise_id}/run", response_model=CodeRunResult)
async def run_code(
    exercise_id: int,
    req: CodeRunRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Execute code for an exercise.

    - Project-mode (exercise.files non-empty): run whole project in runtime venv.
    - Classic mode: run single code snippet.
    """
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)

    files = exercise.files or []
    if files:
        from app.services.project_runner import run_project
        # Merge client-sent files (latest edits) with read_only originals
        client = {f.get("name"): f for f in req.files if f.get("name")}
        merged = []
        for f in files:
            name = f.get("name", "")
            if name in client and not f.get("read_only"):
                merged.append({**f, "content": client[name].get("content", f.get("content", ""))})
            else:
                merged.append(f)
        res = run_project(exercise_id, merged, exercise.entrypoint or "main.py",
                          exercise.requirements or [])
        return CodeRunResult(
            stdout=res["stdout"], stderr=res["stderr"],
            passed=res["exit_code"] == 0, elapsed=res["elapsed"], env=res["env"],
        )

    # Classic single-file mode
    res = execute_code(req.code)
    return CodeRunResult(stdout=res["stdout"], stderr=res["stderr"],
                         passed=res["exit_code"] == 0, elapsed=res["elapsed"])


# ── Project-mode: env status (pilot) ──

@router.get("/exercises/{exercise_id}/env")
async def exercise_env_status(
    exercise_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Report runtime env readiness for a project-mode exercise."""
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)
    from app.services import project_runner
    return {
        "ready": project_runner.venv_ready(),
        "requirements": exercise.requirements or [],
        "installed": project_runner.installed_requirements(),
        "has_files": bool(exercise.files),
    }


# ── Code Review Agent ──

@router.post("/exercises/{exercise_id}/review")
async def review_code(
    exercise_id: int,
    req: CodeRunRequest,  # code + optional selection
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Review code with AI agent."""
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)

    context = f"{exercise.title}: {exercise.description[:200]}"
    agent = CodeAgent()

    if req.selection:
        answer = await agent.explain(req.selection, req.code, context)
    else:
        answer = await agent.review(req.code, context)

    from app.services.learning_runtime import record_event
    await record_event(
        db, event_type="code_review_requested", source="ui",
        learner_id=current.learner.id,
        checkpoint_id=exercise.checkpoint_id,
        payload={"exercise_id": exercise.id, "has_selection": bool(req.selection)},
        provenance={"endpoint": "exercise/review"},
    )
    await db.commit()

    return {"answer": answer}


@router.post("/code/ask")
async def ask_code_question(
    data: dict,
    current: CurrentLearner = Depends(get_current_learner),
):
    """Ask a question about code (without exercise context)."""
    agent = CodeAgent()
    selection = data.get("selection", "")
    code = data.get("code", "")
    question = data.get("question", "")
    context = data.get("context", "")

    if question:
        # Specific question about the code
        full_prompt = f"""## 代码
```python
{code}
```

## 选中的代码段
```python
{selection}
```

## 学生的问题
{question}

## 背景
{context}

请回答学生的问题，用 KaTeX 写公式，控制在 400 字以内。"""
        answer = await agent.llm.ainvoke(
            [HumanMessage(content=full_prompt)]
        )
        return {"answer": answer.content}
    elif selection:
        # Explain selected code
        answer = await agent.explain(selection, code, context)
        return {"answer": answer}
    else:
        # Review full code
        answer = await agent.review(code, context)
        return {"answer": answer}


# ── Embedding Indexing ──

@router.post("/projects/{project_id}/embeddings/index")
async def index_embeddings(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Batch index all chunks for a project via DeepSeek API."""
    await require_owned_project(db, current.learner.id, project_id)
    from app.models.project import Chunk, Source
    from app.services.embedding import embed_batch, cache_embedding

    result = await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id).order_by(Chunk.id)
    )
    chunks = result.scalars().all()
    if not chunks:
        raise HTTPException(404, "No chunks found")

    total = len(chunks)
    batch_size = 20
    indexed = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        try:
            texts = [c.content[:2000] for c in batch]
            embeddings = embed_batch(texts)
            for j, c in enumerate(batch):
                cache_embedding(c.id, embeddings[j])
            indexed += len(batch)
        except Exception as e:
            errors += 1
            print(f"[Embedding] Batch {i//batch_size} failed: {e}")
            continue

    return {"status": "ok", "indexed": indexed, "errors": errors, "total": total}


# ── Concept Questions (T7) ──

@router.get("/checkpoints/{checkpoint_id}/concepts")
async def list_concepts(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    rows = (await db.execute(
        select(ConceptQuestion)
        .where(ConceptQuestion.checkpoint_id == checkpoint_id)
        .order_by(ConceptQuestion.order)
    )).scalars().all()
    return [{
        "id": q.id,
        "checkpoint_id": q.checkpoint_id,
        "question": q.question,
        "options": q.options or [],
        "q_type": q.q_type,
        "difficulty": q.difficulty,
        "code": q.code,
        "order": q.order,
        # answers hidden from list; only used by explain/submit endpoints
    } for q in rows]


@router.post("/checkpoints/{checkpoint_id}/concepts/generate")
async def generate_concepts(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Create a background concept-question generation task (T7)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.id == cp.roadmap_id)
    )).scalar_one_or_none()

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "concept_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        learner_id=current.learner.id,
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        type="concept_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.task_runners import run_concept_generation
    manager.submit(task.id, run_concept_generation(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/concepts/task")
async def get_concept_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "concept_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    return _snapshot(task)


@router.post("/checkpoints/{checkpoint_id}/concepts/{question_id}/explain")
async def explain_concept(
    checkpoint_id: int,
    question_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Lazy AI explanation for one question, with the user's answer."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    q = (await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.id == question_id,
        ConceptQuestion.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    agent = ConceptAgent()
    answer = await agent.explain(
        {
            "question": q.question,
            "options": q.options or [],
            "answer_indexes": q.answer_indexes or [],
            "q_type": q.q_type,
            "expected_output": q.expected_output,
            "explanation": q.explanation,
        },
        user_answer=[int(i) for i in (data or {}).get("user_answer_indexes", [])],
    )
    from app.services.learning_runtime import record_event
    await record_event(
        db, event_type="explanation_requested", source="ui",
        learner_id=current.learner.id,
        checkpoint_id=checkpoint_id,
        payload={"item_type": "concept", "item_id": question_id},
        provenance={"endpoint": "concept/explain"},
    )
    await db.commit()
    return {"explanation": answer, "base_explanation": q.explanation}


@router.post("/checkpoints/{checkpoint_id}/concepts/{question_id}/submit")
async def submit_concept(
    checkpoint_id: int,
    question_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Instant grading: return correct/wrong + right answers (no LLM)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    q = (await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.id == question_id,
        ConceptQuestion.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    submission_key = None
    client_submission_id = str((data or {}).get("client_submission_id") or "").strip()
    if client_submission_id:
        raw_key = (
            f"concept:{current.learner.id}:{checkpoint_id}:{question_id}:"
            f"{client_submission_id}"
        )
        submission_key = raw_key if len(raw_key) <= 160 else (
            f"concept:{current.learner.id}:sha256:"
            f"{hashlib.sha256(raw_key.encode()).hexdigest()}"
        )
        replay = (await db.execute(select(LearningAttempt).where(
            LearningAttempt.learner_id == current.learner.id,
            LearningAttempt.client_submission_id == submission_key,
        ))).scalar_one_or_none()
        if replay:
            return {
                **dict(replay.result or {}),
                "attempt_id": replay.id,
                "idempotent_replay": True,
            }
    correct = sorted(q.answer_indexes or [])
    user = sorted(int(i) for i in (data or {}).get("answer_indexes", []))
    is_correct = user == correct and len(user) > 0
    from app.services.progress import record_concept_answer
    await record_concept_answer(checkpoint_id, question_id, is_correct, db=db)
    assistance_level = str((data or {}).get("assistance_level") or "none")
    from app.services.learning_runtime import (
        create_attempt, record_event, evaluate_checkpoint_status,
    )
    attempt = await create_attempt(
        db,
        learner_id=current.learner.id,
        checkpoint_id=checkpoint_id,
        item_type="concept",
        item_id=question_id,
        submission={"answer_indexes": user},
        result={"correct": is_correct, "answer_indexes": correct},
        assistance_level=assistance_level,
        attempt_role=str((data or {}).get("attempt_role") or "original"),
        client_submission_id=submission_key,
    )
    cp = await db.get(Checkpoint, checkpoint_id)
    roadmap = await db.get(Roadmap, cp.roadmap_id) if cp else None
    evaluation_event = await record_event(
        db, event_type="concept_attempt_evaluated", source="assessment",
        learner_id=current.learner.id,
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        payload={
            "attempt_id": attempt.id,
            "item_id": question_id,
            "question": q.question,
            "correct": is_correct,
            "independent": assistance_level == "none",
            "assistance_level": assistance_level,
        },
        provenance={"grader": "exact_match", "question_type": q.q_type},
        client_event_id=f"attempt:{attempt.id}:evaluated",
    )
    remediation_payload = None
    from app.services.remediation import (
        apply_retry_result, create_remediation_case, load_owned_case, serialize_case,
    )
    remediation_case_id = (data or {}).get("remediation_case_id")
    if remediation_case_id:
        remediation = await load_owned_case(
            db, current.learner.id, int(remediation_case_id),
        )
        if not remediation or remediation.item_type != "concept" or remediation.item_id != question_id:
            raise HTTPException(400, "纠错案例与当前概念题不匹配")
        if remediation.status != "explaining":
            raise HTTPException(409, "当前纠错案例不在原题重做阶段")
        remediation = await apply_retry_result(
            db, remediation=remediation, attempt=attempt,
            passed=is_correct, evidence_event_id=evaluation_event.id,
        )
        remediation_payload = serialize_case(remediation)
    elif not is_correct:
        remediation = await create_remediation_case(
            db,
            attempt=attempt,
            evidence_event_id=evaluation_event.id,
            item_snapshot={
                "question": q.question,
                "options": q.options or [],
                "explanation": q.explanation or "",
                "source_chunk_ids": q.source_chunk_ids or [],
                "assessment_meta": q.assessment_meta or {},
            },
            evaluation={
                "answer_indexes": correct,
                "user_answer_indexes": user,
            },
        )
        remediation_payload = serialize_case(remediation)
    from app.services.review import apply_assessment_result
    schedule = await apply_assessment_result(
        db,
        attempt=attempt,
        passed=is_correct,
        event_id=evaluation_event.id,
        question_form="original",
        remediation_status=(remediation_payload or {}).get("status"),
        is_review=False,
    )
    await evaluate_checkpoint_status(db, checkpoint_id, learner_id=current.learner.id)
    if roadmap:
        await evaluate_project_badge(
            db, learner_id=current.learner.id, project_id=roadmap.project_id,
        )
    response = {
        "correct": is_correct,
        "answer_indexes": correct,
        "user_answer_indexes": user,
        "explanation": q.explanation or "",
        "attempt_id": attempt.id,
        "assistance_level": assistance_level,
        "remediation": remediation_payload,
        "review_schedule_id": schedule.id,
        "review_due_at": schedule.due_at.isoformat(),
    }
    attempt.result = response
    await db.commit()
    return response


# ── Generate Exercises ──

@router.post("/checkpoints/{checkpoint_id}/exercises/generate")
async def generate_exercises(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """T8: background exercise generation — blueprint → per-exercise →
    executable verification (solution × test_cases must all pass)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.id == cp.roadmap_id)
    )).scalar_one_or_none()

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "exercise_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        learner_id=current.learner.id,
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        type="exercise_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.task_runners import run_exercise_generation
    manager.submit(task.id, run_exercise_generation(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/exercises/task")
async def get_exercise_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "exercise_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    return _snapshot(task)


@router.post("/exercises/{exercise_id}/submit")
async def submit_exercise(
    exercise_id: int,
    req: CodeRunRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """T8: judge user code against the exercise's test cases.
    Returns per-case results (passed/expected/actual)."""
    exercise = await require_owned_exercise(db, current.learner.id, exercise_id)
    submission_key = None
    if req.client_submission_id:
        raw_key = f"exercise:{current.learner.id}:{exercise_id}:{req.client_submission_id}"
        submission_key = raw_key if len(raw_key) <= 160 else (
            f"exercise:{current.learner.id}:sha256:{hashlib.sha256(raw_key.encode()).hexdigest()}"
        )
        replay = (await db.execute(select(LearningAttempt).where(
            LearningAttempt.learner_id == current.learner.id,
            LearningAttempt.client_submission_id == submission_key,
        ))).scalar_one_or_none()
        if replay:
            return {**dict(replay.result or {}), "attempt_id": replay.id, "idempotent_replay": True}

    effective_code = req.code

    async def persist_attempt(response: dict, passed_ok: bool):
        from app.services.learning_runtime import (
            create_attempt, record_event, evaluate_checkpoint_status,
        )
        code_bytes = (effective_code or "").encode("utf-8")
        file_refs = [
            {
                "name": f.get("name", ""),
                "sha256": hashlib.sha256(str(f.get("content", "")).encode("utf-8")).hexdigest(),
            }
            for f in (req.files or []) if f.get("name")
        ]
        submission = {
            "code": effective_code[:65536],
            "code_sha256": hashlib.sha256(code_bytes).hexdigest(),
            "truncated": len(code_bytes) > 65536,
            "files": file_refs,
        }
        attempt = await create_attempt(
            db,
            learner_id=current.learner.id,
            checkpoint_id=exercise.checkpoint_id,
            item_type="exercise",
            item_id=exercise.id,
            submission=submission,
            result=response,
            assistance_level=req.assistance_level or "none",
            attempt_role=req.attempt_role or "original",
            client_submission_id=submission_key,
        )
        cp = await db.get(Checkpoint, exercise.checkpoint_id)
        roadmap = await db.get(Roadmap, cp.roadmap_id) if cp else None
        evaluation_event = await record_event(
            db, event_type="exercise_attempt_evaluated", source="assessment",
            learner_id=current.learner.id,
            project_id=roadmap.project_id if roadmap else None,
            checkpoint_id=exercise.checkpoint_id,
            payload={
                "attempt_id": attempt.id,
                "item_id": exercise.id,
                "passed": passed_ok,
                "assistance_level": req.assistance_level or "none",
            },
            provenance={"grader": exercise.judge_mode or "test_cases"},
            client_event_id=f"attempt:{attempt.id}:evaluated",
        )
        from app.services.remediation import (
            apply_retry_result, create_remediation_case, load_owned_case, serialize_case,
        )
        remediation_payload = None
        if req.remediation_case_id:
            remediation = await load_owned_case(
                db, current.learner.id, int(req.remediation_case_id),
            )
            if not remediation or remediation.item_type != "exercise" or remediation.item_id != exercise.id:
                raise HTTPException(400, "纠错案例与当前代码题不匹配")
            if remediation.status != "explaining":
                raise HTTPException(409, "当前纠错案例不在原题重做阶段")
            remediation = await apply_retry_result(
                db, remediation=remediation, attempt=attempt,
                passed=passed_ok, evidence_event_id=evaluation_event.id,
            )
            remediation_payload = serialize_case(remediation)
        elif not passed_ok:
            remediation = await create_remediation_case(
                db,
                attempt=attempt,
                evidence_event_id=evaluation_event.id,
                item_snapshot={
                    "title": exercise.title,
                    "description": exercise.description,
                    "hints": exercise.hints or [],
                    "judge_mode": exercise.judge_mode or "test_cases",
                    "assessment_meta": exercise.assessment_meta or {},
                },
                evaluation=response,
            )
            remediation_payload = serialize_case(remediation)
        from app.services.review import apply_assessment_result
        schedule = await apply_assessment_result(
            db,
            attempt=attempt,
            passed=passed_ok,
            event_id=evaluation_event.id,
            question_form="original",
            remediation_status=(remediation_payload or {}).get("status"),
            is_review=False,
        )
        await evaluate_checkpoint_status(
            db, exercise.checkpoint_id, learner_id=current.learner.id,
        )
        if roadmap:
            await evaluate_project_badge(
                db, learner_id=current.learner.id, project_id=roadmap.project_id,
            )
        response["review_schedule_id"] = schedule.id
        response["review_due_at"] = schedule.due_at.isoformat()
        attempt.result = {
            **response,
            "attempt_id": attempt.id,
            "remediation": remediation_payload,
            "review_schedule_id": schedule.id,
            "review_due_at": schedule.due_at.isoformat(),
        }
        await db.commit()
        return attempt.id, remediation_payload

    # Project-mode judging: run the whole project, check stdout
    if (exercise.files or []) and exercise.judge_mode == "stdout_check":
        from app.services.project_runner import run_project, check_stdout
        client = {f.get("name"): f for f in req.files if f.get("name")}
        merged = []
        for f in (exercise.files or []):
            name = f.get("name", "")
            if name in client and not f.get("read_only"):
                merged.append({**f, "content": client[name].get("content", f.get("content", ""))})
            else:
                merged.append(f)
        res = run_project(exercise_id, merged, exercise.entrypoint or "main.py",
                          exercise.requirements or [])
        if res["exit_code"] != 0 and not res["timed_out"]:
            response = {"passed": 0, "total": 1, "results": [
                {"passed": False, "expected": "正常运行", "actual": f"退出码 {res['exit_code']}",
                 "stderr": res["stderr"][:200]}
            ], "error": None}
            response["attempt_id"], response["remediation"] = await persist_attempt(response, False)
            return response
        check = check_stdout(res["stdout"], exercise.judge_config or {})
        if check["passed"]:
            from app.services.progress import record_exercise_solved
            await record_exercise_solved(exercise.checkpoint_id, exercise.id, db=db)
        response = {"passed": 1 if check["passed"] else 0, "total": 1,
                "results": [{"passed": check["passed"], "expected": check["expected"],
                              "actual": check["actual"], "detail": check["detail"]}],
                "stdout": res["stdout"][-1000:]}
        response["attempt_id"], response["remediation"] = await persist_attempt(response, bool(check["passed"]))
        return response

    test_cases = exercise.test_cases or []
    if not test_cases:
        response = {"passed": 0, "total": 0, "results": [], "error": "该题没有测试用例"}
        response["attempt_id"], response["remediation"] = await persist_attempt(response, False)
        return response

    from app.services.exercise_agent import ExerciseAgent
    results = ExerciseAgent.verify_exercise(effective_code, test_cases)
    passed = sum(1 for r in results if r["passed"])
    if passed == len(results) and passed > 0:
        from app.services.progress import record_exercise_solved
        await record_exercise_solved(exercise.checkpoint_id, exercise.id, db=db)
    response = {"passed": passed, "total": len(results), "results": results}
    response["attempt_id"], response["remediation"] = await persist_attempt(
        response, passed == len(results) and passed > 0
    )
    return response
