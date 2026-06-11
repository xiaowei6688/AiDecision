## AI Decision

企业级AI智能决策后端。

核心能力：

- 提供 HTTP 与 WebSocket 接口。
- 主 Agent 通过 SubAgents 拆分不同角色职责。
- 使用 `session_id` 作为唯一会话 ，通过 PostgreSQL checkpoint 持久化会话状态。
- 支持人机交互（HITL）：Agent 可以暂停流程，等待前端或人工确认后恢复。
- 扩展 `DeepAgentState`，记录意图、槽位、会话阶段、摘要、待人工动作和最近活跃 Agent。
- 自动压缩长上下文：保留最近 N 条消息，旧消息合并进 `summary`，避免单个 session 无限增长。


```bash
uv run uvicorn app.main:app --reload
```

## WebSocket Protocol

对于新对话，无需会话id即可连接。后端会创建一个会话id
并在第一个“ack”事件中返回：

```text
ws://localhost:8000/ws/chat
```

Example `ack`:

```json
{
  "type": "ack",
  "session_id": "77c0e3f0-cf5c-46dd-8d7b-26d5a0a8f9f2",
  "content": "connected",
  "data": {
    "created": true
  }
}
```

前端应该持久化`session_id`，并在其余部分重用
conversation:

```text
ws://localhost:8000/ws/chat/{session_id}
```

Send a user message:

```json
{
  "type": "message",
  "content": "帮我分析这个产品决策",
  "metadata": {
    "user_id": "demo-user"
  }
}
```

服务器事件包括:
- `ack`: 已接受连接.
- `message`: AI回应.
- `dst_state`: 结构化对话状态快照.
- `human_action_required`: 需要人工输入.
- `error`: 验证或运行时错误.
- `pong`: ping响应.

Resume a human action over WebSocket:

```json
{
  "type": "resume",
  "resume": {
    "action": "clarify",
    "content": "会议主题是 Q3 产品规划，参会人张三、李四、王五，下周三下午 3 点，时长 1 小时，需要线上会议链接。",
    "data": {}
  }
}
```

`action` 支持 `approve`、`reject`、`edit`、`clarify`，与 HTTP resume 保持一致。

## HTTP 端点

- `GET /health`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/resume`

Create session example:

```json
{
  "session_id": "77c0e3f0-cf5c-46dd-8d7b-26d5a0a8f9f2"
}
```

Resume example:

```json
{
  "action": "approve",
  "content": "同意继续",
  "data": {}
}
```

## Context Compression

默认配置：

```text
CONTEXT_RECENT_MESSAGES=20
CONTEXT_SUMMARY_MAX_CHARS=6000
```

每次用户继续对话前，后端会读取当前 session 的 checkpoint。如果消息数量超过
`CONTEXT_RECENT_MESSAGES`，系统会：

- 把旧消息追加到 `summary`。
- 从当前消息状态中删除旧消息。
- 只保留最近 N 条完整消息给后续 Agent 使用。

第一版摘要采用确定性压缩，不额外调用模型，因此不会增加一次额外 LLM 成本。后续可以把
`ContextCompressor` 替换成模型摘要版本。

## Development Checks

```bash
uv run mypy app
uv run pytest
```
