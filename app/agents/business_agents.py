"""Business Agent contracts consumed by the single orchestration Agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class RecommendedQuery(BaseModel):
    datasource: str
    question: str
    filters: dict[str, Any] = Field(default_factory=dict)


class RecommendedAction(BaseModel):
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class BusinessAdvice(BaseModel):
    """Structured, non-executable recommendation returned by a Business Agent."""

    facts_and_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    recommended_queries: list[RecommendedQuery] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class BusinessCollaborationStep(BaseModel):
    """One Business Agent consultation chosen by the orchestration Agent."""

    business_id: str
    reason: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class BusinessCollaborationPlan(BaseModel):
    """An auditable dependency graph for Business Agent reasoning."""

    task: str = Field(min_length=1)
    steps: list[BusinessCollaborationStep] = Field(min_length=1)


def validate_collaboration_plan(
    plan: BusinessCollaborationPlan,
    registry: "BusinessAgentRegistry",
) -> BusinessCollaborationPlan:
    business_ids = [step.business_id for step in plan.steps]
    if len(business_ids) != len(set(business_ids)):
        raise ValueError("a Business Agent can appear only once in a collaboration plan")
    known = set(business_ids)
    for step in plan.steps:
        registry.get(step.business_id)
        unknown = set(step.depends_on) - known
        if unknown:
            raise ValueError(
                f"Business Agent {step.business_id} depends on unknown agents: {', '.join(sorted(unknown))}"
            )
        if step.business_id in step.depends_on:
            raise ValueError(f"Business Agent {step.business_id} cannot depend on itself")
    _ensure_collaboration_acyclic(plan.steps)
    return plan


def collaboration_waves(plan: BusinessCollaborationPlan) -> list[list[BusinessCollaborationStep]]:
    """Return dependency-safe batches that can be consulted in parallel."""

    remaining = {step.business_id: step for step in plan.steps}
    completed: set[str] = set()
    waves: list[list[BusinessCollaborationStep]] = []
    while remaining:
        wave = [step for step in remaining.values() if set(step.depends_on).issubset(completed)]
        if not wave:
            raise ValueError("collaboration plan dependencies contain a cycle")
        waves.append(wave)
        completed.update(step.business_id for step in wave)
        for step in wave:
            del remaining[step.business_id]
    return waves


def _ensure_collaboration_acyclic(steps: list[BusinessCollaborationStep]) -> None:
    dependencies = {step.business_id: set(step.depends_on) for step in steps}
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(business_id: str) -> None:
        if business_id in visiting:
            raise ValueError("collaboration plan dependencies contain a cycle")
        if business_id in visited:
            return
        visiting.add(business_id)
        for dependency in dependencies[business_id]:
            visit(dependency)
        visiting.remove(business_id)
        visited.add(business_id)

    for business_id in dependencies:
        visit(business_id)


def parse_business_advice(content: str) -> BusinessAdvice:
    """Validate a Business Agent response without accepting prose as advice."""

    try:
        return BusinessAdvice.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Business Agent must return valid BusinessAdvice JSON: {exc}") from exc


@dataclass(frozen=True)
class BusinessAgentManifest:
    """A domain capability, not a user-selectable root Agent."""

    business_id: str
    title: str
    description: str
    system_prompt: str
    datasources: tuple[str, ...]
    action_prefixes: tuple[str, ...]
    cross_system_notes: str = ""

    def public_dict(self) -> dict[str, object]:
        return {
            "business_id": self.business_id,
            "title": self.title,
            "description": self.description,
            "datasources": list(self.datasources),
            "action_prefixes": list(self.action_prefixes),
        }


class BusinessAgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BusinessAgentManifest] = {}

    def register(self, manifest: BusinessAgentManifest) -> None:
        if not manifest.business_id:
            raise ValueError("business_id is required")
        if manifest.business_id in self._agents:
            raise ValueError(f"Business Agent already registered: {manifest.business_id}")
        self._agents[manifest.business_id] = manifest

    def get(self, business_id: str) -> BusinessAgentManifest:
        try:
            return self._agents[business_id]
        except KeyError as exc:
            raise KeyError(f"Unknown business Agent: {business_id}") from exc

    def list(self) -> list[BusinessAgentManifest]:
        return list(self._agents.values())


default_business_agent_registry = BusinessAgentRegistry()
