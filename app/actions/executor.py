import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from pydantic import ValidationError

from app.actions.policy import PolicyEngine, default_policy_engine
from app.actions.registry import ActionRegistry, default_action_registry
from app.actions.schemas import ActionExecutionContext, ActionResult
from app.adapters.base import BusinessAdapter
from app.core.durable_state import PostgresDurableState


class BusinessActionExecutor:
    """Validates, authorizes and invokes registered business actions."""

    def __init__(
        self,
        registry: ActionRegistry,
        policy_engine: PolicyEngine,
        adapters: dict[str, BusinessAdapter] | None = None,
        confirmation_secret: str = "development-confirmation-secret",
        confirmation_ttl_seconds: int = 600,
        durable_state: PostgresDurableState | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._adapters = adapters or {}
        self._confirmation_secret = confirmation_secret.encode()
        self._confirmation_ttl_seconds = confirmation_ttl_seconds
        self._consumed_confirmation_tokens: set[str] = set()
        self._durable_state = durable_state

    def register_adapter(self, name: str, adapter: BusinessAdapter) -> None:
        self._adapters[name] = adapter

    def configure_confirmation(self, secret: str, ttl_seconds: int | None = None) -> None:
        """Configure confirmation signing from trusted application settings."""

        self._confirmation_secret = secret.encode()
        if ttl_seconds is not None:
            self._confirmation_ttl_seconds = ttl_seconds

    def set_durable_state(self, durable_state: PostgresDurableState | None) -> None:
        self._durable_state = durable_state

    async def execute(
        self,
        action_id: str,
        params: dict[str, Any],
        context: ActionExecutionContext | None = None,
        confirmation_token: str | None = None,
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

        if action.input_model is not None:
            try:
                params = action.input_model.model_validate(params).model_dump(mode="json")
            except ValidationError as exc:
                return ActionResult(
                    status="failed",
                    action_id=action_id,
                    message=f"业务参数不合法：{exc}",
                    data={"validation_errors": exc.errors()},
                    error_code="INVALID_PARAMS",
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

        if action.confirmation.required and not await self._consume_confirmation_token(
            confirmation_token, action_id, params, context
        ):
            token, expires = self._confirmation_token(action_id, params, context)
            if self._durable_state is not None:
                await self._durable_state.issue_confirmation(token, expires)
            return ActionResult(
                status="requires_confirmation",
                action_id=action_id,
                message=self._confirmation_message(action, params),
                data={"action": action.public_dict(), "params": params, "confirmation_token": token},
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

    def _confirmation_payload(
        self,
        action_id: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
        nonce: str,
    ) -> bytes:
        return json.dumps(
            {
                "action_id": action_id,
                "params": params,
                "user_id": context.user_id,
                "session_id": context.session_id,
                "nonce": nonce,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode()

    def _confirmation_token(
        self, action_id: str, params: dict[str, Any], context: ActionExecutionContext
    ) -> tuple[str, int]:
        expires = int(time.time()) + self._confirmation_ttl_seconds
        nonce = secrets.token_urlsafe(12)
        payload = f"{expires}.{nonce}.".encode() + self._confirmation_payload(
            action_id, params, context, nonce
        )
        digest = hmac.new(self._confirmation_secret, payload, hashlib.sha256).hexdigest()
        return f"{expires}.{nonce}.{digest}", expires

    def _valid_confirmation_token(
        self,
        token: str | None,
        action_id: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> bool:
        if not token:
            return False
        try:
            expires_text, nonce, digest = token.split(".", 2)
            expires = int(expires_text)
        except (TypeError, ValueError):
            return False
        if expires < int(time.time()):
            return False
        payload = f"{expires}.{nonce}.".encode() + self._confirmation_payload(
            action_id, params, context, nonce
        )
        expected = hmac.new(self._confirmation_secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, expected)

    async def _consume_confirmation_token(
        self,
        token: str | None,
        action_id: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> bool:
        if not self._valid_confirmation_token(token, action_id, params, context):
            return False
        assert token is not None
        if self._durable_state is not None:
            return await self._durable_state.consume_confirmation(token, int(time.time()))
        if token in self._consumed_confirmation_tokens:
            return False
        self._consumed_confirmation_tokens.add(token)
        return True

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
