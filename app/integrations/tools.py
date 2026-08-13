"""Integration-owned tool registry."""

from __future__ import annotations

from typing import Any

_integration_tools: list[Any] = []


def register_integration_tool(tool: Any) -> None:
    if tool in _integration_tools:
        return
    _integration_tools.append(tool)


def list_integration_tools() -> list[Any]:
    return [*_integration_tools]
