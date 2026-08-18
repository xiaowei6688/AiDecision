"""由单个插件上下文持有的类型化事件投影注册表。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.actions.schemas import ActionResult


ActionResultProjection = Callable[[ActionResult], dict[str, object]]
HumanInterruptProjection = Callable[[list[object]], dict[str, object]]
FrontendCallbackResumeProjection = Callable[[dict[str, Any], Any], dict[str, object]]


class ProjectionRegistry:
    def __init__(self) -> None:
        self._action_results: list[ActionResultProjection] = []
        self._human_interrupts: list[HumanInterruptProjection] = []
        self._frontend_callbacks: list[FrontendCallbackResumeProjection] = []

    def register_action_result(self, projection: ActionResultProjection) -> None:
        self._append_unique(self._action_results, projection)

    def register_human_interrupt(self, projection: HumanInterruptProjection) -> None:
        self._append_unique(self._human_interrupts, projection)

    def register_frontend_callback(
        self, projection: FrontendCallbackResumeProjection
    ) -> None:
        self._append_unique(self._frontend_callbacks, projection)

    def project_action_result(self, result: ActionResult) -> dict[str, object]:
        return self._merge(projection(result) for projection in self._action_results)

    def project_human_interrupt(self, interrupts: list[object]) -> dict[str, object]:
        return self._merge(
            projection(interrupts) for projection in self._human_interrupts
        )

    def project_frontend_callback(
        self, pending_payload: dict[str, Any], resume_value: Any
    ) -> dict[str, object]:
        return self._merge(
            projection(pending_payload, resume_value)
            for projection in self._frontend_callbacks
        )

    def counts(self) -> dict[str, int]:
        return {
            "action_results": len(self._action_results),
            "human_interrupts": len(self._human_interrupts),
            "frontend_callbacks": len(self._frontend_callbacks),
        }

    @staticmethod
    def _append_unique(collection: list[Any], value: Any) -> None:
        if value not in collection:
            collection.append(value)

    @staticmethod
    def _merge(projected: Any) -> dict[str, object]:
        payload: dict[str, object] = {}
        for item in projected:
            payload.update(item)
        return payload
