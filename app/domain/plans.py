"""用于跨系统任务的已校验、不可直接执行的计划。"""

from __future__ import annotations

from enum import StrEnum
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.actions.registry import ActionRegistry


class PlanStatus(StrEnum):
    PLANNED = "planned"
    APPROVED = "approved"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    """跨系统计划中的单个查询或动作。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    kind: Literal["query", "action"]
    datasource: str | None = None
    question: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    action_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    status: PlanStatus = PlanStatus.PLANNED
    result: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    attempts: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_kind_specific_fields(self) -> "PlanStep":
        if self.kind == "query" and (not self.datasource or not self.question):
            raise ValueError("query steps require datasource and question")
        if self.kind == "action" and not self.action_id:
            raise ValueError("action steps require action_id")
        return self


class ExecutionPlan(BaseModel):
    """可供审核的计划；创建时只进行校验，不执行实际操作。"""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    steps: list[PlanStep] = Field(min_length=1)
    status: PlanStatus = PlanStatus.PLANNED
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_note: str | None = None

    def approve(self, approver: str | None, note: str | None = None) -> None:
        if self.status != PlanStatus.PLANNED:
            raise ValueError(f"plan cannot be approved from status: {self.status}")
        self.status = PlanStatus.APPROVED
        self.approved_by = approver
        self.approved_at = datetime.now(timezone.utc)
        self.approval_note = note


def validate_execution_plan(
    plan: ExecutionPlan,
    actions: ActionRegistry,
    datasources: set[str],
) -> ExecutionPlan:
    """计划进入审核前，校验依赖关系和动作输入。"""

    step_ids = [step.step_id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("plan step_id values must be unique")

    known_steps = set(step_ids)
    for step in plan.steps:
        unknown_dependencies = set(step.depends_on) - known_steps
        if unknown_dependencies:
            raise ValueError(
                f"step {step.step_id} depends on unknown steps: {', '.join(sorted(unknown_dependencies))}"
            )
        if step.step_id in step.depends_on:
            raise ValueError(f"step {step.step_id} cannot depend on itself")
        if step.kind == "query":
            assert step.datasource is not None
            if step.datasource not in datasources:
                raise ValueError(f"step {step.step_id} uses unknown datasource: {step.datasource}")
            continue
        assert step.action_id is not None
        action = actions.get(step.action_id)
        if action.input_model is not None:
            step.params = action.input_model.model_validate(step.params).model_dump(mode="json")
        step.idempotency_key = _step_idempotency_key(plan.plan_id, step)

    _ensure_acyclic(plan.steps)
    return plan


def _step_idempotency_key(plan_id: str, step: PlanStep) -> str:
    payload = json.dumps(
        {"plan_id": plan_id, "step_id": step.step_id, "action_id": step.action_id, "params": step.params},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"plan:{hashlib.sha256(payload).hexdigest()}"


def _ensure_acyclic(steps: list[PlanStep]) -> None:
    dependencies = {step.step_id: set(step.depends_on) for step in steps}
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("plan dependencies contain a cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in dependencies:
        visit(step_id)
