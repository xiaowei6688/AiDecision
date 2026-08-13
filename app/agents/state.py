from enum import StrEnum
from typing import Annotated, Any, NotRequired, TypedDict

from deepagents import DeepAgentState


class DialogueStage(StrEnum):
    """当前对话的高级进度标记."""

    STARTED = "started"
    COLLECTING_REQUIREMENTS = "collecting_requirements"
    ANALYZING_OPTIONS = "analyzing_options"
    WAITING_FOR_HUMAN = "waiting_for_human"
    PLANNING = "planning"
    COMPLETED = "completed"


class HumanActionStatus(StrEnum):
    """Agent是否在等待用户批准或澄清."""

    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DialogueSlot(TypedDict, total=False):
    """对话中收集到的结构化事实."""

    name: str
    value: Any
    confidence: float
    source: str


class PendingHumanAction(TypedDict, total=False):
    """可恢复的人在回路动作."""

    status: HumanActionStatus
    question: str
    allowed_actions: list[str]
    payload: dict[str, Any]


def merge_dict_state(
    previous: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply a shallow patch so independent tools do not erase known facts."""

    return {**(previous or {}), **(update or {})}


class DecisionDSTState(DeepAgentState):
    """DeepAgents状态, 丰富DST字段。
        消息仍由DeepAgentState/LangGraph管理。额外的字段是
        故意设计得较小且可序列化，以便检查点保持便携性.
    """

    intent: NotRequired[str | None]
    slots: NotRequired[Annotated[dict[str, DialogueSlot], merge_dict_state]]
    dialogue_stage: NotRequired[DialogueStage]
    summary: NotRequired[str]
    pending_human_action: NotRequired[PendingHumanAction | None]
    domain_state: NotRequired[Annotated[dict[str, Any], merge_dict_state]]
    last_active_agent: NotRequired[str | None]
    metadata: NotRequired[Annotated[dict[str, Any], merge_dict_state]]


def default_dst_metadata() -> dict[str, Any]:
    """返回新对话的基础元数据."""

    return {
        "dst_version": "1.0",
        "description": "dialogue state tracker",
    }
