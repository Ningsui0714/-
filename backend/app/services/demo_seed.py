"""Idempotent offline competition demo dataset."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import Learner, LearnerProfile, LearningAttempt, UserAccount
from app.models.project import Checkpoint, ConceptQuestion, Exercise, Lecture, Project, Roadmap
from app.services.learning_runtime import create_attempt, ensure_kernel_states, record_event
from app.services.remediation import create_remediation_case
from app.services.review import apply_assessment_result


DEMO_USERNAME = "competition-demo"
DEMO_PROJECT_NAME = "LearnFlow 纠错闭环演示"
DEMO_CHECKPOINT_TITLE = "边界条件：安全平均值"


async def seed_competition_demo(db: AsyncSession) -> dict:
    account = (await db.execute(select(UserAccount).where(
        UserAccount.username_normalized == DEMO_USERNAME,
    ))).scalar_one_or_none()
    if not account:
        account = UserAccount(
            username=DEMO_USERNAME,
            username_normalized=DEMO_USERNAME,
            password_hash=None,
            is_legacy_demo=True,
        )
        db.add(account)
        await db.flush()

    learner = (await db.execute(select(Learner).where(
        Learner.user_id == account.id,
    ))).scalar_one_or_none()
    if not learner:
        learner = Learner(
            user_id=account.id,
            key="competition-demo-learner",
            display_name="比赛演示学习者",
        )
        db.add(learner)
        await db.flush()

    profile = await db.get(LearnerProfile, learner.id)
    if not profile:
        profile = LearnerProfile(
            learner_id=learner.id,
            education_stage="undergraduate",
            background="掌握 Python 基础语法，正在训练边界条件与测试思维",
            focus_areas=["Python", "软件测试", "错误纠正"],
            weekly_hours=6,
            preferred_modes=["example", "steps", "practice"],
            career_goal="能独立定位并修复真实代码错误",
            career_goal_status="confirmed",
        )
        db.add(profile)
    await ensure_kernel_states(db, learner.id)

    project = (await db.execute(select(Project).where(
        Project.learner_id == learner.id,
        Project.name == DEMO_PROJECT_NAME,
    ))).scalar_one_or_none()
    if not project:
        project = Project(
            learner_id=learner.id,
            name=DEMO_PROJECT_NAME,
            description=(
                "离线演示：故意答错或提交带边界错误的代码，体验证据纠错、"
                "换讲法、重做原题、变式验证和证据回写。"
            ),
            user_level="beginner",
        )
        db.add(project)
        await db.flush()

    roadmap = (await db.execute(select(Roadmap).where(
        Roadmap.project_id == project.id,
    ))).scalar_one_or_none()
    if not roadmap:
        roadmap = Roadmap(
            project_id=project.id,
            raw_json={
                "title": "从失败测试到可迁移修复",
                "source": "seeded_competition_demo",
                "offline": True,
            },
            conversation_history=[],
        )
        db.add(roadmap)
        await db.flush()

    checkpoint = (await db.execute(select(Checkpoint).where(
        Checkpoint.roadmap_id == roadmap.id,
        Checkpoint.title == DEMO_CHECKPOINT_TITLE,
    ))).scalar_one_or_none()
    if not checkpoint:
        checkpoint = Checkpoint(
            roadmap_id=roadmap.id,
            title=DEMO_CHECKPOINT_TITLE,
            description="通过空列表失败用例，建立输入校验与证据驱动调试习惯。",
            order=1,
            prerequisites=[],
            learning_status="in_progress",
            learning_contract={
                "concept_ids": ["empty-input-guard"],
                "knowledge_target": {"rule": "空集合不能直接作为除数来源"},
                "practice_target": {"artifact": "通过空列表与普通列表测试"},
                "exit_criteria": ["retry_passed", "variant_verified"],
                "source": "seeded_competition_demo",
            },
            brief={"key_concepts": ["边界条件", "防御式编程", "测试契约"]},
            progress={"lecture_read": False, "exercises_done": 0},
        )
        db.add(checkpoint)
        await db.flush()

    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint.id,
    ))).scalar_one_or_none()
    if not lecture:
        lecture = Lecture(
            checkpoint_id=checkpoint.id,
            status="published",
            sections=[
                {
                    "title": "失败证据比猜测更可靠",
                    "content": "先观察失败输入、实际输出和预期输出，再定位首次分歧。",
                    "keywords": ["evidence", "expected", "actual"],
                    "questions": ["空列表为什么会触发除零？"],
                },
                {
                    "title": "最小修正规则",
                    "content": "对可能为空的集合先做前置判断；修复后必须重做并用变式验证。",
                    "keywords": ["guard clause", "retry", "transfer"],
                    "questions": ["为什么答对原题还不等于掌握？"],
                },
            ],
            plan=["失败证据", "最小修正", "变式验证"],
        )
        db.add(lecture)

    concept = (await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.checkpoint_id == checkpoint.id,
        ConceptQuestion.order == 1,
    ))).scalar_one_or_none()
    if not concept:
        concept = ConceptQuestion(
            checkpoint_id=checkpoint.id,
            question="函数 safe_average(values) 遇到空列表时，哪一个前置判断最完整？",
            options=[
                "if values is None:",
                "if not values:",
                "if len(values) < 0:",
                "不需要判断，sum 会自动处理除法",
            ],
            answer_indexes=[1],
            q_type="single",
            difficulty="easy",
            explanation="`if not values` 同时覆盖 None 之外的空列表，能阻止除数变为 0。",
            source_chunk_ids=[],
            assessment_meta={
                "mode": "diagnostic",
                "learning_target": "识别空集合边界条件",
                "evidence_claim": "学习者能选择覆盖空列表的前置判断",
                "variant": {
                    "type": "concept_choice",
                    "validated": True,
                    "prompt": "迁移到配置加载：entries 为空元组时也要返回默认配置，哪项判断最合适？",
                    "options": [
                        "if entries is None:",
                        "if not entries:",
                        "if len(entries) < 0:",
                        "不需要判断",
                    ],
                    "answer_indexes": [1],
                },
            },
            order=1,
        )
        db.add(concept)

    exercise = (await db.execute(select(Exercise).where(
        Exercise.checkpoint_id == checkpoint.id,
        Exercise.title == "修复 safe_average 的空列表错误",
    ))).scalar_one_or_none()
    if not exercise:
        exercise = Exercise(
            checkpoint_id=checkpoint.id,
            title="修复 safe_average 的空列表错误",
            description=(
                "程序从 stdin 读取一个 Python 列表并输出一位小数。"
                "当前实现对空列表会除零；请用最小修改让所有测试通过。"
            ),
            starter_code=(
                "import ast\nimport sys\n\n"
                "def safe_average(values):\n"
                "    return sum(values) / len(values)\n\n"
                "values = ast.literal_eval(sys.stdin.read().strip())\n"
                "print(f\"{safe_average(values):.1f}\")\n"
            ),
            solution=(
                "import ast\nimport sys\n\n"
                "def safe_average(values):\n"
                "    if not values:\n"
                "        return 0.0\n"
                "    return sum(values) / len(values)\n\n"
                "values = ast.literal_eval(sys.stdin.read().strip())\n"
                "print(f\"{safe_average(values):.1f}\")\n"
            ),
            test_cases=[
                {"input": "[]", "expected": "0.0"},
                {"input": "[2, 4, 6]", "expected": "4.0"},
                {"input": "[-2, 2]", "expected": "0.0"},
            ],
            hints=[
                "先看第一个失败用例的输入与异常。",
                "在除法发生前处理空集合。",
            ],
            order=1,
            judge_mode="test_cases",
            assessment_meta={
                "mode": "practice",
                "learning_target": "修复空集合边界条件",
                "evidence_target": {"practice": "retry_then_variant"},
                "variant": {
                    "type": "predict_output",
                    "validated": True,
                    "prompt": "迁移验证：不运行程序，预测修复后的函数处理新输入时的输出。",
                    "input": "[10, 20, 30, 40]",
                    "expected": "25.0",
                },
            },
        )
        db.add(exercise)

    await db.flush()

    # Seed two canonical evidence histories so /review is useful immediately:
    # a concept due for a validated transfer variant, and an open code error.
    concept_seed_key = "competition-demo-review-concept-baseline"
    concept_attempt = (await db.execute(select(LearningAttempt).where(
        LearningAttempt.client_submission_id == concept_seed_key,
    ))).scalar_one_or_none()
    if not concept_attempt:
        baseline_at = datetime.utcnow() - timedelta(days=3, minutes=1)
        concept_attempt = await create_attempt(
            db,
            learner_id=learner.id,
            checkpoint_id=checkpoint.id,
            item_type="concept",
            item_id=concept.id,
            submission={"answer_indexes": [1]},
            result={"correct": True, "answer_indexes": [1]},
            assistance_level="none",
            attempt_role="original",
            client_submission_id=concept_seed_key,
        )
        concept_attempt.started_at = baseline_at
        concept_attempt.submitted_at = baseline_at
        concept_attempt.evaluated_at = baseline_at
        concept_event = await record_event(
            db,
            learner_id=learner.id,
            project_id=project.id,
            checkpoint_id=checkpoint.id,
            event_type="concept_attempt_evaluated",
            source="seed",
            payload={
                "attempt_id": concept_attempt.id,
                "item_id": concept.id,
                "question": concept.question,
                "correct": True,
                "independent": True,
                "assistance_level": "none",
            },
            occurred_at=baseline_at,
            provenance={"seed": "competition-review-v1", "grader": "exact_match"},
            client_event_id="competition-demo-review-concept-baseline-evaluated",
        )
        await apply_assessment_result(
            db,
            attempt=concept_attempt,
            passed=True,
            event_id=concept_event.id,
            question_form="original",
            is_review=False,
            now=baseline_at,
        )

    exercise_seed_key = "competition-demo-review-exercise-wrong"
    exercise_attempt = (await db.execute(select(LearningAttempt).where(
        LearningAttempt.client_submission_id == exercise_seed_key,
    ))).scalar_one_or_none()
    if not exercise_attempt:
        failed_result = {
            "passed": 2,
            "total": 3,
            "results": [
                {
                    "input": "[]",
                    "expected": "0.0",
                    "actual": "",
                    "stderr": "ZeroDivisionError: division by zero",
                    "passed": False,
                },
                {"input": "[2, 4, 6]", "expected": "4.0", "actual": "4.0", "passed": True},
                {"input": "[-2, 2]", "expected": "0.0", "actual": "0.0", "passed": True},
            ],
        }
        exercise_attempt = await create_attempt(
            db,
            learner_id=learner.id,
            checkpoint_id=checkpoint.id,
            item_type="exercise",
            item_id=exercise.id,
            submission={"code": exercise.starter_code, "seeded": True},
            result=failed_result,
            assistance_level="none",
            attempt_role="original",
            client_submission_id=exercise_seed_key,
        )
        exercise_event = await record_event(
            db,
            learner_id=learner.id,
            project_id=project.id,
            checkpoint_id=checkpoint.id,
            event_type="exercise_attempt_evaluated",
            source="seed",
            payload={
                "attempt_id": exercise_attempt.id,
                "item_id": exercise.id,
                "passed": False,
                "assistance_level": "none",
            },
            provenance={"seed": "competition-review-v1", "grader": "test_cases"},
            client_event_id="competition-demo-review-exercise-wrong-evaluated",
        )
        remediation = await create_remediation_case(
            db,
            attempt=exercise_attempt,
            evidence_event_id=exercise_event.id,
            item_snapshot={
                "title": exercise.title,
                "description": exercise.description,
                "hints": exercise.hints or [],
                "judge_mode": exercise.judge_mode,
                "assessment_meta": exercise.assessment_meta or {},
            },
            evaluation=failed_result,
        )
        await apply_assessment_result(
            db,
            attempt=exercise_attempt,
            passed=False,
            event_id=exercise_event.id,
            question_form="original",
            remediation_status=remediation.status,
            is_review=False,
        )

    await record_event(
        db,
        learner_id=learner.id,
        project_id=project.id,
        checkpoint_id=checkpoint.id,
        event_type="project_created",
        source="seed",
        payload={
            "project_id": project.id,
            "name": project.name,
            "description": project.description,
            "demo": True,
        },
        provenance={"seed": "competition-remediation-v1", "offline": True},
        client_event_id="competition-demo-project-seeded",
    )
    await db.commit()
    return {
        "account_id": account.id,
        "learner_id": learner.id,
        "project_id": project.id,
        "checkpoint_id": checkpoint.id,
        "concept_question_id": concept.id,
        "exercise_id": exercise.id,
        "entry_path": "/review",
        "remediation_entry_path": f"/projects/{project.id}/checkpoints/{checkpoint.id}/exercises",
        "project_name": project.name,
        "offline": True,
    }


async def demo_manifest(db: AsyncSession, learner_id: int) -> dict | None:
    row = (await db.execute(
        select(Project, Roadmap, Checkpoint)
        .join(Roadmap, Roadmap.project_id == Project.id)
        .join(Checkpoint, Checkpoint.roadmap_id == Roadmap.id)
        .where(
            Project.learner_id == learner_id,
            Project.name == DEMO_PROJECT_NAME,
            Checkpoint.title == DEMO_CHECKPOINT_TITLE,
        )
    )).first()
    if not row:
        return None
    project, _, checkpoint = row
    return {
        "project_id": project.id,
        "checkpoint_id": checkpoint.id,
        "project_name": project.name,
        "entry_path": "/review",
        "remediation_entry_path": f"/projects/{project.id}/checkpoints/{checkpoint.id}/exercises",
        "offline": True,
    }
