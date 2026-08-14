"""Integration-owned tool registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_integration_tools: list[Any] = []
_tool_steps: dict[str, "ToolStepDescription"] = {}


@dataclass(frozen=True)
class ToolStepDescription:
    title: str
    summary: str


def register_integration_tool(tool: Any) -> None:
    if tool in _integration_tools:
        return
    _integration_tools.append(tool)


def list_integration_tools() -> list[Any]:
    return [*_integration_tools]


def list_context_tools(context: Any | None) -> list[Any]:
    """Return tools registered by one application-scoped plugin context."""

    return list(context.integration_tools) if context is not None else list_integration_tools()


def register_tool_step(tool_name: str, title: str, summary: str | None = None) -> None:
    if not tool_name or not title:
        return
    normalized_title = title.strip()
    normalized_summary = (summary or title).strip()
    if not normalized_title:
        return
    _tool_steps[tool_name] = ToolStepDescription(
        title=normalized_title,
        summary=normalized_summary or normalized_title,
    )


def build_tool_step(tool_name: str, title: str, summary: str | None = None) -> ToolStepDescription | None:
    if not tool_name or not title:
        return None
    normalized_title = title.strip()
    if not normalized_title:
        return None
    return ToolStepDescription(
        title=normalized_title,
        summary=(summary or title).strip() or normalized_title,
    )


def register_tool_label(tool_name: str, label: str) -> None:
    register_tool_step(tool_name, label, label)


def tool_step(tool_name: str) -> ToolStepDescription:
    return _tool_steps.get(tool_name, _infer_tool_step(tool_name))


def context_tool_step(context: Any | None, tool_name: str) -> ToolStepDescription:
    if context is not None:
        description = context.tool_steps.get(tool_name)
        if description is not None:
            return description
    return tool_step(tool_name)


def tool_label(tool_name: str) -> str:
    return tool_step(tool_name).title


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
    if readable:
        title = readable[:1].upper() + readable[1:]
    else:
        title = "核对业务事实"
    return ToolStepDescription(
        title=title[:24],
        summary=f"正在核对与 {title} 相关的事实和条件" if title else "正在核对可用事实和条件",
    )
