import json
from threading import Lock
from typing import TYPE_CHECKING

from app.domain.plans import ExecutionPlan

if TYPE_CHECKING:
    from app.core.durable_state import PostgresDurableState


class PlanStore:
    """会话级计划存储；多实例运行前应替换为持久化存储。"""

    def __init__(self, durable_state: "PostgresDurableState | None" = None) -> None:
        self._plans: dict[str, ExecutionPlan] = {}
        self._lock = Lock()
        self._durable_state = durable_state

    def set_durable_state(self, durable_state: "PostgresDurableState | None") -> None:
        self._durable_state = durable_state

    async def put(self, plan: ExecutionPlan, session_id: str | None) -> ExecutionPlan:
        plan.session_id = session_id
        if self._durable_state is not None:
            await self._durable_state.save_plan(plan.plan_id, session_id, plan.model_dump_json())
        with self._lock:
            self._plans[plan.plan_id] = plan
        return plan

    async def get(self, plan_id: str, session_id: str | None) -> ExecutionPlan:
        if self._durable_state is not None:
            payload = await self._durable_state.load_plan(plan_id, session_id)
            plan = ExecutionPlan.model_validate(json.loads(payload))
            with self._lock:
                self._plans[plan_id] = plan
            return plan
        with self._lock:
            stored_plan = self._plans.get(plan_id)
        if stored_plan is None:
            raise KeyError(f"Unknown execution plan: {plan_id}")
        if stored_plan.session_id != session_id:
            raise PermissionError("Execution plan does not belong to the current session")
        return stored_plan


default_plan_store = PlanStore()
