from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.services.llm_client import LLMToolCall
from app.tools.calculator import calculate
from app.tools.create_todo import create_todo as _create_todo
from app.tools.draft_weekly_report import draft_weekly_report as _draft_weekly_report
from app.tools.summarize_file import summarize_file as _summarize_file


LLM_EXECUTABLE_TOOL_NAMES = (
    "calculator",
    "create_todo",
    "summarize_file",
    "draft_weekly_report",
)


class _ToolExecutionState(TypedDict):
    messages: list[Any]


@dataclass(frozen=True)
class ExecutedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    content: str
    status: str
    error_category: str | None = None

    def to_openai_tool_message(self) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": self.id,
            "name": self.name,
            "content": self.content,
        }

    def to_step_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "status": self.status,
            "error_category": self.error_category,
            "content": self.content,
        }


# An MCP tool caller takes (qualified_tool_name, arguments) and returns
# (result_text, is_error). It is injected by the agent workflow so this module
# stays decoupled from the concrete MCP client implementation.
MCPToolCaller = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]


async def execute_llm_tool_calls(
    tool_calls: list[LLMToolCall],
    *,
    mcp_tool_names: set[str] | None = None,
    mcp_caller: MCPToolCaller | None = None,
) -> list[ExecutedToolCall]:
    allowed_mcp_names = mcp_tool_names or set()
    results: list[ExecutedToolCall | None] = [None] * len(tool_calls)
    local_pending: list[tuple[int, dict[str, Any]]] = []

    for index, tool_call in enumerate(tool_calls):
        name = tool_call.function.name
        is_local = name in LLM_EXECUTABLE_TOOL_NAMES
        is_mcp = name in allowed_mcp_names and mcp_caller is not None
        if not is_local and not is_mcp:
            results[index] = _unknown_tool_result(tool_call, allowed_mcp_names)
            continue

        try:
            arguments = _parse_tool_arguments(tool_call.function.arguments)
        except ValueError as exc:
            results[index] = ExecutedToolCall(
                id=tool_call.id,
                name=name,
                arguments={},
                content=f"Error: {exc}",
                status="error",
                error_category="invalid_arguments",
            )
            continue

        if is_local:
            local_pending.append(
                (
                    index,
                    {
                        "name": name,
                        "args": arguments,
                        "id": tool_call.id,
                        "type": "tool_call",
                    },
                )
            )
        else:
            results[index] = await _execute_mcp_tool_call(
                tool_call, arguments, mcp_caller
            )

    if local_pending:
        executed = await _execute_valid_tool_calls(
            [tool_call for _, tool_call in local_pending]
        )
        for (index, _), executed_call in zip(local_pending, executed, strict=False):
            results[index] = executed_call

    return [result for result in results if result is not None]


def _unknown_tool_result(
    tool_call: LLMToolCall, mcp_tool_names: set[str]
) -> ExecutedToolCall:
    available = ", ".join(sorted(set(LLM_EXECUTABLE_TOOL_NAMES) | mcp_tool_names))
    return ExecutedToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments={},
        content=(
            f"Error: '{tool_call.function.name}' is not a valid tool. "
            f"Available tools: {available}."
        ),
        status="error",
        error_category="unknown_tool",
    )


async def _execute_mcp_tool_call(
    tool_call: LLMToolCall,
    arguments: dict[str, Any],
    mcp_caller: MCPToolCaller,
) -> ExecutedToolCall:
    try:
        text, is_error = await mcp_caller(tool_call.function.name, arguments)
    except Exception as exc:  # noqa: BLE001 - external MCP server boundary
        return ExecutedToolCall(
            id=tool_call.id,
            name=tool_call.function.name,
            arguments=arguments,
            content=f"Error: {exc}",
            status="error",
            error_category="mcp_tool_error",
        )
    return ExecutedToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=arguments,
        content=text or "(empty MCP tool result)",
        status="error" if is_error else "success",
        error_category="mcp_tool_error" if is_error else None,
    )


def calculator(expression: str) -> str:
    """Evaluate a safe arithmetic expression."""
    result = calculate(expression)
    return json.dumps(
        {
            "expression": result.expression,
            "value": result.value,
            "display_value": result.display_value,
        },
        ensure_ascii=False,
    )


def create_todo(text: str) -> str:
    """Create a Markdown todo checklist from todo items or a todo request."""
    result = _create_todo(text)
    return json.dumps(
        {
            "items": [item.title for item in result.items],
            "markdown": result.to_markdown(),
        },
        ensure_ascii=False,
    )


def summarize_file(file_path: str) -> str:
    """Summarize a safe local .md or .txt file."""
    result = _summarize_file(file_path)
    return json.dumps(
        {
            "file_path": result.file_path,
            "line_count": result.line_count,
            "char_count": result.char_count,
            "markdown": result.to_markdown(),
        },
        ensure_ascii=False,
    )


def draft_weekly_report(text: str) -> str:
    """Draft a Markdown weekly report from source material."""
    result = _draft_weekly_report(text)
    return json.dumps(
        {
            "completed": result.completed,
            "blockers": result.blockers,
            "next_steps": result.next_steps,
            "markdown": result.to_markdown(),
        },
        ensure_ascii=False,
    )


def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments must be valid JSON.") from exc
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be a JSON object.")
    return arguments


async def _execute_valid_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[ExecutedToolCall]:
    graph = _build_tool_node_graph()
    ai_message = AIMessage(content="", tool_calls=tool_calls)
    output = await graph.ainvoke({"messages": [ai_message]})
    tool_messages = output["messages"]
    return [
        _executed_tool_call_from_message(tool_message, tool_call)
        for tool_message, tool_call in zip(tool_messages, tool_calls, strict=False)
    ]


def _build_tool_node_graph():
    builder = StateGraph(_ToolExecutionState)
    builder.add_node(
        "tools",
        ToolNode(
            [calculator, create_todo, summarize_file, draft_weekly_report],
            handle_tool_errors=True,
        ),
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    return builder.compile()


def _executed_tool_call_from_message(
    message: ToolMessage,
    tool_call: dict[str, Any],
) -> ExecutedToolCall:
    status = getattr(message, "status", None) or "success"
    error_category = "tool_execution_error" if status == "error" else None
    return ExecutedToolCall(
        id=message.tool_call_id,
        name=message.name or str(tool_call["name"]),
        arguments=dict(tool_call["args"]),
        content=str(message.content),
        status=status,
        error_category=error_category,
    )
