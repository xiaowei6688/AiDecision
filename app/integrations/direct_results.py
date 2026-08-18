"""无需模型参与即可转发已完成工具结果的框架契约。"""

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


@dataclass(frozen=True)
class DirectMessageResult:
    """由插件生成、无需模型改写的最终消息。"""

    message: str
    data: dict[str, Any] | None = None
    status: str = "success"

    def model_dump(self) -> dict[str, Any]:
        return {
            "kind": "message",
            "message": self.message,
            "data": self.data or {},
            "status": self.status,
        }


DirectResult = DirectActionResult | DirectMessageResult
