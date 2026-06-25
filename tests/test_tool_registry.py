import pytest

from app.tools.registry import get_tool_schema, list_openai_tools, list_tool_names


def test_tool_registry_exposes_stable_agent_tool_names() -> None:
    assert list_tool_names() == [
        "search_docs",
        "calculator",
        "create_todo",
        "summarize_file",
        "draft_weekly_report",
        "query_database",
    ]


def test_openai_tools_use_function_tool_shape() -> None:
    tools = list_openai_tools()

    assert len(tools) == 6
    for tool in tools:
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["name"] in list_tool_names()
        assert function["description"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert parameters["required"]
        assert parameters["additionalProperties"] is False


def test_openai_tools_can_be_filtered_in_requested_order() -> None:
    tools = list_openai_tools(["calculator", "search_docs"])

    assert [tool["function"]["name"] for tool in tools] == [
        "calculator",
        "search_docs",
    ]


def test_openai_tool_schema_is_deep_copied() -> None:
    tool = list_openai_tools(["calculator"])[0]
    tool["function"]["parameters"]["properties"]["expression"]["maxLength"] = 1

    fresh_tool = list_openai_tools(["calculator"])[0]

    assert fresh_tool["function"]["parameters"]["properties"]["expression"][
        "maxLength"
    ] == 120


def test_get_tool_schema_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        get_tool_schema("memory_profile")
