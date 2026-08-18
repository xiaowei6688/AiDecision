"""巡检工单与对话会话的插件内关联。"""

from __future__ import annotations

from threading import Lock


class InspectionSessionBindings:
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self._lock = Lock()

    def bind_work_order(self, work_order_id: str | int, session_id: str) -> None:
        with self._lock:
            self._sessions[str(work_order_id)] = session_id

    def session_for_work_order(self, work_order_id: str | int) -> str | None:
        with self._lock:
            return self._sessions.get(str(work_order_id))


inspection_session_bindings = InspectionSessionBindings()
