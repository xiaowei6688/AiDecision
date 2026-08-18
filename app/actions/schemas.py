from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class ActionInputSpec:
    """业务动作所需的单个输入项。"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    resolver: str | None = None


@dataclass(frozen=True)
class ActionConfirmation:
    """业务动作的人机确认策略。"""

    required: bool = False
    template: str | None = None


@dataclass(frozen=True)
class ActionExecutorSpec:
    """真实业务操作的执行位置与执行方式。"""

    adapter: str
    method: str
    operation_type: Literal["query", "command", "workflow"] = "command"


@dataclass(frozen=True)
class ActionSpec:
    """供 Agent 理解业务动作的结构化契约。"""

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
    input_model: type[BaseModel] | None = None

    def public_dict(self) -> dict[str, Any]:
        """返回面向模型的精简动作描述。"""

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
            "input_schema": self.input_model.model_json_schema() if self.input_model else None,
        }


@dataclass(frozen=True)
class ActionExecutionContext:
    """供策略和适配器使用的运行时事实。"""

    user_id: str | None = None
    user_roles: list[str] = field(default_factory=list)
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResult:
    """标准化的动作执行结果。"""

    status: Literal["success", "failed", "requires_confirmation"]
    action_id: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
