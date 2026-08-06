from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ActionInputSpec:
    """A single input expected by a business action."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    resolver: str | None = None


@dataclass(frozen=True)
class ActionConfirmation:
    """Human confirmation policy for a business action."""

    required: bool = False
    template: str | None = None


@dataclass(frozen=True)
class ActionExecutorSpec:
    """Where and how the real business operation is executed."""

    adapter: str
    method: str
    operation_type: Literal["query", "command", "workflow"] = "command"


@dataclass(frozen=True)
class ActionSpec:
    """Structured contract used by the Agent to understand a business action."""

    action_id: str
    title: str
    description: str
    system: str
    inputs: list[ActionInputSpec]
    executor: ActionExecutorSpec
    intent_examples: list[str] = field(default_factory=list)
    pre_checks: list[str] = field(default_factory=list)
    required_roles: list[str] = field(default_factory=list)
    confirmation: ActionConfirmation = field(default_factory=ActionConfirmation)
    risk_level: Literal["low", "medium", "high"] = "low"
    success_template: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Return the compact, model-facing action description."""

        return {
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "system": self.system,
            "inputs": [
                {
                    "name": item.name,
                    "type": item.type,
                    "description": item.description,
                    "required": item.required,
                    "resolver": item.resolver,
                }
                for item in self.inputs
            ],
            "intent_examples": self.intent_examples,
            "pre_checks": self.pre_checks,
            "required_roles": self.required_roles,
            "confirmation_required": self.confirmation.required,
            "risk_level": self.risk_level,
        }


@dataclass(frozen=True)
class ActionExecutionContext:
    """Runtime facts used by policies and adapters."""

    user_id: str | None = None
    user_roles: list[str] = field(default_factory=list)
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResult:
    """Normalized action execution result."""

    status: Literal["success", "failed", "requires_confirmation"]
    action_id: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
