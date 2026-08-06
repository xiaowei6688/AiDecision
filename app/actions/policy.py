from dataclasses import dataclass, field
from typing import Any, Callable

from app.actions.schemas import ActionExecutionContext, ActionSpec


PreCheck = Callable[[ActionSpec, dict[str, Any], ActionExecutionContext], str | None]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    message: str = ""
    failed_checks: list[str] = field(default_factory=list)


class PolicyEngine:
    """Runs deterministic authorization and business pre-checks."""

    def __init__(self) -> None:
        self._pre_checks: dict[str, PreCheck] = {}

    def register_pre_check(self, name: str, check: PreCheck) -> None:
        self._pre_checks[name] = check

    def evaluate(
        self,
        action: ActionSpec,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> PolicyDecision:
        missing_roles = [
            role for role in action.required_roles if role not in context.user_roles
        ]
        if missing_roles:
            return PolicyDecision(
                allowed=False,
                message="当前用户缺少执行业务动作所需角色。",
                failed_checks=[f"missing_role:{role}" for role in missing_roles],
            )

        failed: list[str] = []
        for check_name in action.pre_checks:
            check = self._pre_checks.get(check_name)
            if check is None:
                continue
            failure = check(action, params, context)
            if failure:
                failed.append(f"{check_name}:{failure}")

        if failed:
            return PolicyDecision(
                allowed=False,
                message="业务规则校验未通过。",
                failed_checks=failed,
            )

        return PolicyDecision(allowed=True)


default_policy_engine = PolicyEngine()
