"""对话、DST 状态和人在回路事件的 API 数据结构。"""

from enum import StrEnum
from typing import Any

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


class LegacyChatRequest(BaseModel):
    """旧版前端单入口交互负载。"""

    type: ClientEventType = ClientEventType.MESSAGE
    session_id: str = Field(min_length=1)
    content: str | None = None
    message: str | None = None
    request_id: str | None = None
    message_id: str | None = None
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
    """新版扁平历史，同时携带旧版前端所需的兼容投影。"""

    session_id: str
    exists: bool
    history: list[dict[str, Any]] = Field(default_factory=list)
    total: int | None = None
    offset: int = 0
    limit: int | None = None
    code: int = 200
    msg: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)


class SessionHistorySearchHit(BaseModel):
    session_id: str
    intent: str | None = None
    summary: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class SessionHistorySearchResponse(BaseModel):
    query: str
    results: list[SessionHistorySearchHit] = Field(default_factory=list)
    total: int
    offset: int = 0
    limit: int = 100


class WebSocketClientEvent(BaseModel):
    """客户端到服务器WebSocket负载."""

    type: ClientEventType
    session_id: str = Field(min_length=1)
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

    action: str = Field(min_length=1)
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
