"""Framework contracts for model-free forwarding of completed tool results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DirectActionResult:
    action_id: str
    params: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return {
            "kind": "action",
            "action_id": self.action_id,
            "params": self.params,
        }
