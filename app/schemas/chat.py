"""API schemas for chat, DST state, and human-in-the-loop events."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


class ClientEventType(StrEnum):
    """从前端接受的事件."""

    MESSAGE = "message"
    RESUME = "resume"
    PING = "ping"
    ACTION_RESULT = "actionResult"


class ServerEventType(StrEnum):
    """发送到前端的事件."""

    ACK = "ack"
    TOKEN = "token"
    MESSAGE = "message"
    THINKING_STEP = "thinking_step"
    DST_STATE = "dst_state"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    ERROR = "error"
    PONG = "pong"


class ChatRequest(BaseModel):
    """通过REST或WebSocket发送的用户消息流."""

    message: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    """后端创建新对话时返回的响应."""

    session_id: str


class SessionRecord(BaseModel):
    session_id: str
    created_at: str | None = None
    updated_at: str | None = None
    intent: str | None = None
    dialogue_stage: str | None = None
    summary: str | None = None


class ListSessionsResponse(BaseModel):
    sessions: list[SessionRecord]
    total: int


class SessionHistoryResponse(BaseModel):
    session_id: str
    exists: bool
    history: list[dict[str, Any]] = Field(default_factory=list)


class WebSocketClientEvent(BaseModel):
    """客户端到服务器WebSocket负载."""

    type: ClientEventType
    session_id: str | None = None
    request_id: str | None = None
    message_id: str | None = None
    content: str | None = None
    resume: Any | None = None
    action_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices("action_code", "actionCode"),
    )
    action_result: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("action_result", "actionResult"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketServerEvent(BaseModel):
    """服务器到客户端WebSocket负载."""

    type: ServerEventType
    session_id: str
    request_id: str | None = None
    message_id: str | None = None
    parent_message_id: str | None = None
    content: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class HumanResumeRequest(BaseModel):
    """恢复暂停的人在回路运行的有效载荷."""

    action: Literal["approve", "reject", "edit", "clarify"]
    content: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SessionStateResponse(BaseModel):
    """会话最新DST可序列化视图."""

    session_id: str
    exists: bool
    intent: str | None = None
    dialogue_stage: str | None = None
    summary: str | None = None
    pending_human_action: dict[str, Any] | None = None
    domain_state: dict[str, Any] = Field(default_factory=dict)
    last_active_agent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionResponse(BaseModel):
    """统一的 HTTP 交互响应，兼容普通消息和人机交互恢复."""

    event: dict[str, Any]
    state: SessionStateResponse
