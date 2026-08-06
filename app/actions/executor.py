from typing import Any

from app.actions.policy import PolicyEngine, default_policy_engine
from app.actions.registry import ActionRegistry, default_action_registry
from app.actions.schemas import ActionExecutionContext, ActionResult
from app.adapters.base import BusinessAdapter


class BusinessActionExecutor:
    """Validates, authorizes and invokes registered business actions."""

    def __init__(
        self,
        registry: ActionRegistry,
        policy_engine: PolicyEngine,
        adapters: dict[str, BusinessAdapter] | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._adapters = adapters or {}

    def register_adapter(self, name: str, adapter: BusinessAdapter) -> None:
        self._adapters[name] = adapter

    async def execute(
        self,
        action_id: str,
        params: dict[str, Any],
        context: ActionExecutionContext | None = None,
        confirmed: bool = False,
    ) -> ActionResult:
        context = context or ActionExecutionContext()
        try:
            action = self._registry.get(action_id)
        except KeyError as exc:
            return ActionResult(
                status="failed",
                action_id=action_id,
                message=str(exc),
                error_code="ACTION_NOT_FOUND",
            )

        missing = self._missing_required_inputs(action.inputs, params)
        if missing:
            return ActionResult(
                status="failed",
                action_id=action_id,
                message=f"缺少必要参数：{', '.join(missing)}",
                data={"missing_inputs": missing},
                error_code="MISSING_INPUTS",
            )

        decision = self._policy_engine.evaluate(action, params, context)
        if not decision.allowed:
            return ActionResult(
                status="failed",
                action_id=action_id,
                message=decision.message,
                data={"failed_checks": decision.failed_checks},
                error_code="POLICY_REJECTED",
            )

        if action.confirmation.required and not confirmed:
            return ActionResult(
                status="requires_confirmation",
                action_id=action_id,
                message=self._confirmation_message(action, params),
                data={"action": action.public_dict(), "params": params},
            )

        adapter = self._adapters.get(action.executor.adapter)
        if adapter is None:
            return ActionResult(
                status="failed",
                action_id=action_id,
                message=f"未配置业务系统适配器：{action.executor.adapter}",
                error_code="ADAPTER_NOT_FOUND",
            )

        try:
            data = await adapter.invoke(action.executor.method, params, context)
        except Exception as exc:
            return ActionResult(
                status="failed",
                action_id=action_id,
                message=f"业务动作执行失败：{exc}",
                error_code="ADAPTER_ERROR",
            )

        return ActionResult(
            status="success",
            action_id=action_id,
            message=self._success_message(action.success_template, data),
            data=data,
        )

    def _missing_required_inputs(
        self,
        inputs: list[Any],
        params: dict[str, Any],
    ) -> list[str]:
        return [
            item.name
            for item in inputs
            if item.required and params.get(item.name) in (None, "")
        ]

    def _confirmation_message(self, action: Any, params: dict[str, Any]) -> str:
        template = action.confirmation.template
        if not template:
            return f"确认执行业务动作：{action.title}？"
        return self._render_template(template, params)

    def _success_message(self, template: str | None, data: dict[str, Any]) -> str:
        if not template:
            return "业务动作已执行成功。"
        return self._render_template(template, data)

    def _render_template(self, template: str, values: dict[str, Any]) -> str:
        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered


default_action_executor = BusinessActionExecutor(
    registry=default_action_registry,
    policy_engine=default_policy_engine,
)
