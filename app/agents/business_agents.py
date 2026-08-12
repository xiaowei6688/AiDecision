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
