"""Optional integration-owned projections over generic action results."""

from __future__ import annotations

from typing import Callable

from app.actions.schemas import ActionResult


ActionResultProjection = Callable[[ActionResult], dict[str, object]]

_action_result_projections: list[ActionResultProjection] = []


def register_action_result_projection(projection: ActionResultProjection) -> None:
    if projection in _action_result_projections:
        return
    _action_result_projections.append(projection)


def project_action_result(result: ActionResult) -> dict[str, object]:
    payload: dict[str, object] = {}
    for projection in _action_result_projections:
        payload.update(projection(result))
    return payload
