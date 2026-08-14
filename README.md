## All Core Agent

企业级AI智能决策后端。

核心能力：

- 提供 HTTP 与 WebSocket 接口。
- 主 Agent 通过常驻通用 SubAgent 和已注册的本地业务 Agent 拆分复杂判断。
- 通过 ActionSpec + Executor + Adapter 接入不同业务系统，Agent 只调用统一业务动作。
- 通过 `semantic_query` 预留 text-to-sql 查询工具，用于跨 datasource 查询、参数补全和规则校验。
- 使用 `session_id` 作为唯一会话 ，通过 PostgreSQL checkpoint 持久化会话状态。
- 支持人机交互（HITL）：Agent 可以暂停流程，等待前端或人工确认后恢复。
- 扩展 `DeepAgentState`，记录意图、槽位、会话阶段、摘要、待人工动作和最近活跃 Agent。
- 自动压缩长上下文：保留最近 N 条消息，旧消息合并进 `summary`，避免单个 session 无限增长。


```bash
uv run uvicorn app.main:app --reload
```

详细使用说明见 [docs/agent-usage.md](</Users/levin/Documents/PythonCode/AiDecision/docs/agent-usage.md>).

## Business Integrations

通用框架放在 `app/actions` 和 `app/tools`，具体业务系统放在
`app/integrations/<system>`。每接入一个新系统，新增一个独立目录：

```text
app/integrations/contract/
  __init__.py
  actions.py   # 定义 contract.xxx 业务动作
  adapter.py   # 真正调用合同系统 HTTP/RPC/MCP
  checks.py    # 确定性的权限、参数、业务规则校验
```

启动时由 `app/integrations/bootstrap.py` 统一发现和注册。新插件通过
`bundle.register_context(PluginContext)` 完成注册；主 Agent 只通过
`list_business_actions`、`semantic_query`、`call_business_action` 工作，不直接感知
任何业务系统的真实接口。

每个 `bundle` 就是一个插件入口。应用创建时会为该实例建立独立的 `PluginContext`，插件
在其中注册动作、适配器、工具、业务 Agent、路由和事件投影；应用配置中的
`enabled_integrations` 会同时约束这些能力。核心运行时只消费注册表中的通用协议，不在
`app/agents`、`app/services` 或 `app/api` 中写业务判断。多个应用实例在同一进程中也不会
共享插件能力。

## 业务 Agent 编排

系统始终由一个主编排 Agent 接待用户。各业务系统的业务 Agent 不是用户选择的根 Agent，
而是主 Agent 根据任务按需调度的领域能力。每个业务 Agent 声明自己的数据源、可建议的动作前缀、
领域约束与跨系统依赖；它只输出分析和建议，真实查询及动作仍由主 Agent 经统一工具执行。

```text
用户请求
  -> 主编排 Agent 识别已注册的业务域
  -> consult_business_agents(["业务 Agent A", "业务 Agent B"])
  -> 汇总依赖、冲突与执行顺序
  -> semantic_query / call_business_action
```

主 Agent 先使用 `list_business_agents` 获取能力目录，再用 `plan_business_collaboration` 定义
业务 Agent 的选择理由和依赖图；`run_business_collaboration` 按该图运行，无依赖 Agent 并发，
有依赖 Agent 接收前置的结构化建议。这样业务协作是框架的显式、可校验行为，而非仅依赖 Prompt。

业务 Agent 的调度通过统一的本地 Runtime 协议进行。每个 integration 在本项目内封装自己的
业务 Agent，当前默认实现为 `LocalLLMBusinessAgent`；主 Agent 只面对统一的 `BusinessAdvice`，
不需要知道各业务系统的领域推理细节。

业务 Agent 与 Action/Adapter 同属于 `app/integrations/<system>/`：其中 `agent.py` 声明业务
推理能力，`actions.py`、`adapter.py`、`checks.py`、`workflows.py`、`routes.py`
负责真实受控执行。框架通过 `app/integrations/<system>/bundle.py` 暴露的 `bundle` 自动发现集成。
接入真实系统时新增完整 integration 包，并在 bundle 中注册本地 BusinessAgentManifest。
不要把业务 Agent 做成新的用户会话根 Agent。

### 新插件的职责边界

```text
app/integrations/inventory/
  bundle.py         # 插件唯一注册入口
  agent.py          # 领域约束和结构化建议
  workflows.py      # 查询、组装和确定性的领域流程
  actions.py        # 可执行动作契约
  adapter.py        # 调用真实系统
  models.py         # 该系统的输入/输出模型
  ui.py             # 该系统的前端事件投影（如需要）
```

`agent.py` 可以告诉主 Agent“这个领域能处理什么、需要什么数据、建议什么动作”，但不应
直接操作其他插件或改变 WebSocket 协议。真实业务处理放在该插件的 workflow、action 和
adapter 中；通用框架只负责发现插件、调度建议、校验动作、处理确认/恢复和发送统一事件。

业务语义模型不放在 Agent 协议中：共享引用模型放在 `app/domain/`，各系统命令模型放在
`app/integrations/<system>/models.py`。ActionSpec 引用对应命令模型，Executor 会在调用 Adapter
前完成结构校验并把 JSON Schema 暴露给主 Agent。

跨系统任务先调用 `create_execution_plan` 创建只读计划预览。计划会校验步骤唯一性、动作参数、
已注册数据源及依赖无环，但不会查询或执行。包含写动作的计划必须先由主 Agent 通过 HITL 获得批准；
按计划执行将在后续执行器中实现。

计划动作步骤会获得稳定的 `idempotency_key`。执行器只缓存成功的动作结果，并在恢复时跳过已成功
步骤；真实 Adapter 必须将该键透传给其 HTTP/RPC/MCP 上游的幂等请求机制，才能覆盖网络超时后
“上游已提交但本地未收到结果”的场景。

## Role SubAgents

角色能力按用途拆分在 `app/agents/roles`：

```text
app/agents/roles/
  common/      # 常驻 SubAgent，如 requirements_analyst
```

默认只注册 `requirements_analyst` 这类通用 SubAgent，避免每次对话都加载过多领域
Agent 描述。真实业务系统以本地 Business Agent 方式在 `app/integrations/<system>/agent.py`
注册，只有在复杂、模糊、高风险或跨系统判断时才被主 Agent 按需调度。

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
