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


def direct_result_from_framework_payload(result: Any) -> DirectResult | None:
    """解析插件工具按通用协议声明的直出结果。"""

    if not isinstance(result, dict):
        return None
    framework = result.get("_framework")
    if not isinstance(framework, dict):
        return None
    direct_action = framework.get("direct_action")
    if not isinstance(direct_action, dict):
        return None
    action_id = direct_action.get("action_id")
    params = direct_action.get("params")
    if not isinstance(action_id, str) or not action_id or not isinstance(params, dict):
        return None
    return DirectActionResult(action_id=action_id, params=params)
