# 新业务 Agent 插件接入指南

本文说明如何为框架接入一个新的业务项目。新增业务应该实现为独立插件，业务代码放在
`app/integrations/<project_name>/`，通用框架不需要增加该业务的条件分支。

## 1. 架构边界

一个业务插件负责自己的领域能力和上游系统调用：

```text
app/integrations/<project_name>/
  __init__.py
  bundle.py              # 唯一插件注册入口
  agent.py               # 业务 Agent 能力声明
  workflows.py           # 查询和业务数据组装
  actions.py             # 可执行动作契约
  models.py              # 业务输入模型
  adapter.py             # 真实业务系统调用
  checks.py              # 确定性业务校验
  ui.py                  # 可选，前端事件投影
  websocket_actions.py   # 可选，actionResult 转换
  routes.py              # 可选，业务 HTTP 回调
  auth.py                # 可选，上游认证
  config.py              # 可选，插件私有配置
  .env.example           # 可选，插件配置模板
```

通用框架负责：

- 会话和上下文
- 主 Agent 编排
- Business Agent 协作
- ActionSpec 校验和执行
- 用户确认与 resume
- HTTP/WebSocket 协议
- 插件生命周期

业务插件负责：

- 领域规则和业务术语
- 业务数据查询
- 业务参数组装
- 上游 API、RPC、MCP 调用
- 业务系统认证
- 该业务专属的前端字段和回调格式

新增插件不应修改 `app/services/session_service.py`、`app/api/websocket.py`、
`app/agents/state.py` 或主 Agent 的通用编排逻辑。

## 2. 创建插件目录

假设要接入库存项目：

```text
app/integrations/inventory/
  __init__.py
  bundle.py
  agent.py
```

插件名使用稳定的小写标识，例如 `inventory`。它会同时用于：

- `IntegrationBundle.name`
- `BusinessAgentManifest.business_id`
- `ENABLED_INTEGRATIONS`
- 插件动作 ID 的前缀

## 3. 定义业务 Agent

在 `agent.py` 中声明业务 Agent。它描述能力边界，不直接执行真实动作。

```python
from app.agents.business_agents import BusinessAgentManifest


inventory_agent = BusinessAgentManifest(
    business_id="inventory",
    title="库存业务 Agent",
    description="负责库存查询、库存约束分析和采购建议",
    system_prompt=(
        "你是库存领域 Agent，只分析库存领域事实、约束和缺失信息。"
        "不要执行真实动作。"
    ),
    datasources=("inventory_mysql",),
    action_prefixes=("inventory.",),
    readonly_tool_names=("inventory_query_stock",),
)
```

字段说明：

| 字段 | 作用 |
| --- | --- |
| `business_id` | 插件和业务 Agent 的稳定标识 |
| `title` | 展示给主 Agent 的能力名称 |
| `description` | 业务 Agent 能做什么 |
| `system_prompt` | 领域约束和分析规则 |
| `datasources` | 允许建议使用的数据源 |
| `action_prefixes` | 允许建议使用的动作前缀 |
| `readonly_tool_names` | 允许业务 Agent 自主调用的只读插件工具 |
| `cross_system_notes` | 可选，跨系统协作限制 |

业务 Agent 可以调用 `readonly_tool_names` 中授权的只读工具核对领域事实，最终输出结构化
建议。实际调用会经过框架的 `ToolBroker`，不会由业务 Agent 绕过框架直接执行。写操作、
跨系统动作和用户确认仍由主 Agent 统一执行。

## 4. 实现查询工具

只读查询通常放在 `workflows.py`，并通过插件工具注册表暴露给主 Agent。

```python
from typing import Any

from langchain_core.tools import tool

from app.adapters.text_to_sql import TextToSqlClient
from app.core.config import get_settings


@tool
def inventory_query_stock(product_name: str) -> dict[str, Any]:
    """查询指定商品的库存事实。"""

    settings = get_settings()
    if not product_name.strip():
        return {"status": "failed", "error_code": "MISSING_PRODUCT_NAME"}

    result = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    ).query(
        datasource="inventory_mysql",
        question=f"查询商品{product_name}的库存、仓库和可用数量",
    )
    return result
```

语义查询服务只接受 `datasource` 和 `question` 时，插件工具也只传这两个参数。插件自己的
数据源名称不能放到通用 Agent 配置中：

```python
datasource="inventory_mysql"
```

如果数据源需要配置化，应放在：

```text
app/integrations/inventory/config.py
app/integrations/inventory/.env
```

## 5. 定义写操作

有真实写操作时，按四层拆分：

```text
models.py    参数结构和字段校验
actions.py   ActionSpec 动作契约
checks.py    确定性业务规则
adapter.py   真实系统调用
```

### 5.1 参数模型

```python
from pydantic import BaseModel, Field


class CreatePurchaseOrderInput(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    warehouse_id: str = Field(min_length=1)
```

### 5.2 ActionSpec

```python
from app.actions.schemas import (
    ActionExecutorSpec,
    ActionInputSpec,
    ActionSpec,
    ActionConfirmation,
)

from app.integrations.inventory.models import CreatePurchaseOrderInput


CREATE_PURCHASE_ORDER = ActionSpec(
    action_id="inventory.create_purchase_order",
    title="创建采购单",
    description="根据商品、数量和仓库创建采购单",
    system="inventory",
    inputs=[
        ActionInputSpec("product_id", "商品 ID"),
        ActionInputSpec("quantity", "采购数量"),
        ActionInputSpec("warehouse_id", "仓库 ID"),
    ],
    input_model=CreatePurchaseOrderInput,
    executor=ActionExecutorSpec(
        adapter="inventory",
        method="create_purchase_order",
    ),
    confirmation=ActionConfirmation(
        required=True,
        template="确认创建商品 {{product_id}} 的采购单吗？",
    ),
    pre_checks=["inventory.validate_purchase_order"],
    success_template="采购单 {{order_id}} 创建成功。",
)
```

写操作应默认要求确认。主 Agent 在字段完整后调用统一动作工具，框架返回
`human_action_required`，用户通过 `resume` 或业务前端 `actionResult` 继续。

### 5.3 Adapter

```python
from typing import Any

from app.adapters.base import BusinessAdapter
from app.actions.schemas import ActionExecutionContext


class InventoryAdapter(BusinessAdapter):
    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        if method != "create_purchase_order":
            raise ValueError(f"Unsupported inventory operation: {method}")

        # 在这里调用库存系统 HTTP/RPC/MCP 接口。
        # context.metadata 可读取当前用户、租户和幂等键。
        return {"order_id": "created-by-inventory-system"}
```

Adapter 负责真实调用，不应由 Agent 直接发 HTTP 请求。上游请求应传递：

- 用户或租户上下文
- `idempotency_key`
- 插件自己的认证头

## 6. 注册业务校验

```python
from app.actions.schemas import ActionExecutionContext, ActionSpec


def validate_purchase_order(
    action: ActionSpec,
    params: dict[str, object],
    context: ActionExecutionContext,
) -> str | None:
    if context.user_id is None:
        return "缺少当前用户身份"
    return None
```

校验必须是确定性的。需要模型判断的内容应放入业务 Agent 分析，不要在 policy check 中
调用模型。

## 7. 实现唯一插件入口

```python
from collections.abc import Sequence

from fastapi import APIRouter

from app.integrations.context import PluginContext
from app.integrations.inventory.actions import CREATE_PURCHASE_ORDER
from app.integrations.inventory.adapter import InventoryAdapter
from app.integrations.inventory.agent import inventory_agent
from app.integrations.inventory.checks import validate_purchase_order
from app.integrations.inventory.workflows import inventory_query_stock


class InventoryBundle:
    name = "inventory"

    def register_context(self, context: PluginContext) -> Sequence[APIRouter]:
        context.business_agent_registry.register(inventory_agent)
        context.tools.register(inventory_query_stock, read_only=True)
        context.tools.register_step(
            "inventory_query_stock",
            "核对库存事实",
            "正在核对商品库存、仓库和可用数量",
        )

        context.action_registry.register(CREATE_PURCHASE_ORDER)
        context.action_executor.register_adapter(
            "inventory",
            InventoryAdapter(),
        )
        context.policy_engine.register_pre_check(
            "inventory.validate_purchase_order",
            validate_purchase_order,
        )

        return []

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


bundle = InventoryBundle()
```

框架自动发现：

```text
app.integrations.inventory.bundle.bundle
```

不需要在主 Agent、`SessionService` 或 WebSocket 中添加 `inventory` 分支。

只有同时满足以下两个条件，工具才会下发给业务 Agent：

```text
工具注册时使用 read_only=True
BusinessAgentManifest.readonly_tool_names 包含该工具名
```

未注册、未授权或非只读工具会在业务 Agent 调度阶段被拒绝。插件写操作不得注册为
`read_only=True`，应通过 `ActionSpec + Adapter` 由主 Agent 执行。

`ToolBroker` 会为每次只读调用统一记录：

```text
request_id
session_id
user_id
business_id
tool_name
arguments
status
duration_ms
evidence
```

审计记录会随 Business Agent 的结构化结果返回给主 Agent，并转换成通用
`task_progress/thinking_step`。插件不需要自行实现工具审计或前端步骤事件。

### 实时步骤生命周期

框架保证每个可展示步骤都按稳定的标准 UUID `step_id` 输出生命周期：

```text
running -> completed
running -> failed
```

即使 Agent 快照第一次出现某步骤时已经是 `completed`，框架也会先补发同一
`step_id` 的 `running`。插件或模型提供的 `query_devices`、`step-1`、工具 call id
等仅作为内部关联键，输出前会统一映射为 UUID；嵌套的 `steps/currentStep/completedSteps`
等关联字段使用同一映射。在最终 `message`、`human_action_required` 或流结束前，
仍处于 `running` 的步骤会自动收口；前端应按 `step_id` 更新同一条步骤记录。

插件只需为工具注册用户友好的标题和摘要：

```python
context.tools.register_step(
    "inventory_query_stock",
    "核对库存事实",
    "正在核对商品库存和可用数量",
)
```

多步骤任务也可以调用通用 `update_task_progress`，每项提供稳定的
`id/title/status/summary`。这些内容是可展示的执行进度，不应包含隐藏推理、内部
提示词、原始工具参数或思维链。

## 8. 自定义前端事件

如果业务系统的前端确认格式不同，在插件内部注册投影：

```python
def inventory_human_interrupt_projection(
    interrupts: list[object],
) -> dict[str, object]:
    return {
        "data": {
            "businessId": "inventory",
            "interrupts": interrupts,
        }
    }


context.projections.register_human_interrupt(
    inventory_human_interrupt_projection
)
```

如果前端会回传 `actionResult`，注册业务自己的转换 handler：

```python
context.action_results.register(
    inventory_action_result_to_resume
)
```

普通 `resume` 是框架通用能力，插件只处理自己的业务字段和回调语义。

## 9. 插件认证和配置

业务系统认证属于插件，不属于根 `.env`。

推荐结构：

```text
app/integrations/inventory/config.py
app/integrations/inventory/auth.py
app/integrations/inventory/.env.example
```

示例：

```env
INVENTORY_API_BASE_URL=http://inventory.internal/api
INVENTORY_AUTH_LOGIN_URL=http://inventory.internal/oauth/token
INVENTORY_AUTH_USERNAME=
INVENTORY_AUTH_PASSWORD=
INVENTORY_DATASOURCE=inventory_mysql
```

根 `.env` 只配置框架级内容，例如：

```env
AUTH_ENABLED=true
TEXT_TO_SQL_BASE_URL=http://127.0.0.1:8088/ask
ENABLED_INTEGRATIONS=["inventory"]
```

## 10. 启用插件

在根 `.env` 中配置：

```env
ENABLED_INTEGRATIONS=["inspection", "inventory"]
```

空列表表示加载所有已发现插件：

```env
ENABLED_INTEGRATIONS=[]
```

插件未启用时，它的 Agent、工具、动作、路由和事件 handler 都不会注册到当前应用。

## 11. 测试清单

至少增加：

```text
tests/test_<project_name>_integration.py
```

建议覆盖：

- bundle 能被自动发现
- 插件启用后 Agent 能力可见
- 插件禁用后 Agent、工具和动作不可见
- 工具使用正确 datasource 和 question
- ActionSpec 参数校验正确
- policy check 能拒绝非法请求
- Adapter 使用正确的上游方法和认证头
- 写操作在确认前不会调用 Adapter
- `resume` 或 `actionResult` 能恢复正确流程
- 自定义事件投影不影响其他插件
- 同名工具会在注册阶段报错

运行测试：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest -q
```

## 12. 接入完成标准

一个新业务插件完成后，应满足：

```text
业务逻辑全部位于 app/integrations/<project_name>/
插件只有一个 register_context() 注册入口
主 Agent 不包含项目名称判断
SessionService 不包含项目名称判断
WebSocket 不包含项目名称判断
业务配置不进入通用 .env
写操作由 ActionSpec + Adapter 执行
前端差异通过 ProjectionRegistry 处理
插件之间没有模块级全局注册状态
```
