# Agent Usage

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
        context.register_tool(query_inventory)
        context.business_agent_registry.register(inventory_agent)
        return [inventory_router]
```

`register_context` 是插件唯一的注册入口。插件不应向框架核心增加业务分支，也不应自行
修改其他插件的注册表。

新业务的完整流程建议保持在插件内部：查询和数据组装放 `workflows.py`，业务写操作的
参数模型放 `models.py`，动作契约放 `actions.py`，真实上游调用放 `adapter.py`。如果前端
事件格式或 `actionResult` 语义不同，在插件中注册 projection/handler；不要把这些字段
条件判断加到通用 `SessionService` 或 `WebSocket` 中。

## 业务系统 token

如果某个 integration 需要访问自己的上游系统，比如 inspection：

- 配置放在该 integration 自己的目录，例如 `app/integrations/inspection/.env`
- 模板见 `app/integrations/inspection/.env.example`
- 语义查询的 datasource 也应按 integration 配置，例如 inspection 默认使用 `INSPECTION_TEXT_TO_SQL_DATASOURCE=inspection_mysql`
- `INSPECTION_AUTH_TOKEN`：静态上游 token
- 或 `INSPECTION_AUTH_LOGIN_URL` + 用户名/密码 + basic auth + tenant id：由系统登录获取

获取到的 token 只用于该业务系统上游请求，不是前端用户 token。
框架根 `.env` 只放通用运行时配置，不放单个 Agent 的业务系统地址或认证参数。

inspection integration 会在启动时尝试预取一次 AllCore token；如果配置齐全且不是静态 token 模式，会启动后台续期任务。业务工具调用上游接口时也会被动获取或刷新 token，例如 `inspection_query_plan_detail` 会带 `allcore-auth`、`Authorization`、`Tenant-Id` 请求旧系统计划详情接口。
