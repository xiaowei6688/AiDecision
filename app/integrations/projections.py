"""Optional integration-owned projections over generic action results."""

from __future__ import annotations

from typing import Callable

from app.actions.schemas import ActionResult


ActionResultProjection = Callable[[ActionResult], dict[str, object]]
HumanInterruptProjection = Callable[[list[object]], dict[str, object]]

_action_result_projections: list[ActionResultProjection] = []
_human_interrupt_projections: list[HumanInterruptProjection] = []


def register_action_result_projection(projection: ActionResultProjection) -> None:
    if projection in _action_result_projections:
        return
    _action_result_projections.append(projection)


def project_action_result(result: ActionResult) -> dict[str, object]:
    payload: dict[str, object] = {}
    for projection in _action_result_projections:
        payload.update(projection(result))
    return payload


def register_human_interrupt_projection(projection: HumanInterruptProjection) -> None:
    if projection in _human_interrupt_projections:
        return
    _human_interrupt_projections.append(projection)


def project_human_interrupt(interrupts: list[object]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for projection in _human_interrupt_projections:
        payload.update(projection(interrupts))
    return payload
