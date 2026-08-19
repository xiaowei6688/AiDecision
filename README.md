# AI Decision

AI Decision 是一个面向企业业务系统的**插件化多 Agent 决策与执行框架**。

它的目标不是把某一个业务流程做成一个孤立的聊天机器人，而是提供一套稳定的运行时：由一个主编排 Agent 接待用户，把领域判断交给插件中的业务 Agent，把查询、校验、确认和真实业务写操作交给明确的框架边界处理。

接入新的业务系统时，新增一个 integration 插件即可。业务规则、数据源、上游认证、API 参数组装和前端专属回调都留在插件内部；通用框架不需要增加该业务的条件分支。

## 系统定位

这是一个“主编排 Agent + 业务 Agent 插件 + 受控工具执行”的后端系统：

```text
用户
  │ HTTP / WebSocket
  ▼
会话服务与事件投影
  │
  ▼
主编排 Agent
  ├── 选择业务 Agent
  ├── 组织跨业务协作
  ├── 调用语义查询
  └── 调用统一业务动作
          │
          ├── 只读工具 → ToolBroker → 业务插件查询
          └── 写操作   → ActionExecutor → Check → Adapter → 上游系统
```

主编排 Agent 只需要知道插件声明了哪些能力。它不直接导入巡检、库存、合同等具体业务模块，也不需要知道上游 HTTP/RPC/MCP 接口的细节。

业务 Agent 是领域能力，不是新的用户会话根 Agent。它可以分析领域事实、指出缺失信息、建议工具和动作，但真实写操作必须经过统一的动作执行边界。

## 核心能力

- **插件化业务接入**：每个业务系统拥有独立的 `app/integrations/<name>/` 目录。
- **主 Agent 编排**：统一识别业务领域，协调多个业务 Agent，并维护一份会话上下文。
- **结构化业务动作**：通过 `ActionSpec` 描述输入、确认策略、前置检查和执行器。
- **受控工具执行**：业务 Agent 的只读工具经过 `ToolBroker` 授权、执行和审计。
- **Adapter 隔离上游系统**：真实业务接口、认证和重试逻辑只存在于对应插件。
- **人机协作**：支持普通追问、最终确认、`resume` 恢复，以及插件转换的业务回执。
- **实时进度事件**：通过统一的 `thinking_step` 事件传递工具和任务进度。
- **会话持久化**：使用 `session_id` 标识会话，可接入 PostgreSQL checkpoint 和持久化业务状态。
- **上下文压缩**：长会话会保留最近消息，并把历史内容合并为摘要。
- **会话边界**：当前阶段仅使用 `session_id` 识别和隔离对话，不引入用户登录与用户归属。
- **多应用实例隔离**：每个 FastAPI 应用实例拥有独立的 `PluginContext`，插件注册不会互相污染。

## 目录结构

```text
app/
├── actions/                  # 通用业务动作契约、校验、执行和注册表
├── adapters/                 # 通用 Adapter 协议与公共外部服务客户端
├── agents/                   # 主编排 Agent、业务 Agent 协议和通用角色 Agent
├── api/                      # 通用 HTTP 与 WebSocket 接口
├── core/                     # 配置、认证、状态、进度和运行时上下文
├── domain/                   # 跨业务共享的领域概念
├── integrations/             # 插件边界和具体业务插件
│   ├── contracts.py          # 通用插件契约
│   ├── bootstrap.py          # 插件发现与启用
│   └── <business>/           # 单个业务系统的全部实现
├── schemas/                  # 对外 API 与事件数据结构
├── services/                 # 会话、上下文压缩、事件投影等通用服务
└── tools/                    # 通用工具、工具代理和日期能力
```

业务代码只能放在对应的 integration 插件中。通用目录不得导入具体业务插件；项目中有架构测试持续检查这一边界。

## 插件模型

一个业务插件通常包含：

```text
app/integrations/inventory/
├── bundle.py                 # 唯一注册入口
├── agent.py                  # 业务 Agent 能力声明
├── models.py                 # 业务输入和输出模型
├── workflows.py              # 查询、数据组装和确定性业务流程
├── actions.py                # ActionSpec 动作契约
├── checks.py                 # 权限、参数和业务规则校验
├── adapter.py                # 真实 HTTP/RPC/MCP 调用
├── config.py                 # 插件私有配置
├── ui.py                     # 可选：前端事件投影
└── routes.py                 # 可选：业务 HTTP 回调
```

插件通过 `bundle` 注册自己的 Agent、工具、动作、Adapter、路由和事件处理器：

```python
class InventoryBundle:
    name = "inventory"

    def register_context(self, context: PluginContext) -> list[APIRouter]:
        context.action_registry.register(INVENTORY_ACTION)
        context.action_executor.register_adapter("inventory", InventoryAdapter())
        context.tools.register(query_inventory, read_only=True)
        context.business_agent_registry.register(inventory_agent)
        return []

bundle = InventoryBundle()
```

插件启用后，主 Agent 通过通用注册表发现它。通用框架不读取插件内部的业务字段，也不为某个业务增加 `if inspection` 一类的判断。

完整接入步骤见 [docs/plugin-integration-guide.md](docs/plugin-integration-guide.md)。

## 运行方式

环境要求：Python 3.11+、`uv`，以及生产环境需要的 PostgreSQL 和模型服务。

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

也可以使用项目根目录的启动提示脚本：

```bash
uv run main.py
```

默认服务地址为 `http://127.0.0.1:8000`。当前 `.env.example` 默认启用 `inspection` 插件；如果只启动通用框架，可设置：

```env
ENABLED_INTEGRATIONS='[]'
```

本地自动加载所有已发现插件：

```env
ENABLED_INTEGRATIONS='["*"]'
```

生产环境建议显式列出插件名称，例如 `['inspection', 'inventory']`。

## 会话边界

当前框架不引入用户登录、用户归属或角色鉴权。HTTP 和 WebSocket 均以 `session_id`
作为会话边界：创建会话后，后续请求和实时事件携带同一个 `session_id` 即可。

插件访问自身上游业务系统所需的 Token、账号、租户和认证头仍由插件私有配置管理，
不得写入通用框架配置。

## HTTP 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/sessions` | 查询已注册会话 |
| `POST` | `/sessions` | 创建会话 |
| `GET` | `/sessions/{session_id}/state` | 查询会话状态 |
| `GET` | `/sessions/{session_id}/history` | 查询会话历史 |
| `GET` | `/sessions/search?q=关键词` | 在已注册会话中检索历史消息 |
| `POST` | `/sessions/{session_id}/messages` | 发送用户消息 |
| `POST` | `/sessions/{session_id}/resume` | 恢复暂停的 Agent |
| `POST` | `/chat` | 旧版单入口消息、`resume`、`actionResult` 兼容接口 |
| `GET` | `/history/{session_id}` | 旧版会话历史路径别名 |

创建会话：

```bash
curl -X POST http://127.0.0.1:8000/sessions
```

发送消息：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"帮我查询当前任务状态","metadata":{}}'
```

恢复 Agent：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/resume \
  -H 'Content-Type: application/json' \
  -d '{"action":"approve","content":"确认执行此操作","data":{}}'
```

查询单个会话历史：

```bash
curl 'http://127.0.0.1:8000/sessions/<session_id>/history?q=白路线&role=assistant&offset=0&limit=50'
```

检索历史会话：

```bash
curl 'http://127.0.0.1:8000/sessions/search?q=白路线&offset=0&limit=20'
```

历史消息由通用框架从 Agent checkpoint 读取，包含消息 ID、角色、类型、内容和元数据；生产环境使用 PostgreSQL checkpoint 时，服务重启后仍可读取。`/sessions/search` 检索已注册会话，业务插件无需实现任何历史逻辑。

为了让旧版前端直接读取，历史接口还会同时返回 `code`、`msg` 和 `data.history[0].messages` 的旧版分组结构；顶层 `history` 保持新版扁平消息列表。两种结构来自同一份通用历史数据，不需要插件适配。

## 旧前端接口兼容

旧前端可继续使用 `WS /ws` 或 `WS /ws/{session_id}`；它们与 `/ws/chat` 使用同一套事件处理和认证逻辑。客户端每条消息仍须携带 `session_id`。HTTP 单入口可使用 `POST /chat`，请求体保持旧版字段：`type`、`content`、`session_id`、`resume` 或 `action_result`。业务 `actionResult` 由启用的插件注册转换，不由框架按业务名称判断。

巡检插件额外保留旧通知入口：`POST /notify/start_flying` 与 `POST /notify/detect_result`；新调用方推荐使用 `/integrations/inspection/notify`。这些通知别名仅在启用 `inspection` 插件时注册。

## WebSocket 事件

连接新会话：

```text
ws://127.0.0.1:8000/ws/chat
```

连接已有会话：

```text
ws://127.0.0.1:8000/ws/chat/<session_id>
```

消息体中的 `session_id` 是会话的唯一依据：

```json
{
  "type": "message",
  "content": "查询当前任务状态",
  "session_id": "a71fefbd-38f4-468c-8641-c7714ddb50e0",
  "metadata": {}
}
```

常见服务端事件：

- `ack`：连接已建立。
- `message`：普通文本或插件直接投影的最终结果。
- `thinking_step`：统一的中间进度事件，状态通常为 `running`、`completed` 或 `failed`。
- `human_action_required`：需要前端或用户确认、补充或执行动作。
- `error`：请求或运行时错误。
- `pong`：心跳响应。

`dst_state` 是内部对话状态事件，不会发送到前端。

恢复事件示例：

```json
{
  "type": "resume",
  "session_id": "a71fefbd-38f4-468c-8641-c7714ddb50e0",
  "resume": {
    "action": "approve",
    "content": "确认执行此操作",
    "data": {}
  }
}
```

不同插件可以通过事件投影和 WebSocket action handler 扩展自己的前端数据格式，但不应修改通用 `SessionService`、`WebSocket` 或主 Agent 的业务分支。

## 测试与检查

```bash
uv run pytest -q
uv run python -m compileall -q app tests
git diff --check
```

插件开发详细说明见：

- [docs/agent-usage.md](docs/agent-usage.md)：启动、认证、会话和 Agent 使用方式。
- [docs/plugin-integration-guide.md](docs/plugin-integration-guide.md)：新业务插件接入规范。
