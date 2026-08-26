"""Validated adapter for the auditable learning-work-task Plan stage."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import settings


class LearningTaskPlanError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


AgentRole = Literal[
    "task_contract_compiler",
    "plan_builder",
    "evidence_explorer",
    "candidate_planner",
    "critic_committee",
    "targeted_patch_agent",
    "artifact_publisher",
]

AgentTool = Literal[
    "task_database",
    "knowledge_base_pro",
    "official_web",
    "evidence_verifier",
    "candidate_generator",
    "candidate_critic",
    "task_compiler",
]

ArtifactType = Literal[
    "task_contract",
    "task_plan",
    "evidence_ledger",
    "step_plan",
    "candidate_set",
    "critic_report",
    "patch_plan",
    "selected_candidate",
    "delivery_bundle",
    "failure_report",
]


class PlanUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unknown_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    question: str = Field(min_length=4, max_length=500)
    required_evidence: Literal[
        "upstream",
        "database",
        "knowledge_base",
        "official_web",
        "official_or_upstream",
        "user_confirmation",
    ]
    blocking: bool = True


class PlanWorkPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    agent_role: AgentRole
    objective: str = Field(min_length=8, max_length=1000)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    allowed_tools: list[AgentTool] = Field(min_length=1, max_length=7)
    expected_artifact: ArtifactType
    completion_condition: str = Field(min_length=8, max_length=1000)


class LearningTaskPlan(BaseModel):
    """Visible planning artifact; hidden reasoning fields are forbidden."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["learning-work-task-plan-v1"]
    run_id: str = Field(min_length=8, max_length=100)
    plan_version: int = Field(ge=1, le=1000)
    goal: str = Field(min_length=8, max_length=1000)
    task_contract_fingerprint: str = Field(min_length=16, max_length=64)
    success_criteria: list[str] = Field(min_length=3, max_length=12)
    unknowns: list[PlanUnknown] = Field(default_factory=list, max_length=20)
    work_packages: list[PlanWorkPackage] = Field(min_length=1, max_length=12)
    repair_budget: int = Field(default=2, ge=0, le=2)
    stop_conditions: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> "LearningTaskPlan":
        package_ids = [item.package_id for item in self.work_packages]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("Plan 工作包 ID 必须唯一")
        known = set(package_ids)
        dependencies = {}
        for item in self.work_packages:
            if item.package_id in item.depends_on:
                raise ValueError("Plan 工作包不能依赖自身")
            missing = set(item.depends_on) - known
            if missing:
                raise ValueError(
                    "Plan 工作包依赖不存在: " + ", ".join(sorted(missing))
                )
            dependencies[item.package_id] = set(item.depends_on)
        while dependencies:
            ready = {key for key, values in dependencies.items() if not values}
            if not ready:
                raise ValueError("Plan 工作包依赖存在环")
            dependencies = {
                key: values - ready
                for key, values in dependencies.items()
                if key not in ready
            }
        return self


class LearningTaskPlanRun(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["learning-work-task-agent-state-v1"]
    run_id: str = Field(pattern=r"^run_[A-Fa-f0-9]{16,96}$")
    phase: Literal[
        "INTAKE", "CONTRACT_READY", "PLAN_READY", "EVIDENCE_READY",
        "STEP_PLAN_READY", "CANDIDATES_READY", "REVIEWED",
        "PATCH_REQUIRED", "COMMIT_READY", "COMMITTED", "FAILED",
    ]
    status: Literal["active", "needs_input", "completed", "failed"]
    checkpoint_version: int = Field(ge=1)
    task_contract: dict[str, Any]
    plan: LearningTaskPlan
    state: dict[str, Any]
    next_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_lock(self) -> "LearningTaskPlanRun":
        fingerprint = str(self.task_contract.get("semantic_fingerprint") or "")
        if self.plan.run_id != self.run_id:
            raise ValueError("Plan run_id 与运行不一致")
        if not fingerprint or self.plan.task_contract_fingerprint != fingerprint:
            raise ValueError("Plan 任务语义指纹与任务契约不一致")
        return self


class LearningTaskPlanGateway:
    _READ_ATTEMPTS = 4
    _TRANSIENT_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or settings.learning_task_conversion_base_url
        ).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.learning_task_conversion_timeout_seconds
        )
        self.transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        attempts = self._READ_ATTEMPTS if normalized_method == "GET" else 1
        response: httpx.Response | None = None
        last_error: httpx.HTTPError | None = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.request(
                        normalized_method, path, json=payload,
                    )
                    if (
                        response.status_code not in self._TRANSIENT_STATUS_CODES
                        or attempt == attempts - 1
                    ):
                        break
                except httpx.HTTPError as exc:
                    last_error = exc
                    if attempt == attempts - 1:
                        break
                await asyncio.sleep(min(0.15 * (2 ** attempt), 0.8))
        if response is None:
            status_code = 504 if isinstance(last_error, httpx.TimeoutException) else 502
            raise LearningTaskPlanError(
                f"任务 Plan 服务不可用: {last_error or '连接失败'}",
                status_code=status_code,
            ) from last_error
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            status_code = response.status_code if response.status_code in {404, 409, 422} else 502
            raise LearningTaskPlanError(
                f"任务 Plan 服务返回 {response.status_code}: {detail}",
                status_code=status_code,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise LearningTaskPlanError("任务 Plan 服务返回了无效 JSON") from exc
        if not isinstance(result, dict):
            raise LearningTaskPlanError("任务 Plan 服务返回值必须是 JSON 对象")
        return result

    @staticmethod
    def _validate_run(payload: dict[str, Any]) -> dict[str, Any]:
        # The deployed service stores the state schema marker inside ``state``
        # instead of repeating it at the run root. Normalize the wire format so
        # LearnFlow can expose one stable contract to its frontend.
        normalized = deepcopy(payload)
        if not normalized.get("schema_version"):
            state = normalized.get("state")
            if isinstance(state, dict):
                normalized["schema_version"] = state.get("schema_version")
        try:
            return LearningTaskPlanRun.model_validate(normalized).model_dump(mode="json")
        except ValidationError as exc:
            raise LearningTaskPlanError(
                f"任务 Plan 运行状态不符合契约: {exc.errors()[0]['msg']}"
            ) from exc

    async def create(self, user_query: str) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            "/api/v1/learning-work-task-agent/runs",
            payload={"user_query": user_query},
        )
        return self._validate_run(payload)

    async def get(self, run_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET", f"/api/v1/learning-work-task-agent/runs/{run_id}"
        )
        validated = self._validate_run(payload)
        if validated["run_id"] != run_id:
            raise LearningTaskPlanError("任务 Plan 服务返回了错误的运行 ID")
        return validated

    async def confirm(
        self,
        run_id: str,
        *,
        expected_plan_version: int,
    ) -> dict[str, Any]:
        current = await self.get(run_id)
        current_version = int(current["plan"]["plan_version"])
        if current["phase"] == "PLAN_READY" and current_version > expected_plan_version:
            return current
        if current["phase"] != "CONTRACT_READY":
            raise LearningTaskPlanError(
                f"当前阶段 {current['phase']} 不能确认 Plan",
                status_code=409,
            )
        if current_version != expected_plan_version:
            raise LearningTaskPlanError(
                f"Plan 版本已变化，当前为 v{current_version}",
                status_code=409,
            )
        plan = deepcopy(current["plan"])
        plan["plan_version"] = current_version + 1
        try:
            payload = await self._request(
                "POST",
                f"/api/v1/learning-work-task-agent/runs/{run_id}/plan",
                payload={"plan": plan},
            )
        except LearningTaskPlanError as exc:
            # A concurrent confirmation may have won after the read above.
            if exc.status_code not in {409, 422}:
                raise
            recovered = await self.get(run_id)
            if (
                recovered["phase"] == "PLAN_READY"
                and int(recovered["plan"]["plan_version"]) > expected_plan_version
            ):
                return recovered
            raise
        return self._validate_run(payload)
