"""由单个插件上下文持有的类型化工具注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from app.integrations.direct_results import DirectResult


@dataclass(frozen=True)
class ToolStepDescription:
    title: str
    summary: str


class IntegrationToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._read_only: set[str] = set()
        self._steps: dict[str, ToolStepDescription] = {}
        self._direct_result_projectors: dict[
            str,
            Callable[[Any], DirectResult | None],
        ] = {}

    def register(self, value: Any, *, read_only: bool = False) -> None:
        name = getattr(value, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("plugin tool must expose a non-empty name")
        current = self._tools.get(name)
        if current is not None and current is not value:
            raise ValueError(f"plugin tool already registered: {name}")
        self._tools[name] = value
        if read_only:
            self._read_only.add(name)

    def register_step(
        self, tool_name: str, title: str, summary: str | None = None
    ) -> None:
        description = build_tool_step(tool_name, title, summary)
        if description is not None:
            self._steps[tool_name] = description

    def register_direct_result(
        self,
        tool_name: str,
        projector: Callable[[Any], DirectResult | None],
    ) -> None:
        if tool_name not in self._tools:
            raise ValueError(f"unknown plugin tool: {tool_name}")
        if tool_name in self._direct_result_projectors:
            raise ValueError(f"direct result projector already registered: {tool_name}")
        self._direct_result_projectors[tool_name] = projector

    def project_direct_result(
        self,
        tool_name: str,
        result: Any,
    ) -> DirectResult | None:
        projector = self._direct_result_projectors.get(tool_name)
        return projector(result) if projector is not None else None

    def values(self) -> list[Any]:
        return list(self._tools.values())

    def read_only(self, tool_names: tuple[str, ...]) -> list[Any]:
        tools: list[Any] = []
        for name in tool_names:
            value = self._tools.get(name)
            if value is None:
                raise ValueError(f"unknown plugin tool: {name}")
            if name not in self._read_only:
                raise ValueError(f"business Agent tool must be read-only: {name}")
            tools.append(value)
        return tools

    def step(self, tool_name: str) -> ToolStepDescription:
        return self._steps.get(tool_name, _infer_tool_step(tool_name))

    def __len__(self) -> int:
        return len(self._tools)


def build_tool_step(
    tool_name: str,
    title: str,
    summary: str | None = None,
) -> ToolStepDescription | None:
    if not tool_name or not title:
        return None
    normalized_title = title.strip()
    if not normalized_title:
        return None
    return ToolStepDescription(
        title=normalized_title,
        summary=(summary or title).strip() or normalized_title,
    )


def _infer_tool_step(tool_name: str) -> ToolStepDescription:
    normalized = tool_name.strip().lower()
    if not normalized or normalized == "tool":
        return ToolStepDescription(
            title="核对任务上下文",
            summary="正在整理当前问题需要依赖的已知信息",
        )

    parts = [part for part in normalized.replace("-", "_").split("_") if part]
    if "request" in parts and "human" in parts and "input" in parts:
        return ToolStepDescription(
            title="等待用户确认",
            summary="正在等待用户对当前方案或动作做出确认",
        )
    if "semantic" in parts and "query" in parts:
        return ToolStepDescription(
            title="核对语义查询结果",
            summary="正在根据当前问题核对语义查询得到的事实",
        )
    if "plan" in parts and ("create" in parts or "build" in parts):
        return ToolStepDescription(
            title="整理计划数据",
            summary="正在把已核对的信息整理成可执行的计划数据",
        )
    if "work" in parts and "order" in parts:
        return ToolStepDescription(
            title="整理工单数据",
            summary="正在把已核对的信息整理成可执行的工单数据",
        )
    if "query" in parts:
        return ToolStepDescription(
            title="核对查询结果",
            summary="正在根据当前问题核对查询得到的事实",
        )

    readable = " ".join(parts).strip()
    title = readable[:1].upper() + readable[1:] if readable else "核对业务事实"
    return ToolStepDescription(
        title=title[:24],
        summary=f"正在核对与 {title} 相关的事实和条件",
    )
