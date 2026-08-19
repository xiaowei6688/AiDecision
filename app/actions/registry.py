from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, List

from app.actions.schemas import ActionSpec


class ActionRegistry:
    """面向模型的业务动作契约内存注册表。"""

    def __init__(self, actions: Iterable[ActionSpec] | None = None) -> None:
        self._actions: dict[str, ActionSpec] = {}
        for action in actions or []:
            self.register(action)

    def register(self, action: ActionSpec) -> None:
        self._actions[action.action_id] = action

    def get(self, action_id: str) -> ActionSpec:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise KeyError(f"Unknown business action: {action_id}") from exc

    def list(self) -> List[ActionSpec]:
        return [*self._actions.values()]

    def search(self, query: str, limit: int = 8) -> List[ActionSpec]:
        scored = [
            (self._score(query, action), action)
            for action in self._actions.values()
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [action for score, action in scored[:limit] if score > 0]

    def _score(self, query: str, action: ActionSpec) -> float:
        haystack = " ".join(
            [
                action.action_id,
                action.title,
                action.description,
                action.system,
                *action.intent_examples,
            ]
        ).lower()
        needle = query.lower().strip()
        if not needle:
            return 0.0
        if needle in haystack:
            return 1.0
        return SequenceMatcher(None, needle, haystack).ratio()
