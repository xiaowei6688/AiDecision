# Agent Usage

新增业务 Agent 和业务系统时，参见
[plugin-integration-guide.md](</Users/levin/Documents/PythonCode/AiDecision/docs/plugin-integration-guide.md>)。

## 启动

```bash
uv run uvicorn app.main:app --reload
```

## 用户验证

默认开启验证。请求 HTTP 或 WebSocket 时，需要带：

- `Authorization: Bearer ...`
- `X-User-Id`
- `X-Tenant-Id`
- `X-User-Roles`（可选，逗号分隔）

如果把 `AUTH_ENABLED=false`，系统会关闭用户验证，直接放行，并使用匿名身份：

- `anonymous-user`
- `anonymous-tenant`

## Token 从哪里来

这里的 `Authorization` token 是**调用本服务的人**带来的登录 token，不是业务系统 token。

当前代码里：

- `development` 模式下，如果没带 `Authorization`，会直接按开发身份放行。
- 其他环境下，如果 `AUTH_ENABLED=true`，会要求你提供 `Bearer` token。
- token 的具体签发、解析和校验由你的部署环境决定；仓库里还没有接入真正的 JWT/SSO 验证器。
- 如果 `AUTH_ENABLED=false`，会完全跳过用户验证。

## 使用 Agent

主入口是 `app.main:app`。启动后会自动发现 `app.integrations.<name>.bundle`，并按 `enabled_integrations` 加载。

插件加载顺序是：应用边界为每个 FastAPI 应用创建独立的 `PluginContext`，发现 `bundle`，
把动作/适配器/工具/事件投影和业务 Agent 注册到该上下文，然后主 Agent 从该上下文构建
工具列表。主 Agent 不导入某个具体业务包；业务逻辑应放在对应的
`app/integrations/<name>/` 中。同一进程内多个应用实例不会共享插件能力。

业务 Agent 请求只读工具时统一经过 `PluginContext.tool_broker`。Broker 校验插件授权，
注入当前用户和 session 上下文，并把调用证据返回主 Agent；写操作不经过 Broker，仍由
`ActionExecutor` 和确认流程执行。

常用接口：

- `GET /health`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/resume`
- `WS /ws/chat`
- `WS /ws/chat/{session_id}`

### 会话流

1. `POST /sessions` 创建会话
2. `POST /sessions/{session_id}/messages` 发送消息
3. Agent 普通追问会返回 `message`
4. Agent 需要最终确认、审批或前端执行动作时会返回 `human_action_required`
5. `POST /sessions/{session_id}/resume` 或 WebSocket `resume` 继续执行

WebSocket 的每一条客户端事件都必须在消息体携带 `session_id`，会话选择不依赖
WebSocket URL。消息示例：

```json
{
  "type": "message",
  "content": "可以",
  "session_id": "a71fefbd-38f4-468c-8641-c7714ddb50e0",
  "metadata": {}
}
```

不同 integration 可以注册自己的 WebSocket projection，定制 `human_action_required` 的 `data` 结构和兼容字段。inspection 的普通补字段追问不进入 `human_action_required`；只有计划或工单数据组装完成、需要旧前端确认执行时才进入确认事件。

### 接入新业务

新增业务时，创建：

- `app/integrations/<name>/actions.py`
- `app/integrations/<name>/adapter.py`
- `app/integrations/<name>/checks.py`
- `app/integrations/<name>/workflows.py`
- `app/integrations/<name>/routes.py`
- `app/integrations/<name>/bundle.py`

然后在 `bundle.py` 暴露一个 `bundle` 对象即可，框架会自动发现。新插件应实现：

```python
class InventoryBundle:
    name = "inventory"

    def register_context(self, context: PluginContext) -> list[APIRouter]:
        context.action_registry.register(INVENTORY_ACTION)
        context.action_executor.register_adapter("inventory", InventoryAdapter())
        context.tools.register(query_inventory, read_only=True)
        context.business_agent_registry.register(inventory_agent)
        return [inventory_router]
```

`register_context` 是插件唯一的注册入口。插件不应向框架核心增加业务分支，也不应自行
修改其他插件的注册表。

新业务的完整流程建议保持在插件内部：查询和数据组装放 `workflows.py`，业务写操作的
参数模型放 `models.py`，动作契约放 `actions.py`，真实上游调用放 `adapter.py`。如果前端
事件格式或 `actionResult` 语义不同，在插件中注册 projection/handler；不要把这些字段
条件判断加到通用 `SessionService` 或 `WebSocket` 中。

## 业务系统认证

某个 integration 如果需要访问带认证的上游系统，应在自己的插件目录中定义认证配置，
不要写入框架根 `.env`。inspection 的 AllCore 认证配置只放在
`app/integrations/inspection/.env`，与框架面向用户的 Token 验证相互独立。可配置静态
`INSPECTION_ALLCORE_AUTH_TOKEN`，也可配置登录地址、账号、密码、Basic Auth 和 Tenant ID
动态获取 Token。动态 Token 会在插件启动时预取、到期前刷新，并在业务接口返回 401/403
时强制刷新后重试一次。启动预取和周期刷新由框架通用 `RefreshLifecycle` 提供；插件只实现
自己的登录请求、Token 格式和认证头。配置完整的动态登录参数时，启动预取优先获取新 Token；
只希望使用静态 Token 时，不配置动态登录参数即可。

## Inspection actionResult 回执

旧巡检前端完成计划或工单创建后，通过 WebSocket 回传业务结果：

```json
{
  "type": "actionResult",
  "session_id": "5bfb9911-035b-41d1-8bea-bbee030a028b",
  "action_result": {
    "action_code": "createPlan",
    "content": null,
    "data": {
      "code": 200,
      "success": true,
      "data": "357520855904816740",
      "msg": "操作成功"
    }
  }
}
```

`createPlan` 的 `data.data` 是计划 ID，`createTempOrder` 的 `data.data` 是工单 ID。
inspection 插件会将该结构转换为框架通用的 resume 请求，并声明 `businessContinuation`。
工单 Agent 随即使用该计划 ID 查询真实计划详情、
取得真实 planGuid 并开始覆盖拆分；普通 `resume` 不会冒充业务系统创建成功。
工单成功回执会先按工单 ID 校验入库结果，再把当前 covered/uncovered 组标记完成并决定
是否生成下一组工单。
