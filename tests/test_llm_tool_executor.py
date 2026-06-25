import pytest

from app.services.llm_client import LLMToolCall, LLMToolFunctionCall
from app.tools.llm_executor import execute_llm_tool_calls

pytestmark = pytest.mark.anyio


async def test_execute_llm_tool_calls_runs_calculator_with_tool_node() -> None:
    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_calc",
                type="function",
                function=LLMToolFunctionCall(
                    name="calculator",
                    arguments='{"expression":"2+2"}',
                ),
            )
        ]
    )

    assert len(results) == 1
    assert results[0].id == "call_calc"
    assert results[0].name == "calculator"
    assert results[0].arguments == {"expression": "2+2"}
    assert results[0].status == "success"
    assert results[0].error_category is None
    assert '"display_value": "4"' in results[0].content
    assert results[0].to_openai_tool_message()["role"] == "tool"


async def test_execute_llm_tool_calls_returns_error_for_invalid_json_arguments() -> None:
    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_bad",
                type="function",
                function=LLMToolFunctionCall(
                    name="calculator",
                    arguments="{bad json",
                ),
            )
        ]
    )

    assert len(results) == 1
    assert results[0].id == "call_bad"
    assert results[0].name == "calculator"
    assert results[0].status == "error"
    assert results[0].error_category == "invalid_arguments"
    assert "valid JSON" in results[0].content


async def test_execute_llm_tool_calls_returns_error_for_unknown_tool() -> None:
    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_unknown",
                type="function",
                function=LLMToolFunctionCall(
                    name="unknown_tool",
                    arguments="{}",
                ),
            )
        ]
    )

    assert len(results) == 1
    assert results[0].id == "call_unknown"
    assert results[0].name == "unknown_tool"
    assert results[0].status == "error"
    assert results[0].error_category == "unknown_tool"
    assert "not a valid tool" in results[0].content


async def test_execute_llm_tool_calls_classifies_tool_execution_error() -> None:
    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_div0",
                type="function",
                function=LLMToolFunctionCall(
                    name="calculator",
                    arguments='{"expression":"1/0"}',
                ),
            )
        ]
    )

    assert len(results) == 1
    assert results[0].id == "call_div0"
    assert results[0].name == "calculator"
    assert results[0].status == "error"
    assert results[0].error_category == "tool_execution_error"
    assert results[0].to_step_data()["error_category"] == "tool_execution_error"


async def test_execute_llm_tool_calls_routes_mcp_tool() -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_mcp_caller(name: str, arguments: dict) -> tuple[str, bool]:
        calls.append((name, arguments))
        return "echoed: hi", False

    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_mcp",
                type="function",
                function=LLMToolFunctionCall(
                    name="mcp_demo_echo",
                    arguments='{"text":"hi"}',
                ),
            )
        ],
        mcp_tool_names={"mcp_demo_echo"},
        mcp_caller=fake_mcp_caller,
    )

    assert len(results) == 1
    assert results[0].name == "mcp_demo_echo"
    assert results[0].status == "success"
    assert results[0].error_category is None
    assert results[0].content == "echoed: hi"
    assert calls == [("mcp_demo_echo", {"text": "hi"})]


async def test_execute_llm_tool_calls_marks_mcp_error() -> None:
    async def fake_mcp_caller(name: str, arguments: dict) -> tuple[str, bool]:
        return "tool failed", True

    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="call_mcp_err",
                type="function",
                function=LLMToolFunctionCall(name="mcp_demo_echo", arguments="{}"),
            )
        ],
        mcp_tool_names={"mcp_demo_echo"},
        mcp_caller=fake_mcp_caller,
    )

    assert results[0].status == "error"
    assert results[0].error_category == "mcp_tool_error"


async def test_execute_llm_tool_calls_keeps_local_and_mcp_order() -> None:
    async def fake_mcp_caller(name: str, arguments: dict) -> tuple[str, bool]:
        return "mcp-ok", False

    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="c1",
                type="function",
                function=LLMToolFunctionCall(name="mcp_demo_echo", arguments="{}"),
            ),
            LLMToolCall(
                id="c2",
                type="function",
                function=LLMToolFunctionCall(
                    name="calculator", arguments='{"expression":"6*7"}'
                ),
            ),
        ],
        mcp_tool_names={"mcp_demo_echo"},
        mcp_caller=fake_mcp_caller,
    )

    assert [result.id for result in results] == ["c1", "c2"]
    assert results[0].content == "mcp-ok"
    assert '"display_value": "42"' in results[1].content


async def test_execute_llm_tool_calls_unknown_mcp_without_caller() -> None:
    results = await execute_llm_tool_calls(
        [
            LLMToolCall(
                id="c",
                type="function",
                function=LLMToolFunctionCall(name="mcp_demo_echo", arguments="{}"),
            )
        ],
    )

    assert results[0].status == "error"
    assert results[0].error_category == "unknown_tool"
